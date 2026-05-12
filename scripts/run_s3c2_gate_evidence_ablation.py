import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from run_s3c1_visibility_path_plausibility_pilot import (
    RUN_ID_DEFAULT,
    bool_col,
    json_default,
    label_col,
    num_col,
    text_col,
    to_rel_path,
)
from run_s3c1b_penalty_calibration import build_plausibility_frame, match_known_events


OUTPUT_DIR_DEFAULT = "outputs/s3c2_gate_evidence_ablation_smoke_s1a"
CERTAINTY_HIGH_THRESHOLD = 65.0
EVIDENCE_SUPPORT_THRESHOLD = 65.0


VARIANTS: list[dict[str, Any]] = [
    {
        "variant": "variant_default",
        "low_requires_extra": False,
        "medium_requires_extra": False,
        "all_pattern_a_requires_extra": False,
        "medium_force_review": False,
        "pattern_b_verification_only": False,
        "allow_recommend": False,
        "notes": "Original gate/final labels, no S3-C2 adjustment.",
    },
    {
        "variant": "variant_plausibility_gate_soft",
        "low_requires_extra": True,
        "medium_requires_extra": False,
        "all_pattern_a_requires_extra": False,
        "medium_force_review": False,
        "pattern_b_verification_only": False,
        "allow_recommend": True,
        "notes": "Low-plausibility pattern_A needs extra evidence before high.",
    },
    {
        "variant": "variant_plausibility_gate_medium_review",
        "low_requires_extra": True,
        "medium_requires_extra": True,
        "all_pattern_a_requires_extra": False,
        "medium_force_review": True,
        "pattern_b_verification_only": False,
        "allow_recommend": True,
        "notes": "Low/medium pattern_A needs extra evidence; medium is routed to review when unsupported.",
    },
    {
        "variant": "variant_medium_gate_only",
        "low_requires_extra": True,
        "medium_requires_extra": False,
        "all_pattern_a_requires_extra": False,
        "medium_force_review": False,
        "medium_gate_flag_only": True,
        "pattern_b_verification_only": False,
        "allow_recommend": True,
        "notes": "S3-C1b smoke fallback: low requires extra evidence; medium is evidence-only.",
    },
    {
        "variant": "variant_patternB_protect",
        "low_requires_extra": True,
        "medium_requires_extra": False,
        "all_pattern_a_requires_extra": False,
        "medium_force_review": False,
        "pattern_b_verification_only": True,
        "allow_recommend": True,
        "notes": "Pattern_B is never downgraded by plausibility alone; it is verification-only.",
    },
    {
        "variant": "variant_strict_extra_evidence",
        "low_requires_extra": False,
        "medium_requires_extra": False,
        "all_pattern_a_requires_extra": True,
        "medium_force_review": True,
        "pattern_b_verification_only": True,
        "allow_recommend": False,
        "notes": "Strict upper-bound ablation; not recommended for mainline adoption.",
    },
]


def pct(num: float, den: float) -> float:
    return float(num / den) if den else 0.0


def read_s3c1b_recommendation(output_dir: Path, warnings: list[str]) -> dict[str, Any]:
    summary_path = output_dir / "s3c1b_summary.json"
    rec_path = output_dir / "s3c1b_recommended_strategy.json"
    info: dict[str, Any] = {
        "available": False,
        "output_dir": to_rel_path(output_dir),
        "status": "missing",
        "fallback_strategy": "strategy_medium_gate_only",
        "fallback_reason": "S3-C1b full output is pending; S3-C2 scaffold uses a smoke placeholder only.",
    }
    if not summary_path.exists() or not rec_path.exists():
        warnings.append(f"S3-C1b full outputs not found under {to_rel_path(output_dir)}; using scaffold fallback.")
        return info
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        recommendation = json.loads(rec_path.read_text(encoding="utf-8"))
    except Exception as exc:
        warnings.append(f"could not parse S3-C1b outputs under {to_rel_path(output_dir)}: {exc}")
        info["status"] = "parse_failed"
        return info
    info.update(
        {
            "available": True,
            "status": summary.get("status", "unknown"),
            "run_id": summary.get("run_id"),
            "full_run": bool(summary.get("full_run", False)),
            "recommended_strategy": recommendation.get("recommended_strategy"),
            "recommendation_reason": recommendation.get("reason"),
        }
    )
    if not info["full_run"]:
        warnings.append("S3-C1b output exists but is not full_run; treating recommendation as non-final.")
    return info


def original_final_label(df: pd.DataFrame) -> pd.Series:
    labels = label_col(df)
    if labels.fillna("").astype(str).str.len().sum() > 0:
        return labels.replace("", "needs_review")
    gate = text_col(df, "gating_label")
    return pd.Series(
        np.select(
            [gate.eq("likely_malicious"), gate.eq("likely_benign")],
            ["high_priority_alert", "low_priority_or_background"],
            default="needs_review",
        ),
        index=df.index,
    )


