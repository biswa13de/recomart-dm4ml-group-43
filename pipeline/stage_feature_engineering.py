import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import glob
import pandas as pd
from features.feature_engineering import (
    build_user_features, build_item_features,
    build_interaction_features, build_cooccurrence,
    init_db, save_features_to_db,
)

int_files  = sorted(glob.glob("data/processed/interactions_clean_*.csv"))
prod_files = sorted(glob.glob("data/processed/products_encoded_*.csv"))

df_int  = pd.read_csv(int_files[-1])
df_prod = pd.read_csv(prod_files[-1])

uf   = build_user_features(df_int)
itf  = build_item_features(df_int, df_prod)
intf = build_interaction_features(df_int)
co   = build_cooccurrence(df_int)

conn = init_db(Path("data/recomart.db"))
save_features_to_db(conn, uf, itf, intf, co)

print(f"Features: users={len(uf)} items={len(itf)} interactions={len(intf)} cooccurrence={len(co)}")
