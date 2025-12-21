import requests

URL = "http://localhost:8000/chat"

test_prompts = [
    "What time is it and what is the weather in Ho Chi Minh City?",
    "I need to create a segment for 'Zalo Active Users' and send them a Zalo message saying 'Hello!'",
    "Send an email to the 'VIP-Members' segment about the upcoming winter sale."
]

for prompt in test_prompts:
    print(f"\n--- Testing Prompt: {prompt} ---")
    response = requests.post(URL, json={"prompt": prompt})
    if response.status_code == 200:
        data = response.json()
        print(f"Assistant: {data['answer']}")
        print(f"Debug Info: {data.get('debug', 'No debug data available')}")
    else:
        print(f"Error: {response.text}")