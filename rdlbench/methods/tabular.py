"""Tabular baselines for the Predictive Track: XGBoost and LightGBM.

Entity-level pipeline (one prediction per anchor entity per template):
  1. For each trainable Predictive instance call instantiate_predictive_template
     → PredictiveDataset with entity-level (feature, label) pairs
  2. Align features across templates to a common feature space (pad missing → 0)
  3. Pool training examples across all templates by task_type
  4. Train one model per task_type (classification / regression)
  5. Evaluate on per-template test splits
  6. Return aggregate metrics (AUROC/F1 for Boolean, MAE/RMSE/nMAE for Scalar)
"""

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from tqdm import tqdm

from ..database import get_db_path
from ..predictive_task import (
    build_predictive_task_template, is_trainable, normalize_answer_nature,
)
from ..predictive_dataset import instantiate_predictive_template, PredictiveDataset

logger = logging.getLogger(__name__)


# ── Dataset collection ─────────────────────────────────────────────────────

def collect_predictive_datasets(
    instances:    List[Dict],
    db_dir:       str,
    cfg:          Dict,
    seed:         int,
) -> Tuple[List[PredictiveDataset], Dict]:
    """
    Build a PredictiveDataset for every trainable Predictive instance.
    Returns (datasets, instantiation_stats).
    """
    stats: Dict = {
        "total_predictive_instances":               0,
        "used_for_trained_baselines":               0,
        "skipped_non_classification_or_regression": 0,
        "skipped_missing_anchor_entity":            0,
        "avg_entities_per_template":                0.0,
    }
    datasets: List[PredictiveDataset] = []
    entity_counts: List[int] = []

    for inst in tqdm(instances, desc="Building PredictiveDatasets"):
        if inst["metadata"].get("query_type") != "Predictive":
            continue
        stats["total_predictive_instances"] += 1

        an = normalize_answer_nature(inst["metadata"].get("answer_nature", ""))
        if an not in ("Boolean", "Scalar"):
            stats["skipped_non_classification_or_regression"] += 1
            continue

        iid    = inst["instance_id"]
        # cfg["db_name"] set by caller when loading a single dataset file;
        # fall back to instance_id parse only when not provided.
        domain = cfg.get("db_name") or (iid.split("_")[1].lower() if "_" in iid else "")
        db_path = get_db_path(db_dir, domain)

        template = build_predictive_task_template(inst, db_path)
        if template is None:
            stats["skipped_missing_anchor_entity"] += 1
            continue

        dataset = instantiate_predictive_template(
            template, db_path,
            max_entities=cfg.get("max_entities", 5000),
            seed=seed,
        )
        if dataset is None:
            stats["skipped_missing_anchor_entity"] += 1
            continue

        datasets.append(dataset)
        stats["used_for_trained_baselines"] += 1
        entity_counts.append(len(dataset.anchor_entities))

    if entity_counts:
        stats["avg_entities_per_template"] = float(np.mean(entity_counts))
    return datasets, stats


# ── Feature alignment ──────────────────────────────────────────────────────

def _pad_df_to_cols(
    df:           pd.DataFrame,
    anchor_col:   str,
    all_feat_cols: List[str],
) -> np.ndarray:
    """Reindex df's feature columns to all_feat_cols, missing → 0."""
    X = np.zeros((len(df), len(all_feat_cols)), dtype=np.float32)
    for j, col in enumerate(all_feat_cols):
        if col in df.columns:
            X[:, j] = pd.to_numeric(df[col], errors="coerce").fillna(0.0).values
    return X


def _build_aligned_data(
    datasets: List[PredictiveDataset],
) -> Tuple[Dict, Dict, Dict, List[str]]:
    """
    Return:
      train_data[task_type] = (X_all, y_all)       pooled train from all templates
      val_data[task_type]   = (X_all, y_all)        pooled val  from all templates
      test_data[task_type]  = list of (X, y) per template (for per-template eval)
      all_feat_cols         : ordered union of all feature column names
    """
    # Ordered union of feature column names
    all_feat_cols: List[str] = []
    seen = set()
    for ds in datasets:
        for c in ds.feature_cols:
            if c not in seen:
                all_feat_cols.append(c)
                seen.add(c)

    train_Xs: Dict[str, List[np.ndarray]] = {"classification": [], "regression": []}
    train_ys: Dict[str, List[np.ndarray]] = {"classification": [], "regression": []}
    val_Xs:   Dict[str, List[np.ndarray]] = {"classification": [], "regression": []}
    val_ys:   Dict[str, List[np.ndarray]] = {"classification": [], "regression": []}
    test_data: Dict[str, List[Tuple]]     = {"classification": [], "regression": []}

    for ds in datasets:
        tt         = ds.template.task_type
        anchor_col = ds.template.anchor_col
        dtype      = np.int32 if tt == "classification" else np.float32

        X_tr = _pad_df_to_cols(ds.train_df, anchor_col, all_feat_cols)
        y_tr = ds.train_df["label"].values.astype(dtype)
        train_Xs[tt].append(X_tr)
        train_ys[tt].append(y_tr)

        X_va = _pad_df_to_cols(ds.val_df, anchor_col, all_feat_cols)
        y_va = ds.val_df["label"].values.astype(dtype)
        val_Xs[tt].append(X_va)
        val_ys[tt].append(y_va)

        X_te = _pad_df_to_cols(ds.test_df, anchor_col, all_feat_cols)
        y_te = ds.test_df["label"].values.astype(dtype)
        test_data[tt].append((X_te, y_te))

    train_data: Dict = {}
    val_data:   Dict = {}
    for tt in ("classification", "regression"):
        if train_Xs[tt]:
            train_data[tt] = (
                np.concatenate(train_Xs[tt], axis=0),
                np.concatenate(train_ys[tt], axis=0),
            )
        if val_Xs[tt]:
            val_data[tt] = (
                np.concatenate(val_Xs[tt], axis=0),
                np.concatenate(val_ys[tt], axis=0),
            )

    return train_data, val_data, test_data, all_feat_cols


