"""DIN-SQL: Decomposed In-Context Learning for Text-to-SQL.

Faithfully adapted from:
  Pourreza & Rafiei (2023) — "DIN-SQL: Decomposed In-Context Learning of
  Text-to-SQL with Self-Correction"
  https://github.com/MohammadrezaPourreza/Few-shot-NL2SQL-with-prompting

4-stage pipeline (matching the original):
  1. Schema Linking   — step-by-step table/column/value identification
  2. Classification   — EASY / NON-NESTED / NESTED
  3. SQL Generation   — difficulty-specific prompt (3 variants)
  4. Self-Correction  — validate and fix the generated SQL
"""

import re
from typing import Dict, List, Optional

from tqdm import tqdm

from ..database import get_db_path, execute_sql
from ..dataset  import get_few_shot_examples
from ..model    import LLMWrapper
from ..parser   import extract_sql, normalize_sql_result, parse_ground_truth


# ── Schema formatting (DIN-SQL style) ─────────────────────────────────────

def _din_schema(db_path: str) -> str:
    """
    Format schema as DIN-SQL expects:
      Table t, columns = [*, col1, col2]
      Foreign_keys = [t1.col = t2.col, ...]
    """
    import duckdb
    try:
        con = duckdb.connect(db_path, read_only=True)
        tables = [r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main'"
        ).fetchall()]

        lines = []
        for t in tables:
            cols = [c[1] for c in con.execute(f"PRAGMA table_info('{t}')").fetchall()]
            lines.append(f"Table {t}, columns = [*, {', '.join(cols)}]")

        # DuckDB does not expose FK metadata via PRAGMA — use column name heuristic
        fk_lines = []
        col_map = {}
        for t in tables:
            cols = [c[1] for c in con.execute(f"PRAGMA table_info('{t}')").fetchall()]
            col_map[t] = set(cols)
        for i, t1 in enumerate(tables):
            for t2 in tables[i+1:]:
                shared = col_map[t1] & col_map[t2] - {"id"}
                for col in shared:
                    fk_lines.append(f"{t1}.{col} = {t2}.{col}")

        con.close()
        schema = "\n".join(lines)
        if fk_lines:
            schema += "\nForeign_keys = [" + ", ".join(fk_lines) + "]"
        return schema
    except Exception as e:
        return f"-- Schema unavailable: {e}"


# ── Few-shot example formatting helpers ────────────────────────────────────

def _complexity_label(inst: Dict) -> str:
    """Map instance complexity to DIN-SQL label."""
    features = inst["metadata"]["complexity"].get("sql_features", [])
    level    = inst["metadata"]["complexity"].get("level", "Easy")
    has_nested = any(
        any(kw in f.upper() for kw in ["NESTED", "SUBQUERY", "INTERSECT", "UNION", "EXCEPT"])
        for f in features
    )
    has_join   = any(f in features for f in ["JOIN", "MULTI_TABLE"])
    if has_nested:
        return "NESTED"
    if has_join or level in ("Medium", "Hard"):
        return "NON-NESTED"
    return "EASY"


def _shot_schema_link(inst: Dict) -> str:
    tables = inst["metadata"]["complexity"].get("tables_involved", [])
    sql    = inst["evidence"]["golden_sql"]
    # Extract column references from SQL heuristically
    cols   = re.findall(r'\b(\w+\.\w+)\b', sql)
    links  = list(dict.fromkeys(
        [f"{t}.*" for t in tables] + cols
    ))[:8]
    return "[" + ", ".join(links) + "]"


def _shot_schema_link_block(inst: Dict) -> str:
    return (
        f"Q: \"{inst['question']['primary_nl']}\"\n"
        f"A: Let's think step by step. "
        f"The tables needed are {inst['metadata']['complexity'].get('tables_involved', [])}. "
        f"Based on the tables and columns, the Schema_links are:\n"
        f"Schema_links: {_shot_schema_link(inst)}"
    )


def _shot_classify_block(inst: Dict) -> str:
    label  = _complexity_label(inst)
    tables = inst["metadata"]["complexity"].get("tables_involved", [])
    links  = _shot_schema_link(inst)
    if label == "EASY":
        reason = f"We need table(s) = {tables}, no JOIN and no nested queries needed."
    elif label == "NON-NESTED":
        reason = f"We need to join tables = {tables}, but no nested subqueries."
    else:
        reason = f"The query requires nested subqueries or set operations."
    return (
        f"Q: \"{inst['question']['primary_nl']}\"\n"
        f"schema_links: {links}\n"
        f"A: Let's think step by step. {reason}\n"
        f"Label: \"{label}\""
    )


def _shot_easy_block(inst: Dict) -> str:
    return (
        f"Q: \"{inst['question']['primary_nl']}\"\n"
        f"Schema_links: {_shot_schema_link(inst)}\n"
        f"SQL: {inst['evidence']['golden_sql']}"
    )


