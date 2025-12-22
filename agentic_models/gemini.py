import os
import logging
from typing import List, Dict, Any
from google import genai
from google.genai import types
from google.genai.errors import APIError
from agentic_models.base import BaseLLMEngine

# Configuration moved to main_configs.py
from main_configs import GEMINI_MODEL_ID, GEMINI_API_KEY

logger = logging.getLogger(__name__)

class GeminiEngine(BaseLLMEngine):
    def __init__(self, model_name: str = GEMINI_MODEL_ID, api_key: str = GEMINI_API_KEY):
        if not model_name or not api_key:
            raise ValueError("Gemini API key or model name missing")
        
        self.model_name = model_name
        self.client = genai.Client(api_key=api_key)
        self._last_response = None  # Cache for extract_tool_calls

    def _convert_messages(self, messages: List[Dict[str, str]]):
        """
        Hardened conversion to handle NoneType content and tool responses.
        """
        contents = []
        for m in messages:
            role = "user" if m.get("role") in ["user", "system", "developer"] else "model"
            
            # FIX: Use .get() with a default empty string and handle None explicitly
            raw_content = m.get("content")
            text_content = (raw_content or "").strip() 
            
            # Handle Tool/Function Responses (Crucial for Gemini Function Calling)
            if m.get("role") == "tool":
                # Gemini requires a specific 'function_response' part
                contents.append(types.Content(
                    role="user", # Tool results are sent back as 'user' role in this SDK
                    parts=[types.Part.from_function_response(
                        name=m.get("name"),
                        response={"result": text_content or "success"}
                    )]
                ))
                continue

            # Skip empty messages that trigger the 'data' initialization error
            if not text_content:
                continue
                
            contents.append(types.Content(
                role=role, 
                parts=[types.Part.from_text(text=text_content)]
            ))
            
        # Ensure turn-taking: Gemini is strict about starting with a 'user' turn
        if contents and contents[0].role != "user":
            contents[0].role = "user"
            
        return contents
    

    def generate(self, messages: List[Dict[str, str]], tools: List[Any] | None = None) -> str:
        contents = self._convert_messages(messages)
        
        # Tools in google-genai can be a list of python functions or tool objects
        config = types.GenerateContentConfig(
            temperature=0.4,
            tools=tools if tools else None,
        )

        try:
            self._last_response = self.client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=config
            )
            
            # If the model called a tool, response.text might be empty/error
            # We return an empty string as text, knowing extract_tool_calls will find the data
            try:
                return (self._last_response.text or "").strip()
            except ValueError:
                return "" # Response only contains function calls

        except APIError as e:
            logger.error(f"Gemini API error: {e}")
            return ""
        except Exception:
            logger.exception("Gemini unexpected failure")
            return ""

    def extract_tool_calls(self, text: str = "") -> List[Dict[str, Any]]:
        """
        Natively extracts tool calls from the last Gemini response.
        This is 100% more accurate than regex parsing.
        """
        if not self._last_response or not self._last_response.candidates:
            return []

        calls = []
        # The new SDK provides a direct helper for function_calls
        # This handles parallel function calling automatically.
        for candidate in self._last_response.candidates:
            if candidate.content and candidate.content.parts:
                for part in candidate.content.parts:
                    if part.function_call:
                        fc = part.function_call
                        calls.append({
                            "name": fc.name,
                            "arguments": fc.args # Already a clean Python dict
                        })
        
        return calls