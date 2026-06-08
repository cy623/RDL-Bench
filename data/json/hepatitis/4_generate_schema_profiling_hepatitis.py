import duckdb
import json
import os
from typing import Any, Dict, List


# =====================================================================
# 
# =====================================================================
def q_ident(name: str) -> str:
    """DuckDB """
    return '"' + str(name).replace('"', '""') + '"'


def is_numeric_type(col_type: str) -> bool:
    t = col_type.upper()
    return any(x in t for x in [
        "TINYINT", "SMALLINT", "INTEGER", "BIGINT",
        "UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT",
        "FLOAT", "DOUBLE", "DECIMAL", "REAL"
    ])


def is_date_type(col_type: str) -> bool:
    t = col_type.upper()
    return "DATE" in t or "TIMESTAMP" in t or "TIME" in t


def is_string_type(col_type: str) -> bool:
    return "CHAR" in col_type.upper() or "VARCHAR" in col_type.upper() or "TEXT" in col_type.upper()


def safe_round(x, ndigits=4):
    if x is None:
        return None
    try:
        return round(float(x), ndigits)
    except Exception:
        return x


def try_parse_int_string_set(values: List[str]):
    """string ['0','1','2'] """
    parsed = []
    for v in values:
        if v is None:
            return None
        s = str(v).strip()
        if s == "":
            return None
        if s.startswith("-"):
            body = s[1:]
            if not body.isdigit():
                return None
        else:
            if not s.isdigit():
                return None
        parsed.append(int(s))
    return parsed


# =====================================================================
# column
# =====================================================================
def profile_numeric_column(con, table_name: str, col_name: str) -> Dict[str, Any]:
    t = q_ident(table_name)
    c = q_ident(col_name)

    stats = con.execute(f"""
        SELECT
            MIN({c}),
            MAX({c}),
            AVG({c}),
            STDDEV_SAMP({c}),
            APPROX_QUANTILE({c}, 0.25),
            APPROX_QUANTILE({c}, 0.50),
            APPROX_QUANTILE({c}, 0.75)
        FROM {t}
        WHERE {c} IS NOT NULL
    """).fetchone()

    return {
        "semantic_type": "numeric",
        "min": safe_round(stats[0], 4),
        "max": safe_round(stats[1], 4),
        "avg": safe_round(stats[2], 4),
        "std": safe_round(stats[3], 4),
        "q1": safe_round(stats[4], 4),
        "median": safe_round(stats[5], 4),
        "q3": safe_round(stats[6], 4),
    }


def profile_date_column(con, table_name: str, col_name: str) -> Dict[str, Any]:
    t = q_ident(table_name)
    c = q_ident(col_name)

    stats = con.execute(f"""
        SELECT MIN({c}), MAX({c})
        FROM {t}
        WHERE {c} IS NOT NULL
    """).fetchone()

    return {
        "semantic_type": "temporal",
        "min_date": str(stats[0]) if stats[0] is not None else None,
        "max_date": str(stats[1]) if stats[1] is not None else None,
    }


def profile_string_column(con, table_name: str, col_name: str, row_count: int) -> Dict[str, Any]:
    t = q_ident(table_name)
    c = q_ident(col_name)

    #  top distribution
    top_rows = con.execute(f"""
        SELECT {c}, COUNT(*) AS cnt
        FROM {t}
        WHERE {c} IS NOT NULL
        GROUP BY {c}
        ORDER BY cnt DESC, {c}
        LIMIT 10
    """).fetchall()

    top_distribution = []
    for value, cnt in top_rows:
        top_distribution.append({
            "value": str(value),
            "count": int(cnt),
            "ratio": safe_round(cnt / row_count if row_count else 0, 4)
        })

    #  distinct （ distinct ）
    distinct_count = con.execute(f"""
        SELECT COUNT(DISTINCT {c}) FROM {t}
    """).fetchone()[0]

    distinct_values = None
    ordered_category = None
    category_range = None

    if distinct_count is not None and distinct_count <= 20:
        vals = con.execute(f"""
            SELECT DISTINCT {c}
            FROM {t}
            WHERE {c} IS NOT NULL
            ORDER BY {c}
        """).fetchall()
        distinct_values = [str(v[0]) for v in vals]

        parsed = try_parse_int_string_set(distinct_values)
        if parsed is not None:
            parsed_sorted = sorted(parsed)
            if parsed_sorted == list(range(min(parsed_sorted), max(parsed_sorted) + 1)):
                ordered_category = True
                category_range = {
                    "min_code": min(parsed_sorted),
                    "max_code": max(parsed_sorted),
                    "num_levels": len(parsed_sorted)
                }
            else:
                ordered_category = False

    # 
    sample_values_rows = con.execute(f"""
        SELECT DISTINCT {c}
        FROM {t}
        WHERE {c} IS NOT NULL
        LIMIT 5
    """).fetchall()
    sample_values = [str(r[0]) for r in sample_values_rows]

    result = {
        "semantic_type": "categorical_or_text",
        "distinct_values_count": int(distinct_count) if distinct_count is not None else None,
        "top_distribution": top_distribution,
        "sample_values": sample_values
    }

    if distinct_values is not None:
        result["distinct_values"] = distinct_values

    if ordered_category is not None:
        result["ordered_category"] = ordered_category

    if category_range is not None:
        result["category_range"] = category_range

    return result


