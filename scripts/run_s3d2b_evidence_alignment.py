import argparse
import ipaddress
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd


RUN_ID_DEFAULT = "s2a_expanded_v01_pilot_6h_april16"
RUN_START_DEFAULT = "2024-04-16 00:00:00"
RUN_HOURS_DEFAULT = 6.0
OUTPUT_DIR_DEFAULT = "outputs/s3d2b_evidence_alignment_v01"

RPKI_KEYWORDS = ("rpki", "roa", "vrp", "routinator", "rov")
IRR_KEYWORDS = ("irr", "radb", "route-set", "route6", "route_object", "whois")
AS_REL_KEYWORDS = ("as-rel", "as_rel", "relationship", "relationships", "rel2")
KNOWN_EVENT_KEYWORDS = ("known_event", "known-events")


def json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def parse_dt(value: str) -> pd.Timestamp:
    ts = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(ts):
        raise SystemExit(f"cannot parse datetime: {value}")
    return ts


def parse_snapshot_date(text: str) -> pd.Timestamp | None:
    patterns = [
        r"(?<!\d)(20\d{2})[-_]?([01]\d)[-_]?([0-3]\d)(?!\d)",
        r"(?<!\d)(19\d{2})[-_]?([01]\d)[-_]?([0-3]\d)(?!\d)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        y, m, d = match.groups()
        ts = pd.to_datetime(f"{y}-{m}-{d}", errors="coerce", utc=True)
        if not pd.isna(ts):
            return ts
    return None


def safe_text(value: Any) -> str:
    text = str(value or "").strip()
    if text.lower() in {"nan", "none", "null"}:
        return ""
    return text


def parse_asn(value: Any) -> str:
    text = safe_text(value)
    if not text or text.upper() in {"NA", "UNKNOWN"}:
        return ""
    if text.upper().startswith("AS"):
        text = text[2:]
    try:
        return str(int(float(text)))
    except Exception:
        return text


def parse_path_asns(value: Any) -> list[str]:
    text = safe_text(value).replace(",", " ").replace("|", " ")
    out: list[str] = []
    for token in text.split():
        asn = parse_asn(token)
        if asn and (not out or out[-1] != asn):
            out.append(asn)
    return out


def classify_prefix(prefix: Any) -> tuple[bool, str, int]:
    text = safe_text(prefix)
    if not text:
        return False, "", -1
    try:
        network = ipaddress.ip_network(text, strict=False)
        return True, f"ipv{network.version}", int(network.prefixlen)
    except Exception:
        return False, "", -1


def classify_source_alignment(kind: str, snapshot_date: pd.Timestamp | None, run_start: pd.Timestamp, as_rel_max_age_days: int) -> str:
    if snapshot_date is None:
        return "undated"
    age_days = abs((run_start.normalize() - snapshot_date.normalize()).days)
    if kind == "as_relationship":
        if age_days <= as_rel_max_age_days:
            return "aligned"
        if age_days <= 180:
            return "near_but_not_aligned"
        return "stale"
    if kind in {"rpki_roa", "irr_route_object"}:
        if age_days <= 1:
            return "aligned"
        if age_days <= 14:
            return "near_but_not_aligned"
        return "stale"
    return "reference_only"


def infer_source_kind(path: Path) -> str | None:
    text = str(path).lower()
    name = path.name.lower()
    if any(k in text for k in RPKI_KEYWORDS):
        return "rpki_roa"
    if any(k in text for k in IRR_KEYWORDS):
        return "irr_route_object"
    if any(k in text for k in AS_REL_KEYWORDS) or name.endswith(".as-rel2.txt"):
        return "as_relationship"
    if any(k in text for k in KNOWN_EVENT_KEYWORDS):
        return "known_event_inventory"
    return None


def scan_sources(args: argparse.Namespace, run_start: pd.Timestamp) -> pd.DataFrame:
    roots = [Path(p) for p in args.scan_roots]
    explicit = []
    for value in [args.rpki_cache, args.as_rel_file, args.known_event_file]:
        if value:
            explicit.append(Path(value))

    seen: set[Path] = set()
    rows: list[dict[str, Any]] = []

    candidates: list[Path] = []
    for root in roots:
        if root.exists() and root.is_file():
            candidates.append(root)
        elif root.exists():
            candidates.extend([p for p in root.rglob("*") if p.is_file()])
    candidates.extend([p for p in explicit if p.exists()])

    for path in candidates:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        kind = infer_source_kind(path)
        if not kind:
            continue
        snapshot_date = parse_snapshot_date(str(path))
        alignment = classify_source_alignment(kind, snapshot_date, run_start, args.as_rel_max_age_days)
        rows.append(
            {
                "source_kind": kind,
                "path": str(path),
                "exists": path.exists(),
                "size_bytes": path.stat().st_size if path.exists() else 0,
                "snapshot_date": "" if snapshot_date is None else snapshot_date.strftime("%Y-%m-%d"),
                "age_days_from_run_start": None if snapshot_date is None else int((run_start.normalize() - snapshot_date.normalize()).days),
                "alignment_status": alignment,
                "usable_for_s3d2_now": bool(kind in {"rpki_roa", "as_relationship"} and alignment == "aligned"),
                "note": source_note(kind, alignment),
            }
        )
    return pd.DataFrame(rows)


def source_note(kind: str, alignment: str) -> str:
    if kind == "known_event_inventory":
        return "inventory metadata only; incident match still requires time overlap"
    if alignment == "aligned":
        return "time-aligned candidate for S3-D2 rerun"
    if alignment == "near_but_not_aligned":
        return "nearby snapshot; diagnostic unless explicitly accepted"
    if alignment == "stale":
        return "stale snapshot; do not use as strong evidence"
    if alignment == "undated":
        return "date not inferable from path; inspect metadata before use"
    return "reference only"


def load_queue(args: argparse.Namespace) -> pd.DataFrame:
    evidence_path = Path(args.s3d2_output_dir) / "s3d2_incident_evidence_table.parquet"
    queue_path = Path(args.s3d_output_dir) / "s3d_incident_verification_queue.parquet"
    if evidence_path.exists():
        df = pd.read_parquet(evidence_path)
        source = str(evidence_path)
    elif queue_path.exists():
        df = pd.read_parquet(queue_path)
        source = str(queue_path)
    else:
        raise SystemExit(f"required S3-D/S3-D2 input not found: {evidence_path} or {queue_path}")
    if args.sample_rows and not args.full_run:
        df = df.head(args.sample_rows).copy()
    df["_alignment_input_source"] = source
    for col in [
        "incident_id",
        "verification_queue",
        "calibrated_incident_priority",
        "family",
        "dominant_prefix",
        "dominant_origin_as",
        "dominant_path_signature",
        "rpki_status",
        "path_relation_evidence_strength",
        "known_event_match_status",
    ]:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].fillna("").astype(str)
    for col in [
        "member_count",
        "high_count",
        "needs_count",
        "high_share",
        "affected_prefix_count",
        "collector_union_count",
        "verification_evidence_score",
        "pattern_A_gate_evidence_count",
        "pattern_B_verification_count",
    ]:
        if col not in df.columns:
            df[col] = 0.0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    return df


