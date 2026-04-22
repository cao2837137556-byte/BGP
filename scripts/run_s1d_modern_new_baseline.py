import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd


QUALITY_THRESHOLDS = {
    "clean_certainty_min": 80.0,
    "noisy_conflict_min": 5.0,
    "noisy_certainty_max_exclusive": 60.0,
}


def run_cmd(cmd: list[str], *, workdir: Path, log_path: Path) -> float:
    start = time.perf_counter()
    proc = subprocess.run(
        cmd,
        cwd=str(workdir),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    elapsed = time.perf_counter() - start
    log_path.write_text(
        "$ " + " ".join(cmd) + "\n\n" + proc.stdout + ("\n[stderr]\n" + proc.stderr if proc.stderr else ""),
        encoding="utf-8",
    )
    return elapsed


def maybe_run_cmd(
    *,
    cmd: list[str],
    workdir: Path,
    log_path: Path,
    expected_output: Path,
    force: bool,
) -> float:
    if expected_output.exists() and not force:
        log_path.write_text(f"[REUSE] {expected_output}\n", encoding="utf-8")
        return 0.0
    return run_cmd(cmd, workdir=workdir, log_path=log_path)


def load_existing_timings(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def to_bool_series(series: pd.Series) -> pd.Series:
    if series.empty:
        return pd.Series(dtype=bool)
    if series.dtype == bool:
        return series.fillna(False)
    lowered = series.astype(str).str.strip().str.lower()
    return lowered.isin({"1", "true", "yes", "y", "on"})


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


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_final_df(path: Path) -> pd.DataFrame:
    cols = [
        "event_id",
        "final_alert_label",
        "alert_source_layer",
        "certainty_score",
        "conflict_score",
        "missing_origin_or_path",
        "augmentation_label",
    ]
    df = pd.read_parquet(path, columns=cols)
    df["event_id"] = df["event_id"].fillna("").astype(str)
    df["final_alert_label"] = df["final_alert_label"].fillna("").astype(str)
    df["alert_source_layer"] = df["alert_source_layer"].fillna("").astype(str)
    df["augmentation_label"] = df["augmentation_label"].fillna("").astype(str)
    df["certainty_score"] = pd.to_numeric(df["certainty_score"], errors="coerce").fillna(0.0)
    df["conflict_score"] = pd.to_numeric(df["conflict_score"], errors="coerce").fillna(0.0)
    df["missing_origin_or_path"] = to_bool_series(df["missing_origin_or_path"])
    return df


def load_run_counts(run_root: Path) -> dict:
    events = pd.read_parquet(run_root / "events" / "event_units.parquet", columns=["event_id"])
    candidates = pd.read_parquet(run_root / "candidates" / "candidate_events.parquet", columns=["candidate_flag"])
    candidate_count = int(to_bool_series(candidates["candidate_flag"]).sum())
    return {
        "total_events": int(len(events)),
        "candidate_count": candidate_count,
    }


def summarize_final(final_df: pd.DataFrame) -> dict:
    counts = final_df["final_alert_label"].value_counts().to_dict()
    high_df = final_df[final_df["final_alert_label"] == "high_priority_alert"].copy()
    if not high_df.empty:
        high_df["quality_bucket"] = classify_quality_bucket(high_df)
    else:
        high_df["quality_bucket"] = pd.Series(dtype="object")
    return {
        "final_high": int(counts.get("high_priority_alert", 0)),
        "final_needs": int(counts.get("needs_review", 0)),
        "final_low": int(counts.get("low_priority_or_background", 0)),
        "high_certainty_mean": float(high_df["certainty_score"].mean()) if len(high_df) else 0.0,
        "high_conflict_mean": float(high_df["conflict_score"].mean()) if len(high_df) else 0.0,
        "high_missing_rate": float(high_df["missing_origin_or_path"].mean()) if len(high_df) else 0.0,
        "clean_high": int((high_df["quality_bucket"] == "clean-high").sum()),
        "fragile_high": int((high_df["quality_bucket"] == "fragile-high").sum()),
        "noisy_high": int((high_df["quality_bucket"] == "noisy-high").sum()),
        "gating_likely_malicious_to_high": int(
            ((final_df["final_alert_label"] == "high_priority_alert") & (final_df["alert_source_layer"] == "gating_likely_malicious")).sum()
        ),
        "augmentation_promoted_to_high": int(
            ((final_df["final_alert_label"] == "high_priority_alert") & (final_df["alert_source_layer"] == "augmentation_promoted")).sum()
        ),
    }


def gating_high_ids(final_df: pd.DataFrame) -> set[str]:
    return set(
        final_df.loc[
            (final_df["final_alert_label"] == "high_priority_alert")
            & (final_df["alert_source_layer"] == "gating_likely_malicious"),
            "event_id",
        ].astype(str)
    )


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="S1-D modern rerun with augment A1_missing_block profile.")
    ap.add_argument("--workdir", default=".")
    ap.add_argument("--modern-run-id", default="s1a_expanded_v02_pilot_60m_april16")
    ap.add_argument("--historical-run-id", default="e9a_expanded_v01_rostelecom_20170426")
    ap.add_argument("--s1a-output-dir", default="outputs/s1a_modern_2024_pilot_60m_v02")
    ap.add_argument("--s1c-output-dir", default="outputs/s1c_augment_tightening_v01")
    ap.add_argument("--output-dir", default="outputs/s1d_modern_new_baseline_v01")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    workdir = Path(args.workdir).resolve()
    output_dir = (workdir / args.output_dir).resolve()
    ensure_dir(output_dir)

    modern_run_root = workdir / "data" / "runs" / args.modern_run_id
    hist_run_root = workdir / "data" / "runs" / args.historical_run_id
    modern_out_aug = output_dir / "modern_rerun" / "augmentation"
    modern_out_final = output_dir / "modern_rerun" / "final"
    hist_out_aug = output_dir / "historical_spotcheck" / "augmentation"
    hist_out_final = output_dir / "historical_spotcheck" / "final"
    timings_path = output_dir / "s1d_stage_timings.json"
    timings = load_existing_timings(timings_path)
    ensure_dir(modern_out_aug)
    ensure_dir(modern_out_final)
    ensure_dir(hist_out_aug)
    ensure_dir(hist_out_final)

    augment_elapsed = maybe_run_cmd(
        cmd=[
            sys.executable,
            "scripts/augment_uncertain_candidates.py",
            "--run-id",
            args.modern_run_id,
            "--gating",
            str(modern_run_root / "gating" / "gated_candidates.parquet"),
            "--events",
            str(modern_run_root / "events" / "event_units.parquet"),
            "--baseline-prefix",
            str(modern_run_root / "baseline" / "baseline_prefix.parquet"),
            "--baseline-prefix-origin",
            str(modern_run_root / "baseline" / "baseline_prefix_origin.parquet"),
            "--baseline-path",
            str(modern_run_root / "baseline" / "baseline_path.parquet"),
            "--profile",
            "modern_missing_block",
            "--output-dir",
            str(modern_out_aug),
            "--overwrite",
            "true",
        ],
        workdir=workdir,
        log_path=output_dir / "modern_augment.log",
        expected_output=modern_out_aug / "augmented_candidates.parquet",
        force=args.force,
    )
    if augment_elapsed == 0.0:
        augment_elapsed = float(timings.get("modern_augment_seconds", 0.0))
    else:
        timings["modern_augment_seconds"] = augment_elapsed

    final_elapsed = maybe_run_cmd(
        cmd=[
            sys.executable,
            "scripts/build_final_alerts_streaming.py",
            "--run-id",
            args.modern_run_id,
            "--scores",
            str(modern_run_root / "scores" / "scored_candidates.parquet"),
            "--gating",
            str(modern_run_root / "gating" / "gated_candidates.parquet"),
            "--augmentation",
            str(modern_out_aug / "augmented_candidates.parquet"),
            "--output-dir",
            str(modern_out_final),
            "--overwrite",
            "true",
        ],
        workdir=workdir,
        log_path=output_dir / "modern_final.log",
        expected_output=modern_out_final / "final_alerts.parquet",
        force=args.force,
    )
    if final_elapsed == 0.0:
        final_elapsed = float(timings.get("modern_final_seconds", 0.0))
    else:
        timings["modern_final_seconds"] = final_elapsed

    hist_augment_elapsed = maybe_run_cmd(
        cmd=[
            sys.executable,
            "scripts/augment_uncertain_candidates.py",
            "--run-id",
            args.historical_run_id,
            "--gating",
            str(hist_run_root / "gating" / "gated_candidates.parquet"),
            "--events",
            str(hist_run_root / "events" / "event_units.parquet"),
            "--baseline-prefix",
            str(hist_run_root / "baseline" / "baseline_prefix.parquet"),
            "--baseline-prefix-origin",
            str(hist_run_root / "baseline" / "baseline_prefix_origin.parquet"),
            "--baseline-path",
            str(hist_run_root / "baseline" / "baseline_path.parquet"),
            "--profile",
            "modern_missing_block",
            "--output-dir",
            str(hist_out_aug),
            "--overwrite",
            "true",
        ],
        workdir=workdir,
        log_path=output_dir / "historical_augment.log",
        expected_output=hist_out_aug / "augmented_candidates.parquet",
        force=args.force,
    )
    if hist_augment_elapsed == 0.0:
        hist_augment_elapsed = float(timings.get("historical_spotcheck_augment_seconds", 0.0))
    else:
        timings["historical_spotcheck_augment_seconds"] = hist_augment_elapsed

    hist_final_elapsed = maybe_run_cmd(
        cmd=[
            sys.executable,
            "scripts/build_final_alerts.py",
            "--run-id",
            args.historical_run_id,
            "--scores",
            str(hist_run_root / "scores" / "scored_candidates.parquet"),
            "--gating",
            str(hist_run_root / "gating" / "gated_candidates.parquet"),
            "--augmentation",
            str(hist_out_aug / "augmented_candidates.parquet"),
            "--output-dir",
            str(hist_out_final),
            "--overwrite",
            "true",
        ],
        workdir=workdir,
        log_path=output_dir / "historical_final.log",
        expected_output=hist_out_final / "final_alerts.parquet",
        force=args.force,
    )
    if hist_final_elapsed == 0.0:
        hist_final_elapsed = float(timings.get("historical_spotcheck_final_seconds", 0.0))
    else:
        timings["historical_spotcheck_final_seconds"] = hist_final_elapsed

    timings_path.write_text(json.dumps(timings, ensure_ascii=False, indent=2), encoding="utf-8")

    s1a_results = pd.read_csv(workdir / args.s1a_output_dir / "s1a_modern_2024_results.csv")
    s1a_expanded = s1a_results[s1a_results["setting"] == "expanded_collectors"].iloc[0].to_dict()
    s1c_results = pd.read_csv(workdir / args.s1c_output_dir / "s1c_augment_tightening_results.csv")
    s1c_a1 = s1c_results[s1c_results["variant"] == "A1_missing_block"].iloc[0].to_dict()

    modern_counts = load_run_counts(modern_run_root)
    modern_original_final = load_final_df(modern_run_root / "final" / "final_alerts.parquet")
    modern_rerun_final = load_final_df(modern_out_final / "final_alerts.parquet")
    modern_aug_summary = read_json(modern_out_aug / "augmentation_summary.json")
    modern_final_summary = summarize_final(modern_rerun_final)

    hist_original_final = load_final_df(hist_run_root / "final" / "final_alerts.parquet")
    hist_rerun_final = load_final_df(hist_out_final / "final_alerts.parquet")
    hist_aug_summary = read_json(hist_out_aug / "augmentation_summary.json")

    modern_r0_gate_ids = gating_high_ids(modern_original_final)
    modern_new_gate_ids = gating_high_ids(modern_rerun_final)
    retained_gate_ratio = (len(modern_r0_gate_ids & modern_new_gate_ids) / len(modern_r0_gate_ids)) if modern_r0_gate_ids else 1.0
    gate_high_lost_count = len(modern_r0_gate_ids - modern_new_gate_ids)

    hist_original_high_ids = set(hist_original_final.loc[hist_original_final["final_alert_label"] == "high_priority_alert", "event_id"].astype(str))
    hist_rerun_high_ids = set(hist_rerun_final.loc[hist_rerun_final["final_alert_label"] == "high_priority_alert", "event_id"].astype(str))
    hist_high_dropped = len(hist_original_high_ids - hist_rerun_high_ids)
    hist_merged = hist_original_final[
        ["event_id", "final_alert_label", "alert_source_layer", "missing_origin_or_path", "augmentation_label"]
    ].merge(
        hist_rerun_final[
            ["event_id", "final_alert_label", "alert_source_layer", "missing_origin_or_path", "augmentation_label"]
        ].rename(
            columns={
                "final_alert_label": "rerun_final_alert_label",
                "alert_source_layer": "rerun_alert_source_layer",
                "missing_origin_or_path": "rerun_missing_origin_or_path",
                "augmentation_label": "rerun_augmentation_label",
            }
        ),
        on="event_id",
        how="inner",
    )
    hist_changed_df = hist_merged[hist_merged["final_alert_label"] != hist_merged["rerun_final_alert_label"]].copy()
    hist_changed = int(len(hist_changed_df))
    hist_original_gate_ids = gating_high_ids(hist_original_final)
    hist_rerun_gate_ids = gating_high_ids(hist_rerun_final)
    hist_gate_retained_ratio = (len(hist_original_gate_ids & hist_rerun_gate_ids) / len(hist_original_gate_ids)) if hist_original_gate_ids else 1.0
    hist_change_all_aug_to_needs = bool(
        len(hist_changed_df) > 0
        and (
            (hist_changed_df["final_alert_label"] == "high_priority_alert")
            & (hist_changed_df["rerun_final_alert_label"] == "needs_review")
            & (hist_changed_df["alert_source_layer"] == "augmentation_promoted")
            & (hist_changed_df["rerun_alert_source_layer"] == "gating_uncertain")
            & (hist_changed_df["missing_origin_or_path"] == True)
        ).all()
    )
    hist_spot_check_passed = hist_high_dropped == 0 and hist_changed == 0

    compare_rows = [
        {
            "setting": "S1-A_original",
            "total_events": int(s1a_expanded["total_events"]),
            "candidate_count": int(s1a_expanded["candidate_count"]),
            "final_high": int(s1a_expanded["final_high"]),
            "final_needs": int(s1a_expanded["final_needs"]),
            "final_low": int(s1a_expanded["final_low"]),
            "high_missing_rate": float(s1a_expanded["high_missing_rate"]),
            "high_conflict_mean": float(s1a_expanded["high_conflict_mean"]),
            "gating_likely_malicious_to_high": int((modern_original_final["final_alert_label"].eq("high_priority_alert") & modern_original_final["alert_source_layer"].eq("gating_likely_malicious")).sum()),
            "augmentation_promoted_to_high": int((modern_original_final["final_alert_label"].eq("high_priority_alert") & modern_original_final["alert_source_layer"].eq("augmentation_promoted")).sum()),
        },
        {
            "setting": "S1-C_A1_offline",
            "total_events": int(modern_counts["total_events"]),
            "candidate_count": int(modern_counts["candidate_count"]),
            "final_high": int(s1c_a1["final_high"]),
            "final_needs": int(s1c_a1["final_needs"]),
            "final_low": int(s1c_a1["final_low"]),
            "high_missing_rate": float(s1c_a1["high_missing_rate"]),
            "high_conflict_mean": float(s1c_a1["high_conflict_mean"]),
            "gating_likely_malicious_to_high": int(s1c_a1["gating_likely_malicious_to_high"]),
            "augmentation_promoted_to_high": int(s1c_a1["augmentation_promoted_to_high"]),
        },
        {
            "setting": "S1-D_end_to_end",
            "total_events": int(modern_counts["total_events"]),
            "candidate_count": int(modern_counts["candidate_count"]),
            "final_high": int(modern_final_summary["final_high"]),
            "final_needs": int(modern_final_summary["final_needs"]),
            "final_low": int(modern_final_summary["final_low"]),
            "high_missing_rate": float(modern_final_summary["high_missing_rate"]),
            "high_conflict_mean": float(modern_final_summary["high_conflict_mean"]),
            "gating_likely_malicious_to_high": int(modern_final_summary["gating_likely_malicious_to_high"]),
            "augmentation_promoted_to_high": int(modern_final_summary["augmentation_promoted_to_high"]),
        },
    ]
    compare_df = pd.DataFrame(compare_rows)
    compare_df.to_csv(output_dir / "s1d_three_way_compare.csv", index=False, encoding="utf-8-sig")

    spot_row = {
        "historical_run_id": args.historical_run_id,
        "original_high": int((hist_original_final["final_alert_label"] == "high_priority_alert").sum()),
        "rerun_high": int((hist_rerun_final["final_alert_label"] == "high_priority_alert").sum()),
        "high_dropped": hist_high_dropped,
        "changed_labels": hist_changed,
        "blocked_missing_promotion_count": int(hist_aug_summary.get("blocked_missing_promotion_count", 0)),
        "gate_high_retained_ratio": hist_gate_retained_ratio,
        "all_changes_are_missing_aug_high_to_needs": hist_change_all_aug_to_needs,
        "spot_check_passed": hist_spot_check_passed,
    }
    pd.DataFrame([spot_row]).to_csv(output_dir / "s1d_historical_spot_check.csv", index=False, encoding="utf-8-sig")

    modern_alignment = {
        "target_final_high_s1c_a1": int(s1c_a1["final_high"]),
        "actual_final_high_s1d": int(modern_final_summary["final_high"]),
        "final_high_matches_s1c_a1": int(modern_final_summary["final_high"]) == int(s1c_a1["final_high"]),
        "target_noisy_high_s1c_a1": int(s1c_a1["noisy_high"]),
        "actual_noisy_high_s1d": int(modern_final_summary["noisy_high"]),
        "high_missing_rate_zero": float(modern_final_summary["high_missing_rate"]) == 0.0,
    }
    (output_dir / "s1d_alignment_check.json").write_text(json.dumps(modern_alignment, ensure_ascii=False, indent=2), encoding="utf-8")

    report_lines = [
        "# S1-D Modern New Baseline",
        "",
        "## A. New Steady-State Funnel",
        "",
        f"- total_events: {modern_counts['total_events']}",
        f"- candidate_count: {modern_counts['candidate_count']}",
        f"- final_high: {modern_final_summary['final_high']}",
        f"- final_needs: {modern_final_summary['final_needs']}",
        f"- final_low: {modern_final_summary['final_low']}",
        "",
        "## B. Alignment With S1-C A1",
        "",
        f"- final_high_target_s1c_a1: {modern_alignment['target_final_high_s1c_a1']}",
        f"- final_high_actual_s1d: {modern_alignment['actual_final_high_s1d']}",
        f"- final_high_matches_s1c_a1: {modern_alignment['final_high_matches_s1c_a1']}",
        f"- high_missing_rate: {modern_final_summary['high_missing_rate']:.4f}",
        f"- noisy_high: {modern_final_summary['noisy_high']}",
        "",
        "## C. Protection Metrics",
        "",
        f"- gating_likely_malicious_to_high: {modern_final_summary['gating_likely_malicious_to_high']}",
        f"- r0_gating_high_retained_ratio: {retained_gate_ratio:.4f}",
        f"- gate_high_lost_count: {gate_high_lost_count}",
        f"- augmentation_blocked_missing_promotion_count: {modern_aug_summary.get('blocked_missing_promotion_count', 0)}",
        "",
        "## D. Three-Way Comparison",
        "",
        "| setting | total_events | candidate_count | final_high | final_needs | final_low | high_missing_rate | high_conflict_mean | gating_likely_malicious_to_high | augmentation_promoted_to_high |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for _, row in compare_df.iterrows():
        report_lines.append(
            f"| {row['setting']} | {int(row['total_events'])} | {int(row['candidate_count'])} | {int(row['final_high'])} | "
            f"{int(row['final_needs'])} | {int(row['final_low'])} | {float(row['high_missing_rate']):.4f} | "
            f"{float(row['high_conflict_mean']):.4f} | {int(row['gating_likely_malicious_to_high'])} | {int(row['augmentation_promoted_to_high'])} |"
        )
    report_lines.extend(
        [
            "",
            "## E. Performance",
            "",
            f"- modern_augment_seconds: {augment_elapsed:.2f}",
            f"- modern_final_seconds: {final_elapsed:.2f}",
            f"- historical_spotcheck_augment_seconds: {hist_augment_elapsed:.2f}",
            f"- historical_spotcheck_final_seconds: {hist_final_elapsed:.2f}",
            "- new_performance_bottleneck: none observed in augment/final rerun; this stage remains much cheaper than upstream modern collection/scoring.",
            "",
            "## Historical Spot-Check",
            "",
            f"- historical_run_id: {args.historical_run_id}",
            f"- original_high: {spot_row['original_high']}",
            f"- rerun_high: {spot_row['rerun_high']}",
            f"- high_dropped: {spot_row['high_dropped']}",
            f"- changed_labels: {spot_row['changed_labels']}",
            f"- blocked_missing_promotion_count: {spot_row['blocked_missing_promotion_count']}",
            f"- gate_high_retained_ratio: {spot_row['gate_high_retained_ratio']:.4f}",
            f"- all_changes_are_missing_aug_high_to_needs: {spot_row['all_changes_are_missing_aug_high_to_needs']}",
            f"- spot_check_passed: {spot_row['spot_check_passed']}",
        ]
    )
    if hist_spot_check_passed:
        report_lines.append("- 2017 minimal spot-check passed")
    (output_dir / "s1d_modern_new_baseline_report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    print(f"output_dir={output_dir}")
    print(f"modern_final_high={modern_final_summary['final_high']}")
    print(f"modern_high_missing_rate={modern_final_summary['high_missing_rate']:.4f}")
    print(f"modern_noisy_high={modern_final_summary['noisy_high']}")
    print(f"modern_gating_likely_malicious_to_high={modern_final_summary['gating_likely_malicious_to_high']}")
    print(f"modern_augmentation_promoted_to_high={modern_final_summary['augmentation_promoted_to_high']}")
    print(f"r0_gating_high_retained_ratio={retained_gate_ratio:.4f}")
    print(f"historical_spot_check_passed={hist_spot_check_passed}")


if __name__ == "__main__":
    main()
