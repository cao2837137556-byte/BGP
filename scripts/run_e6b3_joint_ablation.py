import argparse
import json
from pathlib import Path

import pandas as pd


DEFAULT_RUN_ID = "20260313T032554_4f9be28c"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def ratio(numerator: int, denominator: int) -> float:
    return float(numerator) / float(denominator) if denominator else 0.0


def ensure_bool_col(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series([False] * len(df), index=df.index, dtype=bool)
    return df[col].fillna(False).astype(bool)


def safe_mean(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    return float(values.mean()) if len(values) else 0.0


def safe_median(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    return float(values.median()) if len(values) else 0.0


def to_int_dict(series: pd.Series) -> dict:
    return {str(k): int(v) for k, v in series.items()}


def no_gate_label(row: pd.Series) -> tuple[str, str]:
    augmentation_label = str(row.get("augmentation_label", "") or "")
    risk_bucket = str(row.get("risk_bucket", "") or "")
    if augmentation_label == "promoted_suspicious":
        return "high_priority_alert", "augmentation_promoted"
    if augmentation_label == "demoted_suspicious":
        return "low_priority_or_background", "augmentation_demoted"
    if risk_bucket == "high":
        return "high_priority_alert", "score_high_bucket"
    if risk_bucket == "medium":
        return "needs_review", "score_medium_bucket"
    return "low_priority_or_background", "score_low_bucket"


def no_augment_label(row: pd.Series) -> tuple[str, str]:
    gating_label = str(row.get("gating_label", "") or "")
    if gating_label == "likely_malicious":
        return "high_priority_alert", "gating_likely_malicious"
    if gating_label == "likely_benign":
        return "low_priority_or_background", "gating_likely_benign"
    if gating_label == "suspicious_but_uncertain":
        return "needs_review", "gating_uncertain_no_augment"
    return "needs_review", "fallback_uncertain_no_augment"


def joint_label(row: pd.Series) -> tuple[str, str]:
    risk_bucket = str(row.get("risk_bucket", "") or "")
    if risk_bucket == "high":
        return "high_priority_alert", "score_high_bucket_no_gate_no_augment"
    if risk_bucket == "medium":
        return "needs_review", "score_medium_bucket_no_gate_no_augment"
    return "low_priority_or_background", "score_low_bucket_no_gate_no_augment"


def quality_stats(df: pd.DataFrame, group: str) -> dict:
    n = int(len(df))
    missing_count = int(ensure_bool_col(df, "missing_origin_or_path").sum())
    return {
        "group": group,
        "count": n,
        "risk_score_mean": safe_mean(df.get("risk_score", pd.Series(dtype=float))),
        "risk_score_median": safe_median(df.get("risk_score", pd.Series(dtype=float))),
        "certainty_score_mean": safe_mean(df.get("certainty_score", pd.Series(dtype=float))),
        "certainty_score_median": safe_median(df.get("certainty_score", pd.Series(dtype=float))),
        "conflict_score_mean": safe_mean(df.get("conflict_score", pd.Series(dtype=float))),
        "conflict_score_median": safe_median(df.get("conflict_score", pd.Series(dtype=float))),
        "missing_origin_or_path_count": missing_count,
        "missing_origin_or_path_rate": ratio(missing_count, n),
    }


def choose_system_mode(
    default_high: int,
    no_gate_high: int,
    no_augment_high: int,
    joint_high: int,
    default_certainty: float,
    joint_certainty: float,
) -> str:
    if joint_high - default_high >= 100 and joint_certainty <= default_certainty - 20.0:
        if abs(joint_high - no_gate_high) <= 2 and abs(joint_high - no_augment_high) >= 100:
            return "C"
        return "A"
    if joint_high > no_gate_high:
        return "B"
    if abs(joint_high - no_gate_high) <= 2 and abs(joint_high - no_augment_high) >= 50:
        return "C"
    return "D"


def choose_final_tag(system_mode: str) -> str:
    if system_mode in {"A", "C"}:
        return "joint_ablation=支持分层分工"
    if system_mode in {"B", "D"}:
        return "joint_ablation=部分支持"
    return "joint_ablation=暂不能判断"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="E6-B-3 joint ablation: remove gate + remove augment with same scored input for four-setting comparison."
    )
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID, help="Run id under runs root.")
    parser.add_argument("--runs-root", default="data/runs", help="Root path containing run folders.")
    parser.add_argument("--output-dir", default=None, help="Output directory.")
    parser.add_argument("--topk-samples", type=int, default=300, help="Max rows for sample exports.")
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

    output_dir = Path(args.output_dir) if args.output_dir else Path("outputs") / f"e6b3_joint_ablation_{run_id}"
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

    no_gate_decisions = merged.apply(no_gate_label, axis=1, result_type="expand")
    merged["no_gate_final_alert_label"] = no_gate_decisions[0]
    merged["no_gate_alert_source_layer"] = no_gate_decisions[1]

    no_augment_decisions = merged.apply(no_augment_label, axis=1, result_type="expand")
    merged["no_augment_final_alert_label"] = no_augment_decisions[0]
    merged["no_augment_alert_source_layer"] = no_augment_decisions[1]

    joint_decisions = merged.apply(joint_label, axis=1, result_type="expand")
    merged["no_gate_no_augment_final_alert_label"] = joint_decisions[0]
    merged["no_gate_no_augment_alert_source_layer"] = joint_decisions[1]

    merged.to_parquet(output_dir / "e6b3_four_setting_final_alerts.parquet", index=False)

    settings = [
        ("default", "default_final_alert_label"),
        ("no_gate", "no_gate_final_alert_label"),
        ("no_augment", "no_augment_final_alert_label"),
        ("no_gate_no_augment", "no_gate_no_augment_final_alert_label"),
    ]

    flow_rows = []
    for setting_name, label_col in settings:
        counts = merged[label_col].fillna("").astype(str).value_counts()
        flow_rows.append(
            {
                "setting": setting_name,
                "total_events": int(event_summary.get("total_events", 0)),
                "candidate_count": int(candidate_summary.get("candidate_events", 0)),
                "scored_count": int(score_summary.get("output_rows", len(scored))),
                "gated_count": int(gating_summary.get("input_rows", len(gated))),
                "final_high_count": int(counts.get("high_priority_alert", 0)),
                "final_needs_count": int(counts.get("needs_review", 0)),
                "final_low_count": int(counts.get("low_priority_or_background", 0)),
            }
        )
    flow_df = pd.DataFrame(flow_rows)
    flow_df.to_csv(output_dir / "e6b3_four_setting_flow.csv", index=False, encoding="utf-8-sig")

    flow_map = {row["setting"]: row for row in flow_rows}
    pairs = [
        ("default", "no_gate_no_augment"),
        ("no_gate", "no_gate_no_augment"),
        ("no_augment", "no_gate_no_augment"),
    ]
    pair_rows = []
    for base, target in pairs:
        b = flow_map[base]
        t = flow_map[target]
        pair_rows.append(
            {
                "base_setting": base,
                "target_setting": target,
                "delta_high": int(t["final_high_count"] - b["final_high_count"]),
                "delta_needs": int(t["final_needs_count"] - b["final_needs_count"]),
                "delta_low": int(t["final_low_count"] - b["final_low_count"]),
            }
        )
    pair_df = pd.DataFrame(pair_rows)
    pair_df.to_csv(output_dir / "e6b3_pairwise_diffs.csv", index=False, encoding="utf-8-sig")

    quality_rows = []
    for setting_name, label_col in settings:
        high_df = merged[merged[label_col].fillna("").astype(str) == "high_priority_alert"].copy()
        quality_rows.append(quality_stats(high_df, setting_name))
    quality_df = pd.DataFrame(quality_rows)
    quality_df.to_csv(output_dir / "e6b3_high_quality_compare.csv", index=False, encoding="utf-8-sig")

    def high_ids(label_col: str) -> set[str]:
        return set(merged.loc[merged[label_col].fillna("").astype(str) == "high_priority_alert", "event_id"].astype(str))

    ids_default_high = high_ids("default_final_alert_label")
    ids_no_gate_high = high_ids("no_gate_final_alert_label")
    ids_no_augment_high = high_ids("no_augment_final_alert_label")
    ids_joint_high = high_ids("no_gate_no_augment_final_alert_label")

    new_joint_vs_default = ids_joint_high - ids_default_high
    new_joint_vs_no_augment = ids_joint_high - ids_no_augment_high
    new_joint_vs_no_gate = ids_joint_high - ids_no_gate_high

    new_default_df = merged[merged["event_id"].astype(str).isin(new_joint_vs_default)].copy()
    new_no_aug_df = merged[merged["event_id"].astype(str).isin(new_joint_vs_no_augment)].copy()

    default_source = (
        new_default_df.get("default_final_alert_label", pd.Series(dtype=str)).fillna("").value_counts().rename_axis("source_default_label").reset_index(name="count")
    )
    if len(default_source):
        default_source["rate_in_new_joint_high"] = default_source["count"] / float(len(new_default_df))
    else:
        default_source["rate_in_new_joint_high"] = pd.Series(dtype=float)
    default_source.to_csv(output_dir / "e6b3_new_joint_high_vs_default_sources.csv", index=False, encoding="utf-8-sig")

    no_aug_source = (
        new_no_aug_df.get("no_augment_final_alert_label", pd.Series(dtype=str)).fillna("").value_counts().rename_axis("source_no_augment_label").reset_index(name="count")
    )
    if len(no_aug_source):
        no_aug_source["rate_in_new_joint_high"] = no_aug_source["count"] / float(len(new_no_aug_df))
    else:
        no_aug_source["rate_in_new_joint_high"] = pd.Series(dtype=float)
    no_aug_source.to_csv(output_dir / "e6b3_new_joint_high_vs_noaugment_sources.csv", index=False, encoding="utf-8-sig")

    changed_default_joint = merged[
        merged["default_final_alert_label"].fillna("").astype(str)
        != merged["no_gate_no_augment_final_alert_label"].fillna("").astype(str)
    ].copy()
    changed_cols = [
        "event_id",
        "default_final_alert_label",
        "no_gate_no_augment_final_alert_label",
        "no_gate_final_alert_label",
        "no_augment_final_alert_label",
        "default_alert_source_layer",
        "gating_label",
        "augmentation_label",
        "risk_bucket",
        "risk_score",
        "certainty_score",
        "conflict_score",
        "evidence_support_score",
        "missing_origin_or_path",
    ]
    changed_cols = [c for c in changed_cols if c in changed_default_joint.columns]
    changed_default_joint.sort_values(
        ["default_final_alert_label", "no_gate_no_augment_final_alert_label", "risk_score"],
        ascending=[True, True, False],
    ).head(args.topk_samples).to_csv(
        output_dir / "e6b3_changed_default_vs_joint_samples.csv",
        index=False,
        encoding="utf-8-sig",
    )

    default_high = int(flow_map["default"]["final_high_count"])
    no_gate_high = int(flow_map["no_gate"]["final_high_count"])
    no_augment_high = int(flow_map["no_augment"]["final_high_count"])
    joint_high = int(flow_map["no_gate_no_augment"]["final_high_count"])

    default_certainty = float(
        quality_df.loc[quality_df["group"] == "default", "certainty_score_mean"].iloc[0]
        if (quality_df["group"] == "default").any()
        else 0.0
    )
    joint_certainty = float(
        quality_df.loc[quality_df["group"] == "no_gate_no_augment", "certainty_score_mean"].iloc[0]
        if (quality_df["group"] == "no_gate_no_augment").any()
        else 0.0
    )

    system_mode = choose_system_mode(
        default_high=default_high,
        no_gate_high=no_gate_high,
        no_augment_high=no_augment_high,
        joint_high=joint_high,
        default_certainty=default_certainty,
        joint_certainty=joint_certainty,
    )
    final_tag = choose_final_tag(system_mode)

    summary = {
        "run_id": run_id,
        "runs_root": str(runs_root.resolve()),
        "output_dir": str(output_dir.resolve()),
        "flow": {
            row["setting"]: {
                "total_events": int(row["total_events"]),
                "candidate_count": int(row["candidate_count"]),
                "scored_count": int(row["scored_count"]),
                "gated_count": int(row["gated_count"]),
                "final_high_count": int(row["final_high_count"]),
                "final_needs_count": int(row["final_needs_count"]),
                "final_low_count": int(row["final_low_count"]),
            }
            for row in flow_rows
        },
        "pairwise_deltas": pair_rows,
        "new_joint_high": {
            "vs_default_count": int(len(new_joint_vs_default)),
            "vs_no_augment_count": int(len(new_joint_vs_no_augment)),
            "vs_no_gate_count": int(len(new_joint_vs_no_gate)),
            "vs_default_source_dist": to_int_dict(
                new_default_df.get("default_final_alert_label", pd.Series(dtype=str)).fillna("").value_counts()
            ),
            "vs_no_augment_source_dist": to_int_dict(
                new_no_aug_df.get("no_augment_final_alert_label", pd.Series(dtype=str)).fillna("").value_counts()
            ),
            "from_default_needs": int(
                (new_default_df.get("default_final_alert_label", pd.Series(dtype=str)).fillna("") == "needs_review").sum()
            ),
            "from_default_low": int(
                (new_default_df.get("default_final_alert_label", pd.Series(dtype=str)).fillna("") == "low_priority_or_background").sum()
            ),
            "from_no_augment_needs": int(
                (new_no_aug_df.get("no_augment_final_alert_label", pd.Series(dtype=str)).fillna("") == "needs_review").sum()
            ),
            "from_no_augment_low": int(
                (new_no_aug_df.get("no_augment_final_alert_label", pd.Series(dtype=str)).fillna("") == "low_priority_or_background").sum()
            ),
        },
        "augmentation_default_snapshot": {
            "augment_input_uncertain": int(augment_summary.get("input_uncertain_rows", len(augmented))),
            "promoted_suspicious_count": int(augment_summary.get("promoted_suspicious_count", 0)),
            "retained_uncertain_count": int(augment_summary.get("retained_uncertain_count", 0)),
            "demoted_suspicious_count": int(augment_summary.get("demoted_suspicious_count", 0)),
        },
        "final_default_snapshot": {
            "high_priority_from_gating_count": int(final_report.get("high_priority_from_gating_count", 0)),
            "high_priority_from_augmentation_count": int(final_report.get("high_priority_from_augmentation_count", 0)),
            "missing_origin_or_path_in_high_priority": int(final_report.get("missing_origin_or_path_in_high_priority", 0)),
        },
        "system_mode": system_mode,
        "final_tag": final_tag,
    }
    (output_dir / "e6b3_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"run_id={run_id}")
    print(f"runs_root={runs_root.resolve().as_posix()}")
    print(f"output_dir={output_dir.resolve().as_posix()}")
    print(
        "high_counts "
        f"default={default_high} no_gate={no_gate_high} no_augment={no_augment_high} no_gate_no_augment={joint_high}"
    )
    print(
        "new_joint_high "
        f"vs_default={len(new_joint_vs_default)} vs_no_gate={len(new_joint_vs_no_gate)} vs_no_augment={len(new_joint_vs_no_augment)}"
    )
    print(
        "new_joint_high_sources "
        f"from_default_needs={summary['new_joint_high']['from_default_needs']} "
        f"from_default_low={summary['new_joint_high']['from_default_low']} "
        f"from_no_augment_needs={summary['new_joint_high']['from_no_augment_needs']} "
        f"from_no_augment_low={summary['new_joint_high']['from_no_augment_low']}"
    )
    print(f"system_mode={system_mode}")
    print(f"final_tag={final_tag}")


if __name__ == "__main__":
    main()
