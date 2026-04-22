"""
tools.py — All Excel tool functions.
Each function is a standalone, testable unit.
The LLM calls these by name with JSON arguments.
"""

import pandas as pd
import json
import os
from datetime import datetime

# ── File paths ────────────────────────────────────────────────────────────────
# Priority order for locating Excel files:
#   1. DATA_DIR env variable (set in .env)  — handles Windows forward/back slashes
#   2. Same folder as tools.py
#   3. Current working directory

def _norm(path: str) -> str:
    """Normalize a path: strip quotes, replace forward slashes, resolve to absolute."""
    # Strip surrounding quotes that some .env parsers leave in
    path = path.strip().strip('"').strip("'")
    # os.path.abspath handles mixed slashes on all platforms
    return os.path.abspath(path)

def _resolve_data_dir() -> str:
    env_dir = os.getenv("DATA_DIR", "").strip().strip('"').strip("'")
    if env_dir:
        normalized = _norm(env_dir)
        if os.path.isdir(normalized):
            return normalized
        # Try the raw value too (in case abspath changed something)
        if os.path.isdir(env_dir):
            return env_dir

    # Same folder as this file
    here = os.path.dirname(os.path.abspath(__file__))
    if os.path.exists(os.path.join(here, "Real_Estate_Listings.xlsx")):
        return here

    # Current working directory
    cwd = os.path.abspath(os.getcwd())
    if os.path.exists(os.path.join(cwd, "Real_Estate_Listings.xlsx")):
        return cwd

    # Fall back to this file's directory
    return here

BASE_DIR = _resolve_data_dir()
FILES = {
    "real_estate": os.path.normpath(os.path.join(BASE_DIR, "Real_Estate_Listings.xlsx")),
    "marketing":   os.path.normpath(os.path.join(BASE_DIR, "Marketing_Campaigns.xlsx")),
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _load(file_key: str) -> pd.DataFrame:
    path = FILES[file_key]
    df = pd.read_excel(path)
    # Normalise column names: strip whitespace
    df.columns = [c.strip() for c in df.columns]
    return df


def _save(df: pd.DataFrame, file_key: str) -> None:
    df.to_excel(FILES[file_key], index=False)


import numpy as np

def _df_to_records(df: pd.DataFrame, max_rows: int = 100) -> list:
    df = df.head(max_rows).copy()

    # Convert datetime columns
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].dt.strftime("%Y-%m-%d")

    # 🔥 CRITICAL FIX
    df = df.astype(object)
    df = df.where(pd.notna(df), None)

    # Extra safety
    df = df.replace([np.inf, -np.inf], None)

    return df.to_dict(orient="records")

def _find_rows(df: pd.DataFrame, filters: dict) -> pd.Series:
    """
    Return a boolean mask for rows matching ALL filters.
    filters: {column: value}  — case-insensitive string comparison.
    """
    mask = pd.Series([True] * len(df), index=df.index)
    for col, val in filters.items():
        if col not in df.columns:
            raise ValueError(f"Column '{col}' not found. Available: {df.columns.tolist()}")
        col_series = df[col]
        if pd.api.types.is_string_dtype(col_series):
            mask &= col_series.str.strip().str.lower() == str(val).strip().lower()
        else:
            mask &= col_series == val
    return mask


def _apply_conditions(df: pd.DataFrame, conditions: list) -> pd.Series:
    """
    Apply a list of condition dicts to produce a boolean mask.
    Each condition: {"column": str, "operator": str, "value": any}
    Operators: eq, neq, gt, gte, lt, lte, contains, startswith
    """
    mask = pd.Series([True] * len(df), index=df.index)
    for cond in conditions:
        col = cond["column"]
        op  = cond["operator"]
        val = cond["value"]

        if col not in df.columns:
            raise ValueError(f"Column '{col}' not found. Available: {df.columns.tolist()}")

        series = df[col]

        if op == "eq":
            if pd.api.types.is_string_dtype(series):
                mask &= series.str.strip().str.lower() == str(val).strip().lower()
            else:
                mask &= series == val
        elif op == "neq":
            if pd.api.types.is_string_dtype(series):
                mask &= series.str.strip().str.lower() != str(val).strip().lower()
            else:
                mask &= series != val
        elif op == "gt":
            mask &= series > val
        elif op == "gte":
            mask &= series >= val
        elif op == "lt":
            mask &= series < val
        elif op == "lte":
            mask &= series <= val
        elif op == "contains":
            mask &= series.astype(str).str.lower().str.contains(str(val).lower(), na=False)
        elif op == "startswith":
            mask &= series.astype(str).str.lower().str.startswith(str(val).lower(), na=False)
        else:
            raise ValueError(f"Unknown operator '{op}'. Use: eq, neq, gt, gte, lt, lte, contains, startswith")
    return mask


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL 1 — query_data
# ═══════════════════════════════════════════════════════════════════════════════

