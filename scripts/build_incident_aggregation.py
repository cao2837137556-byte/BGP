import argparse
import json
import math
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq


RUN_ID_DEFAULT = "s2a_expanded_v01_pilot_6h_april16"
ALERT_LABELS = {"high_priority_alert", "needs_review"}

FINAL_COLS = [
    "event_id",
    "run_id",
    "prefix",
    "origin_as",
    "as_path_clean",
    "risk_score",
    "risk_bucket",
    "gating_label",
    "augmentation_label",
    "final_alert_label",
    "alert_source_layer",
    "top_contributing_factor",
    "candidate_reasons",
    "missing_origin_or_path",
    "certainty_score",
    "conflict_score",
    "evidence_support_score",
]

EVENT_COLS = [
    "event_id",
    "first_seen",
    "last_seen",
    "duration_sec",
    "record_count",
    "collector_set",
    "collector_count",
    "visibility_count",
]

FAMILY_REASON_RULES = {
    "route_leak_like": {
        "cross_collector_prefix_origin_burst",
    },
    "forged_origin_like": {
        "unseen_origin_for_prefix",
        "unseen_exact_path",
        "unseen_path_for_prefix_origin",
        "weak_path_history",
        "abnormal_path_length_for_prefix_origin",
    },
    "stealth_visibility_like": {
        "single_collector_visibility",
        "unusually_low_visibility_for_prefix",
        "unusually_low_visibility_for_prefix_origin",
        "sparse_short_lived_event",
    },
}


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


def to_bool_series(series: pd.Series) -> pd.Series:
    if series.empty:
        return pd.Series(dtype=bool)
    if series.dtype == bool:
        return series.fillna(False)
    return series.astype(str).str.strip().str.lower().isin({"1", "true", "yes", "y", "on"})


def to_text(df: pd.DataFrame, col: str, default: str = "") -> pd.Series:
    if col not in df.columns:
        return pd.Series(default, index=df.index, dtype="object")
    return df[col].fillna(default).astype(str)


def to_number(df: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in df.columns:
        return pd.Series(default, index=df.index, dtype="float64")
    return pd.to_numeric(df[col], errors="coerce").fillna(default)


def normalize_origin(value) -> str:
    if value is None or pd.isna(value):
        return "NA"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value).strip()
    if numeric.is_integer():
        return str(int(numeric))
    return str(numeric)


@lru_cache(maxsize=200000)
def parse_jsonish_tuple(text_value: str) -> tuple[str, ...]:
    text = str(text_value).strip()
    if not text or text.lower() == "nan":
        return ()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return tuple(str(item).strip() for item in parsed if str(item).strip())
        if isinstance(parsed, str):
            parsed = parsed.strip()
            return (parsed,) if parsed else ()
    except Exception:
        pass
    tokens = re.split(r"[,;|\s]+", text.strip("[](){} "))
    return tuple(tok.strip("'\" ") for tok in tokens if tok.strip("'\" "))


def parse_jsonish_list(value) -> list[str]:
    if value is None or pd.isna(value):
        return []
    return list(parse_jsonish_tuple(str(value)))


def reason_signature(reasons: list[str], top_factor: str) -> str:
    tokens = [tok for tok in reasons if tok]
    if top_factor:
        tokens.append(str(top_factor))
    uniq = sorted(set(tokens))
    return "+".join(uniq[:4]) if uniq else "none"


def path_signature(path_text: str, tail_len: int = 3) -> str:
    tokens = re.findall(r"\d+", str(path_text or ""))
    if not tokens:
        return "NA"
    return " ".join(tokens[-tail_len:])


def triplet_signature(path_text: str) -> str:
    tokens = re.findall(r"\d+", str(path_text or ""))
    if len(tokens) < 3:
        return "NA"
    return " ".join(tokens[-3:])


