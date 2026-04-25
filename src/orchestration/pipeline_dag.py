"""
RecoMart Data Pipeline - Task 10: Pipeline Orchestration
Implements an Airflow-compatible DAG structure that runs the full
end-to-end pipeline: ingestion → validation → preparation →
feature engineering → feature store → model training.

Can run standalone (no Airflow required) or be imported as an Airflow DAG.
"""

import sys
import logging
import time
import json
import traceback
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, field
import pandas as pd
from ingestion.ingest_interactions import ingest_interactions_csv, generate_sample_interactions
from ingestion.ingest_products_api import ingest_products_api, _generate_synthetic_products
from validation.validate_data import validate_interactions, validate_products, write_quality_report, profile_dataframe
from preparation.prepare_data import clean_interactions, clean_products, encode_products, save_processed
from features.feature_engineering import (
    build_user_features, build_item_features,
    build_interaction_features, build_cooccurrence,
    init_db, save_features_to_db, DB_PATH
)
from features.feature_store import (
    FeatureStore, USER_FEATURE_DEFS, ITEM_FEATURE_DEFS, INTERACTION_FEATURE_DEFS
)
from training.train_model import train_svd_model, train_content_model

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "orchestration.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("orchestration")


# ── Lightweight task/DAG runtime ─────────────────────────────────────────────
@dataclass
class TaskResult:
    task_id:    str
    status:     str        # SUCCESS | FAILED | SKIPPED
    start_time: str = ""
    end_time:   str = ""
    duration_s: float = 0.0
    output:     dict = field(default_factory=dict)
    error:      str  = ""


class DAGRunner:
    """Runs a directed acyclic graph of tasks with dependency tracking."""

    def __init__(self, dag_id: str, description: str = ""):
        self.dag_id      = dag_id
        self.description = description
        self.tasks       = {}      # task_id → callable
        self.deps        = {}      # task_id → list of upstream task_ids
        self.results     = {}      # task_id → TaskResult

    def register(self, task_id: str, fn, upstream: list[str] = None):
        self.tasks[task_id] = fn
        self.deps[task_id]  = upstream or []

    def _can_run(self, task_id: str) -> bool:
        return all(
            self.results.get(dep, TaskResult(dep, "PENDING")).status == "SUCCESS"
            for dep in self.deps[task_id]
        )

    def run(self) -> dict:
        run_id    = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        run_start = datetime.utcnow()
        logger.info(f"{'='*60}")
        logger.info(f"DAG: {self.dag_id}  |  Run ID: {run_id}")
        logger.info(f"{'='*60}")

        # Topological execution
        remaining = list(self.tasks.keys())
        while remaining:
            progress = False
            for task_id in list(remaining):
                if not self._can_run(task_id):
                    # Check if any upstream failed → mark SKIPPED
                    if any(
                        self.results.get(dep, TaskResult(dep, "PENDING")).status == "FAILED"
                        for dep in self.deps[task_id]
                    ):
                        self.results[task_id] = TaskResult(
                            task_id=task_id, status="SKIPPED",
                            error="Upstream task failed"
                        )
                        remaining.remove(task_id)
                        logger.warning(f"[{task_id}] SKIPPED (upstream failed)")
                        progress = True
                    continue

                # Execute task
                t_start = datetime.utcnow()
                logger.info(f"[{task_id}] Starting...")
                try:
                    output = self.tasks[task_id]() or {}
                    t_end  = datetime.utcnow()
                    dur    = (t_end - t_start).total_seconds()
                    self.results[task_id] = TaskResult(
                        task_id=task_id, status="SUCCESS",
                        start_time=t_start.isoformat(),
                        end_time=t_end.isoformat(),
                        duration_s=round(dur, 2),
                        output=output if isinstance(output, dict) else {},
                    )
                    logger.info(f"[{task_id}] ✅ SUCCESS in {dur:.2f}s")
                except Exception as e:
                    t_end = datetime.utcnow()
                    dur   = (t_end - t_start).total_seconds()
                    err   = traceback.format_exc()
                    self.results[task_id] = TaskResult(
                        task_id=task_id, status="FAILED",
                        start_time=t_start.isoformat(),
                        end_time=t_end.isoformat(),
                        duration_s=round(dur, 2),
                        error=str(e),
                    )
                    logger.error(f"[{task_id}] ❌ FAILED: {e}\n{err}")

                remaining.remove(task_id)
                progress = True

            if not progress:
                logger.error("Circular dependency or unresolvable DAG — aborting")
                break

        # Run summary
        total_dur   = (datetime.utcnow() - run_start).total_seconds()
        success_cnt = sum(1 for r in self.results.values() if r.status == "SUCCESS")
        failed_cnt  = sum(1 for r in self.results.values() if r.status == "FAILED")
        skipped_cnt = sum(1 for r in self.results.values() if r.status == "SKIPPED")

        summary = {
            "dag_id":      self.dag_id,
            "run_id":      run_id,
            "status":      "SUCCESS" if failed_cnt == 0 else "PARTIAL_FAILURE",
            "total_tasks": len(self.tasks),
            "succeeded":   success_cnt,
            "failed":      failed_cnt,
            "skipped":     skipped_cnt,
            "duration_s":  round(total_dur, 2),
            "task_results": {
                tid: {
                    "status":     r.status,
                    "duration_s": r.duration_s,
                    "error":      r.error,
                }
                for tid, r in self.results.items()
            },
        }

        # Persist run log
        log_path = LOG_DIR / f"dag_run_{run_id}.json"
        with open(log_path, "w") as f:
            json.dump(summary, f, indent=2)

        logger.info(f"{'='*60}")
        logger.info(
            f"DAG complete | status={summary['status']} | "
            f"✅{success_cnt} ❌{failed_cnt} ⏭{skipped_cnt} | "
            f"total={total_dur:.2f}s"
        )
        logger.info(f"Run log → {log_path}")
        logger.info(f"{'='*60}")
        return summary


