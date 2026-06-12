"""Entity-level temporal feature extraction for the Predictive Track.

Each predictive instance follows a temporal structure:
  - A cutoff date is specified in the question ("before 1997-01-01", "up to 2016-01-24")
  - Historical data BEFORE the cutoff is Dctx (context available to the model)
  - The prediction target is a future aggregate AFTER the cutoff

For each instance we:
  1. Parse the cutoff date / season from the question
  2. Identify the target entity (account 178, carrier WN, team_id 1246, …)
  3. For each table in tables_involved, build aggregate features from the
     entity's historical records (filtered by cutoff date)
  4. Include global (DB-level) aggregates as additional context features
  5. Append recency-weighted features (last 30 / 90 days before cutoff)

Feature vector layout (fixed-length via padding/truncation):
  [entity_hist_feats per table | global_db_feats | question_length_feats]
"""

import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import duckdb
import numpy as np


# ── Numeric type detection ─────────────────────────────────────────────────

_NUMERIC = {"INT", "FLOAT", "DOUBLE", "DECIMAL", "NUMERIC", "REAL",
            "BIGINT", "SMALLINT", "TINYINT", "HUGEINT", "UBIGINT", "UINTEGER"}
_DATE_KW = re.compile(
    r"(date|time|year|month|day|ts|timestamp|created|updated|issued|purchased)",
    re.IGNORECASE,
)
_DATE_TYPE = {"DATE", "TIMESTAMP", "TIME"}


def _is_numeric(dtype: str) -> bool:
    return any(t in dtype.upper() for t in _NUMERIC)


def _is_date_col(col_name: str, dtype: str) -> bool:
    return (
        bool(_DATE_KW.search(col_name))
        or any(t in dtype.upper() for t in _DATE_TYPE)
    )


def _safe(val: Any) -> float:
    try:
        f = float(val)
        return 0.0 if (f != f or abs(f) == float("inf")) else f
    except (TypeError, ValueError):
        return 0.0


# ── Parse cutoff date from question ───────────────────────────────────────

