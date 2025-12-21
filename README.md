# Resynap for AMA Platform

**Core Resynap for AI-driven Marketing Automation (AMA) Platform**

Resynap-platform is an intelligent backend service designed to bridge the gap between complex Customer Data Platforms (CDP) and marketing teams. By leveraging **Google's FunctionGemma-270M**, it provides a conversational AI interface for the [LEO CDP Framework](https://github.com/trieu/leo-cdp-framework), allowing users to manage segments and trigger omnichannel marketing activations through natural language.

## 🚀 Overview

FunctionGemma is a specialized version of the Gemma 3 270M model, specifically optimized for high-accuracy function calling. This platform implements the complete four-stage workflow required for reliable tool integration:

1. **Define Tools**: Core CDP operations (segmentation, activation) and utilities (weather, date) are defined with strict docstring schemas.
2. **Model's Turn**: The model processes user intent and generates structured function call objects instead of plain text.
3. **Developer's Turn**: The backend parses these objects, executes Python logic (e.g., triggering a Zalo API call), and appends the result to the conversation history.
4. **Final Response**: The model uses the execution results to generate a natural language confirmation for the user.

## ✨ Key Features

* **Conversational Segmentation**: Create, update, or delete LEO CDP segments using simple prompts.
* **Omnichannel Activation**: An OOP-based strategy layer supporting:
* 📧 **Email**
* 💬 **Zalo OA Push**
* 📱 **Mobile Notification Push**
* 🌐 **Web Push**
* 🌐 and more channels are developed


* **Contextual Intelligence**: Integrated weather-aware logic using the Open-Meteo API to personalize campaigns based on real-time environmental data.

## 🛠️ Installation & Setup

### 1. Prerequisites

* Python 3.10+
* Hugging Face account with access to [google/functiongemma-270m-it](https://huggingface.co/google/functiongemma-270m-it).
* A valid Hugging Face Access Token.

### 2. Create Virtual Environment

```bash
python -m venv venv
# On Windows
venv\Scripts\activate
# On macOS/Linux
source venv/bin/activate

```

### 3. Install Dependencies

```bash
pip install -r requirements.txt

```

*Note: Ensure `torch` and `transformers` are installed as required for the FunctionGemma model.*

## ⚙️ Configuration

Create a `.env` file in the root directory:

```text
HF_TOKEN=your_huggingface_token
ZALO_OA_TOKEN=your_zalo_token
LEO_CDP_API_URL=http://your-leo-cdp-instance:8080

```

## 🚀 Running the Platform

Launch the FastAPI server:

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000

```

## 💬 Usage Example

The platform expects an **Essential System Prompt** to activate the model's function-calling logic:
*`"You are a model that can do function calling with the following functions"`*.

**Endpoint**: `POST /chat`
**Payload**:

```json
{
  "prompt": "Create a segment for 'High Value' users and send them a Zalo message saying 'Exclusive offer just for you!'"
}

```

## 📁 Project Structure

* `main.py`: FastAPI orchestrator managing the four-step FunctionGemma cycle.
* `tools.py`: OOP implementation of LEO CDP tools and activation strategies.
* `model_engine.py`: Handles model loading (`AutoModelForCausalLM`) and response parsing using optimized regex.

---

*For more information on the underlying technology, refer to the [Fine-tuning with FunctionGemma](https://ai.google.dev/gemma/docs/functiongemma/finetuning-with-functiongemma) documentation.*