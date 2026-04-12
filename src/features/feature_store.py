"""
RecoMart Data Pipeline - Task 7: Feature Store
A lightweight custom feature store with versioned retrieval,
metadata registry, and support for both training and inference.
"""

import json
import logging
import hashlib
import pandas as pd
from pathlib import Path
from datetime import datetime

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "feature_store.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("feature_store")

FS_DIR = Path(__file__).resolve().parents[2] / "feature_store"
FS_DIR.mkdir(parents=True, exist_ok=True)

REGISTRY_PATH = FS_DIR / "feature_registry.json"


# ── Feature metadata registry ────────────────────────────────────────────────
class FeatureRegistry:
    def __init__(self, path: Path = REGISTRY_PATH):
        self.path = path
        self.registry = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            with open(self.path) as f:
                return json.load(f)
        return {"feature_groups": {}, "versions": {}}

    def _save(self):
        with open(self.path, "w") as f:
            json.dump(self.registry, f, indent=2)

    def register_feature_group(
        self,
        name: str,
        features: list[dict],
        source: str,
        description: str,
        entity: str,
        version: str = None,
    ) -> str:
        version = version or datetime.utcnow().strftime("v%Y%m%d_%H%M%S")
        entry = {
            "name":        name,
            "entity":      entity,
            "description": description,
            "source":      source,
            "version":     version,
            "created_at":  datetime.utcnow().isoformat(),
            "features":    features,
        }
        if name not in self.registry["feature_groups"]:
            self.registry["feature_groups"][name] = []
        self.registry["feature_groups"][name].append(entry)
        self.registry["versions"][f"{name}:{version}"] = entry
        self._save()
        logger.info(f"Registered feature group '{name}' version '{version}'")
        return version

    def get_latest(self, name: str) -> dict | None:
        versions = self.registry["feature_groups"].get(name, [])
        return versions[-1] if versions else None

    def get_version(self, name: str, version: str) -> dict | None:
        return self.registry["versions"].get(f"{name}:{version}")

    def list_feature_groups(self) -> list[str]:
        return list(self.registry["feature_groups"].keys())


# ── Feature store ─────────────────────────────────────────────────────────────
class FeatureStore:
    def __init__(self, store_dir: Path = FS_DIR):
        self.store_dir = store_dir
        self.registry  = FeatureRegistry()

    def _group_dir(self, name: str, version: str) -> Path:
        d = self.store_dir / name / version
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _checksum(self, df: pd.DataFrame) -> str:
        return hashlib.md5(pd.util.hash_pandas_object(df).values).hexdigest()[:12]

    # ── Write ─────────────────────────────────────────────────────────────────
    def write(
        self,
        name: str,
        df: pd.DataFrame,
        feature_defs: list[dict],
        source: str,
        description: str,
        entity: str,
        version: str = None,
    ) -> str:
        version = self.registry.register_feature_group(
            name, feature_defs, source, description, entity, version
        )
        out_dir  = self._group_dir(name, version)
        parquet  = out_dir / "features.parquet"
        df.to_parquet(parquet, index=False)

        meta = {
            "name":      name,
            "version":   version,
            "rows":      len(df),
            "cols":      len(df.columns),
            "checksum":  self._checksum(df),
            "written_at": datetime.utcnow().isoformat(),
            "columns":   list(df.columns),
        }
        with open(out_dir / "metadata.json", "w") as f:
            json.dump(meta, f, indent=2)

        logger.info(
            f"[FeatureStore] Written '{name}' v={version} | "
            f"{len(df)} rows × {len(df.columns)} cols | checksum={meta['checksum']}"
        )
        return version

    # ── Read (latest) ─────────────────────────────────────────────────────────
    def read(self, name: str, version: str = None, columns: list[str] = None) -> pd.DataFrame:
        if version is None:
            meta = self.registry.get_latest(name)
            if meta is None:
                raise KeyError(f"Feature group '{name}' not found in registry")
            version = meta["version"]

        parquet = self._group_dir(name, version) / "features.parquet"
        if not parquet.exists():
            raise FileNotFoundError(f"Feature data not found: {parquet}")

        df = pd.read_parquet(parquet, columns=columns)
        logger.info(f"[FeatureStore] Read '{name}' v={version} | {len(df)} rows")
        return df

    # ── Point-in-time retrieval (inference) ───────────────────────────────────
    def get_online_features(self, name: str, entity_ids: list, entity_col: str) -> pd.DataFrame:
        df = self.read(name)
        result = df[df[entity_col].isin(entity_ids)]
        logger.info(f"[FeatureStore] Online lookup '{name}' | {len(result)} entities found")
        return result

    def list_versions(self, name: str) -> list[str]:
        versions = self.registry.registry["feature_groups"].get(name, [])
        return [v["version"] for v in versions]


