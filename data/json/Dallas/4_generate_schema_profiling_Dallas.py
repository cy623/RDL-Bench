import duckdb
import json
from pathlib import Path


# =====================================================================
# 
# =====================================================================
def q(name: str) -> str:
    """DuckDB ，column/table。"""
    return '"' + str(name).replace('"', '""') + '"'


def table_exists(con, table_name: str) -> bool:
    sql = """
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_schema = 'main' AND table_name = ?
    """
    return con.execute(sql, [table_name]).fetchone()[0] > 0


def get_columns_info(con, table_name: str):
    return con.execute(f"DESCRIBE {q(table_name)}").fetchall()


def get_column_names(con, table_name: str):
    return [r[0] for r in get_columns_info(con, table_name)]


def has_column(con, table_name: str, col_name: str) -> bool:
    return col_name in get_column_names(con, table_name)


def safe_fetchone(con, sql: str):
    try:
        return con.execute(sql).fetchone()
    except Exception as e:
        return {"error": str(e)}


def safe_fetchall(con, sql: str):
    try:
        return con.execute(sql).fetchall()
    except Exception as e:
        return {"error": str(e)}


def row_to_dict(col_names, row):
    return {col_names[i]: (None if row[i] is None else str(row[i])) for i in range(len(col_names))}


def add_basic_schema(table_data, columns_info, table_meta):
    for col_info in columns_info:
        col_name, col_type = col_info[0], col_info[1]
        table_data["schema"]["columns"].append({
            "name": col_name,
            "type": col_type,
            "comment": table_meta.get("comments", {}).get(col_name, "")
        })


def add_basic_column_stats(con, table_name, table_data):
    """
    column：
    - 
    - distinct_values
    - field top distribution
    """
    row_count = table_data["data_profiling"]["row_count"]
    columns_info = get_columns_info(con, table_name)

    for col_info in columns_info:
        col_name = col_info[0]
        col_type = col_info[1]
        quoted_col = q(col_name)

        stat = {}

        # null ratio / distinct
        try:
            total, non_null, distinct_cnt = con.execute(f"""
                SELECT
                    COUNT(*) AS total_rows,
                    COUNT({quoted_col}) AS non_null_rows,
                    COUNT(DISTINCT {quoted_col}) AS distinct_values
                FROM {q(table_name)}
            """).fetchone()

            null_count = total - non_null
            stat["null_ratio"] = f"{round(null_count / total * 100, 1)}%" if total else "0.0%"
            stat["distinct_values"] = distinct_cnt
        except Exception as e:
            stat["error"] = f"base profile failed: {e}"
            table_data["data_profiling"]["column_stats"][col_name] = stat
            continue

        # numeric valuecolumn/
        upper_type = str(col_type).upper()
        if any(x in upper_type for x in ["INT", "DOUBLE", "FLOAT", "DECIMAL", "BIGINT", "SMALLINT"]):
            try:
                vals = con.execute(f"""
                    SELECT
                        MIN({quoted_col}),
                        MAX({quoted_col}),
                        AVG({quoted_col})
                    FROM {q(table_name)}
                    WHERE {quoted_col} IS NOT NULL
                """).fetchone()
                stat["min"] = vals[0]
                stat["max"] = vals[1]
                stat["avg"] = round(vals[2], 2) if vals[2] is not None else None
            except Exception:
                pass

        # time columns
        elif "DATE" in upper_type or "TIMESTAMP" in upper_type:
            try:
                vals = con.execute(f"""
                    SELECT MIN({quoted_col}), MAX({quoted_col})
                    FROM {q(table_name)}
                    WHERE {quoted_col} IS NOT NULL
                """).fetchone()
                stat["min"] = str(vals[0]) if vals[0] is not None else None
                stat["max"] = str(vals[1]) if vals[1] is not None else None
            except Exception:
                pass

        # stringcolumn top distribution
        else:
            try:
                if stat["distinct_values"] is not None and stat["distinct_values"] <= 30:
                    rows = con.execute(f"""
                        SELECT {quoted_col}, COUNT(*) AS cnt
                        FROM {q(table_name)}
                        WHERE {quoted_col} IS NOT NULL
                        GROUP BY {quoted_col}
                        ORDER BY cnt DESC, {quoted_col}
                        LIMIT 10
                    """).fetchall()
                    stat["top_distribution"] = [
                        {
                            "value": None if r[0] is None else str(r[0]),
                            "count": r[1],
                            "pct": f"{round(r[1] * 100.0 / row_count, 2)}%"
                        }
                        for r in rows
                    ]
            except Exception:
                pass

        table_data["data_profiling"]["column_stats"][col_name] = stat


