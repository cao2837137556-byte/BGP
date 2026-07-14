#!/usr/bin/env python3
"""Validate one complete R-MEM-1D partition materialization without reading Parquet rows."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from datetime import date, timedelta
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = "configs/r_mem1d_10d_parquet_materialization_v01.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--materialization-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--expected-array-job-id")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def allowed_dates(config: dict[str, Any]) -> list[str]:
    start = date.fromisoformat(config["start_date"])
    end = date.fromisoformat(config["end_date"])
    return [
        (start + timedelta(days=offset)).isoformat()
        for offset in range((end - start).days + 1)
    ]


def render_report(summary: dict[str, Any]) -> str:
    return f"""# R-MEM-1D 10-day Parquet Validation Report

- validation passed: `{str(summary['validation_passed']).lower()}`
- task summaries: `{summary['task_summary_count']}` / `{summary['expected_task_count']}`
- parsed files: `{summary['parsed_file_count']}` / `{summary['expected_file_count']}`
- Parquet files: `{summary['actual_parquet_file_count']}`
- total parsed rows: `{summary['total_parsed_rows']}`
- compressed input bytes: `{summary['compressed_input_bytes']}`
- Parquet output bytes: `{summary['parquet_output_bytes']}`
- source integrity verified files: `{summary['source_integrity_verified_file_count']}`
- gate failures: `{summary['gate_failures']}`

