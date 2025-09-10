"""FastAPI application for the filter agent."""

import logging
import time
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ..models import FilterRequest, FilterAPIResponse
from ..agent import FilterAgent
from ..agent.simplified_agent import SimplifiedFilterAgent
from ..config import get_settings
from ..utils import conversation_store
from ..tools.filter_tools import sanitize_response_object, get_cache_stats, add_filter, modify_filter, remove_filter, remove_all_filters, request_clarification

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Get settings
settings = get_settings()

# Create FastAPI app
app = FastAPI(
    title="Natural Language Filter Agent",
    description="Convert natural language queries to structured database filters",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize filter agents
try:
    filter_agent = FilterAgent(
        openai_api_key=settings.openai_api_key,
        model=settings.openai_model,
        temperature=settings.openai_temperature
    )
    print("Filter agent initialized successfully")
    simplified_agent = SimplifiedFilterAgent(
        openai_api_key=settings.openai_api_key,
        model=settings.openai_model,
        temperature=settings.openai_temperature
    )
    print("Simplified agent initialized successfully")
    logger.info("Filter agents initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize filter agents: {e}")
    # Create mock agents for demo mode
    filter_agent = None
    simplified_agent = None


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "Natural Language Filter Agent"}


@app.get("/api/conversations/stats")
async def get_conversation_stats():
    """Get conversation store statistics."""
    return conversation_store.get_stats()


@app.delete("/api/conversations/{conversation_id}")
async def clear_conversation(conversation_id: str):
    """Clear conversation history for a specific conversation_id."""
    conversation_store.clear_conversation(conversation_id)
    return {"message": f"Conversation {conversation_id} cleared"}


@app.post("/api/conversations/cleanup")
async def cleanup_old_conversations():
    """Clean up old conversations."""
    cleaned_count = conversation_store.cleanup_old_conversations()
    return {"message": f"Cleaned up {cleaned_count} old conversations"}


@app.get("/api/cache/stats")
async def get_filter_cache_stats():
    """Get filter cache statistics and performance metrics."""
    return get_cache_stats()


@app.post("/api/filters/natural-language")
async def process_filter_request(request: FilterRequest):
    """
    Process a natural language filter request using simplified flow.
    
    This endpoint:
    1. Sends available_filters and columnGroups to the agent in system prompt
    2. Agent calls get_filter_values to fetch values for right filters mentioned by user. The filters will be one of available_filters. If filters don't exist in available_filters, agent will return clarification needed response.
    3. Agent returns execution plan with function names and parameters
    4. Backend manually executes the functions and returns appropriate response
    """
    # Start total timing
    total_start_time = time.time()
    print(f"\n🚀 [TIMING] Starting natural language filter request processing...")
    print(f"📝 [TIMING] Query: '{request.query}'")
    
    try:
        if simplified_agent is None:
            # Demo mode - return mock response
            demo_start = time.time()
            response = _create_demo_response(request)
            demo_time = time.time() - demo_start
            total_time = time.time() - total_start_time
            print(f"🎭 [TIMING] Demo mode processing: {demo_time:.3f}s")
            print(f"⏱️  [TIMING] Total request time: {total_time:.3f}s")
            return response
        
        # Process the request using the simplified agent (planning phase)
        agent_start_time = time.time()
        print(f"🧠 [TIMING] Starting agent planning phase...")
        agent_result = simplified_agent.process_request(request)
        agent_time = time.time() - agent_start_time
        print(f"🤖 [TIMING] Agent planning completed: {agent_time:.3f}s")
        print(f"📊 [TIMING] Agent result status: {agent_result.get('status', 'unknown')}")
        print(f"DEBUG [API]: Agent result: {agent_result}")
        
        # Execute the plan manually (execution phase)
        execution_start = time.time()
        print(f"⚙️  [TIMING] Starting plan execution phase...")
        response = await _execute_agent_plan(agent_result, request)
        execution_time = time.time() - execution_start
        print(f"✅ [TIMING] Plan execution completed: {execution_time:.3f}s")
        print(f"📈 [TIMING] Agent vs Execution ratio: {agent_time:.3f}s / {execution_time:.3f}s = {(agent_time/execution_time if execution_time > 0 else 0):.2f}x")
        
        total_time = time.time() - total_start_time
        print(f"⏱️  [TIMING] Total request time: {total_time:.3f}s")
        print(f"📊 [TIMING] Performance breakdown:")
        print(f"   - Agent Planning: {agent_time:.3f}s ({(agent_time/total_time*100):.1f}%)")
        print(f"   - Plan Execution: {execution_time:.3f}s ({(execution_time/total_time*100):.1f}%)")
        print(f"   - Other Overhead: {(total_time-agent_time-execution_time):.3f}s ({((total_time-agent_time-execution_time)/total_time*100):.1f}%)")
        logger.info(f"Processed simplified request for conversation {request.conversation_id} in {total_time:.3f}s")
        return response
        
    except Exception as e:
        total_time = time.time() - total_start_time
        print(f"❌ [TIMING] Error occurred after {total_time:.3f}s")
        logger.error(f"Error processing request: {str(e)}")
        from ..models import ErrorResponse
        return {
            "status": "error",
            "message": "An error occurred while processing your request.",
            "error_code": "API_ERROR",
            "conversation_id": request.conversation_id
        }


