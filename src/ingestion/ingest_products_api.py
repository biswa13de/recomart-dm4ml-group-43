"""
RecoMart Data Pipeline - Task 2: Data Ingestion (Product Metadata via API)
Ingests product catalog data from a REST API (simulated) with retry,
exponential backoff, logging, and structured storage.
"""

import os
import json
import time
import logging
import requests
import pandas as pd
from datetime import datetime
from pathlib import Path

# ── Logging ───────────────────────────────────────────────────────────────────
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
logger = logging.getLogger("ingest_products_api")

# ── Constants ─────────────────────────────────────────────────────────────────
RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw" / "products"
RAW_DIR.mkdir(parents=True, exist_ok=True)

API_URL     = "https://fakestoreapi.com/products"
MAX_RETRIES = 3
BACKOFF     = 2  # seconds base


# ── Synthetic fallback ────────────────────────────────────────────────────────
def _generate_synthetic_products(n: int = 500) -> list[dict]:
    import numpy as np
    np.random.seed(0)
    categories = ["electronics", "clothing", "home", "books", "sports", "beauty"]
    brands     = ["BrandA", "BrandB", "BrandC", "BrandD", "BrandE"]
    return [
        {
            "item_id":      i + 1,
            "title":        f"Product_{i+1}",
            "category":     np.random.choice(categories),
            "brand":        np.random.choice(brands),
            "price":        round(np.random.uniform(5.0, 999.0), 2),
            "rating":       round(np.random.uniform(1.0, 5.0), 1),
            "rating_count": int(np.random.randint(5, 5000)),
            "in_stock":     bool(np.random.choice([True, False], p=[0.85, 0.15])),
        }
        for i in range(n)
    ]


# ── API fetch with exponential backoff ───────────────────────────────────────
def fetch_from_api(url: str, retries: int = MAX_RETRIES) -> list[dict] | None:
    for attempt in range(1, retries + 1):
        try:
            logger.info(f"API call attempt {attempt}/{retries} → {url}")
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            logger.info(f"API responded with {len(data)} records")
            return data
        except requests.exceptions.Timeout:
            logger.warning(f"Timeout on attempt {attempt}")
        except requests.exceptions.ConnectionError:
            logger.warning(f"Connection error on attempt {attempt}")
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected API error: {e}")

        wait = BACKOFF ** attempt
        logger.info(f"Backing off {wait}s before retry...")
        time.sleep(wait)

    logger.error("All API retries exhausted — falling back to synthetic data")
    return None


def ingest_products_api() -> str | None:
    """
    Fetch product catalog from REST API; fall back to synthetic data.
    Saves as JSON + CSV and returns the CSV path.
    """
    raw_data = fetch_from_api(API_URL)

    if raw_data is None:
        logger.warning("Using synthetic product data")
        raw_data = _generate_synthetic_products()

    # Normalise FakeStoreAPI schema → RecoMart schema
    records = []
    for p in raw_data:
        records.append({
            "item_id":      p.get("id", p.get("item_id")),
            "title":        p.get("title", ""),
            "category":     p.get("category", "unknown"),
            "brand":        p.get("brand", "unknown"),
            "price":        float(p.get("price", 0.0)),
            "rating":       float(p.get("rating", {}).get("rate", p.get("rating", 0.0)))
                            if isinstance(p.get("rating"), dict)
                            else float(p.get("rating", 0.0)),
            "rating_count": int(p.get("rating", {}).get("count", p.get("rating_count", 0)))
                            if isinstance(p.get("rating"), dict)
                            else int(p.get("rating_count", 0)),
            "in_stock":     p.get("in_stock", True),
        })

    df = pd.DataFrame(records)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    # Save both JSON (raw) and CSV (normalised)
    json_path = RAW_DIR / f"products_raw_{ts}.json"
    csv_path  = RAW_DIR / f"products_{ts}.csv"

    with open(json_path, "w") as f:
        json.dump(raw_data, f, indent=2)

    df.to_csv(csv_path, index=False)

    logger.info(
        f"Product ingestion SUCCESS | records={len(df)} | "
        f"categories={df['category'].nunique()} | "
        f"json={json_path} | csv={csv_path}"
    )
    return str(csv_path)


if __name__ == "__main__":
    path = ingest_products_api()
    print(f"Saved to: {path}")
