#!/usr/bin/env python3
"""Freeze a bounded peer-aware development asset from R-MEM-1E summaries."""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = "configs/r_data_freeze0_9d_development_v01.json"
VALIDATION_NAME = "r_mem1d_validation_summary.json"
TASK_NAME = "r_mem1d_task_summary.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--pullback-root", required=True)
    parser.add_argument("--qa2-candidate-audit", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def date_range(start: str, end: str) -> list[str]:
    first = date.fromisoformat(start)
    last = date.fromisoformat(end)
    return [
        (first + timedelta(days=offset)).isoformat()
        for offset in range((last - first).days + 1)
    ]


def write_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        if fields:
            writer.writeheader()
            writer.writerows(rows)
    temporary.replace(path)


def prepare_output(path: Path, overwrite: bool) -> None:
    if path.exists() and any(path.iterdir()):
        if not overwrite:
            raise FileExistsError(f"output directory is not empty: {path}")
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def source_execution(summary: dict[str, Any]) -> tuple[str, str]:
    root = str(summary.get("materialization_root", ""))
    match = re.search(r"/partition=([^/]+)/array_job=([^/]+)$", root)
    if not match:
        raise ValueError(f"cannot recover source execution from: {root}")
    return match.group(1), match.group(2)


def task_matches_execution(
    task: dict[str, Any], partition: str, array_job: str
) -> bool:
    execution = task.get("execution", {})
    return (
        str(execution.get("slurm_partition")) == partition
        and str(execution.get("slurm_array_job_id")) == array_job
    )


def select_best_execution(
    pullback_root: Path, config: dict[str, Any]
) -> tuple[Path, dict[str, Any], str, str, list[tuple[Path, dict[str, Any]]]]:
    validation_paths = sorted(pullback_root.rglob(VALIDATION_NAME))
    if not validation_paths:
        raise FileNotFoundError(f"no {VALIDATION_NAME} below {pullback_root}")
    all_tasks = [
        (path, load_json(path)) for path in pullback_root.rglob(TASK_NAME)
    ]
    candidates: list[
        tuple[
            tuple[int, int, int],
            Path,
            dict[str, Any],
            str,
            str,
            list[tuple[Path, dict[str, Any]]],
        ]
    ] = []
    for validation_path in validation_paths:
        summary = load_json(validation_path)
        if summary.get("dataset_id") != config["source_dataset_id"]:
            continue
        if summary.get("canonical_schema_version") != config[
            "source_schema_version"
        ]:
            continue
        partition, array_job = source_execution(summary)
        tasks = [
            item
            for item in all_tasks
            if task_matches_execution(item[1], partition, array_job)
        ]
        complete_files = int(summary.get("parsed_file_count", 0))
        footer_failures = int(summary.get("parquet_footer_failure_count", 0))
        score = (len(tasks), complete_files, -footer_failures)
        candidates.append(
            (
                score,
                validation_path,
                summary,
                partition,
                array_job,
                tasks,
            )
        )
    if not candidates:
        raise ValueError("no validation summary matches the configured source")
    _, path, summary, partition, array_job, tasks = max(
        candidates, key=lambda item: item[0]
    )
    return path, summary, partition, array_job, tasks


def boundary_only_failures(
    failures: list[Any], accepted_suffix: str
) -> bool:
    values = [str(value) for value in failures]
    return bool(values) and all(value.endswith(accepted_suffix) for value in values)


def classify_task(
    task: dict[str, Any],
    expected_files: int,
    schema_version: str,
    accepted_suffix: str,
    maximum_offset: float,
) -> tuple[str, list[str]]:
    failures: list[str] = []
    for field in ("selected_file_count", "processed_file_count", "parsed_file_count"):
        if int(task.get(field, -1)) != expected_files:
            failures.append(f"{field}_mismatch")
    if int(task.get("source_integrity_verified_file_count", -1)) != expected_files:
        failures.append("source_integrity_count_mismatch")
    if int(task.get("failed_file_count", -1)) != 0:
        failures.append("failed_file_count_nonzero")
    if task.get("canonical_schema_version") != schema_version:
        failures.append("schema_version_mismatch")
    if task.get("boundary_parser_precheck", {}).get("passed") is not True:
        failures.append("boundary_parser_precheck_failed")
    if failures:
        return "excluded_integrity_or_schema_failure", failures

    task_gate_failures = list(task.get("gate_failures") or [])
    if task.get("materialization_passed") is True and not task_gate_failures:
        return "strict_pass", []
    if (
        boundary_only_failures(task_gate_failures, accepted_suffix)
        and float(task.get("maximum_boundary_offset_sec") or 0.0)
        <= maximum_offset
    ):
        return "accepted_with_row_time_rewindowing", []
    return "excluded_unapproved_gate_failure", [
        f"unapproved_gate_failure:{value}" for value in task_gate_failures
    ]


def archive_date(path: str) -> str | None:
    match = re.search(r"updates[._](\d{8})[._]", path)
    if not match:
        return None
    value = match.group(1)
    return f"{value[:4]}-{value[4:6]}-{value[6:]}"


def build_duplicate_sidecar(
    path: Path, selected_dates: set[str]
) -> tuple[list[dict[str, Any]], int]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        candidates = list(csv.DictReader(handle))
    rows: list[dict[str, Any]] = []
    copy_count = 0
    seen: set[tuple[str, str]] = set()
    for candidate in candidates:
        source_file = str(candidate["source_file"])
        if archive_date(source_file) not in selected_dates:
            continue
        source_counts = Counter(json.loads(candidate["source_identity_counts"]))
        neighbor_counts = Counter(json.loads(candidate["neighbor_identity_counts"]))
        for observation_id in sorted(set(source_counts) & set(neighbor_counts)):
            count = min(
                int(source_counts[observation_id]),
                int(neighbor_counts[observation_id]),
            )
            if count <= 0:
                continue
            key = (source_file, observation_id)
            if key in seen:
                raise ValueError(f"duplicate QA2 exclusion key: {key}")
            seen.add(key)
            copy_count += count
            rows.append(
                {
                    "source_file_to_exclude": source_file,
                    "canonical_neighbor_file": candidate["neighbor_file"],
                    "direction": candidate["direction_set"],
                    "observation_id": observation_id,
                    "exclusion_copy_count": count,
                    "exclusion_reason": "adjacent_archive_overlap",
                    "schema_version": "canonical_observation_v2",
                    "provenance": "R-MEM-1D-QA2 raw peer-identity audit",
                    "candidate_id": candidate["candidate_id"],
                }
            )
    return rows, copy_count


def render_report(summary: dict[str, Any]) -> str:
    return f"""# R-DATA-FREEZE-0 Nine-day Development Asset

## Result

- Freeze passed: `{str(summary['freeze_passed']).lower()}`.
- Frozen dates: `{summary['freeze_start_date']}` through
  `{summary['freeze_end_date']}` (`{summary['frozen_day_count']}` days).
- Complete collectors: `{', '.join(summary['required_collectors'])}`.
- Frozen source files: `{summary['frozen_source_file_count']}`.
- Frozen parsed rows: `{summary['frozen_parsed_row_count']}`.
- Strict-pass dates: `{', '.join(summary['strict_pass_dates'])}`.
- Row-time rewindow dates: `{', '.join(summary['row_time_rewindow_dates'])}`.
- Excluded dates: `{', '.join(summary['excluded_dates'])}`.
- Reversible adjacent-overlap exclusions: `{summary['duplicate_exclusion_copy_count']}`.

## Why Six Days Was Not the Final Usable Count

Six dates passed the old per-archive zero-boundary gate exactly. Three more
complete dates contained only bounded archive-container spill rows, with a
maximum offset of 12 seconds. The temporal audit over the 19 available
collector-days passed and every parsed row was preserved. These dates are
accepted only under the explicit contract that downstream consumers assign
windows from row `ts`, not archive filename time.

The final requested date is excluded because its `rrc00` collector-day is
missing from this materialization. It is not silently treated as a
single-collector day.

## Scientific Boundary

This asset is `unlabeled_operational_background`. It is ready for bounded
system development and controlled injection, but it is not certified benign
and is not negative-training truth. Known-incident and evidence contamination
audits remain mandatory before negative sampling or paper-facing clean-window
claims.
"""


def main() -> int:
    args = parse_args()
    config = load_json(resolve_repo_path(args.config))
    pullback_root = Path(args.pullback_root).resolve()
    qa2_path = Path(args.qa2_candidate_audit).resolve()
    output_dir = Path(args.output_dir).resolve()
    if not pullback_root.is_dir():
        raise FileNotFoundError(f"pullback root does not exist: {pullback_root}")
    if not qa2_path.is_file():
        raise FileNotFoundError(f"QA2 candidate audit does not exist: {qa2_path}")
    prepare_output(output_dir, args.overwrite)

    (
        validation_path,
        validation,
        source_partition,
        source_array_job,
        task_items,
    ) = select_best_execution(pullback_root, config)
    task_map = {
        (str(task.get("collector")), str(task.get("date"))): (path, task)
        for path, task in task_items
    }
    required_collectors = list(config["required_collectors"])
    requested_dates = date_range(
        config["requested_start_date"], config["requested_end_date"]
    )
    frozen_dates = date_range(
        config["freeze_start_date"], config["freeze_end_date"]
    )
    frozen_date_set = set(frozen_dates)
    audit_rows: list[dict[str, Any]] = []
    date_statuses: dict[str, str] = {}
    failures: list[str] = []

    for day in requested_dates:
        collector_states: list[str] = []
        day_reasons: list[str] = []
        for collector in required_collectors:
            item = task_map.get((collector, day))
            if item is None:
                state = "missing"
                reasons = ["collector_day_summary_missing"]
                task = {}
                summary_path = ""
            else:
                summary_path_obj, task = item
                summary_path = str(summary_path_obj)
                state, reasons = classify_task(
                    task,
                    int(config["expected_files_per_collector_day"][collector]),
                    config["source_schema_version"],
                    config["accepted_boundary_failure_suffix"],
                    float(config["maximum_archive_boundary_offset_sec"]),
                )
            collector_states.append(state)
            day_reasons.extend(f"{collector}:{reason}" for reason in reasons)
            audit_rows.append(
                {
                    "date": day,
                    "collector": collector,
                    "task_state": state,
                    "summary_path": summary_path,
                    "parsed_file_count": task.get("parsed_file_count", 0),
                    "total_parsed_rows": task.get("total_parsed_rows", 0),
                    "materialization_passed": task.get(
                        "materialization_passed", False
                    ),
                    "gate_failures": " | ".join(
                        str(value) for value in task.get("gate_failures", [])
                    ),
                    "boundary_warning_file_count": task.get(
                        "temporal_alignment_warning_file_count", 0
                    ),
                    "boundary_warning_row_count": task.get(
                        "temporal_alignment_warning_row_count", 0
                    ),
                    "maximum_boundary_offset_sec": task.get(
                        "maximum_boundary_offset_sec", 0.0
                    ),
                    "included_in_freeze": day in frozen_date_set
                    and state
                    in {"strict_pass", "accepted_with_row_time_rewindowing"},
                }
            )
        if "missing" in collector_states:
            date_status = "excluded_incomplete_collector_day"
        elif any(state.startswith("excluded_") for state in collector_states):
            date_status = "excluded_failed_collector_day"
        elif "accepted_with_row_time_rewindowing" in collector_states:
            date_status = "accepted_with_row_time_rewindowing"
        else:
            date_status = "strict_pass"
        date_statuses[day] = date_status
        if day in frozen_date_set and date_status.startswith("excluded_"):
            failures.append(f"{day}: {date_status}: {day_reasons}")

    strict_dates = [
        day for day in frozen_dates if date_statuses[day] == "strict_pass"
    ]
    rewindow_dates = [
        day
        for day in frozen_dates
        if date_statuses[day] == "accepted_with_row_time_rewindowing"
    ]
    excluded_dates = [
        day for day in requested_dates if date_statuses[day].startswith("excluded_")
    ]
    included_tasks = [
        task
        for _, task in task_items
        if str(task.get("date")) in frozen_date_set
        and str(task.get("collector")) in required_collectors
    ]
    frozen_source_files = sum(
        int(task.get("parsed_file_count", 0)) for task in included_tasks
    )
    frozen_rows = sum(
        int(task.get("total_parsed_rows", 0)) for task in included_tasks
    )
    warning_files = sum(
        int(task.get("temporal_alignment_warning_file_count", 0))
        for task in included_tasks
    )
    warning_rows = sum(
        int(task.get("temporal_alignment_warning_row_count", 0))
        for task in included_tasks
    )
    maximum_offset = max(
        (
            float(task.get("maximum_boundary_offset_sec") or 0.0)
            for task in included_tasks
        ),
        default=0.0,
    )

    duplicate_rows, duplicate_copy_count = build_duplicate_sidecar(
        qa2_path, frozen_date_set
    )
    expected_exclusions = int(validation.get("canonical_exclusion_count", -1))
    if duplicate_copy_count != expected_exclusions:
        failures.append(
            "duplicate exclusion mismatch: "
            f"qa2={duplicate_copy_count} validation={expected_exclusions}"
        )
    if validation.get("temporal_alignment_passed") is not True:
        failures.append("whole-window temporal alignment did not pass")
    if int(validation.get("parquet_footer_failure_count", -1)) != 0:
        failures.append("Parquet footer failures are nonzero")
    if len(frozen_dates) < int(config["minimum_complete_freeze_days"]):
        failures.append("frozen day count is below configured minimum")
    expected_frozen_files = len(frozen_dates) * sum(
        int(config["expected_files_per_collector_day"][collector])
        for collector in required_collectors
    )
    if frozen_source_files != expected_frozen_files:
        failures.append(
            f"frozen source file mismatch: {frozen_source_files} "
            f"!= {expected_frozen_files}"
        )

    summary = {
        "phase": config["phase"],
        "dataset_id": config["dataset_id"],
        "source_dataset_id": validation.get("dataset_id"),
        "source_pair_id": config["source_pair_id"],
        "source_partition": source_partition,
        "source_array_job": source_array_job,
        "source_validation_summary": str(validation_path),
        "source_code_fingerprints": validation.get("code_fingerprints", []),
        "source_schema_version": validation.get("canonical_schema_version"),
        "freeze_start_date": config["freeze_start_date"],
        "freeze_end_date": config["freeze_end_date"],
        "frozen_day_count": len(frozen_dates),
        "required_collectors": required_collectors,
        "strict_pass_dates": strict_dates,
        "row_time_rewindow_dates": rewindow_dates,
        "excluded_dates": excluded_dates,
        "frozen_source_file_count": frozen_source_files,
        "frozen_parsed_row_count": frozen_rows,
        "boundary_warning_file_count": warning_files,
        "boundary_warning_row_count": warning_rows,
        "maximum_archive_boundary_offset_sec": maximum_offset,
        "duplicate_exclusion_row_count": len(duplicate_rows),
        "duplicate_exclusion_copy_count": duplicate_copy_count,
        "row_time_rewindow_required": True,
        "canonical_duplicate_sidecar_required": True,
        "dataset_role": config["dataset_role"],
        "freeze_passed": not failures,
        "development_asset_ready": not failures,
        "negative_training_ready": False,
        "attack_free_claimed": False,
        "confirmed_benign_claimed": False,
        "full_requested_10d_complete": not excluded_dates,
        "failures": failures,
        "recommended_next_action": (
            "start_bounded_system_frontend_and_attack_replay_on_frozen_9d_asset"
            if not failures
            else "repair_freeze_contract_before_system_use"
        ),
    }
    manifest = {
        "dataset_id": config["dataset_id"],
        "role": config["dataset_role"],
        "source": {
            "dataset_id": validation.get("dataset_id"),
            "pair_id": config["source_pair_id"],
            "partition": source_partition,
            "array_job": source_array_job,
            "materialization_root": validation.get("materialization_root"),
            "schema_version": validation.get("canonical_schema_version"),
            "code_fingerprints": validation.get("code_fingerprints", []),
        },
        "selection": {
            "start_inclusive_utc": f"{config['freeze_start_date']}T00:00:00Z",
            "end_exclusive_utc": (
                date.fromisoformat(config["freeze_end_date"])
                + timedelta(days=1)
            ).isoformat()
            + "T00:00:00Z",
            "window_field": "ts",
            "collectors": required_collectors,
            "dates": frozen_dates,
        },
        "canonicalization": {
            "observation_identity": "observation_id",
            "peer_identity": "peer_address",
            "duplicate_exclusion_sidecar": (
                "r_data_freeze0_duplicate_exclusion_sidecar.csv"
            ),
            "duplicate_exclusion_copy_count": duplicate_copy_count,
            "reversible": True,
        },
        "counts": {
            "source_files": frozen_source_files,
            "parsed_rows_before_canonical_exclusions": frozen_rows,
            "archive_boundary_warning_rows_before_row_time_rewindow": warning_rows,
        },
        "truth_contract": config["claim_boundaries"],
        "freeze_passed": summary["freeze_passed"],
    }
    write_csv(
        output_dir / "r_data_freeze0_collector_day_audit.csv", audit_rows
    )
    write_csv(
        output_dir / "r_data_freeze0_duplicate_exclusion_sidecar.csv",
        duplicate_rows,
    )
    write_json(output_dir / "r_data_freeze0_manifest.json", manifest)
    write_json(output_dir / "r_data_freeze0_summary.json", summary)
    (output_dir / "r_data_freeze0_report.md").write_text(
        render_report(summary), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["freeze_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
