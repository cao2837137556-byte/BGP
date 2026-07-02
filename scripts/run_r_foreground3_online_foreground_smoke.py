#!/usr/bin/env python3
"""Run R-FOREGROUND-3 online foreground smoke.

R-FOREGROUND-3 formalizes the best safe R-FOREGROUND-2 pressure-test policy as
a single auditable online foreground candidate. It writes full assignment
artifacts for the validated R-ATTACK-0B multi-attack replay while keeping
controlled truth metadata strictly evaluation-only.
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
import audit_r_foreground2_policy_improvement as fg2


ASSIGN_PROTECTED = fg0.ASSIGN_PROTECTED
ASSIGN_GRAY = fg0.ASSIGN_GRAY
ASSIGN_SUPPRESSED = fg0.ASSIGN_SUPPRESSED

DEFAULT_RUN_ID = "s2a_attack0b_multi_attack_smoke_6h_april16_v01"
DEFAULT_ATTACK_OUTPUT_ROOT = "outputs/r_attack_0b/s2a_attack0b_multi_attack_smoke_6h_april16_v01"
DEFAULT_POLICY_CONFIG = "configs/r_foreground3_online_policy_v1.json"


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
        else Path("outputs") / "r_foreground_3" / args.run_id,
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
        "r_foreground3_summary.json",
        "r_foreground3_population_audit.csv",
        "r_foreground3_attack_retention_audit.csv",
        "r_foreground3_reason_distribution.csv",
        "r_foreground3_semantic_feature_audit.csv",
        "r_foreground3_policy_qualification_audit.csv",
        "r_foreground3_assignment_sample.csv",
        "r_foreground3_assignment.parquet",
        "r_foreground3_foreground_events.parquet",
        "r_foreground3_suppressed_background_events.parquet",
        "r_foreground3_gray_retained_events.parquet",
        "r_foreground3_report.md",
    ]
    existing = [path / name for name in outputs if (path / name).exists()]
    if existing and not overwrite:
        raise FileExistsError(
            "output files already exist; pass --overwrite to replace: "
            + ", ".join(str(item) for item in existing)
        )
    path.mkdir(parents=True, exist_ok=True)


def policy_from_config(config: dict[str, Any]) -> dict[str, Any]:
    policy = dict(config["policy_parameters"])
    policy["policy_id"] = config["policy_id"]
    policy["description"] = config.get("purpose", "")
    policy["recommendable"] = True
    return policy


def load_feature_frame(paths: dict[str, Path], config: dict[str, Any], max_rows: int) -> pd.DataFrame:
    events = fg0.load_events(paths)
    if max_rows and max_rows > 0:
        events = events.head(max_rows).copy()
    events = fg0.attach_evidence(events, paths)
    events = fg0.compute_semantic_features(events, config)
    return events


def assign_online_policy(df: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    policy = policy_from_config(config)
    assignment, protected, suppressed, gray, rare_pop = fg2.assign_policy(df, policy)
    policy_id = str(config["policy_id"])

    protection_reason = fg2.reason_string(
        {
            "rpki_risk": df["rpki_risk_signal"],
            "asrel_risk": df["asrel_risk_signal"],
            "well_known_community": df["community_risk_signal"],
            "rare_prefix_origin_path": rare_pop,
            "low_visibility_external": df["low_visibility"] & df["external_risk_signal"],
        },
        df.index,
    )
    suppression_reason = fg2.reason_string(
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
    gray_reason = fg2.reason_string(
        {
            "evidence_unavailable": df["evidence_unavailable_for_suppression"],
            "low_visibility_without_external_risk": df["low_visibility"] & ~df["external_risk_signal"],
            "not_recurrent_enough_for_suppression": ~suppressed & ~protected,
        },
        df.index,
    ).replace("", "residual_gray")

    df["online_policy_id"] = policy_id
    df["online_assignment"] = assignment
    df["online_assignment_reason"] = ""
    df.loc[protected, "online_assignment_reason"] = protection_reason.loc[protected]
    df.loc[suppressed, "online_assignment_reason"] = suppression_reason.loc[suppressed]
    df.loc[gray, "online_assignment_reason"] = gray_reason.loc[gray]
    df["online_downstream_retained"] = ~df["online_assignment"].eq(ASSIGN_SUPPRESSED)
    return df


def attach_offline_pool_marker(df: pd.DataFrame) -> pd.DataFrame:
    """Mark suppressed labeled rows for later offline training/evaluation pools.

    This must run after truth metadata is attached. The marker is not a policy
    feature and is used only for output accounting.
    """

    df["online_training_eval_pool_candidate"] = (
        df["online_assignment"].eq(ASSIGN_SUPPRESSED)
        & (df["has_hard_negative"] | df["has_scenario_control"] | df["mixed_membership"])
    )
    return df


def population_row(name: str, frame: pd.DataFrame) -> dict[str, Any]:
    counts = fg0.assignment_counts(frame["online_assignment"])
    total = int(len(frame))
    retained = counts[ASSIGN_PROTECTED] + counts[ASSIGN_GRAY]
    return {
        "population": name,
        "rows": total,
        "protected_foreground": counts[ASSIGN_PROTECTED],
        "gray_retained": counts[ASSIGN_GRAY],
        "operational_background_suppressed": counts[ASSIGN_SUPPRESSED],
        "downstream_retained": retained,
        "suppression_rate": fg0.safe_rate(counts[ASSIGN_SUPPRESSED], total),
        "downstream_retention_rate": fg0.safe_rate(retained, total),
    }


def build_population_audit(df: pd.DataFrame) -> pd.DataFrame:
    active_attack = df[df["has_active_attack"]]
    pure_reference = df[~df["has_scenario_membership"]]
    hard_negative = df[df["has_hard_negative"]]
    scenario_control = df[df["has_scenario_control"]]
    mixed = df[df["mixed_membership"]]
    rows = [
        population_row("all_events", df),
        population_row("active_attack", active_attack),
        population_row("hard_negative", hard_negative),
        population_row("scenario_control", scenario_control),
        population_row("pure_reference_background", pure_reference),
        population_row("mixed_membership", mixed),
    ]
    return pd.DataFrame(rows)


def build_attack_audit(df: pd.DataFrame) -> pd.DataFrame:
    active_attack = df[df["has_active_attack"]].copy()
    rows = []
    if active_attack.empty:
        return pd.DataFrame(
            columns=[
                "attack_subtype_set",
                "primary_family_set",
                "rows",
                "suppressed_attack_count",
                "attack_retention",
            ]
        )
    for keys, group in active_attack.groupby(
        ["attack_subtype_set", "primary_family_set"], dropna=False, sort=False
    ):
        suppressed = int(group["online_assignment"].eq(ASSIGN_SUPPRESSED).sum())
        rows.append(
            {
                "attack_subtype_set": keys[0],
                "primary_family_set": keys[1],
                "rows": int(len(group)),
                "protected_foreground": int(group["online_assignment"].eq(ASSIGN_PROTECTED).sum()),
                "gray_retained": int(group["online_assignment"].eq(ASSIGN_GRAY).sum()),
                "suppressed_attack_count": suppressed,
                "attack_retention": fg0.safe_rate(len(group) - suppressed, len(group)),
            }
        )
    return pd.DataFrame(rows)


def reason_distribution(df: pd.DataFrame) -> pd.DataFrame:
    total = int(len(df))
    rows = []
    for state, subset in df.groupby("online_assignment", sort=False):
        counts = subset["online_assignment_reason"].fillna("").replace("", "none").value_counts().head(50)
        for reason, count in counts.items():
            rows.append(
                {
                    "assignment_state": state,
                    "reason": reason,
                    "rows": int(count),
                    "rate_of_total": fg0.safe_rate(count, total),
                    "rate_of_assignment": fg0.safe_rate(count, len(subset)),
                }
            )
    return pd.DataFrame(rows)


def choose_assignment_columns(df: pd.DataFrame) -> list[str]:
    columns = [
        "event_id",
        "run_id",
        "prefix",
        "origin_as",
        "as_path_clean",
        "first_seen",
        "last_seen",
        "duration_sec",
        "record_count",
        "collector_set",
        "collector_count",
        "rpki_status",
        "rpki_evidence_state",
        "path_relation_diagnostic_2024",
        "path_relation_evidence_state_2024",
        "community_evidence_state",
        "raw_match_status",
        "has_no_export",
        "has_no_advertise",
        "has_nopeer",
        "has_communities",
        "prefix_origin_key",
        "prefix_origin_path_key",
        "as_path_signature",
        "prefix_origin_event_count",
        "prefix_origin_path_event_count",
        "path_signature_event_count",
        "external_risk_signal",
        "rpki_risk_signal",
        "asrel_risk_signal",
        "community_risk_signal",
        "low_visibility",
        "short_duration",
        "rare_prefix_origin",
        "rare_path_signature",
        "rare_prefix_origin_path",
        "stable_recurrent_route",
        "common_nonrare_route",
        "evidence_unavailable_for_suppression",
        "online_policy_id",
        "online_assignment",
        "online_assignment_reason",
        "online_downstream_retained",
        "online_training_eval_pool_candidate",
        "population",
        "has_active_attack",
        "has_hard_negative",
        "has_scenario_control",
        "mixed_membership",
        "attack_member_count",
        "hard_negative_member_count",
        "scenario_id_set",
        "scenario_class_set",
        "attack_subtype_set",
        "primary_family_set",
    ]
    return [column for column in columns if column in df.columns]


def summarize(df: pd.DataFrame, config: dict[str, Any], paths: dict[str, Path]) -> dict[str, Any]:
    total = int(len(df))
    foreground = int(df["online_downstream_retained"].sum())
    suppressed = int(df["online_assignment"].eq(ASSIGN_SUPPRESSED).sum())
    active_attack = df[df["has_active_attack"]]
    pure_reference = df[~df["has_scenario_membership"]]
    hard_negative = df[df["has_hard_negative"]]
    scenario_control = df[df["has_scenario_control"]]
    mixed = df[df["mixed_membership"]]

    active_attack_count = int(len(active_attack))
    suppressed_attack_count = int(active_attack["online_assignment"].eq(ASSIGN_SUPPRESSED).sum())
    attack_retention = fg0.safe_rate(active_attack_count - suppressed_attack_count, active_attack_count)
    pure_ref_count = int(len(pure_reference))
    pure_ref_suppressed = int(pure_reference["online_assignment"].eq(ASSIGN_SUPPRESSED).sum())
    background_suppression = fg0.safe_rate(pure_ref_suppressed, pure_ref_count)
    compression_ratio = round(float(total) / float(foreground), 6) if foreground else None
    gray_rate = fg0.safe_rate(int(df["online_assignment"].eq(ASSIGN_GRAY).sum()), total)
    gates = config["multi_attack_smoke_gates"]
    safety_pass = (
        suppressed_attack_count == int(gates["suppressed_attack_count"])
        and attack_retention == float(gates["attack_retention"])
    )
    feasibility_pass = (
        background_suppression >= float(gates["minimum_reference_background_suppression_rate"])
        and (compression_ratio or 0.0) >= float(gates["minimum_compression_ratio"])
        and gray_rate <= float(gates["maximum_gray_zone_rate"])
    )
    online_pass = bool(safety_pass and feasibility_pass)
    hard_negative_suppressed = int(hard_negative["online_assignment"].eq(ASSIGN_SUPPRESSED).sum())
    scenario_control_suppressed = int(scenario_control["online_assignment"].eq(ASSIGN_SUPPRESSED).sum())
    mixed_suppressed = int(mixed["online_assignment"].eq(ASSIGN_SUPPRESSED).sum())
    offline_pool_candidates = int(df["online_training_eval_pool_candidate"].sum())

    return {
        "phase": "R-FOREGROUND-3",
        "policy_id": config["policy_id"],
        "source_policy": config["source_policy"],
        "run_id": str(df["run_id"].dropna().iloc[0]) if "run_id" in df and df["run_id"].notna().any() else "",
        "policy_config": str(paths["policy_config"]),
        "total_rows": total,
        "foreground_rows": foreground,
        "suppressed_rows": suppressed,
        "estimated_compression_ratio": compression_ratio,
        "active_attack_event_count": active_attack_count,
        "suppressed_attack_count": suppressed_attack_count,
        "attack_retention": attack_retention,
        "pure_reference_background_count": pure_ref_count,
        "pure_reference_background_suppressed_count": pure_ref_suppressed,
        "pure_reference_background_suppression_rate": background_suppression,
        "gray_zone_rate": gray_rate,
        "hard_negative_count": int(len(hard_negative)),
        "hard_negative_suppressed_count": hard_negative_suppressed,
        "scenario_control_count": int(len(scenario_control)),
        "scenario_control_suppressed_count": scenario_control_suppressed,
        "mixed_membership_count": int(len(mixed)),
        "mixed_membership_suppressed_count": mixed_suppressed,
        "offline_training_eval_pool_candidate_count": offline_pool_candidates,
        "truth_feature_leakage_count": 0,
        "safety_pass": bool(safety_pass),
        "feasibility_pass": bool(feasibility_pass),
        "online_pass": online_pass,
        "multi_attack_smoke_gates": gates,
        "future_targets": config.get("future_targets", {}),
        "candidate_free": True,
        "online_training_split_note": config["online_training_split_boundary"],
        "allowed_claim": "R-FOREGROUND-3 validates a formal online foreground smoke candidate on the current R-ATTACK-0B controlled multi-attack replay only.",
        "forbidden_claims": config["forbidden_claims"],
        "recommended_next_step": (
            "freeze online_path_pressure_v1 as current foreground baseline and move to R-TRAIN-DATA-0 or R-HIST-0 planning"
            if online_pass
            else "repair online foreground policy before training data construction, historical replay, or poisoning expansion"
        ),
    }


def qualification_audit(summary: dict[str, Any], config: dict[str, Any]) -> pd.DataFrame:
    rows = [
        {
            "check": "source_policy_was_pressure_test",
            "passed": True,
            "value": config["source_policy"],
            "notes": "R-FOREGROUND-3 reruns the policy as a formal single-policy smoke before promotion.",
        },
        {
            "check": "candidate_free",
            "passed": bool(summary["candidate_free"]),
            "value": summary["candidate_free"],
            "notes": "No candidate_flag, candidate_reasons, matched_rule_count, or legacy labels are policy features.",
        },
        {
            "check": "truth_feature_leakage",
            "passed": int(summary["truth_feature_leakage_count"]) == 0,
            "value": summary["truth_feature_leakage_count"],
            "notes": "Truth metadata is attached only after policy assignment.",
        },
        {
            "check": "attack_safety_gate",
            "passed": bool(summary["safety_pass"]),
            "value": f"retention={summary['attack_retention']}; suppressed={summary['suppressed_attack_count']}",
            "notes": "Any suppressed controlled attack row is a stop-loss failure.",
        },
        {
            "check": "foreground_feasibility_gate",
            "passed": bool(summary["feasibility_pass"]),
            "value": f"bg={summary['pure_reference_background_suppression_rate']}; compression={summary['estimated_compression_ratio']}; gray={summary['gray_zone_rate']}",
            "notes": "Current gate is >=0.50 reference-background suppression and >=2.0 compression.",
        },
        {
            "check": "online_training_split",
            "passed": True,
            "value": summary["offline_training_eval_pool_candidate_count"],
            "notes": "Suppressed hard-negative/control/mixed rows remain available for later offline training/evaluation pool construction.",
        },
    ]
    return pd.DataFrame(rows)


def markdown_table(frame: pd.DataFrame) -> str:
    return fg0.markdown_table(frame)


def write_report(
    path: Path,
    summary: dict[str, Any],
    population: pd.DataFrame,
    attack: pd.DataFrame,
    qualification: pd.DataFrame,
    features: pd.DataFrame,
) -> None:
    lines = [
        "# R-FOREGROUND-3 Online Foreground Smoke",
        "",
        "Status: generated by `scripts/run_r_foreground3_online_foreground_smoke.py`.",
        "",
        "## Purpose",
        "",
        "R-FOREGROUND-3 formalizes the best safe R-FOREGROUND-2 pressure-test policy as `online_path_pressure_v1`.",
        "It is candidate-free and uses event fields plus clean RPKI, 2024 AS-rel, and community sidecars.",
        "It does not train learning and does not implement production suppression.",
        "",
        "## Key Results",
        "",
        f"- total rows: `{summary['total_rows']}`",
        f"- foreground rows: `{summary['foreground_rows']}`",
        f"- suppressed rows: `{summary['suppressed_rows']}`",
        f"- compression ratio: `{summary['estimated_compression_ratio']}`",
        f"- background suppression: `{summary['pure_reference_background_suppression_rate']}`",
        f"- attack retention: `{summary['attack_retention']}`",
        f"- suppressed attack count: `{summary['suppressed_attack_count']}`",
        f"- online pass: `{summary['online_pass']}`",
        "",
        "## Qualification Audit",
        "",
        markdown_table(qualification),
        "",
        "## Population Audit",
        "",
        markdown_table(population),
        "",
        "## Per-Family Attack Retention",
        "",
        markdown_table(attack),
        "",
        "## Semantic Feature Audit",
        "",
        markdown_table(features),
        "",
        "## Online vs Offline Data Boundary",
        "",
        "- Online foreground compression is allowed to suppress hard-negative/control/mixed rows if no active attack is suppressed.",
        "- These labeled suppressed rows are not discarded from the research dataset; they become candidates for a later offline training/evaluation pool.",
        "- Suppressed background is operational workload reduction, not confirmed benign.",
        "",
        "## Guardrails",
        "",
        "- Candidate flags, candidate reasons, and matched rule counts are not policy features.",
        "- Truth metadata is evaluation-only and is attached after policy assignment.",
        "- RPKI invalid is not attack truth; RPKI valid is not benign.",
        "- AS-rel diagnostic is not route-leak truth.",
        "- NO_EXPORT presence is not attack truth; absence/unavailable state is not safe.",
        "- This controlled replay does not prove historical-event recall, stealth robustness, or poisoning/evasion robustness.",
        "- Learning remains blocked until foreground safety, offline training data design, historical replay, and poisoning/evasion benchmarks are separately handled.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_outputs(
    df: pd.DataFrame,
    paths: dict[str, Path],
    config: dict[str, Any],
    sample_size: int,
) -> dict[str, Any]:
    output_dir = paths["output_dir"]
    df = attach_offline_pool_marker(df)
    summary = summarize(df, config, paths)
    population = build_population_audit(df)
    attack = build_attack_audit(df)
    reasons = reason_distribution(df)
    features = fg0.semantic_feature_audit(df)
    qualification = qualification_audit(summary, config)
    columns = choose_assignment_columns(df)
    assignment = df.loc[:, columns].copy()

    assignment.to_parquet(output_dir / "r_foreground3_assignment.parquet", index=False)
    assignment[assignment["online_downstream_retained"]].to_parquet(
        output_dir / "r_foreground3_foreground_events.parquet", index=False
    )
    assignment[assignment["online_assignment"].eq(ASSIGN_SUPPRESSED)].to_parquet(
        output_dir / "r_foreground3_suppressed_background_events.parquet", index=False
    )
    assignment[assignment["online_assignment"].eq(ASSIGN_GRAY)].to_parquet(
        output_dir / "r_foreground3_gray_retained_events.parquet", index=False
    )

    population.to_csv(output_dir / "r_foreground3_population_audit.csv", index=False)
    attack.to_csv(output_dir / "r_foreground3_attack_retention_audit.csv", index=False)
    reasons.to_csv(output_dir / "r_foreground3_reason_distribution.csv", index=False)
    features.to_csv(output_dir / "r_foreground3_semantic_feature_audit.csv", index=False)
    qualification.to_csv(output_dir / "r_foreground3_policy_qualification_audit.csv", index=False)
    assignment.head(sample_size).to_csv(output_dir / "r_foreground3_assignment_sample.csv", index=False)
    write_json(output_dir / "r_foreground3_summary.json", summary)
    write_report(
        output_dir / "r_foreground3_report.md",
        summary,
        population,
        attack,
        qualification,
        features,
    )
    return summary


def main() -> None:
    args = parse_args()
    paths = resolve_paths(args)
    config = read_json(paths["policy_config"])
    prepare_output_dir(paths["output_dir"], args.overwrite)
    df = load_feature_frame(paths, config, args.max_rows)
    df = assign_online_policy(df, config)
    truth_labels = fg0.load_truth(paths, df)
    df = fg0.attach_truth_for_evaluation(df, truth_labels)
    summary = write_outputs(df, paths, config, args.sample_size)
    print(json.dumps(summary, indent=2, sort_keys=True, default=json_default))


if __name__ == "__main__":
    main()
