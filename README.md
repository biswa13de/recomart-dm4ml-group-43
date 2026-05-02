# RecoMart — End-to-End Data Management Pipeline

A complete DM4ML (Data Management for Machine Learning) pipeline for a product recommendation system. Covers ingestion, validation, preparation, feature engineering, feature store, model training, data versioning, and orchestration.

---

## Quick Start

### 1. Clone and set up the virtual environment

```bash
git clone <repo-url>
cd recomart

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

### 2. Add `src/` to the Python path (one-time)

```bash
echo "$(pwd)/src" > .venv/lib/python3.*/site-packages/recomart.pth
```

### 3. Run the full pipeline (standalone, no Airflow needed)

```bash
python src/orchestration/pipeline_dag.py
```

Expected output:
```
DAG: recomart_full_pipeline  |  Status: SUCCESS
Tasks: ✅10  ❌0  ⏭0  |  Duration: ~5s
```

---

## Project Structure

```
recomart/
├── src/
│   ├── ingestion/
│   │   ├── ingest_interactions.py     # Task 2 — CSV user interaction ingestion
│   │   └── ingest_products_api.py     # Task 2 — REST API product ingestion
│   ├── validation/
│   │   └── ge_validation.py           # Task 4 — Great Expectations suites + HTML Data Docs
│   ├── preparation/
│   │   └── prepare_data.py            # Task 5 — Cleaning, encoding, EDA
│   ├── features/
│   │   ├── feature_engineering.py     # Task 6 — Feature tables + SQLite
│   │   └── feature_store.py           # Task 7 — Versioned feature store
│   ├── training/
│   │   └── train_model.py             # Task 9 — SVD + Content-based models
│   └── orchestration/
│       └── pipeline_dag.py            # Task 10 — DAGRunner (standalone)
│
├── airflow/
│   └── dags/
│       └── recomart_pipeline.py       # Task 10 — Apache Airflow 3.x DAG
│
├── notebooks/
│   └── eda_analysis.ipynb             # Task 5 — EDA plots (7 charts)
│
├── data/
│   ├── raw/                           # Timestamped raw ingestion files
│   │   ├── interactions/              # interactions_YYYYMMDD_HHMMSS.csv
│   │   └── products/                 # products_raw_*.json + products_*.csv
│   ├── processed/                     # Cleaned + encoded CSVs
│   └── recomart.db                    # SQLite feature database
│
├── feature_store/
│   ├── feature_registry.json          # Feature metadata & version index
│   ├── user_features/v.../            # Versioned user feature Parquet files
│   ├── item_features/v.../            # Versioned item feature Parquet files
│   └── interaction_features/v.../     # Versioned interaction Parquet files
│
├── models/
│   ├── svd_model.pkl                  # Latest SVD collaborative filter
│   ├── content_model.pkl              # Latest content-based model
│   └── mlflow_runs/                   # MLflow-compatible run JSONs + artifacts
│
├── pipeline/                          # DVC stage entry-point scripts
│   ├── stage_ingest.py                #   Stage 1 — ingest
│   ├── stage_validate.py              #   Stage 2 — validate (GE + custom)
│   ├── stage_prepare.py               #   Stage 3 — prepare
│   ├── stage_feature_engineering.py   #   Stage 4 — feature engineering
│   ├── stage_feature_store.py         #   Stage 5 — feature store
│   └── stage_train.py                 #   Stage 6 — train
│
├── gx/                                # Great Expectations context
│   ├── great_expectations.yml         #   GE datasource + store config
│   ├── expectations/
│   │   ├── interactions_suite.json    #   12 expectations for interactions
│   │   └── products_suite.json        #   10 expectations for products
│   └── uncommitted/data_docs/         #   HTML Data Docs (gitignored)
│
├── docs/
│   ├── RecoMart_DM4ML_Assignment_Report.pdf   # Full assignment report
│   └── plots/                                 # EDA charts (PNG)
│
├── logs/                              # Per-module log files + DAG run JSONs
├── dvc.yaml                           # DVC pipeline stage definitions
├── dvc.lock                           # DVC pipeline lock file (reproducibility)
├── generate_report.py                 # Generates docs/RecoMart_..._Report.pdf
└── requirements.txt
```

---

## Running Individual Stages

Each module is independently runnable. All scripts auto-generate synthetic data if no source file is provided.

```bash
# Task 2 — Ingestion
python src/ingestion/ingest_interactions.py
python src/ingestion/ingest_products_api.py

