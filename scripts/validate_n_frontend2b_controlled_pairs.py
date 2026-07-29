#!/usr/bin/env python3
"""Validate N-FRONTEND-2B bounded replay artifacts independently."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd


TRUTH_COLUMNS = {
    "scenario_id",
    "pair_id",
    "variant_role",
    "phase_id",
    "member_id",
    "is_attack_member",
    "is_poisoning_preparation_member",
    "expected_visibility_class",
}


REQUIRED_ROOT_FILES = [
    "n_frontend2b_background_input_manifest.json",
    "n_frontend2b_background_cadence_audit.json",
    "n_frontend2b_observer_registry.json",
    "n_frontend2b_registry_freeze.json",
    "n_frontend2b_synthetic_observation_manifest.csv",
    "n_frontend2b_truth_provenance_sidecar.csv",
    "n_frontend2b_identity_duplicate_audit.csv",
    "n_frontend2b_pair_fairness_audit.csv",
    "n_frontend2b_phase_survival_lineage.csv",
    "n_frontend2b_past_only_route_exposure.csv",
    "n_frontend2b_attack_transition_semantic_delta.csv",
    "n_frontend2b_visibility_contract_audit.csv",
    "n_frontend2b_ambiguity_intersection_audit.csv",
    "n_frontend2b_drop_localization.csv",
    "n_frontend2b_summary.json",
    "n_frontend2b_report.md",
]


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def bool_series(series: pd.Series, name: str) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)
    normalized = series.astype("string").str.strip().str.lower()
    allowed = {"true", "false"}
    unknown = sorted(set(normalized.dropna().unique()) - allowed)
    if unknown:
        raise ValueError(f"invalid boolean values in {name}: {unknown}")
    return normalized.map({"true": True, "false": False}).fillna(False).astype(bool)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--expected-pair-count", type=int, default=5)
    parser.add_argument("--validation-output", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(args.output_dir)
    failures: list[str] = []
    for name in REQUIRED_ROOT_FILES:
        path = root / name
        if not path.is_file() or path.stat().st_size == 0:
            failures.append(f"missing_or_empty:{name}")
    if failures:
        result = {
            "validation_passed": False,
            "failures": failures,
            "pair_count": None,
            "variant_count": None,
        }
        output = Path(args.validation_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        print(json.dumps(result, sort_keys=True))
        raise SystemExit(1)

    summary = json.loads((root / "n_frontend2b_summary.json").read_text())
    required_true = [
        "registry_frozen_before_replay",
        "semantic_phase_survival_pass",
        "past_only_causality_pass",
        "attack_transition_semantic_delta_pass",
        "identity_and_duplicate_gate_pass",
        "visibility_contract_pass",
        "ambiguity_contract_pass",
        "pair_fairness_pass",
        "overall_pass",
    ]
    failures.extend(
        f"summary_false:{key}" for key in required_true if not summary.get(key)
    )
    if int(summary.get("pair_count", -1)) != args.expected_pair_count:
        failures.append("pair_count_mismatch")
    if int(summary.get("variant_count", -1)) != args.expected_pair_count * 2:
        failures.append("variant_count_mismatch")
    if summary.get("background_suppression_performed") is not False:
        failures.append("suppression_boundary_violated")
    if summary.get("learning_trained") is not False:
        failures.append("learning_boundary_violated")
    if summary.get("route_leak_status") != "blocked_diagnostic_only":
        failures.append("route_leak_boundary_violated")

    freeze = json.loads((root / "n_frontend2b_registry_freeze.json").read_text())
    registry = root / "n_frontend2b_observer_registry.json"
    cadence = root / "n_frontend2b_background_cadence_audit.json"
    if hashlib.sha256(registry.read_bytes()).hexdigest() != freeze["registry_sha256"]:
        failures.append("registry_hash_mismatch")
    if hashlib.sha256(cadence.read_bytes()).hexdigest() != freeze["cadence_audit_sha256"]:
        failures.append("cadence_hash_mismatch")
    freeze_copy = dict(freeze)
    stored_fingerprint = freeze_copy.pop("freeze_fingerprint", None)
    calculated_fingerprint = hashlib.sha256(
        stable_json(freeze_copy).encode("utf-8")
    ).hexdigest()
    if stored_fingerprint != calculated_fingerprint:
        failures.append("freeze_fingerprint_mismatch")
    if summary.get("registry_freeze_fingerprint") != stored_fingerprint:
        failures.append("summary_freeze_fingerprint_mismatch")

    cadence_rows = json.loads(cadence.read_text(encoding="utf-8"))
    if not cadence_rows:
        failures.append("empty_cadence_audit")
    for row in cadence_rows:
        if row.get("evidence_scope") != "background_only_before_materialization":
            failures.append("cadence_not_background_only")
            break
        if row.get("intermediate_background_class") == "no_legitimate_restore":
            if int(row.get("post_template_background_count", -1)) != 0:
                failures.append("cadence_classification_mismatch")
                break

    lineage = pd.read_csv(root / "n_frontend2b_phase_survival_lineage.csv")
    expected_visible = bool_series(lineage["expected_visible"], "expected_visible")
    if not bool_series(
        lineage.loc[expected_visible, "semantic_survived"], "semantic_survived"
    ).all():
        failures.append("visible_member_loss")
    invisible = lineage.loc[~expected_visible]
    if not invisible.empty and not bool_series(
        invisible["observability_boundary"], "observability_boundary"
    ).all():
        failures.append("invisible_member_not_boundary")

    exposure = pd.read_csv(root / "n_frontend2b_past_only_route_exposure.csv")
    if not bool_series(exposure["causality_valid"], "causality_valid").all():
        failures.append("past_only_causality_failure")
    contributing = exposure["maximum_contributing_transition_ts"].dropna()
    aligned_attack_ts = exposure.loc[contributing.index, "attack_ts"]
    if not (contributing < aligned_attack_ts).all():
        failures.append("future_transition_contributed")

    delta = pd.read_csv(root / "n_frontend2b_attack_transition_semantic_delta.csv")
    if not bool_series(
        delta["family_expectation_matched"], "family_expectation_matched"
    ).all():
        failures.append("transition_family_expectation_failure")
    identity = pd.read_csv(root / "n_frontend2b_identity_duplicate_audit.csv")
    if not bool_series(identity["passed"], "identity_passed").all():
        failures.append("identity_duplicate_failure")
    fairness = pd.read_csv(root / "n_frontend2b_pair_fairness_audit.csv")
    if not bool_series(fairness["passed"], "fairness_passed").all():
        failures.append("pair_fairness_failure")
    visibility = pd.read_csv(root / "n_frontend2b_visibility_contract_audit.csv")
    if not bool_series(
        visibility["contract_satisfied"], "visibility_contract_satisfied"
    ).all():
        failures.append("visibility_contract_failure")

    variant_summaries = sorted(
        root.glob("evaluation_only/*/*/frontend/n_frontend1_summary.json")
    )
    if len(variant_summaries) != args.expected_pair_count * 2:
        failures.append(
            f"variant_frontend_summary_count:{len(variant_summaries)}"
        )
    mixed_parquets = sorted(
        root.glob("evaluation_only/*/*/evaluation_only_mixed_canonical.parquet")
    )
    if len(mixed_parquets) != args.expected_pair_count * 2:
        failures.append(f"mixed_canonical_count:{len(mixed_parquets)}")
    for path in mixed_parquets:
        leaked = sorted(TRUTH_COLUMNS & set(pd.read_parquet(path).columns))
        if leaked:
            failures.append(f"truth_columns_in_canonical:{path}:{'|'.join(leaked)}")

    report_text = (root / "n_frontend2b_report.md").read_text(encoding="utf-8").lower()
    if "does not validate poisoning" not in report_text:
        failures.append("claim_boundary_missing")

    result = {
        "validation_passed": not failures,
        "failures": failures,
        "pair_count": int(summary["pair_count"]),
        "variant_count": int(summary["variant_count"]),
        "expected_visible_member_count": int(summary["expected_visible_member_count"]),
        "observability_boundary_member_count": int(
            summary["observability_boundary_member_count"]
        ),
        "registry_freeze_fingerprint": summary["registry_freeze_fingerprint"],
        "allowed_claim": summary["allowed_claim"],
    }
    output = Path(args.validation_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
