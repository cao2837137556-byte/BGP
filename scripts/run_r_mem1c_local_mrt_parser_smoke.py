#!/usr/bin/env python3
"""Stream a bounded local MRT sample into audited Parquet.

This parser uses BGPStream's singlefile data interface. It never contacts the
Broker and never materializes an uncompressed MRT intermediate. The output is
a parser/schema qualification artifact, not attack evidence or a truth label.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import shutil
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = "configs/r_mem1c_local_mrt_parser_smoke_v01.json"
ASN_RE = re.compile(r"^[0-9]+$")
WELL_KNOWN = {
    "65535:65281": "no_export",
    "65535:65282": "no_advertise",
    "65535:65283": "no_export_subconfed",
    "65535:65284": "nopeer",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--data-root", default="/data_store")
    parser.add_argument("--manifest")
    parser.add_argument("--output-dir")
    parser.add_argument("--files-per-collector", type=int)
    parser.add_argument("--max-rows-per-file", type=int, default=0)
    parser.add_argument("--plan-only", action="store_true")
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
    path.parent.mkdir(parents=True, exist_ok=True)
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
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def prepare_output(path: Path, overwrite: bool, plan_only: bool) -> None:
    if path.exists() and any(path.iterdir()):
        if not overwrite:
            raise FileExistsError(f"output directory is not empty: {path}")
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    if plan_only:
        return
    (path / "parsed").mkdir(parents=True, exist_ok=True)


def evenly_spaced(items: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    if count <= 0:
        raise ValueError("files_per_collector must be positive")
    if len(items) < count:
        raise ValueError(f"requested {count} samples from only {len(items)} items")
    if count == 1:
        return [items[0]]
    indexes = [round(index * (len(items) - 1) / (count - 1)) for index in range(count)]
    return [items[index] for index in sorted(set(indexes))]


def select_files(
    manifest: list[dict[str, Any]], files_per_collector: int
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    collectors = sorted({str(row["collector"]) for row in manifest})
    for collector in collectors:
        rows = sorted(
            [row for row in manifest if row["collector"] == collector],
            key=lambda row: row["archive_timestamp_utc"],
        )
        selected.extend(evenly_spaced(rows, files_per_collector))
    return sorted(selected, key=lambda row: (row["collector"], row["archive_timestamp_utc"]))


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def normalize_communities(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item)]
    text = str(value).strip()
    return text.split() if text else []


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def derive_origin(as_path: Any) -> tuple[str | None, str]:
    if as_path is None:
        return None, "missing_as_path"
    text = str(as_path).strip()
    if not text:
        return None, "missing_as_path"
    final_segment = text.split()[-1]
    if ASN_RE.fullmatch(final_segment):
        return final_segment, "derived_final_singleton_asn"
    if "{" in final_segment or "}" in final_segment:
        return None, "ambiguous_final_as_set"
    if "(" in final_segment or ")" in final_segment:
        return None, "ambiguous_final_confederation_segment"
    return None, "unrecognized_final_path_segment"


def element_to_row(
    elem: Any,
    source: dict[str, Any],
    source_relative_path: str,
) -> dict[str, Any]:
    fields = elem.fields
    communities = normalize_communities(fields.get("communities"))
    as_path = fields.get("as-path")
    origin_as, origin_provenance = derive_origin(as_path)
    return {
        "ts": float(elem.time),
        "collector": str(source["collector"]),
        "project": str(source["project"]),
        "type": str(elem.type),
        "peer_asn": safe_int(getattr(elem, "peer_asn", None)),
        "prefix": fields.get("prefix"),
        "as_path": str(as_path) if as_path is not None else None,
        "origin_as": origin_as,
        "origin_provenance": origin_provenance,
        "communities": communities,
        "next_hop": fields.get("next-hop"),
        "source_file": source_relative_path,
        "archive_timestamp_utc": source["archive_timestamp_utc"],
    }


def open_singlefile_stream(path: Path):
    import pybgpstream  # type: ignore

    options = {"upd-file": str(path)}
    try:
        return pybgpstream.BGPStream(
            data_interface="singlefile",
            data_interface_options=options,
        )
    except TypeError:
        stream = pybgpstream.BGPStream()
        stream.set_data_interface("singlefile")
        stream.set_data_interface_option("singlefile", "upd-file", str(path))
        return stream


def output_path(output_dir: Path, source: dict[str, Any], interval_minutes: int) -> Path:
    start = parse_utc(source["archive_timestamp_utc"])
    end = start + timedelta(minutes=interval_minutes)
    return (
        output_dir
        / "parsed"
        / f"collector={source['collector']}"
        / f"date={start.date().isoformat()}"
        / f"updates__{start.strftime('%H-%M-%S')}__{end.strftime('%H-%M-%S')}.parquet"
    )


def parquet_schema():
    import pyarrow as pa

    return pa.schema(
        [
            ("ts", pa.float64()),
            ("collector", pa.string()),
            ("project", pa.string()),
            ("type", pa.string()),
            ("peer_asn", pa.int64()),
            ("prefix", pa.string()),
            ("as_path", pa.string()),
            ("origin_as", pa.string()),
            ("origin_provenance", pa.string()),
            ("communities", pa.list_(pa.string())),
            ("next_hop", pa.string()),
            ("source_file", pa.string()),
            ("archive_timestamp_utc", pa.string()),
        ]
    )


def update_stats(stats: dict[str, Any], row: dict[str, Any], start: float, end: float) -> None:
    stats["rows"] += 1
    element_type = row["type"].upper()
    stats["type_counts"][element_type] += 1
    ts = row["ts"]
    stats["timestamp_present"] += int(math.isfinite(ts))
    stats["timestamp_min"] = ts if stats["timestamp_min"] is None else min(stats["timestamp_min"], ts)
    stats["timestamp_max"] = ts if stats["timestamp_max"] is None else max(stats["timestamp_max"], ts)
    stats["out_of_window_rows"] += int(ts < start or ts >= end)
    if element_type in {"A", "W"}:
        stats["update_rows"] += 1
        stats["update_prefix_present"] += int(bool(row["prefix"]))
    if element_type == "A":
        stats["announcement_rows"] += 1
        stats["announcement_as_path_present"] += int(bool(row["as_path"]))
        stats["origin_provenance_counts"][row["origin_provenance"]] += 1
    if row["communities"]:
        stats["community_nonempty_rows"] += 1
        for community, name in WELL_KNOWN.items():
            if community in row["communities"]:
                stats[f"{name}_rows"] += 1


def parse_file(
    source: dict[str, Any],
    data_root: Path,
    output_dir: Path,
    config: dict[str, Any],
    max_rows: int,
    preview: list[dict[str, Any]],
) -> dict[str, Any]:
    import pyarrow as pa
    import pyarrow.parquet as pq

    source_relative = str(source["local_relative_path"])
    source_path = data_root / source_relative
    if not source_path.is_file():
        return {
            "file_path": source_relative,
            "collector": source["collector"],
            "archive_timestamp_utc": source["archive_timestamp_utc"],
            "status": "failed",
            "error_type": "FileNotFoundError",
            "error": "selected source archive is missing",
        }
    actual_size = source_path.stat().st_size
    expected_size = int(source["size_bytes"])
    if actual_size != expected_size:
        return {
            "file_path": source_relative,
            "collector": source["collector"],
            "archive_timestamp_utc": source["archive_timestamp_utc"],
            "status": "failed",
            "error_type": "SourceSizeMismatch",
            "error": f"actual={actual_size} expected={expected_size}",
            "compressed_size_bytes": actual_size,
            "source_size_verified": False,
            "source_sha256_verified": False,
        }
    actual_sha256 = sha256_file(source_path)
    expected_sha256 = str(source["sha256"]).lower()
    if actual_sha256.lower() != expected_sha256:
        return {
            "file_path": source_relative,
            "collector": source["collector"],
            "archive_timestamp_utc": source["archive_timestamp_utc"],
            "status": "failed",
            "error_type": "SourceSha256Mismatch",
            "error": f"actual={actual_sha256} expected={expected_sha256}",
            "compressed_size_bytes": actual_size,
            "source_size_verified": True,
            "source_sha256_verified": False,
        }
    interval_minutes = int(config["collector_intervals_minutes"][source["collector"]])
    output = output_path(output_dir, source, interval_minutes)
    output.parent.mkdir(parents=True, exist_ok=True)
    expected_start = parse_utc(source["archive_timestamp_utc"])
    grace = float(config.get("timestamp_grace_sec", 0))
    expected_end = expected_start + timedelta(minutes=interval_minutes, seconds=grace)
    stats: dict[str, Any] = {
        "rows": 0,
        "update_rows": 0,
        "announcement_rows": 0,
        "timestamp_present": 0,
        "timestamp_min": None,
        "timestamp_max": None,
        "out_of_window_rows": 0,
        "update_prefix_present": 0,
        "announcement_as_path_present": 0,
        "community_nonempty_rows": 0,
        "no_export_rows": 0,
        "no_advertise_rows": 0,
        "no_export_subconfed_rows": 0,
        "nopeer_rows": 0,
        "type_counts": Counter(),
        "origin_provenance_counts": Counter(),
    }
    schema = parquet_schema()
    writer = pq.ParquetWriter(output, schema=schema, compression="zstd")
    batch: list[dict[str, Any]] = []
    parse_error: Exception | None = None
    try:
        stream = open_singlefile_stream(source_path)
        for elem in stream:
            row = element_to_row(elem, source, source_relative)
            update_stats(
                stats,
                row,
                expected_start.timestamp(),
                expected_end.timestamp(),
            )
            if len(preview) < int(config.get("preview_rows", 200)):
                preview.append({**row, "communities": "|".join(row["communities"])})
            batch.append(row)
            if len(batch) >= int(config.get("batch_rows", 100000)):
                writer.write_table(pa.Table.from_pylist(batch, schema=schema))
                batch.clear()
            if max_rows and stats["rows"] >= max_rows:
                break
        if batch:
            writer.write_table(pa.Table.from_pylist(batch, schema=schema))
    except Exception as exc:
        parse_error = exc
    finally:
        writer.close()

    if parse_error is not None:
        output.unlink(missing_ok=True)
        return {
            "file_path": source_relative,
            "collector": source["collector"],
            "archive_timestamp_utc": source["archive_timestamp_utc"],
            "status": "failed",
            "error_type": type(parse_error).__name__,
            "error": str(parse_error),
            "compressed_size_bytes": source_path.stat().st_size if source_path.exists() else None,
        }

    rows = int(stats["rows"])
    update_rows = int(stats["update_rows"])
    announcement_rows = int(stats["announcement_rows"])
    result = {
        "file_path": source_relative,
        "output_path": str(output),
        "collector": source["collector"],
        "project": source["project"],
        "archive_timestamp_utc": source["archive_timestamp_utc"],
        "expected_interval_minutes": interval_minutes,
        "status": "parsed",
        "compressed_size_bytes": actual_size,
        "source_size_verified": True,
        "source_sha256_verified": True,
        "parquet_size_bytes": output.stat().st_size,
        "rows": rows,
        "type_counts": json.dumps(dict(stats["type_counts"]), sort_keys=True),
        "announcement_rows": announcement_rows,
        "withdrawal_rows": int(stats["type_counts"].get("W", 0)),
        "other_type_rows": rows - int(stats["type_counts"].get("A", 0)) - int(stats["type_counts"].get("W", 0)),
        "timestamp_min": stats["timestamp_min"],
        "timestamp_max": stats["timestamp_max"],
        "timestamp_coverage": stats["timestamp_present"] / rows if rows else 0.0,
        "out_of_window_rows": stats["out_of_window_rows"],
        "update_prefix_coverage": stats["update_prefix_present"] / update_rows if update_rows else 0.0,
        "announcement_as_path_coverage": stats["announcement_as_path_present"] / announcement_rows if announcement_rows else 0.0,
        "community_nonempty_rows": stats["community_nonempty_rows"],
        "community_nonempty_rate": stats["community_nonempty_rows"] / rows if rows else 0.0,
        "no_export_rows": stats["no_export_rows"],
        "no_advertise_rows": stats["no_advertise_rows"],
        "no_export_subconfed_rows": stats["no_export_subconfed_rows"],
        "nopeer_rows": stats["nopeer_rows"],
        "origin_provenance_counts": json.dumps(dict(stats["origin_provenance_counts"]), sort_keys=True),
        "max_rows_applied": max_rows,
    }
    return result


def evaluate_gates(
    audits: list[dict[str, Any]], config: dict[str, Any]
) -> tuple[bool, list[str]]:
    gates = config["gates"]
    failures: list[str] = []
    parsed = [row for row in audits if row["status"] == "parsed"]
    required_collectors = set(gates["required_collectors"])
    observed_collectors = {row["collector"] for row in parsed}
    if observed_collectors != required_collectors:
        failures.append(
            f"collector coverage mismatch: observed={sorted(observed_collectors)} required={sorted(required_collectors)}"
        )
    if gates.get("require_community_column", False):
        if "communities" not in parquet_schema().names:
            failures.append("communities column is absent from the Parquet schema")
    for row in audits:
        label = f"{row['collector']}:{row['archive_timestamp_utc']}"
        if row["status"] != "parsed":
            failures.append(f"{label}: parse failed: {row.get('error')}")
            continue
        if int(row["rows"]) < int(gates["minimum_rows_per_file"]):
            failures.append(f"{label}: no parsed rows")
        if float(row["timestamp_coverage"]) < float(gates["minimum_timestamp_coverage"]):
            failures.append(f"{label}: timestamp coverage below gate")
        if float(row["update_prefix_coverage"]) < float(gates["minimum_update_prefix_coverage"]):
            failures.append(f"{label}: update prefix coverage below gate")
        if row["announcement_rows"] and float(row["announcement_as_path_coverage"]) < float(
            gates["minimum_announcement_as_path_coverage"]
        ):
            failures.append(f"{label}: announcement AS_PATH coverage below gate")
        if int(row["out_of_window_rows"]) > int(gates["maximum_out_of_window_rows"]):
            failures.append(f"{label}: timestamps outside archive interval")
    return not failures, failures


def schema_payload() -> dict[str, Any]:
    schema = parquet_schema()
    return {
        "fields": [
            {"name": field.name, "type": str(field.type), "nullable": field.nullable}
            for field in schema
        ],
        "origin_contract": {
            "derived_final_singleton_asn": "origin derived only when the final AS_PATH segment is one decimal ASN",
            "ambiguous_final_as_set": "origin left null",
            "ambiguous_final_confederation_segment": "origin left null",
            "missing_as_path": "origin left null",
        },
        "community_contract": "raw parsed standard communities are retained as list<string>; absence is not a safety claim",
    }


def render_report(summary: dict[str, Any]) -> str:
    return f"""# R-MEM-1C Local MRT Parser Smoke Report

