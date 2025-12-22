


import json
from typing import Any, Dict, List, Optional

from agentic_models.function_gemma import FunctionGemmaEngine
from agentic_models.gemini import GeminiEngine


class AgentRouter:
    """High-level agent that orchestrates tool intent detection, execution, and synthesis.

    Methods
    -------
    handle_message(messages, tools, tools_map)
        Run the full pipeline and return {'answer': str, 'debug': {'calls': [...], 'data': [...]}}
    """

    def __init__(self, mode: str = "auto"):
        self.mode = mode
        self.gemma = FunctionGemmaEngine()
        self.gemini = GeminiEngine()

    def generate(self, messages: List[Dict[str, Any]], tools: Optional[List[Any]] = None) -> str:
        """Compatibility wrapper: select appropriate model based on mode and tools."""
        if self.mode == "gemma":
            return self.gemma.generate(messages, tools)
        if self.mode == "gemini":
            return self.gemini.generate(messages, tools)
        # AUTO
        if tools:
            return self.gemma.generate(messages, tools)
        return self.gemini.generate(messages, tools)

    def extract_tool_calls(self, raw_output: str) -> List[Dict[str, Any]]:
        """Attempt to extract tool calls using FunctionGemma first, then fallback to Gemini extractor."""
        try:
            if isinstance(raw_output, str) and "<start_function_call>" in raw_output:
                return self.gemma.extract_tool_calls(raw_output)
        except Exception:
            pass

        # Fallback to gemini's last-response extraction
        try:
            return self.gemini.extract_tool_calls(raw_output)
        except Exception:
            return []

    def handle_message(self, messages: List[Dict[str, Any]], tools: Optional[List[Any]] = None, tools_map: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Run the full agent pipeline:

        1. Use FunctionGemma to generate intent + tool calls
        2. If no tool calls: ask Gemini for a semantic reply
        3. If tool calls: execute tools (from `tools_map`) and append results to messages
        4. Ask Gemini to synthesize final answer from augmented messages

        Returns a dict: { 'answer': str, 'debug': { 'calls': [ ... ], 'data': [ ... ] } }
        """
        tools_map = tools_map or {}

        # 1. Intent detection via FunctionGemma
        raw_output = self.gemma.generate(messages, tools)
        tool_calls = self.gemma.extract_tool_calls(raw_output) or []

        debug_calls = []
        debug_results = []

        # 2. No tools -> semantic reply via Gemini
        if not tool_calls:
            answer = self.gemini.generate(messages, tools)
            return {"answer": answer, "debug": {"calls": [], "data": []}}

        # 3. Execute tools
        messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{"type": "function", "function": call} for call in tool_calls],
        })

        tool_outputs_for_llm = []

        for call in tool_calls:
            name = call["name"]
            args = call.get("arguments", {})

            debug_calls.append({"name": name, "arguments": args})

            if name not in tools_map:
                result = {"error": f"Tool '{name}' not registered"}
            else:
                try:
                    result = tools_map[name](**args)
                except Exception as exc:  # pylint: disable=broad-except
                    result = {"error": str(exc)}

            debug_results.append({"name": name, "response": result})

            tool_outputs_for_llm.append({
                "role": "tool",
                "name": name,
                "content": json.dumps(result, default=str),
            })

        messages.extend(tool_outputs_for_llm)

        # 4. Final synthesis (prefer Gemini)
        final_answer = (self.gemini.generate(messages, tools) or "").strip()

        # Fallback: if Gemini returns empty, try Gemma or synthesize a summary from tool outputs
        if not final_answer:
            try:
                fallback = (self.gemma.generate(messages, tools) or "").strip()
                if fallback:
                    final_answer = fallback
                else:
                    # Synthesize a short summary from executed tools
                    summaries = []
                    for r in debug_results:
                        name = r.get("name")
                        resp = r.get("response")
                        summaries.append(f"{name}: {resp}")
                    final_answer = "Executed tools: " + "; ".join(summaries) if summaries else "No answer could be synthesized."
            except Exception:
                final_answer = "No answer could be synthesized."

        return {
            "answer": final_answer,
            "debug": {"calls": debug_calls, "data": debug_results},
        }