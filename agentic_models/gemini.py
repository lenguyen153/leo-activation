import logging
from typing import List, Dict, Any, Optional

from google import genai
from google.genai import types
from google.genai.errors import APIError

from agentic_models.base import BaseLLMEngine
from main_configs import GEMINI_MODEL_ID, GEMINI_API_KEY

logger = logging.getLogger(__name__)


class GeminiEngine(BaseLLMEngine):
    def __init__(
        self,
        model_name: str = GEMINI_MODEL_ID,
        api_key: str = GEMINI_API_KEY,
    ):
        if not model_name or not api_key:
            raise ValueError("Gemini API key or model name missing")

        self.model_name = model_name
        self.client = genai.Client(api_key=api_key)
        self._last_response = None

    # ============================================================
    # Internal helpers
    # ============================================================
    def _convert_messages(
        self,
        messages: List[Dict[str, Any]],
    ) -> List[types.Content]:
        """
        Convert OpenAI-style messages to Gemini contents.
        Hardened for:
        - None content
        - tool responses
        - Gemini strict turn-taking
        """
        contents: List[types.Content] = []

        for m in messages:
            role = m.get("role")

            # Gemini only understands user / model
            gemini_role = "user" if role != "assistant" else "model"

            raw_content = m.get("content")
            text_content = (raw_content or "").strip()

            # ----------------------------------------------------
            # Tool / function response
            # ----------------------------------------------------
            if role == "tool":
                contents.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_function_response(
                                name=m.get("name", "tool"),
                                response={
                                    "result": text_content or "success"
                                },
                            )
                        ],
                    )
                )
                continue

            # Skip empty messages (prevents Gemini init error)
            if not text_content:
                continue

            contents.append(
                types.Content(
                    role=gemini_role,
                    parts=[types.Part.from_text(text=text_content)],
                )
            )

        # Gemini requires first turn to be user
        if contents and contents[0].role != "user":
            contents[0].role = "user"

        return contents

    # ============================================================
    # Main generation
    # ============================================================
    def generate(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Any]] = None,
    ) -> str:
        contents = self._convert_messages(messages)

        config = types.GenerateContentConfig(
            temperature=0.4,
            tools=tools or None,
        )

        try:
            self._last_response = self.client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=config,
            )

            # text may be empty when only tool calls exist
            try:
                return (self._last_response.text or "").strip()
            except ValueError:
                return ""

        except APIError as e:
            logger.error("Gemini API error: %s", e)
            return ""
        except Exception:
            logger.exception("Gemini unexpected failure")
            return ""

    # ============================================================
    # Tool call extraction (native, no regex)
    # ============================================================
    def extract_tool_calls(
        self,
        text: str = "",
    ) -> List[Dict[str, Any]]:
        """
        Extract tool calls from the last Gemini response.
        Supports parallel function calling.
        """
        if not self._last_response or not self._last_response.candidates:
            return []

        calls: List[Dict[str, Any]] = []

        for candidate in self._last_response.candidates:
            content = candidate.content
            if not content or not content.parts:
                continue

            for part in content.parts:
                if part.function_call:
                    fc = part.function_call
                    calls.append(
                        {
                            "name": fc.name,
                            "arguments": fc.args or {},
                        }
                    )

        return calls
