import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from run_e8c_known_events_test import CAIDA_REL_DEFAULT, run_cmd, to_bool


def load_plan(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def pick_profile(plan: dict[str, Any], profile_name: str) -> dict[str, Any]:
    for profile in plan.get("profiles", []):
        if str(profile.get("profile_name", "")).strip() == profile_name:
            return profile
    raise SystemExit(f"profile not found in plan: {profile_name}")


def read_parquet_or_empty(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def to_bool_series(series: pd.Series) -> pd.Series:
    if series.empty:
        return pd.Series(dtype=bool)
    if series.dtype == bool:
        return series.fillna(False)
    lowered = series.astype(str).str.strip().str.lower()
    return lowered.isin({"1", "true", "yes", "y", "on"})


def parse_collectors(raw: str) -> list[str]:
    return [item.strip() for item in str(raw).split(",") if item.strip()]


def expected_chunk_count(minutes: int, chunk_minutes: int) -> int:
    return (minutes + chunk_minutes - 1) // chunk_minutes


def count_raw_outputs(run_dir: Path) -> int:
    total = 0
    for path in run_dir.glob("collector=*/date=*/*.parquet"):
        if "__rel" in path.name:
            continue
        total += 1
    return total


def count_rel_outputs(run_dir: Path) -> int:
    return sum(1 for _ in run_dir.glob("collector=*/date=*/*__rel.parquet"))


def has_downstream_outputs(run_dir: Path) -> bool:
    return any((run_dir / name).exists() for name in ["events", "baseline", "candidates", "scores", "gating", "augmentation", "final"])


def run_pipeline_for_window(
    *,
    workdir: Path,
    runs_root: Path,
    run_id: str,
    collect_from: str,
    minutes: int,
    chunk_minutes: int,
    collectors: str,
    max_rows: int,
    caida_rel: str,
    force: bool,
    marker_dir_name: str,
    augment_profile: str,
    augment_script: str,
) -> str:
    run_dir = runs_root / run_id
    final_path = run_dir / "final" / "final_alerts.parquet"
    collectors_list = parse_collectors(collectors)
    expected_outputs = len(collectors_list) * expected_chunk_count(minutes, chunk_minutes)
    raw_ready = run_dir.exists() and any(run_dir.glob("collector=*"))
    raw_outputs = count_raw_outputs(run_dir) if raw_ready else 0
    rel_outputs = count_rel_outputs(run_dir) if raw_ready else 0
    collection_complete = raw_outputs >= expected_outputs
    rel_ready = rel_outputs >= expected_outputs

    if final_path.exists() and not force:
        print(f"[SKIP] reuse existing run: {run_id}")
        return run_id

    if not collection_complete or force:
        run_dir.mkdir(parents=True, exist_ok=True)
        marker_dir = workdir / "data" / marker_dir_name
        marker_dir.mkdir(parents=True, exist_ok=True)

        collect_cmd = [
            sys.executable,
            "scripts/run.py",
            "--minutes",
            str(minutes),
            "--chunk-minutes",
            str(chunk_minutes),
            "--collectors",
            collectors,
            "--record-type",
            "updates",
            "--format",
            "parquet",
            "--max-rows",
            str(max_rows),
            "--run-id",
            run_id,
            "--marker-dir",
            str(marker_dir),
            "--no-label-caida",
        ]
        if raw_ready and raw_outputs > 0 and not force:
            print(f"[RESUME] incomplete raw collection: {run_id} ({raw_outputs}/{expected_outputs})")
            collect_cmd.extend(["--resume", "--bootstrap-from", collect_from])
        else:
            collect_cmd.extend(["--from", collect_from])

        run_cmd(collect_cmd, workdir=workdir)
        raw_outputs = count_raw_outputs(run_dir)
        collection_complete = raw_outputs >= expected_outputs
        rel_outputs = count_rel_outputs(run_dir)
        rel_ready = rel_outputs >= expected_outputs

    if not collection_complete:
        raise SystemExit(f"incomplete raw collection after run.py: {run_id} ({raw_outputs}/{expected_outputs})")

    if not rel_ready:
        if has_downstream_outputs(run_dir):
            raise SystemExit(f"cannot safely relabel run with downstream outputs already present: {run_id}")
        print(f"[LABEL] annotate CAIDA once for completed raw collection: {run_id}")
        run_cmd(
            [
                sys.executable,
                "scripts/04_annotate_caida_rel.py",
                "--run-dir",
                str(run_dir),
                "--caida-rel",
                caida_rel,
                "--suffix",
                "__rel",
            ],
            workdir=workdir,
        )
    else:
        print(f"[REUSE] existing CAIDA-labeled raw collection: {run_id}")

    events_path = run_dir / "events" / "event_units.parquet"
    baseline_dir = run_dir / "baseline"
    candidates_dir = run_dir / "candidates"
    scores_dir = run_dir / "scores"
    gating_dir = run_dir / "gating"
    aug_dir = run_dir / "augmentation"
    final_dir = run_dir / "final"

    run_cmd(
        [
            sys.executable,
            "scripts/build_event_units.py",
            "--run-id",
            run_id,
            "--input",
            str(run_dir),
            "--output",
            str(events_path),
            "--window-sec",
            "300",
            "--prefer-rel",
            "true",
        ],
        workdir=workdir,
    )
    run_cmd(
        [
            sys.executable,
            "scripts/build_historical_baseline.py",
            "--run-id",
            run_id,
            "--input",
            str(events_path),
            "--output-dir",
            str(baseline_dir),
            "--min-events",
            "1",
            "--overwrite",
            "true",
        ],
        workdir=workdir,
    )
    run_cmd(
        [
            sys.executable,
            "scripts/build_weak_candidates_streaming.py",
            "--run-id",
            run_id,
            "--events",
            str(events_path),
            "--baseline-prefix",
            str(baseline_dir / "baseline_prefix.parquet"),
            "--baseline-prefix-origin",
            str(baseline_dir / "baseline_prefix_origin.parquet"),
            "--baseline-path",
            str(baseline_dir / "baseline_path.parquet"),
            "--output-dir",
            str(candidates_dir),
            "--min-weak-rules",
            "2",
            "--overwrite",
            "true",
        ],
        workdir=workdir,
    )
    run_cmd(
        [
            sys.executable,
            "scripts/score_weak_candidates_streaming.py",
            "--run-id",
            run_id,
            "--candidates",
            str(candidates_dir / "candidate_events.parquet"),
            "--baseline-prefix",
            str(baseline_dir / "baseline_prefix.parquet"),
            "--baseline-prefix-origin",
            str(baseline_dir / "baseline_prefix_origin.parquet"),
            "--baseline-path",
            str(baseline_dir / "baseline_path.parquet"),
            "--output-dir",
            str(scores_dir),
            "--overwrite",
            "true",
        ],
        workdir=workdir,
    )
    run_cmd(
        [
            sys.executable,
        "scripts/gate_scored_candidates_streaming.py",
            "--run-id",
            run_id,
            "--scores",
            str(scores_dir / "scored_candidates.parquet"),
            "--output-dir",
            str(gating_dir),
            "--overwrite",
            "true",
        ],
        workdir=workdir,
    )
    run_cmd(
        [
            sys.executable,
            augment_script,
            "--run-id",
            run_id,
            "--events",
            str(events_path),
            "--gating",
            str(gating_dir / "gated_candidates.parquet"),
            "--baseline-prefix",
            str(baseline_dir / "baseline_prefix.parquet"),
            "--baseline-prefix-origin",
            str(baseline_dir / "baseline_prefix_origin.parquet"),
            "--baseline-path",
            str(baseline_dir / "baseline_path.parquet"),
            "--profile",
            augment_profile,
            "--output-dir",
            str(aug_dir),
            "--overwrite",
            "true",
        ],
        workdir=workdir,
    )
    run_cmd(
        [
            sys.executable,
            "scripts/build_final_alerts_streaming.py",
            "--run-id",
            run_id,
            "--scores",
            str(scores_dir / "scored_candidates.parquet"),
            "--gating",
            str(gating_dir / "gated_candidates.parquet"),
            "--augmentation",
            str(aug_dir / "augmented_candidates.parquet"),
            "--output-dir",
            str(final_dir),
            "--overwrite",
            "true",
        ],
        workdir=workdir,
    )
    return run_id


def collector_coverage(events_df: pd.DataFrame) -> pd.DataFrame:
    if events_df.empty or "collector" not in events_df.columns:
        return pd.DataFrame(
            columns=[
                "collector",
                "event_rows",
                "unique_prefixes",
                "unique_origins",
                "avg_as_path_len",
                "avg_collector_count",
                "avg_visibility_count",
            ]
        )

    agg = (
        events_df.groupby("collector", dropna=False)
        .agg(
            event_rows=("event_id", "count"),
            unique_prefixes=("prefix", "nunique"),
            unique_origins=("origin_as", "nunique"),
            avg_as_path_len=("as_path_len", "mean"),
            avg_collector_count=("collector_count", "mean"),
            avg_visibility_count=("visibility_count", "mean"),
        )
        .reset_index()
        .sort_values(["event_rows", "collector"], ascending=[False, True])
    )
    return agg


def summarize_run(setting: str, run_id: str, configured_collectors: str, run_dir: Path) -> tuple[dict[str, Any], pd.DataFrame]:
    events_df = read_parquet_or_empty(run_dir / "events" / "event_units.parquet")
    candidates_df = read_parquet_or_empty(run_dir / "candidates" / "candidate_events.parquet")
    scored_df = read_parquet_or_empty(run_dir / "scores" / "scored_candidates.parquet")
    gated_df = read_parquet_or_empty(run_dir / "gating" / "gated_candidates.parquet")
    final_df = read_parquet_or_empty(run_dir / "final" / "final_alerts.parquet")

    candidate_count = int(to_bool_series(candidates_df.get("candidate_flag", pd.Series(dtype=bool))).sum()) if not candidates_df.empty else 0

    label_counts = {"high": 0, "needs": 0, "low": 0}
    if not final_df.empty and "final_alert_label" in final_df.columns:
        raw_counts = final_df["final_alert_label"].value_counts().to_dict()
        label_counts = {
            "high": int(raw_counts.get("high_priority_alert", 0)),
            "needs": int(raw_counts.get("needs_review", 0)),
            "low": int(raw_counts.get("low_priority_or_background", 0)),
        }

    high_df = final_df[final_df.get("final_alert_label", pd.Series(dtype=str)).astype(str) == "high_priority_alert"].copy() if not final_df.empty else pd.DataFrame()
    collector_df = collector_coverage(events_df)

    row = {
        "setting": setting,
        "run_id": run_id,
        "configured_collectors": configured_collectors,
        "configured_collectors_count": len([x for x in configured_collectors.split(",") if x.strip()]),
        "observed_collectors_count": int(events_df["collector"].nunique()) if not events_df.empty and "collector" in events_df.columns else 0,
        "total_events": int(len(events_df)),
        "candidate_rows": int(len(candidates_df)),
        "candidate_count": candidate_count,
        "candidate_ratio_vs_events": (candidate_count / len(events_df)) if len(events_df) else 0.0,
        "scored_count": int(len(scored_df)),
        "gated_count": int(len(gated_df)),
        "final_high": label_counts["high"],
        "final_needs": label_counts["needs"],
        "final_low": label_counts["low"],
        "high_ratio_vs_scored": (label_counts["high"] / len(scored_df)) if len(scored_df) else 0.0,
        "needs_ratio_vs_scored": (label_counts["needs"] / len(scored_df)) if len(scored_df) else 0.0,
        "avg_collector_count": float(pd.to_numeric(events_df.get("collector_count", pd.Series(dtype=float)), errors="coerce").mean()) if not events_df.empty else 0.0,
        "avg_visibility_count": float(pd.to_numeric(events_df.get("visibility_count", pd.Series(dtype=float)), errors="coerce").mean()) if not events_df.empty else 0.0,
        "avg_as_path_len": float(pd.to_numeric(events_df.get("as_path_len", pd.Series(dtype=float)), errors="coerce").mean()) if not events_df.empty else 0.0,
        "unique_prefixes": int(events_df["prefix"].nunique()) if not events_df.empty and "prefix" in events_df.columns else 0,
        "unique_origins": int(events_df["origin_as"].nunique()) if not events_df.empty and "origin_as" in events_df.columns else 0,
        "high_certainty_mean": float(pd.to_numeric(high_df.get("certainty_score", pd.Series(dtype=float)), errors="coerce").mean()) if not high_df.empty else 0.0,
        "high_conflict_mean": float(pd.to_numeric(high_df.get("conflict_score", pd.Series(dtype=float)), errors="coerce").mean()) if not high_df.empty else 0.0,
        "high_missing_rate": float(to_bool_series(high_df.get("missing_origin_or_path", pd.Series(dtype=bool))).mean()) if not high_df.empty else 0.0,
    }
    return row, collector_df


def build_markdown(
    plan: dict[str, Any],
    profile: dict[str, Any],
    results_df: pd.DataFrame,
    summary: dict[str, Any],
) -> str:
    lines: list[str] = []
    lines.append("# S1-A Modern 2024 Pilot")
    lines.append("")
    lines.append("Scope: modern-data pilot for 2024 under the unchanged layered pipeline. Only collector visibility and time window scale are changed.")
    lines.append("")
    lines.append("## Plan")
    lines.append("")
    lines.append(f"- plan_name: {plan.get('plan_name', '')}")
    lines.append(f"- profile_name: {profile.get('profile_name', '')}")
    lines.append(f"- description: {profile.get('description', '')}")
    lines.append(f"- collect_from: {profile.get('collect_from', '')}")
    lines.append(f"- minutes: {profile.get('minutes', '')}")
    lines.append(f"- chunk_minutes: {profile.get('chunk_minutes', '')}")
    lines.append("")
    lines.append("## Run Table")
    lines.append("")
    lines.append("| setting | run_id | collectors | observed_collectors | total_events | candidate_count | candidate_ratio | scored_count | final_high | final_needs | final_low | high_certainty_mean | high_conflict_mean | high_missing_rate |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for _, r in results_df.iterrows():
        lines.append(
            f"| {r['setting']} | {r['run_id']} | {int(r['configured_collectors_count'])} | {int(r['observed_collectors_count'])} | "
            f"{int(r['total_events'])} | {int(r['candidate_count'])} | {float(r['candidate_ratio_vs_events']):.4f} | "
            f"{int(r['scored_count'])} | {int(r['final_high'])} | {int(r['final_needs'])} | {int(r['final_low'])} | "
            f"{float(r['high_certainty_mean']):.2f} | {float(r['high_conflict_mean']):.2f} | {float(r['high_missing_rate']):.4f} |"
        )
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    for key in [
        "baseline_run_id",
        "expanded_run_id",
        "baseline_total_events",
        "expanded_total_events",
        "baseline_candidate_count",
        "expanded_candidate_count",
        "baseline_final_high",
        "expanded_final_high",
        "baseline_final_needs",
        "expanded_final_needs",
        "baseline_final_low",
        "expanded_final_low",
    ]:
        lines.append(f"- {key}: {summary.get(key)}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="S1-A: modern 2024 pilot/full replay under the unchanged layered pipeline.")
    parser.add_argument("--plan", default="data/modern_2024/s1a_modern_2024_plan_v01.json")
    parser.add_argument("--profile", default="pilot_4h_april16")
    parser.add_argument("--output-dir", default="outputs/s1a_modern_2024_pilot_v01")
    parser.add_argument("--runs-root", default="data/runs")
    parser.add_argument("--baseline-run-prefix", default="s1a_baseline_v01")
    parser.add_argument("--expanded-run-prefix", default="s1a_expanded_v01")
    parser.add_argument("--caida-rel", default=CAIDA_REL_DEFAULT)
    parser.add_argument("--execute-baseline", default="false")
    parser.add_argument("--execute-expanded", default="false")
    parser.add_argument("--force-baseline", default="false")
    parser.add_argument("--force-expanded", default="false")
    parser.add_argument("--print-plan", default="false")
    parser.add_argument(
        "--augment-profile",
        default="default",
        help="Augment profile forwarded to augment_uncertain_candidates.py. default preserves historical behavior.",
    )
    parser.add_argument(
        "--augment-script",
        default="scripts/augment_uncertain_candidates.py",
        help="Augment script to run. Default preserves the historical implementation; S2 can pass the fast S1-F implementation.",
    )
    args = parser.parse_args()

    workdir = Path.cwd()
    runs_root = Path(args.runs_root)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    plan = load_plan(Path(args.plan))
    profile = pick_profile(plan, args.profile)

    plan_snapshot = {
        "plan_name": plan.get("plan_name", ""),
        "profile_name": profile.get("profile_name", ""),
        "description": profile.get("description", ""),
        "collect_from": profile.get("collect_from", ""),
        "minutes": int(profile.get("minutes", 0)),
        "chunk_minutes": int(profile.get("chunk_minutes", 5)),
        "max_rows": int(profile.get("max_rows", 50000)),
        "baseline_collectors": plan.get("baseline_collectors", ""),
        "expanded_collectors": plan.get("expanded_collectors", ""),
        "selection_reason": profile.get("selection_reason", ""),
    }
    (output_dir / "s1a_plan_snapshot.json").write_text(
        json.dumps(plan_snapshot, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if to_bool(args.print_plan):
        print(json.dumps(plan_snapshot, ensure_ascii=False, indent=2))
        return

    baseline_run_id = f"{args.baseline_run_prefix}_{args.profile}"
    expanded_run_id = f"{args.expanded_run_prefix}_{args.profile}"

    if to_bool(args.execute_baseline):
        baseline_run_id = run_pipeline_for_window(
            workdir=workdir,
            runs_root=runs_root,
            run_id=baseline_run_id,
            collect_from=profile["collect_from"],
            minutes=int(profile["minutes"]),
            chunk_minutes=int(profile["chunk_minutes"]),
            collectors=plan["baseline_collectors"],
            max_rows=int(profile["max_rows"]),
            caida_rel=args.caida_rel,
            force=to_bool(args.force_baseline),
            marker_dir_name="markers_s1a_baseline",
            augment_profile=args.augment_profile,
            augment_script=args.augment_script,
        )

    if to_bool(args.execute_expanded):
        expanded_run_id = run_pipeline_for_window(
            workdir=workdir,
            runs_root=runs_root,
            run_id=expanded_run_id,
            collect_from=profile["collect_from"],
            minutes=int(profile["minutes"]),
            chunk_minutes=int(profile["chunk_minutes"]),
            collectors=plan["expanded_collectors"],
            max_rows=int(profile["max_rows"]),
            caida_rel=args.caida_rel,
            force=to_bool(args.force_expanded),
            marker_dir_name="markers_s1a_expanded",
            augment_profile=args.augment_profile,
            augment_script=args.augment_script,
        )

    rows: list[dict[str, Any]] = []
    collector_tables: dict[str, pd.DataFrame] = {}
    for setting, run_id, collectors in [
        ("baseline_2collectors", baseline_run_id, plan["baseline_collectors"]),
        ("expanded_collectors", expanded_run_id, plan["expanded_collectors"]),
    ]:
        row, collector_df = summarize_run(setting, run_id, collectors, runs_root / run_id)
        rows.append(row)
        collector_tables[setting] = collector_df

    results_df = pd.DataFrame(rows)
    results_df.to_csv(output_dir / "s1a_modern_2024_results.csv", index=False, encoding="utf-8-sig")

    for setting, collector_df in collector_tables.items():
        collector_df.to_csv(output_dir / f"s1a_collector_coverage_{setting}.csv", index=False, encoding="utf-8-sig")

    baseline_row = results_df[results_df["setting"] == "baseline_2collectors"].iloc[0].to_dict()
    expanded_row = results_df[results_df["setting"] == "expanded_collectors"].iloc[0].to_dict()
    summary = {
        "plan_name": plan.get("plan_name", ""),
        "profile_name": profile.get("profile_name", ""),
        "baseline_run_id": baseline_run_id,
        "expanded_run_id": expanded_run_id,
        "baseline_total_events": int(baseline_row["total_events"]),
        "expanded_total_events": int(expanded_row["total_events"]),
        "baseline_candidate_count": int(baseline_row["candidate_count"]),
        "expanded_candidate_count": int(expanded_row["candidate_count"]),
        "baseline_final_high": int(baseline_row["final_high"]),
        "expanded_final_high": int(expanded_row["final_high"]),
        "baseline_final_needs": int(baseline_row["final_needs"]),
        "expanded_final_needs": int(expanded_row["final_needs"]),
        "baseline_final_low": int(baseline_row["final_low"]),
        "expanded_final_low": int(expanded_row["final_low"]),
        "total_events_delta": int(expanded_row["total_events"]) - int(baseline_row["total_events"]),
        "candidate_count_delta": int(expanded_row["candidate_count"]) - int(baseline_row["candidate_count"]),
        "final_high_delta": int(expanded_row["final_high"]) - int(baseline_row["final_high"]),
        "final_needs_delta": int(expanded_row["final_needs"]) - int(baseline_row["final_needs"]),
        "final_low_delta": int(expanded_row["final_low"]) - int(baseline_row["final_low"]),
        "baseline_high_certainty_mean": round(to_float(baseline_row["high_certainty_mean"]), 4),
        "expanded_high_certainty_mean": round(to_float(expanded_row["high_certainty_mean"]), 4),
        "baseline_high_conflict_mean": round(to_float(baseline_row["high_conflict_mean"]), 4),
        "expanded_high_conflict_mean": round(to_float(expanded_row["high_conflict_mean"]), 4),
        "baseline_high_missing_rate": round(to_float(baseline_row["high_missing_rate"]), 4),
        "expanded_high_missing_rate": round(to_float(expanded_row["high_missing_rate"]), 4),
    }
    (output_dir / "s1a_modern_2024_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "s1a_modern_2024_report.md").write_text(
        build_markdown(plan, profile, results_df, summary),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
