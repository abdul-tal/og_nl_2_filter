"""FastAPI application for the filter agent."""

import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ..models import FilterRequest, FilterAPIResponse
from ..agent import FilterAgent
from ..config import get_settings
from ..utils import conversation_store

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
    from ..models import FilterResponse, FilterGroup, FilterCondition
    
    # Create a simple demo filter based on the query
    query_lower = request.query.lower()
    
    if "account" in query_lower and "payable" in query_lower:
        demo_filter = FilterGroup(
            operator="and",
            value=[FilterCondition(
                column_name="Account Type",
                value="Accounts Payable", 
                operator="equal"
            )],
            source_type="lens"
        )
    elif "fiscal" in query_lower and "10" in query_lower:
        demo_filter = FilterGroup(
            operator="and",
            value=[FilterCondition(
                column_name="Fiscal Period",
                value="10",
                operator="equal"
            )],
            source_type="lens"
        )
    else:
        demo_filter = FilterGroup(
            operator="and",
            value=[FilterCondition(
                column_name="Demo Filter",
                value="Demo Value",
                operator="equal"
            )],
            source_type="lens"
        )
    
    # Include existing filters if any
    existing_filters = []
    if request.initial_filters:
        for filter_data in request.initial_filters:
            conditions = [
                FilterCondition(**condition_data)
                for condition_data in filter_data.get("value", [])
            ]
            existing_filters.append(FilterGroup(
                operator=filter_data.get("operator", "and"),
                value=conditions,
                source_type=filter_data.get("source_type", "lens")
            ))
    
    # Combine existing and new filters
    all_filters = existing_filters + [demo_filter]
    
    return FilterResponse(
        message=f"Demo: Created filter based on '{request.query}'",
        filters=all_filters,
        conversation_id=request.conversation_id
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.api_host, port=settings.api_port)
