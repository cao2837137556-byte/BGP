import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


DEFAULT_RUN_ID = "s1a_expanded_v02_pilot_60m_april16"


def run_cmd(cmd: list[str], cwd: Path) -> float:
    print("[CMD]", " ".join(cmd), flush=True)
    start = time.perf_counter()
    proc = subprocess.run(cmd, cwd=str(cwd))
    elapsed = time.perf_counter() - start
    if proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(cmd)}")
    return elapsed


def sample_parquet(input_path: Path, output_path: Path, rows: int) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()
    parquet_file = pq.ParquetFile(input_path)
    remaining = rows
    writer = None
    written = 0
    try:
        for batch in parquet_file.iter_batches(batch_size=min(100000, rows)):
            if remaining <= 0:
                break
            table = pa.Table.from_batches([batch])
            if table.num_rows > remaining:
                table = table.slice(0, remaining)
            if writer is None:
                writer = pq.ParquetWriter(output_path, table.schema)
            writer.write_table(table)
            written += table.num_rows
            remaining -= table.num_rows
    finally:
        if writer is not None:
            writer.close()
    return written


def load_summary(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def compare_outputs(reference_path: Path, fast_path: Path, output_csv: Path) -> pd.DataFrame:
    ref = pd.read_parquet(reference_path)
    fast = pd.read_parquet(fast_path)
    rows = []
    rows.append(
        {
            "check": "row_count",
            "reference": len(ref),
            "fast": len(fast),
            "mismatch_count": int(len(ref) != len(fast)),
            "max_abs_diff": 0.0,
            "status": "ok" if len(ref) == len(fast) else "fail",
        }
    )

    if len(ref) != len(fast):
        result = pd.DataFrame(rows)
        result.to_csv(output_csv, index=False)
        return result

    if ref["event_id"].tolist() != fast["event_id"].tolist():
        ref = ref.sort_values("event_id").reset_index(drop=True)
        fast = fast.sort_values("event_id").reset_index(drop=True)
    else:
        ref = ref.reset_index(drop=True)
        fast = fast.reset_index(drop=True)

    event_mismatch = int((ref["event_id"] != fast["event_id"]).sum())
    rows.append(
        {
            "check": "event_id",
            "reference": len(ref),
            "fast": len(fast),
            "mismatch_count": event_mismatch,
            "max_abs_diff": 0.0,
            "status": "ok" if event_mismatch == 0 else "fail",
        }
    )

    numeric_cols = [
        "structural_novelty_score",
        "weak_signal_score",
        "history_rarity_score",
        "path_consistency_score",
        "risk_score",
    ]
    for col in numeric_cols:
        diff = (pd.to_numeric(ref[col], errors="coerce") - pd.to_numeric(fast[col], errors="coerce")).abs()
        max_abs = float(diff.max()) if len(diff) else 0.0
        mismatch = int((diff > 1e-9).sum())
        rows.append(
            {
                "check": col,
                "reference": "",
                "fast": "",
                "mismatch_count": mismatch,
                "max_abs_diff": max_abs,
                "status": "ok" if mismatch == 0 else "fail",
            }
        )

    exact_cols = ["risk_bucket", "top_contributing_factor", "missing_origin_or_path"]
    for col in exact_cols:
        mismatch = int((ref[col].astype(str) != fast[col].astype(str)).sum())
        rows.append(
            {
                "check": col,
                "reference": "",
                "fast": "",
                "mismatch_count": mismatch,
                "max_abs_diff": 0.0,
                "status": "ok" if mismatch == 0 else "fail",
            }
        )

    result = pd.DataFrame(rows)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_csv, index=False)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="S2-B score correctness and benchmark runner.")
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--runs-root", default="data/runs")
    parser.add_argument("--output-dir", default="outputs/s2b_score_optimization_v01")
    parser.add_argument("--correctness-rows", type=int, default=50000)
    parser.add_argument("--fast-benchmark-rows", type=int, default=500000)
    parser.add_argument("--batch-size", type=int, default=100000)
    parser.add_argument("--reference-script", default="scripts/score_weak_candidates.py")
    args = parser.parse_args()

    workdir = Path.cwd()
    run_dir = Path(args.runs_root) / args.run_id
    candidates = run_dir / "candidates" / "candidate_events.parquet"
    baseline_prefix = run_dir / "baseline" / "baseline_prefix.parquet"
    baseline_po = run_dir / "baseline" / "baseline_prefix_origin.parquet"
    baseline_path = run_dir / "baseline" / "baseline_path.parquet"
    for path in [candidates, baseline_prefix, baseline_po, baseline_path]:
        if not path.exists():
            raise SystemExit(f"required input not found: {path}")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    sample_dir = output_dir / "samples"
    correctness_candidate = sample_dir / f"{args.run_id}_correctness_{args.correctness_rows}.parquet"
    benchmark_candidate = sample_dir / f"{args.run_id}_benchmark_{args.fast_benchmark_rows}.parquet"
    correctness_written = sample_parquet(candidates, correctness_candidate, args.correctness_rows)
    benchmark_written = sample_parquet(candidates, benchmark_candidate, args.fast_benchmark_rows)

    ref_dir = output_dir / "correctness_reference"
    fast_dir = output_dir / "correctness_fast"
    bench_dir = output_dir / "benchmark_fast"

    ref_cmd = [
        sys.executable,
        args.reference_script,
        "--run-id",
        args.run_id,
        "--candidates",
        str(correctness_candidate),
        "--baseline-prefix",
        str(baseline_prefix),
        "--baseline-prefix-origin",
        str(baseline_po),
        "--baseline-path",
        str(baseline_path),
        "--output-dir",
        str(ref_dir),
        "--overwrite",
        "true",
    ]
    if "streaming" in Path(args.reference_script).name:
        ref_cmd.extend(["--batch-size", str(args.batch_size)])
    ref_seconds = run_cmd(ref_cmd, workdir)
    fast_seconds = run_cmd(
        [
            sys.executable,
            "scripts/score_weak_candidates_streaming_fast.py",
            "--run-id",
            args.run_id,
            "--candidates",
            str(correctness_candidate),
            "--baseline-prefix",
            str(baseline_prefix),
            "--baseline-prefix-origin",
            str(baseline_po),
            "--baseline-path",
            str(baseline_path),
            "--output-dir",
            str(fast_dir),
            "--batch-size",
            str(args.batch_size),
            "--overwrite",
            "true",
        ],
        workdir,
    )
    bench_seconds = run_cmd(
        [
            sys.executable,
            "scripts/score_weak_candidates_streaming_fast.py",
            "--run-id",
            args.run_id,
            "--candidates",
            str(benchmark_candidate),
            "--baseline-prefix",
            str(baseline_prefix),
            "--baseline-prefix-origin",
            str(baseline_po),
            "--baseline-path",
            str(baseline_path),
            "--output-dir",
            str(bench_dir),
            "--batch-size",
            str(args.batch_size),
            "--overwrite",
            "true",
        ],
        workdir,
    )

    correctness = compare_outputs(
        ref_dir / "scored_candidates.parquet",
        fast_dir / "scored_candidates.parquet",
        output_dir / "s2b_score_correctness_check.csv",
    )

    ref_summary = load_summary(ref_dir / "score_summary.json")
    fast_summary = load_summary(fast_dir / "score_summary.json")
    bench_summary = load_summary(bench_dir / "score_summary.json")
    benchmark = pd.DataFrame(
        [
            {
                "case": "reference_correctness_sample",
                "rows": ref_summary["output_rows"],
                "seconds": ref_seconds,
                "rows_per_sec": ref_summary["output_rows"] / ref_seconds if ref_seconds else 0.0,
            },
            {
                "case": "fast_correctness_sample",
                "rows": fast_summary["output_rows"],
                "seconds": fast_seconds,
                "rows_per_sec": fast_summary["output_rows"] / fast_seconds if fast_seconds else 0.0,
            },
            {
                "case": "fast_benchmark_sample",
                "rows": bench_summary["output_rows"],
                "seconds": bench_seconds,
                "rows_per_sec": bench_summary["output_rows"] / bench_seconds if bench_seconds else 0.0,
            },
        ]
    )
    ref_rps = float(benchmark.loc[benchmark["case"] == "reference_correctness_sample", "rows_per_sec"].iloc[0])
    fast_rps = float(benchmark.loc[benchmark["case"] == "fast_benchmark_sample", "rows_per_sec"].iloc[0])
    benchmark["speedup_vs_reference_sample"] = benchmark["rows_per_sec"] / ref_rps if ref_rps else 0.0
    benchmark.to_csv(output_dir / "s2b_score_benchmark.csv", index=False)

    all_ok = bool((correctness["status"] == "ok").all())
    summary = {
        "run_id": args.run_id,
        "correctness_rows_requested": args.correctness_rows,
        "correctness_rows_written": correctness_written,
        "fast_benchmark_rows_requested": args.fast_benchmark_rows,
        "fast_benchmark_rows_written": benchmark_written,
        "correctness_passed": all_ok,
        "reference_seconds": ref_seconds,
        "fast_correctness_seconds": fast_seconds,
        "fast_benchmark_seconds": bench_seconds,
        "reference_rows_per_sec": ref_rps,
        "fast_rows_per_sec": fast_rps,
        "estimated_full_10_236_431_seconds": 10236431 / fast_rps if fast_rps else None,
    }
    (output_dir / "s2b_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    report = f"""# S2-B1 Score Fast Scorer Validation

## Scope

- validation_run_id: `{args.run_id}`
- correctness_rows_written: `{correctness_written}`
- fast_benchmark_rows_written: `{benchmark_written}`
- correctness_passed: `{all_ok}`

## Benchmark

```text
{benchmark.to_string(index=False)}
```

## Correctness

```text
{correctness.to_string(index=False)}
```

## Estimate

- estimated_full_10_236_431_seconds: `{summary['estimated_full_10_236_431_seconds']}`
- estimated_full_10_236_431_minutes: `{summary['estimated_full_10_236_431_seconds'] / 60 if summary['estimated_full_10_236_431_seconds'] else None}`
"""
    (output_dir / "s2b_score_optimization_report.md").write_text(report, encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    if not all_ok:
        raise SystemExit("correctness check failed; do not run full S2-B2")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
