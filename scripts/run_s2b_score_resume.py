import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd


def run_cmd(cmd: list[str], *, cwd: Path) -> float:
    print("[CMD]", " ".join(cmd), flush=True)
    start = time.perf_counter()
    proc = subprocess.run(cmd, cwd=str(cwd))
    elapsed = time.perf_counter() - start
    if proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(cmd)}")
    return elapsed


def str2bool(value: str) -> bool:
    v = str(value).strip().lower()
    if v in {"1", "true", "yes", "y", "on"}:
        return True
    if v in {"0", "false", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"invalid boolean value: {value}")


def to_bool_series(series: pd.Series) -> pd.Series:
    if series.empty:
        return pd.Series(dtype=bool)
    if series.dtype == bool:
        return series.fillna(False)
    return series.astype(str).str.strip().str.lower().isin({"1", "true", "yes", "y", "on"})


def summarize_final(final_path: Path, events_path: Path, candidates_path: Path, scores_path: Path, gating_path: Path) -> dict:
    final_df = pd.read_parquet(final_path)
    events_count = len(pd.read_parquet(events_path, columns=["event_id"]))
    candidates = pd.read_parquet(candidates_path, columns=["candidate_flag"])
    scored_count = len(pd.read_parquet(scores_path, columns=["event_id"]))
    gated_count = len(pd.read_parquet(gating_path, columns=["event_id"]))
    label_counts = final_df["final_alert_label"].value_counts().to_dict()
    high_df = final_df[final_df["final_alert_label"] == "high_priority_alert"].copy()
    return {
        "total_events": int(events_count),
        "candidate_count": int(to_bool_series(candidates["candidate_flag"]).sum()),
        "scored_count": int(scored_count),
        "gated_count": int(gated_count),
        "final_high": int(label_counts.get("high_priority_alert", 0)),
        "final_needs": int(label_counts.get("needs_review", 0)),
        "final_low": int(label_counts.get("low_priority_or_background", 0)),
        "high_certainty_mean": float(pd.to_numeric(high_df.get("certainty_score", pd.Series(dtype=float)), errors="coerce").mean())
        if not high_df.empty
        else 0.0,
        "high_conflict_mean": float(pd.to_numeric(high_df.get("conflict_score", pd.Series(dtype=float)), errors="coerce").mean())
        if not high_df.empty
        else 0.0,
        "high_missing_rate": float(to_bool_series(high_df.get("missing_origin_or_path", pd.Series(dtype=bool))).mean())
        if not high_df.empty
        else 0.0,
        "gating_likely_malicious_to_high": int(
            (
                (final_df["final_alert_label"] == "high_priority_alert")
                & (final_df.get("alert_source_layer", pd.Series(dtype=str)).astype(str) == "gating_likely_malicious")
            ).sum()
        ),
        "augmentation_promoted_to_high": int(
            (
                (final_df["final_alert_label"] == "high_priority_alert")
                & (final_df.get("alert_source_layer", pd.Series(dtype=str)).astype(str) == "augmentation_promoted")
            ).sum()
        ),
    }


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_outputs(output_dir: Path, run_id: str, stage_seconds: dict, metrics: dict, score_summary: dict, bundle_path: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    downstream_rows = []
    for key, value in metrics.items():
        downstream_rows.append({"metric": key, "value": value})
    for key, value in stage_seconds.items():
        downstream_rows.append({"metric": f"{key}_seconds", "value": value})
    pd.DataFrame(downstream_rows).to_csv(output_dir / "s2b_downstream_summary.csv", index=False)

    summary = {
        "run_id": run_id,
        "stage_seconds": stage_seconds,
        "metrics": metrics,
        "score_summary": score_summary,
        "bundle_path": bundle_path,
    }
    (output_dir / "s2b_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    report = f"""# S2-B Score Resume Report

## Scope

- run_id: `{run_id}`
- bundle: `{bundle_path}`

## Metrics

| metric | value |
|---|---:|
| total_events | {metrics['total_events']} |
| candidate_count | {metrics['candidate_count']} |
| scored_count | {metrics['scored_count']} |
| gated_count | {metrics['gated_count']} |
| final_high | {metrics['final_high']} |
| final_needs | {metrics['final_needs']} |
| final_low | {metrics['final_low']} |
| high_certainty_mean | {metrics['high_certainty_mean']:.4f} |
| high_conflict_mean | {metrics['high_conflict_mean']:.4f} |
| high_missing_rate | {metrics['high_missing_rate']:.4f} |
| gating_likely_malicious_to_high | {metrics['gating_likely_malicious_to_high']} |
| augmentation_promoted_to_high | {metrics['augmentation_promoted_to_high']} |

## Score Summary

```json
{json.dumps(score_summary, ensure_ascii=False, indent=2)}
```

## Stage Seconds

```json
{json.dumps(stage_seconds, ensure_ascii=False, indent=2)}
```
"""
    (output_dir / "s2b_score_optimization_report.md").write_text(report, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Resume S2-A from score stage with fast checkpointable scorer.")
    parser.add_argument("--run-id", default="s2a_expanded_v01_pilot_6h_april16")
    parser.add_argument("--runs-root", default="data/runs")
    parser.add_argument("--output-dir", default="outputs/s2b_score_optimization_v01")
    parser.add_argument("--score-script", default="scripts/score_weak_candidates_streaming_fast.py")
    parser.add_argument("--augment-script", default="scripts/augment_uncertain_candidates_fast.py")
    parser.add_argument("--augment-profile", default="modern_missing_block")
    parser.add_argument("--score-batch-size", type=int, default=250000)
    parser.add_argument("--downstream-batch-size", type=int, default=100000)
    parser.add_argument("--score-resume", type=str2bool, default=True)
    parser.add_argument("--overwrite", type=str2bool, default=True)
    parser.add_argument("--bundle-name", default="s2b_score_optimization_bundle")
    args = parser.parse_args()

    workdir = Path.cwd()
    run_dir = Path(args.runs_root) / args.run_id
    events_path = run_dir / "events" / "event_units.parquet"
    baseline_dir = run_dir / "baseline"
    candidates_dir = run_dir / "candidates"
    scores_dir = run_dir / "scores"
    gating_dir = run_dir / "gating"
    aug_dir = run_dir / "augmentation"
    final_dir = run_dir / "final"
    output_dir = Path(args.output_dir)

    required = [
        events_path,
        candidates_dir / "candidate_events.parquet",
        baseline_dir / "baseline_prefix.parquet",
        baseline_dir / "baseline_prefix_origin.parquet",
        baseline_dir / "baseline_path.parquet",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit("required S2-A pre-score assets are missing: " + ", ".join(missing))

    stage_seconds: dict[str, float] = {}
    stage_seconds["score"] = run_cmd(
        [
            sys.executable,
            args.score_script,
            "--run-id",
            args.run_id,
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
            "--batch-size",
            str(args.score_batch_size),
            "--resume",
            str(args.score_resume).lower(),
            "--overwrite",
            str(args.overwrite).lower(),
        ],
        cwd=workdir,
    )
    stage_seconds["gate"] = run_cmd(
        [
            sys.executable,
            "scripts/gate_scored_candidates_streaming.py",
            "--run-id",
            args.run_id,
            "--scores",
            str(scores_dir / "scored_candidates.parquet"),
            "--output-dir",
            str(gating_dir),
            "--batch-size",
            str(args.downstream_batch_size),
            "--overwrite",
            "true",
        ],
        cwd=workdir,
    )
    stage_seconds["augment"] = run_cmd(
        [
            sys.executable,
            args.augment_script,
            "--run-id",
            args.run_id,
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
            args.augment_profile,
            "--output-dir",
            str(aug_dir),
            "--overwrite",
            "true",
        ],
        cwd=workdir,
    )
    stage_seconds["final"] = run_cmd(
        [
            sys.executable,
            "scripts/build_final_alerts_streaming.py",
            "--run-id",
            args.run_id,
            "--scores",
            str(scores_dir / "scored_candidates.parquet"),
            "--gating",
            str(gating_dir / "gated_candidates.parquet"),
            "--augmentation",
            str(aug_dir / "augmented_candidates.parquet"),
            "--output-dir",
            str(final_dir),
            "--batch-size",
            str(args.downstream_batch_size),
            "--overwrite",
            "true",
        ],
        cwd=workdir,
    )

    metrics = summarize_final(
        final_dir / "final_alerts.parquet",
        events_path,
        candidates_dir / "candidate_events.parquet",
        scores_dir / "scored_candidates.parquet",
        gating_dir / "gated_candidates.parquet",
    )
    score_summary = load_json(scores_dir / "score_summary.json")
    bundle_path = f"outputs/bundles/{args.bundle_name}.zip"
    write_outputs(output_dir, args.run_id, stage_seconds, metrics, score_summary, bundle_path)
    stage_seconds["bundle"] = run_cmd(
        [
            sys.executable,
            "scripts/package_experiment_bundle.py",
            "--bundle-name",
            args.bundle_name,
            "--path",
            str(output_dir),
            "--run-id",
            args.run_id,
        ],
        cwd=workdir,
    )
    write_outputs(output_dir, args.run_id, stage_seconds, metrics, score_summary, bundle_path)
    print(json.dumps({"stage_seconds": stage_seconds, "metrics": metrics, "bundle": bundle_path}, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
