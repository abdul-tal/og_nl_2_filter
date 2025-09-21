"""Simplified tools for the planning-only filter agent."""

import json
from shlex import quote
from urllib.parse import quote as url_quote
import httpx
import threading
import logging
import time
from typing import List, Dict, Any, Optional
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from .filter_tools import cleanup_expired_cache, get_from_cache, set_cache

logger = logging.getLogger(__name__)

# Thread-local storage for simplified state
thread_local = threading.local()

def initialize_simplified_state(available_filters: List[Dict], account_summary: Dict = None, delphi_session: str = None) -> None:
    """Initialize simplified state with available filters, account summary, and delphi session."""
    thread_local.available_filters = [f.model_dump() if hasattr(f, 'model_dump') else f for f in available_filters]
    thread_local.account_summary = account_summary.model_dump() if hasattr(account_summary, 'model_dump') else account_summary
    thread_local.delphi_session = delphi_session if delphi_session else ''

def get_available_filters() -> List[Dict]:
    """Get available filters from thread-local storage."""
    return getattr(thread_local, 'available_filters', [])

def get_account_summary() -> Dict:
    """Get account summary from thread-local storage."""
    return getattr(thread_local, 'account_summary', {})

class GetFilterValuesInput(BaseModel):
    """Input schema for get_filter_values tool."""
    filter_name: str = Field(..., description="Name/identifier of the filter to get values for")
    source_id: str = Field(..., description="Source ID for the filter API call")

@tool("get_filter_values", args_schema=GetFilterValuesInput)
def get_filter_values_tool(filter_name: str, source_id: str) -> Dict[str, Any]:
    """Fetch available values for a filter from the API using the sourceId."""
    # Clean up expired cache entries periodically
    cleanup_expired_cache()
    
    # Check enhanced cache first
    cache_key = f"{filter_name}_{source_id}"
    cache_hit, cached_data = get_from_cache(cache_key)
    if cache_hit:
        return {
            "filter_name": filter_name,
            "source_id": source_id,
            "available_values": cached_data,
            "status": "success"
        }
    
    # Get delphi session from thread-local storage
    delphi_session = getattr(thread_local, 'delphi_session', '')
    print('delphi_session:::', delphi_session)
    url_encoded_source_id = url_quote(source_id, safe='');
    print('url_encoded_source_id:::', url_encoded_source_id)
    url = f"https://controlpanel.ogintegration.us/api/reporting_service/next/dataset/{url_encoded_source_id}/column/{filter_name}/distinct"
    print('url:::', url)
    
    headers = {
        "Cookie": f"_delphi_session={delphi_session}",
        "Content-Type": "application/json"
    }
    
    try:
        api_start = time.time()
        print(f"      🌐 [TIMING] Starting API call for filter '{filter_name}'...")
        
        # Use httpx for async-compatible HTTP requests
        with httpx.Client() as client:
            response = client.get(url, headers=headers)
        
        api_time = time.time() - api_start
        print(f"      📡 [TIMING] API call completed in: {api_time:.3f}s")
        
        if response.status_code == 200:
            parse_start = time.time()
            data = response.json()
            values = data.get("data", [])
            result = [str(value) for value in values if value is not None][:50]  # Limit to 50 values
            parse_time = time.time() - parse_start
            
            print(f'      ✅ [TIMING] Successfully fetched {len(result)} values for {filter_name} (parsing: {parse_time:.3f}s)')
            print(f'      📊 [TIMING] Sample values: {result[:5]}...')
            
            # Cache the result with enhanced caching system
            if result:
                set_cache(cache_key, result, ttl_seconds=300)  # 5 minute TTL
            else:
                # Cache empty results with shorter TTL to avoid repeated failed requests
                set_cache(cache_key, [], ttl_seconds=60)  # 1 minute TTL for empty results
            
            return {
                "filter_name": filter_name,
                "source_id": source_id,
                "available_values": result,
                "status": "success"
            }
        else:
            print(f'      ❌ [TIMING] API request failed with status {response.status_code} for {filter_name} (took: {api_time:.3f}s)')
            # Cache failed requests with very short TTL to avoid immediate retries
            set_cache(cache_key, [], ttl_seconds=30)  # 30 second TTL for failed requests
            return {
                "filter_name": filter_name,
                "source_id": source_id,
                "available_values": [],
                "status": "error",
                "error": f"API request failed with status {response.status_code}"
            }
    except Exception as e:
        print(f'Exception while fetching filter values for {filter_name}: {str(e)}')
        # Cache exceptions with very short TTL
        set_cache(cache_key, [], ttl_seconds=30)
        return {
            "filter_name": filter_name,
            "source_id": source_id,
            "available_values": [],
            "status": "error",
            "error": str(e)
        }

def _get_mock_filter_values(filter_name: str) -> List[str]:
    """Get mock filter values based on filter name."""
    
    # Mock data - in real implementation, this would come from API
    mock_data = {
        "account_type": ["Assets", "Liabilities", "Equity", "Revenue", "Expenses", "Accounts Payable", "Accounts Receivable"],
        "fiscal_period": ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"],
        "department": ["HR", "Finance", "IT", "Marketing", "Operations", "Legal"],
        "fund_type": ["General Fund", "Special Revenue", "Capital Projects", "Debt Service"],
        "segment_0_cat_1": ["General Fund", "Special Revenue", "Capital Projects", "Debt Service"],
        "cost_center": ["CC001", "CC002", "CC003", "CC004", "CC005"],
        "project": ["Project A", "Project B", "Project C", "Project D"]
    }
    
    # Return mock values or empty list if filter not found
    return mock_data.get(filter_name.lower(), mock_data.get(filter_name, []))

# Export simplified tools
SIMPLIFIED_TOOLS = [get_filter_values_tool]
