"""Natural Language Filter Agent - Clean implementation from scratch."""

__version__ = "2.0.0"

from .agent import FilterAgent
from .models import FilterRequest, FilterAPIResponse
from .api import app

__all__ = [
    "FilterAgent",
    "FilterRequest", 
    "FilterAPIResponse",
    "app",
    "__version__"
]
