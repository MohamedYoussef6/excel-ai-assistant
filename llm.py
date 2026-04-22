"""
llm.py — LLM client layer.

Handles:
- Sending messages to the LLM (Groq by default, Gemini fallback)
- Injecting the tool schema into the system prompt
- Parsing the LLM's JSON tool-call response
- Retry logic for malformed responses
"""

import os
import json
import re
import time
from typing import Optional

try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False

try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False


# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an AI assistant that manages two Excel files:

1. **real_estate** — Real estate listings (1000 rows)
   Columns: Listing ID, Property Type, City, State, Bedrooms, Bathrooms,
            Square Footage, Year Built, List Price, Sale Price, Listing Status
   Values:  Property Type: House/Condo/Apartment/Townhouse
            Listing Status: Sold/Pending/Active
            States: Arizona, California, Colorado, Florida, Georgia,
                    Illinois, Massachusetts, New York, Texas, Washington

2. **marketing** — Marketing campaign data (1000 rows)
   Columns: Campaign ID, Campaign Name, Channel, Start Date, End Date,
            Budget Allocated, Amount Spent, Impressions, Clicks,
            Conversions, Revenue Generated
   Values:  Channel: Facebook, LinkedIn, Instagram, Google Ads, Email
            Dates: YYYY-MM-DD format

You respond ONLY by calling one of these tools (respond with a JSON object):

TOOLS:

1. query_data — Filter and retrieve rows
   {"tool": "query_data", "args": {
     "file": "real_estate" | "marketing",
     "conditions": [{"column": str, "operator": "eq|neq|gt|gte|lt|lte|contains", "value": any}],
     "columns": ["col1", ...],   // optional — omit for all columns
     "order_by": "column_name",  // optional
     "ascending": true,          // optional, default true
     "limit": 50                 // optional, default 50
   }}

2. aggregate_data — Compute statistics (sum/mean/median/min/max/count/std)
   {"tool": "aggregate_data", "args": {
     "file": "real_estate" | "marketing",
     "metric": "sum" | "mean" | "median" | "min" | "max" | "count" | "std",
     "column": "column_name",
     "conditions": [...],   // optional filters
     "group_by": "column"   // optional grouping
   }}

3. insert_row — Add a new row
   {"tool": "insert_row", "args": {
     "file": "real_estate" | "marketing",
     "data": {"Column Name": value, ...}
   }}

4. update_rows — Modify existing rows
   {"tool": "update_rows", "args": {
     "file": "real_estate" | "marketing",
     "filters": {"Column Name": exact_value},
     "updates": {"Column Name": new_value}
   }}

5. delete_rows — Remove rows
   {"tool": "delete_rows", "args": {
     "file": "real_estate" | "marketing",
     "filters": {"Column Name": exact_value}
   }}

6. get_schema — Inspect columns and sample values
   {"tool": "get_schema", "args": {"file": "real_estate" | "marketing"}}

RULES:
- Always respond with ONLY a valid JSON object — no prose, no markdown fences.
- Use exact column names (case-sensitive). 
- For computed questions (ROI, CTR, conversion rate), use aggregate_data to get
  the raw numbers, then compute in your final answer.
- If the request is ambiguous, pick the most reasonable interpretation.
- Numeric values in conditions must be numbers, not strings.
- For date comparisons, use "gt"/"lt" with "YYYY-MM-DD" string values.
- If you need to understand the data structure first, call get_schema.
"""

ANSWER_SYSTEM_PROMPT = """You are a helpful data analyst assistant. 
You have been given tool results from an Excel database. 
Summarise the findings clearly and concisely for the user.
- Format numbers with commas and 2 decimal places where appropriate.
- For lists of rows, present them as a clean table or bullet list.
- Be direct. No filler phrases like "Certainly!" or "Great question!".
- If the result is empty or nothing was found, say so clearly.
"""


# ── Groq client ───────────────────────────────────────────────────────────────

def _call_groq(messages: list, system: str, api_key: str) -> str:
    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "system", "content": system}] + messages,
        temperature=0.0,
        max_tokens=1024,
    )
    return response.choices[0].message.content.strip()


# ── Gemini client ─────────────────────────────────────────────────────────────

def _call_gemini(messages: list, system: str, api_key: str) -> str:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name="gemini-1.5-flash",
        system_instruction=system,
    )
    # Flatten messages to a single prompt for simplicity
    conversation = "\n".join(
        f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
        for m in messages
    )
    response = model.generate_content(conversation)
    return response.text.strip()


# ── JSON extraction ───────────────────────────────────────────────────────────

def _extract_json(text: str) -> Optional[dict]:
    """Extract JSON object from LLM response, handling markdown fences."""
    # Strip markdown fences
    text = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Find first {...} block
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return None


# ── Main LLM caller ───────────────────────────────────────────────────────────

class LLMClient:
    def __init__(self):
        self.groq_key   = os.getenv("GROQ_API_KEY", "")
        self.gemini_key = os.getenv("GEMINI_API_KEY", "")
        self.provider   = self._detect_provider()
        self.history    = []  # conversation memory

    def _detect_provider(self) -> str:
        if self.groq_key and GROQ_AVAILABLE:
            return "groq"
        if self.gemini_key and GEMINI_AVAILABLE:
            return "gemini"
        raise EnvironmentError(
            "No LLM API key found.\n"
            "Set GROQ_API_KEY or GEMINI_API_KEY in your .env file.\n"
            "Get a free Groq key at: https://console.groq.com"
        )

    def _call(self, messages: list, system: str) -> str:
        if self.provider == "groq":
            return _call_groq(messages, system, self.groq_key)
        return _call_gemini(messages, system, self.gemini_key)

    def get_tool_call(self, user_message: str, retries: int = 3) -> dict:
        """
        Send user message → get a tool-call JSON from the LLM.
        Retries up to `retries` times on malformed output.
        """
        self.history.append({"role": "user", "content": user_message})

        for attempt in range(retries):
            raw = self._call(self.history, SYSTEM_PROMPT)

            parsed = _extract_json(raw)
            if parsed and "tool" in parsed and "args" in parsed:
                # Store assistant turn
                self.history.append({"role": "assistant", "content": raw})
                return parsed

            # Inject correction hint and retry
            correction = (
                f"Your response was not valid JSON with 'tool' and 'args' keys. "
                f"Raw response: {raw!r}. "
                f"Respond ONLY with a JSON object like: "
                f'{{\"tool\": \"tool_name\", \"args\": {{...}}}}'
            )
            self.history.append({"role": "user", "content": correction})
            time.sleep(0.5)

        return {"tool": "__error__", "args": {},
                "error": "LLM failed to produce valid tool call after retries."}

    def get_final_answer(self, user_message: str, tool_result: dict) -> str:
        """
        Given the original user question and tool result, get a human-readable answer.
        """
        prompt = (
            f"User asked: {user_message}\n\n"
            f"Tool result: {json.dumps(tool_result, indent=2, default=str)}\n\n"
            "Provide a clear, direct answer."
        )
        messages = [{"role": "user", "content": prompt}]
        return self._call(messages, ANSWER_SYSTEM_PROMPT)

    def reset_history(self):
        """Clear conversation history (start fresh)."""
        self.history = []
