"""LLM-only: Predictive Track data-blind baseline."""

from typing import Dict, List

from tqdm import tqdm

from ..database import get_db_path, get_schema, get_profiling_summary
from ..dataset  import get_few_shot_examples
from ..model    import LLMWrapper
from ..parser   import extract_prediction, parse_ground_truth
from ..prompts  import prompt_llm_only


class LLMOnlyMethod:

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
        # Only operate on Predictive instances
        pred_instances = [
            i for i in instances
            if i["metadata"]["query_type"] == "Predictive"
        ]
        results = []
        for inst in tqdm(pred_instances, desc="LLM-only"):
            domain    = self.cfg.get("db_name") or inst["instance_id"].split("_")[1].lower()
            db_path   = get_db_path(self.db_dir, domain)
            schema    = get_schema(db_path)
            profiling = get_profiling_summary(
                db_path,
                sample_rows=self.cfg.get("sample_rows", 3),
            )
            an    = inst["metadata"]["answer_nature"]
            shots = get_few_shot_examples(
                self.train,
                "Predictive",
                n    = self.cfg.get("n_shots", 3),
                seed = self.cfg.get("seed", 42),
            )
            prompt = prompt_llm_only(
                inst["question"]["primary_nl"],
                schema, profiling, shots, an,
            )
            raw  = self.llm.generate(
                prompt,
                max_new_tokens=self.cfg.get("max_pred_tokens", 256),
            )
            pred = extract_prediction(raw, an)
            gold = parse_ground_truth(inst["ground_truth"], an)

            results.append({
                "instance_id":   inst["instance_id"],
                "query_type":    "Predictive",
                "answer_nature": an,
                "prediction":    pred,
                "gold":          gold,
                "raw_output":    raw,
            })
        return results
