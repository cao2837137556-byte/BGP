#!/usr/bin/env python3
"""Run R-FOREGROUND-0 candidate-free semantic foreground audit.

The script evaluates several foreground-extraction policies on event rows plus
clean evidence sidecars. It intentionally does not read candidate flags,
candidate reasons, legacy final labels, or old 2017 AS-rel fields. Controlled
truth metadata is attached only after policy assignment for safety evaluation.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


ASSIGN_PROTECTED = "protected_foreground"
ASSIGN_GRAY = "gray_retained"
ASSIGN_SUPPRESSED = "operational_background_suppressed"

DEFAULT_RUN_ID = "s2a_attack0a2_hardened_origin_smoke_6h_april16_v02"
DEFAULT_ATTACK_OUTPUT_ROOT = "outputs/r_attack_0a3_intel/s2a_baseline_v01_pilot_6h_april16"
DEFAULT_POLICY_CONFIG = "configs/r_foreground0_semantic_policy_audit_v0.json"


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


def existing_columns(path: Path, wanted: list[str]) -> list[str]:
    schema = pq.ParquetFile(path).schema_arrow
    names = set(schema.names)
    return [column for column in wanted if column in names]


def require_path(path: str | Path, label: str) -> Path:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"{label} not found: {p}")
    return p


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
        "output_dir": Path(args.output_dir) if args.output_dir else Path("outputs") / "r_foreground_0" / args.run_id,
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
        paths[key] = require_path(paths[key], key)
    return paths


def prepare_output_dir(path: Path, overwrite: bool) -> None:
    outputs = [
        "r_foreground0_summary.json",
        "r_foreground0_policy_comparison.csv",
        "r_foreground0_policy_population_audit.csv",
        "r_foreground0_policy_attack_retention_audit.csv",
        "r_foreground0_policy_reason_distribution.csv",
        "r_foreground0_semantic_feature_audit.csv",
        "r_foreground0_assignment_sample.csv",
        "r_foreground0_report.md",
    ]
    existing = [path / name for name in outputs if (path / name).exists()]
    if existing and not overwrite:
        raise FileExistsError(
            "output files already exist; pass --overwrite to replace: "
            + ", ".join(str(item) for item in existing)
        )
    path.mkdir(parents=True, exist_ok=True)


def bool_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(False, index=frame.index)
    value = frame[column]
    if value.dtype == bool:
        return value.fillna(False)
    text = value.fillna("").astype(str).str.strip().str.lower()
    return text.isin({"true", "1", "yes", "y"})


def text_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index)
    return frame[column].fillna("").astype(str)


def numeric_series(frame: pd.DataFrame, column: str, default: float = 0.0) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(default, index=frame.index)
    return pd.to_numeric(frame[column], errors="coerce").fillna(default)


def safe_rate(count: int | float, denom: int | float) -> float:
    if not denom:
        return 0.0
    return round(float(count) / float(denom), 9)


def load_events(paths: dict[str, Path]) -> pd.DataFrame:
    columns = existing_columns(
        paths["events"],
        [
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
            "source_file",
        ],
    )
    events = pd.read_parquet(paths["events"], columns=columns)
    events["event_id"] = events["event_id"].astype(str)
    return events


def merge_sidecar(df: pd.DataFrame, path: Path, columns: list[str]) -> pd.DataFrame:
    selected = existing_columns(path, columns)
    if "event_id" not in selected:
        raise ValueError(f"sidecar missing event_id: {path}")
    sidecar = pd.read_parquet(path, columns=selected)
    sidecar["event_id"] = sidecar["event_id"].astype(str)
    return df.merge(sidecar, on="event_id", how="left")


def attach_evidence(df: pd.DataFrame, paths: dict[str, Path]) -> pd.DataFrame:
    df = merge_sidecar(
        df,
        paths["rpki_sidecar"],
        ["event_id", "rpki_status", "rpki_evidence_state", "rpki_snapshot_date"],
    )
    df = merge_sidecar(
        df,
        paths["asrel_sidecar"],
        [
            "event_id",
            "path_relation_diagnostic_2024",
            "path_relation_evidence_state_2024",
            "asrel_snapshot_date",
            "rel_unknown_rate_2024",
        ],
    )
    df = merge_sidecar(
        df,
        paths["community_sidecar"],
        [
            "event_id",
            "community_evidence_state",
            "raw_match_status",
            "has_no_export",
            "has_no_advertise",
            "has_nopeer",
            "has_communities",
        ],
    )
    return df


def compute_semantic_features(df: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    thresholds = config["feature_thresholds"]
    risk_values = config["risk_values"]

    df["prefix_norm"] = text_series(df, "prefix")
    df["origin_as_norm"] = text_series(df, "origin_as")
    df["as_path_signature"] = text_series(df, "as_path_clean")
    df["prefix_origin_key"] = df["prefix_norm"] + "|" + df["origin_as_norm"]
    df["prefix_origin_path_key"] = df["prefix_origin_key"] + "|" + df["as_path_signature"]
    df["collector_count_num"] = numeric_series(df, "collector_count", 0)
    df["duration_sec_num"] = numeric_series(df, "duration_sec", 0)
    df["record_count_num"] = numeric_series(df, "record_count", 0)

    df["prefix_origin_event_count"] = df.groupby("prefix_origin_key")["event_id"].transform("count")
    df["path_signature_event_count"] = df.groupby("as_path_signature")["event_id"].transform("count")
    df["prefix_origin_path_event_count"] = df.groupby("prefix_origin_path_key")["event_id"].transform("count")

    rpki_status = text_series(df, "rpki_status").str.lower()
    asrel_diag = text_series(df, "path_relation_diagnostic_2024").str.lower()
    rpki_risk_values = {str(value).lower() for value in risk_values.get("rpki_statuses", [])}
    asrel_risk_values = {str(value).lower() for value in risk_values.get("asrel_diagnostics", [])}

    df["rpki_risk_signal"] = rpki_status.isin(rpki_risk_values)
    df["asrel_risk_signal"] = asrel_diag.isin(asrel_risk_values)
    df["community_risk_signal"] = False
    for column in risk_values.get("community_flags", []):
        df["community_risk_signal"] |= bool_series(df, column)

    df["external_risk_signal"] = (
        df["rpki_risk_signal"] | df["asrel_risk_signal"] | df["community_risk_signal"]
    )
    df["community_unavailable"] = text_series(df, "community_evidence_state").str.lower().eq("raw_join_unavailable")
    df["asrel_unavailable"] = text_series(df, "path_relation_evidence_state_2024").str.lower().eq("unavailable")
    df["evidence_unavailable_for_suppression"] = df["community_unavailable"] | df["asrel_unavailable"]

    df["low_visibility"] = df["collector_count_num"] <= thresholds["low_visibility_collector_count"]
    df["short_duration"] = df["duration_sec_num"].between(0, thresholds["short_duration_sec"], inclusive="both")
    df["rare_prefix_origin"] = df["prefix_origin_event_count"] <= thresholds["rare_prefix_origin_count"]
    df["rare_path_signature"] = df["path_signature_event_count"] <= thresholds["rare_path_signature_count"]
    df["rare_prefix_origin_path"] = (
        df["prefix_origin_path_event_count"] <= thresholds["rare_prefix_origin_path_count"]
    )
    df["stable_recurrent_route"] = (
        (df["prefix_origin_event_count"] >= thresholds["stable_prefix_origin_count"])
        & (df["prefix_origin_path_event_count"] >= thresholds["stable_prefix_origin_path_count"])
        & (df["path_signature_event_count"] >= thresholds["stable_path_signature_count"])
    )
    df["common_nonrare_route"] = (
        (df["prefix_origin_event_count"] >= thresholds["common_prefix_origin_count"])
        & (df["prefix_origin_path_event_count"] >= thresholds["common_prefix_origin_path_count"])
    )
    df["semantic_signal_count"] = (
        df[
            [
                "external_risk_signal",
                "low_visibility",
                "short_duration",
                "rare_prefix_origin",
                "rare_path_signature",
                "rare_prefix_origin_path",
            ]
        ]
        .astype(int)
        .sum(axis=1)
    )
    return df


def reason_string(parts: dict[str, pd.Series], index: pd.Index) -> pd.Series:
    result = pd.Series("", index=index)
    for label, mask in parts.items():
        current = result.loc[mask].astype(str)
        result.loc[mask] = np.where(current.eq(""), label, current + "|" + label)
    return result


def assign_one_policy(df: pd.DataFrame, policy_id: str) -> tuple[pd.Series, pd.Series, pd.Series]:
    external = df["external_risk_signal"]
    unavailable = df["evidence_unavailable_for_suppression"]
    rare_route = df["rare_prefix_origin"] | df["rare_path_signature"] | df["rare_prefix_origin_path"]
    low_visibility_with_signal = df["low_visibility"] & (
        external | df["rare_prefix_origin"] | df["rare_prefix_origin_path"] | df["short_duration"]
    )

    if policy_id == "external_only_aggressive":
        protected = external
        gray = unavailable & ~protected
        suppressed = ~(protected | gray)
    elif policy_id == "novelty_plus_evidence_balanced":
        protected = external | df["rare_prefix_origin_path"] | (
            df["rare_prefix_origin"] & df["rare_path_signature"]
        ) | low_visibility_with_signal
        suppressed = (
            ~protected
            & ~unavailable
            & df["common_nonrare_route"]
            & ~(df["low_visibility"] & df["short_duration"])
        )
        gray = ~(protected | suppressed)
    elif policy_id == "stable_recurrence_suppression":
        protected = external | df["rare_prefix_origin_path"] | low_visibility_with_signal
        suppressed = ~protected & ~unavailable & df["stable_recurrent_route"] & ~df["low_visibility"]
        gray = ~(protected | suppressed)
    elif policy_id == "aggressive_recurrence":
        protected = external | df["rare_prefix_origin_path"] | (df["low_visibility"] & external)
        suppressed = ~protected & ~unavailable & df["common_nonrare_route"]
        gray = ~(protected | suppressed)
    elif policy_id == "visibility_cautious":
        protected = external | rare_route | low_visibility_with_signal
        suppressed = ~protected & ~unavailable & df["stable_recurrent_route"] & ~df["low_visibility"]
        gray = ~(protected | suppressed)
    else:
        raise ValueError(f"unknown policy_id: {policy_id}")

    assignment = pd.Series(ASSIGN_GRAY, index=df.index)
    assignment.loc[protected] = ASSIGN_PROTECTED
    assignment.loc[suppressed] = ASSIGN_SUPPRESSED
    return assignment, protected.astype(bool), suppressed.astype(bool)


def assign_policies(df: pd.DataFrame, config: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, dict[str, pd.Series]]]:
    masks: dict[str, dict[str, pd.Series]] = {}
    for policy in config["policies"]:
        policy_id = policy["policy_id"]
        assignment, protected, suppressed = assign_one_policy(df, policy_id)
        gray = assignment.eq(ASSIGN_GRAY)
        df[f"{policy_id}_assignment"] = assignment
        protected_reasons = reason_string(
            {
                "rpki_risk": df["rpki_risk_signal"],
                "asrel_risk": df["asrel_risk_signal"],
                "well_known_community": df["community_risk_signal"],
                "rare_prefix_origin": df["rare_prefix_origin"],
                "rare_path_signature": df["rare_path_signature"],
                "rare_prefix_origin_path": df["rare_prefix_origin_path"],
                "low_visibility_with_signal": df["low_visibility"]
                & (df["external_risk_signal"] | df["rare_prefix_origin"] | df["rare_prefix_origin_path"] | df["short_duration"]),
            },
            df.index,
        )
        suppressed_reasons = reason_string(
            {
                "no_external_risk": ~df["external_risk_signal"],
                "common_nonrare_route": df["common_nonrare_route"],
                "stable_recurrent_route": df["stable_recurrent_route"],
                "evidence_available": ~df["evidence_unavailable_for_suppression"],
            },
            df.index,
        )
        df[f"{policy_id}_protection_reason_set"] = ""
        df.loc[protected, f"{policy_id}_protection_reason_set"] = protected_reasons.loc[protected]
        df[f"{policy_id}_suppression_reason_set"] = ""
        df.loc[suppressed, f"{policy_id}_suppression_reason_set"] = suppressed_reasons.loc[suppressed]
        masks[policy_id] = {
            "protected": protected,
            "suppressed": suppressed,
            "gray": gray,
        }
    return df, masks


def load_truth(paths: dict[str, Path], events: pd.DataFrame) -> pd.DataFrame:
    truth_cols = existing_columns(
        paths["raw_truth"],
        [
            "raw_record_id",
            "scenario_id",
            "scenario_class",
            "phase_id",
            "attack_role",
            "is_attack_member",
            "is_hard_negative_member",
            "active_change_member",
            "primary_family",
            "attack_subtype",
            "truth_semantics",
        ],
    )
    truth = pd.read_parquet(paths["raw_truth"], columns=truth_cols)
    truth["raw_record_id"] = truth["raw_record_id"].astype(str)
    membership = pd.read_csv(paths["raw_event_membership"])
    membership = membership[["event_id", "raw_record_id"]].drop_duplicates()
    membership["raw_record_id"] = membership["raw_record_id"].astype(str)
    membership["event_id"] = membership["event_id"].astype(str)
    joined = membership.merge(truth, on="raw_record_id", how="left")
    joined["is_attack_member"] = bool_series(joined, "is_attack_member")
    joined["is_hard_negative_member"] = bool_series(joined, "is_hard_negative_member")
    joined["active_change_member"] = bool_series(joined, "active_change_member")

    grouped = joined.groupby("event_id", sort=False)
    labels = grouped.agg(
        injected_member_count=("raw_record_id", "nunique"),
        attack_member_count=("is_attack_member", "sum"),
        hard_negative_member_count=("is_hard_negative_member", "sum"),
        active_change_member_count=("active_change_member", "sum"),
        scenario_id_set=("scenario_id", lambda s: json.dumps(sorted(set(map(str, s.dropna()))))),
        scenario_class_set=("scenario_class", lambda s: json.dumps(sorted(set(map(str, s.dropna()))))),
        attack_subtype_set=("attack_subtype", lambda s: json.dumps(sorted(set(map(str, s.dropna()))))),
        primary_family_set=("primary_family", lambda s: json.dumps(sorted(set(map(str, s.dropna()))))),
    ).reset_index()
    event_counts = events[["event_id", "record_count"]].copy()
    event_counts["event_id"] = event_counts["event_id"].astype(str)
    event_counts["record_count"] = pd.to_numeric(event_counts["record_count"], errors="coerce").fillna(0)
    labels = labels.merge(event_counts, on="event_id", how="left")
    labels["event_record_count"] = labels["record_count"].fillna(labels["injected_member_count"])
    labels["has_scenario_membership"] = labels["injected_member_count"] > 0
    labels["has_active_attack"] = labels["attack_member_count"] > 0
    labels["has_hard_negative"] = (labels["hard_negative_member_count"] > 0) & ~labels["has_active_attack"]
    labels["has_scenario_control"] = (
        labels["has_scenario_membership"]
        & ~labels["has_active_attack"]
        & ~labels["has_hard_negative"]
    )
    labels["mixed_membership"] = labels["event_record_count"] > labels["injected_member_count"]
    labels["population"] = "scenario_control"
    labels.loc[labels["has_active_attack"], "population"] = "active_attack"
    labels.loc[labels["has_hard_negative"], "population"] = "hard_negative"
    labels.loc[labels["mixed_membership"], "population"] = labels["population"] + "_mixed"
    return labels


def attach_truth_for_evaluation(df: pd.DataFrame, truth_labels: pd.DataFrame) -> pd.DataFrame:
    result = df.merge(
        truth_labels.drop(columns=["record_count"], errors="ignore"),
        on="event_id",
        how="left",
    )
    for column in [
        "has_scenario_membership",
        "has_active_attack",
        "has_hard_negative",
        "has_scenario_control",
        "mixed_membership",
    ]:
        result[column] = bool_series(result, column)
    result["population"] = result["population"].fillna("reference_background")
    for column in [
        "injected_member_count",
        "attack_member_count",
        "hard_negative_member_count",
        "active_change_member_count",
    ]:
        result[column] = numeric_series(result, column, 0).astype(int)
    return result


def assignment_counts(assignments: pd.Series) -> dict[str, int]:
    counts = assignments.value_counts().to_dict()
    return {
        ASSIGN_PROTECTED: int(counts.get(ASSIGN_PROTECTED, 0)),
        ASSIGN_GRAY: int(counts.get(ASSIGN_GRAY, 0)),
        ASSIGN_SUPPRESSED: int(counts.get(ASSIGN_SUPPRESSED, 0)),
    }


def population_row(policy_id: str, name: str, frame: pd.DataFrame, assignment_col: str) -> dict[str, Any]:
    counts = assignment_counts(frame[assignment_col])
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
        "suppression_rate": safe_rate(counts[ASSIGN_SUPPRESSED], total),
        "downstream_retention_rate": safe_rate(retained, total),
    }


def compute_policy_outputs(df: pd.DataFrame, config: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    comparison_rows = []
    population_rows = []
    attack_rows = []
    reason_rows = []
    safety_gates = config["safety_gates"]
    feasibility = config["feasibility_gates"]

    active_attack = df[df["has_active_attack"]]
    pure_reference = df[~df["has_scenario_membership"]]
    hard_negative = df[df["has_hard_negative"]]
    scenario_control = df[df["has_scenario_control"]]
    mixed = df[df["mixed_membership"]]
    total = int(len(df))

    for policy in config["policies"]:
        policy_id = policy["policy_id"]
        assignment_col = f"{policy_id}_assignment"
        assignment = df[assignment_col]
        counts = assignment_counts(assignment)
        foreground_count = counts[ASSIGN_PROTECTED] + counts[ASSIGN_GRAY]
        suppressed_attack_count = int(active_attack[assignment_col].eq(ASSIGN_SUPPRESSED).sum())
        downstream_attack_count = int(active_attack[assignment_col].isin([ASSIGN_PROTECTED, ASSIGN_GRAY]).sum())
        protected_attack_count = int(active_attack[assignment_col].eq(ASSIGN_PROTECTED).sum())
        gray_attack_count = int(active_attack[assignment_col].eq(ASSIGN_GRAY).sum())
        active_attack_count = int(len(active_attack))
        pure_ref_count = int(len(pure_reference))
        pure_ref_suppressed = int(pure_reference[assignment_col].eq(ASSIGN_SUPPRESSED).sum())
        gray_count = int(assignment.eq(ASSIGN_GRAY).sum())
        compression_ratio = round(float(total) / float(foreground_count), 6) if foreground_count else None
        attack_retention = safe_rate(downstream_attack_count, active_attack_count)
        background_suppression = safe_rate(pure_ref_suppressed, pure_ref_count)
        gray_rate = safe_rate(gray_count, total)
        safety_pass = (
            suppressed_attack_count == safety_gates["suppressed_attack_count"]
            and attack_retention == safety_gates["attack_retention"]
        )
        feasibility_pass = (
            background_suppression >= feasibility["minimum_reference_background_suppression_rate"]
            and (compression_ratio or 0) >= feasibility["minimum_compression_ratio"]
            and gray_rate <= feasibility["maximum_gray_zone_rate"]
        )
        comparison_rows.append(
            {
                "policy_id": policy_id,
                "description": policy.get("description", ""),
                "total_rows": total,
                "foreground_rows": int(foreground_count),
                "estimated_compression_ratio": compression_ratio,
                "active_attack_event_count": active_attack_count,
                "suppressed_attack_count": suppressed_attack_count,
                "attack_retention": attack_retention,
                "protected_attack_rate": safe_rate(protected_attack_count, active_attack_count),
                "gray_attack_rate": safe_rate(gray_attack_count, active_attack_count),
                "pure_reference_background_count": pure_ref_count,
                "pure_reference_background_suppressed_count": pure_ref_suppressed,
                "pure_reference_background_suppression_rate": background_suppression,
                "gray_zone_rate": gray_rate,
                "hard_negative_suppressed_count": int(hard_negative[assignment_col].eq(ASSIGN_SUPPRESSED).sum()),
                "scenario_control_suppressed_count": int(scenario_control[assignment_col].eq(ASSIGN_SUPPRESSED).sum()),
                "mixed_membership_count": int(len(mixed)),
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
        for keys, group in active_attack.groupby(["attack_subtype_set", "primary_family_set"], dropna=False, sort=False):
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
                        "rate_of_total": safe_rate(count, total),
                    }
                )
    return (
        pd.DataFrame(comparison_rows),
        pd.DataFrame(population_rows),
        pd.DataFrame(attack_rows),
        pd.DataFrame(reason_rows),
    )


def semantic_feature_audit(df: pd.DataFrame) -> pd.DataFrame:
    total = int(len(df))
    rows = []
    for column in [
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
    ]:
        count = int(bool_series(df, column).sum())
        rows.append({"feature": column, "rows": count, "rate": safe_rate(count, total)})
    return pd.DataFrame(rows)


def choose_recommended_policy(comparison: pd.DataFrame) -> str:
    passing = comparison[comparison["overall_pass"]].copy()
    if passing.empty:
        return "none_stop_loss"
    non_aggressive = passing[
        (~passing["policy_id"].eq("external_only_aggressive"))
        & passing["hard_negative_suppressed_count"].eq(0)
        & passing["scenario_control_suppressed_count"].eq(0)
    ].copy()
    if not non_aggressive.empty:
        passing = non_aggressive
    passing = passing.sort_values(
        by=["pure_reference_background_suppression_rate", "estimated_compression_ratio", "gray_zone_rate"],
        ascending=[False, False, True],
    )
    return str(passing.iloc[0]["policy_id"])


def markdown_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "_empty_"
    cols = list(frame.columns)
    lines = [
        "| " + " | ".join(cols) + " |",
        "| " + " | ".join(["---"] * len(cols)) + " |",
    ]
    for row in frame.itertuples(index=False):
        values = [str(value).replace("|", "\\|") for value in row]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def write_report(path: Path, summary: dict[str, Any], comparison: pd.DataFrame, features: pd.DataFrame) -> None:
    lines = [
        "# R-FOREGROUND-0 Candidate-Free Semantic Foreground Audit",
        "",
        "Status: generated by `scripts/audit_r_foreground0_semantic_foreground.py`.",
        "",
        "## Summary",
        "",
        f"- total rows: `{summary['total_rows']}`",
        f"- recommended policy: `{summary['recommended_policy_id']}`",
        f"- any policy passed: `{summary['any_policy_passed']}`",
        f"- best background suppression rate: `{summary['best_background_suppression_rate']}`",
        f"- best compression ratio: `{summary['best_compression_ratio']}`",
        "",
        "## Policy Comparison",
        "",
        markdown_table(comparison),
        "",
        "## Semantic Feature Audit",
        "",
        markdown_table(features),
        "",
        "## Guardrails",
        "",
        "- Candidate flags and candidate reasons are not policy features.",
        "- Truth metadata is evaluation-only and is attached after policy assignment.",
        "- Suppressed background is operational pressure only, not confirmed benign.",
        "- Foreground is not confirmed attack.",
        "- RPKI invalid is not attack truth; RPKI valid is not benign.",
        "- AS-rel diagnostic is not route-leak truth.",
        "- NO_EXPORT presence is not attack truth; absence/unavailable state is not safe.",
        "- This origin-family smoke does not prove multi-attack recall or poisoning/evasion robustness.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_outputs(
    df: pd.DataFrame,
    paths: dict[str, Path],
    config: dict[str, Any],
    sample_size: int,
) -> dict[str, Any]:
    output_dir = paths["output_dir"]
    comparison, population, attack, reasons = compute_policy_outputs(df, config)
    features = semantic_feature_audit(df)
    recommended = choose_recommended_policy(comparison)
    best_background = float(comparison["pure_reference_background_suppression_rate"].max()) if not comparison.empty else 0.0
    best_compression = float(comparison["estimated_compression_ratio"].max()) if not comparison.empty else 0.0
    any_passed = bool(comparison["overall_pass"].any()) if not comparison.empty else False

    comparison.to_csv(output_dir / "r_foreground0_policy_comparison.csv", index=False)
    population.to_csv(output_dir / "r_foreground0_policy_population_audit.csv", index=False)
    attack.to_csv(output_dir / "r_foreground0_policy_attack_retention_audit.csv", index=False)
    reasons.to_csv(output_dir / "r_foreground0_policy_reason_distribution.csv", index=False)
    features.to_csv(output_dir / "r_foreground0_semantic_feature_audit.csv", index=False)

    sample_cols = [
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
        "rare_prefix_origin",
        "rare_prefix_origin_path",
        "stable_recurrent_route",
        "common_nonrare_route",
        "population",
        "has_active_attack",
        "has_hard_negative",
    ]
    for policy in config["policies"]:
        policy_id = policy["policy_id"]
        sample_cols.extend(
            [
                f"{policy_id}_assignment",
                f"{policy_id}_protection_reason_set",
                f"{policy_id}_suppression_reason_set",
            ]
        )
    sample_cols = [column for column in sample_cols if column in df.columns]
    df.loc[:, sample_cols].head(sample_size).to_csv(output_dir / "r_foreground0_assignment_sample.csv", index=False)

    total = int(len(df))
    summary = {
        "phase": "R-FOREGROUND-0",
        "run_id": str(df["run_id"].dropna().iloc[0]) if "run_id" in df and df["run_id"].notna().any() else "",
        "policy_config": str(paths["policy_config"]),
        "total_rows": total,
        "policy_count": int(len(config["policies"])),
        "recommended_policy_id": recommended,
        "any_policy_passed": any_passed,
        "best_background_suppression_rate": round(best_background, 9),
        "best_compression_ratio": round(best_compression, 6),
        "policy_comparison": comparison.to_dict(orient="records"),
        "candidate_free": True,
        "candidate_boundary": config.get("candidate_boundary", ""),
        "allowed_claim": "Candidate-free semantic foreground audit result only.",
        "forbidden_claims": config.get("forbidden_claims", []),
        "recommended_next_step": (
            "promote the best passing policy to R-FOREGROUND-1 smoke"
            if any_passed
            else "stop-loss: repair semantic evidence/novelty features before foreground promotion"
        ),
    }
    write_json(output_dir / "r_foreground0_summary.json", summary)
    write_report(output_dir / "r_foreground0_report.md", summary, comparison, features)
    return summary


def main() -> None:
    args = parse_args()
    paths = resolve_paths(args)
    config = read_json(paths["policy_config"])
    prepare_output_dir(paths["output_dir"], args.overwrite)
    df = load_events(paths)
    df = attach_evidence(df, paths)
    df = compute_semantic_features(df, config)
    df, _ = assign_policies(df, config)
    truth_labels = load_truth(paths, df)
    df = attach_truth_for_evaluation(df, truth_labels)
    summary = write_outputs(df, paths, config, args.sample_size)
    print(json.dumps(summary, indent=2, sort_keys=True, default=json_default))
    raise SystemExit(0)


if __name__ == "__main__":
    main()
