"""Build prototype Raw Incident Dossiers from candidate-entry plus event time repair.

R-AGG-2 creates an auditable prototype aggregation table. It uses
candidate-entry as the primary source and event-entry only to repair time and
observation fields. It does not modify the legacy seven-layer pipeline, attach
external evidence, train learning, or produce attack/benign truth labels.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import pyarrow.parquet as pq


MISSING = "missing"
SOURCE_ENTRY = "candidate-entry"

FAMILY_HINT_VALUES = {
    "forged_origin_like",
    "route_leak_like",
    "path_manipulation_like",
    "stealth_visibility_like",
    "background_like_pattern",
    "mixed_unknown",
}

OUTPUT_COLUMNS = [
    "raw_incident_id",
    "run_id",
    "source_entry",
    "source_row_count",
    "source_candidate_row_ids",
    "source_event_ids",
    "start_time",
    "end_time",
    "duration_sec",
    "time_bucket_key",
    "time_repair_status",
    "prefix_set",
    "dominant_prefix",
    "origin_as_set",
    "dominant_origin_as",
    "prefix_origin_key",
    "as_path_signature_set",
    "dominant_as_path_signature",
    "collector_set",
    "collector_count",
    "visibility_mode",
    "aggregation_key",
    "aggregation_reason",
    "member_event_count",
    "member_candidate_count",
    "candidate_reason_set",
    "trigger_reason_set",
    "family_hint",
    "family_hint_source",
    "weak_signal_tags",
    "mixedness_hint",
    "aggregation_confidence",
    "component_count_estimate",
    "dominant_component_share",
    "split_needed_hint",
    "legacy_score_fields_present",
    "legacy_gate_fields_present",
    "legacy_final_fields_present",
    "legacy_reference_only_note",
    "evidence_grounding_ready",
    "required_lookup_keys",
    "learning_ready_features",
    "poisoning_benchmark_relevant_fields",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build prototype Raw Incident Dossiers from candidate-entry."
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--candidates", default=None)
    parser.add_argument("--events", default=None)
    parser.add_argument("--schema", default="configs/raw_incident_dossier_schema_v0.yaml")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--time-window-minutes", type=int, default=15)
    parser.add_argument("--max-rows", type=int, default=None)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def discover_path(run_id: str, explicit: str | None, layer: str, filename: str, required: bool) -> Path | None:
    path = Path(explicit) if explicit else Path("data") / "runs" / run_id / layer / filename
    if path.exists():
        return path
    if required:
        raise FileNotFoundError(f"{layer} file not found: {path}")
    return None


def prepare_output_dir(output_dir: Path, overwrite: bool) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_files = [
        output_dir / "raw_incidents_prototype.parquet",
        output_dir / "raw_incidents_prototype_preview.csv",
        output_dir / "raw_incident_prototype_summary.json",
        output_dir / "raw_incident_time_repair_audit.csv",
        output_dir / "raw_incident_grouping_stats.csv",
    ]
    existing = [path for path in output_files if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(
            "output files already exist; pass --overwrite to replace: "
            + ", ".join(str(path) for path in existing)
        )


def is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if isinstance(value, str) and value.strip() in {"", MISSING, "nan", "None", "NaT"}:
        return True
    if isinstance(value, (list, tuple, set, dict)) and len(value) == 0:
        return True
    return False


def normalize_scalar(value: Any) -> str:
    if is_missing(value):
        return MISSING
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, int):
        return str(value)
    return str(value)


def json_list(values: Iterable[Any], limit: int | None = None) -> str:
    cleaned = []
    seen = set()
    for value in values:
        text = normalize_scalar(value)
        if text == MISSING or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
        if limit is not None and len(cleaned) >= limit:
            break
    return json.dumps(cleaned, ensure_ascii=True)


def parse_list_like(value: Any) -> list[str]:
    if is_missing(value):
        return []
    if isinstance(value, list):
        return [normalize_scalar(item) for item in value if not is_missing(item)]
    if isinstance(value, tuple):
        return [normalize_scalar(item) for item in value if not is_missing(item)]
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [normalize_scalar(item) for item in parsed if not is_missing(item)]
        except json.JSONDecodeError:
            pass
    if "," in text:
        return [part.strip() for part in text.split(",") if part.strip()]
    return [text]


def stable_hash(text: str, length: int = 16) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:length]


def as_path_signature(value: Any) -> str:
    if is_missing(value):
        return MISSING
    normalized = " ".join(str(value).split())
    if not normalized:
        return MISSING
    return stable_hash(normalized, 12)


def normalize_reason_list(value: Any) -> list[str]:
    return sorted(set(parse_list_like(value)))


def reason_family(reasons: list[str]) -> tuple[str, str]:
    text = " ".join(reasons).lower()
    if any(token in text for token in ["new_origin", "origin_change", "origin", "rpki"]):
        return "forged_origin_like", "heuristic_from_candidate_reasons"
    if any(token in text for token in ["valley", "leak", "triplet", "asrel", "path_relation"]):
        return "route_leak_like", "heuristic_from_candidate_reasons"
    if any(token in text for token in ["unseen_path", "path_change", "path_len", "path_manipulation", "path"]):
        return "path_manipulation_like", "heuristic_from_candidate_reasons"
    if any(token in text for token in ["low_visibility", "single_collector", "stealth", "no_export", "community"]):
        return "stealth_visibility_like", "heuristic_from_candidate_reasons"
    if any(token in text for token in ["background", "stable", "known"]):
        return "background_like_pattern", "heuristic_from_candidate_reasons"
    return "mixed_unknown", "fallback_insufficient_reason"


def choose_family(reasons: list[str]) -> tuple[str, str]:
    families = []
    source = "heuristic_from_candidate_reasons"
    for reason in reasons:
        family, family_source = reason_family([reason])
        if family != "mixed_unknown":
            families.append(family)
            source = family_source
    unique = sorted(set(families))
    if len(unique) == 1:
        return unique[0], source
    if len(unique) > 1:
        return "mixed_unknown", "mixed_candidate_reason_families"
    return reason_family(reasons)


def visibility_mode_from_count(count: Any) -> str:
    try:
        value = float(count)
    except (TypeError, ValueError):
        return "unknown_visibility"
    if value <= 1:
        return "single_collector"
    if value <= 3:
        return "weak_visibility"
    return "multi_collector"


def read_parquet_limited(path: Path, columns: list[str] | None, max_rows: int | None) -> pd.DataFrame:
    df = pd.read_parquet(path, columns=columns, engine="pyarrow")
    if max_rows is not None:
        return df.head(max_rows).copy()
    return df


def maybe_epoch_to_datetime(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().any():
        return pd.to_datetime(numeric, unit="s", utc=True, errors="coerce")
    return pd.to_datetime(series, utc=True, errors="coerce")


def floor_time_bucket(series: pd.Series, minutes: int) -> pd.Series:
    return series.dt.floor(f"{minutes}min")


def load_candidates(path: Path, max_rows: int | None) -> tuple[pd.DataFrame, int]:
    row_count = pq.ParquetFile(path).metadata.num_rows
    df = read_parquet_limited(path, columns=None, max_rows=max_rows)
    return df, row_count if max_rows is None else len(df)


def load_events(path: Path | None, max_rows: int | None) -> tuple[pd.DataFrame | None, int | None]:
    if path is None:
        return None, None
    wanted = [
        "event_id",
        "first_seen",
        "last_seen",
        "duration_sec",
        "collector",
        "collector_set",
        "collector_count",
        "visibility_count",
    ]
    schema_names = set(pq.ParquetFile(path).schema.names)
    columns = [col for col in wanted if col in schema_names]
    df = read_parquet_limited(path, columns=columns, max_rows=None)
    if max_rows is not None:
        candidate_ids = None
        # The caller may pass a limited candidate table, but event lookup should
        # remain complete enough for exact join on those ids.
        _ = candidate_ids
    return df, len(df)


def repair_time(candidates: pd.DataFrame, events: pd.DataFrame | None) -> pd.DataFrame:
    df = candidates.copy()
    df["candidate_row_id"] = [f"cand_{idx:010d}" for idx in range(len(df))]
    if "event_id" not in df.columns:
        df["event_id"] = pd.NA

    if events is None:
        df["start_time_dt"] = pd.NaT
        df["end_time_dt"] = pd.NaT
        df["duration_sec_repaired"] = pd.to_numeric(df.get("duration_sec"), errors="coerce")
        df["time_repair_status"] = "missing"
        return df

    if "event_id" not in events.columns:
        df["start_time_dt"] = pd.NaT
        df["end_time_dt"] = pd.NaT
        df["duration_sec_repaired"] = pd.to_numeric(df.get("duration_sec"), errors="coerce")
        df["time_repair_status"] = "failed"
        return df

    event_cols = [col for col in [
        "event_id",
        "first_seen",
        "last_seen",
        "duration_sec",
        "collector",
        "collector_set",
        "collector_count",
        "visibility_count",
    ] if col in events.columns]
    events_small = events[event_cols].drop_duplicates("event_id")
    joined = df.merge(events_small, on="event_id", how="left", suffixes=("", "_event"))

    first_seen = joined["first_seen"] if "first_seen" in joined.columns else pd.Series(pd.NA, index=joined.index)
    last_seen = joined["last_seen"] if "last_seen" in joined.columns else pd.Series(pd.NA, index=joined.index)
    joined["start_time_dt"] = maybe_epoch_to_datetime(first_seen)
    joined["end_time_dt"] = maybe_epoch_to_datetime(last_seen)
    if "duration_sec_event" in joined.columns:
        duration = joined["duration_sec_event"]
    elif "duration_sec" in joined.columns:
        duration = joined["duration_sec"]
    else:
        duration = pd.Series(pd.NA, index=joined.index)
    joined["duration_sec_repaired"] = pd.to_numeric(duration, errors="coerce")
    exact = joined["start_time_dt"].notna() & joined["end_time_dt"].notna()
    joined["time_repair_status"] = exact.map({True: "exact_join", False: "failed"})
    return joined


def prepare_candidate_features(df: pd.DataFrame, time_window_minutes: int) -> pd.DataFrame:
    out = df.copy()
    for column in ["prefix", "origin_as", "as_path_clean", "collector_set", "candidate_reasons"]:
        if column not in out.columns:
            out[column] = pd.NA

    out["prefix_norm"] = out["prefix"].map(normalize_scalar)
    out["origin_as_norm"] = out["origin_as"].map(normalize_scalar)
    has_prefix_origin = out["prefix_norm"].ne(MISSING) & out["origin_as_norm"].ne(MISSING)
    out["prefix_origin_key"] = MISSING
    out.loc[has_prefix_origin, "prefix_origin_key"] = (
        out.loc[has_prefix_origin, "prefix_norm"] + "|" + out.loc[has_prefix_origin, "origin_as_norm"]
    )
    out["as_path_signature"] = out["as_path_clean"].map(as_path_signature)
    out["candidate_reason_list"] = out["candidate_reasons"].map(normalize_reason_list)
    out["candidate_reason_set_key"] = out["candidate_reason_list"].map(lambda values: "|".join(values) if values else MISSING)
    family_pairs = out["candidate_reason_list"].map(choose_family)
    out["family_hint"] = family_pairs.map(lambda pair: pair[0])
    out["family_hint_source"] = family_pairs.map(lambda pair: pair[1])
    out["collector_list"] = out["collector_set"].map(parse_list_like)
    out["collector_key"] = out["collector_list"].map(lambda values: "|".join(sorted(set(values))) if values else MISSING)
    out["time_bucket_dt"] = floor_time_bucket(out["start_time_dt"], time_window_minutes)
    out["time_bucket_key"] = out["time_bucket_dt"].map(lambda value: value.isoformat() if pd.notna(value) else MISSING)
    out["time_bucket_missing"] = out["time_bucket_key"].eq(MISSING)
    base_key = (
        out["prefix_origin_key"]
        + "|"
        + out["as_path_signature"]
        + "|"
        + out["family_hint"]
        + "|"
        + out["collector_key"]
    )
    out["aggregation_key"] = base_key.where(out["time_bucket_missing"], base_key + "|" + out["time_bucket_key"])
    partial_mask = out["aggregation_key"].str.contains(MISSING, regex=False, na=True)
    out.loc[partial_mask, "aggregation_key"] = [
        f"partial_key|{stable_hash(str(idx))}" for idx in out.index[partial_mask]
    ]
    return out


def make_aggregation_key(row: pd.Series) -> str:
    parts = [
        row.get("prefix_origin_key", MISSING),
        row.get("as_path_signature", MISSING),
        row.get("family_hint", "mixed_unknown"),
    ]
    time_bucket = row.get("time_bucket_key", MISSING)
    if not is_missing(time_bucket):
        parts.append(str(time_bucket))
    clean = [str(part) for part in parts if not is_missing(part)]
    return "|".join(clean) if clean else f"missing_key|{stable_hash(str(row.name))}"


def mode_value(series: pd.Series) -> str:
    cleaned = series.map(normalize_scalar)
    cleaned = cleaned[cleaned != MISSING]
    if cleaned.empty:
        return MISSING
    return str(cleaned.value_counts().idxmax())


def list_unique(series: pd.Series, limit: int | None = None) -> str:
    values = sorted(set(series.map(normalize_scalar)) - {MISSING})
    return json_list(values, limit=limit)


def list_union(series: pd.Series, limit: int | None = None) -> str:
    values = []
    for item in series:
        values.extend(parse_list_like(item) if not isinstance(item, list) else item)
    return json_list(sorted(set(values)), limit=limit)


def component_share(prefix: pd.Series, origin: pd.Series, path: pd.Series) -> float:
    combo = prefix.map(normalize_scalar) + "|" + origin.map(normalize_scalar) + "|" + path.map(normalize_scalar)
    combo = combo[~combo.str.contains(MISSING, regex=False)]
    if combo.empty:
        return 0.0
    return round(float(combo.value_counts().iloc[0] / len(prefix)), 6)


def mixedness_from_share(share: float, unique_prefix: int, unique_origin: int, unique_path: int) -> str:
    if share <= 0:
        return "unknown"
    if share >= 0.8 and unique_prefix <= 2 and unique_origin <= 2 and unique_path <= 2:
        return "low"
    if share >= 0.5:
        return "medium"
    return "high"


def time_status_for_group(statuses: pd.Series) -> str:
    counts = statuses.value_counts().to_dict()
    total = int(statuses.shape[0])
    if counts.get("exact_join", 0) == total:
        return "exact_join"
    if counts.get("weak_join", 0) == total:
        return "weak_join"
    if counts.get("missing", 0) == total:
        return "missing"
    if counts.get("failed", 0) == total:
        return "failed"
    if counts.get("exact_join", 0) or counts.get("weak_join", 0):
        return "inferred"
    return "failed"


def time_score(status: str) -> float:
    return {
        "exact_join": 1.0,
        "weak_join": 0.85,
        "inferred": 0.65,
        "missing": 0.0,
        "failed": 0.0,
    }.get(status, 0.0)


def derive_group_time_status(row: pd.Series) -> str:
    min_rank = int(row.get("time_repair_rank_min", 0))
    max_rank = int(row.get("time_repair_rank_max", 0))
    first_status = str(row.get("time_repair_status_first", "failed"))
    if min_rank == max_rank == 3:
        return "exact_join"
    if min_rank == max_rank == 2:
        return "weak_join"
    if max_rank > 0:
        return "inferred"
    if first_status == "missing":
        return "missing"
    return "failed"


def build_incidents(df: pd.DataFrame, source_row_count: int, run_id: str) -> pd.DataFrame:
    """Fast prototype aggregation.

    The aggregation key already includes prefix-origin, path signature, family,
    collector set, and time bucket when available. That lets this prototype use
    fast first/max/nunique reductions instead of expensive per-group list
    materialization. Member ids are representative samples; full membership
    cardinality is preserved in the member counts.
    """

    work = df.copy()
    work["component_key"] = (
        work["prefix_norm"].map(normalize_scalar)
        + "|"
        + work["origin_as_norm"].map(normalize_scalar)
        + "|"
        + work["as_path_signature"].map(normalize_scalar)
    )
    work["collector_count_numeric"] = pd.to_numeric(work.get("collector_count"), errors="coerce").fillna(0)
    work["candidate_reason_json"] = work["candidate_reason_list"].map(lambda values: json_list(values))
    work["collector_json"] = work["collector_list"].map(lambda values: json_list(values))
    work["source_candidate_row_id_json"] = work["candidate_row_id"].map(lambda value: json_list([value]))
    work["source_event_id_json"] = work["event_id"].map(lambda value: json_list([value]))
    work["time_repair_rank"] = work["time_repair_status"].map({
        "failed": 0,
        "missing": 0,
        "inferred": 1,
        "weak_join": 2,
        "exact_join": 3,
    }).fillna(0).astype(int)

    grouped = work.groupby("aggregation_key", dropna=False, sort=False)
    incidents = grouped.agg(
        run_id=("run_id", "first"),
        source_candidate_row_ids=("source_candidate_row_id_json", "first"),
        source_event_ids=("source_event_id_json", "first"),
        start_time_dt=("start_time_dt", "min"),
        end_time_dt=("end_time_dt", "max"),
        max_duration_sec=("duration_sec_repaired", "max"),
        time_bucket_key=("time_bucket_key", "first"),
        time_repair_rank_min=("time_repair_rank", "min"),
        time_repair_rank_max=("time_repair_rank", "max"),
        time_repair_status_first=("time_repair_status", "first"),
        prefix_set=("prefix_norm", "first"),
        dominant_prefix=("prefix_norm", "first"),
        prefix_unique_count=("prefix_norm", "nunique"),
        origin_as_set=("origin_as_norm", "first"),
        dominant_origin_as=("origin_as_norm", "first"),
        origin_unique_count=("origin_as_norm", "nunique"),
        prefix_origin_key=("prefix_origin_key", "first"),
        as_path_signature_set=("as_path_signature", "first"),
        dominant_as_path_signature=("as_path_signature", "first"),
        path_unique_count=("as_path_signature", "nunique"),
        collector_set=("collector_json", "first"),
        collector_count=("collector_count_numeric", "max"),
        member_event_count=("event_id", "nunique"),
        member_candidate_count=("candidate_row_id", "size"),
        candidate_reason_set=("candidate_reason_json", "first"),
        trigger_reason_set=("candidate_reason_json", "first"),
        family_hint=("family_hint", "first"),
        weak_signal_tags=("candidate_reason_json", "first"),
        component_count_estimate=("component_key", "nunique"),
    ).reset_index()

    incidents["raw_incident_id"] = incidents["aggregation_key"].map(lambda value: f"rawinc_{stable_hash(str(value), 16)}")
    incidents["source_entry"] = SOURCE_ENTRY
    incidents["source_row_count"] = source_row_count
    incidents["start_time"] = incidents["start_time_dt"].map(lambda value: value.isoformat() if pd.notna(value) else MISSING)
    incidents["end_time"] = incidents["end_time_dt"].map(lambda value: value.isoformat() if pd.notna(value) else MISSING)
    incident_duration = (incidents["end_time_dt"] - incidents["start_time_dt"]).dt.total_seconds()
    incidents["duration_sec"] = incident_duration.where(incident_duration.notna(), incidents["max_duration_sec"])
    incidents["duration_sec"] = incidents["duration_sec"].map(lambda value: MISSING if pd.isna(value) else round(float(value), 6))
    incidents["time_repair_status"] = incidents.apply(derive_group_time_status, axis=1)
    incidents["prefix_set"] = incidents["prefix_set"].map(lambda value: json_list([value]))
    incidents["origin_as_set"] = incidents["origin_as_set"].map(lambda value: json_list([value]))
    incidents["as_path_signature_set"] = incidents["as_path_signature_set"].map(lambda value: json_list([value]))
    incidents["collector_count"] = incidents["collector_count"].astype(int)
    incidents["visibility_mode"] = incidents["collector_count"].map(visibility_mode_from_count)
    incidents["aggregation_reason"] = incidents["time_bucket_key"].map(
        lambda value: "prefix_origin_path_family_collector_time_missing"
        if value == MISSING
        else "prefix_origin_path_family_collector_time_bucket"
    )
    incidents["family_hint_source"] = incidents["family_hint"].map(
        lambda value: "mixed_or_conflicting_candidate_reason_families"
        if value == "mixed_unknown"
        else "heuristic_from_candidate_reasons"
    )
    incidents["component_count_estimate"] = incidents["component_count_estimate"].clip(lower=1).astype(int)
    incidents["dominant_component_share"] = (1.0 / incidents["component_count_estimate"]).round(6)
    incidents["mixedness_hint"] = incidents.apply(
        lambda row: mixedness_from_share(
            float(row["dominant_component_share"]),
            int(row["prefix_unique_count"]),
            int(row["origin_unique_count"]),
            int(row["path_unique_count"]),
        ),
        axis=1,
    )
    incidents["split_needed_hint"] = incidents["mixedness_hint"].map({
        "low": "no",
        "medium": "possible",
        "high": "yes",
        "unknown": "unknown",
    })
    incidents["legacy_score_fields_present"] = any(col in work.columns for col in ["risk_score", "risk_bucket"])
    incidents["legacy_gate_fields_present"] = any(col in work.columns for col in ["gating_label", "certainty_score", "conflict_score"])
    incidents["legacy_final_fields_present"] = "final_alert_label" in work.columns
    incidents["legacy_reference_only_note"] = "legacy fields are reference only; final labels are weak workflow signals, not truth labels"

    prefix_ready = incidents["prefix_origin_key"] != MISSING
    time_ready = incidents["time_repair_status"].isin(["exact_join", "weak_join", "inferred"])
    path_ready = incidents["dominant_as_path_signature"] != MISSING
    collector_ready = incidents["collector_count"] > 0
    reason_ready = incidents["candidate_reason_set"] != "[]"
    incidents["evidence_grounding_ready"] = prefix_ready & time_ready & path_ready & collector_ready & reason_ready
    incidents["required_lookup_keys"] = [
        json.dumps({
            "prefix_origin_key": bool(prefix),
            "time_scope": bool(time),
            "as_path_signature": bool(path),
            "collector_set": bool(collector),
            "candidate_reason_set": bool(reason),
        }, ensure_ascii=True, sort_keys=True)
        for prefix, time, path, collector, reason in zip(prefix_ready, time_ready, path_ready, collector_ready, reason_ready)
    ]
    confidence = (
        prefix_ready.astype(float)
        + time_ready.astype(float)
        + path_ready.astype(float)
        + collector_ready.astype(float)
        + reason_ready.astype(float)
        + incidents["dominant_component_share"].astype(float)
    ) / 6.0
    incidents["aggregation_confidence"] = confidence.round(6)
    incidents["learning_ready_features"] = json_list([
        "family_hint",
        "candidate_reason_set",
        "collector_set",
        "visibility_mode",
        "mixedness_hint",
        "aggregation_confidence",
    ])
    incidents["poisoning_benchmark_relevant_fields"] = json_list([
        "collector_set",
        "visibility_mode",
        "candidate_reason_set",
        "as_path_signature_set",
    ])

    cleanup_cols = [
        "start_time_dt",
        "end_time_dt",
        "max_duration_sec",
        "prefix_unique_count",
        "origin_unique_count",
        "path_unique_count",
        "time_repair_rank_min",
        "time_repair_rank_max",
        "time_repair_status_first",
    ]
    incidents = incidents.drop(columns=[col for col in cleanup_cols if col in incidents.columns])
    return incidents[OUTPUT_COLUMNS]


def missing_rate(series: pd.Series) -> float:
    if series.empty:
        return 1.0
    return round(float(series.map(is_missing).mean()), 6)


def summarize(
    incidents: pd.DataFrame,
    candidate_rows_input: int,
    event_rows_input: int | None,
    output_dir: Path,
    candidates_path: Path,
    events_path: Path | None,
    time_window_minutes: int,
) -> dict[str, Any]:
    raw_count = int(len(incidents))
    confidence = pd.to_numeric(incidents["aggregation_confidence"], errors="coerce")
    fields_missing = {column: missing_rate(incidents[column]) for column in OUTPUT_COLUMNS}
    time_coverage = round(float((incidents["time_repair_status"].isin(["exact_join", "weak_join", "inferred"])).mean()), 6) if raw_count else 0.0
    compression_ratio = round(candidate_rows_input / raw_count, 6) if raw_count else None
    return {
        "phase": "R-AGG-2",
        "status": "completed",
        "source_entry": SOURCE_ENTRY,
        "candidate_path": str(candidates_path),
        "event_path": str(events_path) if events_path else None,
        "time_window_minutes": time_window_minutes,
        "output_dir": str(output_dir),
        "candidate_rows_input": candidate_rows_input,
        "event_rows_input": event_rows_input,
        "raw_incident_count": raw_count,
        "compression_ratio": compression_ratio,
        "time_scope_coverage": time_coverage,
        "time_repair_status_distribution": incidents["time_repair_status"].value_counts().to_dict(),
        "family_hint_distribution": incidents["family_hint"].value_counts().to_dict(),
        "visibility_mode_distribution": incidents["visibility_mode"].value_counts().to_dict(),
        "mixedness_hint_distribution": incidents["mixedness_hint"].value_counts().to_dict(),
        "aggregation_confidence_mean": round(float(confidence.mean()), 6) if confidence.notna().any() else None,
        "aggregation_confidence_p50": round(float(confidence.quantile(0.5)), 6) if confidence.notna().any() else None,
        "aggregation_confidence_p90": round(float(confidence.quantile(0.9)), 6) if confidence.notna().any() else None,
        "top_aggregation_reason_distribution": incidents["aggregation_reason"].value_counts().head(20).to_dict(),
        "fields_missing_rate": fields_missing,
        "evidence_grounding_ready_rate": round(float(incidents["evidence_grounding_ready"].mean()), 6) if raw_count else 0.0,
        "safety": {
            "no_truth_label": True,
            "no_external_evidence_attached": True,
            "learning_trained": False,
            "final_entry_used_as_primary": False,
        },
        "recommended_next_step": "R-AGG-3 aggregation quality audit or Evidence-grounded Incident design",
    }


def write_auxiliary_outputs(incidents: pd.DataFrame, output_dir: Path) -> None:
    preview_cols = OUTPUT_COLUMNS
    incidents.head(200).to_csv(output_dir / "raw_incidents_prototype_preview.csv", index=False, columns=preview_cols)
    time_audit = (
        incidents["time_repair_status"]
        .value_counts()
        .rename_axis("time_repair_status")
        .reset_index(name="raw_incident_count")
    )
    time_audit["share"] = time_audit["raw_incident_count"] / max(1, len(incidents))
    time_audit.to_csv(output_dir / "raw_incident_time_repair_audit.csv", index=False)
    grouping_cols = [
        "raw_incident_id",
        "aggregation_key",
        "aggregation_reason",
        "member_candidate_count",
        "member_event_count",
        "time_repair_status",
        "family_hint",
        "mixedness_hint",
        "aggregation_confidence",
        "dominant_component_share",
        "collector_count",
    ]
    incidents[grouping_cols].to_csv(output_dir / "raw_incident_grouping_stats.csv", index=False)


def main() -> None:
    args = parse_args()
    if args.time_window_minutes <= 0:
        raise ValueError("--time-window-minutes must be positive")
    if args.max_rows is not None and args.max_rows <= 0:
        raise ValueError("--max-rows must be positive when provided")

    schema_path = Path(args.schema)
    if not schema_path.exists():
        raise FileNotFoundError(f"schema file not found: {schema_path}")

    candidates_path = discover_path(args.run_id, args.candidates, "candidates", "candidate_events.parquet", required=True)
    events_path = discover_path(args.run_id, args.events, "events", "event_units.parquet", required=False)
    output_dir = Path(args.output_dir) if args.output_dir else Path("outputs") / "r_agg_2" / args.run_id
    prepare_output_dir(output_dir, args.overwrite)

    candidates, candidate_rows_input = load_candidates(candidates_path, args.max_rows)
    events, event_rows_input = load_events(events_path, args.max_rows)
    repaired = repair_time(candidates, events)
    features = prepare_candidate_features(repaired, args.time_window_minutes)
    incidents = build_incidents(features, candidate_rows_input, args.run_id)

    incidents.to_parquet(output_dir / "raw_incidents_prototype.parquet", index=False)
    write_auxiliary_outputs(incidents, output_dir)
    summary = summarize(
        incidents=incidents,
        candidate_rows_input=candidate_rows_input,
        event_rows_input=event_rows_input,
        output_dir=output_dir,
        candidates_path=candidates_path,
        events_path=events_path,
        time_window_minutes=args.time_window_minutes,
    )
    (output_dir / "raw_incident_prototype_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps({
        "status": "completed",
        "phase": "R-AGG-2",
        "candidate_rows_input": candidate_rows_input,
        "raw_incident_count": summary["raw_incident_count"],
        "compression_ratio": summary["compression_ratio"],
        "time_scope_coverage": summary["time_scope_coverage"],
        "output_dir": str(output_dir),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
