"""LangChain-based filter agent - inspired by reference implementation."""

import json
import logging
import time
from typing import Dict, Any
from langchain_openai import ChatOpenAI
from langchain.agents import create_openai_tools_agent, AgentExecutor
from langchain.prompts.chat import ChatPromptTemplate
from langchain.schema import SystemMessage
from langchain.prompts import MessagesPlaceholder

from ..models import FilterRequest, FilterAPIResponse, FilterResponse, ErrorResponse, AccountSummary, ColumnGroupClarificationResponse
from ..tools import FILTER_TOOLS, initialize_filter_state, thread_local, get_final_account_summary, set_user_query
from ..utils import conversation_store
from .prompts import FILTER_AGENT_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


class FilterAgent:
    """Main filter agent using LangChain tools architecture."""
    
    def __init__(self, openai_api_key: str, model: str = "gpt-4o-mini", temperature: float = 0.1):
        """Initialize the filter agent."""
        self.openai_api_key = openai_api_key
        self.model_name = model
        self.temperature = temperature
        
        # Initialize OpenAI model
        self.model = ChatOpenAI(
            model=model,
            temperature=temperature,
            openai_api_key=openai_api_key
        )
        
        # Create system message
        system_message = SystemMessage(content=FILTER_AGENT_SYSTEM_PROMPT)
        
        # Create prompt template
        self.prompt = ChatPromptTemplate.from_messages([
            system_message,
            MessagesPlaceholder(variable_name="chat_history", optional=True),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad")
        ])
        
        # Create agent with tools
        self.agent = create_openai_tools_agent(self.model, FILTER_TOOLS, self.prompt)
        self.agent_executor = AgentExecutor(
            agent=self.agent,
            tools=FILTER_TOOLS,
            verbose=True,
            return_intermediate_steps=True,
            handle_parsing_errors=True
        )
        
        logger.info(f"FilterAgent initialized with model {model}")
    
    def _execute_agent_with_timing(self, input_message: str) -> Dict[str, Any]:
        """Execute agent with detailed timing breakdown."""
        from langchain.callbacks.base import BaseCallbackHandler
        
        class TimingCallbackHandler(BaseCallbackHandler):
            def __init__(self):
                self.llm_start_time = None
                self.tool_start_time = None
                self.current_tool = None
                
            def on_llm_start(self, serialized, prompts, **kwargs):
                self.llm_start_time = time.time()
                print(f"        🧠 [TIMING] LLM request starting...")
                
            def on_llm_end(self, response, **kwargs):
                if self.llm_start_time:
                    llm_time = time.time() - self.llm_start_time
                    print(f"        🧠 [TIMING] LLM request completed: {llm_time:.3f}s")
                    self.llm_start_time = None
                    
            def on_tool_start(self, serialized, input_str, **kwargs):
                self.tool_start_time = time.time()
                self.current_tool = serialized.get('name', 'unknown_tool')
                print(f"        🔨 [TIMING] Tool '{self.current_tool}' starting...")
                
            def on_tool_end(self, output, **kwargs):
                if self.tool_start_time and self.current_tool:
                    tool_time = time.time() - self.tool_start_time
                    print(f"        🔨 [TIMING] Tool '{self.current_tool}' completed: {tool_time:.3f}s")
                    self.tool_start_time = None
                    self.current_tool = None
                    
            def on_agent_action(self, action, **kwargs):
                print(f"        🤔 [TIMING] Agent deciding to use tool: {action.tool}")
                
            def on_agent_finish(self, finish, **kwargs):
                print(f"        ✅ [TIMING] Agent finished reasoning")
        
        # Execute with timing callback
        timing_callback = TimingCallbackHandler()
        result = self.agent_executor.invoke(
            {"input": input_message},
            config={"callbacks": [timing_callback]}
        )
        
        return result
    
    def process_request(self, request: FilterRequest) -> FilterAPIResponse:
        """Process a filter request using LangChain tools."""
        try:
            print(f"  🔧 [TIMING] Starting filter agent processing...")
            
            # Add user message to conversation store
            conv_start = time.time()
            if request.conversation_id:
                conversation_store.add_message(request.conversation_id, "user", request.query)
            conv_time = time.time() - conv_start
            print(f"    💬 [TIMING] Conversation store update: {conv_time:.3f}s")
            
            # Initialize filter state with existing account_summary, delphi session, and available filters
            init_start = time.time()
            available_filters_dict = [filter_obj.model_dump() for filter_obj in request.available_filters]
            initialize_filter_state(request.account_summary, request.delphi_session, available_filters_dict)
            
            # Store user query for column group identification
            set_user_query(request.query)
            init_time = time.time() - init_start
            print(f"    🔧 [TIMING] Filter state initialization: {init_time:.3f}s")
            
            # Build context for the agent
            context_start = time.time()
            input_message = self._build_input_message(request)
            context_time = time.time() - context_start
            print(f"    📋 [TIMING] Input message building: {context_time:.3f}s")
            
            # Execute agent with detailed timing
            agent_exec_start = time.time()
            print(f"      🎯 [TIMING] Starting LangChain agent execution...")
            
            # Create a custom agent executor with timing callbacks
            result = self._execute_agent_with_timing(input_message)
            
            agent_exec_time = time.time() - agent_exec_start
            print(f"    🎯 [TIMING] Total agent execution: {agent_exec_time:.3f}s")
            
            # Process the result
            result_start = time.time()
            response = self._process_agent_result(result, request.conversation_id)
            result_time = time.time() - result_start
            print(f"    📤 [TIMING] Result processing: {result_time:.3f}s")
            
            # Add assistant response to conversation store
            final_conv_start = time.time()
            if request.conversation_id and hasattr(response, 'message'):
                conversation_store.add_message(request.conversation_id, "assistant", response.message)
            final_conv_time = time.time() - final_conv_start
            print(f"    💾 [TIMING] Final conversation store: {final_conv_time:.3f}s")
            
            return response
            
        except Exception as e:
            logger.error(f"Error processing request: {str(e)}")
            return ErrorResponse(
                message="An error occurred while processing your request.",
                error_code="PROCESSING_ERROR",
                conversation_id=request.conversation_id
            )
    
    def _build_input_message(self, request: FilterRequest) -> str:
        """Build input message for the agent with full context."""
        start_time = time.time()
        print(f"          ⚡ [TIMING] Function '_build_input_message' starting...")
        
        try:
            available_filters_desc = "\n".join([
                f"- {f.label} (name: {f.name}, sourceType: {f.sourceType}, sourceId: {f.sourceId})"
                for f in request.available_filters
            ])
            
            current_filters_desc = "No existing account summary"
            if request.account_summary:
                # Provide a more focused description of the columnGroups structure
                column_groups_desc = []
                for i, cg in enumerate(request.account_summary.columnGroups):
                    filters_count = len(cg.filters)
                    column_groups_desc.append(f"  - ColumnGroup {i} (id: {cg.id}): {filters_count} filters")
                
                if column_groups_desc:
                    current_filters_desc = f"Account Summary with {len(request.account_summary.columnGroups)} columnGroups:\n" + "\n".join(column_groups_desc)
                    current_filters_desc += f"\n\nFull structure:\n{json.dumps(request.account_summary.dict(), indent=2)}"
                else:
                    current_filters_desc = json.dumps(request.account_summary.dict(), indent=2)
            
            # Get conversation history from store
            conversation_context = ""
            if request.conversation_id:
                conversation_history = conversation_store.get_conversation_history(request.conversation_id, last_n_messages=5)
                if conversation_history:
                    conversation_context = "\n\nConversation History:\n"
                    for msg in conversation_history:
                        conversation_context += f"{msg.role.title()}: {msg.content}\n"
                    conversation_context += "\n"
            
            result = f"""User Query: {request.query}

Available Filters:
{available_filters_desc}

Current Account Summary State:
{current_filters_desc}{conversation_context}

Please analyze the user's request and use the appropriate tools to handle it.
Remember to:
1. If the user query is just a value without action words, check conversation history to understand the context
2. Validate filter values using get_filter_values before proceeding
3. Use the correct operation tool (add_filter, modify_filter, remove_filter)
4. Each different filter type should be a separate entry in the final result
5. Request clarification if values don't exist
6. Filters are organized within columnGroups - modify the appropriate columnGroup based on context
"""
            execution_time = time.time() - start_time
            print(f"          ⚡ [TIMING] Function '_build_input_message' completed: {execution_time:.3f}s")
            return result
        except Exception as e:
            execution_time = time.time() - start_time
            print(f"          ❌ [TIMING] Function '_build_input_message' failed after: {execution_time:.3f}s")
            raise
    
    def _process_agent_result(self, result: Dict[str, Any], conversation_id: str) -> FilterAPIResponse:
        """Process agent execution result and convert to appropriate response."""
        start_time = time.time()
        print(f"          ⚡ [TIMING] Function '_process_agent_result' starting...")
        
        try:
            # Check if any tool was called and returned a structured response
            if result.get("intermediate_steps"):
                for action, observation in result["intermediate_steps"]:
                    if isinstance(observation, dict) and "response_type" in observation:
                        response = self._convert_tool_result_to_response(observation, conversation_id)
                        execution_time = time.time() - start_time
                        print(f"          ⚡ [TIMING] Function '_process_agent_result' completed: {execution_time:.3f}s")
                        return response
            
            # If no structured tool result, return the agent's text output as error
            agent_output = result.get("output", "I couldn't process your filter request.")
            
            response = ErrorResponse(
                message=agent_output,
                error_code="NO_STRUCTURED_RESULT",
                conversation_id=conversation_id
            )
            execution_time = time.time() - start_time
            print(f"          ⚡ [TIMING] Function '_process_agent_result' completed: {execution_time:.3f}s")
            return response
        except Exception as e:
            execution_time = time.time() - start_time
            print(f"          ❌ [TIMING] Function '_process_agent_result' failed after: {execution_time:.3f}s")
            raise
    
    def _convert_tool_result_to_response(self, tool_result: Dict[str, Any], conversation_id: str) -> FilterAPIResponse:
        """Convert tool result to appropriate Pydantic response model."""
        response_type = tool_result.get("response_type")
        message = tool_result.get("message", "")
        
        if response_type == "clarification_needed":
            # Handle column group clarification
            available_groups = tool_result.get("available_groups", [])
            return ColumnGroupClarificationResponse(
                message=message,
                available_groups=available_groups,
                conversation_id=conversation_id
            )
        
        elif response_type == "success":
            # Check if the tool returned account_summary directly (new format)
            if "account_summary" in tool_result:
                account_summary_data = tool_result["account_summary"]
                if account_summary_data:
                    account_summary = AccountSummary(**account_summary_data)
                else:
                    # Fallback: Use the updated account_summary from local storage
                    final_account_summary_dict = get_final_account_summary()
                    if final_account_summary_dict:
                        account_summary = AccountSummary(**final_account_summary_dict)
                    else:
                        # Create minimal account_summary structure
                        from ..models import ColumnGroup
                        demo_column_group = ColumnGroup(
                            id="default_column_group",
                            lens={"id": "default_lens"},
                            measureColumn={"id": "default_measure"},
                            grouping=[],
                            filters=[],
                            dateFilter=[],
                            relativeFilter="",
                            type="default",
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
                
                return FilterResponse(
                    message=message,
                    account_summary=account_summary,
                    conversation_id=conversation_id
                )
            
            # Legacy fallback: Use the updated account_summary from local storage
            final_account_summary_dict = get_final_account_summary()
            
            if final_account_summary_dict:
                # Use the stored account_summary which already has all updates applied
                account_summary = AccountSummary(**final_account_summary_dict)
            else:
                # Fallback: Create a minimal account_summary structure 
                from ..models import ColumnGroup
                demo_column_group = ColumnGroup(
                    id="default_column_group",
                    lens={"id": "default_lens"},
                    measureColumn={"id": "default_measure"},
                    grouping=[],
                    filters=[],
                    dateFilter=[],
                    relativeFilter="",
                    type="default",
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
            
            return FilterResponse(
                message=message,
                account_summary=account_summary,
                conversation_id=conversation_id
            )
        
        else:
            return ErrorResponse(
                message=message or "Unknown error occurred",
                error_code=tool_result.get("error_code", "UNKNOWN_ERROR"),
                conversation_id=conversation_id
            )
