#!/usr/bin/env python3
"""Validate the peer-aware canonical observation contract against QA2 results."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from r_mem_canonical_observation_v2 import (
    SCHEMA_VERSION,
    observation_id_from_base_fingerprint,
    run_self_test as run_schema_self_test,
    schema_payload_v2,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = "configs/r_mem1e_peer_aware_schema_smoke_v01.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--qa2-dir")
    parser.add_argument("--output-dir")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


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


def prepare_output(path: Path, overwrite: bool) -> None:
    if path.exists() and any(path.iterdir()):
        if not overwrite:
            raise FileExistsError(f"output directory is not empty: {path}")
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def pair_duplicate_count(
    source: Counter[str], neighbor: Counter[str]
) -> int:
    return sum(min(source[item], neighbor[item]) for item in set(source) & set(neighbor))


def audit(
    candidates: list[dict[str, str]],
    matches: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    failures: list[str] = []
    counts: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    identity_mismatch_count = 0
    peer_missing_count = 0
    preview: list[dict[str, Any]] = []
    for row in matches:
        expected = observation_id_from_base_fingerprint(
            row["base_fingerprint"], row.get("peer_address")
        )
        if expected is None:
            peer_missing_count += 1
            continue
        if expected != row.get("observation_identity"):
            identity_mismatch_count += 1
        counts[(row["file_path"], row["base_fingerprint"])][expected] += 1
        if len(preview) < 200:
            preview.append(
                {
                    "file_path": row["file_path"],
                    "base_fingerprint": row["base_fingerprint"],
                    "peer_address": row.get("peer_address", ""),
                    "observation_id": expected,
                    "type": row.get("type", ""),
                    "prefix": row.get("prefix", ""),
                    "peer_asn": row.get("peer_asn", ""),
                }
            )

    reconciled: list[dict[str, Any]] = []
    duplicate_copy_count = 0
    source_row_count = 0
    neighbor_row_count = 0
    for row in candidates:
        source = counts[(row["source_file"], row["base_fingerprint"])]
        neighbor = counts[(row["neighbor_file"], row["base_fingerprint"])]
        duplicates = pair_duplicate_count(source, neighbor)
        source_rows = sum(source.values())
        neighbor_rows = sum(neighbor.values())
        duplicate_copy_count += duplicates
        source_row_count += source_rows
        neighbor_row_count += neighbor_rows
        retained = source_rows + neighbor_rows - duplicates
        reconciled.append(
            {
                "candidate_id": row["candidate_id"],
                "classification": row["classification"],
                "source_file": row["source_file"],
                "neighbor_file": row["neighbor_file"],
                "base_fingerprint": row["base_fingerprint"],
                "source_peer_aware_rows": source_rows,
                "neighbor_peer_aware_rows": neighbor_rows,
                "same_peer_duplicate_copy_count": duplicates,
                "retained_peer_aware_observation_count": retained,
                "distinct_neighbor_observations_preserved": neighbor_rows - duplicates,
                "v2_identity_complete": source_rows == int(row["source_raw_count"])
                and neighbor_rows == int(row["neighbor_raw_count"]),
            }
        )

    if peer_missing_count:
        failures.append(f"peer_address missing for {peer_missing_count} QA2 matches")
    if identity_mismatch_count:
        failures.append(
            f"v2 observation identity mismatches QA2 for {identity_mismatch_count} rows"
        )
    incomplete = sum(not row["v2_identity_complete"] for row in reconciled)
    if incomplete:
        failures.append(f"peer-aware multiplicity incomplete for {incomplete} candidates")

    metrics = {
        "unique_candidate_count": len(candidates),
        "raw_match_row_count": len(matches),
        "source_peer_aware_row_count": source_row_count,
        "neighbor_peer_aware_row_count": neighbor_row_count,
        "same_peer_duplicate_copy_count": duplicate_copy_count,
        "distinct_neighbor_observations_preserved": neighbor_row_count
        - duplicate_copy_count,
        "canonical_observations_after_pair_dedup": source_row_count
        + neighbor_row_count
        - duplicate_copy_count,
        "peer_address_missing_count": peer_missing_count,
        "observation_identity_mismatch_count": identity_mismatch_count,
        "candidate_identity_incomplete_count": incomplete,
    }
    return reconciled, {"metrics": metrics, "preview": preview}, failures


def report(summary: dict[str, Any]) -> str:
    metrics = summary["metrics"]
    return f"""# R-MEM-1E Peer-aware Canonical Schema Smoke

