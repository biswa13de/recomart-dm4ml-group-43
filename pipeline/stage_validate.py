import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd
from validation.ge_validation import run_ge_validation, write_text_report

df_int  = pd.read_csv("data/raw/interactions/interactions_latest.csv")
df_prod = pd.read_csv("data/raw/products/products_latest.csv")

summary = run_ge_validation(df_int, df_prod)
write_text_report(summary)

for ds in ("interactions", "products"):
    r = summary[ds]
    status = "PASS" if r["success"] else "FAIL"
    print(f"{ds:15} [{status}]  {r['passed']}/{r['evaluated']} ({r['pass_pct']}%)")