def query_data(file: str, conditions: list = None, columns: list = None,
               order_by: str = None, ascending: bool = True,
               limit: int = 50) -> dict:
    """
    Query rows from a file with optional filtering, column selection, sorting.

    Args:
        file:       "real_estate" or "marketing"
        conditions: list of {"column", "operator", "value"} dicts
        columns:    list of column names to return (None = all)
        order_by:   column name to sort by
        ascending:  sort direction
        limit:      max rows to return (default 50, max 200)

    Returns:
        {"rows": [...], "total_matched": int, "columns": [...]}
    """
    df = _load(file)
    limit = min(int(limit), 200)

    if conditions:
        mask = _apply_conditions(df, conditions)
        df = df[mask]

    total = len(df)

    if order_by:
        if order_by not in df.columns:
            raise ValueError(f"order_by column '{order_by}' not found.")
        df = df.sort_values(order_by, ascending=ascending)

    if columns:
        missing = [c for c in columns if c not in df.columns]
        if missing:
            raise ValueError(f"Columns not found: {missing}. Available: {df.columns.tolist()}")
        df = df[columns]

    rows = _df_to_records(df, max_rows=limit)
    return {"rows": rows, "total_matched": total, "columns": df.columns.tolist()}


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL 2 — aggregate_data
# ═══════════════════════════════════════════════════════════════════════════════

def aggregate_data(file: str, metric: str, column: str,
                   conditions: list = None, group_by: str = None) -> dict:
    """
    Compute summary statistics, optionally grouped.

    Args:
        file:       "real_estate" or "marketing"
        metric:     sum | mean | median | min | max | count | std
        column:     numeric column to aggregate
        conditions: optional filter conditions
        group_by:   optional column to group by before aggregating

    Returns:
        {"result": value_or_dict, "metric": str, "column": str}
    """
    df = _load(file)

    if conditions:
        mask = _apply_conditions(df, conditions)
        df = df[mask]

    if len(df) == 0:
        return {"result": None, "metric": metric, "column": column, "note": "No rows matched filters."}

    if column not in df.columns:
        raise ValueError(f"Column '{column}' not found. Available: {df.columns.tolist()}")

    ops = {
        "sum":    lambda s: float(s.sum()),
        "mean":   lambda s: float(s.mean()),
        "median": lambda s: float(s.median()),
        "min":    lambda s: float(s.min()),
        "max":    lambda s: float(s.max()),
        "count":  lambda s: int(s.count()),
        "std":    lambda s: float(s.std()),
    }
    if metric not in ops:
        raise ValueError(f"Unknown metric '{metric}'. Use: {list(ops.keys())}")

    if group_by:
        if group_by not in df.columns:
            raise ValueError(f"group_by column '{group_by}' not found.")
        grouped = df.groupby(group_by)[column].agg(metric)
        result = {str(k): round(float(v), 4) for k, v in grouped.items()}
    else:
        result = round(ops[metric](df[column]), 4)

    return {"result": result, "metric": metric, "column": column,
            "rows_used": len(df)}


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL 3 — insert_row
# ═══════════════════════════════════════════════════════════════════════════════

