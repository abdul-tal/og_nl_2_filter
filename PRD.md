# Product Requirements Document: Natural Language Filter Agent

## 1. Overview

### Product Name
Natural Language Filter Agent

### Purpose
A single API endpoint that accepts natural language filter requests and returns structured filter objects, designed for seamless UI chatbot integration.

### Key Value Proposition
- **Single API Integration**: One endpoint handles all filter logic for easy UI integration
- **Conversational Interface**: Natural language input with intelligent responses
- **Auto-Resolution**: Automatically fetches and validates filter values internally
- **Fallback Handling**: Provides suggestions when exact matches aren't found

## 2. Problem Statement

Users need to apply complex data filters but face challenges with:
- Understanding available filter options and their technical names
- Knowing exact values that exist in the dataset
- Constructing proper filter syntax and operators
- Managing multiple filter combinations efficiently

## 3. Solution Overview

A single REST API endpoint that:
1. Accepts natural language filter requests with available filter metadata
2. Uses OpenAI LLM to interpret user intent
3. Internally fetches filter values from reporting service when needed
4. Maps user requests to structured filter objects
5. Provides suggestions when exact matches aren't found
6. Returns either successful filters or clarification requests

## 4. API Design

### 4.1 Single Endpoint

```
POST /api/filters/natural-language
```

### 4.2 Request Schema

```python
from pydantic import BaseModel
from typing import List, Optional

class AvailableFilter(BaseModel):
    name: str           # Technical filter name (e.g., "demo-filter")
    label: str          # Human-readable label (e.g., "demo-label") 
    type: str           # Filter type (e.g., "lens/dimensions")

class FilterRequest(BaseModel):
    query: str                              # Natural language filter request
    available_filters: List[AvailableFilter] # Available filter metadata
    conversation_id: Optional[str] = None    # For multi-turn conversations
    context: Optional[dict] = None          # Additional context if needed

# Example Request
{
  "query": "Show me accounts with type 'Accounts Payable' for fiscal period 10",
  "available_filters": [
    {"name": "account_type", "label": "Account Type", "type": "lens"},
    {"name": "fiscal_period", "label": "Fiscal Period", "type": "lens"}
  ],
  "conversation_id": "conv_123",
  "context": {}
}
```

### 4.3 Response Schema

```python
from enum import Enum
from typing import List, Optional, Union

class ResponseType(str, Enum):
    SUCCESS = "success"           # Filters successfully created
    CLARIFICATION = "clarification"  # Need user to choose from options
    ERROR = "error"              # Invalid request or system error

class FilterOperator(str, Enum):
    EQUAL = "equal"
    NOT_EQUAL = "notEqual"
    CONTAINS = "contains"
    DOES_NOT_CONTAIN = "doesNotContain"
    IS_BLANK = "isBlank"
    IS_NOT_BLANK = "isNotBlank"

class LogicalOperator(str, Enum):
    AND = "and"
    OR = "or"

class SourceType(str, Enum):
    LENS = "lens"
    DIMENSIONS = "dimensions"

class FilterCondition(BaseModel):
    column_name: str        # Maps to filter.label from availableFilters
    value: str              # Selected value from API response
    operator: FilterOperator

class FilterGroup(BaseModel):
    operator: LogicalOperator
    value: List[FilterCondition]
    source_type: SourceType

# Success Response
class FilterResponse(BaseModel):
    type: ResponseType
    message: str
    filters: Optional[List[FilterGroup]] = None
    conversation_id: Optional[str] = None

# Clarification Response
class ClarificationOption(BaseModel):
    filter_name: str
    available_values: List[str]
    user_input: str  # What user originally asked for

class ClarificationResponse(BaseModel):
    type: ResponseType
    message: str
    clarifications: List[ClarificationOption]
    conversation_id: Optional[str] = None

# Error Response
class ErrorResponse(BaseModel):
    type: ResponseType
    message: str
    error_code: Optional[str] = None
    conversation_id: Optional[str] = None

FilterAPIResponse = Union[FilterResponse, ClarificationResponse, ErrorResponse]
```

### 4.4 Example API Responses

#### Success Response Example
```json
{
  "type": "success",
  "message": "Applied filters for Account Type = 'Accounts Payable' and Fiscal Period = '10'",
  "filters": [
    {
      "operator": "and",
      "value": [
        {
          "column_name": "account_type",
          "value": "Accounts Payable",
          "operator": "equal"
        }
      ],
      "source_type": "lens"
    },
    {
      "operator": "and", 
      "value": [
        {
          "column_name": "fiscal_period",
          "value": "10",
          "operator": "equal"
        }
      ],
      "source_type": "lens"
    }
  ],
  "conversation_id": "conv_123"
}
```