# Task 4 — Validation (Great Expectations)
python src/validation/ge_validation.py    # runs GE suites + writes HTML Data Docs + text report

# Task 5 — Data preparation + EDA
python src/preparation/prepare_data.py

# Task 6 — Feature engineering (writes to data/recomart.db)
python src/features/feature_engineering.py

# Task 7 — Feature store (writes versioned Parquet to feature_store/)
python src/features/feature_store.py

# Task 9 — Model training (SVD + content-based)
python src/training/train_model.py

# Task 10 — Full pipeline (standalone)
python src/orchestration/pipeline_dag.py
```

---

## Running the EDA Notebook

```bash
source .venv/bin/activate
jupyter notebook notebooks/eda_analysis.ipynb
```

Generates 7 charts saved to `docs/plots/`:
- Rating distribution histogram
- Item popularity long-tail curve
- User activity distribution
- Event type breakdown (pie + bar)
- Product category distribution + price boxplot
- User-item interaction sparsity heatmap
- Interaction density by day & hour heatmap

---

## Running with Apache Airflow UI

Airflow 3.2.1 is supported. Run the following from the project root:

```bash
source .venv/bin/activate

export AIRFLOW_HOME=$(pwd)/airflow
export PYTHONPATH=$(pwd)/src
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES   # Required on macOS
export no_proxy="*"                               # Required on macOS

airflow standalone
```

Then open **http://localhost:8080** in your browser.

**Credentials** — auto-generated on first run:
```
Username: admin
Password: see airflow/simple_auth_manager_passwords.json.generated
```

The DAG `recomart_full_pipeline` will appear automatically. Click **Trigger DAG** to run it manually. All 10 tasks should show green (success) within ~15 seconds.

> **Note:** On first run, `airflow standalone` creates `airflow/airflow.db` and the credentials file. Do not commit these files.

---

## Data Versioning with DVC

DVC manages the full pipeline via `dvc.yaml` (6 stages). A local remote is pre-configured.

```bash
# Run the full pipeline (reruns only changed stages):
dvc repro

# Push data artifacts to the remote after a run:
dvc push

# Restore a previous data version:
git checkout <commit-hash>
dvc pull