# ── Metric computation ─────────────────────────────────────────────────────

def _compute_metrics(
    test_data: Dict[str, List[Tuple]],
    models:    Dict[str, Tuple],
) -> Dict:
    """Evaluate trained models on all per-template test splits."""
    bool_probs:    List[float] = []
    bool_preds:    List[int]   = []
    bool_golds:    List[int]   = []
    scalar_preds:  List[float] = []
    scalar_golds:  List[float] = []

    for tt, is_clf in [("classification", True), ("regression", False)]:
        if tt not in models or tt not in test_data:
            continue
        kind, model = models[tt]
        for X_te, y_te in test_data[tt]:
            if len(X_te) == 0:
                continue
            if kind == "clf":
                probs = model.predict_proba(X_te)[:, 1]
                preds = (probs >= 0.5).astype(int)
                bool_probs.extend(probs.tolist())
                bool_preds.extend(preds.tolist())
                bool_golds.extend(y_te.tolist())
            else:
                preds = model.predict(X_te).astype(float)
                scalar_preds.extend(preds.tolist())
                scalar_golds.extend(y_te.tolist())

    out: Dict = {}

    if bool_golds:
        from sklearn.metrics import roc_auc_score, f1_score
        try:
            out["Boolean/AUC"] = float(
                roc_auc_score([int(g) for g in bool_golds], bool_probs)
            )
        except ValueError:
            out["Boolean/AUC"] = None
        out["Boolean/F1"] = float(
            f1_score([int(g) for g in bool_golds],
                     [int(p) for p in bool_preds], zero_division=0)
        )

    if scalar_golds:
        gs = np.array(scalar_golds, dtype=np.float64)
        ps = np.array(scalar_preds, dtype=np.float64)
        mae_val  = float(np.mean(np.abs(ps - gs)))
        rmse_val = float(np.sqrt(np.mean((ps - gs) ** 2)))
        nmae_val = mae_val / (float(np.mean(np.abs(gs))) + 1e-8)
        out["Scalar/MAE"]  = mae_val
        out["Scalar/RMSE"] = rmse_val
        out["Scalar/nMAE"] = nmae_val

    return out


# ── XGBoost ────────────────────────────────────────────────────────────────

class XGBoostMethod:
    """
    XGBoost baseline for Predictive Track.

    Entity-level temporal aggregate features from D_ctx (≤ reference_time).
    Binary classification for Boolean; regression for Scalar.
    Pooled training across all instantiated templates.
    """

    def __init__(self, db_dir: str, instances: List[Dict], cfg: Dict = None):
        self.db_dir    = db_dir
        self.instances = instances
        self.cfg       = cfg or {}

    def run(self, seed: int = 42) -> Tuple[Dict, Dict]:
        """Returns (metrics_dict, instantiation_stats)."""
        import xgboost as xgb

        datasets, stats = collect_predictive_datasets(
            self.instances, self.db_dir, self.cfg, seed
        )
        if not datasets:
            logger.warning("XGBoost: no datasets instantiated")
            return {}, stats

        train_data, val_data, test_data, _ = _build_aligned_data(datasets)

        early_stop = self.cfg.get("early_stopping_rounds", 20)
        xgb_kw = dict(
            n_estimators      = self.cfg.get("n_estimators",       1000),
            max_depth         = self.cfg.get("max_depth",             6),
            learning_rate     = self.cfg.get("learning_rate",       0.1),
            subsample         = self.cfg.get("subsample",           0.8),
            colsample_bytree  = self.cfg.get("colsample_bytree",    0.8),
            random_state      = seed,
            verbosity         = 0,
            early_stopping_rounds = early_stop,
        )
        models: Dict = {}

        if "classification" in train_data:
            X_tr, y_tr = train_data["classification"]
            # scale_pos_weight to handle class imbalance
            n_neg = int((y_tr == 0).sum())
            n_pos = int((y_tr == 1).sum())
            spw   = (n_neg / n_pos) if n_pos > 0 else 1.0

            eval_set = None
            if "classification" in val_data:
                eval_set = [(val_data["classification"][0],
                             val_data["classification"][1])]

            clf = xgb.XGBClassifier(
                **xgb_kw,
                objective         = "binary:logistic",
                eval_metric       = "logloss",
                scale_pos_weight  = spw,
                use_label_encoder = False,
            )
            clf.fit(X_tr, y_tr, eval_set=eval_set, verbose=False)
            models["classification"] = ("clf", clf)
            logger.info(
                f"XGBoost clf trained on {len(y_tr)} examples "
                f"(spw={spw:.2f}, best_iter={clf.best_iteration})"
            )

        if "regression" in train_data:
            X_tr, y_tr = train_data["regression"]
            eval_set = None
            if "regression" in val_data:
                eval_set = [(val_data["regression"][0],
                             val_data["regression"][1])]

            reg = xgb.XGBRegressor(
                **xgb_kw,
                objective   = "reg:squarederror",
                eval_metric = "rmse",
            )
            reg.fit(X_tr, y_tr, eval_set=eval_set, verbose=False)
            models["regression"] = ("reg", reg)
            logger.info(
                f"XGBoost reg trained on {len(y_tr)} examples "
                f"(best_iter={reg.best_iteration})"
            )

        return _compute_metrics(test_data, models), stats


