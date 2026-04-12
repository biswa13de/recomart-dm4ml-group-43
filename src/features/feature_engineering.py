"""
RecoMart Data Pipeline - Task 6: Feature Engineering & Transformation
Creates user-level, item-level, and interaction-level features
for collaborative and content-based recommendation models.
Stores results in SQLite (acts as the warehouse layer).
"""

import logging
import sqlite3
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "features.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("feature_engineering")

PROCESSED_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "recomart.db"


# ── SQL schema ────────────────────────────────────────────────────────────────
SQL_SCHEMA = """
-- User features table
CREATE TABLE IF NOT EXISTS user_features (
    user_id             INTEGER PRIMARY KEY,
    total_interactions  INTEGER,
    unique_items        INTEGER,
    avg_rating_given    REAL,
    std_rating_given    REAL,
    purchase_count      INTEGER,
    view_count          INTEGER,
    wishlist_count      INTEGER,
    cart_count          INTEGER,
    activity_score      REAL,
    recency_days        REAL,
    created_at          TEXT
);

-- Item features table
CREATE TABLE IF NOT EXISTS item_features (
    item_id             INTEGER PRIMARY KEY,
    total_interactions  INTEGER,
    unique_users        INTEGER,
    avg_rating_received REAL,
    std_rating_received REAL,
    popularity_score    REAL,
    category            TEXT,
    brand               TEXT,
    price               REAL,
    price_normalized    REAL,
    category_encoded    INTEGER,
    created_at          TEXT
);

-- User-item interaction features
CREATE TABLE IF NOT EXISTS interaction_features (
    user_id             INTEGER,
    item_id             INTEGER,
    rating              REAL,
    event_type          TEXT,
    timestamp           TEXT,
    hour_of_day         INTEGER,
    day_of_week         INTEGER,
    is_weekend          INTEGER,
    user_item_gap       REAL,
    PRIMARY KEY (user_id, item_id),
    FOREIGN KEY (user_id) REFERENCES user_features(user_id),
    FOREIGN KEY (item_id) REFERENCES item_features(item_id)
);

-- Co-occurrence matrix (items frequently interacted together)
CREATE TABLE IF NOT EXISTS item_cooccurrence (
    item_a              INTEGER,
    item_b              INTEGER,
    cooccur_count       INTEGER,
    jaccard_similarity  REAL,
    PRIMARY KEY (item_a, item_b)
);
"""


def init_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.executescript(SQL_SCHEMA)
    conn.commit()
    logger.info(f"Database initialised: {db_path}")
    return conn


# ── User features ─────────────────────────────────────────────────────────────
def build_user_features(df: pd.DataFrame) -> pd.DataFrame:
    logger.info("Building user features...")
    now = pd.Timestamp.now()

    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=False)
    # Strip timezone info if present to ensure tz-naive arithmetic
    if hasattr(df["timestamp"].dtype, "tz") and df["timestamp"].dt.tz is not None:
        df["timestamp"] = df["timestamp"].dt.tz_localize(None)

    agg = df.groupby("user_id").agg(
        total_interactions = ("item_id", "count"),
        unique_items       = ("item_id", "nunique"),
        avg_rating_given   = ("rating", "mean"),
        std_rating_given   = ("rating", "std"),
        last_interaction   = ("timestamp", "max"),
    ).reset_index()

    # Event-type breakdown (if present)
    if "event_type" in df.columns:
        for evt in ["purchase", "view", "wishlist", "cart"]:
            sub = df[df["event_type"] == evt].groupby("user_id").size().rename(f"{evt}_count")
            agg = agg.merge(sub, on="user_id", how="left")
            agg[f"{evt}_count"] = agg[f"{evt}_count"].fillna(0).astype(int)
    else:
        for evt in ["purchase", "view", "wishlist", "cart"]:
            agg[f"{evt}_count"] = 0

    # Activity score = weighted sum of events
    agg["activity_score"] = (
        agg["purchase_count"] * 4 +
        agg["wishlist_count"] * 2 +
        agg["cart_count"]     * 2 +
        agg["view_count"]     * 1
    )

    # Recency in days
    agg["recency_days"] = (now - agg["last_interaction"]).dt.total_seconds() / 86400
    agg["recency_days"] = agg["recency_days"].fillna(999).round(2)
    agg["std_rating_given"] = agg["std_rating_given"].fillna(0).round(4)
    agg["avg_rating_given"] = agg["avg_rating_given"].round(4)
    agg["created_at"] = now.strftime("%Y-%m-%d %H:%M:%S")
    agg = agg.drop(columns=["last_interaction"])

    logger.info(f"User features: {len(agg)} users, {len(agg.columns)} features")
    return agg