_CUTOFF_RE = re.compile(
    r"(?:before|prior to|up to|leading up to|up until|until|earlier than)"
    r"\s+(\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)
_DATE_BARE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_SEASON_RE    = re.compile(r"\b(20\d{2}|19\d{2})\b")


def parse_cutoff(question: str) -> Optional[str]:
    """Extract the temporal cutoff from a predictive question."""
    m = _CUTOFF_RE.search(question)
    if m:
        return m.group(1)
    dates = _DATE_BARE_RE.findall(question)
    if dates:
        return dates[0]
    return None


def parse_season(question: str) -> Optional[int]:
    """Extract a season/year reference when no ISO date is present."""
    m = _SEASON_RE.search(question)
    return int(m.group(1)) if m else None


# ── Parse entity reference from question ──────────────────────────────────

# Patterns ordered from most specific to most general
_ENTITY_PATTERNS = [
    # e.g. "team_id 1246", "(team_id 1246)"
    re.compile(r'\(?\b(team_id|account_id|client_id|district_id|loan_id|card_id|disp_id)\s+(\d+)\)?', re.IGNORECASE),
    # e.g. "account 178", "client 95", "district 13"
    re.compile(r'\b(account|client|district|loan|card)\s+(\d+)\b', re.IGNORECASE),
    # e.g. "carrier WN", "airport ORD", "origin SFO"
    re.compile(r'\b(carrier|airport|origin|destination|route)\s+([A-Z]{2,4})\b'),
    # e.g. "'SP' state", "state 'SP'"
    re.compile(r"(?:state\s+'([A-Z]{2,4})'|'([A-Z]{2,4})'\s+state)"),
    # e.g. "'cool_stuff' category", "category 'cool_stuff'"
    re.compile(r"(?:'([^']+)'\s+(?:English\s+)?category|category\s+'([^']+)')"),
    # e.g. "the Kentucky Wildcats (team_id 1246)"
    re.compile(r'\(team_id\s+(\d+)\)', re.IGNORECASE),
]


def parse_entity(question: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Returns (entity_keyword, entity_value).
    entity_keyword: the type hint (e.g. 'account', 'carrier', 'district')
    entity_value:   the value to filter on (e.g. '178', 'WN', '13')
    """
    for pat in _ENTITY_PATTERNS:
        m = pat.search(question)
        if m:
            groups = [g for g in m.groups() if g is not None]
            if len(groups) >= 2:
                return groups[0].lower(), groups[1]
            elif len(groups) == 1:
                return None, groups[0]
    return None, None


def _find_entity_col(
    col_names: List[str],
    entity_keyword: Optional[str],
) -> Optional[str]:
    """
    Heuristically find which column stores the entity ID.
    Prefers exact match then partial match.
    """
    if entity_keyword is None:
        return None
    kw = entity_keyword.lower()
    # Exact match
    for c in col_names:
        if c.lower() == kw or c.lower() == kw + "_id":
            return c
    # Partial match
    for c in col_names:
        if kw in c.lower():
            return c
    return None


def _find_date_cols(col_infos: List[tuple]) -> List[str]:
    """Return all date-like column names from PRAGMA table_info output."""
    return [c[1] for c in col_infos if _is_date_col(c[1], c[2])]


def _find_season_col(col_names: List[str]) -> Optional[str]:
    """Find a column that likely represents a season/year."""
    for c in col_names:
        if c.lower() in ("season", "year", "yr"):
            return c
    return None


# ── Per-table entity-level aggregation ────────────────────────────────────

_AGG_STATS = 6  # COUNT, SUM, AVG, MIN, MAX, STDDEV per numeric column
_MAX_NUMERIC_COLS = 5
_RECENCY_SLOTS = 2  # recent-30-day count + recent-90-day count


def _table_entity_features(
    con,
    table:          str,
    col_infos:      List[tuple],
    entity_col:     Optional[str],
    entity_val:     Optional[str],
    cutoff:         Optional[str],
    season:         Optional[int],
) -> List[float]:
    """
    Return aggregate features for one table, filtered by entity + cutoff.
    Layout: [count] + per-numeric-col[6 stats] + [recency-30d, recency-90d]
    """
    col_names   = [c[1] for c in col_infos]
    numeric_cols = [c[1] for c in col_infos if _is_numeric(c[2])][:_MAX_NUMERIC_COLS]
    date_cols   = _find_date_cols(col_infos)
    date_col    = date_cols[0] if date_cols else None
    season_col  = _find_season_col(col_names)

    # Build WHERE clause
    conditions = []
    if entity_col and entity_val and entity_col in col_names:
        # Quote string entities, leave numeric bare
        if entity_val.isdigit():
            conditions.append(f'"{entity_col}" = {entity_val}')
        else:
            conditions.append(f'"{entity_col}" = \'{entity_val}\'')

    if cutoff:
        if date_col:
            conditions.append(f'"{date_col}" < \'{cutoff}\'')
    elif season is not None and season_col:
        conditions.append(f'"{season_col}" < {season}')

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    feats: List[float] = []

    # --- Row count ---
    try:
        n = con.execute(f'SELECT COUNT(*) FROM "{table}" {where}').fetchone()[0]
        feats.append(_safe(n))
    except Exception:
        feats.append(0.0)

    # --- Per-column stats ---
    for col in numeric_cols:
        try:
            row = con.execute(
                f'SELECT SUM("{col}"), AVG("{col}"), MIN("{col}"), '
                f'MAX("{col}"), STDDEV_POP("{col}"), COUNT("{col}") '
                f'FROM "{table}" {where}'
            ).fetchone()
            feats.extend([_safe(v) for v in row])
        except Exception:
            feats.extend([0.0] * _AGG_STATS)

    # Pad to _MAX_NUMERIC_COLS * _AGG_STATS
    pad = _MAX_NUMERIC_COLS - len(numeric_cols)
    feats.extend([0.0] * (pad * _AGG_STATS))

    # --- Recency features ---
    if cutoff and date_col:
        try:
            cutoff_dt = datetime.strptime(cutoff, "%Y-%m-%d")
            for days in (30, 90):
                start = (cutoff_dt - timedelta(days=days)).strftime("%Y-%m-%d")
                cond_recency = conditions.copy()
                # Replace date condition with recency window
                cond_recency = [c for c in cond_recency if date_col not in c]
                cond_recency.append(f'"{date_col}" >= \'{start}\' AND "{date_col}" < \'{cutoff}\'')
                w_recency = f"WHERE {' AND '.join(cond_recency)}"
                cnt = con.execute(
                    f'SELECT COUNT(*) FROM "{table}" {w_recency}'
                ).fetchone()[0]
                feats.append(_safe(cnt))
        except Exception:
            feats.extend([0.0, 0.0])
    else:
        feats.extend([0.0, 0.0])

    return feats


def _feats_per_table() -> int:
    return 1 + _MAX_NUMERIC_COLS * _AGG_STATS + _RECENCY_SLOTS


# ── Global DB-level context features ──────────────────────────────────────

def _global_db_features(con, tables: List[str], max_tables: int = 8) -> List[float]:
    """Row count per table as lightweight global context."""
    feats = []
    for t in tables[:max_tables]:
        try:
            n = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            feats.append(_safe(n))
        except Exception:
            feats.append(0.0)
    feats.extend([0.0] * (max_tables - len(feats)))
    return feats


# ── Public API ─────────────────────────────────────────────────────────────

_MAX_TARGET_TABLES = 4   # max tables_involved per instance
_GLOBAL_TABLES     = 8   # tables for global context
_QUESTION_FEATS    = 3   # question-level meta features


def extract_instance_features(
    inst:       Dict,
    db_path:    str,
    max_target: int = _MAX_TARGET_TABLES,
    max_global: int = _GLOBAL_TABLES,
) -> np.ndarray:
    """
    Build a fixed-length entity-level feature vector for one predictive instance.

    Layout:
      [ entity_hist_feats × max_target_tables
      | global_row_counts × max_global_tables
      | question_meta (cutoff_parsed, entity_found, question_len) ]
    """
    question       = inst["question"]["primary_nl"]
    tables_involved = inst["metadata"]["complexity"].get("tables_involved", [])

    cutoff   = parse_cutoff(question)
    season   = parse_season(question) if cutoff is None else None
    ent_kw, ent_val = parse_entity(question)

    n_per_table = _feats_per_table()
    total_dim   = max_target * n_per_table + max_global + _QUESTION_FEATS
    result      = np.zeros(total_dim, dtype=np.float32)

    try:
        con = duckdb.connect(db_path, read_only=True)
        all_tables = [r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main'"
        ).fetchall()]

        # ── Entity-level features per target table ────────────────────────
        for i, table in enumerate(tables_involved[:max_target]):
            if table not in all_tables:
                continue
            col_infos  = con.execute(f"PRAGMA table_info('{table}')").fetchall()
            col_names  = [c[1] for c in col_infos]
            entity_col = _find_entity_col(col_names, ent_kw)

            feats = _table_entity_features(
                con, table, col_infos,
                entity_col, ent_val, cutoff, season,
            )
            start = i * n_per_table
            arr   = np.array(feats[:n_per_table], dtype=np.float32)
            result[start : start + len(arr)] = arr

        # ── Global DB row counts ──────────────────────────────────────────
        global_feats = _global_db_features(con, all_tables, max_global)
        g_start      = max_target * n_per_table
        result[g_start : g_start + max_global] = global_feats

        con.close()
    except Exception:
        pass

    # ── Question meta ─────────────────────────────────────────────────────
    meta_start = max_target * n_per_table + max_global
    result[meta_start]     = 1.0 if cutoff else 0.0        # cutoff parsed?
    result[meta_start + 1] = 1.0 if ent_val else 0.0       # entity found?
    result[meta_start + 2] = float(len(question)) / 200.0  # question length

    return result
