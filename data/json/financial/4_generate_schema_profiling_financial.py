import duckdb
import json


# =====================================================================
# 2. Core logic：merge schema, metadata, and data profiling
# =====================================================================
def generate_llm_json(db_path, output_json_path,METADATA_INJECTION):
    print(f"Connecting to DuckDB: {db_path}...")
    con = duckdb.connect(db_path, read_only=True)
    
    final_json = {
        "database_metadata": {
            "name": METADATA_INJECTION["database_name"],
            "description": METADATA_INJECTION["database_description"]
        },
        "tables": []
    }

    tables_query = "SELECT table_name FROM information_schema.tables WHERE table_schema='main' AND table_type='BASE TABLE'"
    tables = [r[0] for r in con.execute(tables_query).fetchall()]
    
    for table_name in tables:
        print(f"Table being processed: {table_name}")
        table_meta = METADATA_INJECTION["tables"].get(table_name, {})
        
        # build the base structure for the current table
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
                "column_stats": {}
            }
        }
        
        # 1. count total rows
        row_count = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        table_data["data_profiling"]["row_count"] = row_count

        if row_count > 0:
            # 2. get schema fields and compute profiling
            columns_info = con.execute(f"DESCRIBE {table_name}").fetchall()
            for col_info in columns_info:
                col_name, col_type = col_info[0], col_info[1]
                
                # merge field comments
                col_schema = {
                    "name": col_name,
                    "type": col_type,
                    "comment": table_meta.get("comments", {}).get(col_name, "")
                }
                table_data["schema"]["columns"].append(col_schema)
                
                # compute data profiling (numeric columns use extrema/mean; string columns use distributions)
                try:
                    if any(t in col_type.upper() for t in ['INT', 'DOUBLE', 'BIGINT', 'FLOAT']):
                        if not col_name.lower().endswith('id'): # avoid meaningless ID calculations
                            stats = con.execute(f"SELECT MIN({col_name}), MAX({col_name}), AVG({col_name}) FROM {table_name}").fetchone()
                            table_data["data_profiling"]["column_stats"][col_name] = {
                                "min": round(stats[0], 2) if stats[0] is not None else None,
                                "max": round(stats[1], 2) if stats[1] is not None else None,
                                "avg": round(stats[2], 2) if stats[2] is not None else None
                            }
                    elif 'VARCHAR' in col_type.upper():
                        dist_data = con.execute(f"SELECT {col_name}, COUNT(*) * 100.0 / {row_count} FROM {table_name} WHERE {col_name} IS NOT NULL GROUP BY {col_name} ORDER BY 2 DESC LIMIT 5").fetchall()
                        if dist_data:
                            distribution = {str(row[0]): f"{round(row[1], 1)}%" for row in dist_data}
                            table_data["data_profiling"]["column_stats"][col_name] = {
                                "top_distribution": distribution
                            }
                    elif 'DATE' in col_type.upper() or 'TIMESTAMP' in col_type.upper():
                        date_stats = con.execute(f"SELECT MIN({col_name}), MAX({col_name}) FROM {table_name}").fetchone()
                        table_data["data_profiling"]["column_stats"][col_name] = {
                            "min_date": str(date_stats[0]) if date_stats[0] is not None else None,
                            "max_date": str(date_stats[1]) if date_stats[1] is not None else None
                        }
                except Exception as e:
                    print(f"Calculated field {col_name} failed to generate profile: {e}")

        final_json["tables"].append(table_data)

    con.close()

    # =====================================================================
    # 3. export JSON
    # =====================================================================
    with open(output_json_path, 'w', encoding='utf-8') as f:
        json.dump(final_json, f, ensure_ascii=False, indent=2)
    print(f"Success! The complete JSON file has been saved to: {output_json_path}")

# entry point
if __name__ == "__main__":
    database_name = "stats"
    DB_PATH = f"DB/{database_name}.duckdb"
    OUTPUT_FILE = f"json/{database_name}/data_schema_profiling.json"

    with open(f"json/{database_name}/metadata_{database_name}.json", "r", encoding="utf-8") as f:
        METADATA_INJECTION = json.load(f)
    generate_llm_json(DB_PATH, OUTPUT_FILE, METADATA_INJECTION)