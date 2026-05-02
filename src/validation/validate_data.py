"""
RecoMart Data Pipeline - Task 4: Data Profiling & Validation
Applies schema, range, duplicate, and completeness checks.
Generates a structured Data Quality Report.
"""

import logging
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "validation.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("data_validator")

DOCS_DIR = Path(__file__).resolve().parents[2] / "docs"
DOCS_DIR.mkdir(exist_ok=True)


# ── Validation rule engine ────────────────────────────────────────────────────
class DataValidator:
    def __init__(self, name: str, df: pd.DataFrame):
        self.name    = name
        self.df      = df.copy()
        self.results = []
        self.passed  = 0
        self.failed  = 0

    def _record(self, rule: str, passed: bool, detail: str):
        status = "PASS" if passed else "FAIL"
        icon   = "✅" if passed else "❌"
        self.results.append({"rule": rule, "status": status, "detail": detail})
        if passed:
            self.passed += 1
        else:
            self.failed += 1
        logger.info(f"[{self.name}] {icon} {rule}: {detail}")

    # ── Individual rules ──────────────────────────────────────────────────────
    def check_not_empty(self):
        passed = len(self.df) > 0
        self._record("not_empty", passed, f"{len(self.df)} rows found")

    def check_required_columns(self, columns: list[str]):
        missing = [c for c in columns if c not in self.df.columns]
        passed  = len(missing) == 0
        self._record(
            "required_columns", passed,
            f"All present" if passed else f"Missing: {missing}"
        )

    def check_no_nulls(self, columns: list[str]):
        for col in columns:
            if col not in self.df.columns:
                continue
            null_n = self.df[col].isnull().sum()
            pct    = null_n / len(self.df) * 100
            self._record(
                f"no_nulls:{col}",
                null_n == 0,
                f"{null_n} nulls ({pct:.1f}%)"
            )

    def check_no_duplicates(self, subset: list[str]):
        valid_cols = [c for c in subset if c in self.df.columns]
        if not valid_cols:
            return
        dup_n  = self.df.duplicated(subset=valid_cols).sum()
        self._record(
            f"no_duplicates:{'+'.join(valid_cols)}",
            dup_n == 0,
            f"{dup_n} duplicate rows"
        )

    def check_value_range(self, col: str, min_val: float, max_val: float):
        if col not in self.df.columns:
            return
        out = ((self.df[col] < min_val) | (self.df[col] > max_val)).sum()
        self._record(
            f"range:{col}[{min_val},{max_val}]",
            out == 0,
            f"{out} out-of-range values"
        )

    def check_positive_values(self, col: str):
        if col not in self.df.columns:
            return
        neg = (self.df[col] <= 0).sum()
        self._record(
            f"positive:{col}",
            neg == 0,
            f"{neg} non-positive values"
        )

    def check_referential_integrity(self, col: str, valid_set: set, label: str):
        if col not in self.df.columns:
            return
        invalid = (~self.df[col].isin(valid_set)).sum()
        self._record(
            f"ref_integrity:{col}→{label}",
            invalid == 0,
            f"{invalid} unmatched foreign keys"
        )

    def check_date_format(self, col: str, fmt: str = "%Y-%m-%d %H:%M:%S"):
        if col not in self.df.columns:
            return
        try:
            pd.to_datetime(self.df[col], format=fmt)
            self._record(f"date_format:{col}", True, "All dates valid")
        except Exception:
            try:
                bad = pd.to_datetime(self.df[col], errors="coerce").isnull().sum()
                self._record(f"date_format:{col}", bad == 0, f"{bad} unparseable dates")
            except Exception as e:
                self._record(f"date_format:{col}", False, str(e))

    # ── Summary ───────────────────────────────────────────────────────────────
    def summary(self) -> dict:
        total = self.passed + self.failed
        return {
            "dataset":    self.name,
            "rows":       len(self.df),
            "cols":       len(self.df.columns),
            "rules_run":  total,
            "passed":     self.passed,
            "failed":     self.failed,
            "pass_rate":  f"{self.passed / total * 100:.1f}%" if total else "N/A",
            "results":    self.results,
        }


# ── Profile generator ─────────────────────────────────────────────────────────
def profile_dataframe(df: pd.DataFrame, name: str) -> dict:
    profile = {"dataset": name, "shape": df.shape}
    stats = {}
    for col in df.columns:
        s = df[col]
        entry = {
            "dtype":    str(s.dtype),
            "nulls":    int(s.isnull().sum()),
            "null_pct": f"{s.isnull().mean()*100:.1f}%",
            "unique":   int(s.nunique()),
        }
        if pd.api.types.is_numeric_dtype(s):
            entry.update({
                "min":    round(float(s.min()), 3),
                "max":    round(float(s.max()), 3),
                "mean":   round(float(s.mean()), 3),
                "std":    round(float(s.std()), 3),
                "median": round(float(s.median()), 3),
            })
        else:
            top = s.value_counts().head(3).to_dict()
            entry["top_values"] = {str(k): int(v) for k, v in top.items()}
        stats[col] = entry
    profile["column_stats"] = stats
    return profile


