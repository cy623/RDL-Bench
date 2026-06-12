"""Output parsing: SQL extraction, prediction extraction, answer normalization."""

import json
import re
from typing import Any, Dict, List, Optional


def extract_sql(raw: str) -> str:
    """Extract SQL query from LLM output."""
    # 1. Fenced code block
    m = re.search(r"```(?:sql)?\s*(.*?)```", raw, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    # 2. From SELECT / WITH keyword
    m = re.search(r"(SELECT|WITH)\b", raw, re.IGNORECASE)
    if m:
        return raw[m.start():].split("\n\n")[0].strip()
    return raw.strip()


def extract_prediction(raw: str, answer_nature: str) -> Any:
    """Extract a scalar or boolean prediction from LLM output."""
    text = raw.strip()
    if answer_nature == "Boolean":
        lower = text.lower()
        if re.search(r"\byes\b", lower):
            return True
        if re.search(r"\bno\b", lower):
            return False
        return None
    # Scalar: first numeric token
    m = re.search(r"-?\d+(?:[.,]\d+)?", text)
    if m:
        val = m.group(0).replace(",", ".")
        return float(val) if "." in val else int(val)
    return None


def parse_router_output(raw: str) -> Dict:
    """Parse LLM-Router JSON with fallback to Reasoning track."""
    try:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            obj = json.loads(m.group(0))
            # Normalise track name
            obj["track"] = (
                "Predictive"
                if str(obj.get("track", "")).lower() == "predictive"
                else "Reasoning"
            )
            return obj
    except Exception:
        pass
    return {
        "track":           "Reasoning",
        "query_type":      "Retrieval",
        "answer_nature":   "Sets",
        "tables_involved": [],
    }


def normalize_sql_result(rows: Optional[List], answer_nature: str) -> Any:
    """Convert DuckDB rows to a Python value matching answer_nature."""
    if rows is None:
        return None
    if not rows:
        return [] if answer_nature in ("Sets", "Rankings") else None

    flat = [r[0] if len(r) == 1 else r for r in rows]

    if answer_nature == "Boolean":
        val = flat[0]
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.strip().lower() in ("yes", "true", "1", "t")
        try:
            return bool(int(val))
        except (TypeError, ValueError):
            return bool(val)

    if answer_nature == "Scalars":
        val = flat[0]
        try:
            f = float(str(val))
            return int(f) if f == int(f) else f
        except (TypeError, ValueError):
            return val

    if answer_nature == "Rankings":
        return [str(v) for v in flat]

    # Sets
    return [str(v) for v in flat]


def parse_ground_truth(gt: Dict, answer_nature: str) -> Any:
    """Parse ground_truth.raw_value into a comparable Python object."""
    raw = gt.get("raw_value")
    if raw is None:
        return None

    if answer_nature == "Boolean":
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            return raw.strip().lower() in ("yes", "true", "1", "t")
        return bool(raw)

    if answer_nature == "Scalars":
        try:
            f = float(str(raw))
            return int(f) if f == int(f) else f
        except (TypeError, ValueError):
            return raw

    if answer_nature == "Sets":
        if isinstance(raw, dict):          # {total_count, values, is_truncated}
            return [str(v) for v in raw.get("values", [])]
        if isinstance(raw, list):
            return [str(v) for v in raw]
        return [str(raw)]

    if answer_nature == "Rankings":
        if isinstance(raw, list):
            return [str(v) for v in raw]
        return [str(raw)]

    return raw
