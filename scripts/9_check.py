import json
import duckdb
import pandas as pd

import json
import duckdb
import pandas as pd
import re

class RDBDataValidator:
    def __init__(self, db_path):
    
        self.con = duckdb.connect(db_path)
        self.report = []

    def load_schema_data(self, setup_sql_path=None):
      
        if setup_sql_path:
            with open(setup_sql_path, 'r') as f:
                self.con.execute(f.read())

    def _check_order_by(self, sql):
        return bool(re.search(r"ORDER\s+BY", sql, re.IGNORECASE))

    def _normalize(self, value):
        
        if pd.isna(value): return None
        return str(value).strip()

    def compare_logic(self, actual_df, expected_val, k=5):
        
        if actual_df.empty:
            return False, "Actual result is empty"

   
        if isinstance(expected_val, list):
            actual_top_k = actual_df
            
   
            if len(expected_val) > 0 and isinstance(expected_val[0], dict):
                actual_list = actual_top_k.to_dict('records')
                for i in expected_val:
                    if i in actual_list:
                        continue
                    else:
                        return False
                return True, "List Comparison"
            else:
                actual_list = [self._normalize(x) for x in actual_top_k.iloc[:, 0].tolist()]
                expected_list = [self._normalize(x) for x in expected_val]
                for i in expected_val:
                    if i in actual_list:
                        continue
                    else:
                        return False
                return True, "List Comparison"

        else:
            actual_scalar = self._normalize(actual_df.iloc[0, 0])
            expected_scalar = self._normalize(expected_val)
            return actual_scalar == expected_scalar, "Scalar Comparison"

    def validate(self, json_data_path):
        with open(json_data_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        

        if isinstance(data, dict): data = [data]

        for entry in data:
            iid = entry.get("instance_id", "Unknown")
            sql = entry["evidence"]["golden_sql"]
            expected = entry["ground_truth"]["raw_value"]
            
            status = {"instance_id": iid, "sql": sql, "pass": False, "note": ""}


            is_list = isinstance(expected, list)
            has_order = self._check_order_by(sql)
            if is_list and not has_order:
                status["note"] += "[Warning: No ORDER BY in List Query] "

            try:

                actual_df = self.con.execute(sql).df()

                is_match, msg = self.compare_logic(actual_df, expected)
                status["pass"] = is_match
                status["note"] += msg
                
                if not is_match:
                    status["details"] = f"Expected: {expected} | Got: {actual_df.head(5).values.tolist()}"
                    print(status["instance_id"], status["details"])

            except Exception as e:
                status["pass"] = False
                status["note"] = f"Execution Error: {str(e)}"

            self.report.append(status)




if __name__ == "__main__":
    database_name = " "
    db_path = f"DB/{database_name}.duckdb"
    validator = RDBDataValidator(db_path=db_path)

    validator.validate(' ')
  