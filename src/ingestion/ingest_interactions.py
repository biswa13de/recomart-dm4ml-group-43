"""
RecoMart Data Pipeline - Task 2: Data Ingestion (User Interactions)
Ingests user-item interaction data from CSV files with logging,
error handling, and retry mechanisms.
"""

import os
import time
import logging
import hashlib
import pandas as pd
from datetime import datetime
from pathlib import Path

# ── Logging setup ──────────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "ingestion.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("ingest_interactions")

# ── Constants ─────────────────────────────────────────────────────────────────
RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw" / "interactions"
RAW_DIR.mkdir(parents=True, exist_ok=True)

REQUIRED_COLUMNS = {"user_id", "item_id", "rating", "timestamp"}
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds


# ── Synthetic data generator (simulates CSV source) ───────────────────────────
def generate_sample_interactions(n: int = 2000) -> pd.DataFrame:
    import numpy as np
    np.random.seed(42)
    return pd.DataFrame({
        "user_id":   np.random.randint(1, 201, n),
        "item_id":   np.random.randint(1, 501, n),
        "rating":    np.round(np.random.uniform(1.0, 5.0, n), 1),
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="30min")
                        .strftime("%Y-%m-%d %H:%M:%S"),
        "event_type": np.random.choice(
            ["purchase", "view", "wishlist", "cart"], n,
            p=[0.25, 0.50, 0.15, 0.10]
        ),
    })


def _validate_schema(df: pd.DataFrame, source: str) -> bool:
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        logger.error(f"[{source}] Schema mismatch — missing columns: {missing}")
        return False
    return True


def _compute_checksum(df: pd.DataFrame) -> str:
    return hashlib.md5(pd.util.hash_pandas_object(df).values).hexdigest()


def ingest_interactions_csv(source_path: str = None, retries: int = MAX_RETRIES) -> str | None:
    """
    Ingest user-item interactions from a CSV file (or generate synthetic data).
    Returns the path to the saved raw file, or None on failure.
    """
    attempt = 0
    while attempt < retries:
        attempt += 1
        logger.info(f"Ingestion attempt {attempt}/{retries} for interactions CSV")
        try:
            if source_path and Path(source_path).exists():
                df = pd.read_csv(source_path)
                logger.info(f"Loaded {len(df)} rows from {source_path}")
            else:
                logger.warning("No CSV path provided — generating synthetic interaction data")
                df = generate_sample_interactions()
                logger.info(f"Generated {len(df)} synthetic interaction rows")

            # Schema validation
            if not _validate_schema(df, "interactions_csv"):
                return None

            # Basic quality checks
            null_count = df[list(REQUIRED_COLUMNS)].isnull().sum().sum()
            if null_count > 0:
                logger.warning(f"Found {null_count} nulls in required columns — will handle in validation stage")

            dup_count = df.duplicated(subset=["user_id", "item_id", "timestamp"]).sum()
            if dup_count > 0:
                logger.warning(f"Found {dup_count} duplicate interaction rows")

            # Partition by date and save
            ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            out_path = RAW_DIR / f"interactions_{ts}.csv"
            df.to_csv(out_path, index=False)

            checksum = _compute_checksum(df)
            logger.info(
                f"Ingestion SUCCESS | rows={len(df)} | cols={list(df.columns)} "
                f"| checksum={checksum} | saved={out_path}"
            )
            return str(out_path)

        except FileNotFoundError as e:
            logger.error(f"File not found: {e}")
            return None
        except pd.errors.ParserError as e:
            logger.error(f"CSV parse error: {e}")
        except Exception as e:
            logger.error(f"Unexpected error on attempt {attempt}: {e}")

        if attempt < retries:
            logger.info(f"Retrying in {RETRY_DELAY}s...")
            time.sleep(RETRY_DELAY)

    logger.error(f"Ingestion FAILED after {retries} attempts")
    return None


if __name__ == "__main__":
    path = ingest_interactions_csv()
    print(f"Saved to: {path}")