async def _execute_agent_plan(agent_result: dict, request: FilterRequest) -> dict:
    """Execute the agent's plan manually and return appropriate response."""
    
    # Check the status of the agent result
    status = agent_result.get("status")
    
    if status == "clarification_needed":
        # Return clarification request directly
        return {
            "status": "clarification_needed",
            "message": agent_result.get("message", "Clarification needed"),
            "available_values": agent_result.get("available_values", []),
            "filter_name": agent_result.get("filter_name", ""),
            "filter_label": agent_result.get("filter_label", ""),
            "conversation_id": request.conversation_id
        }
    
    elif status == "error":
        # Return error directly
        return {
            "status": "error",
            "message": agent_result.get("message", "An error occurred"),
            "error_code": agent_result.get("error_code", "UNKNOWN_ERROR"),
            "conversation_id": request.conversation_id
        }
    
    elif status == "success":
        plan_start = time.time()
        execution_plan = agent_result.get("execution_plan", [])
        print(f"\n🚀 [TIMING] Starting plan execution with {len(execution_plan)} operations...")
        print(f"📋 [TIMING] Execution plan: {[item.get('function_name') for item in execution_plan]}")
        
        if not execution_plan:
            return {
                "status": "error",
                "message": "No execution plan provided",
                "error_code": "NO_EXECUTION_PLAN",
                "conversation_id": request.conversation_id
            }
        
        try:
            # Initialize filter state for manual execution
            from ..tools.filter_tools import initialize_filter_state, get_final_account_summary
            available_filters_dict = [filter_obj.model_dump() for filter_obj in request.available_filters]
            initialize_filter_state(request.account_summary, request.delphi_session, available_filters_dict)
            
            # Execute each function in the plan
            for i, plan_item in enumerate(execution_plan, 1):
                function_name = plan_item.get("function_name")
                parameters = plan_item.get("parameters", [])
                func_start = time.time()
                print(f"\n🔧 [TIMING] Executing step {i}/{len(execution_plan)}: {function_name}")
                
                if function_name == "add_filter":
                    await _execute_add_filter(parameters, request.available_filters)
                elif function_name == "modify_filter":
                    await _execute_modify_filter(parameters, request.available_filters)
                elif function_name == "remove_filter":
                    await _execute_remove_filter(parameters, request.available_filters)
                elif function_name == "remove_all_filters":
                    await _execute_remove_all_filters(parameters)
                elif function_name == "request_clarification":
                    func_time = time.time() - func_start
                    print(f"⏰ [TIMING] Function {function_name} completed: {func_time:.3f}s")
                    return await _execute_request_clarification(parameters, request.conversation_id)
                else:
                    logger.warning(f"Unknown function in execution plan: {function_name}")
                
                func_time = time.time() - func_start
                print(f"⏰ [TIMING] Function {function_name} completed: {func_time:.3f}s")
            
            # Get the final account summary after all operations
            summary_start = time.time()
            final_account_summary = get_final_account_summary()
            summary_time = time.time() - summary_start
            total_plan_time = time.time() - plan_start
            
            print(f"📄 [TIMING] Account summary generation: {summary_time:.3f}s")
            print(f"✅ [TIMING] Total plan execution time: {total_plan_time:.3f}s")
            
            # Generate specific operation message based on execution plan
            operation_message = _generate_operation_message(execution_plan, agent_result)
            
            return {
                "status": "success",
                "message": operation_message,
                "account_summary": final_account_summary,
                "conversation_id": request.conversation_id
            }
            
        except Exception as e:
            logger.error(f"Error executing plan: {str(e)}")
            return {
                "status": "error",
                "message": f"Error executing filter operations: {str(e)}",
                "error_code": "EXECUTION_ERROR",
                "conversation_id": request.conversation_id
            }
    
    else:
        return {
            "status": "error",
            "message": "Unknown agent result status",
            "error_code": "UNKNOWN_STATUS",
            "conversation_id": request.conversation_id
        }