# Visualise the pipeline DAG:
dvc dag
```

The pipeline stages defined in `dvc.yaml`:

| Stage | Script | Key Output |
|---|---|---|
| `ingest` | `pipeline/stage_ingest.py` | `data/raw/**/interactions_latest.csv` |
| `validate` | `pipeline/stage_validate.py` | `docs/data_quality_report.txt` |
| `prepare` | `pipeline/stage_prepare.py` | `data/processed/` |
| `feature_engineering` | `pipeline/stage_feature_engineering.py` | `data/recomart.db` |
| `feature_store` | `pipeline/stage_feature_store.py` | `feature_store/` |
| `train` | `pipeline/stage_train.py` | `models/*.pkl` |

To point DVC at a different remote (e.g. S3):
```bash
dvc remote add -d s3_remote s3://your-bucket/recomart
dvc push
```

---

## Pipeline Architecture

```
ingest_interactions ──┐
                       ├──► validate_interactions ──► prepare_interactions ──┐
ingest_products    ──┘                                                         ├──► feature_engineering
                       └──► validate_products    ──► prepare_products    ──┘
                                                                                    └──► feature_store ──► train_svd
                                                                                                       └──► train_content
```

| Stage | Script | Output |
|---|---|---|
| Ingestion | `ingest_interactions.py`, `ingest_products_api.py` | `data/raw/**` |
| Validation | `validate_data.py`, `ge_validation.py` | `docs/data_quality_report.txt`, GE HTML Data Docs |
| Preparation | `prepare_data.py` | `data/processed/**` |
| Feature Engineering | `feature_engineering.py` | `data/recomart.db` (4 tables) |
| Feature Store | `feature_store.py` | `feature_store/**/features.parquet` |
| Training | `train_model.py` | `models/*.pkl`, `models/mlflow_runs/**` |
| Orchestration | `pipeline_dag.py` / Airflow DAG | `logs/dag_run_*.json` |

---

## Feature Store API

```python
from features.feature_store import FeatureStore

fs = FeatureStore()

# Read latest version of a feature group
user_features = fs.read("user_features")

# Read a specific version (for reproducibility)
user_features = fs.read("user_features", version="v20260408_162710")

# Online inference lookup — fetch features for specific entities
online = fs.get_online_features("user_features", [1, 2, 3], entity_col="user_id")

# List all versions of a feature group
print(fs.list_versions("item_features"))
```

**Available feature groups:**

| Group | Entity | Key Features |
|---|---|---|
| `user_features` | `user_id` | total_interactions, avg_rating_given, activity_score, recency_days, purchase_count |
| `item_features` | `item_id` | popularity_score, avg_rating_received, price_normalized, category_encoded |
| `interaction_features` | `user_id + item_id` | rating, hour_of_day, day_of_week, is_weekend, user_item_gap |

---

## Model Experiment Tracking

Experiments are tracked in `models/mlflow_runs/` in MLflow-compatible JSON format.

```python
from training.train_model import train_svd_model, train_content_model
from preparation.prepare_data import clean_interactions
from ingestion.ingest_interactions import generate_sample_interactions

df = clean_interactions(generate_sample_interactions(2000))
run = train_svd_model(df, n_components=50, k=10)

print(run["run_id"])     # e.g. 20260425_213148_185919
print(run["metrics"])    # precision@10, recall@10, ndcg@10, explained_variance
```

Each run saves:
- `run.json` — parameters, metrics, tags, timing
- `svd_model.pkl` / `content_model.pkl` — serialized model artifact

---

## Generating the PDF Report

```bash
source .venv/bin/activate
python generate_report.py
# Output: docs/RecoMart_DM4ML_Assignment_Report.pdf
```

---

## Dependencies

| Package | Purpose |
|---|---|
| `pandas`, `numpy` | Data manipulation |
| `scikit-learn` | SVD, cosine similarity, encoders, scalers |
| `pyarrow` | Parquet read/write for feature store |
| `requests` | REST API ingestion |
| `matplotlib`, `seaborn` | EDA plots |
| `jupyter` | EDA notebook |
| `great-expectations` | Data validation suites + HTML Data Docs |
| `apache-airflow` | Pipeline orchestration UI |
| `dvc` | Data versioning + pipeline reproducibility |
| `reportlab` | PDF report generation |

Install all at once:
```bash
pip install -r requirements.txt
```

---

## Logs

All stages write structured logs to `logs/`:

| File | Written by |
|---|---|
| `ingestion.log` | Ingestion scripts |
| `validation.log` | Data validator |
| `preparation.log` | Data preparation |
| `features.log` | Feature engineering |
| `feature_store.log` | Feature store writes |
| `training.log` | Model training |
| `orchestration.log` | DAGRunner |
| `dag_run_*.json` | Per-run task breakdown with durations |

---

## Common Issues

**`ModuleNotFoundError: No module named 'ingestion'`**
Add `src/` to the Python path:
```bash
echo "$(pwd)/src" > .venv/lib/python3.*/site-packages/recomart.pth
# or run with:
PYTHONPATH=src python src/orchestration/pipeline_dag.py
```

**Airflow SIGSEGV on macOS**
Set these before starting Airflow:
```bash
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export no_proxy="*"
```

**`Unable to find a usable engine` (parquet)**
```bash
pip install pyarrow
```
