"""Core filter data models."""

from typing import List, Dict, Any, Optional, Union
from pydantic import BaseModel, Field
from enum import Enum


class FilterOperator(str, Enum):
    """Filter operators."""
    EQUAL = "equal"
    NOT_EQUAL = "notEqual"
    CONTAINS = "contains"
    DOES_NOT_CONTAIN = "doesNotContain"
    IS_BLANK = "isBlank"
    IS_NOT_BLANK = "isNotBlank"


class FilterType(str, Enum):
    """Filter source types."""
    LENS = "lens"
    DIMENSIONS = "dimensions"


class LogicalOperator(str, Enum):
    """Logical operators for filter groups."""
    AND = "and"
    OR = "or"


class ResponseType(str, Enum):
    """Response types."""
    SUCCESS = "success"
    ERROR = "error"


class AvailableFilter(BaseModel):
    """Available filter metadata."""
    name: str = Field(..., description="Filter name/identifier")
    label: str = Field(..., description="Human-readable label")
    sourceType: str = Field(..., description="Filter source type (lens/dimensions)")
    sourceId: str = Field(..., description="Source ID for API calls")
    joinColumnName: Optional[str] = Field(None, description="Join column name for dimension filters")


class DimensionInfo(BaseModel):
    """Dimension information for dimension filters."""
    id: str = Field(..., description="Dimension source ID")


class FilterCondition(BaseModel):
    """Individual filter condition."""
    column_name: str = Field(..., description="Column name from filter label")
    value: str = Field(..., description="Filter value")
    operator: FilterOperator = Field(default=FilterOperator.EQUAL, description="Filter operator")
    dimension: Optional[DimensionInfo] = Field(None, description="Dimension info for dimension filters")
    joinColumnName: Optional[str] = Field(None, description="Join column name for dimension filters")
    
    def dict(self, **kwargs):
        """Custom dict method to include dimension fields only when present."""
        result = super().dict(**kwargs)
        # Only include dimension and joinColumnName if dimension is present
        if self.dimension is None:
            result.pop('dimension', None)
            result.pop('joinColumnName', None)
        return result


class FilterGroup(BaseModel):
    """Group of filter conditions with logical operator."""
    operator: LogicalOperator = Field(default=LogicalOperator.AND, description="Logical operator")
    value: List[FilterCondition] = Field(..., description="Filter conditions")
    source_type: FilterType = Field(..., description="Source type for this group")


class ConversationMessage(BaseModel):
    """A single message in the conversation history."""
    role: str = Field(..., description="Role: 'user' or 'assistant'")
    content: str = Field(..., description="Message content")
    timestamp: Optional[str] = Field(default=None, description="Message timestamp")


class FilterRequest(BaseModel):
    """Request model for filter operations."""
    query: str = Field(..., description="Natural language filter request")
    available_filters: List[AvailableFilter] = Field(..., description="Available filter metadata")
    delphi_session: str = Field(..., description="Authentication session")
    initial_filters: Optional[List[Dict[str, Any]]] = Field(None, description="Current filter state")
    conversation_id: Optional[str] = Field(None, description="Conversation ID")


class FilterResponse(BaseModel):
    """Success response with filters."""
    type: str = Field(default="success", description="Response type")
    message: str = Field(..., description="Human-readable message")
    filters: List[FilterGroup] = Field(..., description="Filter groups")
    conversation_id: Optional[str] = Field(None, description="Conversation ID")


class ErrorResponse(BaseModel):
    """Error response."""
    type: str = Field(default="error", description="Response type")
    message: str = Field(..., description="Error message")
    error_code: str = Field(..., description="Error code")
    conversation_id: Optional[str] = Field(None, description="Conversation ID")


# Union type for API responses
FilterAPIResponse = Union[FilterResponse, ErrorResponse]
