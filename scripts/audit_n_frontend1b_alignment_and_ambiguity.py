#!/usr/bin/env python3
"""Audit paired N-FRONTEND-1B outputs and same-timestamp ambiguity."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


SUMMARY_NAME = "n_frontend1_summary.json"
VALIDATION_NAME = "n_frontend1b_validation.json"
UNIQUE_NAME = "n_frontend1_unique_observations.parquet"
TRANSITION_NAME = "n_frontend1_transitions.parquet"
MICRO_EVENT_NAME = "n_frontend1_micro_events.parquet"

STATE_COLUMNS = ["collector", "peer_address", "prefix", "path_id", "ts"]
SEMANTIC_COLUMNS = [
    "type",
    "origin_as",
    "as_path",
    "communities",
    "next_hop",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--amd-output-dir")
    parser.add_argument("--intel-output-dir")
    parser.add_argument("--output-dir")
    parser.add_argument("--top-n", type=int, default=50)
    parser.add_argument("--example-limit", type=int, default=200)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def stable_hash(value: Any) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_scalar(value: Any) -> Any:
    if value is None:
        return None
    try:
        missing = pd.isna(value)
        if isinstance(missing, bool) and missing:
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "as_py"):
        value = value.as_py()
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, (list, tuple)):
        return [normalize_scalar(item) for item in value]
    if hasattr(value, "tolist") and not isinstance(value, (str, bytes)):
        converted = value.tolist()
        return normalize_scalar(converted)
    return value


def normalized_text(value: Any) -> str:
    value = normalize_scalar(value)
    return "" if value is None else str(value)


def normalized_list(value: Any) -> tuple[str, ...]:
    value = normalize_scalar(value)
    if value is None:
        return ()
    if isinstance(value, list):
        return tuple(str(item) for item in value)
    return (str(value),)


def route_signature(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        normalized_text(row.get("origin_as")),
        normalized_list(row.get("as_path")),
        normalized_list(row.get("communities")),
        normalized_text(row.get("next_hop")),
    )


def prepare_output_dir(path: Path, overwrite: bool) -> None:
    if path.exists():
        if not overwrite:
            raise FileExistsError(f"output directory exists: {path}")
        shutil.rmtree(path)
    path.mkdir(parents=True)


def require_files(output_dir: Path) -> dict[str, Path]:
    paths = {
        "summary": output_dir / "result" / SUMMARY_NAME,
        "validation": output_dir / VALIDATION_NAME,
        "unique": output_dir / "result" / UNIQUE_NAME,
        "transitions": output_dir / "result" / TRANSITION_NAME,
        "micro_events": output_dir / "result" / MICRO_EVENT_NAME,
        "input_manifest": output_dir / "n_frontend1b_input_manifest.txt",
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing required replay artifacts: " + ", ".join(missing))
    return paths


def semantic_alignment(
    amd_paths: dict[str, Path],
    intel_paths: dict[str, Path],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    amd_summary = load_json(amd_paths["summary"])
    intel_summary = load_json(intel_paths["summary"])
    amd_validation = load_json(amd_paths["validation"])
    intel_validation = load_json(intel_paths["validation"])

    comparable_fields = [
        "input_file_count",
        "input_files",
        "source_rows_scanned",
        "source_rows_scanned_by_file",
        "selected_rows_by_collector",
        "required_collectors",
        "missing_required_collectors",
        "observed_collectors",
        "observed_projects",
        "selected_ts_min",
        "selected_ts_max",
        "input_rows",
        "exact_unique_observation_count",
        "exact_duplicate_copy_count",
        "transition_count",
        "transition_family_counts",
        "same_timestamp_ambiguous_batch_count",
        "causality_violation_count",
        "micro_event_count_by_window_sec",
        "primary_micro_event_count",
        "accounting",
        "contract_passed",
        "output_fingerprints",
    ]
    field_checks = {
        field: amd_summary.get(field) == intel_summary.get(field)
        for field in comparable_fields
    }
    manifest_match = (
        amd_paths["input_manifest"].read_text(encoding="utf-8")
        == intel_paths["input_manifest"].read_text(encoding="utf-8")
    )
    validation_checks = {
        "amd_validation_passed": bool(amd_validation.get("validation_passed")),
        "intel_validation_passed": bool(intel_validation.get("validation_passed")),
        "amd_failed_checks_empty": not amd_validation.get("failed_checks"),
        "intel_failed_checks_empty": not intel_validation.get("failed_checks"),
        "input_manifest_exact_match": manifest_match,
        "all_summary_fields_match": all(field_checks.values()),
        "all_output_fingerprints_match": (
            amd_summary.get("output_fingerprints")
            == intel_summary.get("output_fingerprints")
        ),
    }
    return amd_summary, intel_summary, {
        "field_checks": field_checks,
        "validation_checks": validation_checks,
        "semantic_alignment_passed": all(validation_checks.values()),
    }


def classify_ambiguous_group(group: pd.DataFrame) -> tuple[str, dict[str, bool]]:
    records = group.to_dict("records")
    types = {normalized_text(row.get("type")).upper() for row in records}
    routes = {route_signature(row) for row in records}
    origin_values = {route[0] for route in routes}
    path_values = {route[1] for route in routes}
    community_values = {route[2] for route in routes}
    next_hop_values = {route[3] for route in routes}
    details = {
        "contains_announce": "A" in types,
        "contains_withdraw": "W" in types,
        "origin_differs": len(origin_values) > 1,
        "path_differs": len(path_values) > 1,
        "communities_differ": len(community_values) > 1,
        "next_hop_differs": len(next_hop_values) > 1,
        "path_id_missing": all(not normalized_text(value) for value in group["path_id"]),
    }
    if "A" in types and "W" in types:
        reason = "announce_withdraw_same_timestamp"
    elif types == {"A"}:
        changed = [
            name
            for name, flag in [
                ("origin", details["origin_differs"]),
                ("path", details["path_differs"]),
                ("communities", details["communities_differ"]),
                ("next_hop", details["next_hop_differs"]),
            ]
            if flag
        ]
        reason = (
            "multiple_announcements_" + "_".join(changed)
            if changed
            else "multiple_announcements_unresolved_difference"
        )
    elif types == {"W"}:
        reason = "multiple_withdrawals_unresolved_difference"
    else:
        reason = "mixed_or_unsupported_update_types"
    return reason, details


def ambiguity_profile(
    paths: dict[str, Path],
    summary: dict[str, Any],
    top_n: int,
    example_limit: int,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    unique_table = pq.read_table(
        paths["unique"],
        columns=STATE_COLUMNS + SEMANTIC_COLUMNS + ["observation_id", "source_copy_count"],
    )
    unique = unique_table.to_pandas()
    unique["member_observation_count"] = (
        unique.groupby(STATE_COLUMNS, dropna=False, sort=False)["collector"]
        .transform("size")
        .astype("int64")
    )
    ambiguous = unique[unique["member_observation_count"] > 1].copy()

    group_rows: list[dict[str, Any]] = []
    for key, group in ambiguous.groupby(STATE_COLUMNS, dropna=False, sort=False):
        reason, details = classify_ambiguous_group(group)
        collector, peer_address, prefix, path_id, timestamp = key
        group_rows.append(
            {
                "ambiguity_group_id": stable_hash(
                    {
                        "collector": normalize_scalar(collector),
                        "peer_address": normalize_scalar(peer_address),
                        "prefix": normalize_scalar(prefix),
                        "path_id": normalize_scalar(path_id),
                        "ts": normalize_scalar(timestamp),
                    }
                ),
                "collector": normalize_scalar(collector),
                "peer_address": normalize_scalar(peer_address),
                "prefix": normalize_scalar(prefix),
                "path_id": normalize_scalar(path_id),
                "ts": normalize_scalar(timestamp),
                "member_observation_count": int(group["member_observation_count"].iloc[0]),
                "semantic_variant_count": len(
                    {
                        (
                            normalized_text(row.get("type")).upper(),
                            route_signature(row),
                        )
                        for row in group.to_dict("records")
                    }
                ),
                "ambiguity_reason": reason,
                **details,
            }
        )
    groups = pd.DataFrame(group_rows)
    if groups.empty:
        groups = pd.DataFrame(
            columns=[
                "ambiguity_group_id",
                *STATE_COLUMNS,
                "member_observation_count",
                "semantic_variant_count",
                "ambiguity_reason",
            ]
        )

    reason_counts = Counter(groups.get("ambiguity_reason", pd.Series(dtype=str)))
    collector_counts = Counter(groups.get("collector", pd.Series(dtype=str)))
    profile_rows = [
        {
            "dimension": "ambiguity_reason",
            "value": value,
            "group_count": count,
            "share_of_ambiguous_groups": count / len(groups) if len(groups) else 0.0,
        }
        for value, count in reason_counts.most_common()
    ]
    profile_rows.extend(
        {
            "dimension": "collector",
            "value": value,
            "group_count": count,
            "share_of_ambiguous_groups": count / len(groups) if len(groups) else 0.0,
        }
        for value, count in collector_counts.most_common()
    )
    profile = pd.DataFrame(profile_rows)

    transitions = pq.read_table(
        paths["transitions"],
        columns=["same_timestamp_ambiguous"],
    ).to_pandas()
    micro_events = pq.read_table(
        paths["micro_events"],
        columns=["same_timestamp_ambiguous"],
    ).to_pandas()
    transition_ambiguous = int(transitions["same_timestamp_ambiguous"].fillna(False).sum())
    micro_ambiguous = int(micro_events["same_timestamp_ambiguous"].fillna(False).sum())
    expected = int(summary["same_timestamp_ambiguous_batch_count"])
    audit = {
        "ambiguous_group_count": len(groups),
        "ambiguous_member_observation_count": int(
            groups.get("member_observation_count", pd.Series(dtype=int)).sum()
        ),
        "summary_ambiguous_batch_count": expected,
        "transition_ambiguous_count": transition_ambiguous,
        "micro_event_with_ambiguity_count": micro_ambiguous,
        "ambiguous_transition_rate": (
            transition_ambiguous / int(summary["transition_count"])
            if int(summary["transition_count"])
            else 0.0
        ),
        "ambiguous_micro_event_rate": (
            micro_ambiguous / int(summary["primary_micro_event_count"])
            if int(summary["primary_micro_event_count"])
            else 0.0
        ),
        "path_id_field_present": bool(summary.get("path_id_field_present")),
        "path_id_non_null_rows": int(summary.get("path_id_non_null_rows", 0)),
        "add_path_support_ready": bool(summary.get("add_path_support_ready")),
        "reason_counts": dict(sorted(reason_counts.items())),
        "collector_counts": dict(sorted(collector_counts.items())),
        "ambiguity_accounting_passed": (
            len(groups) == expected == transition_ambiguous
        ),
        "allowed_claim": (
            "same-timestamp distinct route observations are preserved as "
            "unknown-order ambiguity"
        ),
        "forbidden_claims": [
            "same-timestamp ambiguity is an attack",
            "same-timestamp ambiguity is safe background",
            "the observed order is recoverable without finer timestamps or path identifiers",
        ],
        "recommended_action": (
            "retain ambiguity as foreground-eligible unknown-order context; "
            "audit Add-Path and source timestamp granularity before suppression tuning"
        ),
    }
    examples = groups.sort_values(
        ["member_observation_count", "collector", "ts"],
        ascending=[False, True, True],
    ).head(example_limit)
    if top_n > 0:
        profile = (
            profile.sort_values(
                ["dimension", "group_count", "value"],
                ascending=[True, False, True],
            )
            .groupby("dimension", as_index=False, group_keys=False)
            .head(top_n)
        )
    return profile, examples, audit


def write_report(path: Path, summary: dict[str, Any]) -> None:
    ambiguity = summary["ambiguity_audit"]
    lines = [
        "# N-FRONTEND-1C Alignment and Ambiguity Audit",
        "",
        f"- Alignment passed: `{str(summary['semantic_alignment_passed']).lower()}`.",
        f"- Ambiguity accounting passed: `{str(ambiguity['ambiguity_accounting_passed']).lower()}`.",
        f"- Input rows: `{summary['input_rows']}`.",
        f"- Exact unique observations: `{summary['exact_unique_observation_count']}`.",
        f"- Transitions: `{summary['transition_count']}`.",
        f"- Primary micro-events: `{summary['primary_micro_event_count']}`.",
        f"- Raw-to-micro-event compression: `{summary['raw_to_primary_micro_event_compression_ratio']}`.",
        f"- Same-timestamp ambiguous groups: `{ambiguity['ambiguous_group_count']}`.",
        f"- Ambiguous transition rate: `{ambiguity['ambiguous_transition_rate']}`.",
        f"- Micro-events containing ambiguity: `{ambiguity['micro_event_with_ambiguity_count']}`.",
        f"- Add-Path support ready: `{str(ambiguity['add_path_support_ready']).lower()}`.",
        "",
        "## Interpretation",
        "",
        "- AMD and Intel must match on semantic output fingerprints, counts, scope, and validation.",
        "- Same-timestamp distinct observations remain unknown-order context; they are not silently sorted.",
        "- Ambiguity is neither attack truth nor safe-background evidence.",
        "- No foreground suppression rule is changed in this audit.",
        "",
        "## Recommended Action",
        "",
        f"- {ambiguity['recommended_action']}.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_audit(
    amd_output_dir: Path,
    intel_output_dir: Path,
    output_dir: Path,
    top_n: int,
    example_limit: int,
    overwrite: bool,
) -> dict[str, Any]:
    prepare_output_dir(output_dir, overwrite)
    amd_paths = require_files(amd_output_dir)
    intel_paths = require_files(intel_output_dir)
    amd_summary, intel_summary, alignment = semantic_alignment(
        amd_paths,
        intel_paths,
    )
    profile, examples, ambiguity = ambiguity_profile(
        amd_paths,
        amd_summary,
        top_n,
        example_limit,
    )
    summary = {
        "phase": "N-FRONTEND-1C",
        "amd_output_dir": str(amd_output_dir),
        "intel_output_dir": str(intel_output_dir),
        "semantic_alignment_passed": alignment["semantic_alignment_passed"],
        "alignment": alignment,
        "input_rows": int(amd_summary["input_rows"]),
        "exact_unique_observation_count": int(
            amd_summary["exact_unique_observation_count"]
        ),
        "transition_count": int(amd_summary["transition_count"]),
        "primary_micro_event_count": int(
            amd_summary["primary_micro_event_count"]
        ),
        "raw_to_primary_micro_event_compression_ratio": float(
            amd_summary["raw_to_primary_micro_event_compression_ratio"]
        ),
        "output_fingerprints": amd_summary["output_fingerprints"],
        "ambiguity_audit": ambiguity,
        "audit_passed": (
            alignment["semantic_alignment_passed"]
            and ambiguity["ambiguity_accounting_passed"]
        ),
        "claim_boundaries": {
            "proven": [
                "paired replay outputs are semantically aligned",
                "same-timestamp ambiguity is explicitly preserved and accounted",
            ],
            "not_proven": [
                "safe background suppression",
                "attack retention",
                "poisoning or evasion robustness",
                "full nine-day scalability",
            ],
        },
    }
    profile.to_csv(
        output_dir / "n_frontend1c_ambiguity_profile.csv",
        index=False,
    )
    examples.to_csv(
        output_dir / "n_frontend1c_ambiguity_examples.csv",
        index=False,
    )
    (output_dir / "n_frontend1c_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_report(output_dir / "n_frontend1c_report.md", summary)
    return summary


def write_fixture(root: Path) -> None:
    result = root / "result"
    result.mkdir(parents=True)
    unique = pd.DataFrame(
        [
            {
                "collector": "rrc00",
                "peer_address": "192.0.2.1",
                "prefix": "203.0.113.0/24",
                "path_id": None,
                "ts": 1.0,
                "type": "A",
                "origin_as": 64501,
                "as_path": [64500, 64501],
                "communities": ["64500:1"],
                "next_hop": "192.0.2.254",
                "observation_id": "a",
                "source_copy_count": 1,
            },
            {
                "collector": "rrc00",
                "peer_address": "192.0.2.1",
                "prefix": "203.0.113.0/24",
                "path_id": None,
                "ts": 1.0,
                "type": "A",
                "origin_as": 64502,
                "as_path": [64500, 64502],
                "communities": ["64500:1"],
                "next_hop": "192.0.2.254",
                "observation_id": "b",
                "source_copy_count": 1,
            },
        ]
    )
    transitions = pd.DataFrame([{"same_timestamp_ambiguous": True}])
    micro_events = pd.DataFrame([{"same_timestamp_ambiguous": True}])
    pq.write_table(pa.Table.from_pandas(unique), result / UNIQUE_NAME)
    pq.write_table(pa.Table.from_pandas(transitions), result / TRANSITION_NAME)
    pq.write_table(pa.Table.from_pandas(micro_events), result / MICRO_EVENT_NAME)
    summary = {
        "input_file_count": 1,
        "input_files": ["fixture.parquet"],
        "source_rows_scanned": 2,
        "source_rows_scanned_by_file": {"fixture.parquet": 2},
        "selected_rows_by_collector": {"rrc00": 2},
        "required_collectors": ["rrc00"],
        "missing_required_collectors": [],
        "observed_collectors": ["rrc00"],
        "observed_projects": ["ris"],
        "selected_ts_min": 1.0,
        "selected_ts_max": 1.0,
        "input_rows": 2,
        "exact_unique_observation_count": 2,
        "exact_duplicate_copy_count": 0,
        "transition_count": 1,
        "transition_family_counts": {"same_timestamp_ambiguous": 1},
        "same_timestamp_ambiguous_batch_count": 1,
        "causality_violation_count": 0,
        "path_id_field_present": False,
        "path_id_non_null_rows": 0,
        "add_path_support_ready": False,
        "micro_event_count_by_window_sec": {"300": 1},
        "primary_micro_event_count": 1,
        "raw_to_primary_micro_event_compression_ratio": 2.0,
        "accounting": {"all": True},
        "contract_passed": True,
        "output_fingerprints": {
            "unique_observations": "u",
            "transitions": "t",
            "primary_micro_events": "m",
        },
    }
    (result / SUMMARY_NAME).write_text(
        json.dumps(summary),
        encoding="utf-8",
    )
    (root / VALIDATION_NAME).write_text(
        json.dumps({"validation_passed": True, "failed_checks": []}),
        encoding="utf-8",
    )
    (root / "n_frontend1b_input_manifest.txt").write_text(
        "fixture.parquet\n",
        encoding="utf-8",
    )


def self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        amd = root / "amd"
        intel = root / "intel"
        write_fixture(amd)
        shutil.copytree(amd, intel)
        output = root / "audit"
        summary = run_audit(amd, intel, output, 10, 10, False)
        assert summary["audit_passed"]
        assert summary["ambiguity_audit"]["ambiguous_group_count"] == 1
        assert summary["ambiguity_audit"]["reason_counts"] == {
            "multiple_announcements_origin_path": 1
        }
        assert (output / "n_frontend1c_summary.json").is_file()

        intel_summary_path = intel / "result" / SUMMARY_NAME
        intel_summary = load_json(intel_summary_path)
        intel_summary["output_fingerprints"]["transitions"] = "changed"
        intel_summary_path.write_text(
            json.dumps(intel_summary),
            encoding="utf-8",
        )
        rejected = run_audit(
            amd,
            intel,
            root / "audit_mismatch",
            10,
            10,
            False,
        )
        assert not rejected["audit_passed"]
        assert not rejected["semantic_alignment_passed"]
    print("self_test=passed")


def main() -> None:
    args = parse_args()
    if args.self_test:
        self_test()
        return
    required = {
        "--amd-output-dir": args.amd_output_dir,
        "--intel-output-dir": args.intel_output_dir,
        "--output-dir": args.output_dir,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise SystemExit("missing required arguments: " + ", ".join(missing))
    summary = run_audit(
        Path(args.amd_output_dir),
        Path(args.intel_output_dir),
        Path(args.output_dir),
        args.top_n,
        args.example_limit,
        args.overwrite,
    )
    print(f"audit_passed={str(summary['audit_passed']).lower()}")
    print(
        "semantic_alignment_passed="
        f"{str(summary['semantic_alignment_passed']).lower()}"
    )
    print(
        "ambiguous_group_count="
        f"{summary['ambiguity_audit']['ambiguous_group_count']}"
    )
    print(f"output_dir={args.output_dir}")


if __name__ == "__main__":
    main()
