import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


RUN_ID_DEFAULT = "s2a_expanded_v01_pilot_6h_april16"
OUTPUT_DIR_DEFAULT = "outputs/s3c1_visibility_path_plausibility_v01"

PATTERN_A_TOKENS = {
    "single_collector_visibility",
    "unseen_path_for_prefix_origin",
    "unusually_short_duration_for_prefix",
}
PATTERN_B_TOKENS = {
    "abnormal_path_length_for_prefix_origin",
    "single_collector_visibility",
    "unseen_path_for_prefix_origin",
}

SCORE_COLS = [
    "event_id",
    "run_id",
    "prefix",
    "origin_as",
    "as_path_clean",
    "as_path_len",
    "duration_sec",
    "record_count",
    "collector_set",
    "collector_count",
    "visibility_count",
    "candidate_reasons",
    "matched_rule_count",
    "structural_novelty_score",
    "weak_signal_score",
    "history_rarity_score",
    "path_consistency_score",
    "risk_score",
    "risk_bucket",
    "top_contributing_factor",
    "missing_origin_or_path",
    "path_seen_before",
    "path_total_events",
    "po_total_events",
    "po_collector_support",
    "po_time_span_sec",
    "prefix_total_events",
]

CANDIDATE_COLS = [
    "event_id",
    "candidate_flag",
    "po_unique_paths",
    "po_total_events",
    "po_collector_support",
    "po_time_span_sec",
    "path_total_events",
    "path_seen_before",
    "prefix_total_events",
]

EVENT_COLS = [
    "event_id",
    "first_seen",
    "last_seen",
    "duration_sec",
    "collector_count",
    "visibility_count",
    "rel_seq",
    "rel_unknown_cnt",
    "rel_has_unknown",
]

GATING_COLS = [
    "event_id",
    "gating_label",
    "certainty_score",
    "conflict_score",
    "promoted_from_low",
    "demoted_from_high",
]

FINAL_COLS = [
    "event_id",
    "final_alert_label",
    "alert_source_layer",
    "evidence_support_score",
]

MEMBERSHIP_COLS = [
    "event_id",
    "incident_id",
    "final_alert_label",
    "alert_source_layer",
    "incident_priority",
    "risk_bucket",
    "reason_signature",
]

TICKET_COLS = [
    "incident_id",
    "calibrated_priority",
    "family",
    "member_count",
    "high_count",
    "needs_count",
    "high_share",
    "needs_share",
    "affected_prefix_count",
    "incident_score",
    "incident_confidence",
    "dominant_reason_signature",
]

BASELINE_PO_COLS = [
    "prefix",
    "origin_as",
    "total_events",
    "unique_paths",
    "avg_path_len",
    "median_path_len",
    "avg_duration_sec",
    "avg_visibility_count",
    "rel_unknown_rate",
    "rel_has_unknown_rate",
]

OUTPUT_SAMPLE_COLS = [
    "event_id",
    "run_id",
    "prefix",
    "origin_as",
    "as_path_clean",
    "candidate_reasons",
    "top_contributing_factor",
    "risk_score",
    "risk_bucket",
    "adjusted_risk_score_s3c1",
    "adjusted_risk_bucket_s3c1",
    "path_plausibility_score",
    "plausibility_bucket",
    "plausibility_penalty",
    "s3c1_adjustment_reason",
    "visibility_support_score",
    "temporal_support_score",
    "history_support_score",
    "path_length_plausibility_score",
    "relation_support_score",
    "pattern_A_flag",
    "pattern_B_flag",
    "single_collector_flag",
    "short_lived_flag",
    "temporal_confirmation_count",
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


def to_rel_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def available_columns(path: Path, requested: list[str]) -> list[str]:
    if not path.exists():
        return []
    schema_cols = set(pq.ParquetFile(path).schema_arrow.names)
    return [col for col in requested if col in schema_cols]


def parquet_row_count(path: Path) -> int:
    return int(pq.ParquetFile(path).metadata.num_rows)


def read_parquet_limited(path: Path, columns: list[str], sample_rows: int | None, warnings: list[str]) -> pd.DataFrame:
    existing = available_columns(path, columns)
    missing = sorted(set(columns) - set(existing))
    if missing:
        warnings.append(f"{to_rel_path(path)} missing columns: {missing}")
    if not existing:
        return pd.DataFrame()
    if sample_rows is None:
        return pd.read_parquet(path, columns=existing)

    frames = []
    remaining = int(sample_rows)
    parquet_file = pq.ParquetFile(path)
    for batch in parquet_file.iter_batches(batch_size=min(max(remaining, 1), 200_000), columns=existing):
        part = batch.to_pandas()
        if len(part) > remaining:
            part = part.head(remaining)
        frames.append(part)
        remaining -= len(part)
        if remaining <= 0:
            break
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=existing)


def read_optional_by_event_ids(
    path: Path,
    columns: list[str],
    event_ids: set[str] | None,
    warnings: list[str],
    label: str,
) -> tuple[pd.DataFrame | None, dict[str, Any]]:
    info = {"available": False, "path": to_rel_path(path), "label": label}
    if not path.exists():
        info["reason"] = "file_not_found"
        warnings.append(f"{label} input not found: {to_rel_path(path)}")
        return None, info
    cols = available_columns(path, columns)
    if "event_id" not in cols:
        info["reason"] = "event_id_missing"
        info["columns"] = cols
        warnings.append(f"{label} input lacks event_id: {to_rel_path(path)}")
        return None, info
    df = pd.read_parquet(path, columns=cols)
    df["event_id"] = text_col(df, "event_id")
    original_rows = int(len(df))
    if event_ids is not None:
        df = df[df["event_id"].isin(event_ids)].copy()
    info.update(
        {
            "available": True,
            "columns": cols,
            "source_rows": original_rows,
            "joined_candidate_rows": int(len(df)),
        }
    )
    return df, info