def parse_collector_set(value) -> set[str]:
    if value is None or pd.isna(value):
        return set()
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return set()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return {str(item).strip() for item in parsed if str(item).strip()}
    except Exception:
        pass
    return {tok.strip("'\" ") for tok in re.split(r"[,;| ]+", text.strip("[]{}()")) if tok.strip("'\" ")}


def contains_any(series: pd.Series, needles: set[str]) -> pd.Series:
    mask = pd.Series(False, index=series.index)
    for needle in needles:
        mask = mask | series.str.contains(needle, regex=False, na=False)
    return mask


def classify_family(base: pd.DataFrame) -> pd.Series:
    reason_text = base["candidate_reasons"].fillna("").astype(str)
    family = pd.Series("unknown_weak_signal", index=base.index, dtype="object")
    stealth_mask = contains_any(reason_text, FAMILY_REASON_RULES["stealth_visibility_like"]) | (
        (base["collector_count"] <= 1.0) | (base["visibility_count"] <= 1.0)
    )
    forged_mask = contains_any(reason_text, FAMILY_REASON_RULES["forged_origin_like"])
    route_mask = contains_any(reason_text, FAMILY_REASON_RULES["route_leak_like"])
    family.loc[stealth_mask] = "stealth_visibility_like"
    family.loc[forged_mask] = "forged_origin_like"
    family.loc[route_mask] = "route_leak_like"
    return family


