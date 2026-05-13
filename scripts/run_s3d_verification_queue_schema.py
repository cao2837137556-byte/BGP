import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


RUN_ID_DEFAULT = "s2a_expanded_v01_pilot_6h_april16"
OUTPUT_DIR_DEFAULT = "outputs/s3d_verification_queue_schema_v01"

PRIORITIES = ["P1_high", "P2_review", "P3_background"]
QUEUE_ORDER = {
    "high_confidence_candidate": 0,
    "patternB_path_abnormal_verification": 1,
    "route_leak_like_review": 2,
    "gate_evidence_weak_case": 3,
    "background_like_review": 4,
    "unresolved_conflict": 5,
    "low_priority_background": 6,
}

BASE_TICKET_COLS = [
    "incident_id",
    "run_id",
    "family",
    "incident_priority",
    "member_count",
    "micro_incident_count",
    "affected_prefix_count",
    "origin_as_count",
    "path_signature_count",
    "triplet_signature_count",
    "collector_union_count",
    "incident_start",
    "incident_end",
    "incident_duration_sec",
    "incident_score",
    "incident_confidence",
    "high_count",
    "needs_count",
    "max_risk_score",
    "mean_risk_score",
    "p95_risk_score",
    "mean_certainty_score",
    "mean_conflict_score",
    "mean_evidence_support_score",
    "missing_rate",
    "dominant_prefix",
    "dominant_origin_as",
    "dominant_path_signature",
    "dominant_triplet_signature",
    "dominant_top_factor",
    "dominant_reason_signature",
    "dominant_label_share",
    "dominant_reason_share",
    "label_distribution",
    "source_layer_distribution",
    "reason_distribution",
    "top_prefixes",
    "top_origin_as",
    "explanation",
]

CALIBRATED_EXTRA_COLS = [
    "original_priority",
    "calibrated_priority",
    "high_share",
    "needs_share",
    "flag_origin_na",
    "flag_large_fanout",
    "flag_extreme_fanout",
    "flag_low_confidence",
    "flag_large_needs_only",
    "flag_single_broad_reason_fanout",
    "flag_background_fanout_candidate",
    "calibration_flags",
    "calibration_reason",
    "calibration_action",
    "calibrated_subtype",
    "is_downgraded",
]

MEMBERSHIP_COLS = [
    "incident_id",
    "event_id",
    "family",
    "final_alert_label",
    "alert_source_layer",
    "risk_bucket",
    "certainty_score",
    "conflict_score",
    "evidence_support_score",
    "missing_origin_or_path",
    "top_contributing_factor",
    "reason_signature",
    "incident_priority",
    "incident_score",
    "incident_confidence",
]


def json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def available_columns(path: Path, requested: list[str]) -> list[str]:
    schema_cols = set(pq.ParquetFile(path).schema_arrow.names)
    return [col for col in requested if col in schema_cols]


def read_parquet_existing(path: Path, requested: list[str]) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    cols = available_columns(path, requested)
    if not cols:
        raise ValueError(f"none of requested columns exist in {path}: {requested}")
    return pd.read_parquet(path, columns=cols)


def to_text(df: pd.DataFrame, col: str, default: str = "") -> pd.Series:
    if col not in df.columns:
        return pd.Series(default, index=df.index, dtype="object")
    return df[col].fillna(default).astype(str)


