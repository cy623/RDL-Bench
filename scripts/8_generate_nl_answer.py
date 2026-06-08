import json
import os

def backfill_nl_answers(master_path, batch_path, output_path):
    
    if not os.path.exists(master_path):
        print(f"Wrong path: {master_path}")
        return
    
    with open(master_path, 'r', encoding='utf-8') as f:
        master_data = json.load(f)

    if not os.path.exists(batch_path):
        print(f"Wrong path: {batch_path}")
        return

    with open(batch_path, 'r', encoding='utf-8') as f:
        batch_results = json.load(f)


    answer_map = {item['instance_id']: item for item in batch_results}

    update_count = 0
    

    for item in master_data:
        iid = item.get('instance_id')
        
        if iid in answer_map:
            print(f"Processing, instance_id: {iid}")
            new_data = answer_map[iid]
            
            if 'ground_truth' not in item:
                item['ground_truth'] = {}

            if new_data.get('formatted_nl_answer') == None:
                formatted_nl_answer = new_data.get('ground_truth').get('formatted_nl_answer')
                nl_answer_variants = new_data.get('ground_truth').get('nl_answer_variants')
            else:
                formatted_nl_answer = new_data.get('formatted_nl_answer')
                nl_answer_variants = new_data.get('nl_answer_variants')
            item['ground_truth']['formatted_nl_answer'] = formatted_nl_answer
            print(formatted_nl_answer)
            item['ground_truth']['nl_answer_variants'] = nl_answer_variants

            update_count += 1


    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(master_data, f, indent=2, ensure_ascii=False)

    print(f"\n--- Finish ---")
    print(f"Success: {update_count} records updated")
    print(f"Results saved to: {output_path}")


database_name = " "
json_output_path = f" "
batch_json = f' '
backfill_nl_answers(json_output_path, batch_json, ' ')

