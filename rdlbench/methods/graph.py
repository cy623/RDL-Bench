"""Graph-based baselines for the Predictive Track: GraphSAGE, RelGNN, RelGT.

Entity-level pipeline per template:
  1. Instantiate PredictiveDataset → entity nodes + tabular node features
  2. Build entity-entity graph: two anchor entities are connected if they
     co-appear with the same FK value in an involved table (D_ctx only)
  3. Run GNN over this graph: node-level classification / regression
  4. Train on train-mask entities, evaluate on test-mask entities
  5. Collect per-template test metrics, report aggregate AUROC/F1/MAE/RMSE/nMAE

Implementation: pure PyTorch, no PyG dependency.

GraphSAGE (https://github.com/williamleif/GraphSAGE):
  - Supervised concat mode: W @ [h_self || mean(h_sampled_neigh)]
  - L2-normalize output embeddings after each layer
  - Neighborhood sampling: 25 (hop-1), 10 (hop-2)
  - lr=0.01, dropout=0.5, gradient clipping ±5.0, batch_size=512

RelGNN (https://github.com/snap-stanford/RelGNN):
  - Composite aggregation: SAGEConv(sum) + SAGEConv(max) per relation type,
    grouped across relation types → models multi-relational neighborhood
  - LayerNorm + ReLU after each conv (not L2-norm like GraphSAGE)
  - Regression loss: L1Loss (matching RelGNN paper)
  - Full-neighborhood aggregation (no per-hop sampling)

RelGT  : single-head attention
"""

import logging
import math
from typing import Dict, List, Optional, Tuple

import duckdb
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from tqdm import tqdm

from ..database  import get_db_path
from ..predictive_task    import build_predictive_task_template, normalize_answer_nature
from ..predictive_dataset import instantiate_predictive_template, PredictiveDataset
from ..temporal_masking   import detect_timestamp_col
from .tabular import collect_predictive_datasets

logger = logging.getLogger(__name__)


# ── Entity-level edge construction ─────────────────────────────────────────

def _build_entity_edges(
    con,
    anchor_col:      str,
    anchor_entities: List,
    involved_tables: List[str],
    reference_time:  str,
    max_edges:       int = 50_000,
) -> Tuple[List[int], List[int]]:
    """
    Build edges between anchor entities that share a FK value in involved tables.

    Two entities e1, e2 are connected if there exists a table T and a column C
    (ending in _id, not the anchor_col) such that:
        T[anchor_col] = e1 AND T[C] = v   (v ∈ D_ctx)
        T[anchor_col] = e2 AND T[C] = v

    Returns (src_list, dst_list) — both directions included.
    """
    entity_set = set(str(e) for e in anchor_entities)

    all_tables = [r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
    ).fetchall()]

    src_list: List[int] = []
    dst_list: List[int] = []

    # Map entity → index
    ent_index = {str(e): i for i, e in enumerate(anchor_entities)}

    for table in involved_tables:
        if table not in all_tables:
            continue
        try:
            col_infos = con.execute(f"PRAGMA table_info('{table}')").fetchall()
        except Exception:
            continue

        col_names = [c[1] for c in col_infos]
        if anchor_col not in col_names:
            continue

        # FK proxy columns: end with _id, not the anchor_col itself
        fk_cols = [
            c[1] for c in col_infos
            if c[1] != anchor_col and c[1].lower().endswith("_id")
        ]
        if not fk_cols:
            continue

        ts_col = detect_timestamp_col(con, table)
        where  = f'WHERE "{ts_col}" <= \'{reference_time}\'' if ts_col else ""

        for fk_col in fk_cols[:3]:  # at most 3 FK cols per table
            try:
                query = (
                    f'SELECT a1."{anchor_col}" AS src, a2."{anchor_col}" AS dst '
                    f'FROM "{table}" a1 '
                    f'JOIN "{table}" a2 ON a1."{fk_col}" = a2."{fk_col}" '
                    f'{where} '
                    f'WHERE a1."{anchor_col}" < a2."{anchor_col}" '
                    f'LIMIT {max_edges}'
                )
                rows = con.execute(query).fetchall()
            except Exception:
                continue

            for r in rows:
                s_key = str(r[0])
                d_key = str(r[1])
                if s_key in ent_index and d_key in ent_index:
                    si = ent_index[s_key]
                    di = ent_index[d_key]
                    src_list += [si, di]
                    dst_list += [di, si]

        if len(src_list) >= max_edges:
            break

    return src_list[:max_edges], dst_list[:max_edges]


