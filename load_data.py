"""Portable RDL-Bench data access. Ordinary reads do not run validation gates."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime
import importlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SPLITS = ("train", "validation", "test")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def manifest():
    return read(ROOT / "manifest.json")


def domain_info(domain):
    return manifest()["domains"][domain.lower()]


def qa(domain, split, *, canonical_reference_times=True):
    """Read QA objects in the published order, with NCAA cutoff normalization."""
    if split not in SPLITS:
        raise ValueError(f"Unknown split: {split}")
    info = domain_info(domain)
    rows = {r["instance_id"]: r for r in read(ROOT / info["instances"])}
    result = [deepcopy(rows[i]) for i in read(ROOT / info["splits"])[split]]
    if canonical_reference_times and info.get("reference_times"):
        overrides = {r["parent_question_id"]: r["model_reference_time"]
                     for r in read(ROOT / info["reference_times"])}
        for row in result:
            if row["metadata"]["query_type"] == "Predictive":
                row["metadata"]["reference_time"] = overrides[row["instance_id"]]
    return result


def support(domain, split):
    if split not in SPLITS:
        raise ValueError(f"Unknown split: {split}")
    return read(ROOT / domain_info(domain)["support_dir"] / f"{split}.json")


def adaptation_support(domain, split="train"):
    """Few-shot/full adaptation labels come from the target training split."""
    if split != "train":
        raise ValueError("Adaptation uses support/train. Validation is for model selection; test is evaluation-only.")
    return support(domain, "train")


def prediction_test(domain=None, *, include_labels=False):
    """Read predictive QA test questions plus support/test directly from data/.

    No additional instance list is needed. Answers are omitted by default.
    relevant_tables/task_type/reference_time in these rows are annotations.
    A system that evaluates generated Task Specs must substitute its predictions.
    """
    data = manifest()
    domains = [domain.lower()] if domain else list(data["domains"])
    unknown = set(domains) - data["domains"].keys()
    if unknown:
        raise ValueError(f"Unknown domain: {sorted(unknown)}")
    rows = []
    for name in domains:
        for source in qa(name, "test"):
            meta = source["metadata"]
            if meta["query_type"] != "Predictive":
                continue
            uid = f'{name}::{source["instance_id"]}'
            row = dict(sample_id=uid, uid=uid, domain=name,
                parent_question_id=source["instance_id"], parent_split="test",
                role="qa/test", source_role="qa/test", question=source["question"]["primary_nl"],
                anchor=deepcopy(source["target_instances"][0]),
                reference_time=datetime.fromisoformat(meta["reference_time"]).strftime("%Y-%m-%d %H:%M:%S"),
                task_type="Classification" if meta["answer_nature"] == "Boolean" else "Regression",
                relevant_tables=list(meta["complexity"]["tables_involved"]))
            if include_labels:
                row["label"] = float(source["ground_truth"]["raw_value"])
            rows.append(row)
        for source in support(name, "test"):
            row = deepcopy(source)
            label = row.pop("label")
            row.update(uid=f'{name}::{row["sample_id"]}',
                       parent_uid=f'{name}::{row["parent_question_id"]}',
                       role="qa/test", source_role="support/test")
            if include_labels:
                row["label"] = float(label)
            rows.append(row)
    return rows


def open_database(domain):
    """Full read-only snapshot for executing the QA evidence SQL."""
    import duckdb
    return duckdb.connect(str(ROOT / domain_info(domain)["database"]), read_only=True)


def open_history(domain, reference_time):
    """Historical feature views using the released domain-specific policies."""
    name = domain.lower()
    if name == "hepatitis":
        raise ValueError("Hepatitis has no Prediction tasks")
    info = domain_info(name)
    module = importlib.import_module(f"history_views.{name}")
    return module.open_history(ROOT / info["database"], reference_time,
                               ROOT / info["support_dir"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", action="store_true")
    parser.parse_args()
    data = manifest()
    print("RDL-Bench", data["version"])
    print(f"{'Domain':12} {'QA train':>9} {'QA val':>9} {'QA test':>9} {'Sup train':>10} {'Sup val':>9} {'Sup test':>10} {'Pred test':>10}")
    for name, info in data["domains"].items():
        c = info["counts"]
        print(f"{name:12}" + "".join(f"{c[k]:10}" for k in (
            "qa_train", "qa_validation", "qa_test", "support_train", "support_validation", "support_test", "prediction_test")))
    print("Totals:", json.dumps(data["totals"]))


if __name__ == "__main__":
    main()
