import argparse
import json
from pathlib import Path

import pandas as pd


DEFAULT_RUN_ID = "20260313T032554_4f9be28c"

# Keep in sync with scripts/gate_scored_candidates.py
CERTAINTY_THRESHOLD_HIGH = 65.0
CONFLICT_THRESHOLD_HIGH = 35.0
STRUCTURAL_MIN_FOR_HIGH = 45.0


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def safe_mean(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    return float(values.mean()) if len(values) else 0.0


def safe_median(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    return float(values.median()) if len(values) else 0.0


def ratio(numerator: int, denominator: int) -> float:
    return float(numerator) / float(denominator) if denominator else 0.0


def ensure_bool_col(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series([False] * len(df), index=df.index, dtype=bool)
    return df[col].fillna(False).astype(bool)


def no_gate_label(row: pd.Series) -> str:
    augmentation_label = str(row.get("augmentation_label", "") or "")
    risk_bucket = str(row.get("risk_bucket", "") or "")
    if augmentation_label == "promoted_suspicious":
        return "high_priority_alert"
    if augmentation_label == "demoted_suspicious":
        return "low_priority_or_background"
    if risk_bucket == "high":
        return "high_priority_alert"
    if risk_bucket == "medium":
        return "needs_review"
    return "low_priority_or_background"


def no_gate_source(row: pd.Series) -> str:
    augmentation_label = str(row.get("augmentation_label", "") or "")
    risk_bucket = str(row.get("risk_bucket", "") or "")
    if augmentation_label == "promoted_suspicious":
        return "augmentation_promoted"
    if augmentation_label == "demoted_suspicious":
        return "augmentation_demoted"
    if risk_bucket == "high":
        return "score_high_bucket"
    if risk_bucket == "medium":
        return "score_medium_bucket"
    return "score_low_bucket"


def quality_stats(df: pd.DataFrame, name: str) -> dict:
    n = int(len(df))
    missing = int(ensure_bool_col(df, "missing_origin_or_path").sum())
    structural_dom = int((df.get("top_contributing_factor", "") == "structural_novelty_score").sum())
    return {
        "group": name,
        "count": n,
        "missing_origin_or_path_count": missing,
        "missing_origin_or_path_rate": ratio(missing, n),
        "structural_dominance_count": structural_dom,
        "structural_dominance_rate": ratio(structural_dom, n),
        "risk_score_mean": safe_mean(df.get("risk_score", pd.Series(dtype=float))),
        "risk_score_median": safe_median(df.get("risk_score", pd.Series(dtype=float))),
        "certainty_score_mean": safe_mean(df.get("certainty_score", pd.Series(dtype=float))),
        "certainty_score_median": safe_median(df.get("certainty_score", pd.Series(dtype=float))),
        "conflict_score_mean": safe_mean(df.get("conflict_score", pd.Series(dtype=float))),
        "conflict_score_median": safe_median(df.get("conflict_score", pd.Series(dtype=float))),
        "evidence_support_score_mean": safe_mean(df.get("evidence_support_score", pd.Series(dtype=float))),
        "evidence_support_score_median": safe_median(df.get("evidence_support_score", pd.Series(dtype=float))),
    }


def high_gate_pass_mask(df: pd.DataFrame) -> pd.Series:
    risk_bucket_high = df.get("risk_bucket", "").fillna("").astype(str).eq("high")
    certainty_ok = pd.to_numeric(df.get("certainty_score", 0.0), errors="coerce").fillna(0.0) >= CERTAINTY_THRESHOLD_HIGH
    conflict_ok = pd.to_numeric(df.get("conflict_score", 0.0), errors="coerce").fillna(0.0) < CONFLICT_THRESHOLD_HIGH
    structural_ok = pd.to_numeric(df.get("structural_novelty_score", 0.0), errors="coerce").fillna(0.0) >= STRUCTURAL_MIN_FOR_HIGH
    missing_ok = ~ensure_bool_col(df, "missing_origin_or_path")
    return risk_bucket_high & certainty_ok & conflict_ok & structural_ok & missing_ok


def to_int_dict(value_counts: pd.Series) -> dict:
    return {str(k): int(v) for k, v in value_counts.items()}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="E6-B-1 remove-gate ablation: keep other modules unchanged and only remove gate restriction in final split."
    )
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID, help="Run id under runs root.")
    parser.add_argument("--runs-root", default="data/runs", help="Root path containing run folders.")
    parser.add_argument("--output-dir", default=None, help="Output directory.")
    parser.add_argument("--topk-new-high", type=int, default=200, help="How many newly-added high samples to export.")
    return parser


def main():
    args = build_parser().parse_args()
    runs_root = Path(args.runs_root)
    run_id = args.run_id
    run_base = runs_root / run_id

    required = [
        run_base / "events" / "event_units_summary.json",
        run_base / "candidates" / "candidate_summary.json",
        run_base / "scores" / "score_summary.json",
        run_base / "scores" / "scored_candidates.parquet",
        run_base / "gating" / "gated_candidates.parquet",
        run_base / "augmentation" / "augmented_candidates.parquet",
        run_base / "final" / "final_alerts.parquet",
        run_base / "final" / "final_report.json",
    ]
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        raise SystemExit("missing required inputs:\n" + "\n".join(missing))

    output_dir = Path(args.output_dir) if args.output_dir else Path("outputs") / f"e6b1_nogate_ablation_{run_id}"
    output_dir.mkdir(parents=True, exist_ok=True)

    event_summary = read_json(run_base / "events" / "event_units_summary.json")
    candidate_summary = read_json(run_base / "candidates" / "candidate_summary.json")
    score_summary = read_json(run_base / "scores" / "score_summary.json")
    final_report = read_json(run_base / "final" / "final_report.json")

    scored = pd.read_parquet(run_base / "scores" / "scored_candidates.parquet")
    gated = pd.read_parquet(run_base / "gating" / "gated_candidates.parquet")
    augmented = pd.read_parquet(run_base / "augmentation" / "augmented_candidates.parquet")
    default_final = pd.read_parquet(run_base / "final" / "final_alerts.parquet")

    score_cols = [
        "event_id",
        "run_id",
        "prefix",
        "origin_as",
        "as_path_clean",
        "risk_score",
        "risk_bucket",
        "top_contributing_factor",
        "candidate_reasons",
        "matched_rule_count",
        "structural_novelty_score",
        "weak_signal_score",
        "history_rarity_score",
        "path_consistency_score",
        "missing_origin_or_path",
    ]
    scored = scored[[c for c in score_cols if c in scored.columns]].copy()

    gating_cols = ["event_id", "gating_label", "certainty_score", "conflict_score", "gating_explanation"]
    gated = gated[[c for c in gating_cols if c in gated.columns]].copy()

    aug_cols = [
        "event_id",
        "augmentation_label",
        "augmentation_explanation",
        "evidence_support_score",
        "multi_view_support_score",
        "historical_deviation_support_score",
        "consistency_recheck_score",
    ]
    augmented = augmented[[c for c in aug_cols if c in augmented.columns]].copy()

    default_cols = ["event_id", "final_alert_label", "alert_source_layer"]
    default_final = default_final[[c for c in default_cols if c in default_final.columns]].rename(
        columns={
            "final_alert_label": "default_final_alert_label",
            "alert_source_layer": "default_alert_source_layer",
        }
    )

    merged = scored.merge(gated, on="event_id", how="left").merge(augmented, on="event_id", how="left").merge(default_final, on="event_id", how="left")

    merged["no_gate_final_alert_label"] = merged.apply(no_gate_label, axis=1)
    merged["no_gate_alert_source_layer"] = merged.apply(no_gate_source, axis=1)

    no_gate_out = output_dir / "e6b1_no_gate_final_alerts.parquet"
    merged.to_parquet(no_gate_out, index=False)

    default_counts = default_final["default_final_alert_label"].value_counts()
    no_gate_counts = merged["no_gate_final_alert_label"].value_counts()
    flow = pd.DataFrame(
        [
            {
                "setting": "default",
                "total_events": int(event_summary.get("total_events", 0)),
                "candidate_count": int(candidate_summary.get("candidate_events", 0)),
                "scored_count": int(score_summary.get("output_rows", 0)),
                "final_high_count": int(default_counts.get("high_priority_alert", 0)),
                "final_needs_count": int(default_counts.get("needs_review", 0)),
                "final_low_count": int(default_counts.get("low_priority_or_background", 0)),
            },
            {
                "setting": "no_gate",
                "total_events": int(event_summary.get("total_events", 0)),
                "candidate_count": int(candidate_summary.get("candidate_events", 0)),
                "scored_count": int(len(merged)),
                "final_high_count": int(no_gate_counts.get("high_priority_alert", 0)),
                "final_needs_count": int(no_gate_counts.get("needs_review", 0)),
                "final_low_count": int(no_gate_counts.get("low_priority_or_background", 0)),
            },
        ]
    )
    flow.to_csv(output_dir / "e6b1_default_vs_nogate_flow.csv", index=False, encoding="utf-8-sig")

    default_high = set(
        default_final.loc[default_final["default_final_alert_label"] == "high_priority_alert", "event_id"].astype(str)
    )
    no_gate_high = set(merged.loc[merged["no_gate_final_alert_label"] == "high_priority_alert", "event_id"].astype(str))
    newly_high_ids = no_gate_high - default_high
    removed_high_ids = default_high - no_gate_high

    new_high_df = merged[merged["event_id"].astype(str).isin(newly_high_ids)].copy()
    default_high_df = merged[merged["event_id"].astype(str).isin(default_high)].copy()
    no_gate_high_df = merged[merged["event_id"].astype(str).isin(no_gate_high)].copy()

    new_high_sources = (
        new_high_df.get("default_final_alert_label", pd.Series(dtype=str)).fillna("").value_counts().rename_axis("source_default_label").reset_index(name="count")
    )
    if len(new_high_sources):
        new_high_sources["rate_in_new_high"] = new_high_sources["count"] / float(len(new_high_df))
    else:
        new_high_sources["rate_in_new_high"] = pd.Series(dtype=float)
    new_high_sources.to_csv(output_dir / "e6b1_new_high_sources.csv", index=False, encoding="utf-8-sig")

    quality = pd.DataFrame(
        [
            quality_stats(default_high_df, "default_high"),
            quality_stats(no_gate_high_df, "no_gate_high"),
            quality_stats(new_high_df, "newly_added_high"),
        ]
    )
    quality.to_csv(output_dir / "e6b1_high_quality_compare.csv", index=False, encoding="utf-8-sig")

    new_high_gate_pass = high_gate_pass_mask(new_high_df)
    new_high_gate_fail = ~new_high_gate_pass
    certainty_series = pd.to_numeric(new_high_df.get("certainty_score", 0.0), errors="coerce").fillna(0.0)
    conflict_series = pd.to_numeric(new_high_df.get("conflict_score", 0.0), errors="coerce").fillna(0.0)
    structural_series = pd.to_numeric(new_high_df.get("structural_novelty_score", 0.0), errors="coerce").fillna(0.0)
    missing_series = ensure_bool_col(new_high_df, "missing_origin_or_path")
    risk_high_series = new_high_df.get("risk_bucket", "").fillna("").astype(str).eq("high")

    gate_fail_breakdown = {
        "new_high_count": int(len(new_high_df)),
        "would_pass_default_high_gate_count": int(new_high_gate_pass.sum()),
        "would_fail_default_high_gate_count": int(new_high_gate_fail.sum()),
        "gate_fail_reason_counts": {
            "risk_bucket_not_high": int((~risk_high_series).sum()),
            "certainty_below_65": int((certainty_series < CERTAINTY_THRESHOLD_HIGH).sum()),
            "conflict_ge_35": int((conflict_series >= CONFLICT_THRESHOLD_HIGH).sum()),
            "structural_below_45": int((structural_series < STRUCTURAL_MIN_FOR_HIGH).sum()),
            "missing_origin_or_path": int(missing_series.sum()),
        },
    }

    feature_summary = {
        "run_id": run_id,
        "total_events": int(event_summary.get("total_events", 0)),
        "candidate_count": int(candidate_summary.get("candidate_events", 0)),
        "scored_count": int(len(merged)),
        "default_high_count": int(default_counts.get("high_priority_alert", 0)),
        "no_gate_high_count": int(no_gate_counts.get("high_priority_alert", 0)),
        "new_high_count": int(len(new_high_df)),
        "removed_high_count": int(len(removed_high_ids)),
        "new_high_default_label_dist": to_int_dict(new_high_df.get("default_final_alert_label", pd.Series(dtype=str)).fillna("").value_counts()),
        "new_high_gating_label_dist": to_int_dict(new_high_df.get("gating_label", pd.Series(dtype=str)).fillna("").value_counts()),
        "new_high_risk_bucket_dist": to_int_dict(new_high_df.get("risk_bucket", pd.Series(dtype=str)).fillna("").value_counts()),
        "new_high_top_factor_dist": to_int_dict(
            new_high_df.get("top_contributing_factor", pd.Series(dtype=str)).fillna("").value_counts()
        ),
        "new_high_score_means": {
            "risk_score": safe_mean(new_high_df.get("risk_score", pd.Series(dtype=float))),
            "certainty_score": safe_mean(new_high_df.get("certainty_score", pd.Series(dtype=float))),
            "conflict_score": safe_mean(new_high_df.get("conflict_score", pd.Series(dtype=float))),
            "structural_novelty_score": safe_mean(new_high_df.get("structural_novelty_score", pd.Series(dtype=float))),
            "weak_signal_score": safe_mean(new_high_df.get("weak_signal_score", pd.Series(dtype=float))),
            "history_rarity_score": safe_mean(new_high_df.get("history_rarity_score", pd.Series(dtype=float))),
            "path_consistency_score": safe_mean(new_high_df.get("path_consistency_score", pd.Series(dtype=float))),
            "evidence_support_score": safe_mean(new_high_df.get("evidence_support_score", pd.Series(dtype=float))),
        },
        "gate_requirement_check": gate_fail_breakdown,
        "default_final_report_snapshot": {
            "high_priority_alert_count": int(final_report.get("high_priority_alert_count", 0)),
            "needs_review_count": int(final_report.get("needs_review_count", 0)),
            "low_priority_or_background_count": int(final_report.get("low_priority_or_background_count", 0)),
            "high_priority_from_gating_count": int(final_report.get("high_priority_from_gating_count", 0)),
            "high_priority_from_augmentation_count": int(final_report.get("high_priority_from_augmentation_count", 0)),
            "missing_origin_or_path_in_high_priority": int(final_report.get("missing_origin_or_path_in_high_priority", 0)),
        },
    }
    (output_dir / "e6b1_new_high_feature_summary.json").write_text(
        json.dumps(feature_summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    sample_cols = [
        "event_id",
        "prefix",
        "origin_as",
        "as_path_clean",
        "risk_score",
        "risk_bucket",
        "default_final_alert_label",
        "no_gate_final_alert_label",
        "default_alert_source_layer",
        "no_gate_alert_source_layer",
        "gating_label",
        "augmentation_label",
        "top_contributing_factor",
        "structural_novelty_score",
        "weak_signal_score",
        "history_rarity_score",
        "path_consistency_score",
        "missing_origin_or_path",
        "certainty_score",
        "conflict_score",
        "evidence_support_score",
    ]
    sample_cols = [c for c in sample_cols if c in new_high_df.columns]
    new_high_df.sort_values(["risk_score", "certainty_score"], ascending=[False, True]).head(args.topk_new_high)[sample_cols].to_csv(
        output_dir / "e6b1_new_high_samples.csv",
        index=False,
        encoding="utf-8-sig",
    )

    print(f"run_id={run_id}")
    print(f"runs_root={runs_root.resolve().as_posix()}")
    print(f"output_dir={output_dir.resolve().as_posix()}")
    print(f"default_high={int(default_counts.get('high_priority_alert', 0))}")
    print(f"no_gate_high={int(no_gate_counts.get('high_priority_alert', 0))}")
    print(f"new_high={int(len(new_high_df))}")
    print(f"new_high_from_needs={int((new_high_df.get('default_final_alert_label', '') == 'needs_review').sum())}")
    print(
        f"new_high_fail_default_high_gate={int(gate_fail_breakdown['would_fail_default_high_gate_count'])}/{int(len(new_high_df))}"
    )


if __name__ == "__main__":
    main()
