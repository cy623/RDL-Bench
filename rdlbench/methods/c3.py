"""C3SQL: Zero-shot Text-to-SQL with Self-Consistency.

Faithfully adapted from:
  Dong et al. (2023) — "C3: Zero-shot Text-to-SQL with ChatGPT"
  https://github.com/bigbigwatermalon/C3SQL

Pipeline (matching the original):
  1. Table Recall     — LLM ranks tables by relevance; majority-vote over n samples
  2. Column Recall    — LLM ranks columns per table; frequency-vote top-5
  3. Prompt Assembly  — schema with sample values + FK + calibration tips
  4. SQL Generation   — n samples at temperature 0.7
  5. Self-Consistency — cluster by denotational equivalence, pick largest cluster
"""

import json
import re
from collections import Counter, defaultdict
from itertools import product
from typing import Any, Dict, List, Optional, Set, Tuple

import duckdb
from tqdm import tqdm

from ..database import get_db_path, execute_sql
from ..model    import LLMWrapper
from ..parser   import extract_sql, normalize_sql_result, parse_ground_truth


# ── Schema extraction with sample values ───────────────────────────────────

def _get_db_contents(db_path: str, tables: List[str],
                     max_vals: int = 3) -> Dict[str, Dict[str, List[str]]]:
    """
    For each table/column, fetch up to max_vals distinct non-null string values.
    Returns {table: {col: [val, ...]}}.
    """
    contents: Dict[str, Dict[str, List[str]]] = {}
    try:
        con = duckdb.connect(db_path, read_only=True)
        for t in tables:
            contents[t] = {}
            cols = [c[1] for c in con.execute(f"PRAGMA table_info('{t}')").fetchall()]
            dtypes = {c[1]: c[2] for c in
                      con.execute(f"PRAGMA table_info('{t}')").fetchall()}
            for col in cols:
                dtype = dtypes.get(col, "")
                is_text = any(k in dtype.upper()
                              for k in ("CHAR", "TEXT", "VARCHAR", "STRING"))
                if is_text:
                    try:
                        rows = con.execute(
                            f'SELECT DISTINCT "{col}" FROM "{t}" '
                            f'WHERE "{col}" IS NOT NULL LIMIT {max_vals}'
                        ).fetchall()
                        contents[t][col] = [str(r[0]) for r in rows]
                    except Exception:
                        contents[t][col] = []
                else:
                    contents[t][col] = []
        con.close()
    except Exception:
        pass
    return contents


def _get_fk_strings(db_path: str, tables: List[str]) -> List[str]:
    """Heuristic FK detection via shared column names (DuckDB has no FK metadata)."""
    fks = []
    try:
        con = duckdb.connect(db_path, read_only=True)
        col_map: Dict[str, List[str]] = {}
        for t in tables:
            col_map[t] = [c[1] for c in
                          con.execute(f"PRAGMA table_info('{t}')").fetchall()]
        con.close()
        for i, t1 in enumerate(tables):
            for t2 in tables[i+1:]:
                shared = set(col_map[t1]) & set(col_map[t2]) - {"id"}
                for col in shared:
                    fks.append(f"{t1}.{col} = {t2}.{col}")
    except Exception:
        pass
    return fks


def _build_schema_prompt(
    tables:   List[str],
    contents: Dict[str, Dict[str, List[str]]],
    fks:      List[str],
    db_path:  str,
) -> str:
    """
    Build schema string in C3 format:
      table_name ( col1, col2("val1", "val2"), ... )
      # fk1
    """
    try:
        con = duckdb.connect(db_path, read_only=True)
        lines = []
        for t in tables:
            cols = [c[1] for c in con.execute(f"PRAGMA table_info('{t}')").fetchall()]
            col_parts = []
            for col in cols:
                vals = contents.get(t, {}).get(col, [])
                if vals:
                    val_str = '("' + '", "'.join(vals) + '")'
                    col_parts.append(f"{col}{val_str}")
                else:
                    col_parts.append(col)
            lines.append(f"# {t} ( {', '.join(col_parts)} )")
        con.close()
        schema = "\n".join(lines)
        for fk in fks:
            schema += f"\n# {fk}"
        return schema
    except Exception as e:
        return f"# Schema unavailable: {e}"


# ── Stage 1: Table Recall ─────────────────────────────────────────────────

_TABLE_RECALL_INSTRUCTION = (
    "Given the database schema and question, perform the following actions:\n"
    "1 - Rank all the tables based on the possibility of being used in the SQL "
    "according to the question from the most relevant to the least relevant. "
    "Table or its column that matches more with the question words is highly "
    "relevant and must be placed ahead.\n"
    "2 - Check whether you consider all the tables.\n"
    "3 - Output a list object in the order of step 2. "
    "Your output should contain all the tables. "
    'The format should be like: ["table_1", "table_2", ...]'
)


