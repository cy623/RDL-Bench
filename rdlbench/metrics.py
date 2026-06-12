"""All evaluation metrics for RDL-Bench."""

import re
from collections import defaultdict
from typing import Any, Dict, List, Optional

import numpy as np
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score
import unicodedata

# ── Reasoning metrics ──────────────────────────────────────────────────────

def normalized_em(pred: Any, gold: Any, tol: float = 0.01) -> float:
    """Normalized Exact Match for Scalar answers."""
    if pred is None or gold is None:
        return 0.0
    try:
        p, g = float(pred), float(gold)
        if g == 0:
            return 1.0 if abs(p) < 1e-6 else 0.0
        return 1.0 if abs(p - g) / abs(g) <= tol else 0.0
    except (TypeError, ValueError):
        return 1.0 if str(pred).strip().lower() == str(gold).strip().lower() else 0.0


def set_f1(pred: List[str], gold: List[str]) -> float:
    """Token-level Set-F1."""
    if not pred and not gold:
        return 1.0
    if not pred or not gold:
        return 0.0
    pred_set = {str(x).strip().lower() for x in pred}
    gold_set = {str(x).strip().lower() for x in gold}
    tp = len(pred_set & gold_set)
    if tp == 0:
        return 0.0
    p = tp / len(pred_set)
    r = tp / len(gold_set)
    return 2 * p * r / (p + r)


def boolean_acc(pred: Any, gold: Any) -> float:
    if pred is None or gold is None:
        return 0.0
    return 1.0 if bool(pred) == bool(gold) else 0.0


def ndcg_at_k(pred: List, gold: List, k: int = 5) -> float:
    """NDCG@k for ranking answers."""
    if not pred or not gold:
        return 0.0
    gold_rel  = {str(x).lower(): 1 for x in gold}
    relevance = [gold_rel.get(str(x).lower(), 0) for x in pred[:k]]
    ideal     = sorted(gold_rel.values(), reverse=True)[:k]
    if sum(ideal) == 0:
        return 0.0
    relevance = (relevance + [0] * k)[:k]
    ideal     = (ideal     + [0] * k)[:k]

    def dcg(rels):
        return sum(r / np.log2(i + 2) for i, r in enumerate(rels))

    idcg = dcg(ideal)
    return dcg(relevance) / idcg if idcg > 0 else 0.0


def sql_exact_match(pred_sql: str, gold_sql: str) -> float:
    """Auxiliary: normalized SQL exact match."""
    def norm(s): return re.sub(r"\s+", " ", s.lower().strip().rstrip(";"))
    return 1.0 if norm(pred_sql) == norm(gold_sql) else 0.0


# ── Predictive metrics ─────────────────────────────────────────────────────

def auroc(preds: List, golds: List) -> Optional[float]:
    pairs = [(p, g) for p, g in zip(preds, golds)
             if p is not None and g is not None]
    if len(pairs) < 2:
        return None
    ps, gs = zip(*pairs)
    try:
        return float(roc_auc_score([bool(g) for g in gs], [bool(p) for p in ps]))
    except ValueError:
        return None


def f1_binary(preds: List, golds: List) -> float:
    pairs = [(p, g) for p, g in zip(preds, golds)
             if p is not None and g is not None]
    if not pairs:
        return 0.0
    ps, gs = zip(*pairs)
    return float(f1_score(
        [bool(g) for g in gs], [bool(p) for p in ps], zero_division=0
    ))


def mae(preds: List, golds: List) -> Optional[float]:
    pairs = [(float(p), float(g)) for p, g in zip(preds, golds)
             if p is not None and g is not None]
    if not pairs:
        return None
    ps, gs = zip(*pairs)
    return float(np.mean(np.abs(np.array(ps) - np.array(gs))))


def rmse(preds: List, golds: List) -> Optional[float]:
    pairs = [(float(p), float(g)) for p, g in zip(preds, golds)
             if p is not None and g is not None]
    if not pairs:
        return None
    ps, gs = zip(*pairs)
    return float(np.sqrt(np.mean((np.array(ps) - np.array(gs)) ** 2)))


# ── Routing metrics ────────────────────────────────────────────────────────

