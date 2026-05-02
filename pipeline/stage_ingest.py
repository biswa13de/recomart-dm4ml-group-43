import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd
from ingestion.ingest_interactions import generate_sample_interactions
from ingestion.ingest_products_api import _generate_synthetic_products

Path("data/raw/interactions").mkdir(parents=True, exist_ok=True)
Path("data/raw/products").mkdir(parents=True, exist_ok=True)

df_int  = generate_sample_interactions(2000)
df_prod = pd.DataFrame(_generate_synthetic_products(500))

df_int.to_csv("data/raw/interactions/interactions_latest.csv",  index=False)
df_prod.to_csv("data/raw/products/products_latest.csv",          index=False)

print(f"Ingested {len(df_int)} interactions, {len(df_prod)} products")
