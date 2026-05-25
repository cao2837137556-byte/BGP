"""Prototype candidate-entry to Raw Incident Dossier schema mapping.

R-AGG-1 is a schema-design and mapping-preview step. This script reads a small
candidate-entry sample and previews how existing candidate fields can populate
Raw Incident Dossier schema v0. It does not aggregate final incidents, attach
external evidence, train learning, or modify any input file.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import pyarrow.parquet as pq


MISSING = "missing"

FAMILY_HINT_VALUES = [
    "forged_origin_like",
    "route_leak_like",
    "path_manipulation_like",
    "stealth_visibility_like",
    "background_like_pattern",
    "mixed_unknown",
]

SCHEMA_FIELDS: list[dict[str, Any]] = [
    {"group": "identity", "field": "raw_incident_id", "required": True},
    {"group": "identity", "field": "run_id", "required": True},
    {"group": "identity", "field": "source_entry", "required": True},
    {"group": "identity", "field": "source_row_count", "required": True},
    {"group": "identity", "field": "source_member_event_ids", "required": False},
    {"group": "time_scope", "field": "start_time", "required": True},
    {"group": "time_scope", "field": "end_time", "required": True},
    {"group": "time_scope", "field": "duration_sec", "required": False},
    {"group": "time_scope", "field": "time_bucket_key", "required": False},
    {"group": "time_scope", "field": "time_completeness_flag", "required": True},
    {"group": "routing_object", "field": "prefix_set", "required": True},
    {"group": "routing_object", "field": "dominant_prefix", "required": True},
    {"group": "routing_object", "field": "origin_as_set", "required": True},
    {"group": "routing_object", "field": "dominant_origin_as", "required": True},
    {"group": "routing_object", "field": "prefix_origin_key", "required": True},
    {"group": "routing_object", "field": "as_path_signature_set", "required": True},
    {"group": "routing_object", "field": "dominant_as_path_signature", "required": True},
    {"group": "observation_scope", "field": "collector_set", "required": True},
    {"group": "observation_scope", "field": "collector_count", "required": False},
    {"group": "observation_scope", "field": "visibility_mode", "required": False},
    {"group": "observation_scope", "field": "visibility_span_hint", "required": False},
    {"group": "aggregation_explanation", "field": "aggregation_key", "required": True},
    {"group": "aggregation_explanation", "field": "aggregation_reason", "required": True},
    {"group": "aggregation_explanation", "field": "member_event_count", "required": True},
    {"group": "aggregation_explanation", "field": "candidate_reason_set", "required": True},
    {"group": "aggregation_explanation", "field": "trigger_reason_set", "required": False},
    {"group": "weak_semantic_hint", "field": "family_hint", "required": True},
    {"group": "weak_semantic_hint", "field": "family_hint_source", "required": True},
    {"group": "weak_semantic_hint", "field": "weak_signal_tags", "required": False},
    {"group": "structure_quality", "field": "mixedness_hint", "required": False},
    {"group": "structure_quality", "field": "aggregation_confidence", "required": False},
    {"group": "structure_quality", "field": "component_count_estimate", "required": False},
    {"group": "structure_quality", "field": "dominant_component_share", "required": False},
    {"group": "structure_quality", "field": "split_needed_hint", "required": False},
    {"group": "legacy_reference", "field": "legacy_score_fields_present", "required": True},
    {"group": "legacy_reference", "field": "legacy_gate_fields_present", "required": True},
    {"group": "legacy_reference", "field": "legacy_final_fields_present", "required": True},
    {"group": "legacy_reference", "field": "legacy_reference_only_note", "required": True},
    {"group": "downstream_hooks", "field": "evidence_grounding_ready", "required": True},
    {"group": "downstream_hooks", "field": "required_lookup_keys", "required": True},
    {"group": "downstream_hooks", "field": "learning_ready_features", "required": False},
    {"group": "downstream_hooks", "field": "poisoning_benchmark_relevant_fields", "required": False},
]

OUTPUT_COLUMNS = [item["field"] for item in SCHEMA_FIELDS]

FIELD_ALIASES = {
    "event_id": ["event_id", "member_event_id"],
    "run_id": ["run_id"],
    "prefix": ["prefix", "dominant_prefix"],
    "origin_as": ["origin_as", "origin", "origin_asn", "dominant_origin_as"],
    "as_path": ["as_path_signature", "as_path_clean", "as_path", "path_signature"],
    "collector": ["collector_set", "collector", "collector_name"],
    "collector_count": ["collector_count", "visibility_count"],
    "start_time": ["first_seen", "start_time", "ts", "timestamp", "time"],
    "end_time": ["last_seen", "end_time", "ts", "timestamp", "time"],
    "duration_sec": ["duration_sec", "duration", "time_span_sec"],
    "candidate_reasons": ["candidate_reasons", "trigger_reasons", "reason_signature"],
    "record_count": ["record_count", "member_event_count"],
    "matched_rule_count": ["matched_rule_count"],
    "prefix_unique_origins": ["prefix_unique_origins"],
    "po_unique_paths": ["po_unique_paths"],
    "po_collector_support": ["po_collector_support"],
    "visibility_count": ["visibility_count", "collector_count"],
    "risk_score": ["risk_score", "risk_bucket"],
    "gate_fields": ["gating_label", "certainty_score", "conflict_score"],
    "final_fields": ["final_alert_label"],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview candidate-entry mapping to Raw Incident Dossier schema v0."
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--candidates", default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--sample-size", type=int, default=5000)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def discover_candidates(run_id: str, explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit)
    else:
        path = Path("data") / "runs" / run_id / "candidates" / "candidate_events.parquet"
    if not path.exists():
        raise FileNotFoundError(f"candidate parquet not found: {path}")
    return path


def prepare_output_dir(path: Path, overwrite: bool) -> None:
    output_files = [
        path / "raw_incident_schema_mapping_preview.csv",
        path / "raw_incident_schema_mapping_summary.json",
    ]
    existing = [p for p in output_files if p.exists()]
    if existing and not overwrite:
        raise FileExistsError(
            "output files already exist; pass --overwrite to replace: "
            + ", ".join(str(p) for p in existing)
        )
    path.mkdir(parents=True, exist_ok=True)


def first_present(columns: Iterable[str], names: Iterable[str]) -> str | None:
    column_set = set(columns)
    for name in names:
        if name in column_set:
            return name
    return None


def build_field_map(columns: list[str]) -> dict[str, str | None]:
    return {key: first_present(columns, aliases) for key, aliases in FIELD_ALIASES.items()}


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


def row_value(row: pd.Series, column: str | None, default: Any = MISSING) -> Any:
    if not column or column not in row.index:
        return default
    value = row[column]
    if is_missing(value):
        return default
    return value


def normalize_scalar(value: Any) -> str:
    if is_missing(value):
        return MISSING
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


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


def json_list(values: list[str]) -> str:
    return json.dumps(values, ensure_ascii=True)


def derive_family_hint(reasons: list[str], collector_count: Any, as_path: Any) -> tuple[str, str]:
    reason_text = " ".join(reasons).lower()
    if any(token in reason_text for token in ["origin", "prefix_origin", "new_origin"]):
        return "forged_origin_like", "heuristic_from_candidate_reasons"
    if any(token in reason_text for token in ["route_leak", "valley", "peer_transit"]):
        return "route_leak_like", "heuristic_from_candidate_reasons"
    if any(token in reason_text for token in ["path", "as_path", "unseen_path"]):
        return "path_manipulation_like", "heuristic_from_candidate_reasons"
    try:
        collector_num = float(collector_count)
    except (TypeError, ValueError):
        collector_num = math.nan
    if "single_collector" in reason_text or (not math.isnan(collector_num) and collector_num <= 1):
        return "stealth_visibility_like", "heuristic_from_visibility"
    if "background" in reason_text:
        return "background_like_pattern", "heuristic_from_candidate_reasons"
    if not is_missing(as_path):
        return "path_manipulation_like", "heuristic_from_path_presence"
    return "mixed_unknown", "fallback"


def derive_visibility_mode(collector_count: Any) -> str:
    try:
        count = float(collector_count)
    except (TypeError, ValueError):
        return "unknown_visibility"
    if count <= 1:
        return "single_collector"
    if count <= 3:
        return "limited_collectors"
    return "multi_collector"


def stable_short_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def as_path_signature(value: Any) -> str:
    if is_missing(value):
        return MISSING
    text = " ".join(str(value).split())
    if not text:
        return MISSING
    return stable_short_hash(text)


def derive_time_bucket(start_time: Any) -> str:
    if is_missing(start_time):
        return MISSING
    try:
        ts = pd.to_datetime(start_time, utc=True)
        return ts.floor("15min").isoformat()
    except Exception:
        return MISSING


def time_completeness(start_time: Any, end_time: Any, duration: Any) -> str:
    has_start = not is_missing(start_time)
    has_end = not is_missing(end_time)
    has_duration = not is_missing(duration)
    if has_start and has_end and has_duration:
        return "complete"
    if has_duration and not (has_start or has_end):
        return "duration_only"
    if has_start or has_end or has_duration:
        return "partial"
    return "missing_time"


def derive_mixedness(row: pd.Series, field_map: dict[str, str | None]) -> str:
    unique_origins = row_value(row, field_map.get("prefix_unique_origins"), MISSING)
    unique_paths = row_value(row, field_map.get("po_unique_paths"), MISSING)
    matched_rules = row_value(row, field_map.get("matched_rule_count"), MISSING)
    try:
        origins = float(unique_origins)
    except (TypeError, ValueError):
        origins = math.nan
    try:
        paths = float(unique_paths)
    except (TypeError, ValueError):
        paths = math.nan
    try:
        rules = float(matched_rules)
    except (TypeError, ValueError):
        rules = math.nan
    if (not math.isnan(origins) and origins > 1) or (not math.isnan(paths) and paths > 50):
        return "possibly_mixed"
    if not math.isnan(rules) and rules >= 2:
        return "weakly_explained"
    return "unknown"


def source_field_presence(columns: list[str], candidates: list[str]) -> bool:
    return any(name in columns for name in candidates)


def read_sample(path: Path, sample_size: int) -> tuple[pd.DataFrame, int]:
    parquet = pq.ParquetFile(path)
    row_count = parquet.metadata.num_rows if parquet.metadata else 0
    batches = []
    remaining = sample_size
    for batch in parquet.iter_batches(batch_size=min(remaining, 65536)):
        batches.append(batch.to_pandas())
        remaining -= batch.num_rows
        if remaining <= 0:
            break
    if batches:
        sample = pd.concat(batches, ignore_index=True)
        if len(sample) > sample_size:
            sample = sample.head(sample_size)
    else:
        sample = pd.DataFrame(columns=parquet.schema.names)
    return sample, row_count


def map_row(row: pd.Series, idx: int, field_map: dict[str, str | None], total_rows: int, cli_run_id: str, columns: list[str]) -> dict[str, Any]:
    event_id = normalize_scalar(row_value(row, field_map.get("event_id"), f"sample_{idx}"))
    run_id = normalize_scalar(row_value(row, field_map.get("run_id"), cli_run_id))
    prefix = normalize_scalar(row_value(row, field_map.get("prefix"), MISSING))
    origin_as = normalize_scalar(row_value(row, field_map.get("origin_as"), MISSING))
    raw_path = row_value(row, field_map.get("as_path"), MISSING)
    path_sig = as_path_signature(raw_path)
    collector_raw = row_value(row, field_map.get("collector"), MISSING)
    collector_values = parse_list_like(collector_raw)
    collector_count = row_value(row, field_map.get("collector_count"), len(collector_values) if collector_values else MISSING)
    start_time = row_value(row, field_map.get("start_time"), MISSING)
    end_time = row_value(row, field_map.get("end_time"), MISSING)
    duration = row_value(row, field_map.get("duration_sec"), MISSING)
    reasons = parse_list_like(row_value(row, field_map.get("candidate_reasons"), []))
    family_hint, family_source = derive_family_hint(reasons, collector_count, raw_path)
    time_bucket = derive_time_bucket(start_time)
    prefix_origin_key = MISSING if MISSING in {prefix, origin_as} else f"{prefix}|{origin_as}"
    aggregation_key_parts = [prefix_origin_key, time_bucket, family_hint]
    aggregation_key = "|".join(part for part in aggregation_key_parts if part != MISSING) or MISSING
    member_count = row_value(row, field_map.get("record_count"), 1)
    mixedness = derive_mixedness(row, field_map)
    split_needed = "possible" if mixedness == "possibly_mixed" else "unknown"

    time_state = time_completeness(start_time, end_time, duration)
    time_lookup_ready = time_state in {"complete", "partial"}
    required_lookup_keys = {
        "prefix_origin_key": prefix_origin_key != MISSING,
        "time_scope": time_lookup_ready,
        "as_path_signature": path_sig != MISSING,
        "collector_set": bool(collector_values),
        "candidate_reason_set": bool(reasons),
    }
    available_required = sum(1 for value in required_lookup_keys.values() if value)
    aggregation_confidence = round(available_required / len(required_lookup_keys), 6)
    evidence_ready = all(required_lookup_keys.values())

    return {
        "raw_incident_id": f"rawproto_{stable_short_hash(run_id + ':' + event_id)}",
        "run_id": run_id,
        "source_entry": "candidate-entry",
        "source_row_count": total_rows,
        "source_member_event_ids": json_list([event_id] if event_id != MISSING else []),
        "start_time": normalize_scalar(start_time),
        "end_time": normalize_scalar(end_time),
        "duration_sec": normalize_scalar(duration),
        "time_bucket_key": time_bucket,
        "time_completeness_flag": time_state,
        "prefix_set": json_list([prefix] if prefix != MISSING else []),
        "dominant_prefix": prefix,
        "origin_as_set": json_list([origin_as] if origin_as != MISSING else []),
        "dominant_origin_as": origin_as,
        "prefix_origin_key": prefix_origin_key,
        "as_path_signature_set": json_list([path_sig] if path_sig != MISSING else []),
        "dominant_as_path_signature": path_sig,
        "collector_set": json_list(collector_values),
        "collector_count": normalize_scalar(collector_count),
        "visibility_mode": derive_visibility_mode(collector_count),
        "visibility_span_hint": normalize_scalar(row_value(row, field_map.get("visibility_count"), collector_count)),
        "aggregation_key": aggregation_key,
        "aggregation_reason": "candidate_reason_match" if reasons else "candidate_entry_prototype",
        "member_event_count": normalize_scalar(member_count),
        "candidate_reason_set": json_list(reasons),
        "trigger_reason_set": json_list(reasons),
        "family_hint": family_hint,
        "family_hint_source": family_source,
        "weak_signal_tags": json_list(reasons),
        "mixedness_hint": mixedness,
        "aggregation_confidence": aggregation_confidence,
        "component_count_estimate": 1,
        "dominant_component_share": MISSING,
        "split_needed_hint": split_needed,
        "legacy_score_fields_present": source_field_presence(columns, FIELD_ALIASES["risk_score"]),
        "legacy_gate_fields_present": source_field_presence(columns, FIELD_ALIASES["gate_fields"]),
        "legacy_final_fields_present": source_field_presence(columns, FIELD_ALIASES["final_fields"]),
        "legacy_reference_only_note": "legacy fields are reference only; final labels are weak workflow signals, not truth labels",
        "evidence_grounding_ready": evidence_ready,
        "required_lookup_keys": json.dumps(required_lookup_keys, ensure_ascii=True, sort_keys=True),
        "learning_ready_features": json_list([
            "family_hint",
            "candidate_reason_set",
            "collector_set",
            "visibility_mode",
            "mixedness_hint",
            "aggregation_confidence",
        ]),
        "poisoning_benchmark_relevant_fields": json_list([
            "collector_set",
            "visibility_mode",
            "candidate_reason_set",
            "as_path_signature_set",
        ]),
    }


def missing_rate(values: pd.Series) -> float:
    if len(values) == 0:
        return 1.0
    return round(float(values.map(is_missing).mean()), 6)


def summarize(preview: pd.DataFrame, sample: pd.DataFrame, total_rows: int, path: Path, field_map: dict[str, str | None]) -> dict[str, Any]:
    required_fields = [item["field"] for item in SCHEMA_FIELDS if item["required"]]
    field_missing = {field: missing_rate(preview[field]) for field in OUTPUT_COLUMNS}
    required_missing = {field: field_missing[field] for field in required_fields}
    covered_fields = [field for field, rate in field_missing.items() if rate < 1.0]
    missing_required_fields = [field for field, rate in required_missing.items() if rate >= 1.0]

    lookup_key_rates = {
        "prefix_origin_key": 1.0 - field_missing["prefix_origin_key"],
        "time_scope": round(float(preview["time_completeness_flag"].isin(["complete", "partial"]).mean()), 6) if len(preview) else 0.0,
        "as_path_signature": 1.0 - field_missing["dominant_as_path_signature"],
        "collector_set": round(float((preview["collector_set"] != "[]").mean()), 6) if len(preview) else 0.0,
        "candidate_reason_set": round(float((preview["candidate_reason_set"] != "[]").mean()), 6) if len(preview) else 0.0,
    }
    available_lookup_keys = [key for key, rate in lookup_key_rates.items() if rate > 0.0]

    fields_needing_repair = []
    if lookup_key_rates["time_scope"] < 1.0:
        fields_needing_repair.append("start_time/end_time: candidate-entry needs event-entry join or upstream retention")
    if field_missing["time_bucket_key"] >= 1.0:
        fields_needing_repair.append("time_bucket_key: needs start_time retention or event join")
    if field_missing["dominant_component_share"] >= 1.0:
        fields_needing_repair.append("dominant_component_share: only available after R-AGG-2 aggregation")
    if field_missing["collector_set"] > 0.0:
        fields_needing_repair.append("collector_set: repair candidate collector retention if missing")

    family_counts = preview["family_hint"].value_counts(dropna=False).to_dict() if "family_hint" in preview else {}
    required_field_missing_rate = round(sum(required_missing.values()) / len(required_missing), 6) if required_missing else 0.0

    return {
        "phase": "R-AGG-1",
        "schema": "Raw Incident Dossier schema v0",
        "source_entry": "candidate-entry",
        "candidate_path": str(path),
        "candidate_rows_total": total_rows,
        "candidate_row_count_sampled": len(sample),
        "candidate_columns": list(sample.columns),
        "detected_field_map": field_map,
        "schema_field_count": len(OUTPUT_COLUMNS),
        "schema_field_covered_count": len(covered_fields),
        "schema_field_coverage": round(len(covered_fields) / len(OUTPUT_COLUMNS), 6) if OUTPUT_COLUMNS else 0.0,
        "required_field_count": len(required_fields),
        "required_field_missing_rate": required_field_missing_rate,
        "required_field_missing_rates": required_missing,
        "available_lookup_keys": available_lookup_keys,
        "lookup_key_coverage_rates": lookup_key_rates,
        "fields_needing_upstream_repair": fields_needing_repair,
        "family_hint_distribution_sample": family_counts,
        "safety": {
            "no_truth_label": True,
            "no_external_evidence_attached": True,
            "learning_trained": False,
            "final_labels_are_truth": False,
        },
        "next_recommended_phase": "R-AGG-2 prototype aggregation",
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    if args.sample_size <= 0:
        raise ValueError("--sample-size must be positive")
    candidates = discover_candidates(args.run_id, args.candidates)
    output_dir = Path(args.output_dir) if args.output_dir else Path("outputs") / "r_agg_1" / args.run_id
    prepare_output_dir(output_dir, args.overwrite)

    sample, total_rows = read_sample(candidates, args.sample_size)
    field_map = build_field_map(list(sample.columns))
    rows = [
        map_row(row, idx, field_map, total_rows, args.run_id, list(sample.columns))
        for idx, (_, row) in enumerate(sample.iterrows())
    ]
    preview = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    summary = summarize(preview, sample, total_rows, candidates, field_map)

    write_csv(output_dir / "raw_incident_schema_mapping_preview.csv", rows)
    (output_dir / "raw_incident_schema_mapping_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps({
        "status": "completed",
        "phase": "R-AGG-1",
        "sampled_rows": len(sample),
        "schema_field_coverage": summary["schema_field_coverage"],
        "required_field_missing_rate": summary["required_field_missing_rate"],
        "output_dir": str(output_dir),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
