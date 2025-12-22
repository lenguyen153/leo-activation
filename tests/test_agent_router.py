import os
import sys
import json
import types

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agentic_models.router import AgentRouter


class DummyGemma:
    def __init__(self):
        self._generated = ""

    def generate(self, messages, tools=None):
        # Return a fake function call string when the prompt asks for weather
        if any("weather" in (m.get("content") or "").lower() or "ho chi minh" in (m.get("content") or "").lower() for m in messages):
            # produce the FunctionGemma-like tag for get_current_weather
            return "<start_function_call>call:get_current_weather{location:<escape>Ho Chi Minh City<escape>,unit:<escape>celsius<escape>}<end_function_call>"
        return ""

    def extract_tool_calls(self, text: str):
        if not text or "<start_function_call>" not in text:
            return []
        # mimic a single get_current_weather call when function tags are present
        return [{"name": "get_current_weather", "arguments": {"location": "Ho Chi Minh City", "unit": "celsius"}}]


class DummyGemini:
    def __init__(self):
        self.last_messages = None

    def generate(self, messages, tools=None):
        self.last_messages = messages
        return "Final synthesized reply"


def test_handle_message_executes_tools_and_synthesizes(monkeypatch):
    router = AgentRouter(mode="auto")

    # Patch in dummy engines
    router.gemma = DummyGemma()
    router.gemini = DummyGemini()

    # Tools map with a simple callable for weather
    def fake_get_current_weather(location, unit="celsius"):
        return {"status": "success", "location": location, "weather": {"temperature": 30}}

    tools_map = {"get_current_weather": fake_get_current_weather}

    messages = [
        {
            "role": "system",
            "content": (
                "You are LEO, a smart model that can do function calling with tools."
                "Use tools immediately when applicable. "
                "Do not ask for confirmation if parameters are clear. "
                "Explain errors plainly."
            ),
        },
        {"role": "user", "content": "What is the weather in Ho Chi Minh City today?"},
    ]

    res = router.handle_message(messages, tools=[], tools_map=tools_map)

    # Expect an answer and non-empty debug information
    assert len(res["answer"]) > 0
    assert res["debug"]["calls"]
    assert res["debug"]["data"]
    assert res["debug"]["data"][0]["response"]["status"] == "success"


def test_handle_message_no_tools_calls_gemini(monkeypatch):
    router = AgentRouter(mode="auto")
    router.gemma = DummyGemma()
    router.gemini = DummyGemini()

    messages = [
        {"role": "system", "content": "You are LEO"},
        {"role": "user", "content": "Give me a summary"},
    ]

    res = router.handle_message(messages, tools=[], tools_map={})
    assert res["answer"] == "Final synthesized reply"
    assert res["debug"]["calls"] == []


def test_gemini_returns_empty_fallback(monkeypatch):
    router = AgentRouter(mode="auto")

    # Gemma will be used both for detection and as a fallback synthesis
    class GemmaForTest(DummyGemma):
        def generate(self, messages, tools=None):
            # First call (intent detection) returns the function call tag
            if any("weather" in (m.get("content") or "").lower() for m in messages):
                return "<start_function_call>call:get_current_weather{location:<escape>Ho Chi Minh City<escape>,unit:<escape>celsius<escape>}<end_function_call>"
            # For fallback synthesis return a simple text
            return "Fallback synthesized answer from Gemma"

    class EmptyGemini(DummyGemini):
        def generate(self, messages, tools=None):
            return ""  # Simulate empty Gemini response

    router.gemma = GemmaForTest()
    router.gemini = EmptyGemini()

    def fake_get_current_weather(location, unit="celsius"):
        return {"status": "success", "location": location, "weather": {"temperature": 30}}

    tools_map = {"get_current_weather": fake_get_current_weather}

    messages = [
        {"role": "system", "content": "You are LEO"},
        {"role": "user", "content": "What is the weather in Ho Chi Minh City today?"},
    ]

    res = router.handle_message(messages, tools=[], tools_map=tools_map)

    # When Gemini returns empty, AgentRouter should provide a non-empty answer (fallback)
    print(res)
    assert len(res["answer"]) > 0
    assert res["debug"]["calls"]
    assert res["debug"]["data"][0]["response"]["status"] == "success"