def add_random_samples(con, table_name, table_data, limit=10):
    columns_info = get_columns_info(con, table_name)
    col_names = [c[0] for c in columns_info]

    try:
        rows = con.execute(f"""
            SELECT * FROM {q(table_name)}
            ORDER BY RANDOM()
            LIMIT {limit}
        """).fetchall()
        table_data["data_profiling"]["random_samples"] = [row_to_dict(col_names, row) for row in rows]
    except Exception as e:
        table_data["data_profiling"]["random_samples_error"] = str(e)


# =====================================================================
# Dallas: incidents table
# =====================================================================
def profile_dallas_incidents(con, table_name, table_meta):
    row_count = con.execute(f"SELECT COUNT(*) FROM {q(table_name)}").fetchone()[0]

    table_data = {
        "table_name": table_name,
        "description": table_meta.get("description", ""),
        "schema": {
            "columns": [],
            "primary_key": table_meta.get("primary_key", []),
            "foreign_keys": table_meta.get("foreign_keys", [])
        },
        "data_profiling": {
            "row_count": row_count,
            "column_stats": {},
            "advanced_profiling": {}
        }
    }

    columns_info = get_columns_info(con, table_name)
    add_basic_schema(table_data, columns_info, table_meta)

    if row_count == 0:
        return table_data

    add_basic_column_stats(con, table_name, table_data)
    add_random_samples(con, table_name, table_data, limit=10)

    adv = table_data["data_profiling"]["advanced_profiling"]

    # 1. time
    if has_column(con, table_name, "date"):
        try:
            min_date, max_date = con.execute(f"""
                SELECT MIN({q("date")}), MAX({q("date")})
                FROM {q(table_name)}
                WHERE {q("date")} IS NOT NULL
            """).fetchone()
            adv["time_coverage"] = {
                "first_incident_date": str(min_date) if min_date is not None else None,
                "last_incident_date": str(max_date) if max_date is not None else None
            }
        except Exception as e:
            adv["time_coverage_error"] = str(e)

    # 2. subject_statuses distribution
    if has_column(con, table_name, "subject_statuses"):
        try:
            rows = con.execute(f"""
                SELECT {q("subject_statuses")} AS status, COUNT(*) AS cnt
                FROM {q(table_name)}
                WHERE {q("subject_statuses")} IS NOT NULL
                GROUP BY {q("subject_statuses")}
                ORDER BY cnt DESC, status
            """).fetchall()
            adv["subject_status_distribution"] = [
                {"subject_statuses": str(r[0]), "count": r[1], "pct": f"{round(r[1] * 100.0 / row_count, 2)}%"}
                for r in rows
            ]
        except Exception as e:
            adv["subject_status_distribution_error"] = str(e)

    # 3. subject_weapon distribution
    if has_column(con, table_name, "subject_weapon"):
        try:
            rows = con.execute(f"""
                SELECT {q("subject_weapon")} AS weapon, COUNT(*) AS cnt
                FROM {q(table_name)}
                WHERE {q("subject_weapon")} IS NOT NULL
                GROUP BY {q("subject_weapon")}
                ORDER BY cnt DESC, weapon
                LIMIT 15
            """).fetchall()
            adv["top_subject_weapons"] = [
                {"subject_weapon": str(r[0]), "count": r[1], "pct": f"{round(r[1] * 100.0 / row_count, 2)}%"}
                for r in rows
            ]
        except Exception as e:
            adv["top_subject_weapons_error"] = str(e)

    # 4. grand jury disposition distribution
    if has_column(con, table_name, "grand_jury_disposition"):
        try:
            rows = con.execute(f"""
                SELECT {q("grand_jury_disposition")} AS disposition, COUNT(*) AS cnt
                FROM {q(table_name)}
                WHERE {q("grand_jury_disposition")} IS NOT NULL
                GROUP BY {q("grand_jury_disposition")}
                ORDER BY cnt DESC, disposition
            """).fetchall()
            adv["grand_jury_disposition_distribution"] = [
                {"grand_jury_disposition": str(r[0]), "count": r[1], "pct": f"{round(r[1] * 100.0 / row_count, 2)}%"}
                for r in rows
            ]
        except Exception as e:
            adv["grand_jury_disposition_distribution_error"] = str(e)

    # 5. subject_count / officer_count statistics
    for cnt_col in ["subject_count", "officer_count"]:
        if has_column(con, table_name, cnt_col):
            try:
                mn, mx, avg = con.execute(f"""
                    SELECT
                        MIN({q(cnt_col)}),
                        MAX({q(cnt_col)}),
                        AVG({q(cnt_col)})
                    FROM {q(table_name)}
                    WHERE {q(cnt_col)} IS NOT NULL
                """).fetchone()
                adv[f"{cnt_col}_stats"] = {
                    "min": mn,
                    "max": mx,
                    "avg": round(avg, 2) if avg is not None else None
                }
            except Exception as e:
                adv[f"{cnt_col}_stats_error"] = str(e)

    # 6. summary_text 
    if has_column(con, table_name, "summary_text"):
        try:
            mn, mx, avg = con.execute(f"""
                SELECT
                    MIN(LENGTH({q("summary_text")})),
                    MAX(LENGTH({q("summary_text")})),
                    AVG(LENGTH({q("summary_text")}))
                FROM {q(table_name)}
                WHERE {q("summary_text")} IS NOT NULL
            """).fetchone()
            adv["summary_text_length_stats"] = {
                "min_length": mn,
                "max_length": mx,
                "avg_length": round(avg, 2) if avg is not None else None
            }
        except Exception as e:
            adv["summary_text_length_stats_error"] = str(e)

    # 7. 
    if has_column(con, table_name, "latitude") and has_column(con, table_name, "longitude"):
        try:
            lat_min, lat_max, lng_min, lng_max, non_null_geo = con.execute(f"""
                SELECT
                    MIN({q("latitude")}),
                    MAX({q("latitude")}),
                    MIN({q("longitude")}),
                    MAX({q("longitude")}),
                    COUNT(*)
                FROM {q(table_name)}
                WHERE {q("latitude")} IS NOT NULL AND {q("longitude")} IS NOT NULL
            """).fetchone()
            adv["geo_coverage"] = {
                "latitude_min": lat_min,
                "latitude_max": lat_max,
                "longitude_min": lng_min,
                "longitude_max": lng_max,
                "non_null_coordinate_rows": non_null_geo
            }
        except Exception as e:
            adv["geo_coverage_error"] = str(e)

    return table_data