# ── Per-template graph builder ─────────────────────────────────────────────

def build_entity_graph(
    dataset: PredictiveDataset,
    db_path: str,
    max_edges: int = 50_000,
) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor,
           torch.Tensor, torch.Tensor, torch.Tensor]:
    """
    Build entity-level graph for one PredictiveDataset.

    Returns
    -------
    node_feats  : (N, D) float tensor — tabular features
    edge_index  : (2, E) long tensor
    y_all       : (N,) tensor — labels for all entities
    train_mask  : (N,) bool tensor
    val_mask    : (N,) bool tensor
    test_mask   : (N,) bool tensor
    entity_ids  : list[str] — ordered anchor entity identifiers
    """
    template   = dataset.template
    anchor_col = template.anchor_col
    examples   = dataset.examples_df
    feat_cols  = dataset.feature_cols

    # Node ordering follows examples_df
    entities   = examples[anchor_col].tolist()
    N          = len(entities)

    # Node features
    X = examples[feat_cols].values.astype(np.float32)
    node_feats = torch.tensor(X, dtype=torch.float32)

    # Labels
    y_all = torch.tensor(examples["label"].values,
                         dtype=torch.float32 if template.task_type == "regression"
                         else torch.long)

    # Train / val / test masks based on entity identity
    train_ids = set(dataset.train_df[anchor_col].astype(str).tolist())
    val_ids   = set(dataset.val_df[anchor_col].astype(str).tolist())
    test_ids  = set(dataset.test_df[anchor_col].astype(str).tolist())

    entity_strs  = [str(e) for e in entities]
    train_mask   = torch.tensor([e in train_ids for e in entity_strs], dtype=torch.bool)
    val_mask     = torch.tensor([e in val_ids   for e in entity_strs], dtype=torch.bool)
    test_mask    = torch.tensor([e in test_ids  for e in entity_strs], dtype=torch.bool)

    # Edges
    try:
        con = duckdb.connect(db_path, read_only=True)
        srcs, dsts = _build_entity_edges(
            con, anchor_col, entities,
            template.involved_tables, template.reference_time,
            max_edges=max_edges,
        )
        con.close()
    except Exception:
        srcs, dsts = [], []

    if srcs:
        edge_index = torch.tensor([srcs, dsts], dtype=torch.long)
    else:
        edge_index = torch.zeros(2, 0, dtype=torch.long)

    return node_feats, edge_index, y_all, train_mask, val_mask, test_mask, entities


# ── Neighborhood sampling helper ───────────────────────────────────────────

def _sample_neighbors(
    edge_index: torch.Tensor,
    N:          int,
    k:          int,
    rng:        np.random.Generator,
) -> torch.Tensor:
    """
    For each node, sample up to k neighbors (without replacement).
    Returns a new edge_index with at most k edges per destination node.
    This matches the GraphSAGE inductive sampling strategy.
    """
    if edge_index.size(1) == 0:
        return edge_index

    src_np = edge_index[0].cpu().numpy()
    dst_np = edge_index[1].cpu().numpy()

    # Group source nodes by destination
    neigh: Dict[int, List[int]] = {}
    for s, d in zip(src_np.tolist(), dst_np.tolist()):
        neigh.setdefault(d, []).append(s)

    new_src, new_dst = [], []
    for d, neighbors in neigh.items():
        if len(neighbors) > k:
            chosen = rng.choice(neighbors, size=k, replace=False).tolist()
        else:
            chosen = neighbors
        new_src.extend(chosen)
        new_dst.extend([d] * len(chosen))

    if not new_src:
        return torch.zeros(2, 0, dtype=torch.long, device=edge_index.device)
    return torch.tensor([new_src, new_dst],
                        dtype=torch.long, device=edge_index.device)


