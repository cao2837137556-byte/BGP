import argparse
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq


RUN_ID_DEFAULT = "s2a_expanded_v01_pilot_6h_april16"
PRIORITY_ORDER = {"P1_high": 0, "P2_review": 1, "P3_background": 2}
PRIORITY_SORT = {"P1_high": 0, "P2_review": 1, "P3_background": 2}
BROAD_REASON_TOKENS = {
    "single_collector_visibility",
    "sparse_short_lived_event",
    "structural_novelty_score",
    "unusually_short_duration_for_prefix",
}

TICKET_COLS = [
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

MEMBERSHIP_COLS = [
    "incident_id",
    "event_id",
    "final_alert_label",
    "family",
    "reason_signature",
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


def clean_priority(series: pd.Series) -> pd.Series:
    out = series.fillna("P3_background").astype(str)
    return out.where(out.isin(PRIORITY_ORDER), "P3_background")


def is_origin_na(series: pd.Series) -> pd.Series:
    text = series.fillna("").astype(str).str.strip().str.upper()
    return text.isin({"", "NA", "NAN", "NONE", "NULL"})


def contains_any(series: pd.Series, tokens: set[str]) -> pd.Series:
    text = series.fillna("").astype(str)
    mask = pd.Series(False, index=series.index)
    for token in tokens:
        mask = mask | text.str.contains(token, regex=False, na=False)
    return mask


def quantile_value(series: pd.Series, q: float) -> float:
    if series.empty:
        return 0.0
    value = pd.to_numeric(series, errors="coerce").dropna().quantile(q)
    if pd.isna(value):
        return 0.0
    return float(value)


def describe_series(series: pd.Series) -> dict[str, float]:
    nums = pd.to_numeric(series, errors="coerce").dropna()
    if nums.empty:
        return {
            "count": 0,
            "min": 0.0,
            "p50": 0.0,
            "p90": 0.0,
            "p95": 0.0,
            "p99": 0.0,
            "max": 0.0,
            "mean": 0.0,
        }
    return {
        "count": int(nums.size),
        "min": float(nums.min()),
        "p50": float(nums.quantile(0.50)),
        "p90": float(nums.quantile(0.90)),
        "p95": float(nums.quantile(0.95)),
        "p99": float(nums.quantile(0.99)),
        "max": float(nums.max()),
        "mean": float(nums.mean()),
    }


def count_dict(series: pd.Series) -> dict[str, int]:
    return {str(k): int(v) for k, v in series.value_counts(dropna=False).to_dict().items()}


def build_thresholds(tickets: pd.DataFrame, args: argparse.Namespace) -> dict[str, float]:
    affected_p99 = quantile_value(tickets["affected_prefix_count"], 0.99)
    affected_p999 = quantile_value(tickets["affected_prefix_count"], 0.999)
    member_p99 = quantile_value(tickets["member_count"], 0.99)
    needs_p99 = quantile_value(tickets["needs_count"], 0.99)
    return {
        "affected_prefix_p95": quantile_value(tickets["affected_prefix_count"], 0.95),
        "affected_prefix_p99": affected_p99,
        "affected_prefix_p999": affected_p999,
        "member_count_p99": member_p99,
        "needs_count_p99": needs_p99,
        "large_fanout_threshold": float(args.large_fanout_threshold or max(100, math.ceil(affected_p99))),
        "extreme_fanout_threshold": float(args.extreme_fanout_threshold or max(1000, math.ceil(affected_p999))),
        "large_member_threshold": float(args.large_member_threshold or max(1000, math.ceil(member_p99))),
        "large_needs_threshold": float(args.large_needs_threshold or max(1000, math.ceil(needs_p99))),
        "low_confidence_threshold": float(args.low_confidence_threshold),
        "tiny_high_count_max": float(args.tiny_high_count_max),
        "weak_high_share_threshold": float(args.weak_high_share_threshold),
        "broad_reason_share_threshold": float(args.broad_reason_share_threshold),
    }


def load_tickets(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise SystemExit(f"required tickets input not found: {path}")
    tickets = read_parquet_existing(path, TICKET_COLS)
    for col in [
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
    ]:
        tickets[col] = to_text(tickets, col)
    for col in [
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
        "dominant_label_share",
        "dominant_reason_share",
    ]:
        tickets[col] = to_number(tickets, col)
    tickets["incident_priority"] = clean_priority(tickets["incident_priority"])
    return tickets


def load_membership_check(path: Path, tickets: pd.DataFrame, skip: bool) -> dict[str, Any]:
    if skip or not path.exists():
        return {"membership_checked": False, "reason": "skipped_or_missing", "path": str(path)}
    membership = read_parquet_existing(path, MEMBERSHIP_COLS)
    membership["incident_id"] = to_text(membership, "incident_id")
    membership["final_alert_label"] = to_text(membership, "final_alert_label")
    counts = membership.groupby("incident_id", dropna=False).size().rename("membership_member_count")
    merged = tickets[["incident_id", "member_count"]].merge(counts.reset_index(), on="incident_id", how="left")
    merged["membership_member_count"] = merged["membership_member_count"].fillna(0)
    mismatch = merged[merged["member_count"] != merged["membership_member_count"]]
    return {
        "membership_checked": True,
        "path": str(path),
        "membership_rows": int(len(membership)),
        "membership_incident_count": int(membership["incident_id"].nunique()),
        "ticket_incident_count": int(tickets["incident_id"].nunique()),
        "member_count_sum_from_tickets": int(tickets["member_count"].sum()),
        "member_count_mismatch_count": int(len(mismatch)),
        "final_label_distribution": count_dict(membership["final_alert_label"]),
    }


def add_flag(flag_lists: list[list[str]], reason_lists: list[list[str]], indexes: pd.Index, flag: str, reason: str) -> None:
    for idx in indexes:
        flag_lists[int(idx)].append(flag)
        reason_lists[int(idx)].append(reason)


def downgrade_priority(current: pd.Series, mask: pd.Series, new_priority: str) -> pd.Series:
    out = current.copy()
    new_order = PRIORITY_ORDER[new_priority]
    current_order = out.map(PRIORITY_ORDER).fillna(PRIORITY_ORDER["P3_background"])
    apply_mask = mask & (current_order < new_order)
    out.loc[apply_mask] = new_priority
    return out


def apply_calibration(tickets: pd.DataFrame, thresholds: dict[str, float]) -> pd.DataFrame:
    out = tickets.reset_index(drop=True).copy()
    out["original_priority"] = out["incident_priority"]
    out["calibrated_priority"] = out["incident_priority"]
    out["high_share"] = (out["high_count"] / out["member_count"].replace(0, pd.NA)).fillna(0.0)
    out["needs_share"] = (out["needs_count"] / out["member_count"].replace(0, pd.NA)).fillna(0.0)

    origin_na = is_origin_na(out["dominant_origin_as"])
    large_fanout = out["affected_prefix_count"] >= thresholds["large_fanout_threshold"]
    extreme_fanout = out["affected_prefix_count"] >= thresholds["extreme_fanout_threshold"]
    large_member = out["member_count"] >= thresholds["large_member_threshold"]
    large_needs = out["needs_count"] >= thresholds["large_needs_threshold"]
    low_confidence = out["incident_confidence"] < thresholds["low_confidence_threshold"]
    broad_reason = contains_any(out["dominant_reason_signature"], BROAD_REASON_TOKENS)
    single_broad_reason = broad_reason & (
        out["dominant_reason_share"] >= thresholds["broad_reason_share_threshold"]
    )
    no_high = out["high_count"] == 0
    tiny_high_support = out["high_count"] <= thresholds["tiny_high_count_max"]
    weak_high_share = out["high_share"] < thresholds["weak_high_share_threshold"]

    out["flag_origin_na"] = origin_na
    out["flag_large_fanout"] = large_fanout
    out["flag_extreme_fanout"] = extreme_fanout
    out["flag_low_confidence"] = low_confidence
    out["flag_large_needs_only"] = no_high & large_needs
    out["flag_single_broad_reason_fanout"] = single_broad_reason & large_fanout
    out["flag_background_fanout_candidate"] = extreme_fanout & (
        origin_na | low_confidence | (single_broad_reason & (no_high | weak_high_share))
    )

    flag_lists: list[list[str]] = [[] for _ in range(len(out))]
    reason_lists: list[list[str]] = [[] for _ in range(len(out))]

    masks = [
        (
            origin_na,
            "origin_na",
            "dominant_origin_as is NA or empty",
        ),
        (
            large_fanout,
            "large_fanout",
            f"affected_prefix_count >= {thresholds['large_fanout_threshold']:.0f}",
        ),
        (
            extreme_fanout,
            "extreme_fanout",
            f"affected_prefix_count >= {thresholds['extreme_fanout_threshold']:.0f}",
        ),
        (
            low_confidence,
            "low_confidence",
            f"incident_confidence < {thresholds['low_confidence_threshold']:.2f}",
        ),
        (
            no_high & large_needs,
            "large_needs_only",
            f"high_count=0 and needs_count >= {thresholds['large_needs_threshold']:.0f}",
        ),
        (
            single_broad_reason & large_fanout,
            "single_broad_reason_fanout",
            "single dominant broad reason signature with large fan-out",
        ),
        (
            out["flag_background_fanout_candidate"],
            "background_fanout_candidate",
            "extreme fan-out with NA origin, low confidence, or weak broad reason support",
        ),
    ]
    for mask, flag, reason in masks:
        add_flag(flag_lists, reason_lists, out.index[mask], flag, reason)

    na_extreme_needs_only = origin_na & extreme_fanout & no_high
    out["calibrated_priority"] = downgrade_priority(out["calibrated_priority"], na_extreme_needs_only, "P3_background")
    add_flag(
        flag_lists,
        reason_lists,
        out.index[na_extreme_needs_only],
        "downgrade_na_origin_extreme_needs_only",
        "NA-origin extreme fan-out incident has no high rows; treat as background fan-out",
    )

    p1_low_conf_extreme = (out["original_priority"] == "P1_high") & low_confidence & extreme_fanout
    out["calibrated_priority"] = downgrade_priority(out["calibrated_priority"], p1_low_conf_extreme, "P2_review")
    add_flag(
        flag_lists,
        reason_lists,
        out.index[p1_low_conf_extreme],
        "downgrade_p1_low_confidence_extreme_fanout",
        "P1 incident has low confidence and extreme fan-out; retain for review but not high",
    )

    p1_tiny_high_large = (out["original_priority"] == "P1_high") & tiny_high_support & large_member & large_fanout
    out["calibrated_priority"] = downgrade_priority(out["calibrated_priority"], p1_tiny_high_large, "P2_review")
    add_flag(
        flag_lists,
        reason_lists,
        out.index[p1_tiny_high_large],
        "downgrade_p1_tiny_high_support_large_incident",
        "P1 incident has tiny high support relative to a large fan-out incident",
    )

    p1_weak_high_broad = (out["original_priority"] == "P1_high") & weak_high_share & single_broad_reason & large_fanout
    out["calibrated_priority"] = downgrade_priority(out["calibrated_priority"], p1_weak_high_broad, "P2_review")
    add_flag(
        flag_lists,
        reason_lists,
        out.index[p1_weak_high_broad],
        "downgrade_p1_weak_high_share_broad_fanout",
        "P1 incident is mostly needs_review and supported by broad fan-out reasons",
    )

    p2_background_fanout = (
        (out["original_priority"] == "P2_review")
        & out["flag_background_fanout_candidate"]
        & (origin_na | (no_high & low_confidence))
    )
    out["calibrated_priority"] = downgrade_priority(out["calibrated_priority"], p2_background_fanout, "P3_background")
    add_flag(
        flag_lists,
        reason_lists,
        out.index[p2_background_fanout],
        "downgrade_p2_background_fanout",
        "P2 incident is a low-confidence or NA-origin extreme fan-out background candidate",
    )

    p1_no_high = (out["original_priority"] == "P1_high") & no_high
    out["calibrated_priority"] = downgrade_priority(out["calibrated_priority"], p1_no_high, "P2_review")
    add_flag(
        flag_lists,
        reason_lists,
        out.index[p1_no_high],
        "downgrade_p1_no_high_rows",
        "P1 incident contains no high rows; retain at review at most",
    )

    out["calibration_flags"] = [json.dumps(flags, ensure_ascii=False) for flags in flag_lists]
    out["calibration_reason"] = [
        "; ".join(dict.fromkeys(reasons)) if reasons else "retained_by_default"
        for reasons in reason_lists
    ]
    out["calibration_action"] = out["original_priority"] + "_to_" + out["calibrated_priority"]
    out["calibrated_subtype"] = "retained"
    out.loc[out["calibrated_priority"] == "P1_high", "calibrated_subtype"] = "P1_retained"
    out.loc[
        (out["calibrated_priority"] == "P2_review") & out["flag_low_confidence"],
        "calibrated_subtype",
    ] = "P2_low_confidence_review"
    out.loc[
        (out["calibrated_priority"] == "P2_review") & out["flag_background_fanout_candidate"],
        "calibrated_subtype",
    ] = "P2_background_fanout_review"
    out.loc[
        (out["calibrated_priority"] == "P3_background") & out["flag_background_fanout_candidate"],
        "calibrated_subtype",
    ] = "P3_background_fanout"
    out["is_downgraded"] = out["original_priority"] != out["calibrated_priority"]
    out["priority_rank"] = out["calibrated_priority"].map(PRIORITY_SORT).fillna(99).astype(int)
    return out


def summarize_priority(df: pd.DataFrame, col: str, prefix: str) -> pd.DataFrame:
    grouped = (
        df.groupby(col, dropna=False)
        .agg(
            ticket_count=("incident_id", "size"),
            member_count=("member_count", "sum"),
            high_count=("high_count", "sum"),
            needs_count=("needs_count", "sum"),
            affected_prefix_count=("affected_prefix_count", "sum"),
            mean_incident_score=("incident_score", "mean"),
            mean_incident_confidence=("incident_confidence", "mean"),
        )
        .reset_index()
        .rename(columns={col: "priority"})
    )
    grouped = grouped.rename(
        columns={
            "ticket_count": f"{prefix}_ticket_count",
            "member_count": f"{prefix}_member_count",
            "high_count": f"{prefix}_high_count",
            "needs_count": f"{prefix}_needs_count",
            "affected_prefix_count": f"{prefix}_affected_prefix_count",
            "mean_incident_score": f"{prefix}_mean_incident_score",
            "mean_incident_confidence": f"{prefix}_mean_incident_confidence",
        }
    )
    return grouped


def build_before_after(df: pd.DataFrame) -> pd.DataFrame:
    original = summarize_priority(df, "original_priority", "original")
    calibrated = summarize_priority(df, "calibrated_priority", "calibrated")
    priorities = pd.DataFrame({"priority": ["P1_high", "P2_review", "P3_background"]})
    out = priorities.merge(original, on="priority", how="left").merge(calibrated, on="priority", how="left")
    for col in out.columns:
        if col != "priority":
            out[col] = out[col].fillna(0)
    out["ticket_count_delta"] = out["calibrated_ticket_count"] - out["original_ticket_count"]
    out["member_count_delta"] = out["calibrated_member_count"] - out["original_member_count"]
    return out


def build_na_origin_audit(df: pd.DataFrame) -> pd.DataFrame:
    na = df[df["flag_origin_na"]].copy()
    cols = [
        "incident_id",
        "family",
        "original_priority",
        "calibrated_priority",
        "calibrated_subtype",
        "calibration_action",
        "member_count",
        "high_count",
        "needs_count",
        "affected_prefix_count",
        "collector_union_count",
        "incident_score",
        "incident_confidence",
        "dominant_prefix",
        "dominant_origin_as",
        "dominant_path_signature",
        "dominant_reason_signature",
        "dominant_reason_share",
        "calibration_flags",
        "calibration_reason",
    ]
    return na[cols].sort_values(["member_count", "affected_prefix_count"], ascending=[False, False])


def build_reason_patterns(df: pd.DataFrame) -> pd.DataFrame:
    focus = df[(df["original_priority"].isin(["P1_high", "P2_review"])) | (df["calibrated_priority"].isin(["P1_high", "P2_review"]))]
    grouped = (
        focus.groupby(["original_priority", "calibrated_priority", "family", "dominant_reason_signature"], dropna=False)
        .agg(
            ticket_count=("incident_id", "size"),
            member_count=("member_count", "sum"),
            high_count=("high_count", "sum"),
            needs_count=("needs_count", "sum"),
            affected_prefix_count=("affected_prefix_count", "sum"),
            downgraded_count=("is_downgraded", "sum"),
            origin_na_count=("flag_origin_na", "sum"),
            background_fanout_count=("flag_background_fanout_candidate", "sum"),
            mean_incident_score=("incident_score", "mean"),
            mean_incident_confidence=("incident_confidence", "mean"),
            max_member_count=("member_count", "max"),
            max_affected_prefix_count=("affected_prefix_count", "max"),
        )
        .reset_index()
        .sort_values(["member_count", "ticket_count"], ascending=[False, False])
        .reset_index(drop=True)
    )
    if not grouped.empty:
        diagnoses = grouped.apply(diagnose_reason_pattern, axis=1, result_type="expand")
        grouped["diagnosis"] = diagnoses[0]
        grouped["suggested_upgrade_layer"] = diagnoses[1]
    return grouped


def diagnose_reason_pattern(row: pd.Series) -> tuple[str, str]:
    reason = str(row.get("dominant_reason_signature", ""))
    origin_na_count = int(row.get("origin_na_count", 0) or 0)
    background_count = int(row.get("background_fanout_count", 0) or 0)
    if origin_na_count > 0:
        return (
            "unknown-origin extreme fan-out background; avoid treating score-only fan-out as review-worthy",
            "incident priority calibration / candidate origin normalization",
        )
    if "cross_collector_prefix_origin_burst" in reason:
        return (
            "route-leak-like burst pattern; needs triplet legality and external context before priority escalation",
            "incident / verification",
        )
    if "unseen_path_for_prefix_origin" in reason and "structural_novelty_score" in reason:
        if "single_collector_visibility" in reason or "unusually_short_duration_for_prefix" in reason:
            return (
                "transient low-visibility structural novelty dominates queue; needs visibility-aware path plausibility",
                "score / gate",
            )
        return (
            "forged-origin-like path novelty; add stronger path plausibility and historical path semantics",
            "score",
        )
    if "abnormal_path_length_for_prefix_origin" in reason:
        return (
            "path length anomaly; compare against path plausibility and role/churn context",
            "score / gate",
        )
    if background_count > 0:
        return (
            "large fan-out background candidate; keep out of top review unless corroborated",
            "incident priority calibration",
        )
    return (
        "review pattern requires S3-B manual/noise audit before detector changes",
        "S3-B audit",
    )


def build_top_calibrated(df: pd.DataFrame, top_n: int) -> pd.DataFrame:
    cols = [
        "incident_id",
        "family",
        "original_priority",
        "calibrated_priority",
        "calibrated_subtype",
        "calibration_action",
        "member_count",
        "high_count",
        "needs_count",
        "high_share",
        "affected_prefix_count",
        "collector_union_count",
        "incident_score",
        "incident_confidence",
        "dominant_prefix",
        "dominant_origin_as",
        "dominant_path_signature",
        "dominant_triplet_signature",
        "dominant_top_factor",
        "dominant_reason_signature",
        "dominant_reason_share",
        "calibration_flags",
        "calibration_reason",
    ]
    pieces = []
    for priority in ["P1_high", "P2_review"]:
        sub = df[df["calibrated_priority"] == priority].copy()
        sub = sub.sort_values(
            ["incident_score", "member_count", "incident_confidence"],
            ascending=[False, False, False],
        ).head(top_n)
        sub.insert(0, "calibrated_queue", f"top_calibrated_{priority}")
        pieces.append(sub[["calibrated_queue"] + cols])
    if pieces:
        return pd.concat(pieces, ignore_index=True)
    return pd.DataFrame(columns=["calibrated_queue"] + cols)


def action_counts(df: pd.DataFrame) -> dict[str, int]:
    return count_dict(df["calibration_action"])


def build_summary(
    run_id: str,
    tickets: pd.DataFrame,
    calibrated: pd.DataFrame,
    thresholds: dict[str, float],
    membership_check: dict[str, Any],
    output_paths: dict[str, str],
) -> dict[str, Any]:
    downgraded = calibrated[calibrated["is_downgraded"]]
    na = calibrated[calibrated["flag_origin_na"]]
    return {
        "run_id": run_id,
        "input_ticket_count": int(len(tickets)),
        "input_member_count": int(tickets["member_count"].sum()),
        "thresholds": thresholds,
        "original_priority_ticket_distribution": count_dict(calibrated["original_priority"]),
        "calibrated_priority_ticket_distribution": count_dict(calibrated["calibrated_priority"]),
        "original_priority_member_distribution": {
            str(k): int(v) for k, v in calibrated.groupby("original_priority")["member_count"].sum().to_dict().items()
        },
        "calibrated_priority_member_distribution": {
            str(k): int(v) for k, v in calibrated.groupby("calibrated_priority")["member_count"].sum().to_dict().items()
        },
        "calibration_action_counts": action_counts(calibrated),
        "downgraded_ticket_count": int(len(downgraded)),
        "downgraded_member_count": int(downgraded["member_count"].sum()),
        "p1_downgraded_ticket_count": int(((calibrated["original_priority"] == "P1_high") & calibrated["is_downgraded"]).sum()),
        "p2_downgraded_ticket_count": int(((calibrated["original_priority"] == "P2_review") & calibrated["is_downgraded"]).sum()),
        "na_origin_ticket_count": int(len(na)),
        "na_origin_member_count": int(na["member_count"].sum()),
        "na_origin_high_count": int(na["high_count"].sum()),
        "na_origin_needs_count": int(na["needs_count"].sum()),
        "na_origin_downgraded_ticket_count": int(na["is_downgraded"].sum()),
        "na_origin_downgraded_member_count": int(na.loc[na["is_downgraded"], "member_count"].sum()),
        "na_origin_affected_prefix_distribution": describe_series(na["affected_prefix_count"]),
        "na_origin_incident_score_distribution": describe_series(na["incident_score"]),
        "na_origin_incident_confidence_distribution": describe_series(na["incident_confidence"]),
        "na_origin_top_reason_patterns": count_dict(na["dominant_reason_signature"].head(100000)),
        "flag_counts": {
            col: int(calibrated[col].sum())
            for col in [
                "flag_origin_na",
                "flag_large_fanout",
                "flag_extreme_fanout",
                "flag_low_confidence",
                "flag_large_needs_only",
                "flag_single_broad_reason_fanout",
                "flag_background_fanout_candidate",
            ]
        },
        "membership_check": membership_check,
        "outputs": output_paths,
    }


def write_report(path: Path, summary: dict[str, Any], before_after: pd.DataFrame, reason_patterns: pd.DataFrame, top: pd.DataFrame) -> None:
    lines = []
    lines.append("# S3-A2 Incident Priority Calibration Report")
    lines.append("")
    lines.append("## Scope")
    lines.append("")
    lines.append(f"- run_id: `{summary['run_id']}`")
    lines.append("- input: S3-A incident tickets/membership only; no upstream detection rerun")
    lines.append("- policy: preserve original `incident_priority`; add calibrated fields")
    lines.append("")
    lines.append("## Thresholds")
    lines.append("")
    for key, value in summary["thresholds"].items():
        lines.append(f"- {key}: `{value}`")
    lines.append("")
    lines.append("## Before / After")
    lines.append("")
    cols = [
        "priority",
        "original_ticket_count",
        "calibrated_ticket_count",
        "ticket_count_delta",
        "original_member_count",
        "calibrated_member_count",
        "member_count_delta",
    ]
    lines.append("| " + " | ".join(cols) + " |")
    lines.append("| " + " | ".join("---" for _ in cols) + " |")
    for row in before_after[cols].to_dict("records"):
        lines.append("| " + " | ".join(str(row.get(col, "")) for col in cols) + " |")
    lines.append("")
    lines.append("## Downgrades")
    lines.append("")
    lines.append(f"- downgraded_ticket_count: `{summary['downgraded_ticket_count']}`")
    lines.append(f"- downgraded_member_count: `{summary['downgraded_member_count']}`")
    lines.append(f"- p1_downgraded_ticket_count: `{summary['p1_downgraded_ticket_count']}`")
    lines.append(f"- p2_downgraded_ticket_count: `{summary['p2_downgraded_ticket_count']}`")
    lines.append(f"- na_origin_downgraded_ticket_count: `{summary['na_origin_downgraded_ticket_count']}`")
    lines.append(f"- na_origin_downgraded_member_count: `{summary['na_origin_downgraded_member_count']}`")
    lines.append("")
    lines.append("## NA-Origin Audit")
    lines.append("")
    lines.append(f"- na_origin_ticket_count: `{summary['na_origin_ticket_count']}`")
    lines.append(f"- na_origin_member_count: `{summary['na_origin_member_count']}`")
    lines.append(f"- na_origin_high_count: `{summary['na_origin_high_count']}`")
    lines.append(f"- na_origin_needs_count: `{summary['na_origin_needs_count']}`")
    lines.append(f"- affected_prefix_distribution: `{json.dumps(summary['na_origin_affected_prefix_distribution'], ensure_ascii=False)}`")
    lines.append(f"- confidence_distribution: `{json.dumps(summary['na_origin_incident_confidence_distribution'], ensure_ascii=False)}`")
    lines.append("")
    lines.append("## Top Reason Patterns")
    lines.append("")
    rcols = [
        "original_priority",
        "calibrated_priority",
        "family",
        "ticket_count",
        "member_count",
        "high_count",
        "needs_count",
        "downgraded_count",
        "origin_na_count",
        "background_fanout_count",
        "diagnosis",
        "suggested_upgrade_layer",
        "dominant_reason_signature",
    ]
    lines.append("| " + " | ".join(rcols) + " |")
    lines.append("| " + " | ".join("---" for _ in rcols) + " |")
    for row in reason_patterns[rcols].head(20).to_dict("records"):
        lines.append("| " + " | ".join(str(row.get(col, "")) for col in rcols) + " |")
    lines.append("")
    lines.append("## Top Calibrated P1/P2")
    lines.append("")
    tcols = [
        "calibrated_queue",
        "incident_id",
        "family",
        "original_priority",
        "calibrated_priority",
        "member_count",
        "high_count",
        "needs_count",
        "affected_prefix_count",
        "incident_score",
        "incident_confidence",
        "dominant_origin_as",
        "dominant_reason_signature",
    ]
    lines.append("| " + " | ".join(tcols) + " |")
    lines.append("| " + " | ".join("---" for _ in tcols) + " |")
    for row in top[tcols].head(20).to_dict("records"):
        values = []
        for col in tcols:
            value = row.get(col, "")
            if isinstance(value, float):
                values.append(f"{value:.4f}")
            else:
                values.append(str(value))
        lines.append("| " + " | ".join(values) + " |")
    lines.append("")
    lines.append("## Interpretation")
    lines.append("")
    lines.append("- This is not a new detector; it is incident-level priority calibration.")
    lines.append("- Use calibrated P1/P2 for S3-B noise source audit and later top-K verification.")
    lines.append("- Keep original `incident_priority` for before/after comparisons and reproducibility.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_outputs(output_dir: Path, calibrated: pd.DataFrame, summary: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    before_after = build_before_after(calibrated)
    na_audit = build_na_origin_audit(calibrated)
    reason_patterns = build_reason_patterns(calibrated)
    top_calibrated = build_top_calibrated(calibrated, top_n=100)

    calibrated.to_parquet(output_dir / "s3a2_calibrated_incident_tickets.parquet", index=False)
    before_after.to_csv(output_dir / "s3a2_priority_before_after.csv", index=False, encoding="utf-8-sig")
    na_audit.to_csv(output_dir / "s3a2_na_origin_audit.csv", index=False, encoding="utf-8-sig")
    reason_patterns.to_csv(output_dir / "s3a2_p1_p2_reason_patterns.csv", index=False, encoding="utf-8-sig")
    top_calibrated.to_csv(output_dir / "s3a2_top_calibrated_incidents.csv", index=False, encoding="utf-8-sig")
    summary_path = output_dir / "s3a2_priority_summary.json"
    report_path = output_dir / "s3a2_report.md"
    summary["outputs"]["s3a2_calibrated_incident_tickets"] = str(output_dir / "s3a2_calibrated_incident_tickets.parquet")
    summary["outputs"]["s3a2_priority_before_after"] = str(output_dir / "s3a2_priority_before_after.csv")
    summary["outputs"]["s3a2_na_origin_audit"] = str(output_dir / "s3a2_na_origin_audit.csv")
    summary["outputs"]["s3a2_p1_p2_reason_patterns"] = str(output_dir / "s3a2_p1_p2_reason_patterns.csv")
    summary["outputs"]["s3a2_top_calibrated_incidents"] = str(output_dir / "s3a2_top_calibrated_incidents.csv")
    summary["outputs"]["s3a2_priority_summary"] = str(summary_path)
    summary["outputs"]["s3a2_report"] = str(report_path)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=json_default), encoding="utf-8")
    write_report(report_path, summary, before_after, reason_patterns, top_calibrated)


def main() -> int:
    ap = argparse.ArgumentParser(description="Calibrate S3-A incident priority without modifying original incident tickets.")
    ap.add_argument("--run-id", default=RUN_ID_DEFAULT)
    ap.add_argument("--runs-root", default="data/runs")
    ap.add_argument("--tickets", default=None)
    ap.add_argument("--membership", default=None)
    ap.add_argument("--output-dir", default="outputs/s3a2_incident_priority_calibration_v01")
    ap.add_argument("--overwrite", type=str2bool, default=False)
    ap.add_argument("--skip-membership", type=str2bool, default=False)
    ap.add_argument("--low-confidence-threshold", type=float, default=0.55)
    ap.add_argument("--large-fanout-threshold", type=float, default=None)
    ap.add_argument("--extreme-fanout-threshold", type=float, default=None)
    ap.add_argument("--large-member-threshold", type=float, default=None)
    ap.add_argument("--large-needs-threshold", type=float, default=None)
    ap.add_argument("--tiny-high-count-max", type=float, default=5.0)
    ap.add_argument("--weak-high-share-threshold", type=float, default=0.05)
    ap.add_argument("--broad-reason-share-threshold", type=float, default=0.90)
    args = ap.parse_args()

    run_dir = Path(args.runs_root) / args.run_id
    tickets_path = Path(args.tickets) if args.tickets else run_dir / "incidents" / "incident_tickets.parquet"
    membership_path = Path(args.membership) if args.membership else run_dir / "incidents" / "incident_membership.parquet"
    output_dir = Path(args.output_dir)
    expected_outputs = [
        output_dir / "s3a2_priority_summary.json",
        output_dir / "s3a2_priority_before_after.csv",
        output_dir / "s3a2_na_origin_audit.csv",
        output_dir / "s3a2_p1_p2_reason_patterns.csv",
        output_dir / "s3a2_top_calibrated_incidents.csv",
        output_dir / "s3a2_report.md",
        output_dir / "s3a2_calibrated_incident_tickets.parquet",
    ]
    for path in expected_outputs:
        if path.exists() and not args.overwrite:
            raise SystemExit(f"output exists, pass --overwrite true to replace: {path}")

    tickets = load_tickets(tickets_path)
    thresholds = build_thresholds(tickets, args)
    calibrated = apply_calibration(tickets, thresholds)
    membership_check = load_membership_check(membership_path, tickets, args.skip_membership)
    output_paths = {
        "input_tickets": str(tickets_path),
        "input_membership": str(membership_path),
        "output_dir": str(output_dir),
    }
    summary = build_summary(args.run_id, tickets, calibrated, thresholds, membership_check, output_paths)
    write_outputs(output_dir, calibrated, summary)

    print(json.dumps(summary, ensure_ascii=False, indent=2, default=json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
