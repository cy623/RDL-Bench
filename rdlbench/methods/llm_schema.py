"""LLM-Schema: Reasoning Track baseline using schema-only prompting."""

from typing import Dict, List

from tqdm import tqdm

from ..database import get_db_path, get_schema, execute_sql
from ..dataset  import get_few_shot_examples
from ..model    import LLMWrapper
from ..parser   import extract_sql, normalize_sql_result, parse_ground_truth
from ..prompts  import prompt_llm_schema


class LLMSchemaMethod:

    def __init__(
        self,
        llm:             LLMWrapper,
        db_dir:          str,
        train_instances: List[Dict],
        cfg:             Dict = None,
    ):
        self.llm    = llm
        self.db_dir = db_dir
        self.train  = train_instances
        self.cfg    = cfg or {}

    def run(self, instances: List[Dict]) -> List[Dict]:
        results = []
        for inst in tqdm(instances, desc="LLM-Schema"):
            domain   = self.cfg.get("db_name") or inst["instance_id"].split("_")[1].lower()
            db_path  = get_db_path(self.db_dir, domain)
            schema   = get_schema(db_path)
            shots    = get_few_shot_examples(
                self.train,
                inst["metadata"]["query_type"],
                n    = self.cfg.get("n_shots", 3),
                seed = self.cfg.get("seed", 42),
            )
            prompt   = prompt_llm_schema(
                inst["question"]["primary_nl"], schema, shots
            )
            raw      = self.llm.generate(
                prompt,
                max_new_tokens=self.cfg.get("max_sql_tokens", 512),
            )
            pred_sql = extract_sql(raw)
            rows, err = execute_sql(pred_sql, db_path)

            an   = inst["metadata"]["answer_nature"]
            pred = normalize_sql_result(rows, an) if err is None else None
            gold = parse_ground_truth(inst["ground_truth"], an)

            results.append({
                "instance_id":   inst["instance_id"],
                "query_type":    inst["metadata"]["query_type"],
                "answer_nature": an,
                "prediction":    pred,
                "gold":          gold,
                "pred_sql":      pred_sql,
                "gold_sql":      inst["evidence"]["golden_sql"],
                "exec_error":    err,
            })
        return results
