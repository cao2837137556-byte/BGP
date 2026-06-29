#!/usr/bin/env python3
"""Run R-FOREGROUND-1 online foreground smoke.

This script freezes the R-FOREGROUND-0 `aggressive_recurrence` policy as a
single candidate-free online foreground policy. It writes full assignment
artifacts for the current controlled origin-family smoke, while keeping truth
metadata strictly evaluation-only.
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

DEFAULT_RUN_ID = "s2a_attack0a2_hardened_origin_smoke_6h_april16_v02"
DEFAULT_ATTACK_OUTPUT_ROOT = "outputs/r_attack_0a3_intel/s2a_baseline_v01_pilot_6h_april16"
DEFAULT_POLICY_CONFIG = "configs/r_foreground1_online_policy_v1.json"


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
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=json_default), encoding="utf-8")


def resolve_paths(args: argparse.Namespace) -> dict[str, Path]:
    root = Path(args.attack_output_root)
    paths = {
        "events": Path(args.events) if args.events else Path("data") / "runs" / args.run_id / "events" / "event_units.parquet",
        "raw_truth": Path(args.raw_truth) if args.raw_truth else root / "materialization" / "injected_raw_truth.parquet",
        "raw_event_membership": Path(args.raw_event_membership) if args.raw_event_membership else root / "audit" / "raw_event_membership.csv",
        "rpki_sidecar": Path(args.rpki_sidecar) if args.rpki_sidecar else root / "evidence" / "rpki" / "rpki_event_sidecar.parquet",
        "asrel_sidecar": Path(args.asrel_sidecar) if args.asrel_sidecar else root / "evidence" / "asrel" / "asrel_2024_event_sidecar.parquet",
        "community_sidecar": Path(args.community_sidecar) if args.community_sidecar else root / "evidence" / "community" / "community_event_sidecar.parquet",
        "policy_config": Path(args.policy_config),
        "output_dir": Path(args.output_dir) if args.output_dir else Path("outputs") / "r_foreground_1" / args.run_id,
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
        "r_foreground1_summary.json",
        "r_foreground1_population_audit.csv",
        "r_foreground1_attack_retention_audit.csv",
        "r_foreground1_reason_distribution.csv",
        "r_foreground1_semantic_feature_audit.csv",
        "r_foreground1_assignment_sample.csv",
        "r_foreground1_assignment.parquet",
        "r_foreground1_foreground_events.parquet",
        "r_foreground1_suppressed_background_events.parquet",
        "r_foreground1_gray_retained_events.parquet",
        "r_foreground1_report.md",
    ]
    existing = [path / name for name in outputs if (path / name).exists()]
    if existing and not overwrite:
        raise FileExistsError(
            "output files already exist; pass --overwrite to replace: "
            + ", ".join(str(item) for item in existing)
        )
    path.mkdir(parents=True, exist_ok=True)


def load_events(paths: dict[str, Path], max_rows: int) -> pd.DataFrame:
    events = fg0.load_events(paths)
    if max_rows and max_rows > 0:
        events = events.head(max_rows).copy()
    return events


def primary_reason(df: pd.DataFrame) -> pd.Series:
    conditions = [
        df["rpki_risk_signal"],
        df["asrel_risk_signal"],
        df["community_risk_signal"],
        df["rare_prefix_origin_path"],
        df["low_visibility"] & df["external_risk_signal"],
    ]
    choices = [
        "rpki_risk",
        "asrel_risk",
        "well_known_community",
        "rare_prefix_origin_path",
        "low_visibility_with_external_risk",
    ]
    return pd.Series(np.select(conditions, choices, default=""), index=df.index)


def suppression_reason(df: pd.DataFrame) -> pd.Series:
    stable_common = df["stable_recurrent_route"] & df["common_nonrare_route"]
    reason = pd.Series("", index=df.index)
    reason.loc[df["common_nonrare_route"]] = "common_nonrisk_route"
    reason.loc[stable_common] = "stable_common_nonrisk_route"
    return reason


def gray_reason(df: pd.DataFrame) -> pd.Series:
    conditions = [
        df["evidence_unavailable_for_suppression"],
        df["low_visibility"],
        ~df["common_nonrare_route"],
    ]
    choices = [
        "evidence_unavailable",
        "low_visibility_without_external_risk",
        "not_common_enough_for_suppression",
    ]
    return pd.Series(np.select(conditions, choices, default="residual_gray"), index=df.index)


def assign_online_policy(df: pd.DataFrame) -> pd.DataFrame:
    protected = df["external_risk_signal"] | df["rare_prefix_origin_path"] | (
        df["low_visibility"] & df["external_risk_signal"]
    )
    suppressed = ~protected & ~df["evidence_unavailable_for_suppression"] & df["common_nonrare_route"]

    df["online_policy_id"] = "online_aggressive_recurrence_v1"
    df["online_assignment"] = ASSIGN_GRAY
    df.loc[protected, "online_assignment"] = ASSIGN_PROTECTED
    df.loc[suppressed, "online_assignment"] = ASSIGN_SUPPRESSED

    df["online_assignment_reason"] = ""
    df.loc[protected, "online_assignment_reason"] = primary_reason(df).loc[protected]
    df.loc[suppressed, "online_assignment_reason"] = suppression_reason(df).loc[suppressed]
    gray = df["online_assignment"].eq(ASSIGN_GRAY)
    df.loc[gray, "online_assignment_reason"] = gray_reason(df).loc[gray]
    df["online_downstream_retained"] = ~df["online_assignment"].eq(ASSIGN_SUPPRESSED)
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
    for keys, group in active_attack.groupby(["attack_subtype_set", "primary_family_set"], dropna=False, sort=False):
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
    gates = config["current_origin_smoke_gates"]
    safety_pass = (
        suppressed_attack_count == gates["suppressed_attack_count"]
        and attack_retention == gates["attack_retention"]
    )
    feasibility_pass = (
        background_suppression >= gates["minimum_reference_background_suppression_rate"]
        and (compression_ratio or 0) >= gates["minimum_compression_ratio"]
    )
    online_pass = bool(safety_pass and feasibility_pass)
    hard_negative_suppressed = int(hard_negative["online_assignment"].eq(ASSIGN_SUPPRESSED).sum())
    scenario_control_suppressed = int(scenario_control["online_assignment"].eq(ASSIGN_SUPPRESSED).sum())
    mixed_suppressed = int(mixed["online_assignment"].eq(ASSIGN_SUPPRESSED).sum())
    offline_pool_candidates = int(
        df[
            df["online_assignment"].eq(ASSIGN_SUPPRESSED)
            & (df["has_hard_negative"] | df["has_scenario_control"] | df["mixed_membership"])
        ].shape[0]
    )

    return {
        "phase": "R-FOREGROUND-1",
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
        "gray_zone_rate": fg0.safe_rate(int(df["online_assignment"].eq(ASSIGN_GRAY).sum()), total),
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
        "current_origin_smoke_targets": gates,
        "future_multi_attack_targets": config["future_multi_attack_targets"],
        "candidate_free": True,
        "online_training_split_note": config["online_training_split_boundary"],
        "allowed_claim": "R-FOREGROUND-1 validates an online foreground smoke policy on the current origin-family controlled replay only.",
        "forbidden_claims": config["forbidden_claims"],
        "recommended_next_step": (
            "promote to R-ATTACK-0B multi-attack expansion and retest the foreground target"
            if online_pass
            else "repair online foreground policy before attack-family expansion or learning"
        ),
    }


def markdown_table(frame: pd.DataFrame) -> str:
    return fg0.markdown_table(frame)


def write_report(path: Path, summary: dict[str, Any], population: pd.DataFrame, features: pd.DataFrame) -> None:
    lines = [
        "# R-FOREGROUND-1 Online Foreground Smoke",
        "",
        "Status: generated by `scripts/run_r_foreground1_online_foreground_smoke.py`.",
        "",
        "## Purpose",
        "",
        "R-FOREGROUND-1 freezes `aggressive_recurrence` from R-FOREGROUND-0 as an online foreground smoke policy.",
        "It is candidate-free and uses event fields plus clean RPKI, 2024 AS-rel, and community sidecars.",
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
        "## Current And Future Targets",
        "",
        "- Current origin-family smoke target: background suppression >= `0.30`, compression ratio >= `1.5`, suppressed attacks = `0`.",
        "- Future multi-attack target: background suppression >= `0.50`.",
        "- Future stretch target: `0.60-0.70` background suppression after route-leak, path-manipulation, stealth, and poisoning/evasion expansion.",
        "",
        "## Population Audit",
        "",
        markdown_table(population),
        "",
        "## Semantic Feature Audit",
        "",
        markdown_table(features),
        "",
        "## Online vs Offline Data Boundary",
        "",
        "- Online foreground compression is allowed to suppress hard-negative/control rows if no active attack is suppressed.",
        "- These hard-negative/control/mixed rows are not discarded from the research dataset; they become candidates for a later offline training/evaluation pool.",
        "- Suppressed background is operational suppression, not confirmed benign.",
        "",
        "## Guardrails",
        "",
        "- Candidate flags, candidate reasons, and matched rule counts are not policy features.",
        "- Truth metadata is evaluation-only and is attached after policy assignment.",
        "- RPKI invalid is not attack truth; RPKI valid is not benign.",
        "- AS-rel diagnostic is not route-leak truth.",
        "- NO_EXPORT presence is not attack truth; absence/unavailable state is not safe.",
        "- This origin-family smoke does not prove multi-attack recall or poisoning/evasion robustness.",
        "- Learning remains blocked until multi-attack foreground safety and benchmark coverage are qualified.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_outputs(df: pd.DataFrame, paths: dict[str, Path], config: dict[str, Any], sample_size: int) -> dict[str, Any]:
    output_dir = paths["output_dir"]
    summary = summarize(df, config, paths)
    population = build_population_audit(df)
    attack = build_attack_audit(df)
    reasons = reason_distribution(df)
    features = fg0.semantic_feature_audit(df)
    columns = choose_assignment_columns(df)
    assignment = df.loc[:, columns].copy()

    assignment.to_parquet(output_dir / "r_foreground1_assignment.parquet", index=False)
    assignment[assignment["online_downstream_retained"]].to_parquet(
        output_dir / "r_foreground1_foreground_events.parquet", index=False
    )
    assignment[assignment["online_assignment"].eq(ASSIGN_SUPPRESSED)].to_parquet(
        output_dir / "r_foreground1_suppressed_background_events.parquet", index=False
    )
    assignment[assignment["online_assignment"].eq(ASSIGN_GRAY)].to_parquet(
        output_dir / "r_foreground1_gray_retained_events.parquet", index=False
    )

    population.to_csv(output_dir / "r_foreground1_population_audit.csv", index=False)
    attack.to_csv(output_dir / "r_foreground1_attack_retention_audit.csv", index=False)
    reasons.to_csv(output_dir / "r_foreground1_reason_distribution.csv", index=False)
    features.to_csv(output_dir / "r_foreground1_semantic_feature_audit.csv", index=False)
    assignment.head(sample_size).to_csv(output_dir / "r_foreground1_assignment_sample.csv", index=False)
    write_json(output_dir / "r_foreground1_summary.json", summary)
    write_report(output_dir / "r_foreground1_report.md", summary, population, features)
    return summary


def main() -> None:
    args = parse_args()
    paths = resolve_paths(args)
    config = read_json(paths["policy_config"])
    prepare_output_dir(paths["output_dir"], args.overwrite)
    df = load_events(paths, args.max_rows)
    df = fg0.attach_evidence(df, paths)
    df = fg0.compute_semantic_features(df, config)
    df = assign_online_policy(df)
    truth_labels = fg0.load_truth(paths, df)
    df = fg0.attach_truth_for_evaluation(df, truth_labels)
    summary = write_outputs(df, paths, config, args.sample_size)
    print(json.dumps(summary, indent=2, sort_keys=True, default=json_default))
    raise SystemExit(0)


if __name__ == "__main__":
    main()