# ── LightGBM ───────────────────────────────────────────────────────────────

class LightGBMMethod:
    """
    LightGBM baseline for Predictive Track.

    Key differences from XGBoost:
      - Leaf-wise tree growth: num_leaves is the primary depth control
        (max_depth is left at -1 / unlimited and num_leaves governs complexity)
      - is_unbalance=True for imbalanced binary classification (LightGBM native,
        equivalent to automatic scale_pos_weight)
      - min_child_samples: minimum leaf data count, primary anti-overfit knob
      - feature_fraction: per-tree column subsampling (LightGBM native name)
      - Early stopping via lgb.early_stopping callback (4.x recommended API)

    Reference: https://github.com/lightgbm-org/LightGBM
               RelGNN-main/examples/lightgbm_node.py, adapted to RDL-Bench.
    """

    def __init__(self, db_dir: str, instances: List[Dict], cfg: Dict = None):
        self.db_dir    = db_dir
        self.instances = instances
        self.cfg       = cfg or {}

    def run(self, seed: int = 42) -> Tuple[Dict, Dict]:
        """Returns (metrics_dict, instantiation_stats)."""
        import lightgbm as lgb

        datasets, stats = collect_predictive_datasets(
            self.instances, self.db_dir, self.cfg, seed
        )
        if not datasets:
            logger.warning("LightGBM: no datasets instantiated")
            return {}, stats

        train_data, val_data, test_data, _ = _build_aligned_data(datasets)

        early_stop = self.cfg.get("early_stopping_rounds", 20)

        # LightGBM leaf-wise hyperparameters (distinct from XGBoost level-wise)
        lgb_kw = dict(
            n_estimators       = self.cfg.get("n_estimators",       1000),
            num_leaves         = self.cfg.get("num_leaves",           31),
            max_depth          = -1,           # unlimited; num_leaves controls complexity
            learning_rate      = self.cfg.get("learning_rate",       0.1),
            subsample          = self.cfg.get("subsample",           0.8),
            subsample_freq     = 1,            # enable bagging every iteration
            feature_fraction   = self.cfg.get("colsample_bytree",    0.8),
            min_child_samples  = self.cfg.get("min_child_samples",    20),
            reg_alpha          = self.cfg.get("reg_alpha",           0.0),
            reg_lambda         = self.cfg.get("reg_lambda",          0.1),
            random_state       = seed,
            verbose            = -1,
        )
        models: Dict = {}

        if "classification" in train_data:
            X_tr, y_tr = train_data["classification"]

            callbacks = [lgb.early_stopping(early_stop, verbose=False),
                         lgb.log_evaluation(period=-1)]
            eval_set  = None
            if "classification" in val_data:
                eval_set = [val_data["classification"]]

            clf = lgb.LGBMClassifier(
                **lgb_kw,
                objective    = "binary",
                metric       = "binary_logloss",
                is_unbalance = True,    # LightGBM native imbalance handling
            )
            clf.fit(X_tr, y_tr, eval_set=eval_set, callbacks=callbacks)
            models["classification"] = ("clf", clf)
            logger.info(
                f"LightGBM clf trained on {len(y_tr)} examples "
                f"(is_unbalance=True, best_iter={clf.best_iteration_})"
            )

        if "regression" in train_data:
            X_tr, y_tr = train_data["regression"]

            callbacks = [lgb.early_stopping(early_stop, verbose=False),
                         lgb.log_evaluation(period=-1)]
            eval_set  = None
            if "regression" in val_data:
                eval_set = [val_data["regression"]]

            reg = lgb.LGBMRegressor(
                **lgb_kw,
                objective = "regression",
                metric    = "rmse",
            )
            reg.fit(X_tr, y_tr, eval_set=eval_set, callbacks=callbacks)
            models["regression"] = ("reg", reg)
            logger.info(
                f"LightGBM reg trained on {len(y_tr)} examples "
                f"(best_iter={reg.best_iteration_})"
            )

        return _compute_metrics(test_data, models), stats
