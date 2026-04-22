import argparse
import json
from pathlib import Path

import pandas as pd


QUALITY_THRESHOLDS = {
    "clean_certainty_min": 80.0,
    "noisy_conflict_min": 5.0,
    "noisy_certainty_max_exclusive": 60.0,
}

OUTPUT_FILES = {
    "summary": "s1b_modern_high_audit_summary.csv",
    "source_buckets": "s1b_modern_high_source_buckets.csv",
    "quality_buckets": "s1b_modern_high_quality_buckets.csv",
    "baseline_vs_expanded": "s1b_modern_high_baseline_vs_expanded.csv",
    "demotion_candidates": "s1b_modern_high_demotion_candidates.csv",
    "report": "s1b_modern_high_audit_report.md",
}


def normalize_origin(value) -> str:
    if value is None or pd.isna(value):
        return "NA"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value).strip()
    if numeric.is_integer():
        return str(int(numeric))
    return str(numeric)


def to_bool_series(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series.fillna(False)
    lowered = series.astype(str).str.strip().str.lower()
    return lowered.isin({"1", "true", "yes", "y", "on"})


def read_final_alerts(path: Path) -> pd.DataFrame:
    cols = [
        "event_id",
        "run_id",
        "prefix",
        "origin_as",
        "as_path_clean",
        "risk_score",
        "risk_bucket",
        "gating_label",
        "augmentation_label",
        "final_alert_label",
        "alert_source_layer",
        "top_contributing_factor",
        "candidate_reasons",
        "missing_origin_or_path",
        "certainty_score",
        "conflict_score",
        "evidence_support_score",
    ]
    df = pd.read_parquet(path, columns=cols)
    df["prefix"] = df["prefix"].fillna("").astype(str)
    df["as_path_clean"] = df["as_path_clean"].fillna("").astype(str)
    df["gating_label"] = df["gating_label"].fillna("").astype(str)
    df["augmentation_label"] = df["augmentation_label"].fillna("").astype(str)
    df["final_alert_label"] = df["final_alert_label"].fillna("").astype(str)
    df["alert_source_layer"] = df["alert_source_layer"].fillna("").astype(str)
    df["top_contributing_factor"] = df["top_contributing_factor"].fillna("").astype(str)
    df["candidate_reasons"] = df["candidate_reasons"].fillna("[]").astype(str)
    df["origin_as_norm"] = df["origin_as"].map(normalize_origin)
    df["missing_origin_or_path"] = to_bool_series(df["missing_origin_or_path"])
    df["certainty_score"] = pd.to_numeric(df["certainty_score"], errors="coerce").fillna(0.0)
    df["conflict_score"] = pd.to_numeric(df["conflict_score"], errors="coerce").fillna(0.0)
    df["risk_score"] = pd.to_numeric(df["risk_score"], errors="coerce").fillna(0.0)
    df["evidence_support_score"] = pd.to_numeric(df["evidence_support_score"], errors="coerce")
    return df


def classify_quality_bucket(df: pd.DataFrame) -> pd.Series:
    clean_mask = (
        (~df["missing_origin_or_path"])
        & (df["conflict_score"] == 0.0)
        & (df["certainty_score"] >= QUALITY_THRESHOLDS["clean_certainty_min"])
    )
    noisy_mask = (
        df["missing_origin_or_path"]
        | (df["conflict_score"] >= QUALITY_THRESHOLDS["noisy_conflict_min"])
        | (df["certainty_score"] < QUALITY_THRESHOLDS["noisy_certainty_max_exclusive"])
    )
    out = pd.Series("fragile-high", index=df.index, dtype="object")
    out.loc[noisy_mask] = "noisy-high"
    out.loc[clean_mask] = "clean-high"
    return out


def add_business_keys(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["strict_key"] = out["prefix"] + "|" + out["origin_as_norm"] + "|" + out["as_path_clean"]
    out["relaxed_key"] = out["prefix"] + "|" + out["origin_as_norm"]
    return out


def group_pct(df: pd.DataFrame, group_cols: list[str], total: int, label: str) -> pd.DataFrame:
    grouped = (
        df.groupby(group_cols, dropna=False)
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
        .reset_index(drop=True)
    )
    grouped["pct_within_high"] = grouped["count"] / total if total else 0.0
    grouped["analysis_view"] = label
    return grouped


def summarize_quality_buckets(high_df: pd.DataFrame) -> pd.DataFrame:
    grouped = (
        high_df.groupby("quality_bucket", dropna=False)
        .agg(
            count=("event_id", "size"),
            pct_within_high=("event_id", lambda s: len(s) / len(high_df) if len(high_df) else 0.0),
            certainty_mean=("certainty_score", "mean"),
            conflict_mean=("conflict_score", "mean"),
            missing_rate=("missing_origin_or_path", "mean"),
            risk_mean=("risk_score", "mean"),
            gating_share=("alert_source_layer", lambda s: (s == "gating_likely_malicious").mean()),
            augmentation_share=("alert_source_layer", lambda s: (s == "augmentation_promoted").mean()),
        )
        .reset_index()
    )
    return grouped.sort_values("count", ascending=False).reset_index(drop=True)


def top_reason_tokens(series: pd.Series, topn: int = 5) -> str:
    counts = {}
    for raw in series.astype(str):
        try:
            values = json.loads(raw)
            if not isinstance(values, list):
                continue
        except Exception:
            continue
        for token in values:
            tok = str(token).strip()
            if tok:
                counts[tok] = counts.get(tok, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:topn]
    return "; ".join(f"{k}:{v}" for k, v in ranked)


def build_comparison_tables(baseline_high: pd.DataFrame, expanded_high: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    baseline_strict = set(baseline_high["strict_key"].dropna().unique().tolist())
    baseline_relaxed = set(baseline_high["relaxed_key"].dropna().unique().tolist())

    expanded = expanded_high.copy()
    expanded["expanded_only_strict"] = ~expanded["strict_key"].isin(baseline_strict)
    expanded["expanded_only_relaxed"] = ~expanded["relaxed_key"].isin(baseline_relaxed)

    summary_rows = [
        {
            "section": "strict_key_counts",
            "metric": "baseline_high_unique_keys",
            "value": int(len(baseline_strict)),
        },
        {
            "section": "strict_key_counts",
            "metric": "expanded_high_unique_keys",
            "value": int(expanded_high["strict_key"].nunique()),
        },
        {
            "section": "strict_key_counts",
            "metric": "expanded_only_high_unique_keys",
            "value": int(expanded.loc[expanded["expanded_only_strict"], "strict_key"].nunique()),
        },
        {
            "section": "relaxed_key_counts",
            "metric": "baseline_high_unique_keys",
            "value": int(len(baseline_relaxed)),
        },
        {
            "section": "relaxed_key_counts",
            "metric": "expanded_high_unique_keys",
            "value": int(expanded_high["relaxed_key"].nunique()),
        },
        {
            "section": "relaxed_key_counts",
            "metric": "expanded_only_high_unique_keys",
            "value": int(expanded.loc[expanded["expanded_only_relaxed"], "relaxed_key"].nunique()),
        },
    ]

    pattern_frames = []
    for view_name, mask_col in [("expanded_only_strict", "expanded_only_strict"), ("expanded_only_relaxed", "expanded_only_relaxed")]:
        subset = expanded[expanded[mask_col]].copy()
        if subset.empty:
            continue
        grouped = (
            subset.groupby(
                [
                    "quality_bucket",
                    "alert_source_layer",
                    "gating_label",
                    "augmentation_label",
                    "top_contributing_factor",
                ],
                dropna=False,
            )
            .agg(
                count=("event_id", "size"),
                pct_within_subset=("event_id", lambda s: len(s) / len(subset)),
                certainty_mean=("certainty_score", "mean"),
                conflict_mean=("conflict_score", "mean"),
                missing_rate=("missing_origin_or_path", "mean"),
                top_candidate_reasons=("candidate_reasons", top_reason_tokens),
            )
            .reset_index()
            .sort_values("count", ascending=False)
            .reset_index(drop=True)
        )
        grouped.insert(0, "section", view_name)
        pattern_frames.append(grouped)

    summary_df = pd.DataFrame(summary_rows)
    patterns_df = pd.concat(pattern_frames, ignore_index=True) if pattern_frames else pd.DataFrame()
    combined = pd.concat([summary_df, patterns_df], ignore_index=True, sort=False)
    return expanded, combined


def build_demotion_candidates(expanded_high: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    noisy = expanded_high[expanded_high["quality_bucket"] == "noisy-high"].copy()
    noisy["demotion_priority_score"] = (
        noisy["missing_origin_or_path"].astype(int) * 3
        + (noisy["conflict_score"] >= QUALITY_THRESHOLDS["noisy_conflict_min"]).astype(int) * 2
        + (noisy["certainty_score"] < QUALITY_THRESHOLDS["noisy_certainty_max_exclusive"]).astype(int) * 2
        + (noisy["alert_source_layer"] == "augmentation_promoted").astype(int) * 2
        + noisy["expanded_only_relaxed"].astype(int) * 2
        + noisy["expanded_only_strict"].astype(int) * 1
    )
    noisy["demotion_priority_tier"] = pd.cut(
        noisy["demotion_priority_score"],
        bins=[-1, 3, 5, 99],
        labels=["monitor", "review-first", "demote-first"],
    ).astype(str)
    noisy = noisy.sort_values(
        [
            "demotion_priority_score",
            "missing_origin_or_path",
            "conflict_score",
            "certainty_score",
        ],
        ascending=[False, False, False, True],
    ).reset_index(drop=True)

    candidate_cols = [
        "event_id",
        "run_id",
        "prefix",
        "origin_as",
        "origin_as_norm",
        "as_path_clean",
        "risk_score",
        "risk_bucket",
        "alert_source_layer",
        "gating_label",
        "augmentation_label",
        "top_contributing_factor",
        "certainty_score",
        "conflict_score",
        "missing_origin_or_path",
        "quality_bucket",
        "expanded_only_strict",
        "expanded_only_relaxed",
        "demotion_priority_score",
        "demotion_priority_tier",
        "candidate_reasons",
    ]
    candidates_df = noisy[candidate_cols].copy()

    summary = (
        noisy.groupby(
            [
                "demotion_priority_tier",
                "alert_source_layer",
                "gating_label",
                "augmentation_label",
                "top_contributing_factor",
            ],
            dropna=False,
        )
        .agg(
            count=("event_id", "size"),
            pct_within_noisy=("event_id", lambda s: len(s) / len(noisy) if len(noisy) else 0.0),
            certainty_mean=("certainty_score", "mean"),
            conflict_mean=("conflict_score", "mean"),
            missing_rate=("missing_origin_or_path", "mean"),
            expanded_only_relaxed_rate=("expanded_only_relaxed", "mean"),
        )
        .reset_index()
        .sort_values(["count", "conflict_mean"], ascending=[False, False])
        .reset_index(drop=True)
    )
    return candidates_df, summary


def write_markdown_report(
    output_path: Path,
    expanded_high: pd.DataFrame,
    source_buckets: pd.DataFrame,
    quality_buckets: pd.DataFrame,
    comparison_df: pd.DataFrame,
    demotion_summary: pd.DataFrame,
):
    total_high = len(expanded_high)
    quality_map = quality_buckets.set_index("quality_bucket").to_dict("index")
    strict_only = comparison_df[
        (comparison_df["section"] == "strict_key_counts") & (comparison_df["metric"] == "expanded_only_high_unique_keys")
    ]["value"].iloc[0]
    relaxed_only = comparison_df[
        (comparison_df["section"] == "relaxed_key_counts") & (comparison_df["metric"] == "expanded_only_high_unique_keys")
    ]["value"].iloc[0]
    top_source = source_buckets[source_buckets["analysis_view"] == "alert_source_layer"].head(3)
    top_expanded_only = comparison_df[comparison_df["section"] == "expanded_only_relaxed"].head(5)
    top_demotion = demotion_summary.head(5)

    lines = []
    lines.append("# S1-B Modern High Purity Audit")
    lines.append("")
    lines.append("## Audit Setup")
    lines.append("")
    lines.append("- scope: S1-A 2024 modern pilot outputs only; no pipeline rerun")
    lines.append("- strict join key: `prefix + origin_as + as_path_clean`")
    lines.append("- relaxed join key: `prefix + origin_as`")
    lines.append("- clean-high: `missing=false and conflict=0 and certainty>=80`")
    lines.append("- noisy-high: `missing=true or conflict>=5 or certainty<60`")
    lines.append("- fragile-high: all remaining high records")
    lines.append("")
    lines.append("## Expanded High Summary")
    lines.append("")
    lines.append(f"- expanded_final_high_total: {total_high}")
    lines.append(f"- clean_high: {quality_map.get('clean-high', {}).get('count', 0)}")
    lines.append(f"- fragile_high: {quality_map.get('fragile-high', {}).get('count', 0)}")
    lines.append(f"- noisy_high: {quality_map.get('noisy-high', {}).get('count', 0)}")
    lines.append(f"- expanded_only_high_strict_keys: {strict_only}")
    lines.append(f"- expanded_only_high_relaxed_keys: {relaxed_only}")
    lines.append("")
    lines.append("## Top High Source Buckets")
    lines.append("")
    for row in top_source.to_dict("records"):
        lines.append(
            f"- {row['analysis_view']}={row['alert_source_layer']}: count={row['count']}, pct={row['pct_within_high']:.4f}"
        )
    lines.append("")
    lines.append("## Expanded-only High Patterns (relaxed key)")
    lines.append("")
    for row in top_expanded_only.to_dict("records"):
        lines.append(
            "- "
            f"quality={row['quality_bucket']}, source={row['alert_source_layer']}, gate={row['gating_label']}, "
            f"augment={row['augmentation_label']}, top_factor={row['top_contributing_factor']}, "
            f"count={row['count']}, missing_rate={row['missing_rate']:.4f}, conflict_mean={row['conflict_mean']:.4f}"
        )
    lines.append("")
    lines.append("## Demotion Candidate Pool")
    lines.append("")
    for row in top_demotion.to_dict("records"):
        lines.append(
            "- "
            f"tier={row['demotion_priority_tier']}, source={row['alert_source_layer']}, gate={row['gating_label']}, "
            f"augment={row['augmentation_label']}, top_factor={row['top_contributing_factor']}, "
            f"count={row['count']}, pct_noisy={row['pct_within_noisy']:.4f}, "
            f"missing_rate={row['missing_rate']:.4f}, conflict_mean={row['conflict_mean']:.4f}"
        )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="S1-B modern high-priority purity audit")
    ap.add_argument("--output-dir", default="outputs/s1b_modern_high_audit_v01")
    ap.add_argument(
        "--expanded-final",
        default="data/runs/s1a_expanded_v02_pilot_60m_april16/final/final_alerts.parquet",
    )
    ap.add_argument(
        "--baseline-final",
        default="data/runs/s1a_baseline_v02_pilot_60m_april16/final/final_alerts.parquet",
    )
    ap.add_argument(
        "--results-csv",
        default="outputs/s1a_modern_2024_pilot_60m_v02/s1a_modern_2024_results.csv",
    )
    ap.add_argument(
        "--summary-json",
        default="outputs/s1a_modern_2024_pilot_60m_v02/s1a_modern_2024_summary.json",
    )
    args = ap.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    expanded_final = read_final_alerts(Path(args.expanded_final))
    baseline_final = read_final_alerts(Path(args.baseline_final))
    results_df = pd.read_csv(args.results_csv)
    summary_json = json.loads(Path(args.summary_json).read_text(encoding="utf-8"))

    expanded_high = add_business_keys(expanded_final[expanded_final["final_alert_label"] == "high_priority_alert"].copy())
    baseline_high = add_business_keys(baseline_final[baseline_final["final_alert_label"] == "high_priority_alert"].copy())
    expanded_high["quality_bucket"] = classify_quality_bucket(expanded_high)
    baseline_high["quality_bucket"] = classify_quality_bucket(baseline_high)

    source_frames = []
    source_frames.append(group_pct(expanded_high, ["alert_source_layer"], len(expanded_high), "alert_source_layer"))
    source_frames.append(group_pct(expanded_high, ["gating_label"], len(expanded_high), "gating_label"))
    source_frames.append(group_pct(expanded_high, ["augmentation_label"], len(expanded_high), "augmentation_label"))
    source_frames.append(group_pct(expanded_high, ["top_contributing_factor"], len(expanded_high), "top_contributing_factor"))
    source_frames.append(
        group_pct(
            expanded_high,
            ["quality_bucket", "alert_source_layer", "gating_label", "augmentation_label", "top_contributing_factor"],
            len(expanded_high),
            "combined_top_buckets",
        )
    )
    source_buckets = pd.concat(source_frames, ignore_index=True, sort=False)
    source_buckets.to_csv(output_dir / OUTPUT_FILES["source_buckets"], index=False, encoding="utf-8-sig")

    quality_buckets = summarize_quality_buckets(expanded_high)
    quality_buckets.to_csv(output_dir / OUTPUT_FILES["quality_buckets"], index=False, encoding="utf-8-sig")

    expanded_high, comparison_df = build_comparison_tables(baseline_high, expanded_high)
    comparison_df.to_csv(output_dir / OUTPUT_FILES["baseline_vs_expanded"], index=False, encoding="utf-8-sig")

    demotion_candidates, demotion_summary = build_demotion_candidates(expanded_high)
    demotion_candidates.to_csv(output_dir / OUTPUT_FILES["demotion_candidates"], index=False, encoding="utf-8-sig")

    summary_rows = [
        {
            "metric": "expanded_final_high_total",
            "value": int(len(expanded_high)),
        },
        {
            "metric": "clean_high_count",
            "value": int((expanded_high["quality_bucket"] == "clean-high").sum()),
        },
        {
            "metric": "fragile_high_count",
            "value": int((expanded_high["quality_bucket"] == "fragile-high").sum()),
        },
        {
            "metric": "noisy_high_count",
            "value": int((expanded_high["quality_bucket"] == "noisy-high").sum()),
        },
        {
            "metric": "clean_high_ratio",
            "value": float((expanded_high["quality_bucket"] == "clean-high").mean()),
        },
        {
            "metric": "fragile_high_ratio",
            "value": float((expanded_high["quality_bucket"] == "fragile-high").mean()),
        },
        {
            "metric": "noisy_high_ratio",
            "value": float((expanded_high["quality_bucket"] == "noisy-high").mean()),
        },
        {
            "metric": "strict_expanded_only_high_unique_keys",
            "value": int(expanded_high.loc[expanded_high["expanded_only_strict"], "strict_key"].nunique()),
        },
        {
            "metric": "relaxed_expanded_only_high_unique_keys",
            "value": int(expanded_high.loc[expanded_high["expanded_only_relaxed"], "relaxed_key"].nunique()),
        },
        {
            "metric": "demotion_candidate_rows",
            "value": int(len(demotion_candidates)),
        },
        {
            "metric": "demotion_candidate_ratio_vs_high",
            "value": float(len(demotion_candidates) / len(expanded_high) if len(expanded_high) else 0.0),
        },
        {
            "metric": "expanded_high_missing_rate",
            "value": float(expanded_high["missing_origin_or_path"].mean()),
        },
        {
            "metric": "expanded_high_conflict_mean",
            "value": float(expanded_high["conflict_score"].mean()),
        },
        {
            "metric": "expanded_high_certainty_mean",
            "value": float(expanded_high["certainty_score"].mean()),
        },
        {
            "metric": "summary_json_final_high",
            "value": int(summary_json["expanded_final_high"]),
        },
        {
            "metric": "results_csv_final_high",
            "value": int(results_df.loc[results_df["setting"] == "expanded_collectors", "final_high"].iloc[0]),
        },
    ]
    summary_df = pd.DataFrame(summary_rows)
    summary_df.to_csv(output_dir / OUTPUT_FILES["summary"], index=False, encoding="utf-8-sig")

    write_markdown_report(
        output_dir / OUTPUT_FILES["report"],
        expanded_high,
        source_buckets,
        quality_buckets,
        comparison_df,
        demotion_summary,
    )

    print(f"output_dir={output_dir}")
    print(f"expanded_final_high={len(expanded_high)}")
    print(f"clean_high={(expanded_high['quality_bucket'] == 'clean-high').sum()}")
    print(f"fragile_high={(expanded_high['quality_bucket'] == 'fragile-high').sum()}")
    print(f"noisy_high={(expanded_high['quality_bucket'] == 'noisy-high').sum()}")
    print(f"strict_expanded_only_keys={expanded_high.loc[expanded_high['expanded_only_strict'], 'strict_key'].nunique()}")
    print(f"relaxed_expanded_only_keys={expanded_high.loc[expanded_high['expanded_only_relaxed'], 'relaxed_key'].nunique()}")
    print(f"demotion_candidates={len(demotion_candidates)}")


if __name__ == "__main__":
    main()