def to_number(df: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in df.columns:
        return pd.Series(default, index=df.index, dtype="float64")
    return pd.to_numeric(df[col], errors="coerce").fillna(default)


def to_bool(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(False, index=df.index, dtype=bool)
    series = df[col]
    if series.dtype == bool:
        return series.fillna(False)
    return series.fillna(False).astype(str).str.strip().str.lower().isin({"1", "true", "yes", "y", "on"})


def contains_token(series: pd.Series, token: str) -> pd.Series:
    return series.fillna("").astype(str).str.contains(token, regex=False, na=False)


def is_origin_na(series: pd.Series) -> pd.Series:
    text = series.fillna("").astype(str).str.strip().str.upper()
    return text.isin({"", "NA", "NAN", "NONE", "NULL"})


def clean_priority(series: pd.Series) -> pd.Series:
    out = series.fillna("P3_background").astype(str)
    return out.where(out.isin(PRIORITIES), "P3_background")


def safe_ratio(num: pd.Series, den: pd.Series) -> pd.Series:
    den_clean = den.replace(0, np.nan)
    return (num / den_clean).replace([np.inf, -np.inf], np.nan).fillna(0.0)


def load_tickets(args: argparse.Namespace, warnings: list[str]) -> pd.DataFrame:
    run_dir = Path("data") / "runs" / args.run_id
    calibrated_path = Path(args.calibrated_tickets) if args.calibrated_tickets else Path(
        "outputs/s3a2_incident_priority_calibration_v01/s3a2_calibrated_incident_tickets.parquet"
    )
    original_path = Path(args.incident_tickets) if args.incident_tickets else run_dir / "incidents" / "incident_tickets.parquet"
    if calibrated_path.exists():
        tickets = read_parquet_existing(calibrated_path, BASE_TICKET_COLS + CALIBRATED_EXTRA_COLS)
        tickets["ticket_source"] = "s3a2_calibrated"
    elif original_path.exists():
        warnings.append(f"calibrated tickets missing at {calibrated_path}; using original S3-A tickets.")
        tickets = read_parquet_existing(original_path, BASE_TICKET_COLS)
        tickets["ticket_source"] = "s3a_original"
    else:
        raise SystemExit(f"required incident tickets not found: {calibrated_path} or {original_path}")

    text_cols = [
        "incident_id",
        "run_id",
        "family",
        "incident_priority",
        "dominant_prefix",
        "dominant_origin_as",
        "dominant_path_signature",
        "dominant_triplet_signature",
        "dominant_top_factor",
        "dominant_reason_signature",
        "label_distribution",
        "source_layer_distribution",
        "reason_distribution",
        "top_prefixes",
        "top_origin_as",
        "explanation",
        "original_priority",
        "calibrated_priority",
        "calibration_flags",
        "calibration_reason",
        "calibration_action",
        "calibrated_subtype",
    ]
    for col in text_cols:
        tickets[col] = to_text(tickets, col)

    numeric_cols = [
        "member_count",
        "micro_incident_count",
        "affected_prefix_count",
        "origin_as_count",
        "path_signature_count",
        "triplet_signature_count",
        "collector_union_count",
        "incident_duration_sec",
        "incident_score",
        "incident_confidence",
        "high_count",
        "needs_count",
        "max_risk_score",
        "mean_risk_score",
        "p95_risk_score",
        "mean_certainty_score",
        "mean_conflict_score",
        "mean_evidence_support_score",
        "missing_rate",
        "dominant_label_share",
        "dominant_reason_share",
        "high_share",
        "needs_share",
    ]
    for col in numeric_cols:
        tickets[col] = to_number(tickets, col)

    bool_cols = [
        "flag_origin_na",
        "flag_large_fanout",
        "flag_extreme_fanout",
        "flag_low_confidence",
        "flag_large_needs_only",
        "flag_single_broad_reason_fanout",
        "flag_background_fanout_candidate",
        "is_downgraded",
    ]
    for col in bool_cols:
        tickets[col] = to_bool(tickets, col)

    tickets["original_incident_priority"] = tickets["incident_priority"]
    if "original_priority" in tickets.columns and tickets["original_priority"].str.len().sum() > 0:
        tickets["original_incident_priority"] = clean_priority(tickets["original_priority"])
    tickets["calibrated_incident_priority"] = clean_priority(tickets["calibrated_priority"])
    missing_calibrated = tickets["calibrated_incident_priority"].eq("P3_background") & tickets["calibrated_priority"].eq("")
    tickets.loc[missing_calibrated, "calibrated_incident_priority"] = clean_priority(tickets.loc[missing_calibrated, "incident_priority"])
    tickets["high_share"] = np.where(tickets["high_share"].gt(0), tickets["high_share"], safe_ratio(tickets["high_count"], tickets["member_count"]))
    tickets["needs_share"] = np.where(
        tickets["needs_share"].gt(0),
        tickets["needs_share"],
        safe_ratio(tickets["needs_count"], tickets["member_count"]),
    )

    tickets["dominant_origin_is_na"] = is_origin_na(tickets["dominant_origin_as"])
    tickets["large_fanout_flag"] = tickets["flag_large_fanout"] | tickets["affected_prefix_count"].ge(100)
    tickets["extreme_fanout_flag"] = tickets["flag_extreme_fanout"] | tickets["affected_prefix_count"].ge(1000)
    if args.sample_rows and not args.full_run:
        tickets = tickets.head(args.sample_rows).copy()
    return tickets


def read_s3c2_info(output_dir: Path, run_id: str, warnings: list[str]) -> dict[str, Any]:
    summary_path = output_dir / "s3c2_summary.json"
    recommendation_path = output_dir / "s3c2_recommended_variant.json"
    info: dict[str, Any] = {
        "available": False,
        "output_dir": str(output_dir),
        "status": "missing",
    }
    if not summary_path.exists() or not recommendation_path.exists():
        warnings.append(f"S3-C2 summary/recommendation missing under {output_dir}; continuing with membership-derived evidence.")
        return info
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        recommendation = json.loads(recommendation_path.read_text(encoding="utf-8"))
    except Exception as exc:
        warnings.append(f"could not parse S3-C2 outputs under {output_dir}: {exc}")
        info["status"] = "parse_failed"
        return info
    info.update(
        {
            "available": True,
            "status": summary.get("status", "unknown"),
            "run_id": summary.get("run_id"),
            "run_id_matches_current": summary.get("run_id") == run_id,
            "full_run": bool(summary.get("full_run", False)),
            "recommended_variant": recommendation.get("recommended_variant"),
            "recommended_gate_evidence_rows": recommendation.get("metrics", {}).get("gate_evidence_rows"),
            "recommended_pattern_A_gate_evidence_rows": recommendation.get("metrics", {}).get("pattern_A_gate_evidence_rows"),
            "recommended_pattern_B_label_changed_rows": recommendation.get("metrics", {}).get("pattern_B_label_changed_rows"),
        }
    )
    if not info["run_id_matches_current"]:
        warnings.append(f"S3-C2 run_id {info.get('run_id')} does not match S3-D run_id {run_id}.")
    if not info["full_run"]:
        warnings.append("S3-C2 output is not marked full_run; treating it as context only.")
    return info


def load_membership(args: argparse.Namespace, incident_ids: set[str], warnings: list[str]) -> pd.DataFrame:
    run_dir = Path("data") / "runs" / args.run_id
    path = Path(args.membership) if args.membership else run_dir / "incidents" / "incident_membership.parquet"
    if not path.exists():
        warnings.append(f"incident membership missing at {path}; queue will use ticket-level features only.")
        return pd.DataFrame(columns=MEMBERSHIP_COLS)
    membership = read_parquet_existing(path, MEMBERSHIP_COLS)
    for col in ["incident_id", "event_id", "family", "final_alert_label", "alert_source_layer", "risk_bucket", "top_contributing_factor", "reason_signature"]:
        membership[col] = to_text(membership, col)
    for col in ["certainty_score", "conflict_score", "evidence_support_score", "incident_score", "incident_confidence"]:
        membership[col] = to_number(membership, col)
    membership["missing_origin_or_path"] = to_bool(membership, "missing_origin_or_path")
    if incident_ids:
        membership = membership[membership["incident_id"].isin(incident_ids)].copy()
    return membership


def add_membership_evidence(membership: pd.DataFrame) -> pd.DataFrame:
    if membership.empty:
        return membership
    reason = membership["reason_signature"].fillna("").astype(str)
    membership = membership.copy()
    membership["pattern_A_member_flag"] = (
        contains_token(reason, "single_collector_visibility")
        & contains_token(reason, "structural_novelty_score")
        & contains_token(reason, "unseen_path_for_prefix_origin")
        & contains_token(reason, "unusually_short_duration_for_prefix")
    )
    membership["pattern_B_member_flag"] = (
        contains_token(reason, "abnormal_path_length_for_prefix_origin")
        & contains_token(reason, "single_collector_visibility")
        & contains_token(reason, "structural_novelty_score")
        & contains_token(reason, "unseen_path_for_prefix_origin")
    )
    membership["pattern_A_gate_evidence_flag"] = membership["pattern_A_member_flag"] & ~membership["pattern_B_member_flag"]
    membership["pattern_B_verification_flag"] = membership["pattern_B_member_flag"]
    membership["low_visibility_review_flag"] = membership["final_alert_label"].eq("needs_review") & (
        contains_token(reason, "single_collector_visibility")
        | contains_token(reason, "unusually_low_visibility_for_prefix")
        | contains_token(reason, "unusually_low_visibility_for_prefix_origin")
        | contains_token(reason, "unusually_short_duration_for_prefix")
        | contains_token(reason, "sparse_short_lived_event")
    )
    membership["route_leak_like_review_flag"] = membership["final_alert_label"].eq("needs_review") & (
        membership["family"].eq("route_leak_like")
        | contains_token(reason, "cross_collector_prefix_origin_burst")
        | contains_token(reason, "route_leak")
    )
    membership["high_member_flag"] = membership["final_alert_label"].eq("high_priority_alert")
    membership["needs_member_flag"] = membership["final_alert_label"].eq("needs_review")
    return membership


def aggregate_membership(membership: pd.DataFrame) -> pd.DataFrame:
    if membership.empty:
        return pd.DataFrame(columns=["incident_id"])
    bool_cols = [
        "pattern_A_member_flag",
        "pattern_A_gate_evidence_flag",
        "pattern_B_member_flag",
        "pattern_B_verification_flag",
        "low_visibility_review_flag",
        "route_leak_like_review_flag",
        "high_member_flag",
        "needs_member_flag",
        "missing_origin_or_path",
    ]
    agg = membership.groupby("incident_id", sort=False)[bool_cols].sum().reset_index()
    agg = agg.rename(
        columns={
            "pattern_A_member_flag": "pattern_A_member_count",
            "pattern_A_gate_evidence_flag": "pattern_A_gate_evidence_count",
            "pattern_B_member_flag": "pattern_B_member_count",
            "pattern_B_verification_flag": "pattern_B_verification_count",
            "low_visibility_review_flag": "low_visibility_review_count",
            "route_leak_like_review_flag": "route_leak_like_review_count",
            "high_member_flag": "membership_high_count",
            "needs_member_flag": "membership_needs_count",
            "missing_origin_or_path": "missing_origin_or_path_count",
        }
    )
    numeric = membership.groupby("incident_id", sort=False).agg(
        max_conflict_score=("conflict_score", "max"),
        mean_conflict_score_members=("conflict_score", "mean"),
        mean_certainty_score_members=("certainty_score", "mean"),
        mean_evidence_support_score_members=("evidence_support_score", "mean"),
    )
    return agg.merge(numeric.reset_index(), on="incident_id", how="left")


def enrich_queue_features(tickets: pd.DataFrame, membership_agg: pd.DataFrame, warnings: list[str]) -> pd.DataFrame:
    queue = tickets.copy()
    if not membership_agg.empty:
        queue = queue.merge(membership_agg, on="incident_id", how="left")
    for col in [
        "pattern_A_member_count",
        "pattern_A_gate_evidence_count",
        "pattern_B_member_count",
        "pattern_B_verification_count",
        "low_visibility_review_count",
        "route_leak_like_review_count",
        "membership_high_count",
        "membership_needs_count",
        "missing_origin_or_path_count",
        "max_conflict_score",
        "mean_conflict_score_members",
        "mean_certainty_score_members",
        "mean_evidence_support_score_members",
    ]:
        queue[col] = to_number(queue, col)
    queue["gate_evidence_member_count"] = queue["pattern_A_gate_evidence_count"]
    queue["pattern_A_gate_evidence_ratio"] = safe_ratio(queue["pattern_A_gate_evidence_count"], queue["member_count"])
    queue["pattern_B_ratio"] = safe_ratio(queue["pattern_B_member_count"], queue["member_count"])
    queue["gate_evidence_ratio"] = safe_ratio(queue["gate_evidence_member_count"], queue["member_count"])
    queue["pattern_B_protected_flag"] = queue["pattern_B_member_count"].gt(0)
    queue["route_leak_like_flag"] = queue["family"].eq("route_leak_like") | queue["route_leak_like_review_count"].gt(0)
    queue["background_fanout_review_count"] = np.where(
        queue["large_fanout_flag"] & (queue["gate_evidence_ratio"].ge(0.5) | queue["dominant_origin_is_na"] | queue["flag_background_fanout_candidate"]),
        queue["needs_count"],
        0,
    )
    queue["background_like_flag"] = (
        queue["dominant_origin_is_na"]
        | queue["flag_background_fanout_candidate"]
        | (
            queue["large_fanout_flag"]
            & (queue["incident_confidence"].lt(0.55) | queue["high_share"].lt(0.10) | queue["gate_evidence_ratio"].ge(0.70))
        )
        | (queue["background_fanout_review_count"] > 0)
    )
    queue["unresolved_conflict_flag"] = (
        queue["incident_score"].ge(70)
        & (
            queue["incident_confidence"].lt(0.55)
            | queue["max_conflict_score"].ge(40)
            | queue["missing_rate"].ge(0.50)
            | safe_ratio(queue["missing_origin_or_path_count"], queue["member_count"]).ge(0.50)
        )
    )
    queue["high_confidence_candidate_flag"] = (
        queue["calibrated_incident_priority"].eq("P1_high")
        & queue["high_count"].gt(0)
        & queue["incident_confidence"].ge(0.70)
        & queue["high_share"].ge(0.50)
        & ~queue["dominant_origin_is_na"]
        & (queue["gate_evidence_ratio"].lt(0.50) | queue["pattern_B_protected_flag"])
        & ~queue["background_like_flag"]
        & ~queue["route_leak_like_flag"]
    )
    queue["gate_evidence_weak_case_flag"] = (
        queue["calibrated_incident_priority"].isin(["P1_high", "P2_review"])
        & queue["gate_evidence_ratio"].ge(0.50)
        & (queue["needs_share"].ge(0.50) | queue["high_share"].lt(0.50) | queue["high_count"].gt(0))
        & ~queue["background_like_flag"]
        & ~queue["route_leak_like_flag"]
        & ~queue["pattern_B_protected_flag"]
    )
    queue["low_priority_background_flag"] = (
        queue["calibrated_incident_priority"].eq("P3_background")
        & (queue["high_count"].eq(0) | queue["incident_confidence"].lt(0.55) | queue["gate_evidence_ratio"].ge(0.70))
        & ~queue["route_leak_like_flag"]
        & ~queue["pattern_B_protected_flag"]
    )
    warnings.append(
        "S3-D uses incident_membership reason_signature to compute incident-member pattern_A/pattern_B evidence; "
        "full S3-C2 per-event gate evidence is not present in local inputs."
    )
    return queue


def assign_queue(queue: pd.DataFrame) -> pd.DataFrame:
    out = queue.copy()
    choices = [
        out["route_leak_like_flag"],
        out["pattern_B_protected_flag"],
        out["high_confidence_candidate_flag"],
        out["gate_evidence_weak_case_flag"],
        out["background_like_flag"],
        out["unresolved_conflict_flag"],
        out["low_priority_background_flag"],
    ]
    labels = [
        "route_leak_like_review",
        "patternB_path_abnormal_verification",
        "high_confidence_candidate",
        "gate_evidence_weak_case",
        "background_like_review",
        "unresolved_conflict",
        "low_priority_background",
    ]
    out["verification_queue"] = np.select(choices, labels, default="low_priority_background")

    conf_100 = np.where(out["incident_confidence"].le(1.0), out["incident_confidence"] * 100.0, out["incident_confidence"])
    collector_support = np.minimum(out["collector_union_count"] / 12.0, 1.0) * 100.0
    pattern_b_support = np.minimum(out["pattern_B_ratio"] * 100.0, 100.0)
    gate_bonus = (1.0 - out["gate_evidence_ratio"].clip(0.0, 1.0)) * 100.0
    background_penalty = np.where(out["background_like_flag"], 100.0, np.where(out["large_fanout_flag"], 40.0, 0.0))
    score = (
        0.25 * out["incident_score"]
        + 0.25 * conf_100
        + 0.15 * (out["high_share"].clip(0.0, 1.0) * 100.0)
        + 0.15 * pattern_b_support
        + 0.10 * gate_bonus
        + 0.05 * collector_support
        - 0.05 * background_penalty
    )
    out["verification_priority_score"] = np.clip(score, 0.0, 100.0).round(4)
    verification_conf = (
        0.50 * conf_100
        + 0.20 * (out["high_share"].clip(0.0, 1.0) * 100.0)
        + 0.15 * gate_bonus
        + 0.15 * collector_support
    )
    out["verification_confidence"] = np.clip(verification_conf / 100.0, 0.0, 1.0).round(4)

    out["verification_reason"] = np.select(
        [
            out["verification_queue"].eq("high_confidence_candidate"),
            out["verification_queue"].eq("gate_evidence_weak_case"),
            out["verification_queue"].eq("patternB_path_abnormal_verification"),
            out["verification_queue"].eq("background_like_review"),
            out["verification_queue"].eq("route_leak_like_review"),
            out["verification_queue"].eq("unresolved_conflict"),
        ],
        [
            "P1 high-share incident with high confidence and limited gate-evidence burden.",
            "P1/P2 incident dominated by S3-C2 pattern_A gate evidence; verify rather than downgrade.",
            "Pattern_B abnormal path-length support is protected from plausibility-only downgrade.",
            "Large fan-out, NA-origin, low-confidence, or mostly-needs background-like incident.",
            "Route-leak-like family/review incident; evaluate with triplet legality and leak-specific checks.",
            "High score but low confidence, high conflict, or missing evidence; keep out of weak labels.",
        ],
        default="Low-priority background candidate; not confirmed normal.",
    )
    out["recommended_next_check"] = np.select(
        [
            out["verification_queue"].eq("high_confidence_candidate"),
            out["verification_queue"].eq("gate_evidence_weak_case"),
            out["verification_queue"].eq("patternB_path_abnormal_verification"),
            out["verification_queue"].eq("background_like_review"),
            out["verification_queue"].eq("route_leak_like_review"),
            out["verification_queue"].eq("unresolved_conflict"),
        ],
        [
            "external_origin_path_validation",
            "collector_visibility_temporal_recurrence_check",
            "path_length_triplet_legality_check",
            "background_fanout_sanity_sample",
            "route_leak_triplet_valley_free_check",
            "manual_conflict_and_evidence_review",
        ],
        default="retain_as_background_reference",
    )
    out["external_evidence_needed"] = np.select(
        [
            out["verification_queue"].eq("route_leak_like_review"),
            out["verification_queue"].eq("patternB_path_abnormal_verification"),
            out["verification_queue"].eq("high_confidence_candidate"),
            out["verification_queue"].eq("gate_evidence_weak_case"),
        ],
        [
            "AS relationship/triplet legality; public incident references if available",
            "historical path-length distribution; AS path/triplet context",
            "RPKI/IRR/PeeringDB/operator evidence; multi-collector recurrence",
            "collector support, temporal recurrence, historical path plausibility",
        ],
        default="optional; do not treat as verified without external check",
    )
    out["weak_label_candidate"] = np.select(
        [
            out["verification_queue"].eq("high_confidence_candidate"),
            out["verification_queue"].isin(["background_like_review", "low_priority_background"]),
            out["verification_queue"].eq("unresolved_conflict"),
        ],
        ["verified_candidate_positive", "benign_like_candidate", "conflict"],
        default="uncertain",
    )
    out["queue_rank"] = out["verification_queue"].map(QUEUE_ORDER).fillna(99).astype(int)
    return out


def build_distribution(queue: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for qname, group in queue.groupby("verification_queue", dropna=False):
        priorities = group["calibrated_incident_priority"].value_counts().to_dict()
        rows.append(
            {
                "verification_queue": qname,
                "ticket_count": int(len(group)),
                "member_count": float(group["member_count"].sum()),
                "high_count": float(group["high_count"].sum()),
                "needs_count": float(group["needs_count"].sum()),
                "P1_count": int(priorities.get("P1_high", 0)),
                "P2_count": int(priorities.get("P2_review", 0)),
                "P3_count": int(priorities.get("P3_background", 0)),
                "mean_verification_priority_score": float(group["verification_priority_score"].mean()) if len(group) else 0.0,
                "mean_gate_evidence_ratio": float(group["gate_evidence_ratio"].mean()) if len(group) else 0.0,
                "mean_incident_confidence": float(group["incident_confidence"].mean()) if len(group) else 0.0,
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(["ticket_count", "verification_queue"], ascending=[False, True])


def top_by_queue(queue: pd.DataFrame, limit: int = 50) -> pd.DataFrame:
    frames = []
    for qname in [
        "high_confidence_candidate",
        "gate_evidence_weak_case",
        "patternB_path_abnormal_verification",
        "background_like_review",
        "route_leak_like_review",
        "unresolved_conflict",
    ]:
        subset = queue[queue["verification_queue"].eq(qname)].copy()
        if subset.empty:
            continue
        frames.append(
            subset.sort_values(["verification_priority_score", "incident_score", "member_count"], ascending=[False, False, False]).head(limit)
        )
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=queue.columns)


def write_feature_schema(path: Path) -> None:
    schema = {
        "scope": "incident-level verification queue schema v01",
        "labels": {
            "verification_queue": "Queue assignment for verification planning; not a replacement for incident_priority.",
            "weak_label_candidate": "Weak candidate label for future learning prep; not a ground-truth label.",
        },
        "evidence_precision": {
            "pattern_A_member_count": "Exact count over incident_membership rows whose reason_signature matches pattern_A tokens.",
            "pattern_A_gate_evidence_count": "Incident-member fallback for S3-C2 gate evidence: pattern_A member rows excluding pattern_B.",
            "pattern_B_member_count": "Exact count over incident_membership rows whose reason_signature matches pattern_B tokens.",
            "gate_evidence_ratio": "pattern_A_gate_evidence_count / member_count at incident level.",
        },
        "queue_precedence": [
            "route_leak_like_review",
            "patternB_path_abnormal_verification",
            "high_confidence_candidate",
            "gate_evidence_weak_case",
            "background_like_review",
            "unresolved_conflict",
            "low_priority_background",
        ],
        "non_goals": [
            "Does not perform external verification.",
            "Does not overwrite score/gate/final/incident outputs.",
            "Does not claim P1/P2 are true anomalies or P3 is normal.",
        ],
    }
    path.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")


def count_dict(series: pd.Series) -> dict[str, int]:
    return {str(k): int(v) for k, v in series.value_counts(dropna=False).to_dict().items()}


def write_report(path: Path, summary: dict[str, Any], distribution: pd.DataFrame) -> None:
    qcounts = summary["queue_count_by_type"]
    lines = [
        "# S3-D Incident-Level Verification Queue Schema",
        "",
        f"run_id: `{summary['run_id']}`",
        f"status: `{summary['status']}`",
        f"mode: `{'full' if summary['full_run'] else 'sample'}`",
        "",
        "## Scope",
        "",
        "S3-D builds an incident-level verification queue. It does not run external verification, does not overwrite final labels, and does not reduce P1/P2 by itself.",
        "",
        "## Summary",
        "",
        f"- total_incidents: `{summary['total_incidents']}`",
        f"- total_P1/P2/P3: `{summary['total_P1']}` / `{summary['total_P2']}` / `{summary['total_P3']}`",
        f"- high_confidence_candidate: `{qcounts.get('high_confidence_candidate', 0)}`",
        f"- gate_evidence_weak_case: `{qcounts.get('gate_evidence_weak_case', 0)}`",
        f"- patternB_path_abnormal_verification: `{qcounts.get('patternB_path_abnormal_verification', 0)}`",
        f"- background_like_review: `{qcounts.get('background_like_review', 0)}`",
        f"- route_leak_like_review: `{qcounts.get('route_leak_like_review', 0)}`",
        f"- unresolved_conflict: `{qcounts.get('unresolved_conflict', 0)}`",
        f"- low_priority_background: `{qcounts.get('low_priority_background', 0)}`",
        "",
        "## Required Answers",
        "",
        "### 1. Did S3-D convert S3-C2 gate evidence into an incident-level verification queue?",
        "",
        f"Yes. S3-D creates `verification_queue`, `verification_priority_score`, `verification_reason`, and verification check fields for `{summary['total_incidents']}` incidents. S3-C2 evidence is represented at incident-member level using membership reason signatures.",
        "",
        "### 2. How many P1/P2 incidents enter gate_evidence_weak_case?",
        "",
        f"`{summary['P1_P2_gate_evidence_weak_case']}` P1/P2 incidents are assigned to `gate_evidence_weak_case`.",
        "",
        "### 3. How many P1/P2 incidents look like high_confidence_candidate?",
        "",
        f"`{summary['P1_P2_high_confidence_candidate']}` P1/P2 incidents are assigned to `high_confidence_candidate`.",
        "",
        "### 4. How many incidents are background_like_review?",
        "",
        f"`{summary['background_like_review_incidents']}` incidents are assigned to `background_like_review`.",
        "",
        "### 5. Is pattern_B retained as a separate verification queue?",
        "",
        f"Yes. `{summary['patternB_verification_incidents']}` incidents enter `patternB_path_abnormal_verification`. They are not downgraded by low visibility alone.",
        "",
        "### 6. Is route_leak_like a separate review queue?",
        "",
        f"Yes. `{summary['route_leak_like_review_incidents']}` incidents enter `route_leak_like_review`.",
        "",
        "### 7. Does this reduce final labels or P1/P2 count?",
        "",
        "No. S3-D is queue reorganization and verification preparation. It does not change final labels, calibrated priority, or mainline outputs.",
        "",
        "### 8. Next steps",
        "",
        "- S3-C3 route-leak triplet legality for route-leak-like and patternB path-abnormal queues.",
        "- S3-D2 external evidence attachment for high-confidence and gate-evidence weak cases.",
        "- S4 learning-ready high-confidence set only after external verification exists.",
        "",
        "### 9. Future learning fields",
        "",
        "`verification_queue`, `verification_priority_score`, `gate_evidence_ratio`, `pattern_A_gate_evidence_ratio`, `pattern_B_ratio`, `high_share`, `needs_share`, confidence fields, fan-out flags, and `weak_label_candidate` are suitable inputs. `weak_label_candidate` is not ground truth.",
        "",
        "### 10. Uncertainty and risk",
        "",
        "- S3-D uses incident-member reason signatures for S3-C2 evidence because local full S2 scored/gated/final parquet inputs are absent.",
        "- Known-event matched rows were zero in S3-C2; this cannot prove no regression risk.",
        "- Background-like incidents are not confirmed benign.",
        "- P1/P2 are not confirmed anomalies.",
    ]
    if not distribution.empty:
        lines.extend(["", "## Queue Distribution", ""])
        for row in distribution.to_dict("records"):
            lines.append(
                f"- `{row['verification_queue']}`: tickets `{int(row['ticket_count'])}`, members `{int(row['member_count'])}`, "
                f"P1/P2/P3 `{int(row['P1_count'])}/{int(row['P2_count'])}/{int(row['P3_count'])}`"
            )
    if summary.get("warnings"):
        lines.extend(["", "## Warnings", ""])
        lines.extend([f"- {item}" for item in summary["warnings"]])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    s3c2_info = read_s3c2_info(Path(args.s3c2_output_dir), args.run_id, warnings)
    tickets = load_tickets(args, warnings)
    membership = load_membership(args, set(tickets["incident_id"].astype(str)), warnings)
    membership = add_membership_evidence(membership)
    membership_agg = aggregate_membership(membership)
    queue = enrich_queue_features(tickets, membership_agg, warnings)
    queue = assign_queue(queue)

    output_cols = [
        "incident_id",
        "original_incident_priority",
        "calibrated_incident_priority",
        "family",
        "member_count",
        "high_count",
        "needs_count",
        "high_share",
        "needs_share",
        "affected_prefix_count",
        "origin_as_count",
        "collector_union_count",
        "incident_score",
        "incident_confidence",
        "dominant_origin_as",
        "dominant_prefix",
        "dominant_path_signature",
        "dominant_triplet_signature",
        "dominant_reason_signature",
        "pattern_A_member_count",
        "pattern_A_gate_evidence_count",
        "pattern_A_gate_evidence_ratio",
        "pattern_B_member_count",
        "pattern_B_verification_count",
        "pattern_B_protected_flag",
        "gate_evidence_member_count",
        "gate_evidence_ratio",
        "background_fanout_review_count",
        "low_visibility_review_count",
        "route_leak_like_review_count",
        "verification_queue",
        "verification_priority_score",
        "verification_confidence",
        "verification_reason",
        "recommended_next_check",
        "external_evidence_needed",
        "weak_label_candidate",
    ]
    for col in output_cols:
        if col not in queue.columns:
            queue[col] = "" if col.endswith("reason") or col.endswith("check") else 0
    output_queue = queue[output_cols].copy()
    distribution = build_distribution(queue)
    top_candidates = top_by_queue(output_queue)

    background = output_queue[output_queue["verification_queue"].eq("background_like_review")].sort_values(
        ["member_count", "affected_prefix_count"], ascending=[False, False]
    )
    pattern_a_incidents = output_queue[output_queue["pattern_A_gate_evidence_count"].gt(0)].sort_values(
        ["pattern_A_gate_evidence_ratio", "member_count"], ascending=[False, False]
    )
    pattern_b_incidents = output_queue[output_queue["pattern_B_member_count"].gt(0)].sort_values(
        ["verification_priority_score", "pattern_B_member_count"], ascending=[False, False]
    )
    route_leak = output_queue[output_queue["verification_queue"].eq("route_leak_like_review")].sort_values(
        ["verification_priority_score", "member_count"], ascending=[False, False]
    )

    priorities = count_dict(queue["calibrated_incident_priority"])
    by_queue_priority = (
        queue.groupby(["verification_queue", "calibrated_incident_priority"]).size().rename("ticket_count").reset_index()
    )
    p1p2 = queue["calibrated_incident_priority"].isin(["P1_high", "P2_review"])
    summary = {
        "run_id": args.run_id,
        "total_incidents": int(len(queue)),
        "total_P1": int(priorities.get("P1_high", 0)),
        "total_P2": int(priorities.get("P2_review", 0)),
        "total_P3": int(priorities.get("P3_background", 0)),
        "queue_count_by_type": count_dict(queue["verification_queue"]),
        "P1_distribution_by_queue": count_dict(queue.loc[queue["calibrated_incident_priority"].eq("P1_high"), "verification_queue"]),
        "P2_distribution_by_queue": count_dict(queue.loc[queue["calibrated_incident_priority"].eq("P2_review"), "verification_queue"]),
        "P3_distribution_by_queue": count_dict(queue.loc[queue["calibrated_incident_priority"].eq("P3_background"), "verification_queue"]),
        "patternA_touched_incidents": int(queue["pattern_A_gate_evidence_count"].gt(0).sum()),
        "patternB_verification_incidents": int(queue["verification_queue"].eq("patternB_path_abnormal_verification").sum()),
        "background_like_review_incidents": int(queue["verification_queue"].eq("background_like_review").sum()),
        "route_leak_like_review_incidents": int(queue["verification_queue"].eq("route_leak_like_review").sum()),
        "P1_P2_gate_evidence_weak_case": int((p1p2 & queue["verification_queue"].eq("gate_evidence_weak_case")).sum()),
        "P1_P2_high_confidence_candidate": int((p1p2 & queue["verification_queue"].eq("high_confidence_candidate")).sum()),
        "topK_candidate_count": int(len(top_candidates)),
        "evidence_source": "incident_membership.reason_signature",
        "s3c2_output_dir": args.s3c2_output_dir,
        "s3c2_info": s3c2_info,
        "full_run": bool(args.full_run),
        "sample_rows": None if args.full_run else args.sample_rows,
        "warnings": warnings,
        "status": "completed_with_warnings" if warnings else "completed",
    }

    output_queue.to_parquet(output_dir / "s3d_incident_verification_queue.parquet", index=False)
    output_queue.to_csv(output_dir / "s3d_incident_verification_queue.csv", index=False)
    distribution.to_csv(output_dir / "s3d_queue_distribution.csv", index=False)
    top_candidates.to_csv(output_dir / "s3d_top_verification_candidates.csv", index=False)
    background.head(5000).to_csv(output_dir / "s3d_background_like_candidates.csv", index=False)
    pattern_a_incidents.head(5000).to_csv(output_dir / "s3d_patternA_gate_evidence_incidents.csv", index=False)
    pattern_b_incidents.head(5000).to_csv(output_dir / "s3d_patternB_verification_incidents.csv", index=False)
    route_leak.to_csv(output_dir / "s3d_route_leak_review_incidents.csv", index=False)
    by_queue_priority.to_csv(output_dir / "s3d_queue_priority_crosswalk.csv", index=False)
    write_feature_schema(output_dir / "s3d_feature_schema.json")
    (output_dir / "s3d_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=json_default), encoding="utf-8")
    write_report(output_dir / "s3d_report.md", summary, distribution)
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="S3-D incident-level verification queue/schema builder.")
    ap.add_argument("--run-id", default=RUN_ID_DEFAULT, help="Run id under data/runs/<run_id>.")
    ap.add_argument("--output-dir", default=OUTPUT_DIR_DEFAULT, help="Output directory for S3-D artifacts.")
    ap.add_argument("--s3c2-output-dir", default="outputs/s3c2_gate_evidence_ablation_v01")
    ap.add_argument("--incident-tickets", default=None)
    ap.add_argument("--membership", default=None)
    ap.add_argument("--calibrated-tickets", default=None)
    ap.add_argument("--sample-rows", type=int, default=200_000)
    ap.add_argument("--full-run", action="store_true")
    args = ap.parse_args()

    if args.sample_rows is not None and args.sample_rows <= 0:
        raise SystemExit("--sample-rows must be > 0")
    summary = run(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=json_default))


if __name__ == "__main__":
    main()
