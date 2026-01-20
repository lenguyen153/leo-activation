import json
import logging
from typing import Any, Dict, List, Optional

# Assuming these are your existing wrappers
from agentic_models.function_gemma import FunctionGemmaEngine
from agentic_models.gemini import GeminiEngine

# Configure Logging
logger = logging.getLogger("leo_router")
logger.setLevel(logging.INFO)

def build_system_prompt(model_type: str = "gemini") -> str:
    """
    Returns the appropriate system prompt based on the model.
    
    According to FunctionGemma docs:
    - Turn 1 must be a 'developer' role defining tools.
    - The specific trigger phrase "You are a model that can do function calling..." is required.
    """
    if model_type == "gemma":
        # STRICT FunctionGemma requirement:
        # We do not add the "LEO" persona here. Gemma's only job is to route.
        # The 'developer' role and tool definitions are handled by the FunctionGemmaEngine 
        # using the `tools` list provided at runtime.
        # This string acts as the "context" before tool definitions.
        return "You are a model that can do function calling with the following functions."
    
    else:
        # GEMINI / SYNTHESIS Prompt
        # This is where the LEO persona lives.
        return (
            "You are LEO, an expert CDP assistant. "
            "You have received the results of technical tool executions. "
            "Your goal is to synthesize these results into a helpful, natural language response "
            "for the user in their language (Vietnamese/English).\n"
            "\n"
            "### GUIDELINES:\n"
            "1. **Be Helpful:** Explain what action was taken clearly.\n"
            "2. **Tone:** Professional, concise, and empathetic.\n"
        )

