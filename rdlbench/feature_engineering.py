"""Entity-level tabular feature engineering from D_ctx.

For each anchor entity, build a feature vector by aggregating
statistics from D_ctx (all records with timestamp <= reference_time).

Feature families per table:
  - COUNT of historical records
  - SUM / AVG / MIN / MAX / STDDEV of numeric columns
  - COUNT of distinct related entities
  - Recency: record count in last 30 / 90 days before t_ref
  - Days-since-last-event (if timestamp column exists)

Output: one row per anchor entity, columns = named features.
Missing entities (no history) get all-zero features.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .temporal_masking import detect_timestamp_col, build_dctx_views, execute_with_temporal_views


_MAX_NUMERIC_COLS = 6      # per table
_NUMERIC_TYPES    = {"INT", "FLOAT", "DOUBLE", "DECIMAL", "NUMERIC", "REAL",
                     "BIGINT", "SMALLINT", "TINYINT", "HUGEINT", "UBIGINT", "UINTEGER"}


def _is_numeric(dtype: str) -> bool:
    return any(t in dtype.upper() for t in _NUMERIC_TYPES)


def _safe(v) -> float:
    try:
        f = float(v)
        return 0.0 if (f != f or abs(f) == float("inf")) else f
    except (TypeError, ValueError):
        return 0.0


def _get_col_infos(con, table: str) -> List[tuple]:
    try:
        return con.execute(f"PRAGMA table_info('{table}')").fetchall()
    except Exception:
        return []


# ── Per-table feature SQL builder ──────────────────────────────────────────

def _build_table_feature_sql(
    table:       str,
    anchor_col:  str,
    col_infos:   List[tuple],
    t_ref:       str,
    ts_col:      Optional[str],
) -> Tuple[str, List[str]]:
    """
    Build a SQL that returns (anchor_col, feature_1, ...) from D_ctx.
    Returns (sql, feature_names).
    """
    col_names  = [c[1] for c in col_infos]
    num_cols   = [c[1] for c in col_infos
                  if _is_numeric(c[2]) and c[1] != anchor_col][:_MAX_NUMERIC_COLS]

    agg_exprs  : List[str] = []
    feat_names : List[str] = []

    # --- row count ---
    agg_exprs.append(f'COUNT(*) AS {table}__count')
    feat_names.append(f'{table}__count')

    # --- numeric aggregates ---
    for col in num_cols:
        for agg, sfx in [("SUM",     "sum"),
                         ("AVG",     "avg"),
                         ("MIN",     "min"),
                         ("MAX",     "max"),
                         ("STDDEV_POP", "std")]:
            name = f'{table}__{col}__{sfx}'
            agg_exprs.append(f'{agg}("{col}") AS {name}')
            feat_names.append(name)

    # --- recency features (needs timestamp col) ---
    if ts_col:
        try:
            t_ref_dt = datetime.strptime(t_ref[:10], "%Y-%m-%d")
            for days, sfx in [(30, "rec30"), (90, "rec90")]:
                start = (t_ref_dt - timedelta(days=days)).strftime("%Y-%m-%d")
                name  = f'{table}__{sfx}'
                agg_exprs.append(
                    f'COUNT(CASE WHEN "{ts_col}" >= \'{start}\' THEN 1 END) AS {name}'
                )
                feat_names.append(name)

            # days-since-last-event
            name = f'{table}__days_since_last'
            agg_exprs.append(
                f"DATEDIFF('day', MAX(\"{ts_col}\"), DATE '{t_ref}') AS {name}"
            )
            feat_names.append(name)
        except ValueError:
            pass

    # --- distinct related entities ---
    related_cols = [c[1] for c in col_infos
                    if c[1] != anchor_col
                    and c[1].lower().endswith("_id")
                    and not _is_numeric(c[2])][:3]
    for col in related_cols:
        name = f'{table}__{col}__nunique'
        agg_exprs.append(f'COUNT(DISTINCT "{col}") AS {name}')
        feat_names.append(name)

    # Build D_ctx WHERE clause
    where = f'WHERE "{ts_col}" <= \'{t_ref}\'' if ts_col else ""

    sql = (
        f'SELECT "{anchor_col}", {", ".join(agg_exprs)} '
        f'FROM "{table}" {where} '
        f'GROUP BY "{anchor_col}"'
    )
    return sql, feat_names


# ── Main feature builder ────────────────────────────────────────────────────

def build_tabular_features(
    con,
    anchor_col:      str,
    anchor_entities: List,
    involved_tables: List[str],
    reference_time:  str,
) -> pd.DataFrame:
    """
    Return a DataFrame indexed by anchor_col with one feature column per stat.

    Entities with no historical records get all-zero feature rows.
    """
    all_tables = [r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'main'"
    ).fetchall()]

    # Start with the anchor entity list as the base
    base_df = pd.DataFrame({anchor_col: anchor_entities})

    for table in involved_tables:
        if table not in all_tables:
            continue
        col_infos = _get_col_infos(con, table)
        col_names = [c[1] for c in col_infos]
        if anchor_col not in col_names:
            continue  # table doesn't contain anchor_col

        ts_col = detect_timestamp_col(con, table)
        feat_sql, feat_names = _build_table_feature_sql(
            table, anchor_col, col_infos, reference_time, ts_col
        )

        try:
            rows = con.execute(feat_sql).fetchall()
        except Exception as e:
            continue

        if not rows:
            continue

        tbl_df = pd.DataFrame(rows, columns=[anchor_col] + feat_names)
        # Safe cast
        for col in feat_names:
            tbl_df[col] = pd.to_numeric(tbl_df[col], errors="coerce").fillna(0.0)
        # Coerce anchor_col type for merge
        try:
            base_df[anchor_col] = base_df[anchor_col].astype(type(rows[0][0]))
            tbl_df[anchor_col]  = tbl_df[anchor_col].astype(type(rows[0][0]))
        except Exception:
            pass

        base_df = base_df.merge(tbl_df, on=anchor_col, how="left")

    # Fill NaNs with 0 (entities with no history)
    feature_cols = [c for c in base_df.columns if c != anchor_col]
    base_df[feature_cols] = base_df[feature_cols].fillna(0.0)

    return base_df
