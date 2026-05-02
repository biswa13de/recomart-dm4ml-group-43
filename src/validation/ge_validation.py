"""
RecoMart - Task 4: Data Validation using Great Expectations
Defines expectation suites for interactions and products datasets.
Generates HTML Data Docs at great_expectations/uncommitted/data_docs/
"""

import logging
import pandas as pd
from pathlib import Path

logger  = logging.getLogger("ge_validator")
ROOT_DIR = Path(__file__).resolve().parents[2]


# ── Expectation suites ────────────────────────────────────────────────────────

def _interactions_expectations(validator) -> None:
    # Row count
    validator.expect_table_row_count_to_be_between(min_value=100)

    # Required columns present
    validator.expect_table_columns_to_match_set(
        column_set=["user_id", "item_id", "rating", "timestamp"],
        exact_match=False,
    )

    # Completeness
    for col in ["user_id", "item_id", "rating", "timestamp"]:
        validator.expect_column_values_to_not_be_null(col)

    # Domain: rating must be 1–5
    validator.expect_column_values_to_be_between(
        "rating", min_value=1.0, max_value=5.0
    )

    # IDs must be positive integers
    validator.expect_column_min_to_be_between("user_id", min_value=1)
    validator.expect_column_min_to_be_between("item_id", min_value=1)

    # No duplicate (user, item, timestamp) triplets
    validator.expect_compound_columns_to_be_unique(
        column_list=["user_id", "item_id", "timestamp"]
    )

    # Timestamp format
    validator.expect_column_values_to_match_strftime_format(
        "timestamp", strftime_format="%Y-%m-%d %H:%M:%S"
    )

    # Event type whitelist (optional column — catch_exceptions=True skips if absent)
    validator.expect_column_values_to_be_in_set(
        "event_type",
        value_set=["view", "purchase", "wishlist", "cart"],
        catch_exceptions=True,
    )


def _products_expectations(validator) -> None:
    # Row count
    validator.expect_table_row_count_to_be_between(min_value=10)

    # Required columns
    validator.expect_table_columns_to_match_set(
        column_set=["item_id", "title", "category", "price"],
        exact_match=False,
    )

    # Completeness
    for col in ["item_id", "title", "category", "price"]:
        validator.expect_column_values_to_not_be_null(col)

    # item_id must be unique
    validator.expect_column_values_to_be_unique("item_id")

    # Price must be positive
    validator.expect_column_values_to_be_between("price", min_value=0.01)

    # Category whitelist
    validator.expect_column_values_to_be_in_set(
        "category",
        value_set=["electronics", "clothing", "home", "books", "sports", "beauty"],
    )

    # Product rating 0–5 (optional column)
    validator.expect_column_values_to_be_between(
        "rating", min_value=0.0, max_value=5.0, catch_exceptions=True
    )


# ── Main runner ───────────────────────────────────────────────────────────────

def run_ge_validation(
    df_interactions: pd.DataFrame,
    df_products: pd.DataFrame,
) -> dict:
    """
    Run Great Expectations validation on both datasets.
    Generates HTML Data Docs and returns a summary dict.
    """
    import great_expectations as gx

    context = gx.get_context(project_root_dir=str(ROOT_DIR))
    datasource = context.sources.add_or_update_pandas("recomart_pandas")

    summary = {}

    for name, df, builder in [
        ("interactions", df_interactions, _interactions_expectations),
        ("products",     df_products,     _products_expectations),
    ]:
        asset     = datasource.add_dataframe_asset(name=f"{name}_asset")
        batch_req = asset.build_batch_request(dataframe=df)

        suite_name = f"{name}_suite"
        context.add_or_update_expectation_suite(suite_name)

        validator = context.get_validator(
            batch_request=batch_req,
            expectation_suite_name=suite_name,
        )
        builder(validator)
        validator.save_expectation_suite(discard_failed_expectations=False)

        result = validator.validate()
        stats  = result["statistics"]

        passed  = stats["successful_expectations"]
        total   = stats["evaluated_expectations"]
        pct     = round(stats["success_percent"] or 0.0, 1)

        summary[name] = {
            "success":   result.success,
            "evaluated": total,
            "passed":    passed,
            "failed":    stats["unsuccessful_expectations"],
            "pass_pct":  pct,
            "results":   [
                {
                    "expectation": r["expectation_config"]["expectation_type"],
                    "kwargs":      r["expectation_config"]["kwargs"],
                    "success":     r["success"],
                    "result":      r.get("result", {}),
                }
                for r in result["results"]
            ],
        }

        logger.info(
            "[GE] %-15s %d/%d expectations passed (%.1f%%)",
            name, passed, total, pct,
        )

    # Build HTML Data Docs
    try:
        docs_urls = context.build_data_docs()
        html_path = list(docs_urls.values())[0] if docs_urls else ""
        summary["html_report"] = html_path
        logger.info("[GE] Data Docs → %s", html_path)
    except Exception as exc:
        logger.warning("[GE] Could not build data docs: %s", exc)
        summary["html_report"] = ""

    return summary


def write_text_report(summary: dict) -> str:
    """Write a plain-text quality report from GE summary to docs/data_quality_report.txt."""
    from datetime import datetime
    DOCS_DIR = ROOT_DIR / "docs"
    DOCS_DIR.mkdir(exist_ok=True)
    out_path = DOCS_DIR / "data_quality_report.txt"
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = [
        "=" * 70,
        "  RECOMART DATA QUALITY REPORT (Great Expectations)",
        f"  Generated: {ts}",
        "=" * 70, "",
    ]
    for ds in ("interactions", "products"):
        if ds not in summary:
            continue
        r = summary[ds]
        status = "PASS" if r["success"] else "FAIL"
        lines += [
            f"── Dataset: {ds.upper()} [{status}] ──",
            f"   Expectations: {r['passed']}/{r['evaluated']} passed ({r['pass_pct']}%)",
            "",
            "   Results:",
        ]
        for exp in r.get("results", []):
            icon = "✅" if exp["success"] else "❌"
            lines.append(f"     {icon}  {exp['expectation']}")
        lines.append("")
    if summary.get("html_report"):
        lines += [f"HTML Data Docs → {summary['html_report']}", ""]
    with open(out_path, "w") as f:
        f.write("\n".join(lines))
    logger.info("Text report → %s", out_path)
    return str(out_path)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(ROOT_DIR / "src"))

    from ingestion.ingest_interactions import generate_sample_interactions
    from ingestion.ingest_products_api  import _generate_synthetic_products

    df_int  = generate_sample_interactions(2000)
    df_prod = pd.DataFrame(_generate_synthetic_products(500))

    results = run_ge_validation(df_int, df_prod)

    for dataset in ("interactions", "products"):
        r = results[dataset]
        status = "PASS" if r["success"] else "FAIL"
        print(f"{dataset:15} [{status}]  {r['passed']}/{r['evaluated']} ({r['pass_pct']}%)")

    if results.get("html_report"):
        print(f"\nData Docs → {results['html_report']}")