def read_optional_by_incident_ids(
    path: Path,
    columns: list[str],
    incident_ids: set[str] | None,
    warnings: list[str],
    label: str,
) -> tuple[pd.DataFrame | None, dict[str, Any]]:
    info = {"available": False, "path": to_rel_path(path), "label": label}
    if not path.exists():
        info["reason"] = "file_not_found"
        warnings.append(f"{label} input not found: {to_rel_path(path)}")
        return None, info
    cols = available_columns(path, columns)
    if "incident_id" not in cols:
        info["reason"] = "incident_id_missing"
        info["columns"] = cols
        warnings.append(f"{label} input lacks incident_id: {to_rel_path(path)}")
        return None, info
    df = pd.read_parquet(path, columns=cols)
    df["incident_id"] = text_col(df, "incident_id")
    original_rows = int(len(df))
    if incident_ids is not None:
        df = df[df["incident_id"].isin(incident_ids)].copy()
    info.update({"available": True, "columns": cols, "source_rows": original_rows, "joined_ticket_rows": int(len(df))})
    return df, info


def text_col(df: pd.DataFrame, col: str, default: str = "") -> pd.Series:
    if col not in df.columns:
        return pd.Series(default, index=df.index, dtype="object")
    return df[col].fillna(default).astype(str)


