import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd
from validation.validate_data import validate_interactions, validate_products, write_quality_report, profile_dataframe
from validation.ge_validation import run_ge_validation

df_int  = pd.read_csv("data/raw/interactions/interactions_latest.csv")
df_prod = pd.read_csv("data/raw/products/products_latest.csv")

ge = run_ge_validation(df_int, df_prod)
s_int  = validate_interactions(df_int)
s_prod = validate_products(df_prod)
write_quality_report([s_int, s_prod], [profile_dataframe(df_int, "interactions"), profile_dataframe(df_prod, "products")])

print(f"GE interactions: {ge['interactions']['pass_pct']}% | products: {ge['products']['pass_pct']}%")
print(f"Custom rules — interactions: {s_int['pass_rate']} | products: {s_prod['pass_rate']}")