# ── GNN layers ─────────────────────────────────────────────────────────────

class _SAGEConv(nn.Module):
    """
    GraphSAGE mean-aggregator layer — supervised concat mode.

    Faithful to williamleif/GraphSAGE supervised_models.py:
      h_out = ReLU( W @ concat(h_self, mean(h_sampled_neigh)) )
      h_out = L2_normalize(h_out)          ← applied after activation

    The concat mode doubles input dim, so lin takes (2*in_dim, out_dim).
    """

    def __init__(self, in_dim: int, out_dim: int):
        super().__init__()
        # concat(self, neigh_mean) → out_dim
        self.lin  = nn.Linear(2 * in_dim, out_dim, bias=True)

    def forward(self, x: torch.Tensor, edge_index: torch.Tensor) -> torch.Tensor:
        N = x.size(0)
        if edge_index.size(1) == 0:
            # No neighbors: concat self with zeros
            zeros = torch.zeros_like(x)
            h = F.relu(self.lin(torch.cat([x, zeros], dim=-1)))
        else:
            src, dst = edge_index[0], edge_index[1]
            agg   = torch.zeros_like(x)
            count = torch.zeros(N, device=x.device)
            agg.index_add_(0, dst, x[src])
            count.index_add_(0, dst, torch.ones(src.size(0), device=x.device))
            neigh_mean = agg / count.clamp(min=1).unsqueeze(1)
            h = F.relu(self.lin(torch.cat([x, neigh_mean], dim=-1)))
        # L2 normalize output (faithfully from original GraphSAGE)
        return F.normalize(h, p=2, dim=-1)


