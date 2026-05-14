import argparse
import ipaddress
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


RUN_ID_DEFAULT = "s2a_expanded_v01_pilot_6h_april16"
OUTPUT_DIR_DEFAULT = "outputs/s3d2_external_evidence_attachment_v01"
RUN_DATE_DEFAULT = "2024-04-16"

TICKET_COLS = [
    "incident_id",
    "incident_start",
    "incident_end",
    "incident_duration_sec",
    "micro_incident_count",
    "mean_certainty_score",
    "mean_conflict_score",
    "mean_evidence_support_score",
    "missing_rate",
    "calibration_flags",
    "calibration_reason",
]

MEMBERSHIP_COLS = [
    "incident_id",
    "event_id",
    "final_alert_label",
    "alert_source_layer",
    "risk_bucket",
    "certainty_score",
    "conflict_score",
    "evidence_support_score",
    "missing_origin_or_path",
    "reason_signature",
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


def safe_ratio(num: pd.Series, den: pd.Series) -> pd.Series:
    den_clean = den.replace(0, np.nan)
    return (num / den_clean).replace([np.inf, -np.inf], np.nan).fillna(0.0)


def parse_asn(value: Any) -> str:
    text = str(value).strip()
    if not text or text.upper() in {"NA", "NAN", "NONE", "NULL"}:
        return ""
    if text.upper().startswith("AS"):
        text = text[2:]
    try:
        return str(int(float(text)))
    except Exception:
        return text


def parse_path_asns(path_value: Any) -> list[str]:
    text = str(path_value or "").replace(",", " ").replace("|", " ").strip()
    out: list[str] = []
    for token in text.split():
        asn = parse_asn(token)
        if asn and asn not in out[-1:]:
            out.append(asn)
    return out


def load_s3d_queue(args: argparse.Namespace, warnings: list[str]) -> pd.DataFrame:
    queue_path = Path(args.s3d_output_dir) / "s3d_incident_verification_queue.parquet"
    if not queue_path.exists():
        raise SystemExit(f"required S3-D queue not found: {queue_path}")
    queue = pd.read_parquet(queue_path)
    if args.sample_rows and not args.full_run:
        queue = queue.head(args.sample_rows).copy()
    text_cols = [
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
    ]
    for col in text_cols:
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
    warnings.append("S3-D2 consumes S3-D queue labels as verification planning fields, not as truth labels.")
    return queue


def enrich_from_tickets(queue: pd.DataFrame, args: argparse.Namespace, warnings: list[str]) -> pd.DataFrame:
    run_dir = Path("data") / "runs" / args.run_id
    candidates = [
        Path(args.calibrated_tickets) if args.calibrated_tickets else Path("outputs/s3a2_incident_priority_calibration_v01/s3a2_calibrated_incident_tickets.parquet"),
        run_dir / "incidents" / "incident_tickets.parquet",
    ]
    ticket_path = next((p for p in candidates if p and p.exists()), None)
    if ticket_path is None:
        warnings.append("incident tickets unavailable; duration/calibration auxiliary fields may be incomplete.")
        return queue
    tickets = read_parquet_existing(ticket_path, list(dict.fromkeys(["incident_id"] + TICKET_COLS)))
    tickets["incident_id"] = to_text(tickets, "incident_id")
    for col in ["calibration_flags", "calibration_reason"]:
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
    return queue.merge(tickets, on="incident_id", how="left", suffixes=("", "_ticket"))


def enrich_from_membership(queue: pd.DataFrame, args: argparse.Namespace, warnings: list[str]) -> pd.DataFrame:
    run_dir = Path("data") / "runs" / args.run_id
    membership_path = Path(args.membership) if args.membership else run_dir / "incidents" / "incident_membership.parquet"
    if not membership_path.exists():
        warnings.append("incident membership unavailable; row-level evidence density fields are fallback-only.")
        return queue
    membership = read_parquet_existing(membership_path, MEMBERSHIP_COLS)
    membership["incident_id"] = to_text(membership, "incident_id")
    membership = membership[membership["incident_id"].isin(set(queue["incident_id"]))].copy()
    if membership.empty:
        warnings.append("incident membership join returned no rows for S3-D queue incidents.")
        return queue
    for col in ["final_alert_label", "alert_source_layer", "risk_bucket", "reason_signature"]:
        membership[col] = to_text(membership, col)
    for col in ["certainty_score", "conflict_score", "evidence_support_score"]:
        membership[col] = to_number(membership, col)
    membership["missing_origin_or_path"] = to_bool(membership, "missing_origin_or_path")
    reason = membership["reason_signature"].fillna("").astype(str)
    membership["single_collector_reason"] = reason.str.contains("single_collector_visibility", regex=False, na=False)
    membership["short_lived_reason"] = reason.str.contains("unusually_short_duration_for_prefix", regex=False, na=False) | reason.str.contains(
        "sparse_short_lived_event", regex=False, na=False
    )
    membership["history_rarity_reason"] = reason.str.contains("history_rarity_score", regex=False, na=False)
    agg = membership.groupby("incident_id", sort=False).agg(
        evidence_density_member_count=("event_id", "count"),
        mean_certainty_score_members=("certainty_score", "mean"),
        max_conflict_score_members=("conflict_score", "max"),
        mean_conflict_score_members=("conflict_score", "mean"),
        mean_evidence_support_score_members=("evidence_support_score", "mean"),
        missing_member_count=("missing_origin_or_path", "sum"),
        single_collector_reason_count=("single_collector_reason", "sum"),
        short_lived_reason_count=("short_lived_reason", "sum"),
        history_rarity_reason_count=("history_rarity_reason", "sum"),
    )
    return queue.merge(agg.reset_index(), on="incident_id", how="left")


def normalize_rpki_status(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"valid", "rpki_valid"}:
        return "valid"
    if text in {"invalid_asn", "invalid_as"}:
        return "invalid_asn"
    if text in {"invalid_length", "invalid_max_length", "invalid_length_asn"}:
        return "invalid_length"
    if text == "invalid":
        return "invalid"
    if text in {"unknown", "not_found", "notfound"}:
        return "unknown"
    if text == "unavailable":
        return "unavailable"
    return "unknown" if text else "unavailable"


def load_rpki_cache(path_value: str | None, warnings: list[str]) -> pd.DataFrame:
    if not path_value:
        warnings.append("historical RPKI cache not provided; rpki_status will be unavailable.")
        return pd.DataFrame()
    path = Path(path_value)
    if not path.exists():
        warnings.append(f"RPKI cache not found at {path}; rpki_status will be unavailable.")
        return pd.DataFrame()
    if path.suffix.lower() == ".parquet":
        df = pd.read_parquet(path)
    elif path.suffix.lower() in {".json", ".jsonl"}:
        if path.suffix.lower() == ".jsonl":
            df = pd.read_json(path, lines=True)
        else:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                raw = raw.get("records") or raw.get("roas") or raw.get("data") or []
            df = pd.DataFrame(raw)
    else:
        df = pd.read_csv(path)
    if df.empty:
        warnings.append(f"RPKI cache at {path} is empty.")
        return df
    lower = {str(c).lower(): c for c in df.columns}
    prefix_col = lower.get("prefix") or lower.get("roa_prefix")
    origin_col = lower.get("origin_as") or lower.get("origin") or lower.get("asn") or lower.get("origin_asn")
    status_col = lower.get("rpki_status") or lower.get("status") or lower.get("validation_status")
    if not prefix_col or not origin_col or not status_col:
        warnings.append(f"RPKI cache at {path} lacks prefix/origin/status columns; rpki_status will be unavailable.")
        return pd.DataFrame()
    out = pd.DataFrame(
        {
            "dominant_prefix": df[prefix_col].fillna("").astype(str),
            "dominant_origin_as_norm": df[origin_col].map(parse_asn),
            "rpki_status": df[status_col].map(normalize_rpki_status),
        }
    )
    out = out.drop_duplicates(["dominant_prefix", "dominant_origin_as_norm"], keep="first")
    return out


def attach_rpki(queue: pd.DataFrame, args: argparse.Namespace, warnings: list[str]) -> pd.DataFrame:
    out = queue.copy()
    out["dominant_origin_as_norm"] = out["dominant_origin_as"].map(parse_asn)
    cache = load_rpki_cache(args.rpki_cache, warnings)
    if args.allow_online_rpki:
        warnings.append("online RPKI lookup is intentionally not used for full incident queues; provide --rpki-cache for reproducible evidence.")
    if cache.empty:
        out["rpki_status"] = "unavailable"
        out["rpki_evidence_note"] = "historical_rpki_cache_missing"
    else:
        out = out.merge(cache, on=["dominant_prefix", "dominant_origin_as_norm"], how="left")
        out["rpki_status"] = out["rpki_status"].fillna("unknown").map(normalize_rpki_status)
        out["rpki_evidence_note"] = np.where(out["rpki_status"].eq("unknown"), "no_matching_roa_in_cache", "matched_local_historical_rpki_cache")
    out["rpki_is_valid"] = out["rpki_status"].eq("valid")
    out["rpki_is_invalid"] = out["rpki_status"].isin(["invalid_asn", "invalid_length", "invalid"])
    out["rpki_is_unknown"] = out["rpki_status"].eq("unknown")
    out["rpki_evidence_strength"] = np.select(
        [out["rpki_is_invalid"], out["rpki_is_valid"], out["rpki_is_unknown"], out["rpki_status"].eq("unavailable")],
        ["medium", "weak_context", "weak_context", "unavailable"],
        default="unavailable",
    )
    out["rpki_score_component"] = np.select([out["rpki_is_invalid"], out["rpki_is_valid"], out["rpki_is_unknown"]], [18.0, 4.0, 0.0], default=0.0)
    return out


def infer_snapshot_date(path: Path) -> str:
    stem = path.name
    digits = "".join(ch for ch in stem if ch.isdigit())
    if len(digits) >= 8:
        return digits[:8]
    return ""


def load_as_rel(path_value: str | None, run_date: str, warnings: list[str]) -> tuple[dict[tuple[str, str], str], dict[str, Any]]:
    info: dict[str, Any] = {"available": False, "path": path_value or "", "snapshot_date": "", "stale": True}
    if not path_value:
        warnings.append("AS relationship file not provided; path relation evidence will be unavailable.")
        return {}, info
    path = Path(path_value)
    if not path.exists():
        warnings.append(f"AS relationship file not found: {path}; path relation evidence will be unavailable.")
        return {}, info
    snapshot = infer_snapshot_date(path)
    info["snapshot_date"] = snapshot
    run_yyyymmdd = run_date.replace("-", "")[:8]
    info["stale"] = bool(snapshot and snapshot[:4] != run_yyyymmdd[:4])
    if info["stale"]:
        warnings.append(f"AS relationship snapshot {snapshot or 'unknown'} is not time-aligned with run date {run_date}; evidence is diagnostic, not strong.")
    rels: dict[tuple[str, str], str] = {}
    with path.open("r", encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            if not line or line.startswith("#"):
                continue
            parts = line.strip().split("|")
            if len(parts) < 3:
                continue
            a, b, rel = parse_asn(parts[0]), parse_asn(parts[1]), parts[2].strip()
            if not a or not b:
                continue
            if rel == "0":
                rels[(a, b)] = "p2p"
                rels[(b, a)] = "p2p"
            elif rel == "-1":
                rels[(a, b)] = "p2c"
                rels[(b, a)] = "c2p"
            else:
                rels[(a, b)] = "unknown"
                rels[(b, a)] = "unknown"
    info.update({"available": True, "edge_count": len(rels)})
    return rels, info


def path_relation_for_path(path: str, rels: dict[tuple[str, str], str], stale: bool) -> dict[str, Any]:
    asns = parse_path_asns(path)
    if len(asns) < 2:
        return {
            "rel_seq_available": False,
            "rel_unknown_cnt": 0,
            "rel_unknown_ratio": 1.0,
            "rel_has_unknown": True,
            "possible_valley_free_violation": False,
            "path_relation_risk_score": 0.0,
            "path_relation_note": "dominant_path_unavailable",
        }
    rel_seq = [rels.get((a, b), "unknown") for a, b in zip(asns, asns[1:])]
    unknown_cnt = sum(1 for r in rel_seq if r == "unknown")
    unknown_ratio = unknown_cnt / len(rel_seq) if rel_seq else 1.0
    phase = "up"
    violation = False
    for rel in rel_seq:
        if rel == "unknown":
            continue
        if phase == "up":
            if rel == "p2p":
                phase = "peer"
            elif rel == "p2c":
                phase = "down"
        elif phase == "peer":
            if rel in {"c2p", "p2p"}:
                violation = True
            elif rel == "p2c":
                phase = "down"
        elif phase == "down":
            if rel in {"c2p", "p2p"}:
                violation = True
    risk = unknown_ratio * 35.0 + (45.0 if violation else 0.0)
    if stale:
        risk = min(risk, 40.0)
    note = "as_rel_snapshot_stale_diagnostic" if stale else "as_rel_snapshot_time_aligned"
    if violation:
        note += ";possible_valley_free_violation"
    if unknown_cnt:
        note += f";unknown_edges={unknown_cnt}/{len(rel_seq)}"
    return {
        "rel_seq_available": True,
        "rel_unknown_cnt": int(unknown_cnt),
        "rel_unknown_ratio": float(unknown_ratio),
        "rel_has_unknown": bool(unknown_cnt > 0),
        "possible_valley_free_violation": bool(violation),
        "path_relation_risk_score": float(round(min(risk, 100.0), 4)),
        "path_relation_note": note,
    }


def attach_path_relation(queue: pd.DataFrame, args: argparse.Namespace, warnings: list[str]) -> tuple[pd.DataFrame, dict[str, Any]]:
    rels, rel_info = load_as_rel(args.as_rel_file, args.run_date, warnings)
    out = queue.copy()
    if not rels:
        out["rel_seq_available"] = False
        out["rel_unknown_cnt"] = 0
        out["rel_unknown_ratio"] = 1.0
        out["rel_has_unknown"] = True
        out["path_relation_risk_score"] = 0.0
        out["possible_valley_free_violation"] = False
        out["path_relation_evidence_strength"] = "unavailable"
        out["path_relation_note"] = "as_relationship_file_missing"
        out["path_relation_score_component"] = 0.0
        out["as_rel_snapshot_stale"] = True
        return out, rel_info
    cache: dict[str, dict[str, Any]] = {}
    rows = []
    for path in out["dominant_path_signature"].fillna("").astype(str):
        if path not in cache:
            cache[path] = path_relation_for_path(path, rels, bool(rel_info.get("stale", True)))
        rows.append(cache[path])
    rel_df = pd.DataFrame(rows, index=out.index)
    out = pd.concat([out, rel_df], axis=1)
    out["as_rel_snapshot_stale"] = bool(rel_info.get("stale", True))
    out["path_relation_evidence_strength"] = np.select(
        [
            out["as_rel_snapshot_stale"],
            out["path_relation_risk_score"].ge(55),
            out["rel_seq_available"] & out["rel_unknown_ratio"].lt(0.25),
            out["rel_seq_available"],
        ],
        ["weak_stale_snapshot", "medium", "medium", "weak_context"],
        default="unavailable",
    )
    out["path_relation_score_component"] = np.where(out["as_rel_snapshot_stale"], out["path_relation_risk_score"] * 0.25, out["path_relation_risk_score"] * 0.60)
    return out, rel_info


def attach_history_support(queue: pd.DataFrame) -> pd.DataFrame:
    out = queue.copy()
    out["collector_support_score"] = np.minimum(to_number(out, "collector_union_count") / 12.0, 1.0) * 100.0
    out["single_collector_incident_flag"] = to_number(out, "collector_union_count").le(1)
    duration = to_number(out, "incident_duration_sec")
    out["temporal_support_score"] = np.select(
        [duration.ge(3600), duration.ge(600), duration.ge(60), duration.gt(0)],
        [100.0, 75.0, 45.0, 20.0],
        default=5.0,
    )
    out["recurrence_support_score"] = np.minimum(np.log1p(to_number(out, "micro_incident_count")) / math.log1p(600), 1.0) * 100.0
    out["history_support_score"] = np.clip(
        0.35 * (to_number(out, "incident_confidence").where(to_number(out, "incident_confidence").gt(1), to_number(out, "incident_confidence") * 100))
        + 0.25 * (to_number(out, "high_share") * 100.0)
        + 0.20 * out["collector_support_score"]
        + 0.10 * out["temporal_support_score"]
        + 0.10 * out["recurrence_support_score"]
        - 20.0 * to_number(out, "gate_evidence_ratio"),
        0.0,
        100.0,
    )
    member_count = to_number(out, "member_count").replace(0, np.nan)
    out["missing_member_ratio"] = (to_number(out, "missing_member_count") / member_count).fillna(0.0)
    out["evidence_density_score"] = np.clip(
        0.30 * out["collector_support_score"]
        + 0.25 * out["temporal_support_score"]
        + 0.20 * out["recurrence_support_score"]
        + 0.15 * (100.0 - to_number(out, "gate_evidence_ratio") * 100.0)
        + 0.10 * (100.0 - out["missing_member_ratio"] * 100.0),
        0.0,
        100.0,
    )
    out["history_collector_score_component"] = np.clip(0.40 * out["history_support_score"] + 0.20 * out["evidence_density_score"], 0.0, 60.0)
    return out


def load_known_events(path_value: str | None, warnings: list[str]) -> list[dict[str, Any]]:
    if not path_value:
        warnings.append("known-event inventory not provided; known-event matching skipped.")
        return []
    path = Path(path_value)
    if not path.exists():
        warnings.append(f"known-event inventory missing: {path}; known-event matching skipped.")
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        warnings.append(f"could not parse known-event inventory {path}: {exc}")
        return []
    events = raw.get("events", raw) if isinstance(raw, dict) else raw
    if not isinstance(events, list):
        warnings.append(f"known-event inventory {path} has unsupported structure; matching skipped.")
        return []
    return [event for event in events if isinstance(event, dict)]


def prefix_overlap(prefix_a: str, prefix_b: str) -> bool:
    try:
        net_a = ipaddress.ip_network(prefix_a, strict=False)
        net_b = ipaddress.ip_network(prefix_b, strict=False)
        return net_a.version == net_b.version and net_a.overlaps(net_b)
    except Exception:
        return False


def event_time_overlaps_run(event: dict[str, Any], run_date: str) -> bool:
    text = " ".join(str(event.get(k, "")) for k in ["approximate_time_window", "collect_from"])
    return run_date[:4] in text or run_date in text


def match_one_known_event(row: pd.Series, events: list[dict[str, Any]], run_date: str) -> dict[str, Any]:
    best = {"known_event_match_status": "no_match", "known_event_match_strength": 0.0, "known_event_id": "", "known_event_note": "no_known_event_overlap"}
    incident_prefix = str(row.get("dominant_prefix", ""))
    origin = parse_asn(row.get("dominant_origin_as", ""))
    path_asns = set(parse_path_asns(row.get("dominant_path_signature", "")))
    for event in events:
        prefixes = event.get("target_prefixes") or []
        if isinstance(prefixes, str):
            prefixes = [prefixes]
        prefix_hit = any(prefix_overlap(incident_prefix, str(prefix)) for prefix in prefixes)
        origin_candidates = {
            parse_asn(event.get("anchor_origin_as")),
            parse_asn(event.get("known_malicious_origin_asn")),
        }
        origin_candidates |= {parse_asn(v) for v in event.get("known_attacker_asns", []) or []}
        origin_candidates.discard("")
        origin_hit = bool(origin and origin in origin_candidates)
        chain = {parse_asn(v) for v in event.get("anchor_chain", []) or []}
        chain.discard("")
        path_hit = bool(path_asns & chain)
        time_hit = event_time_overlaps_run(event, run_date)
        score = (40 if prefix_hit else 0) + (25 if origin_hit else 0) + (20 if path_hit else 0) + (15 if time_hit else 0)
        if score > best["known_event_match_strength"]:
            status = "candidate_match" if score >= 40 else "weak_overlap"
            if not time_hit and score > 0:
                status = "out_of_window_overlap"
            best = {
                "known_event_match_status": status,
                "known_event_match_strength": float(score),
                "known_event_id": str(event.get("slug") or event.get("event_name") or ""),
                "known_event_note": f"prefix={prefix_hit};origin={origin_hit};path={path_hit};time={time_hit}",
            }
    return best


def attach_known_events(queue: pd.DataFrame, args: argparse.Namespace, warnings: list[str]) -> pd.DataFrame:
    events = load_known_events(args.known_event_file, warnings)
    out = queue.copy()
    if not events:
        out["known_event_match_status"] = "unavailable"
        out["known_event_match_strength"] = 0.0
        out["known_event_id"] = ""
        out["known_event_note"] = "known_event_inventory_unavailable"
        out["known_event_score_component"] = 0.0
        return out
    rows = [match_one_known_event(row, events, args.run_date) for _, row in out.iterrows()]
    known_df = pd.DataFrame(rows, index=out.index)
    out = pd.concat([out, known_df], axis=1)
    out["known_event_score_component"] = np.where(out["known_event_match_status"].eq("candidate_match"), 20.0, np.where(out["known_event_match_status"].eq("out_of_window_overlap"), 5.0, 0.0))
    warnings.append("known-event matching is incident-level and inventory-limited; no match does not imply no real incident.")
    return out


def attach_composite_evidence(queue: pd.DataFrame) -> pd.DataFrame:
    out = queue.copy()
    out["verification_evidence_score"] = np.clip(
        to_number(out, "rpki_score_component")
        + to_number(out, "path_relation_score_component")
        + to_number(out, "history_collector_score_component")
        + to_number(out, "known_event_score_component"),
        0.0,
        100.0,
    ).round(4)
    unavailable_sources = (
        out["rpki_status"].eq("unavailable").astype(int)
        + out["path_relation_evidence_strength"].eq("unavailable").astype(int)
        + out["known_event_match_status"].eq("unavailable").astype(int)
    )
    out["verification_evidence_bucket"] = np.select(
        [
            unavailable_sources.ge(2),
            out["verification_evidence_score"].ge(70),
            out["verification_evidence_score"].ge(40),
            out["verification_evidence_score"].gt(0),
        ],
        ["unavailable", "strong", "medium", "weak"],
        default="unavailable",
    )
    strong_support = out["verification_evidence_score"].ge(70)
    medium_support = out["verification_evidence_score"].ge(40)
    background_support = (
        out["verification_queue"].isin(["background_like_review", "low_priority_background"])
        & out["high_share"].lt(0.05)
        & out["needs_share"].ge(0.90)
        & (out["gate_evidence_ratio"].ge(0.70) | out["affected_prefix_count"].ge(100) | out["dominant_origin_as_norm"].eq(""))
    )
    conflict = out["rpki_is_valid"] & out["path_relation_risk_score"].ge(55)
    out["verification_status_candidate"] = np.select(
        [
            unavailable_sources.ge(2),
            conflict,
            strong_support & out["verification_queue"].isin(["high_confidence_candidate", "patternB_path_abnormal_verification", "route_leak_like_review"]),
            medium_support & out["verification_queue"].isin(["gate_evidence_weak_case", "patternB_path_abnormal_verification", "route_leak_like_review"]),
            background_support,
        ],
        [
            "external_evidence_unavailable",
            "evidence_conflict",
            "evidence_supported_suspicious",
            "evidence_supported_suspicious",
            "evidence_supported_background_like",
        ],
        default="evidence_insufficient",
    )
    out["verification_reason_v01"] = np.select(
        [
            out["verification_status_candidate"].eq("external_evidence_unavailable"),
            out["verification_status_candidate"].eq("evidence_conflict"),
            out["verification_status_candidate"].eq("evidence_supported_suspicious"),
            out["verification_status_candidate"].eq("evidence_supported_background_like"),
        ],
        [
            "Required external evidence caches are unavailable or not time-aligned.",
            "Evidence components disagree; keep for manual review.",
            "Attached evidence supports suspicion candidate but does not confirm attack.",
            "Attached incident-level evidence supports background-like candidate but does not confirm normal.",
        ],
        default="Evidence remains insufficient for a stronger status candidate.",
    )
    flags = []
    for _, row in out.iterrows():
        active = []
        for col in ["rpki_evidence_strength", "path_relation_evidence_strength", "known_event_match_status"]:
            active.append(f"{col}={row.get(col, '')}")
        if bool(row.get("as_rel_snapshot_stale", True)):
            active.append("as_rel_snapshot_stale=true")
        flags.append(";".join(active))
    out["evidence_source_flags"] = flags
    out["external_evidence_needed"] = np.where(
        out["verification_status_candidate"].eq("external_evidence_unavailable"),
        "historical_rpki_cache;time_aligned_as_relationship_snapshot",
        out["external_evidence_needed"],
    )
    return out


def build_distribution(queue: pd.DataFrame, group_col: str, value_col: str = "incident_id") -> pd.DataFrame:
    if queue.empty:
        return pd.DataFrame(columns=[group_col, "incident_count"])
    return queue.groupby(group_col, dropna=False)[value_col].count().rename("incident_count").reset_index().sort_values("incident_count", ascending=False)


def write_report(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# S3-D2 External Evidence Attachment",
        "",
        f"run_id: `{summary['run_id']}`",
        f"status: `{summary['status']}`",
        f"mode: `{'full' if summary['full_run'] else 'sample'}`",
        "",
        "## Scope",
        "",
        "S3-D2 attaches first-pass external/provenance evidence fields to the incident-level verification queue. It does not perform final truth labeling, does not alter final labels, and does not alter P1/P2/P3.",
        "",
        "## Summary",
        "",
        f"- total_incidents: `{summary['total_incidents']}`",
        f"- evidence buckets: `{summary['evidence_bucket_distribution']}`",
        f"- RPKI status: `{summary['rpki_status_distribution']}`",
        f"- known_event_match_count: `{summary['known_event_match_count']}`",
        f"- known_event_out_of_window_overlap_count: `{summary['known_event_out_of_window_overlap_count']}`",
        f"- high_confidence_candidate_with_strong_evidence: `{summary['high_confidence_candidate_with_strong_evidence']}`",
        f"- gate_weak_case_with_strong_evidence: `{summary['gate_weak_case_with_strong_evidence']}`",
        f"- gate_weak_case_evidence_insufficient: `{summary['gate_weak_case_evidence_insufficient']}`",
        f"- patternB_with_path_evidence: `{summary['patternB_with_path_evidence']}`",
        f"- route_leak_relation_pending: `{summary['route_leak_relation_pending']}`",
        f"- background_like_evidence_supported: `{summary['background_like_evidence_supported']}`",
        f"- external_evidence_unavailable_count: `{summary['external_evidence_unavailable_count']}`",
        "",
        "## Required Answers",
        "",
        "### 1. Did S3-D2 attach first-pass evidence fields?",
        "",
        "Yes. It adds RPKI, AS relationship/path relation, history/collector support, known-event matching, score components, and status-candidate fields to the S3-D incident queue.",
        "",
        "### 2. RPKI coverage",
        "",
        "Historical RPKI cache is required for reproducible 2024 evidence. If absent, S3-D2 sets `rpki_status=unavailable` and does not use current online RPKI as 2024 evidence.",
        "",
        "### 3. Path relation coverage",
        "",
        f"AS relationship info: `{summary['as_rel_info']}`. Stale snapshots are diagnostic only and cannot create strong evidence.",
        "",
        "### 4. History / collector support",
        "",
        "History and collector support are computed from incident fields and membership aggregates. They help rank weak/background-like cases but do not hard-delete incidents.",
        "",
        "### 5. High-confidence queue evidence",
        "",
        f"`{summary['high_confidence_candidate_with_strong_evidence']}` high-confidence candidates have strong evidence under v01 scoring.",
        "",
        "### 6. Gate-evidence weak cases",
        "",
        f"`{summary['gate_weak_case_evidence_insufficient']}` gate-evidence weak cases remain evidence-insufficient.",
        "",
        "### 7. Pattern_B path relation entry",
        "",
        f"`{summary['patternB_with_path_evidence']}` patternB incidents have non-unavailable path relation evidence fields. Stale AS-rel snapshots remain diagnostic.",
        "",
        "### 8. Route-leak queue",
        "",
        f"`{summary['route_leak_relation_pending']}` route-leak review incidents still need S3-C3 triplet legality / valley-free strengthening.",
        "",
        "### 9. Known-event matching",
        "",
        f"Time-aligned known-event matches: `{summary['known_event_match_count']}`. Out-of-window overlaps: `{summary['known_event_out_of_window_overlap_count']}`. A zero time-aligned match does not prove no regression or no real incident; the inventory is limited and mostly historical.",
        "",
        "### 10. Did this complete truth judgment?",
        "",
        "No. This is evidence attachment only. It produces status candidates, not confirmed attack/benign labels.",
        "",
        "### 11. Next step",
        "",
        "- Add time-aligned RPKI/IRR/AS relationship caches and rerun S3-D2.",
        "- Run S3-C3 route-leak triplet legality for route-leak and patternB queues.",
        "- Build S3-D3 high-confidence incident set only after external evidence is attached and reviewed.",
    ]
    if summary.get("warnings"):
        lines.extend(["", "## Warnings", ""])
        lines.extend([f"- {w}" for w in summary["warnings"]])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    queue = load_s3d_queue(args, warnings)
    queue = enrich_from_tickets(queue, args, warnings)
    queue = enrich_from_membership(queue, args, warnings)
    queue = attach_rpki(queue, args, warnings)
    queue, as_rel_info = attach_path_relation(queue, args, warnings)
    queue = attach_history_support(queue)
    queue = attach_known_events(queue, args, warnings)
    queue = attach_composite_evidence(queue)

    output_cols = [
        "incident_id",
        "verification_queue",
        "calibrated_incident_priority",
        "family",
        "member_count",
        "high_count",
        "needs_count",
        "high_share",
        "needs_share",
        "affected_prefix_count",
        "collector_union_count",
        "dominant_prefix",
        "dominant_origin_as",
        "dominant_path_signature",
        "rpki_status",
        "rpki_is_valid",
        "rpki_is_invalid",
        "rpki_is_unknown",
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
        "collector_support_score",
        "single_collector_incident_flag",
        "temporal_support_score",
        "incident_duration_sec",
        "recurrence_support_score",
        "history_support_score",
        "evidence_density_score",
        "known_event_match_status",
        "known_event_match_strength",
        "known_event_id",
        "known_event_note",
        "rpki_score_component",
        "path_relation_score_component",
        "history_collector_score_component",
        "known_event_score_component",
        "verification_evidence_score",
        "verification_evidence_bucket",
        "verification_status_candidate",
        "external_evidence_needed",
        "verification_reason_v01",
        "recommended_next_check",
        "evidence_source_flags",
        "weak_label_candidate",
    ]
    for col in output_cols:
        if col not in queue.columns:
            queue[col] = ""
    evidence_table = queue[output_cols].copy()

    qdist = queue.groupby(["verification_queue", "verification_evidence_bucket"]).size().rename("incident_count").reset_index()
    rpki_summary = queue.groupby(["verification_queue", "rpki_status"]).size().rename("incident_count").reset_index()
    path_summary = queue.groupby(["verification_queue", "path_relation_evidence_strength"]).size().rename("incident_count").reset_index()
    hist_summary = queue.groupby("verification_queue").agg(
        incident_count=("incident_id", "count"),
        mean_collector_support_score=("collector_support_score", "mean"),
        mean_temporal_support_score=("temporal_support_score", "mean"),
        mean_history_support_score=("history_support_score", "mean"),
        mean_evidence_density_score=("evidence_density_score", "mean"),
    ).reset_index()
    known_match = queue[queue["known_event_match_status"].eq("candidate_match")].copy()
    known_overlap = queue[queue["known_event_match_status"].eq("out_of_window_overlap")].copy()
    external_unavailable = queue["rpki_status"].eq("unavailable") | queue["path_relation_evidence_strength"].isin(
        ["unavailable", "weak_stale_snapshot"]
    )

    strong = queue["verification_evidence_bucket"].eq("strong")
    gate_weak = queue["verification_queue"].eq("gate_evidence_weak_case")
    pattern_b = queue["verification_queue"].eq("patternB_path_abnormal_verification")
    route_leak = queue["verification_queue"].eq("route_leak_like_review")
    background = queue["verification_queue"].eq("background_like_review")
    summary = {
        "run_id": args.run_id,
        "total_incidents": int(len(queue)),
        "queue_count_by_type": count_dict(queue["verification_queue"]),
        "evidence_bucket_distribution": count_dict(queue["verification_evidence_bucket"]),
        "rpki_status_distribution": count_dict(queue["rpki_status"]),
        "path_relation_evidence_distribution": count_dict(queue["path_relation_evidence_strength"]),
        "known_event_match_count": int(len(known_match)),
        "known_event_out_of_window_overlap_count": int(len(known_overlap)),
        "high_confidence_candidate_with_strong_evidence": int((queue["verification_queue"].eq("high_confidence_candidate") & strong).sum()),
        "gate_weak_case_with_strong_evidence": int((gate_weak & strong).sum()),
        "gate_weak_case_evidence_insufficient": int((gate_weak & queue["verification_status_candidate"].eq("evidence_insufficient")).sum()),
        "patternB_with_path_evidence": int((pattern_b & ~queue["path_relation_evidence_strength"].eq("unavailable")).sum()),
        "route_leak_relation_pending": int((route_leak & queue["as_rel_snapshot_stale"]).sum()),
        "background_like_evidence_supported": int((background & queue["verification_status_candidate"].eq("evidence_supported_background_like")).sum()),
        "external_evidence_unavailable_count": int(external_unavailable.sum()),
        "as_rel_info": as_rel_info,
        "full_run": bool(args.full_run),
        "sample_rows": None if args.full_run else args.sample_rows,
        "warnings": warnings,
        "status": "completed_with_warnings" if warnings else "completed",
    }

    evidence_table.to_parquet(output_dir / "s3d2_incident_evidence_table.parquet", index=False)
    evidence_table.to_csv(output_dir / "s3d2_incident_evidence_table.csv", index=False)
    qdist.to_csv(output_dir / "s3d2_queue_evidence_distribution.csv", index=False)
    rpki_summary.to_csv(output_dir / "s3d2_rpki_evidence_summary.csv", index=False)
    path_summary.to_csv(output_dir / "s3d2_path_relation_evidence_summary.csv", index=False)
    hist_summary.to_csv(output_dir / "s3d2_history_collector_evidence_summary.csv", index=False)
    queue[queue["verification_queue"].eq("high_confidence_candidate")].sort_values("verification_evidence_score", ascending=False).head(500).to_csv(
        output_dir / "s3d2_top_high_confidence_with_evidence.csv", index=False
    )
    queue[gate_weak].sort_values("verification_evidence_score", ascending=False).head(5000).to_csv(
        output_dir / "s3d2_gate_weak_cases_with_evidence.csv", index=False
    )
    queue[pattern_b].sort_values("path_relation_risk_score", ascending=False).head(5000).to_csv(
        output_dir / "s3d2_patternB_with_path_evidence.csv", index=False
    )
    queue[route_leak].sort_values("path_relation_risk_score", ascending=False).to_csv(
        output_dir / "s3d2_route_leak_with_relation_evidence.csv", index=False
    )
    queue[background].sort_values(["member_count", "affected_prefix_count"], ascending=False).head(5000).to_csv(
        output_dir / "s3d2_background_like_with_evidence.csv", index=False
    )
    pd.concat([known_match, known_overlap], ignore_index=True).to_csv(output_dir / "s3d2_known_event_matching.csv", index=False)
    (output_dir / "s3d2_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=json_default), encoding="utf-8")
    write_report(output_dir / "s3d2_report.md", summary)
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="S3-D2 external/provenance evidence attachment for incident verification queues.")
    ap.add_argument("--run-id", default=RUN_ID_DEFAULT)
    ap.add_argument("--output-dir", default=OUTPUT_DIR_DEFAULT)
    ap.add_argument("--s3d-output-dir", default="outputs/s3d_verification_queue_schema_v01")
    ap.add_argument("--as-rel-file", default=None)
    ap.add_argument("--known-event-file", default="data/known_events/known_event_candidates_v05.json")
    ap.add_argument("--rpki-cache", default=None)
    ap.add_argument("--membership", default=None)
    ap.add_argument("--calibrated-tickets", default=None)
    ap.add_argument("--sample-rows", type=int, default=50_000)
    ap.add_argument("--full-run", action="store_true")
    ap.add_argument("--run-date", default=RUN_DATE_DEFAULT)
    ap.add_argument("--allow-online-rpki", action="store_true")
    args = ap.parse_args()

    if args.sample_rows is not None and args.sample_rows <= 0:
        raise SystemExit("--sample-rows must be > 0")
    summary = run(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=json_default))


if __name__ == "__main__":
    main()
