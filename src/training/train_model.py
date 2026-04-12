"""
RecoMart Data Pipeline - Task 9: Model Training & Evaluation
Trains SVD-based Collaborative Filtering and Content-Based models.
Tracks experiments with MLflow (file-based backend).
Evaluates using Precision@K, Recall@K, NDCG@K.
"""

import logging
import json
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime
from collections import defaultdict

from sklearn.decomposition import TruncatedSVD
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.model_selection import train_test_split
import pickle

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "training.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("model_training")

MODELS_DIR = Path(__file__).resolve().parents[2] / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

MLFLOW_DIR = Path(__file__).resolve().parents[2] / "models" / "mlflow_runs"
MLFLOW_DIR.mkdir(parents=True, exist_ok=True)


# ── Lightweight MLflow-compatible tracker ─────────────────────────────────────
class ExperimentTracker:
    """Logs params, metrics, and artifacts in MLflow-compatible format."""
    def __init__(self, experiment_name: str):
        self.experiment_name = experiment_name
        self.run_id    = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
        self.run_dir   = MLFLOW_DIR / experiment_name / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.params    = {}
        self.metrics   = {}
        self.tags      = {}
        self.start_time = datetime.utcnow().isoformat()
        logger.info(f"[MLflow] Started run {self.run_id} for experiment '{experiment_name}'")

    def log_param(self, key: str, value):
        self.params[key] = value

    def log_params(self, d: dict):
        self.params.update(d)

    def log_metric(self, key: str, value: float):
        self.metrics[key] = round(float(value), 6)

    def log_metrics(self, d: dict):
        for k, v in d.items():
            self.log_metric(k, v)

    def set_tag(self, key: str, value: str):
        self.tags[key] = str(value)

    def log_artifact(self, artifact: object, name: str):
        path = self.run_dir / name
        with open(path, "wb") as f:
            pickle.dump(artifact, f)
        logger.info(f"[MLflow] Artifact saved: {path}")

    def end_run(self, status: str = "FINISHED"):
        summary = {
            "run_id":       self.run_id,
            "experiment":   self.experiment_name,
            "status":       status,
            "start_time":   self.start_time,
            "end_time":     datetime.utcnow().isoformat(),
            "params":       self.params,
            "metrics":      self.metrics,
            "tags":         self.tags,
        }
        with open(self.run_dir / "run.json", "w") as f:
            json.dump(summary, f, indent=2)
        logger.info(
            f"[MLflow] Run {self.run_id} {status} | "
            f"metrics={self.metrics}"
        )
        return summary


# ── Evaluation metrics ────────────────────────────────────────────────────────
def precision_at_k(recommended: list, relevant: set, k: int) -> float:
    recs = recommended[:k]
    hits = sum(1 for r in recs if r in relevant)
    return hits / k if k > 0 else 0.0


def recall_at_k(recommended: list, relevant: set, k: int) -> float:
    recs = recommended[:k]
    hits = sum(1 for r in recs if r in relevant)
    return hits / len(relevant) if relevant else 0.0


def ndcg_at_k(recommended: list, relevant: set, k: int) -> float:
    recs = recommended[:k]
    dcg  = sum(
        1 / np.log2(idx + 2)
        for idx, r in enumerate(recs) if r in relevant
    )
    ideal = sum(1 / np.log2(idx + 2) for idx in range(min(len(relevant), k)))
    return dcg / ideal if ideal > 0 else 0.0


def evaluate_recommendations(predictions: dict[int, list], test_set: dict[int, set], k: int = 10) -> dict:
    p_scores, r_scores, n_scores = [], [], []
    for user_id, recs in predictions.items():
        relevant = test_set.get(user_id, set())
        if not relevant:
            continue
        p_scores.append(precision_at_k(recs, relevant, k))
        r_scores.append(recall_at_k(recs, relevant, k))
        n_scores.append(ndcg_at_k(recs, relevant, k))
    return {
        f"precision@{k}": round(np.mean(p_scores), 4) if p_scores else 0.0,
        f"recall@{k}":    round(np.mean(r_scores), 4) if r_scores else 0.0,
        f"ndcg@{k}":      round(np.mean(n_scores), 4) if n_scores else 0.0,
        "evaluated_users": len(p_scores),
    }