#### Clarification Response Example
```json
{
  "type": "clarification",
  "message": "I couldn't find exact matches for some values. Please choose from available options:",
  "clarifications": [
    {
      "filter_name": "account_type",
      "user_input": "Checking Account",
      "available_values": ["Accounts Payable", "Accounts Receivable", "Cash", "Inventory"]
    }
  ],
  "conversation_id": "conv_123"
}
```

#### Error Response Example
```json
{
  "type": "error",
  "message": "Filter 'invalid_filter' not found in available filters",
  "error_code": "FILTER_NOT_FOUND",
  "conversation_id": "conv_123"
}
```

## 5. Functional Requirements

### 5.1 Core Workflow (Single API)

1. **Request Processing**
   - Receive natural language query + available filters in single request
   - Parse and index available filters for efficient lookup
   - Validate request structure and required fields

2. **Intent Analysis**
   - Use OpenAI to parse natural language and identify:
     - Filter references (by name or label)
     - Desired values or value patterns
     - Logical operators (and/or/not)
     - Comparison operators (equals, contains, blank, etc.)

3. **Value Resolution & Validation**
   - For each identified filter, internally call reporting service API
   - Match user's desired values against available values
   - Handle fuzzy matching for approximate matches

4. **Response Generation**
   - **Success Path**: Return structured filters when all values match
   - **Clarification Path**: Return available options when values don't match
   - **Error Path**: Return error details for invalid requests

5. **Conversation State**
   - Maintain conversation context using conversation_id
   - Support follow-up clarifications in subsequent requests

### 5.2 Intelligent Matching

#### Exact Match
- Direct string comparison (case-insensitive)
- Support for partial string matching when appropriate

#### Fuzzy Matching
- Handle typos and minor variations
- Semantic similarity for conceptually related terms
- Suggest top 3-5 closest matches when exact match fails

#### Contextual Understanding
- Recognize common filter patterns:
  - Date ranges → fiscal_period filters
  - Account types → account_type filters
  - Blank/empty conditions → isBlank/isNotBlank operators

### 5.3 Error Handling

#### Invalid Filter References
- When user mentions non-existent filter names/labels
- Suggest similar available filters
- List all available filters if no close matches

#### Missing Values
- When API returns empty value set
- Inform user that filter has no available values
- Suggest alternative filters

#### Ambiguous Queries
- When multiple interpretations possible
- Ask clarifying questions
- Provide examples of valid syntax

## 6. User Experience Requirements

### 6.1 UI Integration Examples

#### Happy Path - Direct Success
```javascript
// UI sends request
POST /api/filters/natural-language
{
  "query": "Show accounts with type 'Accounts Payable' for fiscal period 10",
  "available_filters": [...],
  "conversation_id": "conv_123"
}

// API returns success
{
  "type": "success",
  "message": "Applied filters for Account Type = 'Accounts Payable' and Fiscal Period = '10'",
  "filters": [...]
}

// UI can immediately apply filters to data
```

#### Clarification Path - Need User Choice
```javascript
// UI sends request
POST /api/filters/natural-language
{
  "query": "Filter by account type 'Checking'",
  "available_filters": [...],
  "conversation_id": "conv_124"
}

// API returns clarification
{
  "type": "clarification", 
  "message": "I couldn't find 'Checking' in account types. Please choose:",
  "clarifications": [
    {
      "filter_name": "account_type",
      "user_input": "Checking",
      "available_values": ["Accounts Payable", "Accounts Receivable", "Cash"]
    }
  ]
}

// UI displays options for user selection
// User selects "Cash"

// UI sends follow-up request
POST /api/filters/natural-language
{
  "query": "Use 'Cash' for account type",
  "available_filters": [...],
  "conversation_id": "conv_124"  // Same conversation
}

// API returns success with filters
```

### 6.2 Benefits for UI Integration

#### Single API Call
- **Simplified Integration**: UI only needs to integrate with one endpoint
- **Reduced Complexity**: No need to manage multiple API calls or orchestration
- **Better Performance**: Server-side optimization of data fetching

#### Conversation Management
- **Stateful Conversations**: Server maintains context between requests
- **Multi-turn Support**: Handle clarifications naturally
- **Session Persistence**: UI can pause/resume conversations

#### Error Handling
- **Standardized Responses**: Consistent response format for all scenarios
- **Clear Action Items**: UI knows exactly what to do with each response type
- **User Guidance**: Built-in suggestions for better user experience

## 7. Technical Requirements

### 7.1 Architecture Overview

```
┌─────────────────┐    POST /api/filters/natural-language    ┌─────────────────┐
│                 │ ────────────────────────────────────────► │                 │
│   UI Chatbot    │                                           │  Filter Agent   │
│                 │ ◄──────────────────────────────────────── │   (Single API)  │
└─────────────────┘              JSON Response               └─────────────────┘
                                                                        │
                                                                        │ Internal Calls
                                                                        ▼
                                                              ┌─────────────────┐
                                                              │  Reporting API  │
                                                              │ (Filter Values) │
                                                              └─────────────────┘
```

