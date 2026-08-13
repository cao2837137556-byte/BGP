#!/usr/bin/env python3
"""Compare scientific N-FRONTEND-3B outputs from AMD and Intel replays."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


CSV_ARTIFACTS = [
    "n_frontend3b_denominator_audit.csv",
    "n_frontend3b_transition_learning_load.csv",
    "n_frontend3b_micro_event_learning_load.csv",
    "n_frontend3b_micro_event_member_distribution.csv",
    "n_frontend3b_foreground_family_composition.csv",
    "n_frontend3b_phase_survival_regression.csv",
    "n_frontend3b_restoration_audit.csv",
    "n_frontend3b_past_only_exposure_equality.csv",
    "n_frontend3b_causal_strict_replay_audit.csv",
    "n_frontend3b_semantic_delta_regression.csv",
    "n_frontend3b_gray_tripwire_audit.csv",
    "n_frontend3b_stop_loss_audit.csv",
]
SUMMARY_FIELDS = [
    "phase",
    "config_version",
    "frozen_contract_commit",
    "source_2b_registry_fingerprint",
    "source_2b_protocol_sha256",
    "pair_count",
    "variant_count",
    "count_scope",
    "transition_operational_background_input_count",
    "transition_operational_background_suppressed_count",
    "transition_learning_input_reduction_rate",
    "micro_event_operational_background_input_count",
    "micro_event_operational_background_suppressed_count",
    "micro_event_learning_input_reduction_rate",
    "suppressed_attack_count",
    "gray_count",
    "expected_visible_member_count",
    "observability_boundary_member_count",
    "upstream_exact_duplicate_copy_count_variant_expanded",
    "upstream_exact_dedup_counted_in_3b_reduction",
    "stop_loss_gates",
    "overall_pass",
    "allowed_claim",
    "forbidden_claims",
    "learning_trained",
    "attack_or_benign_truth_produced",
    "storage_compression_claimed",
    "semantic_output_fingerprint",
]


def normalize(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if math.isnan(float(value)) else float(value)
    if isinstance(value, dict):
        return {str(key): normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, np.ndarray)):
        return [normalize(item) for item in list(value)]
    if pd.isna(value):
        return None
    return value


def canonical(value: Any) -> str:
    return json.dumps(normalize(value), ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("ascii")).hexdigest()


def csv_records(path: Path) -> list[dict[str, Any]]:
    frame = pd.read_csv(path)
    records = [normalize(row) for row in frame.to_dict("records")]
    return sorted(records, key=canonical)


def compare(amd_result: Path, intel_result: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for name in CSV_ARTIFACTS:
        amd_path = amd_result / name
        intel_path = intel_result / name
        missing = [str(path) for path in (amd_path, intel_path) if not path.is_file()]
        if missing:
            rows.append({"artifact": name, "passed": False, "missing": missing})
            continue
        amd_value = csv_records(amd_path)
        intel_value = csv_records(intel_path)
        rows.append(
            {
                "artifact": name,
                "comparison": "canonical_csv_records",
                "amd_sha256": digest(amd_value),
                "intel_sha256": digest(intel_value),
                "passed": canonical(amd_value) == canonical(intel_value),
            }
        )

    amd_summary = json.loads((amd_result / "n_frontend3b_summary.json").read_text(encoding="utf-8"))
    intel_summary = json.loads((intel_result / "n_frontend3b_summary.json").read_text(encoding="utf-8"))
    amd_selected = {field: amd_summary.get(field) for field in SUMMARY_FIELDS}
    intel_selected = {field: intel_summary.get(field) for field in SUMMARY_FIELDS}
    rows.append(
        {
            "artifact": "n_frontend3b_summary.json",
            "comparison": "pre_registered_scientific_fields_only",
            "excluded_fields": ["source_2b_root"],
            "amd_sha256": digest(amd_selected),
            "intel_sha256": digest(intel_selected),
            "passed": canonical(amd_selected) == canonical(intel_selected),
        }
    )
    for name in (
        "n_frontend3b_semantic_output_manifest.json",
        "n_frontend3b_observer_prefix_exhaustion_summary.json",
    ):
        amd_value = json.loads((amd_result / name).read_text(encoding="utf-8"))
        intel_value = json.loads((intel_result / name).read_text(encoding="utf-8"))
        rows.append(
            {
                "artifact": name,
                "comparison": "canonical_json",
                "amd_sha256": digest(amd_value),
                "intel_sha256": digest(intel_value),
                "passed": canonical(amd_value) == canonical(intel_value),
            }
        )
    return {
        "phase": "N-FRONTEND-3B",
        "amd_result": str(amd_result),
        "intel_result": str(intel_result),
        "comparison_scope": "scientific semantic outputs; machine paths and wall-clock timing excluded",
        "artifact_comparisons": rows,
        "parity_passed": bool(rows) and all(row["passed"] for row in rows),
    }


def write_fixture(root: Path, marker: int) -> None:
    root.mkdir(parents=True)
    for name in CSV_ARTIFACTS:
        pd.DataFrame([{"pair_id": "pair", "count": marker, "passed": True}]).to_csv(
            root / name, index=False
        )
    summary = {field: None for field in SUMMARY_FIELDS}
    summary.update(
        {
            "phase": "N-FRONTEND-3B",
            "pair_count": marker,
            "stop_loss_gates": {"gate": True},
            "overall_pass": True,
            "source_2b_root": f"machine-specific-{marker}",
        }
    )
    (root / "n_frontend3b_summary.json").write_text(
        json.dumps(summary), encoding="utf-8"
    )
    for name in (
        "n_frontend3b_semantic_output_manifest.json",
        "n_frontend3b_observer_prefix_exhaustion_summary.json",
    ):
        (root / name).write_text(json.dumps({"marker": marker}), encoding="utf-8")


def run_self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="n_frontend3b_parity_") as temp:
        root = Path(temp)
        write_fixture(root / "amd", 1)
        write_fixture(root / "intel", 1)
        assert compare(root / "amd", root / "intel")["parity_passed"]
        frame = pd.read_csv(root / "intel" / CSV_ARTIFACTS[0])
        frame.loc[0, "count"] = 2
        frame.to_csv(root / "intel" / CSV_ARTIFACTS[0], index=False)
        assert not compare(root / "amd", root / "intel")["parity_passed"]
    print("self_test=passed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--amd-result")
    parser.add_argument("--intel-result")
    parser.add_argument("--output")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        run_self_test()
        return
    if not args.amd_result or not args.intel_result or not args.output:
        parser.error("--amd-result, --intel-result, and --output are required")
    result = compare(Path(args.amd_result).resolve(), Path(args.intel_result).resolve())
    target = Path(args.output).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    if not result["parity_passed"]:
        raise SystemExit("N-FRONTEND-3B dual-partition parity failed")


if __name__ == "__main__":
    main()
