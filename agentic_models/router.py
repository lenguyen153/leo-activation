import json
from typing import Any, Dict, List, Optional

from agentic_models.function_gemma import FunctionGemmaEngine
from agentic_models.gemini import GeminiEngine

def build_messages(prompt):
    messages = [
        {
            "role": "system",
            "content": (
                "You are LEO, an expert CDP assistant. "
                "Your goal is to understand the user's intent and act using the available tools.\n"
                "\n"
                "### GUIDELINES:\n"
                "1. **Analyze First:** Always output a short 'Thought:' explaining your reasoning.\n"
                "2. **Stop & Act:** After your thought, if a tool is needed, trigger it immediately. Do not write 'Tool: ...' in text.\n"
                "3. **Parameter Mapping Rules:**\n"
                "   - 'Zalo' or 'Zalo OA' -> channel='zalo_oa'\n"
                "   - 'Facebook' -> channel='facebook_page'\n"
                "   - 'Push' -> channel='mobile_push'\n"
                "   - Segment names must be extracted exactly as written (including spaces).\n"
                "\n"
                "### EXAMPLES:\n"
                "User: 'Sync the VIP segment to Facebook Ads'\n"
                "Thought: The user wants to activate the 'VIP' segment. The channel 'Facebook Ads' maps to 'facebook_page'.\n"
                "\n"
                "User: 'Send thank you notification to segment \"Users with phone number to test\" via Zalo'\n"
                "Thought: Intent is activation. Segment is 'Users with phone number to test'. Channel 'Zalo' maps to 'zalo_oa'. Message content is implied as 'Thank you notification'.\n"
                "\n"
                "User: 'Is it raining in Hanoi?'\n"
                "Thought: User needs weather info for Hanoi. I will use the weather tool.\n"
            ),
        },
        {
            "role": "user",
            "content": prompt
        },
    ]
    return messages

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


    def handle_message(self, messages: List[Dict[str, Any]], tools: Optional[List[Any]] = None, tools_map: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        tools_map = tools_map or {}

        # 1. Intent detection via FunctionGemma
        # The model will output: "Thought: ... <start_function_call>..."
        raw_output = self.gemma.generate(messages, tools)
        
        # Parse the output: Split "Thought" from "Function Call" tags
        # (This is just for clean logging)
        thought_text = raw_output.split("<start_function_call>")[0].strip()
        print(f"Agent Thought: {thought_text}")

        # Extract tool calls from FunctionGemma's output
        tool_calls = self.gemma.extract_tool_calls(raw_output) or []
        
        debug_calls = []
        debug_results = []

        # 2. Case A: No tools -> semantic reply via Gemini
        # If Gemma didn't call a tool, we hand off to Gemini for a better conversational reply
        if not tool_calls:
            print("No tool calls detected, using Gemini for direct answer.")
            # We pass the thought as context to Gemini so it knows what happened
            if thought_text:
                messages.append({"role": "assistant", "content": thought_text})
            
            answer = self.gemini.generate(messages, tools)
            return {"answer": answer, "debug": {"calls": [], "data": []}}

        # 3. Case B: Execute Tools
        # Add the assistant's decision to history (CRITICAL for multi-turn)
        messages.append({
            "role": "assistant", 
            "content": raw_output # Contains both thought and function tokens
        })

        print(f"\n🛠️  TRIGGERED {len(tool_calls)} TOOL(S):")

        tool_outputs_for_llm = []
        final_summary_lines = []

        for call in tool_calls:
            name = call["name"]
            args = call.get("arguments", {})
            
            # --- PRINT DETAILED DEBUG INFO ---
            print(f"  [>] Calling: {name}")
            print(f"  [i] Args:    {json.dumps(args, indent=2)}")

            debug_calls.append({"name": name, "arguments": args})

            if name not in tools_map:
                result = {"error": f"Tool '{name}' not registered"}
                print(f"  [X] Error: Tool not found")
            else:
                try:
                    result = tools_map[name](**args)
                    print(f"  [✓] Success. Result: {str(result)[:100]}...") # Print first 100 chars
                except Exception as exc:
                    result = {"error": str(exc)}
                    print(f"  [!] Exception: {exc}")

            debug_results.append({"name": name, "response": result})

            # Format specifically for FunctionGemma/Gemini tool role
            tool_outputs_for_llm.append({
                "role": "tool",
                "name": name,
                "content": json.dumps(result, default=str),
            })

            status = "Success" if "error" not in result else "Failed"
            final_summary_lines.append(f"- Action: {name}\n  Status: {status}\n  Output: {result}")

        messages.extend(tool_outputs_for_llm)

        # 4. Final synthesis
        # We ask Gemini to summarize the result because it writes better English/Vietnamese than Gemma 2b
        # final_answer = (self.gemini.generate(messages, tools) or "").strip()

        print("\n✅ Execution Complete. Skipping final LLM synthesis.")
        final_answer = "### Tool Execution Report\n" + "\n".join(final_summary_lines)

        return {
            "answer": final_answer,
            "debug": {"calls": debug_calls, "data": debug_results},
        }