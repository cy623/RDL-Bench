import json
import re
from collections import Counter

def normalize_sql(sql):
    if not sql: return ""
    sql = sql.lower()
    sql = re.sub(r'\s+', ' ', sql).strip()
    return sql

def deduplicate_json_data(input_path, output_path):
    with open(input_path, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            print(f"Error: Failed to decode JSON from {input_path}. Please check the file format.")
            return

    seen_ids = set()
    seen_questions = set()
    
    clean_data = []
    removed_ids = 0
    removed_texts = 0

    print(f"--- start cleanning: {input_path} (original number: {len(data)}) ---")

    for item in data:
        instance_id = item.get('instance_id')
 
        question_text = item.get('question', {}).get('primary_nl', "").strip()
        
        
        if instance_id in seen_ids:
            print(f"[delete] repeat ID: {instance_id}")
            removed_ids += 1
            continue
            
        if question_text in seen_questions:
            print(f"[delete] repeat text (ID: {instance_id}): \"{question_text[:30]}...\"")
            removed_texts += 1
            continue


        clean_data.append(item)
        seen_ids.add(instance_id)
        seen_questions.add(question_text)


    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(clean_data, f, ensure_ascii=False, indent=2)

    print(f"save the unique records: {len(clean_data)} ")
    print(f"filtered ID duplicates: {removed_ids} ")
    print(f"filtered text duplicates: {removed_texts} ")
    print(f"output file: {output_path}")


input_file = ' '        
output_file = ' '  

deduplicate_json_data(input_file, output_file)