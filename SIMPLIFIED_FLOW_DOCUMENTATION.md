# Simplified Natural Language Filter Flow

## Overview

The simplified flow for `/api/filters/natural-language` reduces LLM calls from N+1 to exactly 2 by implementing a planning-only approach where the agent returns execution plans instead of executing operations directly.

## Flow Steps

### 1. Request Processing
- `available_filters` and `account_summary` are sent in the request body
- Column groups and their IDs are extracted from `account_summary`
- Both `available_filters` and `columnGroups` are embedded in the system prompt sent to the LLM

### 2. Agent Planning Phase
- Agent has only one tool: `get_filter_values`
- Agent **always** calls `get_filter_values` immediately when user mentions a filter
- Agent analyzes the user query and available filter values
- Agent returns execution plan with function names and parameters

### 3. Manual Execution Phase
- Backend receives execution plan from agent
- Backend manually calls the appropriate functions based on the plan
- Functions are executed sequentially
- Final response is sent to user based on execution results

## API Response Formats

### Success Response
```json
{
  "status": "success",
  "execution_plan": [
    {"function_name": "add_filter", "parameters": ["account_type", "Assets"]},
    {"function_name": "remove_filter", "parameters": ["fiscal_period", "10"]}
  ],
  "message": "Execution plan created successfully",
  "account_summary": {...},
  "conversation_id": "conv_123"
}
```

### Clarification Needed Response
```json
{
  "status": "clarification_needed",
  "message": "The value 'XYZ' is not available for Account Type. Please choose from: Assets, Liabilities, Equity",
  "available_values": ["Assets", "Liabilities", "Equity", "Revenue", "Expenses"],
  "filter_name": "account_type",
  "filter_label": "Account Type",
  "conversation_id": "conv_123"
}
```

### Error Response
```json
{
  "status": "error",
  "message": "Error description",
  "error_code": "ERROR_CODE",
  "conversation_id": "conv_123"
}
```

## Available Functions in Execution Plans

1. **add_filter**: Add a new filter condition
   - Parameters: `[filter_name, filter_value]`
   - Example: `{"function_name": "add_filter", "parameters": ["account_type", "Assets"]}`

2. **modify_filter**: Modify existing filter
   - Parameters: `[filter_name, filter_value]`
   - Example: `{"function_name": "modify_filter", "parameters": ["fiscal_period", "5"]}`

3. **remove_filter**: Remove specific filter
   - Parameters: `[filter_name, filter_value]`
   - Example: `{"function_name": "remove_filter", "parameters": ["account_type", "Assets"]}`

4. **remove_all_filters**: Remove all filters
   - Parameters: `[]`
   - Example: `{"function_name": "remove_all_filters", "parameters": []}`

5. **request_clarification**: Ask user to choose from available options
   - Parameters: `[filter_name, user_input, available_values, message]`
   - Used internally when filter values don't match

## Key Components

### SimplifiedFilterAgent (`src/agent/simplified_agent.py`)
- Handles the planning phase
- Embeds available filters and column groups in system prompt
- Returns execution plans instead of executing operations
- Reduces LLM interactions to exactly 2 calls

### Simplified Tools (`src/tools/simplified_tools.py`)
- Contains only `get_filter_values` tool
- Fetches available values for filters mentioned by user
- Provides mock data for testing (can be replaced with real API calls)

### Manual Execution Functions (`src/api/main.py`)
- `_execute_agent_plan()`: Main execution coordinator
- `_execute_add_filter()`: Execute add filter operations
- `_execute_modify_filter()`: Execute modify filter operations
- `_execute_remove_filter()`: Execute remove filter operations
- `_execute_remove_all_filters()`: Execute remove all operations
- `_execute_request_clarification()`: Handle clarification requests

## Performance Benefits

1. **Reduced LLM Calls**: From N+1 to exactly 2 calls
2. **60-70% Latency Reduction**: Fewer network round trips
3. **Better Error Handling**: Immediate failure response without multiple LLM calls
4. **Maintained Functionality**: All existing filter operations supported

## Example Usage

```python
# Request
{
  "query": "add account type filter for Assets",
  "available_filters": [...],
  "account_summary": {...},
  "conversation_id": "conv_123"
}

# Agent Planning Phase Response
{
  "status": "success", 
  "execution_plan": [
    {"function_name": "add_filter", "parameters": ["account_type", "Assets"]}
  ]
}

# Backend Execution Phase
# - Calls add_filter("account_type", "Assets") internally
# - Returns final response with updated account_summary
```

## Migration from Old Flow

The new simplified flow is backward compatible and can be used alongside the existing flow. The main differences:

1. **Old Flow**: Agent executes operations directly using multiple tools
2. **New Flow**: Agent returns execution plans, backend executes manually
3. **Performance**: New flow is significantly faster with fewer LLM calls
4. **Maintainability**: Cleaner separation between planning and execution

## Testing

Run the example file to test the simplified flow:

```bash
python example_simplified_flow.py
```

This will test various scenarios including successful operations, clarification requests, and error handling.