# ── Feature definitions ───────────────────────────────────────────────────────
USER_FEATURE_DEFS = [
    {"name": "total_interactions",  "dtype": "int",   "description": "Total number of user interactions"},
    {"name": "unique_items",        "dtype": "int",   "description": "Number of unique items interacted with"},
    {"name": "avg_rating_given",    "dtype": "float", "description": "Average rating given by the user"},
    {"name": "std_rating_given",    "dtype": "float", "description": "Std deviation of ratings given"},
    {"name": "purchase_count",      "dtype": "int",   "description": "Number of purchases"},
    {"name": "view_count",          "dtype": "int",   "description": "Number of item views"},
    {"name": "activity_score",      "dtype": "float", "description": "Weighted engagement score"},
    {"name": "recency_days",        "dtype": "float", "description": "Days since last interaction"},
]

ITEM_FEATURE_DEFS = [
    {"name": "total_interactions",   "dtype": "int",   "description": "Total interactions with the item"},
    {"name": "unique_users",         "dtype": "int",   "description": "Number of unique users who interacted"},
    {"name": "avg_rating_received",  "dtype": "float", "description": "Average rating received by the item"},
    {"name": "popularity_score",     "dtype": "float", "description": "Log-normalised popularity score [0,1]"},
    {"name": "price_normalized",     "dtype": "float", "description": "Min-max normalised price"},
    {"name": "category_encoded",     "dtype": "int",   "description": "Label-encoded product category"},
]

INTERACTION_FEATURE_DEFS = [
    {"name": "rating",          "dtype": "float", "description": "User rating for item"},
    {"name": "hour_of_day",     "dtype": "int",   "description": "Hour of interaction (0-23)"},
    {"name": "day_of_week",     "dtype": "int",   "description": "Day of week (0=Mon, 6=Sun)"},
    {"name": "is_weekend",      "dtype": "int",   "description": "1 if weekend interaction"},
    {"name": "user_item_gap",   "dtype": "float", "description": "Rating deviation from user average"},
]


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ingestion.ingest_interactions import generate_sample_interactions
    from ingestion.ingest_products_api  import _generate_synthetic_products
    from preparation.prepare_data import (
        clean_interactions, clean_products, encode_products
    )
    from features.feature_engineering import (
        build_user_features, build_item_features, build_interaction_features
    )

    df_int  = clean_interactions(generate_sample_interactions(2000))
    df_prod, _ = encode_products(clean_products(pd.DataFrame(_generate_synthetic_products(500))))

    user_f  = build_user_features(df_int)
    item_f  = build_item_features(df_int, df_prod)
    inter_f = build_interaction_features(df_int)

    fs = FeatureStore()

    v_user  = fs.write("user_features",  user_f,  USER_FEATURE_DEFS,
                       source="interactions_csv",
                       description="User engagement and activity features",
                       entity="user_id")

    v_item  = fs.write("item_features",  item_f,  ITEM_FEATURE_DEFS,
                       source="interactions_csv+products_api",
                       description="Item popularity and catalogue features",
                       entity="item_id")

    v_inter = fs.write("interaction_features", inter_f, INTERACTION_FEATURE_DEFS,
                       source="interactions_csv",
                       description="User-item interaction context features",
                       entity="user_id+item_id")

    print(f"\nFeature groups registered: {fs.list_versions('user_features')}")

    # Demonstrate online lookup
    sample_users = [1, 2, 3, 4, 5]
    online_feats = fs.get_online_features("user_features", sample_users, "user_id")
    print(f"\nOnline feature lookup for users {sample_users}:")
    print(online_feats[["user_id", "activity_score", "avg_rating_given", "recency_days"]].to_string())

    # Demonstrate versioned read
    read_back = fs.read("item_features", version=v_item, columns=["item_id", "popularity_score"])
    print(f"\nVersioned item feature read (v={v_item}): {len(read_back)} rows")
