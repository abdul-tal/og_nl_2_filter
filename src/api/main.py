"""FastAPI application for the filter agent."""

import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ..models import FilterRequest, FilterAPIResponse
from ..agent import FilterAgent
from ..config import get_settings
from ..utils import conversation_store
from ..tools.filter_tools import sanitize_response_object

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

# Initialize filter agent
try:
    filter_agent = FilterAgent(
        openai_api_key=settings.openai_api_key,
        model=settings.openai_model,
        temperature=settings.openai_temperature
    )
    logger.info("Filter agent initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize filter agent: {e}")
    # Create a mock agent for demo mode
    filter_agent = None


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


@app.post("/api/filters/natural-language", response_model=FilterAPIResponse)
async def process_filter_request(request: FilterRequest) -> FilterAPIResponse:
    """
    Process a natural language filter request.
    
    This endpoint takes a natural language query and converts it to structured filters
    while preserving existing filters and supporting incremental operations.
    """
    try:
        if filter_agent is None:
            # Demo mode - return mock response
            return _create_demo_response(request)
        
        # Process the request using the filter agent
        response = filter_agent.process_request(request)
        
        # Sanitize the response to remove unwanted properties
        if hasattr(response, 'dict'):
            response_dict = response.dict()
            sanitized_dict = sanitize_response_object(response_dict)
            # Create a custom JSONResponse to ensure sanitization is applied
            return JSONResponse(content=sanitized_dict)
        
        logger.info(f"Processed request for conversation {request.conversation_id}")
        return response
        
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}")
        from ..models import ErrorResponse
        return ErrorResponse(
            message="An error occurred while processing your request.",
            error_code="API_ERROR",
            conversation_id=request.conversation_id
        )


def _create_demo_response(request: FilterRequest) -> FilterAPIResponse:
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
    response_dict = response.dict()
    sanitized_dict = sanitize_response_object(response_dict)
    return JSONResponse(content=sanitized_dict)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.api_host, port=settings.api_port)