class _RelGNNConv(nn.Module):
    """
    RelGNN conv layer — faithful to snap-stanford/RelGNN.

    RelGNN handles multiple relation types by applying separate SAGEConv
    aggregators per relation and grouping results. For our homogeneous
    entity graph we model this as two parallel aggregation paths (sum + max)
    that jointly capture different aspects of the neighborhood, then combine:

        h_sum = W_sum @ agg_sum(h_neigh)
        h_max = W_max @ agg_max(h_neigh)
        h_self = W_self @ h_self
        h_out  = LayerNorm( ReLU( h_self + h_sum + h_max ) )

    LayerNorm (not L2-norm) follows each layer, as in the original code.
    """

    def __init__(self, in_dim: int, out_dim: int):
        super().__init__()
        self.lin_self = nn.Linear(in_dim,      out_dim, bias=True)
        self.lin_sum  = nn.Linear(in_dim, out_dim // 2, bias=False)
        self.lin_max  = nn.Linear(in_dim, out_dim // 2, bias=False)
        self.norm     = nn.LayerNorm(out_dim)

    def forward(self, x: torch.Tensor, edge_index: torch.Tensor) -> torch.Tensor:
        N, D = x.size()
        if edge_index.size(1) == 0:
            return self.norm(F.relu(self.lin_self(x)))

        src, dst = edge_index[0], edge_index[1]
        x_src = x[src]

        # Sum aggregation path
        agg_sum = torch.zeros(N, D, device=x.device)
        agg_sum.index_add_(0, dst, x_src)

        # Max aggregation path (scatter_reduce, no in-place on grad tensors)
        dst_exp = dst.unsqueeze(1).expand(-1, D)
        agg_max = torch.full((N, D), -1e9, device=x.device)
        agg_max = agg_max.scatter_reduce(
            0, dst_exp, x_src, reduce="amax", include_self=True
        ).clamp(min=0)

        # Combine: self + sum-branch + max-branch, then LayerNorm
        out = self.lin_self(x) + torch.cat(
            [self.lin_sum(agg_sum), self.lin_max(agg_max)], dim=-1
        )
        return self.norm(F.relu(out))


class _RelGTConv(nn.Module):
    """RelGT layer: single-head attention over neighbourhood + LayerNorm output."""

    def __init__(self, in_dim: int, out_dim: int):
        super().__init__()
        self.attn_q   = nn.Linear(in_dim, out_dim, bias=False)
        self.attn_k   = nn.Linear(in_dim, out_dim, bias=False)
        self.attn_v   = nn.Linear(in_dim, out_dim, bias=False)
        self.lin_self = nn.Linear(in_dim, out_dim)
        self.norm     = nn.LayerNorm(out_dim)
        self.scale    = math.sqrt(out_dim)

    def forward(self, x: torch.Tensor, edge_index: torch.Tensor) -> torch.Tensor:
        N     = x.size(0)
        h_self = self.lin_self(x)
        if edge_index.size(1) == 0:
            return self.norm(F.relu(h_self))
        src, dst = edge_index[0], edge_index[1]
        Q   = self.attn_q(x[dst])
        K   = self.attn_k(x[src])
        V   = self.attn_v(x[src])
        raw = (Q * K).sum(dim=-1) / self.scale
        raw = raw.clamp(-10, 10)
        exp = raw.exp()
        denom = torch.zeros(N, device=x.device).index_add(0, dst, exp).clamp(min=1e-9)
        w   = (exp / denom[dst]).unsqueeze(1)
        agg = torch.zeros(N, V.size(1), device=x.device)
        agg.index_add_(0, dst, w * V)
        return self.norm(F.relu(h_self + agg))


# ── Node-level GNN model ────────────────────────────────────────────────────

class _NodeGNN(nn.Module):
    """2-layer GNN → node-level prediction head."""

    def __init__(self, conv_class, in_dim: int, hidden: int, out_dim: int,
                 dropout: float = 0.5):
        super().__init__()
        self.conv1   = conv_class(in_dim,  hidden)
        self.conv2   = conv_class(hidden,  hidden)
        self.dropout = nn.Dropout(dropout)
        self.head    = nn.Linear(hidden, out_dim)

    def forward(self, x: torch.Tensor,
                ei1: torch.Tensor,          # edge_index for layer 1 (sampled)
                ei2: torch.Tensor,          # edge_index for layer 2 (sampled)
                ) -> torch.Tensor:
        h = self.dropout(self.conv1(x,  ei1))
        h = self.dropout(self.conv2(h,  ei2))
        return self.head(h)                  # (N, out_dim)


# ── Per-template training / eval ────────────────────────────────────────────

def _train_eval_template(
    conv_class,
    dataset:    PredictiveDataset,
    db_path:    str,
    cfg:        Dict,
    device:     torch.device,
    rng:        np.random.Generator,
) -> Optional[Dict]:
    """
    Train a node-level GNN on one PredictiveDataset.

    GraphSAGE-faithful training:
      - Per-epoch neighborhood sampling: 25 neighbors (layer 1), 10 (layer 2)
      - Gradient clipping ±5.0
      - lr=0.01, dropout=0.5, weight_decay=0 (matching original)

    Returns dict with predictions on test-mask nodes, or None if empty.
    """
    node_feats, edge_index, y_all, train_mask, val_mask, test_mask, _ = \
        build_entity_graph(dataset, db_path, max_edges=cfg.get("max_edges", 50_000))

    if test_mask.sum() == 0:
        return None

    N      = node_feats.size(0)
    in_dim = node_feats.size(1)
    hidden = cfg.get("gnn_hidden",   128)
    epochs = cfg.get("gnn_epochs",   10)
    lr     = cfg.get("gnn_lr",       0.01)   # GraphSAGE default
    drop   = cfg.get("dropout",      0.5)    # GraphSAGE default
    clip   = cfg.get("grad_clip",    5.0)    # GraphSAGE gradient clipping
    k1     = cfg.get("sage_k1",       25)    # hop-1 sample size
    k2     = cfg.get("sage_k2",       10)    # hop-2 sample size
    tt     = dataset.template.task_type

    model   = _NodeGNN(conv_class, in_dim, hidden, 1, drop).to(device)
    opt     = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=0.0)

    if tt == "classification":
        loss_fn = nn.BCEWithLogitsLoss()
    elif conv_class is _RelGNNConv:
        loss_fn = nn.L1Loss()      # RelGNN paper uses L1Loss for regression
    else:
        loss_fn = nn.MSELoss()

    x          = node_feats.to(device)
    y          = y_all.to(device).float()
    train_mask = train_mask.to(device)
    test_mask  = test_mask.to(device)

    # Input feature normalization using train-set statistics (prevents large tabular
    # values from causing exploding activations in RelGT which has no internal norm).
    # Use correction=0 (population std) to avoid NaN when only 1 training entity
    # exists — PyTorch's default correction=1 gives NaN for N=1, and clamp cannot
    # convert NaN because NaN comparisons always return False.
    if train_mask.any():
        x_mean = x[train_mask].mean(0, keepdim=True)
        x_std  = x[train_mask].std(0, correction=0, keepdim=True).clamp(min=1e-8)
        x = (x - x_mean) / x_std

    # Target normalization for regression (prevents extreme outputs, esp. in RelGT).
    # Use correction=0 (population std) to avoid NaN when only 1 training entity
    # exists — sample std (correction=1) returns NaN for N=1, and Python's
    # max(nan, 1e-8) returns nan (NaN comparisons are always False, so max keeps nan).
    y_orig = y.clone()
    y_mean_val = y_std_val = None
    if tt != "classification" and train_mask.any():
        y_mean_val = float(y[train_mask].mean())
        y_std_val  = max(float(y[train_mask].std(correction=0)), 1e-8)
        y          = (y - y_mean_val) / y_std_val

    # Determine per-layer k based on conv_class
    # GraphSAGE samples neighbors; RelGNN / RelGT use full neighborhood
    use_sampling = (conv_class is _SAGEConv)
    _k1 = k1 if use_sampling else edge_index.size(1)  # no cap for non-SAGE
    _k2 = k2 if use_sampling else edge_index.size(1)

    model.train()
    for _ in range(epochs):
        # Sample fresh neighborhoods each epoch (GraphSAGE inductive sampling)
        if use_sampling:
            ei1 = _sample_neighbors(edge_index, N, _k1, rng).to(device)
            ei2 = _sample_neighbors(edge_index, N, _k2, rng).to(device)
        else:
            ei1 = ei2 = edge_index.to(device)

        opt.zero_grad()
        out  = model(x, ei1, ei2).squeeze(-1)   # (N,)
        loss = loss_fn(out[train_mask], y[train_mask])
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), clip)
        opt.step()

    # Evaluation: use full edge_index (no sampling at inference)
    ei_full = edge_index.to(device)
    model.eval()
    with torch.no_grad():
        out = model(x, ei_full, ei_full).squeeze(-1)

    out_test = out[test_mask].cpu().numpy()
    # Always use original (un-normalized) labels for metrics
    y_test   = y_orig[test_mask].cpu().numpy()

    if tt == "classification":
        probs = 1.0 / (1.0 + np.exp(-out_test))
        preds = (probs >= 0.5).astype(int)
        return {"type": "classification", "probs": probs, "preds": preds,
                "golds": y_test.astype(int)}
    else:
        # Inverse-transform predictions back to original target scale
        if y_mean_val is not None:
            out_test = out_test * y_std_val + y_mean_val
        return {"type": "regression", "preds": out_test, "golds": y_test}


