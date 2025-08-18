"""LangChain tools for filter operations - inspired by reference implementation."""

import json
import httpx
import threading
import logging
from typing import List, Dict, Any, Optional
from langchain_core.tools import tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

from ..models import (
    FilterGroup, FilterCondition, FilterOperator, FilterType, LogicalOperator, DimensionInfo, AccountSummary,
    ColumnGroupClarificationNeeded
)

# Thread-local storage for filter state management (from reference implementation)
thread_local = threading.local()


# Local storage functions for account_summary management
def store_account_summary(account_summary: dict) -> None:
    """Store account_summary in thread-local storage."""
    thread_local.account_summary_dict = account_summary
    # Initialize current_column_group_id to first columnGroup if available
    column_groups = account_summary.get("columnGroups", [])
    if column_groups:
        thread_local.current_column_group_id = column_groups[0].get("id")
    else:
        thread_local.current_column_group_id = None


def get_stored_account_summary() -> dict:
    """Retrieve account_summary from thread-local storage."""
    return getattr(thread_local, 'account_summary_dict', {})


def set_current_column_group_id(column_group_id: str) -> None:
    """Set the current columnGroup ID being modified."""
    thread_local.current_column_group_id = column_group_id


def get_current_column_group_id() -> Optional[str]:
    """Get the current columnGroup ID being modified."""
    return getattr(thread_local, 'current_column_group_id', None)


def set_user_query(user_query: str) -> None:
    """Store the user query for column group identification."""
    thread_local.user_query = user_query


def get_user_query() -> str:
    """Get the stored user query."""
    return getattr(thread_local, 'user_query', '')


