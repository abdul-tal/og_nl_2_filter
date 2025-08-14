"""LangChain tools for filter operations - inspired by reference implementation."""

import json
import httpx
import threading
from typing import List, Dict, Any, Optional
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from ..models import (
    FilterGroup, FilterCondition, FilterOperator, FilterType, LogicalOperator
)

# Thread-local storage for filter state management (from reference implementation)
thread_local = threading.local()


class FilterOperationInput(BaseModel):
    """Input schema for filter operations."""
    filter_name: str = Field(..., description="Name/identifier of the filter")
    filter_label: str = Field(..., description="Human-readable label of the filter")  
    filter_value: str = Field(..., description="Value for the filter")
    filter_type: str = Field(..., description="Filter type (lens/dimensions)")
    source_id: str = Field(..., description="Source ID for API calls")
    message: str = Field(..., description="Success message to show user")
    operator: str = Field(default="equal", description="Filter operator")


class ORFilterOperationInput(BaseModel):
    """Input schema for OR filter operations with multiple values."""
    filter_name: str = Field(..., description="Name/identifier of the filter")
    filter_label: str = Field(..., description="Human-readable label of the filter")
    filter_values: List[str] = Field(..., description="List of filter values for OR operation")
    filter_type: str = Field(..., description="Filter type (lens/dimensions)")
    source_id: str = Field(..., description="Source ID for API calls")
    message: str = Field(..., description="Success message to show user")
    operator: str = Field(default="equal", description="Filter operator")


class MultipleFilterRemovalInput(BaseModel):
    """Input schema for removing multiple filter types."""
    filter_types: List[str] = Field(..., description="List of filter types to remove (e.g., ['account type', 'fund type'])")
    message: str = Field(..., description="Success message to show user")


class ClarificationInput(BaseModel):
    """Input schema for clarification requests."""
    filter_name: str = Field(..., description="Filter name needing clarification")
    user_input: str = Field(..., description="What the user originally requested")
    available_values: List[str] = Field(..., description="Available values to choose from")
    message: str = Field(..., description="Clarification message")


@tool("add_filter", args_schema=FilterOperationInput)
def add_filter(filter_name: str, filter_label: str, filter_value: str, filter_type: str, source_id: str, message: str, operator: str = "equal") -> Dict[str, Any]:
    """Add a new filter condition. Same filter types are grouped together, different filter types get separate entries."""
    
    # Get available filters to map label back to name if needed
    available_filters = getattr(thread_local, 'available_filters', [])
    
    # Fix parameter swap issue - if filter_name looks like a label, find the actual name
    actual_filter_name = filter_name
    if ' ' in filter_name or (filter_name and filter_name[0].isupper()):  # Likely a label, not a name
        for af in available_filters:
            if af.get('label', '') == filter_name:
                actual_filter_name = af.get('name', filter_name)
                break
    
    # Get existing filters from thread-local storage
    existing_filters = getattr(thread_local, 'current_filters', [])
    
    # Check if there's already a filter group for this filter type
    updated_filters = []
    filter_added = False
    
    for filter_group in existing_filters:
        # Check if this group already contains the same filter type
        has_same_filter_type = any(
            condition.column_name.lower().replace(' ', '_') == filter_name.lower() or
            condition.column_name.lower() == filter_label.lower()
            for condition in filter_group.value
        )
        
        if has_same_filter_type and filter_group.source_type.value == filter_type:
            # Add the new condition to the existing filter group
            new_conditions = list(filter_group.value) + [FilterCondition(
                column_name=actual_filter_name,
                value=filter_value,
                operator=FilterOperator(operator)
            )]
            
            updated_filters.append(FilterGroup(
                operator=filter_group.operator,
                value=new_conditions,
                source_type=filter_group.source_type
            ))
            filter_added = True
        else:
            # Keep existing filter groups unchanged
            updated_filters.append(filter_group)
    
    # If no existing group was found for this filter type, create a new one
    if not filter_added:
        new_filter = FilterGroup(
            operator=LogicalOperator.AND,
            value=[FilterCondition(
                column_name=actual_filter_name,
                value=filter_value,
                operator=FilterOperator(operator)
            )],
            source_type=FilterType(filter_type)
        )
        updated_filters.append(new_filter)
    
    # Store in thread-local
    thread_local.current_filters = updated_filters
    
    return {
        "response_type": "success",
        "message": message,
        "filters": [filter_group.model_dump() for filter_group in updated_filters]
    }