def _table_recall_prompt(schema_text: str, question: str) -> str:
    return f"{_TABLE_RECALL_INSTRUCTION}\n\nSchema:\n{schema_text}\n\nQuestion:\n{question}"


def _parse_table_list(raw: str, all_tables: List[str]) -> List[str]:
    """Extract table list from LLM output; keep only valid table names."""
    m = re.search(r'\[.*?\]', raw, re.DOTALL)
    if not m:
        return all_tables
    try:
        parsed = json.loads(m.group(0))
        valid = [t for t in parsed if isinstance(t, str)
                 and t.lower() in {x.lower() for x in all_tables}]
        return valid if valid else all_tables
    except Exception:
        return all_tables


def _table_majority_vote(all_results: List[List[str]],
                         all_tables: List[str],
                         top_k: int = 4) -> List[str]:
    """
    Frequency-based voting over table lists (original: counts.most_common).
    Returns the most common table set up to top_k.
    """
    normalized = [tuple(sorted(t.lower() for t in lst[:top_k]))
                  for lst in all_results if lst]
    if not normalized:
        return all_tables
    winner, _ = Counter(normalized).most_common(1)[0]
    # Preserve order from the first matching result
    for lst in all_results:
        if tuple(sorted(t.lower() for t in lst[:top_k])) == winner:
            return lst[:top_k]
    return list(winner)


# ── Stage 2: Column Recall ────────────────────────────────────────────────

_COLUMN_RECALL_INSTRUCTION = (
    "Given the database tables and question, perform the following actions:\n"
    "1 - Rank the columns in each table based on the possibility of being used "
    "in the SQL. Column that matches more with the question words or the "
    "foreign key is highly relevant and must be placed ahead. You should output "
    "them in the order of the most relevant to the least relevant.\n"
    "2 - Output a JSON object that contains all the columns in each table "
    "according to your explanation. The format should be like:\n"
    '{\n  "table_1": ["column_1", "column_2"],\n  "table_2": [...]\n}'
)


def _column_recall_prompt(schema_text: str, question: str,
                           recalled_tables: List[str]) -> str:
    return (
        f"{_COLUMN_RECALL_INSTRUCTION}\n\n"
        f"Tables to consider: {recalled_tables}\n\n"
        f"Schema:\n{schema_text}\n\nQuestion:\n{question}"
    )


def _parse_column_dict(raw: str,
                       table_cols: Dict[str, List[str]]) -> Dict[str, List[str]]:
    """Extract {table: [cols]} from LLM output; keep only valid column names."""
    m = re.search(r'\{.*\}', raw, re.DOTALL)
    if not m:
        return table_cols
    try:
        parsed = json.loads(m.group(0))
        result: Dict[str, List[str]] = {}
        for t, cols in parsed.items():
            if t in table_cols and isinstance(cols, list):
                valid_cols = {c.lower(): c for c in table_cols[t]}
                result[t] = [valid_cols[c.lower()] for c in cols
                             if isinstance(c, str) and c.lower() in valid_cols]
        return result
    except Exception:
        return table_cols


def _column_frequency_vote(all_results: List[Dict[str, List[str]]],
                            table_cols: Dict[str, List[str]],
                            top_k: int = 5) -> Dict[str, List[str]]:
    """
    Per-table frequency voting: select top-k most commonly recalled columns.
    Original: counter.most_common(5)
    """
    candidates: Dict[str, List[str]] = {t: [] for t in table_cols}
    for result in all_results:
        for t, cols in result.items():
            if t in candidates:
                candidates[t].extend(cols)

    final: Dict[str, List[str]] = {}
    for t, col_list in candidates.items():
        if col_list:
            counter = Counter(c.lower() for c in col_list)
            top     = [c for c, _ in counter.most_common(top_k)]
            # Map back to original case
            case_map = {c.lower(): c for c in table_cols[t]}
            final[t] = [case_map[c] for c in top if c in case_map]
        else:
            final[t] = table_cols.get(t, [])
    return final


# ── Stage 3: Prompt assembly ──────────────────────────────────────────────

# Original calibration system turns (Tips 1 & 2 from C3SQL paper)
_CALIBRATION_SYSTEM = (
    "You are now an excellent SQL writer, first I'll give you some tips and "
    "examples, and I need you to remember the tips, and do not make same mistakes.\n\n"
    "Tips 1:\n"
    "Question: Which A has most number of B?\n"
    "Gold SQL: select A from B group by A order by count(*) desc limit 1;\n"
    "Notice that the Gold SQL doesn't select COUNT(*) because the question only "
    "wants to know the A and the number should be only used in ORDER BY clause.\n\n"
    "Tips 2:\n"
    'Don\'t use "IN", "OR", "LEFT JOIN" as it might cause extra results, '
    'use "INTERSECT" or "EXCEPT" instead, and remember to use "DISTINCT" or '
    '"LIMIT" when necessary.\n'
    "For example,\n"
    "Question: Who are the A who have been nominated for both B award and C award?\n"
    "Gold SQL: select A from X where award = 'B' intersect "
    "select A from X where award = 'C';"
)