class AgentRouter:
    """
    High-level agent orchestrator.
    
    Architecture:
    1. User Query -> FunctionGemma (Router) -> Generates <start_function_call>...
    2. Execute Tools -> Get Results
    3. Results + History -> Gemini (Synthesizer) -> Natural Language Answer
    """

    def __init__(self, mode: str = "auto"):
        self.mode = mode
        self.gemma = FunctionGemmaEngine()
        self.gemini = GeminiEngine()

    def handle_tool_calling(
        self,
        tool_calling_json: Dict[str, Any],
        tools: Optional[List[Any]] = None,
        tools_map: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Directly executes a specific tool call and synthesizes the result via Gemini.
        Bypasses the intent detection (Gemma) step.

        Args:
            tool_calling_json: Dict like {"tool_name": "...", "args": {...}}
            tools: List of tool definitions (optional, for compatibility)
            tools_map: Mapping of tool names to functions

        Returns:
            Dict matching the standard response format: {'answer': ..., 'debug': ...}
        """
        tools_map = tools_map or {}
        
        tool_name = tool_calling_json.get("tool_name")
        args = tool_calling_json.get("args", {})
        
        logger.info(f"🔧 Direct tool execution requested: {tool_name}")
        
        debug_calls = [{"name": tool_name, "arguments": args}]
        debug_results = []
        result_content = ""

        # 1. Execute the Tool
        if tool_name not in tools_map:
            error_msg = f"Tool '{tool_name}' not registered in tools_map."
            logger.error(error_msg)
            result_content = json.dumps({"error": error_msg})
        else:
            try:
                print(f"  [>] Calling: {tool_name}")
                func_result = tools_map[tool_name](**args)
                print(f"  [✓] Success.")
                result_content = json.dumps(func_result, default=str)
            except Exception as exc:
                print(f"  [!] Exception: {exc}")
                result_content = json.dumps({"error": str(exc)})

        debug_results.append({"name": tool_name, "response": result_content})

        # 2. Synthesize Result via Gemini
        # We construct a synthetic history so Gemini understands what happened.
        # System -> User (Synthetic Context) -> Tool Output
        
        synthesis_messages = [
            {"role": "system", "content": build_system_prompt("gemini")},
            {
                "role": "user", 
                "content": f"Execute the tool '{tool_name}' with arguments {args} and report the result."
            },
            {
                "role": "tool",
                "name": tool_name,
                "content": result_content
            }
        ]

        print("📝 Synthesizing answer via Gemini...")
        final_answer = self.gemini.generate(synthesis_messages, tools) or ""
        final_answer = final_answer.strip()

        if not final_answer:
            final_answer = "Tool execution complete. (No summary generated)"

        return {
            "answer": final_answer,
            "debug": {"calls": debug_calls, "data": debug_results},
        }

    def handle_message(
        self, 
        messages: List[Dict[str, Any]], 
        tools: Optional[List[Any]] = None, 
        tools_map: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        
        tools_map = tools_map or {}
        
        # --- STEP 1: PREPARE FOR ROUTING (FunctionGemma) ---
        # FunctionGemma is sensitive. We ensure the prompt is pure.
        # We strip previous system messages if they don't match the tool-calling requirement.
        router_messages = [m for m in messages if m["role"] != "system"]
        
        # Add the specific Developer trigger expected by FunctionGemma
        # Note: Your FunctionGemmaEngine likely handles the actual <start_of_turn>developer wrapping
        router_messages.insert(0, {
            "role": "system", # or "developer" depending on your engine's template mapping
            "content": build_system_prompt("gemma")
        })

        # --- STEP 2: INTENT DETECTION ---
        logger.info("🤖 Routing via FunctionGemma...")
        # raw_output will contain: <start_function_call>call:func{arg:<escape>val<escape>}...
        raw_output = self.gemma.generate(router_messages, tools)
        
        # Debug logging
        logger.debug(f"Raw Model Output: {raw_output}")

        # Extract tool calls (Engine must handle <escape> parsing!)
        tool_calls = self.gemma.extract_tool_calls(raw_output) or []
        
        # Check for "Thoughts" (Text before the function call)
        # FunctionGemma isn't explicitly trained for "Thoughts", but if they occur, capture them.
        thought_text = ""
        if "<start_function_call>" in raw_output:
            thought_text = raw_output.split("<start_function_call>")[0].strip()
        elif not tool_calls:
            thought_text = raw_output.strip()

        if thought_text:
            print(f"Agent Thought: {thought_text}")

        # --- STEP 3: EXECUTION OR DIRECT REPLY ---
        debug_calls = []
        debug_results = []
        
        # CASE A: No tools triggered -> Hand off to Gemini for conversation
        if not tool_calls:
            print("ℹ️ No tool calls detected. Switching to Gemini for chat.")
            
            # Re-build messages with the LEO Persona for Gemini
            chat_messages = [
                {"role": "system", "content": build_system_prompt("gemini")}
            ] + [m for m in messages if m["role"] != "system"]
            
            # If Gemma had a thought, pass it as context
            if thought_text:
                chat_messages.append({"role": "assistant", "content": thought_text})
                
            answer = self.gemini.generate(chat_messages)
            return {"answer": answer, "debug": {"calls": [], "data": []}}

        # CASE B: Execute Tools
        print(f"\n🛠️  TRIGGERED {len(tool_calls)} TOOL(S):")
        
        # According to doc: Turn 3 is the Model outputting the call
        # We add this to history so Gemini knows what happened
        messages.append({
            "role": "assistant",
            "content": raw_output # Contains the <start_function_call> tokens
        })

        tool_outputs_for_llm = []

        for call in tool_calls:
            name = call["name"]
            args = call.get("arguments", {})
            
            print(f"  [>] Calling: {name}")
            debug_calls.append({"name": name, "arguments": args})

            result_content = ""
            
            if name not in tools_map:
                error_msg = f"Tool '{name}' not registered in tools_map."
                print(f"  [X] Error: {error_msg}")
                result_content = json.dumps({"error": error_msg})
            else:
                try:
                    # Execute python function
                    func_result = tools_map[name](**args)
                    print(f"  [✓] Success.")
                    
                    # Convert to JSON string
                    result_content = json.dumps(func_result, default=str)
                except Exception as exc:
                    print(f"  [!] Exception: {exc}")
                    result_content = json.dumps({"error": str(exc)})

            debug_results.append({"name": name, "response": result_content})

            # Format for LLM History (Standard Chat Format)
            # Your GeminiEngine will likely convert this to standard user/model turns
            # or FunctionGemma would convert this to <start_function_response>
            tool_outputs_for_llm.append({
                "role": "tool",
                "name": name,
                "content": result_content
            })

        # Append execution results to history
        messages.extend(tool_outputs_for_llm)

        # --- STEP 4: FINAL SYNTHESIS (Gemini) ---
        # We switch to Gemini here because FunctionGemma is "Single Turn" optimized
        # and we want a rich conversational response.
        
        print("📝 Synthesizing answer via Gemini...")
        
        # Replace the FunctionGemma system prompt with the LEO Persona
        # This ensures the final answer sounds like LEO, not a raw robot.
        final_messages = [
            {"role": "system", "content": build_system_prompt("gemini")}
        ] + [m for m in messages if m["role"] != "system"]

        final_answer = self.gemini.generate(final_messages, tools) or ""
        final_answer = final_answer.strip()

        if not final_answer:
            final_answer = "Analysis complete. (No summary generated)"

        return {
            "answer": final_answer,
            "debug": {"calls": debug_calls, "data": debug_results},
        }