import duckdb
import json

def profile_lookup_table(con, table_name, table_meta):
    """
    Lookup/table：， LLM 。
     product_category_name_translation (table), geolocation () 。
    """
    row_count = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]

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
            "column_stats": {}
        }
    }

    columns_info = con.execute(f"DESCRIBE {table_name}").fetchall()
    for col_info in columns_info:
        col_name, col_type = col_info[0], col_info[1]
        table_data["schema"]["columns"].append({
            "name": col_name,
            "type": col_type,
            "comment": table_meta.get("comments", {}).get(col_name, "")
        })

    if row_count == 0:
        return table_data

    if row_count <= 50:
        # table (table)
        rows = con.execute(f"SELECT * FROM {table_name} ORDER BY 1").fetchall()
        col_names = [c[0] for c in columns_info]
        table_data["data_profiling"]["full_enum"] = [
            {col_names[i]: str(row[i]) for i in range(len(col_names))}
            for row in rows
        ]
        table_data["data_profiling"]["note"] = "Small lookup table: full enumeration provided for LLM semantic understanding."
    else:
        # table（ geolocation, products） 10 
        rows = con.execute(f"SELECT * FROM {table_name} ORDER BY RANDOM() LIMIT 10").fetchall()
        col_names = [c[0] for c in columns_info]
        table_data["data_profiling"]["random_samples"] = [
            {col_names[i]: str(row[i]) for i in range(len(col_names))}
            for row in rows
        ]
        table_data["data_profiling"]["note"] = f"Large lookup table ({row_count} rows): 10 random samples provided."

    return table_data


def profile_olist_fact_table(con, table_name, table_meta):
    """
    table (Orders, Items, Payments, Reviews, Customers) ，
     QA question（、、、、time）。
    """
    row_count = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]

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
            "advanced_profiling": {}  # result
        }
    }

    columns_info = con.execute(f"DESCRIBE {table_name}").fetchall()
    for col_info in columns_info:
        col_name, col_type = col_info[0], col_info[1]
        table_data["schema"]["columns"].append({
            "name": col_name,
            "type": col_type,
            "comment": table_meta.get("comments", {}).get(col_name, "")
        })

    if row_count == 0:
        return table_data

    adv = table_data["data_profiling"]["advanced_profiling"]

    # table
    if table_name == "olist_orders_dataset":
        # 1. distribution & time (Analytical / Predictive)
        status_dist = con.execute(f"""
            SELECT order_status, COUNT(*) AS cnt,
                   ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS pct
            FROM {table_name} GROUP BY order_status ORDER BY cnt DESC
        """).fetchall()
        adv["order_status_distribution"] = [{"status": r[0], "count": r[1], "pct": f"{r[2]}%"} for r in status_dist]

        time_range = con.execute(f"""
            SELECT MIN(order_purchase_timestamp), MAX(order_purchase_timestamp)
            FROM {table_name} WHERE order_purchase_timestamp IS NOT NULL
        """).fetchone()
        adv["time_coverage"] = {"first_order": str(time_range[0]), "last_order": str(time_range[1])}

    elif table_name == "olist_order_items_dataset":
        # 2. 、 (Analytical)
        financial_stats = con.execute(f"""
            SELECT ROUND(MIN(price), 2), ROUND(MAX(price), 2), ROUND(AVG(price), 2),
                   ROUND(MIN(freight_value), 2), ROUND(MAX(freight_value), 2), ROUND(AVG(freight_value), 2)
            FROM {table_name}
        """).fetchone()
        adv["financial_metrics"] = {
            "price": {"min": financial_stats[0], "max": financial_stats[1], "avg": financial_stats[2]},
            "freight_value": {"min": financial_stats[3], "max": financial_stats[4], "avg": financial_stats[5]}
        }

    elif table_name == "olist_order_payments_dataset":
        # 3. distribution (Analytical / Relational)
        payment_dist = con.execute(f"""
            SELECT payment_type, COUNT(*) AS cnt, ROUND(AVG(payment_value), 2) AS avg_value
            FROM {table_name} GROUP BY payment_type ORDER BY cnt DESC
        """).fetchall()
        adv["payment_type_distribution"] = [
            {"payment_type": r[0], "usage_count": r[1], "avg_payment_value": r[2]} for r in payment_dist
        ]

    elif table_name == "olist_order_reviews_dataset":
        # 4. distribution (Predictive / Analytical)
        review_dist = con.execute(f"""
            SELECT review_score, COUNT(*) AS cnt,
                   ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS pct
            FROM {table_name} WHERE review_score IS NOT NULL
            GROUP BY review_score ORDER BY review_score DESC
        """).fetchall()
        adv["review_score_distribution"] = [{"score": r[0], "count": r[1], "pct": f"{r[2]}%"} for r in review_dist]

    elif table_name == "olist_customers_dataset":
        # 5. distribution Top 10 (Retrieval / Relational)
        state_dist = con.execute(f"""
            SELECT customer_state, COUNT(*) AS cnt
            FROM {table_name} GROUP BY customer_state ORDER BY cnt DESC LIMIT 10
        """).fetchall()
        adv["top_10_customer_states"] = [{"state": r[0], "customer_count": r[1]} for r in state_dist]

    elif table_name == "olist_sellers_dataset":
        # 6. distribution Top 10 (Retrieval / Relational)
        seller_state_dist = con.execute(f"""
            SELECT seller_state, COUNT(*) AS cnt
            FROM {table_name} GROUP BY seller_state ORDER BY cnt DESC LIMIT 10
        """).fetchall()
        adv["top_10_seller_states"] = [{"state": r[0], "seller_count": r[1]} for r in seller_state_dist]


    # ==================================================================
    # field（null_ratio / distinct_values）
    # ==================================================================
    col_stats = table_data["data_profiling"]["column_stats"]
    for col_info in columns_info:
        col_name = col_info[0]
        try:
            base = con.execute(
                f"SELECT COUNT(*), COUNT({col_name}), COUNT(DISTINCT {col_name}) FROM {table_name}"
            ).fetchone()
            total, non_null, unique = base
            col_stats[col_name] = {
                "null_ratio": f"{round((total - non_null) / total * 100, 1)}%",
                "distinct_values": unique
            }
        except Exception as e:
            print(f"  [WARN] column stat failed for {col_name}: {e}")

    return table_data