def track_accuracy(results: List[Dict]) -> float:
    correct = [
        1.0 if r["pred_track"].lower() == r["gold_track"].lower() else 0.0
        for r in results
    ]
    return float(np.mean(correct)) if correct else 0.0


def table_f1(results: List[Dict]) -> float:
    scores = []
    for r in results:
        pred = {t.lower() for t in r.get("pred_tables", [])}
        gold = {t.lower() for t in r.get("gold_tables", [])}
        if not pred and not gold:
            scores.append(1.0)
            continue
        if not pred or not gold:
            scores.append(0.0)
            continue
        tp  = len(pred & gold)
        p   = tp / len(pred)
        rec = tp / len(gold)
        scores.append(2 * p * rec / (p + rec) if (p + rec) > 0 else 0.0)
    return float(np.mean(scores)) if scores else 0.0


# ── Aggregation ────────────────────────────────────────────────────────────

# def compute_reasoning_metrics(results: List[Dict], ndcg_k: int = 5) -> Dict:
#     """Aggregate Reasoning Track metrics by answer_nature."""
#     by_nature = defaultdict(list)
#     sql_ems   = []

#     for r in results:
#         an   = r["answer_nature"]
#         pred = r["prediction"]
#         gold = r["gold"]

#         if an == "Scalars":
#             by_nature["Scalars"].append(normalized_em(pred, gold))
#         elif an == "Sets":
#             by_nature["Sets"].append(set_f1(pred or [], gold or []))
#         elif an == "Boolean":
#             by_nature["Boolean"].append(boolean_acc(pred, gold))
#         elif an == "Rankings":
#             by_nature["Rankings"].append(ndcg_at_k(pred or [], gold or [], k=ndcg_k))

#         if r.get("pred_sql") and r.get("gold_sql"):
#             sql_ems.append(sql_exact_match(r["pred_sql"], r["gold_sql"]))

#     out = {k: float(np.mean(v)) for k, v in by_nature.items() if v}
#     if sql_ems:
#         out["SQL_EM (aux)"] = float(np.mean(sql_ems))

#     valid = [v for k, v in out.items() if "aux" not in k]
#     out["Overall"] = float(np.mean(valid)) if valid else None
#     return out

import re
import math
from typing import Any, Optional


def parse_number(x: Any) -> Optional[float]:
    """Parse a scalar numeric value from int/float/string.

    Returns None if x is not a clean numeric scalar.
    """
    if x is None:
        return None

    if isinstance(x, bool):
        return None

    if isinstance(x, (int, float)):
        if math.isnan(float(x)) or math.isinf(float(x)):
            return None
        return float(x)

    if isinstance(x, str):
        s = x.strip().replace(",", "")

        # Remove common harmless wrappers.
        s = s.replace("$", "").replace("%", "")

        # Require the whole string to be numeric.
        # This avoids treating "case 203348T" as 203348.
        if re.fullmatch(r"[-+]?\d+(\.\d+)?", s):
            return float(s)

    return None


def is_numeric_value(x: Any) -> bool:
    """Return True if x is a numeric scalar."""
    return parse_number(x) is not None


def numeric_match(pred: Any, gold: Any, rel_tol: float = 1e-3, abs_tol: float = 1e-6) -> float:
    """Tolerance-based numeric match."""
    p = parse_number(pred)
    g = parse_number(gold)

    if p is None or g is None:
        return 0.0

    return float(math.isclose(p, g, rel_tol=rel_tol, abs_tol=abs_tol))


def normalize_answer_nature(an: str) -> str:
    mapping = {
        "Scalar": "Scalar",
        "Scalars": "Scalar",
        "Set": "Set",
        "Sets": "Set",
        "Boolean": "Boolean",
        "Ranking": "Ranking",
        "Rankings": "Ranking",
    }
    return mapping.get(an, an)

def normalize_text(x: Any, case_sensitive: bool = False) -> str:
    """Normalize text for exact-match style evaluation."""
    if x is None:
        return ""

    # Convert non-string values to string.
    s = str(x)

    # Unicode normalization.
    s = unicodedata.normalize("NFKC", s)

    # Strip leading/trailing whitespace.
    s = s.strip()

    # Case normalization.
    if not case_sensitive:
        s = s.lower()

    # Normalize whitespace.
    s = re.sub(r"\s+", " ", s)

    # Remove common trailing punctuation.
    s = s.strip(" \t\n\r.,;:")

    return s


