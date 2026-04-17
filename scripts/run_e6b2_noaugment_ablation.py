import argparse
import json
from pathlib import Path

import pandas as pd


DEFAULT_RUN_ID = "20260313T032554_4f9be28c"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def ratio(numerator: int, denominator: int) -> float:
    return float(numerator) / float(denominator) if denominator else 0.0


def safe_mean(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    return float(values.mean()) if len(values) else 0.0


def safe_median(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    return float(values.median()) if len(values) else 0.0


def ensure_bool_col(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series([False] * len(df), index=df.index, dtype=bool)
    return df[col].fillna(False).astype(bool)


def to_int_dict(series: pd.Series) -> dict:
    return {str(k): int(v) for k, v in series.items()}


def no_augment_label(gating_label: str) -> tuple[str, str]:
    g = str(gating_label or "").strip()
    if g == "likely_malicious":
        return "high_priority_alert", "gating_likely_malicious"
    if g == "likely_benign":
        return "low_priority_or_background", "gating_likely_benign"
    if g == "suspicious_but_uncertain":
        return "needs_review", "gating_uncertain_no_augment"
    return "needs_review", "fallback_uncertain_no_augment"


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


def choose_path_type(high_lost: int, needs_increase: int, low_increase: int) -> str:
    # Heuristic mapping for A/B/C/D in the task definition.
    if high_lost > 0 and needs_increase >= high_lost:
        if high_lost <= 3 and abs(needs_increase) <= 30:
            return "C"
        return "A"
    if needs_increase > 0 and low_increase < 0:
        return "B"
    if high_lost == 0 and abs(needs_increase) <= 5 and abs(low_increase) <= 5:
        return "D"
    return "C"


def choose_final_tag(high_lost: int, needs_increase: int, low_abs_change: int) -> str:
    if high_lost >= 5 or needs_increase >= 50:
        return "augment=独立有效"
    if high_lost > 0 or needs_increase > 0 or low_abs_change >= 10:
        return "augment=作用有限"
    return "augment=暂不能判断"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="E6-B-2 remove-augment ablation: keep gate and other modules unchanged, remove augmentation effect only."
    )
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID, help="Run id under runs root.")
    parser.add_argument("--runs-root", default="data/runs", help="Root path containing run folders.")
    parser.add_argument("--output-dir", default=None, help="Output directory.")
    parser.add_argument("--topk-samples", type=int, default=200, help="Max rows in changed sample exports.")
    return parser


def main():
    args = build_parser().parse_args()
    run_id = args.run_id
    runs_root = Path(args.runs_root)
    run_base = runs_root / run_id

    required = [
        run_base / "events" / "event_units_summary.json",
        run_base / "candidates" / "candidate_summary.json",
        run_base / "scores" / "score_summary.json",
        run_base / "gating" / "gating_summary.json",
        run_base / "augmentation" / "augmentation_summary.json",
        run_base / "final" / "final_report.json",
        run_base / "scores" / "scored_candidates.parquet",
        run_base / "gating" / "gated_candidates.parquet",
        run_base / "augmentation" / "augmented_candidates.parquet",
        run_base / "final" / "final_alerts.parquet",
    ]
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        raise SystemExit("missing required inputs:\n" + "\n".join(missing))

    output_dir = Path(args.output_dir) if args.output_dir else Path("outputs") / f"e6b2_noaugment_ablation_{run_id}"
    output_dir.mkdir(parents=True, exist_ok=True)

    event_summary = read_json(run_base / "events" / "event_units_summary.json")
    candidate_summary = read_json(run_base / "candidates" / "candidate_summary.json")
    score_summary = read_json(run_base / "scores" / "score_summary.json")
    gating_summary = read_json(run_base / "gating" / "gating_summary.json")
    augment_summary = read_json(run_base / "augmentation" / "augmentation_summary.json")
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

    augment_cols = [
        "event_id",
        "augmentation_label",
        "augmentation_explanation",
        "evidence_support_score",
        "multi_view_support_score",
        "historical_deviation_support_score",
        "consistency_recheck_score",
    ]
    augmented = augmented[[c for c in augment_cols if c in augmented.columns]].copy()

    default_cols = ["event_id", "final_alert_label", "alert_source_layer"]
    default_final = default_final[[c for c in default_cols if c in default_final.columns]].rename(
        columns={
            "final_alert_label": "default_final_alert_label",
            "alert_source_layer": "default_alert_source_layer",
        }
    )

    merged = (
        scored.merge(gated, on="event_id", how="left")
        .merge(augmented, on="event_id", how="left")
        .merge(default_final, on="event_id", how="left")
    )

    no_aug_decisions = merged.get("gating_label", "").fillna("").astype(str).apply(no_augment_label)
    merged["no_augment_final_alert_label"] = no_aug_decisions.map(lambda x: x[0])
    merged["no_augment_alert_source_layer"] = no_aug_decisions.map(lambda x: x[1])

    merged.to_parquet(output_dir / "e6b2_no_augment_final_alerts.parquet", index=False)

    default_counts = merged.get("default_final_alert_label", pd.Series(dtype=str)).fillna("").value_counts()
    no_aug_counts = merged.get("no_augment_final_alert_label", pd.Series(dtype=str)).fillna("").value_counts()

    flow_df = pd.DataFrame(
        [
            {
                "setting": "default",
                "total_events": int(event_summary.get("total_events", 0)),
                "candidate_count": int(candidate_summary.get("candidate_events", 0)),
                "scored_count": int(score_summary.get("output_rows", 0)),
                "gated_count": int(gating_summary.get("input_rows", len(gated))),
                "final_high_count": int(default_counts.get("high_priority_alert", 0)),
                "final_needs_count": int(default_counts.get("needs_review", 0)),
                "final_low_count": int(default_counts.get("low_priority_or_background", 0)),
            },
            {
                "setting": "no_augment",
                "total_events": int(event_summary.get("total_events", 0)),
                "candidate_count": int(candidate_summary.get("candidate_events", 0)),
                "scored_count": int(len(merged)),
                "gated_count": int(len(gated)),
                "final_high_count": int(no_aug_counts.get("high_priority_alert", 0)),
                "final_needs_count": int(no_aug_counts.get("needs_review", 0)),
                "final_low_count": int(no_aug_counts.get("low_priority_or_background", 0)),
            },
        ]
    )
    flow_df.to_csv(output_dir / "e6b2_default_vs_noaugment_flow.csv", index=False, encoding="utf-8-sig")

    transition = (
        merged.groupby(["default_final_alert_label", "no_augment_final_alert_label"], dropna=False)
        .size()
        .reset_index(name="count")
    )
    transition["default_final_alert_label"] = transition["default_final_alert_label"].fillna("").astype(str)
    transition["no_augment_final_alert_label"] = transition["no_augment_final_alert_label"].fillna("").astype(str)

    from_totals = transition.groupby("default_final_alert_label", dropna=False)["count"].sum().to_dict()
    transition["rate_over_default_label"] = transition.apply(
        lambda r: ratio(int(r["count"]), int(from_totals.get(str(r["default_final_alert_label"]), 0))),
        axis=1,
    )
    transition = transition.sort_values(["default_final_alert_label", "no_augment_final_alert_label"]).reset_index(drop=True)
    transition.to_csv(output_dir / "e6b2_label_transition_matrix.csv", index=False, encoding="utf-8-sig")

    default_high = int(default_counts.get("high_priority_alert", 0))
    default_needs = int(default_counts.get("needs_review", 0))
    default_low = int(default_counts.get("low_priority_or_background", 0))

    no_aug_high = int(no_aug_counts.get("high_priority_alert", 0))
    no_aug_needs = int(no_aug_counts.get("needs_review", 0))
    no_aug_low = int(no_aug_counts.get("low_priority_or_background", 0))

    high_lost = default_high - no_aug_high
    needs_increase = no_aug_needs - default_needs
    low_increase = no_aug_low - default_low

    mask_def_high = merged["default_final_alert_label"].fillna("").eq("high_priority_alert")
    mask_def_needs = merged["default_final_alert_label"].fillna("").eq("needs_review")
    mask_def_low = merged["default_final_alert_label"].fillna("").eq("low_priority_or_background")
    mask_no_high = merged["no_augment_final_alert_label"].fillna("").eq("high_priority_alert")
    mask_no_needs = merged["no_augment_final_alert_label"].fillna("").eq("needs_review")
    mask_no_low = merged["no_augment_final_alert_label"].fillna("").eq("low_priority_or_background")

    default_high_to_no_needs = int((mask_def_high & mask_no_needs).sum())
    default_high_to_no_low = int((mask_def_high & mask_no_low).sum())
    default_needs_to_no_low = int((mask_def_needs & mask_no_low).sum())
    default_low_to_no_needs = int((mask_def_low & mask_no_needs).sum())

    delta_df = pd.DataFrame(
        [
            {"metric": "augment_input_count_default", "value": int(augment_summary.get("input_uncertain_rows", len(augmented)))},
            {"metric": "default_promoted_suspicious_count", "value": int(augment_summary.get("promoted_suspicious_count", 0))},
            {"metric": "default_retained_uncertain_count", "value": int(augment_summary.get("retained_uncertain_count", 0))},
            {"metric": "default_demoted_suspicious_count", "value": int(augment_summary.get("demoted_suspicious_count", 0))},
            {"metric": "high_lost_no_augment_vs_default", "value": int(high_lost)},
            {"metric": "needs_delta_no_augment_minus_default", "value": int(needs_increase)},
            {"metric": "low_delta_no_augment_minus_default", "value": int(low_increase)},
            {"metric": "default_high_to_no_augment_needs", "value": int(default_high_to_no_needs)},
            {"metric": "default_high_to_no_augment_low", "value": int(default_high_to_no_low)},
            {"metric": "default_needs_to_no_augment_low", "value": int(default_needs_to_no_low)},
            {"metric": "default_low_to_no_augment_needs", "value": int(default_low_to_no_needs)},
        ]
    )
    delta_df.to_csv(output_dir / "e6b2_delta_summary.csv", index=False, encoding="utf-8-sig")

    default_high_df = merged[mask_def_high].copy()
    no_aug_high_df = merged[mask_no_high].copy()
    dropped_from_high_df = merged[mask_def_high & (~mask_no_high)].copy()

    quality_df = pd.DataFrame(
        [
            quality_stats(default_high_df, "default_high"),
            quality_stats(no_aug_high_df, "no_augment_high"),
            quality_stats(dropped_from_high_df, "dropped_from_high_after_remove_augment"),
        ]
    )
    quality_df.to_csv(output_dir / "e6b2_high_quality_compare.csv", index=False, encoding="utf-8-sig")

    dropped_feature_summary = {
        "dropped_high_count": int(len(dropped_from_high_df)),
        "default_alert_source_dist": to_int_dict(
            dropped_from_high_df.get("default_alert_source_layer", pd.Series(dtype=str)).fillna("").value_counts()
        ),
        "gating_label_dist": to_int_dict(
            dropped_from_high_df.get("gating_label", pd.Series(dtype=str)).fillna("").value_counts()
        ),
        "augmentation_label_dist": to_int_dict(
            dropped_from_high_df.get("augmentation_label", pd.Series(dtype=str)).fillna("").value_counts()
        ),
        "top_factor_dist": to_int_dict(
            dropped_from_high_df.get("top_contributing_factor", pd.Series(dtype=str)).fillna("").value_counts()
        ),
        "missing_origin_or_path_count": int(ensure_bool_col(dropped_from_high_df, "missing_origin_or_path").sum()),
        "mean_scores": {
            "risk_score": safe_mean(dropped_from_high_df.get("risk_score", pd.Series(dtype=float))),
            "certainty_score": safe_mean(dropped_from_high_df.get("certainty_score", pd.Series(dtype=float))),
            "conflict_score": safe_mean(dropped_from_high_df.get("conflict_score", pd.Series(dtype=float))),
            "evidence_support_score": safe_mean(dropped_from_high_df.get("evidence_support_score", pd.Series(dtype=float))),
            "multi_view_support_score": safe_mean(dropped_from_high_df.get("multi_view_support_score", pd.Series(dtype=float))),
            "historical_deviation_support_score": safe_mean(
                dropped_from_high_df.get("historical_deviation_support_score", pd.Series(dtype=float))
            ),
            "consistency_recheck_score": safe_mean(dropped_from_high_df.get("consistency_recheck_score", pd.Series(dtype=float))),
        },
    }

    path_type = choose_path_type(high_lost, needs_increase, low_increase)
    final_tag = choose_final_tag(high_lost, needs_increase, abs(low_increase))

    summary_json = {
        "run_id": run_id,
        "runs_root": str(runs_root.resolve()),
        "output_dir": str(output_dir.resolve()),
        "default_counts": {
            "high": default_high,
            "needs": default_needs,
            "low": default_low,
        },
        "no_augment_counts": {
            "high": no_aug_high,
            "needs": no_aug_needs,
            "low": no_aug_low,
        },
        "augment_target_subset": {
            "augment_input_count_default": int(augment_summary.get("input_uncertain_rows", len(augmented))),
            "promoted_suspicious_count": int(augment_summary.get("promoted_suspicious_count", 0)),
            "retained_uncertain_count": int(augment_summary.get("retained_uncertain_count", 0)),
            "demoted_suspicious_count": int(augment_summary.get("demoted_suspicious_count", 0)),
        },
        "delta": {
            "high_lost_no_augment_vs_default": high_lost,
            "needs_delta_no_augment_minus_default": needs_increase,
            "low_delta_no_augment_minus_default": low_increase,
            "default_high_to_no_augment_needs": default_high_to_no_needs,
            "default_high_to_no_augment_low": default_high_to_no_low,
            "default_needs_to_no_augment_low": default_needs_to_no_low,
            "default_low_to_no_augment_needs": default_low_to_no_needs,
        },
        "path_judgement": path_type,
        "final_tag": final_tag,
        "dropped_high_feature_summary": dropped_feature_summary,
        "final_report_snapshot": {
            "high_priority_from_gating_count": int(final_report.get("high_priority_from_gating_count", 0)),
            "high_priority_from_augmentation_count": int(final_report.get("high_priority_from_augmentation_count", 0)),
            "missing_origin_or_path_in_high_priority": int(final_report.get("missing_origin_or_path_in_high_priority", 0)),
        },
    }
    (output_dir / "e6b2_summary.json").write_text(json.dumps(summary_json, ensure_ascii=False, indent=2), encoding="utf-8")

    sample_cols = [
        "event_id",
        "prefix",
        "origin_as",
        "as_path_clean",
        "risk_score",
        "risk_bucket",
        "gating_label",
        "augmentation_label",
        "default_final_alert_label",
        "no_augment_final_alert_label",
        "default_alert_source_layer",
        "no_augment_alert_source_layer",
        "top_contributing_factor",
        "missing_origin_or_path",
        "certainty_score",
        "conflict_score",
        "evidence_support_score",
        "multi_view_support_score",
        "historical_deviation_support_score",
        "consistency_recheck_score",
    ]
    sample_cols = [c for c in sample_cols if c in dropped_from_high_df.columns]
    dropped_from_high_df.sort_values(["evidence_support_score", "risk_score"], ascending=[False, False]).head(args.topk_samples)[
        sample_cols
    ].to_csv(output_dir / "e6b2_dropped_high_samples.csv", index=False, encoding="utf-8-sig")

    changed_mask = merged["default_final_alert_label"].fillna("").ne(merged["no_augment_final_alert_label"].fillna(""))
    changed_df = merged[changed_mask].copy()
    changed_cols = [
        "event_id",
        "default_final_alert_label",
        "no_augment_final_alert_label",
        "default_alert_source_layer",
        "no_augment_alert_source_layer",
        "gating_label",
        "augmentation_label",
        "risk_bucket",
        "risk_score",
        "certainty_score",
        "conflict_score",
        "evidence_support_score",
    ]
    changed_cols = [c for c in changed_cols if c in changed_df.columns]
    changed_df.sort_values(["default_final_alert_label", "no_augment_final_alert_label", "risk_score"], ascending=[True, True, False]).to_csv(
        output_dir / "e6b2_changed_label_samples.csv",
        index=False,
        encoding="utf-8-sig",
    )

    print(f"run_id={run_id}")
    print(f"runs_root={runs_root.resolve().as_posix()}")
    print(f"output_dir={output_dir.resolve().as_posix()}")
    print(f"default_high={default_high} no_augment_high={no_aug_high} high_lost={high_lost}")
    print(f"default_needs={default_needs} no_augment_needs={no_aug_needs} needs_delta={needs_increase}")
    print(f"default_low={default_low} no_augment_low={no_aug_low} low_delta={low_increase}")
    print(
        "transition_high_to_noaug "
        f"needs={default_high_to_no_needs} low={default_high_to_no_low}; "
        f"default_needs_to_noaug_low={default_needs_to_no_low}; default_low_to_noaug_needs={default_low_to_no_needs}"
    )
    print(f"path_judgement={path_type}")
    print(f"final_tag={final_tag}")


if __name__ == "__main__":
    main()
