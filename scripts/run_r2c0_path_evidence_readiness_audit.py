#!/usr/bin/env python3
"""R-2C-0 path evidence readiness audit.

This is an audit-only script. It extracts path/triplet lookup targets and
audits local path-evidence cache readiness. It does not download evidence,
modify verifier verdicts, train models, or run route-leak verification.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


RUN_ID_DEFAULT = "s2a_expanded_v01_pilot_6h_april16"
RUN_DATE_DEFAULT = "2024-04-16"
OUTPUT_DIR_DEFAULT = "outputs/r2c0_path_evidence_readiness_audit_v01"

PATH_SAFETY_NOTES = {
    "caida_as_relationship": "CAIDA AS relationship evidence must be time aligned; stale snapshots are diagnostic only.",
    "as_relationship_2024_near": "A 2024-near AS relationship cache can reduce path-unavailable states, but it is still not confirmed route-leak truth.",
    "aspa": "ASPA can support path authorization when available and aligned, but absence or partial deployment is not benign.",
    "bgp_roles_otc": "BGP Roles / OTC can support route-leak evidence when observed and aligned; missing roles do not imply benign.",
    "peeringdb_context": "PeeringDB is context/diagnostic evidence only, not strong path-legality proof.",
    "known_event_path_context": "Known-event matches can support provenance only when object/time aligned; no match is not normal.",
    "internal_path_novelty": "Internal path novelty is monitor-side context, not independent truth.",
    "public_monitor_path_context": "Public monitor path context is trigger/context evidence and may be poisoning-susceptible.",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=RUN_ID_DEFAULT)
    parser.add_argument("--run-date", default=RUN_DATE_DEFAULT)
    parser.add_argument("--incident-tickets-file", required=True)
    parser.add_argument("--incident-membership-file", required=True)
    parser.add_argument("--r2b-verifier-table", required=True)
    parser.add_argument("--r2b-summary-file", default="")
    parser.add_argument("--existing-path-targets-file", default="")
    parser.add_argument("--legacy-as-rel-file", default="")
    parser.add_argument("--evidence-root", default="data/evidence")
    parser.add_argument("--output-dir", default=OUTPUT_DIR_DEFAULT)
    parser.add_argument("--sample-rows", type=int, default=0)
    parser.add_argument("--full-run", action="store_true")
    return parser.parse_args()


def json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, set):
        return sorted(value)
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=json_default), encoding="utf-8")


def read_json(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def available_columns(path: str | Path, requested: list[str]) -> list[str]:
    p = Path(path)
    if not p.exists():
        return []
    schema_cols = set(pq.ParquetFile(p).schema_arrow.names)
    return [col for col in requested if col in schema_cols]


def read_parquet_existing(path: str | Path, requested: list[str]) -> pd.DataFrame:
    p = Path(path)
    cols = available_columns(p, requested)
    if not cols:
        raise ValueError(f"none of requested columns exist in {p}: {requested}")
    return pd.read_parquet(p, columns=cols)


def normalize_text(value: Any) -> str:
    text = str(value or "").strip()
    if text.upper() in {"", "NA", "NAN", "NONE", "NULL", "[]"}:
        return ""
    return text


def parse_as_path(value: Any) -> list[str]:
    text = normalize_text(value)
    if not text:
        return []
    nums = re.findall(r"\d+", text)
    out: list[str] = []
    for token in nums:
        try:
            asn = int(token)
        except ValueError:
            continue
        if asn > 0:
            out.append(str(asn))
    return out


def adjacent_pairs(path_tokens: list[str]) -> list[str]:
    return [f"{a}-{b}" for a, b in zip(path_tokens, path_tokens[1:])]


def triplets(path_tokens: list[str]) -> list[str]:
    return [f"{a}-{b}-{c}" for a, b, c in zip(path_tokens, path_tokens[1:], path_tokens[2:])]


def count_distribution(series: pd.Series) -> dict[str, int]:
    return {str(k): int(v) for k, v in series.fillna("NA").value_counts().sort_index().items()}


def infer_date_from_name(path: Path) -> str:
    text = path.name
    patterns = [
        r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})",
        r"(20\d{2})(\d{2})(\d{2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            y, m, d = match.groups()
            return f"{y}-{m}-{d}"
    return ""


def freshness_days(snapshot_date: str, run_date: str) -> int | None:
    if not snapshot_date:
        return None
    try:
        return abs((pd.Timestamp(run_date).date() - pd.Timestamp(snapshot_date).date()).days)
    except Exception:
        return None


def list_files(path: Path) -> list[Path]:
    if not path.exists():
        return []
    if path.is_file():
        return [path]
    return [p for p in path.rglob("*") if p.is_file()]


def audit_path_keys(tickets: pd.DataFrame, membership: pd.DataFrame, r2b: pd.DataFrame, sample_rows: int, full_run: bool) -> pd.DataFrame:
    if sample_rows and not full_run:
        incident_ids = tickets["incident_id"].head(sample_rows).astype(str)
        tickets = tickets[tickets["incident_id"].astype(str).isin(set(incident_ids))]
        r2b = r2b[r2b["incident_id"].astype(str).isin(set(incident_ids))]
        membership = membership[membership["incident_id"].astype(str).isin(set(incident_ids))]

    if "path_signature" not in membership.columns:
        membership["path_signature"] = ""
    if "triplet_signature" not in membership.columns:
        membership["triplet_signature"] = ""

    grouped = pd.DataFrame({"incident_id": pd.Series(dtype="object")})
    if not membership.empty:
        membership = membership.copy()
        membership["path_signature_norm"] = membership["path_signature"].map(normalize_text)
        membership["triplet_signature_norm"] = membership["triplet_signature"].map(normalize_text)
        membership["path_len_calc"] = membership["path_signature_norm"].map(lambda x: len(parse_as_path(x)))
        membership["path_available_flag"] = membership["path_signature_norm"].astype(bool).astype(int)
        membership["triplet_available_flag"] = membership["triplet_signature_norm"].astype(bool).astype(int)
        membership["path_len_positive"] = membership["path_len_calc"].where(membership["path_len_calc"] > 0)

        grouped = (
            membership.groupby("incident_id", sort=False)
            .agg(
                member_rows=("incident_id", "size"),
                member_paths_available=("path_available_flag", "sum"),
                member_triplets_available=("triplet_available_flag", "sum"),
                path_member_count=("path_available_flag", "sum"),
                unique_path_count=("path_signature_norm", lambda s: int(s[s.astype(bool)].nunique())),
                unique_triplet_count=("triplet_signature_norm", lambda s: int(s[s.astype(bool)].nunique())),
                path_len_min=("path_len_positive", "min"),
                path_len_median=("path_len_positive", "median"),
                path_len_max=("path_len_positive", "max"),
            )
            .reset_index()
        )

        path_counts = (
            membership.loc[membership["path_signature_norm"].astype(bool), ["incident_id", "path_signature_norm"]]
            .value_counts(["incident_id", "path_signature_norm"])
            .rename("dominant_path_member_count")
            .reset_index()
            .sort_values(["incident_id", "dominant_path_member_count", "path_signature_norm"], ascending=[True, False, True])
            .drop_duplicates("incident_id")
            .rename(columns={"path_signature_norm": "representative_as_path"})
        )
        triplet_counts = (
            membership.loc[membership["triplet_signature_norm"].astype(bool), ["incident_id", "triplet_signature_norm"]]
            .value_counts(["incident_id", "triplet_signature_norm"])
            .rename("dominant_triplet_member_count")
            .reset_index()
            .sort_values(["incident_id", "dominant_triplet_member_count", "triplet_signature_norm"], ascending=[True, False, True])
            .drop_duplicates("incident_id")
            .rename(columns={"triplet_signature_norm": "representative_triplet"})
        )
        grouped = grouped.merge(path_counts, on="incident_id", how="left")
        grouped = grouped.merge(triplet_counts, on="incident_id", how="left")
        grouped["dominant_path_share"] = grouped["dominant_path_member_count"].fillna(0) / grouped["member_rows"].replace(0, np.nan)
        grouped["dominant_triplet_share"] = grouped["dominant_triplet_member_count"].fillna(0) / grouped["member_rows"].replace(0, np.nan)

    if grouped.empty:
        grouped = pd.DataFrame({"incident_id": tickets["incident_id"].astype(str)})

    keep_ticket = [
        "incident_id",
        "dominant_path_signature",
        "dominant_triplet_signature",
        "dominant_prefix",
        "dominant_origin_as",
        "family",
        "incident_priority",
        "member_count",
        "high_count",
        "needs_count",
        "path_signature_count",
        "triplet_signature_count",
    ]
    ticket_cols = [c for c in keep_ticket if c in tickets.columns]
    out = tickets[ticket_cols].copy()
    out["incident_id"] = out["incident_id"].astype(str)
    out = out.merge(grouped, on="incident_id", how="left")

    r2b_cols = [
        "incident_id",
        "verification_queue",
        "calibrated_incident_priority",
        "verifier_verdict_vrp",
        "component_purity_class",
        "pattern_B_member_count",
    ]
    r2b_cols = [c for c in r2b_cols if c in r2b.columns]
    if r2b_cols:
        r2b_small = r2b[r2b_cols].copy()
        r2b_small["incident_id"] = r2b_small["incident_id"].astype(str)
        out = out.merge(r2b_small, on="incident_id", how="left")

    defaults = {
        "dominant_path_signature": "",
        "dominant_triplet_signature": "",
        "representative_as_path": "",
        "representative_triplet": "",
        "member_paths_available": 0,
        "member_triplets_available": 0,
        "path_member_count": 0,
        "unique_path_count": 0,
        "unique_triplet_count": 0,
        "dominant_path_member_count": 0,
        "dominant_triplet_member_count": 0,
        "dominant_path_share": 0.0,
        "dominant_triplet_share": 0.0,
        "path_len_min": 0,
        "path_len_median": 0.0,
        "path_len_max": 0,
    }
    for col, default in defaults.items():
        if col not in out.columns:
            out[col] = default
        out[col] = out[col].fillna(default)

    has_rep = out["representative_as_path"].map(normalize_text).astype(bool)
    has_dom_path = out["dominant_path_signature"].map(normalize_text).astype(bool)
    has_dom_triplet = out["dominant_triplet_signature"].map(normalize_text).astype(bool)
    member_paths = pd.to_numeric(out["member_paths_available"], errors="coerce").fillna(0)
    member_triplets = pd.to_numeric(out["member_triplets_available"], errors="coerce").fillna(0)

    out["has_representative_path"] = has_rep
    out["has_dominant_path_signature"] = has_dom_path
    out["has_dominant_triplet_signature"] = has_dom_triplet

    conditions = [
        member_paths > 0,
        has_rep | has_dom_path,
        member_triplets.gt(0) | has_dom_triplet,
        out["dominant_path_signature"].map(normalize_text).astype(bool),
    ]
    choices = ["complete_member_paths", "complete_dominant_path", "triplet_only", "partial_path_signature"]
    out["path_key_quality"] = np.select(conditions, choices, default="unusable")

    missing_fields: list[str] = []
    for _, row in out.iterrows():
        missing: list[str] = []
        if not row["has_representative_path"] and not row["has_dominant_path_signature"]:
            missing.append("representative_or_dominant_path")
        if not row["has_dominant_triplet_signature"] and int(row.get("member_triplets_available", 0) or 0) <= 0:
            missing.append("triplet_signature")
        if not normalize_text(row.get("dominant_prefix", "")):
            missing.append("dominant_prefix")
        if not normalize_text(row.get("dominant_origin_as", "")):
            missing.append("dominant_origin_as")
        missing_fields.append(";".join(missing))
    out["missing_path_fields"] = missing_fields
    return out


def target_rows(completeness: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    pair_rows: list[dict[str, Any]] = []
    triplet_rows: list[dict[str, Any]] = []
    full_rows: list[dict[str, Any]] = []

    for idx, row in completeness.reset_index(drop=True).iterrows():
        incident_id = str(row["incident_id"])
        path = normalize_text(row.get("representative_as_path", "")) or normalize_text(row.get("dominant_path_signature", ""))
        path_tokens = parse_as_path(path)
        triplet_sig = normalize_text(row.get("representative_triplet", "")) or normalize_text(row.get("dominant_triplet_signature", ""))
        pair_list = adjacent_pairs(path_tokens)
        triplet_list = triplets(path_tokens) or ([triplet_sig.replace(" ", "-")] if triplet_sig else [])
        key_quality = str(row.get("path_key_quality", "unusable"))
        base = {
            "incident_id": incident_id,
            "representative_as_path": " ".join(path_tokens) if path_tokens else path,
            "dominant_path_signature": normalize_text(row.get("dominant_path_signature", "")),
            "dominant_triplet_signature": normalize_text(row.get("dominant_triplet_signature", "")),
            "path_len": int(len(path_tokens)),
            "dominant_path_share": float(row.get("dominant_path_share", 0.0) or 0.0),
            "dominant_triplet_share": float(row.get("dominant_triplet_share", 0.0) or 0.0),
            "source_queue": normalize_text(row.get("verification_queue", "")),
            "legacy_priority": normalize_text(row.get("calibrated_incident_priority", "")) or normalize_text(row.get("incident_priority", "")),
            "member_count": int(float(row.get("member_count", 0) or 0)),
            "high_count": int(float(row.get("high_count", 0) or 0)),
            "needs_count": int(float(row.get("needs_count", 0) or 0)),
            "r2b_verdict": normalize_text(row.get("verifier_verdict_vrp", "")),
            "r2b_component_purity_class": normalize_text(row.get("component_purity_class", "")),
            "key_quality": key_quality,
            "missing_reason": normalize_text(row.get("missing_path_fields", "")),
        }
        if pair_list:
            pair_rows.append(
                {
                    "target_id": f"pair_{len(pair_rows):09d}",
                    "target_type": "as_pair",
                    "adjacent_as_pairs": ";".join(pair_list),
                    "triplets": "",
                    **base,
                }
            )
        if triplet_list:
            triplet_rows.append(
                {
                    "target_id": f"triplet_{len(triplet_rows):09d}",
                    "target_type": "as_triplet",
                    "adjacent_as_pairs": ";".join(pair_list),
                    "triplets": ";".join(triplet_list),
                    **base,
                }
            )
        if path_tokens:
            full_rows.append(
                {
                    "target_id": f"path_{len(full_rows):09d}",
                    "target_type": "full_path",
                    "adjacent_as_pairs": ";".join(pair_list),
                    "triplets": ";".join(triplet_list),
                    **base,
                }
            )

    return pd.DataFrame(pair_rows), pd.DataFrame(triplet_rows), pd.DataFrame(full_rows)


def cache_inventory(args: argparse.Namespace) -> pd.DataFrame:
    evidence_root = Path(args.evidence_root)
    expected: list[tuple[str, Path, str]] = [
        ("caida_as_relationship", Path(args.legacy_as_rel_file) if args.legacy_as_rel_file else Path("data/caida/as-relationships/serial-2/20170701.as-rel2.txt"), "legacy CAIDA AS relationship snapshot"),
        ("as_relationship_2024_near", evidence_root / "as_relationships", "2024-near AS relationship cache"),
        ("aspa", evidence_root / "aspa", "ASPA cache"),
        ("bgp_roles_otc", evidence_root / "bgp_roles_otc", "BGP Roles / OTC cache"),
        ("peeringdb_context", evidence_root / "peeringdb", "PeeringDB context cache"),
        ("known_event_path_context", Path("data/known_events"), "known event inventory"),
    ]
    rows: list[dict[str, Any]] = []
    run_date = args.run_date
    for evidence_type, path, desc in expected:
        files = list_files(path)
        exists = bool(files)
        latest_file = max(files, key=lambda p: p.stat().st_mtime).as_posix() if files else ""
        inferred = infer_date_from_name(Path(latest_file)) if latest_file else ""
        if evidence_type == "caida_as_relationship" and path.name == "20170701.as-rel2.txt":
            inferred = "2017-07-01"
        days = freshness_days(inferred, run_date)
        aligned = days is not None and days <= 30
        readiness = "missing"
        usable = False
        notes = desc
        if exists:
            if evidence_type == "caida_as_relationship":
                readiness = "ready_stale"
                usable = True
                notes = "2017 CAIDA AS-rel exists but is stale for 2024; use stale_diagnostic only."
                aligned = False
            elif evidence_type == "peeringdb_context":
                readiness = "present_unverified_schema"
                usable = True
                notes = "PeeringDB is context/diagnostic only, not strong evidence."
            elif evidence_type == "known_event_path_context":
                readiness = "present_unverified_schema"
                usable = True
                notes = "Known-event inventory requires time/object alignment before strong use."
            elif aligned:
                readiness = "ready_aligned"
                usable = True
                notes = f"{desc} appears time-aligned by filename."
            else:
                readiness = "present_unverified_schema" if not inferred else "ready_stale"
                usable = True
                notes = f"{desc} exists but schema/alignment is not verified."
        rows.append(
            {
                "evidence_type": evidence_type,
                "expected_path": path.as_posix(),
                "exists": exists,
                "file_count": int(len(files)),
                "latest_file": latest_file,
                "inferred_snapshot_date": inferred,
                "aligned_to_run_date": bool(aligned),
                "freshness_days": "" if days is None else int(days),
                "usable_for_r2c": bool(usable),
                "readiness_state": readiness,
                "notes": notes,
            }
        )
    return pd.DataFrame(rows)


def readiness_matrix(completeness: pd.DataFrame, pair_targets: pd.DataFrame, triplet_targets: pd.DataFrame, full_targets: pd.DataFrame, inventory: pd.DataFrame) -> pd.DataFrame:
    total = max(len(completeness), 1)
    pair_count = len(pair_targets)
    triplet_count = len(triplet_targets)
    full_count = len(full_targets)
    complete_path_count = int(completeness["path_key_quality"].isin(["complete_member_paths", "complete_dominant_path"]).sum())
    triplet_complete_count = int(completeness["path_key_quality"].isin(["complete_member_paths", "complete_dominant_path", "triplet_only"]).sum())

    inv = {str(r["evidence_type"]): str(r["readiness_state"]) for _, r in inventory.iterrows()}

    def row(evidence_type: str, targets: int, complete: int, impact: str, blocker: str, action: str, route_leak: bool, path_manip: bool, strong: str) -> dict[str, Any]:
        cache = inv.get(evidence_type, "missing")
        return {
            "evidence_type": evidence_type,
            "lookup_target_count": int(targets),
            "complete_key_count": int(complete),
            "complete_key_rate": float(complete / total),
            "cache_readiness": cache,
            "expected_verdict_impact": impact,
            "current_blocker": blocker,
            "next_required_action": action,
            "can_reduce_path_unavailable": cache in {"ready_aligned", "present_unverified_schema", "ready_stale"},
            "can_support_route_leak_candidate": bool(route_leak),
            "can_support_path_manipulation_candidate": bool(path_manip),
            "can_support_strongly_supported_suspicious": strong,
            "hard_safety_notes": PATH_SAFETY_NOTES.get(evidence_type, ""),
        }

    rows = [
        row(
            "caida_as_relationship",
            pair_count,
            complete_path_count,
            "diagnostic_only",
            "snapshot is stale for 2024",
            "use only for stale diagnostic smoke; acquire 2024-near AS relationship cache before evidence-supported path verdicts",
            False,
            False,
            "no",
        ),
        row(
            "as_relationship_2024_near",
            pair_count,
            complete_path_count,
            "reduce_path_unavailable",
            "aligned cache missing",
            "materialize 2024-near AS relationship cache",
            True,
            True,
            "conditional",
        ),
        row(
            "aspa",
            full_count,
            complete_path_count,
            "route_leak_candidate_support",
            "ASPA cache missing",
            "run ASPA schema readiness / feasibility check",
            True,
            True,
            "conditional",
        ),
        row(
            "bgp_roles_otc",
            triplet_count,
            triplet_complete_count,
            "route_leak_candidate_support",
            "BGP Roles / OTC cache missing",
            "check availability of Roles/OTC evidence for 2024",
            True,
            False,
            "conditional",
        ),
        row(
            "peeringdb_context",
            pair_count,
            complete_path_count,
            "diagnostic_only",
            "context source only",
            "optional PeeringDB context inventory",
            False,
            False,
            "no",
        ),
        row(
            "known_event_path_context",
            full_count,
            complete_path_count,
            "diagnostic_only",
            "requires time/object alignment",
            "path-aware known-event overlap audit",
            False,
            False,
            "no",
        ),
        row(
            "internal_path_novelty",
            full_count,
            complete_path_count,
            "future_work",
            "monitor-derived and poisoning-susceptible",
            "use as context only in R-2C/R-3",
            False,
            True,
            "no",
        ),
        row(
            "public_monitor_path_context",
            full_count,
            complete_path_count,
            "future_work",
            "monitor context is not independent truth",
            "use as trigger/context and stress under R-3 poisoning benchmark",
            False,
            False,
            "no",
        ),
    ]
    return pd.DataFrame(rows)


def minimal_plan(matrix: pd.DataFrame, completeness: pd.DataFrame) -> pd.DataFrame:
    path_complete_rate = float(completeness["path_key_quality"].isin(["complete_member_paths", "complete_dominant_path"]).mean())
    rows: list[dict[str, Any]] = []
    if path_complete_rate < 0.80:
        rows.append(
            {
                "priority": "P0a",
                "evidence_type": "incident_path_schema",
                "acquisition_or_build_target": "repair incident/membership path schema",
                "required_lookup_targets": "full path, AS pair, AS triplet",
                "required_cache_schema": "not applicable",
                "expected_benefit": "make path evidence joinable",
                "blocking_issue": "path key completeness too low",
                "codex_next_task": "audit and repair path schema extraction",
                "forbidden_shortcut": "do not treat missing path as benign",
            }
        )
    rows.append(
        {
            "priority": "P0b",
            "evidence_type": "as_relationship_2024_near",
            "acquisition_or_build_target": "materialize 2024-near AS relationship cache",
            "required_lookup_targets": "AS pair targets from R-2C-0",
            "required_cache_schema": "asn_left, asn_right, relationship, snapshot_date, source, provenance",
            "expected_benefit": "reduce path evidence unavailable/stale states and enable route-leak/path diagnostics",
            "blocking_issue": "only 2017 CAIDA AS-rel exists; stale for 2024",
            "codex_next_task": "R-2C-P0b AS relationship cache materialization",
            "forbidden_shortcut": "do not use 2017 CAIDA as aligned strong evidence",
        }
    )
    rows.append(
        {
            "priority": "P1",
            "evidence_type": "aspa",
            "acquisition_or_build_target": "ASPA schema readiness / feasibility check",
            "required_lookup_targets": "full path and AS pair targets",
            "required_cache_schema": "customer_as, provider_as, afi, snapshot_date, source, provenance",
            "expected_benefit": "support path authorization / route-leak candidate evidence when coverage exists",
            "blocking_issue": "ASPA cache missing",
            "codex_next_task": "ASPA availability audit",
            "forbidden_shortcut": "do not infer benign from absent ASPA",
        }
    )
    rows.append(
        {
            "priority": "P1",
            "evidence_type": "bgp_roles_otc",
            "acquisition_or_build_target": "BGP Roles / OTC availability check",
            "required_lookup_targets": "triplet targets and full paths",
            "required_cache_schema": "path element, role/otc signal, collector/source, timestamp, provenance",
            "expected_benefit": "route-leak legality support when observed and aligned",
            "blocking_issue": "Roles/OTC cache missing",
            "codex_next_task": "BGP Roles/OTC evidence feasibility audit",
            "forbidden_shortcut": "do not treat missing role/OTC as no leak",
        }
    )
    rows.append(
        {
            "priority": "P2",
            "evidence_type": "peeringdb_known_event_context",
            "acquisition_or_build_target": "PeeringDB and path-aware known-event context inventory",
            "required_lookup_targets": "AS pair, facility/IXP, known path fragments",
            "required_cache_schema": "context object with timestamp/provenance",
            "expected_benefit": "diagnostic context and case-study support",
            "blocking_issue": "context not strong evidence",
            "codex_next_task": "optional context inventory after P0/P1",
            "forbidden_shortcut": "do not use context-only evidence as strong verdict support",
        }
    )
    return pd.DataFrame(rows)


def df_to_markdown(df: pd.DataFrame) -> str:
    if df.empty:
        return "_empty_"
    cols = [str(c) for c in df.columns]
    lines = [
        "| " + " | ".join(cols) + " |",
        "| " + " | ".join(["---"] * len(cols)) + " |",
    ]
    for _, row in df.iterrows():
        vals = []
        for col in df.columns:
            text = str(row[col]).replace("\n", " ").replace("|", "\\|")
            vals.append(text)
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)


def write_markdown_tables(out_dir: Path, matrix: pd.DataFrame, plan: pd.DataFrame) -> None:
    matrix_md = ["# R-2C Path Readiness Matrix", ""]
    matrix_md.append(df_to_markdown(matrix))
    matrix_md.append("")
    matrix_md.append("Safety note: readiness does not imply truth. Missing path evidence is not benign, stale AS-rel is diagnostic only, and public monitor context is not independent external truth.")
    (out_dir / "r2c_path_readiness_matrix.md").write_text("\n".join(matrix_md), encoding="utf-8")

    plan_md = ["# R-2C Minimal Path Evidence Plan", ""]
    plan_md.append(df_to_markdown(plan))
    plan_md.append("")
    plan_md.append("Recommended next step: R-2C-P0b AS relationship cache materialization, unless a path schema blocker is detected.")
    (out_dir / "r2c_minimal_path_evidence_plan.md").write_text("\n".join(plan_md), encoding="utf-8")


def build_report(out_dir: Path, summary: dict[str, Any]) -> None:
    report = [
        "# R-2C-0 Path Evidence Readiness Audit",
        "",
        f"Run id: `{summary['run_id']}`",
        f"Run date: `{summary['run_date']}`",
        f"Status: `{summary['status']}`",
        "",
        "## 1. Lookup-Key Readiness",
        "",
        f"Incidents checked: `{summary['total_incidents']}`",
        f"Complete path-key incidents: `{summary['complete_path_key_count']}` (`{summary['complete_path_key_rate']:.6f}`)",
        f"Triplet-capable incidents: `{summary['triplet_key_count']}` (`{summary['triplet_key_rate']:.6f}`)",
        "",
        "The current fixed S2 incident/membership artifacts are path-ready enough for a path evidence branch. Missing or partial keys are preserved as `unusable`/partial targets, not converted into benignness.",
        "",
        "## 2. Target Counts",
        "",
        f"AS-pair targets: `{summary['as_pair_target_count']}`",
        f"Triplet targets: `{summary['triplet_target_count']}`",
        f"Full-path targets: `{summary['full_path_target_count']}`",
        "",
        "## 3. Cache Inventory",
        "",
        f"2024-near AS relationship cache: `{summary['cache_readiness_by_type'].get('as_relationship_2024_near', 'missing')}`",
        f"Legacy 2017 CAIDA AS-rel: `{summary['cache_readiness_by_type'].get('caida_as_relationship', 'missing')}`",
        f"ASPA cache: `{summary['cache_readiness_by_type'].get('aspa', 'missing')}`",
        f"BGP Roles / OTC cache: `{summary['cache_readiness_by_type'].get('bgp_roles_otc', 'missing')}`",
        f"PeeringDB context cache: `{summary['cache_readiness_by_type'].get('peeringdb_context', 'missing')}`",
        "",
        "The 2017 CAIDA AS relationship file can only be used as `stale_diagnostic` for this 2024 run. It must not be treated as aligned or strong evidence. PeeringDB can only be context/diagnostic evidence, not strong path-legality evidence.",
        "",
        "## 4. Can We Enter Route-Leak Verifier Directly?",
        "",
        f"Can enter R-2C materialization: `{summary['can_enter_r2c_materialization']}`",
        f"Can enter direct route-leak verifier: `{summary['can_enter_direct_route_leak_verifier']}`",
        "",
        "The recommended next step is not a direct route-leak verifier. It is R-2C-P0b path evidence materialization, starting with a 2024-near AS relationship cache. ASPA and BGP Roles/OTC feasibility checks should follow.",
        "",
        "## 5. Safety Boundaries",
        "",
        "- This audit did not modify verifier verdicts.",
        "- This audit did not download new evidence.",
        "- This audit did not train a learning layer.",
        "- Stale AS-rel is diagnostic only.",
        "- Valley-free or path-legality conflicts in later phases must not be called confirmed route leaks.",
        "- Missing path evidence is not benign.",
        "- Public monitor context is not independent truth.",
        "",
        "## 6. Learning Layer",
        "",
        "Formal learning training is still blocked. L1 design can continue, but training requires verifier-supported targets, path evidence, poisoning/evasion settings, and provenance-aware evaluation.",
        "",
        "## 7. Recommended Next Step",
        "",
        summary["recommended_next_step"],
    ]
    (out_dir / "r2c0_report.md").write_text("\n".join(report), encoding="utf-8")


def main() -> None:
    args = parse_args()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []

    ticket_cols = [
        "incident_id",
        "dominant_path_signature",
        "dominant_triplet_signature",
        "dominant_prefix",
        "dominant_origin_as",
        "family",
        "incident_priority",
        "member_count",
        "high_count",
        "needs_count",
        "path_signature_count",
        "triplet_signature_count",
    ]
    membership_cols = [
        "incident_id",
        "as_path",
        "as_path_clean",
        "representative_as_path",
        "path_signature",
        "triplet_signature",
        "as_path_len",
        "origin_as",
        "origin_as_norm",
        "prefix",
        "collector",
        "first_seen_ts",
        "last_seen_ts",
        "first_seen",
        "last_seen",
    ]
    r2b_cols = [
        "incident_id",
        "verification_queue",
        "calibrated_incident_priority",
        "verifier_verdict_vrp",
        "component_purity_class",
        "pattern_B_member_count",
    ]

    tickets = read_parquet_existing(args.incident_tickets_file, ticket_cols)
    membership = read_parquet_existing(args.incident_membership_file, membership_cols)
    r2b = read_parquet_existing(args.r2b_verifier_table, r2b_cols)
    r2b_summary = read_json(args.r2b_summary_file) if args.r2b_summary_file else {}

    if args.sample_rows and not args.full_run:
        warnings.append(f"sample_rows={args.sample_rows}; outputs are smoke-sample only")

    completeness = audit_path_keys(tickets, membership, r2b, args.sample_rows, args.full_run)
    pair_targets, triplet_targets, full_targets = target_rows(completeness)
    inventory = cache_inventory(args)
    matrix = readiness_matrix(completeness, pair_targets, triplet_targets, full_targets, inventory)
    plan = minimal_plan(matrix, completeness)

    completeness.to_csv(out_dir / "r2c_path_key_completeness.csv", index=False)
    pair_targets.to_parquet(out_dir / "r2c_as_pair_targets.parquet", index=False)
    pair_targets.to_csv(out_dir / "r2c_as_pair_targets.csv", index=False)
    triplet_targets.to_parquet(out_dir / "r2c_triplet_targets.parquet", index=False)
    triplet_targets.to_csv(out_dir / "r2c_triplet_targets.csv", index=False)
    full_targets.to_parquet(out_dir / "r2c_full_path_targets.parquet", index=False)
    inventory.to_csv(out_dir / "r2c_path_evidence_cache_inventory.csv", index=False)
    write_json(out_dir / "r2c_path_evidence_cache_inventory.json", {"items": inventory.to_dict(orient="records")})
    matrix.to_csv(out_dir / "r2c_path_readiness_matrix.csv", index=False)
    plan.to_csv(out_dir / "r2c_minimal_path_evidence_plan.csv", index=False)
    write_markdown_tables(out_dir, matrix, plan)

    complete_path_mask = completeness["path_key_quality"].isin(["complete_member_paths", "complete_dominant_path"])
    triplet_mask = completeness["path_key_quality"].isin(["complete_member_paths", "complete_dominant_path", "triplet_only"])
    key_summary = {
        "total_incidents_checked": int(len(completeness)),
        "complete_path_key_count": int(complete_path_mask.sum()),
        "complete_path_key_rate": float(complete_path_mask.mean()) if len(completeness) else 0.0,
        "triplet_key_count": int(triplet_mask.sum()),
        "triplet_key_rate": float(triplet_mask.mean()) if len(completeness) else 0.0,
        "path_key_quality_distribution": count_distribution(completeness["path_key_quality"]),
        "missing_field_counts": count_distribution(completeness["missing_path_fields"]),
        "status": "completed",
    }
    write_json(out_dir / "r2c_path_key_completeness_summary.json", key_summary)

    target_summary = {
        "as_pair_target_count": int(len(pair_targets)),
        "triplet_target_count": int(len(triplet_targets)),
        "full_path_target_count": int(len(full_targets)),
        "pair_key_quality_distribution": count_distribution(pair_targets["key_quality"]) if not pair_targets.empty else {},
        "triplet_key_quality_distribution": count_distribution(triplet_targets["key_quality"]) if not triplet_targets.empty else {},
        "full_path_key_quality_distribution": count_distribution(full_targets["key_quality"]) if not full_targets.empty else {},
    }
    write_json(out_dir / "r2c_path_target_summary.json", target_summary)

    cache_by_type = {str(r["evidence_type"]): str(r["readiness_state"]) for _, r in inventory.iterrows()}
    direct_route_leak = cache_by_type.get("as_relationship_2024_near") == "ready_aligned" or cache_by_type.get("aspa") == "ready_aligned"
    can_materialize = bool(key_summary["complete_path_key_rate"] >= 0.80 and cache_by_type.get("as_relationship_2024_near") != "ready_aligned")
    summary = {
        "run_id": args.run_id,
        "run_date": args.run_date,
        "total_incidents": int(len(completeness)),
        "sampled_incidents": int(len(completeness)) if args.sample_rows and not args.full_run else 0,
        "complete_path_key_count": key_summary["complete_path_key_count"],
        "complete_path_key_rate": key_summary["complete_path_key_rate"],
        "triplet_key_count": key_summary["triplet_key_count"],
        "triplet_key_rate": key_summary["triplet_key_rate"],
        "as_pair_target_count": int(len(pair_targets)),
        "triplet_target_count": int(len(triplet_targets)),
        "full_path_target_count": int(len(full_targets)),
        "cache_readiness_by_type": cache_by_type,
        "readiness_matrix_summary": matrix[["evidence_type", "cache_readiness", "expected_verdict_impact", "current_blocker", "next_required_action"]].to_dict(orient="records"),
        "p0_recommendation": "R-2C-P0b AS relationship cache materialization",
        "can_enter_r2c_materialization": can_materialize,
        "can_enter_direct_route_leak_verifier": bool(direct_route_leak),
        "can_train_learning_layer": False,
        "verifier_verdict_modified": False,
        "new_external_evidence_downloaded": False,
        "r2b_source_status": r2b_summary.get("status", "unknown"),
        "recommended_next_step": "R-2C-P0b 2024-near AS relationship cache materialization; then ASPA/Roles feasibility and route-leak verifier smoke.",
        "warnings": warnings,
        "status": "completed",
    }
    write_json(out_dir / "r2c0_summary.json", summary)
    build_report(out_dir, summary)

    print(json.dumps(summary, indent=2, sort_keys=True, default=json_default))


if __name__ == "__main__":
    main()