async def _execute_add_filter(parameters: list, available_filters: list) -> None:
    """Execute add_filter function with given parameters."""
    if len(parameters) < 6:
        raise ValueError("add_filter requires at least 6 parameters: filter_name, filter_label, filter_value, filter_type, source_id, message")
    
    filter_name = parameters[0]
    filter_label = parameters[1]
    filter_value = parameters[2]
    filter_type = parameters[3]
    source_id = parameters[4]
    message = parameters[5]
    operator = parameters[6] if len(parameters) > 6 else "equal"
    
    print(f"🔍 [TIMING] Adding filter: {filter_name}={filter_value} ({filter_type})")
    tool_start = time.time()
    
    # Call the add_filter tool directly with all parameters
    result = add_filter(
        filter_name=filter_name,
        filter_label=filter_label,
        filter_value=filter_value,
        filter_type=filter_type,
        source_id=source_id,
        message=message,
        operator=operator
    )
    
    tool_time = time.time() - tool_start
    print(f"⚡ [TIMING] add_filter tool execution: {tool_time:.3f}s")
    
    if result.get("response_type") != "success":
        raise ValueError(f"Failed to add filter: {result.get('message', 'Unknown error')}")


async def _execute_modify_filter(parameters: list, available_filters: list) -> None:
    """Execute modify_filter function with given parameters."""
    if len(parameters) < 6:
        raise ValueError("modify_filter requires at least 6 parameters: filter_name, filter_label, filter_value, filter_type, source_id, message")
    
    filter_name = parameters[0]
    filter_label = parameters[1]
    filter_value = parameters[2]
    filter_type = parameters[3]
    source_id = parameters[4]
    message = parameters[5]
    operator = parameters[6] if len(parameters) > 6 else "equal"
    
    print(f"🔄 [TIMING] Modifying filter: {filter_name}={filter_value} ({filter_type})")
    tool_start = time.time()
    
    # Call the modify_filter tool directly with all parameters
    result = modify_filter(
        filter_name=filter_name,
        filter_label=filter_label,
        filter_value=filter_value,
        filter_type=filter_type,
        source_id=source_id,
        message=message,
        operator=operator
    )
    
    tool_time = time.time() - tool_start
    print(f"⚡ [TIMING] modify_filter tool execution: {tool_time:.3f}s")
    
    if result.get("response_type") != "success":
        raise ValueError(f"Failed to modify filter: {result.get('message', 'Unknown error')}")


async def _execute_remove_filter(parameters: list, available_filters: list) -> None:
    """Execute remove_filter function with given parameters."""
    if len(parameters) < 6:
        raise ValueError("remove_filter requires at least 6 parameters: filter_name, filter_label, filter_value, filter_type, source_id, message")
    
    filter_name = parameters[0]
    filter_label = parameters[1]
    filter_value = parameters[2]
    filter_type = parameters[3]
    source_id = parameters[4]
    message = parameters[5]
    operator = parameters[6] if len(parameters) > 6 else "equal"
    
    print(f"🗑️  [TIMING] Removing filter: {filter_name}={filter_value} ({filter_type})")
    tool_start = time.time()
    
    # Call the remove_filter tool directly with all parameters
    result = remove_filter(
        filter_name=filter_name,
        filter_label=filter_label,
        filter_value=filter_value,
        filter_type=filter_type,
        source_id=source_id,
        message=message,
        operator=operator
    )
    
    tool_time = time.time() - tool_start
    print(f"⚡ [TIMING] remove_filter tool execution: {tool_time:.3f}s")
    
    if result.get("response_type") != "success":
        raise ValueError(f"Failed to remove filter: {result.get('message', 'Unknown error')}")


async def _execute_remove_all_filters(parameters: list) -> None:
    """Execute remove_all_filters function with given parameters."""
    if len(parameters) < 1:
        raise ValueError("remove_all_filters requires at least 1 parameter: message")
    
    message = parameters[0]
    
    print(f"🧹 [TIMING] Removing all filters")
    tool_start = time.time()
    
    # Call the remove_all_filters tool directly with message parameter
    result = remove_all_filters(message)
    
    tool_time = time.time() - tool_start
    print(f"⚡ [TIMING] remove_all_filters tool execution: {tool_time:.3f}s")
    
    if result.get("response_type") != "success":
        raise ValueError(f"Failed to remove all filters: {result.get('message', 'Unknown error')}")


