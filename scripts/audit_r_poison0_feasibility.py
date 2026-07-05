"""Audit R-POISON-0 paired poisoning/evasion benchmark feasibility.

This script is intentionally read-only with respect to experiment inputs. It
does not materialize poisoned/evasive BGP rows and does not modify foreground
policy. Its job is to verify that the next poisoning/evasion phase has a
scientifically strict paired protocol before any data generation starts.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_CONFIG = "configs/r_poison0_paired_benchmark_protocol_v01.json"
DEFAULT_ATTACK0B_CONFIG = "configs/r_attack0b_multi_attack_smoke_v01.json"
DEFAULT_ATTACK1_CONFIG = "configs/r_attack1_family_expansion_v01.json"

DEFAULT_ATTACK0B_VALIDATION_CANDIDATES = [
    "outputs/r_attack_0b/s2a_attack0b_multi_attack_smoke_6h_april16_v01/full_replay_validation.json",
    r"D:\study\paper\supercompute_transfer\r_attack0b_pullback_2775002\outputs\r_attack_0b\s2a_attack0b_multi_attack_smoke_6h_april16_v01\full_replay_validation.json",
]
DEFAULT_ATTACK1_VALIDATION_CANDIDATES = [
    "outputs/r_attack_1/s2a_attack1_family_expansion_6h_april16_v01/full_replay_validation.json",
    r"D:\study\paper\supercompute_transfer\r_attack1_pullback_20260705_125817\outputs\r_attack_1\s2a_attack1_family_expansion_6h_april16_v01\full_replay_validation.json",
]

REQUIRED_HELD_CONSTANTS = {
    "victim_prefix_group",
    "legitimate_origin_group",
    "attacker_as_group",
    "background_window_id",
    "evidence_snapshot_binding",
    "foreground_policy",
}
REQUIRED_COMMON_FIELDS = {
    "pair_id",
    "clean_base_scenario_id",
    "family",
    "adversarial_variant",
    "threat_model",
    "benchmark_track",
    "materialization_status",
    "held_constant",
    "changed_variables",
    "phases",
    "observability_contract",
}
ALLOWED_VARIANTS = {
    "clean",
    "data_poisoned",
    "visibility_evasive",
    "noexport_evasive",
    "combined",
}
CORE_THREAT_MODELS = {"detection_data_poisoning", "visibility_evasion"}
VISIBILITY_THREAT_MODELS = {"visibility_evasion"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit R-POISON-0 paired poisoning/evasion protocol feasibility."
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--attack0b-config", default=DEFAULT_ATTACK0B_CONFIG)
    parser.add_argument("--attack1-config", default=DEFAULT_ATTACK1_CONFIG)
    parser.add_argument("--attack0b-validation")
    parser.add_argument("--attack1-validation")
    parser.add_argument(
        "--output-dir",
        default="outputs/r_poison_0/s2a_baseline_v01_pilot_6h_april16",
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def resolve_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def resolve_first_existing(explicit: str | None, candidates: list[str]) -> Path | None:
    search: list[str] = []
    if explicit:
        search.append(explicit)
    search.extend(candidates)
    for item in search:
        path = resolve_path(item)
        if path.exists():
            return path
    return None


def scenario_registry(*configs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}
    for config in configs:
        for scenario in config.get("scenarios", []):
            scenario_id = scenario.get("scenario_id")
            if scenario_id:
                registry[str(scenario_id)] = dict(scenario)
    return registry


def validation_status(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {
            "available": False,
            "validated": False,
            "path": None,
            "foreground_attack_retention": None,
            "foreground_suppressed_attack_count": None,
        }
    data = read_json(path)
    return {
        "available": True,
        "validated": bool(data.get("validated")),
        "path": str(path),
        "phase": data.get("phase"),
        "foreground_attack_retention": data.get("foreground_attack_retention"),
        "foreground_suppressed_attack_count": data.get(
            "foreground_suppressed_attack_count"
        ),
        "attack_subtype_counts": data.get("attack_subtype_counts", {}),
    }


def base_phase_for_scenario(scenario_id: str) -> str:
    if scenario_id.startswith("r_attack0b_"):
        return "R-ATTACK-0B"
    if scenario_id.startswith("r_attack1_"):
        return "R-ATTACK-1"
    return "unknown"


def audit_pair(
    pair: dict[str, Any],
    scenarios: dict[str, dict[str, Any]],
    validations: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    missing_common = sorted(REQUIRED_COMMON_FIELDS - set(pair))
    for field in missing_common:
        errors.append(f"missing_field:{field}")

    pair_id = str(pair.get("pair_id", ""))
    clean_base = str(pair.get("clean_base_scenario_id", ""))
    base = scenarios.get(clean_base)
    if base is None:
        errors.append("clean_base_missing")
    elif base.get("scenario_class") != "attack":
        errors.append("clean_base_not_attack")

    base_phase = base_phase_for_scenario(clean_base)
    validation = validations.get(base_phase, {})
    if not validation.get("available"):
        warnings.append(f"base_validation_missing:{base_phase}")
    elif not validation.get("validated"):
        errors.append(f"base_validation_failed:{base_phase}")

    held_constant = set(pair.get("held_constant") or [])
    missing_held = sorted(REQUIRED_HELD_CONSTANTS - held_constant)
    for item in missing_held:
        errors.append(f"missing_held_constant:{item}")

    changed_variables = pair.get("changed_variables") or []
    if not changed_variables:
        errors.append("missing_changed_variables")

    threat_model = str(pair.get("threat_model", ""))
    if threat_model not in CORE_THREAT_MODELS:
        errors.append(f"unknown_or_noncore_threat_model:{threat_model}")

    variant = str(pair.get("adversarial_variant", ""))
    if variant not in ALLOWED_VARIANTS or variant == "clean":
        errors.append(f"invalid_adversarial_variant:{variant}")

    materialization_status = str(pair.get("materialization_status", ""))
    if materialization_status != "protocol_ready_pending_r_poison1":
        warnings.append(f"not_materialization_ready:{materialization_status}")

    phases = set(pair.get("phases") or [])
    if threat_model == "detection_data_poisoning":
        if "poisoning_preparation" not in phases:
            errors.append("poisoning_pair_missing_preparation_phase")
        if not pair.get("knowledge_base_targets"):
            errors.append("poisoning_pair_missing_knowledge_base_targets")
        if not pair.get("drift_metrics"):
            errors.append("poisoning_pair_missing_drift_metrics")

    contract = pair.get("observability_contract") or {}
    expected_visibility = str(contract.get("expected_visibility_class", ""))
    denominator_policy = str(contract.get("recall_denominator_policy", ""))
    if not expected_visibility:
        errors.append("missing_expected_visibility_class")
    if not denominator_policy:
        errors.append("missing_recall_denominator_policy")
    if expected_visibility == "public_invisible" and "excluded" not in denominator_policy:
        errors.append("public_invisible_counted_as_recall_miss")
    if threat_model in VISIBILITY_THREAT_MODELS:
        seen = str(contract.get("expected_public_collectors_seen", ""))
        not_seen = str(contract.get("expected_public_collectors_not_seen", ""))
        if not seen:
            errors.append("visibility_pair_missing_expected_seen_collectors")
        if not not_seen:
            errors.append("visibility_pair_missing_expected_not_seen_collectors")

    family_match = None
    if base is not None:
        family_match = {
            "base_primary_family": base.get("primary_family"),
            "base_attack_subtype": base.get("attack_subtype"),
            "pair_family": pair.get("family"),
        }

    feasible = not errors and materialization_status == "protocol_ready_pending_r_poison1"
    return {
        "pair_id": pair_id,
        "clean_base_scenario_id": clean_base,
        "base_phase": base_phase,
        "base_available": base is not None,
        "base_validation_available": bool(validation.get("available")),
        "base_validation_validated": bool(validation.get("validated")),
        "family": pair.get("family"),
        "threat_model": threat_model,
        "adversarial_variant": variant,
        "materialization_status": materialization_status,
        "expected_visibility_class": expected_visibility,
        "recall_denominator_policy": denominator_policy,
        "held_constant_count": len(held_constant),
        "changed_variable_count": len(changed_variables),
        "has_knowledge_base_targets": bool(pair.get("knowledge_base_targets")),
        "has_drift_metrics": bool(pair.get("drift_metrics")),
        "feasible_for_r_poison1": feasible,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": ";".join(errors),
        "warnings": ";".join(warnings),
        "family_match": json.dumps(family_match, ensure_ascii=False, sort_keys=True),
    }


def audit_required_fields(pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    required = sorted(
        REQUIRED_COMMON_FIELDS
        | {
            "knowledge_base_targets",
            "drift_metrics",
            "forbidden_shortcuts",
        }
    )
    for field in required:
        present = sum(1 for pair in pairs if field in pair and pair.get(field) not in (None, [], {}))
        rows.append(
            {
                "protocol_field": field,
                "pair_count": len(pairs),
                "present_count": present,
                "missing_count": len(pairs) - present,
                "coverage_rate": round(present / len(pairs), 6) if pairs else None,
                "notes": field_notes(field),
            }
        )
    return rows


def field_notes(field: str) -> str:
    notes = {
        "held_constant": "required to make clean-vs-adversarial comparison paired",
        "changed_variables": "required to isolate poisoning/evasion manipulation",
        "observability_contract": "required to avoid counting public-invisible cases as misses",
        "knowledge_base_targets": "required for detection-data poisoning pairs",
        "drift_metrics": "required for detection-data poisoning pairs",
        "forbidden_shortcuts": "required to encode reviewer-risk guardrails",
    }
    return notes.get(field, "required protocol field")


def audit_forbidden_shortcuts(config: dict[str, Any], pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    global_claims = config.get("global_forbidden_claims") or []
    for claim in global_claims:
        rows.append(
            {
                "scope": "global",
                "pair_id": "*",
                "forbidden_shortcut": claim,
                "encoded": True,
                "notes": "global guardrail",
            }
        )
    for pair in pairs:
        shortcuts = pair.get("forbidden_shortcuts") or []
        rows.append(
            {
                "scope": "pair",
                "pair_id": pair.get("pair_id"),
                "forbidden_shortcut": "pair_forbidden_shortcuts_present",
                "encoded": bool(shortcuts),
                "notes": f"{len(shortcuts)} pair-specific shortcuts",
            }
        )
        for shortcut in shortcuts:
            rows.append(
                {
                    "scope": "pair",
                    "pair_id": pair.get("pair_id"),
                    "forbidden_shortcut": shortcut,
                    "encoded": True,
                    "notes": "pair-specific guardrail",
                }
            )
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_next_action(path: Path, summary: dict[str, Any]) -> None:
    if summary["overall_feasible"]:
        action = (
            "Proceed to R-POISON-1 bounded materialization for feasible pairs only. "
            "Keep route-leak policy poisoning design-only until policy semantics are bounded."
        )
    else:
        action = (
            "Do not materialize poisoning/evasion data. Repair protocol blockers first."
        )
    lines = [
        "# R-POISON-0 Recommended Next Action",
        "",
        f"- overall_feasible: `{summary['overall_feasible']}`",
        f"- feasible_pair_count: `{summary['feasible_pair_count']}`",
        f"- blocked_pair_count: `{summary['blocked_pair_count']}`",
        f"- core_threat_models_covered: `{', '.join(summary['core_threat_models_covered'])}`",
        f"- recommended_next_step: {action}",
        "",
        "Guardrails:",
        "",
        "- R-POISON-0 generated no attack data and trained no model.",
        "- R-POISON-1 may materialize only paired clean-vs-adversarial variants.",
        "- Public-invisible variants require an explicit observability denominator.",
        "- NO_EXPORT, RPKI, and AS-rel remain evidence or diagnostics, not truth.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def prepare_output_dir(path: Path, overwrite: bool) -> None:
    outputs = [
        "r_poison0_summary.json",
        "r_poison0_pair_feasibility.csv",
        "r_poison0_required_protocol_fields.csv",
        "r_poison0_forbidden_shortcut_audit.csv",
        "r_poison0_next_action.md",
    ]
    if path.exists() and not overwrite:
        existing = [name for name in outputs if (path / name).exists()]
        if existing:
            raise SystemExit(
                "Output files already exist; pass --overwrite to replace: "
                + ", ".join(existing)
            )
    path.mkdir(parents=True, exist_ok=True)


def main() -> None:
    args = parse_args()
    config_path = resolve_path(args.config)
    attack0b_config_path = resolve_path(args.attack0b_config)
    attack1_config_path = resolve_path(args.attack1_config)
    output_dir = resolve_path(args.output_dir)
    prepare_output_dir(output_dir, args.overwrite)

    config = read_json(config_path)
    attack0b_config = read_json(attack0b_config_path)
    attack1_config = read_json(attack1_config_path)

    attack0b_validation_path = resolve_first_existing(
        args.attack0b_validation, DEFAULT_ATTACK0B_VALIDATION_CANDIDATES
    )
    attack1_validation_path = resolve_first_existing(
        args.attack1_validation, DEFAULT_ATTACK1_VALIDATION_CANDIDATES
    )
    validations = {
        "R-ATTACK-0B": validation_status(attack0b_validation_path),
        "R-ATTACK-1": validation_status(attack1_validation_path),
    }

    scenarios = scenario_registry(attack0b_config, attack1_config)
    pairs = config.get("pair_templates") or []
    pair_rows = [audit_pair(pair, scenarios, validations) for pair in pairs]
    field_rows = audit_required_fields(pairs)
    shortcut_rows = audit_forbidden_shortcuts(config, pairs)

    feasible_pairs = [row for row in pair_rows if row["feasible_for_r_poison1"]]
    blocked_pairs = [row for row in pair_rows if not row["feasible_for_r_poison1"]]
    covered_threat_models = sorted(
        {row["threat_model"] for row in feasible_pairs if row["threat_model"]}
    )
    required_models = set(
        config.get("stop_loss_criteria", {}).get(
            "required_core_pair_types", list(CORE_THREAT_MODELS)
        )
    )
    minimum_feasible = int(
        config.get("stop_loss_criteria", {}).get("minimum_feasible_core_pairs", 0)
    )
    validation_pass = all(
        validations[phase]["available"] and validations[phase]["validated"]
        for phase in ("R-ATTACK-0B", "R-ATTACK-1")
    )
    overall_feasible = (
        validation_pass
        and len(feasible_pairs) >= minimum_feasible
        and required_models.issubset(set(covered_threat_models))
    )

    summary = {
        "phase": "R-POISON-0",
        "schema_version": config.get("schema_version"),
        "overall_feasible": overall_feasible,
        "this_phase_generated_attack_data": False,
        "this_phase_trained_learning": False,
        "this_phase_changed_foreground_policy": False,
        "r_poison1_materialization_feasible": overall_feasible,
        "pair_count": len(pair_rows),
        "feasible_pair_count": len(feasible_pairs),
        "blocked_pair_count": len(blocked_pairs),
        "blocked_pair_ids": [row["pair_id"] for row in blocked_pairs],
        "core_threat_models_covered": covered_threat_models,
        "minimum_feasible_core_pairs": minimum_feasible,
        "required_core_pair_types": sorted(required_models),
        "base_validation_status": validations,
        "base_scenario_count": len(scenarios),
        "foreground_policy": config.get("foreground_policy"),
        "evidence_snapshot_binding": config.get("evidence_snapshot_binding"),
        "forbidden_claims_encoded": len(config.get("global_forbidden_claims", [])),
        "allowed_claim": (
            "R-POISON-0 defines and audits a paired poisoning/evasion benchmark "
            "protocol; it does not prove poisoning robustness."
        ),
        "forbidden_claims": config.get("global_forbidden_claims", []),
        "recommended_next_step": (
            "R-POISON-1 bounded materialization for feasible paired variants"
            if overall_feasible
            else "repair R-POISON-0 protocol blockers before materialization"
        ),
    }

    write_json(output_dir / "r_poison0_summary.json", summary)
    write_csv(output_dir / "r_poison0_pair_feasibility.csv", pair_rows)
    write_csv(output_dir / "r_poison0_required_protocol_fields.csv", field_rows)
    write_csv(output_dir / "r_poison0_forbidden_shortcut_audit.csv", shortcut_rows)
    write_next_action(output_dir / "r_poison0_next_action.md", summary)

    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
