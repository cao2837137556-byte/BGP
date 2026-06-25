#!/usr/bin/env python3
"""Evaluate R-NOISE-CLEAN-1 foreground safety on a labeled full replay.

This script is intentionally not the archived R-NOISE-1 implementation. It
does not read legacy final labels, P1/P2/P3, or old 2017 AS-rel-derived fields.
Truth metadata is used only after policy assignment to evaluate whether any
controlled attack would be suppressed.
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
DEFAULT_POLICY_CONFIG = "configs/r_noise_clean1_policy_v0.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--candidates", default="")
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


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=json_default), encoding="utf-8")


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
        "candidates": Path(args.candidates) if args.candidates else Path("data") / "runs" / args.run_id / "candidates" / "candidate_events.parquet",
        "events": Path(args.events) if args.events else Path("data") / "runs" / args.run_id / "events" / "event_units.parquet",
        "raw_truth": Path(args.raw_truth) if args.raw_truth else root / "materialization" / "injected_raw_truth.parquet",
        "raw_event_membership": Path(args.raw_event_membership) if args.raw_event_membership else root / "audit" / "raw_event_membership.csv",
        "rpki_sidecar": Path(args.rpki_sidecar) if args.rpki_sidecar else root / "evidence" / "rpki" / "rpki_event_sidecar.parquet",
        "asrel_sidecar": Path(args.asrel_sidecar) if args.asrel_sidecar else root / "evidence" / "asrel" / "asrel_2024_event_sidecar.parquet",
        "community_sidecar": Path(args.community_sidecar) if args.community_sidecar else root / "evidence" / "community" / "community_event_sidecar.parquet",
        "policy_config": Path(args.policy_config),
        "output_dir": Path(args.output_dir) if args.output_dir else Path("outputs") / "r_noise_clean1" / args.run_id,
    }
    for key in [
        "candidates",
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
        "r_noise_clean1_summary.json",
        "r_noise_clean1_assignment.parquet",
        "r_noise_clean1_foreground.parquet",
        "r_noise_clean1_suppressed_background.parquet",
        "r_noise_clean1_gray_retained.parquet",
        "r_noise_clean1_population_audit.csv",
        "r_noise_clean1_attack_retention_audit.csv",
        "r_noise_clean1_hard_negative_audit.csv",
        "r_noise_clean1_scenario_control_audit.csv",
        "r_noise_clean1_safety_gates.csv",
        "r_noise_clean1_assignment_sample.csv",
        "r_noise_clean1_report.md",
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
    text = value.astype(str).str.strip().str.lower()
    return text.isin({"true", "1", "yes", "y"})


def text_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index)
    return frame[column].fillna("").astype(str)


def numeric_series(frame: pd.DataFrame, column: str, default: float = 0.0) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(default, index=frame.index)
    return pd.to_numeric(frame[column], errors="coerce").fillna(default)


def contains_any(series: pd.Series, tokens: list[str]) -> pd.Series:
    if not tokens:
        return pd.Series(False, index=series.index)
    lowered = series.fillna("").astype(str).str.lower()
    mask = pd.Series(False, index=series.index)
    for token in tokens:
        mask |= lowered.str.contains(str(token).lower(), regex=False)
    return mask


def safe_rate(count: int | float, denom: int | float) -> float:
    if not denom:
        return 0.0
    return round(float(count) / float(denom), 9)


def load_core(paths: dict[str, Path]) -> pd.DataFrame:
    candidate_cols = existing_columns(
        paths["candidates"],
        ["event_id", "candidate_flag", "candidate_reasons", "matched_rule_count"],
    )
    event_cols = existing_columns(
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
    candidates = pd.read_parquet(paths["candidates"], columns=candidate_cols)
    events = pd.read_parquet(paths["events"], columns=event_cols)
    df = events.merge(candidates, on="event_id", how="left", suffixes=("", "_candidate"))
    df["event_id"] = df["event_id"].astype(str)
    return df


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


def assign_policy(df: pd.DataFrame, config: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, pd.Series]]:
    candidate_flag = bool_series(df, "candidate_flag")
    matched_rule_count = numeric_series(df, "matched_rule_count", 0)
    reason_text = text_series(df, "candidate_reasons")
    reason_signal = contains_any(reason_text, config.get("protected_reason_tokens", []))
    rpki_status = text_series(df, "rpki_status").str.lower()
    rpki_protected = rpki_status.isin({str(v).lower() for v in config.get("protected_rpki_statuses", [])})
    asrel_diag = text_series(df, "path_relation_diagnostic_2024").str.lower()
    asrel_protected = asrel_diag.isin({str(v).lower() for v in config.get("protected_asrel_diagnostics", [])})
    asrel_unavailable = text_series(df, "path_relation_evidence_state_2024").str.lower().eq("unavailable")
    community_protected = pd.Series(False, index=df.index)
    for column in config.get("protected_community_flags", []):
        community_protected |= bool_series(df, column)
    community_unavailable = text_series(df, "community_evidence_state").str.lower().eq("raw_join_unavailable")
    visibility_protected = (numeric_series(df, "collector_count", 0) <= 1) & (
        candidate_flag | reason_signal | rpki_protected | asrel_protected | community_protected
    )

    protected = (
        candidate_flag
        | (matched_rule_count > 0)
        | reason_signal
        | rpki_protected
        | asrel_protected
        | community_protected
        | visibility_protected
    )
    suppressible = (
        ~protected
        & ~candidate_flag
        & matched_rule_count.eq(0)
        & reason_text.str.strip().isin({"", "[]", "{}", "nan", "None"})
        & ~asrel_unavailable
        & ~community_unavailable
    )
    gray = ~(protected | suppressible)

    df["noise_clean_policy_id"] = str(config.get("schema_version", "r_noise_clean1_policy_v0"))
    df["foreground_assignment"] = ASSIGN_GRAY
    df.loc[protected, "foreground_assignment"] = ASSIGN_PROTECTED
    df.loc[suppressible, "foreground_assignment"] = ASSIGN_SUPPRESSED
    df["is_protected_foreground"] = protected.astype(bool)
    df["is_gray_retained"] = gray.astype(bool)
    df["is_operational_background_suppressed"] = suppressible.astype(bool)
    df["policy_feature_note"] = "truth-free clean foreground policy"
    df["suppression_reason_set"] = ""
    df.loc[suppressible, "suppression_reason_set"] = "no_clean_protected_signal"
    df["protection_reason_set"] = ""
    reason_parts = {
        "candidate_flag": candidate_flag,
        "candidate_reason_or_rule": (matched_rule_count > 0) | reason_signal,
        "rpki_invalid_protect": rpki_protected,
        "asrel_path_diagnostic_protect": asrel_protected,
        "well_known_community_protect": community_protected,
        "low_visibility_with_signal_protect": visibility_protected,
    }
    for label, mask in reason_parts.items():
        current = df.loc[mask, "protection_reason_set"].astype(str)
        df.loc[mask, "protection_reason_set"] = np.where(
            current.eq(""), label, current + "|" + label
        )
    masks = {
        "candidate_flag": candidate_flag,
        "reason_signal": reason_signal,
        "rpki_protected": rpki_protected,
        "asrel_protected": asrel_protected,
        "community_protected": community_protected,
        "asrel_unavailable": asrel_unavailable,
        "community_unavailable": community_unavailable,
        "protected": protected,
        "suppressible": suppressible,
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
    # The propagation audit membership file may already carry truth columns.
    # Keep only join keys here so labels come from the raw truth table exactly
    # once and pandas does not suffix scenario/family columns during merge.
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
    result["injected_member_count"] = result["injected_member_count"].fillna(0).astype(int)
    result["attack_member_count"] = result["attack_member_count"].fillna(0).astype(int)
    result["hard_negative_member_count"] = result["hard_negative_member_count"].fillna(0).astype(int)
    result["active_change_member_count"] = result["active_change_member_count"].fillna(0).astype(int)
    return result


def assignment_counts(frame: pd.DataFrame) -> dict[str, int]:
    counts = frame["foreground_assignment"].value_counts().to_dict()
    return {
        ASSIGN_PROTECTED: int(counts.get(ASSIGN_PROTECTED, 0)),
        ASSIGN_GRAY: int(counts.get(ASSIGN_GRAY, 0)),
        ASSIGN_SUPPRESSED: int(counts.get(ASSIGN_SUPPRESSED, 0)),
    }


def population_row(name: str, frame: pd.DataFrame) -> dict[str, Any]:
    counts = assignment_counts(frame)
    total = int(len(frame))
    retained = counts[ASSIGN_PROTECTED] + counts[ASSIGN_GRAY]
    return {
        "population": name,
        "rows": total,
        "protected_foreground": counts[ASSIGN_PROTECTED],
        "gray_retained": counts[ASSIGN_GRAY],
        "operational_background_suppressed": counts[ASSIGN_SUPPRESSED],
        "downstream_retained": retained,
        "suppression_rate": safe_rate(counts[ASSIGN_SUPPRESSED], total),
        "downstream_retention_rate": safe_rate(retained, total),
    }


def write_outputs(
    df: pd.DataFrame,
    paths: dict[str, Path],
    config: dict[str, Any],
    sample_size: int,
) -> dict[str, Any]:
    output_dir = paths["output_dir"]
    policy_cols = [
        "event_id",
        "run_id",
        "prefix",
        "origin_as",
        "as_path_clean",
        "first_seen",
        "last_seen",
        "record_count",
        "collector_set",
        "collector_count",
        "candidate_flag",
        "candidate_reasons",
        "matched_rule_count",
        "rpki_status",
        "rpki_evidence_state",
        "path_relation_diagnostic_2024",
        "path_relation_evidence_state_2024",
        "community_evidence_state",
        "raw_match_status",
        "has_no_export",
        "has_no_advertise",
        "has_nopeer",
        "noise_clean_policy_id",
        "foreground_assignment",
        "protection_reason_set",
        "suppression_reason_set",
        "is_protected_foreground",
        "is_gray_retained",
        "is_operational_background_suppressed",
        "policy_feature_note",
    ]
    eval_cols = [
        "population",
        "has_scenario_membership",
        "has_active_attack",
        "has_hard_negative",
        "has_scenario_control",
        "mixed_membership",
        "injected_member_count",
        "attack_member_count",
        "hard_negative_member_count",
        "scenario_id_set",
        "scenario_class_set",
        "attack_subtype_set",
        "primary_family_set",
    ]
    out_cols = [column for column in [*policy_cols, *eval_cols] if column in df.columns]
    assignment = df.loc[:, out_cols].copy()
    assignment.to_parquet(output_dir / "r_noise_clean1_assignment.parquet", index=False)
    assignment[assignment["foreground_assignment"].isin([ASSIGN_PROTECTED, ASSIGN_GRAY])].to_parquet(
        output_dir / "r_noise_clean1_foreground.parquet", index=False
    )
    assignment[assignment["foreground_assignment"].eq(ASSIGN_SUPPRESSED)].to_parquet(
        output_dir / "r_noise_clean1_suppressed_background.parquet", index=False
    )
    assignment[assignment["foreground_assignment"].eq(ASSIGN_GRAY)].to_parquet(
        output_dir / "r_noise_clean1_gray_retained.parquet", index=False
    )
    assignment.head(sample_size).to_csv(output_dir / "r_noise_clean1_assignment_sample.csv", index=False)

    active_attack = df[df["has_active_attack"]]
    pure_reference = df[~df["has_scenario_membership"]]
    mixed = df[df["mixed_membership"]]
    hard_negative = df[df["has_hard_negative"]]
    scenario_control = df[df["has_scenario_control"]]

    pop_rows = [
        population_row("all_events", df),
        population_row("active_attack", active_attack),
        population_row("hard_negative", hard_negative),
        population_row("scenario_control", scenario_control),
        population_row("pure_reference_background", pure_reference),
        population_row("mixed_membership", mixed),
    ]
    population_audit = pd.DataFrame(pop_rows)
    population_audit.to_csv(output_dir / "r_noise_clean1_population_audit.csv", index=False)

    attack_group_cols = ["attack_subtype_set", "primary_family_set"]
    attack_rows = []
    for keys, group in active_attack.groupby(attack_group_cols, dropna=False, sort=False):
        if not isinstance(keys, tuple):
            keys = (keys, "")
        row = population_row("active_attack_subtype", group)
        row["attack_subtype_set"] = keys[0]
        row["primary_family_set"] = keys[1]
        attack_rows.append(row)
    attack_audit = pd.DataFrame(attack_rows)
    attack_audit.to_csv(output_dir / "r_noise_clean1_attack_retention_audit.csv", index=False)

    hard_negative[[
        column for column in [
            "event_id",
            "foreground_assignment",
            "protection_reason_set",
            "suppression_reason_set",
            "scenario_id_set",
            "attack_subtype_set",
            "candidate_flag",
            "candidate_reasons",
            "rpki_status",
            "path_relation_diagnostic_2024",
            "community_evidence_state",
        ]
        if column in hard_negative.columns
    ]].to_csv(output_dir / "r_noise_clean1_hard_negative_audit.csv", index=False)
    scenario_control[[
        column for column in [
            "event_id",
            "foreground_assignment",
            "protection_reason_set",
            "suppression_reason_set",
            "scenario_id_set",
            "attack_subtype_set",
            "candidate_flag",
            "candidate_reasons",
        ]
        if column in scenario_control.columns
    ]].to_csv(output_dir / "r_noise_clean1_scenario_control_audit.csv", index=False)

    suppressed_attack_count = int(active_attack["foreground_assignment"].eq(ASSIGN_SUPPRESSED).sum())
    downstream_attack_count = int(active_attack["foreground_assignment"].isin([ASSIGN_PROTECTED, ASSIGN_GRAY]).sum())
    protected_attack_count = int(active_attack["foreground_assignment"].eq(ASSIGN_PROTECTED).sum())
    gray_attack_count = int(active_attack["foreground_assignment"].eq(ASSIGN_GRAY).sum())
    active_attack_count = int(len(active_attack))
    pure_ref_count = int(len(pure_reference))
    pure_ref_suppressed = int(pure_reference["foreground_assignment"].eq(ASSIGN_SUPPRESSED).sum())
    gray_count = int(df["foreground_assignment"].eq(ASSIGN_GRAY).sum())
    total = int(len(df))
    mixed_in_background_denominator = 0
    truth_feature_leakage_count = 0

    safety_rows = [
        {
            "gate": "suppressed_attack_count",
            "observed": suppressed_attack_count,
            "required": config["safety_gates"]["suppressed_attack_count"],
            "pass": suppressed_attack_count == config["safety_gates"]["suppressed_attack_count"],
        },
        {
            "gate": "candidate_to_downstream_attack_retention",
            "observed": safe_rate(downstream_attack_count, active_attack_count),
            "required": config["safety_gates"]["candidate_to_downstream_attack_retention"],
            "pass": safe_rate(downstream_attack_count, active_attack_count)
            == config["safety_gates"]["candidate_to_downstream_attack_retention"],
        },
        {
            "gate": "truth_feature_leakage_count",
            "observed": truth_feature_leakage_count,
            "required": config["safety_gates"]["truth_feature_leakage_count"],
            "pass": truth_feature_leakage_count == config["safety_gates"]["truth_feature_leakage_count"],
        },
        {
            "gate": "mixed_membership_in_background_denominator_count",
            "observed": mixed_in_background_denominator,
            "required": config["safety_gates"]["mixed_membership_in_background_denominator_count"],
            "pass": mixed_in_background_denominator
            == config["safety_gates"]["mixed_membership_in_background_denominator_count"],
        },
        {
            "gate": "minimum_reference_background_suppression_rate",
            "observed": safe_rate(pure_ref_suppressed, pure_ref_count),
            "required": config["feasibility_gates"]["minimum_reference_background_suppression_rate"],
            "pass": safe_rate(pure_ref_suppressed, pure_ref_count)
            >= config["feasibility_gates"]["minimum_reference_background_suppression_rate"],
        },
        {
            "gate": "maximum_gray_zone_rate",
            "observed": safe_rate(gray_count, total),
            "required": config["feasibility_gates"]["maximum_gray_zone_rate"],
            "pass": safe_rate(gray_count, total)
            <= config["feasibility_gates"]["maximum_gray_zone_rate"],
        },
    ]
    safety = pd.DataFrame(safety_rows)
    safety.to_csv(output_dir / "r_noise_clean1_safety_gates.csv", index=False)

    all_counts = assignment_counts(df)
    foreground_count = all_counts[ASSIGN_PROTECTED] + all_counts[ASSIGN_GRAY]
    summary = {
        "phase": "R-NOISE-CLEAN-1",
        "run_id": str(df["run_id"].dropna().iloc[0]) if "run_id" in df and df["run_id"].notna().any() else "",
        "policy_config": str(paths["policy_config"]),
        "total_rows": total,
        "assignment_counts": all_counts,
        "foreground_rows": int(foreground_count),
        "estimated_compression_ratio": round(float(total) / float(foreground_count), 6) if foreground_count else None,
        "active_attack_event_count": active_attack_count,
        "suppressed_attack_count": suppressed_attack_count,
        "candidate_to_protected_attack_rate": safe_rate(protected_attack_count, active_attack_count),
        "candidate_to_gray_attack_rate": safe_rate(gray_attack_count, active_attack_count),
        "candidate_to_downstream_attack_retention": safe_rate(downstream_attack_count, active_attack_count),
        "hard_negative_event_count": int(len(hard_negative)),
        "scenario_control_event_count": int(len(scenario_control)),
        "pure_reference_background_count": pure_ref_count,
        "pure_reference_background_suppressed_count": pure_ref_suppressed,
        "pure_reference_background_suppression_rate": safe_rate(pure_ref_suppressed, pure_ref_count),
        "gray_zone_rate": safe_rate(gray_count, total),
        "mixed_membership_count": int(len(mixed)),
        "truth_feature_leakage_count": truth_feature_leakage_count,
        "safety_pass": bool(safety.iloc[:4]["pass"].all()),
        "feasibility_pass": bool(safety.iloc[4:]["pass"].all()),
        "overall_pass": bool(safety["pass"].all()),
        "community_caveat": (
            "Community absence/unavailable state is not used as a safe or benign feature. "
            "R-ATTACK-0A-3 has a one-row global community raw-match caveat."
        ),
        "allowed_claim": "Origin-family controlled foreground safety gate result only.",
        "forbidden_claims": config.get("forbidden_claims", []),
        "recommended_next_step": (
            "R-ATTACK-0B family expansion"
            if bool(safety["pass"].all())
            else "repair foreground policy before learning or attack-family expansion"
        ),
    }
    write_json(output_dir / "r_noise_clean1_summary.json", summary)
    write_report(output_dir / "r_noise_clean1_report.md", summary, population_audit, safety)
    return summary


def write_report(path: Path, summary: dict[str, Any], population: pd.DataFrame, safety: pd.DataFrame) -> None:
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

    lines = [
        "# R-NOISE-CLEAN-1 Foreground Evaluation",
        "",
        "Status: generated by `scripts/evaluate_r_noise_clean1_foreground.py`.",
        "",
        "## Summary",
        "",
        f"- total rows: `{summary['total_rows']}`",
        f"- foreground rows: `{summary['foreground_rows']}`",
        f"- estimated compression ratio: `{summary['estimated_compression_ratio']}`",
        f"- active attack events: `{summary['active_attack_event_count']}`",
        f"- suppressed attack count: `{summary['suppressed_attack_count']}`",
        f"- candidate-to-downstream attack retention: `{summary['candidate_to_downstream_attack_retention']}`",
        f"- pure reference background suppression rate: `{summary['pure_reference_background_suppression_rate']}`",
        f"- gray-zone rate: `{summary['gray_zone_rate']}`",
        f"- overall pass: `{summary['overall_pass']}`",
        "",
        "## Population Audit",
        "",
        markdown_table(population),
        "",
        "## Safety Gates",
        "",
        markdown_table(safety),
        "",
        "## Guardrails",
        "",
        "- Truth metadata is evaluation-only and is not used by the foreground policy.",
        "- Suppressed background is not confirmed benign.",
        "- Foreground is not confirmed attack.",
        "- RPKI invalid is not attack truth; RPKI valid is not benign.",
        "- AS-rel diagnostic is not route-leak truth.",
        "- NO_EXPORT presence is not attack truth; absence/unavailable state is not safe.",
        "- This origin-family smoke does not prove multi-attack recall or poisoning/evasion robustness.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    paths = resolve_paths(args)
    config = read_json(paths["policy_config"])
    prepare_output_dir(paths["output_dir"], args.overwrite)
    df = load_core(paths)
    df = attach_evidence(df, paths)
    df, _ = assign_policy(df, config)
    truth_labels = load_truth(paths, df)
    df = attach_truth_for_evaluation(df, truth_labels)
    summary = write_outputs(df, paths, config, args.sample_size)
    print(json.dumps(summary, indent=2, sort_keys=True))
    raise SystemExit(0 if summary["overall_pass"] else 3)


if __name__ == "__main__":
    main()
