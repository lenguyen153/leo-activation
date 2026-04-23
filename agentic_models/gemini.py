import logging
import re
import json
import hashlib
import os
from typing import List, Dict, Any, Optional

import redis

try:
    from google import genai
    from google.genai import types
    from google.genai.errors import APIError
    _GEMINI_AVAILABLE = True
except ImportError:
    _GEMINI_AVAILABLE = False

from main_configs import GEMINI_MODEL_ID, GEMINI_API_KEY, REDIS_URL

logger = logging.getLogger(__name__)

CACHE_TTL = 3600

# ============================================================
# NEW: Enhanced System Instruction for Insights & Natural Language
# ============================================================
DEFAULT_SYSTEM_INSTRUCTION = """
You are LEO, an expert Customer Data Platform (CDP) Analyst.

### YOUR GOAL:
Provide natural, human-readable responses rich with actionable insights. Never just dump raw JSON or data.

### RULES FOR HANDLING TOOL RESULTS:
1. **Analyze, Don't Just Report:** When a tool returns data, you must interpret it.
   - *Bad:* "The user count is 5,000."
   - *Good:* "We found 5,000 active users in this segment, which represents a significant audience for your next campaign."
2. **Provide Context:** Explain *why* the data matters or what the user should do next.
3. **Format for Clarity:** Use Markdown (bullet points, **bold text**) to make the insights scannable and easy to read.
4. **Natural Tone:** Speak professionally but conversationally. Avoid robotic phrases like "Here is the output."

### FALLBACK:
If a tool returns empty data or an error, explain what happened in plain English and suggest a specific next step to fix it.
"""