# ── Build the RecoMart pipeline DAG ──────────────────────────────────────────
def build_recomart_dag() -> DAGRunner:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    # Shared context passed between tasks via closure
    ctx = {}

    dag = DAGRunner(
        dag_id="recomart_full_pipeline",
        description="End-to-end data + ML pipeline for RecoMart recommendation system"
    )

    # ── Task 1: Ingest interactions ───────────────────────────────────────────
    def t_ingest_interactions():
        ctx["df_int_raw"] = generate_sample_interactions(2000)
        logger.info(f"Ingested {len(ctx['df_int_raw'])} interaction rows")
        return {"rows": len(ctx["df_int_raw"])}

    # ── Task 2: Ingest products ───────────────────────────────────────────────
    def t_ingest_products():
        ctx["df_prod_raw"] = pd.DataFrame(_generate_synthetic_products(500))
        logger.info(f"Ingested {len(ctx['df_prod_raw'])} product rows")
        return {"rows": len(ctx["df_prod_raw"])}

    # ── Task 3: Validate interactions ─────────────────────────────────────────
    def t_validate_interactions():
        s = validate_interactions(ctx["df_int_raw"])
        ctx["val_summary_int"] = s
        logger.info(f"Interaction validation: {s['pass_rate']} pass rate")
        if s["failed"] > 0:
            logger.warning(f"{s['failed']} validation rules failed — proceeding with cleaning")
        return {"pass_rate": s["pass_rate"], "failed": s["failed"]}

    # ── Task 4: Validate products ──────────────────────────────────────────────
    def t_validate_products():
        s = validate_products(ctx["df_prod_raw"])
        ctx["val_summary_prod"] = s
        p_int  = profile_dataframe(ctx["df_int_raw"],  "interactions")
        p_prod = profile_dataframe(ctx["df_prod_raw"], "products")
        write_quality_report(
            [ctx.get("val_summary_int", s), s],
            [p_int, p_prod]
        )
        return {"pass_rate": s["pass_rate"]}

    # ── Task 5: Prepare interactions ──────────────────────────────────────────
    def t_prepare_interactions():
        ctx["df_int_clean"] = clean_interactions(ctx["df_int_raw"])
        save_processed(ctx["df_int_clean"], "interactions_clean")
        return {"rows": len(ctx["df_int_clean"])}

    # ── Task 6: Prepare products ──────────────────────────────────────────────
    def t_prepare_products():
        df_clean          = clean_products(ctx["df_prod_raw"])
        df_enc, encoders  = encode_products(df_clean)
        ctx["df_prod_enc"]   = df_enc
        ctx["encoders"]      = encoders
        save_processed(df_enc, "products_encoded")
        return {"rows": len(df_enc)}

    # ── Task 7: Feature engineering ───────────────────────────────────────────
    def t_feature_engineering():
        ctx["user_f"]    = build_user_features(ctx["df_int_clean"])
        ctx["item_f"]    = build_item_features(ctx["df_int_clean"], ctx["df_prod_enc"])
        ctx["inter_f"]   = build_interaction_features(ctx["df_int_clean"])
        ctx["cooccur_f"] = build_cooccurrence(ctx["df_int_clean"])
        conn = init_db(DB_PATH)
        save_features_to_db(conn, ctx["user_f"], ctx["item_f"], ctx["inter_f"], ctx["cooccur_f"])
        conn.close()
        return {
            "user_features": len(ctx["user_f"]),
            "item_features": len(ctx["item_f"]),
        }

    # ── Task 8: Feature store write ───────────────────────────────────────────
    def t_feature_store():
        fs = FeatureStore()
        fs.write("user_features", ctx["user_f"], USER_FEATURE_DEFS,
                 source="interactions_csv",
                 description="User engagement features",
                 entity="user_id")
        fs.write("item_features", ctx["item_f"], ITEM_FEATURE_DEFS,
                 source="interactions+products",
                 description="Item popularity and catalogue features",
                 entity="item_id")
        fs.write("interaction_features", ctx["inter_f"], INTERACTION_FEATURE_DEFS,
                 source="interactions_csv",
                 description="Interaction context features",
                 entity="user_id+item_id")
        return {"groups_written": 3}

    # ── Task 9: Train SVD model ───────────────────────────────────────────────
    def t_train_svd():
        run = train_svd_model(ctx["df_int_clean"], n_components=50, k=10)
        ctx["svd_run"] = run
        return {"metrics": run["metrics"]}

    # ── Task 10: Train content-based model ────────────────────────────────────
    def t_train_content():
        run = train_content_model(ctx["df_int_clean"], ctx["item_f"])
        ctx["cb_run"] = run
        return {"metrics": run["metrics"]}

    # ── Register tasks with dependencies ─────────────────────────────────────
    dag.register("ingest_interactions",     t_ingest_interactions)
    dag.register("ingest_products",         t_ingest_products)
    dag.register("validate_interactions",   t_validate_interactions,  ["ingest_interactions"])
    dag.register("validate_products",       t_validate_products,      ["ingest_products"])
    dag.register("prepare_interactions",    t_prepare_interactions,   ["validate_interactions"])
    dag.register("prepare_products",        t_prepare_products,       ["validate_products"])
    dag.register("feature_engineering",     t_feature_engineering,    ["prepare_interactions", "prepare_products"])
    dag.register("feature_store",           t_feature_store,          ["feature_engineering"])
    dag.register("train_svd",               t_train_svd,              ["feature_store"])
    dag.register("train_content",           t_train_content,          ["feature_store"])

    return dag


