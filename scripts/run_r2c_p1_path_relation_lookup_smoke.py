#!/usr/bin/env python3
"""R-2C-P1 path relation lookup smoke.

This stage attaches the 2024-near CAIDA AS relationship cache back to
AS-pair, triplet, full-path, and incident-level path evidence. It is a smoke
and audit stage only: it does not produce route-leak verdicts, does not modify
R-2B verifier verdicts, and does not treat inferred AS relationships as truth.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd


RUN_ID_DEFAULT = "s2a_expanded_v01_pilot_6h_april16"
RUN_DATE_DEFAULT = "2024-04-16"
OUTPUT_DIR_DEFAULT = "outputs/r2c_p1_path_relation_lookup_smoke_v01"

SAFETY_NOTES = [
    "AS relationship evidence is inferred evidence, not ground truth",
    "AS-rel matched does not mean path benign",
    "AS-rel unmatched does not mean path suspicious",
    "possible valley-free flags are diagnostic only",
    "this stage does not generate route-leak verdicts",
    "this stage does not modify R-2B verifier verdicts",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=RUN_ID_DEFAULT)
    parser.add_argument("--run-date", default=RUN_DATE_DEFAULT)
    parser.add_argument("--asrel-cache-file", required=True)
    parser.add_argument("--asrel-metadata-file", required=True)
    parser.add_argument("--as-pair-targets-file", required=True)
    parser.add_argument("--triplet-targets-file", required=True)
    parser.add_argument("--full-path-targets-file", required=True)
    parser.add_argument("--r2b-verifier-table", required=True)
    parser.add_argument("--incident-tickets-file", required=True)
    parser.add_argument("--incident-membership-file", required=True)
    parser.add_argument("--output-dir", default=OUTPUT_DIR_DEFAULT)
    parser.add_argument("--sample-rows", type=int, default=0)
    parser.add_argument("--full-run", action="store_true")
    return parser.parse_args()


def json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, (datetime, date, Path)):
        return str(value)
    if pd.isna(value):
        return None
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=json_default), encoding="utf-8")


def write_table(df: pd.DataFrame, parquet_path: Path, csv_path: Path) -> None:
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(parquet_path, index=False)
    df.to_csv(csv_path, index=False)


def read_json(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def read_parquet_required(path: str | Path) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"required input missing: {p}")
    return pd.read_parquet(p)


def maybe_sample(df: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    if args.full_run:
        return df
    if args.sample_rows and len(df) > args.sample_rows:
        return df.head(args.sample_rows).copy()
    return df


def distribution(series: pd.Series) -> dict[str, int]:
    if series.empty:
        return {}
    return {str(k): int(v) for k, v in series.fillna("NA").value_counts().sort_index().items()}


def top_distribution(series: pd.Series, n: int = 20) -> list[dict[str, Any]]:
    if series.empty:
        return []
    vc = series.fillna("NA").value_counts().head(n)
    return [{"value": str(k), "count": int(v)} for k, v in vc.items()]


def safe_float(value: Any, default: float = 0.0) -> float:
    if value is None or pd.isna(value):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    if value is None or pd.isna(value):
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def normalize_asn(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    if not text or text.upper() in {"NA", "NAN", "NONE", "NULL"}:
        return ""
    if text.upper().startswith("AS"):
        text = text[2:]
    try:
        return str(int(float(text)))
    except ValueError:
        return text


def parse_as_path(value: Any) -> list[str]:
    if value is None or pd.isna(value):
        return []
    return [normalize_asn(x) for x in re.findall(r"\d+", str(value)) if normalize_asn(x)]


def parse_pairs(value: Any, representative_path: Any = "") -> list[tuple[str, str]]:
    text = "" if value is None or pd.isna(value) else str(value).strip()
    pairs: list[tuple[str, str]] = []
    for left, right in re.findall(r"(\d+)\s*-\s*(\d+)", text):
        pairs.append((normalize_asn(left), normalize_asn(right)))
    if pairs:
        return pairs
    path = parse_as_path(representative_path)
    return [(path[i], path[i + 1]) for i in range(max(len(path) - 1, 0))]


def parse_triplets(value: Any, representative_path: Any = "") -> list[tuple[str, str, str]]:
    text = "" if value is None or pd.isna(value) else str(value).strip()
    triplets: list[tuple[str, str, str]] = []
    for a, b, c in re.findall(r"(\d+)\s*-\s*(\d+)\s*-\s*(\d+)", text):
        triplets.append((normalize_asn(a), normalize_asn(b), normalize_asn(c)))
    if triplets:
        return triplets
    path = parse_as_path(representative_path)
    return [(path[i], path[i + 1], path[i + 2]) for i in range(max(len(path) - 2, 0))]


def relation_state(found: bool, relation_type: str, conflict: bool = False) -> str:
    if conflict:
        return "conflicting"
    if found and relation_type in {"p2p", "p2c_or_c2p_raw"}:
        return "aligned_medium"
    if found:
        return "diagnostic_only"
    return "unavailable"


def possible_valley_transition(rel_ab: str, rel_bc: str, dir_ab: str, dir_bc: str) -> bool:
    """Conservative diagnostic flag only.

    CAIDA -1 direction is preserved as raw orientation in the P0b cache, so this
    is intentionally narrow and only marks candidates for a later R-2C-P2
    verifier.
    """

    if rel_ab == "unknown" or rel_bc == "unknown":
        return False
    if rel_ab == "p2p" and rel_bc == "p2p":
        return True
    return dir_ab == "raw_-1_reverse_as2_to_as1" and dir_bc == "raw_-1_forward_as1_to_as2"


def load_asrel_lookup(args: argparse.Namespace, warnings: list[str]) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, Any]]:
    metadata = read_json(args.asrel_metadata_file)
    asrel = read_parquet_required(args.asrel_cache_file)
    required = {"as_left", "as_right", "rel_type", "relation_from_left_to_right", "rel_direction_note", "source_snapshot_date", "provenance_json"}
    missing = sorted(required - set(asrel.columns))
    if missing:
        raise ValueError(f"AS-rel cache missing columns: {missing}")

    asrel = asrel[list(required)].copy()
    asrel["as_left"] = asrel["as_left"].map(normalize_asn)
    asrel["as_right"] = asrel["as_right"].map(normalize_asn)
    before = len(asrel)
    conflict_pairs = (
        asrel.groupby(["as_left", "as_right"])["rel_type"].nunique(dropna=False).reset_index(name="rel_type_count")
    )
    conflict_count = int((conflict_pairs["rel_type_count"] > 1).sum())
    if conflict_count:
        warnings.append(f"AS-rel cache has {conflict_count} directed pairs with multiple relation types; first record used and conflict marked only in summary.")
    asrel = asrel.drop_duplicates(["as_left", "as_right"], keep="first")
    if len(asrel) != before:
        warnings.append(f"AS-rel cache deduplicated from {before} to {len(asrel)} directed lookup rows.")

    lookup: dict[tuple[str, str], dict[str, Any]] = {}
    for row in asrel.itertuples(index=False):
        lookup[(row.as_left, row.as_right)] = {
            "relation_type": str(row.rel_type) if pd.notna(row.rel_type) else "unknown",
            "relation_direction_note": str(row.rel_direction_note) if pd.notna(row.rel_direction_note) else "",
            "relation_from_left_to_right": str(row.relation_from_left_to_right) if pd.notna(row.relation_from_left_to_right) else "",
            "source_snapshot_date": str(row.source_snapshot_date) if pd.notna(row.source_snapshot_date) else str(metadata.get("snapshot_date", "")),
            "relation_provenance": str(row.provenance_json) if pd.notna(row.provenance_json) else "{}",
        }
    metadata["deduplicated_directed_lookup_rows"] = len(lookup)
    metadata["directed_pair_conflict_count"] = conflict_count
    return lookup, metadata


def lookup_pair(lookup: dict[tuple[str, str], dict[str, Any]], left: str, right: str) -> dict[str, Any]:
    hit = lookup.get((normalize_asn(left), normalize_asn(right)))
    if hit:
        return {
            "relation_found": True,
            "relation_type": hit.get("relation_type", "unknown"),
            "relation_direction_note": hit.get("relation_direction_note", ""),
            "relation_from_left_to_right": hit.get("relation_from_left_to_right", ""),
            "source_snapshot_date": hit.get("source_snapshot_date", ""),
            "relation_provenance": hit.get("relation_provenance", "{}"),
            "relation_evidence_state": relation_state(True, str(hit.get("relation_type", "unknown"))),
        }
    return {
        "relation_found": False,
        "relation_type": "unknown",
        "relation_direction_note": "no AS relationship record found in aligned CAIDA cache",
        "relation_from_left_to_right": "unknown",
        "source_snapshot_date": "",
        "relation_provenance": "{}",
        "relation_evidence_state": "unavailable",
    }


def build_pair_lookup(pair_targets: pd.DataFrame, lookup: dict[tuple[str, str], dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for row in pair_targets.itertuples(index=False):
        pairs = parse_pairs(getattr(row, "adjacent_as_pairs", ""), getattr(row, "representative_as_path", ""))
        if not pairs:
            rows.append(
                {
                    "target_id": getattr(row, "target_id", ""),
                    "incident_id": getattr(row, "incident_id", ""),
                    "as_left": "",
                    "as_right": "",
                    **lookup_pair(lookup, "", ""),
                    "is_inferred_evidence": True,
                }
            )
            continue
        for left, right in pairs:
            hit = lookup_pair(lookup, left, right)
            rows.append(
                {
                    "target_id": getattr(row, "target_id", ""),
                    "incident_id": getattr(row, "incident_id", ""),
                    "as_left": left,
                    "as_right": right,
                    **hit,
                    "is_inferred_evidence": True,
                }
            )
    return pd.DataFrame(rows)


def build_triplet_lookup(triplet_targets: pd.DataFrame, lookup: dict[tuple[str, str], dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for row in triplet_targets.itertuples(index=False):
        triplets = parse_triplets(getattr(row, "triplets", ""), getattr(row, "representative_as_path", ""))
        if not triplets:
            rows.append(
                {
                    "target_id": getattr(row, "target_id", ""),
                    "incident_id": getattr(row, "incident_id", ""),
                    "triplet": "",
                    "as_a": "",
                    "as_b": "",
                    "as_c": "",
                    "rel_ab": "unknown",
                    "rel_bc": "unknown",
                    "rel_ab_found": False,
                    "rel_bc_found": False,
                    "triplet_relation_pattern": "unavailable",
                    "triplet_unknown_count": 2,
                    "triplet_unknown_rate": 1.0,
                    "possible_valley_transition_flag": False,
                    "triplet_evidence_state": "unavailable",
                    "triplet_note": "no usable triplet target",
                }
            )
            continue
        for a, b, c in triplets:
            ab = lookup_pair(lookup, a, b)
            bc = lookup_pair(lookup, b, c)
            rel_ab = str(ab["relation_type"])
            rel_bc = str(bc["relation_type"])
            unknown_count = int(not ab["relation_found"]) + int(not bc["relation_found"])
            flag = possible_valley_transition(
                rel_ab,
                rel_bc,
                str(ab["relation_from_left_to_right"]),
                str(bc["relation_from_left_to_right"]),
            )
            if unknown_count == 0:
                state = "aligned_medium"
                note = "both adjacent AS relationships found; diagnostic triplet evidence only"
            elif unknown_count == 1:
                state = "aligned_weak"
                note = "one adjacent AS relationship missing; insufficient for verifier verdict"
            else:
                state = "unavailable"
                note = "both adjacent AS relationships missing"
            if flag:
                note = "possible valley/peer-transit transition candidate; diagnostic only"
            rows.append(
                {
                    "target_id": getattr(row, "target_id", ""),
                    "incident_id": getattr(row, "incident_id", ""),
                    "triplet": f"{a}-{b}-{c}",
                    "as_a": a,
                    "as_b": b,
                    "as_c": c,
                    "rel_ab": rel_ab,
                    "rel_bc": rel_bc,
                    "rel_ab_found": bool(ab["relation_found"]),
                    "rel_bc_found": bool(bc["relation_found"]),
                    "triplet_relation_pattern": f"{rel_ab} -> {rel_bc}",
                    "triplet_unknown_count": unknown_count,
                    "triplet_unknown_rate": unknown_count / 2.0,
                    "possible_valley_transition_flag": flag,
                    "triplet_evidence_state": state,
                    "triplet_note": note,
                }
            )
    return pd.DataFrame(rows)


def full_path_relation_sequence(full_targets: pd.DataFrame, lookup: dict[tuple[str, str], dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for row in full_targets.itertuples(index=False):
        path = parse_as_path(getattr(row, "representative_as_path", ""))
        pairs = parse_pairs(getattr(row, "adjacent_as_pairs", ""), getattr(row, "representative_as_path", ""))
        if len(path) < 2 and not pairs:
            rows.append(
                {
                    "target_id": getattr(row, "target_id", ""),
                    "incident_id": getattr(row, "incident_id", ""),
                    "representative_as_path": getattr(row, "representative_as_path", ""),
                    "path_len": safe_int(getattr(row, "path_len", 0)),
                    "adjacent_pair_count": 0,
                    "matched_pair_count": 0,
                    "unknown_pair_count": 0,
                    "unknown_pair_rate": 1.0,
                    "relation_sequence": "",
                    "relation_sequence_compact": "",
                    "path_relation_pattern_class": "too_short_or_unusable",
                    "possible_valley_free_violation_flag": False,
                    "path_legality_smoke_state": "path_evidence_unavailable",
                    "path_legality_note": "path too short or missing; no route-leak verdict generated",
                }
            )
            continue

        relation_types: list[str] = []
        relation_dirs: list[str] = []
        matched = 0
        possible_flags = 0
        for left, right in pairs:
            hit = lookup_pair(lookup, left, right)
            relation_types.append(str(hit["relation_type"]))
            relation_dirs.append(str(hit["relation_from_left_to_right"]))
            if hit["relation_found"]:
                matched += 1
        for i in range(max(len(relation_types) - 1, 0)):
            if possible_valley_transition(relation_types[i], relation_types[i + 1], relation_dirs[i], relation_dirs[i + 1]):
                possible_flags += 1

        pair_count = len(pairs)
        unknown = pair_count - matched
        unknown_rate = (unknown / pair_count) if pair_count else 1.0
        if pair_count == 0:
            pattern_class = "too_short_or_unusable"
            state = "path_evidence_unavailable"
            note = "no adjacent AS pairs available"
        elif unknown_rate >= 0.5:
            pattern_class = "high_unknown_relation_sequence"
            state = "path_evidence_unavailable"
            note = "high unknown relation share; unavailable/insufficient path evidence"
        elif possible_flags:
            pattern_class = "possible_valley_transition"
            state = "diagnostic_path_evidence"
            note = "possible valley/peer-transit transition candidate; diagnostic only"
        elif unknown > 0:
            pattern_class = "partially_unknown_relation_sequence"
            state = "path_evidence_insufficient"
            note = "partial relation sequence; insufficient for route-leak verdict"
        else:
            pattern_class = "fully_known_relation_sequence"
            state = "aligned_path_evidence"
            note = "full relation sequence found; still inferred evidence only"

        rows.append(
            {
                "target_id": getattr(row, "target_id", ""),
                "incident_id": getattr(row, "incident_id", ""),
                "representative_as_path": getattr(row, "representative_as_path", ""),
                "path_len": safe_int(getattr(row, "path_len", len(path))),
                "adjacent_pair_count": pair_count,
                "matched_pair_count": matched,
                "unknown_pair_count": unknown,
                "unknown_pair_rate": unknown_rate,
                "relation_sequence": ";".join(relation_types),
                "relation_sequence_compact": ">".join(relation_types),
                "path_relation_pattern_class": pattern_class,
                "possible_valley_free_violation_flag": possible_flags > 0,
                "path_legality_smoke_state": state,
                "path_legality_note": note,
            }
        )
    return pd.DataFrame(rows)


def mode_or_empty(series: pd.Series) -> str:
    if series.empty:
        return ""
    mode = series.dropna().astype(str).mode()
    return str(mode.iloc[0]) if not mode.empty else ""


def aggregate_incident_path_evidence(
    pair_lookup: pd.DataFrame,
    triplet_lookup: pd.DataFrame,
    full_seq: pd.DataFrame,
    r2b: pd.DataFrame,
) -> pd.DataFrame:
    pair_agg = (
        pair_lookup.groupby("incident_id")
        .agg(
            pair_target_count=("target_id", "nunique"),
            matched_pair_count=("relation_found", "sum"),
            unknown_pair_count=("relation_found", lambda s: int((~s.astype(bool)).sum())),
            pair_row_count=("target_id", "size"),
        )
        .reset_index()
    )

    triplet_agg = (
        triplet_lookup.groupby("incident_id")
        .agg(
            triplet_target_count=("target_id", "nunique"),
            possible_valley_transition_count=("possible_valley_transition_flag", "sum"),
            triplet_row_count=("target_id", "size"),
        )
        .reset_index()
    )

    full_agg = (
        full_seq.groupby("incident_id")
        .agg(
            full_path_target_count=("target_id", "nunique"),
            path_target_count=("target_id", "nunique"),
            high_unknown_path_count=(
                "path_relation_pattern_class",
                lambda s: int((s == "high_unknown_relation_sequence").sum()),
            ),
            dominant_path_relation_pattern_class=("path_relation_pattern_class", mode_or_empty),
            dominant_relation_sequence=("relation_sequence_compact", mode_or_empty),
            avg_unknown_pair_rate=("unknown_pair_rate", "mean"),
        )
        .reset_index()
    )

    base_cols = [
        "incident_id",
        "verifier_verdict_vrp",
        "component_purity_class",
        "verification_queue",
        "family",
        "member_count",
        "high_count",
        "needs_count",
        "high_share",
        "dominant_pair_rpki_status",
        "pattern_B_member_count",
        "route_leak_like_review_count",
    ]
    base_cols = [c for c in base_cols if c in r2b.columns]
    out = r2b[base_cols].copy()
    out = out.rename(
        columns={
            "verifier_verdict_vrp": "r2b_verifier_verdict",
            "component_purity_class": "r2b_component_purity_class",
        }
    )
    for agg in [pair_agg, triplet_agg, full_agg]:
        out = out.merge(agg, on="incident_id", how="left")

    numeric_defaults = [
        "pair_target_count",
        "matched_pair_count",
        "unknown_pair_count",
        "pair_row_count",
        "triplet_target_count",
        "possible_valley_transition_count",
        "triplet_row_count",
        "full_path_target_count",
        "path_target_count",
        "high_unknown_path_count",
    ]
    for col in numeric_defaults:
        if col in out.columns:
            out[col] = out[col].fillna(0).astype(int)
    if "avg_unknown_pair_rate" not in out.columns:
        out["avg_unknown_pair_rate"] = 1.0
    out["unknown_pair_rate"] = out.apply(
        lambda r: (safe_float(r.get("unknown_pair_count")) / safe_float(r.get("pair_row_count"), 1.0))
        if safe_float(r.get("pair_row_count")) > 0
        else 1.0,
        axis=1,
    )
    out["possible_valley_transition_share"] = out.apply(
        lambda r: safe_float(r.get("possible_valley_transition_count")) / safe_float(r.get("triplet_row_count"), 1.0)
        if safe_float(r.get("triplet_row_count")) > 0
        else 0.0,
        axis=1,
    )

    def classify_state(row: pd.Series) -> str:
        if safe_int(row.get("path_target_count")) == 0 and safe_int(row.get("pair_row_count")) == 0:
            return "unavailable"
        if safe_int(row.get("possible_valley_transition_count")) > 0:
            return "diagnostic_only"
        if safe_float(row.get("unknown_pair_rate")) <= 0.10 and safe_int(row.get("matched_pair_count")) > 0:
            return "aligned_medium"
        if safe_float(row.get("unknown_pair_rate")) <= 0.35 and safe_int(row.get("matched_pair_count")) > 0:
            return "aligned_weak"
        if safe_int(row.get("matched_pair_count")) > 0:
            return "evidence_insufficient"
        return "unavailable"

    def classify_purity(row: pd.Series) -> str:
        if safe_int(row.get("path_target_count")) == 0:
            return "path_unusable"
        if safe_float(row.get("unknown_pair_rate")) >= 0.50:
            return "path_high_unknown"
        pattern = str(row.get("dominant_path_relation_pattern_class", ""))
        if pattern == "fully_known_relation_sequence":
            return "path_pure_dominant"
        if pattern in {"partially_unknown_relation_sequence", "possible_valley_transition"}:
            return "path_mostly_dominant"
        return "path_mixed"

    out["path_evidence_state"] = out.apply(classify_state, axis=1)
    out["path_component_purity_class"] = out.apply(classify_purity, axis=1)
    out["route_leak_like_diagnostic_flag"] = (
        (out.get("route_leak_like_review_count", 0).fillna(0).astype(int) > 0)
        | (out["possible_valley_transition_count"] > 0)
    )
    out["path_manipulation_like_diagnostic_flag"] = (
        (out.get("pattern_B_member_count", 0).fillna(0).astype(int) > 0)
        & out["path_evidence_state"].isin(["aligned_medium", "aligned_weak", "diagnostic_only"])
    )
    out["safe_for_verifier_candidate_flag"] = out["path_evidence_state"].isin(["aligned_medium", "diagnostic_only"]) & ~(
        out["path_component_purity_class"] == "path_high_unknown"
    )
    out["path_evidence_note"] = out.apply(
        lambda r: (
            "diagnostic route-leak/path-transition candidate; no route-leak verdict generated"
            if r["route_leak_like_diagnostic_flag"]
            else "path evidence attached as inferred AS relationship smoke"
            if r["path_evidence_state"] in {"aligned_medium", "aligned_weak", "diagnostic_only"}
            else "path evidence insufficient or unavailable"
        ),
        axis=1,
    )
    return out


def combined_origin_path(incident_path: pd.DataFrame) -> pd.DataFrame:
    df = incident_path.copy()
    r2b_verdict = df["r2b_verifier_verdict"].fillna("")
    rpki = df.get("dominant_pair_rpki_status", pd.Series([""] * len(df))).fillna("")
    path_supported = df["safe_for_verifier_candidate_flag"].fillna(False)
    path_diag = df["route_leak_like_diagnostic_flag"].fillna(False) | df["path_manipulation_like_diagnostic_flag"].fillna(False)
    origin_supported = r2b_verdict.isin(["evidence_supported_suspicious", "strongly_supported_suspicious"])
    background = r2b_verdict.eq("background_like_but_unconfirmed")

    classes: list[str] = []
    actions: list[str] = []
    notes: list[str] = []
    for i in range(len(df)):
        if r2b_verdict.iloc[i] == "evidence_conflict" or df["path_evidence_state"].iloc[i] == "conflict":
            classes.append("origin_path_conflict")
            actions.append("mark_conflict_for_review")
            notes.append("origin/path evidence conflict remains visible")
        elif origin_supported.iloc[i] and path_supported.iloc[i]:
            classes.append("origin_and_path_supported")
            actions.append("candidate_for_r2c_p2_verifier")
            notes.append("origin-side verifier support plus path diagnostic support")
        elif origin_supported.iloc[i]:
            classes.append("origin_supported_only")
            actions.append("keep_r2b_verdict")
            notes.append("R-2B origin evidence remains the main support")
        elif path_supported.iloc[i] and rpki.iloc[i] == "valid":
            classes.append("origin_valid_path_suspicious")
            actions.append("upgrade_to_path_review_candidate")
            notes.append("RPKI-valid dominant origin with path diagnostic evidence; not benign")
        elif path_supported.iloc[i] and rpki.iloc[i] == "unknown":
            classes.append("origin_unknown_path_suspicious")
            actions.append("upgrade_to_path_review_candidate")
            notes.append("RPKI unknown with path diagnostic evidence; needs R-2C-P2")
        elif path_supported.iloc[i] or path_diag.iloc[i]:
            classes.append("path_supported_only")
            actions.append("candidate_for_r2c_p2_verifier")
            notes.append("path evidence is diagnostic support only")
        elif background.iloc[i]:
            classes.append("background_like_combined")
            actions.append("keep_insufficient_wait_more_evidence")
            notes.append("background-like remains unconfirmed, not normal truth")
        else:
            classes.append("insufficient_combined_evidence")
            actions.append("keep_insufficient_wait_more_evidence")
            notes.append("combined origin/path evidence insufficient")

    df["combined_origin_path_evidence_class"] = classes
    df["combined_evidence_note"] = notes
    df["recommended_r2c_verifier_action"] = actions
    return df[
        [
            "incident_id",
            "r2b_verifier_verdict",
            "dominant_pair_rpki_status",
            "r2b_component_purity_class",
            "path_evidence_state",
            "route_leak_like_diagnostic_flag",
            "path_manipulation_like_diagnostic_flag",
            "combined_origin_path_evidence_class",
            "combined_evidence_note",
            "recommended_r2c_verifier_action",
        ]
    ]


def topk_path_review(combined: pd.DataFrame, incident_path: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = incident_path.merge(
        combined[
            [
                "incident_id",
                "combined_origin_path_evidence_class",
                "recommended_r2c_verifier_action",
            ]
        ],
        on="incident_id",
        how="left",
    )
    df["path_review_score"] = (
        df["route_leak_like_diagnostic_flag"].astype(int) * 30
        + df["path_manipulation_like_diagnostic_flag"].astype(int) * 25
        + df["safe_for_verifier_candidate_flag"].astype(int) * 20
        + (df["r2b_verifier_verdict"].fillna("").eq("evidence_supported_suspicious")).astype(int) * 20
        + (df["r2b_verifier_verdict"].fillna("").eq("evidence_conflict")).astype(int) * 10
        + df["high_count"].fillna(0).map(lambda x: min(math.log1p(max(float(x), 0.0)) * 2.0, 15.0))
        - df["unknown_pair_rate"].fillna(1.0) * 10
    )
    top_candidates = df.sort_values(["path_review_score", "member_count"], ascending=[False, False]).head(500).copy()
    rows = []
    for k in [50, 100, 500]:
        top = df.sort_values(["path_review_score", "member_count"], ascending=[False, False]).head(k)
        if top.empty:
            rows.append({"topk": k, "review_density": 0.0, "notes": "no candidates"})
            continue
        path_supported = top["safe_for_verifier_candidate_flag"].astype(bool)
        combined_supported = top["combined_origin_path_evidence_class"].isin(
            ["origin_and_path_supported", "path_supported_only", "origin_valid_path_suspicious", "origin_unknown_path_suspicious"]
        )
        rows.append(
            {
                "topk": k,
                "route_leak_like_diagnostic_count": int(top["route_leak_like_diagnostic_flag"].sum()),
                "path_supported_count": int(path_supported.sum()),
                "high_unknown_count": int((top["path_component_purity_class"] == "path_high_unknown").sum()),
                "evidence_supported_from_r2b_count": int((top["r2b_verifier_verdict"] == "evidence_supported_suspicious").sum()),
                "combined_origin_path_supported_count": int(combined_supported.sum()),
                "conflict_count": int((top["r2b_verifier_verdict"] == "evidence_conflict").sum()),
                "review_density": float(combined_supported.sum() / len(top)),
                "notes": "deterministic smoke score; no model training",
            }
        )
    return pd.DataFrame(rows), top_candidates


def write_report(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# R-2C-P1 Path Relation Lookup Smoke Report",
        "",
        f"Run id: `{summary['run_id']}`",
        f"Run date: `{summary['run_date']}`",
        f"Mode: `{'full' if summary['full_run'] else 'sample'}`",
        "",
        "## Key Results",
        "",
        f"- AS-pair expanded rows: `{summary['as_pair_lookup']['expanded_pair_rows']}`",
        f"- AS-pair match rate: `{summary['as_pair_lookup']['match_rate']:.6f}`",
        f"- Triplet rows: `{summary['triplet_lookup']['triplet_rows']}`",
        f"- Full-path rows: `{summary['full_path_lookup']['full_path_rows']}`",
        f"- Incident path evidence rows: `{summary['incident_path_evidence']['incident_rows']}`",
        f"- Route-leak-like diagnostic candidates: `{summary['incident_path_evidence']['route_leak_like_diagnostic_candidate_count']}`",
        f"- Path-manipulation-like diagnostic candidates: `{summary['incident_path_evidence']['path_manipulation_like_diagnostic_candidate_count']}`",
        "",
        "## Safety Answers",
        "",
        "- 本轮是否生成 route-leak verdict？没有。",
        "- 本轮是否修改 R-2B verifier verdict？没有。",
        "- AS-rel 是否被当作 ground truth？没有，只作为 inferred path evidence。",
        "- possible valley-free violation 是否被当作 confirmed route leak？没有，只作为 diagnostic candidate。",
        "- NO_EXPORT/community branch 是否在本轮执行？没有，后续 R-2D-0。",
        "- AS Hegemony 是否在本轮执行？没有，后续 L1/L2 ranker。",
        "- learning layer 是否可以正式训练？不能；可以继续 L1 design。",
        "",
        "## AS-pair Lookup",
        "",
        f"- Matched rows: `{summary['as_pair_lookup']['matched_pair_rows']}`",
        f"- Unmatched rows: `{summary['as_pair_lookup']['unmatched_pair_rows']}`",
        f"- Relation type distribution: `{summary['as_pair_lookup']['relation_type_distribution']}`",
        "",
        "## Triplet Relation Patterns",
        "",
        f"- Pattern distribution top values: `{summary['triplet_lookup']['triplet_pattern_top']}`",
        f"- Possible valley/peer-transit diagnostic rows: `{summary['triplet_lookup']['possible_valley_transition_rows']}`",
        "",
        "## Full-path Relation Sequence",
        "",
        f"- Unknown pair rate mean: `{summary['full_path_lookup']['mean_unknown_pair_rate']:.6f}`",
        f"- Path pattern distribution: `{summary['full_path_lookup']['path_pattern_distribution']}`",
        "",
        "## Incident-level Path Evidence",
        "",
        f"- Path evidence distribution: `{summary['incident_path_evidence']['path_evidence_state_distribution']}`",
        f"- Component purity distribution: `{summary['incident_path_evidence']['path_component_purity_distribution']}`",
        "",
        "## Combined Origin + Path Evidence",
        "",
        f"- Combined class distribution: `{summary['combined_evidence']['combined_class_distribution']}`",
        f"- Recommended action distribution: `{summary['combined_evidence']['recommended_action_distribution']}`",
        "",
        "## Top-K Path Review Smoke",
        "",
        "This queue is deterministic and model-free. It is a workload smoke, not a trained ranking result.",
        "",
        f"- Top-K summary: `{summary['topk_review_summary']}`",
        "",
        "## Next Step",
        "",
        "Proceed to R-2C-P2 route-leak/path-legality verifier smoke. Keep AS-rel as inferred evidence, and add ASPA/BGP Roles/OTC feasibility before any stronger path-legality claim.",
        "",
        "## Warnings",
        "",
    ]
    for warning in summary.get("warnings", []):
        lines.append(f"- {warning}")
    if not summary.get("warnings"):
        lines.append("- None.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    warnings: list[str] = []
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    pair_targets = maybe_sample(read_parquet_required(args.as_pair_targets_file), args)
    triplet_targets = maybe_sample(read_parquet_required(args.triplet_targets_file), args)
    full_targets = maybe_sample(read_parquet_required(args.full_path_targets_file), args)
    r2b = read_parquet_required(args.r2b_verifier_table)
    if not args.full_run and args.sample_rows:
        sample_ids = set(full_targets["incident_id"].astype(str))
        r2b = r2b[r2b["incident_id"].astype(str).isin(sample_ids)].copy()

    # Required by the contract; read existence/schemas but do not use them for a
    # new verdict or detector modification.
    _tickets = read_parquet_required(args.incident_tickets_file)
    _membership_schema = pd.read_parquet(args.incident_membership_file, columns=["incident_id"]).head(1)
    del _tickets, _membership_schema

    asrel_lookup, asrel_metadata = load_asrel_lookup(args, warnings)
    if str(asrel_metadata.get("usable_for_r2c", "true")).lower() == "false":
        warnings.append("AS-rel metadata marks cache unusable for R-2C; output remains diagnostic only.")

    pair_lookup = build_pair_lookup(pair_targets, asrel_lookup)
    triplet_lookup = build_triplet_lookup(triplet_targets, asrel_lookup)
    full_seq = full_path_relation_sequence(full_targets, asrel_lookup)
    incident_path = aggregate_incident_path_evidence(pair_lookup, triplet_lookup, full_seq, r2b)
    combined = combined_origin_path(incident_path)
    topk_summary, topk_candidates = topk_path_review(combined, incident_path)

    write_table(pair_lookup, out_dir / "r2c_as_pair_relation_lookup.parquet", out_dir / "r2c_as_pair_relation_lookup.csv")
    write_table(triplet_lookup, out_dir / "r2c_triplet_relation_lookup.parquet", out_dir / "r2c_triplet_relation_lookup.csv")
    write_table(full_seq, out_dir / "r2c_full_path_relation_sequence.parquet", out_dir / "r2c_full_path_relation_sequence.csv")
    write_table(incident_path, out_dir / "r2c_incident_path_evidence_table.parquet", out_dir / "r2c_incident_path_evidence_table.csv")
    write_table(combined, out_dir / "r2c_combined_origin_path_evidence_table.parquet", out_dir / "r2c_combined_origin_path_evidence_table.csv")
    topk_summary.to_csv(out_dir / "r2c_topk_path_review_simulation.csv", index=False)
    topk_candidates.to_csv(out_dir / "r2c_topk_path_review_candidates.csv", index=False)

    path_dist = incident_path["path_evidence_state"].value_counts().rename_axis("path_evidence_state").reset_index(name="incident_count")
    path_dist.to_csv(out_dir / "r2c_path_evidence_distribution.csv", index=False)
    incident_path[incident_path["route_leak_like_diagnostic_flag"]].to_csv(
        out_dir / "r2c_route_leak_like_diagnostic_candidates.csv", index=False
    )
    incident_path[incident_path["path_component_purity_class"] == "path_high_unknown"].to_csv(
        out_dir / "r2c_high_unknown_path_cases.csv", index=False
    )
    incident_path[incident_path["path_evidence_state"] == "conflict"].to_csv(out_dir / "r2c_path_conflict_cases.csv", index=False)
    combined["combined_origin_path_evidence_class"].value_counts().rename_axis("combined_origin_path_evidence_class").reset_index(
        name="incident_count"
    ).to_csv(out_dir / "r2c_combined_evidence_distribution.csv", index=False)

    pair_summary = {
        "target_rows": int(len(pair_targets)),
        "expanded_pair_rows": int(len(pair_lookup)),
        "matched_pair_rows": int(pair_lookup["relation_found"].sum()) if not pair_lookup.empty else 0,
        "unmatched_pair_rows": int((~pair_lookup["relation_found"].astype(bool)).sum()) if not pair_lookup.empty else 0,
        "match_rate": float(pair_lookup["relation_found"].mean()) if not pair_lookup.empty else 0.0,
        "relation_type_distribution": distribution(pair_lookup["relation_type"]) if not pair_lookup.empty else {},
    }
    triplet_summary = {
        "target_rows": int(len(triplet_targets)),
        "triplet_rows": int(len(triplet_lookup)),
        "possible_valley_transition_rows": int(triplet_lookup["possible_valley_transition_flag"].sum()) if not triplet_lookup.empty else 0,
        "triplet_evidence_state_distribution": distribution(triplet_lookup["triplet_evidence_state"]) if not triplet_lookup.empty else {},
        "triplet_pattern_top": top_distribution(triplet_lookup["triplet_relation_pattern"], 15) if not triplet_lookup.empty else [],
    }
    full_summary = {
        "target_rows": int(len(full_targets)),
        "full_path_rows": int(len(full_seq)),
        "mean_unknown_pair_rate": float(full_seq["unknown_pair_rate"].mean()) if not full_seq.empty else 0.0,
        "path_pattern_distribution": distribution(full_seq["path_relation_pattern_class"]) if not full_seq.empty else {},
        "path_legality_smoke_state_distribution": distribution(full_seq["path_legality_smoke_state"]) if not full_seq.empty else {},
    }
    incident_summary = {
        "incident_rows": int(len(incident_path)),
        "path_evidence_state_distribution": distribution(incident_path["path_evidence_state"]),
        "path_component_purity_distribution": distribution(incident_path["path_component_purity_class"]),
        "route_leak_like_diagnostic_candidate_count": int(incident_path["route_leak_like_diagnostic_flag"].sum()),
        "path_manipulation_like_diagnostic_candidate_count": int(incident_path["path_manipulation_like_diagnostic_flag"].sum()),
    }
    combined_summary = {
        "combined_class_distribution": distribution(combined["combined_origin_path_evidence_class"]),
        "recommended_action_distribution": distribution(combined["recommended_r2c_verifier_action"]),
    }

    summary = {
        "run_id": args.run_id,
        "run_date": args.run_date,
        "full_run": bool(args.full_run),
        "sample_rows": 0 if args.full_run else int(args.sample_rows or 0),
        "asrel_snapshot_date": asrel_metadata.get("snapshot_date", asrel_metadata.get("source_snapshot_date", "")),
        "asrel_alignment_delta_days": asrel_metadata.get("alignment_delta_days"),
        "as_pair_lookup": pair_summary,
        "triplet_lookup": triplet_summary,
        "full_path_lookup": full_summary,
        "incident_path_evidence": incident_summary,
        "combined_evidence": combined_summary,
        "topk_review_summary": topk_summary.to_dict(orient="records"),
        "route_leak_verdict_generated": False,
        "r2b_verifier_verdict_modified": False,
        "asrel_used_as_ground_truth": False,
        "learning_layer_trained": False,
        "no_export_or_communities_executed": False,
        "as_hegemony_executed": False,
        "can_enter_r2c_p2": True,
        "can_enter_learning_layer": False,
        "recommended_next_step": "R-2C-P2 route-leak/path-legality verifier smoke; keep AS-rel diagnostic and add ASPA/BGP Roles/OTC feasibility before stronger claims.",
        "safety_notes": SAFETY_NOTES,
        "warnings": warnings,
        "status": "completed",
    }
    write_json(out_dir / "r2c_as_pair_relation_summary.json", pair_summary)
    write_json(out_dir / "r2c_triplet_relation_summary.json", triplet_summary)
    write_json(out_dir / "r2c_full_path_relation_summary.json", full_summary)
    write_json(out_dir / "r2c_p1_summary.json", summary)
    write_report(out_dir / "r2c_p1_report.md", summary)
    print(json.dumps(summary, indent=2, sort_keys=True, default=json_default))


if __name__ == "__main__":
    main()
