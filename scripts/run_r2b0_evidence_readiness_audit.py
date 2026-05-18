import argparse
import ipaddress
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


RUN_ID_DEFAULT = "s2a_expanded_v01_pilot_6h_april16"
RUN_DATE_DEFAULT = "2024-04-16"
OUTPUT_DIR_DEFAULT = "outputs/r2b0_evidence_readiness_audit_v01"

R1_SAFETY_NOTES = {
    "rpki_vrp": "RPKI validates prefix-origin authorization only; valid is not benign and invalid is not confirmed attack.",
    "irr_route_object": "IRR match is not ownership truth; IRR miss is not attack evidence.",
    "as_relationship": "AS relationship evidence must be time aligned; stale snapshots are diagnostic only.",
    "aspa": "ASPA can support path legality when aligned, but deployment coverage can be sparse.",
    "bgp_roles_otc": "Roles/OTC can be strong route-leak evidence only when directly observed and time aligned.",
    "peeringdb": "PeeringDB is context evidence, not truth.",
    "known_event": "Known-event/operator evidence can be strong only when time/object aligned.",
    "incident_internal_visibility": "Internal incident visibility is verifier context, not truth.",
    "public_monitor_context": "RIS/RouteViews/public monitor slices are monitor/context evidence, not independent external truth.",
}

READINESS_ORDER = {
    "ready_aligned": 5,
    "present_unverified_schema": 4,
    "ready_stale": 3,
    "unusable": 2,
    "missing": 1,
}

FRESHNESS_LIMIT_DAYS = {
    "rpki_vrp": 1,
    "irr_route_object": 7,
    "as_relationship": 30,
    "aspa": 7,
    "peeringdb": 30,
    "known_event": 0,
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
    "dominant_prefix",
    "dominant_origin_as",
    "dominant_path_signature",
    "dominant_triplet_signature",
    "dominant_reason_signature",
    "label_distribution",
    "source_layer_distribution",
    "reason_distribution",
    "top_prefixes",
    "top_origin_as",
    "explanation",
]


def json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=json_default), encoding="utf-8")


def available_columns(path: Path, requested: list[str]) -> list[str]:
    schema_cols = set(pq.ParquetFile(path).schema_arrow.names)
    return [col for col in requested if col in schema_cols]


def read_parquet_existing(path: Path, requested: list[str]) -> pd.DataFrame:
    cols = available_columns(path, requested)
    if not cols:
        raise ValueError(f"none of requested columns exist in {path}: {requested}")
    return pd.read_parquet(path, columns=cols)


def parquet_schema(path: Path) -> list[str]:
    if not path.exists():
        return []
    return pq.ParquetFile(path).schema_arrow.names


def to_text(series: pd.Series | None, index: pd.Index, default: str = "") -> pd.Series:
    if series is None:
        return pd.Series(default, index=index, dtype="object")
    return series.fillna(default).astype(str)


def to_number(series: pd.Series | None, index: pd.Index, default: float = 0.0) -> pd.Series:
    if series is None:
        return pd.Series(default, index=index, dtype="float64")
    return pd.to_numeric(series, errors="coerce").fillna(default)


def count_dict(series: pd.Series) -> dict[str, int]:
    return {str(k): int(v) for k, v in series.value_counts(dropna=False).to_dict().items()}


def coalesce_text(df: pd.DataFrame, cols: list[str], default: str = "") -> pd.Series:
    out = pd.Series(default, index=df.index, dtype="object")
    for col in cols:
        if col not in df.columns:
            continue
        vals = to_text(df[col], df.index)
        mask = out.astype(str).str.strip().eq("") | out.astype(str).str.upper().isin({"NA", "NAN", "NONE", "NULL"})
        usable = vals.str.strip().ne("") & ~vals.str.upper().isin({"NA", "NAN", "NONE", "NULL"})
        out = out.mask(mask & usable, vals)
    return out.fillna(default).astype(str)


def coalesce_number(df: pd.DataFrame, cols: list[str], default: float = 0.0) -> pd.Series:
    out = pd.Series(np.nan, index=df.index, dtype="float64")
    for col in cols:
        if col not in df.columns:
            continue
        vals = pd.to_numeric(df[col], errors="coerce")
        out = out.where(out.notna(), vals)
    return out.fillna(default)


