To help you test your **LEO CDP AI Assistant**, I have organized sample data into three categories: **API Request Payloads** (to send to your FastAPI endpoint), **Mock Customer Profiles** (to simulate the LEO CDP database), and **Existing Segments**.

### 1. API Request Samples (`POST /chat`)

These are JSON payloads you can send to `http://localhost:8000/chat` using Postman, cURL, or Python's `requests` library.

| Use Case | Sample JSON Payload |
| --- | --- |
| **Basic Weather** | `{"prompt": "What is the weather like in Saigon right now?"}` |
| **Segment Creation** | `{"prompt": "Create a new segment for High-Value customers who live in Hanoi."}` |
| **Multi-channel Activation** | `{"prompt": "Send a Zalo message to the 'New Leads' segment with the text 'Welcome to our store!' and also send an email to them."}` |
| **Weather-based Logic** | `{"prompt": "Check the weather in Tokyo. If it is cold, I want to create a segment called 'Winter Shoppers'."}` |
| **Date & Activity** | `{"prompt": "What is today's date? Then delete the segment named 'Expired Leads'."}` |

---

### 2. Mock LEO CDP Customer Profiles (`customers.json`)

You can use this data to mock the "Developer's Turn" execution if you decide to add a tool that searches for specific users.

```json
[
  {
    "id": "user_001",
    "email": "nguyen.van@example.vn",
    "full_name": "Nguyen Van A",
    "location": "Ho Chi Minh City",
    "total_spend": 1250.50,
    "last_login": "2025-12-15",
    "loyalty_tier": "Gold",
    "zalo_id": "zalo_abc_123"
  },
  {
    "id": "user_002",
    "email": "le.thi@example.com",
    "full_name": "Le Thi B",
    "location": "Hanoi",
    "total_spend": 45.00,
    "last_login": "2025-11-20",
    "loyalty_tier": "Silver",
    "zalo_id": "zalo_def_456"
  },
  {
    "id": "user_003",
    "email": "tanaka.h@example.jp",
    "full_name": "Hiroshi Tanaka",
    "location": "Tokyo",
    "total_spend": 3200.00,
    "last_login": "2025-12-20",
    "loyalty_tier": "Platinum",
    "zalo_id": null
  }
]

```

---

### 3. Mock LEO CDP Segments (`segments.csv`)

If you want to test the `manage_leo_segment` or `activate_channel` tools, here is a list of segments that you can assume "already exist" in your system.

| Segment Name | Description | Member Count | Primary Channel |
| --- | --- | --- | --- |
| `VIP-Members` | Users with >$1000 spend | 450 | Email |
| `New-Leads` | Signed up in last 7 days | 1,200 | Zalo |
| `Cart-Abandoners` | Items in cart for >24h | 89 | Web Push |
| `Hanoi-Local` | Users located in Hanoi | 3,400 | Mobile Push |

### 4. Integration Test Script (Python)

You can run this simple script to test your running FastAPI server with multiple scenarios:

```python
import requests

URL = "http://localhost:8000/chat"

test_prompts = [
    "What time is it and what is the weather in Tokyo?",
    "I need to create a segment for 'Zalo Active Users' and send them a Zalo message saying 'Hello!'",
    "Send an email to the 'VIP-Members' segment about the upcoming winter sale."
]

for prompt in test_prompts:
    print(f"\n--- Testing Prompt: {prompt} ---")
    response = requests.post(URL, json={"prompt": prompt})
    if response.status_code == 200:
        data = response.json()
        print(f"Assistant: {data['answer']}")
        print(f"Debug Info: {data['debug']}")
    else:
        print(f"Error: {response.text}")

```

This data will allow you to verify that **FunctionGemma** is correctly mapping the `prompt` to the OOP-based `activate_channel` logic you built for the LEO CDP framework.