This validation qualifies a 10-day routing-observation data asset only. It
does not create attack/benign truth, modify foreground policy, train learning,
or prove poisoning robustness.
"""


def main() -> int:
    args = parse_args()
    config = json.loads(resolve_repo_path(args.config).read_text(encoding="utf-8"))
    root = Path(args.materialization_root).resolve()
    output_dir = Path(args.output_dir).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"materialization root does not exist: {root}")
    if output_dir.exists() and any(output_dir.iterdir()):
        if not args.overwrite:
            raise FileExistsError(f"output directory is non-empty: {output_dir}")
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    expected_matrix = {
        (collector, day)
        for collector in config["collectors"]
        for day in allowed_dates(config)
    }
    expected_files = sum(
        int(config["expected_files_per_collector_day"][collector])
        for collector, _ in expected_matrix
    )
    summary_paths = sorted(root.rglob("r_mem1d_task_summary.json"))
    rows: list[dict[str, Any]] = []
    failures: list[str] = []
    observed_matrix: list[tuple[str, str]] = []
    source_paths: set[str] = set()

    for summary_path in summary_paths:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        collector = str(summary.get("collector"))
        day = str(summary.get("date"))
        observed_matrix.append((collector, day))
        task_dir = summary_path.parent
        audit_path = task_dir / "r_mem1d_file_audit.csv"
        audit_rows: list[dict[str, str]] = []
        if audit_path.is_file():
            with audit_path.open("r", encoding="utf-8", newline="") as handle:
                audit_rows = list(csv.DictReader(handle))
        else:
            failures.append(f"{collector}:{day}: missing file audit")
        task_sources = [row.get("file_path", "") for row in audit_rows]
        duplicates = source_paths.intersection(path for path in task_sources if path)
        if duplicates:
            failures.append(
                f"{collector}:{day}: duplicate source paths across tasks: {sorted(duplicates)[:3]}"
            )
        source_paths.update(path for path in task_sources if path)
        parquet_paths = list((task_dir / "parsed").rglob("*.parquet"))
        parquet_count = len(parquet_paths)
        zero_byte_parquet_count = sum(
            int(path.stat().st_size == 0) for path in parquet_paths
        )
        expected_task_files = int(
            config["expected_files_per_collector_day"].get(collector, -1)
        )
        if summary.get("materialization_passed") is not True:
            failures.append(f"{collector}:{day}: materialization did not pass")
        if int(summary.get("parsed_file_count", -1)) != expected_task_files:
            failures.append(f"{collector}:{day}: parsed file count mismatch")
        if int(summary.get("processed_file_count", -1)) != expected_task_files:
            failures.append(f"{collector}:{day}: processed file count mismatch")
        if int(summary.get("failed_file_count", -1)) != 0:
            failures.append(f"{collector}:{day}: failed file count is nonzero")
        if int(
            summary.get("source_integrity_verified_file_count", -1)
        ) != expected_task_files:
            failures.append(f"{collector}:{day}: source integrity count mismatch")
        if parquet_count != expected_task_files:
            failures.append(f"{collector}:{day}: Parquet file count mismatch")
        if zero_byte_parquet_count:
            failures.append(f"{collector}:{day}: zero-byte Parquet files found")
        if len(audit_rows) != expected_task_files:
            failures.append(f"{collector}:{day}: audit row count mismatch")
        if any(row.get("status") != "parsed" for row in audit_rows):
            failures.append(f"{collector}:{day}: non-parsed file audit row found")
        if any(
            row.get("source_size_verified") != "True"
            or row.get("source_sha256_verified") != "True"
            for row in audit_rows
        ):
            failures.append(f"{collector}:{day}: file audit integrity flag failed")
        if summary.get("early_gate", {}).get("passed") is not True:
            failures.append(f"{collector}:{day}: early gate did not pass")
        execution = summary.get("execution", {})
        if args.expected_array_job_id and str(
            execution.get("slurm_array_job_id")
        ) != str(args.expected_array_job_id):
            failures.append(f"{collector}:{day}: array job provenance mismatch")
        rows.append(
            {
                "collector": collector,
                "date": day,
                "summary_path": str(summary_path),
                "materialization_passed": summary.get("materialization_passed"),
                "expected_file_count": expected_task_files,
                "parsed_file_count": summary.get("parsed_file_count"),
                "actual_parquet_file_count": parquet_count,
                "zero_byte_parquet_file_count": zero_byte_parquet_count,
                "audit_row_count": len(audit_rows),
                "total_parsed_rows": summary.get("total_parsed_rows"),
                "compressed_input_bytes": summary.get("compressed_input_bytes"),
                "parquet_output_bytes": summary.get("parquet_output_bytes"),
                "source_integrity_verified_file_count": summary.get(
                    "source_integrity_verified_file_count"
                ),
                "code_fingerprint": execution.get("code_fingerprint"),
                "slurm_array_job_id": execution.get("slurm_array_job_id"),
                "slurm_array_task_id": execution.get("slurm_array_task_id"),
            }
        )

    observed_set = set(observed_matrix)
    duplicate_tasks = sorted(
        key for key in observed_set if observed_matrix.count(key) != 1
    )
    missing_tasks = sorted(expected_matrix - observed_set)
    extra_tasks = sorted(observed_set - expected_matrix)
    if duplicate_tasks:
        failures.append(f"duplicate collector-day summaries: {duplicate_tasks}")
    if missing_tasks:
        failures.append(f"missing collector-day summaries: {missing_tasks}")
    if extra_tasks:
        failures.append(f"unexpected collector-day summaries: {extra_tasks}")
    if len(summary_paths) != len(expected_matrix):
        failures.append(
            f"task summary count mismatch: found={len(summary_paths)} expected={len(expected_matrix)}"
        )
    if len(source_paths) != expected_files:
        failures.append(
            f"unique source coverage mismatch: found={len(source_paths)} expected={expected_files}"
        )

    fingerprints = sorted(
        {str(row["code_fingerprint"]) for row in rows if row.get("code_fingerprint")}
    )
    if len(fingerprints) != 1:
        failures.append(f"expected one code fingerprint, found={fingerprints}")

    def total(field: str) -> int:
        return sum(int(row.get(field) or 0) for row in rows)

    summary = {
        "phase": config["phase"],
        "dataset_id": config["dataset_id"],
        "validation_passed": not failures,
        "materialization_root": str(root),
        "expected_task_count": len(expected_matrix),
        "task_summary_count": len(summary_paths),
        "expected_file_count": expected_files,
        "parsed_file_count": total("parsed_file_count"),
        "actual_parquet_file_count": total("actual_parquet_file_count"),
        "unique_source_file_count": len(source_paths),
        "total_parsed_rows": total("total_parsed_rows"),
        "compressed_input_bytes": total("compressed_input_bytes"),
        "parquet_output_bytes": total("parquet_output_bytes"),
        "source_integrity_verified_file_count": total(
            "source_integrity_verified_file_count"
        ),
        "missing_tasks": missing_tasks,
        "extra_tasks": extra_tasks,
        "duplicate_tasks": duplicate_tasks,
        "code_fingerprints": fingerprints,
        "gate_failures": failures,
        "claims": {
            "attack_or_benign_truth_produced": False,
            "foreground_modified": False,
            "learning_trained": False,
            "poisoning_robustness_proven": False,
        },
    }
    write_csv(output_dir / "r_mem1d_task_validation_audit.csv", rows)
    write_json(output_dir / "r_mem1d_validation_summary.json", summary)
    (output_dir / "r_mem1d_validation_report.md").write_text(
        render_report(summary), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