class GeminiEngine:
    def __init__(
        self,
        model_name: str = GEMINI_MODEL_ID,
        api_key: str = GEMINI_API_KEY,
    ):
        if not _GEMINI_AVAILABLE:
            raise RuntimeError("google-genai is not installed. AI features are disabled.")
        if not model_name or not api_key:
            raise ValueError("Gemini API key or model name missing")

        self.model_name = model_name
        self.client = genai.Client(api_key=api_key)
        
        self._last_response = None
        self._cached_tool_calls: List[Dict] = []

        # Initialize Redis
        self.redis_client = None
        try:
            # Safely handle potential None/Empty REDIS_URL
            if REDIS_URL:
                self.redis_client = redis.from_url(REDIS_URL)
                self.redis_client.ping()
            else:
                logger.warning("REDIS_URL is not set. Caching is disabled.")
        except Exception as e:
            logger.warning(f"Redis connection failed. Caching disabled. Error: {e}")

    # ============================================================
    # Caching Helpers
    # ============================================================
    def _generate_cache_key(self, messages: List[Dict], tools: Optional[List]) -> str:
        def default_serializer(obj):
            if hasattr(obj, '__name__'):
                return f"func:{obj.__name__}"
            return str(obj)

        payload = {
            "model": self.model_name,
            "messages": messages,
            "tools": tools
        }
        # Sort keys to ensure consistent hashing
        payload_str = json.dumps(payload, sort_keys=True, default=default_serializer)
        return hashlib.sha256(payload_str.encode("utf-8")).hexdigest()

    def _get_from_cache(self, key: str) -> Optional[Dict]:
        if not self.redis_client:
            return None
        try:
            cached_data = self.redis_client.get(key)
            if cached_data:
                return json.loads(cached_data)
        except Exception as e:
            logger.error(f"Redis read error: {e}")
        return None

    def _save_to_cache(self, key: str, text: str, tool_calls: List[Dict]):
        if not self.redis_client:
            return
        try:
            # We cache both text and tool calls to restore complete state
            data = {
                "text": text,
                "tool_calls": tool_calls
            }
            self.redis_client.setex(key, CACHE_TTL, json.dumps(data))
        except Exception as e:
            logger.error(f"Redis write error: {e}")

    # ============================================================
    # Parsing & Conversion
    # ============================================================
    def _parse_custom_tool_call(self, text_content: str) -> Optional[Any]:
        """Parses your custom <start_function_call> string format."""
        pattern = r"<start_function_call>call:(?P<name>[\w_]+)\{(?P<args>.*)\}<end_function_call>"
        match = re.search(pattern, text_content)
        
        if match:
            fn_name = match.group("name")
            raw_args = match.group("args")
            args_dict = {}
            if ":" in raw_args:
                try:
                    key, val = raw_args.split(":", 1)
                    val = val.replace("<escape>", "").strip()
                    args_dict = {key.strip(): val}
                except Exception:
                    pass 
            
            return types.Part.from_function_call(name=fn_name, args=args_dict)
        return None

    def _convert_messages(self, messages: List[Dict[str, Any]]) -> tuple[List[Any], Optional[str]]:
        contents: List[types.Content] = []
        
        # Start with the DEFAULT instruction to ensure insights/persona
        system_parts: List[str] = [DEFAULT_SYSTEM_INSTRUCTION]

        for m in messages:
            role = m.get("role")
            content_str = (m.get("content") or "").strip()

            if role == "system":
                # Append user-specific system prompts (e.g., current date, specific task)
                system_parts.append(content_str)
                continue

            if role == "tool":
                contents.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_function_response(
                                name=m.get("name", "tool"),
                                response={"result": content_str or "success"},
                            )
                        ]
                    )
                )
                continue

            if role == "assistant":
                tool_call_part = self._parse_custom_tool_call(content_str)
                if tool_call_part:
                    contents.append(types.Content(role="model", parts=[tool_call_part]))
                elif content_str:
                    contents.append(types.Content(role="model", parts=[types.Part.from_text(text=content_str)]))
                continue

            if content_str:
                contents.append(types.Content(role="user", parts=[types.Part.from_text(text=content_str)]))

        # Join all system parts into one comprehensive instruction block
        full_system_instruction = "\n\n".join(system_parts) if system_parts else None
        
        return contents, full_system_instruction

    # ============================================================
    # Main Generation
    # ============================================================
    def generate(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Any]] = None,
    ) -> str:
        
        # 1. Check Cache
        cache_key = self._generate_cache_key(messages, tools)
        cached_result = self._get_from_cache(cache_key)

        if cached_result:
            logger.info("⚡ Gemini Cache Hit ✅")
            self._last_response = None 
            self._cached_tool_calls = cached_result.get("tool_calls", [])
            return cached_result.get("text", "")

        # 2. Prepare Live Call
        print("\n--- ✅ Gemini Generation Call (Live) ---")
        self._cached_tool_calls = [] 
        
        contents, system_instruction = self._convert_messages(messages)
        
        config = types.GenerateContentConfig(
            temperature=0.4, # Keep low for accuracy, System Instruction adds the "flair"
            tools=tools or None,
            system_instruction=system_instruction
        )

        try:
            # 3. Call API
            self._last_response = self.client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=config,
            )

            # 4. Extract Results (Text AND Tools)
            text_result = ""
            current_tool_calls = []

            if self._last_response.candidates:
                # Extract text if it exists (even if there are tool calls)
                try:
                    text_result = (self._last_response.text or "").strip()
                except ValueError:
                    # API raises ValueError if accessing .text on a pure function-call response
                    text_result = "" 
                
                # Extract tools
                current_tool_calls = self._extract_tool_calls_from_response(self._last_response)

            # 5. Save to Cache
            # Only cache if we got a valid response (text or tools)
            if text_result or current_tool_calls:
                self._save_to_cache(cache_key, text_result, current_tool_calls)

            return text_result

        except APIError as e:
            logger.error("Gemini API error: %s", e)
            return f"Error connecting to AI service: {e}"
        except Exception:
            logger.exception("Gemini unexpected failure")
            return "An unexpected error occurred."

    # ============================================================
    # Tool Extraction
    # ============================================================
    def _extract_tool_calls_from_response(self, response) -> List[Dict[str, Any]]:
        calls = []
        if not response or not response.candidates:
            return calls

        for candidate in response.candidates:
            if not candidate.content or not candidate.content.parts:
                continue
            for part in candidate.content.parts:
                if part.function_call:
                    calls.append({
                        "name": part.function_call.name,
                        "arguments": part.function_call.args
                    })
        return calls

    def extract_tool_calls(self, text: str = "") -> List[Dict[str, Any]]:
        if self._cached_tool_calls:
            return self._cached_tool_calls
            
        if self._last_response:
            return self._extract_tool_calls_from_response(self._last_response)
            
        return []