def load_base_alerts(run_dir: Path, final_path: Path | None, events_path: Path | None) -> pd.DataFrame:
    final_path = final_path or run_dir / "final" / "final_alerts.parquet"
    events_path = events_path or run_dir / "events" / "event_units.parquet"
    for path in [final_path, events_path]:
        if not path.exists():
            raise SystemExit(f"required input not found: {path}")

    final_df = read_parquet_existing(final_path, FINAL_COLS)
    final_df["event_id"] = to_text(final_df, "event_id")
    final_df["run_id"] = to_text(final_df, "run_id")
    final_df["prefix"] = to_text(final_df, "prefix")
    final_df["origin_as_norm"] = final_df.get("origin_as", pd.Series(index=final_df.index)).map(normalize_origin)
    final_df["as_path_clean"] = to_text(final_df, "as_path_clean")
    for col in ["risk_bucket", "gating_label", "augmentation_label", "final_alert_label", "alert_source_layer", "top_contributing_factor"]:
        final_df[col] = to_text(final_df, col)
    final_df["candidate_reasons"] = to_text(final_df, "candidate_reasons", default="[]")
    final_df["risk_score"] = to_number(final_df, "risk_score")
    final_df["certainty_score"] = to_number(final_df, "certainty_score")
    final_df["conflict_score"] = to_number(final_df, "conflict_score")
    final_df["evidence_support_score"] = to_number(final_df, "evidence_support_score", default=float("nan"))
    final_df["missing_origin_or_path"] = to_bool_series(final_df.get("missing_origin_or_path", pd.Series(False, index=final_df.index)))
    final_df = final_df[final_df["final_alert_label"].isin(ALERT_LABELS)].copy()

    events_df = read_parquet_existing(events_path, EVENT_COLS)
    events_df["event_id"] = to_text(events_df, "event_id")
    for col in ["first_seen", "last_seen", "duration_sec", "record_count", "collector_count", "visibility_count"]:
        events_df[col] = to_number(events_df, col)
    events_df["collector_set"] = to_text(events_df, "collector_set")

    base = final_df.merge(events_df, on="event_id", how="left", validate="many_to_one")
    for col in ["first_seen", "last_seen", "duration_sec", "record_count", "collector_count", "visibility_count"]:
        base[col] = to_number(base, col)
    base["collector_set"] = to_text(base, "collector_set")
    base["reason_signature"] = [
        reason_signature(parse_jsonish_list(raw_reasons), top_factor)
        for raw_reasons, top_factor in zip(base["candidate_reasons"], base["top_contributing_factor"], strict=False)
    ]
    base["family"] = classify_family(base)
    base["path_signature"] = base["as_path_clean"].map(path_signature)
    base["triplet_signature"] = base["as_path_clean"].map(triplet_signature)
    base["time_bucket_micro"] = (base["first_seen"] // 900).fillna(0).astype("int64")
    return base


def assign_micro_incidents(base: pd.DataFrame, micro_window_sec: int) -> pd.DataFrame:
    sort_cols = ["family", "prefix", "origin_as_norm", "path_signature", "first_seen", "last_seen", "event_id"]
    out = base.sort_values(sort_cols).reset_index(drop=True).copy()
    group_cols = ["family", "prefix", "origin_as_norm", "path_signature"]
    prev_last = out.groupby(group_cols, dropna=False)["last_seen"].shift(1)
    is_new = prev_last.isna() | ((out["first_seen"] - prev_last) > float(micro_window_sec))
    out["micro_seq"] = is_new.astype("int64").groupby([out[col] for col in group_cols], dropna=False).cumsum()
    out["micro_incident_key"] = (
        out["family"]
        + "|"
        + out["prefix"]
        + "|"
        + out["origin_as_norm"]
        + "|"
        + out["path_signature"]
        + "|"
        + out["micro_seq"].astype(str)
    )
    micro_codes, uniques = pd.factorize(out["micro_incident_key"], sort=True)
    out["micro_incident_id"] = [f"micro_{idx:09d}" for idx in micro_codes]
    return out


def choose_macro_key(row: pd.Series, macro_window_sec: int) -> str:
    bucket = int(float(row.get("micro_start", 0.0) or 0.0) // float(macro_window_sec))
    family = str(row.get("family", "unknown_weak_signal"))
    origin = str(row.get("dominant_origin_as", row.get("origin_as_norm", "NA")))
    prefix = str(row.get("dominant_prefix", row.get("prefix", "")))
    path_sig = str(row.get("dominant_path_signature", row.get("path_signature", "NA")))
    triplet = str(row.get("dominant_triplet_signature", row.get("triplet_signature", "NA")))
    reason = str(row.get("dominant_reason_signature", row.get("reason_signature", "none")))
    if family == "route_leak_like":
        key = f"{family}|origin={origin}|triplet={triplet}|bucket={bucket}"
    elif family == "forged_origin_like":
        key = f"{family}|origin={origin}|path={path_sig}|bucket={bucket}"
    elif family == "stealth_visibility_like":
        key = f"{family}|origin={origin}|reason={reason}|bucket={bucket}"
    else:
        key = f"{family}|prefix={prefix}|origin={origin}|bucket={bucket}"
    return key


def mode_or_empty(series: pd.Series) -> str:
    non_empty = series.fillna("").astype(str)
    non_empty = non_empty[non_empty != ""]
    if non_empty.empty:
        return ""
    return str(non_empty.mode(dropna=True).iloc[0])


def build_micro_table(member_df: pd.DataFrame) -> pd.DataFrame:
    grouped = member_df.groupby("micro_incident_id", dropna=False)
    micro = grouped.agg(
        family=("family", "first"),
        member_count=("event_id", "size"),
        micro_start=("first_seen", "min"),
        micro_end=("last_seen", "max"),
        dominant_prefix=("prefix", mode_or_empty),
        dominant_origin_as=("origin_as_norm", mode_or_empty),
        dominant_path_signature=("path_signature", mode_or_empty),
        dominant_triplet_signature=("triplet_signature", mode_or_empty),
        dominant_reason_signature=("reason_signature", mode_or_empty),
        max_risk_score=("risk_score", "max"),
        mean_risk_score=("risk_score", "mean"),
        mean_certainty_score=("certainty_score", "mean"),
        mean_conflict_score=("conflict_score", "mean"),
        high_count=("final_alert_label", lambda s: int((s == "high_priority_alert").sum())),
        needs_count=("final_alert_label", lambda s: int((s == "needs_review").sum())),
    ).reset_index()
    return micro


def assign_macro_incidents(member_df: pd.DataFrame, micro_df: pd.DataFrame, macro_window_sec: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    micro = micro_df.copy()
    micro["macro_key"] = micro.apply(lambda row: choose_macro_key(row, macro_window_sec), axis=1)
    macro_codes, _ = pd.factorize(micro["macro_key"], sort=True)
    micro["incident_id"] = [f"incident_{idx:09d}" for idx in macro_codes]
    out = member_df.merge(micro[["micro_incident_id", "incident_id"]], on="micro_incident_id", how="left", validate="many_to_one")
    return out, micro


def counter_json(values: pd.Series, limit: int = 10) -> str:
    counts = Counter()
    for value in values:
        if isinstance(value, list):
            for item in value:
                text = str(item).strip()
                if text:
                    counts[text] += 1
        else:
            text = "" if value is None or pd.isna(value) else str(value).strip()
            if text:
                counts[text] += 1
    return json.dumps(dict(counts.most_common(limit)), ensure_ascii=False)


def collector_union_count(values: pd.Series) -> int:
    union = set()
    for value in values:
        union.update(parse_collector_set(value))
    return len(union)


def top_list_json(values: pd.Series, limit: int = 8) -> str:
    counts = Counter(str(v) for v in values.fillna("").astype(str) if str(v))
    return json.dumps([{"value": key, "count": int(count)} for key, count in counts.most_common(limit)], ensure_ascii=False)


def dominant_share(values: pd.Series) -> float:
    counts = Counter(str(v) for v in values.fillna("").astype(str) if str(v))
    total = sum(counts.values())
    if not total:
        return 0.0
    return float(counts.most_common(1)[0][1] / total)


def build_ticket_table(member_df: pd.DataFrame, micro_df: pd.DataFrame) -> pd.DataFrame:
    grouped = member_df.groupby("incident_id", dropna=False)
    tickets = grouped.agg(
        run_id=("run_id", mode_or_empty),
        family=("family", mode_or_empty),
        member_count=("event_id", "size"),
        micro_incident_count=("micro_incident_id", "nunique"),
        affected_prefix_count=("prefix", "nunique"),
        origin_as_count=("origin_as_norm", "nunique"),
        path_signature_count=("path_signature", "nunique"),
        triplet_signature_count=("triplet_signature", "nunique"),
        collector_union_count=("collector_set", collector_union_count),
        incident_start=("first_seen", "min"),
        incident_end=("last_seen", "max"),
        max_risk_score=("risk_score", "max"),
        mean_risk_score=("risk_score", "mean"),
        p95_risk_score=("risk_score", lambda s: float(s.quantile(0.95))),
        mean_certainty_score=("certainty_score", "mean"),
        mean_conflict_score=("conflict_score", "mean"),
        mean_evidence_support_score=("evidence_support_score", "mean"),
        missing_rate=("missing_origin_or_path", "mean"),
        high_count=("final_alert_label", lambda s: int((s == "high_priority_alert").sum())),
        needs_count=("final_alert_label", lambda s: int((s == "needs_review").sum())),
        dominant_prefix=("prefix", mode_or_empty),
        dominant_origin_as=("origin_as_norm", mode_or_empty),
        dominant_path_signature=("path_signature", mode_or_empty),
        dominant_triplet_signature=("triplet_signature", mode_or_empty),
        dominant_top_factor=("top_contributing_factor", mode_or_empty),
        dominant_reason_signature=("reason_signature", mode_or_empty),
        dominant_label_share=("final_alert_label", dominant_share),
        dominant_reason_share=("reason_signature", dominant_share),
        label_distribution=("final_alert_label", counter_json),
        source_layer_distribution=("alert_source_layer", counter_json),
        reason_distribution=("reason_signature", counter_json),
        top_prefixes=("prefix", top_list_json),
        top_origin_as=("origin_as_norm", top_list_json),
    ).reset_index()

    tickets["incident_duration_sec"] = tickets["incident_end"] - tickets["incident_start"]
    tickets["has_high"] = tickets["high_count"] > 0
    tickets["time_compactness"] = (1.0 - (tickets["incident_duration_sec"].clip(lower=0, upper=7200) / 7200.0)).fillna(0.0)
    tickets["scope_score"] = (
        tickets["member_count"].map(lambda v: min(20.0, math.log1p(float(v)) * 3.0))
        + tickets["affected_prefix_count"].map(lambda v: min(20.0, math.log1p(float(v)) * 4.0))
        + tickets["collector_union_count"].map(lambda v: min(10.0, float(v) * 2.0))
    )
    evidence = tickets["mean_evidence_support_score"].fillna(0.0).clip(lower=0.0, upper=100.0)
    conflict_penalty = tickets["mean_conflict_score"].fillna(0.0).clip(lower=0.0, upper=30.0) * 0.35
    tickets["incident_score"] = (
        tickets["p95_risk_score"].fillna(0.0) * 0.45
        + tickets["mean_certainty_score"].fillna(0.0) * 0.20
        + evidence * 0.15
        + tickets["scope_score"].fillna(0.0)
        - conflict_penalty
    ).clip(lower=0.0, upper=100.0).round(4)
    tickets["incident_confidence"] = (
        tickets["dominant_reason_share"].fillna(0.0) * 0.40
        + tickets["dominant_label_share"].fillna(0.0) * 0.25
        + (1.0 - tickets["missing_rate"].fillna(0.0).clip(lower=0.0, upper=1.0)) * 0.20
        + tickets["time_compactness"].fillna(0.0) * 0.15
    ).clip(lower=0.0, upper=1.0).round(4)
    tickets["incident_priority"] = "P3_background"
    p1 = tickets["has_high"] & (tickets["incident_confidence"] >= 0.70)
    p2 = (~p1) & ((tickets["incident_score"] >= 55.0) | ((tickets["family"] == "route_leak_like") & (tickets["affected_prefix_count"] >= 5)))
    tickets.loc[p1, "incident_priority"] = "P1_high"
    tickets.loc[p2, "incident_priority"] = "P2_review"
    tickets["explanation"] = tickets.apply(build_explanation, axis=1)

    ordered_cols = [
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
    return tickets[ordered_cols].sort_values(["incident_priority", "incident_score", "member_count"], ascending=[True, False, False]).reset_index(drop=True)


def build_explanation(row: pd.Series) -> str:
    labels = json.loads(row.get("label_distribution", "{}") or "{}")
    label_text = ", ".join(f"{k}={v}" for k, v in labels.items()) or "no label distribution"
    duration_min = float(row.get("incident_duration_sec", 0.0) or 0.0) / 60.0
    return (
        f"{row['family']} incident around prefix {row['dominant_prefix']} / origin {row['dominant_origin_as']} "
        f"groups {int(row['member_count'])} alert events across {int(row['affected_prefix_count'])} prefixes "
        f"and {int(row['collector_union_count'])} collectors over {duration_min:.1f} minutes. "
        f"Dominant reason signature: {row['dominant_reason_signature']}; top factor: {row['dominant_top_factor']}. "
        f"Labels: {label_text}. Suggested next check: inspect path/triplet context and family-specific external evidence."
    )


def build_membership(member_df: pd.DataFrame, tickets: pd.DataFrame) -> pd.DataFrame:
    ticket_small = tickets[["incident_id", "incident_priority", "incident_score", "incident_confidence"]]
    out = member_df.merge(ticket_small, on="incident_id", how="left", validate="many_to_one")
    cols = [
        "event_id",
        "incident_id",
        "micro_incident_id",
        "family",
        "final_alert_label",
        "alert_source_layer",
        "prefix",
        "origin_as_norm",
        "path_signature",
        "triplet_signature",
        "first_seen",
        "last_seen",
        "risk_score",
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
    return out[cols].sort_values(["incident_id", "first_seen", "event_id"]).reset_index(drop=True)


def write_report(output_path: Path, summary: dict, tickets: pd.DataFrame) -> None:
    lines = []
    lines.append("# S3-A Incident Aggregation Report")
    lines.append("")
    lines.append("## Scope")
    lines.append("")
    lines.append(f"- run_id: `{summary['run_id']}`")
    lines.append("- input: existing final/events outputs only; no upstream detection rerun")
    lines.append("- unit: high_priority_alert + needs_review event rows -> incident tickets")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    for key in [
        "raw_alert_count",
        "raw_high_count",
        "raw_needs_count",
        "incident_count",
        "compression_ratio",
        "analyst_workload_reduction",
        "micro_incident_count",
    ]:
        value = summary.get(key)
        if isinstance(value, float):
            lines.append(f"- {key}: `{value:.6f}`")
        else:
            lines.append(f"- {key}: `{value}`")
    lines.append("")
    lines.append("## Incidents By Priority")
    lines.append("")
    for key, value in summary["incident_count_by_priority"].items():
        lines.append(f"- {key}: `{value}`")
    lines.append("")
    lines.append("## Incidents By Family")
    lines.append("")
    for key, value in summary["incident_count_by_family"].items():
        lines.append(f"- {key}: `{value}`")
    lines.append("")
    lines.append("## Top Incidents")
    lines.append("")
    cols = [
        "incident_id",
        "incident_priority",
        "family",
        "member_count",
        "affected_prefix_count",
        "collector_union_count",
        "incident_score",
        "incident_confidence",
        "high_count",
        "needs_count",
        "dominant_prefix",
        "dominant_origin_as",
        "dominant_reason_signature",
    ]
    top = tickets[cols].head(20)
    lines.append("| " + " | ".join(cols) + " |")
    lines.append("| " + " | ".join("---" for _ in cols) + " |")
    for row in top.to_dict("records"):
        values = []
        for col in cols:
            value = row.get(col, "")
            if isinstance(value, float):
                values.append(f"{value:.4f}")
            else:
                values.append(str(value))
        lines.append("| " + " | ".join(values) + " |")
    lines.append("")
    lines.append("## Interpretation Checklist")
    lines.append("")
    lines.append("- Check whether compression_ratio is high enough to make review tractable.")
    lines.append("- Inspect top 100 incidents for dominant family/reason purity before trusting aggregate counts.")
    lines.append("- Confirm forged_origin_like and route_leak_like form distinct queues before using this layer for 24h evaluation.")
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_summary(run_id: str, member_df: pd.DataFrame, membership: pd.DataFrame, tickets: pd.DataFrame) -> dict:
    raw_alert_count = int(len(member_df))
    raw_high_count = int((member_df["final_alert_label"] == "high_priority_alert").sum())
    raw_needs_count = int((member_df["final_alert_label"] == "needs_review").sum())
    incident_count = int(len(tickets))
    compression_ratio = float(raw_alert_count / incident_count) if incident_count else 0.0
    workload_reduction = float(1.0 - incident_count / raw_alert_count) if raw_alert_count else 0.0
    return {
        "run_id": run_id,
        "raw_alert_count": raw_alert_count,
        "raw_high_count": raw_high_count,
        "raw_needs_count": raw_needs_count,
        "micro_incident_count": int(membership["micro_incident_id"].nunique()),
        "incident_count": incident_count,
        "compression_ratio": compression_ratio,
        "analyst_workload_reduction": workload_reduction,
        "incident_count_by_family": {str(k): int(v) for k, v in tickets["family"].value_counts().to_dict().items()},
        "incident_count_by_priority": {str(k): int(v) for k, v in tickets["incident_priority"].value_counts().to_dict().items()},
        "raw_alert_count_by_family": {str(k): int(v) for k, v in member_df["family"].value_counts().to_dict().items()},
        "top_incidents_sample": tickets.head(20)[
            [
                "incident_id",
                "family",
                "incident_priority",
                "member_count",
                "affected_prefix_count",
                "collector_union_count",
                "incident_score",
                "incident_confidence",
                "dominant_prefix",
                "dominant_origin_as",
            ]
        ].to_dict("records"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Build incident tickets from final alert events.")
    ap.add_argument("--run-id", default=RUN_ID_DEFAULT)
    ap.add_argument("--runs-root", default="data/runs")
    ap.add_argument("--final", default=None)
    ap.add_argument("--events", default=None)
    ap.add_argument("--output-dir", default="outputs/s3a_incident_aggregation_v01")
    ap.add_argument("--incidents-dir", default=None)
    ap.add_argument("--micro-window-sec", type=int, default=900)
    ap.add_argument("--macro-window-sec", type=int, default=7200)
    ap.add_argument("--overwrite", type=str2bool, default=False)
    ap.add_argument("--explanation-mode", default="template", choices=["template"])
    args = ap.parse_args()

    if args.micro_window_sec <= 0 or args.macro_window_sec <= 0:
        raise SystemExit("window sizes must be positive")

    run_dir = Path(args.runs_root) / args.run_id
    final_path = Path(args.final) if args.final else None
    events_path = Path(args.events) if args.events else None
    output_dir = Path(args.output_dir)
    incidents_dir = Path(args.incidents_dir) if args.incidents_dir else run_dir / "incidents"
    output_dir.mkdir(parents=True, exist_ok=True)
    incidents_dir.mkdir(parents=True, exist_ok=True)

    out_membership = incidents_dir / "incident_membership.parquet"
    out_tickets = incidents_dir / "incident_tickets.parquet"
    out_summary = incidents_dir / "incident_summary.json"
    report_path = output_dir / "s3a_report.md"
    summary_copy = output_dir / "s3a_incident_summary.json"
    for path in [out_membership, out_tickets, out_summary, report_path, summary_copy]:
        if path.exists() and not args.overwrite:
            raise SystemExit(f"output exists, pass --overwrite true to replace: {path}")

    base = load_base_alerts(run_dir, final_path, events_path)
    if base.empty:
        raise SystemExit("no high_priority_alert or needs_review rows found in final alerts")

    member_df = assign_micro_incidents(base, args.micro_window_sec)
    micro_df = build_micro_table(member_df)
    member_df, micro_df = assign_macro_incidents(member_df, micro_df, args.macro_window_sec)
    tickets = build_ticket_table(member_df, micro_df)
    membership = build_membership(member_df, tickets)
    summary = build_summary(args.run_id, member_df, membership, tickets)
    summary["micro_window_sec"] = int(args.micro_window_sec)
    summary["macro_window_sec"] = int(args.macro_window_sec)
    summary["output_membership_path"] = str(out_membership)
    summary["output_tickets_path"] = str(out_tickets)
    summary["output_summary_path"] = str(out_summary)
    summary["output_report_path"] = str(report_path)

    membership.to_parquet(out_membership, index=False)
    tickets.to_parquet(out_tickets, index=False)
    out_summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=json_default), encoding="utf-8")
    summary_copy.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=json_default), encoding="utf-8")
    tickets.head(200).to_csv(output_dir / "s3a_top_incidents.csv", index=False, encoding="utf-8-sig")
    tickets["family"].value_counts().rename_axis("family").reset_index(name="incident_count").to_csv(
        output_dir / "s3a_incidents_by_family.csv", index=False, encoding="utf-8-sig"
    )
    tickets["incident_priority"].value_counts().rename_axis("incident_priority").reset_index(name="incident_count").to_csv(
        output_dir / "s3a_incidents_by_priority.csv", index=False, encoding="utf-8-sig"
    )
    write_report(report_path, summary, tickets)

    print(json.dumps(summary, ensure_ascii=False, indent=2, default=json_default), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
