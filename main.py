from fastapi import FastAPI
from pydantic import BaseModel
from model_engine import FunctionGemmaEngine
from tools import AVAILABLE_TOOLS, get_date, get_current_weather, manage_leo_segment, activate_channel

app = FastAPI(title="LEO CDP Assistant")
engine = FunctionGemmaEngine()

class ChatRequest(BaseModel):
    prompt: str

@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    tools_list = [get_date, get_current_weather, manage_leo_segment, activate_channel]
    
    # IMPROVEMENT: Use a more directive system prompt to encourage tool use
    messages = [
        {"role": "developer", "content": "You are a LEO CDP assistant. Use the provided tools immediately whenever a user asks to manage segments or send messages. Do not ask for confirmation if the information is already in the prompt."},
        {"role": "user", "content": request.prompt},
    ]

    raw_output = engine.generate(messages, tools_list)
    tool_calls = engine.extract_tool_calls(raw_output)

    # 1. If no tools are called, return empty debug info to avoid KeyError
    if not tool_calls:
        return {
            "answer": raw_output,
            "debug": {"calls": [], "data": []} 
        }

    # 2. Proceed with tool execution...
    messages.append({
        "role": "assistant",
        "tool_calls": [{"type": "function", "function": tc} for tc in tool_calls]
    })

    tool_results = []
    for call in tool_calls:
        func_name = call['name']
        if func_name in AVAILABLE_TOOLS:
            result = AVAILABLE_TOOLS[func_name](**call['arguments'])
            tool_results.append({"name": func_name, "response": result})

    messages.append({"role": "tool", "content": tool_results})

    # 3. Final Response
    final_answer = engine.generate(messages, tools_list)
    
    return {
        "answer": final_answer,
        "debug": {"calls": tool_calls, "data": tool_results}
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)