# ── Model 1: SVD Collaborative Filtering ─────────────────────────────────────
class SVDRecommender:
    def __init__(self, n_components: int = 50):
        self.n_components  = n_components
        self.svd           = TruncatedSVD(n_components=n_components, random_state=42)
        self.user_idx      = {}
        self.item_idx      = {}
        self.idx_to_item   = {}
        self.user_item_mat = None
        self.user_factors  = None
        self.item_factors  = None

    def fit(self, df: pd.DataFrame):
        users = df["user_id"].unique()
        items = df["item_id"].unique()
        self.user_idx    = {u: i for i, u in enumerate(users)}
        self.item_idx    = {it: i for i, it in enumerate(items)}
        self.idx_to_item = {i: it for it, i in self.item_idx.items()}

        # Build user-item rating matrix
        mat = np.zeros((len(users), len(items)), dtype=np.float32)
        for _, row in df.iterrows():
            u = self.user_idx.get(row["user_id"])
            i = self.item_idx.get(row["item_id"])
            if u is not None and i is not None:
                mat[u, i] = row["rating"]

        self.user_item_mat = mat
        self.user_factors  = self.svd.fit_transform(mat)
        self.item_factors  = self.svd.components_.T
        logger.info(
            f"SVD fitted | users={len(users)}, items={len(items)}, "
            f"components={self.n_components}, "
            f"explained_variance={self.svd.explained_variance_ratio_.sum():.3f}"
        )

    def recommend(self, user_id: int, n: int = 10, exclude_seen: bool = True) -> list[int]:
        u_idx = self.user_idx.get(user_id)
        if u_idx is None:
            return []
        scores   = self.user_factors[u_idx] @ self.item_factors.T
        seen_idx = set(np.where(self.user_item_mat[u_idx] > 0)[0]) if exclude_seen else set()
        ranked   = np.argsort(scores)[::-1]
        recs     = [self.idx_to_item[i] for i in ranked if i not in seen_idx]
        return recs[:n]

    def recommend_batch(self, user_ids: list[int], n: int = 10) -> dict[int, list]:
        return {uid: self.recommend(uid, n) for uid in user_ids}


# ── Model 2: Content-Based Filtering ─────────────────────────────────────────
class ContentBasedRecommender:
    def __init__(self):
        self.item_ids       = []
        self.similarity_mat = None
        self.item_idx       = {}

    def fit(self, df_items: pd.DataFrame, feature_cols: list[str]):
        feature_cols = [c for c in feature_cols if c in df_items.columns]
        self.item_ids = df_items["item_id"].tolist()
        self.item_idx = {it: i for i, it in enumerate(self.item_ids)}
        feat_mat      = df_items[feature_cols].fillna(0).values.astype(np.float32)
        self.similarity_mat = cosine_similarity(feat_mat)
        logger.info(
            f"Content-based fitted | items={len(self.item_ids)}, "
            f"features={feature_cols}"
        )

    def recommend_similar(self, item_id: int, n: int = 10) -> list[int]:
        idx = self.item_idx.get(item_id)
        if idx is None:
            return []
        sims   = self.similarity_mat[idx]
        ranked = np.argsort(sims)[::-1]
        return [self.item_ids[i] for i in ranked if i != idx][:n]


