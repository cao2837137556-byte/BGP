"""Materialize bounded R-POISON-1 paired poisoning/evasion prototypes.

R-POISON-1 intentionally does not run a full raw-to-foreground replay. It
creates a small, auditable benchmark asset for the feasible R-POISON-0 pairs:
pair registry, evaluation-only truth prototypes, comparability audit, and
evidence/foreground contracts. Actual adversarial foreground retention remains
pending until the next replay phase.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_PROTOCOL = "configs/r_poison0_paired_benchmark_protocol_v01.json"
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
DEFAULT_ATTACK0B_FOREGROUND_CANDIDATES = [
    r"D:\study\paper\supercompute_transfer\r_attack0b_pullback_2775002\outputs\r_attack_0b\s2a_attack0b_multi_attack_smoke_6h_april16_v01\foreground3\r_foreground3_summary.json",
]
DEFAULT_ATTACK1_FOREGROUND_CANDIDATES = [
    r"D:\study\paper\supercompute_transfer\r_attack1_pullback_20260705_125817\outputs\r_attack_1\s2a_attack1_family_expansion_6h_april16_v01\foreground3\r_foreground3_summary.json",
]

REQUIRED_HELD_CONSTANTS = {
    "victim_prefix_group",
    "legitimate_origin_group",
    "attacker_as_group",
    "background_window_id",
    "evidence_snapshot_binding",
    "foreground_policy",
}
FEASIBLE_STATUS = "protocol_ready_pending_r_poison1"
DESIGN_ONLY_STATUS = "design_only_needs_policy_semantics"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", default=DEFAULT_PROTOCOL)
    parser.add_argument("--attack0b-config", default=DEFAULT_ATTACK0B_CONFIG)
    parser.add_argument("--attack1-config", default=DEFAULT_ATTACK1_CONFIG)
    parser.add_argument("--attack0b-validation", default="")
    parser.add_argument("--attack1-validation", default="")
    parser.add_argument("--attack0b-foreground-summary", default="")
    parser.add_argument("--attack1-foreground-summary", default="")
    parser.add_argument(
        "--output-dir",
        default="outputs/r_poison_1/s2a_baseline_v01_pilot_6h_april16",
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def resolve_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def resolve_first_existing(explicit: str, candidates: list[str]) -> Path | None:
    search: list[str] = []
    if explicit:
        search.append(explicit)
    search.extend(candidates)
    for item in search:
        path = resolve_path(item)
        if path.exists():
            return path
    return None


def read_json(path: str | Path) -> dict[str, Any]:
    with resolve_path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


def read_json_optional(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, payload: dict[str, Any] | list[dict[str, Any]]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_parquet_or_note(path: Path, frame: pd.DataFrame) -> str:
    try:
        frame.to_parquet(path, index=False)
        return "written"
    except Exception as exc:  # pragma: no cover - depends on local parquet engine
        note_path = path.with_suffix(path.suffix + ".not_written.txt")
        note_path.write_text(
            f"Parquet output was not written: {type(exc).__name__}: {exc}\n",
            encoding="utf-8",
        )
        return f"not_written:{type(exc).__name__}"


def scenario_registry(*configs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}
    for config in configs:
        for scenario in config.get("scenarios", []):
            sid = scenario.get("scenario_id")
            if sid:
                registry[str(sid)] = dict(scenario)
    return registry


def base_phase_for_scenario(scenario_id: str) -> str:
    if scenario_id.startswith("r_attack0b_"):
        return "R-ATTACK-0B"
    if scenario_id.startswith("r_attack1_"):
        return "R-ATTACK-1"
    return "unknown"


def validation_summary(path: Path | None) -> dict[str, Any]:
    data = read_json_optional(path)
    return {
        "available": bool(data),
        "validated": bool(data.get("validated")),
        "path": str(path) if path else "",
        "foreground_attack_retention": data.get("foreground_attack_retention"),
        "foreground_suppressed_attack_count": data.get(
            "foreground_suppressed_attack_count"
        ),
        "foreground_background_suppression_rate": data.get(
            "foreground_background_suppression_rate"
        ),
        "foreground_compression_ratio": data.get("foreground_compression_ratio"),
    }


def foreground_summary(path: Path | None) -> dict[str, Any]:
    data = read_json_optional(path)
    return {
        "available": bool(data),
        "path": str(path) if path else "",
        "policy_id": data.get("policy_id"),
        "online_pass": data.get("online_pass"),
        "attack_retention": data.get("attack_retention"),
        "suppressed_attack_count": data.get("suppressed_attack_count"),
        "pure_reference_background_suppression_rate": data.get(
            "pure_reference_background_suppression_rate"
        ),
        "estimated_compression_ratio": data.get("estimated_compression_ratio"),
    }


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def pair_hash(pair_id: str, variant_role: str, phase_id: str) -> str:
    text = f"{pair_id}|{variant_role}|{phase_id}"
    return "poison1_" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:20]


def extract_constant(base: dict[str, Any], pair: dict[str, Any], name: str, protocol: dict[str, Any]) -> Any:
    if name == "background_window_id":
        return protocol.get("source_background_run_id")
    if name == "evidence_snapshot_binding":
        return protocol.get("evidence_snapshot_binding")
    if name == "foreground_policy":
        return protocol.get("foreground_policy")
    if name == "collector_set_id":
        return (
            base.get("collector_set_id")
            or protocol.get("evidence_snapshot_binding", {}).get("collector_set_id")
            or "route_views_sg_plus_rrc00_v1"
        )
    if name == "prefix_specificity":
        active = base.get("active_template", {})
        baseline = base.get("baseline_template", {})
        active_prefix = active.get("output_prefix") or active.get("prefix")
        base_prefix = baseline.get("output_prefix") or baseline.get("prefix")
        return "subprefix" if active_prefix != base_prefix else "exact"
    return base.get(name)


def expected_collectors(base: dict[str, Any], attack0b_config: dict[str, Any]) -> list[str]:
    collectors = base.get("expected_collectors")
    if collectors:
        return list(collectors)
    return list(attack0b_config.get("expected_collectors", []))


def build_pair_registry(
    protocol: dict[str, Any],
    attack0b_config: dict[str, Any],
    scenarios: dict[str, dict[str, Any]],
    validations: dict[str, dict[str, Any]],
    foregrounds: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    blocked_design_only: list[str] = []
    for pair in protocol.get("pair_templates", []):
        status = pair.get("materialization_status")
        pair_id = str(pair.get("pair_id"))
        if status == DESIGN_ONLY_STATUS:
            blocked_design_only.append(pair_id)
            continue
        if status != FEASIBLE_STATUS:
            continue
        clean_base_id = str(pair.get("clean_base_scenario_id"))
        base = scenarios.get(clean_base_id, {})
        phase = base_phase_for_scenario(clean_base_id)
        row = {
            "pair_id": pair_id,
            "clean_base_scenario_id": clean_base_id,
            "clean_variant_scenario_id": f"{pair_id}__clean",
            "adversarial_variant_scenario_id": f"{pair_id}__{pair.get('adversarial_variant')}",
            "family": pair.get("family"),
            "threat_model": pair.get("threat_model"),
            "adversarial_variant": pair.get("adversarial_variant"),
            "base_phase": phase,
            "base_primary_family": base.get("primary_family"),
            "base_attack_subtype": base.get("attack_subtype"),
            "victim_prefix_group": base.get("victim_prefix_group"),
            "legitimate_origin_group": base.get("legitimate_origin_group"),
            "attacker_as_group": base.get("attacker_as_group"),
            "background_window_id": protocol.get("source_background_run_id"),
            "collector_set_id": extract_constant(base, pair, "collector_set_id", protocol),
            "expected_clean_collectors": stable_json(expected_collectors(base, attack0b_config)),
            "expected_visibility_class": (pair.get("observability_contract") or {}).get(
                "expected_visibility_class"
            ),
            "recall_denominator_policy": (pair.get("observability_contract") or {}).get(
                "recall_denominator_policy"
            ),
            "held_constant": stable_json(pair.get("held_constant", [])),
            "changed_variables": stable_json(pair.get("changed_variables", [])),
            "knowledge_base_targets": stable_json(pair.get("knowledge_base_targets", [])),
            "drift_metrics": stable_json(pair.get("drift_metrics", [])),
            "evidence_snapshot_binding": stable_json(
                protocol.get("evidence_snapshot_binding", {})
            ),
            "foreground_policy": protocol.get("foreground_policy"),
            "base_validation_available": validations.get(phase, {}).get("available"),
            "base_validation_validated": validations.get(phase, {}).get("validated"),
            "base_foreground_attack_retention": validations.get(phase, {}).get(
                "foreground_attack_retention"
            ),
            "base_foreground_suppressed_attack_count": validations.get(phase, {}).get(
                "foreground_suppressed_attack_count"
            ),
            "foreground_summary_available": foregrounds.get(phase, {}).get("available"),
            "foreground_online_pass": foregrounds.get(phase, {}).get("online_pass"),
            "materialization_scope": "bounded_truth_prototype_no_full_replay",
        }
        rows.append(row)

    audit_rows = []
    for row in rows:
        held = set(json.loads(row["held_constant"]))
        missing = sorted(REQUIRED_HELD_CONSTANTS - held)
        changed = json.loads(row["changed_variables"])
        errors = []
        if missing:
            errors.append("missing_held_constants:" + "|".join(missing))
        if not changed:
            errors.append("missing_changed_variables")
        if not row["base_validation_validated"]:
            errors.append("clean_base_not_validated")
        if row["adversarial_variant"] == "clean":
            errors.append("adversarial_variant_is_clean")
        if row["expected_visibility_class"] == "public_invisible" and "excluded" not in str(
            row["recall_denominator_policy"]
        ):
            errors.append("public_invisible_not_excluded")
        audit_rows.append(
            {
                "pair_id": row["pair_id"],
                "clean_base_scenario_id": row["clean_base_scenario_id"],
                "base_phase": row["base_phase"],
                "held_constant_count": len(held),
                "changed_variable_count": len(changed),
                "base_validation_validated": row["base_validation_validated"],
                "base_foreground_attack_retention": row["base_foreground_attack_retention"],
                "base_foreground_suppressed_attack_count": row[
                    "base_foreground_suppressed_attack_count"
                ],
                "expected_visibility_class": row["expected_visibility_class"],
                "recall_denominator_policy": row["recall_denominator_policy"],
                "fair_pair_contract_pass": not errors,
                "errors": ";".join(errors),
            }
        )
    return rows, audit_rows, blocked_design_only


def build_truth_prototypes(pair_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pair in pair_rows:
        common = {
            "pair_id": pair["pair_id"],
            "clean_base_scenario_id": pair["clean_base_scenario_id"],
            "family": pair["family"],
            "threat_model": pair["threat_model"],
            "victim_prefix_group": pair["victim_prefix_group"],
            "legitimate_origin_group": pair["legitimate_origin_group"],
            "attacker_as_group": pair["attacker_as_group"],
            "background_window_id": pair["background_window_id"],
            "collector_set_id": pair["collector_set_id"],
            "evidence_snapshot_binding": pair["evidence_snapshot_binding"],
            "foreground_policy": pair["foreground_policy"],
            "expected_visibility_class": pair["expected_visibility_class"],
            "recall_denominator_policy": pair["recall_denominator_policy"],
            "truth_source": "controlled_pair_protocol",
            "truth_confidence_tier": "tier1_controlled",
            "truth_semantics": "evaluation_only",
        }
        variant_specs = [
            ("clean", pair["clean_variant_scenario_id"], "clean"),
            (
                "adversarial",
                pair["adversarial_variant_scenario_id"],
                pair["adversarial_variant"],
            ),
        ]
        for variant_role, variant_id, variant_type in variant_specs:
            phase_ids = ["stable_baseline", "attack_launch", "recovery"]
            if variant_role == "adversarial" and pair["threat_model"] == "detection_data_poisoning":
                phase_ids = [
                    "stable_baseline",
                    "poisoning_preparation",
                    "attack_launch",
                    "recovery",
                ]
            for phase_id in phase_ids:
                is_attack = phase_id == "attack_launch"
                is_poison = phase_id == "poisoning_preparation"
                rows.append(
                    {
                        **common,
                        "prototype_record_id": pair_hash(
                            pair["pair_id"], variant_role, phase_id
                        ),
                        "variant_role": variant_role,
                        "variant_scenario_id": variant_id,
                        "adversarial_variant": variant_type,
                        "phase_id": phase_id,
                        "attack_role": "poison_announce"
                        if is_poison
                        else ("attacker_announce" if is_attack else "background"),
                        "is_attack_member": is_attack,
                        "is_poisoning_preparation_member": is_poison,
                        "expected_foreground_evaluation_status": "clean_base_validated"
                        if variant_role == "clean"
                        else "pending_replay_validation",
                        "raw_parser_admitted": None,
                        "raw_event_eligible": True,
                        "event_contains_attack_member": None,
                        "attack_member_count": None,
                        "attack_member_share": None,
                        "drop_stage": "pending_replay",
                        "foreground_bucket": "pending_replay",
                        "allowed_claim": "bounded pair prototype for later replay",
                        "forbidden_claim": "do not claim adversarial retention before replay",
                    }
                )
    return rows


def build_contract_rows(pair_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pair in pair_rows:
        for variant_role, variant_id in [
            ("clean", pair["clean_variant_scenario_id"]),
            ("adversarial", pair["adversarial_variant_scenario_id"]),
        ]:
            rows.append(
                {
                    "pair_id": pair["pair_id"],
                    "variant_role": variant_role,
                    "variant_scenario_id": variant_id,
                    "threat_model": pair["threat_model"],
                    "adversarial_variant": "clean"
                    if variant_role == "clean"
                    else pair["adversarial_variant"],
                    "evidence_join_status": "clean_base_validated"
                    if variant_role == "clean"
                    else "must_recompute_in_replay",
                    "foreground_v1_retention_status": "clean_base_validated"
                    if variant_role == "clean"
                    else "pending_replay_validation",
                    "foreground_policy": pair["foreground_policy"],
                    "expected_visibility_class": pair["expected_visibility_class"],
                    "recall_denominator_policy": pair["recall_denominator_policy"],
                    "public_invisible_is_miss": False
                    if pair["expected_visibility_class"] == "public_invisible"
                    else None,
                    "allowed_claim": "contract checked"
                    if variant_role == "clean"
                    else "adversarial variant materialized as bounded prototype only",
                    "forbidden_claim": "poisoning robustness proven",
                }
            )
    return rows


def write_report(path: Path, summary: dict[str, Any], pair_rows: list[dict[str, Any]]) -> None:
    lines = [
        "# R-POISON-1 Bounded Paired Materialization",
        "",
        "Status: bounded materialization only; no full replay.",
        "",
        "## Summary",
        "",
        f"- materialized feasible pairs: `{summary['materialized_pair_count']}`",
        f"- truth prototype rows: `{summary['truth_prototype_rows']}`",
        f"- clean base validation pass: `{summary['clean_base_validation_pass']}`",
        f"- fair pair contract pass: `{summary['fair_pair_contract_pass']}`",
        f"- route-leak policy poisoning skipped: `{summary['route_leak_policy_poisoning_skipped']}`",
        "",
        "## Pair Scope",
        "",
        "| Pair | Threat model | Variant | Clean base | Status |",
        "|---|---|---|---|---|",
    ]
    for row in pair_rows:
        lines.append(
            f"| `{row['pair_id']}` | `{row['threat_model']}` | "
            f"`{row['adversarial_variant']}` | `{row['clean_base_scenario_id']}` | "
            "`bounded prototype` |"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- R-POISON-1 did not generate full derived raw runs.",
            "- R-POISON-1 did not run event/candidate/foreground replay.",
            "- Clean-base evidence and foreground status are inherited from already validated R-ATTACK-0B/R-ATTACK-1 results.",
            "- Adversarial evidence and foreground retention remain `pending_replay_validation`.",
            "- `NO_EXPORT` is propagation-control evidence, not attack truth.",
            "- Public-invisible variants are observability-boundary cases, not foreground misses.",
            "",
            "## Next Step",
            "",
            "R-POISON-2 should run bounded raw-level replay for the materialized feasible pairs, recompute evidence sidecars, and then rerun `online_path_pressure_v1` to measure clean-vs-adversarial retention drop.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def prepare_output_dir(path: Path, overwrite: bool) -> None:
    if path.exists() and any(path.iterdir()):
        if not overwrite:
            raise FileExistsError(f"output directory not empty; pass --overwrite: {path}")
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def main() -> None:
    args = parse_args()
    output_dir = resolve_path(args.output_dir)
    prepare_output_dir(output_dir, args.overwrite)

    protocol = read_json(args.protocol)
    attack0b_config = read_json(args.attack0b_config)
    attack1_config = read_json(args.attack1_config)
    scenarios = scenario_registry(attack0b_config, attack1_config)

    attack0b_validation = resolve_first_existing(
        args.attack0b_validation, DEFAULT_ATTACK0B_VALIDATION_CANDIDATES
    )
    attack1_validation = resolve_first_existing(
        args.attack1_validation, DEFAULT_ATTACK1_VALIDATION_CANDIDATES
    )
    attack0b_foreground = resolve_first_existing(
        args.attack0b_foreground_summary, DEFAULT_ATTACK0B_FOREGROUND_CANDIDATES
    )
    attack1_foreground = resolve_first_existing(
        args.attack1_foreground_summary, DEFAULT_ATTACK1_FOREGROUND_CANDIDATES
    )
    validations = {
        "R-ATTACK-0B": validation_summary(attack0b_validation),
        "R-ATTACK-1": validation_summary(attack1_validation),
    }
    foregrounds = {
        "R-ATTACK-0B": foreground_summary(attack0b_foreground),
        "R-ATTACK-1": foreground_summary(attack1_foreground),
    }

    pair_rows, comparability_rows, blocked_design_only = build_pair_registry(
        protocol, attack0b_config, scenarios, validations, foregrounds
    )
    truth_rows = build_truth_prototypes(pair_rows)
    contract_rows = build_contract_rows(pair_rows)

    pair_frame = pd.DataFrame(pair_rows)
    truth_frame = pd.DataFrame(truth_rows)
    comparability_frame = pd.DataFrame(comparability_rows)
    contract_frame = pd.DataFrame(contract_rows)

    write_json(output_dir / "r_poison1_pair_registry.json", pair_rows)
    write_csv(output_dir / "r_poison1_pair_registry.csv", pair_rows)
    write_csv(output_dir / "r_poison1_truth_prototype.csv", truth_rows)
    truth_parquet_status = write_parquet_or_note(
        output_dir / "r_poison1_truth_prototype.parquet", truth_frame
    )
    write_csv(output_dir / "r_poison1_pair_comparability_audit.csv", comparability_rows)
    write_csv(output_dir / "r_poison1_evidence_foreground_contract.csv", contract_rows)

    clean_base_validation_pass = all(
        bool(row["base_validation_validated"]) for row in pair_rows
    )
    fair_pair_contract_pass = all(
        bool(row["fair_pair_contract_pass"]) for row in comparability_rows
    )
    route_leak_skipped = "pair_route_leak_policy_poisoning_v01" in blocked_design_only
    summary = {
        "phase": "R-POISON-1",
        "status": "bounded_materialization_no_full_replay",
        "materialized_pair_count": len(pair_rows),
        "materialized_pairs": [row["pair_id"] for row in pair_rows],
        "truth_prototype_rows": len(truth_rows),
        "variant_contract_rows": len(contract_rows),
        "clean_base_validation_pass": clean_base_validation_pass,
        "fair_pair_contract_pass": fair_pair_contract_pass,
        "route_leak_policy_poisoning_skipped": route_leak_skipped,
        "blocked_design_only_pairs": blocked_design_only,
        "threat_models": sorted({row["threat_model"] for row in pair_rows}),
        "this_phase_full_replay": False,
        "this_phase_trained_learning": False,
        "this_phase_changed_foreground_policy": False,
        "adversarial_retention_claimed": False,
        "truth_parquet_status": truth_parquet_status,
        "base_validations": validations,
        "base_foregrounds": foregrounds,
        "allowed_claim": (
            "R-POISON-1 materializes bounded pair prototypes and contracts for "
            "feasible R-POISON-0 pairs."
        ),
        "forbidden_claims": [
            "Do not claim poisoning robustness before replay.",
            "Do not claim adversarial foreground retention before replay.",
            "Do not claim NO_EXPORT is attack truth.",
            "Do not count public-invisible variants as foreground misses.",
            "Do not treat AS-rel diagnostic as route-leak truth.",
        ],
        "recommended_next_step": (
            "R-POISON-2 bounded replay for the materialized feasible pairs"
            if clean_base_validation_pass and fair_pair_contract_pass
            else "repair R-POISON-1 pair contracts before replay"
        ),
    }
    write_json(output_dir / "r_poison1_summary.json", summary)
    write_report(output_dir / "r_poison1_report.md", summary, pair_rows)

    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