# ── Item features ─────────────────────────────────────────────────────────────
def build_item_features(df_int: pd.DataFrame, df_prod: pd.DataFrame) -> pd.DataFrame:
    logger.info("Building item features...")

    agg = df_int.groupby("item_id").agg(
        total_interactions  = ("user_id", "count"),
        unique_users        = ("user_id", "nunique"),
        avg_rating_received = ("rating", "mean"),
        std_rating_received = ("rating", "std"),
    ).reset_index()

    # Popularity score (log-normalised interaction count)
    agg["popularity_score"] = np.log1p(agg["total_interactions"])
    agg["popularity_score"] = (
        (agg["popularity_score"] - agg["popularity_score"].min()) /
        (agg["popularity_score"].max() - agg["popularity_score"].min() + 1e-9)
    ).round(4)

    # Merge product metadata
    prod_cols = ["item_id", "category", "price", "price_normalized"]
    if "brand" in df_prod.columns:
        prod_cols.append("brand")
    if "category_encoded" in df_prod.columns:
        prod_cols.append("category_encoded")

    prod_cols = [c for c in prod_cols if c in df_prod.columns]
    agg = agg.merge(df_prod[prod_cols], on="item_id", how="left")

    agg["std_rating_received"] = agg["std_rating_received"].fillna(0).round(4)
    agg["avg_rating_received"] = agg["avg_rating_received"].round(4)
    agg["created_at"] = pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    logger.info(f"Item features: {len(agg)} items, {len(agg.columns)} features")
    return agg


# ── Interaction features ──────────────────────────────────────────────────────
def build_interaction_features(df: pd.DataFrame) -> pd.DataFrame:
    logger.info("Building interaction features...")

    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df["hour_of_day"] = df["timestamp"].dt.hour
    df["day_of_week"] = df["timestamp"].dt.dayofweek
    df["is_weekend"]  = df["day_of_week"].isin([5, 6]).astype(int)

    # User-item rating gap from user average
    user_avg = df.groupby("user_id")["rating"].transform("mean")
    df["user_item_gap"] = (df["rating"] - user_avg).round(4)

    # Keep relevant columns
    cols = ["user_id", "item_id", "rating", "hour_of_day",
            "day_of_week", "is_weekend", "user_item_gap"]
    if "event_type" in df.columns:
        cols.append("event_type")
    if "timestamp" in df.columns:
        df["timestamp"] = df["timestamp"].astype(str)
        cols.append("timestamp")

    result = df[cols].drop_duplicates(subset=["user_id", "item_id"])
    logger.info(f"Interaction features: {len(result)} rows")
    return result


# ── Co-occurrence features ────────────────────────────────────────────────────
def build_cooccurrence(df: pd.DataFrame, min_cooccur: int = 2) -> pd.DataFrame:
    logger.info("Building item co-occurrence features...")

    # Items purchased/interacted with by same user
    user_items = df.groupby("user_id")["item_id"].apply(list)
    pairs = []
    for items in user_items:
        items = list(set(items))
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                a, b = sorted([items[i], items[j]])
                pairs.append((a, b))

    if not pairs:
        return pd.DataFrame(columns=["item_a", "item_b", "cooccur_count", "jaccard_similarity"])

    co_df = pd.DataFrame(pairs, columns=["item_a", "item_b"])
    co_df = co_df.groupby(["item_a", "item_b"]).size().reset_index(name="cooccur_count")
    co_df = co_df[co_df["cooccur_count"] >= min_cooccur]

    # Jaccard similarity
    item_users = df.groupby("item_id")["user_id"].apply(set)
    def jaccard(a, b):
        if a not in item_users.index or b not in item_users.index:
            return 0.0
        s1, s2 = item_users[a], item_users[b]
        inter  = len(s1 & s2)
        union  = len(s1 | s2)
        return round(inter / union, 4) if union > 0 else 0.0

    co_df["jaccard_similarity"] = co_df.apply(
        lambda r: jaccard(r["item_a"], r["item_b"]), axis=1
    )

    logger.info(f"Co-occurrence pairs: {len(co_df)}")
    return co_df


# ── Save to DB ────────────────────────────────────────────────────────────────
def save_features_to_db(conn, user_f, item_f, inter_f, cooccur_f):
    user_f.to_sql("user_features",         conn, if_exists="replace", index=False)
    item_f.to_sql("item_features",         conn, if_exists="replace", index=False)
    inter_f.to_sql("interaction_features", conn, if_exists="replace", index=False)
    cooccur_f.to_sql("item_cooccurrence",  conn, if_exists="replace", index=False)
    conn.commit()
    logger.info("All feature tables saved to database")


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ingestion.ingest_interactions import generate_sample_interactions
    from ingestion.ingest_products_api  import _generate_synthetic_products
    from preparation.prepare_data import (
        clean_interactions, clean_products, encode_products
    )

    df_int  = clean_interactions(generate_sample_interactions(2000))
    df_prod, _ = encode_products(clean_products(pd.DataFrame(_generate_synthetic_products(500))))

    user_f    = build_user_features(df_int)
    item_f    = build_item_features(df_int, df_prod)
    inter_f   = build_interaction_features(df_int)
    cooccur_f = build_cooccurrence(df_int)

    conn = init_db(DB_PATH)
    save_features_to_db(conn, user_f, item_f, inter_f, cooccur_f)
    conn.close()

    print(f"\nFeature tables saved to: {DB_PATH}")
    print(f"  user_features:         {len(user_f)} rows")
    print(f"  item_features:         {len(item_f)} rows")
    print(f"  interaction_features:  {len(inter_f)} rows")
    print(f"  item_cooccurrence:     {len(cooccur_f)} rows")
