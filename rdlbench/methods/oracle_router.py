"""Oracle-Router: upper-bound task-aware baseline using ground-truth routing."""

from typing import Dict, List, Tuple

from tqdm import tqdm


class OracleRouterMethod:
    """
    Routes each question using ground-truth query_type metadata,
    then dispatches to the appropriate native solver.
    This is the upper-bound for task-aware routing.
    """

    def __init__(
        self,
        reasoning_solver,
        predictive_solver,
        cfg: Dict = None,
    ):
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
        routing_results : list of dicts with perfect routing metadata
        e2e_results     : list of dicts with prediction results
        """
        routing_results = []
        reasoning_batch, predictive_batch = [], []

        for inst in tqdm(instances, desc="Oracle-Router (routing)"):
            gold_track  = self._gold_track(inst)
            gold_tables = inst["metadata"]["complexity"].get("tables_involved", [])

            routing_results.append({
                "instance_id": inst["instance_id"],
                "pred_track":  gold_track,   # oracle = always correct
                "gold_track":  gold_track,
                "pred_tables": gold_tables,   # oracle = always correct
                "gold_tables": gold_tables,
            })

            if gold_track == "Predictive":
                predictive_batch.append(inst)
            else:
                reasoning_batch.append(inst)

        print(f"  → Oracle dispatch: Reasoning={len(reasoning_batch)}, "
              f"Predictive={len(predictive_batch)}")

        e2e_results = []
        if reasoning_batch:
            e2e_results.extend(self.reasoning_solver.run(reasoning_batch))
        if predictive_batch:
            e2e_results.extend(self.predictive_solver.run(predictive_batch))

        return routing_results, e2e_results
