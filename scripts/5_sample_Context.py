import duckdb
import random

def sample_db_values(db_path, tables_config):
  
    conn = duckdb.connect(db_path)
    samples = {}
    
    for table, columns in tables_config.items():
        samples[table] = {}
        for col in columns:
            
            query = f"SELECT DISTINCT {col} FROM {table} WHERE {col} IS NOT NULL ORDER BY RANDOM() LIMIT 5"
            vals = [str(row[0]) for row in conn.execute(query).fetchall()]
            samples[table][col] = vals
            
    conn.close()
    return samples


config = {

    "incidents": [
        "date",                        
        "location",                   
        "subject_statuses",           
        "subject_weapon",              
        "subject_count",               
        "officer_count",               
        "grand_jury_disposition",     
        "latitude",                    
        "longitude"                    
    ],


    "officers": [
        "race",                        
        "gender",                       
        "full_name"                  
        
    ],



    "subjects": [
        "race",                        
        "gender",                      
        "full_name"                    
    ]
}
database_name = " "
DB_PATH = f"DB/{database_name}.duckdb"
sampled_data = sample_db_values(DB_PATH, config)
print(sampled_data)