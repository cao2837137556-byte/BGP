"""Audit lightweight evidence-aware pre-triage feasibility.

R-EVID-0 is a read-only design and feasibility audit over R-AGG-2 Raw Incident
prototype rows. It estimates which lightweight evidence signals are available
and whether a three-way pre-triage design can protect suspicious weak signals,
identify suppressible background-like candidates, and retain gray-zone cases.

This script does not delete rows, change aggregation, train learning, or create
attack/benign truth labels.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import math
import re
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq


MISSING = "missing"
OUTPUT_FILES = [
    "r_evid_0_summary.json",
    "evidence_availability_audit.csv",
    "protected_signal_audit.csv",
    "suppressible_background_feasibility.csv",
    "gray_zone_audit.csv",
    "overlap_risk_audit.csv",
]

ORIGIN_TOKENS = [
    "new_origin",
    "origin_change",
    "unseen_origin",
    "prefix_origin_not_in_history",
    "unseen_prefix_origin",
]
PATH_TOKENS = [
    "unseen_path",
    "path_change",
    "path_len",
    "abnormal_path_length",
    "path_manipulation",
]
ASREL_TOKENS = ["valley", "triplet", "asrel", "as-rel", "path_relation", "relationship"]
COMMUNITY_TOKENS = ["community", "no_export", "no-advertise", "no_advertise", "nopeer"]
LOW_SPECIFICITY_TOKENS = ["single_collector_visibility", "unusually_short_duration_for_prefix"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit lightweight evidence-aware pre-triage feasibility.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--raw-incidents", default=None)
    parser.add_argument("--candidates", default=None)
    parser.add_argument("--events", default=None)
    parser.add_argument("--baseline", default=None)
    parser.add_argument("--rpki", default=None)
    parser.add_argument("--asrel", default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--sample-size", type=int, default=10000)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def default_run_root(run_id: str) -> Path:
    return Path("data") / "runs" / run_id


def resolve_input(explicit: str | None, default_path: Path | None, required: bool = False) -> Path | None:
    path = Path(explicit) if explicit else default_path
    if path is None:
        if required:
            raise FileNotFoundError("required input path is not configured")
        return None
    if not path.exists():
        if required:
            raise FileNotFoundError(f"required input not found: {path}")
        return None
    return path


def resolve_paths(args: argparse.Namespace) -> dict[str, Path | None]:
    run_root = default_run_root(args.run_id)
    paths = {
        "raw_incidents": resolve_input(
            args.raw_incidents,
            Path("outputs") / "r_agg_2" / args.run_id / "raw_incidents_prototype.parquet",
            required=True,
        ),
        "candidates": resolve_input(args.candidates, run_root / "candidates" / "candidate_events.parquet"),
        "events": resolve_input(args.events, run_root / "events" / "event_units.parquet"),
        "baseline": resolve_input(args.baseline, run_root / "baseline" / "baseline_prefix_origin.parquet"),
        "rpki": resolve_input(args.rpki, Path("data") / "evidence" / "rpki" / "vrp_2024-04-16.parquet"),
        "asrel": resolve_input(args.asrel, Path("data") / "evidence" / "as_relationships" / "as_rel_2024-04-01.parquet"),
        "r_agg_3_summary": resolve_input(
            None, Path("outputs") / "r_agg_3" / args.run_id / "r_agg_3_summary.json"
        ),
    }
    return paths


def prepare_output_dir(output_dir: Path, overwrite: bool) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    existing = [output_dir / name for name in OUTPUT_FILES if (output_dir / name).exists()]
    if existing and not overwrite:
        raise FileExistsError(
            "output files already exist; pass --overwrite to replace: "
            + ", ".join(str(path) for path in existing)
        )


def parquet_info(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists() or path.suffix.lower() != ".parquet":
        return {"exists": bool(path and path.exists()), "rows": None, "columns": []}
    pf = pq.ParquetFile(path)
    return {"exists": True, "rows": int(pf.metadata.num_rows), "columns": list(pf.schema.names)}


def load_raw_incidents(path: Path) -> pd.DataFrame:
    wanted = [
        "raw_incident_id",
        "source_event_ids",
        "start_time",
        "end_time",
        "duration_sec",
        "time_bucket_key",
        "dominant_prefix",
        "dominant_origin_as",
        "prefix_origin_key",
        "dominant_as_path_signature",
        "collector_set",
        "collector_count",
        "visibility_mode",
        "candidate_reason_set",
        "trigger_reason_set",
        "family_hint",
        "weak_signal_tags",
        "aggregation_confidence",
        "evidence_grounding_ready",
    ]
    schema_names = set(pq.ParquetFile(path).schema.names)
    columns = [column for column in wanted if column in schema_names]
    df = pd.read_parquet(path, columns=columns, engine="pyarrow")
    for column in wanted:
        if column not in df.columns:
            df[column] = MISSING
    return df


def normalize_text(series: pd.Series) -> pd.Series:
    return series.fillna(MISSING).astype(str)


def lower_text(series: pd.Series) -> pd.Series:
    return normalize_text(series).str.lower()


def contains_any(series: pd.Series, tokens: list[str]) -> pd.Series:
    text = lower_text(series)
    result = pd.Series(False, index=series.index)
    for token in tokens:
        result = result | text.str.contains(token, regex=False)
    return result


def safe_rate(count: int | float, denominator: int | float) -> float:
    return round(float(count) / float(denominator), 6) if denominator else 0.0


def non_missing_rate(series: pd.Series) -> float:
    text = normalize_text(series)
    present = ~text.str.lower().isin(["", MISSING, "none", "nan", "[]"])
    return safe_rate(int(present.sum()), len(series))


def normalize_asn(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    match = re.search(r"\d+", str(value))
    if not match:
        return None
    try:
        return int(match.group(0))
    except ValueError:
        return None


def make_prefix_origin_key(prefix: Any, origin: Any) -> str:
    prefix_text = str(prefix).strip() if prefix is not None else MISSING
    asn = normalize_asn(origin)
    if not prefix_text or prefix_text.lower() in {MISSING, "none", "nan"} or asn is None:
        return MISSING
    return f"{prefix_text}|{asn}"


def build_vrp_index(vrp_path: Path | None) -> dict[str, list[tuple[int, int]]]:
    if vrp_path is None or not vrp_path.exists():
        return {}
    vrp = pd.read_parquet(vrp_path, columns=["prefix", "asn", "max_length"], engine="pyarrow")
    index: dict[str, list[tuple[int, int]]] = {}
    for row in vrp.itertuples(index=False):
        try:
            network = ipaddress.ip_network(str(row.prefix), strict=False)
        except ValueError:
            continue
        asn = normalize_asn(row.asn)
        if asn is None:
            continue
        try:
            max_length = int(row.max_length)
        except (TypeError, ValueError):
            max_length = int(network.prefixlen)
        index.setdefault(str(network), []).append((asn, max_length))
    return index


def covering_vrps(prefix: str, vrp_index: dict[str, list[tuple[int, int]]]) -> list[tuple[int, int, int]]:
    if not vrp_index or not prefix or prefix.lower() in {MISSING, "none", "nan"}:
        return []
    try:
        network = ipaddress.ip_network(prefix, strict=False)
    except ValueError:
        return []
    matches: list[tuple[int, int, int]] = []
    for prefix_len in range(int(network.prefixlen), -1, -1):
        try:
            candidate = network if prefix_len == network.prefixlen else network.supernet(new_prefix=prefix_len)
        except ValueError:
            continue
        for asn, max_length in vrp_index.get(str(candidate), []):
            matches.append((asn, max_length, int(network.prefixlen)))
    return matches


def classify_rpki(prefix: str, origin: Any, vrp_index: dict[str, list[tuple[int, int]]]) -> str:
    if not vrp_index:
        return "missing"
    asn = normalize_asn(origin)
    if asn is None:
        return "missing"
    matches = covering_vrps(prefix, vrp_index)
    if not matches:
        return "unknown"
    valid = any(vrp_asn == asn and route_len <= max_len for vrp_asn, max_len, route_len in matches)
    if valid:
        return "valid"
    origin_length_mismatch = any(vrp_asn == asn and route_len > max_len for vrp_asn, max_len, route_len in matches)
    if origin_length_mismatch:
        return "invalid_length"
    alternate_origin_cover = any(route_len <= max_len and vrp_asn != asn for vrp_asn, max_len, route_len in matches)
    if alternate_origin_cover:
        return "invalid_asn"
    return "invalid_length"


def attach_rpki_status(df: pd.DataFrame, vrp_path: Path | None) -> dict[str, Any]:
    vrp_index = build_vrp_index(vrp_path)
    if not vrp_index:
        df["rpki_status"] = "missing"
        return {"cache_present": False, "unique_prefix_origin_checked": 0}

    unique = (
        df[["dominant_prefix", "dominant_origin_as"]]
        .drop_duplicates()
        .copy()
    )
    unique["prefix_origin_key_norm"] = [
        make_prefix_origin_key(prefix, origin)
        for prefix, origin in zip(unique["dominant_prefix"], unique["dominant_origin_as"])
    ]
    unique["rpki_status"] = [
        classify_rpki(str(prefix), origin, vrp_index)
        for prefix, origin in zip(unique["dominant_prefix"], unique["dominant_origin_as"])
    ]
    status_map = dict(zip(unique["prefix_origin_key_norm"], unique["rpki_status"]))
    raw_keys = [
        make_prefix_origin_key(prefix, origin)
        for prefix, origin in zip(df["dominant_prefix"], df["dominant_origin_as"])
    ]
    df["rpki_status"] = pd.Series(raw_keys, index=df.index).map(status_map).fillna("missing")
    return {"cache_present": True, "unique_prefix_origin_checked": int(len(unique))}


def first_event_id(series: pd.Series) -> pd.Series:
    text = normalize_text(series)
    extracted = text.str.extract(r'"([^"]+)"', expand=False)
    fallback = text.where(~text.str.contains("[", regex=False), MISSING)
    return extracted.fillna(fallback).fillna(MISSING)


def attach_event_rel_diagnostics(df: pd.DataFrame, events_path: Path | None) -> dict[str, Any]:
    df["first_event_id"] = first_event_id(df["source_event_ids"])
    df["event_joined"] = False
    df["rel_unknown_cnt"] = 0
    df["rel_has_unknown"] = False
    df["rel_seq"] = MISSING
    if events_path is None or not events_path.exists():
        return {"events_present": False, "event_join_rate": 0.0, "rel_fields_present": False}

    schema_names = set(pq.ParquetFile(events_path).schema.names)
    needed = [column for column in ["event_id", "rel_unknown_cnt", "rel_has_unknown", "rel_seq"] if column in schema_names]
    if "event_id" not in needed:
        return {"events_present": True, "event_join_rate": 0.0, "rel_fields_present": False}
    events = pd.read_parquet(events_path, columns=needed, engine="pyarrow").drop_duplicates("event_id")
    events = events.set_index("event_id")
    joined = df["first_event_id"].isin(events.index)
    df["event_joined"] = joined
    if "rel_unknown_cnt" in events.columns:
        df["rel_unknown_cnt"] = df["first_event_id"].map(events["rel_unknown_cnt"]).fillna(0)
    if "rel_has_unknown" in events.columns:
        mapped = df["first_event_id"].map(events["rel_has_unknown"])
        df["rel_has_unknown"] = mapped.fillna(False).astype(bool)
    if "rel_seq" in events.columns:
        df["rel_seq"] = df["first_event_id"].map(events["rel_seq"]).fillna(MISSING)
    return {
        "events_present": True,
        "event_join_rate": safe_rate(int(joined.sum()), len(df)),
        "rel_fields_present": any(column in events.columns for column in ["rel_unknown_cnt", "rel_has_unknown", "rel_seq"]),
    }


def mask_dictionary(df: pd.DataFrame) -> dict[str, pd.Series]:
    reason_text = lower_text(df["candidate_reason_set"]) + " " + lower_text(df["weak_signal_tags"])
    collector_count = pd.to_numeric(df["collector_count"], errors="coerce").fillna(0)
    rpki_status = normalize_text(df["rpki_status"])
    aggregation_confidence = pd.to_numeric(df["aggregation_confidence"], errors="coerce").fillna(0)

    origin_novelty = contains_any(reason_text, ORIGIN_TOKENS) | df["family_hint"].eq("forged_origin_like")
    path_novelty = contains_any(reason_text, PATH_TOKENS) | df["family_hint"].eq("path_manipulation_like")
    asrel_diagnostic = (
        contains_any(reason_text, ASREL_TOKENS)
        | pd.to_numeric(df["rel_unknown_cnt"], errors="coerce").fillna(0).gt(0)
        | df["rel_has_unknown"].fillna(False).astype(bool)
    )
    rpki_invalid = rpki_status.isin(["invalid_asn", "invalid_length"])
    low_visibility_with_weak_signal = collector_count.le(1) & (
        origin_novelty
        | path_novelty
        | contains_any(reason_text, ["abnormal_path_length", "unusually_short_duration", "short_duration"])
    )
    community_signal = contains_any(reason_text, COMMUNITY_TOKENS)
    known_event_like = contains_any(reason_text, ["known_event", "case_study", "inventory_match"])

    protected_masks = {
        "origin_novelty_present": origin_novelty,
        "rpki_invalid_present": rpki_invalid,
        "path_novelty_present": path_novelty,
        "asrel_diagnostic_present": asrel_diagnostic,
        "low_visibility_with_other_weak_signal": low_visibility_with_weak_signal,
        "community_or_no_export_present": community_signal,
        "known_event_like_present": known_event_like,
    }

    protected = pd.Series(False, index=df.index)
    for mask in protected_masks.values():
        protected = protected | mask

    family_backgroundish = df["family_hint"].isin(["mixed_unknown", "background_like_pattern", "stealth_visibility_like"])
    weak_or_missing_reason = (
        lower_text(df["candidate_reason_set"]).isin(["[]", MISSING, "none", "nan", ""])
        | contains_any(reason_text, LOW_SPECIFICITY_TOKENS)
    )
    no_visibility_anomaly = collector_count.gt(1) & ~lower_text(df["visibility_mode"]).isin(
        ["single_collector", "weak_visibility"]
    )
    no_origin_or_path_diagnostic = ~(origin_novelty | path_novelty | asrel_diagnostic | rpki_invalid | community_signal)
    rpki_not_protective = rpki_status.isin(["valid", "unknown", "missing"])
    suppressible = (
        ~protected
        & no_origin_or_path_diagnostic
        & rpki_not_protective
        & weak_or_missing_reason
        & no_visibility_anomaly
        & family_backgroundish
    )
    gray_zone = ~(protected | suppressible)

    broad_background_like = family_backgroundish | (
        collector_count.le(1) & rpki_not_protective & ~df["family_hint"].isin(["forged_origin_like", "route_leak_like"])
    )

    return {
        **protected_masks,
        "protected_suspicious": protected,
        "suppressible_background_like": suppressible,
        "gray_zone_retained": gray_zone,
        "broad_background_like_risk": broad_background_like,
        "family_backgroundish": family_backgroundish,
        "origin_novelty": origin_novelty,
        "path_novelty": path_novelty,
        "asrel_diagnostic": asrel_diagnostic,
        "rpki_invalid": rpki_invalid,
        "low_visibility_with_weak_signal": low_visibility_with_weak_signal,
        "weak_or_missing_reason": weak_or_missing_reason,
        "no_visibility_anomaly": no_visibility_anomaly,
        "aggregation_confidence_high": aggregation_confidence.ge(0.9),
    }


def reasons_for_index(index: Any, masks: dict[str, pd.Series], names: list[str]) -> list[str]:
    return [name for name in names if bool(masks[name].loc[index])]


def json_reason_series(sample: pd.DataFrame, masks: dict[str, pd.Series], names: list[str]) -> list[str]:
    return [json.dumps(reasons_for_index(index, masks, names), ensure_ascii=False) for index in sample.index]


def confidence_hint(sample: pd.DataFrame, protected_counts: pd.Series) -> pd.Series:
    base = protected_counts.loc[sample.index].astype(float) / 7.0
    rpki_bonus = normalize_text(sample["rpki_status"]).isin(["invalid_asn", "invalid_length"]).astype(float) * 0.2
    return (base + rpki_bonus).clip(upper=1.0).round(6)


def suppression_risk(sample: pd.DataFrame, masks: dict[str, pd.Series]) -> pd.Series:
    collector_count = pd.to_numeric(sample["collector_count"], errors="coerce").fillna(0)
    score = (
        masks["family_backgroundish"].loc[sample.index].astype(float) * 0.35
        + masks["weak_or_missing_reason"].loc[sample.index].astype(float) * 0.25
        + masks["no_visibility_anomaly"].loc[sample.index].astype(float) * 0.20
        + collector_count.gt(1).astype(float) * 0.10
        + normalize_text(sample["rpki_status"]).isin(["valid", "unknown"]).astype(float) * 0.10
    )
    return score.round(6)


def write_protected_sample(df: pd.DataFrame, masks: dict[str, pd.Series], output_dir: Path, sample_size: int) -> None:
    protected_names = [
        "origin_novelty_present",
        "rpki_invalid_present",
        "path_novelty_present",
        "asrel_diagnostic_present",
        "low_visibility_with_other_weak_signal",
        "community_or_no_export_present",
        "known_event_like_present",
    ]
    protected_count = sum(masks[name].astype(int) for name in protected_names)
    columns = [
        "raw_incident_id",
        "family_hint",
        "candidate_reason_set",
        "weak_signal_tags",
        "rpki_status",
        "collector_count",
        "visibility_mode",
    ]
    sample = df.loc[masks["protected_suspicious"], columns].head(sample_size).copy()
    sample["protected_reason_set"] = json_reason_series(sample, masks, protected_names)
    sample["protected_signal_count"] = protected_count.loc[sample.index].astype(int)
    sample["confidence_hint"] = confidence_hint(sample, protected_count)
    sample[
        [
            "raw_incident_id",
            "protected_reason_set",
            "protected_signal_count",
            "family_hint",
            "confidence_hint",
            "rpki_status",
            "collector_count",
            "visibility_mode",
            "candidate_reason_set",
            "weak_signal_tags",
        ]
    ].to_csv(output_dir / "protected_signal_audit.csv", index=False)


def write_suppressible_sample(df: pd.DataFrame, masks: dict[str, pd.Series], output_dir: Path, sample_size: int) -> None:
    reason_names = ["weak_or_missing_reason", "no_visibility_anomaly", "family_backgroundish"]
    columns = [
        "raw_incident_id",
        "family_hint",
        "candidate_reason_set",
        "weak_signal_tags",
        "rpki_status",
        "collector_count",
        "visibility_mode",
    ]
    sample = df.loc[masks["suppressible_background_like"], columns].head(sample_size).copy()
    sample["suppressible_reason_set"] = json_reason_series(sample, masks, reason_names)
    sample["suppression_risk"] = suppression_risk(sample, masks)
    sample["must_not_suppress_flag"] = False
    sample[
        [
            "raw_incident_id",
            "suppressible_reason_set",
            "suppression_risk",
            "must_not_suppress_flag",
            "family_hint",
            "rpki_status",
            "collector_count",
            "visibility_mode",
            "candidate_reason_set",
            "weak_signal_tags",
        ]
    ].to_csv(output_dir / "suppressible_background_feasibility.csv", index=False)


def write_gray_sample(df: pd.DataFrame, masks: dict[str, pd.Series], output_dir: Path, sample_size: int) -> None:
    columns = [
        "raw_incident_id",
        "family_hint",
        "candidate_reason_set",
        "weak_signal_tags",
        "rpki_status",
        "collector_count",
        "visibility_mode",
        "aggregation_confidence",
    ]
    sample = df.loc[masks["gray_zone_retained"], columns].head(sample_size).copy()
    sample["gray_zone_reason_set"] = "insufficient_protected_signal_or_unsafe_to_suppress"
    sample["retention_reason"] = "gray_zone_retained"
    sample.to_csv(output_dir / "gray_zone_audit.csv", index=False)


def write_overlap_sample(df: pd.DataFrame, masks: dict[str, pd.Series], output_dir: Path, sample_size: int) -> None:
    overlap = masks["protected_suspicious"] & masks["broad_background_like_risk"]
    protected_names = [
        "origin_novelty_present",
        "rpki_invalid_present",
        "path_novelty_present",
        "asrel_diagnostic_present",
        "low_visibility_with_other_weak_signal",
        "community_or_no_export_present",
        "known_event_like_present",
    ]
    columns = [
        "raw_incident_id",
        "family_hint",
        "candidate_reason_set",
        "weak_signal_tags",
        "rpki_status",
        "collector_count",
        "visibility_mode",
    ]
    sample = df.loc[overlap, columns].head(sample_size).copy()
    sample["overlap_type"] = "protected_suspicious_and_background_like_risk"
    sample["protected_reason_set"] = json_reason_series(sample, masks, protected_names)
    sample["risk_note"] = "do_not_suppress_without_evidence_aware_protection"
    sample.to_csv(output_dir / "overlap_risk_audit.csv", index=False)


def evidence_availability_rows(
    df: pd.DataFrame,
    masks: dict[str, pd.Series],
    paths: dict[str, Path | None],
    event_info: dict[str, Any],
    rpki_info: dict[str, Any],
) -> list[dict[str, Any]]:
    raw_count = len(df)
    rpki_status = normalize_text(df["rpki_status"])
    rpki_covered = rpki_status.isin(["valid", "invalid_asn", "invalid_length"])
    asrel_signal = masks["asrel_diagnostic"]
    rows = [
        {
            "evidence_type": "prefix_origin_key",
            "source_path": str(paths["raw_incidents"]),
            "available": True,
            "coverage_rate": non_missing_rate(df["prefix_origin_key"]),
            "join_ready": True,
            "notes": "Raw Incident lookup key is present.",
            "misuse_boundary": "prefix_origin_key is not a verdict",
        },
        {
            "evidence_type": "origin_novelty",
            "source_path": str(paths["raw_incidents"]),
            "available": True,
            "coverage_rate": safe_rate(int(masks["origin_novelty"].sum()), raw_count),
            "join_ready": True,
            "notes": "Derived from candidate_reason_set, weak_signal_tags, and family_hint.",
            "misuse_boundary": "new origin is not confirmed hijack",
        },
        {
            "evidence_type": "path_novelty",
            "source_path": str(paths["raw_incidents"]),
            "available": True,
            "coverage_rate": safe_rate(int(masks["path_novelty"].sum()), raw_count),
            "join_ready": True,
            "notes": "Derived from candidate reasons and path-oriented family hints.",
            "misuse_boundary": "path novelty is not confirmed path manipulation",
        },
        {
            "evidence_type": "visibility_signals",
            "source_path": str(paths["raw_incidents"]),
            "available": True,
            "coverage_rate": min(
                non_missing_rate(df["collector_count"]),
                non_missing_rate(df["collector_set"]),
                non_missing_rate(df["visibility_mode"]),
            ),
            "join_ready": True,
            "notes": "collector_count, collector_set, and visibility_mode are retained.",
            "misuse_boundary": "low visibility is not confirmed stealth or NO_EXPORT",
        },
        {
            "evidence_type": "rpki_status",
            "source_path": str(paths["rpki"]) if paths["rpki"] else MISSING,
            "available": bool(rpki_info.get("cache_present")),
            "coverage_rate": safe_rate(int(rpki_covered.sum()), raw_count),
            "join_ready": bool(rpki_info.get("cache_present")),
            "notes": "Computed by local VRP prefix containment over unique prefix-origin keys.",
            "misuse_boundary": "RPKI invalid is not attack truth; RPKI valid is not benign",
        },
        {
            "evidence_type": "asrel_path_diagnostic",
            "source_path": str(paths["events"]) if paths["events"] else MISSING,
            "available": bool(event_info.get("rel_fields_present")),
            "coverage_rate": float(event_info.get("event_join_rate", 0.0)),
            "join_ready": bool(event_info.get("rel_fields_present")),
            "notes": "Uses event-layer rel_* diagnostic fields when event_id join succeeds; these are diagnostic, not route-leak truth.",
            "misuse_boundary": "AS-rel diagnostic is not route leak truth",
        },
        {
            "evidence_type": "candidate_reason_set",
            "source_path": str(paths["raw_incidents"]),
            "available": True,
            "coverage_rate": non_missing_rate(df["candidate_reason_set"]),
            "join_ready": True,
            "notes": "Stage 1 weak signal provenance retained in Raw Incident.",
            "misuse_boundary": "candidate reasons are not truth labels",
        },
        {
            "evidence_type": "weak_signal_tags",
            "source_path": str(paths["raw_incidents"]),
            "available": True,
            "coverage_rate": non_missing_rate(df["weak_signal_tags"]),
            "join_ready": True,
            "notes": "Weak semantic tags retained in Raw Incident.",
            "misuse_boundary": "weak tags are not attack labels",
        },
        {
            "evidence_type": "time_scope",
            "source_path": str(paths["raw_incidents"]),
            "available": True,
            "coverage_rate": min(non_missing_rate(df["start_time"]), non_missing_rate(df["end_time"])),
            "join_ready": True,
            "notes": "R-AGG-2 event-entry time repair is available.",
            "misuse_boundary": "duration is not a truth label",
        },
        {
            "evidence_type": "family_hint",
            "source_path": str(paths["raw_incidents"]),
            "available": True,
            "coverage_rate": non_missing_rate(df["family_hint"]),
            "join_ready": True,
            "notes": "Family hint exists but R-AGG-3 found mapping repair is needed.",
            "misuse_boundary": "family_hint is semantic hint, not attack label",
        },
        {
            "evidence_type": "communities_no_export",
            "source_path": str(paths["raw_incidents"]),
            "available": False,
            "coverage_rate": 0.0,
            "join_ready": False,
            "notes": "R-2D-0 found raw communities exist but are not propagated into Raw Incident.",
            "misuse_boundary": "NO_EXPORT present is not confirmed attack; absent is not safe",
        },
    ]
    rows.append(
        {
            "evidence_type": "asrel_aligned_cache_presence",
            "source_path": str(paths["asrel"]) if paths["asrel"] else MISSING,
            "available": bool(paths["asrel"]),
            "coverage_rate": 1.0 if paths["asrel"] else 0.0,
            "join_ready": False,
            "notes": "Aligned AS-rel cache exists, but R-EVID-0 does not recompute path legality from raw AS paths.",
            "misuse_boundary": "cache presence is not incident-level path evidence",
        }
    )
    rows.append(
        {
            "evidence_type": "asrel_diagnostic_signal_rate",
            "source_path": str(paths["events"]) if paths["events"] else MISSING,
            "available": bool(event_info.get("rel_fields_present")),
            "coverage_rate": safe_rate(int(asrel_signal.sum()), raw_count),
            "join_ready": bool(event_info.get("rel_fields_present")),
            "notes": "Fraction with relation unknown/path diagnostic signal, not coverage.",
            "misuse_boundary": "diagnostic signal is not route leak truth",
        }
    )
    return rows


def stop_loss_assessment(
    df: pd.DataFrame,
    masks: dict[str, pd.Series],
    rpki_coverage: float,
    asrel_diagnostic_coverage: float,
    protected_background_overlap_rate: float,
) -> dict[str, Any]:
    raw_count = len(df)
    gray_rate = safe_rate(int(masks["gray_zone_retained"].sum()), raw_count)
    mixed_unknown_rate = safe_rate(int(df["family_hint"].eq("mixed_unknown").sum()), raw_count)
    risky_suppression_rate = protected_background_overlap_rate
    triggered = []
    if protected_background_overlap_rate > 0.20:
        triggered.append("protected_background_overlap_rate_too_high")
    if gray_rate > 0.50:
        triggered.append("gray_zone_rate_too_high")
    if rpki_coverage < 0.20:
        triggered.append("rpki_coverage_too_low_for_pretriage")
    if asrel_diagnostic_coverage < 0.20:
        triggered.append("asrel_diagnostic_coverage_too_low_or_not_join_ready")
    if risky_suppression_rate > 0.01:
        triggered.append("risky_suppression_rate_too_high")
    if mixed_unknown_rate > 0.40:
        triggered.append("family_hint_mixed_unknown_rate_too_high")

    if triggered:
        decision = "do_not_enter_R_EVID_1_yet"
        recommended = "R-AGG-4 family_hint mapping repair, then rerun R-EVID-0 before implementation"
    else:
        decision = "eligible_for_R_EVID_1_smoke"
        recommended = "R-EVID-1 evidence pre-triage smoke with no deletion"
    return {
        "triggered": bool(triggered),
        "triggered_criteria": triggered,
        "gray_zone_rate": gray_rate,
        "mixed_unknown_rate": mixed_unknown_rate,
        "risky_suppression_rate": risky_suppression_rate,
        "decision": decision,
        "recommended_action": recommended,
    }


def main() -> None:
    args = parse_args()
    paths = resolve_paths(args)
    output_dir = Path(args.output_dir) if args.output_dir else Path("outputs") / "r_evid_0" / args.run_id
    prepare_output_dir(output_dir, args.overwrite)

    raw_path = paths["raw_incidents"]
    assert raw_path is not None
    df = load_raw_incidents(raw_path)
    raw_count = len(df)

    event_info = attach_event_rel_diagnostics(df, paths["events"])
    rpki_info = attach_rpki_status(df, paths["rpki"])
    masks = mask_dictionary(df)

    availability_rows = evidence_availability_rows(df, masks, paths, event_info, rpki_info)
    availability_df = pd.DataFrame(availability_rows)
    availability_df.to_csv(output_dir / "evidence_availability_audit.csv", index=False)

    write_protected_sample(df, masks, output_dir, args.sample_size)
    write_suppressible_sample(df, masks, output_dir, args.sample_size)
    write_gray_sample(df, masks, output_dir, args.sample_size)
    write_overlap_sample(df, masks, output_dir, args.sample_size)

    protected_count = int(masks["protected_suspicious"].sum())
    suppressible_count = int(masks["suppressible_background_like"].sum())
    gray_count = int(masks["gray_zone_retained"].sum())
    protected_background_overlap = masks["protected_suspicious"] & masks["broad_background_like_risk"]
    protected_background_overlap_count = int(protected_background_overlap.sum())
    protected_background_overlap_rate = safe_rate(protected_background_overlap_count, raw_count)

    rpki_status_dist = normalize_text(df["rpki_status"]).value_counts(dropna=False).to_dict()
    rpki_coverage = safe_rate(
        int(normalize_text(df["rpki_status"]).isin(["valid", "invalid_asn", "invalid_length"]).sum()),
        raw_count,
    )
    asrel_diagnostic_coverage = float(event_info.get("event_join_rate", 0.0))
    stop_loss = stop_loss_assessment(
        df,
        masks,
        rpki_coverage,
        asrel_diagnostic_coverage,
        protected_background_overlap_rate,
    )

    evidence_rate_by_type = {
        str(row["evidence_type"]): float(row["coverage_rate"])
        for row in availability_rows
    }
    summary = {
        "phase": "R-EVID-0",
        "status": "completed",
        "run_id": args.run_id,
        "raw_incidents_path": str(raw_path),
        "raw_incident_count": raw_count,
        "sample_size_per_detail_output": args.sample_size,
        "input_inventory": {
            "raw_incidents": parquet_info(paths["raw_incidents"]),
            "candidates": parquet_info(paths["candidates"]),
            "events": parquet_info(paths["events"]),
            "baseline": parquet_info(paths["baseline"]),
            "rpki": parquet_info(paths["rpki"]),
            "asrel": parquet_info(paths["asrel"]),
            "r_agg_3_summary_present": bool(paths["r_agg_3_summary"]),
        },
        "evidence_availability_rate_by_type": evidence_rate_by_type,
        "protected_suspicious_count": protected_count,
        "protected_suspicious_rate": safe_rate(protected_count, raw_count),
        "suppressible_background_like_count": suppressible_count,
        "suppressible_background_like_rate": safe_rate(suppressible_count, raw_count),
        "gray_zone_count": gray_count,
        "gray_zone_rate": safe_rate(gray_count, raw_count),
        "protected_background_overlap_count": protected_background_overlap_count,
        "protected_background_overlap_rate": protected_background_overlap_rate,
        "risky_suppression_count": protected_background_overlap_count,
        "rpki_coverage": rpki_coverage,
        "rpki_status_distribution": {str(key): int(value) for key, value in rpki_status_dist.items()},
        "rpki_cache_present": bool(rpki_info.get("cache_present")),
        "rpki_unique_prefix_origin_checked": int(rpki_info.get("unique_prefix_origin_checked", 0)),
        "asrel_diagnostic_coverage": asrel_diagnostic_coverage,
        "asrel_diagnostic_signal_rate": safe_rate(int(masks["asrel_diagnostic"].sum()), raw_count),
        "event_join_rate": float(event_info.get("event_join_rate", 0.0)),
        "aligned_asrel_cache_present": bool(paths["asrel"]),
        "aligned_asrel_incident_join_ready": False,
        "family_hint_distribution": {
            str(key): int(value) for key, value in df["family_hint"].value_counts(dropna=False).to_dict().items()
        },
        "stop_loss_assessment": stop_loss,
        "recommended_next_step": stop_loss["recommended_action"],
        "truth_safety_statement": {
            "rpki_invalid_is_attack_truth": False,
            "asrel_diagnostic_is_route_leak_truth": False,
            "background_like_is_benign": False,
            "trained_learning": False,
            "implemented_suppression": False,
        },
        "output_files": OUTPUT_FILES,
    }
    with (output_dir / "r_evid_0_summary.json").open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(
        json.dumps(
            {
                "status": "completed",
                "phase": "R-EVID-0",
                "raw_incident_count": raw_count,
                "protected_suspicious_rate": summary["protected_suspicious_rate"],
                "suppressible_background_like_rate": summary["suppressible_background_like_rate"],
                "gray_zone_rate": summary["gray_zone_rate"],
                "stop_loss_decision": stop_loss["decision"],
                "output_dir": str(output_dir),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