@tool("modify_filter", args_schema=FilterOperationInput)
def modify_filter(filter_name: str, filter_label: str, filter_value: str, filter_type: str, source_id: str, message: str, operator: str = "equal") -> Dict[str, Any]:
    """Modify an existing filter while preserving other filters."""
    
    # Get available filters to map label back to name if needed (same as add_filter)
    available_filters = getattr(thread_local, 'available_filters', [])
    
    # Fix parameter swap issue - if filter_name looks like a label, find the actual name
    actual_filter_name = filter_name
    if ' ' in filter_name or (filter_name and filter_name[0].isupper()):  # Likely a label, not a name
        for af in available_filters:
            if af.get('label', '') == filter_name:
                actual_filter_name = af.get('name', filter_name)
                break
    
    existing_filters = getattr(thread_local, 'current_filters', [])
    updated_filters = []
    filter_found = False
    
    for filter_group in existing_filters:
        # Check if this filter group contains the target filter
        contains_target = any(
            condition.column_name.lower().replace(' ', '_') == filter_name.lower() or
            condition.column_name.lower() == filter_label.lower()
            for condition in filter_group.value
        )
        
        if contains_target:
            # Modify only the target condition, keep others in the same group
            new_conditions = []
            for condition in filter_group.value:
                if (condition.column_name.lower().replace(' ', '_') == filter_name.lower() or
                    condition.column_name.lower() == filter_label.lower()):
                    # Update this condition
                    new_conditions.append(FilterCondition(
                        column_name=actual_filter_name,
                        value=filter_value,
                        operator=FilterOperator(operator)
                    ))
                    filter_found = True
                else:
                    # Keep other conditions unchanged
                    new_conditions.append(condition)
            
            updated_filters.append(FilterGroup(
                operator=filter_group.operator,
                value=new_conditions,
                source_type=filter_group.source_type
            ))
        else:
            # Keep filter groups that don't contain the target filter
            updated_filters.append(filter_group)
    
    if not filter_found:
        # If filter not found, add as new filter
        new_filter = FilterGroup(
            operator=LogicalOperator.AND,
            value=[FilterCondition(
                column_name=actual_filter_name,
                value=filter_value,
                operator=FilterOperator(operator)
            )],
            source_type=FilterType(filter_type)
        )
        updated_filters.append(new_filter)
    
    thread_local.current_filters = updated_filters
    return {
        "response_type": "success",
        "message": message,
        "filters": [filter_group.model_dump() for filter_group in updated_filters]
    }


