import logging
import re
import json
import hashlib
import os
from typing import List, Dict, Any, Optional

import redis
from google import genai
from google.genai import types
from google.genai.errors import APIError

from main_configs import GEMINI_MODEL_ID, GEMINI_API_KEY

logger = logging.getLogger(__name__)

# Cache Expiration in seconds (e.g., 1 hour). Adjust as needed.
CACHE_TTL = 3600 

class GeminiEngine:
    def __init__(
        self,
        model_name: str = GEMINI_MODEL_ID,
        api_key: str = GEMINI_API_KEY,
    ):
        if not model_name or not api_key:
            raise ValueError("Gemini API key or model name missing")

        self.model_name = model_name
        self.client = genai.Client(api_key=api_key)
        
        # State to hold the last live API response
        self._last_response = None
        # State to hold cached tool calls (if we hit Redis)
        self._cached_tool_calls: List[Dict] = []

        # Initialize Redis
        redis_url = os.getenv("REDIS_URL")
        self.redis_client = None
        if redis_url:
            try:
                self.redis_client = redis.from_url(redis_url)
                # Test connection lightly
                self.redis_client.ping()
            except Exception as e:
                logger.warning(f"Redis connection failed. Caching disabled. Error: {e}")

    # ============================================================
    # Caching Helpers
    # ============================================================
    def _generate_cache_key(self, messages: List[Dict], tools: Optional[List]) -> str:
        """
        Generates a deterministic SHA256 hash based on inputs.
        """
        # specialized serializer for tools (which might be functions)
        def default_serializer(obj):
            if hasattr(obj, '__name__'):
                return f"func:{obj.__name__}"
            return str(obj)

        # Create a unique signature structure
        payload = {
            "model": self.model_name,
            "messages": messages,
            "tools": tools
        }
        
        # Dump to JSON string with sorted keys for consistency
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
            data = {
                "text": text,
                "tool_calls": tool_calls
            }
            self.redis_client.setex(key, CACHE_TTL, json.dumps(data))
        except Exception as e:
            logger.error(f"Redis write error: {e}")

    # ============================================================
    # Internal Logic (Parsing)
    # ============================================================
    def _parse_custom_tool_call(self, text_content: str) -> Optional[types.Part]:
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
                    pass # Fallback if parsing fails
            
            return types.Part.from_function_call(name=fn_name, args=args_dict)
        return None

    def _convert_messages(self, messages: List[Dict[str, Any]]) -> tuple[List[types.Content], Optional[str]]:
        contents: List[types.Content] = []
        system_parts: List[str] = []

        for m in messages:
            role = m.get("role")
            content_str = (m.get("content") or "").strip()

            if role == "system":
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

        return contents, ("\n\n".join(system_parts) if system_parts else None)

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
            logger.info("⚡ Gemini Cache Hit")
            # Restore state so extract_tool_calls works
            self._last_response = None 
            self._cached_tool_calls = cached_result.get("tool_calls", [])
            return cached_result.get("text", "")

        # 2. Prepare API Call
        print("\n--- Gemini Generation Call (Live) ---")
        self._cached_tool_calls = [] # Reset cache state
        
        contents, system_instruction = self._convert_messages(messages)
        config = types.GenerateContentConfig(
            temperature=0.4,
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

            # 4. Extract Results
            text_result = ""
            current_tool_calls = []

            # Handle candidates
            if self._last_response.candidates:
                # Try to get text
                try:
                    text_result = (self._last_response.text or "").strip()
                except ValueError:
                    text_result = "" # No text, purely function call
                
                # Extract tool calls (for caching purposes)
                current_tool_calls = self._extract_tool_calls_from_response(self._last_response)

            # 5. Save to Cache
            self._save_to_cache(cache_key, text_result, current_tool_calls)

            return text_result

        except APIError as e:
            logger.error("Gemini API error: %s", e)
            return ""
        except Exception:
            logger.exception("Gemini unexpected failure")
            return ""

    # ============================================================
    # Tool Extraction
    # ============================================================
    def _extract_tool_calls_from_response(self, response) -> List[Dict[str, Any]]:
        """Helper to parse a raw Gemini response object."""
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
        """
        Public method to get tool calls.
        Works for both Live responses and Cached responses.
        """
        # If we have a cached result, use it
        if self._cached_tool_calls:
            return self._cached_tool_calls
            
        # If we have a live response object, parse it
        if self._last_response:
            return self._extract_tool_calls_from_response(self._last_response)
            
        return []