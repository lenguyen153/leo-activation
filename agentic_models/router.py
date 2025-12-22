


from agentic_models.function_gemma import FunctionGemmaEngine
from agentic_models.gemini import GeminiEngine


class LLMRouter:
    """
    Strategy:
    - tool-heavy / structured → FunctionGemma
    - semantic / reasoning → Gemini
    """

    def __init__(self, mode: str = "auto"):
        self.mode = mode
        self.gemma = FunctionGemmaEngine()
        self.gemini = GeminiEngine()

    def generate(self, messages, tools=None):
        """ Generates response using the appropriate LLM based on mode and tools.
        Args:
            messages: List of message dicts for the chat history.
            tools: Optional list of tool definitions for tool-calling.
        Returns:
            Generated response string.
        """
    
        if self.mode == "gemma":
            return self.gemma.generate(messages, tools)
        
        if self.mode == "gemini":
            return self.gemini.generate(messages, tools)

        # AUTO MODE
        if tools:
            return self.gemma.generate(messages, tools)

        # default to higher intelligence
        return self.gemini.generate(messages, tools)

    def extract_tool_calls(self, raw_output: str) -> list[dict]:
        """
        Extract tool calls from the raw output of the LLM.
        Returns a list of tool call dicts.
        """
        if self.mode == "gemma":
            return self.gemma.extract_tool_calls(raw_output)
        
        if self.mode == "gemini":
            return self.gemini.extract_tool_calls(raw_output)

        # AUTO MODE
        gemma_calls = self.gemma.extract_tool_calls(raw_output)
        if gemma_calls:
            return gemma_calls

        return self.gemini.extract_tool_calls(raw_output)