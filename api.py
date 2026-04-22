"""
api.py — Flask web server.

Exposes the Agent and tools via a clean REST API.
The frontend (index.html) talks exclusively to these endpoints.

Endpoints:
  POST /api/chat          — send a message, get AI response
  POST /api/reset         — clear conversation history
  GET  /api/data/<file>   — get raw table data for the data browser
  GET  /api/stats         — get summary stats for both files
  GET  /api/schema/<file> — get column schema for a file
"""

import os
import sys
import json
import traceback

from flask import Flask, request, jsonify, render_template
try:
    from flask_cors import CORS
    _CORS = True
except ImportError:
    _CORS = False
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Add project root to path so we can import our modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tools as tools_module
from tools import dispatch, _load, _df_to_records

app = Flask(__name__)
if _CORS: CORS(app)

# ── Lazy-load the agent (avoids crashing on import if no API key) ─────────────
_agent = None

def get_agent():
    global _agent
    if _agent is None:
        from agent import Agent
        _agent = Agent(verbose=False)
    return _agent


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN PAGE
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template("index.html")


# ═══════════════════════════════════════════════════════════════════════════════
# CHAT
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/chat", methods=["POST"])
def chat():
    """
    Body: {"message": "user text here"}
    Returns: {"response": "...", "tool_used": "...", "ok": true}
    """
    body = request.get_json(silent=True) or {}
    message = (body.get("message") or "").strip()

    if not message:
        return jsonify({"ok": False, "error": "Empty message"}), 400

    try:
        agent = get_agent()

        # Intercept the agent to also capture what tool was called
        # We do this by temporarily patching dispatch
        tool_used = {"name": None, "args": None, "result": None}
        original_dispatch = tools_module.dispatch

        def tracking_dispatch(tool_name, tool_args):
            result = original_dispatch(tool_name, tool_args)
            tool_used["name"] = tool_name
            tool_used["args"] = tool_args
            tool_used["result"] = result
            return result

        # Patch dispatch on the agent's imported module reference
        import agent as agent_module
        original = agent_module.dispatch
        agent_module.dispatch = tracking_dispatch

        try:
            response = agent.run(message)
        finally:
            agent_module.dispatch = original

        return jsonify({
            "ok": True,
            "response": response,
            "tool_used": tool_used["name"],
            "tool_args": tool_used["args"],
            "tool_result": _safe_serialize(tool_used["result"]),
        })

    except EnvironmentError as e:
        return jsonify({"ok": False, "error": str(e), "type": "config_error"}), 503
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e), "type": "server_error"}), 500


# ═══════════════════════════════════════════════════════════════════════════════
# RESET
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/reset", methods=["POST"])
def reset():
    global _agent
    # If agent was never created (no API key yet), still return ok
    if _agent is not None:
        try:
            _agent.reset()
        except Exception:
            pass
    # Always succeed — history is conceptually empty if agent doesn't exist
    return jsonify({"ok": True, "message": "Conversation history cleared."})


