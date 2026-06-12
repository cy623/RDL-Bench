"""DuckDB connection, schema extraction, and 2-hop context retrieval."""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import duckdb
import numpy as np
from rank_bm25 import BM25Okapi


def get_db_path(db_dir: str, domain: str) -> str:
    """Resolve the .duckdb file for a domain."""
    # If db_dir is directly a .duckdb file, use it
    if Path(db_dir).is_file():
        return db_dir
    # Try exact matches first
    for base in [Path(db_dir) / domain, Path(db_dir)]:
        for name in [domain, domain.upper(), domain.capitalize()]:
            p = base / f"{name}.duckdb"
            if p.exists():
                return str(p)
    # Fuzzy fallback: any .duckdb whose stem starts with domain
    for p in sorted(Path(db_dir).glob("*.duckdb")):
        if p.stem.lower().startswith(domain.lower()):
            return str(p)
    raise FileNotFoundError(
        f"No .duckdb file found for domain '{domain}' in {db_dir}"
    )


def _connect(db_path: str):
    return duckdb.connect(db_path, read_only=True)


def get_table_names(db_path: str) -> List[str]:
    con = _connect(db_path)
    tables = [r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'main'"
    ).fetchall()]
    con.close()
    return tables


def get_columns(db_path: str, table: str) -> List[str]:
    con = _connect(db_path)
    cols = [c[1] for c in con.execute(
        f"PRAGMA table_info('{table}')"
    ).fetchall()]
    con.close()
    return cols


def get_schema(db_path: str) -> str:
    """Extract CREATE TABLE DDL (or PRAGMA fallback) from the database."""
    try:
        con     = _connect(db_path)
        tables  = [r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main'"
        ).fetchall()]
        parts = []
        for t in tables:
            cols = con.execute(f"PRAGMA table_info('{t}')").fetchall()
            col_defs = ",\n  ".join(
                f"{c[1]} {c[2]}" + (" PRIMARY KEY" if c[5] else "")
                for c in cols
            )
            parts.append(f"CREATE TABLE {t} (\n  {col_defs}\n);")
        con.close()
        return "\n\n".join(parts)
    except Exception as e:
        return f"-- Schema unavailable: {e}"


def get_profiling_summary(db_path: str, sample_rows: int = 3) -> str:
    """
    Aggregate statistics over the full database (proxy for D_ctx).
    Returns a text summary for LLM-only prompts.
    """
    try:
        con    = _connect(db_path)
        tables = [r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main'"
        ).fetchall()]
        lines = []
        for t in tables:
            count  = con.execute(f"SELECT COUNT(*) FROM \"{t}\"").fetchone()[0]
            sample = con.execute(
                f"SELECT * FROM \"{t}\" LIMIT {sample_rows}"
            ).fetchall()
            cols = [c[1] for c in con.execute(
                f"PRAGMA table_info('{t}')"
            ).fetchall()]
            lines.append(f"Table {t}: {count} rows | columns: {', '.join(cols)}")
            if sample:
                lines.append(f"  sample: {sample[0]}")
        con.close()
        return "\n".join(lines)
    except Exception as e:
        return f"-- Profiling unavailable: {e}"


def get_two_hop_context(
    question:           str,
    db_path:            str,
    bm25_top_n:         int = 3,
    max_context_tables: int = 6,
    sample_rows:        int = 3,
) -> str:
    """
    BM25-based 2-hop relational context retrieval.
    Steps:
      1. BM25 match question tokens → top-n candidate tables
      2. Expand candidates via shared column names (FK proxy)
      3. Include sample_rows representative rows per table
    """
    try:
        con    = _connect(db_path)
        tables = [r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main'"
        ).fetchall()]

        # Build BM25 corpus: [table_name, col1, col2, ...]
        col_map = {}
        corpus  = []
        for t in tables:
            cols = [c[1] for c in con.execute(
                f"PRAGMA table_info('{t}')"
            ).fetchall()]
            col_map[t] = cols
            corpus.append([t.lower()] + [c.lower() for c in cols])

        bm25      = BM25Okapi(corpus)
        scores    = bm25.get_scores(question.lower().split())
        top_idx   = np.argsort(scores)[-bm25_top_n:][::-1]
        top_tables = [tables[i] for i in top_idx]

        # 2-hop expansion: connect tables sharing column names
        expanded = set(top_tables)
        for t in list(top_tables):
            t_cols = set(col_map[t])
            for other in tables:
                if other in expanded:
                    continue
                if t_cols & set(col_map[other]):
                    expanded.add(other)

        # Build context string
        parts = []
        for t in list(expanded)[:max_context_tables]:
            rows = con.execute(
                f"SELECT * FROM \"{t}\" LIMIT {sample_rows}"
            ).fetchall()
            cols = col_map[t]
            parts.append(
                f"-- Table: {t}\n"
                f"-- Columns: {', '.join(cols)}\n"
                f"-- Sample rows: {rows}"
            )

        con.close()
        return "\n\n".join(parts) if parts else "-- No context retrieved"

    except Exception as e:
        return f"-- 2-hop context unavailable: {e}"


def execute_sql(
    sql:     str,
    db_path: str,
) -> Tuple[Optional[List], Optional[str]]:
    """
    Execute SQL via DuckDB.
    Returns (rows, error). rows is a list of tuples; None on error.
    """
    try:
        con  = _connect(db_path)
        rows = con.execute(sql).fetchall()
        con.close()
        return rows, None
    except Exception as e:
        return None, str(e)
