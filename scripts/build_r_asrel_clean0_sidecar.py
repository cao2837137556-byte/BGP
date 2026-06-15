#!/usr/bin/env python3
"""Build R-ASREL-CLEAN-0 2024-aligned AS-rel sidecar.

This script creates an independent sidecar for candidate/event rows using the
2024-04-01 CAIDA AS relationship cache. It does not modify the old pipeline,
does not overwrite event_units, does not train a model, and does not produce
route-leak truth labels.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd


RUN_ID_DEFAULT = "s2a_baseline_v01_pilot_6h_april16"
RUN_DATE_DEFAULT = "2024-04-16"
ASREL_SNAPSHOT_DEFAULT = "2024-04-01"

SAFETY_NOTES = [
    "AS-rel evidence is inferred evidence, not route-leak truth",
    "AS-rel matched path is not benign",
    "AS-rel unknown path is not suspicious by itself",
    "possible_valley_transition is diagnostic only",
    "legacy rel_* fields are audit reference only",
    "this sidecar does not modify old pipeline outputs",
    "this sidecar does not train learning",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=RUN_ID_DEFAULT)
    parser.add_argument("--run-date", default=RUN_DATE_DEFAULT)
    parser.add_argument("--candidates", default="")
    parser.add_argument("--events", default="")
    parser.add_argument("--asrel-cache", default="data/evidence/as_relationships/as_rel_2024-04-01.parquet")
    parser.add_argument("--asrel-metadata", default="data/evidence/as_relationships/as_rel_2024-04-01.metadata.json")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--sample-rows", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, (datetime, date, Path)):
        return str(value)
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=json_default), encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_can_write(paths: list[Path], overwrite: bool) -> None:
    existing = [str(path) for path in paths if path.exists()]
    if existing and not overwrite:
        raise FileExistsError("output exists; pass --overwrite to replace: " + "; ".join(existing))


def resolve_inputs(args: argparse.Namespace) -> tuple[Path, Path, Path, Path, Path]:
    run_root = Path("data") / "runs" / args.run_id
    candidates = Path(args.candidates) if args.candidates else run_root / "candidates" / "candidate_events.parquet"
    events = Path(args.events) if args.events else run_root / "events" / "event_units.parquet"
    asrel_cache = Path(args.asrel_cache)
    asrel_metadata = Path(args.asrel_metadata)
    output_dir = Path(args.output_dir) if args.output_dir else Path("outputs") / "r_asrel_clean_0" / args.run_id
    return candidates, events, asrel_cache, asrel_metadata, output_dir


def read_parquet_required(path: Path, columns: list[str] | None = None) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"required input missing: {path}")
    return pd.read_parquet(path, columns=columns)


def normalize_asn(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
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
    if value is None:
        return []
    try:
        if pd.isna(value):
            return []
    except (TypeError, ValueError):
        pass
    tokens = [normalize_asn(x) for x in re.findall(r"\d+", str(value))]
    cleaned: list[str] = []
    prev = ""
    for token in tokens:
        if token and token != prev:
            cleaned.append(token)
            prev = token
    return cleaned


def legacy_token_from_relation(direction: str) -> str:
    if direction == "p2p":
        return "p2p"
    if direction == "raw_-1_forward_as1_to_as2":
        return "p2c"
    if direction == "raw_-1_reverse_as2_to_as1":
        return "c2p"
    return "unk"


def load_asrel_lookup(asrel_cache: Path, asrel_metadata: Path) -> tuple[dict[tuple[str, str], dict[str, str]], dict[str, Any]]:
    metadata = read_json(asrel_metadata)
    required = [
        "as_left",
        "as_right",
        "rel_type",
        "relation_from_left_to_right",
        "source",
        "snapshot_date",
        "run_date",
        "alignment_delta_days",
        "aligned_to_run_date",
        "relation_confidence",
        "source_snapshot_date",
        "provenance_json",
    ]
    asrel = read_parquet_required(asrel_cache, columns=required)
    asrel["as_left"] = asrel["as_left"].map(normalize_asn)
    asrel["as_right"] = asrel["as_right"].map(normalize_asn)

    before = len(asrel)
    conflicts = (
        asrel.groupby(["as_left", "as_right"])["relation_from_left_to_right"]
        .nunique(dropna=False)
        .reset_index(name="relation_type_count")
    )
    conflict_count = int((conflicts["relation_type_count"] > 1).sum())
    asrel = asrel.drop_duplicates(["as_left", "as_right"], keep="first")

    lookup: dict[tuple[str, str], dict[str, str]] = {}
    for row in asrel.itertuples(index=False):
        direction = str(row.relation_from_left_to_right) if pd.notna(row.relation_from_left_to_right) else "unknown"
        lookup[(row.as_left, row.as_right)] = {
            "rel_type": str(row.rel_type) if pd.notna(row.rel_type) else "unknown",
            "relation_from_left_to_right": direction,
            "legacy_token": legacy_token_from_relation(direction),
            "source": str(row.source) if pd.notna(row.source) else "CAIDA AS Relationships serial-2",
            "snapshot_date": str(row.snapshot_date) if pd.notna(row.snapshot_date) else str(metadata.get("snapshot_date", "")),
            "run_date": str(row.run_date) if pd.notna(row.run_date) else str(metadata.get("run_date", "")),
            "alignment_delta_days": str(row.alignment_delta_days) if pd.notna(row.alignment_delta_days) else str(metadata.get("alignment_delta_days", "")),
            "aligned_to_run_date": str(row.aligned_to_run_date) if pd.notna(row.aligned_to_run_date) else str(metadata.get("aligned_to_run_date", "")),
            "relation_confidence": str(row.relation_confidence) if pd.notna(row.relation_confidence) else str(metadata.get("usable_evidence_strength", "")),
            "source_snapshot_date": str(row.source_snapshot_date) if pd.notna(row.source_snapshot_date) else str(metadata.get("snapshot_date", "")),
            "provenance_json": str(row.provenance_json) if pd.notna(row.provenance_json) else "{}",
        }

    metadata["directed_lookup_rows_before_dedup"] = int(before)
    metadata["directed_lookup_rows_after_dedup"] = int(len(lookup))
    metadata["directed_pair_conflict_count"] = conflict_count
    return lookup, metadata


def valley_status(rels: list[str]) -> tuple[bool, str]:
    if not rels:
        return False, "no_relationship_sequence"
    if "unk" in rels:
        return False, "contains_unknown_edge"
    valid = {"c2p", "p2p", "p2c"}
    if any(rel not in valid for rel in rels):
        return False, "contains_unsupported_edge"

    seen_p2p = 0
    phase = "up"
    for idx, rel in enumerate(rels):
        if rel == "c2p":
            if phase in {"peer", "down"}:
                return True, f"c2p_after_peer_or_down_at_{idx}"
        elif rel == "p2p":
            seen_p2p += 1
            if seen_p2p > 1:
                return True, "multiple_p2p_edges"
            if phase == "down":
                return True, f"p2p_after_down_at_{idx}"
            phase = "peer"
        elif rel == "p2c":
            phase = "down"
    return False, "valley_pattern_not_observed"


def diagnose_path(as_path_clean: Any, lookup: dict[tuple[str, str], dict[str, str]]) -> dict[str, Any]:
    tokens = parse_as_path(as_path_clean)
    if len(tokens) < 2:
        return {
            "as_path_clean_normalized": " ".join(tokens),
            "as_path_len_clean": len(tokens),
            "as_pair_count_2024": 0,
            "asrel_pair_found_count_2024": 0,
            "rel_seq_2024": "",
            "rel_seq_2024_raw": "",
            "rel_unknown_cnt_2024": 0,
            "rel_has_unknown_2024": False,
            "rel_unknown_rate_2024": 0.0,
            "possible_valley_transition_2024": False,
            "path_relation_diagnostic_2024": "no_usable_as_path",
            "path_relation_evidence_state_2024": "unavailable",
            "asrel_pair_detail_2024": "",
            "path_relation_note_2024": "AS path has fewer than two ASNs",
        }

    legacy_rels: list[str] = []
    raw_rels: list[str] = []
    pair_details: list[str] = []
    found = 0
    unknown = 0
    for left, right in zip(tokens[:-1], tokens[1:]):
        hit = lookup.get((left, right))
        if hit:
            found += 1
            legacy = hit["legacy_token"]
            raw = hit["relation_from_left_to_right"]
        else:
            unknown += 1
            legacy = "unk"
            raw = "unknown"
        legacy_rels.append(legacy)
        raw_rels.append(raw)
        pair_details.append(f"{left}-{right}:{legacy}/{raw}")

    pair_count = len(legacy_rels)
    unknown_rate = unknown / pair_count if pair_count else 0.0
    possible_valley, valley_reason = valley_status(legacy_rels)
    if unknown == pair_count:
        diagnostic = "fully_unknown_relation_sequence"
        evidence_state = "unavailable"
        note = "no adjacent AS pair matched the aligned CAIDA cache"
    elif unknown > 0:
        diagnostic = "partially_unknown_relation_sequence"
        evidence_state = "aligned_weak"
        note = "some adjacent AS pairs are unavailable; diagnostic only"
    elif possible_valley:
        diagnostic = "possible_valley_transition"
        evidence_state = "aligned_medium"
        note = f"valley-like pattern candidate ({valley_reason}); diagnostic only"
    else:
        diagnostic = "all_pairs_known_no_valley_diagnostic"
        evidence_state = "aligned_medium"
        note = "all adjacent AS pairs matched; no valley-like diagnostic from this sidecar"

    return {
        "as_path_clean_normalized": " ".join(tokens),
        "as_path_len_clean": len(tokens),
        "as_pair_count_2024": pair_count,
        "asrel_pair_found_count_2024": found,
        "rel_seq_2024": "|".join(legacy_rels),
        "rel_seq_2024_raw": "|".join(raw_rels),
        "rel_unknown_cnt_2024": unknown,
        "rel_has_unknown_2024": bool(unknown > 0),
        "rel_unknown_rate_2024": unknown_rate,
        "possible_valley_transition_2024": bool(possible_valley),
        "path_relation_diagnostic_2024": diagnostic,
        "path_relation_evidence_state_2024": evidence_state,
        "asrel_pair_detail_2024": ";".join(pair_details),
        "path_relation_note_2024": note,
    }


def normalize_rel_seq(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip().lower().replace("unknown", "unk")


def compare_old_new(old_rel: Any, new_rel: Any) -> str:
    old = normalize_rel_seq(old_rel)
    new = normalize_rel_seq(new_rel)
    if old and new and old == new:
        return "old_and_2024_same_sequence"
    if old and new:
        return "old_and_2024_different_sequence"
    if old and not new:
        return "old_available_2024_missing"
    if not old and new:
        return "old_missing_2024_available"
    return "both_missing"


def load_candidate_event_rows(args: argparse.Namespace, candidates_path: Path, events_path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    candidate_columns = [
        "event_id",
        "run_id",
        "prefix",
        "origin_as",
        "as_path_clean",
        "as_path_len",
        "candidate_reasons",
        "candidate_flag",
        "collector_set",
        "collector_count",
        "duration_sec",
    ]
    candidates = read_parquet_required(candidates_path)
    candidate_columns = [col for col in candidate_columns if col in candidates.columns]
    candidates = candidates[candidate_columns].copy()
    input_candidate_rows = len(candidates)
    if args.sample_rows and input_candidate_rows > args.sample_rows:
        candidates = candidates.head(args.sample_rows).copy()

    event_columns = [
        "event_id",
        "collector",
        "first_seen",
        "last_seen",
        "source_file",
        "time_window_sec",
        "rel_seq",
        "rel_unknown_cnt",
        "rel_has_unknown",
    ]
    events = read_parquet_required(events_path)
    input_event_rows = len(events)
    event_columns = [col for col in event_columns if col in events.columns]
    events = events[event_columns].drop_duplicates("event_id", keep="first").copy()

    rows = candidates.merge(events, on="event_id", how="left", suffixes=("", "_event"))
    summary = {
        "candidate_rows_input": int(input_candidate_rows),
        "event_rows_input": int(input_event_rows),
        "sample_rows_used": int(len(candidates)),
        "event_join_matched_rows": int(rows["first_seen"].notna().sum()) if "first_seen" in rows.columns else 0,
        "event_join_rate": float(rows["first_seen"].notna().mean()) if "first_seen" in rows.columns and len(rows) else 0.0,
    }
    return rows, summary


def build_sidecar(rows: pd.DataFrame, lookup: dict[tuple[str, str], dict[str, str]], metadata: dict[str, Any], args: argparse.Namespace) -> pd.DataFrame:
    diagnostics = [diagnose_path(value, lookup) for value in rows["as_path_clean"]]
    diag = pd.DataFrame(diagnostics)
    out = pd.concat([rows.reset_index(drop=True), diag], axis=1)

    snapshot_date = str(metadata.get("snapshot_date") or metadata.get("source_snapshot_date") or ASREL_SNAPSHOT_DEFAULT)
    run_date = str(metadata.get("run_date") or args.run_date)
    alignment_delta = metadata.get("alignment_delta_days", 15)
    evidence_strength = str(metadata.get("usable_evidence_strength") or metadata.get("relation_confidence") or "aligned_medium")

    out["asrel_snapshot_date"] = snapshot_date
    out["asrel_run_date"] = run_date
    out["asrel_alignment_delta_days"] = int(alignment_delta)
    out["asrel_source"] = str(metadata.get("source") or "CAIDA AS Relationships serial-2")
    out["asrel_evidence_strength"] = evidence_strength
    out["asrel_provenance"] = json.dumps(
        {
            "source": out["asrel_source"].iloc[0] if len(out) else "CAIDA AS Relationships serial-2",
            "snapshot_date": snapshot_date,
            "run_date": run_date,
            "alignment_delta_days": int(alignment_delta),
            "cache": str(Path(args.asrel_cache).as_posix()),
            "metadata": str(Path(args.asrel_metadata).as_posix()),
            "relationship_semantics": "CAIDA inferred relationship evidence; diagnostic only",
        },
        sort_keys=True,
    )
    out["allowed_claim"] = "2024-aligned AS-rel path diagnostic sidecar available"
    out["forbidden_claim"] = "confirmed route leak; benign path; attack truth"
    out["legacy_rel_used_for_decision"] = False
    out["old_rel_comparison_status"] = [
        compare_old_new(old_rel, new_rel)
        for old_rel, new_rel in zip(out.get("rel_seq", pd.Series([""] * len(out))), out["rel_seq_2024"])
    ]
    out["old_rel_unknown_delta"] = (
        pd.to_numeric(out.get("rel_unknown_cnt", pd.Series([0] * len(out))), errors="coerce").fillna(0).astype(int)
        - pd.to_numeric(out["rel_unknown_cnt_2024"], errors="coerce").fillna(0).astype(int)
    )
    return out


def value_counts_frame(series: pd.Series, name: str) -> pd.DataFrame:
    counts = series.fillna("NA").astype(str).value_counts().reset_index()
    counts.columns = [name, "count"]
    total = int(counts["count"].sum())
    counts["share"] = counts["count"] / max(total, 1)
    return counts


def build_summary(sidecar: pd.DataFrame, input_summary: dict[str, Any], metadata: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    total = len(sidecar)
    pair_eligible = int((sidecar["as_pair_count_2024"] > 0).sum())
    all_known = int((sidecar["path_relation_diagnostic_2024"] == "all_pairs_known_no_valley_diagnostic").sum())
    possible_valley = int(sidecar["possible_valley_transition_2024"].sum())
    has_unknown = int(sidecar["rel_has_unknown_2024"].sum())
    old_diff = int((sidecar["old_rel_comparison_status"] == "old_and_2024_different_sequence").sum())
    old_same = int((sidecar["old_rel_comparison_status"] == "old_and_2024_same_sequence").sum())

    return {
        "phase": "R-ASREL-CLEAN-0",
        "run_id": args.run_id,
        "run_date": args.run_date,
        **input_summary,
        "sidecar_rows": int(total),
        "asrel_cache": str(Path(args.asrel_cache).as_posix()),
        "asrel_metadata": str(Path(args.asrel_metadata).as_posix()),
        "asrel_snapshot_date": str(metadata.get("snapshot_date") or ASREL_SNAPSHOT_DEFAULT),
        "asrel_alignment_delta_days": int(metadata.get("alignment_delta_days", 15)),
        "asrel_lookup_rows": int(metadata.get("directed_lookup_rows_after_dedup", 0)),
        "asrel_directed_pair_conflict_count": int(metadata.get("directed_pair_conflict_count", 0)),
        "path_pair_eligible_rows": pair_eligible,
        "path_pair_eligible_rate": pair_eligible / max(total, 1),
        "all_pairs_known_no_valley_diagnostic_rows": all_known,
        "all_pairs_known_no_valley_diagnostic_rate": all_known / max(total, 1),
        "rows_with_unknown_relation_2024": has_unknown,
        "rows_with_unknown_relation_2024_rate": has_unknown / max(total, 1),
        "possible_valley_transition_rows": possible_valley,
        "possible_valley_transition_rate": possible_valley / max(total, 1),
        "old_and_2024_same_sequence_rows": old_same,
        "old_and_2024_different_sequence_rows": old_diff,
        "old_and_2024_different_sequence_rate": old_diff / max(total, 1),
        "diagnostic_distribution": {
            str(k): int(v)
            for k, v in sidecar["path_relation_diagnostic_2024"].value_counts(dropna=False).sort_index().items()
        },
        "evidence_state_distribution": {
            str(k): int(v)
            for k, v in sidecar["path_relation_evidence_state_2024"].value_counts(dropna=False).sort_index().items()
        },
        "old_rel_comparison_distribution": {
            str(k): int(v)
            for k, v in sidecar["old_rel_comparison_status"].value_counts(dropna=False).sort_index().items()
        },
        "safety": {
            "old_pipeline_modified": False,
            "legacy_rel_used_for_decision": False,
            "route_leak_truth_generated": False,
            "benign_label_generated": False,
            "learning_trained": False,
        },
        "safety_notes": SAFETY_NOTES,
        "recommended_next_step": "R-COMM-CLEAN-0 community / NO_EXPORT sidecar or R-LABEL-0 benchmark protocol after confirming AS-rel sidecar coverage",
    }


def write_report(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# R-ASREL-CLEAN-0 Report",
        "",
        "## Scope",
        "",
        "This run built a separate 2024-aligned CAIDA AS-rel sidecar for candidate/event rows. It did not modify the old pipeline and did not generate route-leak truth labels.",
        "",
        "## Core Results",
        "",
        f"- run_id: `{summary['run_id']}`",
        f"- sidecar rows: `{summary['sidecar_rows']}`",
        f"- event join rate: `{summary['event_join_rate']:.6f}`",
        f"- AS-rel snapshot: `{summary['asrel_snapshot_date']}`",
        f"- alignment delta days: `{summary['asrel_alignment_delta_days']}`",
        f"- path-pair eligible rows: `{summary['path_pair_eligible_rows']}` (`{summary['path_pair_eligible_rate']:.6f}`)",
        f"- rows with 2024 unknown relation: `{summary['rows_with_unknown_relation_2024']}` (`{summary['rows_with_unknown_relation_2024_rate']:.6f}`)",
        f"- possible valley-transition diagnostic rows: `{summary['possible_valley_transition_rows']}` (`{summary['possible_valley_transition_rate']:.6f}`)",
        f"- old vs 2024 different sequence rows: `{summary['old_and_2024_different_sequence_rows']}` (`{summary['old_and_2024_different_sequence_rate']:.6f}`)",
        "",
        "## Safety Boundaries",
        "",
        "- AS-rel diagnostic is not route-leak truth.",
        "- AS-rel matched is not benign.",
        "- AS-rel unknown is not suspicious by itself.",
        "- Old `rel_*` fields were used only for comparison audit.",
        "- No learning was trained.",
        "",
        "## Next",
        "",
        summary["recommended_next_step"],
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    candidates_path, events_path, asrel_cache, asrel_metadata, output_dir = resolve_inputs(args)
    output_dir.mkdir(parents=True, exist_ok=True)

    sidecar_path = output_dir / "asrel_2024_event_sidecar.parquet"
    preview_path = output_dir / "asrel_2024_event_sidecar_preview.csv"
    summary_path = output_dir / "asrel_2024_summary.json"
    diagnostic_path = output_dir / "asrel_2024_path_diagnostic_distribution.csv"
    old_rel_audit_path = output_dir / "asrel_2024_old_rel_comparison_audit.csv"
    report_path = output_dir / "asrel_2024_report.md"
    ensure_can_write(
        [sidecar_path, preview_path, summary_path, diagnostic_path, old_rel_audit_path, report_path],
        args.overwrite,
    )

    rows, input_summary = load_candidate_event_rows(args, candidates_path, events_path)
    lookup, metadata = load_asrel_lookup(asrel_cache, asrel_metadata)
    args.asrel_cache = str(asrel_cache)
    args.asrel_metadata = str(asrel_metadata)
    sidecar = build_sidecar(rows, lookup, metadata, args)
    summary = build_summary(sidecar, input_summary, metadata, args)

    sidecar.to_parquet(sidecar_path, index=False)
    sidecar.head(1000).to_csv(preview_path, index=False)
    write_json(summary_path, summary)
    value_counts_frame(sidecar["path_relation_diagnostic_2024"], "path_relation_diagnostic_2024").to_csv(diagnostic_path, index=False)
    (
        sidecar.groupby(["old_rel_comparison_status", "path_relation_diagnostic_2024"], dropna=False)
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
        .to_csv(old_rel_audit_path, index=False)
    )
    write_report(report_path, summary)

    print(json.dumps(summary, indent=2, sort_keys=True, default=json_default))


if __name__ == "__main__":
    main()