def _sql_generation_prompt(schema_text: str, question: str) -> str:
    """
    Final prompt in C3 format:
      [calibration system] + schema + question
    Output starts with SELECT (model completes it).
    """
    return (
        f"{_CALIBRATION_SYSTEM}\n\n"
        "### Complete SQL query only and with no explanation, and do not "
        "select extra columns that are not explicitly requested in the query.\n"
        f"### SQL tables, with their properties:\n#\n{schema_text}\n#\n"
        f"### {question}\nSELECT"
    )


# ── Stage 4/5: Self-consistency voting ────────────────────────────────────

def _unorder_row(row: tuple) -> tuple:
    return tuple(sorted(row, key=lambda x: str(x) + str(type(x))))


def _multiset_eq(l1: List, l2: List) -> bool:
    if len(l1) != len(l2):
        return False
    d: Dict[Any, int] = defaultdict(int)
    for e in l1:
        d[e] += 1
    for e in l2:
        d[e] -= 1
        if d[e] < 0:
            return False
    return True


def _quick_rej(r1: List[tuple], r2: List[tuple]) -> bool:
    s1 = {_unorder_row(row) for row in r1}
    s2 = {_unorder_row(row) for row in r2}
    return s1 == s2


def _permute_tuple(t: tuple, perm: tuple) -> tuple:
    return tuple(t[i] for i in perm)


def _result_eq(r1: List[tuple], r2: List[tuple]) -> bool:
    """
    Denotational equivalence check (from get_selfconsistent_output.py).
    Handles unordered rows and column permutations.
    """
    if len(r1) == 0 and len(r2) == 0:
        return True
    if len(r1) != len(r2):
        return False
    if not r1 or not r2:
        return False
    num_cols = len(r1[0])
    if len(r2[0]) != num_cols:
        return False
    if not _quick_rej(r1, r2):
        return False

    # Build per-column value sets for r1
    tab1_sets = [{row[i] for row in r1} for i in range(num_cols)]

    # Prune permutation space using 20 random rows from r2
    import random
    perm_constraints = [set(range(num_cols)) for _ in range(num_cols)]
    sample_r2 = random.sample(r2, min(20, len(r2)))
    for row2 in sample_r2:
        for col1 in range(num_cols):
            for col2 in set(perm_constraints[col1]):
                if row2[col2] not in tab1_sets[col1]:
                    perm_constraints[col1].discard(col2)

    for perm in product(*perm_constraints):
        if len(set(perm)) != num_cols:
            continue
        r2_perm = [_permute_tuple(row, perm) for row in r2]
        if set(r1) == set(r2_perm) and _multiset_eq(r1, r2_perm):
            return True
    return False


def _self_consistency_vote(
    sql_candidates: List[str],
    db_path:        str,
) -> str:
    """
    Execute each SQL, cluster by denotational equivalence,
    return the first SQL from the largest cluster.
    (Original: get_sqls in get_selfconsistent_output.py)
    """
    clusters: List[List[str]] = []
    denotations: Dict[str, List[tuple]] = {}

    for sql in sql_candidates:
        rows, err = execute_sql(sql, db_path)
        if err is not None or rows is None:
            continue
        rows_t = [tuple(r) for r in rows]
        denotations[sql] = rows_t

        matched = False
        for cluster in clusters:
            center = cluster[0]
            if _result_eq(denotations[center], rows_t):
                cluster.append(sql)
                matched = True
                break
        if not matched:
            clusters.append([sql])

    if not clusters:
        return sql_candidates[0] if sql_candidates else ""

    clusters.sort(key=len, reverse=True)
    return clusters[0][0]


# ── Main method ────────────────────────────────────────────────────────────

