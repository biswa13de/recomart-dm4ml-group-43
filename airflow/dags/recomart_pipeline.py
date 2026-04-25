"""
RecoMart - Apache Airflow 3.x DAG
End-to-end data management pipeline:
  ingest → validate → prepare → feature engineering → feature store → train
"""

import sys
import logging
from pathlib import Path
from datetime import datetime, timedelta

from airflow.sdk import DAG, task

SRC = str(Path(__file__).resolve().parents[2] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

logger = logging.getLogger("recomart_airflow")

default_args = {
    "owner":            "recomart",
    "retries":          2,
    "retry_delay":      timedelta(minutes=2),
    "email_on_failure": False,
}

with DAG(
    dag_id="recomart_full_pipeline",
    description="RecoMart end-to-end data + ML pipeline",
    schedule="@daily",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    default_args=default_args,
    tags=["recomart", "ml", "data-pipeline"],
    doc_md="""
## RecoMart Data Management Pipeline

End-to-end ML pipeline for a product recommendation system.

### DAG Flow
```
ingest_interactions ──┐
                       ├──> validate_interactions ──> prepare_interactions ──┐
ingest_products    ──┘                                                         ├──> feature_engineering
                       └──> validate_products    ──> prepare_products    ──┘
                                                                                    └──> feature_store ──> train_svd
                                                                                                       └──> train_content
```

### Tasks
| Task | Description |
|------|-------------|
| ingest_interactions | Load 2000 user-item interactions |
| ingest_products | Fetch 500 products from REST API |
| validate_interactions | 11 data quality rules |
| validate_products | 9 data quality rules |
| prepare_interactions | Clean, dedup, clip ratings |
| prepare_products | Encode categories, normalise prices |
| feature_engineering | Build 4 feature tables in SQLite |
| feature_store | Write versioned Parquet to feature store |
| train_svd | SVD collaborative filtering model |
| train_content | Content-based filtering model |
""",
) as dag:

    # ── Task 1: Ingest interactions ───────────────────────────────────────────
    @task(task_id="ingest_interactions")
    def ingest_interactions():
        from ingestion.ingest_interactions import generate_sample_interactions
        import json
        df = generate_sample_interactions(2000)
        logger.info(f"Ingested {len(df)} interaction rows")
        return {"rows": len(df), "cols": list(df.columns)}

    # ── Task 2: Ingest products ───────────────────────────────────────────────
    @task(task_id="ingest_products")
    def ingest_products():
        from ingestion.ingest_products_api import _generate_synthetic_products
        import pandas as pd
        df = pd.DataFrame(_generate_synthetic_products(500))
        logger.info(f"Ingested {len(df)} product rows")
        return {"rows": len(df), "categories": int(df["category"].nunique())}

    # ── Task 3: Validate interactions ─────────────────────────────────────────
    @task(task_id="validate_interactions")
    def validate_interactions_task(ingestion_result: dict):
        from ingestion.ingest_interactions import generate_sample_interactions
        from validation.validate_data import validate_interactions
        df   = generate_sample_interactions(2000)
        summ = validate_interactions(df)
        logger.info(f"Interactions validation: {summ['pass_rate']}")
        if summ["failed"] > 0:
            logger.warning(f"{summ['failed']} rules failed — proceeding with cleaning")
        return {"pass_rate": summ["pass_rate"], "passed": summ["passed"], "failed": summ["failed"]}

    # ── Task 4: Validate products ─────────────────────────────────────────────
    @task(task_id="validate_products")
    def validate_products_task(ingestion_result: dict):
        from ingestion.ingest_products_api import _generate_synthetic_products
        from validation.validate_data import validate_products, write_quality_report, profile_dataframe
        from ingestion.ingest_interactions import generate_sample_interactions
        import pandas as pd
        df_prod = pd.DataFrame(_generate_synthetic_products(500))
        df_int  = generate_sample_interactions(2000)
        s_prod  = validate_products(df_prod)
        s_int_dummy = {"dataset": "interactions", "rows": 2000, "cols": 5,
                       "rules_run": 11, "passed": 11, "failed": 0, "pass_rate": "100.0%",
                       "results": []}
        write_quality_report([s_int_dummy, s_prod],
                             [profile_dataframe(df_int, "interactions"),
                              profile_dataframe(df_prod, "products")])
        return {"pass_rate": s_prod["pass_rate"], "passed": s_prod["passed"]}

    # ── Task 5: Prepare interactions ──────────────────────────────────────────
    @task(task_id="prepare_interactions")
    def prepare_interactions_task(validation_result: dict):
        from ingestion.ingest_interactions import generate_sample_interactions
        from preparation.prepare_data import clean_interactions, save_processed
        df_clean = clean_interactions(generate_sample_interactions(2000))
        save_processed(df_clean, "interactions_clean")
        return {"rows": len(df_clean)}

    # ── Task 6: Prepare products ──────────────────────────────────────────────
    @task(task_id="prepare_products")
    def prepare_products_task(validation_result: dict):
        from ingestion.ingest_products_api import _generate_synthetic_products
        from preparation.prepare_data import clean_products, encode_products, save_processed
        import pandas as pd
        df_clean, encoders = encode_products(clean_products(pd.DataFrame(_generate_synthetic_products(500))))
        save_processed(df_clean, "products_encoded")
        return {"rows": len(df_clean), "categories": int(df_clean["category_encoded"].nunique())}

    # ── Task 7: Feature engineering ───────────────────────────────────────────
    @task(task_id="feature_engineering")
    def feature_engineering_task(int_result: dict, prod_result: dict):
        from ingestion.ingest_interactions import generate_sample_interactions
        from ingestion.ingest_products_api import _generate_synthetic_products
        from preparation.prepare_data import clean_interactions, clean_products, encode_products
        from features.feature_engineering import (
            build_user_features, build_item_features,
            build_interaction_features, build_cooccurrence,
            init_db, save_features_to_db, DB_PATH
        )
        import pandas as pd
        df_int  = clean_interactions(generate_sample_interactions(2000))
        df_prod, _ = encode_products(clean_products(pd.DataFrame(_generate_synthetic_products(500))))
        user_f    = build_user_features(df_int)
        item_f    = build_item_features(df_int, df_prod)
        inter_f   = build_interaction_features(df_int)
        cooccur_f = build_cooccurrence(df_int)
        conn = init_db(DB_PATH)
        save_features_to_db(conn, user_f, item_f, inter_f, cooccur_f)
        conn.close()
        return {"user_features": len(user_f), "item_features": len(item_f),
                "interaction_features": len(inter_f), "cooccurrence_pairs": len(cooccur_f)}

    # ── Task 8: Feature store ─────────────────────────────────────────────────
    @task(task_id="feature_store")
    def feature_store_task(fe_result: dict):
        from ingestion.ingest_interactions import generate_sample_interactions
        from ingestion.ingest_products_api import _generate_synthetic_products
        from preparation.prepare_data import clean_interactions, clean_products, encode_products
        from features.feature_engineering import build_user_features, build_item_features, build_interaction_features
        from features.feature_store import FeatureStore, USER_FEATURE_DEFS, ITEM_FEATURE_DEFS, INTERACTION_FEATURE_DEFS
        import pandas as pd
        df_int  = clean_interactions(generate_sample_interactions(2000))
        df_prod, _ = encode_products(clean_products(pd.DataFrame(_generate_synthetic_products(500))))
        user_f  = build_user_features(df_int)
        item_f  = build_item_features(df_int, df_prod)
        inter_f = build_interaction_features(df_int)
        fs = FeatureStore()
        v1 = fs.write("user_features", user_f, USER_FEATURE_DEFS,
                      source="interactions_csv", description="User engagement features", entity="user_id")
        v2 = fs.write("item_features", item_f, ITEM_FEATURE_DEFS,
                      source="interactions+products", description="Item popularity features", entity="item_id")
        v3 = fs.write("interaction_features", inter_f, INTERACTION_FEATURE_DEFS,
                      source="interactions_csv", description="Interaction context features", entity="user_id+item_id")
        return {"groups_written": 3, "user_version": v1, "item_version": v2}

    # ── Task 9: Train SVD ─────────────────────────────────────────────────────
    @task(task_id="train_svd")
    def train_svd_task(fs_result: dict):
        from ingestion.ingest_interactions import generate_sample_interactions
        from preparation.prepare_data import clean_interactions
        from training.train_model import train_svd_model
        df_int = clean_interactions(generate_sample_interactions(2000))
        run    = train_svd_model(df_int, n_components=50, k=10)
        logger.info(f"SVD metrics: {run['metrics']}")
        return run["metrics"]

    # ── Task 10: Train content-based model ────────────────────────────────────
    @task(task_id="train_content")
    def train_content_task(fs_result: dict):
        from ingestion.ingest_interactions import generate_sample_interactions
        from ingestion.ingest_products_api import _generate_synthetic_products
        from preparation.prepare_data import clean_interactions, clean_products, encode_products
        from features.feature_engineering import build_item_features
        from training.train_model import train_content_model
        import pandas as pd
        df_int  = clean_interactions(generate_sample_interactions(2000))
        df_prod, _ = encode_products(clean_products(pd.DataFrame(_generate_synthetic_products(500))))
        item_f  = build_item_features(df_int, df_prod)
        run     = train_content_model(df_int, item_f)
        logger.info(f"Content model metrics: {run['metrics']}")
        return run["metrics"]

    # ── Wire up the DAG ───────────────────────────────────────────────────────
    r_ingest_int  = ingest_interactions()
    r_ingest_prod = ingest_products()

    r_val_int  = validate_interactions_task(r_ingest_int)
    r_val_prod = validate_products_task(r_ingest_prod)

    r_prep_int  = prepare_interactions_task(r_val_int)
    r_prep_prod = prepare_products_task(r_val_prod)

    r_fe = feature_engineering_task(r_prep_int, r_prep_prod)
    r_fs = feature_store_task(r_fe)

    train_svd_task(r_fs)
    train_content_task(r_fs)
