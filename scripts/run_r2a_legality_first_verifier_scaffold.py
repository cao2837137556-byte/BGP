import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


RUN_ID_DEFAULT = "s2a_expanded_v01_pilot_6h_april16"
RUN_DATE_DEFAULT = "2024-04-16"
OUTPUT_DIR_DEFAULT = "outputs/r2a_legality_first_verifier_v01"

R1_VERDICTS = {
    "strongly_supported_suspicious",
    "evidence_supported_suspicious",
    "evidence_conflict",
    "evidence_insufficient",
    "external_evidence_unavailable",
    "background_like_but_unconfirmed",
    "stale_evidence_only",
    "abstain",
}

R1_EVIDENCE_STATES = {
    "aligned_strong",
    "aligned_medium",
    "aligned_weak",
    "stale_diagnostic",
    "unavailable",
    "conflicting",
    "monitor_only",
    "poisoning_susceptible",
    "external_confirmed_pending",
    "not_applicable",
}

LEARNING_ELIGIBILITY = {
    "positive_candidate",
    "ranking_only",
    "abstain_class",
    "conflict_class",
    "no",
}

QUEUE_COLS = [
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

TICKET_COLS = [
    "incident_id",
    "run_id",
    "incident_priority",
    "incident_start",
    "incident_end",
    "incident_duration_sec",
    "micro_incident_count",
    "mean_certainty_score",
    "mean_conflict_score",
    "mean_evidence_support_score",
    "missing_rate",
    "label_distribution",
    "source_layer_distribution",
    "reason_distribution",
]

S3D2_COLS = [
    "incident_id",
    "rpki_status",
    "rpki_evidence_strength",
    "rpki_evidence_note",
    "rel_seq_available",
    "rel_unknown_cnt",
    "rel_unknown_ratio",
    "rel_has_unknown",
    "path_relation_risk_score",
    "possible_valley_free_violation",
    "path_relation_evidence_strength",
    "path_relation_note",
    "as_rel_snapshot_stale",
    "known_event_match_status",
    "known_event_match_strength",
    "known_event_id",
    "known_event_note",
    "verification_evidence_score",
    "verification_evidence_bucket",
    "verification_status_candidate",
    "evidence_source_flags",
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


def count_dict(series: pd.Series) -> dict[str, int]:
    return {str(k): int(v) for k, v in series.value_counts(dropna=False).to_dict().items()}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=json_default), encoding="utf-8")


