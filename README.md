# Excel AI Assistant

An AI assistant that reads, queries, inserts, modifies, and deletes data from two Excel files using natural language — built from scratch in Python with no agent frameworks.

## Quick Start

**1. Clone the repo**
```bash
git clone https://github.com/YOUR_USERNAME/excel-ai-assistant.git
cd excel-ai-assistant
```

**2. Install dependencies**
```bash
pip install -r requirements.txt
```

**3. Set up your API key**
```bash
cp .env.example .env
# Edit .env and add your GROQ_API_KEY
# Free key at: https://console.groq.com
```

**4a. Run the Web UI (recommended)**
```bash
python api.py
# Open http://localhost:5000
```

**4b. Or use the CLI**
```bash
python main.py
```

## Usage

```
You: Show me all 3-bedroom houses in Texas under $500,000
You: What is the average sale price grouped by property type?
You: Add a new listing: 2-bed condo in Miami Florida, $320k asking price, Active status
You: Update listing LST-5001 status to Pending
You: Delete campaign CMP-8003
You: Which marketing channel has the highest ROI?
You: How many active listings are there in California?
You: Show me the top 5 campaigns by revenue generated
```

### Special commands
- `reset` — clear conversation history
- `quit` — exit

### Verbose mode (shows tool calls)
```bash
python main.py --verbose
```

### Single query
```bash
python main.py --query "Average list price in Texas"
```

## Running Tests
```bash
python test_tools.py
```
All 29 tests run on isolated copies of the Excel files — originals are never touched.

## Files

```
excel-ai-assistant/
├── main.py                     # CLI entry point
├── agent.py                    # Agentic loop (LLM → tool → answer)
├── llm.py                      # LLM client (Groq / Gemini)
├── tools.py                    # All 6 Excel tool functions
├── test_tools.py               # 29 unit tests
├── requirements.txt
├── .env.example
├── Real_Estate_Listings.xlsx
└── Marketing_Campaigns.xlsx
```

## Architecture

```
User Input
    ↓
LLMClient.get_tool_call()    ← LLM (Groq llama-3.3-70b) decides which tool + args
    ↓
tools.dispatch(name, args)   ← Python executes the tool against Excel files
    ↓
LLMClient.get_final_answer() ← LLM converts raw result to natural language
    ↓
Printed Response
```

## Supported Tools

| Tool | What it does |
|------|-------------|
| `query_data` | Filter rows with conditions, sort, select columns |
| `aggregate_data` | Sum/mean/count/min/max/median/std, with optional grouping |
| `insert_row` | Append a new row (auto-generates ID if missing) |
| `update_rows` | Modify fields on matching rows |
| `delete_rows` | Remove matching rows |
| `get_schema` | Inspect column names, types, and sample values |

## Data Files

**Real_Estate_Listings.xlsx** — 1,000 U.S. property listings  
Columns: Listing ID, Property Type, City, State, Bedrooms, Bathrooms, Square Footage, Year Built, List Price, Sale Price, Listing Status

**Marketing_Campaigns.xlsx** — 1,000 marketing campaigns  
Columns: Campaign ID, Campaign Name, Channel, Start Date, End Date, Budget Allocated, Amount Spent, Impressions, Clicks, Conversions, Revenue Generated