@tool("add_or_filter", args_schema=ORFilterOperationInput)
def add_or_filter(filter_name: str, filter_label: str, filter_values: List[str], filter_type: str, source_id: str, message: str, operator: str = "equal") -> Dict[str, Any]:
    """Add or modify a filter with OR logic for multiple values."""
    
    # Get available filters to map label back to name if needed (same as add_filter)
    available_filters = getattr(thread_local, 'available_filters', [])
    
    # Fix parameter swap issue - if filter_name looks like a label, find the actual name
    actual_filter_name = filter_name
    if ' ' in filter_name or (filter_name and filter_name[0].isupper()):  # Likely a label, not a name
        for af in available_filters:
            if af.get('label', '') == filter_name:
                actual_filter_name = af.get('name', filter_name)
                break
    
    existing_filters = getattr(thread_local, 'current_filters', [])
    updated_filters = []
    filter_found = False
    
    for filter_group in existing_filters:
        # Check if this filter group contains the same filter type
        contains_same_filter = any(
            condition.column_name.lower().replace(' ', '_') == filter_name.lower() or
            condition.column_name.lower() == filter_label.lower()
            for condition in filter_group.value
        )
        
        if contains_same_filter and filter_group.source_type.value == filter_type:
            # Replace this filter group with OR logic and all values
            new_conditions = [
                FilterCondition(
                    column_name=actual_filter_name,
                    value=value,
                    operator=FilterOperator(operator)
                )
                for value in filter_values
            ]
            
            updated_filters.append(FilterGroup(
                operator=LogicalOperator.OR,  # Use OR for multiple values
                value=new_conditions,
                source_type=FilterType(filter_type)
            ))
            filter_found = True
        else:
            # Keep other filter groups unchanged
            updated_filters.append(filter_group)
    
    # If no existing group was found, create a new OR group
    if not filter_found:
        new_conditions = [
            FilterCondition(
                column_name=actual_filter_name,
                value=value,
                operator=FilterOperator(operator)
            )
            for value in filter_values
        ]
        
        new_filter = FilterGroup(
            operator=LogicalOperator.OR,
            value=new_conditions,
            source_type=FilterType(filter_type)
        )
        updated_filters.append(new_filter)
    
    thread_local.current_filters = updated_filters
    
    return {
        "response_type": "success",
        "message": message,
        "filters": [filter_group.model_dump() for filter_group in updated_filters]
    }


@tool("remove_filter", args_schema=FilterOperationInput)
def remove_filter(filter_name: str, filter_label: str, filter_value: str, filter_type: str, source_id: str, message: str, operator: str = "equal") -> Dict[str, Any]:
    """Remove a specific filter while preserving others."""
    
    # Check if this is actually a "remove all" scenario based on the message
    if any(keyword in message.lower() for keyword in ["all filters", "remove all", "clear all", "delete all", "everything"]):
        return remove_all_filters("Successfully removed all filters.")
    
    existing_filters = getattr(thread_local, 'current_filters', [])
    updated_filters = []
    
    for filter_group in existing_filters:
        # Filter out conditions that match the target filter
        remaining_conditions = [
            condition for condition in filter_group.value
            if not (condition.column_name.lower().replace(' ', '_') == filter_name.lower() or
                   condition.column_name.lower() == filter_label.lower())
        ]
        
        # Only keep filter groups that still have conditions
        if remaining_conditions:
            updated_filters.append(FilterGroup(
                operator=filter_group.operator,
                value=remaining_conditions,
                source_type=filter_group.source_type
            ))
    
    thread_local.current_filters = updated_filters
    
    return {
        "response_type": "success",
        "message": message,
        "filters": [filter_group.model_dump() for filter_group in updated_filters]
    }


@tool("remove_multiple_filters", args_schema=MultipleFilterRemovalInput)
def remove_multiple_filters(filter_types: List[str], message: str) -> Dict[str, Any]:
    """Remove multiple specific filter types (e.g., 'account type and fund type')."""
    
    existing_filters = getattr(thread_local, 'current_filters', [])
    updated_filters = []
    
    # Convert filter types to lowercase for matching
    filter_types_lower = [ft.lower().replace(' ', '_') for ft in filter_types]
    
    for filter_group in existing_filters:
        # Check if any condition in this group matches any of the filter types to remove
        should_remove_group = False
        
        for condition in filter_group.value:
            condition_name_variants = [
                condition.column_name.lower().replace(' ', '_'),
                condition.column_name.lower()
            ]
            
            # Check if this condition matches any of the filter types to remove
            for filter_type in filter_types_lower:
                if any(filter_type in variant or variant in filter_type for variant in condition_name_variants):
                    should_remove_group = True
                    break
            
            if should_remove_group:
                break
        
        # Only keep filter groups that don't match any of the types to remove
        if not should_remove_group:
            updated_filters.append(filter_group)
    
    thread_local.current_filters = updated_filters
    
    return {
        "response_type": "success",
        "message": message,
        "filters": [filter_group.model_dump() for filter_group in updated_filters]
    }