def build_prefix_origin_targets(queue: pd.DataFrame) -> pd.DataFrame:
    df = queue.copy()
    parsed = df["dominant_prefix"].apply(classify_prefix)
    df["valid_prefix"] = parsed.apply(lambda item: item[0])
    df["ip_version"] = parsed.apply(lambda item: item[1])
    df["prefix_length"] = parsed.apply(lambda item: item[2])
    df["origin_as_normalized"] = df["dominant_origin_as"].apply(parse_asn)
    df = df[df["valid_prefix"] & df["origin_as_normalized"].ne("")].copy()
    if df.empty:
        return pd.DataFrame()

    queue_weight = {
        "high_confidence_candidate": 120.0,
        "patternB_path_abnormal_verification": 95.0,
        "gate_evidence_weak_case": 80.0,
        "route_leak_like_review": 75.0,
        "background_like_review": 35.0,
        "low_priority_background": 10.0,
    }
    df["queue_weight"] = df["verification_queue"].map(queue_weight).fillna(20.0)
    df["priority_weight"] = df["calibrated_incident_priority"].map({"P1_high": 60.0, "P2_review": 35.0, "P3_background": 5.0}).fillna(5.0)
    df["needs_rpki_lookup"] = df.get("rpki_status", "").astype(str).eq("unavailable") | df.get("rpki_status", "").astype(str).eq("")
    df["needs_as_rel_lookup"] = df.get("path_relation_evidence_strength", "").astype(str).isin(["weak_stale_snapshot", "unavailable", ""])
    group_cols = ["dominant_prefix", "origin_as_normalized", "ip_version", "prefix_length"]
    agg = df.groupby(group_cols, dropna=False).agg(
        incident_count=("incident_id", "count"),
        member_count=("member_count", "sum"),
        high_count=("high_count", "sum"),
        needs_count=("needs_count", "sum"),
        max_high_share=("high_share", "max"),
        max_affected_prefix_count=("affected_prefix_count", "max"),
        max_collector_union_count=("collector_union_count", "max"),
        max_verification_evidence_score=("verification_evidence_score", "max"),
        queue_weight=("queue_weight", "max"),
        priority_weight=("priority_weight", "max"),
        needs_rpki_lookup=("needs_rpki_lookup", "max"),
        needs_as_rel_lookup=("needs_as_rel_lookup", "max"),
    ).reset_index()
    agg["lookup_priority_score"] = (
        agg["queue_weight"]
        + agg["priority_weight"]
        + agg["high_count"].clip(upper=1000) / 25.0
        + agg["member_count"].clip(upper=5000) / 200.0
        + agg["max_collector_union_count"].clip(upper=12) * 2.0
    ).round(4)
    return agg.sort_values(["lookup_priority_score", "incident_count", "member_count"], ascending=False)