# ── Training pipeline ─────────────────────────────────────────────────────────
def train_svd_model(df_int: pd.DataFrame, n_components: int = 50, k: int = 10) -> dict:
    tracker = ExperimentTracker("svd_collaborative_filtering")
    tracker.log_params({"n_components": n_components, "k": k, "model_type": "SVD"})
    tracker.set_tag("framework", "sklearn.TruncatedSVD")

    # Train/test split by user (80/20)
    users = df_int["user_id"].unique()
    train_users, test_users = train_test_split(users, test_size=0.2, random_state=42)

    df_train = df_int[df_int["user_id"].isin(train_users)]
    df_test  = df_int[df_int["user_id"].isin(test_users)]

    tracker.log_params({
        "train_users":  len(train_users),
        "test_users":   len(test_users),
        "train_rows":   len(df_train),
        "test_rows":    len(df_test),
    })

    # Fit model
    model = SVDRecommender(n_components=n_components)
    model.fit(df_train)

    # Build test ground truth
    test_ground_truth = (
        df_test[df_test["rating"] >= 3.5]
        .groupby("user_id")["item_id"]
        .apply(set).to_dict()
    )

    # Generate predictions
    test_user_ids = [u for u in test_users if u in model.user_idx]
    predictions   = model.recommend_batch(test_user_ids, n=k)

    # Evaluate
    metrics = evaluate_recommendations(predictions, test_ground_truth, k=k)
    tracker.log_metrics(metrics)
    tracker.log_metrics({
        "explained_variance": round(float(model.svd.explained_variance_ratio_.sum()), 4),
        "n_users":  int(df_int["user_id"].nunique()),
        "n_items":  int(df_int["item_id"].nunique()),
        "sparsity": round(1 - len(df_int) / (df_int["user_id"].nunique() * df_int["item_id"].nunique()), 4),
    })

    # Save model
    tracker.log_artifact(model, "svd_model.pkl")
    run_summary = tracker.end_run()

    # Save to models dir
    model_path = MODELS_DIR / "svd_model.pkl"
    with open(model_path, "wb") as f:
        pickle.dump(model, f)
    logger.info(f"SVD model saved → {model_path}")

    return run_summary


def train_content_model(df_int: pd.DataFrame, df_items: pd.DataFrame) -> dict:
    tracker = ExperimentTracker("content_based_filtering")
    tracker.log_params({"model_type": "ContentBased", "similarity": "cosine"})

    feature_cols = ["price_normalized", "category_encoded", "popularity_score",
                    "avg_rating_received", "total_interactions"]
    model = ContentBasedRecommender()
    model.fit(df_items, feature_cols)
    tracker.log_params({"feature_cols": feature_cols, "n_items": len(df_items)})

    # Sample evaluation: check if similar items share category
    sample_items = df_items["item_id"].head(20).tolist()
    category_match = []
    item_cats = df_items.set_index("item_id")["category"].to_dict() if "category" in df_items.columns else {}
    for item_id in sample_items:
        sims = model.recommend_similar(item_id, n=5)
        if item_cats:
            src_cat  = item_cats.get(item_id, "")
            matches  = [item_cats.get(s, "") == src_cat for s in sims]
            category_match.append(np.mean(matches))

    cat_consistency = round(float(np.mean(category_match)), 4) if category_match else 0.0
    tracker.log_metric("category_consistency@5", cat_consistency)
    tracker.log_artifact(model, "content_model.pkl")
    run_summary = tracker.end_run()

    model_path = MODELS_DIR / "content_model.pkl"
    with open(model_path, "wb") as f:
        pickle.dump(model, f)
    logger.info(f"Content model saved → {model_path}")
    return run_summary


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ingestion.ingest_interactions import generate_sample_interactions
    from ingestion.ingest_products_api  import _generate_synthetic_products
    from preparation.prepare_data import (
        clean_interactions, clean_products, encode_products
    )
    from features.feature_engineering import build_item_features

    df_int  = clean_interactions(generate_sample_interactions(3000))
    df_prod, _ = encode_products(clean_products(pd.DataFrame(_generate_synthetic_products(500))))
    df_items   = build_item_features(df_int, df_prod)

    print("\n" + "="*60)
    print("Training SVD Collaborative Filtering model...")
    svd_run = train_svd_model(df_int, n_components=50, k=10)
    print(f"\nSVD Run ID: {svd_run['run_id']}")
    print(f"Metrics: {svd_run['metrics']}")

    print("\n" + "="*60)
    print("Training Content-Based model...")
    cb_run = train_content_model(df_int, df_items)
    print(f"\nContent-Based Run ID: {cb_run['run_id']}")
    print(f"Metrics: {cb_run['metrics']}")