def normalize_asn(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text.upper() in {"NA", "NAN", "NONE", "NULL"}:
        return ""
    if text.upper().startswith("AS"):
        text = text[2:]
    try:
        return str(int(float(text)))
    except Exception:
        return text


def state_count(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    total = max(len(frame), 1)
    for col in columns:
        if col not in frame.columns:
            continue
        for state, count in frame[col].value_counts(dropna=False).items():
            rows.append(
                {
                    "state_field": col,
                    "state": str(state),
                    "count": int(count),
                    "share": float(count) / total,
                }
            )
    return pd.DataFrame(rows)


def load_s3d_queue(args: argparse.Namespace, warnings: list[str]) -> pd.DataFrame:
    queue_path = Path(args.s3d_output_dir) / "s3d_incident_verification_queue.parquet"
    if not queue_path.exists():
        raise SystemExit(f"required S3-D queue missing: {queue_path}")
    queue = read_parquet_existing(queue_path, QUEUE_COLS)
    if args.sample_rows and not args.full_run:
        queue = queue.head(args.sample_rows).copy()
    for col in [
        "incident_id",
        "original_incident_priority",
        "calibrated_incident_priority",
        "family",
        "dominant_origin_as",
        "dominant_prefix",
        "dominant_path_signature",
        "dominant_triplet_signature",
        "dominant_reason_signature",
        "verification_queue",
        "verification_reason",
        "recommended_next_check",
        "external_evidence_needed",
        "weak_label_candidate",
    ]:
        queue[col] = to_text(queue, col)
    for col in [
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
        "pattern_A_member_count",
        "pattern_A_gate_evidence_count",
        "pattern_A_gate_evidence_ratio",
        "pattern_B_member_count",
        "pattern_B_verification_count",
        "gate_evidence_member_count",
        "gate_evidence_ratio",
        "background_fanout_review_count",
        "low_visibility_review_count",
        "route_leak_like_review_count",
        "verification_priority_score",
        "verification_confidence",
    ]:
        queue[col] = to_number(queue, col)
    queue["pattern_B_protected_flag"] = to_bool(queue, "pattern_B_protected_flag")
    warnings.append("S3-D queue is consumed as verifier input planning data, not truth labels.")
    return queue


def optional_enrich_tickets(frame: pd.DataFrame, args: argparse.Namespace, warnings: list[str]) -> pd.DataFrame:
    ticket_path = Path("data") / "runs" / args.run_id / "incidents" / "incident_tickets.parquet"
    if not ticket_path.exists():
        warnings.append(f"required incident_tickets parquet missing for enrichment: {ticket_path}")
        return frame
    tickets = read_parquet_existing(ticket_path, TICKET_COLS)
    tickets["incident_id"] = to_text(tickets, "incident_id")
    for col in ["run_id", "incident_priority", "label_distribution", "source_layer_distribution", "reason_distribution"]:
        tickets[col] = to_text(tickets, col)
    for col in [
        "incident_start",
        "incident_end",
        "incident_duration_sec",
        "micro_incident_count",
        "mean_certainty_score",
        "mean_conflict_score",
        "mean_evidence_support_score",
        "missing_rate",
    ]:
        tickets[col] = to_number(tickets, col)
    return frame.merge(tickets, on="incident_id", how="left", suffixes=("", "_ticket"))


def check_required_membership(args: argparse.Namespace, warnings: list[str]) -> None:
    membership_path = Path("data") / "runs" / args.run_id / "incidents" / "incident_membership.parquet"
    if not membership_path.exists():
        warnings.append(f"required incident_membership parquet missing: {membership_path}")
    else:
        warnings.append("incident_membership exists; R-2A scaffold uses S3-D incident-level fields for smoke output.")


def optional_enrich_s3d2(frame: pd.DataFrame, args: argparse.Namespace, warnings: list[str]) -> pd.DataFrame:
    if not args.s3d2_output_dir:
        warnings.append("S3-D2 output dir not provided; external evidence fields fall back to unavailable.")
        return frame
    evidence_path = Path(args.s3d2_output_dir) / "s3d2_incident_evidence_table.parquet"
    if not evidence_path.exists():
        warnings.append(f"S3-D2 evidence table missing: {evidence_path}")
        return frame
    evidence = read_parquet_existing(evidence_path, S3D2_COLS)
    evidence["incident_id"] = to_text(evidence, "incident_id")
    wanted = set(frame["incident_id"])
    evidence = evidence[evidence["incident_id"].isin(wanted)].copy()
    for col in [
        "rpki_status",
        "rpki_evidence_strength",
        "rpki_evidence_note",
        "path_relation_evidence_strength",
        "path_relation_note",
        "known_event_match_status",
        "known_event_id",
        "known_event_note",
        "verification_evidence_bucket",
        "verification_status_candidate",
        "evidence_source_flags",
    ]:
        evidence[col] = to_text(evidence, col)
    for col in [
        "rel_unknown_cnt",
        "rel_unknown_ratio",
        "path_relation_risk_score",
        "known_event_match_strength",
        "verification_evidence_score",
    ]:
        evidence[col] = to_number(evidence, col)
    for col in ["rel_seq_available", "rel_has_unknown", "possible_valley_free_violation", "as_rel_snapshot_stale"]:
        evidence[col] = to_bool(evidence, col)
    warnings.append("S3-D2 evidence fields are reused as attached evidence candidates, not final verification results.")
    return frame.merge(evidence, on="incident_id", how="left", suffixes=("", "_s3d2"))


def discover_cache(args: argparse.Namespace, attr: str, fallback_name: str | None = None) -> Path | None:
    explicit = getattr(args, attr)
    if explicit:
        path = Path(explicit)
        return path if path.exists() else None
    if args.evidence_cache_dir and fallback_name:
        path = Path(args.evidence_cache_dir) / fallback_name
        return path if path.exists() else None
    return None


def build_monitor_evidence(frame: pd.DataFrame) -> pd.DataFrame:
    reason = to_text(frame, "dominant_reason_signature")
    queue = to_text(frame, "verification_queue")
    family = to_text(frame, "family")
    high_count = to_number(frame, "high_count")
    needs_count = to_number(frame, "needs_count")
    gate_ratio = to_number(frame, "gate_evidence_ratio")
    pattern_a_ratio = to_number(frame, "pattern_A_gate_evidence_ratio")

    poison_reason = (
        reason.str.contains("single_collector_visibility", regex=False, na=False)
        | reason.str.contains("unusually_low_visibility", regex=False, na=False)
        | reason.str.contains("unusually_short_duration", regex=False, na=False)
        | reason.str.contains("sparse_short_lived_event", regex=False, na=False)
    )
    poison = (gate_ratio >= 0.50) | (pattern_a_ratio >= 0.50) | poison_reason
    aligned_weak = (
        queue.isin(["high_confidence_candidate", "patternB_path_abnormal_verification", "route_leak_like_review"])
        & (high_count > 0)
    )
    has_monitor = (high_count + needs_count) > 0

    frame["monitor_evidence_state"] = np.select(
        [poison, aligned_weak, has_monitor],
        ["poisoning_susceptible", "aligned_weak", "monitor_only"],
        default="unavailable",
    )
    frame["monitor_evidence_note"] = np.select(
        [poison, aligned_weak, has_monitor],
        [
            "legacy monitor evidence is poisoning-susceptible due to low visibility/gate evidence/path novelty",
            "legacy monitor evidence is useful but weak; public monitor output remains trigger-only",
            "legacy monitor evidence exists but has no independent external support",
        ],
        default="monitor evidence unavailable",
    )
    frame["monitor_confidence_cap"] = np.select(
        [poison, aligned_weak, has_monitor],
        [0.45, 0.50, 0.45],
        default=0.45,
    ).astype(float)
    family_route = family.str.contains("route_leak", regex=False, na=False)
    frame["monitor_family_note"] = np.where(family_route, "route_leak_like monitor trigger", "forged_origin_like/other monitor trigger")
    return frame


def build_rpki_evidence(frame: pd.DataFrame, args: argparse.Namespace, warnings: list[str]) -> pd.DataFrame:
    cache = discover_cache(args, "rpki_vrp_cache", "rpki/normalized_vrp_2024-04-16.parquet")
    frame["rpki_source_path"] = str(cache) if cache else ""
    frame["rpki_cache_aligned"] = False
    if cache is None:
        frame["rpki_status"] = "unavailable"
        frame["rpki_evidence_state"] = "unavailable"
        frame["rpki_evidence_note"] = "historical_rpki_cache_unavailable"
        frame["rpki_confidence_cap"] = 0.45
        warnings.append("RPKI cache unavailable; rpki_evidence_state=unavailable for all processed incidents.")
        return frame

    try:
        vrp = pd.read_parquet(cache)
    except Exception as exc:
        frame["rpki_status"] = "unavailable"
        frame["rpki_evidence_state"] = "unavailable"
        frame["rpki_evidence_note"] = f"rpki_cache_read_failed:{exc}"
        frame["rpki_confidence_cap"] = 0.45
        warnings.append(f"RPKI cache read failed: {cache}: {exc}")
        return frame

    prefix_col = next((c for c in ["prefix", "roa_prefix", "vrp_prefix"] if c in vrp.columns), None)
    asn_col = next((c for c in ["asn", "origin_as", "origin_asn", "origin", "asID"] if c in vrp.columns), None)
    maxlen_col = next((c for c in ["max_length", "maxlen", "maxLength"] if c in vrp.columns), None)
    if prefix_col is None or asn_col is None:
        frame["rpki_status"] = "unavailable"
        frame["rpki_evidence_state"] = "unavailable"
        frame["rpki_evidence_note"] = "rpki_cache_missing_required_prefix_or_asn_columns"
        frame["rpki_confidence_cap"] = 0.45
        warnings.append(f"RPKI cache lacks required prefix/asn columns: {cache}")
        return frame

    vrp = vrp[[c for c in [prefix_col, asn_col, maxlen_col] if c]].copy()
    vrp["lookup_prefix"] = vrp[prefix_col].fillna("").astype(str)
    vrp["lookup_asn"] = vrp[asn_col].map(normalize_asn)
    if maxlen_col:
        vrp["max_length_norm"] = pd.to_numeric(vrp[maxlen_col], errors="coerce")
    else:
        vrp["max_length_norm"] = np.nan
    grouped = vrp.groupby("lookup_prefix", dropna=False).agg(
        rpki_allowed_asns=("lookup_asn", lambda values: set(v for v in values if v)),
        rpki_max_length=("max_length_norm", "max"),
    )

    prefixes = to_text(frame, "dominant_prefix")
    origins = to_text(frame, "dominant_origin_as").map(normalize_asn)
    statuses: list[str] = []
    for prefix, origin in zip(prefixes, origins):
        if not prefix or not origin or prefix.upper() == "NA":
            statuses.append("unknown")
            continue
        if prefix not in grouped.index:
            statuses.append("unknown")
            continue
        allowed = grouped.at[prefix, "rpki_allowed_asns"]
        if origin in allowed:
            statuses.append("valid")
        elif allowed:
            statuses.append("invalid_asn")
        else:
            statuses.append("unknown")
    frame["rpki_status"] = statuses
    frame["rpki_evidence_state"] = np.select(
        [
            frame["rpki_status"].isin(["valid", "invalid_asn", "invalid_length", "invalid"]),
            frame["rpki_status"].eq("unknown"),
        ],
        ["aligned_medium", "aligned_weak"],
        default="unavailable",
    )
    frame["rpki_evidence_note"] = np.select(
        [
            frame["rpki_status"].eq("valid"),
            frame["rpki_status"].isin(["invalid_asn", "invalid_length", "invalid"]),
            frame["rpki_status"].eq("unknown"),
        ],
        [
            "RPKI origin evidence is valid but does not imply benign",
            "RPKI origin anomaly supports suspicion but is not confirmed attack",
            "RPKI lookup returned unknown; not benign",
        ],
        default="RPKI unavailable",
    )
    frame["rpki_cache_aligned"] = True
    frame["rpki_confidence_cap"] = np.where(frame["rpki_evidence_state"].eq("aligned_medium"), 0.75, 0.50)
    warnings.append(f"RPKI cache used with exact-prefix scaffold lookup only: {cache}")
    return frame


def build_irr_evidence(frame: pd.DataFrame, args: argparse.Namespace, warnings: list[str]) -> pd.DataFrame:
    cache = discover_cache(args, "irr_cache", "irr/irr_route_objects_2024-04-16.parquet")
    if cache is None:
        frame["irr_status"] = "unavailable"
        frame["irr_evidence_state"] = "unavailable"
        frame["irr_evidence_note"] = "historical_irr_cache_unavailable"
        warnings.append("IRR cache unavailable; irr_evidence_state=unavailable.")
        return frame
    try:
        irr = pd.read_parquet(cache)
    except Exception as exc:
        frame["irr_status"] = "unavailable"
        frame["irr_evidence_state"] = "unavailable"
        frame["irr_evidence_note"] = f"irr_cache_read_failed:{exc}"
        warnings.append(f"IRR cache read failed: {cache}: {exc}")
        return frame

    prefix_col = next((c for c in ["prefix", "route", "route6"] if c in irr.columns), None)
    asn_col = next((c for c in ["origin_as", "origin", "asn", "origin_asn"] if c in irr.columns), None)
    if prefix_col is None or asn_col is None:
        frame["irr_status"] = "unavailable"
        frame["irr_evidence_state"] = "unavailable"
        frame["irr_evidence_note"] = "irr_cache_missing_required_prefix_or_origin_columns"
        warnings.append(f"IRR cache lacks required prefix/origin columns: {cache}")
        return frame
    irr_lookup = set(zip(irr[prefix_col].fillna("").astype(str), irr[asn_col].map(normalize_asn)))
    prefixes = to_text(frame, "dominant_prefix")
    origins = to_text(frame, "dominant_origin_as").map(normalize_asn)
    match = [bool(prefix and origin and (prefix, origin) in irr_lookup) for prefix, origin in zip(prefixes, origins)]
    frame["irr_status"] = np.where(match, "route_object_match", "no_route_object")
    frame["irr_evidence_state"] = np.where(match, "aligned_medium", "aligned_weak")
    frame["irr_evidence_note"] = np.where(
        match,
        "IRR route object matched prefix-origin, auxiliary only",
        "no aligned IRR route object found; not benign",
    )
    warnings.append(f"IRR cache used with exact-prefix scaffold lookup only: {cache}")
    return frame


def build_path_legality_evidence(frame: pd.DataFrame, args: argparse.Namespace, warnings: list[str]) -> pd.DataFrame:
    aligned_as_rel = discover_cache(args, "as_rel_cache", "as_relationships/as_rel_normalized_2024.parquet")
    legacy_as_rel = Path(args.legacy_as_rel_file) if args.legacy_as_rel_file else None
    legacy_exists = bool(legacy_as_rel and legacy_as_rel.exists())
    aligned_exists = bool(aligned_as_rel)
    if aligned_exists:
        relation_source = str(aligned_as_rel)
        relation_snapshot_date = args.run_date
        relation_is_stale = False
        warnings.append(f"Aligned AS relationship cache supplied: {aligned_as_rel}. R-2A still uses scaffold path-legality rules.")
    elif legacy_exists:
        relation_source = str(legacy_as_rel)
        relation_snapshot_date = "2017-07-01"
        relation_is_stale = True
        warnings.append("Legacy 2017 CAIDA AS-rel file supplied; it is stale_diagnostic only for 2024 incidents.")
    else:
        relation_source = ""
        relation_snapshot_date = ""
        relation_is_stale = False
        warnings.append("No aligned AS-rel/ASPA/Roles cache supplied; path legality evidence falls back to unavailable/not_applicable.")

    queue = to_text(frame, "verification_queue")
    family = to_text(frame, "family")
    path = to_text(frame, "dominant_path_signature")
    triplet = to_text(frame, "dominant_triplet_signature")
    reason = to_text(frame, "dominant_reason_signature")
    has_path = path.str.strip().ne("") & ~path.str.upper().isin(["NA", "NAN", "NONE", "NULL"])
    has_triplet = triplet.str.strip().ne("") & ~triplet.str.upper().isin(["NA", "NAN", "NONE", "NULL"])
    path_relevant = (
        queue.isin(["patternB_path_abnormal_verification", "route_leak_like_review"])
        | family.str.contains("route_leak", regex=False, na=False)
        | reason.str.contains("abnormal_path_length_for_prefix_origin", regex=False, na=False)
    )
    route_leak_like = queue.eq("route_leak_like_review") | family.str.contains("route_leak", regex=False, na=False)
    pattern_b = queue.eq("patternB_path_abnormal_verification") | (to_number(frame, "pattern_B_member_count") > 0)

    if aligned_exists:
        state = np.select(
            [path_relevant & (has_path | has_triplet), ~path_relevant],
            ["aligned_medium", "not_applicable"],
            default="unavailable",
        )
        note = np.select(
            [path_relevant & (has_path | has_triplet), ~path_relevant],
            [
                "aligned path relation cache exists; R-2A scaffold marks path legality as aligned_medium pending full legality check",
                "path legality not central for this incident",
            ],
            default="path/triplet missing for path-relevant incident",
        )
    elif legacy_exists:
        state = np.select(
            [path_relevant & (has_path | has_triplet), ~path_relevant],
            ["stale_diagnostic", "not_applicable"],
            default="unavailable",
        )
        note = np.select(
            [path_relevant & (has_path | has_triplet), ~path_relevant],
            [
                "only stale 2017 AS-rel evidence is available; diagnostic only",
                "path legality not central for this incident",
            ],
            default="path/triplet missing and only stale relation source available",
        )
    else:
        state = np.select(
            [path_relevant & (has_path | has_triplet), ~path_relevant],
            ["unavailable", "not_applicable"],
            default="unavailable",
        )
        note = np.select(
            [path_relevant & (has_path | has_triplet), ~path_relevant],
            [
                "path/triplet exists but no aligned relation source is available",
                "path legality not central for this incident",
            ],
            default="path/triplet and relation source unavailable",
        )

    frame["path_legality_state"] = state
    frame["path_legality_note"] = note
    frame["representative_path_or_triplet"] = np.where(has_triplet, triplet, path)
    frame["relation_source"] = relation_source
    frame["relation_snapshot_date"] = relation_snapshot_date
    frame["relation_is_stale"] = relation_is_stale
    if "rel_unknown_ratio" not in frame.columns:
        frame["rel_unknown_ratio"] = 1.0 if not aligned_exists else 0.0
    else:
        frame["rel_unknown_ratio"] = to_number(frame, "rel_unknown_ratio", 1.0)
    frame["possible_route_leak_flag"] = route_leak_like
    frame["possible_path_manipulation_flag"] = pattern_b | reason.str.contains("abnormal_path_length", regex=False, na=False)
    frame["path_confidence_cap"] = np.select(
        [frame["path_legality_state"].eq("aligned_medium"), frame["path_legality_state"].eq("stale_diagnostic")],
        [0.75, 0.40],
        default=0.45,
    ).astype(float)
    return frame


def build_known_event_state(frame: pd.DataFrame, args: argparse.Namespace, warnings: list[str]) -> pd.DataFrame:
    file_path = Path(args.known_event_file) if args.known_event_file else None
    has_file = bool(file_path and file_path.exists())
    status = to_text(frame, "known_event_match_status", "unavailable")
    if not has_file and "known_event_match_status" not in frame.columns:
        frame["known_event_evidence_state"] = "unavailable"
        frame["known_event_evidence_note"] = "known_event_file_unavailable"
        warnings.append("known-event file unavailable; known_event_evidence_state=unavailable.")
        return frame
    if not has_file:
        warnings.append("S3-D2 known-event fields reused, but known-event inventory file was not provided for R-2A.")
    lower = status.str.lower()
    frame["known_event_evidence_state"] = np.select(
        [
            lower.str.contains("time_aligned", regex=False, na=False) | lower.str.contains("match", regex=False, na=False) & ~lower.str.contains("no_match", regex=False, na=False),
            lower.str.contains("out_of_window", regex=False, na=False),
            lower.str.contains("no_match", regex=False, na=False),
        ],
        ["aligned_medium", "stale_diagnostic", "unavailable"],
        default="unavailable",
    )
    frame["known_event_evidence_note"] = np.select(
        [
            frame["known_event_evidence_state"].eq("aligned_medium"),
            frame["known_event_evidence_state"].eq("stale_diagnostic"),
        ],
        ["known-event inventory has a time-aligned candidate match", "known-event overlap is out-of-window diagnostic only"],
        default="no time-aligned known-event support; not benign",
    )
    return frame


def aggregate_states(frame: pd.DataFrame) -> pd.DataFrame:
    state_cols = ["monitor_evidence_state", "rpki_evidence_state", "path_legality_state", "irr_evidence_state", "known_event_evidence_state"]
    for col in state_cols:
        if col not in frame.columns:
            frame[col] = "unavailable"
    external_cols = ["rpki_evidence_state", "path_legality_state", "irr_evidence_state", "known_event_evidence_state"]
    states = frame[state_cols]
    external = frame[external_cols]
    frame["evidence_has_conflict"] = states.eq("conflicting").any(axis=1)
    frame["evidence_has_unavailable"] = external.eq("unavailable").any(axis=1)
    frame["external_aligned_count"] = external.isin(["aligned_medium", "aligned_strong"]).sum(axis=1)
    frame["external_stale_count"] = external.eq("stale_diagnostic").sum(axis=1)
    frame["external_unavailable_count"] = external.eq("unavailable").sum(axis=1)
    frame["evidence_has_stale_only"] = (frame["external_stale_count"] > 0) & (frame["external_aligned_count"] == 0)
    priority = {
        "aligned_strong": 9,
        "aligned_medium": 8,
        "aligned_weak": 7,
        "monitor_only": 6,
        "external_confirmed_pending": 5,
        "poisoning_susceptible": 4,
        "stale_diagnostic": 3,
        "unavailable": 2,
        "not_applicable": 1,
        "conflicting": 0,
    }
    reverse = {v: k for k, v in priority.items()}
    max_score = states.apply(lambda col: col.map(priority).fillna(0)).max(axis=1)
    frame["strongest_evidence_state"] = max_score.map(lambda value: reverse.get(int(value), "unavailable"))
    frame["poisoning_susceptibility_score"] = (
        np.where(frame["monitor_evidence_state"].eq("poisoning_susceptible"), 70.0, 15.0)
        + np.minimum(to_number(frame, "gate_evidence_ratio") * 20.0, 20.0)
        + np.minimum(to_number(frame, "pattern_A_gate_evidence_ratio") * 10.0, 10.0)
    )
    frame["poisoning_susceptibility_score"] = np.clip(frame["poisoning_susceptibility_score"], 0, 100)
    frame["evidence_strength_summary"] = (
        "monitor="
        + frame["monitor_evidence_state"].astype(str)
        + ";rpki="
        + frame["rpki_evidence_state"].astype(str)
        + ";path="
        + frame["path_legality_state"].astype(str)
        + ";irr="
        + frame["irr_evidence_state"].astype(str)
        + ";known="
        + frame["known_event_evidence_state"].astype(str)
    )
    return frame


def assign_verdicts(frame: pd.DataFrame) -> pd.DataFrame:
    queue = to_text(frame, "verification_queue")
    monitor_present = frame["monitor_evidence_state"].isin(["monitor_only", "aligned_weak", "poisoning_susceptible"])
    background = queue.isin(["background_like_review", "low_priority_background"]) & (to_number(frame, "high_share") <= 0.05)
    stale_path_relevant = frame["path_legality_state"].eq("stale_diagnostic") & (
        queue.isin(["patternB_path_abnormal_verification", "route_leak_like_review"]) | to_number(frame, "pattern_B_member_count").gt(0)
    )
    all_core_unavailable = (
        frame["rpki_evidence_state"].eq("unavailable")
        & frame["irr_evidence_state"].eq("unavailable")
        & frame["known_event_evidence_state"].eq("unavailable")
        & frame["path_legality_state"].isin(["unavailable", "not_applicable"])
    )
    evidence_supported = monitor_present & (frame["external_aligned_count"] >= 1) & ~frame["evidence_has_conflict"]
    strong_supported = (
        monitor_present
        & (frame["external_aligned_count"] >= 2)
        & ~frame["evidence_has_conflict"]
        & ~frame["evidence_has_stale_only"]
        & ~frame["rpki_status"].isin(["invalid_asn", "invalid_length", "invalid"])
    )
    no_monitor_no_external = frame["monitor_evidence_state"].eq("unavailable") & (frame["external_aligned_count"] == 0)

    frame["verifier_verdict"] = np.select(
        [
            frame["evidence_has_conflict"],
            strong_supported,
            evidence_supported,
            background,
            stale_path_relevant,
            monitor_present & all_core_unavailable,
            monitor_present,
            no_monitor_no_external,
        ],
        [
            "evidence_conflict",
            "strongly_supported_suspicious",
            "evidence_supported_suspicious",
            "background_like_but_unconfirmed",
            "stale_evidence_only",
            "external_evidence_unavailable",
            "evidence_insufficient",
            "abstain",
        ],
        default="abstain",
    )
    frame["confidence_cap"] = np.select(
        [
            frame["verifier_verdict"].eq("evidence_conflict"),
            frame["verifier_verdict"].eq("strongly_supported_suspicious"),
            frame["verifier_verdict"].eq("evidence_supported_suspicious"),
            frame["verifier_verdict"].eq("background_like_but_unconfirmed"),
            frame["verifier_verdict"].eq("stale_evidence_only"),
            frame["verifier_verdict"].eq("external_evidence_unavailable"),
            frame["verifier_verdict"].eq("evidence_insufficient"),
        ],
        [0.55, 0.90, 0.75, 0.45, 0.40, 0.45, 0.50],
        default=0.55,
    ).astype(float)
    no_aligned_external = frame["external_aligned_count"] == 0
    poison_without_support = frame["monitor_evidence_state"].eq("poisoning_susceptible") & no_aligned_external
    frame.loc[poison_without_support, "confidence_cap"] = np.minimum(frame.loc[poison_without_support, "confidence_cap"], 0.45)

    frame["confidence_cap_reason"] = np.select(
        [
            frame["verifier_verdict"].eq("evidence_conflict"),
            frame["verifier_verdict"].eq("strongly_supported_suspicious"),
            frame["verifier_verdict"].eq("evidence_supported_suspicious"),
            frame["verifier_verdict"].eq("background_like_but_unconfirmed"),
            frame["verifier_verdict"].eq("stale_evidence_only"),
            frame["verifier_verdict"].eq("external_evidence_unavailable"),
            poison_without_support,
            frame["verifier_verdict"].eq("evidence_insufficient"),
        ],
        [
            "conflicting evidence cannot produce suspicious verdict",
            "multiple aligned external evidence sources with no conflict",
            "aligned external evidence supports suspicion but is not confirmed truth",
            "background-like without external confirmation",
            "stale diagnostic evidence only",
            "core external evidence unavailable",
            "poisoning-susceptible monitor evidence without independent support",
            "insufficient external evidence",
        ],
        default="abstain_or_unresolved",
    )
    frame["abstain_reason"] = np.where(
        frame["verifier_verdict"].eq("abstain"),
        "state machine cannot safely produce a supported verdict",
        "",
    )
    frame["conflict_reason"] = np.where(
        frame["verifier_verdict"].eq("evidence_conflict"),
        "one or more evidence states are conflicting",
        "",
    )
    frame["learning_eligibility"] = np.select(
        [
            frame["verifier_verdict"].isin(["strongly_supported_suspicious", "evidence_supported_suspicious"]),
            frame["verifier_verdict"].eq("evidence_conflict"),
            frame["verifier_verdict"].eq("abstain"),
            frame["verifier_verdict"].isin(["background_like_but_unconfirmed", "external_evidence_unavailable", "evidence_insufficient"]),
            frame["verifier_verdict"].eq("stale_evidence_only"),
        ],
        ["positive_candidate", "conflict_class", "abstain_class", "ranking_only", "ranking_only"],
        default="no",
    )
    frame["verifier_confidence"] = np.minimum(frame["confidence_cap"], to_number(frame, "incident_confidence", 0.0)).round(4)
    frame["verifier_reason_v0"] = np.select(
        [
            frame["verifier_verdict"].eq("strongly_supported_suspicious"),
            frame["verifier_verdict"].eq("evidence_supported_suspicious"),
            frame["verifier_verdict"].eq("evidence_conflict"),
            frame["verifier_verdict"].eq("background_like_but_unconfirmed"),
            frame["verifier_verdict"].eq("stale_evidence_only"),
            frame["verifier_verdict"].eq("external_evidence_unavailable"),
            frame["verifier_verdict"].eq("evidence_insufficient"),
        ],
        [
            "R-2A found multiple aligned external evidence sources without key conflict.",
            "R-2A found aligned external evidence support, but not confirmed truth.",
            "R-2A preserved evidence conflict as required by R-1.",
            "R-2A marked broad/low-support incident as background-like but unconfirmed.",
            "R-2A found stale diagnostic evidence only.",
            "R-2A found monitor trigger but core external evidence unavailable.",
            "R-2A found monitor signal but insufficient aligned external evidence.",
        ],
        default="R-2A abstained because evidence could not safely support another verdict.",
    )
    return frame


def validate_enums(frame: pd.DataFrame) -> None:
    bad_verdicts = set(frame["verifier_verdict"].dropna().astype(str)) - R1_VERDICTS
    if bad_verdicts:
        raise SystemExit(f"non-R1 verifier verdicts produced: {sorted(bad_verdicts)}")
    for col in ["monitor_evidence_state", "rpki_evidence_state", "path_legality_state", "irr_evidence_state", "known_event_evidence_state", "strongest_evidence_state"]:
        bad_states = set(frame[col].dropna().astype(str)) - R1_EVIDENCE_STATES
        if bad_states:
            raise SystemExit(f"non-R1 evidence states in {col}: {sorted(bad_states)}")
    bad_learning = set(frame["learning_eligibility"].dropna().astype(str)) - LEARNING_ELIGIBILITY
    if bad_learning:
        raise SystemExit(f"unexpected learning eligibility values: {sorted(bad_learning)}")


def provenance_json(row: pd.Series) -> str:
    payload = {
        "monitor": {
            "state": row.get("monitor_evidence_state", "unavailable"),
            "note": row.get("monitor_evidence_note", ""),
        },
        "rpki": {
            "state": row.get("rpki_evidence_state", "unavailable"),
            "status": row.get("rpki_status", "unavailable"),
            "source": row.get("rpki_source_path", ""),
            "cache_aligned": bool(row.get("rpki_cache_aligned", False)),
        },
        "path_legality": {
            "state": row.get("path_legality_state", "unavailable"),
            "source": row.get("relation_source", ""),
            "snapshot_date": row.get("relation_snapshot_date", ""),
            "stale": bool(row.get("relation_is_stale", False)),
        },
        "irr": {
            "state": row.get("irr_evidence_state", "unavailable"),
            "status": row.get("irr_status", "unavailable"),
        },
        "known_event": {
            "state": row.get("known_event_evidence_state", "unavailable"),
            "status": row.get("known_event_match_status", "unavailable"),
        },
    }
    return json.dumps(payload, sort_keys=True, default=json_default)


def write_outputs(frame: pd.DataFrame, args: argparse.Namespace, warnings: list[str]) -> dict[str, Any]:
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    frame = frame.copy()
    frame["evidence_provenance_json"] = frame.apply(provenance_json, axis=1)

    output_cols = [
        "incident_id",
        "run_id",
        "family",
        "verification_queue",
        "original_incident_priority",
        "calibrated_incident_priority",
        "member_count",
        "high_count",
        "needs_count",
        "high_share",
        "needs_share",
        "dominant_prefix",
        "dominant_origin_as",
        "dominant_path_signature",
        "dominant_triplet_signature",
        "dominant_reason_signature",
        "monitor_evidence_state",
        "monitor_evidence_note",
        "rpki_status",
        "rpki_evidence_state",
        "rpki_evidence_note",
        "rpki_source_path",
        "rpki_cache_aligned",
        "path_legality_state",
        "path_legality_note",
        "representative_path_or_triplet",
        "relation_source",
        "relation_snapshot_date",
        "relation_is_stale",
        "rel_unknown_ratio",
        "possible_route_leak_flag",
        "possible_path_manipulation_flag",
        "irr_status",
        "irr_evidence_state",
        "irr_evidence_note",
        "known_event_evidence_state",
        "known_event_evidence_note",
        "evidence_strength_summary",
        "strongest_evidence_state",
        "evidence_has_conflict",
        "evidence_has_unavailable",
        "evidence_has_stale_only",
        "external_aligned_count",
        "poisoning_susceptibility_score",
        "verifier_verdict",
        "verifier_confidence",
        "confidence_cap",
        "confidence_cap_reason",
        "abstain_reason",
        "conflict_reason",
        "verifier_reason_v0",
        "learning_eligibility",
        "evidence_provenance_json",
    ]
    output_cols = [col for col in output_cols if col in frame.columns]
    output = frame[output_cols].copy()
    output.to_parquet(out / "r2a_incident_verifier_table.parquet", index=False)
    output.to_csv(out / "r2a_incident_verifier_table.csv", index=False)

    verdict_dist = (
        output["verifier_verdict"].value_counts(dropna=False).rename_axis("verifier_verdict").reset_index(name="count")
    )
    verdict_dist["share"] = verdict_dist["count"] / max(len(output), 1)
    verdict_dist.to_csv(out / "r2a_verdict_distribution.csv", index=False)

    evidence_dist = state_count(
        output,
        [
            "monitor_evidence_state",
            "rpki_evidence_state",
            "path_legality_state",
            "irr_evidence_state",
            "known_event_evidence_state",
            "strongest_evidence_state",
        ],
    )
    evidence_dist.to_csv(out / "r2a_evidence_state_distribution.csv", index=False)

    cap_dist = output.groupby("confidence_cap_reason", dropna=False).agg(
        count=("incident_id", "size"),
        min_cap=("confidence_cap", "min"),
        max_cap=("confidence_cap", "max"),
        mean_cap=("confidence_cap", "mean"),
    ).reset_index()
    cap_dist.to_csv(out / "r2a_confidence_cap_distribution.csv", index=False)

    def top_cases(verdict: str, filename: str) -> None:
        cols = [
            "incident_id",
            "verification_queue",
            "family",
            "calibrated_incident_priority",
            "member_count",
            "high_count",
            "needs_count",
            "dominant_prefix",
            "dominant_origin_as",
            "verifier_verdict",
            "confidence_cap",
            "confidence_cap_reason",
            "evidence_strength_summary",
            "verifier_reason_v0",
        ]
        subset = output[output["verifier_verdict"].eq(verdict)].head(200)
        subset[[c for c in cols if c in subset.columns]].to_csv(out / filename, index=False)

    top_cases("abstain", "r2a_abstain_cases.csv")
    top_cases("evidence_conflict", "r2a_conflict_cases.csv")
    top_cases("external_evidence_unavailable", "r2a_external_unavailable_cases.csv")

    route_pattern = output[
        output["verification_queue"].isin(["patternB_path_abnormal_verification", "route_leak_like_review"])
        | output["family"].fillna("").astype(str).str.contains("route_leak", regex=False, na=False)
        | output["possible_path_manipulation_flag"].fillna(False)
    ].head(500)
    route_pattern.to_csv(out / "r2a_route_leak_patternB_candidates.csv", index=False)

    state_distribution = {
        field: count_dict(output[field])
        for field in [
            "monitor_evidence_state",
            "rpki_evidence_state",
            "path_legality_state",
            "irr_evidence_state",
            "known_event_evidence_state",
            "strongest_evidence_state",
        ]
        if field in output.columns
    }
    summary = {
        "run_id": args.run_id,
        "mode": "full" if args.full_run else "smoke",
        "sample_rows": int(args.sample_rows or 0),
        "input_incidents": int(len(frame)),
        "processed_incidents": int(len(output)),
        "verifier_verdict_distribution": count_dict(output["verifier_verdict"]),
        "evidence_state_distribution": state_distribution,
        "rpki_status_distribution": count_dict(output["rpki_status"]),
        "path_legality_state_distribution": count_dict(output["path_legality_state"]),
        "stale_evidence_count": int(output[["rpki_evidence_state", "path_legality_state", "irr_evidence_state", "known_event_evidence_state"]].eq("stale_diagnostic").any(axis=1).sum()),
        "unavailable_evidence_count": int(output[["rpki_evidence_state", "path_legality_state", "irr_evidence_state", "known_event_evidence_state"]].eq("unavailable").any(axis=1).sum()),
        "conflict_count": int(output["verifier_verdict"].eq("evidence_conflict").sum()),
        "abstain_count": int(output["verifier_verdict"].eq("abstain").sum()),
        "evidence_supported_suspicious_count": int(output["verifier_verdict"].eq("evidence_supported_suspicious").sum()),
        "strongly_supported_suspicious_count": int(output["verifier_verdict"].eq("strongly_supported_suspicious").sum()),
        "background_like_but_unconfirmed_count": int(output["verifier_verdict"].eq("background_like_but_unconfirmed").sum()),
        "learning_eligibility_distribution": count_dict(output["learning_eligibility"]),
        "warnings": warnings,
        "status": "completed",
    }
    write_json(out / "r2a_summary.json", summary)
    (out / "r2a_report.md").write_text(render_report(summary, verdict_dist, evidence_dist, args), encoding="utf-8")
    return summary


def render_report(summary: dict[str, Any], verdict_dist: pd.DataFrame, evidence_dist: pd.DataFrame, args: argparse.Namespace) -> str:
    verdict_lines = "\n".join(
        f"- `{row.verifier_verdict}`: {int(row.count)} ({float(row.share):.4f})" for row in verdict_dist.itertuples(index=False)
    )
    path_counts = summary.get("path_legality_state_distribution", {})
    rpki_counts = summary.get("rpki_status_distribution", {})
    warnings = summary.get("warnings", [])
    warning_lines = "\n".join(f"- {warning}" for warning in warnings) if warnings else "- <none>"
    strong_count = summary.get("strongly_supported_suspicious_count", 0)
    return f"""# R-2A Legality-First Verifier Scaffold Report

Run ID: `{summary['run_id']}`
Mode: `{summary['mode']}`
Output directory: `{args.output_dir}`

## 1. Did R-2A convert legacy incidents into a verifier table?

Yes. R-2A processed `{summary['processed_incidents']}` incident rows and wrote an incident-level verifier table with evidence states, R-1 verdict candidates, confidence caps, abstain/conflict reasons, and provenance JSON.

## 2. Did this modify legacy high/needs/low or P1/P2/P3?

No. R-2A only reads legacy/S3 incident artifacts and writes a new verifier scaffold output. It does not overwrite score, gate, final alerts, incident tickets, or S3-D queues.

## 3. Did this complete real attack judgment?

No. This is a legality-first verifier scaffold. Verdicts are verifier candidates under partial evidence, not confirmed attack or confirmed benign labels.

## 4. RPKI coverage

RPKI status distribution:

```json
{json.dumps(rpki_counts, indent=2, sort_keys=True)}
```

Missing RPKI cache is handled as `rpki_evidence_state=unavailable`; it is not treated as benign.

## 5. Path legality coverage

Path legality state distribution:

```json
{json.dumps(path_counts, indent=2, sort_keys=True)}
```

Stale relation evidence is kept as `stale_diagnostic`; unavailable relation evidence is explicit. Neither can produce a strong verdict.

## 6. Verdict distribution

{verdict_lines}

## 7. Is evidence_supported_suspicious backed by aligned external evidence?

The scaffold only assigns `evidence_supported_suspicious` when monitor-side evidence is paired with at least one aligned external evidence state and there is no conflict. In this run, count = `{summary['evidence_supported_suspicious_count']}`.

## 8. Strongly supported suspicious

`strongly_supported_suspicious` count = `{strong_count}`.

If this count is nonzero, the script requires at least two aligned external evidence sources, no conflict, no stale-only path, and no RPKI-invalid-only trigger. A count of zero is acceptable for R-2A, especially when aligned RPKI/ASPA/AS-rel caches are missing.

## 9. Unavailable / stale / conflict / abstain scale

- stale evidence rows: `{summary['stale_evidence_count']}`
- unavailable evidence rows: `{summary['unavailable_evidence_count']}`
- conflict rows: `{summary['conflict_count']}`
- abstain rows: `{summary['abstain_count']}`

These are explicit verifier outcomes/conditions, not hidden failures.

## 10. Candidates for R-2B or R-3

Incidents in `patternB_path_abnormal_verification` and `route_leak_like_review` are written to `r2a_route_leak_patternB_candidates.csv`. They are the most natural bridge to R-2B legality refinement and later R-3 poisoning/evasion tests.

## 11. Why not enter learning layer now?

Current outputs are verifier candidates, not ground truth. Missing/stale evidence is common, and legacy detector labels are not labels. The learning layer remains postponed until verifier-supported ranking targets or reviewed incident sets exist.

## 12. Next step ordering

Recommended order:
1. R-2B legality-first verifier refinement using aligned path/RPKI/IRR caches when available.
2. Evidence cache completion for `2024-04-16` RPKI/ROA and 2024-near AS relationship data.
3. R-3 poisoning/evasion benchmark after R-2B has stable legality behavior.

## Warnings

{warning_lines}
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="R-2A legality-first verifier scaffold.")
    parser.add_argument("--run-id", default=RUN_ID_DEFAULT)
    parser.add_argument("--output-dir", default=OUTPUT_DIR_DEFAULT)
    parser.add_argument("--sample-rows", type=int, default=0)
    parser.add_argument("--full-run", action="store_true")
    parser.add_argument("--s3d-output-dir", default="outputs/s3d_verification_queue_schema_v01")
    parser.add_argument("--s3d2-output-dir", default="")
    parser.add_argument("--evidence-cache-dir", default="")
    parser.add_argument("--rpki-vrp-cache", default="")
    parser.add_argument("--as-rel-cache", default="")
    parser.add_argument("--irr-cache", default="")
    parser.add_argument("--known-event-file", default="")
    parser.add_argument("--legacy-as-rel-file", default="")
    parser.add_argument("--run-date", default=RUN_DATE_DEFAULT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    warnings: list[str] = []
    frame = load_s3d_queue(args, warnings)
    check_required_membership(args, warnings)
    frame = optional_enrich_tickets(frame, args, warnings)
    frame = optional_enrich_s3d2(frame, args, warnings)
    frame = build_monitor_evidence(frame)
    frame = build_rpki_evidence(frame, args, warnings)
    frame = build_path_legality_evidence(frame, args, warnings)
    frame = build_irr_evidence(frame, args, warnings)
    frame = build_known_event_state(frame, args, warnings)
    frame = aggregate_states(frame)
    frame = assign_verdicts(frame)
    validate_enums(frame)
    summary = write_outputs(frame, args, warnings)
    print(json.dumps(summary, indent=2, sort_keys=True, default=json_default))


if __name__ == "__main__":
    main()
