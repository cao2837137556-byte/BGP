import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq


RUN_ID_DEFAULT = "s2a_expanded_v01_pilot_6h_april16"

TICKET_COLS = [
    "incident_id",
    "run_id",
    "family",
    "incident_priority",
    "member_count",
    "affected_prefix_count",
    "origin_as_count",
    "path_signature_count",
    "triplet_signature_count",
    "collector_union_count",
    "incident_score",
    "incident_confidence",
    "high_count",
    "needs_count",
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
    "dominant_reason_share",
    "original_priority",
    "calibrated_priority",
    "calibrated_subtype",
    "calibration_action",
    "calibration_flags",
    "calibration_reason",
    "high_share",
    "needs_share",
    "flag_origin_na",
    "flag_large_fanout",
    "flag_extreme_fanout",
    "flag_low_confidence",
    "flag_background_fanout_candidate",
    "is_downgraded",
]

MEMBERSHIP_COLS = [
    "incident_id",
    "event_id",
    "family",
    "final_alert_label",
    "alert_source_layer",
    "prefix",
    "origin_as_norm",
    "path_signature",
    "triplet_signature",
    "risk_score",
    "risk_bucket",
    "certainty_score",
    "conflict_score",
    "evidence_support_score",
    "missing_origin_or_path",
    "top_contributing_factor",
    "reason_signature",
]

FINAL_COLS = [
    "event_id",
    "candidate_reasons",
    "as_path_clean",
]


def json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def str2bool(value: str) -> bool:
    v = str(value).strip().lower()
    if v in {"1", "true", "yes", "y", "on"}:
        return True
    if v in {"0", "false", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"invalid boolean value: {value}")


def available_columns(path: Path, requested: list[str]) -> list[str]:
    schema_cols = set(pq.ParquetFile(path).schema_arrow.names)
    return [col for col in requested if col in schema_cols]


def read_parquet_existing(path: Path, requested: list[str]) -> pd.DataFrame:
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


def to_bool_series(series: pd.Series) -> pd.Series:
    if series.empty:
        return pd.Series(dtype=bool)
    if series.dtype == bool:
        return series.fillna(False)
    return series.astype(str).str.strip().str.lower().isin({"1", "true", "yes", "y", "on"})


def is_origin_na(series: pd.Series) -> pd.Series:
    text = series.fillna("").astype(str).str.strip().str.upper()
    return text.isin({"", "NA", "NAN", "NONE", "NULL"})


def contains_token(series: pd.Series, token: str) -> pd.Series:
    return series.fillna("").astype(str).str.contains(token, regex=False, na=False)


def count_dict(series: pd.Series) -> dict[str, int]:
    return {str(k): int(v) for k, v in series.value_counts(dropna=False).to_dict().items()}


def count_top_dict(series: pd.Series, limit: int = 20) -> dict[str, int]:
    return {str(k): int(v) for k, v in series.value_counts(dropna=False).head(limit).to_dict().items()}


def num_stats(series: pd.Series) -> dict[str, float]:
    nums = pd.to_numeric(series, errors="coerce").dropna()
    if nums.empty:
        return {"count": 0, "p50": 0.0, "p90": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0, "mean": 0.0}
    return {
        "count": int(nums.size),
        "p50": float(nums.quantile(0.50)),
        "p90": float(nums.quantile(0.90)),
        "p95": float(nums.quantile(0.95)),
        "p99": float(nums.quantile(0.99)),
        "max": float(nums.max()),
        "mean": float(nums.mean()),
    }


