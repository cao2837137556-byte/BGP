#!/usr/bin/env python3
"""Materialize one collector-day of verified local MRT into Parquet.

The task consumes the immutable R-MEM-1B manifest, parses the first and last
archive first as a boundary parser precheck, and then processes the remaining
files. Each file receives an atomic Parquet output and an atomic audit
checkpoint so a requeued Slurm task can resume without overwriting completed
work.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from run_r_mem1c_local_mrt_parser_smoke import (
    evaluate_gates,
    parse_file,
    schema_payload,
    write_csv,
    write_json,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = "configs/r_mem1d_10d_parquet_materialization_v01.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--data-root", default="/data_store")
    parser.add_argument("--manifest")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--collector", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--max-files", type=int, default=0)
    return parser.parse_args()


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def allowed_dates(config: dict[str, Any]) -> list[str]:
    start = parse_date(config["start_date"])
    end = parse_date(config["end_date"])
    return [
        (start + timedelta(days=offset)).isoformat()
        for offset in range((end - start).days + 1)
    ]


def select_collector_day(
    manifest: list[dict[str, Any]], collector: str, day: str
) -> list[dict[str, Any]]:
    selected = sorted(
        [
            row
            for row in manifest
            if str(row.get("collector")) == collector
            and str(row.get("archive_timestamp_utc", "")).startswith(day)
        ],
        key=lambda row: str(row["archive_timestamp_utc"]),
    )
    if len(selected) <= 2:
        return selected
    return [selected[0], selected[-1], *selected[1:-1]]


def checkpoint_path(output_dir: Path, source: dict[str, Any]) -> Path:
    relative = str(source["local_relative_path"])
    digest = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:20]
    return output_dir / "checkpoints" / f"{digest}.json"


def load_completed_checkpoint(
    path: Path, source: dict[str, Any]
) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("status") != "parsed":
        return None
    if payload.get("file_path") != str(source["local_relative_path"]):
        return None
    current_fingerprint = os.environ.get("R_MEM1D_CODE_FINGERPRINT")
    checkpoint_fingerprint = payload.get("checkpoint_execution", {}).get(
        "code_fingerprint"
    )
    if current_fingerprint and checkpoint_fingerprint != current_fingerprint:
        return None
    output = Path(str(payload.get("output_path", "")))
    if not output.is_file() or output.stat().st_size != int(
        payload.get("parquet_size_bytes", -1)
    ):
        return None
    payload["resumed_from_checkpoint"] = True
    return payload


def prepare_output(output_dir: Path, resume: bool) -> None:
    if output_dir.exists() and any(output_dir.iterdir()) and not resume:
        raise FileExistsError(
            f"output directory is non-empty; use --resume only for the same task: {output_dir}"
        )
    (output_dir / "parsed").mkdir(parents=True, exist_ok=True)
    (output_dir / "checkpoints").mkdir(parents=True, exist_ok=True)


def execution_payload() -> dict[str, Any]:
    return {
        "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
        "slurm_array_job_id": os.environ.get("SLURM_ARRAY_JOB_ID"),
        "slurm_array_task_id": os.environ.get("SLURM_ARRAY_TASK_ID"),
        "slurm_partition": os.environ.get("SLURM_JOB_PARTITION"),
        "slurm_node_list": os.environ.get("SLURM_NODELIST"),
        "pair_id": os.environ.get("R_MEM1D_PAIR_ID"),
        "code_commit": os.environ.get("R_MEM1D_CODE_COMMIT"),
        "code_fingerprint": os.environ.get("R_MEM1D_CODE_FINGERPRINT"),
    }


def report(summary: dict[str, Any]) -> str:
    return f"""# R-MEM-1D Collector-day Materialization Report

- collector: `{summary['collector']}`
- date: `{summary['date']}`
- passed: `{str(summary['materialization_passed']).lower()}`
- expected files: `{summary['expected_file_count']}`
- parsed files: `{summary['parsed_file_count']}`
- resumed files: `{summary['resumed_file_count']}`
- total rows: `{summary['total_parsed_rows']}`
- parse seconds: `{summary['summed_parse_elapsed_sec']}`
- aggregate rows/second: `{summary['aggregate_rows_per_sec']}`
- gate failures: `{summary['gate_failures']}`

