"""
RecoMart Data Pipeline - Task 5: Data Preparation
Handles missing values, encoding, normalization, sparsity analysis,
and generates EDA summary statistics and plots metadata.
"""

import logging
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
from sklearn.preprocessing import LabelEncoder, MinMaxScaler

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "preparation.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("data_preparation")

PROCESSED_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


# ── Step 1: Clean interactions ────────────────────────────────────────────────
def clean_interactions(df: pd.DataFrame) -> pd.DataFrame:
    logger.info(f"Cleaning interactions — input shape: {df.shape}")
    initial_rows = len(df)

    # 1. Drop rows with null user_id or item_id (non-recoverable)
    df = df.dropna(subset=["user_id", "item_id"])
    logger.info(f"  After dropping null IDs: {len(df)} rows")

    # 2. Fill missing ratings with user median, then global median
    if df["rating"].isnull().any():
        user_medians = df.groupby("user_id")["rating"].transform("median")
        df["rating"] = df["rating"].fillna(user_medians)
        df["rating"] = df["rating"].fillna(df["rating"].median())
        logger.info("  Filled missing ratings with user/global median")

    # 3. Clip ratings to valid range [1.0, 5.0]
    clipped = ((df["rating"] < 1.0) | (df["rating"] > 5.0)).sum()
    df["rating"] = df["rating"].clip(1.0, 5.0)
    if clipped:
        logger.warning(f"  Clipped {clipped} out-of-range ratings to [1.0, 5.0]")

    # 4. Remove duplicates (keep last interaction per user-item pair)
    before_dedup = len(df)
    df = df.sort_values("timestamp").drop_duplicates(
        subset=["user_id", "item_id"], keep="last"
    )
    logger.info(f"  Removed {before_dedup - len(df)} duplicate user-item pairs (kept latest)")

    # 5. Convert types
    df["user_id"]   = df["user_id"].astype(int)
    df["item_id"]   = df["item_id"].astype(int)
    df["rating"]    = df["rating"].astype(float).round(1)
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")

    # 6. Remove rows with unparseable timestamps
    bad_ts = df["timestamp"].isnull().sum()
    if bad_ts:
        df = df.dropna(subset=["timestamp"])
        logger.warning(f"  Dropped {bad_ts} rows with invalid timestamps")

    logger.info(f"Interactions cleaned: {initial_rows} → {len(df)} rows")
    return df.reset_index(drop=True)


# ── Step 2: Clean products ────────────────────────────────────────────────────
def clean_products(df: pd.DataFrame) -> pd.DataFrame:
    logger.info(f"Cleaning products — input shape: {df.shape}")

    # 1. Drop duplicate item_ids
    df = df.drop_duplicates(subset=["item_id"])

    # 2. Fill missing categories
    df["category"] = df["category"].fillna("unknown")

    # 3. Fix negative or zero prices
    bad_prices = (df["price"] <= 0).sum()
    df.loc[df["price"] <= 0, "price"] = df["price"][df["price"] > 0].median()
    if bad_prices:
        logger.warning(f"  Fixed {bad_prices} invalid prices with median")

    # 4. Clip ratings
    df["rating"] = df["rating"].clip(0.0, 5.0)

    # 5. Fill missing booleans
    if "in_stock" in df.columns:
        df["in_stock"] = df["in_stock"].fillna(True)

    logger.info(f"Products cleaned: {len(df)} rows")
    return df.reset_index(drop=True)


# ── Step 3: Encode categoricals ───────────────────────────────────────────────
def encode_products(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    encoders = {}
    for col in ["category", "brand"]:
        if col not in df.columns:
            continue
        le = LabelEncoder()
        df[f"{col}_encoded"] = le.fit_transform(df[col].astype(str))
        encoders[col] = le
        logger.info(f"  Encoded '{col}' → {df[col].nunique()} classes")

    # Normalize price
    scaler = MinMaxScaler()
    df["price_normalized"] = scaler.fit_transform(df[["price"]])
    encoders["price_scaler"] = scaler
    logger.info("  Normalized 'price' → [0,1]")

    return df, encoders


# ── Step 4: EDA summary ───────────────────────────────────────────────────────
def eda_summary(df_int: pd.DataFrame, df_prod: pd.DataFrame) -> dict:
    n_users    = df_int["user_id"].nunique()
    n_items    = df_int["item_id"].nunique()
    n_interact = len(df_int)
    sparsity   = 1 - (n_interact / (n_users * n_items))

    # Rating distribution
    rating_dist = df_int["rating"].value_counts().sort_index().to_dict()
    rating_dist = {str(k): int(v) for k, v in rating_dist.items()}

    # Top 10 most interacted items
    top_items = (
        df_int.groupby("item_id")["user_id"]
        .count().sort_values(ascending=False).head(10).to_dict()
    )
    top_items = {str(k): int(v) for k, v in top_items.items()}

    # User activity distribution
    user_activity = df_int.groupby("user_id")["item_id"].count()

    # Event type breakdown
    event_dist = {}
    if "event_type" in df_int.columns:
        event_dist = df_int["event_type"].value_counts().to_dict()
        event_dist = {str(k): int(v) for k, v in event_dist.items()}

    # Category distribution in products
    cat_dist = {}
    if "category" in df_prod.columns:
        cat_dist = df_prod["category"].value_counts().to_dict()
        cat_dist = {str(k): int(v) for k, v in cat_dist.items()}

    summary = {
        "n_users":         n_users,
        "n_items":         n_items,
        "n_interactions":  n_interact,
        "sparsity":        f"{sparsity * 100:.2f}%",
        "avg_rating":      round(float(df_int["rating"].mean()), 3),
        "rating_std":      round(float(df_int["rating"].std()), 3),
        "rating_distribution": rating_dist,
        "top_10_items_by_interactions": top_items,
        "user_activity_stats": {
            "min":    int(user_activity.min()),
            "max":    int(user_activity.max()),
            "mean":   round(float(user_activity.mean()), 2),
            "median": round(float(user_activity.median()), 2),
        },
        "event_type_distribution": event_dist,
        "product_category_distribution": cat_dist,
    }

    logger.info(
        f"EDA: users={n_users}, items={n_items}, interactions={n_interact}, "
        f"sparsity={summary['sparsity']}"
    )
    return summary


# ── Step 5: Save processed data ───────────────────────────────────────────────
def save_processed(df: pd.DataFrame, name: str) -> str:
    ts   = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    path = PROCESSED_DIR / f"{name}_{ts}.csv"
    df.to_csv(path, index=False)
    logger.info(f"Saved processed {name} → {path}")
    return str(path)


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys, json
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ingestion.ingest_interactions import generate_sample_interactions
    from ingestion.ingest_products_api  import _generate_synthetic_products

    # Load raw data
    df_int  = generate_sample_interactions(2000)
    df_prod = pd.DataFrame(_generate_synthetic_products(500))

    # Inject dirty data for demonstration
    df_int.loc[:5, "rating"]  = [6.0, -1.0, None, 5.5, 0.5, None]
    df_prod.loc[0, "price"]   = -50.0

    # Clean
    df_int_clean  = clean_interactions(df_int)
    df_prod_clean = clean_products(df_prod)

    # Encode
    df_prod_enc, encoders = encode_products(df_prod_clean)

    # EDA
    eda = eda_summary(df_int_clean, df_prod_enc)
    print("\n── EDA Summary ──")
    print(json.dumps(eda, indent=2))

    # Save
    save_processed(df_int_clean,  "interactions_clean")
    save_processed(df_prod_enc,   "products_encoded")
