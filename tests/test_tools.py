import requests
import json
from typing import Dict, Any

# Configuration
API_URL = "http://localhost:8000/tool_calling"

# Define test cases for each tool
# format: "tool_name": {"arg_name": "value", ...}
TEST_CASES: Dict[str, Dict[str, Any]] = {
    "get_date": {},  # No args usually required
    
    "get_current_weather": {
        "location": "Ho Chi Minh City, Vietnam"
    },
    
    "get_current_marketing_event": {
        # Assuming similar args to weather or simple query
        "location": "Hanoi" 
    },
    
    "manage_cdp_segment": {
        "action": "create",
        "segment_name": "Test Segment Alpha",
        "criteria": {"age_min": 25, "active_last_7_days": True}
    },
    
    "analyze_segment": {
        "segment_identifier": "VIP Customers"
    },
    
    "show_all_segments": {
        "limit": 5  # Assuming it might take a limit, or empty dict if none
    },
    
    "activate_channel": {
        "segment_name": "New Users",
        "channel": "zalo_oa",
        "message_template": "welcome_promo_2025"
    }
}

def run_tests():
    print(f"🚀 Starting Tool Tests against {API_URL}...\n")
    
    success_count = 0
    fail_count = 0

    for tool_name, args in TEST_CASES.items():
        payload = {
            "tool_name": tool_name,
            "tool_args": args
        }
        
        print(f"Testing: {tool_name}...")
        print(f"  Input: {json.dumps(args)}")

        try:
            response = requests.post(API_URL, json=payload, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                print(f"  ✅ Status: 200 OK")
                
                # Print a snippet of the 'answer' to verify LLM synthesis
                answer_snippet = data.get('answer', '')[:100].replace('\n', ' ')
                print(f"  📝 Answer: {answer_snippet}...")
                
                # Check actual tool execution status in debug
                debug_calls = data.get('debug', {}).get('calls', [])
                if debug_calls:
                    print(f"  🛠️  Tool executed: {debug_calls[0]['name']}")
                else:
                    print(f"  ⚠️  Warning: No tool execution recorded in debug info.")
                
                success_count += 1
            else:
                print(f"  ❌ Failed: Status {response.status_code}")
                print(f"  Error: {response.text}")
                fail_count += 1

        except requests.exceptions.ConnectionError:
            print("  ❌ Connection Error: Is the server running on port 8000?")
            fail_count += 1
            break
        except Exception as e:
            print(f"  ❌ Exception: {str(e)}")
            fail_count += 1
        
        print("-" * 50)

    print(f"\n📊 Test Summary: {success_count} Passed | {fail_count} Failed")

if __name__ == "__main__":
    run_tests()