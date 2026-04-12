# RecoMart - Data Versioning with DVC (Task 8)
# ================================================
# Run these commands in order to set up data versioning

# 1. Initialize DVC in the project
dvc init

# 2. Track raw data directories
dvc add data/raw/interactions/
dvc add data/raw/products/
dvc add data/processed/

# 3. Set remote storage (local filesystem as example)
dvc remote add -d local_remote /tmp/recomart_dvc_remote
# For cloud: dvc remote add -d s3_remote s3://your-bucket/recomart

# 4. Commit .dvc files to Git
git add data/raw/interactions/.gitignore data/raw/interactions.dvc
git add data/raw/products/.gitignore data/raw/products.dvc
git add data/processed/.gitignore data/processed.dvc
git add .dvc/config
git commit -m "feat: add DVC tracking for raw and processed data"

# 5. Push data to remote
dvc push

# ── Versioning workflow ──────────────────────────────────────────────────────
# After a new pipeline run, update tracked data:
#   dvc add data/processed/
#   git add data/processed.dvc
#   git commit -m "data: update processed dataset v2 - added 500 new interactions"
#   dvc push

# Reproducing a past version:
#   git checkout <commit-hash> -- data/processed.dvc
#   dvc pull

# ── Pipeline stages (dvc.yaml) ────────────────────────────────────────────────
# stages:
#   ingest:
#     cmd: python src/ingestion/ingest_interactions.py
#     deps: []
#     outs: [data/raw/interactions/]
#
#   validate:
#     cmd: python src/validation/validate_data.py
#     deps: [data/raw/interactions/, data/raw/products/]
#     outs: [docs/data_quality_report.txt]
#
#   prepare:
#     cmd: python src/preparation/prepare_data.py
#     deps: [data/raw/]
#     outs: [data/processed/]
#
#   features:
#     cmd: python src/features/feature_engineering.py
#     deps: [data/processed/]
#     outs: [data/recomart.db, feature_store/]
#
#   train:
#     cmd: python src/training/train_model.py
#     deps: [feature_store/]
#     outs: [models/]
#     metrics: [models/mlflow_runs/]