# ── Main GNN runner ────────────────────────────────────────────────────────

def _run_gnn_method(
    conv_class,
    instances:   List[Dict],
    db_dir:      str,
    cfg:         Dict,
    method_name: str,
    seed:        int = 42,
) -> Tuple[Dict, Dict]:
    """
    Build entity-level graphs for all trainable Predictive instances,
    train/evaluate per-template node GNN, aggregate metrics.

    Returns (metrics_dict, instantiation_stats).
    """
    torch.manual_seed(seed)
    np.random.seed(seed)

    device_str = cfg.get("device", "auto")
    if device_str == "auto":
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    else:
        device = torch.device(device_str)

    datasets, stats = collect_predictive_datasets(instances, db_dir, cfg, seed)
    if not datasets:
        return {}, stats

    rng = np.random.default_rng(seed)

    bool_probs: List[float] = []
    bool_preds: List[int]   = []
    bool_golds: List[int]   = []
    scal_preds: List[float] = []
    scal_golds: List[float] = []

    for ds in tqdm(datasets, desc=method_name):
        iid     = ds.template.instance_id
        # cfg["db_name"] overrides the instance_id-derived domain (all IDs are RDB_FIN_xxx)
        domain  = cfg.get("db_name") or (iid.split("_")[1].lower() if "_" in iid else "")
        db_path = get_db_path(db_dir, domain)

        result = _train_eval_template(conv_class, ds, db_path, cfg, device, rng)
        if result is None:
            continue

        if result["type"] == "classification":
            bool_probs.extend(result["probs"].tolist())
            bool_preds.extend(result["preds"].tolist())
            bool_golds.extend(result["golds"].tolist())
        else:
            scal_preds.extend(result["preds"].tolist())
            scal_golds.extend(result["golds"].tolist())

    out: Dict = {}

    if bool_golds:
        from sklearn.metrics import roc_auc_score, f1_score
        try:
            out["Boolean/AUC"] = float(roc_auc_score(bool_golds, bool_probs))
        except ValueError:
            out["Boolean/AUC"] = None
        out["Boolean/F1"] = float(
            f1_score(bool_golds, bool_preds, zero_division=0)
        )

    if scal_golds:
        gs = np.array(scal_golds, dtype=np.float64)
        ps = np.array(scal_preds, dtype=np.float64)
        mae_val  = float(np.mean(np.abs(ps - gs)))
        rmse_val = float(np.sqrt(np.mean((ps - gs) ** 2)))
        nmae_val = mae_val / (float(np.mean(np.abs(gs))) + 1e-8)
        out["Scalar/MAE"]  = mae_val
        out["Scalar/RMSE"] = rmse_val
        out["Scalar/nMAE"] = nmae_val

    return out, stats


