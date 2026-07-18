#!/usr/bin/env python3
"""Audit bounded MRT archive spill and adjacent-file overlap for R-MEM-1D."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable

from run_r_mem1c_local_mrt_parser_smoke import parse_utc, parquet_schema
from r_mem_canonical_observation_v2 import parquet_schema_v2


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = "configs/r_mem1d_10d_parquet_materialization_v01.json"
ACTIVE_SCHEMA_BUILDER = parquet_schema


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--materialization-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--schema-version", choices=("v1", "v2"), default="v1")
    return parser.parse_args()


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def write_json(path: Path, payload: Any) -> None:
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


def read_audits(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("r_mem1d_file_audit.csv")):
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                row["task_audit_path"] = str(path)
                rows.append(row)
    return rows


def scalar(value: Any) -> Any:
    if hasattr(value, "as_py"):
        return value.as_py()
    return value


def fingerprint(row: dict[str, Any]) -> str:
    payload = {
        field: scalar(row.get(field))
        for field in ACTIVE_SCHEMA_BUILDER().names
        if field not in {"source_file", "archive_timestamp_utc"}
    }
    if "observation_id" in payload and not payload["observation_id"]:
        payload["non_deduplicable_source_file"] = scalar(row.get("source_file"))
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def read_filtered_rows(
    path: Path,
    predicate: Callable[[float], bool],
    row_group_may_match: Callable[[float, float], bool],
) -> list[dict[str, Any]]:
    import pyarrow.parquet as pq

    parquet = pq.ParquetFile(path)
    fields = ACTIVE_SCHEMA_BUILDER().names
    ts_index = parquet.schema_arrow.names.index("ts")
    rows: list[dict[str, Any]] = []
    for group_index in range(parquet.num_row_groups):
        column = parquet.metadata.row_group(group_index).column(ts_index)
        stats = column.statistics
        if stats is not None and not row_group_may_match(
            float(stats.min), float(stats.max)
        ):
            continue
        table = parquet.read_row_group(group_index, columns=fields)
        for row in table.to_pylist():
            ts = row.get("ts")
            if ts is not None and predicate(float(ts)):
                rows.append(row)
    return rows


def main() -> int:
    global ACTIVE_SCHEMA_BUILDER
    args = parse_args()
    ACTIVE_SCHEMA_BUILDER = (
        parquet_schema_v2 if args.schema_version == "v2" else parquet_schema
    )
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

    audits = read_audits(root)
    index = {
        (str(row["collector"]), str(row["archive_timestamp_utc"])): row
        for row in audits
    }
    results: list[dict[str, Any]] = []
    duplicate_examples: list[dict[str, Any]] = []
    duplicate_exclusions: list[dict[str, Any]] = []
    exclusion_keys: set[tuple[str, str]] = set()
    failures: list[str] = []

    for row in audits:
        outside = int(float(row.get("out_of_window_rows") or 0))
        if outside <= 0:
            continue
        collector = str(row["collector"])
        start_dt = parse_utc(str(row["archive_timestamp_utc"]))
        interval = int(config["collector_intervals_minutes"][collector])
        grace = float(config.get("timestamp_grace_sec", 0))
        nominal_start = start_dt.timestamp()
        accepted_end = (start_dt + timedelta(minutes=interval)).timestamp() + grace
        path = Path(str(row["output_path"]))

        early_rows = read_filtered_rows(
            path,
            lambda ts: ts < nominal_start,
            lambda minimum, _maximum: minimum < nominal_start,
        )
        late_rows = read_filtered_rows(
            path,
            lambda ts: ts >= accepted_end,
            lambda _minimum, maximum: maximum >= accepted_end,
        )
        observed_outside = len(early_rows) + len(late_rows)
        if observed_outside != outside:
            failures.append(
                f"{row['file_path']}: audit count={outside} row scan={observed_outside}"
            )

        checks = [
            (
                "early",
                early_rows,
                start_dt - timedelta(minutes=interval),
            ),
            (
                "late",
                late_rows,
                start_dt + timedelta(minutes=interval),
            ),
        ]
        for direction, spill_rows, neighbor_dt in checks:
            if not spill_rows:
                continue
            neighbor = index.get((collector, neighbor_dt.strftime("%Y-%m-%dT%H:%M:%SZ")))
            neighbor_rows: list[dict[str, Any]] = []
            minimum_spill_ts = min(float(item["ts"]) for item in spill_rows)
            maximum_spill_ts = max(float(item["ts"]) for item in spill_rows)
            if neighbor:
                neighbor_rows = read_filtered_rows(
                    Path(str(neighbor["output_path"])),
                    lambda ts, minimum=minimum_spill_ts, maximum=maximum_spill_ts: (
                        minimum <= ts <= maximum
                    ),
                    lambda minimum, maximum, spill_min=minimum_spill_ts, spill_max=maximum_spill_ts: (
                        maximum >= spill_min and minimum <= spill_max
                    ),
                )
            else:
                failures.append(
                    f"{row['file_path']}: missing {direction} adjacent archive for spill audit"
                )
            spill_fingerprints = {fingerprint(item) for item in spill_rows}
            neighbor_fingerprints = {fingerprint(item) for item in neighbor_rows}
            duplicates = sorted(spill_fingerprints & neighbor_fingerprints)
            if duplicates:
                if args.schema_version == "v1":
                    failures.append(
                        f"{row['file_path']}: {len(duplicates)} potential adjacent duplicates"
                    )
                for digest in duplicates:
                    duplicate_examples.append(
                        {
                            "source_file": row["file_path"],
                            "direction": direction,
                            "neighbor_file": neighbor.get("file_path") if neighbor else "",
                            "fingerprint": digest,
                        }
                    )
                    exclusion_key = (str(row["file_path"]), digest)
                    if exclusion_key not in exclusion_keys:
                        exclusion_keys.add(exclusion_key)
                        duplicate_exclusions.append(
                            {
                                "source_file_to_exclude": row["file_path"],
                                "canonical_neighbor_file": (
                                    neighbor.get("file_path") if neighbor else ""
                                ),
                                "direction": direction,
                                "observation_fingerprint": digest,
                                "exclusion_reason": "adjacent_archive_overlap",
                                "schema_version": args.schema_version,
                            }
                        )
            results.append(
                {
                    "collector": collector,
                    "archive_timestamp_utc": row["archive_timestamp_utc"],
                    "source_file": row["file_path"],
                    "direction": direction,
                    "spill_row_count": len(spill_rows),
                    "neighbor_available": neighbor is not None,
                    "neighbor_file": neighbor.get("file_path") if neighbor else "",
                    "neighbor_boundary_row_count": len(neighbor_rows),
                    "potential_duplicate_count": len(duplicates),
                    "maximum_boundary_offset_sec": row.get(
                        "maximum_boundary_offset_sec", 0.0
                    ),
                }
            )

    summary = {
        "canonical_schema_version": args.schema_version,
        "phase": config["phase"],
        "temporal_alignment_passed": not failures,
        "source_complete_materialization_passed": not failures,
        "materialization_root": str(root),
        "file_audit_row_count": len(audits),
        "boundary_warning_file_count": sum(
            int(float(row.get("out_of_window_rows") or 0) > 0) for row in audits
        ),
        "boundary_warning_row_count": sum(
            int(float(row.get("out_of_window_rows") or 0)) for row in audits
        ),
        "adjacent_boundary_check_count": len(results),
        "potential_duplicate_count": sum(
            int(row["potential_duplicate_count"]) for row in results
        ),
        "canonical_exclusion_count": len(duplicate_exclusions),
        "canonical_view_ready_without_exclusions": (
            not failures and not duplicate_exclusions
        ),
        "canonical_view_requires_exclusion_sidecar": bool(duplicate_exclusions),
        "missing_adjacent_file_check_count": sum(
            int(not bool(row["neighbor_available"])) for row in results
        ),
        "failures": failures,
        "claims": {
            "boundary_warning_is_attack_signal": False,
            "adjacent_archive_overlap_is_attack_signal": False,
            "duplicate_rows_silently_deleted": False,
            "rows_deleted": False,
            "attack_or_benign_truth_produced": False,
        },
    }
    write_csv(output_dir / "r_mem1d_temporal_alignment_audit.csv", results)
    write_csv(output_dir / "r_mem1d_potential_duplicate_examples.csv", duplicate_examples)
    write_csv(
        output_dir / "r_mem1d_duplicate_exclusion_sidecar.csv",
        duplicate_exclusions,
    )
    write_json(output_dir / "r_mem1d_temporal_alignment_summary.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
