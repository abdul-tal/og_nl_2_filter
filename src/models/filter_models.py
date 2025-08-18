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
    columnName: str = Field(..., description="Column name from filter label")
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
    
    def dict(self, **kwargs):
        """Custom dict method to exclude source_type from JSON output."""
        result = super().dict(**kwargs)
        result.pop('source_type', None)
        return result
    
    def json(self, **kwargs):
        """Custom json method to exclude source_type from JSON output."""
        return super().json(exclude={'source_type'}, **kwargs)


class ColumnGroup(BaseModel):
    """Column group configuration for account summary."""
    id: str = Field(..., description="Column group identifier")
    lens: Dict[str, Any] = Field(..., description="Lens configuration")
    measureColumn: Dict[str, Any] = Field(..., description="Measure column configuration")
    grouping: List[Dict[str, Any]] = Field(..., description="Grouping configuration")
    filters: List[Dict[str, Any]] = Field(..., description="Filters for this column group")
    dateFilter: List[Dict[str, Any]] = Field(..., description="Date filter configuration")
    relativeFilter: str = Field(..., description="Relative filter configuration")
    type: str = Field(..., description="Column group type")
    columnValueMapping: Dict[str, Any] = Field(..., description="Column value mapping")
    rollingNumRangeOption: Dict[str, Any] = Field(..., description="Rolling number range options")


class AccountSummary(BaseModel):
    """Account summary configuration."""
    columnGroups: List[ColumnGroup] = Field(..., description="List of column groups")
    columnOrder: Dict[str, Any] = Field(..., description="Column order configuration")
    expandedGroupKeys: Dict[str, Any] = Field(..., description="Expanded group keys")
    expandedRows: Dict[str, Any] = Field(..., description="Expanded rows configuration")
    filters: List[Dict[str, Any]] = Field(..., description="Global filters")
    formatting: Dict[str, Any] = Field(..., description="Formatting configuration")
    hiddenColumns: Dict[str, Any] = Field(..., description="Hidden columns configuration")
    rowGroups: List[Dict[str, Any]] = Field(..., description="Row groups configuration")
    charts: List[Dict[str, Any]] = Field(..., description="Charts configuration")
    rounding: Dict[str, Any] = Field(..., description="Rounding configuration")


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
    account_summary: Optional[AccountSummary] = Field(None, description="Current account summary state")
    conversation_id: Optional[str] = Field(None, description="Conversation ID")


class FilterResponse(BaseModel):
    """Success response with account summary."""
    type: str = Field(default="success", description="Response type")
    message: str = Field(..., description="Human-readable message")
    account_summary: AccountSummary = Field(..., description="Updated account summary")
    conversation_id: Optional[str] = Field(None, description="Conversation ID")


class ErrorResponse(BaseModel):
    """Error response."""
    type: str = Field(default="error", description="Response type")
    message: str = Field(..., description="Error message")
    error_code: str = Field(..., description="Error code")
    conversation_id: Optional[str] = Field(None, description="Conversation ID")


class ColumnGroupClarificationNeeded(Exception):
    """Exception raised when column group clarification is needed."""
    
    def __init__(self, available_groups: List[Dict[str, str]], message: str = "Multiple column groups found. Please specify which one."):
        self.available_groups = available_groups
        self.message = message
        super().__init__(self.message)


class ColumnGroupClarificationResponse(BaseModel):
    """Response requesting column group clarification."""
    type: str = Field(default="clarification_needed", description="Response type")
    message: str = Field(..., description="Clarification message")
    available_groups: List[Dict[str, str]] = Field(..., description="Available column groups for selection")
    conversation_id: Optional[str] = Field(None, description="Conversation ID")


class ColumnGroupSelectionRequest(BaseModel):
    """Request model for column group selection."""
    column_group_id: str = Field(..., description="Selected column group ID")
    column_group_name: str = Field(..., description="Selected column group name")


# Union type for API responses
FilterAPIResponse = Union[FilterResponse, ErrorResponse, ColumnGroupClarificationResponse]