# =====================================================================
# Dallas: officers / subjects 
# =====================================================================
def profile_dallas_person_like_table(con, table_name, table_meta, role_name="entity"):
    row_count = con.execute(f"SELECT COUNT(*) FROM {q(table_name)}").fetchone()[0]

    table_data = {
        "table_name": table_name,
        "description": table_meta.get("description", ""),
        "schema": {
            "columns": [],
            "primary_key": table_meta.get("primary_key", []),
            "foreign_keys": table_meta.get("foreign_keys", [])
        },
        "data_profiling": {
            "row_count": row_count,
            "column_stats": {},
            "advanced_profiling": {}
        }
    }

    columns_info = get_columns_info(con, table_name)
    add_basic_schema(table_data, columns_info, table_meta)

    if row_count == 0:
        return table_data

    add_basic_column_stats(con, table_name, table_data)
    add_random_samples(con, table_name, table_data, limit=10)

    adv = table_data["data_profiling"]["advanced_profiling"]

    # race distribution
    if has_column(con, table_name, "race"):
        try:
            rows = con.execute(f"""
                SELECT {q("race")} AS race, COUNT(*) AS cnt
                FROM {q(table_name)}
                WHERE {q("race")} IS NOT NULL
                GROUP BY {q("race")}
                ORDER BY cnt DESC, race
            """).fetchall()
            adv["race_distribution"] = [
                {"race": str(r[0]), "count": r[1], "pct": f"{round(r[1] * 100.0 / row_count, 2)}%"}
                for r in rows
            ]
        except Exception as e:
            adv["race_distribution_error"] = str(e)

    # gender distribution
    if has_column(con, table_name, "gender"):
        try:
            rows = con.execute(f"""
                SELECT {q("gender")} AS gender, COUNT(*) AS cnt
                FROM {q(table_name)}
                WHERE {q("gender")} IS NOT NULL
                GROUP BY {q("gender")}
                ORDER BY cnt DESC, gender
            """).fetchall()
            adv["gender_distribution"] = [
                {"gender": str(r[0]), "count": r[1], "pct": f"{round(r[1] * 100.0 / row_count, 2)}%"}
                for r in rows
            ]
        except Exception as e:
            adv["gender_distribution_error"] = str(e)

    #  incident
    if has_column(con, table_name, "case_number"):
        try:
            case_cnt = con.execute(f"""
                SELECT COUNT(DISTINCT {q("case_number")})
                FROM {q(table_name)}
                WHERE {q("case_number")} IS NOT NULL
            """).fetchone()[0]
            adv["incident_linkage"] = {
                "distinct_case_numbers": case_cnt,
                "avg_records_per_case": round(row_count / case_cnt, 2) if case_cnt else None,
                "role": role_name
            }
        except Exception as e:
            adv["incident_linkage_error"] = str(e)

    # 
    if has_column(con, table_name, "full_name"):
        try:
            rows = con.execute(f"""
                SELECT {q("full_name")}, COUNT(*) AS cnt
                FROM {q(table_name)}
                WHERE {q("full_name")} IS NOT NULL
                GROUP BY {q("full_name")}
                ORDER BY cnt DESC, {q("full_name")}
                LIMIT 10
            """).fetchall()
            adv["top_full_names"] = [
                {"full_name": str(r[0]), "count": r[1]} for r in rows
            ]
        except Exception as e:
            adv["top_full_names_error"] = str(e)

    return table_data


