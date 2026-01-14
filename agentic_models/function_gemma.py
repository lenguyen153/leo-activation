import os
import threading
import re
import torch
import logging
from transformers import AutoTokenizer, AutoModelForCausalLM
from huggingface_hub import login
from agentic_models.base import BaseLLMEngine
from main_configs import GEMMA_FUNCTION_MODEL_ID, HUGGINGFACE_TOKEN

# Setup Logging
logger = logging.getLogger(__name__)

_login_lock = threading.Lock()
_logged_in = False

def ensure_hf_login():
    global _logged_in
    if _logged_in:
        return

    with _login_lock:
        if not _logged_in:
            token = HUGGINGFACE_TOKEN
            if not token:
                raise RuntimeError("HUGGINGFACE_TOKEN is not set")

            login(token=token)
            _logged_in = True

class FunctionGemmaEngine(BaseLLMEngine):
    def __init__(self, model_id: str = GEMMA_FUNCTION_MODEL_ID):
        super().__init__()
        self.model_id = model_id
        
        ensure_hf_login()

        logger.info(f"Loading FunctionGemma model: {self.model_id}")
        
        # NOTE: For FunctionGemma, AutoTokenizer is sufficient for chat templates. 
        # AutoProcessor is often used for multimodal, but this is text-to-text.
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_id)
        
        # ------------------------------------------------------------------
        # ACCURACY TIP: Do not quantize 270M models to 4-bit/8-bit unless necessary.
        # The model is tiny (~0.6 GB). Precision loss at this scale is severe.
        # ------------------------------------------------------------------
        torch_dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
        
        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_id,
            device_map="auto",
            torch_dtype=torch_dtype,
            trust_remote_code=True
        ).eval()

    def extract_tool_calls(self, text: str) -> list[dict]:
        """
        Parses FunctionGemma's specific output format:
        <start_function_call>call:func_name{param:<escape>value<escape>}<end_function_call>
        """
        calls = []
        
        # 1. Clean and normalize tags
        if "<start_function_call>" in text and "<end_function_call>" not in text:
            text += "}<end_function_call>" # Attempt to close truncated generations

        # 2. Regex for the function block
        # Matches: call:func_name{...} inside the tags
        # Logic: Finds the function name and the raw argument string inside the braces
        pattern = r"<start_function_call>call:(\w+)\{(.*?)\}(?:<end_function_call>|$)"
        
        for name, args_block in re.findall(pattern, text, re.DOTALL):
            parsed_args = {}
            
            # 3. Robust Argument Parsing
            # FunctionGemma uses 'key:value' or 'key:<escape>value<escape>'
            # We split by comma BUT ignore commas inside <escape> tags.
            
            # This regex finds: key : ( <escape>content<escape> OR simple_value )
            arg_pattern = r"(\w+)\s*:\s*(?:<escape>(.*?)<escape>|'([^']*)'|\"([^\"]*)\"|([^,{}]+))"
            
            for key, val_escaped, val_single, val_double, val_simple in re.findall(arg_pattern, args_block):
                # Select the captured group that isn't empty
                if val_escaped: raw_val = val_escaped
                elif val_single is not None and val_single != "": raw_val = val_single
                elif val_double is not None and val_double != "": raw_val = val_double
                else: raw_val = val_simple

                parsed_args[key] = self._cast_value(raw_val)

            calls.append({"name": name, "arguments": parsed_args})

        return calls

    def _cast_value(self, v: str):
        """Helper to cast string values to python types for LEO CDP."""
        v = v.strip()
        if v.lower() == "true": return True
        if v.lower() == "false": return False
        if v.lower() in ("none", "null"): return None
        
        # Try numeric
        try:
            if "." in v: return float(v)
            return int(v)
        except ValueError:
            pass
            
        # Clean quotes if they exist (though <escape> usually handles this)
        return v.strip("'\"")

    def generate(self, messages, tools=None) -> str:
        """
        Generates response using FunctionGemma's specific developer role constraints.
        """
        
        # 
        # Vital: Check if the mandatory developer prompt exists. 
        # FunctionGemma IGNORES tools if this specific line is missing.
        SYSTEM_TRIGGER = "You are a model that can do function calling with the following functions"
        
        # Check for existing trigger, if not present, inject it
        # check for both 'system' and 'developer' roles to be safe
        # For example: valid message for has_trigger = true: {"role": "developer", "content": "You are a model that can do function calling with the following functions..."}
        has_trigger = any(
            m.get("role") in ["system", "developer"] and SYSTEM_TRIGGER in m.get("content", "")
            for m in messages
        )

        if not has_trigger and tools:
            # Inject the mandatory system prompt for FunctionGemma
            # It maps 'system' to 'developer' role internally usually, but we make it explicit
            messages.insert(0, {
                "role": "system", 
                "content": SYSTEM_TRIGGER
            })

        # Apply chat template handles the <start_function_declaration> formatting automatically
        inputs = self.tokenizer.apply_chat_template(
            messages,
            tools=tools,
            add_generation_prompt=True,
            return_dict=True,
            return_tensors="pt"
        ).to(self.model.device)
        
        # Use torch inference mode for efficiency because we don't need gradients
        with torch.inference_mode():
            output = self.model.generate(
                **inputs,
                max_new_tokens=512,
                # Greedy decoding is STRONGLY recommended for function calling accuracy
                do_sample=False, 
                # Slightly higher rep penalty to stop 270M from looping
                repetition_penalty=1.05 
            )

        gen_tokens = output[0][inputs["input_ids"].shape[1]:]
        decoded = self.tokenizer.decode(gen_tokens, skip_special_tokens=True)
        
        # Fallback: Log if we expected a tool call but got plain text
        if tools and "<start_function_call>" not in decoded and len(decoded) < 20:
             logger.warning(f"Engine Warning: Model did not trigger function call. Output: {decoded}")

        return decoded