## Result

- parser smoke passed: `{str(summary['parser_smoke_passed']).lower()}`
- selected files: `{summary['selected_file_count']}`
- parsed files: `{summary['parsed_file_count']}`
- total parsed rows: `{summary['total_parsed_rows']}`
- announcements: `{summary['announcement_rows']}`
- withdrawals: `{summary['withdrawal_rows']}`
- rows with communities: `{summary['community_nonempty_rows']}`
- compressed input bytes: `{summary['compressed_input_bytes']}`
- Parquet output bytes: `{summary['parquet_output_bytes']}`
- gate failures: `{summary['gate_failures']}`

## Boundaries

This smoke qualifies local binary parsing and schema preservation only. It does
not modify foreground policy, establish attack or benign truth, train learning,
or prove 10-day path maturity. NO_EXPORT presence remains propagation-control
evidence; absence remains non-conclusive.
"""


def main() -> int:
    args = parse_args()
    config_path = resolve_repo_path(args.config)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    data_root = Path(args.data_root).resolve()
    manifest_path = (
        Path(args.manifest).resolve()
        if args.manifest
        else data_root / config["manifest_relative_path"]
    )
    output_dir = (
        Path(args.output_dir).resolve()
        if args.output_dir
        else data_root / config["default_output_relative_path"]
    )
    files_per_collector = args.files_per_collector or int(config["files_per_collector"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if len(manifest) != 3840:
        raise ValueError(f"expected complete 3,840-file manifest, found {len(manifest)}")
    relative_paths = [str(row["local_relative_path"]) for row in manifest]
    if len(relative_paths) != len(set(relative_paths)):
        raise ValueError("manifest contains duplicate local_relative_path values")
    selected = select_files(manifest, files_per_collector)
    prepare_output(output_dir, args.overwrite, args.plan_only)
    plan = {
        "phase": config["phase"],
        "dataset_id": config["dataset_id"],
        "config_path": str(config_path),
        "manifest_path": str(manifest_path),
        "data_root": str(data_root),
        "output_dir": str(output_dir),
        "manifest_file_count": len(manifest),
        "selected_file_count": len(selected),
        "selected_by_collector": dict(Counter(row["collector"] for row in selected)),
        "selected_files": selected,
        "plan_only": args.plan_only,
    }
    write_json(output_dir / "r_mem1c_parse_plan.json", plan)
    print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
    if args.plan_only:
        return 0

    preview: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []
    for index, source in enumerate(selected, start=1):
        result = parse_file(
            source,
            data_root,
            output_dir,
            config,
            args.max_rows_per_file,
            preview,
        )
        audits.append(result)
        print(
            f"parsed={index}/{len(selected)} collector={source['collector']} "
            f"status={result['status']} rows={result.get('rows', 0)}",
            flush=True,
        )

    passed, failures = evaluate_gates(audits, config)
    if config["gates"].get("require_full_selected_file_parse", False) and args.max_rows_per_file:
        failures.append(
            "max_rows_per_file was applied; a capped debug run cannot qualify the formal smoke"
        )
        passed = False
    parsed = [row for row in audits if row["status"] == "parsed"]
    summary = {
        "phase": config["phase"],
        "dataset_id": config["dataset_id"],
        "parser_smoke_passed": passed,
        "selected_file_count": len(selected),
        "parsed_file_count": len(parsed),
        "failed_file_count": len(audits) - len(parsed),
        "selected_by_collector": dict(Counter(row["collector"] for row in selected)),
        "total_parsed_rows": sum(int(row["rows"]) for row in parsed),
        "announcement_rows": sum(int(row["announcement_rows"]) for row in parsed),
        "withdrawal_rows": sum(int(row["withdrawal_rows"]) for row in parsed),
        "community_nonempty_rows": sum(int(row["community_nonempty_rows"]) for row in parsed),
        "community_column_present": "communities" in parquet_schema().names,
        "source_integrity_verified_file_count": sum(
            int(bool(row.get("source_size_verified")) and bool(row.get("source_sha256_verified")))
            for row in parsed
        ),
        "compressed_input_bytes": sum(int(row["compressed_size_bytes"]) for row in parsed),
        "parquet_output_bytes": sum(int(row["parquet_size_bytes"]) for row in parsed),
        "gate_failures": failures,
        "max_rows_per_file": args.max_rows_per_file,
        "full_parse_per_selected_file": args.max_rows_per_file == 0,
        "recommended_next_step": (
            "run full 10-day local-MRT parsing with checkpointed per-file outputs"
            if passed
            else "repair parser/schema contract before any full parse"
        ),
        "claims": {
            "attack_or_benign_truth_produced": False,
            "foreground_modified": False,
            "learning_trained": False,
            "path_maturity_proven": False,
        },
    }
    write_json(output_dir / "r_mem1c_summary.json", summary)
    write_json(output_dir / "r_mem1c_schema.json", schema_payload())
    write_csv(output_dir / "r_mem1c_file_audit.csv", audits)
    write_csv(output_dir / "r_mem1c_preview.csv", preview)
    (output_dir / "r_mem1c_report.md").write_text(
        render_report(summary), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
