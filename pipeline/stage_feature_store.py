import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import sqlite3
import pandas as pd
from features.feature_store import FeatureStore

conn = sqlite3.connect("data/recomart.db")
fs   = FeatureStore()

groups = [
    ("user_features",        "user_features",        "user_id",          "User activity and engagement features"),
    ("item_features",        "item_features",        "item_id",          "Item popularity and metadata features"),
    ("interaction_features", "interaction_features", "user_id+item_id",  "User-item interaction features"),
]

for table, group, entity, description in groups:
    df = pd.read_sql(f"SELECT * FROM {table}", conn)
    feature_defs = [{"name": c, "dtype": str(df[c].dtype), "description": c} for c in df.columns]
    fs.write(group, df, feature_defs=feature_defs, source="recomart.db", description=description, entity=entity)
    print(f"Wrote {group}: {len(df)} rows")

conn.close()