def _shot_nonnested_block(inst: Dict) -> str:
    tables = inst["metadata"]["complexity"].get("tables_involved", [])
    return (
        f"Q: \"{inst['question']['primary_nl']}\"\n"
        f"Schema_links: {_shot_schema_link(inst)}\n"
        f"A: Let's think step by step. "
        f"We need to join tables = {tables}.\n"
        f"Intermediate_representation: {inst['evidence']['golden_sql']}\n"
        f"SQL: {inst['evidence']['golden_sql']}"
    )


def _shot_nested_block(inst: Dict) -> str:
    return (
        f"Q: \"{inst['question']['primary_nl']}\"\n"
        f"Schema_links: {_shot_schema_link(inst)}\n"
        f"A: Let's think step by step. This query requires a nested subquery.\n"
        f"Intermediate_representation: {inst['evidence']['golden_sql']}\n"
        f"SQL: {inst['evidence']['golden_sql']}"
    )


# ── Stage prompts ──────────────────────────────────────────────────────────

def _prompt_schema_linking(question: str, schema: str, shots: List[Dict]) -> str:
    shot_text = "\n\n".join(_shot_schema_link_block(s) for s in shots)
    return (
        "# Given the database schema and question, perform schema linking and "
        "identify the relevant tables, columns, and values.\n\n"
        f"{schema}\n\n"
        f"{shot_text}\n\n"
        f"Q: \"{question}\"\n"
        "A: Let's think step by step."
    )


def _prompt_classify(
    question: str, schema_links: str, schema: str, shots: List[Dict]
) -> str:
    shot_text = "\n\n".join(_shot_classify_block(s) for s in shots)
    return (
        "# Classify the SQL query as EASY, NON-NESTED, or NESTED.\n"
        "# EASY: single table, no JOIN, no nested queries.\n"
        "# NON-NESTED: requires JOIN but no nested subqueries.\n"
        "# NESTED: requires nested subqueries (IN, NOT IN, INTERSECT, UNION, EXCEPT).\n\n"
        f"{schema}\n\n"
        f"{shot_text}\n\n"
        f"Q: \"{question}\"\n"
        f"schema_links: {schema_links}\n"
        "A: Let's think step by step."
    )


def _prompt_easy(question: str, schema_links: str, schema: str, shots: List[Dict]) -> str:
    shot_text = "\n\n".join(_shot_easy_block(s) for s in shots)
    return (
        "# Use the schema links to generate the SQL query. "
        "Output only the SQL after 'SQL:'.\n\n"
        f"{schema}\n\n"
        f"{shot_text}\n\n"
        f"Q: \"{question}\"\n"
        f"Schema_links: {schema_links}\n"
        "SQL:"
    )


def _prompt_nonnested(
    question: str, schema_links: str, schema: str, shots: List[Dict]
) -> str:
    shot_text = "\n\n".join(_shot_nonnested_block(s) for s in shots)
    return (
        "# Use an intermediate representation to generate the SQL query. "
        "Show reasoning, then output SQL after 'SQL:'.\n\n"
        f"{schema}\n\n"
        f"{shot_text}\n\n"
        f"Q: \"{question}\"\n"
        f"Schema_links: {schema_links}\n"
        "A: Let's think step by step."
    )


def _prompt_nested(
    question: str, schema_links: str, schema: str, shots: List[Dict]
) -> str:
    shot_text = "\n\n".join(_shot_nested_block(s) for s in shots)
    return (
        "# Decompose into sub-questions, use intermediate representation, "
        "then output SQL after 'SQL:'.\n\n"
        f"{schema}\n\n"
        f"{shot_text}\n\n"
        f"Q: \"{question}\"\n"
        f"Schema_links: {schema_links}\n"
        "A: Let's think step by step."
    )


def _prompt_self_correct(
    question: str, sql: str, error: str, schema: str
) -> str:
    return (
        "# The following SQL may contain errors. "
        "Identify all issues and output a corrected SQL after 'Revised_SQL:'.\n\n"
        f"{schema}\n\n"
        f"Q: {question}\n"
        f"SQL: {sql}\n"
        f"Error: {error}\n\n"
        "A: Let's think step by step.\n"
        "1) Check column names exist in the schema.\n"
        "2) Check JOINs are correct.\n"
        "3) Check WHERE conditions.\n"
        "4) Check GROUP BY / ORDER BY.\n"
        "5) Check subquery structure.\n"
        "Revised_SQL:"
    )


# ── Output parsing ─────────────────────────────────────────────────────────

def _parse_schema_links(raw: str) -> str:
    m = re.search(r'Schema_links:\s*(\[.*?\])', raw, re.DOTALL)
    return m.group(1) if m else "[]"


