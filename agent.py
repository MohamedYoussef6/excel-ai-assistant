"""
agent.py — The agentic execution loop.

Data flow:
  user input
      ↓
  LLMClient.get_tool_call()     ← sends to LLM, parses JSON response
      ↓
  tools.dispatch(name, args)    ← calls the right Python function
      ↓
  LLMClient.get_final_answer()  ← LLM turns raw result into English
      ↓
  printed response
"""

import json
from tools import dispatch
from llm import LLMClient


class Agent:
    def __init__(self, verbose: bool = False):
        self.llm     = LLMClient()
        self.verbose = verbose

    def run(self, user_input: str) -> str:
        """
        Process one user request end-to-end.
        Returns the final human-readable response string.
        """
        user_input = user_input.strip()
        if not user_input:
            return "Please enter a question or command."

        # ── Step 1: LLM decides which tool to call ────────────────────────────
        tool_call = self.llm.get_tool_call(user_input)

        if self.verbose:
            print(f"\n[DEBUG] Tool call: {json.dumps(tool_call, indent=2)}")

        # ── Step 2: Check for LLM error ───────────────────────────────────────
        if tool_call.get("tool") == "__error__":
            return f"Sorry, I couldn't understand that request. {tool_call.get('error', '')}"

        tool_name = tool_call["tool"]
        tool_args = tool_call["args"]

        # ── Step 3: Execute the tool ──────────────────────────────────────────
        result = dispatch(tool_name, tool_args)

        if self.verbose:
            print(f"[DEBUG] Tool result: {json.dumps(result, indent=2, default=str)[:500]}")

        # ── Step 4: Check for tool-level error ────────────────────────────────
        if "error" in result:
            # Feed the error back to the LLM for a user-friendly message
            return self.llm.get_final_answer(
                user_input,
                {"error": result["error"], "hint": "Explain the problem to the user clearly."}
            )

        # ── Step 5: LLM converts raw result → natural language ────────────────
        final_answer = self.llm.get_final_answer(user_input, result)
        return final_answer

    def reset(self):
        """Clear conversation history."""
        self.llm.reset_history()
        print("Conversation history cleared.")