# ═══════════════════════════════════════════════════════════════════════════════
# DATA BROWSER — raw table data
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/data/<file_key>")
def get_data(file_key):
    """
    Returns paginated table data for the data browser panel.
    Query params: page (1-based), per_page, search, sort_col, sort_dir
    """
    if file_key not in ("real_estate", "marketing"):
        return jsonify({"ok": False, "error": "Unknown file"}), 400

    try:
        page     = max(1, int(request.args.get("page", 1)))
        per_page = min(100, max(5, int(request.args.get("per_page", 20))))
        search   = request.args.get("search", "").strip().lower()
        sort_col = request.args.get("sort_col", "")
        sort_dir = request.args.get("sort_dir", "asc")

        df = _load(file_key)

        # Full-text search across all string columns
        if search:
            mask = df.apply(
                lambda row: row.astype(str).str.lower().str.contains(search).any(),
                axis=1
            )
            df = df[mask]

        total_rows = len(df)

        # Sort
        if sort_col and sort_col in df.columns:
            df = df.sort_values(sort_col, ascending=(sort_dir == "asc"))

        # Paginate
        start = (page - 1) * per_page
        end   = start + per_page
        page_df = df.iloc[start:end]

        rows = _df_to_records(page_df, max_rows=per_page)

        return jsonify({
            "ok":         True,
            "rows":       rows,
            "columns":    df.columns.tolist(),
            "total_rows": total_rows,
            "page":       page,
            "per_page":   per_page,
            "total_pages": max(1, (total_rows + per_page - 1) // per_page),
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════════
# STATS — summary cards for both files
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/stats")
def get_stats():
    """Returns summary statistics used by the dashboard cards."""
    try:
        re_df  = _load("real_estate")
        mkt_df = _load("marketing")

        # Real estate stats
        re_stats = {
            "total_listings":    int(len(re_df)),
            "active":            int((re_df["Listing Status"] == "Active").sum()),
            "sold":              int((re_df["Listing Status"] == "Sold").sum()),
            "pending":           int((re_df["Listing Status"] == "Pending").sum()),
            "avg_list_price":    round(float(re_df["List Price"].mean()), 2),
            "avg_sale_price":    round(float(re_df["Sale Price"].dropna().mean()), 2),
            "by_property_type":  re_df["Property Type"].value_counts().to_dict(),
            "by_state":          re_df["State"].value_counts().to_dict(),
            "avg_price_by_type": re_df.groupby("Property Type")["List Price"].mean().round(2).to_dict(),
        }

        # Marketing stats
        mkt_stats = {
            "total_campaigns":      int(len(mkt_df)),
            "total_revenue":        round(float(mkt_df["Revenue Generated"].sum()), 2),
            "total_budget":         round(float(mkt_df["Budget Allocated"].sum()), 2),
            "total_spent":          round(float(mkt_df["Amount Spent"].sum()), 2),
            "total_conversions":    int(mkt_df["Conversions"].sum()),
            "total_clicks":         int(mkt_df["Clicks"].sum()),
            "total_impressions":    int(mkt_df["Impressions"].sum()),
            "by_channel":           mkt_df["Channel"].value_counts().to_dict(),
            "revenue_by_channel":   mkt_df.groupby("Channel")["Revenue Generated"].sum().round(2).to_dict(),
            "avg_ctr_by_channel":   (
                (mkt_df.groupby("Channel")["Clicks"].sum() /
                 mkt_df.groupby("Channel")["Impressions"].sum() * 100)
                .round(4).to_dict()
            ),
            "avg_roi_by_channel": (
                ((mkt_df.groupby("Channel")["Revenue Generated"].sum() -
                  mkt_df.groupby("Channel")["Amount Spent"].sum()) /
                 mkt_df.groupby("Channel")["Amount Spent"].sum() * 100)
                .round(2).to_dict()
            ),
        }

        return jsonify({"ok": True, "real_estate": re_stats, "marketing": mkt_stats})

    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════════
# SCHEMA
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/schema/<file_key>")
def get_schema(file_key):
    if file_key not in ("real_estate", "marketing"):
        return jsonify({"ok": False, "error": "Unknown file"}), 400
    result = dispatch("get_schema", {"file": file_key})
    return jsonify({"ok": True, **result})


# ═══════════════════════════════════════════════════════════════════════════════
# HEALTH CHECK
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/health")
def health():
    has_groq   = bool(os.getenv("GROQ_API_KEY"))
    has_gemini = bool(os.getenv("GEMINI_API_KEY"))

    # Check whether Excel files are actually reachable
    re_path  = tools_module.FILES["real_estate"]
    mkt_path = tools_module.FILES["marketing"]
    re_exists  = os.path.exists(re_path)
    mkt_exists = os.path.exists(mkt_path)

    return jsonify({
        "ok":            True,
        "groq_key":      has_groq,
        "gemini_key":    has_gemini,
        "llm_ready":     has_groq or has_gemini,
        "data_dir":      tools_module.BASE_DIR,
        "re_file":       re_path,
        "mkt_file":      mkt_path,
        "re_exists":     re_exists,
        "mkt_exists":    mkt_exists,
        "files_ok":      re_exists and mkt_exists,
    })


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _safe_serialize(obj):
    """Make any object JSON-serialisable."""
    if obj is None:
        return None
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return json.loads(json.dumps(obj, default=str))


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))

    # Always re-resolve paths at startup so we catch .env changes
    import importlib
    importlib.reload(tools_module)

    re_path  = tools_module.FILES['real_estate']
    mkt_path = tools_module.FILES['marketing']
    re_ok    = os.path.exists(re_path)
    mkt_ok   = os.path.exists(mkt_path)

    print(f"\n Excel AI Assistant")
    print(f"   URL  : http://localhost:{port}")
    print(f"   LLM  : {'Groq OK' if os.getenv('GROQ_API_KEY') else 'Gemini OK' if os.getenv('GEMINI_API_KEY') else 'WARNING: No API key - add GROQ_API_KEY to .env'}")
    print(f"   Data : {tools_module.BASE_DIR}")
    print(f"   RE   : {'OK' if re_ok  else 'NOT FOUND'} -> {re_path}")
    print(f"   MKT  : {'OK' if mkt_ok else 'NOT FOUND'} -> {mkt_path}")

    if not (re_ok and mkt_ok):
        raw_env = os.getenv('DATA_DIR', '(not set)')
        print(f"\n   DATA_DIR in .env = {raw_env!r}")
        print("   The path above was not found. Check:")
        print("   1. The .env file is in the SAME folder as api.py")
        print("   2. DATA_DIR uses forward slashes: C:/Users/.../skygate-task")
        print("   3. No quotes around the value in .env")
        print("   4. The Excel filenames are exactly:")
        print("      Real_Estate_Listings.xlsx")
        print("      Marketing_Campaigns.xlsx")
    print()
    app.run(debug=True, port=port, use_reloader=False)
