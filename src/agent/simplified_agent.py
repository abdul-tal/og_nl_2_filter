"""Simplified Natural Language Filter Agent with planning-only approach."""

import json
import logging
import time
from typing import Dict, Any, List
from langchain_openai import ChatOpenAI
from langchain.agents import create_openai_tools_agent, AgentExecutor
from langchain.prompts.chat import ChatPromptTemplate
from langchain.schema import SystemMessage
from langchain.prompts import MessagesPlaceholder

from ..models import FilterRequest, FilterAPIResponse, FilterResponse, ErrorResponse, AccountSummary
from ..tools.simplified_tools import SIMPLIFIED_TOOLS, initialize_simplified_state, get_filter_values_tool
from ..utils import conversation_store

logger = logging.getLogger(__name__)


class SimplifiedFilterAgent:
    """Simplified filter agent that returns execution plans instead of executing operations."""
    
    def __init__(self, openai_api_key: str, model: str = "gpt-4o-mini", temperature: float = 0.1):
        """Initialize the simplified filter agent."""
        self.openai_api_key = openai_api_key
        self.model_name = model
        self.temperature = temperature
        
        # Initialize OpenAI model
        self.model = ChatOpenAI(
            model=model,
            temperature=temperature,
            openai_api_key=openai_api_key
        )
        
        logger.info(f"SimplifiedFilterAgent initialized with model {model}")
    
    def process_request(self, request: FilterRequest) -> Dict[str, Any]:
        """Process a filter request and return execution plan."""
        start_time = time.time()
        
        def log_step(step_name: str, step_start: float = None):
            current_time = time.time()
            relative_time = current_time - start_time
            if step_start:
                step_duration = current_time - step_start
                print(f"⏱️  [AGENT-STEP] {step_name} completed at +{relative_time:.3f}s (took {step_duration:.3f}s)")
            else:
                print(f"🚀 [AGENT-STEP] {step_name} starting at +{relative_time:.3f}s")
            return current_time
        
        try:
            log_step("SimplifiedFilterAgent.process_request")
            
            # Add user message to conversation store
            step_start = log_step("Adding user message to conversation store")
            if request.conversation_id:
                conversation_store.add_message(request.conversation_id, "user", request.query)
            log_step("User message added", step_start)
            
            # Initialize simplified state with available filters, column groups, and delphi session
            step_start = log_step("Initializing simplified state")
            initialize_simplified_state(request.available_filters, request.account_summary, request.delphi_session)
            log_step("Simplified state initialized", step_start)
            
            # Build system prompt with available filters and column groups
            step_start = log_step("Building system prompt")
            system_prompt = self._build_system_prompt(request.available_filters, request.account_summary)
            log_step("System prompt built", step_start)
            
            # Create prompt template
            step_start = log_step("Creating prompt template")
            prompt = ChatPromptTemplate.from_messages([
                SystemMessage(content=system_prompt),
                MessagesPlaceholder(variable_name="chat_history", optional=True),
                ("human", "{input}"),
                MessagesPlaceholder(variable_name="agent_scratchpad")
            ])
            log_step("Prompt template created", step_start)
            
            # Create agent with simplified tools
            step_start = log_step("Creating OpenAI tools agent")
            agent = create_openai_tools_agent(self.model, SIMPLIFIED_TOOLS, prompt)
            log_step("OpenAI tools agent created", step_start)
            
            step_start = log_step("Creating AgentExecutor")
            agent_executor = AgentExecutor(
                agent=agent,
                tools=SIMPLIFIED_TOOLS,
                verbose=True,
                return_intermediate_steps=True,
                handle_parsing_errors=True
            )
            log_step("AgentExecutor created", step_start)
            
            # Build input message
            step_start = log_step("Building input message")
            input_message = self._build_input_message(request)
            log_step("Input message built", step_start)
            
            # Execute agent
            step_start = log_step("Executing agent (this includes LLM calls and tool execution)")
            result = agent_executor.invoke({"input": input_message})
            log_step("Agent execution completed", step_start)
            
            # Debug: Print the raw result structure
            step_start = log_step("Processing agent result")
            print(f"DEBUG [AGENT]: Raw result keys: {list(result.keys())}")
            print(f"DEBUG [AGENT]: Raw output: {result.get('output', 'NO OUTPUT')}")
            
            # Process the result and return execution plan
            response = self._process_agent_result(result, request)
            log_step("Agent result processed", step_start)
            
            # Add assistant response to conversation store
            step_start = log_step("Adding assistant response to conversation store")
            if request.conversation_id and "message" in response:
                conversation_store.add_message(request.conversation_id, "assistant", response["message"])
            log_step("Assistant response added", step_start)
            
            total_time = time.time() - start_time
            print(f"✅ [AGENT-TOTAL] SimplifiedFilterAgent.process_request completed in {total_time:.3f}s")
            
            return response
            
        except Exception as e:
            import traceback
            error_time = time.time() - start_time
            print(f"❌ [AGENT-ERROR] Exception occurred at +{error_time:.3f}s: {str(e)}")
            logger.error(f"Error processing request: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {
                "status": "error",
                "message": "An error occurred while processing your request.",
                "error_code": "PROCESSING_ERROR",
                "conversation_id": request.conversation_id
            }
    
    def _build_system_prompt(self, available_filters: List, account_summary: AccountSummary = None) -> str:
        """Build system prompt with available filters and column groups embedded."""
        
        # Format available filters - handle both dict and Pydantic model objects
        filters_text = "\n".join([
            f"- {f.label if hasattr(f, 'label') else f['label']} (name: {f.name if hasattr(f, 'name') else f['name']}, sourceType: {f.sourceType if hasattr(f, 'sourceType') else f['sourceType']}, sourceId: {f.sourceId if hasattr(f, 'sourceId') else f['sourceId']})"
            for f in available_filters
        ])
        
        # Format column groups
        column_groups_text = "No column groups available"
        if account_summary and account_summary.columnGroups:
            column_groups_list = []
            for i, cg in enumerate(account_summary.columnGroups):
                group_name = "Unknown Group"
                # Try to extract group name from grouping
                if cg.grouping:
                    for grouping_item in cg.grouping:
                        if isinstance(grouping_item, dict) and "constant" in grouping_item:
                            group_name = grouping_item["constant"]
                            break
                column_groups_list.append(f"- {group_name} (id: {cg.id})")
            column_groups_text = "\n".join(column_groups_list)
        
        system_prompt = """You are a Natural Language Filter Agent that analyzes user requests and returns execution plans.

Your role is to:
1. Understand user filter requests
2. Call get_filter_values to fetch available values for filters mentioned by the user. Always make sure to call get_filter_values with the filter name(not label) and source id.
3. Return function names and parameters for the backend to execute

AVAILABLE FILTERS:
""" + filters_text + """

COLUMN GROUPS:
""" + column_groups_text + """

IMPORTANT RULES:
1. ALWAYS call get_filter_values immediately when a user mentions a filter
2. After getting filter values, determine the appropriate function to call
3. Return execution plans with complete parameters for each function
4. If filter value doesn't match available values, return clarification request
5. If match found, return the function name and parameters for backend execution

AVAILABLE FUNCTIONS TO RETURN:
- add_filter: Add a new filter condition
  Parameters: [filter_name, filter_label, filter_value, filter_type, source_id, message, operator (optional)]
  Example: ["account_type", "Account Type", "Assets", "lens", "source_123", "Added Account Type filter", "equal"]

- modify_filter: Modify existing filter
  Parameters: [filter_name, filter_label, filter_value, filter_type, source_id, message, operator (optional)]
  Example: ["department", "Department", "Finance", "lens", "source_456", "Modified Department filter", "equal"]

- remove_filter: Remove specific filter
  Parameters: [filter_name, filter_label, filter_value, filter_type, source_id, message, operator (optional)]
  Example: ["fund_type", "Fund Type", "General", "lens", "source_789", "Removed Fund Type filter", "equal"]

- remove_all_filters: Remove all filters
  Parameters: [message]
  Example: ["Removed all filters"]

- request_clarification: Ask user to choose from available options
  Parameters: [filter_name, user_input, available_values, message]
  Example: ["department", "sales", ["Sales", "Marketing", "Finance"], "Please choose from available departments"]

RESPONSE FORMATS:

Success (match found):
{
    "status": "success",
    "execution_plan": [
        {"function_name": "add_filter", "parameters": ["departments", "Department", "001", "lens", "source_id_123", "Added Department filter"]},
        {"function_name": "remove_filter", "parameters": ["another_filter", "Another Filter", "002", "lens", "source_id_456", "Removed Another Filter"]}
    ],
    "message": "Execution plan created successfully"
}

Clarification needed:
{
    "status": "clarification_needed", 
    "message": "The value 'xyz' is not available for Department. Please choose from: A, B, C",
    "available_values": ["A", "B", "C"],
    "filter_name": "departments",
    "filter_label": "Department"
}

Error:
{
    "status": "error",
    "message": "Error description",
    "error_code": "ERROR_CODE"
}

Remember: Your job is to create execution plans, not execute operations. The backend will handle the actual function calls."""
        
        return system_prompt

    def _build_input_message(self, request: FilterRequest) -> str:
        """Build input message for the agent."""
        
        # Get conversation history
        conversation_context = ""
        if request.conversation_id:
            conversation_history = conversation_store.get_conversation_history(request.conversation_id, last_n_messages=3)
            if conversation_history:
                conversation_context = "\n\nConversation History:\n"
                for msg in conversation_history:
                    conversation_context += f"{msg.role.title()}: {msg.content}\n"
        
        return f"""User Query: {request.query}

Please analyze the user's request and:
1. Call get_filter_values for any filter mentioned in the query
2. Based on the results, return the appropriate execution plan
3. If values don't match, request clarification
4. If values match, return function calls for backend execution

{conversation_context}"""

    def _process_agent_result(self, result: Dict[str, Any], request: FilterRequest) -> Dict[str, Any]:
        """Process agent execution result and return execution plan."""
        
        # Debug: Print the entire result to understand its structure
        print(f"DEBUG: Agent result keys: {list(result.keys())}")
        print(f"DEBUG: Agent output: {result.get('output', 'NO OUTPUT')}")
        print(f"DEBUG: Intermediate steps count: {len(result.get('intermediate_steps', []))}")
        
        # Check if the agent's final output is a JSON string containing the response (prioritize this)
        agent_output = result.get("output", "")
        if agent_output and isinstance(agent_output, str):
            try:
                # Try to parse the output as JSON
                import json
                # Look for JSON in the output string
                if "{" in agent_output and "}" in agent_output:
                    # Extract JSON from the output
                    start_idx = agent_output.find("{")
                    end_idx = agent_output.rfind("}") + 1
                    json_str = agent_output[start_idx:end_idx]
                    print(f"DEBUG: Extracted JSON string: {json_str}")
                    parsed_output = json.loads(json_str)
                    if isinstance(parsed_output, dict) and "status" in parsed_output:
                        print(f"DEBUG: Successfully parsed JSON: {parsed_output}")
                        return parsed_output
            except (json.JSONDecodeError, ValueError) as e:
                # If it's not valid JSON, continue with other checks
                print(f"DEBUG: JSON parsing failed: {e}")
                pass
        
        # Fallback: check if agent returned structured response from tools
        if result.get("intermediate_steps"):
            for action, observation in result["intermediate_steps"]:
                print(f"DEBUG: Processing intermediate step - action: {action}, observation type: {type(observation)}")
                if isinstance(observation, dict):
                    print(f"DEBUG: Observation dict: {observation}")
                    # If tool returned a structured response with execution_plan, use it
                    if "status" in observation and "execution_plan" in observation:
                        print(f"DEBUG: Found status and execution_plan in observation, returning: {observation}")
                        return observation
                    
                    # If it's get_filter_values result, process it
                    if "available_values" in observation:
                        print(f"DEBUG: Found available_values, creating execution plan")
                        return self._create_execution_plan_from_values(
                            observation, request.query, request.available_filters
                        )
        
        # Check if the agent's final output is a JSON string containing the response
        agent_output = result.get("output", "")
        if agent_output and isinstance(agent_output, str):
            try:
                # Try to parse the output as JSON
                import json
                # Look for JSON in the output string
                if "{" in agent_output and "}" in agent_output:
                    # Extract JSON from the output
                    start_idx = agent_output.find("{")
                    end_idx = agent_output.rfind("}") + 1
                    json_str = agent_output[start_idx:end_idx]
                    print(f"DEBUG: Extracted JSON string: {json_str}")
                    parsed_output = json.loads(json_str)
                    if isinstance(parsed_output, dict) and "status" in parsed_output:
                        print(f"DEBUG: Successfully parsed JSON: {parsed_output}")
                        return parsed_output
            except (json.JSONDecodeError, ValueError) as e:
                # If it's not valid JSON, continue with other checks
                print(f"DEBUG: JSON parsing failed: {e}")
                pass
        
        # Fallback: return agent's text output as error
        return {
            "status": "error",
            "message": agent_output if agent_output else "I couldn't process your filter request.",
            "error_code": "NO_STRUCTURED_RESULT",
            "conversation_id": request.conversation_id
        }
    
    def _create_execution_plan_from_values(self, values_result: Dict, user_query: str, available_filters: List) -> Dict[str, Any]:
        """Create execution plan based on get_filter_values result."""
        
        filter_name = values_result.get("filter_name", "")
        available_values = values_result.get("available_values", [])
        
        # Find filter metadata - handle both dict and Pydantic model objects
        filter_metadata = None
        for f in available_filters:
            f_name = f.name if hasattr(f, 'name') else f['name']
            if f_name == filter_name:
                filter_metadata = f
                break
        
        if not filter_metadata:
            return {
                "status": "error",
                "message": f"Filter '{filter_name}' not found in available filters",
                "error_code": "FILTER_NOT_FOUND"
            }
        
        # Simple value extraction from query (this is basic - could be enhanced)
        query_lower = user_query.lower()
        
        # Look for values in the query that match available values
        matched_values = []
        for value in available_values:
            if str(value).lower() in query_lower:
                matched_values.append(str(value))
        
        if not matched_values:
            f_label = filter_metadata.label if hasattr(filter_metadata, 'label') else filter_metadata['label']
            return {
                "status": "clarification_needed",
                "message": f"Please specify a value for {f_label}. Available values are: {', '.join(map(str, available_values[:10]))}{'...' if len(available_values) > 10 else ''}",
                "available_values": available_values,
                "filter_name": filter_name,
                "filter_label": f_label
            }
        
        # Determine operation type based on query keywords
        operation = "add_filter"  # default
        if any(word in query_lower for word in ["change", "modify", "update", "set to"]):
            operation = "modify_filter"
        elif any(word in query_lower for word in ["remove", "delete", "clear"]):
            operation = "remove_filter"
        
        # Create execution plan with complete parameters
        execution_plan = []
        f_label = filter_metadata.label if hasattr(filter_metadata, 'label') else filter_metadata['label']
        f_type = filter_metadata.sourceType if hasattr(filter_metadata, 'sourceType') else filter_metadata['sourceType']
        f_source_id = filter_metadata.sourceId if hasattr(filter_metadata, 'sourceId') else filter_metadata['sourceId']
        
        for value in matched_values:
            # Create message based on operation type
            if operation == "add_filter":
                message = f"Added {f_label} filter with value {value}"
            elif operation == "modify_filter":
                message = f"Modified {f_label} filter to {value}"
            elif operation == "remove_filter":
                message = f"Removed {f_label} filter with value {value}"
            else:
                message = f"Applied {operation} to {f_label} filter"
            
            execution_plan.append({
                "function_name": operation,
                "parameters": [filter_name, f_label, value, f_type, f_source_id, message]
            })
        
        f_label = filter_metadata.label if hasattr(filter_metadata, 'label') else filter_metadata['label']
        return {
            "status": "success",
            "execution_plan": execution_plan,
            "message": f"Created execution plan for {f_label} filter"
        }
