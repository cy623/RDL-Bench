"""PredictiveTaskTemplate: parse each Predictive instance into a task template.

Each Predictive Track instance defines a forecasting task:
  - anchor_table / anchor_key : the entity type being predicted over
  - reference_time            : temporal cutoff (D_ctx = records <= t_ref)
  - t_end                     : end of prediction window (from golden_sql)
  - target_sql                : label-construction SQL (entity-parameterized)
  - task_type                 : "classification" (Boolean) or "regression" (Scalar)

Native predictive solvers (XGBoost, GNN, …) use oracle metadata directly.
They do NOT parse primary_nl — that is reserved for LLM-only / LLM-Router.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Answer-nature normalisation ────────────────────────────────────────────

def normalize_answer_nature(x: str) -> str:
    return {
        "Boolean":  "Boolean",
        "Booleans": "Boolean",
        "Scalar":   "Scalar",
        "Scalars":  "Scalar",
        "Set":      "Set",
        "Sets":     "Set",
        "Ranking":  "Ranking",
        "Rankings": "Ranking",
    }.get(x, x)


def is_trainable(instance: Dict) -> bool:
    """True iff this instance can be used for trained predictive baselines."""
    if instance["metadata"].get("query_type") != "Predictive":
        return False
    return normalize_answer_nature(
        instance["metadata"].get("answer_nature", "")
    ) in ("Boolean", "Scalar")


# ── SQL parsing helpers ────────────────────────────────────────────────────

# Matches table aliases: "account a", "loan AS l"
_ALIAS_RE = re.compile(r'\b(\w+)(?:\s+(?:AS\s+)?\w+)?', re.IGNORECASE)

# Date/timestamp literals
_DATE_LIT_RE = re.compile(r'\d{4}-\d{2}-\d{2}')

# Temporal columns by name
_TEMPORAL_COL_NAMES = {
    "date", "time", "timestamp", "flightdate", "issued", "created",
    "creationdate", "order_purchase_timestamp", "order_delivered_customer_date",
    "birth_date", "daynum", "season",
}


def _strip_alias(col_expr: str) -> str:
    """'t.account_id'  →  'account_id'"""
    return col_expr.split(".")[-1]


def _parse_from_table(sql: str) -> Optional[str]:
    """Return the first table name after FROM."""
    m = re.search(r'\bFROM\s+(\w+)', sql, re.IGNORECASE)
    return m.group(1) if m else None


def _parse_where_conditions(sql: str) -> List[Tuple[str, str]]:
    """
    Extract (col, val) equality conditions from WHERE clause.
    Returns stripped column names (no aliases) and raw values.
    """
    where_m = re.search(
        r'\bWHERE\b(.+?)(?:\bGROUP BY\b|\bORDER BY\b|\bLIMIT\b|$)',
        sql, re.IGNORECASE | re.DOTALL,
    )
    if not where_m:
        return []

    clause = where_m.group(1)
    # Match col = val patterns (numeric or single-quoted string)
    raw = re.findall(
        r'(\w+(?:\.\w+)?)\s*=\s*(\d+|\'[^\']*\')',
        clause,
    )
    results = []
    for col_expr, val in raw:
        col = _strip_alias(col_expr)
        results.append((col, val.strip("'")))
    return results


def _is_temporal_condition(col: str, val: str) -> bool:
    return (
        col.lower() in _TEMPORAL_COL_NAMES
        or bool(_DATE_LIT_RE.search(val))
    )


def _parse_anchor(sql: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Find the first non-temporal equality condition in WHERE.
    Returns (anchor_col, anchor_val) or (None, None).

    Handles:
      account_id = 178
      carrier = 'WN'
      district_id = 13
      p.owneruserid = 25078  → owneruserid
    """
    conditions = _parse_where_conditions(sql)
    for col, val in conditions:
        if not _is_temporal_condition(col, val):
            return col, val
    # Fallback: OR-pattern for NCAA-style (wteam = X OR lteam = X)
    m = re.search(
        r'\(\s*(\w+)\s*=\s*(\d+)\s*OR\s*\w+\s*=\s*\2\s*\)',
        sql, re.IGNORECASE,
    )
    if m:
        return m.group(1), m.group(2)
    return None, None


def _parse_t_ref(instance: Dict) -> Optional[str]:
    """Read reference_time from metadata (already provided by benchmark)."""
    t = instance["metadata"].get("reference_time")
    if t:
        return str(t).split(" ")[0]   # strip HH:MM:SS if present
    return None


def _parse_t_end(sql: str) -> Optional[str]:
    """Parse upper bound of prediction window from golden_sql."""
    # <= 'YYYY-MM-DD' or < 'YYYY-MM-DD HH:MM:SS'
    for op in (r"<=?", r"<"):
        m = re.search(
            op + r"\s*'(\d{4}-\d{2}-\d{2})",
            sql, re.IGNORECASE,
        )
        if m:
            return m.group(1)
    return None


# ── Entity-level label SQL rewriting ──────────────────────────────────────