def _parse_label(raw: str) -> str:
    m = re.search(r'Label:\s*"?(EASY|NON-NESTED|NESTED)"?', raw, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    # Fallback: look for keywords in reasoning
    upper = raw.upper()
    if "NESTED" in upper:
        return "NESTED"
    if "NON-NESTED" in upper or "JOIN" in upper:
        return "NON-NESTED"
    return "EASY"


def _parse_revised_sql(raw: str) -> Optional[str]:
    m = re.search(r'Revised_SQL:\s*(.*?)(?:$|\n\n)', raw,
                  re.DOTALL | re.IGNORECASE)
    if m:
        sql = m.group(1).strip()
        if sql:
            return sql
    return None


# ── Main method ────────────────────────────────────────────────────────────

class DINSQLMethod:
    """
    DIN-SQL: 4-stage decomposed in-context learning pipeline.
    Schema Linking → Classification → SQL Generation → Self-Correction.
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

    def _get_shots(self, query_type: str, label: str, n: int) -> List[Dict]:
        """Select few-shot examples matching the target difficulty label."""
        seed = self.cfg.get("seed", 42)
        # Filter by query_type first, then by complexity label
        pool = [
            i for i in self.train
            if i["metadata"]["query_type"] == query_type
            and _complexity_label(i) == label
        ]
        if len(pool) < n:
            # Fall back to all reasoning train instances
            pool = [i for i in self.train
                    if i["metadata"]["query_type"] == query_type]
        import random
        rng = random.Random(seed)
        return rng.sample(pool, min(n, len(pool)))

    def run(self, instances: List[Dict]) -> List[Dict]:
        n_shots = self.cfg.get("n_shots", 3)
        results = []

        for inst in tqdm(instances, desc="DIN-SQL"):
            domain   = self.cfg.get("db_name") or inst["instance_id"].split("_")[1].lower()
            db_path  = get_db_path(self.db_dir, domain)
            schema   = _din_schema(db_path)
            question = inst["question"]["primary_nl"]
            an       = inst["metadata"]["answer_nature"]
            q_type   = inst["metadata"]["query_type"]

            # General shots for schema linking and classification
            from ..dataset import get_few_shot_examples
            all_shots = get_few_shot_examples(
                self.train, q_type, n=n_shots * 3, seed=self.cfg.get("seed", 42)
            )

            # ── Stage 1: Schema Linking ────────────────────────────────────
            link_prompt = _prompt_schema_linking(question, schema, all_shots[:n_shots])
            link_raw    = self.llm.generate(
                link_prompt,
                max_new_tokens=self.cfg.get("max_link_tokens", 300),
            )
            schema_links = _parse_schema_links(link_raw)

            # ── Stage 2: Classification ────────────────────────────────────
            cls_prompt = _prompt_classify(question, schema_links, schema,
                                          all_shots[:n_shots])
            cls_raw    = self.llm.generate(
                cls_prompt,
                max_new_tokens=self.cfg.get("max_cls_tokens", 200),
            )
            label = _parse_label(cls_raw)

            # ── Stage 3: SQL Generation (label-specific prompt) ────────────
            gen_shots = self._get_shots(q_type, label, n_shots)

            if label == "EASY":
                gen_prompt = _prompt_easy(question, schema_links, schema, gen_shots)
            elif label == "NON-NESTED":
                gen_prompt = _prompt_nonnested(question, schema_links, schema, gen_shots)
            else:  # NESTED
                gen_prompt = _prompt_nested(question, schema_links, schema, gen_shots)

            gen_raw  = self.llm.generate(
                gen_prompt,
                max_new_tokens=self.cfg.get("max_sql_tokens", 512),
            )
            pred_sql = extract_sql(gen_raw)

            # ── Stage 4: Self-Correction ────────────────────────────────────
            rows, err = execute_sql(pred_sql, db_path)
            if err is not None:
                corr_prompt = _prompt_self_correct(question, pred_sql, err, schema)
                corr_raw    = self.llm.generate(
                    corr_prompt,
                    max_new_tokens=self.cfg.get("max_sql_tokens", 512),
                )
                revised = _parse_revised_sql(corr_raw) or extract_sql(corr_raw)
                if revised:
                    rows2, err2 = execute_sql(revised, db_path)
                    if err2 is None:
                        pred_sql, rows, err = revised, rows2, err2

            pred = normalize_sql_result(rows, an) if err is None else None
            gold = parse_ground_truth(inst["ground_truth"], an)

            results.append({
                "instance_id":    inst["instance_id"],
                "query_type":     q_type,
                "answer_nature":  an,
                "prediction":     pred,
                "gold":           gold,
                "pred_sql":       pred_sql,
                "gold_sql":       inst["evidence"]["golden_sql"],
                "exec_error":     err,
                "schema_links":   schema_links,
                "din_label":      label,
            })
        return results