# =====================================================================
#  fallback
# =====================================================================
def profile_generic_table(con, table_name, table_meta):
    row_count = con.execute(f"SELECT COUNT(*) FROM {q(table_name)}").fetchone()[0]

    table_data = {
        "table_name": table_name,
        "description": table_meta.get("description", ""),
        "schema": {
            "columns": [],
            "primary_key": table_meta.get("primary_key", []),
            "foreign_keys": table_meta.get("foreign_keys", [])
        },
        "data_profiling": {
            "row_count": row_count,
            "column_stats": {},
            "advanced_profiling": {}
        }
    }

    columns_info = get_columns_info(con, table_name)
    add_basic_schema(table_data, columns_info, table_meta)

    if row_count == 0:
        return table_data

    add_basic_column_stats(con, table_name, table_data)
    add_random_samples(con, table_name, table_data, limit=10)

    return table_data


# =====================================================================
# 
# =====================================================================
def generate_llm_json(db_path, output_json_path, METADATA_INJECTION):
    print(f"Connecting to DuckDB: {db_path} ...")
    con = duckdb.connect(db_path, read_only=True)

    final_json = {
        "database_metadata": {
            "name": METADATA_INJECTION["database_name"],
            "description": METADATA_INJECTION["database_description"],
            "target_qa_generation_framework": [
                {
                    "Type": "Retrieval",
                    "Description": "Direct lookup of records, entities, or attributes.",
                    "Example": "What was the grand jury disposition for a given case number?"
                },
                {
                    "Type": "Analytical",
                    "Description": "Aggregation, ranking, distribution, and statistical summaries.",
                    "Example": "Which subject status appears most frequently across incidents?"
                },
                {
                    "Type": "Relational Reasoning",
                    "Description": "Questions requiring joins or multi-table reasoning across incidents, officers, and subjects.",
                    "Example": "Which incidents involved multiple officers and multiple subjects?"
                },
                {
                    "Type": "Predictive",
                    "Description": "Questions that infer possible future or hidden patterns from historical records.",
                    "Example": "Based on past patterns, which incident characteristics are associated with certain dispositions?"
                }
            ]
        },
        "tables": []
    }

    tables = [
        r[0]
        for r in con.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema='main' AND table_type='BASE TABLE'
            ORDER BY table_name
        """).fetchall()
    ]

    for table_name in tables:
        print(f"Processing table: {table_name} ...")
        table_meta = METADATA_INJECTION["tables"].get(table_name, {})

        if table_name == "incidents":
            table_data = profile_dallas_incidents(con, table_name, table_meta)
        elif table_name == "officers":
            table_data = profile_dallas_person_like_table(con, table_name, table_meta, role_name="officer")
        elif table_name == "subjects":
            table_data = profile_dallas_person_like_table(con, table_name, table_meta, role_name="subject")
        else:
            table_data = profile_generic_table(con, table_name, table_meta)

        final_json["tables"].append(table_data)

    con.close()

    output_path = Path(output_json_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(final_json, f, ensure_ascii=False, indent=2)

    print(f"\nDone. JSON saved to: {output_json_path}")


# =====================================================================
# entry point
# =====================================================================
if __name__ == "__main__":
    database_name = "Dallas"
    DB_PATH = f"DB/{database_name}.duckdb"
    OUTPUT_FILE = f"json/{database_name}/data_schema_profiling.json"

    with open(f"json/{database_name}/metadata_{database_name}.json", "r", encoding="utf-8") as f:
        METADATA_INJECTION = json.load(f)

    generate_llm_json(DB_PATH, OUTPUT_FILE, METADATA_INJECTION)