def insert_row(file: str, data: dict) -> dict:
    """
    Append a new row to the file.

    Args:
        file: "real_estate" or "marketing"
        data: dict of {column: value} for the new row.
              Missing columns will be filled with None.

    Returns:
        {"inserted": dict, "new_row_count": int}
    """
    df = _load(file)

    # Auto-generate ID if missing
    id_col = "Listing ID" if file == "real_estate" else "Campaign ID"
    if id_col not in data or not data[id_col]:
        prefix = "LST" if file == "real_estate" else "CMP"
        existing_ids = df[id_col].tolist()
        nums = []
        for eid in existing_ids:
            try:
                nums.append(int(str(eid).split("-")[1]))
            except Exception:
                pass
        next_num = max(nums) + 1 if nums else 1
        data[id_col] = f"{prefix}-{next_num}"

    # Build new row aligned to existing columns
    new_row = {col: data.get(col, None) for col in df.columns}

    # Parse date strings for marketing file
    if file == "marketing":
        for date_col in ["Start Date", "End Date"]:
            if date_col in new_row and isinstance(new_row[date_col], str):
                try:
                    new_row[date_col] = pd.to_datetime(new_row[date_col])
                except Exception:
                    pass

    new_df = pd.DataFrame([new_row])
    df = pd.concat([df, new_df], ignore_index=True)
    _save(df, file)

    return {"inserted": new_row, "new_row_count": len(df)}


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL 4 — update_rows
# ═══════════════════════════════════════════════════════════════════════════════

def update_rows(file: str, filters: dict, updates: dict) -> dict:
    """
    Update columns on all rows matching the filter.

    Args:
        file:    "real_estate" or "marketing"
        filters: {column: value} — all conditions ANDed (exact match)
        updates: {column: new_value} — fields to change

    Returns:
        {"rows_updated": int}
    """
    df = _load(file)
    mask = _find_rows(df, filters)
    count = int(mask.sum())

    if count == 0:
        return {"rows_updated": 0, "note": "No rows matched the filter."}

    for col, val in updates.items():
        if col not in df.columns:
            raise ValueError(f"Update column '{col}' not found. Available: {df.columns.tolist()}")
        # Date coercion for marketing
        if file == "marketing" and col in ["Start Date", "End Date"] and isinstance(val, str):
            val = pd.to_datetime(val)
        df.loc[mask, col] = val

    _save(df, file)
    return {"rows_updated": count}


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL 5 — delete_rows
# ═══════════════════════════════════════════════════════════════════════════════

def delete_rows(file: str, filters: dict) -> dict:
    """
    Delete all rows matching the filter.

    Args:
        file:    "real_estate" or "marketing"
        filters: {column: value} exact match conditions (all ANDed)

    Returns:
        {"rows_deleted": int, "remaining_rows": int}
    """
    df = _load(file)
    mask = _find_rows(df, filters)
    count = int(mask.sum())

    if count == 0:
        return {"rows_deleted": 0, "note": "No rows matched the filter. Nothing deleted."}

    df = df[~mask].reset_index(drop=True)
    _save(df, file)
    return {"rows_deleted": count, "remaining_rows": len(df)}


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL 6 — get_schema
# ═══════════════════════════════════════════════════════════════════════════════

def get_schema(file: str) -> dict:
    """
    Return column names, types, sample values, and row count.
    Useful for the LLM to understand available columns before querying.
    """
    df = _load(file)
    schema = {}
    for col in df.columns:
        series = df[col]
        sample = [v for v in series.dropna().head(3).tolist()]
        # Make sample JSON-serialisable
        sample = [str(v) if not isinstance(v, (int, float, bool, type(None))) else v
                  for v in sample]
        schema[col] = {
            "dtype": str(series.dtype),
            "sample": sample,
            "null_count": int(series.isna().sum()),
        }
    return {"file": file, "row_count": len(df), "columns": schema}


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL REGISTRY — maps name → function for the dispatcher
# ═══════════════════════════════════════════════════════════════════════════════

TOOL_REGISTRY = {
    "query_data":     query_data,
    "aggregate_data": aggregate_data,
    "insert_row":     insert_row,
    "update_rows":    update_rows,
    "delete_rows":    delete_rows,
    "get_schema":     get_schema,
}


def dispatch(tool_name: str, tool_args: dict) -> dict:
    """
    Call a tool by name with args dict.
    Returns result dict or {"error": message} on failure.
    """
    if tool_name not in TOOL_REGISTRY:
        return {"error": f"Unknown tool '{tool_name}'. Available: {list(TOOL_REGISTRY.keys())}"}
    try:
        return TOOL_REGISTRY[tool_name](**tool_args)
    except TypeError as e:
        return {"error": f"Bad arguments for '{tool_name}': {e}"}
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Tool '{tool_name}' failed: {type(e).__name__}: {e}"}