# =====================================================================
# foreign keycheck
# =====================================================================
def profile_primary_key(con, table_name: str, pk_cols: List[str]) -> Dict[str, Any]:
    if not pk_cols:
        return {}

    t = q_ident(table_name)
    pk_expr = ", ".join(q_ident(c) for c in pk_cols)

    total_rows = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    distinct_rows = con.execute(f"SELECT COUNT(*) FROM (SELECT DISTINCT {pk_expr} FROM {t})").fetchone()[0]

    null_conditions = " OR ".join(f"{q_ident(c)} IS NULL" for c in pk_cols)
    null_pk_rows = con.execute(f"SELECT COUNT(*) FROM {t} WHERE {null_conditions}").fetchone()[0]

    return {
        "columns": pk_cols,
        "is_unique": distinct_rows == total_rows,
        "duplicate_row_count": int(total_rows - distinct_rows),
        "null_in_pk_row_count": int(null_pk_rows)
    }


def profile_foreign_keys(con, table_name: str, fk_defs: List[str]) -> List[Dict[str, Any]]:
    """
    fk_defs :
    [
      "b_id -> bio.b_id",
      "m_id -> dispat.m_id"
    ]
    """
    results = []
    for fk in fk_defs:
        try:
            left, right = fk.split("->")
            left_col = left.strip()
            right_table, right_col = right.strip().split(".")
            t = q_ident(table_name)
            lq = q_ident(left_col)
            rt = q_ident(right_table.strip())
            rq = q_ident(right_col.strip())

            total_non_null = con.execute(f"""
                SELECT COUNT(*) FROM {t}
                WHERE {lq} IS NOT NULL
            """).fetchone()[0]

            unmatched = con.execute(f"""
                SELECT COUNT(*)
                FROM {t} a
                LEFT JOIN {rt} b
                ON a.{lq} = b.{rq}
                WHERE a.{lq} IS NOT NULL
                  AND b.{rq} IS NULL
            """).fetchone()[0]

            results.append({
                "foreign_key": fk,
                "non_null_rows": int(total_non_null),
                "unmatched_rows": int(unmatched),
                "referential_integrity_ok": unmatched == 0
            })
        except Exception as e:
            results.append({
                "foreign_key": fk,
                "error": str(e)
            })

    return results


# =====================================================================
# QA 
# =====================================================================
def build_column_summary(col_name: str, col_type: str, col_comment: str, col_profile: Dict[str, Any]) -> str:
    semantic_type = col_profile.get("semantic_type", "")

    if semantic_type == "numeric":
        return (
            f"{col_name} ({col_type}): {col_comment} "
            f"Range [{col_profile.get('min')}, {col_profile.get('max')}], "
            f"avg={col_profile.get('avg')}, median={col_profile.get('median')}."
        )

    if semantic_type == "temporal":
        return (
            f"{col_name} ({col_type}): {col_comment} "
            f"Date range [{col_profile.get('min_date')}, {col_profile.get('max_date')}]."
        )

    if semantic_type == "categorical_or_text":
        distinct_count = col_profile.get("distinct_values_count")
        if col_profile.get("ordered_category") and col_profile.get("category_range"):
            cr = col_profile["category_range"]
            return (
                f"{col_name} ({col_type}): {col_comment} "
                f"Ordered categorical values with {cr['num_levels']} levels, "
                f"code range {cr['min_code']} to {cr['max_code']}."
            )

        if distinct_count is not None and distinct_count <= 20 and "distinct_values" in col_profile:
            return (
                f"{col_name} ({col_type}): {col_comment} "
                f"{distinct_count} distinct values: {col_profile['distinct_values']}."
            )

        return (
            f"{col_name} ({col_type}): {col_comment} "
            f"{distinct_count} distinct values."
        )

    return f"{col_name} ({col_type}): {col_comment}"