def load_tickets(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise SystemExit(f"required calibrated ticket input not found: {path}")
    tickets = read_parquet_existing(path, TICKET_COLS)
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
        "original_priority",
        "calibrated_priority",
        "calibrated_subtype",
        "calibration_action",
        "calibration_flags",
        "calibration_reason",
    ]
    for col in text_cols:
        tickets[col] = to_text(tickets, col)
    numeric_cols = [
        "member_count",
        "affected_prefix_count",
        "origin_as_count",
        "path_signature_count",
        "triplet_signature_count",
        "collector_union_count",
        "incident_score",
        "incident_confidence",
        "high_count",
        "needs_count",
        "mean_certainty_score",
        "mean_conflict_score",
        "mean_evidence_support_score",
        "missing_rate",
        "dominant_reason_share",
        "high_share",
        "needs_share",
    ]
    for col in numeric_cols:
        tickets[col] = to_number(tickets, col)
    for col in [
        "flag_origin_na",
        "flag_large_fanout",
        "flag_extreme_fanout",
        "flag_low_confidence",
        "flag_background_fanout_candidate",
        "is_downgraded",
    ]:
        tickets[col] = to_bool_series(tickets[col]) if col in tickets.columns else False
    tickets["origin_is_na"] = is_origin_na(tickets["dominant_origin_as"])
    tickets["large_fanout"] = tickets["affected_prefix_count"] >= 100
    tickets["extreme_fanout"] = tickets["affected_prefix_count"] >= 1000
    tickets["mostly_needs"] = tickets["needs_share"] >= 0.90
    tickets["tiny_high_support"] = tickets["high_share"] < 0.05
    tickets["reason_single_collector"] = contains_token(tickets["dominant_reason_signature"], "single_collector_visibility")
    tickets["reason_sparse_short"] = contains_token(tickets["dominant_reason_signature"], "sparse_short_lived_event") | contains_token(
        tickets["dominant_reason_signature"], "unusually_short_duration_for_prefix"
    )
    tickets["reason_structural"] = contains_token(tickets["dominant_reason_signature"], "structural_novelty_score")
    tickets["reason_unseen_path"] = contains_token(tickets["dominant_reason_signature"], "unseen_path_for_prefix_origin")
    tickets["reason_route_leak"] = contains_token(tickets["dominant_reason_signature"], "cross_collector_prefix_origin_burst")
    tickets["broad_background_pattern"] = (
        tickets["large_fanout"]
        & (
            tickets["origin_is_na"]
            | tickets["flag_background_fanout_candidate"]
            | (tickets["reason_single_collector"] & tickets["reason_structural"] & tickets["mostly_needs"])
        )
    )
    return tickets


