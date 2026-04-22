# DECISIONS.md — Design Choices, Tradeoffs & Reflections

## 1. Overall Architecture: Why a Two-Call LLM Pattern?

### Decision
The system uses **two LLM calls per user request**:
1. **Tool selection call** — LLM reads the user's natural language and outputs a JSON tool call
2. **Answer synthesis call** — LLM reads the raw tool result and writes a human-readable response

### Why not one call?
A single call attempting to both choose the tool AND narrate the answer produces worse results. The LLM struggles to stay in JSON format while also wanting to write prose. Separating concerns makes each call simpler, more reliable, and easier to debug.

### Why not a streaming multi-step ReAct loop?
The task requires CRUD on Excel files — nearly every request is a single operation (filter, aggregate, insert, update, delete). A ReAct loop that calls multiple tools iteratively adds latency and complexity for no real gain here. If a request genuinely needs two steps (e.g., "find all active listings in Texas, then update their price"), the current design handles it through the user's follow-up turn — which is the natural conversation pattern anyway.

---

## 2. Tool Design: Why 6 Tools?

### The 6 tools: query_data, aggregate_data, insert_row, update_rows, delete_rows, get_schema

### Why not fewer tools?
An alternative is one `execute` tool that takes raw Python/SQL. This is dangerous (arbitrary code execution), hard for the LLM to use reliably, and non-defensible. Named tools with typed parameters constrain the LLM to safe, predictable operations.

### Why not more tools?
I considered separate tools per operation per file (12 tools total). This is worse — the LLM's context grows, and you introduce redundancy. Keeping `file` as a parameter of every tool is cleaner and more scalable.

### Why separate `query_data` and `aggregate_data`?
They serve different purposes. `query_data` returns rows (for display). `aggregate_data` returns a scalar or grouped dict (for computation). Merging them would create a bloated, harder-to-use tool schema that the LLM is more likely to misuse.

### Why include `get_schema`?
The LLM cannot know about column names or valid values at inference time unless told. Rather than hardcoding everything into the system prompt (brittle when data changes), `get_schema` lets the LLM self-inspect. In practice the system prompt already provides the column names, but `get_schema` is the graceful fallback for ambiguous requests.

---

## 3. LLM Choice: Why Groq (llama-3.3-70b)?

### Decision
Primary: Groq with `llama-3.3-70b-versatile`. Fallback: Google Gemini 1.5 Flash.

### Why Groq?
- Free tier with generous rate limits
- Llama 3.3 70B produces reliable JSON tool calls with low hallucination rates
- Very fast inference (important for interactive feel in a CLI)
- The `groq` Python SDK is minimal and easy to explain

### Why not a local model?
Local models (Ollama, llama.cpp) would satisfy the "free" constraint but require the evaluator to install significant software. A free API key is a much lower friction setup for a take-home assignment. In production, local would be the right call for data privacy.

### Why not GPT-4 or Claude?
Not free. The task explicitly requires free LLMs only.

### Fallback to Gemini
Gemini 1.5 Flash is free-tier and capable. Having it as a fallback means the code works even if someone doesn't have a Groq key.

---

## 4. Prompt Design: Why JSON-only responses?

### Decision
The system prompt instructs the LLM to respond **only** with a JSON object containing `"tool"` and `"args"`. No prose.

### Why?
- JSON is machine-parseable deterministically
- It forces the LLM to commit to a single action
- Easier to validate and retry on failure

### Retry mechanism
If the LLM returns malformed JSON (markdown fences, extra prose), the code:
1. Strips markdown fences via regex
2. Searches for the first `{...}` block
3. If still invalid, injects a correction hint and retries up to 3 times

This handles ~99% of real-world LLM formatting failures without crashing.

---

## 5. Persistence: Direct File Writes

### Decision
Every insert, update, and delete writes back to the `.xlsx` file immediately using `df.to_excel()`.

### Why not a database?
The task says "Excel files." Using SQLite and syncing back would be overengineering, and it adds a sync consistency problem. Writing directly keeps the file as the single source of truth.

### Tradeoff
No transactions — if a write fails midway, the file could be in a partial state. For a production system, I'd write to a temp file and atomically rename it. For this scope (small files, single-process), direct write is acceptable and defensible.

---

## 6. Condition System: Structured Filters vs. Free SQL

### Decision
Conditions are expressed as `[{"column": ..., "operator": ..., "value": ...}]` — a simple DSL.

### Why not SQL?
SQL requires an embedded SQL engine (sqlite, DuckDB). While powerful, it means:
- More dependencies
- The LLM generating SQL is harder to validate safely
- SQL injection risk (even from an LLM)

The structured condition list is safe by construction — `operator` is whitelisted, `column` is validated against the DataFrame, and values are typed.

### Why not pandas `query()` string?
Same problem — arbitrary string evaluation. Dangerous and hard to validate.

---

## 7. Conversation History

### Decision
`LLMClient` maintains a `self.history` list that grows across turns. The user can type `reset` to clear it.

### Why maintain history?
Allows follow-up questions: "Now filter those by California" works after "Show me all 3-bedroom houses."

### Tradeoff
History grows unbounded in a long session, eventually hitting the LLM's context limit. In production I'd implement a sliding window or summarization. For a 3-day take-home, this is acceptable — and I can articulate exactly why and how I'd fix it.

---

## 8. What I'd Do Differently with More Time

1. **Atomic file writes** — write to temp file, then `os.replace()` to avoid corruption on crash
2. **Context window management** — rolling history with summarization for very long sessions
3. **Schema validation on insert** — enforce types and check required fields before writing
4. **Multi-step planning** — for requests that require two operations (e.g., "move all active listings in Ohio to Pending"), use a simple planner that emits multiple tool calls
5. **Web UI** — a simple Flask/FastAPI + HTML frontend would make the UX dramatically better than a CLI
6. **Backup on mutations** — copy the `.xlsx` to `filename.backup.xlsx` before any write operation
7. **Structured logging** — log every tool call and result to a JSON log file for auditability

---

## 9. What the Design Gets Right

- **Explainability**: Every component (tools.py, llm.py, agent.py) has a single clear responsibility and can be explained line by line
- **Testability**: tools.py has zero LLM dependencies — all 29 unit tests run offline against real data
- **Safety**: No eval(), no SQL injection surface, no arbitrary code execution
- **Robustness**: JSON retry logic, graceful error messages, validation at tool call time
- **UX**: The two-call pattern means users always get a natural language answer, not raw JSON