# =====================================================================
# Core logic
# =====================================================================
def generate_llm_json(db_path, output_json_path, METADATA_INJECTION):
    print(f"Connecting to DuckDB: {db_path}...")
    con = duckdb.connect(db_path, read_only=True)

    final_json = {
        "database_metadata": {
            "name": METADATA_INJECTION["database_name"],
            "description": METADATA_INJECTION["database_description"]
        },
        "tables": []
    }

    tables_query = """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'main' AND table_type = 'BASE TABLE'
        ORDER BY table_name
    """
    tables = [r[0] for r in con.execute(tables_query).fetchall()]

    for table_name in tables:
        print(f"Processing table: {table_name}")
        table_meta = METADATA_INJECTION.get("tables", {}).get(table_name, {})

        table_data = {
            "table_name": table_name,
            "description": table_meta.get("description", ""),
            "schema": {
                "columns": [],
                "primary_key": table_meta.get("primary_key", []),
                "foreign_keys": table_meta.get("foreign_keys", [])
            },
            "data_profiling": {
                "row_count": 0,
                "sample_rows": [],
                "column_stats": {},
                "primary_key_profile": {},
                "foreign_key_profiles": []
            },
            "qa_hints": {
                "table_summary": "",
                "column_summaries": []
            }
        }

        t = q_ident(table_name)

        # 1) 
        row_count = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        table_data["data_profiling"]["row_count"] = int(row_count)

        # 2) 
        if row_count > 0:
            sample_rows = con.execute(f"SELECT * FROM {t} LIMIT 5").fetchall()
            column_names = [d[0] for d in con.description]
            table_data["data_profiling"]["sample_rows"] = [
                {column_names[i]: row[i] for i in range(len(column_names))}
                for row in sample_rows
            ]

        # 3) schema column
        columns_info = con.execute(f"DESCRIBE {t}").fetchall()
        for col_info in columns_info:
            col_name, col_type = col_info[0], col_info[1]
            c = q_ident(col_name)

            col_comment = table_meta.get("comments", {}).get(col_name, "")
            table_data["schema"]["columns"].append({
                "name": col_name,
                "type": col_type,
                "comment": col_comment
            })

            # statistics：、
            null_count = con.execute(f"""
                SELECT COUNT(*) FROM {t}
                WHERE {c} IS NULL
            """).fetchone()[0]

            distinct_count = con.execute(f"""
                SELECT COUNT(DISTINCT {c}) FROM {t}
            """).fetchone()[0]

            col_profile = {
                "null_count": int(null_count),
                "null_ratio": safe_round(null_count / row_count if row_count else 0, 4),
                "distinct_count": int(distinct_count) if distinct_count is not None else None
            }

            try:
                if row_count > 0:
                    if is_numeric_type(col_type) and not col_name.lower().endswith("id"):
                        col_profile.update(profile_numeric_column(con, table_name, col_name))
                    elif is_date_type(col_type):
                        col_profile.update(profile_date_column(con, table_name, col_name))
                    elif is_string_type(col_type):
                        col_profile.update(profile_string_column(con, table_name, col_name, row_count))
                    else:
                        # 
                        vals = con.execute(f"""
                            SELECT DISTINCT {c}
                            FROM {t}
                            WHERE {c} IS NOT NULL
                            LIMIT 5
                        """).fetchall()
                        col_profile["sample_values"] = [str(v[0]) for v in vals]
            except Exception as e:
                col_profile["profile_error"] = str(e)

            table_data["data_profiling"]["column_stats"][col_name] = col_profile
            table_data["qa_hints"]["column_summaries"].append(
                build_column_summary(col_name, col_type, col_comment, col_profile)
            )

        # 4) primary key
        pk_cols = table_meta.get("primary_key", [])
        table_data["data_profiling"]["primary_key_profile"] = profile_primary_key(con, table_name, pk_cols)

        # 5) foreign key
        fk_defs = table_meta.get("foreign_keys", [])
        table_data["data_profiling"]["foreign_key_profiles"] = profile_foreign_keys(con, table_name, fk_defs)

        # 6) table QA 
        table_data["qa_hints"]["table_summary"] = (
            f"Table `{table_name}` has {row_count} rows. "
            f"{table_meta.get('description', '')}"
        )

        final_json["tables"].append(table_data)

    con.close()

    os.makedirs(os.path.dirname(output_json_path), exist_ok=True)
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(final_json, f, ensure_ascii=False, indent=2)

    print(f"Success! JSON saved to: {output_json_path}")


# =====================================================================
# entry point
# =====================================================================
if __name__ == "__main__":
    database_name = "hepatitis"
    DB_PATH = f"DB/{database_name}.duckdb"
    OUTPUT_FILE = f"json/{database_name}/data_schema_profiling.json"

    with open(f"json/{database_name}/metadata_{database_name}.json", "r", encoding="utf-8") as f:
        METADATA_INJECTION = json.load(f)

    generate_llm_json(DB_PATH, OUTPUT_FILE, METADATA_INJECTION)