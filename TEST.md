# TEST MESSAGES

10 test messages designed to validate your refactored FunctionGemma agent. 
They cover **basic controls**, **segmentation logic**, **activation workflows**, and **complex multi-step reasoning**.

You can send these JSON payloads directly to your `/chat` endpoint.

### **Group 1: Basic Tool Control (Sanity Checks)**

These ensure the model can call simple tools correctly without hallucinating LEO CDP logic.

**1. Basic Weather Check**
*Tests `get_current_weather*`

```json
{
  "prompt": "What is the current weather in Ho Chi Minh City?"
}

```

**2. Date Retrieval**
*Tests `get_date*`

```json
{
  "prompt": "Can you check today's date for me?"
}

```

---

### **Group 2: LEO CDP Segmentation**

These test the `manage_cdp_segment` tool, ensuring the model extracts criteria and names correctly.

**3. Simple Segmentation**
*Tests creation with explicit time window.*

```json
{
  "prompt": "Create a new segment for all users who visited the website in the last 7 days."
}

```

**4. Complex Logical Segmentation**
*Tests handling of multiple conditions (Logic: AND).*

```json
{
  "prompt": "I need a segment named 'High Value Leads' consisting of users with a Lifetime Value over $500 who have also clicked on an email this month."
}

```

**5. Behavioral Segmentation**
*Tests specific behavioral triggers.*

```json
{
  "prompt": "Segment users who added items to their cart but did not complete the checkout process within 24 hours."
}

```

---

### **Group 3: Channel Activation**

These test the `activate_channel` tool, verifying the model can link segments to external platforms.

**6. Social Ad Activation**
*Tests standard activation to a major ad network.*

Facebook

```json
{
  "prompt": "Activate the 'Summer Sale Target' segment on Facebook Page immediately."
}

```

Zalo 

```json
{
  "prompt": "Activate the 'Summer Sale Target' segment on Zalo OA immediately."
}

```



**7. Zalo Marketing**
*Tests activation to Zalo.*

```json
{
  "prompt": "for segment 'new user at channel Zalo, send 'hello @user'"
}

```


---

### **Group 4: Advanced / Multi-Step**

These require the model to reason, potentially call multiple tools, or handle mixed intents.

**8. Contextual Activation (Weather + CDP)**
*Tests if the model can use environmental data (weather) to influence CDP decisions.*

```json
{
  "prompt": "Check the weather in London. If it's raining, create a segment called 'London Rain Target' for users in that region."
}

```

**9. Multi-Tool Execution**
*Tests doing two distinct tasks in one prompt.*

```json
{
  "prompt": "First, create a segment for 'VIP Users', and then immediately activate that segment on Google Customer Match."
}

```

**10. Ambiguous/Correction Handling**
*Tests how the model handles a request that implies action but might need default assumptions (or how it formats the error if 'TikTok' isn't a configured channel).*

```json
{
  "prompt": "Send to our segment 'Churn Risk' using Zalo OA  with message 'Hello' right now."
}

```