## Result

- Smoke passed: `{str(summary['smoke_passed']).lower()}`.
- QA2 candidates reconciled: `{metrics['unique_candidate_count']}`.
- Same-peer duplicate copies identifiable: `{metrics['same_peer_duplicate_copy_count']}`.
- Distinct-peer neighbor observations preserved: `{metrics['distinct_neighbor_observations_preserved']}`.
- Canonical observations after pair-level deduplication: `{metrics['canonical_observations_after_pair_dedup']}`.
- Missing peer addresses: `{metrics['peer_address_missing_count']}`.

## Data Boundary

This smoke validates the peer-aware observation identity contract. It does not
rewrite the immutable R-MEM-1D-R1 Parquets and does not call the 10-day window
attack-free. The window remains unlabeled operational public-BGP background.
Possible incidents must be audited and quarantined before any row is used as a
negative training label.
"""


def run_contract_self_test() -> int:
    run_schema_self_test()
    source = Counter({"same": 1, "left": 1})
    neighbor = Counter({"same": 1, "right": 1})
    assert pair_duplicate_count(source, neighbor) == 1
    print("audit_self_test=passed")
    return 0


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_contract_self_test()
    if not args.qa2_dir or not args.output_dir:
        raise SystemExit("--qa2-dir and --output-dir are required")

    config = json.loads(resolve_repo_path(args.config).read_text(encoding="utf-8"))
    qa2_dir = Path(args.qa2_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    required = {
        "summary": qa2_dir / "r_mem1d_qa2_summary.json",
        "candidates": qa2_dir / "r_mem1d_qa2_candidate_identity_audit.csv",
        "matches": qa2_dir / "r_mem1d_qa2_raw_match_audit.csv",
    }
    missing = [str(path) for path in required.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing QA2 artifacts: {missing}")
    prepare_output(output_dir, args.overwrite)

    qa2_summary = json.loads(required["summary"].read_text(encoding="utf-8"))
    candidates = read_csv(required["candidates"])
    matches = read_csv(required["matches"])
    reconciled, audit_result, failures = audit(candidates, matches)
    metrics = audit_result["metrics"]

    expectations = config["expected_qa2_metrics"]
    for field, expected in expectations.items():
        actual = metrics.get(field)
        if actual != expected:
            failures.append(f"{field}: expected={expected} actual={actual}")
    if qa2_summary.get("identity_audit_passed") is not True:
        failures.append("QA2 identity audit did not pass")
    if qa2_summary.get("recommended_next_action") != (
        "add_peer_address_to_canonical_observation_schema"
    ):
        failures.append("QA2 does not recommend the peer-aware schema repair")

    summary = {
        "phase": "R-MEM-1E",
        "schema_version": SCHEMA_VERSION,
        "qa2_dir": str(qa2_dir),
        "metrics": metrics,
        "smoke_passed": not failures,
        "failures": failures,
        "dataset_role": "unlabeled_operational_background",
        "background_contamination_contract": config[
            "background_contamination_contract"
        ],
        "recommended_next_action": (
            "materialize_peer_aware_v2_then_run_background_contamination_audit"
            if not failures
            else "repair_peer_aware_schema_contract_before_full_materialization"
        ),
        "claims": {
            "old_parquets_rewritten": False,
            "attack_free_window_claimed": False,
            "attack_or_benign_truth_produced": False,
            "foreground_or_learning_modified": False,
        },
    }
    write_json(output_dir / "r_mem1e_summary.json", summary)
    write_json(output_dir / "r_mem1e_schema_v2.json", schema_payload_v2())
    write_csv(output_dir / "r_mem1e_candidate_reconciliation.csv", reconciled)
    write_csv(
        output_dir / "r_mem1e_peer_aware_match_preview.csv",
        audit_result["preview"],
    )
    (output_dir / "r_mem1e_report.md").write_text(report(summary), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["smoke_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
