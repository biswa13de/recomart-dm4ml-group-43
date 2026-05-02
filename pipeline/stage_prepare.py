import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd
from preparation.prepare_data import clean_interactions, clean_products, encode_products, save_processed

df_int  = pd.read_csv("data/raw/interactions/interactions_latest.csv")
df_prod = pd.read_csv("data/raw/products/products_latest.csv")

df_int_clean          = clean_interactions(df_int)
df_prod_clean, _      = encode_products(clean_products(df_prod))

save_processed(df_int_clean,  "interactions_clean")
save_processed(df_prod_clean, "products_encoded")

print(f"Prepared: {len(df_int_clean)} interactions, {len(df_prod_clean)} products")
