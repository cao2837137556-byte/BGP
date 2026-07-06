#!/usr/bin/env python3
"""Audit R-POISON-2 retention reasons and signal ablations.

R-POISON-2 showed that the frozen online_path_pressure_v1 foreground policy
keeps four adversarial poisoning/evasion pairs but suppresses the
path-manipulation history-poisoning pair. This script answers the next
scientific question: why were the retained pairs retained, and are they robust
to removing individual strong evidence signals?

This phase is read-only. It does not change the foreground policy, does not run
full 6h replay, and does not train learning.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POISON2_ROOT = "outputs/r_poison_2/s2a_baseline_v01_pilot_6h_april16"
DEFAULT_POLICY_CONFIG = "configs/r_foreground3_online_policy_v1.json"
DEFAULT_OUTPUT_DIR = "outputs/r_poison_2a/s2a_baseline_v01_pilot_6h_april16"

ASSIGN_PROTECTED = "protected_foreground"
ASSIGN_GRAY = "gray_retained"
ASSIGN_SUPPRESSED = "operational_background_suppressed"


ABLATIONS = [
    {
        "ablation_id": "baseline_no_mask",
        "masked_signals": [],
        "purpose": "Current frozen foreground behavior.",
    },
    {
        "ablation_id": "mask_rpki_risk",
        "masked_signals": ["rpki_risk"],
        "purpose": "Test whether retention depends on RPKI invalidity.",
    },
    {
        "ablation_id": "mask_asrel_diagnostic",
        "masked_signals": ["asrel_diagnostic"],
        "purpose": "Test whether retention depends on AS-rel/path diagnostic.",
    },
    {
        "ablation_id": "mask_community_visibility",
        "masked_signals": ["community_visibility"],
        "purpose": "Test whether retention depends on NO_EXPORT/community flags.",
    },
    {
        "ablation_id": "mask_path_novelty",
        "masked_signals": ["path_novelty"],
        "purpose": "Test whether retention depends on prefix-origin-path rarity.",
    },
    {
        "ablation_id": "mask_low_visibility",
        "masked_signals": ["low_visibility"],
        "purpose": "Test whether retention depends on single-collector visibility.",
    },
    {
        "ablation_id": "mask_all_external_evidence",
        "masked_signals": ["rpki_risk", "asrel_diagnostic", "community_visibility"],
        "purpose": "Test whether retention survives without external evidence.",
    },
    {
        "ablation_id": "mask_external_and_path_novelty",
        "masked_signals": [
            "rpki_risk",
            "asrel_diagnostic",
            "community_visibility",
            "path_novelty",
        ],
        "purpose": "Stress test the foreground policy when external evidence and novelty are both unavailable.",
    },
]


FAMILY_CONTRACTS = {
    "origin_hijack": {
        "expected_signals": ["rpki_risk", "path_novelty"],
        "note": "Origin-family retention should not rely only on RPKI invalidity; origin/history shift remains needed for RPKI-valid cases.",
    },
    "forged_origin_hijack": {
        "expected_signals": ["asrel_diagnostic", "path_novelty"],
        "note": "Forged-origin cases may be RPKI-valid, so path/history semantics are central.",
    },
    "path_manipulation_like": {
        "expected_signals": ["path_novelty", "path_memory_poisoning_guard"],
        "note": "History poisoning can wash out novelty; a recent-crafted-history guard is required.",
    },
    "subprefix_origin_hijack": {
        "expected_signals": ["rpki_risk", "path_novelty", "community_visibility", "low_visibility"],
        "note": "Subprefix retention should preserve origin/subprefix risk and visibility-evasion evidence without calling NO_EXPORT attack truth.",
    },
    "stealth_evasion_like": {
        "expected_signals": ["community_visibility", "low_visibility"],
        "note": "Stealth retention should treat NO_EXPORT/collector asymmetry as observability evidence, not attack truth.",
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--poison2-root", default=DEFAULT_POISON2_ROOT)
    parser.add_argument("--policy-config", default=DEFAULT_POLICY_CONFIG)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def resolve_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def read_json(path_like: str | Path) -> dict[str, Any]:
    with resolve_path(path_like).open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path_like}")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
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


def prepare_output_dir(path: Path, overwrite: bool) -> None:
    if path.exists() and any(path.iterdir()):
        if not overwrite:
            raise FileExistsError(f"output directory not empty; pass --overwrite: {path}")
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def risk_sets(policy: dict[str, Any]) -> tuple[set[str], set[str], set[str]]:
    risk = policy.get("risk_values", {})
    return (
        set(map(str, risk.get("rpki_statuses", []))),
        set(map(str, risk.get("asrel_diagnostics", []))),
        set(map(str, risk.get("community_flags", []))),
    )


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return text in {"true", "1", "yes", "y"}


def apply_masks(row: dict[str, Any], masked_signals: list[str], policy: dict[str, Any]) -> dict[str, Any]:
    masked = dict(row)
    params = policy.get("policy_parameters", {})
    suppress_po_min = int(params.get("suppress_prefix_origin_min", 2))
    suppress_pop_min = int(params.get("suppress_prefix_origin_path_min", 2))

    if "rpki_risk" in masked_signals:
        masked["rpki_status"] = "valid"
    if "asrel_diagnostic" in masked_signals:
        masked["path_relation_diagnostic_2024"] = "all_pairs_known_no_valley_diagnostic"
    if "community_visibility" in masked_signals:
        masked["has_no_export"] = False
        masked["has_no_advertise"] = False
        masked["has_nopeer"] = False
        masked["community_evidence_state"] = "masked_for_ablation"
    if "path_novelty" in masked_signals:
        masked["prefix_origin_event_count"] = max(
            int(float(masked.get("prefix_origin_event_count", 0) or 0)),
            suppress_po_min,
        )
        masked["prefix_origin_path_event_count"] = max(
            int(float(masked.get("prefix_origin_path_event_count", 0) or 0)),
            suppress_pop_min,
        )
        masked["path_signature_event_count"] = max(
            int(float(masked.get("path_signature_event_count", 0) or 0)),
            suppress_pop_min,
        )
    if "low_visibility" in masked_signals:
        masked["collector_count"] = max(int(float(masked.get("collector_count", 0) or 0)), 2)
        masked["public_collector_visibility_drop"] = 0.0
    return masked


def assign_row(row: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    rpki_risk, asrel_risk, community_flags = risk_sets(policy)
    params = policy.get("policy_parameters", {})
    thresholds = policy.get("feature_thresholds", {})

    rare_path_max = int(params.get("rare_prefix_origin_path_protect_max", 1))
    suppress_po_min = int(params.get("suppress_prefix_origin_min", 2))
    suppress_pop_min = int(params.get("suppress_prefix_origin_path_min", 2))
    low_visibility_max = int(thresholds.get("low_visibility_collector_count", 1))

    rpki_signal = str(row.get("rpki_status", "")) in rpki_risk
    asrel_signal = str(row.get("path_relation_diagnostic_2024", "")) in asrel_risk
    community_signal = any(
        [
            as_bool(row.get("has_no_export")) and "has_no_export" in community_flags,
            as_bool(row.get("has_no_advertise")) and "has_no_advertise" in community_flags,
            as_bool(row.get("has_nopeer")) and "has_nopeer" in community_flags,
        ]
    )
    external_risk_signal = bool(rpki_signal or asrel_signal or community_signal)
    low_visibility = int(float(row.get("collector_count", 0) or 0)) <= low_visibility_max
    pop_count = int(float(row.get("prefix_origin_path_event_count", 0) or 0))
    po_count = int(float(row.get("prefix_origin_event_count", 0) or 0))
    rare_prefix_origin_path = pop_count <= rare_path_max
    evidence_unavailable = str(row.get("rpki_status")) == "missing" and str(
        row.get("path_relation_diagnostic_2024")
    ) == "missing"

    protected = external_risk_signal or rare_prefix_origin_path or (
        low_visibility and external_risk_signal
    )
    suppressed = (
        not protected
        and not evidence_unavailable
        and po_count >= suppress_po_min
        and pop_count >= suppress_pop_min
    )

    signal_set = []
    if rpki_signal:
        signal_set.append("rpki_risk")
    if asrel_signal:
        signal_set.append("asrel_diagnostic")
    if community_signal:
        signal_set.append("community_visibility")
    if rare_prefix_origin_path:
        signal_set.append("path_novelty")
    if low_visibility and external_risk_signal:
        signal_set.append("low_visibility_external")

    if protected:
        assignment = ASSIGN_PROTECTED
        reason = "external_or_rare_path_signal"
    elif suppressed:
        assignment = ASSIGN_SUPPRESSED
        reason = "recurrent_without_unmasked_external_or_novelty_signal"
    else:
        assignment = ASSIGN_GRAY
        reason = "insufficient_for_safe_suppression"

    return {
        "assignment": assignment,
        "retained": assignment != ASSIGN_SUPPRESSED,
        "reason": reason,
        "policy_signal_set": "|".join(signal_set) if signal_set else "none",
        "rpki_risk_signal": rpki_signal,
        "asrel_risk_signal": asrel_signal,
        "community_risk_signal": community_signal,
        "external_risk_signal": external_risk_signal,
        "low_visibility": low_visibility,
        "rare_prefix_origin_path": rare_prefix_origin_path,
    }


def family_contract(family: str) -> dict[str, Any]:
    return FAMILY_CONTRACTS.get(
        family,
        {
            "expected_signals": [],
            "note": "No family-specific contract is registered for this family.",
        },
    )


def split_signal_set(value: str) -> set[str]:
    if not value or value == "none":
        return set()
    return {part for part in str(value).split("|") if part}


def retention_reason_rows(events: pd.DataFrame, policy: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in events.to_dict("records"):
        assignment = assign_row(row, policy)
        family = str(row["family"])
        contract = family_contract(family)
        expected = set(contract["expected_signals"])
        current_signals = split_signal_set(assignment["policy_signal_set"])
        expected_supported = sorted(current_signals & expected)
        incidental = sorted(current_signals - expected)

        if assignment["assignment"] == ASSIGN_SUPPRESSED:
            interpretation = "current_foreground_failure"
        elif expected_supported:
            interpretation = "retained_by_family_relevant_signal"
        elif incidental:
            interpretation = "retained_by_incidental_strong_signal"
        else:
            interpretation = "retained_but_reason_needs_manual_check"

        rows.append(
            {
                "pair_id": row["pair_id"],
                "variant_role": row["variant_role"],
                "family": family,
                "threat_model": row["threat_model"],
                "adversarial_variant": row["adversarial_variant"],
                "current_assignment": assignment["assignment"],
                "current_retained": assignment["retained"],
                "current_policy_signal_set": assignment["policy_signal_set"],
                "family_expected_signal_set": "|".join(contract["expected_signals"]),
                "family_relevant_supported_signal_set": "|".join(expected_supported)
                if expected_supported
                else "none",
                "incidental_strong_signal_set": "|".join(incidental) if incidental else "none",
                "retention_interpretation": interpretation,
                "knowledge_base_drift_score": row.get("knowledge_base_drift_score", 0),
                "novelty_signal_drop": row.get("novelty_signal_drop", 0),
                "allowed_claim": "foreground retention reason identified, not attack truth",
                "forbidden_claim": "do not claim retained pair proves poisoning robustness",
                "notes": contract["note"],
            }
        )
    return rows


def ablation_rows(events: pd.DataFrame, policy: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in events.to_dict("records"):
        baseline = assign_row(row, policy)
        for ablation in ABLATIONS:
            masked = apply_masks(row, ablation["masked_signals"], policy)
            assigned = assign_row(masked, policy)
            rows.append(
                {
                    "pair_id": row["pair_id"],
                    "variant_role": row["variant_role"],
                    "family": row["family"],
                    "threat_model": row["threat_model"],
                    "adversarial_variant": row["adversarial_variant"],
                    "ablation_id": ablation["ablation_id"],
                    "masked_signals": "|".join(ablation["masked_signals"])
                    if ablation["masked_signals"]
                    else "none",
                    "attack_event_count": int(float(row.get("attack_event_count", 0) or 0)),
                    "assignment": assigned["assignment"],
                    "retained": assigned["retained"],
                    "policy_signal_set_after_ablation": assigned["policy_signal_set"],
                    "assignment_changed_from_baseline": assigned["assignment"]
                    != baseline["assignment"],
                    "retention_changed_from_baseline": assigned["retained"]
                    != baseline["retained"],
                    "ablation_purpose": ablation["purpose"],
                }
            )
    return rows


def pair_ablation_rows(ablation: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    group_cols = ["pair_id", "variant_role", "family", "threat_model", "ablation_id"]
    for keys, group in ablation.groupby(group_cols, sort=False):
        pair_id, variant_role, family, threat_model, ablation_id = keys
        total = int(group["attack_event_count"].sum())
        retained = int(group.loc[group["retained"], "attack_event_count"].sum())
        rows.append(
            {
                "pair_id": pair_id,
                "variant_role": variant_role,
                "family": family,
                "threat_model": threat_model,
                "ablation_id": ablation_id,
                "attack_event_count": total,
                "retained_attack_event_count": retained,
                "retention_rate": retained / total if total else None,
                "assignment_set": "|".join(sorted(set(map(str, group["assignment"])))),
            }
        )
    return rows


def fragility_rows(pair_ablation: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    adv = pair_ablation[pair_ablation["variant_role"].eq("adversarial")].copy()
    single_signal_ablation_ids = {
        item["ablation_id"]
        for item in ABLATIONS
        if len(item["masked_signals"]) == 1
    }
    for pair_id, group in adv.groupby("pair_id", sort=False):
        base = group[group["ablation_id"].eq("baseline_no_mask")]
        if base.empty:
            continue
        baseline_rate = float(base["retention_rate"].iloc[0])
        drops = group[
            group["ablation_id"].ne("baseline_no_mask")
            & (pd.to_numeric(group["retention_rate"], errors="coerce") < baseline_rate)
        ].copy()
        zeroed = group[
            group["ablation_id"].ne("baseline_no_mask")
            & (pd.to_numeric(group["retention_rate"], errors="coerce") <= 0)
        ].copy()
        single_drop = drops[drops["ablation_id"].isin(single_signal_ablation_ids)]
        single_zero = zeroed[zeroed["ablation_id"].isin(single_signal_ablation_ids)]
        combined_drop = drops[~drops["ablation_id"].isin(single_signal_ablation_ids)]
        combined_zero = zeroed[~zeroed["ablation_id"].isin(single_signal_ablation_ids)]
        family = str(group["family"].iloc[0])
        threat_model = str(group["threat_model"].iloc[0])
        if baseline_rate <= 0:
            status = "current_failure_needs_repair"
            next_action = "repair path-memory poisoning guard before larger replay"
        elif len(single_zero):
            status = "retained_but_single_signal_fragile"
            next_action = "write must-keep contract and add secondary guards before claiming robustness"
        elif len(single_drop):
            status = "retained_but_single_signal_sensitive"
            next_action = "document dependency and test stronger adversarial variants"
        elif len(combined_zero):
            status = "retained_under_single_signal_ablation_but_combined_stress_fragile"
            next_action = "document current protection bundle and test stronger paired variants"
        elif len(combined_drop):
            status = "retained_under_single_signal_ablation_but_combined_stress_sensitive"
            next_action = "document current protection bundle and test stronger paired variants"
        else:
            status = "retained_under_single_signal_ablation"
            next_action = "keep in benchmark; later test stronger paired variants"

        rows.append(
            {
                "pair_id": pair_id,
                "family": family,
                "threat_model": threat_model,
                "baseline_adversarial_retention": baseline_rate,
                "minimum_ablation_retention": float(
                    pd.to_numeric(group["retention_rate"], errors="coerce").min()
                ),
                "ablation_ids_with_retention_drop": "|".join(drops["ablation_id"].tolist())
                if len(drops)
                else "none",
                "ablation_ids_with_zero_retention": "|".join(zeroed["ablation_id"].tolist())
                if len(zeroed)
                else "none",
                "single_signal_ablation_ids_with_drop": "|".join(
                    single_drop["ablation_id"].tolist()
                )
                if len(single_drop)
                else "none",
                "single_signal_ablation_ids_with_zero_retention": "|".join(
                    single_zero["ablation_id"].tolist()
                )
                if len(single_zero)
                else "none",
                "combined_stress_ablation_ids_with_drop": "|".join(
                    combined_drop["ablation_id"].tolist()
                )
                if len(combined_drop)
                else "none",
                "combined_stress_ablation_ids_with_zero_retention": "|".join(
                    combined_zero["ablation_id"].tolist()
                )
                if len(combined_zero)
                else "none",
                "fragility_status": status,
                "recommended_next_action": next_action,
            }
        )
    return rows


def repair_design_rows(fragility: list[dict[str, Any]]) -> list[dict[str, Any]]:
    path_failed = any(
        row["pair_id"] == "pair_path_manipulation_history_poisoning_v01"
        and row["fragility_status"] == "current_failure_needs_repair"
        for row in fragility
    )
    rows = [
        {
            "repair_item": "path_memory_poisoning_guard",
            "priority": "P0" if path_failed else "P1",
            "target_failure_mode": "history poisoning washes out path novelty and makes a suspicious path look recurrent",
            "policy_feature_needed": "path_age_or_first_seen_delta; pre_attack_path_burst; long_term_vs_recent_recurrence split; path_signature_stability window",
            "allowed_claim": "short-lived recurrence is not the same as long-term benign history",
            "forbidden_claim": "path manipulation attack truth from recurrence alone",
            "compression_risk": "low-to-medium if restricted to recent-crafted-history patterns",
            "next_phase": "R-FOREGROUND-4",
        },
        {
            "repair_item": "origin_family_secondary_guard",
            "priority": "P1",
            "target_failure_mode": "origin-family pairs are currently retained by RPKI/AS-rel or novelty; stronger variants may remove one of these signals",
            "policy_feature_needed": "prefix-origin age; origin history drift; new-origin burst; RPKI-valid-but-history-inconsistent indicator",
            "allowed_claim": "RPKI valid is not benign and origin-history drift can remain foreground evidence",
            "forbidden_claim": "RPKI invalid is attack truth",
            "compression_risk": "medium if applied broadly; must be bounded by rarity/age windows",
            "next_phase": "future R-FOREGROUND repair after P0 path guard",
        },
        {
            "repair_item": "visibility_evasion_contract",
            "priority": "P1",
            "target_failure_mode": "NO_EXPORT/low-visibility cases are retained now, but public-invisible cases need observability-boundary accounting",
            "policy_feature_needed": "collector visibility denominator; NO_EXPORT provenance; collector asymmetry; visible-vs-public-invisible flag",
            "allowed_claim": "NO_EXPORT and low visibility are visibility-evasion evidence",
            "forbidden_claim": "NO_EXPORT present is attack truth or NO_EXPORT absent is safe",
            "compression_risk": "low if limited to positive well-known-community or explicit asymmetry evidence",
            "next_phase": "after path-memory guard and before larger evasion replay",
        },
        {
            "repair_item": "compression_after_repair",
            "priority": "P2",
            "target_failure_mode": "foreground still needs stronger background compression after adversarial retention is repaired",
            "policy_feature_needed": "stable long-term recurrence; evidence-clean background denominator; hard-negative offline-pool split",
            "allowed_claim": "online suppression reduces workload, not benign truth",
            "forbidden_claim": "suppressed background is benign or training negative",
            "compression_risk": "managed by attack/adversarial retention stop-loss gates",
            "next_phase": "R-FOREGROUND-4 full policy smoke after repair audit",
        },
    ]
    return rows


def write_report(
    path: Path,
    summary: dict[str, Any],
    retention_rows_data: list[dict[str, Any]],
    fragility_rows_data: list[dict[str, Any]],
    repair_rows_data: list[dict[str, Any]],
) -> None:
    lines = [
        "# R-POISON-2A Retention Reason and Ablation Audit",
        "",
        "Status: read-only audit; no foreground policy change.",
        "",
        "## Summary",
        "",
        f"- pair count: `{summary['pair_count']}`",
        f"- adversarial pairs currently retained: `{summary['adversarial_pairs_currently_retained']}`",
        f"- adversarial pairs currently suppressed: `{summary['adversarial_pairs_currently_suppressed']}`",
        f"- single-signal fragile retained adversarial pairs: `{summary['single_signal_fragile_retained_adversarial_pairs']}`",
        f"- combined-stress fragile retained adversarial pairs: `{summary['combined_stress_fragile_retained_adversarial_pairs']}`",
        f"- current failure pairs: `{', '.join(summary['current_failure_pairs']) or 'none'}`",
        f"- recommended next step: `{summary['recommended_next_step']}`",
        "",
        "## Retention Reason Audit",
        "",
        "| Pair | Variant | Family | Assignment | Policy signals | Interpretation |",
        "|---|---|---|---|---|---|",
    ]
    for row in retention_rows_data:
        if row["variant_role"] != "adversarial":
            continue
        lines.append(
            f"| `{row['pair_id']}` | `{row['variant_role']}` | `{row['family']}` | "
            f"`{row['current_assignment']}` | `{row['current_policy_signal_set']}` | "
            f"`{row['retention_interpretation']}` |"
        )
    lines.extend(
        [
            "",
            "## Fragility Audit",
            "",
            "| Pair | Baseline adversarial retention | Minimum ablation retention | Fragility status | Critical ablations |",
            "|---|---:|---:|---|---|",
        ]
    )
    for row in fragility_rows_data:
        lines.append(
            f"| `{row['pair_id']}` | `{row['baseline_adversarial_retention']}` | "
            f"`{row['minimum_ablation_retention']}` | `{row['fragility_status']}` | "
            f"`{row['ablation_ids_with_zero_retention']}` |"
        )
    lines.extend(
        [
            "",
            "## Repair Design",
            "",
            "| Item | Priority | Next phase | Core idea |",
            "|---|---|---|---|",
        ]
    )
    for row in repair_rows_data:
        lines.append(
            f"| `{row['repair_item']}` | `{row['priority']}` | `{row['next_phase']}` | "
            f"{row['allowed_claim']} |"
        )
    lines.extend(
        [
            "",
            "## Boundaries",
            "",
            "- This audit does not prove poisoning robustness.",
            "- This audit does not train learning.",
            "- This audit does not change `online_path_pressure_v1`.",
            "- RPKI invalid, AS-rel diagnostic, and NO_EXPORT remain evidence or diagnostics, not attack truth.",
            "- Suppressed operational background is not benign and is not a training negative.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    poison2_root = resolve_path(args.poison2_root)
    output_dir = resolve_path(args.output_dir)
    prepare_output_dir(output_dir, args.overwrite)

    policy = read_json(args.policy_config)
    events_path = poison2_root / "r_poison2_bounded_replay_events.csv"
    metrics_path = poison2_root / "r_poison2_pair_metrics.csv"
    if not events_path.exists():
        raise FileNotFoundError(events_path)
    if not metrics_path.exists():
        raise FileNotFoundError(metrics_path)

    events = pd.read_csv(events_path)
    metrics = pd.read_csv(metrics_path)

    retention = retention_reason_rows(events, policy)
    ablation = ablation_rows(events, policy)
    pair_ablation = pair_ablation_rows(pd.DataFrame(ablation))
    fragility = fragility_rows(pd.DataFrame(pair_ablation))
    repair = repair_design_rows(fragility)

    write_csv(output_dir / "r_poison2a_retention_reason_audit.csv", retention)
    write_csv(output_dir / "r_poison2a_signal_ablation_audit.csv", ablation)
    write_csv(output_dir / "r_poison2a_pair_ablation_summary.csv", pair_ablation)
    write_csv(output_dir / "r_poison2a_pair_fragility_audit.csv", fragility)
    write_csv(output_dir / "r_poison2a_foreground_repair_design.csv", repair)

    fragility_df = pd.DataFrame(fragility)
    current_failures = fragility_df.loc[
        fragility_df["fragility_status"].eq("current_failure_needs_repair"),
        "pair_id",
    ].tolist()
    fragile_retained = fragility_df.loc[
        fragility_df["fragility_status"].isin(
            ["retained_but_single_signal_fragile", "retained_but_single_signal_sensitive"]
        ),
        "pair_id",
    ].tolist()
    combined_stress_fragile = fragility_df.loc[
        fragility_df["fragility_status"].isin(
            [
                "retained_under_single_signal_ablation_but_combined_stress_fragile",
                "retained_under_single_signal_ablation_but_combined_stress_sensitive",
            ]
        ),
        "pair_id",
    ].tolist()
    current_retained = metrics[
        pd.to_numeric(metrics["poisoned_or_evasive_attack_retention"], errors="coerce") > 0
    ]
    current_suppressed = metrics[
        pd.to_numeric(metrics["poisoned_or_evasive_attack_retention"], errors="coerce") <= 0
    ]

    summary = {
        "phase": "R-POISON-2A",
        "status": "retention_reason_and_signal_ablation_audit",
        "pair_count": int(metrics["pair_id"].nunique()),
        "event_rows": int(len(events)),
        "ablation_event_rows": int(len(ablation)),
        "adversarial_pairs_currently_retained": int(len(current_retained)),
        "adversarial_pairs_currently_suppressed": int(len(current_suppressed)),
        "current_failure_pairs": current_failures,
        "single_signal_fragile_retained_adversarial_pairs": fragile_retained,
        "combined_stress_fragile_retained_adversarial_pairs": combined_stress_fragile,
        "path_memory_poisoning_guard_required": "pair_path_manipulation_history_poisoning_v01"
        in current_failures,
        "this_phase_changed_foreground_policy": False,
        "this_phase_full_6h_replay": False,
        "this_phase_trained_learning": False,
        "allowed_claim": (
            "R-POISON-2A explains foreground retention reasons and tests "
            "counterfactual signal dependence for bounded R-POISON-2 pairs."
        ),
        "forbidden_claims": [
            "Do not claim retained pairs prove poisoning robustness.",
            "Do not claim ablated signals are attack truth.",
            "Do not treat NO_EXPORT, RPKI, or AS-rel as labels.",
            "Do not claim suppressed background is benign.",
        ],
        "recommended_next_step": (
            "R-FOREGROUND-4 targeted path-memory poisoning guard, then rerun "
            "foreground safety/compression gates before learning or larger replay."
        ),
    }
    write_json(output_dir / "r_poison2a_summary.json", summary)
    write_report(
        output_dir / "r_poison2a_report.md",
        summary,
        retention,
        fragility,
        repair,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