def _generate_operation_message(execution_plan: list, agent_result: dict) -> str:
    """Generate a specific message based on the operations performed in the execution plan."""
    if not execution_plan:
        return "No operations performed"
    
    messages = []
    
    for plan_item in execution_plan:
        function_name = plan_item.get("function_name")
        parameters = plan_item.get("parameters", [])
        
        if function_name == "add_filter":
            if len(parameters) >= 3:
                filter_label = parameters[1]  # filter_label is the second parameter
                filter_value = parameters[2]  # filter_value is the third parameter
                messages.append(f"{filter_label} filter '{filter_value}' added")
            else:
                messages.append("Filter added")
                
        elif function_name == "modify_filter":
            if len(parameters) >= 3:
                filter_label = parameters[1]
                filter_value = parameters[2]
                messages.append(f"{filter_label} filter modified to '{filter_value}'")
            else:
                messages.append("Filter modified")
                
        elif function_name == "remove_filter":
            if len(parameters) >= 3:
                filter_label = parameters[1]
                filter_value = parameters[2]
                messages.append(f"{filter_label} filter '{filter_value}' removed")
            else:
                messages.append("Filter removed")
                
        elif function_name == "remove_all_filters":
            messages.append("All filters removed")
            
        elif function_name == "request_clarification":
            if len(parameters) >= 1:
                filter_name = parameters[0]
                messages.append(agent_result.get("message", ""))
            else:
                messages.append("Clarification requested")
    
    if len(messages) == 1:
        return messages[0]
    elif len(messages) > 1:
        return "; ".join(messages)
    else:
        return "Filter operations completed successfully"


async def _execute_request_clarification(parameters: list, conversation_id: str) -> dict:
    """Execute request_clarification function with given parameters."""
    if len(parameters) < 4:
        raise ValueError("request_clarification requires 4 parameters: filter_name, user_input, available_values, message")
    
    filter_name = parameters[0]
    user_input = parameters[1]
    available_values = parameters[2]
    message = parameters[3]
    
    print(f"❓ [TIMING] Requesting clarification for filter: {filter_name}")
    tool_start = time.time()
    
    # Call the request_clarification tool directly
    result = request_clarification(
        filter_name=filter_name,
        user_input=user_input,
        available_values=available_values,
        message=message
    )
    
    tool_time = time.time() - tool_start
    print(f"⚡ [TIMING] request_clarification tool execution: {tool_time:.3f}s")
    
    # Convert tool response to API response format
    return {
        "status": "clarification_needed",
        "message": result.get("message", message),
        "available_values": available_values,
        "filter_name": filter_name,
        "filter_label": filter_name,  # Use filter_name as label for now
        "conversation_id": conversation_id
    }


def _create_demo_response(request: FilterRequest) -> dict:
    """Create a demo response when OpenAI is not available."""
    from ..models import FilterResponse, AccountSummary, ColumnGroup
    
    # Create a simple demo filter based on the query
    query_lower = request.query.lower()
    
    # Create demo filter data
    if "account" in query_lower and "payable" in query_lower:
        demo_filter_data = {
            "operator": "and",
            "value": [{
                "column_name": "Account Type",
                "value": "Accounts Payable", 
                "operator": "equal"
            }]
        }
    elif "fiscal" in query_lower and "10" in query_lower:
        demo_filter_data = {
            "operator": "and",
            "value": [{
                "column_name": "Fiscal Period",
                "value": "10",
                "operator": "equal"
            }]
        }
    else:
        demo_filter_data = {
            "operator": "and",
            "value": [{
                "column_name": "Demo Filter",
                "value": "Demo Value",
                "operator": "equal"
            }]
        }
    
    # Use existing account_summary if provided, otherwise create a minimal demo structure
    if request.account_summary:
        updated_account_summary = request.account_summary.dict()
        # Add the new filter to the first column group's filters
        if updated_account_summary["columnGroups"]:
            updated_account_summary["columnGroups"][0]["filters"].append(demo_filter_data)
        account_summary = AccountSummary(**updated_account_summary)
    else:
        # Create a minimal demo account_summary structure
        demo_column_group = ColumnGroup(
            id="demo_column_group",
            lens={"id": "demo_lens"},
            measureColumn={"id": "demo_measure"},
            grouping=[],
            filters=[demo_filter_data],
            dateFilter=[],
            relativeFilter="",
            type="demo",
            columnValueMapping={},
            rollingNumRangeOption={}
        )
        
        account_summary = AccountSummary(
            columnGroups=[demo_column_group],
            columnOrder={},
            expandedGroupKeys={},
            expandedRows={},
            filters=[],
            formatting={},
            hiddenColumns={},
            rowGroups=[],
            charts=[],
            rounding={}
        )
    
    response = FilterResponse(
        message=f"Demo: Created filter based on '{request.query}'",
        account_summary=account_summary,
        conversation_id=request.conversation_id
    )
    
    # Sanitize the demo response as well
    response_dict = response if isinstance(response, dict) else response.dict()
    sanitized_dict = sanitize_response_object(response_dict)
    return sanitized_dict


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.api_host, port=settings.api_port)
