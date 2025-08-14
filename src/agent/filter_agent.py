"""LangChain-based filter agent - inspired by reference implementation."""

import json
import logging
from typing import Dict, Any
from langchain_openai import ChatOpenAI
from langchain.agents import create_openai_tools_agent, AgentExecutor
from langchain.prompts.chat import ChatPromptTemplate
from langchain.schema import SystemMessage
from langchain.prompts import MessagesPlaceholder

from ..models import FilterRequest, FilterAPIResponse, FilterResponse, ErrorResponse
from ..tools import FILTER_TOOLS, initialize_filter_state
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
    
    def process_request(self, request: FilterRequest) -> FilterAPIResponse:
        """Process a filter request using LangChain tools."""
        try:
            # Add user message to conversation store
            if request.conversation_id:
                conversation_store.add_message(request.conversation_id, "user", request.query)
            
            # Initialize filter state with existing filters, delphi session, and available filters
            available_filters_dict = [filter_obj.model_dump() for filter_obj in request.available_filters]
            initialize_filter_state(request.initial_filters or [], request.delphi_session, available_filters_dict)
            
            # Build context for the agent
            input_message = self._build_input_message(request)
            
            # Execute agent
            result = self.agent_executor.invoke({
                "input": input_message
            })
            
            # Process the result
            response = self._process_agent_result(result, request.conversation_id)
            
            # Add assistant response to conversation store
            if request.conversation_id and hasattr(response, 'message'):
                conversation_store.add_message(request.conversation_id, "assistant", response.message)
            
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
        available_filters_desc = "\n".join([
            f"- {f.label} (name: {f.name}, sourceType: {f.sourceType}, sourceId: {f.sourceId})"
            for f in request.available_filters
        ])
        
        current_filters_desc = "No existing filters"
        if request.initial_filters:
            current_filters_desc = json.dumps(request.initial_filters, indent=2)
        
        # Get conversation history from store
        conversation_context = ""
        if request.conversation_id:
            conversation_history = conversation_store.get_conversation_history(request.conversation_id, last_n_messages=5)
            if conversation_history:
                conversation_context = "\n\nConversation History:\n"
                for msg in conversation_history:
                    conversation_context += f"{msg.role.title()}: {msg.content}\n"
                conversation_context += "\n"
        
        return f"""User Query: {request.query}

Available Filters:
{available_filters_desc}

Current Filters State:
{current_filters_desc}{conversation_context}

Please analyze the user's request and use the appropriate tools to handle it.
Remember to:
1. If the user query is just a value without action words, check conversation history to understand the context
2. Validate filter values using get_filter_values before proceeding
3. Use the correct operation tool (add_filter, modify_filter, remove_filter)
4. Each different filter type should be a separate entry in the final result
5. Request clarification if values don't exist
"""
    
    def _process_agent_result(self, result: Dict[str, Any], conversation_id: str) -> FilterAPIResponse:
        """Process agent execution result and convert to appropriate response."""
        
        # Check if any tool was called and returned a structured response
        if result.get("intermediate_steps"):
            for action, observation in result["intermediate_steps"]:
                if isinstance(observation, dict) and "response_type" in observation:
                    return self._convert_tool_result_to_response(observation, conversation_id)
        
        # If no structured tool result, return the agent's text output as error
        agent_output = result.get("output", "I couldn't process your filter request.")
        
        return ErrorResponse(
            message=agent_output,
            error_code="NO_STRUCTURED_RESULT",
            conversation_id=conversation_id
        )
    
    def _convert_tool_result_to_response(self, tool_result: Dict[str, Any], conversation_id: str) -> FilterAPIResponse:
        """Convert tool result to appropriate Pydantic response model."""
        response_type = tool_result.get("response_type")
        message = tool_result.get("message", "")
        
        if response_type == "success":
            filters_data = tool_result.get("filters", [])
            
            # Convert to FilterGroup objects  
            from ..models import FilterGroup, FilterCondition
            filter_groups = []
            
            for filter_data in filters_data:
                conditions = [
                    FilterCondition(**condition_data)
                    for condition_data in filter_data.get("value", [])
                ]
                filter_groups.append(FilterGroup(
                    operator=filter_data.get("operator", "and"),
                    value=conditions,
                    source_type=filter_data.get("source_type", "lens")
                ))
            
            return FilterResponse(
                message=message,
                filters=filter_groups,
                conversation_id=conversation_id
            )
        
        else:
            return ErrorResponse(
                message=message or "Unknown error occurred",
                error_code=tool_result.get("error_code", "UNKNOWN_ERROR"),
                conversation_id=conversation_id
            )
