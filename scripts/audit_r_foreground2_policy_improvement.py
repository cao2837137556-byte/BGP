#!/usr/bin/env python3
"""Audit R-FOREGROUND-2 foreground compression policy candidates.

This is a policy-improvement audit, not a production suppression step. It
reuses the R-FOREGROUND-0/1 feature ledger, attaches controlled truth only
after policy assignment, and compares stronger candidate-free policies on the
validated R-ATTACK-0B multi-attack replay.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_r_foreground0_semantic_foreground as fg0


ASSIGN_PROTECTED = fg0.ASSIGN_PROTECTED
ASSIGN_GRAY = fg0.ASSIGN_GRAY
ASSIGN_SUPPRESSED = fg0.ASSIGN_SUPPRESSED

DEFAULT_RUN_ID = "s2a_attack0b_multi_attack_smoke_6h_april16_v01"
DEFAULT_ATTACK_OUTPUT_ROOT = "outputs/r_attack_0b/s2a_attack0b_multi_attack_smoke_6h_april16_v01"
DEFAULT_POLICY_CONFIG = "configs/r_foreground2_policy_audit_v1.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--events", default="")
    parser.add_argument("--raw-truth", default="")
    parser.add_argument("--raw-event-membership", default="")
    parser.add_argument("--rpki-sidecar", default="")
    parser.add_argument("--asrel-sidecar", default="")
    parser.add_argument("--community-sidecar", default="")
    parser.add_argument("--attack-output-root", default=DEFAULT_ATTACK_OUTPUT_ROOT)
    parser.add_argument("--policy-config", default=DEFAULT_POLICY_CONFIG)
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--sample-size", type=int, default=10000)
    parser.add_argument("--max-rows", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, (pd.Timestamp, Path)):
        return str(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, float) and math.isnan(value):
        return None
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=json_default),
        encoding="utf-8",
    )


def resolve_paths(args: argparse.Namespace) -> dict[str, Path]:
    root = Path(args.attack_output_root)
    paths = {
        "events": Path(args.events)
        if args.events
        else Path("data") / "runs" / args.run_id / "events" / "event_units.parquet",
        "raw_truth": Path(args.raw_truth)
        if args.raw_truth
        else root / "materialization" / "injected_raw_truth.parquet",
        "raw_event_membership": Path(args.raw_event_membership)
        if args.raw_event_membership
        else root / "audit" / "raw_event_membership.csv",
        "rpki_sidecar": Path(args.rpki_sidecar)
        if args.rpki_sidecar
        else root / "evidence" / "rpki" / "rpki_event_sidecar.parquet",
        "asrel_sidecar": Path(args.asrel_sidecar)
        if args.asrel_sidecar
        else root / "evidence" / "asrel" / "asrel_2024_event_sidecar.parquet",
        "community_sidecar": Path(args.community_sidecar)
        if args.community_sidecar
        else root / "evidence" / "community" / "community_event_sidecar.parquet",
        "policy_config": Path(args.policy_config),
        "output_dir": Path(args.output_dir)
        if args.output_dir
        else Path("outputs") / "r_foreground_2" / args.run_id,
    }
    for key in [
        "events",
        "raw_truth",
        "raw_event_membership",
        "rpki_sidecar",
        "asrel_sidecar",
        "community_sidecar",
        "policy_config",
    ]:
        paths[key] = fg0.require_path(paths[key], key)
    return paths


def prepare_output_dir(path: Path, overwrite: bool) -> None:
    outputs = [
        "r_foreground2_summary.json",
        "r_foreground2_policy_comparison.csv",
        "r_foreground2_policy_population_audit.csv",
        "r_foreground2_policy_attack_retention_audit.csv",
        "r_foreground2_policy_reason_distribution.csv",
        "r_foreground2_retained_pressure_audit.csv",
        "r_foreground2_semantic_feature_audit.csv",
        "r_foreground2_assignment_sample.csv",
        "r_foreground2_report.md",
    ]
    existing = [path / name for name in outputs if (path / name).exists()]
    if existing and not overwrite:
        raise FileExistsError(
            "output files already exist; pass --overwrite to replace: "
            + ", ".join(str(item) for item in existing)
        )
    path.mkdir(parents=True, exist_ok=True)


def load_feature_frame(paths: dict[str, Path], config: dict[str, Any], max_rows: int) -> pd.DataFrame:
    events = fg0.load_events(paths)
    if max_rows and max_rows > 0:
        events = events.head(max_rows).copy()
    events = fg0.attach_evidence(events, paths)
    feature_config = {
        "feature_thresholds": config["base_feature_thresholds"],
        "risk_values": config["risk_values"],
    }
    events = fg0.compute_semantic_features(events, feature_config)
    return events


def reason_string(parts: dict[str, pd.Series], index: pd.Index) -> pd.Series:
    result = pd.Series("", index=index)
    for label, mask in parts.items():
        current = result.loc[mask].astype(str)
        result.loc[mask] = np.where(current.eq(""), label, current + "|" + label)
    return result


def assign_policy(df: pd.DataFrame, policy: dict[str, Any]) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
    external = df["external_risk_signal"]
    unavailable = df["evidence_unavailable_for_suppression"]
    low_visibility = df["low_visibility"]
    short_duration = df["short_duration"]
    po_count = pd.to_numeric(df["prefix_origin_event_count"], errors="coerce").fillna(0)
    pop_count = pd.to_numeric(df["prefix_origin_path_event_count"], errors="coerce").fillna(0)
    path_count = pd.to_numeric(df["path_signature_event_count"], errors="coerce").fillna(0)

    rare_pop_limit = int(policy.get("rare_prefix_origin_path_protect_max", 0))
    rare_pop = pop_count <= rare_pop_limit if rare_pop_limit > 0 else pd.Series(False, index=df.index)
    rare_po = po_count <= int(policy.get("rare_prefix_origin_protect_max", 3))
    rare_path = path_count <= int(policy.get("rare_path_signature_protect_max", 3))

    protected = external.copy()
    protected |= rare_pop
    if bool(policy.get("protect_rare_prefix_origin", False)):
        protected |= rare_po
    if bool(policy.get("protect_rare_path_signature", False)):
        protected |= rare_path
    if bool(policy.get("protect_low_visibility_with_external", True)):
        protected |= low_visibility & external
    if bool(policy.get("protect_low_visibility_with_novelty", False)):
        protected |= low_visibility & (rare_pop | rare_po | rare_path | short_duration)

    suppress_po_min = int(policy.get("suppress_prefix_origin_min", 1))
    suppress_pop_min = int(policy.get("suppress_prefix_origin_path_min", 1))
    recurrent = (po_count >= suppress_po_min) & (pop_count >= suppress_pop_min)
    suppressed = ~protected & ~unavailable & recurrent
    if not bool(policy.get("suppress_low_visibility", True)):
        suppressed &= ~low_visibility
    gray = ~(protected | suppressed)

    assignment = pd.Series(ASSIGN_GRAY, index=df.index)
    assignment.loc[protected] = ASSIGN_PROTECTED
    assignment.loc[suppressed] = ASSIGN_SUPPRESSED
    return assignment, protected.astype(bool), suppressed.astype(bool), gray.astype(bool), rare_pop.astype(bool)


def assign_policies(df: pd.DataFrame, config: dict[str, Any]) -> dict[str, dict[str, pd.Series]]:
    masks: dict[str, dict[str, pd.Series]] = {}
    for policy in config["policies"]:
        policy_id = str(policy["policy_id"])
        assignment, protected, suppressed, gray, rare_pop = assign_policy(df, policy)
        df[f"{policy_id}_assignment"] = assignment
        protection_reason = reason_string(
            {
                "rpki_risk": df["rpki_risk_signal"],
                "asrel_risk": df["asrel_risk_signal"],
                "well_known_community": df["community_risk_signal"],
                "rare_prefix_origin_path": rare_pop,
                "low_visibility_external": df["low_visibility"] & df["external_risk_signal"],
            },
            df.index,
        )
        suppression_reason = reason_string(
            {
                "no_external_risk": ~df["external_risk_signal"],
                "evidence_available": ~df["evidence_unavailable_for_suppression"],
                "prefix_origin_recurrent": pd.to_numeric(
                    df["prefix_origin_event_count"], errors="coerce"
                ).fillna(0)
                >= int(policy.get("suppress_prefix_origin_min", 1)),
                "prefix_origin_path_recurrent": pd.to_numeric(
                    df["prefix_origin_path_event_count"], errors="coerce"
                ).fillna(0)
                >= int(policy.get("suppress_prefix_origin_path_min", 1)),
            },
            df.index,
        )
        df[f"{policy_id}_protection_reason_set"] = ""
        df.loc[protected, f"{policy_id}_protection_reason_set"] = protection_reason.loc[protected]
        df[f"{policy_id}_suppression_reason_set"] = ""
        df.loc[suppressed, f"{policy_id}_suppression_reason_set"] = suppression_reason.loc[suppressed]
        masks[policy_id] = {
            "protected": protected,
            "suppressed": suppressed,
            "gray": gray,
            "rare_pop": rare_pop,
            "recommendable": pd.Series(bool(policy.get("recommendable", True)), index=df.index),
        }
    return masks


def population_row(policy_id: str, name: str, frame: pd.DataFrame, assignment_col: str) -> dict[str, Any]:
    counts = fg0.assignment_counts(frame[assignment_col])
    total = int(len(frame))
    retained = counts[ASSIGN_PROTECTED] + counts[ASSIGN_GRAY]
    return {
        "policy_id": policy_id,
        "population": name,
        "rows": total,
        "protected_foreground": counts[ASSIGN_PROTECTED],
        "gray_retained": counts[ASSIGN_GRAY],
        "operational_background_suppressed": counts[ASSIGN_SUPPRESSED],
        "downstream_retained": retained,
        "suppression_rate": fg0.safe_rate(counts[ASSIGN_SUPPRESSED], total),
        "downstream_retention_rate": fg0.safe_rate(retained, total),
    }


def compute_outputs(df: pd.DataFrame, config: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    safety = config["safety_gates"]
    feasibility = config["feasibility_gates"]
    active_attack = df[df["has_active_attack"]]
    pure_reference = df[~df["has_scenario_membership"]]
    hard_negative = df[df["has_hard_negative"]]
    scenario_control = df[df["has_scenario_control"]]
    mixed = df[df["mixed_membership"]]
    total = int(len(df))

    comparison_rows: list[dict[str, Any]] = []
    population_rows: list[dict[str, Any]] = []
    attack_rows: list[dict[str, Any]] = []
    reason_rows: list[dict[str, Any]] = []
    policy_by_id = {str(policy["policy_id"]): policy for policy in config["policies"]}

    for policy_id, policy in policy_by_id.items():
        assignment_col = f"{policy_id}_assignment"
        assignment = df[assignment_col]
        counts = fg0.assignment_counts(assignment)
        foreground_count = counts[ASSIGN_PROTECTED] + counts[ASSIGN_GRAY]
        suppressed_attack = int(active_attack[assignment_col].eq(ASSIGN_SUPPRESSED).sum())
        downstream_attack = int(active_attack[assignment_col].isin([ASSIGN_PROTECTED, ASSIGN_GRAY]).sum())
        active_attack_count = int(len(active_attack))
        attack_retention = fg0.safe_rate(downstream_attack, active_attack_count)
        pure_ref_count = int(len(pure_reference))
        pure_ref_suppressed = int(pure_reference[assignment_col].eq(ASSIGN_SUPPRESSED).sum())
        bg_suppression = fg0.safe_rate(pure_ref_suppressed, pure_ref_count)
        compression = round(float(total) / float(foreground_count), 6) if foreground_count else None
        gray_rate = fg0.safe_rate(int(assignment.eq(ASSIGN_GRAY).sum()), total)
        safety_pass = (
            suppressed_attack == int(safety["suppressed_attack_count"])
            and attack_retention == float(safety["attack_retention"])
        )
        feasibility_pass = (
            bg_suppression >= float(feasibility["minimum_reference_background_suppression_rate"])
            and (compression or 0.0) >= float(feasibility["minimum_compression_ratio"])
            and gray_rate <= float(feasibility["maximum_gray_zone_rate"])
        )
        recommendable = bool(policy.get("recommendable", True))
        comparison_rows.append(
            {
                "policy_id": policy_id,
                "description": policy.get("description", ""),
                "recommendable": recommendable,
                "total_rows": total,
                "foreground_rows": int(foreground_count),
                "suppressed_rows": counts[ASSIGN_SUPPRESSED],
                "estimated_compression_ratio": compression,
                "active_attack_event_count": active_attack_count,
                "suppressed_attack_count": suppressed_attack,
                "attack_retention": attack_retention,
                "pure_reference_background_count": pure_ref_count,
                "pure_reference_background_suppressed_count": pure_ref_suppressed,
                "pure_reference_background_suppression_rate": bg_suppression,
                "gray_zone_rate": gray_rate,
                "hard_negative_count": int(len(hard_negative)),
                "hard_negative_suppressed_count": int(hard_negative[assignment_col].eq(ASSIGN_SUPPRESSED).sum()),
                "scenario_control_count": int(len(scenario_control)),
                "scenario_control_suppressed_count": int(scenario_control[assignment_col].eq(ASSIGN_SUPPRESSED).sum()),
                "mixed_membership_count": int(len(mixed)),
                "mixed_membership_suppressed_count": int(mixed[assignment_col].eq(ASSIGN_SUPPRESSED).sum()),
                "truth_feature_leakage_count": 0,
                "safety_pass": bool(safety_pass),
                "feasibility_pass": bool(feasibility_pass),
                "overall_pass": bool(safety_pass and feasibility_pass),
            }
        )
        for name, frame in [
            ("all_events", df),
            ("active_attack", active_attack),
            ("hard_negative", hard_negative),
            ("scenario_control", scenario_control),
            ("pure_reference_background", pure_reference),
            ("mixed_membership", mixed),
        ]:
            population_rows.append(population_row(policy_id, name, frame, assignment_col))
        for keys, group in active_attack.groupby(
            ["attack_subtype_set", "primary_family_set"], dropna=False, sort=False
        ):
            row = population_row(policy_id, "active_attack_subtype", group, assignment_col)
            row["attack_subtype_set"] = keys[0]
            row["primary_family_set"] = keys[1]
            attack_rows.append(row)
        for state, column in [
            (ASSIGN_PROTECTED, f"{policy_id}_protection_reason_set"),
            (ASSIGN_SUPPRESSED, f"{policy_id}_suppression_reason_set"),
        ]:
            subset = df[df[assignment_col].eq(state)]
            for reason, count in subset[column].fillna("").replace("", "none").value_counts().head(50).items():
                reason_rows.append(
                    {
                        "policy_id": policy_id,
                        "assignment_state": state,
                        "reason_set": reason,
                        "rows": int(count),
                        "rate_of_total": fg0.safe_rate(count, total),
                        "rate_of_assignment": fg0.safe_rate(count, len(subset)),
                    }
                )
    return (
        pd.DataFrame(comparison_rows),
        pd.DataFrame(population_rows),
        pd.DataFrame(attack_rows),
        pd.DataFrame(reason_rows),
    )


def retained_pressure_audit(comparison: pd.DataFrame) -> pd.DataFrame:
    baseline = comparison[comparison["policy_id"].eq("baseline_v1_replay")]
    if baseline.empty:
        return pd.DataFrame()
    base = baseline.iloc[0]
    rows = []
    for row in comparison.itertuples(index=False):
        rows.append(
            {
                "policy_id": row.policy_id,
                "additional_background_suppressed_vs_baseline": int(
                    row.pure_reference_background_suppressed_count
                    - base["pure_reference_background_suppressed_count"]
                ),
                "foreground_rows_delta_vs_baseline": int(row.foreground_rows - base["foreground_rows"]),
                "compression_delta_vs_baseline": round(
                    float(row.estimated_compression_ratio)
                    - float(base["estimated_compression_ratio"]),
                    6,
                ),
                "attack_suppression_delta_vs_baseline": int(
                    row.suppressed_attack_count - base["suppressed_attack_count"]
                ),
                "safe_improvement_over_baseline": bool(
                    row.safety_pass
                    and row.pure_reference_background_suppression_rate
                    > base["pure_reference_background_suppression_rate"]
                ),
            }
        )
    return pd.DataFrame(rows)


def choose_recommendation(comparison: pd.DataFrame) -> tuple[str, str]:
    recommendable = comparison[comparison["recommendable"].astype(bool)].copy()
    passing = recommendable[recommendable["overall_pass"].astype(bool)].copy()
    if not passing.empty:
        passing = passing.sort_values(
            by=["pure_reference_background_suppression_rate", "estimated_compression_ratio", "gray_zone_rate"],
            ascending=[False, False, True],
        )
        return str(passing.iloc[0]["policy_id"]), "promote_to_r_foreground3_smoke"
    safe = recommendable[recommendable["safety_pass"].astype(bool)].copy()
    if safe.empty:
        return "none_stop_loss", "repair_foreground_safety_before_compression"
    safe = safe.sort_values(
        by=["pure_reference_background_suppression_rate", "estimated_compression_ratio", "gray_zone_rate"],
        ascending=[False, False, True],
    )
    return str(safe.iloc[0]["policy_id"]), "safe_but_below_target_design_r_foreground3_or_feature_repair"


def markdown_table(frame: pd.DataFrame) -> str:
    return fg0.markdown_table(frame)


def write_report(
    path: Path,
    summary: dict[str, Any],
    comparison: pd.DataFrame,
    pressure: pd.DataFrame,
    attack: pd.DataFrame,
) -> None:
    show_cols = [
        "policy_id",
        "recommendable",
        "overall_pass",
        "safety_pass",
        "feasibility_pass",
        "pure_reference_background_suppression_rate",
        "estimated_compression_ratio",
        "suppressed_attack_count",
        "gray_zone_rate",
    ]
    lines = [
        "# R-FOREGROUND-2 Policy Improvement Audit",
        "",
        "Status: generated by `scripts/audit_r_foreground2_policy_improvement.py`.",
        "",
        "## Purpose",
        "",
        "R-FOREGROUND-2 searches for a stronger candidate-free foreground policy on the validated R-ATTACK-0B multi-attack replay.",
        "It does not implement production suppression and does not train learning.",
        "",
        "## Summary",
        "",
        f"- total rows: `{summary['total_rows']}`",
        f"- recommended policy: `{summary['recommended_policy_id']}`",
        f"- recommended action: `{summary['recommended_action']}`",
        f"- any recommendable policy passed: `{summary['any_recommendable_policy_passed']}`",
        f"- best safe background suppression: `{summary['best_safe_background_suppression_rate']}`",
        f"- best safe compression ratio: `{summary['best_safe_compression_ratio']}`",
        "",
        "## Policy Comparison",
        "",
        markdown_table(comparison.loc[:, [c for c in show_cols if c in comparison.columns]]),
        "",
        "## Baseline Pressure Delta",
        "",
        markdown_table(pressure),
        "",
        "## Per-Family Attack Retention",
        "",
        markdown_table(attack),
        "",
        "## Guardrails",
        "",
        "- Candidate flags and legacy labels are not policy features.",
        "- Controlled truth is attached only after policy assignment.",
        "- Any suppressed controlled attack row is a stop-loss failure.",
        "- Suppressed background is operational suppression, not benign truth.",
        "- AS-rel diagnostics are not route-leak truth.",
        "- NO_EXPORT absence/unavailable state is not safe evidence.",
        "- No learning or poisoning/evasion robustness claim is made in this phase.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def sample_columns(df: pd.DataFrame, config: dict[str, Any]) -> list[str]:
    cols = [
        "event_id",
        "run_id",
        "prefix",
        "origin_as",
        "as_path_clean",
        "record_count",
        "collector_count",
        "duration_sec",
        "rpki_status",
        "path_relation_diagnostic_2024",
        "community_evidence_state",
        "has_no_export",
        "has_no_advertise",
        "has_nopeer",
        "prefix_origin_event_count",
        "prefix_origin_path_event_count",
        "path_signature_event_count",
        "external_risk_signal",
        "low_visibility",
        "short_duration",
        "rare_prefix_origin_path",
        "common_nonrare_route",
        "population",
        "has_active_attack",
        "has_hard_negative",
        "attack_subtype_set",
        "primary_family_set",
    ]
    for policy in config["policies"]:
        policy_id = str(policy["policy_id"])
        cols.extend(
            [
                f"{policy_id}_assignment",
                f"{policy_id}_protection_reason_set",
                f"{policy_id}_suppression_reason_set",
            ]
        )
    return [col for col in cols if col in df.columns]


def write_outputs(
    df: pd.DataFrame,
    paths: dict[str, Path],
    config: dict[str, Any],
    sample_size: int,
) -> dict[str, Any]:
    comparison, population, attack, reasons = compute_outputs(df, config)
    pressure = retained_pressure_audit(comparison)
    features = fg0.semantic_feature_audit(df)
    recommended, action = choose_recommendation(comparison)
    safe = comparison[comparison["safety_pass"].astype(bool)].copy()
    recommendable_passed = bool(
        comparison[comparison["recommendable"].astype(bool)]["overall_pass"].any()
    )
    best_safe_bg = float(safe["pure_reference_background_suppression_rate"].max()) if not safe.empty else 0.0
    best_safe_compression = float(safe["estimated_compression_ratio"].max()) if not safe.empty else 0.0
    output_dir = paths["output_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)

    comparison.to_csv(output_dir / "r_foreground2_policy_comparison.csv", index=False)
    population.to_csv(output_dir / "r_foreground2_policy_population_audit.csv", index=False)
    attack.to_csv(output_dir / "r_foreground2_policy_attack_retention_audit.csv", index=False)
    reasons.to_csv(output_dir / "r_foreground2_policy_reason_distribution.csv", index=False)
    pressure.to_csv(output_dir / "r_foreground2_retained_pressure_audit.csv", index=False)
    features.to_csv(output_dir / "r_foreground2_semantic_feature_audit.csv", index=False)
    df.loc[:, sample_columns(df, config)].head(sample_size).to_csv(
        output_dir / "r_foreground2_assignment_sample.csv", index=False
    )

    total = int(len(df))
    summary = {
        "phase": "R-FOREGROUND-2",
        "run_id": str(df["run_id"].dropna().iloc[0]) if "run_id" in df and df["run_id"].notna().any() else "",
        "policy_config": str(paths["policy_config"]),
        "total_rows": total,
        "policy_count": int(len(config["policies"])),
        "recommended_policy_id": recommended,
        "recommended_action": action,
        "any_recommendable_policy_passed": recommendable_passed,
        "best_safe_background_suppression_rate": round(best_safe_bg, 9),
        "best_safe_compression_ratio": round(best_safe_compression, 6),
        "future_target_background_suppression_rate": config["future_targets"]["minimum_reference_background_suppression_rate"],
        "future_stretch_target": config["future_targets"]["stretch_reference_background_suppression_rate"],
        "policy_comparison": comparison.to_dict(orient="records"),
        "candidate_free": True,
        "truth_feature_leakage_count": 0,
        "online_training_split_boundary": config.get("online_training_split_boundary", ""),
        "allowed_claim": "R-FOREGROUND-2 policy improvement audit result only.",
        "forbidden_claims": config.get("forbidden_claims", []),
        "recommended_next_step": (
            "promote recommended policy to R-FOREGROUND-3 smoke"
            if recommendable_passed
            else "do not promote directly; inspect best safe policy and repair features before another smoke"
        ),
    }
    write_json(output_dir / "r_foreground2_summary.json", summary)
    write_report(output_dir / "r_foreground2_report.md", summary, comparison, pressure, attack)
    return summary


def main() -> None:
    args = parse_args()
    paths = resolve_paths(args)
    config = read_json(paths["policy_config"])
    prepare_output_dir(paths["output_dir"], args.overwrite)
    df = load_feature_frame(paths, config, args.max_rows)
    assign_policies(df, config)
    truth_labels = fg0.load_truth(paths, df)
    df = fg0.attach_truth_for_evaluation(df, truth_labels)
    summary = write_outputs(df, paths, config, args.sample_size)
    print(json.dumps(summary, indent=2, sort_keys=True, default=json_default))


if __name__ == "__main__":
    main()
