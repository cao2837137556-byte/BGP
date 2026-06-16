#!/usr/bin/env python3
"""R-RPKI-CLEAN-0 event/candidate RPKI sidecar builder.

This script attaches the aligned 2024-04-16 VRP cache to baseline 6h
event/candidate rows. It produces evidence sidecars only: no verifier verdict,
no attack/benign label, no suppression, and no learning target.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import math
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


RUN_ID_DEFAULT = "s2a_baseline_v01_pilot_6h_april16"
RUN_DATE_DEFAULT = "2024-04-16"
RUN_ROOT_DEFAULT = "data/runs/s2a_baseline_v01_pilot_6h_april16"
VRP_DEFAULT = "data/evidence/rpki/vrp_2024-04-16.parquet"
VRP_METADATA_DEFAULT = "data/evidence/rpki/vrp_2024-04-16.metadata.json"
OUTPUT_DIR_DEFAULT = "outputs/r_rpki_clean_0/s2a_baseline_v01_pilot_6h_april16"
MISSING = "missing"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=RUN_ID_DEFAULT)
    parser.add_argument("--run-date", default=RUN_DATE_DEFAULT)
    parser.add_argument("--run-root", default=RUN_ROOT_DEFAULT)
    parser.add_argument("--events", default=None)
    parser.add_argument("--candidates", default=None)
    parser.add_argument("--vrp-cache", default=VRP_DEFAULT)
    parser.add_argument("--vrp-metadata", default=VRP_METADATA_DEFAULT)
    parser.add_argument("--output-dir", default=OUTPUT_DIR_DEFAULT)
    parser.add_argument("--sample-rows", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, (datetime, date, pd.Timestamp, Path)):
        return str(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, float) and math.isnan(value):
        return None
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=json_default), encoding="utf-8")


def rel_path(path: str | Path) -> str:
    p = Path(path)
    try:
        return p.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return p.as_posix()


def existing_columns(path: Path, wanted: list[str]) -> list[str]:
    schema = pq.ParquetFile(path).schema_arrow
    names = set(schema.names)
    return [col for col in wanted if col in names]


def normalize_asn(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    text = str(value).strip().upper()
    if not text or text in {"NAN", "NONE", "NULL", MISSING.upper()}:
        return None
    if text.startswith("AS"):
        text = text[2:]
    try:
        return int(float(text))
    except ValueError:
        return None


def normalize_prefix(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null", MISSING}:
        return None
    try:
        return str(ipaddress.ip_network(text, strict=False))
    except ValueError:
        return None


def load_metadata(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_vrp_index(vrp_path: Path) -> tuple[dict[tuple[int, int, str], list[dict[str, Any]]], dict[str, Any]]:
    vrp = pd.read_parquet(vrp_path, columns=["prefix", "asn", "max_length", "ta", "source", "snapshot_date"])
    index: dict[tuple[int, int, str], list[dict[str, Any]]] = {}
    invalid_rows = 0
    for row in vrp.itertuples(index=False):
        prefix = normalize_prefix(row.prefix)
        asn = normalize_asn(row.asn)
        if prefix is None or asn is None:
            invalid_rows += 1
            continue
        network = ipaddress.ip_network(prefix, strict=False)
        try:
            max_length = int(row.max_length)
        except (TypeError, ValueError):
            max_length = int(network.prefixlen)
        record = {
            "asn": asn,
            "max_length": max_length,
            "ta": str(row.ta),
            "source": str(row.source),
            "snapshot_date": str(row.snapshot_date),
            "vrp_prefix": str(network),
        }
        index.setdefault((network.version, int(network.prefixlen), str(network)), []).append(record)
    info = {
        "vrp_rows": int(len(vrp)),
        "vrp_invalid_rows_skipped": int(invalid_rows),
        "vrp_index_keys": int(len(index)),
    }
    return index, info


def covering_vrps(prefix: str | None, index: dict[tuple[int, int, str], list[dict[str, Any]]]) -> tuple[list[dict[str, Any]], int | None]:
    if prefix is None:
        return [], None
    try:
        network = ipaddress.ip_network(prefix, strict=False)
    except ValueError:
        return [], None
    route_len = int(network.prefixlen)
    matches: list[dict[str, Any]] = []
    for prefix_len in range(route_len, -1, -1):
        try:
            candidate = network if prefix_len == route_len else network.supernet(new_prefix=prefix_len)
        except ValueError:
            continue
        for record in index.get((network.version, prefix_len, str(candidate)), []):
            matches.append(record)
    return matches, route_len


def classify_prefix_origin(prefix: Any, origin_as: Any, index: dict[tuple[int, int, str], list[dict[str, Any]]]) -> dict[str, Any]:
    prefix_norm = normalize_prefix(prefix)
    asn = normalize_asn(origin_as)
    if prefix_norm is None or asn is None:
        return {
            "prefix_norm": prefix_norm or "",
            "origin_as_norm": asn if asn is not None else np.nan,
            "rpki_status": "missing",
            "rpki_evidence_state": "unavailable",
            "rpki_lookup_note": "missing_prefix_or_origin",
            "matched_vrp_count": 0,
            "covering_vrp_asns": "",
            "covering_vrp_max_lengths": "",
            "matched_vrp_prefixes": "",
            "validating_vrp_count": 0,
            "route_prefix_len": np.nan,
        }

    matches, route_len = covering_vrps(prefix_norm, index)
    if not matches:
        return {
            "prefix_norm": prefix_norm,
            "origin_as_norm": asn,
            "rpki_status": "unknown",
            "rpki_evidence_state": "aligned_weak",
            "rpki_lookup_note": "no_covering_vrp",
            "matched_vrp_count": 0,
            "covering_vrp_asns": "",
            "covering_vrp_max_lengths": "",
            "matched_vrp_prefixes": "",
            "validating_vrp_count": 0,
            "route_prefix_len": route_len,
        }

    validating = [record for record in matches if int(record["asn"]) == asn and int(route_len) <= int(record["max_length"])]
    same_asn_too_specific = [record for record in matches if int(record["asn"]) == asn and int(route_len) > int(record["max_length"])]
    asns = sorted({int(record["asn"]) for record in matches})
    max_lengths = sorted({int(record["max_length"]) for record in matches})
    prefixes = sorted({str(record["vrp_prefix"]) for record in matches})

    if validating:
        status = "valid"
        note = "origin_authorized_by_covering_vrp"
    elif same_asn_too_specific:
        status = "invalid_length"
        note = "origin_as_matches_but_prefix_too_specific"
    else:
        status = "invalid_asn"
        note = "covering_vrp_exists_for_different_origin"

    return {
        "prefix_norm": prefix_norm,
        "origin_as_norm": asn,
        "rpki_status": status,
        "rpki_evidence_state": "aligned_medium",
        "rpki_lookup_note": note,
        "matched_vrp_count": len(matches),
        "covering_vrp_asns": "|".join(str(value) for value in asns[:20]),
        "covering_vrp_max_lengths": "|".join(str(value) for value in max_lengths[:20]),
        "matched_vrp_prefixes": "|".join(prefixes[:20]),
        "validating_vrp_count": len(validating),
        "route_prefix_len": route_len,
    }


def build_lookup(events: pd.DataFrame, index: dict[tuple[int, int, str], list[dict[str, Any]]]) -> pd.DataFrame:
    unique = events[["prefix", "origin_as"]].drop_duplicates().copy()
    rows = [classify_prefix_origin(prefix, origin, index) for prefix, origin in zip(unique["prefix"], unique["origin_as"])]
    lookup = pd.concat([unique.reset_index(drop=True), pd.DataFrame(rows)], axis=1)
    return lookup


def build_event_sidecar(events_path: Path, lookup: pd.DataFrame, sample_rows: int) -> pd.DataFrame:
    columns = [
        "event_id",
        "run_id",
        "collector",
        "prefix",
        "origin_as",
        "as_path_clean",
        "first_seen",
        "last_seen",
        "duration_sec",
        "record_count",
    ]
    events = pd.read_parquet(events_path, columns=columns)
    if sample_rows and sample_rows > 0:
        events = events.head(sample_rows).copy()
    sidecar = events.merge(lookup, on=["prefix", "origin_as"], how="left")
    sidecar["rpki_status"] = sidecar["rpki_status"].fillna("missing")
    sidecar["rpki_evidence_state"] = sidecar["rpki_evidence_state"].fillna("unavailable")
    sidecar["rpki_lookup_note"] = sidecar["rpki_lookup_note"].fillna("lookup_join_missing")
    sidecar["rpki_is_valid"] = sidecar["rpki_status"].eq("valid")
    sidecar["rpki_is_invalid"] = sidecar["rpki_status"].isin(["invalid_asn", "invalid_length"])
    sidecar["rpki_is_unknown"] = sidecar["rpki_status"].eq("unknown")
    sidecar["rpki_is_missing"] = sidecar["rpki_status"].eq("missing")
    sidecar["rpki_provenance"] = "vrp_2024_04_16_prefix_origin_lookup"
    sidecar["allowed_claim"] = "RPKI origin authorization evidence is aligned to the run date"
    sidecar["forbidden_claim"] = "Do not claim RPKI invalid is attack; do not claim RPKI valid is benign; do not claim RPKI unknown is normal"
    return sidecar


def build_candidate_sidecar(candidates_path: Path, event_sidecar: pd.DataFrame) -> tuple[pd.DataFrame, float]:
    candidate_cols = [
        "event_id",
        "run_id",
        "prefix",
        "origin_as",
        "as_path_clean",
        "candidate_reasons",
        "collector_set",
        "collector_count",
        "visibility_count",
    ]
    existing = existing_columns(candidates_path, candidate_cols)
    candidates = pd.read_parquet(candidates_path, columns=existing)
    event_ids = set(event_sidecar["event_id"].astype(str))
    candidates = candidates[candidates["event_id"].astype(str).isin(event_ids)].copy()
    sidecar_cols = [
        "event_id",
        "rpki_status",
        "rpki_evidence_state",
        "rpki_lookup_note",
        "matched_vrp_count",
        "validating_vrp_count",
        "covering_vrp_asns",
        "covering_vrp_max_lengths",
        "matched_vrp_prefixes",
        "rpki_is_valid",
        "rpki_is_invalid",
        "rpki_is_unknown",
        "rpki_is_missing",
        "rpki_provenance",
        "allowed_claim",
        "forbidden_claim",
    ]
    merged = candidates.merge(event_sidecar[sidecar_cols], on="event_id", how="left", indicator=True)
    join_rate = float((merged["_merge"] == "both").mean()) if len(merged) else 0.0
    return merged.drop(columns=["_merge"]), join_rate


def distribution(series: pd.Series) -> dict[str, int]:
    return {str(k): int(v) for k, v in series.fillna("missing").value_counts(dropna=False).sort_index().items()}


def write_report(path: Path, summary: dict[str, Any]) -> None:
    status = summary["rpki_status_distribution"]
    lines = [
        "# R-RPKI-CLEAN-0 Event-level RPKI Sidecar Report",
        "",
        f"Run id: `{summary['run_id']}`",
        "",
        "## Scope",
        "",
        "This stage attaches the aligned `2024-04-16` VRP cache to baseline event/candidate rows as a clean sidecar.",
        "It does not reuse old verifier outputs and does not produce attack, benign, suppression, or learning labels.",
        "",
        "## Inputs",
        "",
        f"- events: `{summary['events_path']}`",
        f"- candidates: `{summary['candidates_path']}`",
        f"- VRP cache: `{summary['vrp_cache']}`",
        f"- VRP metadata: `{summary['vrp_metadata']}`",
        f"- aligned to run date: `{summary['vrp_metadata_aligned_to_run_date']}`",
        "",
        "## Output Quality",
        "",
        f"- event sidecar rows: `{summary['event_sidecar_rows']}`",
        f"- candidate sidecar rows: `{summary['candidate_sidecar_rows']}`",
        f"- candidate sidecar join rate: `{summary['candidate_sidecar_join_rate']}`",
        f"- unique prefix-origin pairs checked: `{summary['unique_prefix_origin_checked']}`",
        "",
        "RPKI status distribution:",
        "",
        "| Status | Count |",
        "|---|---:|",
    ]
    lines.extend(f"| `{key}` | `{value}` |" for key, value in status.items())
    lines.extend(
        [
            "",
            "## Scientific Boundary",
            "",
            "Allowed claim:",
            "",
            "`RPKI origin-authorization evidence is aligned and event/candidate-ready.`",
            "",
            "Forbidden claims:",
            "",
            "- RPKI invalid is not a confirmed attack.",
            "- RPKI valid is not benign.",
            "- RPKI unknown is not normal.",
            "- RPKI status alone is not a training label.",
            "",
            "## Next Step",
            "",
            summary["recommended_next_step"],
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    run_root = Path(args.run_root)
    events_path = Path(args.events) if args.events else run_root / "events" / "event_units.parquet"
    candidates_path = Path(args.candidates) if args.candidates else run_root / "candidates" / "candidate_events.parquet"
    vrp_path = Path(args.vrp_cache)
    metadata_path = Path(args.vrp_metadata)
    output_dir = Path(args.output_dir)

    for required in [events_path, candidates_path, vrp_path]:
        if not required.exists():
            raise FileNotFoundError(required)
    if output_dir.exists() and any(output_dir.iterdir()) and not args.overwrite:
        raise FileExistsError(f"output directory is not empty; pass --overwrite: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    metadata = load_metadata(metadata_path)
    index, vrp_info = load_vrp_index(vrp_path)
    event_key_cols = ["prefix", "origin_as"]
    events_for_lookup = pd.read_parquet(events_path, columns=event_key_cols)
    if args.sample_rows and args.sample_rows > 0:
        events_for_lookup = events_for_lookup.head(args.sample_rows).copy()
    lookup = build_lookup(events_for_lookup, index)
    event_sidecar = build_event_sidecar(events_path, lookup, args.sample_rows)
    candidate_sidecar, candidate_join_rate = build_candidate_sidecar(candidates_path, event_sidecar)

    event_sidecar_path = output_dir / "rpki_event_sidecar.parquet"
    candidate_sidecar_path = output_dir / "rpki_candidate_sidecar.parquet"
    preview_path = output_dir / "rpki_event_sidecar_preview.csv"
    lookup_path = output_dir / "rpki_prefix_origin_lookup_audit.csv"
    dist_path = output_dir / "rpki_status_distribution.csv"
    summary_path = output_dir / "rpki_clean0_summary.json"
    report_path = output_dir / "rpki_clean0_report.md"

    event_sidecar.to_parquet(event_sidecar_path, index=False)
    candidate_sidecar.to_parquet(candidate_sidecar_path, index=False)
    event_sidecar.head(1000).to_csv(preview_path, index=False)
    lookup.to_csv(lookup_path, index=False)
    event_sidecar["rpki_status"].value_counts(dropna=False).rename_axis("rpki_status").reset_index(name="count").to_csv(
        dist_path, index=False
    )

    event_rows = int(len(event_sidecar))
    status_dist = distribution(event_sidecar["rpki_status"])
    evidence_state_dist = distribution(event_sidecar["rpki_evidence_state"])
    metadata_aligned = bool(metadata.get("aligned_to_run_date")) if metadata else None
    summary = {
        "run_id": args.run_id,
        "run_date": args.run_date,
        "events_path": rel_path(events_path),
        "candidates_path": rel_path(candidates_path),
        "vrp_cache": rel_path(vrp_path),
        "vrp_metadata": rel_path(metadata_path),
        "vrp_metadata_aligned_to_run_date": metadata_aligned,
        "vrp_record_count": vrp_info["vrp_rows"],
        "vrp_invalid_rows_skipped": vrp_info["vrp_invalid_rows_skipped"],
        "vrp_index_keys": vrp_info["vrp_index_keys"],
        "event_sidecar_rows": event_rows,
        "candidate_sidecar_rows": int(len(candidate_sidecar)),
        "candidate_sidecar_join_rate": candidate_join_rate,
        "unique_prefix_origin_checked": int(len(lookup)),
        "rpki_status_distribution": status_dist,
        "rpki_evidence_state_distribution": evidence_state_dist,
        "rpki_valid_rate": (status_dist.get("valid", 0) / event_rows) if event_rows else 0.0,
        "rpki_invalid_rate": ((status_dist.get("invalid_asn", 0) + status_dist.get("invalid_length", 0)) / event_rows) if event_rows else 0.0,
        "rpki_unknown_rate": (status_dist.get("unknown", 0) / event_rows) if event_rows else 0.0,
        "rpki_missing_rate": (status_dist.get("missing", 0) / event_rows) if event_rows else 0.0,
        "allowed_claim": "RPKI origin authorization evidence is aligned to 2024-04-16 and event/candidate-ready",
        "forbidden_claims": [
            "Do not claim RPKI invalid is attack truth",
            "Do not claim RPKI valid is benign",
            "Do not claim RPKI unknown is normal",
            "Do not use RPKI status as a training label",
        ],
        "recommended_next_step": "R-LABEL-0: define multi-attack benchmark and label protocol before foreground validation or learning.",
        "outputs": {
            "event_sidecar": rel_path(event_sidecar_path),
            "candidate_sidecar": rel_path(candidate_sidecar_path),
            "preview": rel_path(preview_path),
            "lookup_audit": rel_path(lookup_path),
            "status_distribution": rel_path(dist_path),
            "report": rel_path(report_path),
        },
    }
    write_json(summary_path, summary)
    write_report(report_path, summary)
    print(json.dumps(summary, indent=2, sort_keys=True, default=json_default))


if __name__ == "__main__":
    main()
