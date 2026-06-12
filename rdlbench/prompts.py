"""Prompt templates for all LLM-based methods."""

from typing import Dict, List


def _shot_block(ex: Dict) -> str:
    return (
        f"Question: {ex['question']['primary_nl']}\n"
        f"SQL: {ex['evidence']['golden_sql']}"
    )


def _pred_shot_block(ex: Dict) -> str:
    return (
        f"Question: {ex['question']['primary_nl']}\n"
        f"Answer: {ex['ground_truth']['formatted_nl_answer']}"
    )


def prompt_llm_schema(
    question: str,
    schema:   str,
    shots:    List[Dict],
) -> str:
    shot_text = "\n\n".join(_shot_block(s) for s in shots)
    return (
        "You are an expert SQL assistant. Given the database schema and a "
        "natural language question, generate a valid SQL query. "
        "Output only the SQL statement, no explanation.\n\n"
        f"## Schema\n{schema}\n\n"
        f"## Examples\n{shot_text}\n\n"
        f"## Your Turn\nQuestion: {question}\nSQL:"
    )


def prompt_llm_2hop(
    question: str,
    schema:   str,
    context:  str,
    shots:    List[Dict],
) -> str:
    shot_text = "\n\n".join(_shot_block(s) for s in shots)
    return (
        "You are an expert SQL assistant. Use the schema and relational "
        "context below to generate a valid SQL query. "
        "Output only the SQL statement, no explanation.\n\n"
        f"## Schema\n{schema}\n\n"
        f"## Relational Context\n{context}\n\n"
        f"## Examples\n{shot_text}\n\n"
        f"## Your Turn\nQuestion: {question}\nSQL:"
    )


def prompt_llm_only(
    question:      str,
    schema:        str,
    profiling:     str,
    shots:         List[Dict],
    answer_nature: str,
) -> str:
    shot_text = "\n\n".join(_pred_shot_block(s) for s in shots)
    fmt = {
        "Scalars": "a single number",
        "Boolean": "Yes or No",
        "Sets":    "a comma-separated list of values",
        "Rankings":"a ranked comma-separated list",
    }.get(answer_nature, "a value")
    return (
        "You are a data analyst. Based solely on the database schema and "
        f"statistics below, predict the answer. Reply with {fmt} only — "
        "no explanation.\n\n"
        f"## Schema\n{schema}\n\n"
        f"## Database Statistics\n{profiling}\n\n"
        f"## Examples\n{shot_text}\n\n"
        f"## Your Turn\nQuestion: {question}\nAnswer:"
    )


def prompt_llm_router(
    question: str,
    schema:   str,
) -> str:
    return (
        "You are a database query router. Classify the question and output "
        "a JSON object with exactly these fields:\n"
        '  "track": "Reasoning" or "Predictive"\n'
        '  "query_type": "Retrieval", "Analytical", '
        '"Relational Reasoning", or "Predictive"\n'
        '  "answer_nature": "Sets", "Scalars", "Boolean", or "Rankings"\n'
        '  "tables_involved": [list of table names from the schema]\n\n'
        "Output valid JSON only. No explanation.\n\n"
        f"## Schema\n{schema}\n\n"
        f"## Question\n{question}\n\n"
        "## JSON Route:"
    )