def build_path_relation_targets(queue: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for _, row in queue.iterrows():
        asns = parse_path_asns(row.get("dominant_path_signature"))
        if len(asns) < 2:
            continue
        edges = [f"{a}-{b}" for a, b in zip(asns[:-1], asns[1:])]
        triplets = [f"{a}-{b}-{c}" for a, b, c in zip(asns[:-2], asns[1:-1], asns[2:])]
        rows.append(
            {
                "dominant_path_signature": row.get("dominant_path_signature", ""),
                "incident_id": row.get("incident_id", ""),
                "verification_queue": row.get("verification_queue", ""),
                "family": row.get("family", ""),
                "member_count": row.get("member_count", 0),
                "high_count": row.get("high_count", 0),
                "as_path_len": len(asns),
                "edge_signature": " ".join(edges),
                "triplet_signature": " ".join(triplets),
                "needs_time_aligned_as_rel": str(row.get("path_relation_evidence_strength", "")) in {"weak_stale_snapshot", "unavailable", ""},
            }
        )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    return df.groupby(["dominant_path_signature", "edge_signature", "triplet_signature"], dropna=False).agg(
        incident_count=("incident_id", "count"),
        member_count=("member_count", "sum"),
        high_count=("high_count", "sum"),
        max_path_len=("as_path_len", "max"),
        needs_time_aligned_as_rel=("needs_time_aligned_as_rel", "max"),
    ).reset_index().sort_values(["high_count", "member_count", "incident_count"], ascending=False)


def load_known_events(path_value: str) -> list[dict[str, Any]]:
    path = Path(path_value)
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        return list(payload.get("events", []))
    if isinstance(payload, list):
        return payload
    return []


def event_time_window(event: dict[str, Any]) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    start_text = event.get("collect_from") or event.get("start") or event.get("start_time")
    if not start_text:
        return None, None
    start = pd.to_datetime(start_text, errors="coerce", utc=True)
    if pd.isna(start):
        return None, None
    minutes = event.get("minutes") or event.get("duration_minutes") or 0
    try:
        minutes_float = float(minutes)
    except Exception:
        minutes_float = 0.0
    if minutes_float <= 0:
        minutes_float = 60.0
    return start, start + pd.Timedelta(minutes=minutes_float)


def build_known_event_alignment(
    events: list[dict[str, Any]],
    targets: pd.DataFrame,
    run_start: pd.Timestamp,
    run_end: pd.Timestamp,
) -> pd.DataFrame:
    prefix_set = set(targets.get("dominant_prefix", pd.Series(dtype=str)).astype(str))
    origin_set = set(targets.get("origin_as_normalized", pd.Series(dtype=str)).astype(str))
    rows: list[dict[str, Any]] = []
    for event in events:
        start, end = event_time_window(event)
        target_prefixes = [str(p) for p in event.get("target_prefixes", [])]
        attackers = [parse_asn(x) for x in event.get("known_attacker_asns", [])]
        malicious = parse_asn(event.get("known_malicious_origin_asn"))
        if malicious:
            attackers.append(malicious)
        anchor_origin = parse_asn(event.get("anchor_origin_as"))
        if anchor_origin:
            attackers.append(anchor_origin)
        attackers = sorted(set([a for a in attackers if a]))
        time_overlap = bool(start is not None and end is not None and start < run_end and end > run_start)
        prefix_overlap = bool(prefix_set.intersection(target_prefixes))
        as_overlap = bool(origin_set.intersection(attackers))
        if time_overlap:
            status = "time_aligned_window_overlap"
        elif prefix_overlap or as_overlap:
            status = "out_of_window_asset_overlap"
        else:
            status = "no_overlap"
        rows.append(
            {
                "slug": event.get("slug", event.get("event_name", "")),
                "event_name": event.get("event_name", ""),
                "event_type": event.get("event_type", ""),
                "collect_from": "" if start is None else start.isoformat(),
                "event_end": "" if end is None else end.isoformat(),
                "time_overlap_with_run": time_overlap,
                "prefix_overlap_with_current_targets": prefix_overlap,
                "asn_overlap_with_current_targets": as_overlap,
                "alignment_status": status,
                "target_prefix_count": len(target_prefixes),
                "known_asn_count": len(attackers),
                "note": "matching aid only; no overlap does not prove no real incident",
            }
        )
    return pd.DataFrame(rows)


def write_cache_schema(path: Path) -> None:
    schema = {
        "rpki_cache_accepted_columns": {
            "required": ["prefix", "origin_as or origin_asn or asn", "rpki_status or status or roa_status"],
            "optional": ["max_length", "source", "snapshot_date", "not_before", "not_after"],
            "status_values": ["valid", "invalid_asn", "invalid_length", "invalid", "unknown", "unavailable"],
        },
        "as_relationship_required": {
            "format": "CAIDA as-rel2 text or equivalent edge table",
            "target_snapshot": "near run date; default max age 45 days",
            "s3d2_behavior": "aligned snapshots may provide stronger path-relation evidence; stale snapshots remain diagnostic only",
        },
        "irr_cache_recommended_columns": {
            "required": ["prefix", "origin_as", "source", "snapshot_date"],
            "optional": ["mnt_by", "descr", "route_object", "route6_object", "rir"],
            "current_use": "inventory/planning only until S3-D2 learns an --irr-cache input",
        },
    }
    path.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")


def write_rerun_manifest(
    path: Path,
    args: argparse.Namespace,
    inventory: pd.DataFrame,
    run_start: pd.Timestamp,
    run_end: pd.Timestamp,
) -> dict[str, Any]:
    rpki_aligned = inventory[(inventory["source_kind"].eq("rpki_roa")) & (inventory["alignment_status"].eq("aligned"))] if not inventory.empty else pd.DataFrame()
    as_rel_aligned = inventory[(inventory["source_kind"].eq("as_relationship")) & (inventory["alignment_status"].eq("aligned"))] if not inventory.empty else pd.DataFrame()
    rpki_arg = "<path-to-2024-04-16-rpki-cache.parquet/csv/jsonl>" if rpki_aligned.empty else rpki_aligned.iloc[0]["path"]
    as_rel_arg = "<path-to-2024-near-as-rel2.txt>" if as_rel_aligned.empty else as_rel_aligned.iloc[0]["path"]
    manifest = {
        "run_id": args.run_id,
        "run_start": run_start.isoformat(),
        "run_end": run_end.isoformat(),
        "s3d2_rerun_ready": bool(not rpki_aligned.empty and not as_rel_aligned.empty),
        "required_before_strong_evidence": [
            "2024-04-16 historical RPKI/ROA VRP cache",
            f"AS relationship snapshot within {args.as_rel_max_age_days} days of run start",
        ],
        "optional_next": [
            "IRR route/route6 object cache aligned to run date",
            "modern known-event or operator report inventory for 2024-04-16",
        ],
        "s3d2_rerun_command": (
            "python scripts\\run_s3d2_external_evidence_attachment.py "
            f"--run-id {args.run_id} "
            "--output-dir outputs\\s3d2_external_evidence_attachment_aligned_v01 "
            f"--s3d-output-dir {args.s3d_output_dir} "
            f"--rpki-cache {rpki_arg} "
            f"--as-rel-file {as_rel_arg} "
            f"--known-event-file {args.known_event_file} "
            "--full-run"
        ),
    }
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def write_report(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# S3-D2B Evidence Alignment",
        "",
        f"run_id: `{summary['run_id']}`",
        f"status: `{summary['status']}`",
        f"mode: `{'full' if summary['full_run'] else 'sample'}`",
        "",
        "## Scope",
        "",
        "S3-D2B inventories and aligns evidence inputs for rerunning S3-D2 with time-appropriate external caches. It does not download large external datasets, does not call online APIs at scale, and does not change any upstream detection output.",
        "",
        "## Findings",
        "",
        f"- incidents inspected: `{summary['incident_rows']}`",
        f"- valid prefix-origin lookup targets: `{summary['valid_prefix_origin_target_count']}`",
        f"- top lookup target file: `s3d2b_prefix_origin_targets_top.csv`",
        f"- evidence sources found: `{summary['source_inventory_count']}`",
        f"- source alignment counts: `{summary['source_alignment_counts']}`",
        f"- RPKI aligned cache available: `{summary['rpki_aligned_available']}`",
        f"- AS relationship aligned snapshot available: `{summary['as_rel_aligned_available']}`",
        f"- known-event time-aligned overlaps: `{summary['known_event_time_aligned_count']}`",
        f"- known-event out-of-window overlaps: `{summary['known_event_out_of_window_count']}`",
        f"- S3-D2 aligned rerun ready: `{summary['s3d2_rerun_ready']}`",
        "",
        "## Interpretation",
        "",
        "The local workspace is not yet ready to produce strong external evidence for the 2024 run. Current RPKI evidence remains unavailable unless a historical VRP/ROA cache is supplied. The existing CAIDA `20170701` AS relationship file is useful for format testing and diagnostics, but remains stale for the 2024-04-16 window.",
        "",
        "## Next Action",
        "",
        "Acquire or build the two required caches listed in `s3d2b_rerun_manifest.json`, then rerun S3-D2 using the generated command. IRR cache support is recorded as a planned extension rather than treated as evidence in this run.",
    ]
    if summary.get("warnings"):
        lines.extend(["", "## Warnings", ""])
        lines.extend([f"- {w}" for w in summary["warnings"]])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    run_start = parse_dt(args.run_start)
    run_end = run_start + pd.Timedelta(hours=args.run_hours)
    warnings: list[str] = [
        "S3-D2B is an evidence-alignment planning stage, not external validation.",
        "Do not use current online RPKI status as historical 2024 evidence.",
    ]

    queue = load_queue(args)
    targets = build_prefix_origin_targets(queue)
    path_targets = build_path_relation_targets(queue)
    inventory = scan_sources(args, run_start)
    events = load_known_events(args.known_event_file) if args.known_event_file else []
    known_alignment = build_known_event_alignment(events, targets, run_start, run_end) if events else pd.DataFrame()

    if targets.empty:
        warnings.append("no valid dominant prefix-origin targets were found.")
    if inventory.empty:
        warnings.append("no local external evidence source candidates were found under scan roots.")
    if known_alignment.empty:
        warnings.append("known-event inventory unavailable or empty.")

    rpki_aligned_available = bool(
        not inventory.empty
        and ((inventory["source_kind"] == "rpki_roa") & (inventory["alignment_status"] == "aligned")).any()
    )
    as_rel_aligned_available = bool(
        not inventory.empty
        and ((inventory["source_kind"] == "as_relationship") & (inventory["alignment_status"] == "aligned")).any()
    )
    if not rpki_aligned_available:
        warnings.append("2024-04-16 aligned RPKI/ROA cache is missing.")
    if not as_rel_aligned_available:
        warnings.append(f"AS relationship snapshot within {args.as_rel_max_age_days} days of run start is missing.")

    targets.to_parquet(output_dir / "s3d2b_prefix_origin_targets.parquet", index=False)
    targets.head(args.top_targets).to_csv(output_dir / "s3d2b_prefix_origin_targets_top.csv", index=False)
    targets[targets.get("needs_rpki_lookup", pd.Series(False, index=targets.index)).astype(bool)].head(args.top_targets).to_csv(
        output_dir / "s3d2b_rpki_lookup_targets.csv", index=False
    )
    path_targets.to_csv(output_dir / "s3d2b_path_relation_targets.csv", index=False)
    inventory.to_csv(output_dir / "s3d2b_evidence_source_inventory.csv", index=False)
    known_alignment.to_csv(output_dir / "s3d2b_known_event_time_alignment.csv", index=False)
    write_cache_schema(output_dir / "s3d2b_required_cache_schema.json")
    rerun_manifest = write_rerun_manifest(output_dir / "s3d2b_rerun_manifest.json", args, inventory, run_start, run_end)

    source_alignment_counts: dict[str, int] = {}
    if not inventory.empty:
        source_alignment_counts = {
            f"{row.source_kind}:{row.alignment_status}": int(row.incident_count)
            for row in inventory.groupby(["source_kind", "alignment_status"]).size().rename("incident_count").reset_index().itertuples()
        }
    known_time_aligned = int(known_alignment.get("time_overlap_with_run", pd.Series(dtype=bool)).sum()) if not known_alignment.empty else 0
    known_out_of_window = int((known_alignment.get("alignment_status", pd.Series(dtype=str)) == "out_of_window_asset_overlap").sum()) if not known_alignment.empty else 0
    summary = {
        "run_id": args.run_id,
        "run_start": run_start.isoformat(),
        "run_end": run_end.isoformat(),
        "incident_rows": int(len(queue)),
        "input_source": queue["_alignment_input_source"].iloc[0] if not queue.empty else "",
        "valid_prefix_origin_target_count": int(len(targets)),
        "path_relation_target_count": int(len(path_targets)),
        "source_inventory_count": int(len(inventory)),
        "source_alignment_counts": source_alignment_counts,
        "rpki_aligned_available": rpki_aligned_available,
        "as_rel_aligned_available": as_rel_aligned_available,
        "known_event_count": int(len(known_alignment)),
        "known_event_time_aligned_count": known_time_aligned,
        "known_event_out_of_window_count": known_out_of_window,
        "s3d2_rerun_ready": bool(rerun_manifest["s3d2_rerun_ready"]),
        "top_targets_written": int(min(args.top_targets, len(targets))),
        "full_run": bool(args.full_run),
        "sample_rows": None if args.full_run else args.sample_rows,
        "warnings": warnings,
        "status": "completed_with_action_items",
    }
    (output_dir / "s3d2b_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=json_default), encoding="utf-8")
    write_report(output_dir / "s3d2b_report.md", summary)
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="S3-D2B evidence source alignment and cache request planning.")
    ap.add_argument("--run-id", default=RUN_ID_DEFAULT)
    ap.add_argument("--run-start", default=RUN_START_DEFAULT)
    ap.add_argument("--run-hours", type=float, default=RUN_HOURS_DEFAULT)
    ap.add_argument("--output-dir", default=OUTPUT_DIR_DEFAULT)
    ap.add_argument("--s3d-output-dir", default="outputs/s3d_verification_queue_schema_v01")
    ap.add_argument("--s3d2-output-dir", default="outputs/s3d2_external_evidence_attachment_v01")
    ap.add_argument("--known-event-file", default="data/known_events/known_event_candidates_v05.json")
    ap.add_argument("--rpki-cache", default=None)
    ap.add_argument("--as-rel-file", default="data/caida/as-relationships/serial-2/20170701.as-rel2.txt")
    ap.add_argument("--scan-roots", nargs="+", default=["data"])
    ap.add_argument("--as-rel-max-age-days", type=int, default=45)
    ap.add_argument("--top-targets", type=int, default=5000)
    ap.add_argument("--sample-rows", type=int, default=50_000)
    ap.add_argument("--full-run", action="store_true")
    args = ap.parse_args()
    if args.run_hours <= 0:
        raise SystemExit("--run-hours must be > 0")
    if args.top_targets <= 0:
        raise SystemExit("--top-targets must be > 0")
    if args.sample_rows is not None and args.sample_rows <= 0:
        raise SystemExit("--sample-rows must be > 0")
    summary = run(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=json_default))


if __name__ == "__main__":
    main()
