"""LLM-Router: Task-Aware System baseline."""

from typing import Dict, List, Tuple

from tqdm import tqdm

from ..database import get_db_path, get_schema
from ..model    import LLMWrapper
from ..parser   import parse_router_output
from ..prompts  import prompt_llm_router


class LLMRouterMethod:
    """
    Routes each question using the LLM, then dispatches to the
    appropriate native solver (reasoning_solver or predictive_solver).
    """

    def __init__(
        self,
        llm:               LLMWrapper,
        db_dir:            str,
        reasoning_solver,               # e.g. LLMSchemaMethod
        predictive_solver,              # e.g. LLMOnlyMethod
        cfg:               Dict = None,
    ):
        self.llm               = llm
        self.db_dir            = db_dir
        self.reasoning_solver  = reasoning_solver
        self.predictive_solver = predictive_solver
        self.cfg               = cfg or {}

    @staticmethod
    def _gold_track(inst: Dict) -> str:
        return (
            "Predictive"
            if inst["metadata"]["query_type"] == "Predictive"
            else "Reasoning"
        )

    def run(
        self,
        instances: List[Dict],
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        Returns
        -------
        routing_results : list of dicts with routing metadata (for routing metrics)
        e2e_results     : list of dicts with prediction results (for end-to-end metrics)
        """
        routing_results = []
        reasoning_batch, predictive_batch = [], []

        for inst in tqdm(instances, desc="LLM-Router (routing)"):
            domain  = self.cfg.get("db_name") or inst["instance_id"].split("_")[1].lower()
            db_path = get_db_path(self.db_dir, domain)
            schema  = get_schema(db_path)
            prompt  = prompt_llm_router(
                inst["question"]["primary_nl"], schema
            )
            raw   = self.llm.generate(
                prompt,
                max_new_tokens=self.cfg.get("max_pred_tokens", 256),
            )
            route = parse_router_output(raw)

            gold_track  = self._gold_track(inst)
            gold_tables = inst["metadata"]["complexity"].get(
                "tables_involved", []
            )
            routing_results.append({
                "instance_id":  inst["instance_id"],
                "pred_track":   route["track"],
                "gold_track":   gold_track,
                "pred_tables":  route.get("tables_involved", []),
                "gold_tables":  gold_tables,
            })

            if route["track"] == "Predictive":
                predictive_batch.append(inst)
            else:
                reasoning_batch.append(inst)

        # Execute dispatched batches
        print(f"  → Dispatched: Reasoning={len(reasoning_batch)}, "
              f"Predictive={len(predictive_batch)}")

        e2e_results = []
        if reasoning_batch:
            e2e_results.extend(self.reasoning_solver.run(reasoning_batch))
        if predictive_batch:
            e2e_results.extend(self.predictive_solver.run(predictive_batch))

        return routing_results, e2e_results