# ── Main validation runner ────────────────────────────────────────────────────
def validate_interactions(df: pd.DataFrame) -> dict:
    v = DataValidator("interactions", df)
    v.check_not_empty()
    v.check_required_columns(["user_id", "item_id", "rating", "timestamp"])
    v.check_no_nulls(["user_id", "item_id", "rating", "timestamp"])
    v.check_no_duplicates(["user_id", "item_id", "timestamp"])
    v.check_value_range("rating", 1.0, 5.0)
    v.check_positive_values("user_id")
    v.check_positive_values("item_id")
    v.check_date_format("timestamp")
    return v.summary()


def validate_products(df: pd.DataFrame) -> dict:
    v = DataValidator("products", df)
    v.check_not_empty()
    v.check_required_columns(["item_id", "title", "category", "price"])
    v.check_no_nulls(["item_id", "title", "category", "price"])
    v.check_no_duplicates(["item_id"])
    v.check_positive_values("price")
    v.check_value_range("rating", 0.0, 5.0)
    return v.summary()


# ── Text report writer ────────────────────────────────────────────────────────
def write_quality_report(summaries: list[dict], profiles: list[dict]):
    ts        = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    out_path  = DOCS_DIR / "data_quality_report.txt"

    lines = [
        "=" * 70,
        "  RECOMART DATA QUALITY REPORT",
        f"  Generated: {ts}",
        "=" * 70,
        "",
    ]

    for s in summaries:
        lines += [
            f"── Dataset: {s['dataset'].upper()} ──",
            f"   Rows: {s['rows']}  |  Columns: {s['cols']}",
            f"   Rules run: {s['rules_run']}  |  Passed: {s['passed']}  |  Failed: {s['failed']}",
            f"   Pass rate: {s['pass_rate']}",
            "",
            "   Validation Results:",
        ]
        for r in s["results"]:
            icon = "✅" if r["status"] == "PASS" else "❌"
            lines.append(f"     {icon}  {r['rule']:<45} {r['detail']}")
        lines.append("")

    lines += ["=" * 70, "  COLUMN PROFILES", "=" * 70, ""]
    for p in profiles:
        lines.append(f"── {p['dataset'].upper()} ({p['shape'][0]} rows × {p['shape'][1]} cols) ──")
        for col, st in p["column_stats"].items():
            lines.append(f"   {col} ({st['dtype']}):")
            lines.append(f"     nulls={st['nulls']} ({st['null_pct']})  unique={st['unique']}")
            if "mean" in st:
                lines.append(f"     min={st['min']}  max={st['max']}  mean={st['mean']}  std={st['std']}")
            elif "top_values" in st:
                lines.append(f"     top values: {st['top_values']}")
        lines.append("")

    with open(out_path, "w") as f:
        f.write("\n".join(lines))

    logger.info(f"Data Quality Report saved → {out_path}")
    return str(out_path)


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from ingestion.ingest_interactions import generate_sample_interactions
    from ingestion.ingest_products_api  import _generate_synthetic_products
    from validation.ge_validation       import run_ge_validation

    logger.info("Running data validation pipeline...")

    df_int  = generate_sample_interactions(2000)
    df_prod = pd.DataFrame(_generate_synthetic_products(500))

    # ── 1. Great Expectations validation ─────────────────────────────────────
    logger.info("=== Great Expectations Validation ===")
    ge_results = run_ge_validation(df_int, df_prod)
    for ds in ("interactions", "products"):
        r = ge_results[ds]
        status = "PASS" if r["success"] else "FAIL"
        logger.info("[GE] %-15s [%s] %d/%d (%.1f%%)", ds, status, r["passed"], r["evaluated"], r["pass_pct"])
    if ge_results.get("html_report"):
        logger.info("[GE] Data Docs → %s", ge_results["html_report"])

    # ── 2. Custom rule-engine validation (with deliberate errors) ─────────────
    logger.info("=== Custom Validator (with injected errors) ===")
    df_int_err  = df_int.copy()
    df_prod_err = df_prod.copy()
    df_int_err.loc[0, "rating"]  = 6.5
    df_int_err.loc[1, "user_id"] = None
    df_prod_err.loc[0, "price"]  = -10.0

    s_int  = validate_interactions(df_int_err)
    s_prod = validate_products(df_prod_err)

    p_int  = profile_dataframe(df_int,  "interactions")
    p_prod = profile_dataframe(df_prod, "products")

    report_path = write_quality_report([s_int, s_prod], [p_int, p_prod])
    print(f"\nCustom Quality Report : {report_path}")
    print(f"GE HTML Report        : {ge_results.get('html_report', 'N/A')}")
    print(f"Interactions — pass rate : {s_int['pass_rate']}")
    print(f"Products      — pass rate : {s_prod['pass_rate']}")
