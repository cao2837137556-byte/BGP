#!/usr/bin/env python3
"""Resolve R-MEM-1D adjacent-archive duplicate candidates with peer identity."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
import types
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import timedelta
from pathlib import Path
from typing import Any

from audit_r_mem1d_temporal_alignment import (
    parse_utc,
    read_audits,
    read_filtered_rows,
)
from run_r_mem1c_local_mrt_parser_smoke import element_to_row, parquet_schema


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = "configs/r_mem1d_qa2_boundary_identity_v01.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--materialization-root")
    parser.add_argument("--data-root")
    parser.add_argument("--output-dir")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--self-test", action="store_true")
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


def normalize_text(value: Any) -> str:
    return "" if value is None else str(value)


def canonical_base_fingerprint(row: dict[str, Any]) -> str:
    payload: dict[str, Any] = {}
    for field in parquet_schema().names:
        if field in {"source_file", "archive_timestamp_utc"}:
            continue
        value = row.get(field)
        if hasattr(value, "as_py"):
            value = value.as_py()
        if field == "communities" and value is not None:
            value = sorted(str(item) for item in value)
        payload[field] = value
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def raw_identity(
    base_fingerprint: str,
    peer_address: Any,
    router: Any,
    router_ip: Any,
) -> str:
    basis, value = identity_basis(peer_address, router, router_ip)
    payload = {
        "base_fingerprint": base_fingerprint,
        "identity_basis": basis,
        "identity_value": value,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()


def identity_basis(peer_address: Any, router: Any, router_ip: Any) -> tuple[str, str]:
    peer_text = normalize_text(peer_address)
    if peer_text:
        return "peer_address", peer_text
    router_ip_text = normalize_text(router_ip)
    if router_ip_text:
        return "router_ip_fallback", router_ip_text
    router_text = normalize_text(router)
    if router_text:
        return "router_fallback", router_text
    return "missing", ""


def classify_identity_overlap(
    parquet_source_count: int,
    parquet_neighbor_count: int,
    source_identities: Counter[str],
    neighbor_identities: Counter[str],
) -> dict[str, Any]:
    source_raw_count = sum(source_identities.values())
    neighbor_raw_count = sum(neighbor_identities.values())
    shared = set(source_identities) & set(neighbor_identities)
    same_identity_overlap_count = sum(
        min(source_identities[item], neighbor_identities[item]) for item in shared
    )
    complete = (
        source_raw_count == parquet_source_count
        and neighbor_raw_count == parquet_neighbor_count
    )
    if not complete:
        classification = "unresolved_raw_parquet_multiplicity_mismatch"
    elif same_identity_overlap_count == 0:
        classification = "distinct_peer_observation_collision"
    elif (
        same_identity_overlap_count == source_raw_count
        and same_identity_overlap_count == neighbor_raw_count
    ):
        classification = "archive_overlap_duplicate_candidate"
    else:
        classification = "mixed_identity_overlap"
    return {
        "classification": classification,
        "source_raw_count": source_raw_count,
        "neighbor_raw_count": neighbor_raw_count,
        "source_identity_count": len(source_identities),
        "neighbor_identity_count": len(neighbor_identities),
        "shared_identity_count": len(shared),
        "same_identity_overlap_count": same_identity_overlap_count,
        "raw_parquet_multiplicity_complete": complete,
    }


def run_self_test() -> int:
    row_a = {field: None for field in parquet_schema().names}
    row_b = dict(row_a)
    row_a["communities"] = ["64500:2", "64500:1"]
    row_b["communities"] = ["64500:1", "64500:2"]
    assert canonical_base_fingerprint(row_a) == canonical_base_fingerprint(row_b)
    exact = classify_identity_overlap(1, 1, Counter({"a": 1}), Counter({"a": 1}))
    assert exact["classification"] == "archive_overlap_duplicate_candidate"
    distinct = classify_identity_overlap(
        1, 1, Counter({"a": 1}), Counter({"b": 1})
    )
    assert distinct["classification"] == "distinct_peer_observation_collision"
    mixed = classify_identity_overlap(
        2, 2, Counter({"a": 1, "b": 1}), Counter({"a": 1, "c": 1})
    )
    assert mixed["classification"] == "mixed_identity_overlap"
    unresolved = classify_identity_overlap(
        2, 2, Counter({"a": 1}), Counter({"a": 1})
    )
    assert unresolved["classification"] == "unresolved_raw_parquet_multiplicity_mismatch"

    class FakeRecord:
        router = "router-a"
        router_ip = "192.0.2.10"

    class FakeElement:
        time = 1712448899.0
        type = "A"
        peer_asn = 64500
        peer_address = "192.0.2.20"
        record = FakeRecord()
        fields = {
            "prefix": "203.0.113.0/24",
            "as-path": "64500 64496",
            "communities": {"64500:2", "64500:1"},
            "next-hop": "192.0.2.1",
        }

    class FakeStream:
        def __init__(self, data_interface: str):
            assert data_interface == "singlefile"

        def set_data_interface_option(self, *_args: Any) -> None:
            return None

        def __iter__(self):
            return iter([FakeElement()])

    fake_source = {
        "collector": "route-views.sg",
        "project": "routeviews",
        "archive_timestamp_utc": "2024-04-07T00:15:00Z",
    }
    fake_row = element_to_row(FakeElement(), fake_source, "raw/fake.bz2")
    fake_digest = canonical_base_fingerprint(fake_row)
    previous = sys.modules.get("pybgpstream")
    sys.modules["pybgpstream"] = types.SimpleNamespace(BGPStream=FakeStream)
    try:
        raw_result = inspect_raw_archive(
            {
                "file_path": "raw/fake.bz2",
                "raw_path": "unused-by-fake-stream",
                "target_fingerprints": [fake_digest],
                "source_metadata": fake_source,
            }
        )
        assert raw_result["status"] == "parsed"
        assert raw_result["matched_element_count"] == 1
        assert raw_result["matches"][0]["peer_address"] == "192.0.2.20"
        assert raw_result["matches"][0]["identity_basis"] == "peer_address"
    finally:
        if previous is None:
            del sys.modules["pybgpstream"]
        else:
            sys.modules["pybgpstream"] = previous
    print("self_test=passed")
    return 0


def find_duplicate_candidates(
    materialization_root: Path,
    materialization_config: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], list[str]]:
    audits = read_audits(materialization_root)
    index = {
        (str(row["collector"]), str(row["archive_timestamp_utc"])): row
        for row in audits
    }
    candidate_index: dict[tuple[str, str, str], dict[str, Any]] = {}
    failures: list[str] = []
    for row in audits:
        outside = int(float(row.get("out_of_window_rows") or 0))
        if outside <= 0:
            continue
        collector = str(row["collector"])
        start_dt = parse_utc(str(row["archive_timestamp_utc"]))
        interval = int(materialization_config["collector_intervals_minutes"][collector])
        grace = float(materialization_config.get("timestamp_grace_sec", 0))
        nominal_start = start_dt.timestamp()
        accepted_end = (start_dt + timedelta(minutes=interval)).timestamp() + grace
        source_output = Path(str(row["output_path"]))
        early_rows = read_filtered_rows(
            source_output,
            lambda ts: ts < nominal_start,
            lambda minimum, _maximum: minimum < nominal_start,
        )
        late_rows = read_filtered_rows(
            source_output,
            lambda ts: ts >= accepted_end,
            lambda _minimum, maximum: maximum >= accepted_end,
        )
        for direction, spill_rows, neighbor_dt in (
            ("early", early_rows, start_dt - timedelta(minutes=interval)),
            ("late", late_rows, start_dt + timedelta(minutes=interval)),
        ):
            if not spill_rows:
                continue
            neighbor = index.get(
                (collector, neighbor_dt.strftime("%Y-%m-%dT%H:%M:%SZ"))
            )
            if neighbor is None:
                failures.append(
                    f"{row['file_path']}: missing {direction} adjacent archive"
                )
                continue
            minimum_ts = min(float(item["ts"]) for item in spill_rows)
            maximum_ts = max(float(item["ts"]) for item in spill_rows)
            neighbor_rows = read_filtered_rows(
                Path(str(neighbor["output_path"])),
                lambda ts, low=minimum_ts, high=maximum_ts: low <= ts <= high,
                lambda low, high, spill_low=minimum_ts, spill_high=maximum_ts: (
                    high >= spill_low and low <= spill_high
                ),
            )
            source_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
            neighbor_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for item in spill_rows:
                source_groups[canonical_base_fingerprint(item)].append(item)
            for item in neighbor_rows:
                neighbor_groups[canonical_base_fingerprint(item)].append(item)
            for digest in sorted(set(source_groups) & set(neighbor_groups)):
                source_file = str(row["file_path"])
                neighbor_file = str(neighbor["file_path"])
                ordered_files = tuple(sorted((source_file, neighbor_file)))
                key = (ordered_files[0], ordered_files[1], digest)
                representative = source_groups[digest][0]
                existing = candidate_index.get(key)
                if existing is None:
                    candidate_index[key] = {
                        "candidate_id": hashlib.sha256(
                            "|".join(key).encode("utf-8")
                        ).hexdigest()[:20],
                        "source_file": source_file,
                        "neighbor_file": neighbor_file,
                        "collector": collector,
                        "direction_set": {direction},
                        "base_fingerprint": digest,
                        "parquet_source_count": len(source_groups[digest]),
                        "parquet_neighbor_count": len(neighbor_groups[digest]),
                        "ts": representative.get("ts"),
                        "type": representative.get("type"),
                        "peer_asn": representative.get("peer_asn"),
                        "prefix": representative.get("prefix"),
                        "as_path": representative.get("as_path"),
                    }
                else:
                    existing["direction_set"].add(direction)
    candidates = []
    for row in candidate_index.values():
        row["direction_set"] = "|".join(sorted(row["direction_set"]))
        candidates.append(row)
    candidates.sort(
        key=lambda item: (
            item["source_file"], item["neighbor_file"], item["base_fingerprint"]
        )
    )
    audit_by_path = {str(row["file_path"]): row for row in audits}
    return candidates, audit_by_path, failures


def inspect_raw_archive(spec: dict[str, Any]) -> dict[str, Any]:
    path = Path(spec["raw_path"])
    result: dict[str, Any] = {
        "file_path": spec["file_path"],
        "raw_path": str(path),
        "status": "failed",
        "error": "",
        "parsed_element_count": 0,
        "matched_element_count": 0,
        "matches": [],
    }
    try:
        import pybgpstream  # type: ignore

        stream = pybgpstream.BGPStream(data_interface="singlefile")
        stream.set_data_interface_option("singlefile", "upd-file", str(path))
        targets = set(spec["target_fingerprints"])
        for elem in stream:
            result["parsed_element_count"] += 1
            row = element_to_row(elem, spec["source_metadata"], spec["file_path"])
            digest = canonical_base_fingerprint(row)
            if digest not in targets:
                continue
            record = getattr(elem, "record", None)
            peer_address = getattr(elem, "peer_address", None)
            router = getattr(record, "router", None) if record is not None else None
            router_ip = (
                getattr(record, "router_ip", None) if record is not None else None
            )
            basis, _identity_value = identity_basis(peer_address, router, router_ip)
            result["matches"].append(
                {
                    "file_path": spec["file_path"],
                    "base_fingerprint": digest,
                    "observation_identity": raw_identity(
                        digest, peer_address, router, router_ip
                    ),
                    "peer_address": normalize_text(peer_address),
                    "router": normalize_text(router),
                    "router_ip": normalize_text(router_ip),
                    "identity_basis": basis,
                    "ts": row.get("ts"),
                    "peer_asn": row.get("peer_asn"),
                    "prefix": row.get("prefix"),
                    "type": row.get("type"),
                }
            )
        result["matched_element_count"] = len(result["matches"])
        result["status"] = "parsed"
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def build_raw_specs(
    candidates: list[dict[str, Any]],
    audit_by_path: dict[str, dict[str, Any]],
    data_root: Path,
) -> list[dict[str, Any]]:
    targets: dict[str, set[str]] = defaultdict(set)
    for row in candidates:
        targets[row["source_file"]].add(row["base_fingerprint"])
        targets[row["neighbor_file"]].add(row["base_fingerprint"])
    specs: list[dict[str, Any]] = []
    for file_path, digests in sorted(targets.items()):
        audit = audit_by_path[file_path]
        specs.append(
            {
                "file_path": file_path,
                "raw_path": str(data_root / file_path),
                "target_fingerprints": sorted(digests),
                "source_metadata": {
                    "collector": audit["collector"],
                    "project": audit["project"],
                    "archive_timestamp_utc": audit["archive_timestamp_utc"],
                },
            }
        )
    return specs


def inspect_raw_archives(
    specs: list[dict[str, Any]], workers: int
) -> list[dict[str, Any]]:
    if workers <= 1:
        return [inspect_raw_archive(spec) for spec in specs]
    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(inspect_raw_archive, spec): spec for spec in specs}
        for future in as_completed(futures):
            results.append(future.result())
    return sorted(results, key=lambda item: item["file_path"])


def report(summary: dict[str, Any]) -> str:
    counts = summary["classification_counts"]
    lines = [
        "# R-MEM-1D-QA2 Boundary Observation Identity Audit",
        "",
        "## Result",
        "",
        f"- Unique base-fingerprint candidates: `{summary['unique_candidate_count']}`.",
        f"- Raw archives replayed: `{summary['raw_archive_count']}`.",
        f"- Identity audit passed: `{str(summary['identity_audit_passed']).lower()}`.",
        f"- Safe to deduplicate using the old base fingerprint: `{str(summary['safe_to_deduplicate_current_fingerprint']).lower()}`.",
        f"- Recommended next action: `{summary['recommended_next_action']}`.",
        "",
        "## Classification",
        "",
        "| Classification | Count |",
        "|---|---:|",
    ]
    for key, value in sorted(counts.items()):
        lines.append(f"| {key} | {value} |")
    lines.extend(
        [
            "",
            "## Scientific Boundary",
            "",
            "A Parquet base-fingerprint match is not a deletion rule. The current",
            "materialization omits peer address, so raw MRT peer identity must be",
            "recovered before archive overlap can be distinguished from separate",
            "observations emitted by different peers in the same ASN. No row is",
            "deleted or rewritten in this audit.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test()
    if not args.materialization_root or not args.data_root or not args.output_dir:
        raise SystemExit(
            "--materialization-root, --data-root, and --output-dir are required"
        )
    config = json.loads(resolve_repo_path(args.config).read_text(encoding="utf-8"))
    materialization_config_path = resolve_repo_path(config["materialization_config"])
    materialization_config = json.loads(
        materialization_config_path.read_text(encoding="utf-8")
    )
    root = Path(args.materialization_root).resolve()
    data_root = Path(args.data_root).resolve()
    output_dir = Path(args.output_dir).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"materialization root does not exist: {root}")
    if output_dir.exists() and any(output_dir.iterdir()):
        if not args.overwrite:
            raise FileExistsError(f"output directory is non-empty: {output_dir}")
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    candidates, audit_by_path, discovery_failures = find_duplicate_candidates(
        root, materialization_config
    )
    specs = build_raw_specs(candidates, audit_by_path, data_root)
    missing_raw = [spec["raw_path"] for spec in specs if not Path(spec["raw_path"]).is_file()]
    if missing_raw:
        raise FileNotFoundError(f"missing raw archives: {missing_raw[:5]}")
    workers = max(1, min(args.workers, int(config.get("maximum_workers", 4))))
    raw_results = inspect_raw_archives(specs, workers)
    raw_failures = [
        f"{row['file_path']}: {row['error']}"
        for row in raw_results
        if row["status"] != "parsed"
    ]
    matches_by_file: dict[str, dict[str, Counter[str]]] = defaultdict(
        lambda: defaultdict(Counter)
    )
    raw_match_rows: list[dict[str, Any]] = []
    raw_file_rows: list[dict[str, Any]] = []
    for result in raw_results:
        raw_file_rows.append(
            {
                key: result[key]
                for key in (
                    "file_path",
                    "raw_path",
                    "status",
                    "error",
                    "parsed_element_count",
                    "matched_element_count",
                )
            }
        )
        for match in result["matches"]:
            raw_match_rows.append(match)
            matches_by_file[match["file_path"]][match["base_fingerprint"]][
                match["observation_identity"]
            ] += 1

    classified_rows: list[dict[str, Any]] = []
    for candidate in candidates:
        source_counts = matches_by_file[candidate["source_file"]][
            candidate["base_fingerprint"]
        ]
        neighbor_counts = matches_by_file[candidate["neighbor_file"]][
            candidate["base_fingerprint"]
        ]
        outcome = classify_identity_overlap(
            int(candidate["parquet_source_count"]),
            int(candidate["parquet_neighbor_count"]),
            source_counts,
            neighbor_counts,
        )
        classified_rows.append(
            {
                **candidate,
                **outcome,
                "source_identity_counts": json.dumps(source_counts, sort_keys=True),
                "neighbor_identity_counts": json.dumps(neighbor_counts, sort_keys=True),
            }
        )

    classification_counts = Counter(
        row["classification"] for row in classified_rows
    )
    identity_basis_counts = Counter(row["identity_basis"] for row in raw_match_rows)
    unresolved_count = sum(
        value
        for key, value in classification_counts.items()
        if key.startswith("unresolved")
    )
    distinct_or_mixed_count = sum(
        classification_counts.get(key, 0)
        for key in (
            "distinct_peer_observation_collision",
            "mixed_identity_overlap",
        )
    )
    failures = discovery_failures + raw_failures
    identity_audit_passed = not failures and unresolved_count == 0
    safe_to_deduplicate = (
        identity_audit_passed
        and bool(classified_rows)
        and distinct_or_mixed_count == 0
        and classification_counts.get("archive_overlap_duplicate_candidate", 0)
        == len(classified_rows)
    )
    if not classified_rows and identity_audit_passed:
        next_action = "no_overlap_candidates_validate_without_deduplication"
    elif not identity_audit_passed:
        next_action = "repair_raw_identity_audit_before_dataset_qualification"
    elif distinct_or_mixed_count:
        next_action = "add_peer_address_to_canonical_observation_schema"
    elif safe_to_deduplicate:
        next_action = "design_non_destructive_archive_overlap_exclusion_sidecar"
    else:
        next_action = "manual_boundary_identity_review"

    summary = {
        "phase": "R-MEM-1D-QA2",
        "materialization_root": str(root),
        "source_file_audit_count": len(audit_by_path),
        "unique_candidate_count": len(classified_rows),
        "raw_archive_count": len(specs),
        "raw_archive_failure_count": len(raw_failures),
        "classification_counts": dict(sorted(classification_counts.items())),
        "identity_basis_counts": dict(sorted(identity_basis_counts.items())),
        "peer_address_missing_match_count": sum(
            value
            for key, value in identity_basis_counts.items()
            if key != "peer_address"
        ),
        "identity_audit_passed": identity_audit_passed,
        "safe_to_deduplicate_current_fingerprint": safe_to_deduplicate,
        "recommended_next_action": next_action,
        "failures": failures,
        "workers": workers,
        "claims": {
            "rows_deleted_or_rewritten": False,
            "attack_or_benign_truth_produced": False,
            "foreground_or_learning_modified": False,
            "matching_identity_is_automatic_protocol_message_truth": False,
        },
    }
    write_csv(output_dir / "r_mem1d_qa2_candidate_identity_audit.csv", classified_rows)
    write_csv(output_dir / "r_mem1d_qa2_raw_match_audit.csv", raw_match_rows)
    write_csv(output_dir / "r_mem1d_qa2_raw_file_audit.csv", raw_file_rows)
    write_json(output_dir / "r_mem1d_qa2_summary.json", summary)
    (output_dir / "r_mem1d_qa2_report.md").write_text(
        report(summary), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if identity_audit_passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
