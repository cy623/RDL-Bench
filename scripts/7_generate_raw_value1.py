import json
import duckdb  
import os
import datetime
import json
import duckdb



def execute_and_fill_truth(json_input_path, json_output_path, db_path):

    with open(json_input_path, 'r', encoding='utf-8') as f:
        instances = json.load(f)


    con = duckdb.connect(db_path)

    success_count = 0
    error_count = 0
    empty_count = 0

    kept_instances = [] 

    print(f"Processing {len(instances)} instances...")

    for item in instances:
        sql = item['evidence']['golden_sql']
        nature = item['metadata']['answer_nature']
        iid = item['instance_id']
        qtype = item['metadata']['query_type']

        try:
            rel = con.execute(sql)
            cols = [desc[0] for desc in rel.description]
            rows = rel.fetchall()

            if qtype == "Predictive" or qtype == "predictive":
                if not rows:
                    val = 0 if "COUNT" in sql.upper() else False
                    empty_count += 1
                    print(f"[{iid}] The result is empty.")
                else:
                    if len(rows) == 1 and len(rows[0]) == 1:
                        val = rows[0][0]
                    else:
                        val = True if len(rows) > 0 else False

                item.setdefault('ground_truth', {})
                item['ground_truth']['raw_value'] = val

            else:
                if not rows:
                    item.setdefault('ground_truth', {})
                    item['ground_truth']['raw_value'] = None if nature == "Scalars" else []
                    empty_count += 1
                    print(f"[{iid}] The result is empty.")
                else:
                    item.setdefault('ground_truth', {})

                    if nature == "Scalars":
                        item['ground_truth']['raw_value'] = rows[0][0]

                    elif nature == "Boolean":
                        item['ground_truth']['raw_value'] = len(rows) > 0

                    elif nature in ["Rankings"]:
                        if len(cols) == 1:
                            item['ground_truth']['raw_value'] = [row[0] for row in rows]
                        else:
                            item['ground_truth']['raw_value'] = [list(row) for row in rows]

                    elif nature in ["Sets"]:
                        total_count = len(rows)
                        if len(cols) == 1:
                            flattened = [row[0] for row in rows]
                        else:
                            flattened = [list(row) for row in rows]

                        cleaned_values = flattened[:5]
                        is_truncated = total_count > 5

                        item['ground_truth']['raw_value'] = {
                            "total_count": total_count,
                            "values": cleaned_values,
                            "is_truncated": is_truncated
                        }

            success_count += 1
            kept_instances.append(item)  

        except Exception as e:
            error_count += 1
            print(f" [{iid}] SQL failed: {e}")

    with open(json_output_path, 'w', encoding='utf-8') as f:
        json.dump(kept_instances, f, indent=2, ensure_ascii=False, default=json_default)

    print("\n--- Finish ---")
    print(f"Success: {success_count}")
    print(f"Empty results (still kept): {empty_count} ")
    print(f"Execution failed (removed): {error_count}")
    print(f"Output count: {len(kept_instances)} / Input count: {len(instances)}")


def json_default(o):
    if isinstance(o, (datetime.date, datetime.datetime)):
        return o.isoformat() 
    return str(o)  


database_name = " "
json_input_path = f'query_cleaned.json'
DB_PATH = f"DB/{database_name}.duckdb"
json_output_path = f" "

execute_and_fill_truth(json_input_path, json_output_path, DB_PATH)