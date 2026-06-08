import duckdb
import json

def generate_metadata_template(db_path, output_json_path):
    print(f"Scanning the DuckDB database: {db_path}...")
    con = duckdb.connect(db_path, read_only=True)
    
    template = {
        "database_name": "TODO",
        "database_description": "TODO",
        "tables": {}
    }

    tables_query = "SELECT table_name FROM information_schema.tables WHERE table_schema='main' AND table_type='BASE TABLE'"
    tables = [r[0] for r in con.execute(tables_query).fetchall()]
    
    for table_name in tables:

        table_info = {
            "description": f"TODO",
            "primary_key": [
                "TODO"
            ],
            "foreign_keys": [
                "TODO"
            ],
            "comments": {}
        }
        

        columns_query = f"SELECT column_name FROM information_schema.columns WHERE table_name='{table_name}'"
        columns = [r[0] for r in con.execute(columns_query).fetchall()]
        
        for col_name in columns:
            hint = ""
            if col_name.lower().endswith('id'):
                hint = " (maybe foreign or primary key?)"
            
            table_info["comments"][col_name] = f"TODO{hint}"
            
        template["tables"][table_name] = table_info
    

    con.close()

    with open(output_json_path, 'w', encoding='utf-8') as f:
        json.dump(template, f, ensure_ascii=False, indent=2)
        
    print(f"Template generated! Please open [{output_json_path}] and fill in the blanks.")

if __name__ == "__main__":
    database_name = " "
    DB_PATH = f"DB/{database_name}.duckdb"

    TEMPLATE_FILE = f"json/{database_name}/metadata_{database_name}.json"
    
    generate_metadata_template(DB_PATH, TEMPLATE_FILE)