@tool("remove_all_filters")
def remove_all_filters(message: str = "Successfully removed all filters.") -> Dict[str, Any]:
    """Remove all filters and reset to empty state."""
    
    # Clear all filters
    thread_local.current_filters = []
    
    return {
        "response_type": "success",
        "message": message,
        "filters": []
    }


@tool("handle_casual_conversation")
def handle_casual_conversation(message: str) -> Dict[str, Any]:
    """Handle casual conversation that doesn't involve filter operations."""
    
    # Get initial filters from thread-local storage to preserve them
    initial_filters = getattr(thread_local, 'initial_filters', [])
    
    return {
        "response_type": "success",
        "message": message,
        "filters": [filter_group.model_dump() if hasattr(filter_group, 'model_dump') else filter_group 
                   for filter_group in initial_filters]
    }


@tool("request_clarification", args_schema=ClarificationInput)
def request_clarification(filter_name: str, user_input: str, available_values: List[str], message: str) -> Dict[str, Any]:
    """Request clarification when filter value is ambiguous."""
    
    # Get initial filters from thread-local storage to preserve them
    initial_filters = getattr(thread_local, 'initial_filters', [])
    
    # Format available values as a nice list in the message
    if available_values:
        options_text = "\n".join([f"• {value}" for value in available_values[:10]])
        formatted_message = f"{message}\n\nAvailable options:\n{options_text}\n\nWhich {filter_name.replace('_', ' ')} would you like to filter by?"
    else:
        formatted_message = f"{message}\n\nNo available options found for {filter_name.replace('_', ' ')}."
    
    return {
        "response_type": "success",
        "message": formatted_message,
        "filters": [filter_group.model_dump() if hasattr(filter_group, 'model_dump') else filter_group 
                   for filter_group in initial_filters]
    }



@tool("get_filter_values")
def get_filter_values(filter_name: str, source_id: str) -> List[str]:
    """Fetch available values for a filter from the API using the sourceId."""
    try:
        # Get delphi session from thread-local storage
        delphi_session = getattr(thread_local, 'delphi_session', '')
        
        url = f"http://controlpanel.ogov.me/api/reporting_service/next/dataset/{source_id}/column/{filter_name}/distinct"
        
        headers = {
            "Cookie": f"_delphi_session={delphi_session}",
            "Content-Type": "application/json"
        }
        
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                values = data.get("data", [])
                result = [str(value) for value in values if value is not None][:50]  # Limit to 50 values
                print('result:get_filter_values', result)
                # If no values returned but API succeeded, return demo values for testing
                if not result:
                    return []
                
                return result
            else:
                # Fallback demo values if API fails
                return []
    except Exception:
        # Fallback demo values on exception
        return []


def initialize_filter_state(initial_filters: List[Dict[str, Any]], delphi_session: str, available_filters: List[Dict[str, Any]] = None) -> None:
    """Initialize thread-local filter state from initial_filters and store delphi session."""
    filter_groups = []
    
    for filter_data in initial_filters:
        conditions = [
            FilterCondition(**condition_data)
            for condition_data in filter_data.get("value", [])
        ]
        filter_groups.append(FilterGroup(
            operator=LogicalOperator(filter_data.get("operator", "and")),
            value=conditions,
            source_type=FilterType(filter_data.get("source_type", "lens"))
        ))
    
    thread_local.current_filters = filter_groups
    thread_local.initial_filters = filter_groups.copy()  # Store initial state for preservation
    thread_local.delphi_session = delphi_session
    thread_local.available_filters = available_filters or []


def get_current_filters() -> List[FilterGroup]:
    """Get current filter state."""
    return getattr(thread_local, 'current_filters', [])


# Export all tools for the agent
FILTER_TOOLS = [add_filter, modify_filter, remove_filter, remove_multiple_filters, remove_all_filters, handle_casual_conversation, request_clarification, get_filter_values, add_or_filter]