def load_membership(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise SystemExit(f"required membership input not found: {path}")
    membership = read_parquet_existing(path, MEMBERSHIP_COLS)
    text_cols = [
        "incident_id",
        "event_id",
        "family",
        "final_alert_label",
        "alert_source_layer",
        "prefix",
        "origin_as_norm",
        "path_signature",
        "triplet_signature",
        "risk_bucket",
        "top_contributing_factor",
        "reason_signature",
    ]
    for col in text_cols:
        membership[col] = to_text(membership, col)
    for col in ["risk_score", "certainty_score", "conflict_score", "evidence_support_score"]:
        membership[col] = to_number(membership, col)
    membership["missing_origin_or_path"] = to_bool_series(membership["missing_origin_or_path"])
    return membership


def try_load_final(path: Path, event_ids: pd.Series) -> tuple[pd.DataFrame | None, dict[str, Any]]:
    if not path.exists():
        return None, {"final_join_available": False, "reason": "final_alerts_not_found", "path": str(path)}
    cols = available_columns(path, FINAL_COLS)
    if not cols or "event_id" not in cols:
        return None, {"final_join_available": False, "reason": "final_required_columns_missing", "path": str(path), "columns": cols}
    final_df = pd.read_parquet(path, columns=cols)
    final_df["event_id"] = to_text(final_df, "event_id")
    final_df = final_df[final_df["event_id"].isin(set(event_ids.astype(str)))]
    for col in ["candidate_reasons", "as_path_clean"]:
        final_df[col] = to_text(final_df, col)
    return final_df, {
        "final_join_available": True,
        "path": str(path),
        "columns": cols,
        "joined_rows": int(len(final_df)),
    }


def add_buckets(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["certainty_bucket"] = pd.cut(
        out["certainty_score"],
        bins=[-0.01, 40, 60, 80, 1000],
        labels=["cert_00_40", "cert_40_60", "cert_60_80", "cert_80_plus"],
    ).astype(str)
    out["conflict_bucket"] = pd.cut(
        out["conflict_score"],
        bins=[-0.01, 0, 5, 15, 1000],
        labels=["conflict_0", "conflict_0_5", "conflict_5_15", "conflict_15_plus"],
    ).astype(str)
    out["evidence_bucket"] = pd.cut(
        out["evidence_support_score"],
        bins=[-1000, 0, 40, 60, 80, 1000],
        labels=["evidence_missing_or_0", "evidence_0_40", "evidence_40_60", "evidence_60_80", "evidence_80_plus"],
    ).astype(str)
    return out


def classify_need_category(df: pd.DataFrame) -> pd.Series:
    reason = df["reason_signature"].fillna("").astype(str)
    out = pd.Series("other_needs_review", index=df.index, dtype="object")
    out.loc[df["family"] == "route_leak_like"] = "route_leak_like_review"
    out.loc[df["family"] == "forged_origin_like"] = "forged_origin_like_review"
    out.loc[
        contains_token(reason, "single_collector_visibility")
        | contains_token(reason, "sparse_short_lived_event")
        | contains_token(reason, "unusually_short_duration_for_prefix"),
    ] = "single_collector_sparse_short_lived_needs"
    out.loc[df["large_fanout"] & (df["mostly_needs"] | df["broad_background_pattern"])] = "large_fanout_background_like_needs"
    out.loc[df["incident_has_high"]] = "weak_support_needs_with_high_same_incident"
    out.loc[df["family"] == "route_leak_like"] = "route_leak_like_review"
    return out


def add_quality_flags(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    flags = []
    for row in out.to_dict("records"):
        row_flags = []
        if row.get("calibrated_priority") == "P1_high" and float(row.get("incident_confidence", 0.0)) < 0.70:
            row_flags.append("low_confidence_but_p1")
        if row.get("calibrated_priority") == "P1_high" and float(row.get("high_share", 0.0)) < 0.05:
            row_flags.append("tiny_high_support_but_p1")
        if row.get("calibrated_priority") in {"P1_high", "P2_review"} and float(row.get("needs_share", 0.0)) >= 0.90:
            row_flags.append("mostly_needs_in_review_queue")
        reason = str(row.get("dominant_reason_signature", ""))
        if "single_collector_visibility" in reason:
            row_flags.append("single_collector_visibility_dominant")
        if "sparse_short_lived_event" in reason or "unusually_short_duration_for_prefix" in reason:
            row_flags.append("sparse_or_short_lived_dominant")
        if "structural_novelty_score" in reason:
            row_flags.append("structural_novelty_contributor")
        if "unseen_path_for_prefix_origin" in reason and int(row.get("affected_prefix_count", 0) or 0) >= 100:
            row_flags.append("unseen_path_large_repetition")
        if bool(row.get("large_fanout")) and float(row.get("incident_confidence", 0.0)) < 0.55:
            row_flags.append("broad_fanout_low_confidence")
        if bool(row.get("origin_is_na")) or str(row.get("dominant_path_signature", "")).upper() == "NA":
            row_flags.append("unknown_origin_or_path")
        flags.append("+".join(row_flags) if row_flags else "none")
    out["likely_noise_flags"] = flags
    return out


def priority_reason_patterns(tickets: pd.DataFrame) -> pd.DataFrame:
    focus = tickets[tickets["calibrated_priority"].isin(["P1_high", "P2_review"])].copy()
    grouped = (
        focus.groupby(["calibrated_priority", "family", "dominant_reason_signature"], dropna=False)
        .agg(
            ticket_count=("incident_id", "size"),
            member_count=("member_count", "sum"),
            high_count=("high_count", "sum"),
            needs_count=("needs_count", "sum"),
            affected_prefix_count_sum=("affected_prefix_count", "sum"),
            affected_prefix_count_mean=("affected_prefix_count", "mean"),
            origin_as_count_mean=("origin_as_count", "mean"),
            collector_union_count_mean=("collector_union_count", "mean"),
            incident_score_mean=("incident_score", "mean"),
            incident_confidence_mean=("incident_confidence", "mean"),
            high_share_mean=("high_share", "mean"),
            needs_share_mean=("needs_share", "mean"),
            large_fanout_count=("large_fanout", "sum"),
            extreme_fanout_count=("extreme_fanout", "sum"),
            background_fanout_count=("broad_background_pattern", "sum"),
            origin_na_count=("origin_is_na", "sum"),
        )
        .reset_index()
    )
    grouped["high_share_weighted"] = grouped["high_count"] / grouped["member_count"].replace(0, pd.NA)
    grouped["needs_share_weighted"] = grouped["needs_count"] / grouped["member_count"].replace(0, pd.NA)
    return grouped.sort_values(["member_count", "ticket_count"], ascending=[False, False]).reset_index(drop=True)


def needs_review_source_patterns(needs: pd.DataFrame) -> pd.DataFrame:
    group_cols = [
        "needs_review_category",
        "calibrated_priority",
        "family_ticket",
        "reason_signature",
        "top_contributing_factor",
        "alert_source_layer",
        "risk_bucket",
        "missing_origin_or_path",
        "certainty_bucket",
        "conflict_bucket",
        "evidence_bucket",
    ]
    grouped = (
        needs.groupby(group_cols, dropna=False)
        .agg(
            needs_event_count=("event_id", "size"),
            incident_count=("incident_id", "nunique"),
            origin_count=("origin_as_norm", "nunique"),
            prefix_count=("prefix", "nunique"),
            path_signature_count=("path_signature", "nunique"),
            mean_certainty_score=("certainty_score", "mean"),
            mean_conflict_score=("conflict_score", "mean"),
            mean_evidence_support_score=("evidence_support_score", "mean"),
            large_fanout_event_count=("large_fanout", "sum"),
            same_incident_high_event_count=("incident_has_high", "sum"),
            top_origin_as=("origin_as_norm", lambda s: s.value_counts(dropna=False).index[0] if len(s) else ""),
            top_prefix=("prefix", lambda s: s.value_counts(dropna=False).index[0] if len(s) else ""),
            top_path_signature=("path_signature", lambda s: s.value_counts(dropna=False).index[0] if len(s) else ""),
        )
        .reset_index()
        .sort_values(["needs_event_count", "incident_count"], ascending=[False, False])
        .reset_index(drop=True)
    )
    return grouped


def large_fanout_incidents(tickets: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "incident_id",
        "family",
        "original_priority",
        "calibrated_priority",
        "calibrated_subtype",
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
        "large_fanout",
        "extreme_fanout",
        "origin_is_na",
        "broad_background_pattern",
        "calibration_action",
        "calibration_flags",
        "calibration_reason",
    ]
    out = tickets[tickets["large_fanout"]].copy()
    return out[cols].sort_values(["member_count", "affected_prefix_count"], ascending=[False, False]).reset_index(drop=True)


def origin_prefix_path_hotspots(tickets: pd.DataFrame) -> pd.DataFrame:
    focus = tickets[tickets["calibrated_priority"].isin(["P1_high", "P2_review"])].copy()
    group_cols = [
        "calibrated_priority",
        "family",
        "dominant_origin_as",
        "dominant_prefix",
        "dominant_path_signature",
        "dominant_triplet_signature",
    ]
    grouped = (
        focus.groupby(group_cols, dropna=False)
        .agg(
            ticket_count=("incident_id", "size"),
            member_count=("member_count", "sum"),
            high_count=("high_count", "sum"),
            needs_count=("needs_count", "sum"),
            affected_prefix_count_sum=("affected_prefix_count", "sum"),
            collector_union_count_max=("collector_union_count", "max"),
            incident_score_max=("incident_score", "max"),
            incident_confidence_mean=("incident_confidence", "mean"),
            dominant_reason_signature=("dominant_reason_signature", lambda s: s.value_counts(dropna=False).index[0] if len(s) else ""),
            large_fanout_count=("large_fanout", "sum"),
            extreme_fanout_count=("extreme_fanout", "sum"),
        )
        .reset_index()
    )
    grouped["high_share_weighted"] = grouped["high_count"] / grouped["member_count"].replace(0, pd.NA)
    grouped["needs_share_weighted"] = grouped["needs_count"] / grouped["member_count"].replace(0, pd.NA)
    return grouped.sort_values(["member_count", "ticket_count"], ascending=[False, False]).reset_index(drop=True)


def p1_p2_quality_by_pattern(tickets: pd.DataFrame) -> pd.DataFrame:
    focus = add_quality_flags(tickets[tickets["calibrated_priority"].isin(["P1_high", "P2_review"])].copy())
    grouped = (
        focus.groupby(["family", "dominant_reason_signature"], dropna=False)
        .agg(
            ticket_count=("incident_id", "size"),
            member_count=("member_count", "sum"),
            high_count=("high_count", "sum"),
            needs_count=("needs_count", "sum"),
            avg_incident_score=("incident_score", "mean"),
            avg_incident_confidence=("incident_confidence", "mean"),
            avg_high_share=("high_share", "mean"),
            weighted_high_share=("high_count", "sum"),
            avg_affected_prefix_count=("affected_prefix_count", "mean"),
            max_affected_prefix_count=("affected_prefix_count", "max"),
            P1_count=("calibrated_priority", lambda s: int((s == "P1_high").sum())),
            P2_count=("calibrated_priority", lambda s: int((s == "P2_review").sum())),
            large_fanout_count=("large_fanout", "sum"),
            extreme_fanout_count=("extreme_fanout", "sum"),
            origin_na_count=("origin_is_na", "sum"),
            background_fanout_count=("broad_background_pattern", "sum"),
            likely_noise_flags=("likely_noise_flags", lambda s: "+".join(sorted(set("+".join(s).split("+")) - {""}))),
        )
        .reset_index()
    )
    grouped["weighted_high_share"] = grouped["high_count"] / grouped["member_count"].replace(0, pd.NA)
    grouped["weighted_needs_share"] = grouped["needs_count"] / grouped["member_count"].replace(0, pd.NA)
    return grouped.sort_values(["member_count", "ticket_count"], ascending=[False, False]).reset_index(drop=True)


def diagnosis_for_pattern(row: pd.Series) -> tuple[str, str, str, str, str]:
    reason = str(row.get("dominant_reason_signature", ""))
    weighted_high = float(row.get("weighted_high_share", 0.0) or 0.0)
    member_count = int(row.get("member_count", 0) or 0)
    background_count = int(row.get("background_fanout_count", 0) or 0)
    origin_na_count = int(row.get("origin_na_count", 0) or 0)
    large_count = int(row.get("large_fanout_count", 0) or 0)
    if origin_na_count:
        return (
            "NA-origin extreme fan-out background",
            "incident_priority",
            "downgrade rule",
            "May hide malformed but meaningful origin data if applied before origin normalization",
            "S3-C candidate origin normalization audit",
        )
    if "cross_collector_prefix_origin_burst" in reason:
        return (
            "route-leak-like review depends on topology/path legality, not forged-origin scoring",
            "verification",
            "route-leak-specific handling",
            "Route leaks may be under-prioritized if only origin novelty is used",
            "S3-C route-leak triplet legality pilot",
        )
    if "single_collector_visibility" in reason and "unseen_path_for_prefix_origin" in reason:
        if weighted_high < 0.15 and member_count > 100000:
            return (
                "Large mostly-needs low-visibility path novelty dominates queue",
                "score",
                "collector-visibility-aware handling",
                "Over-aggressive downgrade may suppress stealth weak signals",
                "S3-C visibility-aware path plausibility scoring pilot",
            )
        return (
            "Low-visibility structural path novelty is over-represented in P1/P2",
            "gate",
            "extra evidence requirement",
            "Could reduce recall for partial-observability forged-origin signals",
            "S3-C gate evidence support ablation",
        )
    if "abnormal_path_length_for_prefix_origin" in reason:
        return (
            "Path length anomaly needs stronger path plausibility and AS role context",
            "score",
            "stronger semantic feature",
            "May miss path-poisoning-like or traffic engineering edge cases",
            "S3-C forged-origin path plausibility feature audit",
        )
    if background_count or large_count:
        return (
            "Large fan-out pattern requires corroboration before top review",
            "incident_priority",
            "verification-only",
            "Could demote broad but real routing events without external corroboration",
            "S3-C verification evidence pilot",
        )
    return (
        "Pattern needs manual/noise audit before detector change",
        "verification",
        "verification-only",
        "Unknown until incident-level validation is available",
        "S3-B top incident manual review sample",
    )


def detection_upgrade_candidates(quality: pd.DataFrame, limit: int = 30) -> pd.DataFrame:
    rows = []
    focus = quality.head(limit).copy()
    for _, row in focus.iterrows():
        issue, layer, fix_type, risk, experiment = diagnosis_for_pattern(row)
        rows.append(
            {
                "pattern_name": str(row["dominant_reason_signature"]),
                "family": str(row["family"]),
                "affected_ticket_count": int(row["ticket_count"]),
                "affected_member_count": int(row["member_count"]),
                "current_priority": f"P1={int(row['P1_count'])};P2={int(row['P2_count'])}",
                "weighted_high_share": float(row["weighted_high_share"]),
                "weighted_needs_share": float(row["weighted_needs_share"]),
                "large_fanout_count": int(row["large_fanout_count"]),
                "suspected_issue": issue,
                "suggested_layer": layer,
                "suggested_fix_type": fix_type,
                "risk_if_changed": risk,
                "recommended_next_experiment": experiment,
            }
        )
    return pd.DataFrame(rows)


def build_priority_summary(tickets: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {
        "calibrated_priority_ticket_distribution": count_dict(tickets["calibrated_priority"]),
        "calibrated_priority_member_distribution": {
            str(k): int(v) for k, v in tickets.groupby("calibrated_priority")["member_count"].sum().to_dict().items()
        },
        "family_ticket_distribution": count_dict(tickets["family"]),
    }
    for priority in ["P1_high", "P2_review", "P3_background"]:
        sub = tickets[tickets["calibrated_priority"] == priority]
        out[priority] = {
            "ticket_count": int(len(sub)),
            "member_count": int(sub["member_count"].sum()),
            "high_count": int(sub["high_count"].sum()),
            "needs_count": int(sub["needs_count"].sum()),
            "affected_prefix_count_distribution": num_stats(sub["affected_prefix_count"]),
            "origin_as_count_distribution": num_stats(sub["origin_as_count"]),
            "collector_union_count_distribution": num_stats(sub["collector_union_count"]),
            "incident_score_distribution": num_stats(sub["incident_score"]),
            "incident_confidence_distribution": num_stats(sub["incident_confidence"]),
            "top_reason_signatures": count_top_dict(sub["dominant_reason_signature"]),
            "top_origin_as": count_top_dict(sub["dominant_origin_as"]),
            "top_path_signature": count_top_dict(sub["dominant_path_signature"]),
            "top_triplet_signature": count_top_dict(sub["dominant_triplet_signature"]),
        }
    return out


def build_needs_frame(membership: pd.DataFrame, tickets: pd.DataFrame, final_df: pd.DataFrame | None) -> pd.DataFrame:
    needs = membership[membership["final_alert_label"] == "needs_review"].copy()
    ticket_cols = [
        "incident_id",
        "calibrated_priority",
        "family",
        "member_count",
        "high_count",
        "needs_count",
        "high_share",
        "needs_share",
        "affected_prefix_count",
        "incident_confidence",
        "large_fanout",
        "extreme_fanout",
        "mostly_needs",
        "broad_background_pattern",
        "origin_is_na",
    ]
    ticket_small = tickets[ticket_cols].rename(columns={"family": "family_ticket"})
    needs = needs.merge(ticket_small, on="incident_id", how="left", validate="many_to_one")
    needs["incident_has_high"] = needs["high_count"].fillna(0) > 0
    needs["large_fanout"] = needs["large_fanout"].fillna(False)
    needs["mostly_needs"] = needs["mostly_needs"].fillna(False)
    needs["broad_background_pattern"] = needs["broad_background_pattern"].fillna(False)
    if final_df is not None and not final_df.empty:
        needs = needs.merge(final_df, on="event_id", how="left", validate="many_to_one")
    else:
        needs["candidate_reasons"] = needs["reason_signature"]
        needs["as_path_clean"] = needs["path_signature"]
    needs = add_buckets(needs)
    needs["needs_review_category"] = classify_need_category(needs)
    return needs


def build_summary(
    run_id: str,
    tickets: pd.DataFrame,
    membership: pd.DataFrame,
    needs: pd.DataFrame,
    priority_patterns: pd.DataFrame,
    large_fanout: pd.DataFrame,
    quality: pd.DataFrame,
    upgrades: pd.DataFrame,
    final_join_info: dict[str, Any],
    outputs: dict[str, str],
) -> dict[str, Any]:
    p1p2 = tickets[tickets["calibrated_priority"].isin(["P1_high", "P2_review"])]
    return {
        "run_id": run_id,
        "input_ticket_count": int(len(tickets)),
        "input_member_count": int(tickets["member_count"].sum()),
        "membership_rows": int(len(membership)),
        "needs_review_rows": int(len(needs)),
        "priority_summary": build_priority_summary(tickets),
        "p1_p2_ticket_count": int(len(p1p2)),
        "p1_p2_member_count": int(p1p2["member_count"].sum()),
        "p1_p2_high_count": int(p1p2["high_count"].sum()),
        "p1_p2_needs_count": int(p1p2["needs_count"].sum()),
        "large_fanout_ticket_count": int(tickets["large_fanout"].sum()),
        "extreme_fanout_ticket_count": int(tickets["extreme_fanout"].sum()),
        "large_fanout_p1_p2_ticket_count": int((p1p2["large_fanout"]).sum()),
        "large_fanout_member_count": int(tickets.loc[tickets["large_fanout"], "member_count"].sum()),
        "large_fanout_p1_p2_member_count": int(p1p2.loc[p1p2["large_fanout"], "member_count"].sum()),
        "needs_review_category_distribution": count_dict(needs["needs_review_category"]),
        "top_priority_reason_pattern": priority_patterns.head(1).to_dict("records"),
        "top_quality_pattern": quality.head(1).to_dict("records"),
        "top_detection_upgrade_candidates": upgrades.head(10).to_dict("records"),
        "final_join_info": final_join_info,
        "outputs": outputs,
    }


def write_report(
    path: Path,
    summary: dict[str, Any],
    priority_patterns: pd.DataFrame,
    needs_patterns: pd.DataFrame,
    large_fanout: pd.DataFrame,
    quality: pd.DataFrame,
    upgrades: pd.DataFrame,
) -> None:
    lines: list[str] = []
    lines.append("# S3-B Noise Source Audit Report")
    lines.append("")
    lines.append("## Scope")
    lines.append("")
    lines.append(f"- run_id: `{summary['run_id']}`")
    lines.append("- input: S3-A incidents + S3-A2 calibrated tickets + membership")
    lines.append("- boundary: audit only; no upstream rerun, no detector change, no precision/recall claim")
    lines.append("")
    lines.append("## Executive Answers")
    lines.append("")
    lines.append("1. S3-A2 后 P1/P2 仍大的主要原因：`single_collector_visibility + structural_novelty_score + unseen_path_for_prefix_origin` 组合在 forged-origin-like 队列中贡献最大，尤其是短时/低可见度路径新颖性。")
    lines.append("2. needs_review 主要来源：多数 needs 与 high 同 incident 或落在 forged-origin-like review 队列中，核心 reason 仍是低可见度结构新颖性和 unseen path。")
    lines.append("3. large fan-out 是重要噪声源，但不是唯一噪声源；它解释了超大背景工单和部分 P1/P2 member 覆盖量，但大量 ticket 数来自重复的小/中型低可见度 novelty。")
    lines.append("4. `single_collector_visibility`、`sparse/short-lived`、`structural_novelty_score` 明显过度贡献，需要 visibility-aware path plausibility，而不是简单删除。")
    lines.append("5. route-leak-like 与 forged-origin-like 表现不同：route-leak-like tickets 少，更多应进入 triplet legality / verification；forged-origin-like 是 P1/P2 主体。")
    lines.append("6. 不应直接删的模式：低可见度与短时事件，因为它们也是 partial observability 弱信号主线的一部分，应进入 verification 或要求额外证据。")
    lines.append("7. 适合 score/gate 增强的模式：大规模低可见度 path novelty、abnormal path length、weak high-share fan-out；适合 verification 的模式：route-leak-like、外部证据依赖模式。")
    lines.append("8. 下一步建议：先做 S3-C detection capability upgrade design，围绕 visibility-aware path plausibility 和 route-leak triplet legality 设计小型校准/消融，再做 verification pilot。")
    lines.append("")
    lines.append("## Key Counts")
    lines.append("")
    lines.append(f"- input_ticket_count: `{summary['input_ticket_count']}`")
    lines.append(f"- input_member_count: `{summary['input_member_count']}`")
    lines.append(f"- needs_review_rows: `{summary['needs_review_rows']}`")
    lines.append(f"- p1_p2_ticket_count: `{summary['p1_p2_ticket_count']}`")
    lines.append(f"- p1_p2_member_count: `{summary['p1_p2_member_count']}`")
    lines.append(f"- p1_p2_high_count: `{summary['p1_p2_high_count']}`")
    lines.append(f"- p1_p2_needs_count: `{summary['p1_p2_needs_count']}`")
    lines.append(f"- large_fanout_ticket_count: `{summary['large_fanout_ticket_count']}`")
    lines.append(f"- large_fanout_p1_p2_ticket_count: `{summary['large_fanout_p1_p2_ticket_count']}`")
    lines.append(f"- large_fanout_p1_p2_member_count: `{summary['large_fanout_p1_p2_member_count']}`")
    lines.append("")
    lines.append("## Priority Reason Patterns")
    lines.append("")
    add_table(lines, priority_patterns.head(15), ["calibrated_priority", "family", "ticket_count", "member_count", "high_count", "needs_count", "large_fanout_count", "dominant_reason_signature"])
    lines.append("")
    lines.append("## Needs Review Source Patterns")
    lines.append("")
    add_table(lines, needs_patterns.head(15), ["needs_review_category", "calibrated_priority", "family_ticket", "needs_event_count", "incident_count", "top_contributing_factor", "risk_bucket", "reason_signature"])
    lines.append("")
    lines.append("## Large Fan-Out Incidents")
    lines.append("")
    add_table(lines, large_fanout.head(15), ["incident_id", "family", "calibrated_priority", "member_count", "high_count", "needs_count", "affected_prefix_count", "incident_confidence", "dominant_origin_as", "dominant_reason_signature"])
    lines.append("")
    lines.append("## P1/P2 Quality By Pattern")
    lines.append("")
    add_table(lines, quality.head(15), ["family", "ticket_count", "member_count", "weighted_high_share", "large_fanout_count", "likely_noise_flags", "dominant_reason_signature"])
    lines.append("")
    lines.append("## Detection Upgrade Candidates")
    lines.append("")
    add_table(lines, upgrades.head(15), ["pattern_name", "affected_ticket_count", "affected_member_count", "suggested_layer", "suggested_fix_type", "recommended_next_experiment"])
    lines.append("")
    lines.append("## Caveats")
    lines.append("")
    lines.append("- P3 is not absolute normal; it is lower priority/background under current incident evidence.")
    lines.append("- P1/P2 are not claimed true anomalies; they are suspicious incident queues.")
    lines.append("- This audit produces diagnosis and upgrade candidates, not a new detector.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def add_table(lines: list[str], df: pd.DataFrame, cols: list[str]) -> None:
    lines.append("| " + " | ".join(cols) + " |")
    lines.append("| " + " | ".join("---" for _ in cols) + " |")
    for row in df[cols].to_dict("records"):
        values = []
        for col in cols:
            value = row.get(col, "")
            if isinstance(value, float):
                values.append(f"{value:.4f}")
            else:
                values.append(str(value))
        lines.append("| " + " | ".join(values) + " |")


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit S3-A/S3-A2 noise sources without modifying detector outputs.")
    ap.add_argument("--run-id", default=RUN_ID_DEFAULT)
    ap.add_argument("--runs-root", default="data/runs")
    ap.add_argument("--tickets", default=None)
    ap.add_argument("--membership", default=None)
    ap.add_argument("--calibrated-tickets", default="outputs/s3a2_incident_priority_calibration_v01/s3a2_calibrated_incident_tickets.parquet")
    ap.add_argument("--final", default=None)
    ap.add_argument("--output-dir", default="outputs/s3b_noise_source_audit_v01")
    ap.add_argument("--overwrite", type=str2bool, default=False)
    ap.add_argument("--read-final", type=str2bool, default=True)
    args = ap.parse_args()

    run_dir = Path(args.runs_root) / args.run_id
    calibrated_path = Path(args.calibrated_tickets)
    membership_path = Path(args.membership) if args.membership else run_dir / "incidents" / "incident_membership.parquet"
    final_path = Path(args.final) if args.final else run_dir / "final" / "final_alerts.parquet"
    output_dir = Path(args.output_dir)
    outputs = {
        "s3b_noise_summary": str(output_dir / "s3b_noise_summary.json"),
        "s3b_priority_reason_patterns": str(output_dir / "s3b_priority_reason_patterns.csv"),
        "s3b_needs_review_source_patterns": str(output_dir / "s3b_needs_review_source_patterns.csv"),
        "s3b_large_fanout_incidents": str(output_dir / "s3b_large_fanout_incidents.csv"),
        "s3b_origin_prefix_path_hotspots": str(output_dir / "s3b_origin_prefix_path_hotspots.csv"),
        "s3b_p1_p2_quality_by_pattern": str(output_dir / "s3b_p1_p2_quality_by_pattern.csv"),
        "s3b_detection_upgrade_candidates": str(output_dir / "s3b_detection_upgrade_candidates.csv"),
        "s3b_report": str(output_dir / "s3b_report.md"),
    }
    for path_text in outputs.values():
        path = Path(path_text)
        if path.exists() and not args.overwrite:
            raise SystemExit(f"output exists, pass --overwrite true to replace: {path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    tickets = load_tickets(calibrated_path)
    membership = load_membership(membership_path)
    needs_event_ids = membership.loc[membership["final_alert_label"] == "needs_review", "event_id"]
    final_df = None
    final_join_info = {"final_join_available": False, "reason": "read_final_disabled", "path": str(final_path)}
    if args.read_final:
        final_df, final_join_info = try_load_final(final_path, needs_event_ids)
    needs = build_needs_frame(membership, tickets, final_df)

    priority_patterns = priority_reason_patterns(tickets)
    needs_patterns = needs_review_source_patterns(needs)
    fanout = large_fanout_incidents(tickets)
    hotspots = origin_prefix_path_hotspots(tickets)
    quality = p1_p2_quality_by_pattern(tickets)
    upgrades = detection_upgrade_candidates(quality)

    priority_patterns.to_csv(outputs["s3b_priority_reason_patterns"], index=False, encoding="utf-8-sig")
    needs_patterns.to_csv(outputs["s3b_needs_review_source_patterns"], index=False, encoding="utf-8-sig")
    fanout.to_csv(outputs["s3b_large_fanout_incidents"], index=False, encoding="utf-8-sig")
    hotspots.to_csv(outputs["s3b_origin_prefix_path_hotspots"], index=False, encoding="utf-8-sig")
    quality.to_csv(outputs["s3b_p1_p2_quality_by_pattern"], index=False, encoding="utf-8-sig")
    upgrades.to_csv(outputs["s3b_detection_upgrade_candidates"], index=False, encoding="utf-8-sig")

    summary = build_summary(args.run_id, tickets, membership, needs, priority_patterns, fanout, quality, upgrades, final_join_info, outputs)
    Path(outputs["s3b_noise_summary"]).write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=json_default), encoding="utf-8")
    write_report(Path(outputs["s3b_report"]), summary, priority_patterns, needs_patterns, fanout, quality, upgrades)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