def add_gate_evidence_fields(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["original_final_alert_label_s3c2"] = original_final_label(out)
    out["original_gating_label_s3c2"] = text_col(out, "gating_label", "unknown")
    out["path_seen_before_flag"] = bool_col(out, "path_seen_before")
    out["certainty_extra_evidence_flag"] = num_col(out, "certainty_score") >= CERTAINTY_HIGH_THRESHOLD
    out["support_extra_evidence_flag"] = num_col(out, "evidence_support_score") >= EVIDENCE_SUPPORT_THRESHOLD
    out["cross_collector_extra_evidence_flag"] = num_col(out, "collector_count") > 1.0
    out["temporal_extra_evidence_flag"] = num_col(out, "temporal_confirmation_count") > 0.0
    out["history_extra_evidence_flag"] = bool_col(out, "path_seen_before_flag")
    out["gate_extra_evidence_met_base"] = (
        out["certainty_extra_evidence_flag"]
        | out["support_extra_evidence_flag"]
        | out["cross_collector_extra_evidence_flag"]
        | out["temporal_extra_evidence_flag"]
        | out["history_extra_evidence_flag"]
    )
    out["gate_extra_evidence_sources"] = ""
    source_pairs = [
        ("certainty", "certainty_extra_evidence_flag"),
        ("support", "support_extra_evidence_flag"),
        ("cross_collector", "cross_collector_extra_evidence_flag"),
        ("temporal", "temporal_extra_evidence_flag"),
        ("history", "history_extra_evidence_flag"),
    ]
    sources = []
    for source, col in source_pairs:
        sources.append(np.where(out[col].to_numpy(), source, ""))
    source_frame = pd.DataFrame(np.array(sources).T, index=out.index, columns=[p[0] for p in source_pairs])
    out["gate_extra_evidence_sources"] = source_frame.apply(lambda row: "|".join([v for v in row if v]), axis=1)
    return out


def apply_variant(df: pd.DataFrame, variant: dict[str, Any]) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    name = str(variant["variant"])
    pattern_a = bool_col(df, "pattern_A_flag") & ~bool_col(df, "pattern_B_flag")
    pattern_b = bool_col(df, "pattern_B_flag")
    low_a = pattern_a & text_col(df, "plausibility_bucket").eq("low_plausibility")
    medium_a = pattern_a & text_col(df, "plausibility_bucket").eq("medium_plausibility")

    required = pd.Series(False, index=df.index)
    if bool(variant.get("all_pattern_a_requires_extra")):
        required = required | pattern_a
    if bool(variant.get("low_requires_extra")):
        required = required | low_a
    if bool(variant.get("medium_requires_extra")):
        required = required | medium_a

    medium_gate_only = bool(variant.get("medium_gate_flag_only"))
    flag_only = medium_a if medium_gate_only else pd.Series(False, index=df.index)
    pattern_b_verify = pattern_b if bool(variant.get("pattern_b_verification_only")) else pd.Series(False, index=df.index)
    extra_met = bool_col(df, "gate_extra_evidence_met_base")
    unsupported = required & ~extra_met
    original_final = text_col(df, "original_final_alert_label_s3c2", "needs_review")
    original_gate = text_col(df, "original_gating_label_s3c2", "unknown")

    adjusted_final = original_final.copy()
    high_blocked = unsupported & original_final.eq("high_priority_alert")
    adjusted_final.loc[high_blocked] = "needs_review"
    if bool(variant.get("medium_force_review")):
        medium_review = medium_a & ~extra_met & original_final.isin(["high_priority_alert", "needs_review"])
        adjusted_final.loc[medium_review] = "needs_review"

    adjusted_gate = original_gate.copy()
    adjusted_gate.loc[high_blocked & original_gate.eq("likely_malicious")] = "suspicious_but_uncertain"

    reason = pd.Series("no_s3c2_adjustment", index=df.index, dtype="object")
    reason.loc[required & extra_met] = "extra_evidence_met_keep_original"
    reason.loc[low_a & required & ~extra_met] = "pattern_A_low_plausibility_extra_evidence_missing"
    reason.loc[medium_a & required & ~extra_met] = "pattern_A_medium_plausibility_extra_evidence_missing"
    reason.loc[flag_only & reason.eq("no_s3c2_adjustment")] = "pattern_A_medium_plausibility_gate_flag_only"
    reason.loc[pattern_b_verify & reason.eq("no_s3c2_adjustment")] = "pattern_B_verification_only_no_downgrade"
    if name == "variant_default":
        reason = pd.Series("variant_default_no_adjustment", index=df.index, dtype="object")

    out["s3c2_gate_variant"] = name
    out["gate_evidence_flag"] = required | flag_only | pattern_b_verify
    out["gate_extra_evidence_required"] = required
    out["gate_extra_evidence_met"] = extra_met
    out["gate_flag_only"] = flag_only | pattern_b_verify
    out["adjusted_gating_label_s3c2"] = adjusted_gate
    out["adjusted_final_alert_label_s3c2"] = adjusted_final
    out["simulated_gating_label_s3c2"] = adjusted_gate
    out["simulated_final_alert_label_s3c2"] = adjusted_final
    out["adjusted_gate_reason_s3c2"] = reason
    out["simulated_gate_reason_s3c2"] = reason
    out["final_label_changed_s3c2"] = original_final.ne(adjusted_final)
    priority = text_col(df, "calibrated_priority", "unavailable")
    adjusted_priority = priority.copy()
    adjusted_priority.loc[out["final_label_changed_s3c2"] & priority.isin(["P1_high", "P2_review"])] = "requires_incident_recalibration"
    out["adjusted_incident_priority_s3c2"] = adjusted_priority
    out["simulated_incident_priority_s3c2"] = adjusted_priority
    out["high_to_needs_s3c2"] = original_final.eq("high_priority_alert") & adjusted_final.eq("needs_review")
    out["needs_to_low_s3c2"] = original_final.eq("needs_review") & adjusted_final.eq("low_priority_or_background")
    out["pattern_A_controlled_s3c2"] = pattern_a & (out["gate_evidence_flag"] | out["final_label_changed_s3c2"])
    out["pattern_B_verification_flag_s3c2"] = pattern_b_verify
    return out


def label_counts(labels: pd.Series) -> dict[str, int]:
    vc = labels.value_counts(dropna=False).to_dict()
    return {
        "high": int(vc.get("high_priority_alert", 0)),
        "needs": int(vc.get("needs_review", 0)),
        "low": int(vc.get("low_priority_or_background", 0)),
    }


def variant_metrics(df: pd.DataFrame, result: pd.DataFrame, variant: dict[str, Any], known_metrics: dict[str, Any]) -> dict[str, Any]:
    before = text_col(df, "original_final_alert_label_s3c2", "needs_review")
    after = text_col(result, "adjusted_final_alert_label_s3c2", "needs_review")
    before_counts = label_counts(before)
    after_counts = label_counts(after)
    pattern_a = bool_col(df, "pattern_A_flag")
    pattern_b = bool_col(df, "pattern_B_flag")
    p1p2 = text_col(df, "calibrated_priority").isin(["P1_high", "P2_review"]) if "calibrated_priority" in df.columns else pd.Series(False, index=df.index)
    impacted = result["gate_evidence_flag"] | result["final_label_changed_s3c2"]
    p1p2_impacted = p1p2 & impacted
    row: dict[str, Any] = {
        "variant": variant["variant"],
        "notes": variant["notes"],
        "allow_recommend": bool(variant.get("allow_recommend", False)),
        "candidate_rows": int(len(df)),
        "adjusted_high_rows": after_counts["high"],
        "adjusted_needs_rows": after_counts["needs"],
        "adjusted_low_rows": after_counts["low"],
        "high_before": before_counts["high"],
        "needs_before": before_counts["needs"],
        "low_before": before_counts["low"],
        "high_delta": after_counts["high"] - before_counts["high"],
        "needs_delta": after_counts["needs"] - before_counts["needs"],
        "low_delta": after_counts["low"] - before_counts["low"],
        "final_label_changed_rows": int(result["final_label_changed_s3c2"].sum()),
        "gate_evidence_rows": int(result["gate_evidence_flag"].sum()),
        "extra_evidence_required_rows": int(result["gate_extra_evidence_required"].sum()),
        "extra_evidence_missing_rows": int((result["gate_extra_evidence_required"] & ~result["gate_extra_evidence_met"]).sum()),
        "pattern_A_rows": int(pattern_a.sum()),
        "pattern_A_gate_evidence_rows": int((pattern_a & result["gate_evidence_flag"]).sum()),
        "pattern_A_label_changed_rows": int((pattern_a & result["final_label_changed_s3c2"]).sum()),
        "pattern_A_high_delta": int((after[pattern_a].eq("high_priority_alert").sum()) - (before[pattern_a].eq("high_priority_alert").sum())),
        "pattern_A_needs_delta": int((after[pattern_a].eq("needs_review").sum()) - (before[pattern_a].eq("needs_review").sum())),
        "pattern_A_low_delta": int((after[pattern_a].eq("low_priority_or_background").sum()) - (before[pattern_a].eq("low_priority_or_background").sum())),
        "pattern_B_rows": int(pattern_b.sum()),
        "pattern_B_gate_evidence_rows": int((pattern_b & result["gate_evidence_flag"]).sum()),
        "pattern_B_label_changed_rows": int((pattern_b & result["final_label_changed_s3c2"]).sum()),
        "pattern_B_high_delta": int((after[pattern_b].eq("high_priority_alert").sum()) - (before[pattern_b].eq("high_priority_alert").sum())),
        "pattern_B_needs_delta": int((after[pattern_b].eq("needs_review").sum()) - (before[pattern_b].eq("needs_review").sum())),
        "pattern_B_low_delta": int((after[pattern_b].eq("low_priority_or_background").sum()) - (before[pattern_b].eq("low_priority_or_background").sum())),
        "P1_P2_joined_rows": int(p1p2.sum()),
        "P1_P2_affected_rows": int(p1p2_impacted.sum()),
        "touched_p1_p2_incidents": int(df.loc[p1p2_impacted, "incident_id"].nunique()) if "incident_id" in df.columns else 0,
        "touched_p1_incidents": int(df.loc[p1p2_impacted & text_col(df, "calibrated_priority").eq("P1_high"), "incident_id"].nunique()) if "incident_id" in df.columns else 0,
        "touched_p2_incidents": int(df.loc[p1p2_impacted & text_col(df, "calibrated_priority").eq("P2_review"), "incident_id"].nunique()) if "incident_id" in df.columns else 0,
        "known_event_available": known_metrics.get("known_event_available"),
        "known_event_matched_rows": known_metrics.get("known_event_matched_rows"),
        "known_event_retained_count": known_metrics.get("known_event_retained_count"),
        "known_event_regression_count": known_metrics.get("known_event_regression_count"),
    }
    row["high_change_rate"] = pct(abs(row["high_delta"]), row["high_before"])
    row["pattern_A_control_rate"] = pct(row["pattern_A_gate_evidence_rows"] + row["pattern_A_label_changed_rows"], row["pattern_A_rows"])
    return row


def pattern_impact(df: pd.DataFrame, result: pd.DataFrame, variant_name: str, pattern_col: str, pattern_name: str) -> dict[str, Any]:
    mask = bool_col(df, pattern_col)
    before = text_col(df, "original_final_alert_label_s3c2", "needs_review")
    after = text_col(result, "adjusted_final_alert_label_s3c2", "needs_review")
    return {
        "variant": variant_name,
        "pattern_name": pattern_name,
        "rows": int(mask.sum()),
        "gate_evidence_rows": int((mask & result["gate_evidence_flag"]).sum()),
        "label_changed_rows": int((mask & result["final_label_changed_s3c2"]).sum()),
        "extra_evidence_required_rows": int((mask & result["gate_extra_evidence_required"]).sum()),
        "extra_evidence_missing_rows": int((mask & result["gate_extra_evidence_required"] & ~result["gate_extra_evidence_met"]).sum()),
        "high_before": int((mask & before.eq("high_priority_alert")).sum()),
        "high_after": int((mask & after.eq("high_priority_alert")).sum()),
        "needs_before": int((mask & before.eq("needs_review")).sum()),
        "needs_after": int((mask & after.eq("needs_review")).sum()),
        "low_before": int((mask & before.eq("low_priority_or_background")).sum()),
        "low_after": int((mask & after.eq("low_priority_or_background")).sum()),
        "mean_plausibility_score": float(num_col(df.loc[mask], "path_plausibility_score").mean()) if int(mask.sum()) else 0.0,
        "low_plausibility_rows": int((mask & text_col(df, "plausibility_bucket").eq("low_plausibility")).sum()),
        "medium_plausibility_rows": int((mask & text_col(df, "plausibility_bucket").eq("medium_plausibility")).sum()),
        "high_plausibility_rows": int((mask & text_col(df, "plausibility_bucket").eq("high_plausibility")).sum()),
    }


def p1_p2_impact(df: pd.DataFrame, result: pd.DataFrame, variant_name: str) -> dict[str, Any]:
    priority = text_col(df, "calibrated_priority")
    p1p2 = priority.isin(["P1_high", "P2_review"])
    impacted = result["gate_evidence_flag"] | result["final_label_changed_s3c2"]
    selected = p1p2 & impacted
    return {
        "variant": variant_name,
        "p1_p2_rows_joined": int(p1p2.sum()),
        "p1_p2_affected_rows": int(selected.sum()),
        "p1_p2_label_changed_rows": int((selected & result["final_label_changed_s3c2"]).sum()),
        "p1_p2_gate_evidence_rows": int((selected & result["gate_evidence_flag"]).sum()),
        "touched_p1_p2_incidents": int(df.loc[selected, "incident_id"].nunique()) if "incident_id" in df.columns else 0,
        "touched_p1_incidents": int(df.loc[selected & priority.eq("P1_high"), "incident_id"].nunique()) if "incident_id" in df.columns else 0,
        "touched_p2_incidents": int(df.loc[selected & priority.eq("P2_review"), "incident_id"].nunique()) if "incident_id" in df.columns else 0,
    }


def build_event_label_delta(df: pd.DataFrame, result: pd.DataFrame, variant_name: str) -> pd.DataFrame:
    tmp = pd.DataFrame(
        {
            "variant": variant_name,
            "original_final_alert_label": text_col(df, "original_final_alert_label_s3c2", "needs_review"),
            "simulated_final_alert_label_s3c2": text_col(result, "simulated_final_alert_label_s3c2", "needs_review"),
            "pattern_A_flag": bool_col(df, "pattern_A_flag"),
            "pattern_B_flag": bool_col(df, "pattern_B_flag"),
            "p1_p2_flag": text_col(df, "calibrated_priority").isin(["P1_high", "P2_review"]),
            "gate_evidence_flag": result["gate_evidence_flag"],
        },
        index=df.index,
    )
    return (
        tmp.groupby(["variant", "original_final_alert_label", "simulated_final_alert_label_s3c2"], dropna=False)
        .agg(
            rows=("variant", "size"),
            pattern_A_rows=("pattern_A_flag", "sum"),
            pattern_B_rows=("pattern_B_flag", "sum"),
            p1_p2_rows=("p1_p2_flag", "sum"),
            gate_evidence_rows=("gate_evidence_flag", "sum"),
        )
        .reset_index()
    )


def simulate_priority(original_priority: str, simulated_high: float, simulated_needs: float) -> str:
    priority = str(original_priority or "unavailable")
    high = float(simulated_high or 0.0)
    needs = float(simulated_needs or 0.0)
    if priority == "P1_high" and high <= 0:
        return "P2_review" if needs > 0 else "P3_background"
    if priority == "P2_review" and high <= 0 and needs <= 0:
        return "P3_background"
    return priority


def build_incident_priority_outputs(
    df: pd.DataFrame,
    result: pd.DataFrame,
    variant_name: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    base_cols = {"incident_id", "calibrated_priority"}
    if not base_cols.issubset(df.columns):
        empty = pd.DataFrame(
            [
                {
                    "variant": variant_name,
                    "original_priority": "unavailable",
                    "simulated_priority_s3c2": "unavailable",
                    "ticket_count": 0,
                    "member_count_before": 0,
                    "member_count_after": 0,
                    "high_count_before": 0,
                    "high_count_after": 0,
                    "needs_count_before": 0,
                    "needs_count_after": 0,
                    "affected_prefix_count_sum": 0,
                    "affected_prefix_count_max": 0,
                }
            ]
        )
        return empty, {"variant": variant_name, "incident_priority_available": False}

    incident_id = text_col(df, "incident_id")
    member_mask = incident_id.ne("") & incident_id.ne("nan")
    member = df.loc[member_mask].copy()
    if member.empty:
        empty = pd.DataFrame(
            [
                {
                    "variant": variant_name,
                    "original_priority": "unavailable",
                    "simulated_priority_s3c2": "unavailable",
                    "ticket_count": 0,
                    "member_count_before": 0,
                    "member_count_after": 0,
                    "high_count_before": 0,
                    "high_count_after": 0,
                    "needs_count_before": 0,
                    "needs_count_after": 0,
                    "affected_prefix_count_sum": 0,
                    "affected_prefix_count_max": 0,
                }
            ]
        )
        return empty, {"variant": variant_name, "incident_priority_available": False}

    before = text_col(member, "original_final_alert_label_s3c2", "needs_review")
    after = text_col(result.loc[member.index], "simulated_final_alert_label_s3c2", "needs_review")
    tmp = pd.DataFrame(
        {
            "incident_id": text_col(member, "incident_id"),
            "original_priority": text_col(member, "calibrated_priority", "unavailable"),
            "member_count_ticket": num_col(member, "member_count"),
            "high_count_ticket": num_col(member, "high_count"),
            "needs_count_ticket": num_col(member, "needs_count"),
            "affected_prefix_count": num_col(member, "affected_prefix_count"),
            "before_high": before.eq("high_priority_alert").astype("int64"),
            "before_needs": before.eq("needs_review").astype("int64"),
            "after_high": after.eq("high_priority_alert").astype("int64"),
            "after_needs": after.eq("needs_review").astype("int64"),
            "after_low": after.eq("low_priority_or_background").astype("int64"),
            "high_to_needs": (before.eq("high_priority_alert") & after.eq("needs_review")).astype("int64"),
            "high_to_low": (before.eq("high_priority_alert") & after.eq("low_priority_or_background")).astype("int64"),
            "needs_to_low": (before.eq("needs_review") & after.eq("low_priority_or_background")).astype("int64"),
            "label_changed": before.ne(after).astype("int64"),
        }
    )
    incident = (
        tmp.groupby("incident_id", dropna=False)
        .agg(
            original_priority=("original_priority", "first"),
            member_count_ticket=("member_count_ticket", "first"),
            high_count_ticket=("high_count_ticket", "first"),
            needs_count_ticket=("needs_count_ticket", "first"),
            affected_prefix_count=("affected_prefix_count", "first"),
            before_high=("before_high", "sum"),
            before_needs=("before_needs", "sum"),
            after_high=("after_high", "sum"),
            after_needs=("after_needs", "sum"),
            after_low=("after_low", "sum"),
            high_to_needs=("high_to_needs", "sum"),
            high_to_low=("high_to_low", "sum"),
            needs_to_low=("needs_to_low", "sum"),
            label_changed=("label_changed", "sum"),
        )
        .reset_index()
    )
    original_high = incident["high_count_ticket"].where(incident["high_count_ticket"] > 0, incident["before_high"])
    original_needs = incident["needs_count_ticket"].where(incident["needs_count_ticket"] > 0, incident["before_needs"])
    original_member = incident["member_count_ticket"].where(
        incident["member_count_ticket"] > 0,
        original_high + original_needs,
    )
    incident["original_high_count_s3c2"] = original_high
    incident["original_needs_count_s3c2"] = original_needs
    incident["original_member_count_s3c2"] = original_member
    incident["simulated_high_count_s3c2"] = (original_high + incident["after_high"] - incident["before_high"]).clip(lower=0)
    incident["simulated_needs_count_s3c2"] = (original_needs + incident["after_needs"] - incident["before_needs"]).clip(lower=0)
    incident["simulated_member_count_s3c2"] = (
        original_member - incident["high_to_low"] - incident["needs_to_low"]
    ).clip(lower=0)
    incident["simulated_priority_s3c2"] = [
        simulate_priority(priority, high, needs)
        for priority, high, needs in zip(
            incident["original_priority"],
            incident["simulated_high_count_s3c2"],
            incident["simulated_needs_count_s3c2"],
        )
    ]
    incident["variant"] = variant_name

    delta = (
        incident.groupby(["variant", "original_priority", "simulated_priority_s3c2"], dropna=False)
        .agg(
            ticket_count=("incident_id", "nunique"),
            member_count_before=("original_member_count_s3c2", "sum"),
            member_count_after=("simulated_member_count_s3c2", "sum"),
            high_count_before=("original_high_count_s3c2", "sum"),
            high_count_after=("simulated_high_count_s3c2", "sum"),
            needs_count_before=("original_needs_count_s3c2", "sum"),
            needs_count_after=("simulated_needs_count_s3c2", "sum"),
            affected_prefix_count_sum=("affected_prefix_count", "sum"),
            affected_prefix_count_max=("affected_prefix_count", "max"),
            label_changed_member_rows=("label_changed", "sum"),
        )
        .reset_index()
    )

    before_p1 = incident["original_priority"].eq("P1_high")
    before_p2 = incident["original_priority"].eq("P2_review")
    before_p1p2 = before_p1 | before_p2
    after_p1 = incident["simulated_priority_s3c2"].eq("P1_high")
    after_p2 = incident["simulated_priority_s3c2"].eq("P2_review")
    after_p1p2 = after_p1 | after_p2
    p1_to_p2 = before_p1 & after_p2

    burden = {
        "variant": variant_name,
        "incident_priority_available": True,
        "p1_ticket_before": int(before_p1.sum()),
        "p1_ticket_after": int(after_p1.sum()),
        "p2_ticket_before": int(before_p2.sum()),
        "p2_ticket_after": int(after_p2.sum()),
        "p1_p2_ticket_before": int(before_p1p2.sum()),
        "p1_p2_ticket_after": int(after_p1p2.sum()),
        "p1_p2_ticket_delta": int(after_p1p2.sum() - before_p1p2.sum()),
        "p1_to_p2_ticket_count": int(p1_to_p2.sum()),
        "p1_p2_member_before": float(incident.loc[before_p1p2, "original_member_count_s3c2"].sum()),
        "p1_p2_member_after": float(incident.loc[after_p1p2, "simulated_member_count_s3c2"].sum()),
        "p1_p2_high_before": float(incident.loc[before_p1p2, "original_high_count_s3c2"].sum()),
        "p1_p2_high_after": float(incident.loc[after_p1p2, "simulated_high_count_s3c2"].sum()),
        "p1_p2_needs_before": float(incident.loc[before_p1p2, "original_needs_count_s3c2"].sum()),
        "p1_p2_needs_after": float(incident.loc[after_p1p2, "simulated_needs_count_s3c2"].sum()),
        "p1_to_p2_member_count": float(incident.loc[p1_to_p2, "original_member_count_s3c2"].sum()),
    }
    burden["p1_p2_member_delta"] = burden["p1_p2_member_after"] - burden["p1_p2_member_before"]
    burden["p1_p2_high_delta"] = burden["p1_p2_high_after"] - burden["p1_p2_high_before"]
    burden["p1_p2_needs_delta"] = burden["p1_p2_needs_after"] - burden["p1_p2_needs_before"]
    return delta, burden


def build_review_subtype_distribution(df: pd.DataFrame, result: pd.DataFrame, variant_name: str) -> pd.DataFrame:
    after = text_col(result, "simulated_final_alert_label_s3c2", "needs_review")
    before = text_col(df, "original_final_alert_label_s3c2", "needs_review")
    review = after.eq("needs_review")
    reason = text_col(df, "candidate_reasons") + "|" + text_col(df, "dominant_reason_signature")
    subtype = pd.Series("unknown_review", index=df.index, dtype="object")
    route_leak = text_col(df, "family").eq("route_leak_like") | reason.str.contains("route_leak", case=False, regex=False)
    background_fanout = num_col(df, "affected_prefix_count") >= 100.0
    low_visibility = bool_col(df, "pattern_A_flag") | bool_col(df, "single_collector_flag") | bool_col(df, "low_visibility_flag") | bool_col(df, "short_lived_flag")
    pattern_b = bool_col(df, "pattern_B_flag")
    high_to_needs = before.eq("high_priority_alert") & after.eq("needs_review")
    subtype.loc[low_visibility] = "low_visibility_review"
    subtype.loc[background_fanout] = "background_fanout_review"
    subtype.loc[route_leak] = "route_leak_like_review"
    subtype.loc[pattern_b] = "pattern_B_verification_review"
    subtype.loc[high_to_needs] = "gate_evidence_missing_review"
    tmp = pd.DataFrame(
        {
            "variant": variant_name,
            "review_subtype": subtype[review],
            "original_final_alert_label": before[review],
            "pattern_A_flag": bool_col(df, "pattern_A_flag")[review],
            "pattern_B_flag": bool_col(df, "pattern_B_flag")[review],
            "p1_p2_flag": text_col(df, "calibrated_priority").isin(["P1_high", "P2_review"])[review],
            "gate_evidence_flag": result["gate_evidence_flag"][review],
        }
    )
    if tmp.empty:
        return pd.DataFrame(
            columns=[
                "variant",
                "review_subtype",
                "original_final_alert_label",
                "rows",
                "pattern_A_rows",
                "pattern_B_rows",
                "p1_p2_rows",
                "gate_evidence_rows",
            ]
        )
    return (
        tmp.groupby(["variant", "review_subtype", "original_final_alert_label"], dropna=False)
        .agg(
            rows=("variant", "size"),
            pattern_A_rows=("pattern_A_flag", "sum"),
            pattern_B_rows=("pattern_B_flag", "sum"),
            p1_p2_rows=("p1_p2_flag", "sum"),
            gate_evidence_rows=("gate_evidence_flag", "sum"),
        )
        .reset_index()
    )


def known_variant_rows(
    df: pd.DataFrame,
    result: pd.DataFrame,
    variant_name: str,
    known_base: pd.DataFrame,
    known_info: dict[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if not known_info.get("available"):
        out = known_base.copy()
        out["variant"] = variant_name
        return out, {
            "known_event_available": False,
            "known_event_matched_rows": None,
            "known_event_retained_count": None,
            "known_event_regression_count": None,
        }
    rows = []
    known_mask = known_info.get("known_mask", pd.Series(False, index=df.index))
    before = text_col(df, "original_final_alert_label_s3c2", "needs_review")
    after = text_col(result, "adjusted_final_alert_label_s3c2", "needs_review")
    regress = known_mask & (
        (before.eq("high_priority_alert") & ~after.eq("high_priority_alert"))
        | (before.eq("needs_review") & after.eq("low_priority_or_background"))
    )
    for _, row in known_base.iterrows():
        mask = known_info["event_masks"].get(str(row["slug"]), pd.Series(False, index=df.index))
        rows.append(
            {
                **row.to_dict(),
                "variant": variant_name,
                "gate_evidence_rows": int((mask & result["gate_evidence_flag"]).sum()),
                "label_changed_rows": int((mask & result["final_label_changed_s3c2"]).sum()),
                "regression_rows": int((mask & regress).sum()),
                "retained_rows": int(mask.sum() - (mask & regress).sum()),
            }
        )
    return pd.DataFrame(rows), {
        "known_event_available": True,
        "known_event_matched_rows": int(known_mask.sum()),
        "known_event_retained_count": int(known_mask.sum() - regress.sum()),
        "known_event_regression_count": int(regress.sum()),
    }


def choose_recommended_variant(comparison: pd.DataFrame, s3c1b_info: dict[str, Any]) -> dict[str, Any]:
    candidates = comparison[(comparison["allow_recommend"]) & (comparison["pattern_B_label_changed_rows"] == 0)].copy()
    if "known_event_available" in candidates.columns and candidates["known_event_available"].fillna(False).any():
        candidates = candidates[candidates["known_event_regression_count"].fillna(0) <= 0]
    if "p1_p2_ticket_delta" in candidates.columns:
        candidates = candidates[pd.to_numeric(candidates["p1_p2_ticket_delta"], errors="coerce").fillna(0) <= 0]
    if "p1_p2_member_delta" in candidates.columns:
        candidates = candidates[pd.to_numeric(candidates["p1_p2_member_delta"], errors="coerce").fillna(0) <= 0]
    if candidates.empty:
        row = comparison[comparison["variant"] == "variant_plausibility_gate_soft"].iloc[0].to_dict()
        return {
            "recommended_variant": row["variant"],
            "status": "fallback",
            "reason": "No candidate survived protection filters; falling back to the soft gate evidence variant.",
            "metrics": row,
        }

    preferred = [
        "variant_medium_gate_only",
        "variant_plausibility_gate_soft",
        "variant_patternB_protect",
        "variant_plausibility_gate_medium_review",
    ]
    if s3c1b_info.get("available") and s3c1b_info.get("recommended_strategy") == "strategy_gate_only":
        preferred = ["variant_plausibility_gate_soft", "variant_patternB_protect", "variant_medium_gate_only"]

    for name in preferred:
        subset = candidates[candidates["variant"] == name]
        if subset.empty:
            continue
        row = subset.iloc[0]
        if int(row["pattern_A_gate_evidence_rows"]) + int(row["pattern_A_label_changed_rows"]) <= 0:
            continue
        needs_growth_rate = pct(max(float(row.get("needs_delta", 0.0)), 0.0), float(row.get("needs_before", 0.0)))
        if float(row["high_change_rate"]) <= 0.35 and needs_growth_rate <= 0.35:
            return {
                "recommended_variant": name,
                "status": "scaffold_recommendation",
                "reason": "Best scaffold balance: controls pattern_A through gate evidence, protects pattern_B, and avoids direct score replacement.",
                "metrics": row.to_dict(),
            }

    row = candidates.sort_values(["pattern_B_label_changed_rows", "high_change_rate", "final_label_changed_rows"]).iloc[0].to_dict()
    return {
        "recommended_variant": row["variant"],
        "status": "scaffold_recommendation",
        "reason": "Chosen by minimal high-label movement under pattern_B and known-event filters.",
        "metrics": row,
    }


def build_top_adjusted_cases(df: pd.DataFrame, result: pd.DataFrame, variant_name: str, limit: int = 2000) -> pd.DataFrame:
    cols = [
        "event_id",
        "run_id",
        "prefix",
        "origin_as",
        "as_path_clean",
        "risk_score",
        "risk_bucket",
        "original_final_alert_label_s3c2",
        "path_plausibility_score",
        "plausibility_bucket",
        "pattern_A_flag",
        "pattern_B_flag",
        "certainty_score",
        "evidence_support_score",
        "collector_count",
        "temporal_confirmation_count",
        "path_seen_before_flag",
        "gate_extra_evidence_sources",
        "calibrated_priority",
    ]
    mask = result["gate_evidence_flag"] | result["final_label_changed_s3c2"]
    out = df.loc[mask, [c for c in cols if c in df.columns]].head(limit).copy()
    if out.empty:
        return out
    out["s3c2_gate_variant"] = variant_name
    out["adjusted_final_alert_label_s3c2"] = result.loc[out.index, "adjusted_final_alert_label_s3c2"]
    out["simulated_final_alert_label_s3c2"] = result.loc[out.index, "simulated_final_alert_label_s3c2"]
    out["adjusted_incident_priority_s3c2"] = result.loc[out.index, "adjusted_incident_priority_s3c2"]
    out["simulated_incident_priority_s3c2"] = result.loc[out.index, "simulated_incident_priority_s3c2"]
    out["adjusted_gate_reason_s3c2"] = result.loc[out.index, "adjusted_gate_reason_s3c2"]
    out["simulated_gate_reason_s3c2"] = result.loc[out.index, "simulated_gate_reason_s3c2"]
    out["gate_extra_evidence_required"] = result.loc[out.index, "gate_extra_evidence_required"]
    out["gate_extra_evidence_met"] = result.loc[out.index, "gate_extra_evidence_met"]
    return out


def write_report(path: Path, summary: dict[str, Any], comparison: pd.DataFrame, recommendation: dict[str, Any]) -> None:
    rec_name = recommendation["recommended_variant"]
    rec = comparison[comparison["variant"].eq(rec_name)].iloc[0]
    default = comparison[comparison["variant"].eq("variant_default")].iloc[0]
    lines = [
        "# S3-C2 Gate Evidence Ablation Scaffold",
        "",
        f"run_id: `{summary['run_id']}`",
        f"status: `{summary['status']}`",
        f"mode: `{'full' if summary['full_run'] else 'sample'}`",
        "",
        "## Scope",
        "",
        "S3-C2 is an offline gate-evidence scaffold. It does not overwrite score, gate, final, or incident outputs.",
        "S3-C1b full is treated as pending unless a full-run recommendation is present under `--s3c1b-output-dir`.",
        "",
        "## Summary",
        "",
        f"- loaded_rows: `{summary['loaded_rows']}`",
        f"- S3-C1b full available for this run: `{summary['s3c1b_info'].get('available') and summary['s3c1b_info'].get('full_run') and summary['s3c1b_info'].get('run_id_matches_current')}`",
        f"- recommended_variant: `{rec_name}`",
        f"- recommended gate_evidence_rows: `{int(rec['gate_evidence_rows'])}`",
        f"- recommended final_label_changed_rows: `{int(rec['final_label_changed_rows'])}`",
        f"- recommended pattern_A_gate_evidence_rows: `{int(rec['pattern_A_gate_evidence_rows'])}`",
        f"- recommended pattern_B_label_changed_rows: `{int(rec['pattern_B_label_changed_rows'])}`",
        f"- recommended P1/P2 ticket delta: `{rec.get('p1_p2_ticket_delta')}`",
        f"- recommended P1->P2 transfer tickets: `{rec.get('p1_to_p2_ticket_count')}`",
        "",
        "## Required Answers",
        "",
        "### 1. Is S3-C2 only high -> needs transfer?",
        "",
        f"Recommended `high_delta={int(rec['high_delta'])}` and `needs_delta={int(rec['needs_delta'])}`. The event transition table must be used to separate high->needs from any other movement. All fields are simulated and do not overwrite mainline outputs.",
        "",
        "### 2. Does needs_review inflate?",
        "",
        f"Recommended needs before/after is `{int(rec['needs_before'])}` -> `{int(rec['adjusted_needs_rows'])}`. A variant should not be recommended if it only hides high by expanding review without reducing incident burden.",
        "",
        "### 3. Is P1 only transferred to P2?",
        "",
        f"Recommended `p1_to_p2_ticket_count={rec.get('p1_to_p2_ticket_count')}`. P1->P2 is reported separately and is not counted as true workload reduction.",
        "",
        "### 4. Does total P1+P2 burden go down?",
        "",
        f"Recommended P1/P2 tickets before/after are `{rec.get('p1_p2_ticket_before')}` -> `{rec.get('p1_p2_ticket_after')}` and members before/after are `{rec.get('p1_p2_member_before')}` -> `{rec.get('p1_p2_member_after')}`.",
        "",
        "### 5. Which pattern_A rows are controlled?",
        "",
        f"`{rec_name}` has `pattern_A_gate_evidence_rows={int(rec['pattern_A_gate_evidence_rows'])}` and `pattern_A_label_changed_rows={int(rec['pattern_A_label_changed_rows'])}`. The detailed pattern table separates low/medium/high plausibility.",
        "",
        "### 6. Is pattern_B protected?",
        "",
        f"Yes for the recommendation: `pattern_B_label_changed_rows={int(rec['pattern_B_label_changed_rows'])}`. Pattern_B is routed to verification-only handling where configured.",
        "",
        "### 7. Known-event regression risk",
        "",
        f"known_event_available=`{bool(rec.get('known_event_available'))}`; matched rows=`{rec.get('known_event_matched_rows')}`; regression count=`{rec.get('known_event_regression_count')}`. If matched rows are zero, this does not prove safety.",
        "",
        "### 8. Is the recommended variant suitable for S3-D verification?",
        "",
        f"`{rec_name}` is suitable as a verification queue input if fixed S2 full does not inflate P1+P2 burden and keeps pattern_B protected.",
        "",
        "### 9. Next step",
        "",
        "If fixed S2 S3-C2 is stable, enter S3-D verification schema or S3-C3 route-leak triplet legality. If it mostly transfers labels without reducing burden, continue S3-C2 calibration.",
    ]
    if summary.get("warnings"):
        lines.extend(["", "## Warnings", ""])
        lines.extend([f"- {item}" for item in summary["warnings"]])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    df, meta = build_plausibility_frame(args)
    df = add_gate_evidence_fields(df)
    warnings = list(meta["warnings"])
    s3c1b_info = read_s3c1b_recommendation(Path(args.s3c1b_output_dir), warnings)
    s3c1b_info["run_id_matches_current"] = bool(s3c1b_info.get("run_id") == args.run_id)
    if s3c1b_info.get("available") and not s3c1b_info["run_id_matches_current"]:
        warnings.append(
            f"S3-C1b output run_id {s3c1b_info.get('run_id')} does not match current run_id {args.run_id}; using it only as a scaffold hint."
        )
    known_base, known_info = match_known_events(df, Path(args.known_event_file), warnings)

    comparison_rows = []
    pattern_rows = []
    p1p2_rows = []
    event_delta_frames = []
    incident_delta_frames = []
    burden_rows = []
    review_subtype_frames = []
    known_frames = []
    variant_results: dict[str, pd.DataFrame] = {}

    for variant in VARIANTS:
        result = apply_variant(df, variant)
        variant_results[variant["variant"]] = result
        known_rows, known_metrics = known_variant_rows(df, result, variant["variant"], known_base, known_info)
        incident_delta, burden = build_incident_priority_outputs(df, result, variant["variant"])
        known_frames.append(known_rows)
        metrics = variant_metrics(df, result, variant, known_metrics)
        metrics.update(
            {
                "p1_p2_ticket_before": burden.get("p1_p2_ticket_before"),
                "p1_p2_ticket_after": burden.get("p1_p2_ticket_after"),
                "p1_p2_ticket_delta": burden.get("p1_p2_ticket_delta"),
                "p1_p2_member_before": burden.get("p1_p2_member_before"),
                "p1_p2_member_after": burden.get("p1_p2_member_after"),
                "p1_p2_member_delta": burden.get("p1_p2_member_delta"),
                "p1_to_p2_ticket_count": burden.get("p1_to_p2_ticket_count"),
                "p1_to_p2_member_count": burden.get("p1_to_p2_member_count"),
            }
        )
        comparison_rows.append(metrics)
        pattern_rows.append(pattern_impact(df, result, variant["variant"], "pattern_A_flag", "pattern_A_single_collector_short_unseen_path"))
        pattern_rows.append(pattern_impact(df, result, variant["variant"], "pattern_B_flag", "pattern_B_abnormal_length_single_collector_unseen_path"))
        p1p2_rows.append(p1_p2_impact(df, result, variant["variant"]))
        event_delta_frames.append(build_event_label_delta(df, result, variant["variant"]))
        incident_delta_frames.append(incident_delta)
        burden_rows.append(burden)
        review_subtype_frames.append(build_review_subtype_distribution(df, result, variant["variant"]))

    comparison = pd.DataFrame(comparison_rows)
    pattern_df = pd.DataFrame(pattern_rows)
    pattern_a = pattern_df[pattern_df["pattern_name"].str.startswith("pattern_A")].copy()
    pattern_b = pattern_df[pattern_df["pattern_name"].str.startswith("pattern_B")].copy()
    p1p2_df = pd.DataFrame(p1p2_rows)
    event_label_delta = pd.concat(event_delta_frames, ignore_index=True) if event_delta_frames else pd.DataFrame()
    incident_priority_delta = pd.concat(incident_delta_frames, ignore_index=True) if incident_delta_frames else pd.DataFrame()
    p1_p2_burden = pd.DataFrame(burden_rows)
    review_subtype_distribution = pd.concat(review_subtype_frames, ignore_index=True) if review_subtype_frames else pd.DataFrame()
    known_check = pd.concat(known_frames, ignore_index=True) if known_frames else pd.DataFrame()
    recommendation = choose_recommended_variant(comparison, s3c1b_info)
    recommended_result = variant_results[recommendation["recommended_variant"]]
    top_cases = build_top_adjusted_cases(df, recommended_result, recommendation["recommended_variant"])

    summary = {
        "run_id": args.run_id,
        "input_rows": int(meta["source_rows"]),
        "loaded_rows": int(meta["loaded_rows"]),
        "full_run": bool(args.full_run),
        "sample_rows": None if args.full_run else args.sample_rows,
        "variant_count": int(len(VARIANTS)),
        "recommended_variant": recommendation["recommended_variant"],
        "recommendation_reason": recommendation["reason"],
        "s3c1b_info": s3c1b_info,
        "known_event_info": {k: v for k, v in known_info.items() if k not in {"known_mask", "event_masks"}},
        "join_info": meta["join_info"],
        "warnings": warnings,
        "status": "completed_with_warnings" if warnings else "completed",
    }

    comparison.to_csv(output_dir / "s3c2_variant_comparison.csv", index=False)
    event_label_delta.to_csv(output_dir / "s3c2_event_label_delta.csv", index=False)
    incident_priority_delta.to_csv(output_dir / "s3c2_incident_priority_delta.csv", index=False)
    p1_p2_burden.to_csv(output_dir / "s3c2_p1_p2_total_burden.csv", index=False)
    pattern_a.to_csv(output_dir / "s3c2_pattern_A_impact.csv", index=False)
    pattern_b.to_csv(output_dir / "s3c2_pattern_B_protection.csv", index=False)
    p1p2_df.to_csv(output_dir / "s3c2_p1_p2_impact.csv", index=False)
    review_subtype_distribution.to_csv(output_dir / "s3c2_review_subtype_distribution.csv", index=False)
    known_check.to_csv(output_dir / "s3c2_known_event_regression_check.csv", index=False)
    top_cases.to_csv(output_dir / "s3c2_top_adjusted_cases.csv", index=False)
    (output_dir / "s3c2_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=json_default), encoding="utf-8")
    (output_dir / "s3c2_recommended_variant.json").write_text(
        json.dumps(recommendation, ensure_ascii=False, indent=2, default=json_default),
        encoding="utf-8",
    )
    write_report(output_dir / "s3c2_report.md", summary, comparison, recommendation)
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="S3-C2 offline gate evidence ablation scaffold.")
    ap.add_argument("--run-id", default=RUN_ID_DEFAULT, help="Run id under data/runs/<run_id>.")
    ap.add_argument("--output-dir", default=OUTPUT_DIR_DEFAULT, help="Output directory for S3-C2 artifacts.")
    ap.add_argument("--scores", default=None)
    ap.add_argument("--candidates", default=None)
    ap.add_argument("--events", default=None)
    ap.add_argument("--gating", default=None)
    ap.add_argument("--final", default=None)
    ap.add_argument("--membership", default=None)
    ap.add_argument("--tickets", default=None)
    ap.add_argument("--baseline-prefix-origin", default=None)
    ap.add_argument("--s3c1b-output-dir", default="outputs/s3c1b_penalty_calibration_v01")
    ap.add_argument("--known-event-file", default="data/known_events/known_event_candidates_v05.json")
    ap.add_argument("--sample-rows", type=int, default=200_000)
    ap.add_argument("--full-run", action="store_true")
    ap.add_argument("--temporal-window-sec", type=int, default=600)
    args = ap.parse_args()

    if args.sample_rows is not None and args.sample_rows <= 0:
        raise SystemExit("--sample-rows must be > 0")
    if args.temporal_window_sec <= 0:
        raise SystemExit("--temporal-window-sec must be > 0")

    summary = run(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=json_default))


if __name__ == "__main__":
    main()
