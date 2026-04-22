import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd


EXPECTED = {
    "final_high": 101292,
    "final_needs": 769836,
    "final_low": 739397,
    "high_missing_rate": 0.0,
    "noisy_high": 13,
    "gating_likely_malicious_to_high": 85511,
    "augmentation_promoted_to_high": 15781,
}

QUALITY_THRESHOLDS = {
    "clean_certainty_min": 80.0,
    "noisy_conflict_min": 5.0,
    "noisy_certainty_max_exclusive": 60.0,
}


def run_cmd(cmd: list[str], *, cwd: Path, log_path: Path, force: bool, expected_output: Path) -> float:
    if expected_output.exists() and not force:
        log_path.write_text(f"[REUSE] {expected_output}\n", encoding="utf-8")
        return 0.0
    start = time.perf_counter()
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
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


def to_bool_series(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series.fillna(False)
    return series.astype(str).str.strip().str.lower().isin({"1", "true", "yes", "y", "on"})


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


def load_final(path: Path) -> pd.DataFrame:
    cols = [
        "event_id",
        "final_alert_label",
        "alert_source_layer",
        "certainty_score",
        "conflict_score",
        "missing_origin_or_path",
        "augmentation_label",
        "evidence_support_score",
    ]
    df = pd.read_parquet(path, columns=cols)
    for col in ["event_id", "final_alert_label", "alert_source_layer", "augmentation_label"]:
        df[col] = df[col].fillna("").astype(str)
    for col in ["certainty_score", "conflict_score", "evidence_support_score"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    df["missing_origin_or_path"] = to_bool_series(df["missing_origin_or_path"])
    return df


def summarize_final(df: pd.DataFrame) -> dict:
    counts = df["final_alert_label"].value_counts().to_dict()
    high = df[df["final_alert_label"] == "high_priority_alert"].copy()
    if not high.empty:
        high["quality_bucket"] = classify_quality_bucket(high)
    return {
        "final_high": int(counts.get("high_priority_alert", 0)),
        "final_needs": int(counts.get("needs_review", 0)),
        "final_low": int(counts.get("low_priority_or_background", 0)),
        "high_missing_rate": float(high["missing_origin_or_path"].mean()) if len(high) else 0.0,
        "high_conflict_mean": float(high["conflict_score"].mean()) if len(high) else 0.0,
        "noisy_high": int((high.get("quality_bucket", pd.Series(dtype=object)) == "noisy-high").sum()),
        "gating_likely_malicious_to_high": int(
            ((df["final_alert_label"] == "high_priority_alert") & (df["alert_source_layer"] == "gating_likely_malicious")).sum()
        ),
        "augmentation_promoted_to_high": int(
            ((df["final_alert_label"] == "high_priority_alert") & (df["alert_source_layer"] == "augmentation_promoted")).sum()
        ),
    }


def compare_augment(reference_path: Path, candidate_path: Path) -> dict:
    cols = [
        "event_id",
        "augmentation_label",
        "evidence_support_score",
        "multi_view_support_score",
        "historical_deviation_support_score",
        "consistency_recheck_score",
        "blocked_missing_promotion",
        "route_leak_review_preserved",
    ]
    ref = pd.read_parquet(reference_path, columns=cols).sort_values("event_id").reset_index(drop=True)
    cand = pd.read_parquet(candidate_path, columns=cols).sort_values("event_id").reset_index(drop=True)
    out = {
        "reference_rows": int(len(ref)),
        "candidate_rows": int(len(cand)),
        "event_id_equal": bool(ref["event_id"].equals(cand["event_id"])),
    }
    if len(ref) != len(cand) or not out["event_id_equal"]:
        out["augmentation_label_mismatch"] = None
        out["evidence_support_score_mismatch"] = None
        return out
    out["augmentation_label_mismatch"] = int((ref["augmentation_label"] != cand["augmentation_label"]).sum())
    for col in [
        "evidence_support_score",
        "multi_view_support_score",
        "historical_deviation_support_score",
        "consistency_recheck_score",
    ]:
        diff = (pd.to_numeric(ref[col], errors="coerce") - pd.to_numeric(cand[col], errors="coerce")).abs()
        out[f"{col}_mismatch"] = int((diff > 1e-9).sum())
        out[f"{col}_max_abs_diff"] = float(diff.max())
    for col in ["blocked_missing_promotion", "route_leak_review_preserved"]:
        out[f"{col}_mismatch"] = int((ref[col].astype(str) != cand[col].astype(str)).sum())
    return out


def compare_final(reference_path: Path, candidate_path: Path) -> dict:
    ref = load_final(reference_path).sort_values("event_id").reset_index(drop=True)
    cand = load_final(candidate_path).sort_values("event_id").reset_index(drop=True)
    out = {
        "reference_rows": int(len(ref)),
        "candidate_rows": int(len(cand)),
        "event_id_equal": bool(ref["event_id"].equals(cand["event_id"])),
    }
    if len(ref) != len(cand) or not out["event_id_equal"]:
        out["final_label_mismatch"] = None
        return out
    out["final_label_mismatch"] = int((ref["final_alert_label"] != cand["final_alert_label"]).sum())
    out["alert_source_layer_mismatch"] = int((ref["alert_source_layer"] != cand["alert_source_layer"]).sum())
    return out


def write_report(
    *,
    output_dir: Path,
    augment_seconds: float,
    final_seconds: float,
    final_summary: dict,
    augment_compare: dict,
    final_compare: dict,
    regression_passed: bool,
) -> None:
    old_seconds = 6634.60
    speedup = old_seconds / augment_seconds if augment_seconds else 0.0
    report = f"""# S1-F Augment Optimization Report

## Summary

- optimization: `augment_uncertain_candidates_fast.py`
- old_s1d_augment_seconds: {old_seconds:.2f}
- optimized_augment_seconds: {augment_seconds:.2f}
- final_seconds: {final_seconds:.2f}
- speedup: {speedup:.2f}x
- regression_passed: {str(regression_passed).lower()}

## Final Metrics

| metric | expected | optimized |
|---|---:|---:|
| final_high | {EXPECTED['final_high']} | {final_summary['final_high']} |
| final_needs | {EXPECTED['final_needs']} | {final_summary['final_needs']} |
| final_low | {EXPECTED['final_low']} | {final_summary['final_low']} |
| high_missing_rate | {EXPECTED['high_missing_rate']:.4f} | {final_summary['high_missing_rate']:.4f} |
| noisy_high | {EXPECTED['noisy_high']} | {final_summary['noisy_high']} |
| gating_likely_malicious_to_high | {EXPECTED['gating_likely_malicious_to_high']} | {final_summary['gating_likely_malicious_to_high']} |
| augmentation_promoted_to_high | {EXPECTED['augmentation_promoted_to_high']} | {final_summary['augmentation_promoted_to_high']} |

## Row-Level Regression

### Augmentation

```json
{json.dumps(augment_compare, ensure_ascii=False, indent=2)}
```

### Final

```json
{json.dumps(final_compare, ensure_ascii=False, indent=2)}
```

## Interpretation

The fast implementation keeps the same scoring and profile rules, but replaces per-row DataFrame materialization with array-backed interval indexes for nearby event lookup. It is an implementation optimization, not a business-rule change.
"""
    (output_dir / "s1f_optimization_report.md").write_text(report, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="S1-F low-risk augment optimization runner.")
    parser.add_argument("--workdir", default=".")
    parser.add_argument("--run-id", default="s1a_expanded_v02_pilot_60m_april16")
    parser.add_argument("--s1d-output-dir", default="outputs/s1d_modern_new_baseline_v01")
    parser.add_argument("--output-dir", default="outputs/s1f_augment_optimization_v01")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    workdir = Path(args.workdir).resolve()
    output_dir = (workdir / args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    run_root = workdir / "data" / "runs" / args.run_id
    augment_dir = output_dir / "fast_full" / "augmentation"
    final_dir = output_dir / "fast_full" / "final"
    augment_dir.mkdir(parents=True, exist_ok=True)
    final_dir.mkdir(parents=True, exist_ok=True)

    augment_seconds = run_cmd(
        [
            sys.executable,
            "scripts/augment_uncertain_candidates_fast.py",
            "--run-id",
            args.run_id,
            "--gating",
            str(run_root / "gating" / "gated_candidates.parquet"),
            "--events",
            str(run_root / "events" / "event_units.parquet"),
            "--baseline-prefix",
            str(run_root / "baseline" / "baseline_prefix.parquet"),
            "--baseline-prefix-origin",
            str(run_root / "baseline" / "baseline_prefix_origin.parquet"),
            "--baseline-path",
            str(run_root / "baseline" / "baseline_path.parquet"),
            "--profile",
            "modern_missing_block",
            "--output-dir",
            str(augment_dir),
            "--overwrite",
            "true",
        ],
        cwd=workdir,
        log_path=output_dir / "s1f_fast_augment.log",
        force=args.force,
        expected_output=augment_dir / "augmented_candidates.parquet",
    )

    final_seconds = run_cmd(
        [
            sys.executable,
            "scripts/build_final_alerts_streaming.py",
            "--run-id",
            args.run_id,
            "--scores",
            str(run_root / "scores" / "scored_candidates.parquet"),
            "--gating",
            str(run_root / "gating" / "gated_candidates.parquet"),
            "--augmentation",
            str(augment_dir / "augmented_candidates.parquet"),
            "--output-dir",
            str(final_dir),
            "--overwrite",
            "true",
        ],
        cwd=workdir,
        log_path=output_dir / "s1f_fast_final.log",
        force=args.force,
        expected_output=final_dir / "final_alerts.parquet",
    )

    s1d_output = workdir / args.s1d_output_dir
    augment_compare = compare_augment(
        s1d_output / "modern_rerun" / "augmentation" / "augmented_candidates.parquet",
        augment_dir / "augmented_candidates.parquet",
    )
    final_compare = compare_final(
        s1d_output / "modern_rerun" / "final" / "final_alerts.parquet",
        final_dir / "final_alerts.parquet",
    )
    final_summary = summarize_final(load_final(final_dir / "final_alerts.parquet"))
    regression_passed = (
        all(final_summary[k] == v for k, v in EXPECTED.items() if k != "high_missing_rate")
        and abs(final_summary["high_missing_rate"] - EXPECTED["high_missing_rate"]) <= 1e-12
        and augment_compare.get("event_id_equal") is True
        and augment_compare.get("augmentation_label_mismatch") == 0
        and augment_compare.get("evidence_support_score_mismatch") == 0
        and final_compare.get("event_id_equal") is True
        and final_compare.get("final_label_mismatch") == 0
        and final_compare.get("alert_source_layer_mismatch") == 0
    )

    summary = {
        "augment_seconds": augment_seconds,
        "final_seconds": final_seconds,
        "final_summary": final_summary,
        "augment_compare": augment_compare,
        "final_compare": final_compare,
        "regression_passed": regression_passed,
    }
    (output_dir / "s1f_optimization_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(
        output_dir=output_dir,
        augment_seconds=augment_seconds,
        final_seconds=final_seconds,
        final_summary=final_summary,
        augment_compare=augment_compare,
        final_compare=final_compare,
        regression_passed=regression_passed,
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not regression_passed:
        raise SystemExit("S1-F regression failed")


if __name__ == "__main__":
    main()