### 7.2 Internal Implementation

#### OpenAI Integration
- **Model**: GPT-4 or GPT-3.5-turbo for natural language understanding
- **Function Calling**: Internal tool for fetching filter values
- **Structured Output**: Consistent response formatting

#### Internal Tool for Value Fetching
```python
# Internal function (not exposed to UI)
async def get_filter_values(filter_name: str, source_type: str) -> List[str]:
    """
    Internal function to fetch filter values from reporting service
    """
    url = f"http://controlpanel.ogov.me/api/reporting_service/next/dataset/{source_type}/column/{filter_name}/distinct"
    
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        response.raise_for_status()
        data = response.json()
        return data.get("values", [])
```

### 7.3 State Management

#### Conversation Context
- Track conversation history using conversation_id
- Support multi-turn clarifications
- Session timeout and cleanup

#### Caching Strategy
- Cache filter values to reduce API calls to reporting service
- Implement TTL for value freshness (e.g., 1 hour)
- In-memory cache for development, Redis for production

### 7.4 Performance Requirements

#### Response Time Targets
- **Success Response**: < 3 seconds end-to-end
- **Clarification Response**: < 2 seconds (no filter fetching needed)
- **Error Response**: < 1 second

#### Scalability
- Support concurrent requests from multiple UI sessions
- Rate limiting to prevent abuse
- Horizontal scaling capability

### 7.5 Deployment Architecture

```python
# FastAPI application structure
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Natural Language Filter Agent")

@app.post("/api/filters/natural-language", response_model=FilterAPIResponse)
async def process_filter_request(request: FilterRequest) -> FilterAPIResponse:
    """
    Single endpoint that handles all filter processing
    """
    try:
        # 1. Parse available filters
        # 2. Use OpenAI to understand intent
        # 3. Fetch filter values internally if needed
        # 4. Return appropriate response type
        pass
    except Exception as e:
        return ErrorResponse(
            type="error",
            message=str(e),
            conversation_id=request.conversation_id
        )
```

## 8. Success Metrics

### 8.1 Accuracy Metrics
- **Filter Resolution Rate**: % of filters correctly identified
- **Value Match Rate**: % of user values successfully matched
- **Query Success Rate**: % of queries resulting in valid filters

### 8.2 User Experience Metrics
- **Conversation Length**: Average turns to complete filter
- **User Satisfaction**: Qualitative feedback on ease of use
- **Error Recovery**: % of errors leading to successful resolution

### 8.3 Performance Metrics
- **Response Time**: < 3 seconds end-to-end
- **API Call Efficiency**: Minimize redundant value fetches
- **Cache Hit Rate**: % of value requests served from cache

## 9. Future Enhancements

### 9.1 Advanced Features
- **Multi-turn Conversations**: Build complex filters over multiple exchanges
- **Filter Validation**: Warn about conflicting or ineffective filter combinations
- **Smart Suggestions**: Proactively suggest useful filters based on data patterns

### 9.2 Integration Capabilities
- **Filter Persistence**: Save and recall named filter sets
- **Integration APIs**: Webhook/callback support for external systems
- **Batch Processing**: Handle multiple filter requests simultaneously

## 10. Implementation Phases

### Phase 1: Core Functionality (MVP)
- Basic natural language parsing
- Filter value API integration
- Simple exact matching
- Basic error handling

### Phase 2: Enhanced Intelligence
- Fuzzy matching capabilities
- Contextual understanding
- Improved suggestion engine

### Phase 3: Advanced Features
- Multi-turn conversations
- Performance optimizations
- Advanced caching strategies

## 11. Dependencies

### External Dependencies
- OpenAI Python SDK (`openai`)
- Pydantic for data validation (`pydantic`)
- HTTP client library (`httpx` or `requests`)
- Existing filter values API endpoint
- Authentication/authorization system

### Internal Dependencies
- Filter metadata availability
- Consistent filter naming conventions
- Stable API contracts

### Python Package Requirements
```
openai>=1.0.0
pydantic>=2.0.0
httpx>=0.24.0
python-dotenv>=1.0.0  # For environment variable management
typing-extensions>=4.0.0  # For enhanced type hints
```

## 12. Risks and Mitigations

### Technical Risks
- **API Rate Limits**: Implement intelligent caching and request batching
- **LLM Consistency**: Use structured prompts and validation
- **Filter API Changes**: Version API contracts and handle gracefully

### User Experience Risks
- **Complex Queries**: Provide clear examples and guidance
- **Ambiguous Intent**: Design conversation flows for clarification
- **Performance**: Set clear expectations for response times

---

This PRD provides a comprehensive foundation for implementing the Natural Language Filter Agent. The modular design allows for iterative development while maintaining focus on core user value and technical feasibility.
