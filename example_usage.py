#!/usr/bin/env python3
"""Example usage of the Natural Language Filter Agent API."""

import asyncio
import json
from typing import List, Dict, Any

# For demonstration, we'll create a mock request
class MockFilterRequest:
    def __init__(self, query: str, available_filters: List[Dict]):
        self.query = query
        self.available_filters = [type('Filter', (), f)() for f in available_filters]
        self.conversation_id = None
        self.context = None

async def demo_filter_agent():
    """Demonstrate the Natural Language Filter Agent."""
    print("🚀 Natural Language Filter Agent Demo")
    print("=" * 50)
    
    # Example available filters
    available_filters = [
        {"name": "account_type", "label": "Account Type", "type": "lens"},
        {"name": "fiscal_period", "label": "Fiscal Period", "type": "lens"},
        {"name": "department", "label": "Department", "type": "dimensions"},
        {"name": "amount", "label": "Amount", "type": "lens"},
    ]
    
    # Example queries to test
    test_queries = [
        "Show me accounts with type 'Accounts Payable'",
        "Filter by fiscal period 10 and department 'Sales'",
        "Find records where amount is greater than 1000",
        "Show governmental accounts for period 12",
    ]
    
    print("📋 Available Filters:")
    for filter_def in available_filters:
        print(f"  - {filter_def['label']} ({filter_def['name']}, {filter_def['type']})")
    
    print("\n🔍 Test Queries:")
    for i, query in enumerate(test_queries, 1):
        print(f"  {i}. {query}")
    
    print("\n" + "=" * 50)
    print("✅ Implementation Complete!")
    print("\nTo use the API:")
    print("1. Set your OPENAI_API_KEY environment variable")
    print("2. Run: python run.py")
    print("3. Visit: http://localhost:8000/docs")
    print("4. Test the /api/filters/natural-language endpoint")
    
    print("\n📖 Example API Request:")
    example_request = {
        "query": "Show me accounts with type 'Accounts Payable' for fiscal period 10",
        "available_filters": available_filters,
        "conversation_id": "conv_123",
        "context": {}
    }
    print(json.dumps(example_request, indent=2))
    
    print("\n🎯 Expected Response Types:")
    print("- SUCCESS: Returns structured filter objects")
    print("- CLARIFICATION: Requests user to choose from available values") 
    print("- ERROR: Provides error details and guidance")

if __name__ == "__main__":
    asyncio.run(demo_filter_agent())