class C3Method:
    """
    C3SQL: Table Recall → Column Recall → SQL Generation (n samples)
           → Self-Consistency Voting by denotational equivalence.
    """

    def __init__(
        self,
        llm:             LLMWrapper,
        db_dir:          str,
        train_instances: List[Dict],
        cfg:             Dict = None,
    ):
        self.llm    = llm
        self.db_dir = db_dir
        self.train  = train_instances
        self.cfg    = cfg or {}

    def _get_all_tables(self, db_path: str) -> List[str]:
        try:
            con    = duckdb.connect(db_path, read_only=True)
            tables = [r[0] for r in con.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main'"
            ).fetchall()]
            con.close()
            return tables
        except Exception:
            return []

    def _get_table_cols(self, db_path: str,
                        tables: List[str]) -> Dict[str, List[str]]:
        try:
            con = duckdb.connect(db_path, read_only=True)
            result = {}
            for t in tables:
                result[t] = [c[1] for c in
                             con.execute(f"PRAGMA table_info('{t}')").fetchall()]
            con.close()
            return result
        except Exception:
            return {}

    def run(self, instances: List[Dict]) -> List[Dict]:
        n_table  = self.cfg.get("c3_n_table",  5)   # samples for table recall
        n_col    = self.cfg.get("c3_n_col",     5)   # samples for column recall
        n_sql    = self.cfg.get("c3_n_sql",    20)   # samples for SQL generation
        temp     = self.cfg.get("c3_temperature", 0.7)
        max_sql  = self.cfg.get("max_sql_tokens", 512)
        max_meta = self.cfg.get("max_meta_tokens", 512)

        results = []
        for inst in tqdm(instances, desc="C3"):
            domain   = self.cfg.get("db_name") or inst["instance_id"].split("_")[1].lower()
            db_path  = get_db_path(self.db_dir, domain)
            question = inst["question"]["primary_nl"]
            an       = inst["metadata"]["answer_nature"]

            all_tables = self._get_all_tables(db_path)
            table_cols = self._get_table_cols(db_path, all_tables)

            # Build raw schema text (all tables) for recall stages
            contents_all = _get_db_contents(db_path, all_tables)
            fks          = _get_fk_strings(db_path, all_tables)
            schema_all   = _build_schema_prompt(all_tables, contents_all, fks, db_path)

            # ── Stage 1: Table Recall ──────────────────────────────────────
            t_prompt = _table_recall_prompt(schema_all, question)
            t_results: List[List[str]] = []
            for _ in range(n_table):
                raw = self.llm.generate(t_prompt, max_new_tokens=max_meta,
                                        temperature=temp)
                t_results.append(_parse_table_list(raw, all_tables))
            recalled_tables = _table_majority_vote(t_results, all_tables, top_k=4)

            # ── Stage 2: Column Recall ─────────────────────────────────────
            recalled_cols_map = {t: table_cols.get(t, []) for t in recalled_tables}
            c_prompt = _column_recall_prompt(schema_all, question, recalled_tables)
            c_results: List[Dict[str, List[str]]] = []
            for _ in range(n_col):
                raw = self.llm.generate(c_prompt, max_new_tokens=max_meta,
                                        temperature=temp)
                c_results.append(_parse_column_dict(raw, recalled_cols_map))
            recalled_cols = _column_frequency_vote(c_results, recalled_cols_map,
                                                    top_k=5)

            # ── Stage 3: Prompt assembly with recalled schema + FK ─────────
            contents_r = _get_db_contents(db_path, recalled_tables)
            # Override with only recalled columns
            contents_filtered: Dict[str, Dict[str, List[str]]] = {}
            for t in recalled_tables:
                cols = recalled_cols.get(t, table_cols.get(t, []))
                contents_filtered[t] = {
                    c: contents_r.get(t, {}).get(c, []) for c in cols
                }
            schema_recalled = _build_schema_prompt(
                recalled_tables, contents_filtered, fks, db_path
            )
            gen_prompt = _sql_generation_prompt(schema_recalled, question)

            # ── Stage 4: SQL Generation (n samples at temperature 0.7) ─────
            sql_candidates: List[str] = []
            for _ in range(n_sql):
                raw = self.llm.generate(gen_prompt, max_new_tokens=max_sql,
                                        temperature=temp)
                # Original: prepend SELECT (prompt ends with "SELECT")
                sql = "SELECT " + raw.strip().lstrip("SELECT").strip()
                sql = sql.replace("SELECT SELECT", "SELECT")
                sql = sql.replace("> =", ">=").replace("< =", "<=").replace("! =", "!=")
                sql = re.sub(r"\s+", " ", sql).strip()
                sql_candidates.append(sql)

            # ── Stage 5: Self-Consistency Voting ──────────────────────────
            pred_sql  = _self_consistency_vote(sql_candidates, db_path)
            rows, err = execute_sql(pred_sql, db_path)

            pred = normalize_sql_result(rows, an) if err is None else None
            gold = parse_ground_truth(inst["ground_truth"], an)

            results.append({
                "instance_id":   inst["instance_id"],
                "query_type":    inst["metadata"]["query_type"],
                "answer_nature": an,
                "prediction":    pred,
                "gold":          gold,
                "pred_sql":      pred_sql,
                "gold_sql":      inst["evidence"]["golden_sql"],
                "exec_error":    err,
                "recalled_tables": recalled_tables,
                "n_candidates":    len(sql_candidates),
            })
        return results