def num_col(df: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in df.columns:
        return pd.Series(default, index=df.index, dtype="float64")
    return pd.to_numeric(df[col], errors="coerce").fillna(default)


def bool_col(df: pd.DataFrame, col: str, default: bool = False) -> pd.Series:
    if col not in df.columns:
        return pd.Series(default, index=df.index, dtype="bool")
    series = df[col]
    if series.dtype == bool:
        return series.fillna(default)
    return series.fillna(default).astype(str).str.strip().str.lower().isin({"1", "true", "yes", "y", "on"})


def normalize_origin(value: Any) -> str:
    if value is None or pd.isna(value):
        return "NA"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        text = str(value).strip()
        return text if text else "NA"
    if math.isfinite(numeric) and numeric.is_integer():
        return str(int(numeric))
    return str(numeric)


def contains_token(series: pd.Series, token: str) -> pd.Series:
    return series.fillna("").astype(str).str.contains(token, regex=False, na=False)


def contains_all(reason_text: pd.Series, tokens: set[str]) -> pd.Series:
    mask = pd.Series(True, index=reason_text.index)
    for token in tokens:
        mask = mask & contains_token(reason_text, token)
    return mask


def clamp(series: pd.Series, low: float = 0.0, high: float = 100.0) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(0.0).clip(lower=low, upper=high)


def bucket_from_score(score: float, thresholds: dict[str, float]) -> str:
    if score >= float(thresholds["high"]):
        return "high"
    if score >= float(thresholds["medium"]):
        return "medium"
    return "low"


def load_score_thresholds(run_dir: Path, scores: pd.DataFrame, warnings: list[str]) -> dict[str, float]:
    summary_path = run_dir / "scores" / "score_summary.json"
    if summary_path.exists():
        try:
            data = json.loads(summary_path.read_text(encoding="utf-8"))
            thresholds = data.get("risk_bucket_thresholds") or {}
            if "high" in thresholds and "medium" in thresholds:
                return {"high": float(thresholds["high"]), "medium": float(thresholds["medium"])}
        except Exception as exc:
            warnings.append(f"could not parse score thresholds from {to_rel_path(summary_path)}: {exc}")
    clean = num_col(scores, "risk_score").dropna()
    if clean.empty:
        warnings.append("risk thresholds unavailable; fallback to high=70 medium=45")
        return {"high": 70.0, "medium": 45.0}
    warnings.append("score_summary risk thresholds unavailable; derived thresholds from loaded rows")
    return {"high": float(clean.quantile(0.80)), "medium": float(clean.quantile(0.40))}


def coalesce_column(df: pd.DataFrame, col: str, fallback_col: str) -> None:
    if fallback_col not in df.columns:
        return
    if col not in df.columns:
        df[col] = df[fallback_col]
        return
    df[col] = df[col].where(df[col].notna(), df[fallback_col])


def add_candidate_join(base: pd.DataFrame, candidate_path: Path, warnings: list[str]) -> tuple[pd.DataFrame, dict[str, Any]]:
    event_ids = set(base["event_id"].astype(str))
    cand, info = read_optional_by_event_ids(candidate_path, CANDIDATE_COLS, event_ids, warnings, "candidate_events")
    if cand is None or cand.empty:
        return base, info
    for col in cand.columns:
        if col != "event_id":
            cand = cand.rename(columns={col: f"{col}_candidate"})
    out = base.merge(cand, on="event_id", how="left", validate="one_to_one")
    for col in [
        "po_unique_paths",
        "po_total_events",
        "po_collector_support",
        "po_time_span_sec",
        "path_total_events",
        "path_seen_before",
        "prefix_total_events",
    ]:
        coalesce_column(out, col, f"{col}_candidate")
    return out, info


def add_event_join(base: pd.DataFrame, event_path: Path, warnings: list[str]) -> tuple[pd.DataFrame, dict[str, Any]]:
    event_ids = set(base["event_id"].astype(str))
    events, info = read_optional_by_event_ids(event_path, EVENT_COLS, event_ids, warnings, "event_units")
    if events is None or events.empty:
        return base, info
    for col in events.columns:
        if col != "event_id":
            events = events.rename(columns={col: f"{col}_event"})
    out = base.merge(events, on="event_id", how="left", validate="one_to_one")
    for col in ["first_seen", "last_seen", "duration_sec", "collector_count", "visibility_count", "rel_seq", "rel_unknown_cnt", "rel_has_unknown"]:
        coalesce_column(out, col, f"{col}_event")
    return out, info


def add_simple_optional_join(
    base: pd.DataFrame,
    path: Path,
    columns: list[str],
    label: str,
    warnings: list[str],
    suffix: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    event_ids = set(base["event_id"].astype(str))
    joined, info = read_optional_by_event_ids(path, columns, event_ids, warnings, label)
    if joined is None or joined.empty:
        return base, info
    for col in joined.columns:
        if col != "event_id" and col in base.columns:
            joined = joined.rename(columns={col: f"{col}_{suffix}"})
    out = base.merge(joined, on="event_id", how="left", validate="one_to_one")
    return out, info


def add_baseline_po(base: pd.DataFrame, baseline_path: Path, warnings: list[str]) -> tuple[pd.DataFrame, dict[str, Any]]:
    info = {"available": False, "path": to_rel_path(baseline_path), "label": "baseline_prefix_origin"}
    if not baseline_path.exists():
        warnings.append(f"baseline_prefix_origin input not found: {to_rel_path(baseline_path)}")
        return base, info
    cols = available_columns(baseline_path, BASELINE_PO_COLS)
    if not {"prefix", "origin_as"}.issubset(set(cols)):
        warnings.append(f"baseline_prefix_origin lacks prefix/origin_as keys: {to_rel_path(baseline_path)}")
        info["columns"] = cols
        info["reason"] = "key_columns_missing"
        return base, info
    baseline = pd.read_parquet(baseline_path, columns=cols)
    baseline["prefix"] = text_col(baseline, "prefix")
    baseline["origin_as_norm"] = baseline["origin_as"].map(normalize_origin)
    keep_cols = ["prefix", "origin_as_norm"] + [col for col in cols if col not in {"prefix", "origin_as"}]
    baseline = baseline[keep_cols].rename(columns={col: f"baseline_po_{col}" for col in keep_cols if col not in {"prefix", "origin_as_norm"}})
    out = base.merge(baseline, on=["prefix", "origin_as_norm"], how="left", validate="many_to_one")
    info.update({"available": True, "columns": cols, "source_rows": int(len(baseline)), "joined_rows": int(out["baseline_po_total_events"].notna().sum()) if "baseline_po_total_events" in out.columns else 0})
    return out, info


def add_incident_context(
    base: pd.DataFrame,
    membership_path: Path,
    tickets_path: Path,
    warnings: list[str],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    out, membership_info = add_simple_optional_join(base, membership_path, MEMBERSHIP_COLS, "incident_membership", warnings, "membership")
    ticket_info = {"available": False, "path": to_rel_path(tickets_path), "label": "calibrated_incident_tickets"}
    if "incident_id" not in out.columns:
        return out, {"membership": membership_info, "tickets": ticket_info}
    incident_ids = set(out["incident_id"].dropna().astype(str))
    tickets, ticket_info = read_optional_by_incident_ids(tickets_path, TICKET_COLS, incident_ids, warnings, "calibrated_incident_tickets")
    if tickets is None or tickets.empty:
        return out, {"membership": membership_info, "tickets": ticket_info}
    for col in tickets.columns:
        if col != "incident_id" and col in out.columns:
            tickets = tickets.rename(columns={col: f"{col}_ticket"})
    out = out.merge(tickets, on="incident_id", how="left", validate="many_to_one")
    return out, {"membership": membership_info, "tickets": ticket_info}


def normalize_base(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["event_id"] = text_col(out, "event_id")
    out["run_id"] = text_col(out, "run_id")
    out["prefix"] = text_col(out, "prefix")
    out["origin_as_norm"] = out.get("origin_as", pd.Series(index=out.index)).map(normalize_origin)
    out["origin_as"] = out["origin_as_norm"]
    out["as_path_clean"] = text_col(out, "as_path_clean")
    out["candidate_reasons"] = text_col(out, "candidate_reasons", "[]")
    out["top_contributing_factor"] = text_col(out, "top_contributing_factor", "none")
    out["risk_bucket"] = text_col(out, "risk_bucket", "low")
    for col in [
        "as_path_len",
        "duration_sec",
        "record_count",
        "collector_count",
        "visibility_count",
        "matched_rule_count",
        "structural_novelty_score",
        "weak_signal_score",
        "history_rarity_score",
        "path_consistency_score",
        "risk_score",
        "path_total_events",
        "po_total_events",
        "po_collector_support",
        "po_time_span_sec",
        "prefix_total_events",
        "po_unique_paths",
        "first_seen",
        "last_seen",
        "rel_unknown_cnt",
    ]:
        out[col] = num_col(out, col, np.nan if col in {"first_seen", "last_seen"} else 0.0)
    out["missing_origin_or_path"] = bool_col(out, "missing_origin_or_path")
    out["path_seen_before"] = bool_col(out, "path_seen_before")
    out["rel_has_unknown"] = bool_col(out, "rel_has_unknown")
    return out


def add_flags(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    reason = text_col(out, "candidate_reasons")
    top_factor = text_col(out, "top_contributing_factor")
    out["single_collector_flag"] = (num_col(out, "collector_count") <= 1.0) | contains_token(reason, "single_collector_visibility")
    out["low_visibility_flag"] = contains_token(reason, "unusually_low_visibility_for_prefix") | contains_token(
        reason, "unusually_low_visibility_for_prefix_origin"
    )
    out["short_lived_flag"] = contains_token(reason, "unusually_short_duration_for_prefix") | contains_token(
        reason, "sparse_short_lived_event"
    )
    out["abnormal_path_length_flag"] = contains_token(reason, "abnormal_path_length_for_prefix_origin")
    structural_top = top_factor.eq("structural_novelty_score") | contains_token(reason, "structural_novelty_score")
    out["pattern_A_flag"] = contains_all(reason, PATTERN_A_TOKENS) & structural_top
    out["pattern_B_flag"] = contains_all(reason, PATTERN_B_TOKENS) & structural_top
    collectors = num_col(out, "collector_count")
    out["collector_diversity_bucket"] = np.select(
        [collectors <= 1, collectors <= 2, collectors <= 4],
        ["single", "low", "medium"],
        default="broad",
    )
    duration = num_col(out, "duration_sec")
    out["duration_bucket"] = np.select(
        [duration <= 60, duration <= 300, duration <= 1800],
        ["very_short", "short", "medium"],
        default="long",
    )
    return out


def neighbor_bucket_count(df: pd.DataFrame, key_cols: list[str], bucket_col: str) -> pd.Series:
    needed = key_cols + [bucket_col]
    if df.empty or any(col not in df.columns for col in needed):
        return pd.Series(0, index=df.index, dtype="int64")
    tmp = df[needed].copy()
    tmp["_row_id"] = np.arange(len(tmp))
    counts = tmp.groupby(needed, dropna=False).size().reset_index(name="_bucket_count")
    total = pd.Series(0, index=tmp.index, dtype="int64")
    for shift in (-1, 0, 1):
        shifted = counts.copy()
        shifted[bucket_col] = shifted[bucket_col] - shift
        merged = tmp.merge(shifted, on=needed, how="left", sort=False)
        total = total.add(merged["_bucket_count"].fillna(0).astype("int64"), fill_value=0)
    return total.astype("int64")


def add_temporal_confirmation(df: pd.DataFrame, window_sec: int) -> pd.DataFrame:
    out = df.copy()
    first_seen = num_col(out, "first_seen", np.nan)
    if first_seen.isna().all():
        out["temporal_confirmation_count"] = 0
        return out
    bucket = np.floor(first_seen.fillna(0.0) / float(max(window_sec, 1))).astype("int64")
    out["_s3c1_time_bucket"] = bucket
    po_count = neighbor_bucket_count(out, ["prefix", "origin_as_norm"], "_s3c1_time_bucket")
    path_count = neighbor_bucket_count(out, ["prefix", "origin_as_norm", "as_path_clean"], "_s3c1_time_bucket")
    out["temporal_confirmation_count"] = np.maximum(po_count.to_numpy(), path_count.to_numpy()) - 1
    out["temporal_confirmation_count"] = out["temporal_confirmation_count"].clip(lower=0).astype("int64")
    out = out.drop(columns=["_s3c1_time_bucket"])
    return out


def score_visibility(df: pd.DataFrame) -> pd.Series:
    collector_count = num_col(df, "collector_count")
    po_support = num_col(df, "po_collector_support")
    visibility = num_col(df, "visibility_count")
    denom = po_support.where(po_support > 0, visibility.where(visibility > 0, 1.0)).clip(lower=1.0)
    ratio = (collector_count / denom).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    df["collector_visibility_ratio"] = ratio.clip(lower=0.0, upper=2.0)
    collector_component = np.minimum(collector_count / 4.0, 1.0) * 30.0
    ratio_component = np.minimum(ratio, 1.0) * 45.0
    score = 20.0 + collector_component + ratio_component
    score = score - df["single_collector_flag"].astype(float) * 20.0
    score = score - df["low_visibility_flag"].astype(float) * 10.0
    return clamp(score)


def score_temporal(df: pd.DataFrame) -> pd.Series:
    duration = num_col(df, "duration_sec")
    confirms = num_col(df, "temporal_confirmation_count")
    duration_component = pd.Series(0.0, index=df.index)
    duration_component.loc[duration > 60] = 20.0
    duration_component.loc[duration > 300] = 35.0
    duration_component.loc[duration > 1800] = 45.0
    confirmation_component = np.minimum(np.log1p(confirms) / math.log1p(5), 1.0) * 35.0
    collector_component = np.minimum(num_col(df, "collector_count") / 3.0, 1.0) * 10.0
    score = 15.0 + duration_component + confirmation_component + collector_component
    no_confirm_short = df["short_lived_flag"] & (confirms <= 0)
    score = score - no_confirm_short.astype(float) * 20.0
    return clamp(score)


def score_history(df: pd.DataFrame) -> pd.Series:
    path_seen = bool_col(df, "path_seen_before")
    po_unique = num_col(df, "po_unique_paths")
    po_total = num_col(df, "po_total_events")
    path_total = num_col(df, "path_total_events")
    path_reuse = df.groupby("as_path_clean", dropna=False)["prefix"].transform("nunique") if "as_path_clean" in df.columns else 0
    origin_paths = df.groupby("origin_as_norm", dropna=False)["as_path_clean"].transform("nunique") if "origin_as_norm" in df.columns else 0
    df["prefix_origin_path_support"] = np.minimum(np.log1p(po_total) / math.log1p(50), 1.0) * 100.0
    df["path_reuse_score"] = np.minimum(np.log1p(path_reuse) / math.log1p(20), 1.0) * 100.0
    df["path_neighborhood_support"] = (
        np.minimum(np.log1p(po_unique) / math.log1p(10), 1.0) * 60.0
        + np.minimum(np.log1p(origin_paths) / math.log1p(50), 1.0) * 40.0
    )
    exact_component = path_seen.astype(float) * 100.0
    path_total_component = np.minimum(np.log1p(path_total) / math.log1p(20), 1.0) * 100.0
    score = (
        exact_component * 0.35
        + df["prefix_origin_path_support"] * 0.20
        + df["path_reuse_score"] * 0.25
        + df["path_neighborhood_support"] * 0.15
        + path_total_component * 0.05
    )
    return clamp(score)


def score_path_length(df: pd.DataFrame) -> pd.Series:
    path_len = num_col(df, "as_path_len")
    median = num_col(df, "baseline_po_median_path_len", np.nan)
    avg = num_col(df, "baseline_po_avg_path_len", np.nan)
    baseline_len = median.where(median > 0, avg)
    if baseline_len.isna().all():
        group_median = df.groupby(["prefix", "origin_as_norm"], dropna=False)["as_path_len"].transform("median")
        baseline_len = group_median.where(group_median > 0, path_len)
    diff = (path_len - baseline_len).abs()
    denom = np.maximum(baseline_len.fillna(path_len).abs() * 0.35, 1.0)
    zscore = (diff / denom).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    df["path_length_zscore"] = zscore
    score = 100.0 - np.minimum(zscore, 3.0) * 25.0
    score = score - df["abnormal_path_length_flag"].astype(float) * 10.0
    return clamp(score)


def score_relation(df: pd.DataFrame, relation_source_available: bool) -> tuple[pd.Series, bool]:
    if not relation_source_available:
        return pd.Series(70.0, index=df.index), False
    unknown_cnt = num_col(df, "rel_unknown_cnt")
    path_len = num_col(df, "as_path_len").clip(lower=1.0)
    ratio = (unknown_cnt / path_len).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    df["rel_unknown_ratio"] = ratio.clip(lower=0.0, upper=1.0)
    df["rel_has_unknown_flag"] = bool_col(df, "rel_has_unknown")
    score = 90.0 - np.minimum(ratio, 1.0) * 60.0 - df["rel_has_unknown_flag"].astype(float) * 10.0
    df["relation_conflict_flag"] = False
    return clamp(score), True


def add_plausibility_scores(df: pd.DataFrame, relation_available: bool) -> pd.DataFrame:
    out = df.copy()
    weights = {
        "visibility_support_score": 0.25,
        "temporal_support_score": 0.25,
        "history_support_score": 0.30,
        "path_length_plausibility_score": 0.15,
        "relation_support_score": 0.05,
    }
    if not relation_available:
        removed = weights.pop("relation_support_score")
        scale = 1.0 / (1.0 - removed)
        weights = {key: value * scale for key, value in weights.items()}
        out["relation_support_score"] = np.nan
    composite = pd.Series(0.0, index=out.index)
    for col, weight in weights.items():
        composite = composite + num_col(out, col) * weight
    out["path_plausibility_score"] = clamp(composite)
    score = num_col(out, "path_plausibility_score")
    out["plausibility_bucket"] = np.select(
        [score >= 70.0, score >= 40.0],
        ["high_plausibility", "medium_plausibility"],
        default="low_plausibility",
    )
    return out


def add_adjusted_risk(df: pd.DataFrame, thresholds: dict[str, float]) -> pd.DataFrame:
    out = df.copy()
    penalty = pd.Series(0.0, index=out.index)
    reason = pd.Series("no_adjustment", index=out.index, dtype="object")
    pattern_a_penalty_target = out["pattern_A_flag"] & ~out["pattern_B_flag"]
    out["pattern_A_penalty_target_flag"] = pattern_a_penalty_target
    low_a = pattern_a_penalty_target & out["plausibility_bucket"].eq("low_plausibility")
    med_a = pattern_a_penalty_target & out["plausibility_bucket"].eq("medium_plausibility")
    penalty.loc[low_a] = 15.0
    reason.loc[low_a] = "pattern_A_low_plausibility_minus15"
    penalty.loc[med_a] = 5.0
    reason.loc[med_a] = "pattern_A_medium_plausibility_minus5"
    low_b = out["pattern_B_flag"] & out["plausibility_bucket"].eq("low_plausibility")
    any_b = out["pattern_B_flag"]
    reason.loc[any_b & reason.eq("no_adjustment")] = "pattern_B_review_only_no_score_change"
    reason.loc[low_b & reason.eq("pattern_B_review_only_no_score_change")] = "pattern_B_low_plausibility_review_only_no_score_change"
    out["plausibility_penalty"] = penalty
    out["adjusted_risk_score_s3c1"] = (num_col(out, "risk_score") - penalty).clip(lower=0.0, upper=100.0).round(4)
    out["adjusted_risk_bucket_s3c1"] = out["adjusted_risk_score_s3c1"].map(lambda value: bucket_from_score(float(value), thresholds))
    out["s3c1_adjustment_reason"] = reason
    out["risk_bucket_changed_s3c1"] = text_col(out, "risk_bucket").ne(out["adjusted_risk_bucket_s3c1"])
    out["adjusted_down_s3c1"] = out["plausibility_penalty"] > 0
    return out


def build_score_before_after(df: pd.DataFrame) -> pd.DataFrame:
    grouped = (
        df.groupby(["risk_bucket", "adjusted_risk_bucket_s3c1"], dropna=False)
        .agg(
            rows=("event_id", "size"),
            adjusted_down_rows=("adjusted_down_s3c1", "sum"),
            mean_risk_before=("risk_score", "mean"),
            mean_adjusted_risk=("adjusted_risk_score_s3c1", "mean"),
            mean_plausibility_score=("path_plausibility_score", "mean"),
        )
        .reset_index()
        .sort_values(["risk_bucket", "adjusted_risk_bucket_s3c1"])
    )
    return grouped


def label_col(df: pd.DataFrame) -> pd.Series:
    if "final_alert_label" in df.columns:
        return text_col(df, "final_alert_label")
    if "final_alert_label_membership" in df.columns:
        return text_col(df, "final_alert_label_membership")
    return pd.Series("", index=df.index, dtype="object")


def build_pattern_delta(df: pd.DataFrame) -> pd.DataFrame:
    labels = label_col(df)
    rows = []
    patterns = {
        "pattern_A_single_collector_short_unseen_path": df["pattern_A_flag"],
        "pattern_B_abnormal_length_single_collector_unseen_path": df["pattern_B_flag"],
        "all_rows": pd.Series(True, index=df.index),
    }
    for name, mask in patterns.items():
        sub = df[mask].copy()
        if sub.empty:
            rows.append(
                {
                    "pattern_name": name,
                    "rows_before": 0,
                    "rows_after_adjusted_down": 0,
                    "mean_risk_before": 0.0,
                    "mean_adjusted_risk": 0.0,
                    "mean_plausibility_score": 0.0,
                    "low_plausibility_rate": 0.0,
                    "risk_bucket_changed_rate": 0.0,
                    "high_share_before": np.nan,
                    "needs_share_before": np.nan,
                    "incident_ticket_count_before": np.nan,
                    "estimated_ticket_delta": np.nan,
                }
            )
            continue
        sub_labels = labels.loc[sub.index]
        incident_count = sub["incident_id"].nunique() if "incident_id" in sub.columns else np.nan
        touched_tickets = (
            sub.loc[sub["adjusted_down_s3c1"], "incident_id"].nunique()
            if "incident_id" in sub.columns
            else np.nan
        )
        rows.append(
            {
                "pattern_name": name,
                "rows_before": int(len(sub)),
                "rows_after_adjusted_down": int(sub["adjusted_down_s3c1"].sum()),
                "mean_risk_before": float(num_col(sub, "risk_score").mean()) if len(sub) else 0.0,
                "mean_adjusted_risk": float(num_col(sub, "adjusted_risk_score_s3c1").mean()) if len(sub) else 0.0,
                "mean_plausibility_score": float(num_col(sub, "path_plausibility_score").mean()) if len(sub) else 0.0,
                "low_plausibility_rate": float(sub["plausibility_bucket"].eq("low_plausibility").mean()),
                "risk_bucket_changed_rate": float(sub["risk_bucket_changed_s3c1"].mean()),
                "high_share_before": float(sub_labels.eq("high_priority_alert").mean()) if sub_labels.ne("").any() else np.nan,
                "needs_share_before": float(sub_labels.eq("needs_review").mean()) if sub_labels.ne("").any() else np.nan,
                "incident_ticket_count_before": incident_count,
                "estimated_ticket_delta": touched_tickets,
            }
        )
    return pd.DataFrame(rows)


def build_bucket_distribution(df: pd.DataFrame) -> pd.DataFrame:
    before = text_col(df, "risk_bucket").value_counts(dropna=False).rename_axis("bucket").reset_index(name="before_rows")
    after = df["adjusted_risk_bucket_s3c1"].value_counts(dropna=False).rename_axis("bucket").reset_index(name="after_rows")
    out = before.merge(after, on="bucket", how="outer").fillna(0)
    out["before_rows"] = out["before_rows"].astype("int64")
    out["after_rows"] = out["after_rows"].astype("int64")
    out["delta_rows"] = out["after_rows"] - out["before_rows"]
    return out.sort_values("bucket")


def build_top_demoted(df: pd.DataFrame, limit: int = 200) -> pd.DataFrame:
    cols = [col for col in OUTPUT_SAMPLE_COLS if col in df.columns]
    out = df[df["adjusted_down_s3c1"]].copy()
    if out.empty:
        return pd.DataFrame(columns=cols)
    out = out.sort_values(["plausibility_penalty", "risk_score", "path_plausibility_score"], ascending=[False, False, True])
    return out.head(limit)[cols]


def build_known_event_check(df: pd.DataFrame, inventory_path: Path, warnings: list[str]) -> tuple[pd.DataFrame, dict[str, Any]]:
    info = {"available": False, "path": to_rel_path(inventory_path)}
    columns = [
        "event_name",
        "slug",
        "event_type",
        "anchor_type",
        "matched_rows",
        "adjusted_down_rows",
        "risk_bucket_changed_rows",
        "retained_rows",
        "status",
    ]
    if not inventory_path.exists():
        warnings.append(f"known-event inventory not found: {to_rel_path(inventory_path)}")
        return pd.DataFrame(columns=columns), info | {"reason": "file_not_found"}
    try:
        data = json.loads(inventory_path.read_text(encoding="utf-8"))
    except Exception as exc:
        warnings.append(f"could not parse known-event inventory: {exc}")
        return pd.DataFrame(columns=columns), info | {"reason": "parse_failed"}
    rows = []
    for item in data.get("events", []):
        prefixes = {str(p) for p in item.get("target_prefixes", [])}
        attackers = {str(v) for v in item.get("known_attacker_asns", []) if v is not None}
        malicious = item.get("known_malicious_origin_asn")
        if malicious is not None:
            attackers.add(str(malicious))
        anchor_origin = item.get("anchor_origin_as")
        if anchor_origin is not None:
            attackers.add(str(anchor_origin))
        mask = df["prefix"].isin(prefixes)
        if attackers:
            mask = mask & df["origin_as_norm"].isin(attackers)
        matched = df[mask]
        adjusted = int(matched["adjusted_down_s3c1"].sum()) if not matched.empty else 0
        changed = int(matched["risk_bucket_changed_s3c1"].sum()) if not matched.empty else 0
        rows.append(
            {
                "event_name": str(item.get("event_name", "")),
                "slug": str(item.get("slug", "")),
                "event_type": str(item.get("event_type", "")),
                "anchor_type": str(item.get("anchor_type", "")),
                "matched_rows": int(len(matched)),
                "adjusted_down_rows": adjusted,
                "risk_bucket_changed_rows": changed,
                "retained_rows": int(len(matched) - adjusted),
                "status": "matched" if len(matched) else "not_visible_in_loaded_run",
            }
        )
    info.update({"available": True, "event_count": len(rows), "matched_event_count": int(sum(1 for row in rows if row["matched_rows"] > 0))})
    return pd.DataFrame(rows, columns=columns), info


def build_estimated_ticket_delta(df: pd.DataFrame) -> dict[str, Any]:
    if "incident_id" not in df.columns or "calibrated_priority" not in df.columns:
        return {"available": False, "reason": "incident_context_missing"}
    focus = df[text_col(df, "calibrated_priority").isin(["P1_high", "P2_review"])].copy()
    changed = focus[focus["adjusted_down_s3c1"]]
    out = {
        "available": True,
        "p1_p2_rows_joined": int(len(focus)),
        "adjusted_down_rows_in_p1_p2": int(len(changed)),
        "touched_p1_p2_incidents": int(changed["incident_id"].nunique()),
        "touched_p1_incidents": int(changed.loc[text_col(changed, "calibrated_priority").eq("P1_high"), "incident_id"].nunique()),
        "touched_p2_incidents": int(changed.loc[text_col(changed, "calibrated_priority").eq("P2_review"), "incident_id"].nunique()),
    }
    return out


def build_summary(
    df: pd.DataFrame,
    run_id: str,
    source_rows: int,
    join_info: dict[str, Any],
    thresholds: dict[str, float],
    warnings: list[str],
    known_event_info: dict[str, Any],
) -> dict[str, Any]:
    labels = label_col(df)
    estimated_high_to_review = None
    if labels.ne("").any():
        estimated_high_to_review = int((labels.eq("high_priority_alert") & df["risk_bucket_changed_s3c1"]).sum())
    changed_rows = int(df["adjusted_down_s3c1"].sum())
    summary = {
        "run_id": run_id,
        "input_rows": int(source_rows),
        "loaded_rows": int(len(df)),
        "joined_rows": int(len(df)),
        "missing_join_rows": int(sum(max(0, len(df) - int(info.get("joined_candidate_rows", info.get("joined_rows", len(df)) or 0))) for info in join_info.values() if isinstance(info, dict) and info.get("available") and info.get("label") in {"candidate_events", "event_units"})),
        "pattern_A_rows": int(df["pattern_A_flag"].sum()),
        "pattern_B_rows": int(df["pattern_B_flag"].sum()),
        "low_plausibility_rows": int(df["plausibility_bucket"].eq("low_plausibility").sum()),
        "medium_plausibility_rows": int(df["plausibility_bucket"].eq("medium_plausibility").sum()),
        "high_plausibility_rows": int(df["plausibility_bucket"].eq("high_plausibility").sum()),
        "adjusted_risk_changed_rows": changed_rows,
        "risk_bucket_changed_rows": int(df["risk_bucket_changed_s3c1"].sum()),
        "pattern_A_adjusted_down_rows": int((df["pattern_A_flag"] & df["adjusted_down_s3c1"]).sum()),
        "pattern_B_adjusted_down_rows": int((df["pattern_B_flag"] & df["adjusted_down_s3c1"]).sum()),
        "estimated_high_to_review_rows": estimated_high_to_review,
        "estimated_p1_p2_ticket_delta": build_estimated_ticket_delta(df),
        "known_event_retained_count": int(known_event_info.get("matched_event_count", 0)) if known_event_info.get("available") else None,
        "risk_bucket_thresholds": thresholds,
        "join_info": join_info,
        "warnings": warnings,
        "status": "completed_with_warnings" if warnings else "completed",
    }
    return summary


def write_report(path: Path, summary: dict[str, Any], pattern_delta: pd.DataFrame, bucket_distribution: pd.DataFrame) -> None:
    pattern_a = pattern_delta[pattern_delta["pattern_name"].eq("pattern_A_single_collector_short_unseen_path")]
    pattern_b = pattern_delta[pattern_delta["pattern_name"].eq("pattern_B_abnormal_length_single_collector_unseen_path")]
    a = pattern_a.iloc[0].to_dict() if not pattern_a.empty else {}
    b = pattern_b.iloc[0].to_dict() if not pattern_b.empty else {}
    bucket_table = ["| bucket | before_rows | after_rows | delta_rows |", "| --- | ---: | ---: | ---: |"]
    for row in bucket_distribution.to_dict("records"):
        bucket_table.append(
            f"| {row.get('bucket', '')} | {int(row.get('before_rows', 0))} | {int(row.get('after_rows', 0))} | {int(row.get('delta_rows', 0))} |"
        )
    lines = [
        "# S3-C1 Visibility-Aware Path Plausibility Pilot",
        "",
        f"run_id: `{summary['run_id']}`",
        f"status: `{summary['status']}`",
        "",
        "## Scope",
        "",
        "S3-C1 is an offline scoring pilot. It does not overwrite `risk_score`, `risk_bucket`, `gating_label`, `final_alert_label`, incident tickets, or any upstream output.",
        "",
        "## Summary",
        "",
        f"- loaded_rows: `{summary['loaded_rows']}`",
        f"- pattern_A_rows: `{summary['pattern_A_rows']}`",
        f"- pattern_B_rows: `{summary['pattern_B_rows']}`",
        f"- low_plausibility_rows: `{summary['low_plausibility_rows']}`",
        f"- medium_plausibility_rows: `{summary['medium_plausibility_rows']}`",
        f"- high_plausibility_rows: `{summary['high_plausibility_rows']}`",
        f"- adjusted_risk_changed_rows: `{summary['adjusted_risk_changed_rows']}`",
        f"- risk_bucket_changed_rows: `{summary['risk_bucket_changed_rows']}`",
        "",
        "## Required Answers",
        "",
        "### 1. Did S3-C1 identify low-plausibility dominant patterns?",
        "",
        f"Pattern A low-plausibility rate is `{a.get('low_plausibility_rate', 0.0)}` and adjusted-down rows are `{summary['pattern_A_adjusted_down_rows']}`. This is the primary target because S3-B showed it dominates calibrated P1/P2 while carrying a low weighted high share.",
        "",
        "### 2. Why is pattern_A the priority downgrade target?",
        "",
        "Pattern A combines single collector visibility, unseen prefix-origin path novelty, short duration, and structural novelty. In the clean stable 6h window, S3-B showed this structure contributes most P1/P2 members but is mostly needs_review, so it is the safest first offline penalty target.",
        "",
        "### 3. Why not downgrade pattern_B the same way?",
        "",
        f"Pattern B is reported separately. Its adjusted-down rows are `{summary['pattern_B_adjusted_down_rows']}` by default because abnormal path length had a much higher weighted high share in S3-B. It should go to S3-C2/S3-C3-style evidence checks instead of a coarse S3-C1 penalty.",
        "",
        "### 4. Which components drive the downgrade?",
        "",
        "The pilot keeps separate `visibility_support_score`, `temporal_support_score`, `history_support_score`, `path_length_plausibility_score`, and `relation_support_score`. Downgrade only happens when the combined `path_plausibility_score` is medium/low and the row matches pattern_A.",
        "",
        "### 5. What is the theoretical high/P1/P2 impact?",
        "",
        f"`estimated_high_to_review_rows` is `{summary.get('estimated_high_to_review_rows')}` and `estimated_p1_p2_ticket_delta` is `{json.dumps(summary.get('estimated_p1_p2_ticket_delta'), ensure_ascii=False)}`. These are estimates only; S3-C1 does not rebuild gate/final/incidents.",
        "",
        "### 6. Which samples should not be downgraded?",
        "",
        "High-plausibility low-visibility rows, pattern_B rows, route-leak-like burst/triplet rows, and any row with temporal/history corroboration should move to verification instead of direct penalty.",
        "",
        "### 7. Known-event regression risk",
        "",
        f"`known_event_retained_count` is `{summary.get('known_event_retained_count')}`. If the fixed modern run has no known-event inventory overlap or final inventory inputs are unavailable, this check is marked as unavailable/skipped in `s3c1_known_event_regression_check.csv`.",
        "",
        "### 8. Next step",
        "",
        "If full S2 data are present, run S3-C1 full and then enter S3-C2 gate evidence support ablation. If S2 score/event inputs are missing locally, pull them first; if pattern_A bucket changes are too aggressive, tune S3-C1 weights before S3-C2.",
        "",
        "## Bucket Distribution",
        "",
        "\n".join(bucket_table),
    ]
    if summary.get("warnings"):
        lines.extend(["", "## Warnings", ""])
        lines.extend([f"- {item}" for item in summary["warnings"]])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_outputs(
    df: pd.DataFrame,
    output_dir: Path,
    summary: dict[str, Any],
    known_event_check: pd.DataFrame,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    sample_cols = [col for col in OUTPUT_SAMPLE_COLS if col in df.columns]
    sample = df.sort_values(["adjusted_down_s3c1", "path_plausibility_score"], ascending=[False, True]).head(200_000)
    sample[sample_cols].to_parquet(output_dir / "s3c1_candidate_plausibility_sample.parquet", index=False)

    score_before_after = build_score_before_after(df)
    pattern_delta = build_pattern_delta(df)
    bucket_distribution = build_bucket_distribution(df)
    top_demoted = build_top_demoted(df)

    score_before_after.to_csv(output_dir / "s3c1_score_before_after.csv", index=False)
    pattern_delta.to_csv(output_dir / "s3c1_pattern_delta.csv", index=False)
    bucket_distribution.to_csv(output_dir / "s3c1_bucket_distribution.csv", index=False)
    top_demoted.to_csv(output_dir / "s3c1_top_demoted_candidates.csv", index=False)
    known_event_check.to_csv(output_dir / "s3c1_known_event_regression_check.csv", index=False)
    (output_dir / "s3c1_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=json_default), encoding="utf-8")
    write_report(output_dir / "s3c1_report.md", summary, pattern_delta, bucket_distribution)


def run(args: argparse.Namespace) -> dict[str, Any]:
    run_id = args.run_id
    run_dir = Path("data") / "runs" / run_id
    output_dir = Path(args.output_dir)
    warnings: list[str] = []

    scores_path = Path(args.scores) if args.scores else run_dir / "scores" / "scored_candidates.parquet"
    candidate_path = Path(args.candidates) if args.candidates else run_dir / "candidates" / "candidate_events.parquet"
    event_path = Path(args.events) if args.events else run_dir / "events" / "event_units.parquet"
    gating_path = Path(args.gating) if args.gating else run_dir / "gating" / "gated_candidates.parquet"
    final_path = Path(args.final) if args.final else run_dir / "final" / "final_alerts.parquet"
    membership_path = Path(args.membership) if args.membership else run_dir / "incidents" / "incident_membership.parquet"
    tickets_path = Path(args.tickets) if args.tickets else Path("outputs") / "s3a2_incident_priority_calibration_v01" / "s3a2_calibrated_incident_tickets.parquet"
    baseline_po_path = Path(args.baseline_prefix_origin) if args.baseline_prefix_origin else run_dir / "baseline" / "baseline_prefix_origin.parquet"
    inventory_path = Path(args.known_event_inventory)

    if not scores_path.exists():
        raise SystemExit(
            "required S3-C1 input missing: "
            f"{to_rel_path(scores_path)}. Pull scored candidates for {run_id} before running the fixed-run pilot."
        )
    source_rows = parquet_row_count(scores_path)
    sample_rows = None if args.full_run else args.sample_rows
    if not args.full_run and not sample_rows:
        sample_rows = 200_000

    scores = read_parquet_limited(scores_path, SCORE_COLS, sample_rows, warnings)
    if scores.empty:
        raise SystemExit(f"no score rows loaded from {to_rel_path(scores_path)}")
    scores = normalize_base(scores)

    join_info: dict[str, Any] = {}
    base, join_info["candidate_events"] = add_candidate_join(scores, candidate_path, warnings)
    base, join_info["event_units"] = add_event_join(base, event_path, warnings)
    base, join_info["gating"] = add_simple_optional_join(base, gating_path, GATING_COLS, "gated_candidates", warnings, "gating")
    base, join_info["final"] = add_simple_optional_join(base, final_path, FINAL_COLS, "final_alerts", warnings, "final")
    base, join_info["baseline_prefix_origin"] = add_baseline_po(base, baseline_po_path, warnings)
    base, incident_info = add_incident_context(base, membership_path, tickets_path, warnings)
    join_info.update(incident_info)

    base = normalize_base(base)
    base = add_flags(base)
    base = add_temporal_confirmation(base, int(args.temporal_window_sec))
    base["visibility_support_score"] = score_visibility(base)
    base["temporal_support_score"] = score_temporal(base)
    base["history_support_score"] = score_history(base)
    base["path_length_plausibility_score"] = score_path_length(base)
    relation_source_available = bool(
        join_info.get("event_units", {}).get("available")
        and set(join_info.get("event_units", {}).get("columns", [])) & {"rel_unknown_cnt", "rel_has_unknown", "rel_seq"}
    )
    base["relation_support_score"], relation_available = score_relation(base, relation_source_available)
    base = add_plausibility_scores(base, relation_available)

    thresholds = load_score_thresholds(run_dir, base, warnings)
    base = add_adjusted_risk(base, thresholds)
    known_event_check, known_event_info = build_known_event_check(base, inventory_path, warnings)
    summary = build_summary(base, run_id, source_rows, join_info, thresholds, warnings, known_event_info)
    write_outputs(base, output_dir, summary, known_event_check)
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="S3-C1 offline visibility-aware path plausibility scoring pilot.")
    ap.add_argument("--run-id", default=RUN_ID_DEFAULT, help="Run id under data/runs/<run_id>.")
    ap.add_argument("--output-dir", default=OUTPUT_DIR_DEFAULT, help="Output directory for S3-C1 artifacts.")
    ap.add_argument("--scores", default=None, help="Optional scored_candidates.parquet path.")
    ap.add_argument("--candidates", default=None, help="Optional candidate_events.parquet path.")
    ap.add_argument("--events", default=None, help="Optional event_units.parquet path.")
    ap.add_argument("--gating", default=None, help="Optional gated_candidates.parquet path.")
    ap.add_argument("--final", default=None, help="Optional final_alerts.parquet path.")
    ap.add_argument("--membership", default=None, help="Optional incident_membership.parquet path.")
    ap.add_argument("--tickets", default=None, help="Optional calibrated incident tickets parquet path.")
    ap.add_argument("--baseline-prefix-origin", default=None, help="Optional baseline_prefix_origin.parquet path.")
    ap.add_argument("--known-event-inventory", default="data/known_events/known_event_candidates_v05.json")
    ap.add_argument("--sample-rows", type=int, default=200_000, help="Load first N scored rows for smoke mode.")
    ap.add_argument("--full-run", action="store_true", help="Process all scored rows.")
    ap.add_argument("--temporal-window-sec", type=int, default=600, help="Bucketed near-time support window.")
    args = ap.parse_args()

    if args.sample_rows is not None and args.sample_rows <= 0:
        raise SystemExit("--sample-rows must be > 0")
    if args.temporal_window_sec <= 0:
        raise SystemExit("--temporal-window-sec must be > 0")

    summary = run(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=json_default))


if __name__ == "__main__":
    main()
