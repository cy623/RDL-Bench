"""Temporal masking: build D_ctx and future database from DuckDB.

D_ctx    = all records with timestamp <= reference_time  (for feature construction)
D_future = all records with timestamp in (t_ref, t_end]  (for label construction only)

Tables without a detectable timestamp column are treated as dimension tables
and kept unchanged in both D_ctx and D_future.
"""

import re
from typing import Dict, List, Optional, Tuple

import duckdb


# ── Timestamp column detection ─────────────────────────────────────────────

_DATE_COL_RE = re.compile(
    r"(date|time|timestamp|issued|created|purchased|delivery|"
    r"daynum|flightdate|creationdate)",
    re.IGNORECASE,
)
_DATE_TYPES = {"DATE", "TIMESTAMP", "TIME"}


def _get_col_infos(con, table: str) -> List[tuple]:
    try:
        return con.execute(f"PRAGMA table_info('{table}')").fetchall()
    except Exception:
        return []


def detect_timestamp_col(con, table: str) -> Optional[str]:
    """Return the first datetime-like column name, or None for dimension tables.

    Priority: proper DATE/TIMESTAMP/TIME dtype always wins.  Name-pattern match
    is accepted only when the dtype is NOT a numeric type — this prevents integer
    columns like NCAA's "daynum" (a season-day integer, e.g. 134) from being
    misidentified as a timestamp column.
    """
    _NUMERIC = ("INT", "FLOAT", "DOUBLE", "REAL", "DECIMAL", "NUMERIC")
    for c in _get_col_infos(con, table):
        col_name = c[1]
        dtype    = c[2].upper()
        if any(t in dtype for t in _DATE_TYPES):
            return col_name
        is_numeric = any(t in dtype for t in _NUMERIC)
        if not is_numeric and bool(_DATE_COL_RE.search(col_name)):
            return col_name
    return None


# ── Temporal view builders ─────────────────────────────────────────────────

def _all_tables(con) -> List[str]:
    return [r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'main'"
    ).fetchall()]


def build_dctx_views(
    con,
    reference_time: str,
    table_subset: Optional[List[str]] = None,
) -> Dict[str, str]:
    """
    Return {table: view_sql} for D_ctx (t <= t_ref).
    Dimension tables (no timestamp) get a full-scan view.
    """
    tables = table_subset or _all_tables(con)
    views: Dict[str, str] = {}
    for t in tables:
        ts_col = detect_timestamp_col(con, t)
        if ts_col:
            views[t] = (
                f'SELECT * FROM "{t}" WHERE "{ts_col}" <= \'{reference_time}\''
            )
        else:
            views[t] = f'SELECT * FROM "{t}"'
    return views


def build_future_views(
    con,
    reference_time: str,
    t_end:          Optional[str],
    table_subset:   Optional[List[str]] = None,
) -> Dict[str, str]:
    """
    Return {table: view_sql} for future window (t_ref < t <= t_end).
    Used ONLY for label construction.
    """
    tables = table_subset or _all_tables(con)
    views: Dict[str, str] = {}
    for t in tables:
        ts_col = detect_timestamp_col(con, t)
        if ts_col:
            cond = f'"{ts_col}" > \'{reference_time}\''
            if t_end:
                cond += f' AND "{ts_col}" <= \'{t_end}\''
            views[t] = f'SELECT * FROM "{t}" WHERE {cond}'
        else:
            views[t] = f'SELECT * FROM "{t}"'
    return views


def execute_with_temporal_views(
    con,
    sql:            str,
    table_views:    Dict[str, str],
) -> Tuple[Optional[list], Optional[str]]:
    """
    Execute `sql` replacing each table reference with the appropriate view.
    Uses DuckDB CTEs for clean substitution.
    """
    cte_parts = [f'"{t}" AS ({v})' for t, v in table_views.items()]
    if not cte_parts:
        try:
            return con.execute(sql).fetchall(), None
        except Exception as e:
            return None, str(e)

    full_sql = "WITH\n" + ",\n".join(cte_parts) + "\n" + sql
    try:
        return con.execute(full_sql).fetchall(), None
    except Exception as e:
        return None, str(e)
