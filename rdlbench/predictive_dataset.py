"""PredictiveDataset: instantiate a PredictiveTaskTemplate into entity-level examples.

Pipeline per template:
  1. Sample up to max_entities anchor entities from D_ctx[anchor_table]
  2. Build tabular features from D_ctx for each anchor entity
  3. Build labels by executing entity-level target_sql on future records
  4. Merge features + labels; fill missing labels with default (0)
  5. Split into train / val / test at entity level (60/20/20)

Output is a PredictiveDataset with .X_train, .y_train, etc.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import duckdb
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

from .predictive_task    import PredictiveTaskTemplate
from .temporal_masking   import (build_dctx_views, build_future_views,
                                 execute_with_temporal_views, detect_timestamp_col)
from .feature_engineering import build_tabular_features

logger = logging.getLogger(__name__)


# ── Label construction ─────────────────────────────────────────────────────

def _construct_labels(
    con,
    template:        PredictiveTaskTemplate,
    anchor_entities: List,
) -> pd.DataFrame:
    """
    Execute the entity-level target_sql on future records.
    Returns DataFrame with [anchor_col, label].
    Missing entities get default label (0 for Boolean, 0.0 for Scalar).
    """
    anchor_col = template.anchor_col
    future_views = build_future_views(
        con,
        template.reference_time,
        template.t_end,
    )

    rows, err = execute_with_temporal_views(
        con, template.target_sql, future_views
    )

    if err or not rows:
        logger.warning(
            f"[{template.instance_id}] Label SQL failed: {err or 'empty result'}. "
            "All entities get default label 0."
        )
        return pd.DataFrame({
            anchor_col: anchor_entities,
            "label":    [0] * len(anchor_entities),
        })

    # Build DataFrame from result rows
    try:
        label_df = pd.DataFrame(rows, columns=[anchor_col, "label"])
    except Exception:
        label_df = pd.DataFrame({anchor_col: [], "label": []})

    # Cast label
    if template.task_type == "classification":
        label_df["label"] = label_df["label"].apply(
            lambda v: 1 if (
                str(v).strip().lower() in ("1", "true", "yes", "t") or v is True
            ) else 0
        )
    else:
        label_df["label"] = pd.to_numeric(label_df["label"], errors="coerce").fillna(0.0)

    # Fill missing entities with default label 0
    all_df = pd.DataFrame({anchor_col: anchor_entities})
    try:
        all_df[anchor_col] = all_df[anchor_col].astype(label_df[anchor_col].dtype)
    except Exception:
        pass
    merged = all_df.merge(label_df, on=anchor_col, how="left")
    merged["label"] = merged["label"].fillna(0)

    return merged[[anchor_col, "label"]]


# ── Entity sampling ────────────────────────────────────────────────────────

def _sample_anchor_entities(
    con,
    template:    PredictiveTaskTemplate,
    max_entities: int,
    seed:         int,
) -> List:
    """
    Sample up to max_entities anchor entity values from D_ctx[anchor_table].
    Returns a list of entity IDs.
    """
    table      = template.anchor_table
    anchor_col = template.anchor_col
    t_ref      = template.reference_time
    ts_col     = detect_timestamp_col(con, table)

    where = f'WHERE "{ts_col}" <= \'{t_ref}\'' if ts_col else ""
    try:
        rows = con.execute(
            f'SELECT DISTINCT "{anchor_col}" FROM "{table}" {where}'
        ).fetchall()
    except Exception:
        # anchor_col might not be in anchor_table; try involved_tables
        for t in template.involved_tables:
            try:
                ts = detect_timestamp_col(con, t)
                w  = f'WHERE "{ts}" <= \'{t_ref}\'' if ts else ""
                rows = con.execute(
                    f'SELECT DISTINCT "{anchor_col}" FROM "{t}" {w}'
                ).fetchall()
                if rows:
                    break
            except Exception:
                continue
        else:
            return []

    entities = [r[0] for r in rows if r[0] is not None]
    if len(entities) > max_entities:
        rng      = np.random.default_rng(seed)
        entities = list(rng.choice(entities, size=max_entities, replace=False))
    return entities


# ── Train / val / test split ───────────────────────────────────────────────

def _split_examples(
    examples_df: pd.DataFrame,
    task_type:   str,
    seed:        int,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """60/20/20 entity-level split, stratified for classification."""
    stratify = examples_df["label"] if task_type == "classification" else None

    # Check stratify is viable
    if stratify is not None and stratify.nunique() < 2:
        stratify = None

    try:
        train_df, tmp_df = train_test_split(
            examples_df, test_size=0.4, random_state=seed, stratify=stratify
        )
        val_stratify = tmp_df["label"] if (
            task_type == "classification" and tmp_df["label"].nunique() >= 2
        ) else None
        val_df, test_df = train_test_split(
            tmp_df, test_size=0.5, random_state=seed, stratify=val_stratify
        )
    except ValueError:
        # Fallback: random split without stratify
        n      = len(examples_df)
        idx    = np.random.default_rng(seed).permutation(n)
        t_end  = int(n * 0.6)
        v_end  = int(n * 0.8)
        train_df = examples_df.iloc[idx[:t_end]]
        val_df   = examples_df.iloc[idx[t_end:v_end]]
        test_df  = examples_df.iloc[idx[v_end:]]

    return train_df, val_df, test_df


# ── PredictiveDataset ──────────────────────────────────────────────────────

@dataclass
class PredictiveDataset:
    template:        PredictiveTaskTemplate
    anchor_entities: List
    features_df:     pd.DataFrame        # anchor_col + feature columns
    labels_df:       pd.DataFrame        # anchor_col + label
    examples_df:     pd.DataFrame        # merged features + label
    train_df:        pd.DataFrame
    val_df:          pd.DataFrame
    test_df:         pd.DataFrame

    @property
    def feature_cols(self) -> List[str]:
        return [c for c in self.examples_df.columns
                if c not in (self.template.anchor_col, "label")]

    def Xy(self, split: str):
        """Return (X, y) numpy arrays for 'train' / 'val' / 'test'."""
        df = {"train": self.train_df, "val": self.val_df, "test": self.test_df}[split]
        X  = df[self.feature_cols].values.astype(np.float32)
        y  = df["label"].values
        y  = y.astype(np.float32 if self.template.task_type == "regression"
                       else np.int32)
        return X, y

    def n_classes(self) -> int:
        return int(self.examples_df["label"].nunique())


def instantiate_predictive_template(
    template:     PredictiveTaskTemplate,
    db_path:      str,
    max_entities: int = 5000,
    seed:         int = 42,
) -> Optional[PredictiveDataset]:
    """
    Build entity-level supervised examples for one template.
    Returns None if instantiation fails (e.g., empty entity set).
    """
    try:
        con = duckdb.connect(db_path, read_only=True)
    except Exception as e:
        logger.error(f"[{template.instance_id}] DB connection failed: {e}")
        return None

    try:
        # ── 1. Sample anchor entities from D_ctx ───────────────────────────
        anchor_entities = _sample_anchor_entities(con, template, max_entities, seed)
        if not anchor_entities:
            logger.warning(
                f"[{template.instance_id}] No anchor entities found — skipping"
            )
            con.close()
            return None

        # ── 2. Build tabular features from D_ctx ───────────────────────────
        features_df = build_tabular_features(
            con,
            template.anchor_col,
            anchor_entities,
            template.involved_tables,
            template.reference_time,
        )

        # ── 3. Construct entity-level labels (future window) ───────────────
        labels_df = _construct_labels(con, template, anchor_entities)

        con.close()

        # ── 4. Merge and validate ──────────────────────────────────────────
        anchor_col = template.anchor_col
        try:
            features_df[anchor_col] = features_df[anchor_col].astype(
                labels_df[anchor_col].dtype
            )
        except Exception:
            pass

        examples_df = features_df.merge(labels_df, on=anchor_col, how="inner")
        if examples_df.empty:
            logger.warning(f"[{template.instance_id}] Merged examples are empty")
            return None

        # Drop columns that are all-zero (no information)
        feat_cols  = [c for c in examples_df.columns if c not in (anchor_col, "label")]
        non_zero   = [c for c in feat_cols if examples_df[c].abs().sum() > 0]
        keep_cols  = [anchor_col] + non_zero + ["label"]
        examples_df = examples_df[keep_cols]

        if len(non_zero) == 0:
            logger.warning(f"[{template.instance_id}] All features are zero — skipping")
            return None

        # ── 5. Split ───────────────────────────────────────────────────────
        train_df, val_df, test_df = _split_examples(
            examples_df, template.task_type, seed
        )

        return PredictiveDataset(
            template        = template,
            anchor_entities = anchor_entities,
            features_df     = features_df,
            labels_df       = labels_df,
            examples_df     = examples_df,
            train_df        = train_df,
            val_df          = val_df,
            test_df         = test_df,
        )

    except Exception as e:
        logger.error(f"[{template.instance_id}] Instantiation failed: {e}")
        try:
            con.close()
        except Exception:
            pass
        return None