# ── Airflow DAG definition (used when imported by Airflow) ───────────────────
try:
    from airflow import DAG
    from airflow.operators.python import PythonOperator

    with DAG(
        dag_id="recomart_pipeline",
        description="RecoMart end-to-end data + ML pipeline",
        schedule_interval="@daily",
        start_date=datetime(2024, 1, 1),
        catchup=False,
        default_args={
            "retries": 2,
            "retry_delay": timedelta(minutes=5),
        },
        tags=["recomart", "ml", "data-pipeline"],
    ) as airflow_dag:
        pass  # Tasks would be added here for full Airflow deployment

except ImportError:
    airflow_dag = None  # Airflow not installed — standalone mode


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    dag     = build_recomart_dag()
    summary = dag.run()

    print("\n" + "=" * 60)
    print("PIPELINE EXECUTION SUMMARY")
    print("=" * 60)
    print(f"DAG:      {summary['dag_id']}")
    print(f"Status:   {summary['status']}")
    print(f"Duration: {summary['duration_s']}s")
    print(f"Tasks:    ✅{summary['succeeded']}  ❌{summary['failed']}  ⏭{summary['skipped']}")
    print("\nTask breakdown:")
    for tid, r in summary["task_results"].items():
        icon = "✅" if r["status"] == "SUCCESS" else ("❌" if r["status"] == "FAILED" else "⏭")
        print(f"  {icon}  {tid:<35} {r['duration_s']}s")
    if summary["failed"] > 0:
        print("\nFailed tasks:")
        for tid, r in summary["task_results"].items():
            if r["status"] == "FAILED":
                print(f"  ❌ {tid}: {r['error']}")