def textual_match(pred: Any, gold: Any, case_sensitive: bool = False) -> float:
    """Normalized exact match for textual scalar answers."""
    return float(
        normalize_text(pred, case_sensitive=case_sensitive)
        == normalize_text(gold, case_sensitive=case_sensitive)
    )


def compute_reasoning_metrics(results: List[Dict], ndcg_k: int = 5) -> Dict:
    """
    Aggregate Reasoning Track metrics.

    Returns:
        - Per-answer-nature metrics
        - Overall micro average: instance-level average
        - Overall macro average: unweighted average over answer types
        - SQL_EM as an auxiliary metric
    """
    by_nature = defaultdict(list)
    sql_ems = []
    all_scores = []

    for r in results:
        an = normalize_answer_nature(r["answer_nature"])
        pred = r.get("prediction")
        gold = r.get("gold")
        score = None

        if an == "Scalar":
            if is_numeric_value(gold):
                score = numeric_match(pred, gold, rel_tol=1e-3, abs_tol=1e-6)
            else:
                score = textual_match(pred, gold, case_sensitive=False)
            by_nature["Scalar"].append(score)

        elif an == "Set":
            score = set_f1(pred or [], gold or [])
            by_nature["Set"].append(score)

        elif an == "Boolean":
            score = boolean_acc(pred, gold)
            by_nature["Boolean"].append(score)

        elif an == "Ranking":
            score = ndcg_at_k(pred or [], gold or [], k=ndcg_k)
            by_nature["Ranking"].append(score)

        else:
            # Optional: log unknown answer nature.
            continue

        if score is not None:
            all_scores.append(score)

        # SQL EM is auxiliary. If gold SQL exists, missing predicted SQL is failure.
        if r.get("gold_sql"):
            sql_ems.append(
                sql_exact_match(r.get("pred_sql", ""), r["gold_sql"])
            )

    out = {}

    for k, v in by_nature.items():
        if v:
            out[k] = float(np.mean(v))

    out["Overall (micro)"] = float(np.mean(all_scores)) if all_scores else None

    macro_values = [float(np.mean(v)) for v in by_nature.values() if v]
    out["Overall (macro)"] = float(np.mean(macro_values)) if macro_values else None

    if sql_ems:
        out["SQL_EM (aux)"] = float(np.mean(sql_ems))

    return out


def nMAE(preds: List, golds: List) -> Optional[float]:
    """Normalized MAE: MAE / (mean(|y_true|) + 1e-8)."""
    pairs = [(float(p), float(g)) for p, g in zip(preds, golds)
             if p is not None and g is not None]
    if not pairs:
        return None
    ps, gs = np.array([p for p, _ in pairs]), np.array([g for _, g in pairs])
    mae_val = float(np.mean(np.abs(ps - gs)))
    return mae_val / (float(np.mean(np.abs(gs))) + 1e-8)


def compute_predictive_metrics(results: List[Dict]) -> Dict:
    """Aggregate Predictive Track metrics (AUROC/F1 for Boolean, MAE/RMSE/nMAE for Scalar)."""
    bool_res   = [(r["prediction"], r["gold"])
                  for r in results
                  if normalize_answer_nature(r.get("answer_nature", "")) == "Boolean"]
    scalar_res = [(r["prediction"], r["gold"])
                  for r in results
                  if normalize_answer_nature(r.get("answer_nature", "")) == "Scalar"]

    out = {}
    if bool_res:
        ps, gs = zip(*bool_res)
        out["Boolean/AUC"] = auroc(list(ps), list(gs))
        out["Boolean/F1"]  = f1_binary(list(ps), list(gs))
    if scalar_res:
        ps, gs = zip(*scalar_res)
        out["Scalar/MAE"]  = mae(list(ps), list(gs))
        out["Scalar/RMSE"] = rmse(list(ps), list(gs))
        out["Scalar/nMAE"] = nMAE(list(ps), list(gs))
    return out


def compute_routing_metrics(results: List[Dict]) -> Dict:
    return {
        "Track_Accuracy": track_accuracy(results),
        "Table_F1":       table_f1(results),
    }