def _make_entity_level_sql(
    original_sql: str,
    anchor_col:   str,
    anchor_val:   str,
) -> Optional[str]:
    """
    Transform a single-entity golden_sql into an entity-level label SQL:
      SELECT <anchor_col>, <agg_expr> FROM ...
      WHERE <temporal_conditions>           ← entity filter removed
      GROUP BY <anchor_col>

    Returns None if rewriting fails.
    """
    sql = original_sql.strip().rstrip(";")

    # Remove entity filter (handles both "col = val AND ..." and "... AND col = val")
    # Patterns to remove (with possible table alias prefix)
    quote_val = re.escape(anchor_val)
    col_pat   = re.escape(anchor_col)

    patterns = [
        # Dot-qualified: "t.anchor_col = val"
        rf'\b\w+\.{col_pat}\s*=\s*(?:{quote_val}|' + f"'{quote_val}'" + r')\s*AND\s*',
        rf'AND\s*\b\w+\.{col_pat}\s*=\s*(?:{quote_val}|' + f"'{quote_val}'" + r')',
        # Plain: "anchor_col = val"
        rf'\b{col_pat}\s*=\s*(?:{quote_val}|' + f"'{quote_val}'" + r')\s*AND\s*',
        rf'AND\s*\b{col_pat}\s*=\s*(?:{quote_val}|' + f"'{quote_val}'" + r')',
        # Only condition
        rf'WHERE\s+\b{col_pat}\s*=\s*(?:{quote_val}|' + f"'{quote_val}'" + r')\b',
        # OR pattern: "(wteam = X OR lteam = X)"
        rf'\(\s*\w+\s*=\s*{quote_val}\s*OR\s*\w+\s*=\s*{quote_val}\s*\)',
    ]

    modified = sql
    for pat in patterns:
        modified = re.sub(pat, '', modified, flags=re.IGNORECASE).strip()

    # If WHERE was removed entirely (only had entity filter), re-add WHERE placeholder
    if not re.search(r'\bWHERE\b', modified, re.IGNORECASE):
        # No temporal conditions left → WHERE still needed for GROUP BY to work
        modified = re.sub(
            r'\bFROM\b(\s+\w+.*?)(\bGROUP BY\b|$)',
            lambda m: m.group(0),  # keep as-is; GROUP BY added below
            modified, flags=re.IGNORECASE,
        )

    # Add GROUP BY if not present
    if not re.search(r'\bGROUP BY\b', modified, re.IGNORECASE):
        modified = modified + f' GROUP BY {anchor_col}'

    # Inject anchor_col into SELECT clause
    # Handles "SELECT agg" → "SELECT anchor_col, agg as label"
    select_m = re.match(r'(SELECT\s+)(.*?)(\s+FROM\b)', modified,
                        re.IGNORECASE | re.DOTALL)
    if not select_m:
        return None

    agg_expr = select_m.group(2).strip()
    # Avoid double-injecting
    if anchor_col.lower() not in agg_expr.lower().split(",")[0].lower():
        modified = (
            f"SELECT {anchor_col}, {agg_expr} AS label"
            + modified[select_m.end(2):]
        )

    return modified


# ── PredictiveTaskTemplate ─────────────────────────────────────────────────

@dataclass
class PredictiveTaskTemplate:
    instance_id:       str
    domain:            str
    question:          str
    answer_nature:     str                  # "Boolean" or "Scalar"
    task_type:         str                  # "classification" or "regression"
    anchor_table:      str
    anchor_col:        str                  # entity grouping column
    involved_tables:   List[str]
    reference_time:    str                  # t_ref (D_ctx cutoff)
    t_end:             Optional[str]        # end of prediction window
    target_sql:        str                  # entity-level label SQL
    original_sql:      str                  # original golden_sql (for reference)
    metadata:          Dict = field(default_factory=dict)


def build_predictive_task_template(
    instance: Dict,
    db_path:  str,           # path to .duckdb file (for schema lookup)
) -> Optional[PredictiveTaskTemplate]:
    """
    Parse a Predictive instance into a PredictiveTaskTemplate.
    Returns None (with a warning) if the instance cannot be parameterized.
    """
    iid        = instance["instance_id"]
    meta       = instance["metadata"]
    golden_sql = instance["evidence"]["golden_sql"]
    an         = normalize_answer_nature(meta.get("answer_nature", ""))

    if an not in ("Boolean", "Scalar"):
        logger.debug(f"Skip {iid}: answer_nature={an} not trainable")
        return None

    # ── oracle metadata ────────────────────────────────────────────────────
    t_ref           = _parse_t_ref(instance)
    involved_tables = meta["complexity"].get("tables_involved", [])
    anchor_table    = _parse_from_table(golden_sql) or (
        involved_tables[0] if involved_tables else None
    )

    if not t_ref or not anchor_table:
        logger.warning(f"Skip {iid}: missing reference_time or anchor_table")
        return None

    # ── anchor entity ──────────────────────────────────────────────────────
    anchor_col, anchor_val = _parse_anchor(golden_sql)
    if not anchor_col:
        logger.warning(
            f"Skip {iid}: no entity filter found in golden_sql — "
            "aggregate-level instance, not usable for trained baselines"
        )
        return None

    t_end = _parse_t_end(golden_sql)

    # ── entity-level label SQL ─────────────────────────────────────────────
    entity_sql = _make_entity_level_sql(golden_sql, anchor_col, anchor_val)
    if not entity_sql:
        logger.warning(f"Skip {iid}: failed to rewrite SQL as entity-level")
        return None

    # ── domain ────────────────────────────────────────────────────────────
    domain = iid.split("_")[1].lower() if "_" in iid else "unknown"

    return PredictiveTaskTemplate(
        instance_id     = iid,
        domain          = domain,
        question        = instance["question"]["primary_nl"],
        answer_nature   = an,
        task_type       = "classification" if an == "Boolean" else "regression",
        anchor_table    = anchor_table,
        anchor_col      = anchor_col,
        involved_tables = involved_tables,
        reference_time  = t_ref,
        t_end           = t_end,
        target_sql      = entity_sql,
        original_sql    = golden_sql,
        metadata        = meta,
    )
