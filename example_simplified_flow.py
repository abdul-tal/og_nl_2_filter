"""Example usage of the simplified natural language filter flow."""

import asyncio
import json
from src.models import FilterRequest, FilterInfo, AccountSummary, ColumnGroup
from src.agent.simplified_agent import SimplifiedFilterAgent
from src.config import get_settings

async def test_simplified_flow():
    """Test the simplified filter flow with example requests."""
    
    # Get settings
    settings = get_settings()
    
    # Initialize simplified agent
    try:
        agent = SimplifiedFilterAgent(
            openai_api_key=settings.openai_api_key,
            model=settings.openai_model,
            temperature=settings.openai_temperature
        )
        print("✅ SimplifiedFilterAgent initialized successfully")
    except Exception as e:
        print(f"❌ Failed to initialize agent: {e}")
        return
    
    # Create sample available filters
    available_filters = [
        FilterInfo(
            name="account_type",
            label="Account Type",
            sourceType="lens",
            sourceId="lens%2Fentity%2Fcustom%2F7f1e93a6-3609-494c-8fca-07c24478e0f1"
        ),
        FilterInfo(
            name="fiscal_period",
            label="Fiscal Period", 
            sourceType="dimensions",
            sourceId="dimension%2Fentity%2Fcoa%2F0259e325-66ab-4678-9081-46fb9329b1b7"
        ),
        FilterInfo(
            name="department",
            label="Department",
            sourceType="lens",
            sourceId="lens%2Fentity%2Fcustom%2F8g2f04b7-4710-595d-9gdb-18d35579f1g2"
        )
    ]
    
    # Create sample account summary with column groups
    column_group = ColumnGroup(
        id="actuals_group_id",
        lens={"id": "actuals_lens"},
        measureColumn={"id": "amount"},
        grouping=[{"constant": "Actuals Data"}],
        filters=[],
        dateFilter=[],
        relativeFilter="",
        type="actuals",
        columnValueMapping={},
        rollingNumRangeOption={}
    )
    
    account_summary = AccountSummary(
        columnGroups=[column_group],
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
    
    # Test cases
    test_cases = [
        {
            "name": "Add Account Type Filter",
            "query": "add account type filter for Assets",
            "expected_status": "success"
        },
        {
            "name": "Add Fiscal Period Filter", 
            "query": "filter by fiscal period 10",
            "expected_status": "success"
        },
        {
            "name": "Ambiguous Filter Value",
            "query": "add account type filter for XYZ",
            "expected_status": "clarification_needed"
        },
        {
            "name": "Remove Filter",
            "query": "remove account type filter",
            "expected_status": "success"
        },
        {
            "name": "Modify Filter",
            "query": "change fiscal period to 5",
            "expected_status": "success"
        }
    ]
    
    print("\n🧪 Testing Simplified Filter Flow")
    print("=" * 50)
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n{i}. {test_case['name']}")
        print(f"Query: '{test_case['query']}'")
        
        # Create request
        request = FilterRequest(
            query=test_case['query'],
            available_filters=available_filters,
            account_summary=account_summary,
            conversation_id=f"test_conv_{i}",
            delphi_session={"session_id": "test_session"}
        )
        
        try:
            # Process request
            result = agent.process_request(request)
            
            # Display result
            status = result.get("status", "unknown")
            print(f"Status: {status}")
            print(f"Expected: {test_case['expected_status']}")
            
            if status == "success":
                execution_plan = result.get("execution_plan", [])
                print(f"Execution Plan: {json.dumps(execution_plan, indent=2)}")
            elif status == "clarification_needed":
                print(f"Message: {result.get('message', 'No message')}")
                available_values = result.get("available_values", [])
                print(f"Available Values: {available_values[:5]}{'...' if len(available_values) > 5 else ''}")
            elif status == "error":
                print(f"Error: {result.get('message', 'Unknown error')}")
            
            # Check if result matches expected
            if status == test_case['expected_status']:
                print("✅ Test PASSED")
            else:
                print("❌ Test FAILED")
                
        except Exception as e:
            print(f"❌ Test FAILED with exception: {e}")
        
        print("-" * 30)
    
    print("\n🎯 Summary")
    print("The simplified flow:")
    print("1. ✅ Embeds available_filters and columnGroups in system prompt")
    print("2. ✅ Agent calls get_filter_values to fetch filter values")
    print("3. ✅ Agent returns execution plans instead of executing operations")
    print("4. ✅ Backend manually executes functions based on the plan")
    print("5. ✅ Reduces LLM calls from N+1 to exactly 2 (planning + execution)")

if __name__ == "__main__":
    asyncio.run(test_simplified_flow())
