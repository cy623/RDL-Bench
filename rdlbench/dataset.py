"""Dataset loading and splitting utilities."""

from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np


REASONING_TYPES  = ["Retrieval", "Analytical", "Relational Reasoning"]
PREDICTIVE_TYPES = ["Predictive"]


def load_dataset(data_dir: str) -> List[Dict]:
    """Load all instances from JSON files under data_dir (file or directory)."""
    import json
    p = Path(data_dir)
    paths = [p] if p.is_file() else sorted(p.rglob("*.json"))
    instances = []
    for path in paths:
        with open(path) as f:
            data = json.load(f)
        if isinstance(data, list):
            items = [x for x in data if isinstance(x, dict) and "instance_id" in x]
            instances.extend(items)
        elif isinstance(data, dict) and "instance_id" in data:
            instances.append(data)
    print(f"[Dataset] Loaded {len(instances)} instances from {data_dir}")
    return instances


def get_domain(instance: Dict) -> str:
    """Extract domain from instance_id (e.g. RDB_FIN_001 → fin)."""
    parts = instance["instance_id"].split("_")
    return parts[1].lower() if len(parts) > 1 else "unknown"


def stratified_split(
    instances:   List[Dict],
    train_ratio: float = 0.6,
    val_ratio:   float = 0.2,
    seed:        int   = 42,
) -> Tuple[List[Dict], List[Dict], List[Dict]]:
    """
    Stratified 60/20/20 split by domain × query_type.
    Returns (train, val, test).
    """
    groups: Dict[str, List[int]] = defaultdict(list)
    for i, inst in enumerate(instances):
        domain     = get_domain(inst)
        query_type = inst["metadata"]["query_type"]
        groups[f"{domain}_{query_type}"].append(i)

    train_idx, val_idx, test_idx = [], [], []
    rng = np.random.default_rng(seed)

    for key, idxs in groups.items():
        idxs = np.array(idxs)
        rng.shuffle(idxs)
        n     = len(idxs)
        n_tr  = max(1, int(n * train_ratio))
        n_val = max(1, int(n * val_ratio))
        train_idx.extend(idxs[:n_tr].tolist())
        val_idx.extend(  idxs[n_tr : n_tr + n_val].tolist())
        test_idx.extend( idxs[n_tr + n_val:].tolist())

    train = [instances[i] for i in train_idx]
    val   = [instances[i] for i in val_idx]
    test  = [instances[i] for i in test_idx]

    print(f"[Split] Train={len(train)} Val={len(val)} Test={len(test)}")
    return train, val, test


def get_few_shot_examples(
    train_instances: List[Dict],
    query_type:      str,
    n:               int = 3,
    seed:            int = 42,
) -> List[Dict]:
    """Sample n in-context examples of the same query_type."""
    pool = [x for x in train_instances
            if x["metadata"]["query_type"] == query_type]
    if not pool:
        pool = train_instances
    rng    = np.random.default_rng(seed)
    chosen = rng.choice(len(pool), size=min(n, len(pool)), replace=False)
    return [pool[i] for i in chosen]


def filter_by_track(instances: List[Dict], track: str) -> List[Dict]:
    """Filter instances by 'Reasoning' or 'Predictive' track."""
    if track == "Reasoning":
        return [i for i in instances
                if i["metadata"]["query_type"] in REASONING_TYPES]
    elif track == "Predictive":
        return [i for i in instances
                if i["metadata"]["query_type"] in PREDICTIVE_TYPES]
    return instances