This task creates no attack/benign truth, does not modify foreground policy,
and does not establish path maturity or poisoning robustness.
"""


def main() -> int:
    args = parse_args()
    config_path = resolve_repo_path(args.config)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    data_root = Path(args.data_root).resolve()
    output_dir = Path(args.output_dir).resolve()
    manifest_path = (
        Path(args.manifest).resolve()
        if args.manifest
        else data_root / config["manifest_relative_path"]
    )

    if args.collector not in config["collectors"]:
        raise ValueError(f"collector is outside the frozen contract: {args.collector}")
    if args.date not in allowed_dates(config):
        raise ValueError(f"date is outside the frozen contract: {args.date}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if len(manifest) != 3840:
        raise ValueError(f"expected 3,840 manifest rows, found {len(manifest)}")
    relative_paths = [str(row["local_relative_path"]) for row in manifest]
    if len(relative_paths) != len(set(relative_paths)):
        raise ValueError("manifest contains duplicate local_relative_path values")

    selected = select_collector_day(manifest, args.collector, args.date)
    expected_count = int(
        config["expected_files_per_collector_day"][args.collector]
    )
    if len(selected) != expected_count:
        raise ValueError(
            f"collector-day file count mismatch: expected={expected_count} found={len(selected)}"
        )
    if args.max_files:
        selected = selected[: args.max_files]

    plan = {
        "phase": config["phase"],
        "dataset_id": config["dataset_id"],
        "collector": args.collector,
        "date": args.date,
        "manifest_path": str(manifest_path),
        "output_dir": str(output_dir),
        "expected_file_count": expected_count,
        "selected_file_count": len(selected),
        "selected_files": selected,
        "selection_order": "first_archive_then_last_archive_then_chronological_middle",
        "resume": args.resume,
        "plan_only": args.plan_only,
        "max_files": args.max_files,
        "execution": execution_payload(),
    }
    if args.plan_only:
        if output_dir.exists() and any(output_dir.iterdir()):
            raise FileExistsError(f"plan output directory is non-empty: {output_dir}")
        output_dir.mkdir(parents=True, exist_ok=True)
    else:
        prepare_output(output_dir, args.resume)
    write_json(output_dir / "r_mem1d_task_plan.json", plan)
    print(
        json.dumps(
            {
                "phase": plan["phase"],
                "collector": plan["collector"],
                "date": plan["date"],
                "expected_file_count": plan["expected_file_count"],
                "selected_file_count": plan["selected_file_count"],
                "selection_order": plan["selection_order"],
                "output_dir": plan["output_dir"],
                "resume": plan["resume"],
                "plan_only": plan["plan_only"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    if args.plan_only:
        return 0

    runtime_config = copy.deepcopy(config)
    runtime_config["gates"]["required_collectors"] = [args.collector]
    preview: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []
    boundary_parser_precheck: dict[str, Any] | None = None

    for index, source in enumerate(selected, start=1):
        checkpoint = checkpoint_path(output_dir, source)
        result = load_completed_checkpoint(checkpoint, source) if args.resume else None
        if result is None:
            result = parse_file(
                source,
                data_root,
                output_dir,
                runtime_config,
                0,
                preview,
            )
            result["checkpoint_execution"] = execution_payload()
            write_json(checkpoint, result)
        audits.append(result)
        write_json(
            output_dir / "r_mem1d_task_progress.json",
            {
                "phase": config["phase"],
                "collector": args.collector,
                "date": args.date,
                "completed_file_count": len(audits),
                "selected_file_count": len(selected),
                "file_audits": audits,
                "execution": execution_payload(),
            },
        )
        print(
            f"progress={index}/{len(selected)} collector={args.collector} "
            f"date={args.date} status={result['status']} "
            f"rows={result.get('rows', 0)} resumed={result.get('resumed_from_checkpoint', False)}",
            flush=True,
        )
        if result["status"] != "parsed":
            break
        if index == min(2, len(selected)):
            gate_passed, gate_failures = evaluate_gates(audits, runtime_config)
            boundary_parser_precheck = {
                "passed": gate_passed,
                "file_count": len(audits),
                "file_paths": [row["file_path"] for row in audits],
                "gate_failures": gate_failures,
            }
            write_json(
                output_dir / "r_mem1d_boundary_parser_precheck.json",
                boundary_parser_precheck,
            )
            print(f"boundary_parser_precheck_passed={gate_passed}", flush=True)
            if not gate_passed:
                break

    gate_passed, gate_failures = evaluate_gates(audits, runtime_config)
    if len(audits) != len(selected):
        gate_failures.append(
            f"task stopped before all selected files: processed={len(audits)} selected={len(selected)}"
        )
        gate_passed = False
    if args.max_files:
        gate_failures.append("max_files debug cap prevents formal qualification")
        gate_passed = False

    parsed = [row for row in audits if row["status"] == "parsed"]
    total_rows = sum(int(row["rows"]) for row in parsed)
    parse_seconds = sum(float(row.get("parse_elapsed_sec", 0.0)) for row in parsed)
    summary = {
        "phase": config["phase"],
        "dataset_id": config["dataset_id"],
        "collector": args.collector,
        "date": args.date,
        "materialization_passed": gate_passed,
        "boundary_parser_precheck": boundary_parser_precheck,
        "expected_file_count": expected_count,
        "selected_file_count": len(selected),
        "processed_file_count": len(audits),
        "parsed_file_count": len(parsed),
        "failed_file_count": len(audits) - len(parsed),
        "resumed_file_count": sum(
            int(bool(row.get("resumed_from_checkpoint"))) for row in parsed
        ),
        "total_parsed_rows": total_rows,
        "announcement_rows": sum(int(row["announcement_rows"]) for row in parsed),
        "withdrawal_rows": sum(int(row["withdrawal_rows"]) for row in parsed),
        "community_nonempty_rows": sum(
            int(row["community_nonempty_rows"]) for row in parsed
        ),
        "source_integrity_verified_file_count": sum(
            int(bool(row.get("source_size_verified")) and bool(row.get("source_sha256_verified")))
            for row in parsed
        ),
        "compressed_input_bytes": sum(
            int(row["compressed_size_bytes"]) for row in parsed
        ),
        "parquet_output_bytes": sum(int(row["parquet_size_bytes"]) for row in parsed),
        "summed_parse_elapsed_sec": round(parse_seconds, 6),
        "aggregate_rows_per_sec": (
            round(total_rows / parse_seconds, 3) if parse_seconds else None
        ),
        "gate_failures": gate_failures,
        "execution": execution_payload(),
        "claims": {
            "attack_or_benign_truth_produced": False,
            "foreground_modified": False,
            "learning_trained": False,
            "path_maturity_proven": False,
        },
    }
    write_json(output_dir / "r_mem1d_task_summary.json", summary)
    write_json(output_dir / "r_mem1d_schema.json", schema_payload())
    write_csv(output_dir / "r_mem1d_file_audit.csv", audits)
    write_csv(output_dir / "r_mem1d_preview.csv", preview)
    (output_dir / "r_mem1d_task_report.md").write_text(
        report(summary), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if gate_passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
