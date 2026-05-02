import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import glob
import pickle
import pandas as pd
from training.train_model import SVDRecommender, ContentBasedRecommender, ExperimentTracker

int_files  = sorted(glob.glob("data/processed/interactions_clean_*.csv"))
prod_files = sorted(glob.glob("data/processed/products_encoded_*.csv"))

df_int  = pd.read_csv(int_files[-1])
df_prod = pd.read_csv(prod_files[-1])

Path("models").mkdir(exist_ok=True)

svd = SVDRecommender()
svd.fit(df_int)
pickle.dump(svd, open("models/svd_model.pkl", "wb"))
print(f"SVD trained — explained_variance={svd.svd.explained_variance_ratio_.sum():.4f}")

cb = ContentBasedRecommender()
cb.fit(df_prod, feature_cols=["price_normalized", "category_encoded", "popularity_score", "avg_rating_received", "total_interactions"])
pickle.dump(cb, open("models/content_model.pkl", "wb"))
print("Content-based model trained and saved")