def normalize_asn(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text.upper() in {"NA", "NAN", "NONE", "NULL"}:
        return ""
    if text.upper().startswith("AS"):
        text = text[2:]
    try:
        number = int(float(text))
    except Exception:
        return text
    if number <= 0:
        return ""
    return str(number)


def is_valid_prefix(value: Any) -> bool:
    text = str(value or "").strip()
    if not text or text.upper() in {"NA", "NAN", "NONE", "NULL"}:
        return False
    try:
        ipaddress.ip_network(text, strict=False)
        return "/" in text
    except Exception:
        return False


def is_valid_time(value: Any) -> bool:
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
        float(value)
        return True
    except Exception:
        return str(value).strip() != ""


def parse_as_path(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text or text.upper() in {"NA", "NAN", "NONE", "NULL"}:
        return []
    return re.findall(r"\d+", text)


def make_pairs(tokens: list[str]) -> str:
    if len(tokens) < 2:
        return ""
    return ";".join(f"{tokens[i]}-{tokens[i + 1]}" for i in range(len(tokens) - 1))


def make_triplets(tokens: list[str]) -> str:
    if len(tokens) < 3:
        return ""
    return ";".join(f"{tokens[i]}-{tokens[i + 1]}-{tokens[i + 2]}" for i in range(len(tokens) - 2))


def infer_snapshot_date(path_text: str) -> date | None:
    text = path_text.replace("\\", "/")
    for pattern in [r"(?<!\d)((?:19|20)\d{2})[-_]?(\d{2})[-_]?(\d{2})(?!\d)", r"(?<!\d)((?:19|20)\d{2})[-_]?(\d{2})(?!\d)"]:
        match = re.search(pattern, text)
        if not match:
            continue
        year = int(match.group(1))
        month = int(match.group(2))
        day = int(match.group(3)) if len(match.groups()) >= 3 and match.group(3) else 1
        try:
            return date(year, month, day)
        except ValueError:
            return None
    return None


def freshness_days(snapshot: date | None, run_date: date) -> int | None:
    if snapshot is None:
        return None
    return abs((run_date - snapshot).days)


def readiness_for(evidence_type: str, exists: bool, snapshot: date | None, run_date: date, note_hint: str = "") -> tuple[str, bool, int | None, str]:
    if not exists:
        return "missing", False, None, "cache path missing"
    days = freshness_days(snapshot, run_date)
    limit = FRESHNESS_LIMIT_DAYS.get(evidence_type)
    if evidence_type == "known_event":
        if snapshot is None:
            return "present_unverified_schema", False, None, "known-event inventory present but not time-alignment verified"
        return "present_unverified_schema", False, days, "known-event inventory requires incident-level time/object matching"
    if snapshot is None:
        return "present_unverified_schema", False, None, "present but snapshot date could not be inferred"
    if limit is not None and days is not None and days <= limit:
        return "ready_aligned", True, days, "snapshot appears aligned to run date"
    if evidence_type == "as_relationship" and "2017" in note_hint:
        return "ready_stale", False, days, "legacy 2017 CAIDA AS-rel is stale diagnostic only for 2024 incidents"
    return "ready_stale", False, days, "snapshot is outside freshness window"


def best_readiness(states: list[str]) -> str:
    if not states:
        return "missing"
    return max(states, key=lambda state: READINESS_ORDER.get(state, 0))


def scan_expected_path(evidence_type: str, expected_path: Path, run_date: date) -> dict[str, Any]:
    exists = expected_path.exists()
    file_count = 0
    latest_file = ""
    latest_date: date | None = None
    if exists and expected_path.is_dir():
        files = [p for p in expected_path.rglob("*") if p.is_file()]
        file_count = len(files)
        dated_files: list[tuple[date, Path]] = []
        for file_path in files:
            inferred = infer_snapshot_date(str(file_path))
            if inferred:
                dated_files.append((inferred, file_path))
        if dated_files:
            latest_date, latest_file_path = max(dated_files, key=lambda item: item[0])
            latest_file = str(latest_file_path)
        elif files:
            latest_file_path = max(files, key=lambda item: item.stat().st_mtime)
            latest_file = str(latest_file_path)
            latest_date = infer_snapshot_date(str(latest_file_path))
    elif exists and expected_path.is_file():
        file_count = 1
        latest_file = str(expected_path)
        latest_date = infer_snapshot_date(str(expected_path))

    note_hint = str(expected_path)
    state, aligned, days, notes = readiness_for(evidence_type, exists, latest_date, run_date, note_hint)
    if exists and expected_path.is_dir() and file_count == 0:
        state = "missing"
        aligned = False
        notes = "cache directory exists but contains no files"
    return {
        "evidence_type": evidence_type,
        "expected_path": str(expected_path),
        "exists": bool(exists),
        "file_count": int(file_count),
        "latest_file": latest_file,
        "inferred_snapshot_date": latest_date.isoformat() if latest_date else "",
        "aligned_to_run_date": bool(aligned),
        "freshness_days": "" if days is None else int(days),
        "usable_for_r2b": bool(aligned or state in {"present_unverified_schema", "ready_stale"}),
        "readiness_state": state,
        "notes": notes,
    }


def load_incidents(args: argparse.Namespace, warnings: list[str]) -> tuple[pd.DataFrame, dict[str, Any]]:
    run_dir = Path("data/runs") / args.run_id
    queue_path = Path(args.s3d_output_dir) / "s3d_incident_verification_queue.parquet"
    tickets_path = run_dir / "incidents" / "incident_tickets.parquet"
    membership_path = run_dir / "incidents" / "incident_membership.parquet"
    if not queue_path.exists():
        raise SystemExit(f"required S3-D queue missing: {queue_path}")
    if not tickets_path.exists():
        raise SystemExit(f"required incident tickets missing: {tickets_path}")
    if not membership_path.exists():
        raise SystemExit(f"required incident membership missing: {membership_path}")

    queue = read_parquet_existing(queue_path, QUEUE_COLS)
    if args.sample_rows and not args.full_run:
        queue = queue.head(args.sample_rows).copy()
    ticket_cols = available_columns(tickets_path, TICKET_COLS)
    tickets = pd.read_parquet(tickets_path, columns=ticket_cols)
    tickets = tickets[tickets["incident_id"].isin(queue["incident_id"])].copy()
    merged = queue.merge(tickets, on="incident_id", how="left", suffixes=("", "_ticket"))

    membership_cols = parquet_schema(membership_path)
    if args.sample_rows and not args.full_run:
        warnings.append("sample mode audits the first S3-D queue incidents only; membership parquet schema was inspected but rows were not joined.")
    else:
        warnings.append("full mode audits incident-level readiness; incident_membership schema was inspected but row-level membership was not re-aggregated.")
    warnings.append("R-2B-0 is readiness audit only; no legacy high/needs/low, P1/P2/P3, or verifier verdict is changed.")

    index = merged.index
    out = pd.DataFrame(index=index)
    out["incident_id"] = coalesce_text(merged, ["incident_id"])
    out["run_id"] = coalesce_text(merged, ["run_id"], args.run_id).replace("", args.run_id)
    out["verification_queue"] = coalesce_text(merged, ["verification_queue"])
    out["legacy_priority"] = coalesce_text(
        merged,
        ["calibrated_incident_priority", "original_incident_priority", "incident_priority", "incident_priority_ticket"],
    )
    out["family"] = coalesce_text(merged, ["family", "family_ticket"])
    out["dominant_prefix"] = coalesce_text(merged, ["dominant_prefix", "dominant_prefix_ticket"])
    out["dominant_origin_as"] = coalesce_text(merged, ["dominant_origin_as", "dominant_origin_as_ticket"]).map(normalize_asn)
    out["dominant_path_signature"] = coalesce_text(merged, ["dominant_path_signature", "dominant_path_signature_ticket"])
    out["dominant_triplet_signature"] = coalesce_text(merged, ["dominant_triplet_signature", "dominant_triplet_signature_ticket"])
    out["dominant_reason_signature"] = coalesce_text(merged, ["dominant_reason_signature", "dominant_reason_signature_ticket"])
    out["incident_start"] = coalesce_number(merged, ["incident_start"])
    out["incident_end"] = coalesce_number(merged, ["incident_end"])
    out["duration_sec"] = coalesce_number(merged, ["incident_duration_sec"])
    out["member_count"] = coalesce_number(merged, ["member_count", "member_count_ticket"])
    out["high_count"] = coalesce_number(merged, ["high_count", "high_count_ticket"])
    out["needs_count"] = coalesce_number(merged, ["needs_count", "needs_count_ticket"])
    out["collector_count"] = coalesce_number(merged, ["collector_count", "collector_union_count", "collector_union_count_ticket"])
    out["collector_union_count"] = coalesce_number(merged, ["collector_union_count", "collector_union_count_ticket"])
    out["affected_prefix_count"] = coalesce_number(merged, ["affected_prefix_count", "affected_prefix_count_ticket"])
    out["origin_as_count"] = coalesce_number(merged, ["origin_as_count", "origin_as_count_ticket"])
    out["gate_evidence_ratio"] = coalesce_number(merged, ["gate_evidence_ratio"])
    out["pattern_A_gate_evidence_ratio"] = coalesce_number(merged, ["pattern_A_gate_evidence_ratio"])
    out["pattern_B_member_count"] = coalesce_number(merged, ["pattern_B_member_count"])

    meta = {
        "queue_path": str(queue_path),
        "tickets_path": str(tickets_path),
        "membership_path": str(membership_path),
        "membership_columns": membership_cols,
        "queue_rows_loaded": int(len(queue)),
        "ticket_rows_matched": int(len(tickets)),
    }
    return out.reset_index(drop=True), meta


def build_key_completeness(incidents: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    frame = incidents.copy()
    frame["has_incident_id"] = frame["incident_id"].astype(str).str.strip().ne("")
    frame["has_run_id"] = frame["run_id"].astype(str).str.strip().ne("")
    frame["has_verification_queue"] = frame["verification_queue"].astype(str).str.strip().ne("")
    frame["has_legacy_priority"] = frame["legacy_priority"].astype(str).str.strip().ne("")
    frame["has_incident_start"] = frame["incident_start"].map(is_valid_time)
    frame["has_incident_end"] = frame["incident_end"].map(is_valid_time)
    frame["has_first_seen_ts"] = frame["has_incident_start"]
    frame["has_last_seen_ts"] = frame["has_incident_end"]
    frame["has_duration_sec"] = frame["duration_sec"].notna() & (frame["duration_sec"] >= 0)
    frame["has_dominant_prefix"] = frame["dominant_prefix"].map(is_valid_prefix)
    frame["has_dominant_origin_as"] = frame["dominant_origin_as"].map(lambda value: normalize_asn(value) != "")
    frame["has_prefix"] = frame["has_dominant_prefix"]
    frame["has_origin_as"] = frame["has_dominant_origin_as"]
    frame["has_prefix_origin_pair"] = frame["has_dominant_prefix"] & frame["has_dominant_origin_as"]
    frame["has_dominant_path_signature"] = frame["dominant_path_signature"].map(lambda value: len(parse_as_path(value)) >= 2)
    frame["has_representative_as_path"] = frame["has_dominant_path_signature"]
    frame["has_as_path"] = frame["has_dominant_path_signature"]
    frame["has_path_len"] = frame["dominant_path_signature"].map(lambda value: len(parse_as_path(value)) >= 1)
    frame["path_len"] = frame["dominant_path_signature"].map(lambda value: len(parse_as_path(value)))
    frame["has_dominant_triplet_signature"] = frame["dominant_triplet_signature"].map(lambda value: len(parse_as_path(value)) >= 3)
    frame["has_collector_count"] = frame["collector_count"].notna() & (frame["collector_count"] > 0)
    frame["has_collectors"] = frame["has_collector_count"]
    frame["has_vp_count"] = frame["has_collector_count"]
    frame["has_member_count"] = frame["member_count"].notna() & (frame["member_count"] > 0)
    frame["has_high_count"] = frame["high_count"].notna()
    frame["has_needs_count"] = frame["needs_count"].notna()
    frame["has_gate_evidence_ratio"] = frame["gate_evidence_ratio"].notna()
    frame["has_pattern_A_gate_evidence_ratio"] = frame["pattern_A_gate_evidence_ratio"].notna()
    frame["has_pattern_B_member_count"] = frame["pattern_B_member_count"].notna()

    frame["time_window_key_quality"] = np.where(
        frame["has_incident_start"] & frame["has_incident_end"], "complete", "missing_time"
    )
    frame["prefix_origin_key_quality"] = np.select(
        [
            frame["has_dominant_prefix"] & frame["has_dominant_origin_as"],
            frame["has_dominant_prefix"] & ~frame["has_dominant_origin_as"],
            ~frame["has_dominant_prefix"] & frame["has_dominant_origin_as"],
        ],
        ["complete", "prefix_only", "origin_only"],
        default="unusable",
    )
    frame["path_key_quality"] = np.select(
        [frame["has_dominant_path_signature"], frame["has_dominant_triplet_signature"]],
        ["complete", "partial_triplet"],
        default="unusable",
    )
    frame["triplet_key_quality"] = np.where(frame["has_dominant_triplet_signature"], "complete", "unusable")
    frame["collector_key_quality"] = np.where(frame["has_collector_count"], "complete", "unusable")

    completeness_fields = [
        "has_incident_id",
        "has_run_id",
        "has_verification_queue",
        "has_legacy_priority",
        "has_incident_start",
        "has_incident_end",
        "has_first_seen_ts",
        "has_last_seen_ts",
        "has_duration_sec",
        "has_dominant_prefix",
        "has_dominant_origin_as",
        "has_prefix",
        "has_origin_as",
        "has_prefix_origin_pair",
        "has_dominant_path_signature",
        "has_representative_as_path",
        "has_dominant_triplet_signature",
        "has_as_path",
        "has_path_len",
        "has_collector_count",
        "has_collectors",
        "has_vp_count",
        "has_member_count",
        "has_high_count",
        "has_needs_count",
        "has_gate_evidence_ratio",
        "has_pattern_A_gate_evidence_ratio",
        "has_pattern_B_member_count",
    ]

    def missing_for_row(row: pd.Series) -> str:
        missing = [name.removeprefix("has_") for name in completeness_fields if not bool(row[name])]
        return ";".join(missing)

    frame["missing_fields"] = frame.apply(missing_for_row, axis=1)
    missing_counts = {name.removeprefix("has_"): int((~frame[name]).sum()) for name in completeness_fields}
    blocker_fields = [
        field
        for field in [
            "dominant_prefix",
            "dominant_origin_as",
            "incident_start",
            "incident_end",
            "dominant_path_signature",
            "dominant_triplet_signature",
            "collector_count",
        ]
        if missing_counts.get(field, 0) > 0
    ]
    summary = {
        "total_incidents_checked": int(len(frame)),
        "incidents_with_prefix_origin_key": int((frame["prefix_origin_key_quality"] == "complete").sum()),
        "incidents_with_time_window": int((frame["time_window_key_quality"] == "complete").sum()),
        "incidents_with_path_key": int((frame["path_key_quality"] == "complete").sum()),
        "incidents_with_triplet_key": int((frame["triplet_key_quality"] == "complete").sum()),
        "incidents_with_collector_key": int((frame["collector_key_quality"] == "complete").sum()),
        "missing_field_counts": missing_counts,
        "blocker_fields": blocker_fields,
        "status": "completed",
    }
    output_cols = [
        "incident_id",
        "run_id",
        "verification_queue",
        "legacy_priority",
        "prefix_origin_key_quality",
        "time_window_key_quality",
        "path_key_quality",
        "triplet_key_quality",
        "collector_key_quality",
        "missing_fields",
    ] + completeness_fields
    return frame[output_cols].copy(), summary


def build_prefix_origin_targets(incidents: pd.DataFrame, run_id: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    frame = incidents.copy()
    prefix_ok = frame["dominant_prefix"].map(is_valid_prefix)
    origin_ok = frame["dominant_origin_as"].map(lambda value: normalize_asn(value) != "")
    time_ok = frame["incident_start"].map(is_valid_time) & frame["incident_end"].map(is_valid_time)
    frame["key_quality"] = np.select(
        [
            prefix_ok & origin_ok & time_ok,
            prefix_ok & origin_ok & ~time_ok,
            prefix_ok & ~origin_ok,
            ~prefix_ok & origin_ok,
        ],
        ["complete", "missing_time", "prefix_only", "origin_only"],
        default="unusable",
    )
    frame["missing_reason"] = np.select(
        [
            frame["key_quality"].eq("complete"),
            frame["key_quality"].eq("missing_time"),
            frame["key_quality"].eq("prefix_only"),
            frame["key_quality"].eq("origin_only"),
        ],
        ["", "missing incident_start or incident_end", "missing origin_as", "missing prefix"],
        default="missing prefix and origin_as",
    )
    targets = pd.DataFrame(
        {
            "target_id": [f"po_{i:09d}" for i in range(len(frame))],
            "incident_id": frame["incident_id"],
            "run_id": run_id,
            "lookup_prefix": frame["dominant_prefix"],
            "lookup_origin_as": frame["dominant_origin_as"].map(normalize_asn),
            "incident_start": frame["incident_start"],
            "incident_end": frame["incident_end"],
            "source_queue": frame["verification_queue"],
            "legacy_priority": frame["legacy_priority"],
            "member_count": frame["member_count"],
            "high_count": frame["high_count"],
            "needs_count": frame["needs_count"],
            "key_quality": frame["key_quality"],
            "missing_reason": frame["missing_reason"],
            "lookup_candidate": frame["key_quality"].isin(["complete", "missing_time"]),
        }
    )
    counts = count_dict(targets["key_quality"])
    lookup_candidates = int(targets["lookup_candidate"].sum())
    summary = {
        "total_targets": int(len(targets)),
        "key_quality_counts": counts,
        "candidate_lookup_targets": lookup_candidates,
        "complete_targets": int((targets["key_quality"] == "complete").sum()),
        "missing_time_targets": int((targets["key_quality"] == "missing_time").sum()),
        "unusable_targets": int((targets["key_quality"] == "unusable").sum()),
        "status": "completed",
    }
    return targets, summary


def build_path_triplet_targets(incidents: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for idx, row in incidents.iterrows():
        path = str(row.get("dominant_path_signature", "") or "")
        triplet = str(row.get("dominant_triplet_signature", "") or "")
        path_tokens = parse_as_path(path)
        triplet_tokens = parse_as_path(triplet)
        has_path = len(path_tokens) >= 2
        has_triplet = len(triplet_tokens) >= 3
        if has_path:
            key_quality = "complete"
            missing_reason = ""
            representative = " ".join(path_tokens)
        elif has_triplet:
            key_quality = "partial_triplet"
            missing_reason = "representative path missing; dominant triplet available"
            representative = ""
        else:
            key_quality = "unusable"
            missing_reason = "missing path and triplet"
            representative = ""
        source_queue = str(row.get("verification_queue", ""))
        family = str(row.get("family", ""))
        rows.append(
            {
                "target_id": f"path_{idx:09d}",
                "incident_id": row.get("incident_id", ""),
                "representative_as_path": representative,
                "dominant_path_signature": path,
                "dominant_triplet_signature": triplet,
                "path_len": len(path_tokens),
                "adjacent_as_pairs": make_pairs(path_tokens),
                "triplets": make_triplets(path_tokens) or ("-".join(triplet_tokens[:3]) if has_triplet else ""),
                "source_queue": source_queue,
                "pattern_B_member_count": row.get("pattern_B_member_count", 0),
                "possible_route_leak_queue_flag": bool("route_leak" in source_queue or "route_leak" in family),
                "key_quality": key_quality,
                "missing_reason": missing_reason,
            }
        )
    targets = pd.DataFrame(rows)
    summary = {
        "total_targets": int(len(targets)),
        "key_quality_counts": count_dict(targets["key_quality"]),
        "complete_targets": int((targets["key_quality"] == "complete").sum()),
        "partial_triplet_targets": int((targets["key_quality"] == "partial_triplet").sum()),
        "usable_targets": int(targets["key_quality"].isin(["complete", "partial_triplet"]).sum()),
        "route_leak_queue_targets": int(targets["possible_route_leak_queue_flag"].sum()),
        "pattern_B_targets": int((pd.to_numeric(targets["pattern_B_member_count"], errors="coerce").fillna(0) > 0).sum()),
        "status": "completed",
    }
    return targets, summary


def build_cache_inventory(args: argparse.Namespace, run_date: date) -> tuple[pd.DataFrame, dict[str, str]]:
    evidence_root = Path(args.evidence_root)
    known_events_dir = Path(args.known_events_dir)
    expected = [
        ("rpki_vrp", evidence_root / "rpki"),
        ("rpki_vrp", evidence_root / "rpki" / "vrp_20240416.parquet"),
        ("rpki_vrp", evidence_root / "rpki" / "vrp_2024-04-16.parquet"),
        ("rpki_vrp", evidence_root / "rpki" / "normalized_vrp_2024-04-16.parquet"),
        ("irr_route_object", evidence_root / "irr"),
        ("as_relationship", evidence_root / "as_relationships"),
        ("as_relationship", Path(args.legacy_as_rel_file) if args.legacy_as_rel_file else Path("data/caida/as-relationships/serial-2/20170701.as-rel2.txt")),
        ("aspa", evidence_root / "aspa"),
        ("peeringdb", evidence_root / "peeringdb"),
        ("known_event", known_events_dir),
        ("known_event", known_events_dir / "known_event_candidates_v05.json"),
    ]
    rows = [scan_expected_path(evidence_type, path, run_date) for evidence_type, path in expected]
    inventory = pd.DataFrame(rows)
    by_type = {
        evidence_type: best_readiness(group["readiness_state"].astype(str).tolist())
        for evidence_type, group in inventory.groupby("evidence_type")
    }
    return inventory, by_type


def build_readiness_matrix(
    prefix_targets: pd.DataFrame,
    path_targets: pd.DataFrame,
    completeness: pd.DataFrame,
    cache_by_type: dict[str, str],
) -> pd.DataFrame:
    po_lookup = int(prefix_targets["lookup_candidate"].sum())
    po_complete = int((prefix_targets["key_quality"] == "complete").sum())
    po_rate = float(po_complete / max(len(prefix_targets), 1))
    path_usable = int(path_targets["key_quality"].isin(["complete", "partial_triplet"]).sum())
    path_complete = int((path_targets["key_quality"] == "complete").sum())
    path_rate = float(path_complete / max(len(path_targets), 1))
    collector_complete = int((completeness["collector_key_quality"] == "complete").sum())
    collector_rate = float(collector_complete / max(len(completeness), 1))
    cache_by_type = dict(cache_by_type)
    cache_by_type["incident_internal_visibility"] = "ready_aligned" if collector_complete else "missing"
    cache_by_type["public_monitor_context"] = "ready_aligned"

    def row(
        evidence_type: str,
        lookup_count: int,
        complete_count: int,
        complete_rate: float,
        cache_key: str,
        impact: str,
        blocker: str,
        action: str,
        reduce_unavailable: bool,
        supported: bool,
        strong: bool,
    ) -> dict[str, Any]:
        return {
            "evidence_type": evidence_type,
            "lookup_target_count": lookup_count,
            "complete_key_count": complete_count,
            "complete_key_rate": complete_rate,
            "cache_readiness": cache_by_type.get(cache_key, "missing"),
            "expected_verdict_impact": impact,
            "current_blocker": blocker,
            "next_required_action": action,
            "can_reduce_external_unavailable": reduce_unavailable,
            "can_support_evidence_supported_suspicious": supported,
            "can_support_strongly_supported_suspicious": strong,
            "hard_safety_notes": R1_SAFETY_NOTES[evidence_type],
        }

    matrix_rows = [
        row(
            "rpki_vrp",
            po_lookup,
            po_complete,
            po_rate,
            "rpki_vrp",
            "reduce_external_unavailable",
            "missing aligned 2024-04-16 VRP cache" if cache_by_type.get("rpki_vrp") != "ready_aligned" else "",
            "materialize historical VRP cache for run date" if cache_by_type.get("rpki_vrp") != "ready_aligned" else "rerun R-2A/R-2B smoke with VRP lookup",
            cache_by_type.get("rpki_vrp") == "ready_aligned",
            cache_by_type.get("rpki_vrp") == "ready_aligned",
            False,
        ),
        row(
            "irr_route_object",
            po_lookup,
            po_complete,
            po_rate,
            "irr_route_object",
            "convert_to_evidence_insufficient",
            "IRR cache missing or schema unverified",
            "materialize IRR route object cache after P0 VRP",
            cache_by_type.get("irr_route_object") == "ready_aligned",
            False,
            False,
        ),
        row(
            "as_relationship",
            path_usable,
            path_complete,
            path_rate,
            "as_relationship",
            "diagnostic_only" if cache_by_type.get("as_relationship") == "ready_stale" else "enable_evidence_supported_candidate",
            "only stale AS-rel snapshot available" if cache_by_type.get("as_relationship") == "ready_stale" else "missing aligned AS relationship cache",
            "acquire 2024-near AS relationship snapshot or keep stale_diagnostic",
            cache_by_type.get("as_relationship") == "ready_aligned",
            cache_by_type.get("as_relationship") == "ready_aligned",
            False,
        ),
        row(
            "aspa",
            path_usable,
            path_complete,
            path_rate,
            "aspa",
            "future_work",
            "ASPA cache missing and deployment coverage may be sparse",
            "defer to route-leak/path-specific R-2C or P2 cache work",
            False,
            False,
            False,
        ),
        row(
            "bgp_roles_otc",
            path_usable,
            path_complete,
            path_rate,
            "bgp_roles_otc",
            "future_work",
            "no public Roles/OTC cache configured",
            "define optional Roles/OTC ingestion only for aligned observations",
            False,
            False,
            False,
        ),
        row(
            "peeringdb",
            po_lookup,
            po_complete,
            po_rate,
            "peeringdb",
            "convert_to_evidence_insufficient",
            "PeeringDB cache missing or context-only",
            "materialize PeeringDB context after P0/P1 if needed",
            cache_by_type.get("peeringdb") == "ready_aligned",
            False,
            False,
        ),
        row(
            "known_event",
            po_lookup,
            po_complete,
            po_rate,
            "known_event",
            "enable_evidence_supported_candidate",
            "known-event inventory present only as unverified/time-alignment dependent" if cache_by_type.get("known_event") == "present_unverified_schema" else "known-event inventory missing",
            "normalize known-event inventory to incident time/object matching schema",
            cache_by_type.get("known_event") == "ready_aligned",
            False,
            False,
        ),
        row(
            "incident_internal_visibility",
            len(completeness),
            collector_complete,
            collector_rate,
            "incident_internal_visibility",
            "diagnostic_only",
            "" if collector_rate > 0 else "collector visibility fields missing",
            "retain as internal support/context, not truth",
            False,
            False,
            False,
        ),
        row(
            "public_monitor_context",
            len(completeness),
            len(completeness),
            1.0,
            "public_monitor_context",
            "diagnostic_only",
            "public monitor context is manipulable and not independent truth",
            "use only as candidate trigger/context evidence",
            False,
            False,
            False,
        ),
    ]
    return pd.DataFrame(matrix_rows)


def build_minimal_cache_plan(matrix: pd.DataFrame, prefix_summary: dict[str, Any], completeness_summary: dict[str, Any]) -> pd.DataFrame:
    prefix_complete_rate = completeness_summary["incidents_with_prefix_origin_key"] / max(
        completeness_summary["total_incidents_checked"], 1
    )
    time_complete_rate = completeness_summary["incidents_with_time_window"] / max(
        completeness_summary["total_incidents_checked"], 1
    )
    rpki_readiness = matrix.loc[matrix["evidence_type"] == "rpki_vrp", "cache_readiness"].iloc[0]
    rows = []
    if prefix_complete_rate < 0.8 or time_complete_rate < 0.8:
        p0a_issue = "prefix/origin/time lookup keys are incomplete"
        p0a_next = "repair incident schema before evidence materialization"
    else:
        p0a_issue = "lookup keys are mostly ready"
        p0a_next = "no schema repair blocker for P0 VRP materialization"
    rows.append(
        {
            "priority": "P0a",
            "evidence_type": "incident_lookup_keys",
            "acquisition_target": "stable incident_start/end + dominant_prefix + dominant_origin_as",
            "required_lookup_targets": int(prefix_summary["candidate_lookup_targets"]),
            "required_cache_schema": "incident-level target table",
            "expected_benefit": "enables deterministic external evidence lookup",
            "blocking_issue": p0a_issue,
            "codex_next_task": p0a_next,
            "forbidden_shortcut": "do not infer benign/suspicious from missing lookup keys",
        }
    )
    rows.append(
        {
            "priority": "P0b",
            "evidence_type": "rpki_vrp",
            "acquisition_target": "historical VRP/RPKI cache aligned to 2024-04-16",
            "required_lookup_targets": int(prefix_summary["candidate_lookup_targets"]),
            "required_cache_schema": "prefix,max_length,asn,snapshot_ts,ta",
            "expected_benefit": "reduces external_evidence_unavailable and enables medium origin evidence",
            "blocking_issue": "VRP cache is not ready_aligned" if rpki_readiness != "ready_aligned" else "VRP cache ready",
            "codex_next_task": "materialize VRP cache before R-2C" if rpki_readiness != "ready_aligned" else "run 100k R-2B smoke with VRP cache",
            "forbidden_shortcut": "RPKI valid is not benign; RPKI invalid is not confirmed attack",
        }
    )
    rows.append(
        {
            "priority": "P0c",
            "evidence_type": "r2b_smoke",
            "acquisition_target": "100k smoke with aligned VRP cache",
            "required_lookup_targets": int(prefix_summary["candidate_lookup_targets"]),
            "required_cache_schema": "R-2B verifier table with provenance",
            "expected_benefit": "tests whether external_unavailable declines without safety-rule violations",
            "blocking_issue": "wait for P0b unless VRP cache is ready",
            "codex_next_task": "rerun R-2A/R-2B-lite smoke after VRP materialization",
            "forbidden_shortcut": "do not change legacy detector score or verdict set to force suspicious outputs",
        }
    )
    rows.append(
        {
            "priority": "P1",
            "evidence_type": "irr_peeringdb_known_events",
            "acquisition_target": "IRR route objects, PeeringDB context, normalized known-event inventory",
            "required_lookup_targets": int(prefix_summary["candidate_lookup_targets"]),
            "required_cache_schema": "source,last_modified/provenance/time-window fields",
            "expected_benefit": "adds auxiliary context and a small number of stronger anchors",
            "blocking_issue": "P0 VRP is higher signal-to-cost",
            "codex_next_task": "defer until P0b/P0c smoke explains remaining unavailable cases",
            "forbidden_shortcut": "IRR match is not truth; IRR miss is not attack",
        }
    )
    rows.append(
        {
            "priority": "P2",
            "evidence_type": "aspa_roles_otc_dataplane",
            "acquisition_target": "ASPA, BGP Roles/OTC, targeted data-plane telemetry",
            "required_lookup_targets": int(matrix.loc[matrix["evidence_type"] == "aspa", "lookup_target_count"].iloc[0]),
            "required_cache_schema": "customer_as,provider_as_set or directly observed role/OTC records",
            "expected_benefit": "stronger path-legality checks for route leak and patternB queues",
            "blocking_issue": "higher acquisition cost and sparse public availability",
            "codex_next_task": "defer to R-2C route-leak/path-specific refinement",
            "forbidden_shortcut": "do not use stale AS-rel as strong path evidence",
        }
    )
    return pd.DataFrame(rows)


def write_matrix_markdown(path: Path, matrix: pd.DataFrame) -> None:
    lines = [
        "# R-2B-0 Evidence Readiness Matrix",
        "",
        "This matrix is an audit artifact. It does not change legacy detector outputs or verifier verdicts.",
        "",
        markdown_table(matrix),
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_plan_markdown(path: Path, plan: pd.DataFrame) -> None:
    lines = [
        "# R-2B-0 Minimal Cache Acquisition Plan",
        "",
        "The plan keeps Phase R hard safety rules intact. Missing evidence remains unavailable, not benign.",
        "",
        markdown_table(plan),
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def markdown_table(frame: pd.DataFrame) -> str:
    """Render a small markdown table without requiring pandas optional deps."""
    if frame.empty:
        return "_No rows._"
    columns = list(frame.columns)
    rows = []
    for _, row in frame.iterrows():
        rows.append([str(row[col]).replace("|", "\\|").replace("\n", " ") for col in columns])
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join(["---"] * len(columns)) + " |"
    body = ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join([header, separator, *body])


def write_report(
    path: Path,
    args: argparse.Namespace,
    completeness_summary: dict[str, Any],
    prefix_summary: dict[str, Any],
    path_summary: dict[str, Any],
    cache_by_type: dict[str, str],
    matrix: pd.DataFrame,
    plan: pd.DataFrame,
    warnings: list[str],
) -> None:
    total = completeness_summary["total_incidents_checked"]
    po_count = completeness_summary["incidents_with_prefix_origin_key"]
    time_count = completeness_summary["incidents_with_time_window"]
    path_count = completeness_summary["incidents_with_path_key"]
    triplet_count = completeness_summary["incidents_with_triplet_key"]
    rpki_ready = cache_by_type.get("rpki_vrp", "missing")
    irr_ready = cache_by_type.get("irr_route_object", "missing")
    asrel_ready = cache_by_type.get("as_relationship", "missing")
    p0 = plan.loc[plan["priority"].eq("P0b"), "codex_next_task"].iloc[0]
    can_r2c = bool(rpki_ready == "ready_aligned" and asrel_ready == "ready_aligned")
    lines = [
        "# R-2B-0 Evidence Readiness Audit Report",
        "",
        f"Run ID: `{args.run_id}`",
        f"Run date: `{args.run_date}`",
        f"Mode: `{'full' if args.full_run else 'sample'}`",
        "",
        "## Summary",
        "",
        f"- incidents checked: `{total}`",
        f"- prefix-origin complete: `{po_count}` (`{po_count / max(total, 1):.4f}`)",
        f"- time-window complete: `{time_count}` (`{time_count / max(total, 1):.4f}`)",
        f"- path-key complete: `{path_count}` (`{path_count / max(total, 1):.4f}`)",
        f"- triplet-key complete: `{triplet_count}` (`{triplet_count / max(total, 1):.4f}`)",
        f"- candidate prefix-origin lookup targets: `{prefix_summary['candidate_lookup_targets']}`",
        f"- usable path/triplet targets: `{path_summary['usable_targets']}`",
        "",
        "## Required Questions",
        "",
        "1. Current incidents have RPKI/VRP lookup keys: "
        f"`{po_count}` of `{total}` incidents have complete prefix-origin keys; `{time_count}` have complete incident time windows.",
        "2. Prefix-origin target count: "
        f"`{prefix_summary['total_targets']}` total targets, `{prefix_summary['complete_targets']}` complete, "
        f"`{prefix_summary['candidate_lookup_targets']}` usable for candidate lookup.",
        "3. Path/triplet target count: "
        f"`{path_summary['total_targets']}` total targets, `{path_summary['complete_targets']}` complete paths, "
        f"`{path_summary['partial_triplet_targets']}` partial triplet targets.",
        f"4. Aligned local VRP cache: `{rpki_ready}`.",
        f"5. Local IRR cache: `{irr_ready}`.",
        f"6. 2024-near AS-rel cache: `{asrel_ready}`.",
        "7. The 2017 CAIDA AS-rel snapshot can only be used as `stale_diagnostic` evidence for the 2024 run.",
        "8. RIS/RouteViews slices are monitor/context evidence, not independent external truth.",
        f"9. Recommended immediate next step: `{p0}`.",
        f"10. Direct R-2C verifier refinement ready now: `{str(can_r2c).lower()}`. R-2C is better after P0 VRP materialization unless the goal is schema-only refinement.",
        "11. Learning layer readiness: `false`. Verifier-supported training targets do not exist yet.",
        "12. Legacy detector optimization is not recommended unless it blocks verifier lookup keys or a future R-3 baseline.",
        "13. Recommended next step: P0b historical VRP/RPKI cache materialization if prefix-origin keys are sufficient; otherwise P0a incident key repair.",
        "",
        "## Evidence Readiness Matrix",
        "",
        markdown_table(matrix),
        "",
        "## Minimal Cache Plan",
        "",
        markdown_table(plan),
        "",
        "## Hard Safety Notes",
        "",
        "- RPKI/ROA only validates prefix-origin authorization; it does not validate full AS paths.",
        "- RPKI invalid is not confirmed attack.",
        "- RPKI valid is not confirmed benign.",
        "- RPKI unknown is not normal.",
        "- IRR match is not confirmed legitimate; IRR miss is not attack.",
        "- Public monitor / RIS / RouteViews evidence remains trigger/context, not truth.",
        "- Unavailable evidence remains unavailable, not benign.",
        "",
        "## Warnings",
        "",
    ]
    lines.extend(f"- {warning}" for warning in warnings)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="R-2B-0 evidence readiness audit")
    parser.add_argument("--run-id", default=RUN_ID_DEFAULT)
    parser.add_argument("--output-dir", default=OUTPUT_DIR_DEFAULT)
    parser.add_argument("--sample-rows", type=int, default=0)
    parser.add_argument("--full-run", action="store_true")
    parser.add_argument("--s3d-output-dir", default="outputs/s3d_verification_queue_schema_v01")
    parser.add_argument("--r2a-output-dir", default="")
    parser.add_argument("--s3d2-output-dir", default="")
    parser.add_argument("--evidence-root", default="data/evidence")
    parser.add_argument("--known-events-dir", default="data/known_events")
    parser.add_argument("--legacy-as-rel-file", default="")
    parser.add_argument("--run-date", default=RUN_DATE_DEFAULT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    run_date = date.fromisoformat(args.run_date)
    warnings: list[str] = []

    incidents, input_meta = load_incidents(args, warnings)
    completeness, completeness_summary = build_key_completeness(incidents)
    prefix_targets, prefix_summary = build_prefix_origin_targets(incidents, args.run_id)
    path_targets, path_summary = build_path_triplet_targets(incidents)
    cache_inventory, cache_by_type = build_cache_inventory(args, run_date)
    matrix = build_readiness_matrix(prefix_targets, path_targets, completeness, cache_by_type)
    plan = build_minimal_cache_plan(matrix, prefix_summary, completeness_summary)

    if args.r2a_output_dir:
        r2a_path = Path(args.r2a_output_dir) / "r2a_incident_verifier_table.parquet"
        if not r2a_path.exists():
            warnings.append(f"optional R-2A verifier table missing: {r2a_path}")
    if args.s3d2_output_dir:
        s3d2_path = Path(args.s3d2_output_dir) / "s3d2_incident_evidence_table.parquet"
        if not s3d2_path.exists():
            warnings.append(f"optional S3-D2 evidence table missing: {s3d2_path}")

    completeness.to_csv(output_dir / "r2b_lookup_key_completeness.csv", index=False)
    write_json(output_dir / "r2b_lookup_key_completeness_summary.json", completeness_summary)
    prefix_targets.to_parquet(output_dir / "r2b_prefix_origin_targets.parquet", index=False)
    prefix_targets.to_csv(output_dir / "r2b_prefix_origin_targets.csv", index=False)
    write_json(output_dir / "r2b_prefix_origin_target_summary.json", prefix_summary)
    path_targets.to_parquet(output_dir / "r2b_path_triplet_targets.parquet", index=False)
    path_targets.to_csv(output_dir / "r2b_path_triplet_targets.csv", index=False)
    write_json(output_dir / "r2b_path_triplet_target_summary.json", path_summary)
    cache_inventory.to_csv(output_dir / "r2b_cache_inventory.csv", index=False)
    write_json(
        output_dir / "r2b_cache_inventory.json",
        {
            "cache_inventory_by_type": cache_by_type,
            "rows": cache_inventory.to_dict(orient="records"),
        },
    )
    matrix.to_csv(output_dir / "r2b_evidence_readiness_matrix.csv", index=False)
    write_matrix_markdown(output_dir / "r2b_evidence_readiness_matrix.md", matrix)
    plan.to_csv(output_dir / "r2b_minimal_cache_plan.csv", index=False)
    write_plan_markdown(output_dir / "r2b_minimal_cache_plan.md", plan)

    rpki_readiness = cache_by_type.get("rpki_vrp", "missing")
    asrel_readiness = cache_by_type.get("as_relationship", "missing")
    p0_recommendation = plan.loc[plan["priority"].eq("P0b"), "codex_next_task"].iloc[0]
    summary = {
        "run_id": args.run_id,
        "run_date": args.run_date,
        "total_incidents": int(input_meta["queue_rows_loaded"] if args.full_run else len(incidents)),
        "sampled_incidents": 0 if args.full_run else int(len(incidents)),
        "prefix_origin_complete_count": int(completeness_summary["incidents_with_prefix_origin_key"]),
        "prefix_origin_complete_rate": float(
            completeness_summary["incidents_with_prefix_origin_key"] / max(len(incidents), 1)
        ),
        "path_key_complete_count": int(completeness_summary["incidents_with_path_key"]),
        "path_key_complete_rate": float(completeness_summary["incidents_with_path_key"] / max(len(incidents), 1)),
        "triplet_key_complete_count": int(completeness_summary["incidents_with_triplet_key"]),
        "triplet_key_complete_rate": float(completeness_summary["incidents_with_triplet_key"] / max(len(incidents), 1)),
        "cache_inventory_by_type": cache_by_type,
        "readiness_by_evidence_type": {
            row["evidence_type"]: row["cache_readiness"] for row in matrix.to_dict(orient="records")
        },
        "p0_recommendation": p0_recommendation,
        "can_run_vrp_materialization_next": bool(
            completeness_summary["incidents_with_prefix_origin_key"] > 0 and rpki_readiness != "ready_aligned"
        ),
        "can_run_r2c_next": bool(rpki_readiness == "ready_aligned" and asrel_readiness == "ready_aligned"),
        "can_train_learning_layer": False,
        "warnings": warnings,
        "status": "completed",
        "input_meta": input_meta,
    }
    write_json(output_dir / "r2b0_summary.json", summary)
    write_report(
        output_dir / "r2b0_report.md",
        args,
        completeness_summary,
        prefix_summary,
        path_summary,
        cache_by_type,
        matrix,
        plan,
        warnings,
    )

    print(json.dumps(summary, indent=2, sort_keys=True, default=json_default))


if __name__ == "__main__":
    main()