# ── Public method classes ───────────────────────────────────────────────────

class GraphSAGEMethod:
    """GraphSAGE entity-level node classification/regression baseline."""

    def __init__(self, db_dir: str, instances: List[Dict], cfg: Dict = None):
        self.db_dir    = db_dir
        self.instances = instances
        self.cfg       = cfg or {}

    def run(self, seed: int = 42) -> Tuple[Dict, Dict]:
        return _run_gnn_method(
            _SAGEConv, self.instances, self.db_dir, self.cfg, "GraphSAGE", seed
        )


class RelGNNMethod:
    """RelGNN entity-level node classification/regression baseline."""

    def __init__(self, db_dir: str, instances: List[Dict], cfg: Dict = None):
        self.db_dir    = db_dir
        self.instances = instances
        self.cfg       = cfg or {}

    def run(self, seed: int = 42) -> Tuple[Dict, Dict]:
        return _run_gnn_method(
            _RelGNNConv, self.instances, self.db_dir, self.cfg, "RelGNN", seed
        )


class RelGTMethod:
    """RelGT entity-level node classification/regression baseline."""

    def __init__(self, db_dir: str, instances: List[Dict], cfg: Dict = None):
        self.db_dir    = db_dir
        self.instances = instances
        self.cfg       = cfg or {}

    def run(self, seed: int = 42) -> Tuple[Dict, Dict]:
        return _run_gnn_method(
            _RelGTConv, self.instances, self.db_dir, self.cfg, "RelGT", seed
        )
