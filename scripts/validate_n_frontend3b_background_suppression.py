#!/usr/bin/env python3
"""Independently validate N-FRONTEND-3B bounded suppression artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ASSIGN_FOREGROUND = "protected_semantic_foreground"
ASSIGN_BACKGROUND = "suppressible_semantic_redundancy"
ASSIGN_GRAY = "gray_contract_anomaly"
FINAL_FOREGROUND = "semantic_foreground"
FINAL_BACKGROUND = "reversible_background_summary"
FINAL_GRAY = "gray_contract_anomaly"
ROOT_REQUIRED = [
    "n_frontend3b_summary.json",
    "n_frontend3b_report.md",
    "n_frontend3b_package_manifest.json",
    "n_frontend3b_source_anchor_audit.csv",
    "n_frontend3b_frozen_input_manifest.json",
    "n_frontend3b_denominator_audit.csv",
    "n_frontend3b_transition_learning_load.csv",
    "n_frontend3b_micro_event_learning_load.csv",
    "n_frontend3b_micro_event_member_distribution.csv",
    "n_frontend3b_foreground_family_composition.csv",
    "n_frontend3b_upstream_exact_dedup_audit.csv",
    "n_frontend3b_observer_prefix_exhaustion.csv",
    "n_frontend3b_observer_prefix_exhaustion_summary.json",
    "n_frontend3b_phase_survival_regression.csv",
    "n_frontend3b_restoration_audit.csv",
    "n_frontend3b_past_only_exposure_equality.csv",
    "n_frontend3b_stage_accounting_audit.csv",
    "n_frontend3b_causal_strict_replay_audit.csv",
    "n_frontend3b_semantic_delta_regression.csv",
    "n_frontend3b_gray_tripwire_audit.csv",
    "n_frontend3b_non_route_bypass_audit.csv",
    "n_frontend3b_stop_loss_audit.csv",
    "n_frontend3b_semantic_output_manifest.json",
]
VARIANT_REQUIRED = [
    "n_frontend3b_variant_manifest.json",
    "n_frontend3b_transition_assignments.parquet",
    "n_frontend3b_micro_event_routing.parquet",
    "semantic_foreground_transitions.parquet",
    "semantic_foreground_micro_events.parquet",
    "immutable_background_transitions.parquet",
    "reversible_background_micro_events.parquet",
    "gray_contract_anomaly_transitions.parquet",
    "n_frontend3b_reversible_background_index.parquet",
    "n_frontend3b_background_member_manifest.parquet",
    "n_frontend3b_past_only_exposure_pre.csv",
    "n_frontend3b_past_only_exposure_post.csv",
    "n_frontend3b_past_only_exposure_equality.csv",
]
TRUTH_COLUMNS = {
    "pair_id", "scenario_id", "variant_role", "phase_id",
    "is_attack_member", "is_poisoning_preparation_member",
    "expected_visible", "expected_visibility_class", "family", "threat_model",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir")
    parser.add_argument("--config", default="configs/n_frontend3b_background_suppression_v01.json")
    parser.add_argument("--validation-output")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if math.isnan(float(value)) else float(value)
    if isinstance(value, np.ndarray):
        return [normalize(item) for item in value.tolist()]
    if isinstance(value, (list, tuple, set)):
        return [normalize(item) for item in value]
    if pd.isna(value):
        return None
    return value


def json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_ready(item) for item in value]
    return normalize(value)


def text(value: Any) -> str | None:
    value = normalize(value)
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    value = normalize(value)
    return bool(value) if value is not None else False


def as_list(value: Any) -> list[str]:
    value = normalize(value)
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in (text(part) for part in value) if item]
    if isinstance(value, str) and value.strip().startswith("["):
        try:
            return as_list(json.loads(value))
        except json.JSONDecodeError:
            pass
    return [str(value)] if text(value) else []


def normalized_table_records(frame: pd.DataFrame, columns: list[str]) -> list[dict[str, Any]]:
    keys = [
        "pair_id", "variant_role", "collector", "peer_address",
        "attack_observation_id",
    ]

    def normalized_cell(value: Any) -> Any:
        value = normalize(value)
        if isinstance(value, str) and value.strip().startswith(("[", "{")):
            try:
                return json_ready(json.loads(value))
            except json.JSONDecodeError:
                pass
        return json_ready(value)

    records = [
        {column: normalized_cell(row.get(column)) for column in columns}
        for row in frame.to_dict("records")
    ]
    return sorted(
        records,
        key=lambda row: tuple(str(row.get(key)) for key in keys if key in columns),
    )


def frozen_exposure_equal(recomputed_path: Path, baseline_path: Path) -> bool:
    recomputed = pd.read_csv(recomputed_path)
    baseline = pd.read_csv(baseline_path)
    shared = [column for column in baseline.columns if column in recomputed.columns]
    required = {
        "pair_id", "variant_role", "collector", "peer_address",
        "attack_observation_id",
    }
    if not required.issubset(shared):
        return False
    return normalized_table_records(recomputed, shared) == normalized_table_records(
        baseline, shared
    )


def independent_assignment(row: dict[str, Any], config: dict[str, Any]) -> str:
    rule = config["suppression_eligibility"]
    required_identity = all(text(row.get(field)) for field in rule["required_identity_fields"])
    required_provenance = all(as_list(row.get(field)) for field in rule["required_reversible_fields"])
    required_counts = all(
        normalize(row.get(field)) is not None and int(normalize(row.get(field))) >= 1
        for field in rule["required_positive_count_fields"]
    )
    state_fields_present = all(normalize(row.get(field)) is not None for field in (
        "state_known_before", "state_known_after", "same_timestamp_ambiguous"
    ))
    if not required_identity or not required_provenance or not required_counts or not state_fields_present:
        return ASSIGN_GRAY
    exact = (
        text(row.get("transition_family")) == rule["transition_family"]
        and text(row.get("old_route_signature")) is not None
        and text(row.get("old_route_signature")) == text(row.get("new_route_signature"))
        and all(not as_bool(row.get(field)) for field in rule["required_false_flags"])
        and all(as_bool(row.get(field)) for field in rule["required_true_flags"])
    )
    return ASSIGN_BACKGROUND if exact else ASSIGN_FOREGROUND


def expected_micro_route(member_assignments: list[str]) -> str:
    if ASSIGN_FOREGROUND in member_assignments:
        return FINAL_FOREGROUND
    if ASSIGN_GRAY in member_assignments or not member_assignments:
        return FINAL_GRAY
    return FINAL_BACKGROUND if all(value == ASSIGN_BACKGROUND for value in member_assignments) else FINAL_GRAY


def validate(output_dir: Path, config_path: Path) -> dict[str, Any]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    missing_root = [name for name in ROOT_REQUIRED if not (output_dir / name).is_file()]
    if missing_root:
        errors.append(f"missing_root_artifacts:{','.join(missing_root)}")
        return {"validation_passed": False, "errors": errors}

    summary = json.loads((output_dir / "n_frontend3b_summary.json").read_text(encoding="utf-8"))
    variants = sorted((output_dir / "evaluation_only").glob("*/*"))
    if len(variants) != 10:
        errors.append(f"variant_count:{len(variants)}")
    route_counts = {FINAL_FOREGROUND: 0, FINAL_BACKGROUND: 0, FINAL_GRAY: 0}
    background_eligibility_failures = 0
    independent_assignment_mismatches = 0
    micro_precedence_mismatches = 0
    restoration_failures = 0
    truth_leak_columns: set[str] = set()
    exposure_mismatches = 0
    frozen_exposure_mismatches = 0
    same_timestamp_prior_hash_failures = 0

    for variant_dir in variants:
        missing = [name for name in VARIANT_REQUIRED if not (variant_dir / name).is_file()]
        if missing:
            errors.append(f"missing_variant_artifacts:{variant_dir}:{','.join(missing)}")
            continue
        manifest = json.loads((variant_dir / "n_frontend3b_variant_manifest.json").read_text(encoding="utf-8"))
        source_path = Path(manifest["source_transition_path"])
        if not source_path.is_file():
            errors.append(f"missing_source_transition:{source_path}")
            continue
        if sha256_file(source_path) != manifest.get("source_transition_sha256"):
            errors.append(f"source_transition_hash_mismatch:{source_path}")
            continue
        source_exposure_path = Path(manifest.get("source_exposure_path", ""))
        if not source_exposure_path.is_file():
            errors.append(f"missing_source_exposure:{source_exposure_path}")
            continue
        if sha256_file(source_exposure_path) != manifest.get("source_exposure_sha256"):
            errors.append(f"source_exposure_hash_mismatch:{source_exposure_path}")
            continue
        source = pd.read_parquet(source_path)
        assignments = pd.read_parquet(variant_dir / "n_frontend3b_transition_assignments.parquet")
        micro = pd.read_parquet(variant_dir / "n_frontend3b_micro_event_routing.parquet")
        truth_leak_columns.update(set(assignments.columns) & TRUTH_COLUMNS)
        source_index = {str(row["transition_id"]): row for row in source.to_dict("records")}
        assignment_index = {
            str(row["transition_id"]): row for row in assignments.to_dict("records")
        }
        if set(source_index) != set(assignment_index):
            restoration_failures += 1
        for transition_id, row in source_index.items():
            observed = assignment_index.get(transition_id, {})
            expected = independent_assignment(row, config)
            if observed.get("eligibility_assignment") != expected:
                independent_assignment_mismatches += 1
            route = observed.get("final_route")
            if route in route_counts:
                route_counts[route] += 1
            else:
                errors.append(f"unknown_final_route:{route}")
            if route == FINAL_BACKGROUND and expected != ASSIGN_BACKGROUND:
                background_eligibility_failures += 1

        assignment_value = {
            transition_id: row.get("eligibility_assignment")
            for transition_id, row in assignment_index.items()
        }
        for event in micro.to_dict("records"):
            members = as_list(event.get("member_transition_ids"))
            values = [assignment_value.get(member, ASSIGN_GRAY) for member in members]
            if event.get("final_route") != expected_micro_route(values):
                micro_precedence_mismatches += 1

        for _, batch in assignments.groupby("transition_ts", dropna=False, sort=False):
            if batch["decision_prior_ledger_fingerprint"].nunique(dropna=False) != 1:
                same_timestamp_prior_hash_failures += 1
        equality = pd.read_csv(variant_dir / "n_frontend3b_past_only_exposure_equality.csv")
        exposure_mismatches += int((~equality["exact_equal"].map(as_bool)).sum())
        if not frozen_exposure_equal(
            variant_dir / "n_frontend3b_past_only_exposure_pre.csv",
            source_exposure_path,
        ):
            frozen_exposure_mismatches += 1
        routed_frames = [
            pd.read_parquet(variant_dir / "semantic_foreground_transitions.parquet"),
            pd.read_parquet(variant_dir / "immutable_background_transitions.parquet"),
            pd.read_parquet(variant_dir / "gray_contract_anomaly_transitions.parquet"),
        ]
        restored_ids = sorted(
            str(value)
            for frame in routed_frames
            for value in frame["transition_id"].tolist()
        )
        if restored_ids != sorted(source_index):
            restoration_failures += 1

    stop_loss = pd.read_csv(output_dir / "n_frontend3b_stop_loss_audit.csv")
    safety = pd.read_csv(output_dir / "n_frontend3b_phase_survival_regression.csv")
    denominator = pd.read_csv(output_dir / "n_frontend3b_denominator_audit.csv")
    gray = pd.read_csv(output_dir / "n_frontend3b_gray_tripwire_audit.csv")
    stage = pd.read_csv(output_dir / "n_frontend3b_stage_accounting_audit.csv")
    non_route = pd.read_csv(output_dir / "n_frontend3b_non_route_bypass_audit.csv")
    micro_load = pd.read_csv(output_dir / "n_frontend3b_micro_event_learning_load.csv")
    micro_distribution = pd.read_csv(
        output_dir / "n_frontend3b_micro_event_member_distribution.csv"
    )
    upstream_dedup = pd.read_csv(
        output_dir / "n_frontend3b_upstream_exact_dedup_audit.csv"
    )
    boundary = safety[safety["observability_boundary"].map(as_bool)]
    boundary_pass = bool(
        len(boundary) == int(summary["observability_boundary_member_count"])
        and not boundary["expected_visible"].map(as_bool).any()
        and boundary["transition_id"].isna().all()
        and boundary["final_route"].isna().all()
        and not boundary["attack_suppressed"].map(as_bool).any()
    )
    checks = {
        "summary_overall_pass": bool(summary.get("overall_pass")),
        "summary_stop_loss_all_pass": all(bool(value) for value in summary.get("stop_loss_gates", {}).values()),
        "stop_loss_table_all_pass": bool(stop_loss["passed"].map(as_bool).all()),
        "variant_count_pass": len(variants) == 10,
        "truth_not_online_pass": not truth_leak_columns,
        "independent_eligibility_pass": independent_assignment_mismatches == 0,
        "background_eligibility_pass": background_eligibility_failures == 0,
        "micro_precedence_pass": micro_precedence_mismatches == 0,
        "restoration_pass": restoration_failures == 0,
        "stage_accounting_pass": bool(
            stage["passed"].map(as_bool).all()
            and (stage["unexplained_loss_count"] == 0).all()
        ),
        "non_route_bypass_pass": bool(
            (non_route["non_route_records_consumed_by_suppression"] == 0).all()
            and non_route["passed"].map(as_bool).all()
        ),
        "past_only_equality_pass": exposure_mismatches == 0,
        "frozen_2b_exposure_regression_pass": frozen_exposure_mismatches == 0,
        "same_timestamp_batch_pass": same_timestamp_prior_hash_failures == 0,
        "suppressed_attack_count_pass": not safety["attack_suppressed"].map(as_bool).any(),
        "visible_traceability_pass": safety.loc[safety["expected_visible"].map(as_bool), "traceable_after_routing"].map(as_bool).all(),
        "denominator_truth_after_routing_pass": denominator["truth_used_only_after_routing"].map(as_bool).all(),
        "gray_zero_pass": int(gray["gray_count"].sum()) == 0,
        "observability_boundary_not_miss_pass": boundary_pass,
        "micro_member_distribution_accounting_pass": int(
            micro_distribution["micro_event_count"].sum()
        ) == int(micro_load["background_input_count"].sum()),
        "upstream_dedup_separation_pass": bool(
            not upstream_dedup["counted_in_3b_learning_input_reduction"]
            .map(as_bool)
            .any()
        ),
        "background_route_exercised": route_counts[FINAL_BACKGROUND] > 0,
    }
    if not all(checks.values()):
        errors.extend(key for key, value in checks.items() if not value)
    return {
        "phase": "N-FRONTEND-3B",
        "validation_passed": not errors,
        "checks": checks,
        "variant_count": len(variants),
        "route_counts": route_counts,
        "independent_assignment_mismatch_count": independent_assignment_mismatches,
        "background_eligibility_failure_count": background_eligibility_failures,
        "micro_precedence_mismatch_count": micro_precedence_mismatches,
        "restoration_failure_count": restoration_failures,
        "exposure_mismatch_count": exposure_mismatches,
        "frozen_exposure_mismatch_count": frozen_exposure_mismatches,
        "same_timestamp_prior_hash_failure_count": same_timestamp_prior_hash_failures,
        "truth_leak_columns": sorted(truth_leak_columns),
        "errors": errors,
    }


def run_self_test(config_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="n_frontend3b_validator_") as temp:
        output = Path(temp) / "result"
        subprocess.run(
            [
                sys.executable,
                str(repo_root / "scripts" / "run_n_frontend3b_background_suppression.py"),
                "--self-test",
                "--config",
                str(config_path),
                "--output-dir",
                str(output),
                "--overwrite",
            ],
            check=True,
            cwd=repo_root,
            stdout=subprocess.DEVNULL,
        )
        # The runner creates its upstream 2B fixture in a temporary directory.
        # Persist an immutable reconstruction beside each validation fixture so
        # this independent validator can re-evaluate eligibility after the
        # runner's temporary source has been removed.
        for variant in sorted((output / "evaluation_only").glob("*/*")):
            source_copy = variant / "_validator_selftest_source_transitions.parquet"
            full = pd.concat(
                [
                    pd.read_parquet(variant / "semantic_foreground_transitions.parquet"),
                    pd.read_parquet(variant / "immutable_background_transitions.parquet"),
                    pd.read_parquet(variant / "gray_contract_anomaly_transitions.parquet"),
                ],
                ignore_index=True,
                sort=False,
            )
            full.to_parquet(source_copy, index=False)
            manifest_path = variant / "n_frontend3b_variant_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["source_transition_path"] = str(source_copy)
            manifest["source_transition_sha256"] = sha256_file(source_copy)
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        result = validate(output, config_path)
        assert result["validation_passed"], result

        # Negative regression: the independently anchored 2B exposure table
        # is not interchangeable with the runner's own pre/post comparison.
        variant = sorted((output / "evaluation_only").glob("*/*"))[0]
        manifest_path = variant / "n_frontend3b_variant_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        exposure_path = Path(manifest["source_exposure_path"])
        original_exposure = exposure_path.read_bytes()
        exposure = pd.read_csv(exposure_path)
        exposure.loc[exposure.index[0], "prior_exposure_count"] = (
            int(exposure.loc[exposure.index[0], "prior_exposure_count"]) + 1
        )
        exposure.to_csv(exposure_path, index=False)
        manifest["source_exposure_sha256"] = sha256_file(exposure_path)
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        tampered_exposure = validate(output, config_path)
        assert not tampered_exposure["validation_passed"]
        assert tampered_exposure["frozen_exposure_mismatch_count"] > 0
        exposure_path.write_bytes(original_exposure)
        manifest["source_exposure_sha256"] = sha256_file(exposure_path)
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        # Negative regression: flip one background-eligible assignment to
        # foreground. The independent validator must reject the inconsistency.
        path = variant / "n_frontend3b_transition_assignments.parquet"
        frame = pd.read_parquet(path)
        target = frame.index[frame["eligibility_assignment"] == ASSIGN_BACKGROUND][0]
        frame.loc[target, "eligibility_assignment"] = ASSIGN_FOREGROUND
        frame.to_parquet(path, index=False)
        tampered = validate(output, config_path)
        assert not tampered["validation_passed"]
        assert tampered["independent_assignment_mismatch_count"] > 0
    print("self_test=passed")


def main() -> None:
    args = parse_args()
    config_path = Path(args.config).resolve()
    if args.self_test:
        run_self_test(config_path)
        return
    if not args.output_dir:
        raise ValueError("--output-dir is required")
    result = validate(Path(args.output_dir).resolve(), config_path)
    target = Path(args.validation_output).resolve() if args.validation_output else Path(args.output_dir).resolve() / "n_frontend3b_validation.json"
    result = json_ready(result)
    target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    if not result["validation_passed"]:
        raise SystemExit("N-FRONTEND-3B validation failed")


if __name__ == "__main__":
    main()