def normalize_filter_condition(condition_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize filter condition data to match our FilterCondition model.
    
    Handles real-world data inconsistencies:
    - dimension object structures
    - missing required fields
    """
    normalized = dict(condition_data)
    
    # Ensure columnName exists (using original field name)
    if "columnName" not in normalized:
        normalized["columnName"] = normalized.get("column_name", "unknown_column")
    
    # Handle dimension object normalization
    if "dimension" in normalized and normalized["dimension"]:
        dimension_data = normalized["dimension"]
        if isinstance(dimension_data, dict) and "id" in dimension_data:
            try:
                # Handle URL-encoded dimension IDs
                dimension_id = dimension_data["id"]
                if "%2F" in dimension_id:
                    import urllib.parse
                    dimension_id = urllib.parse.unquote(dimension_id)
                normalized["dimension"] = DimensionInfo(id=dimension_id)
            except Exception as e:
                logger.warning(f"Failed to create DimensionInfo for {dimension_data}: {e}")
                normalized.pop("dimension", None)
    
    # Ensure value is string
    if "value" in normalized:
        normalized["value"] = str(normalized["value"])
    
    # Handle operator validation
    if "operator" in normalized:
        try:
            # Validate operator exists in our enum
            FilterOperator(normalized["operator"])
        except ValueError:
            logger.warning(f"Unknown operator {normalized['operator']}, defaulting to 'equal'")
            normalized["operator"] = "equal"
    
    return normalized


def normalize_filter_group(filter_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize filter group data to match our FilterGroup model.
    
    Handles missing source_type and other inconsistencies.
    """
    normalized = dict(filter_data)
    
    # Remove source_type from normalized data as it should not appear in API responses
    normalized.pop("source_type", None)
    
    # Validate operator
    if "operator" not in normalized:
        normalized["operator"] = "and"
    
    return normalized


def sanitize_response_object(response_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sanitize response object by removing unwanted properties and null values.
    
    This function recursively traverses the response object and removes:
    1. Properties that should not be exposed in the API response
    2. Properties with null/None values
    
    Args:
        response_data: The response dictionary to sanitize
        
    Returns:
        Sanitized response dictionary with unwanted properties and null values removed
    """
    # List of properties to remove from responses
    UNWANTED_PROPERTIES = {'source_type'}
    
    def _sanitize_recursive(obj):
        """Recursively sanitize nested objects."""
        if isinstance(obj, dict):
            # Create a new dict without unwanted properties and null values
            sanitized = {}
            for key, value in obj.items():
                if key not in UNWANTED_PROPERTIES:
                    sanitized_value = _sanitize_recursive(value)
                    # Only include the key if the value is not None/null
                    if sanitized_value is not None:
                        sanitized[key] = sanitized_value
            return sanitized
        elif isinstance(obj, list):
            # Recursively sanitize list items and filter out None values
            sanitized_list = []
            for item in obj:
                sanitized_item = _sanitize_recursive(item)
                if sanitized_item is not None:
                    sanitized_list.append(sanitized_item)
            return sanitized_list
        else:
            # Return primitive values as-is (including None for filtering at parent level)
            return obj
    
    return _sanitize_recursive(response_data)


def handle_column_group_identification(account_summary: dict) -> Dict[str, Any]:
    """
    Handle column group identification with proper error handling and clarification.
    
    Returns:
        Dict with either success info or clarification/error response
    """
    current_column_group_id = get_current_column_group_id()
    if current_column_group_id:
        return {"status": "success", "column_group_id": current_column_group_id}
    
    try:
        user_query = get_user_query()
        current_column_group_id = identify_target_column_group(user_query, account_summary)
        set_current_column_group_id(current_column_group_id)
        return {"status": "success", "column_group_id": current_column_group_id}
        
    except ColumnGroupClarificationNeeded as e:
        return {
            "status": "clarification_needed",
            "response_type": "clarification_needed",
            "message": "I found multiple data groups. Which one would you like to add the filter to?\n\n" + 
                      "\n".join([f"• {group['name']}" for group in e.available_groups]) + 
                      "\n\nPlease specify which column group you'd like to modify.",
            "available_groups": e.available_groups
        }
        
    except ValueError:
        return {
            "status": "error",
            "response_type": "error", 
            "message": "No column groups found in account summary"
        }


def update_column_group_filters(column_group_id: str, updated_filters: List[dict]) -> None:
    """Update filters for specific columnGroup in stored account_summary."""
    account_summary = get_stored_account_summary()
    column_groups = account_summary.get("columnGroups", [])
    
    for i, group in enumerate(column_groups):
        if group.get("id") == column_group_id:
            # Update the filters for this columnGroup
            account_summary["columnGroups"][i]["filters"] = updated_filters
            thread_local.account_summary_dict = account_summary
            break


def get_final_account_summary() -> dict:
    """Get final account_summary with all modifications applied."""
    return get_stored_account_summary()


def _update_stored_account_summary_with_filters(updated_filters: List[FilterGroup]) -> None:
    """Update the stored account_summary with new filter state."""
    current_column_group_id = get_current_column_group_id()
    if current_column_group_id:
        # Convert FilterGroup objects to dicts for storage and sanitize
        filter_dicts = [sanitize_response_object(filter_group.dict()) for filter_group in updated_filters]
        update_column_group_filters(current_column_group_id, filter_dicts)


def create_filter_condition(filter_name: str, filter_value: str, operator: str, filter_type: str, available_filters: List[Dict[str, Any]]) -> FilterCondition:
    """Create a FilterCondition with appropriate structure based on sourceType."""
    
    # Find the filter metadata
    filter_metadata = None
    for af in available_filters:
        if af.get('name', '') == filter_name:
            filter_metadata = af
            break
    
    base_condition = {
        "columnName": filter_name,
        "value": filter_value,
        "operator": FilterOperator(operator)
    }
    
    # Add dimension-specific fields if sourceType is dimensions
    if filter_metadata and filter_metadata.get('sourceType') == 'dimensions':
        print(f"DEBUG: Creating dimension filter for {filter_name}, sourceId: {filter_metadata.get('sourceId')}, joinColumnName: {filter_metadata.get('joinColumnName')}")
        base_condition["dimension"] = DimensionInfo(id=filter_metadata.get('sourceId', ''))
        base_condition["joinColumnName"] = filter_metadata.get('joinColumnName')
    else:
        print(f"DEBUG: Creating lens filter for {filter_name}")
    
    condition = FilterCondition(**base_condition)
    print(f"DEBUG: Created condition: {condition.dict()}")
    return condition


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


class ColumnGroupIdentificationInput(BaseModel):
    """Input schema for column group identification."""
    user_query: str = Field(..., description="User's natural language query")
    account_summary: Dict[str, Any] = Field(..., description="Account summary data structure")
    clarification_message: str = Field(..., description="Message to show if clarification is needed")


class ColumnGroupSelectionInput(BaseModel):
    """Input schema for column group selection."""
    group_name: str = Field(..., description="Name of the selected column group")
    message: str = Field(..., description="Success message to show user")


@tool("add_filter", args_schema=FilterOperationInput)
def add_filter(filter_name: str, filter_label: str, filter_value: str, filter_type: str, source_id: str, message: str, operator: str = "equal") -> Dict[str, Any]:
    """Add a new filter condition. Same filter types are grouped together, different filter types get separate entries."""
    
    # Get stored account_summary from thread-local
    account_summary = get_stored_account_summary()
    if not account_summary:
        return {
            "response_type": "error",
            "message": "No account summary available",
            "account_summary": {}
        }
    
    # Get available filters to map label back to name if needed
    available_filters = getattr(thread_local, 'available_filters', [])
    
    # Fix parameter swap issue - if filter_name looks like a label, find the actual name
    actual_filter_name = filter_name
    if ' ' in filter_name or (filter_name and filter_name[0].isupper()):  # Likely a label, not a name
        for af in available_filters:
            if af.get('label', '') == filter_name:
                actual_filter_name = af.get('name', filter_name)
                break
    
    # Identify target columnGroup using improved logic
    column_group_result = handle_column_group_identification(account_summary)
    if column_group_result["status"] != "success":
        # Return clarification or error directly
        column_group_result["account_summary"] = account_summary
        return column_group_result
    
    current_column_group_id = column_group_result["column_group_id"]
    
    # Get existing filters from target columnGroup
    existing_filters = []
    column_groups = account_summary.get("columnGroups", [])
    for group in column_groups:
        if group.get("id") == current_column_group_id:
            filters_data = group.get("filters", [])
            for filter_data in filters_data:
                conditions = []
                for condition_data in filter_data.get("value", []):
                    try:
                        normalized_condition = normalize_filter_condition(condition_data)
                        conditions.append(FilterCondition(**normalized_condition))
                    except Exception as e:
                        logger.warning(f"Skipping invalid filter condition: {condition_data} - Error: {e}")
                        continue
                
                if conditions:  # Only add if we have valid conditions
                    try:
                        normalized_filter_group = normalize_filter_group(filter_data)
                        existing_filters.append(FilterGroup(
                            operator=LogicalOperator(normalized_filter_group.get("operator", "and")),
                            value=conditions,
                            source_type=FilterType(normalized_filter_group.get("source_type", "lens"))
                        ))
                    except Exception as e:
                        logger.warning(f"Skipping invalid filter group: {filter_data} - Error: {e}")
            break
    
    # Check if there's already a filter group for this filter type
    updated_filters = []
    filter_added = False
    
    for filter_group in existing_filters:
        # Check if this group already contains the same filter type
        has_same_filter_type = any(
            condition.columnName.lower().replace(' ', '_') == filter_name.lower() or
            condition.columnName.lower() == filter_label.lower()
            for condition in filter_group.value
        )
        
        if has_same_filter_type and filter_group.source_type.value == filter_type:
            # Add the new condition to the existing filter group
            new_condition = create_filter_condition(actual_filter_name, filter_value, operator, filter_type, available_filters)
            new_conditions = list(filter_group.value) + [new_condition]
            
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
        new_condition = create_filter_condition(actual_filter_name, filter_value, operator, filter_type, available_filters)
        new_filter = FilterGroup(
            operator=LogicalOperator.AND,
            value=[new_condition],
            source_type=FilterType(filter_type)
        )
        updated_filters.append(new_filter)
    
    # Store in thread-local for backward compatibility
    thread_local.current_filters = updated_filters
    
    # Update target columnGroup with new filters
    filter_dicts = [sanitize_response_object(filter_group.dict()) for filter_group in updated_filters]
    update_column_group_filters(current_column_group_id, filter_dicts)
    
    return {
        "response_type": "success",
        "message": message,
        "account_summary": get_stored_account_summary()
    }


@tool("modify_filter", args_schema=FilterOperationInput)
def modify_filter(filter_name: str, filter_label: str, filter_value: str, filter_type: str, source_id: str, message: str, operator: str = "equal") -> Dict[str, Any]:
    """Modify an existing filter while preserving other filters."""
    
    # Get stored account_summary from thread-local
    account_summary = get_stored_account_summary()
    if not account_summary:
        return {
            "response_type": "error",
            "message": "No account summary available",
            "account_summary": {}
        }
    
    # Get available filters to map label back to name if needed
    available_filters = getattr(thread_local, 'available_filters', [])
    
    # Fix parameter swap issue - if filter_name looks like a label, find the actual name
    actual_filter_name = filter_name
    if ' ' in filter_name or (filter_name and filter_name[0].isupper()):  # Likely a label, not a name
        for af in available_filters:
            if af.get('label', '') == filter_name:
                actual_filter_name = af.get('name', filter_name)
                break
    
    # Identify target columnGroup using improved logic
    column_group_result = handle_column_group_identification(account_summary)
    if column_group_result["status"] != "success":
        # Return clarification or error directly
        column_group_result["account_summary"] = account_summary
        return column_group_result
    
    current_column_group_id = column_group_result["column_group_id"]
    
    # Get existing filters from target columnGroup
    existing_filters = []
    column_groups = account_summary.get("columnGroups", [])
    for group in column_groups:
        if group.get("id") == current_column_group_id:
            filters_data = group.get("filters", [])
            for filter_data in filters_data:
                conditions = []
                for condition_data in filter_data.get("value", []):
                    try:
                        normalized_condition = normalize_filter_condition(condition_data)
                        conditions.append(FilterCondition(**normalized_condition))
                    except Exception as e:
                        logger.warning(f"Skipping invalid filter condition: {condition_data} - Error: {e}")
                        continue
                
                if conditions:  # Only add if we have valid conditions
                    try:
                        normalized_filter_group = normalize_filter_group(filter_data)
                        existing_filters.append(FilterGroup(
                            operator=LogicalOperator(normalized_filter_group.get("operator", "and")),
                            value=conditions,
                            source_type=FilterType(normalized_filter_group.get("source_type", "lens"))
                        ))
                    except Exception as e:
                        logger.warning(f"Skipping invalid filter group: {filter_data} - Error: {e}")
            break
    
    updated_filters = []
    filter_found = False
    
    for filter_group in existing_filters:
        # Check if this filter group contains the target filter
        contains_target = any(
            condition.columnName.lower().replace(' ', '_') == filter_name.lower() or
            condition.columnName.lower() == filter_label.lower()
            for condition in filter_group.value
        )
        
        if contains_target:
            # Modify only the target condition, keep others in the same group
            new_conditions = []
            for condition in filter_group.value:
                if (condition.columnName.lower().replace(' ', '_') == filter_name.lower() or
                    condition.columnName.lower() == filter_label.lower()):
                    # Update this condition
                    new_condition = create_filter_condition(actual_filter_name, filter_value, operator, filter_type, available_filters)
                    new_conditions.append(new_condition)
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
        new_condition = create_filter_condition(actual_filter_name, filter_value, operator, filter_type, available_filters)
        new_filter = FilterGroup(
            operator=LogicalOperator.AND,
            value=[new_condition],
            source_type=FilterType(filter_type)
        )
        updated_filters.append(new_filter)
    
    # Store in thread-local for backward compatibility
    thread_local.current_filters = updated_filters
    
    # Update target columnGroup with new filters
    filter_dicts = [sanitize_response_object(filter_group.dict()) for filter_group in updated_filters]
    update_column_group_filters(current_column_group_id, filter_dicts)
    
    return {
        "response_type": "success",
        "message": message,
        "account_summary": get_stored_account_summary()
    }


@tool("add_or_filter", args_schema=ORFilterOperationInput)
def add_or_filter(filter_name: str, filter_label: str, filter_values: List[str], filter_type: str, source_id: str, message: str, operator: str = "equal") -> Dict[str, Any]:
    """Add or modify a filter with OR logic for multiple values."""
    
    # Get stored account_summary from thread-local
    account_summary = get_stored_account_summary()
    if not account_summary:
        return {
            "response_type": "error",
            "message": "No account summary available",
            "account_summary": {}
        }
    
    # Get available filters to map label back to name if needed
    available_filters = getattr(thread_local, 'available_filters', [])
    
    # Fix parameter swap issue - if filter_name looks like a label, find the actual name
    actual_filter_name = filter_name
    if ' ' in filter_name or (filter_name and filter_name[0].isupper()):  # Likely a label, not a name
        for af in available_filters:
            if af.get('label', '') == filter_name:
                actual_filter_name = af.get('name', filter_name)
                break
    
    # Identify target columnGroup using improved logic
    column_group_result = handle_column_group_identification(account_summary)
    if column_group_result["status"] != "success":
        # Return clarification or error directly
        column_group_result["account_summary"] = account_summary
        return column_group_result
    
    current_column_group_id = column_group_result["column_group_id"]
    
    # Get existing filters from target columnGroup
    existing_filters = []
    column_groups = account_summary.get("columnGroups", [])
    for group in column_groups:
        if group.get("id") == current_column_group_id:
            filters_data = group.get("filters", [])
            for filter_data in filters_data:
                conditions = []
                for condition_data in filter_data.get("value", []):
                    try:
                        normalized_condition = normalize_filter_condition(condition_data)
                        conditions.append(FilterCondition(**normalized_condition))
                    except Exception as e:
                        logger.warning(f"Skipping invalid filter condition: {condition_data} - Error: {e}")
                        continue
                
                if conditions:  # Only add if we have valid conditions
                    try:
                        normalized_filter_group = normalize_filter_group(filter_data)
                        existing_filters.append(FilterGroup(
                            operator=LogicalOperator(normalized_filter_group.get("operator", "and")),
                            value=conditions,
                            source_type=FilterType(normalized_filter_group.get("source_type", "lens"))
                        ))
                    except Exception as e:
                        logger.warning(f"Skipping invalid filter group: {filter_data} - Error: {e}")
            break
    
    updated_filters = []
    filter_found = False
    
    for filter_group in existing_filters:
        # Check if this filter group contains the same filter type
        contains_same_filter = any(
            condition.columnName.lower().replace(' ', '_') == filter_name.lower() or
            condition.columnName.lower() == filter_label.lower()
            for condition in filter_group.value
        )
        
        if contains_same_filter and filter_group.source_type.value == filter_type:
            # Replace this filter group with OR logic and all values
            new_conditions = [
                create_filter_condition(actual_filter_name, value, operator, filter_type, available_filters)
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
            create_filter_condition(actual_filter_name, value, operator, filter_type, available_filters)
            for value in filter_values
        ]
        
        new_filter = FilterGroup(
            operator=LogicalOperator.OR,
            value=new_conditions,
            source_type=FilterType(filter_type)
        )
        updated_filters.append(new_filter)
    
    # Store in thread-local for backward compatibility
    thread_local.current_filters = updated_filters
    
    # Update target columnGroup with new filters
    filter_dicts = [sanitize_response_object(filter_group.dict()) for filter_group in updated_filters]
    update_column_group_filters(current_column_group_id, filter_dicts)
    
    return {
        "response_type": "success",
        "message": message,
        "account_summary": get_stored_account_summary()
    }


@tool("remove_filter", args_schema=FilterOperationInput)
def remove_filter(filter_name: str, filter_label: str, filter_value: str, filter_type: str, source_id: str, message: str, operator: str = "equal") -> Dict[str, Any]:
    """Remove a specific filter while preserving others."""
    
    # Check if this is actually a "remove all" scenario based on the message
    if any(keyword in message.lower() for keyword in ["all filters", "remove all", "clear all", "delete all", "everything"]):
        return remove_all_filters("Successfully removed all filters.")
    
    # Get stored account_summary from thread-local
    account_summary = get_stored_account_summary()
    if not account_summary:
        return {
            "response_type": "error",
            "message": "No account summary available",
            "account_summary": {}
        }
    
    # Identify target columnGroup using improved logic
    column_group_result = handle_column_group_identification(account_summary)
    if column_group_result["status"] != "success":
        # Return clarification or error directly
        column_group_result["account_summary"] = account_summary
        return column_group_result
    
    current_column_group_id = column_group_result["column_group_id"]
    
    # Get existing filters from target columnGroup
    existing_filters = []
    column_groups = account_summary.get("columnGroups", [])
    for group in column_groups:
        if group.get("id") == current_column_group_id:
            filters_data = group.get("filters", [])
            for filter_data in filters_data:
                conditions = []
                for condition_data in filter_data.get("value", []):
                    try:
                        normalized_condition = normalize_filter_condition(condition_data)
                        conditions.append(FilterCondition(**normalized_condition))
                    except Exception as e:
                        logger.warning(f"Skipping invalid filter condition: {condition_data} - Error: {e}")
                        continue
                
                if conditions:  # Only add if we have valid conditions
                    try:
                        normalized_filter_group = normalize_filter_group(filter_data)
                        existing_filters.append(FilterGroup(
                            operator=LogicalOperator(normalized_filter_group.get("operator", "and")),
                            value=conditions,
                            source_type=FilterType(normalized_filter_group.get("source_type", "lens"))
                        ))
                    except Exception as e:
                        logger.warning(f"Skipping invalid filter group: {filter_data} - Error: {e}")
            break
    
    updated_filters = []
    
    for filter_group in existing_filters:
        # Filter out conditions that match the target filter
        remaining_conditions = [
            condition for condition in filter_group.value
            if not (condition.columnName.lower().replace(' ', '_') == filter_name.lower() or
                   condition.columnName.lower() == filter_label.lower())
        ]
        
        # Only keep filter groups that still have conditions
        if remaining_conditions:
            updated_filters.append(FilterGroup(
                operator=filter_group.operator,
                value=remaining_conditions,
                source_type=filter_group.source_type
            ))
    
    # Store in thread-local for backward compatibility
    thread_local.current_filters = updated_filters
    
    # Update target columnGroup with new filters
    filter_dicts = [sanitize_response_object(filter_group.dict()) for filter_group in updated_filters]
    update_column_group_filters(current_column_group_id, filter_dicts)
    
    return {
        "response_type": "success",
        "message": message,
        "account_summary": get_stored_account_summary()
    }


@tool("remove_multiple_filters", args_schema=MultipleFilterRemovalInput)
def remove_multiple_filters(filter_types: List[str], message: str) -> Dict[str, Any]:
    """Remove multiple specific filter types (e.g., 'account type and fund type')."""
    
    # Get stored account_summary from thread-local
    account_summary = get_stored_account_summary()
    if not account_summary:
        return {
            "response_type": "error",
            "message": "No account summary available",
            "account_summary": {}
        }
    
    # Identify target columnGroup using improved logic
    column_group_result = handle_column_group_identification(account_summary)
    if column_group_result["status"] != "success":
        # Return clarification or error directly
        column_group_result["account_summary"] = account_summary
        return column_group_result
    
    current_column_group_id = column_group_result["column_group_id"]
    
    # Get existing filters from target columnGroup
    existing_filters = []
    column_groups = account_summary.get("columnGroups", [])
    for group in column_groups:
        if group.get("id") == current_column_group_id:
            filters_data = group.get("filters", [])
            for filter_data in filters_data:
                conditions = []
                for condition_data in filter_data.get("value", []):
                    try:
                        normalized_condition = normalize_filter_condition(condition_data)
                        conditions.append(FilterCondition(**normalized_condition))
                    except Exception as e:
                        logger.warning(f"Skipping invalid filter condition: {condition_data} - Error: {e}")
                        continue
                
                if conditions:  # Only add if we have valid conditions
                    try:
                        normalized_filter_group = normalize_filter_group(filter_data)
                        existing_filters.append(FilterGroup(
                            operator=LogicalOperator(normalized_filter_group.get("operator", "and")),
                            value=conditions,
                            source_type=FilterType(normalized_filter_group.get("source_type", "lens"))
                        ))
                    except Exception as e:
                        logger.warning(f"Skipping invalid filter group: {filter_data} - Error: {e}")
            break
    
    updated_filters = []
    
    # Convert filter types to lowercase for matching
    filter_types_lower = [ft.lower().replace(' ', '_') for ft in filter_types]
    
    for filter_group in existing_filters:
        # Check if any condition in this group matches any of the filter types to remove
        should_remove_group = False
        
        for condition in filter_group.value:
            condition_name_variants = [
                condition.columnName.lower().replace(' ', '_'),
                condition.columnName.lower()
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
    
    # Store in thread-local for backward compatibility
    thread_local.current_filters = updated_filters
    
    # Update target columnGroup with new filters
    filter_dicts = [sanitize_response_object(filter_group.dict()) for filter_group in updated_filters]
    update_column_group_filters(current_column_group_id, filter_dicts)
    
    return {
        "response_type": "success",
        "message": message,
        "account_summary": get_stored_account_summary()
    }


@tool("remove_all_filters")
def remove_all_filters(message: str = "Successfully removed all filters.") -> Dict[str, Any]:
    """Remove all filters and reset to empty state."""
    
    # Get stored account_summary from thread-local
    account_summary = get_stored_account_summary()
    if not account_summary:
        return {
            "response_type": "error",
            "message": "No account summary available",
            "account_summary": {}
        }
    
    # Identify target columnGroup using improved logic
    column_group_result = handle_column_group_identification(account_summary)
    if column_group_result["status"] != "success":
        # Return clarification or error directly
        column_group_result["account_summary"] = account_summary
        return column_group_result
    
    current_column_group_id = column_group_result["column_group_id"]
    
    # Clear all filters
    thread_local.current_filters = []
    
    # Update target columnGroup with empty filters
    update_column_group_filters(current_column_group_id, [])
    
    return {
        "response_type": "success",
        "message": message,
        "account_summary": get_stored_account_summary()
    }


@tool("handle_casual_conversation")
def handle_casual_conversation(message: str) -> Dict[str, Any]:
    """Handle casual conversation that doesn't involve filter operations."""
    
    # Get initial filters from thread-local storage to preserve them
    initial_filters = getattr(thread_local, 'initial_filters', [])
    
    return {
        "response_type": "success",
        "message": message,
        "account_summary": get_final_account_summary()
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
        "account_summary": get_final_account_summary()
    }



def identify_target_column_group(user_query: str, account_summary: dict) -> str:
    """
    Identify which columnGroup the user wants to modify.
    Returns columnGroup ID or raises ColumnGroupClarificationNeeded.
    
    Args:
        user_query: The user's natural language query
        account_summary: The account summary data structure
        
    Returns:
        str: The columnGroup ID to use
        
    Raises:
        ColumnGroupClarificationNeeded: When clarification is required
    """
    column_groups = account_summary.get("columnGroups", [])
    
    # If only one group, use it
    if len(column_groups) == 1:
        return column_groups[0]["id"]
    
    # If no groups, raise error
    if len(column_groups) == 0:
        raise ValueError("No column groups found in account summary")
    
    # Extract group names from grouping[0].constant
    group_names = []
    for group in column_groups:
        group_name = _extract_group_name(group)
        if group_name:
            group_names.append({
                "id": group["id"],
                "name": group_name
            })
    
    # Check for explicit mentions in user query
    user_query_lower = user_query.lower()
    
    # Direct matching - check if any group name appears in the query
    for group_info in group_names:
        group_name_lower = group_info["name"].lower()
        if group_name_lower in user_query_lower:
            return group_info["id"]
    
    # Fuzzy matching - check for partial matches and common words
    for group_info in group_names:
        group_name_lower = group_info["name"].lower()
        group_words = group_name_lower.split()
        
        # Check if any word from the group name appears in the user query
        for word in group_words:
            if len(word) > 2 and word in user_query_lower:  # Only match words longer than 2 chars
                return group_info["id"]
    
    # Check for common abbreviations and synonyms
    synonyms = {
        "actual": ["actuals", "actual data"],
        "budget": ["budgets", "budget data"],
        "forecast": ["forecasts", "forecast data", "projected"],
        "plan": ["planned", "planning"],
        "prior": ["previous", "last year"],
        "current": ["this year", "cy"],
        "py": ["prior year", "previous year"]
    }
    
    for group_info in group_names:
        group_name_lower = group_info["name"].lower()
        for synonym_key, synonym_list in synonyms.items():
            if synonym_key in group_name_lower:
                for synonym in synonym_list:
                    if synonym in user_query_lower:
                        return group_info["id"]
    
    # If ambiguous, raise clarification exception
    available_groups = [{"id": g["id"], "name": g["name"]} for g in group_names]
    raise ColumnGroupClarificationNeeded(available_groups)


@tool("identify_column_group", args_schema=ColumnGroupIdentificationInput)
def identify_column_group(user_query: str, account_summary: Dict[str, Any], clarification_message: str) -> Dict[str, Any]:
    """Identify which columnGroup to modify when multiple columnGroups exist in account_summary."""
    
    try:
        column_group_id = identify_target_column_group(user_query, account_summary)
        set_current_column_group_id(column_group_id)
        
        # Find the group name for the identified ID
        column_groups = account_summary.get("columnGroups", [])
        group_name = None
        for group in column_groups:
            if group.get("id") == column_group_id:
                group_name = _extract_group_name(group)
                break
        
        return {
            "response_type": "success",
            "message": f"Identified column group: {group_name or column_group_id}",
            "column_group_id": column_group_id,
            "column_group_name": group_name
        }
        
    except ColumnGroupClarificationNeeded as e:
        # Format the clarification message with available options
        group_names = [group["name"] for group in e.available_groups if group["name"]]
        if group_names:
            options_text = "\n".join([f"• {name}" for name in group_names])
            formatted_message = f"{clarification_message}\n\nAvailable column groups:\n{options_text}\n\nWhich column group would you like to modify?"
        else:
            formatted_message = f"{clarification_message}\n\nNo identifiable column groups found."
        
        return {
            "response_type": "clarification_needed",
            "message": formatted_message,
            "column_group_id": None,
            "column_group_name": None,
            "available_groups": e.available_groups
        }
        
    except ValueError as e:
        return {
            "response_type": "error",
            "message": str(e),
            "column_group_id": None,
            "column_group_name": None
        }


@tool("select_column_group", args_schema=ColumnGroupSelectionInput)
def select_column_group(group_name: str, message: str) -> Dict[str, Any]:
    """Select a column group by name after clarification."""
    
    # Get stored account_summary from thread-local
    account_summary = get_stored_account_summary()
    if not account_summary:
        return {
            "response_type": "error",
            "message": "No account summary available",
            "account_summary": {}
        }
    
    column_groups = account_summary.get("columnGroups", [])
    
    # Find the column group by name (case-insensitive)
    group_name_lower = group_name.lower()
    selected_group_id = None
    
    for group in column_groups:
        group_display_name = _extract_group_name(group)
        if group_display_name and group_display_name.lower() == group_name_lower:
            selected_group_id = group.get("id")
            break
    
    # Also try partial matching if exact match fails
    if not selected_group_id:
        for group in column_groups:
            group_display_name = _extract_group_name(group)
            if group_display_name and group_name_lower in group_display_name.lower():
                selected_group_id = group.get("id")
                break
    
    if not selected_group_id:
        return {
            "response_type": "error",
            "message": f"Column group '{group_name}' not found. Please try again with an exact group name.",
            "account_summary": account_summary
        }
    
    # Set the selected column group as current
    set_current_column_group_id(selected_group_id)
    
    return {
        "response_type": "success",
        "message": message,
        "account_summary": account_summary,
        "selected_group_id": selected_group_id,
        "selected_group_name": group_name
    }


def _extract_group_name(column_group: Dict[str, Any]) -> Optional[str]:
    """Extract the group name from columnGroup.grouping[0].constant field."""
    grouping = column_group.get("grouping", [])
    if grouping and len(grouping) > 0:
        first_grouping = grouping[0]
        if isinstance(first_grouping, dict) and "constant" in first_grouping:
            return first_grouping["constant"]
    return None


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


def initialize_filter_state(account_summary: Optional[AccountSummary], delphi_session: str, available_filters: List[Dict[str, Any]] = None) -> None:
    """Initialize thread-local filter state from account_summary and store delphi session."""
    filter_groups = []
    
    # Store the full account_summary dict for local storage
    if account_summary:
        account_summary_dict = account_summary.dict() if hasattr(account_summary, 'dict') else account_summary
        store_account_summary(account_summary_dict)
        
        # Extract filters from the first columnGroup if account_summary is provided
        if hasattr(account_summary, 'columnGroups') and account_summary.columnGroups:
            first_column_group = account_summary.columnGroups[0]
            # Set the current column group ID to the first one
            set_current_column_group_id(first_column_group.id)
            initial_filters = first_column_group.filters
            
            for filter_data in initial_filters:
                conditions = []
                for condition_data in filter_data.get("value", []):
                    try:
                        normalized_condition = normalize_filter_condition(condition_data)
                        conditions.append(FilterCondition(**normalized_condition))
                    except Exception as e:
                        logger.warning(f"Skipping invalid filter condition: {condition_data} - Error: {e}")
                        continue
                
                if conditions:  # Only add if we have valid conditions
                    try:
                        normalized_filter_group = normalize_filter_group(filter_data)
                        filter_groups.append(FilterGroup(
                            operator=LogicalOperator(normalized_filter_group.get("operator", "and")),
                            value=conditions,
                            source_type=FilterType(normalized_filter_group.get("source_type", "lens"))
                        ))
                    except Exception as e:
                        logger.warning(f"Skipping invalid filter group during initialization: {filter_data} - Error: {e}")
        elif isinstance(account_summary, dict) and account_summary.get('columnGroups'):
            # Handle dict-based account_summary
            first_column_group = account_summary['columnGroups'][0]
            set_current_column_group_id(first_column_group.get('id'))
            initial_filters = first_column_group.get('filters', [])
            
            for filter_data in initial_filters:
                conditions = []
                for condition_data in filter_data.get("value", []):
                    try:
                        normalized_condition = normalize_filter_condition(condition_data)
                        conditions.append(FilterCondition(**normalized_condition))
                    except Exception as e:
                        logger.warning(f"Skipping invalid filter condition: {condition_data} - Error: {e}")
                        continue
                
                if conditions:  # Only add if we have valid conditions
                    try:
                        normalized_filter_group = normalize_filter_group(filter_data)
                        filter_groups.append(FilterGroup(
                            operator=LogicalOperator(normalized_filter_group.get("operator", "and")),
                            value=conditions,
                            source_type=FilterType(normalized_filter_group.get("source_type", "lens"))
                        ))
                    except Exception as e:
                        logger.warning(f"Skipping invalid filter group during initialization: {filter_data} - Error: {e}")
    else:
        # Initialize empty account_summary
        store_account_summary({})
    
    # Store the legacy account_summary for backward compatibility
    thread_local.account_summary = account_summary
    
    thread_local.current_filters = filter_groups
    thread_local.initial_filters = filter_groups.copy()  # Store initial state for preservation
    thread_local.delphi_session = delphi_session
    thread_local.available_filters = available_filters or []


def get_current_filters() -> List[FilterGroup]:
    """Get current filter state."""
    return getattr(thread_local, 'current_filters', [])


# Export all tools for the agent
FILTER_TOOLS = [add_filter, modify_filter, remove_filter, remove_multiple_filters, remove_all_filters, handle_casual_conversation, request_clarification, get_filter_values, add_or_filter, identify_column_group, select_column_group]

# Export storage functions for use by other modules
__all__ = [
    'FILTER_TOOLS',
    'initialize_filter_state', 
    'get_current_filters',
    'store_account_summary',
    'get_stored_account_summary', 
    'set_current_column_group_id',
    'get_current_column_group_id',
    'update_column_group_filters',
    'get_final_account_summary',
    'set_user_query',
    'get_user_query',
    'identify_target_column_group'
]