# =====================================================================
# ：merge schema, metadata, and data profiling
# =====================================================================
def generate_llm_json(db_path, output_json_path, METADATA_INJECTION):
    print(f"Connecting to DuckDB: {db_path}...")
    con = duckdb.connect(db_path, read_only=True)

    # generate (QA Types)
    final_json = {
        "database_metadata": {
            "name": METADATA_INJECTION["database_name"],
            "description": METADATA_INJECTION["database_description"],
            "target_qa_generation_framework": [
                {
                    "Type": "Retrieval",
                    "Description": "Directly search for entities or records",
                    "Example": "Return the names of all users who have purchased the iPhone 13."
                },
                {
                    "Type": "Analytical",
                    "Description": "Aggregation, sorting, statistics",
                    "Example": "Which city had the highest average order value over the past 6 months?"
                },
                {
                    "Type": "Relational Reasoning",
                    "Description": "Multi-table joins, multi-hop logic, existence/exclusion relationships",
                    "Example": "Which users have placed orders but never left any product reviews on the platform?"
                },
                {
                    "Type": "Predictive",
                    "Description": "Inferring future behavior or state based on historical data",
                    "Example": "Based on historical behavior, which users are unlikely to place another order within the next 30 days?"
                }
            ]
        },
        "tables": []
    }

    tables_query = (
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='main' AND table_type='BASE TABLE'"
    )
    tables = [r[0] for r in con.execute(tables_query).fetchall()]

    # table Olist table (table)
    core_fact_tables = [
        "olist_orders_dataset",
        "olist_order_items_dataset",
        "olist_order_payments_dataset",
        "olist_order_reviews_dataset",
        "olist_customers_dataset",
        "olist_sellers_dataset"
    ]

    for table_name in tables:
        print(f"Processing table: {table_name} ...")
        table_meta = METADATA_INJECTION["tables"].get(table_name, {})

        #  Profile 
        if table_name in core_fact_tables:
            table_data = profile_olist_fact_table(con, table_name, table_meta)
        else:
            table_data = profile_lookup_table(con, table_name, table_meta)

        final_json["tables"].append(table_data)

    con.close()

    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(final_json, f, ensure_ascii=False, indent=2)
    print(f"\n✅ Done! JSON saved to: {output_json_path}")


# =====================================================================
# entry point
# =====================================================================
if __name__ == "__main__":
    database_name = "Olist"  #  Olist
    DB_PATH = f"DB/{database_name}.duckdb"
    OUTPUT_FILE = f"json/{database_name}/data_schema_profiling.json"

    with open(f"json/{database_name}/metadata_{database_name}.json", "r", encoding="utf-8") as f:
        METADATA_INJECTION = json.load(f)

    generate_llm_json(DB_PATH, OUTPUT_FILE, METADATA_INJECTION)