import os
import re
import torch
from dotenv import load_dotenv
from transformers import AutoProcessor, AutoModelForCausalLM
from huggingface_hub import login

load_dotenv()
if os.getenv("HF_TOKEN"):
    login(token=os.getenv("HF_TOKEN"))

class FunctionGemmaEngine:
    def __init__(self):
        self.model_id = "google/functiongemma-270m-it"
        self.processor = AutoProcessor.from_pretrained(self.model_id)
        # FIX: Using dtype instead of torch_dtype
        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_id, 
            device_map="auto", 
            dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32
        )

    def extract_tool_calls(self, text):
        def cast(v):
            try: return int(v)
            except:
                try: return float(v)
                except: return {'true': True, 'false': False}.get(v.lower(), v.strip("'\""))

        return [{
            "name": name,
            "arguments": {
                k: cast((v1 or v2).strip())
                for k, v1, v2 in re.findall(r"(\w+):(?:<escape>(.*?)<escape>|([^,}]*))", args)
            }
        } for name, args in re.findall(r"<start_function_call>call:(\w+)\{(.*?)\}<end_function_call>", text, re.DOTALL)]

    def generate(self, messages, tools):
        inputs = self.processor.apply_chat_template(
            messages, 
            tools=tools, 
            add_generation_prompt=True, 
            return_dict=True, 
            return_tensors="pt"
        ).to(self.model.device)

        out = self.model.generate(**inputs, max_new_tokens=256, pad_token_id=self.processor.eos_token_id)
        generated_tokens = out[0][len(inputs["input_ids"][0]):]
        return self.processor.decode(generated_tokens, skip_special_tokens=True)