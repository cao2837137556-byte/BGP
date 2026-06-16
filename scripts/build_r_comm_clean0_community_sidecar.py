#!/usr/bin/env python3
"""R-COMM-CLEAN-0 raw community / NO_EXPORT sidecar builder.

This script builds an independent, audit-friendly sidecar that attaches raw
BGP community attributes to 2024-04-16 event/candidate rows. It deliberately
does not modify the legacy seven-layer pipeline and does not produce attack,
benign, suppression, or learning labels.
"""

from __future__ import annotations

import argparse
import ast
import json
import math
import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


RUN_ID_DEFAULT = "s2a_baseline_v01_pilot_6h_april16"
RUN_DATE_DEFAULT = "2024-04-16"
RUN_ROOT_DEFAULT = "data/runs/s2a_baseline_v01_pilot_6h_april16"
OUTPUT_DIR_DEFAULT = "outputs/r_comm_clean_0/s2a_baseline_v01_pilot_6h_april16"

ASN_RE = re.compile(r"\d+")
KEY_COLS = ["prefix_key", "origin_key", "as_path_key"]

WELL_KNOWN_COMMUNITIES = {
    "NO_EXPORT": {
        "pair": "65535:65281",
        "decimal": "4294967041",
        "hex": "0xffffff01",
        "aliases": {"no_export", "no-export"},
    },
    "NO_ADVERTISE": {
        "pair": "65535:65282",
        "decimal": "4294967042",
        "hex": "0xffffff02",
        "aliases": {"no_advertise", "no-advertise"},
    },
    "NO_EXPORT_SUBCONFED": {
        "pair": "65535:65283",
        "decimal": "4294967043",
        "hex": "0xffffff03",
        "aliases": {"no_export_subconfed", "no-export-subconfed", "no_export_subconfederation"},
    },
    "NOPEER": {
        "pair": "65535:65284",
        "decimal": "4294967044",
        "hex": "0xffffff04",
        "aliases": {"nopeer", "no_peer", "no-peer"},
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=RUN_ID_DEFAULT)
    parser.add_argument("--run-date", default=RUN_DATE_DEFAULT)
    parser.add_argument("--run-root", default=RUN_ROOT_DEFAULT)
    parser.add_argument("--events", default=None)
    parser.add_argument("--candidates", default=None)
    parser.add_argument("--output-dir", default=OUTPUT_DIR_DEFAULT)
    parser.add_argument(
        "--source-mode",
        choices=["raw_counterpart", "event_source"],
        default="raw_counterpart",
        help="Prefer raw update chunks by replacing __rel.parquet with .parquet, or read event source files directly.",
    )
    parser.add_argument("--sample-events", type=int, default=0, help="Optional event-row limit for smoke runs.")
    parser.add_argument("--max-files", type=int, default=0, help="Optional source-file limit for smoke runs.")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, (datetime, date, pd.Timestamp, Path)):
        return str(value)
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, float) and math.isnan(value):
        return None
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=json_default), encoding="utf-8")


def safe_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value)


def is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    text = safe_str(value).strip().lower()
    return text in {"", "nan", "none", "null", "[]", "{}", "()"}


def rel_path(path: str | Path) -> str:
    p = Path(path)
    try:
        return p.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return p.as_posix()


def parse_as_path(value: Any) -> list[int]:
    if is_missing(value):
        return []
    nums = [int(x) for x in ASN_RE.findall(str(value))]
    deduped: list[int] = []
    prev = None
    for n in nums:
        if n != prev:
            deduped.append(n)
            prev = n
    return deduped


def normalize_raw_updates(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    work["ts"] = pd.to_numeric(work["ts"], errors="coerce")
    work = work[work["ts"].notna()].copy()
    work["prefix_key"] = work["prefix"].astype(str)

    clean_values: list[str] = []
    origin_values: list[int] = []
    normalized_paths = work["as_path_clean"] if "as_path_clean" in work.columns else pd.Series([""] * len(work), index=work.index)
    raw_paths = work["as_path"] if "as_path" in work.columns else pd.Series([""] * len(work), index=work.index)
    raw_origins = work["origin_as"] if "origin_as" in work.columns else pd.Series([None] * len(work), index=work.index)
    for normalized_path, raw_path, raw_origin in zip(normalized_paths, raw_paths, raw_origins):
        seq = parse_as_path(normalized_path)
        if not seq:
            seq = parse_as_path(raw_path)
        clean_values.append(" ".join(str(x) for x in seq))
        origin_value = pd.to_numeric(pd.Series([raw_origin]), errors="coerce").iloc[0]
        origin_values.append(int(origin_value) if pd.notna(origin_value) else (seq[-1] if seq else -1))
    work["as_path_key"] = clean_values
    work["origin_key"] = origin_values
    return work


def flatten_community_value(value: Any) -> list[str]:
    out: list[str] = []
    if is_missing(value):
        return out
    if isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            out.extend(flatten_community_value(item))
        return out
    if isinstance(value, np.ndarray):
        for item in value.tolist():
            out.extend(flatten_community_value(item))
        return out
    text = safe_str(value).strip()
    if not text:
        return out
    if (text.startswith("[") and text.endswith("]")) or (text.startswith("(") and text.endswith(")")):
        for fn in (json.loads, ast.literal_eval):
            try:
                parsed = fn(text)
                if isinstance(parsed, (list, tuple, set, frozenset)):
                    for item in parsed:
                        out.extend(flatten_community_value(item))
                    return out
            except Exception:
                pass
    out.append(text)
    return out


def parse_community_tokens(value: Any) -> dict[str, Any]:
    flattened = flatten_community_value(value)
    tokens: list[str] = []
    hits = {name: False for name in WELL_KNOWN_COMMUNITIES}
    parse_success = False
    has_large = False

    for raw in flattened:
        text = safe_str(raw).strip()
        if not text:
            continue
        normalized_name_text = text.lower().replace("-", "_").replace(" ", "_")
        for name, spec in WELL_KNOWN_COMMUNITIES.items():
            if normalized_name_text in spec["aliases"] or any(alias in normalized_name_text for alias in spec["aliases"]):
                hits[name] = True
                parse_success = True

        for token in re.findall(r"\b\d+\s*:\s*\d+(?::\s*\d+)?\b", text):
            clean = token.replace(" ", "")
            tokens.append(clean)
            parse_success = True
            if clean.count(":") == 2:
                has_large = True
            for name, spec in WELL_KNOWN_COMMUNITIES.items():
                if clean == spec["pair"]:
                    hits[name] = True

        for token in re.findall(r"\b(?:0x)?[0-9a-fA-F]{8}\b", text):
            clean = token.lower()
            tokens.append(clean)
            parse_success = True
            for name, spec in WELL_KNOWN_COMMUNITIES.items():
                if clean == spec["hex"]:
                    hits[name] = True

        for token in re.findall(r"\b\d{7,10}\b", text):
            tokens.append(token)
            parse_success = True
            for name, spec in WELL_KNOWN_COMMUNITIES.items():
                if token == spec["decimal"]:
                    hits[name] = True

    non_empty = bool(flattened)
    return {
        "community_non_empty": non_empty,
        "community_parse_success": parse_success,
        "community_parse_failure": bool(non_empty and not parse_success),
        "community_token_count": len(set(tokens)),
        "has_large_community": has_large,
        "has_no_export": hits["NO_EXPORT"],
        "has_no_advertise": hits["NO_ADVERTISE"],
        "has_no_export_subconfed": hits["NO_EXPORT_SUBCONFED"],
        "has_nopeer": hits["NOPEER"],
        "community_token_example": "|".join(list(dict.fromkeys(tokens))[:8]),
    }


def split_source_files(value: Any) -> list[str]:
    return [part for part in safe_str(value).split("|") if part]


def source_to_read_path(source_file: str, source_mode: str) -> Path:
    source = Path(source_file)
    if source_mode == "raw_counterpart" and source.name.endswith("__rel.parquet"):
        return source.with_name(source.name.replace("__rel.parquet", ".parquet"))
    return source


def existing_columns(path: Path, wanted: Iterable[str]) -> list[str]:
    schema = pq.ParquetFile(path).schema_arrow
    names = set(schema.names)
    return [col for col in wanted if col in names]


def prepare_events(events_path: Path, sample_events: int) -> tuple[pd.DataFrame, pd.DataFrame]:
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
        "source_file",
    ]
    events = pd.read_parquet(events_path, columns=columns)
    if sample_events and sample_events > 0:
        events = events.head(sample_events).copy()

    events["prefix_key"] = events["prefix"].astype(str)
    events["origin_key"] = pd.to_numeric(events["origin_as"], errors="coerce").fillna(-1).astype(int)
    events["as_path_key"] = events["as_path_clean"].fillna("").astype(str)
    events["first_seen"] = pd.to_numeric(events["first_seen"], errors="coerce")
    events["last_seen"] = pd.to_numeric(events["last_seen"], errors="coerce")
    events["record_count"] = pd.to_numeric(events["record_count"], errors="coerce").fillna(0).astype(int)
    events["source_file_count"] = events["source_file"].map(lambda value: len(split_source_files(value)))

    exploded = events[
        [
            "event_id",
            "prefix_key",
            "origin_key",
            "as_path_key",
            "first_seen",
            "last_seen",
            "source_file",
        ]
    ].copy()
    exploded["_source_file_part"] = exploded["source_file"].map(split_source_files)
    exploded = exploded.explode("_source_file_part")
    exploded = exploded[exploded["_source_file_part"].notna()].copy()
    exploded = exploded.rename(columns={"_source_file_part": "source_file_part"})
    return events, exploded


def assign_raw_rows_to_events(raw: pd.DataFrame, source_events: pd.DataFrame) -> pd.DataFrame:
    if raw.empty or source_events.empty:
        return pd.DataFrame()

    left = raw.sort_values(["ts", *KEY_COLS]).reset_index(drop=True)
    right = source_events.sort_values(["first_seen", *KEY_COLS]).reset_index(drop=True)
    try:
        merged = pd.merge_asof(
            left,
            right,
            left_on="ts",
            right_on="first_seen",
            by=KEY_COLS,
            direction="backward",
            allow_exact_matches=True,
        )
    except ValueError:
        chunks: list[pd.DataFrame] = []
        right_groups = {key: group.sort_values("first_seen") for key, group in source_events.groupby(KEY_COLS, dropna=False)}
        for key, raw_group in raw.groupby(KEY_COLS, dropna=False):
            event_group = right_groups.get(key)
            if event_group is None or event_group.empty:
                continue
            chunks.append(
                pd.merge_asof(
                    raw_group.sort_values("ts"),
                    event_group,
                    left_on="ts",
                    right_on="first_seen",
                    direction="backward",
                    allow_exact_matches=True,
                )
            )
        merged = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()

    if merged.empty or "event_id" not in merged.columns:
        return pd.DataFrame()
    assigned = merged[
        merged["event_id"].notna()
        & (pd.to_numeric(merged["ts"], errors="coerce") >= pd.to_numeric(merged["first_seen"], errors="coerce"))
        & (pd.to_numeric(merged["ts"], errors="coerce") <= pd.to_numeric(merged["last_seen"], errors="coerce"))
    ].copy()
    return assigned


def aggregate_assigned_rows(assigned: pd.DataFrame, community_field_present: bool) -> tuple[pd.DataFrame, pd.DataFrame]:
    if assigned.empty:
        empty = pd.DataFrame(
            columns=[
                "event_id",
                "raw_rows_matched",
                "raw_rows_with_community_field",
                "community_non_empty_rows",
                "community_parse_success_rows",
                "community_parse_failure_rows",
                "community_token_count_sum",
                "large_community_rows",
                "no_export_rows",
                "no_advertise_rows",
                "no_export_subconfed_rows",
                "nopeer_rows",
                "community_token_examples",
            ]
        )
        return empty, pd.DataFrame()

    if community_field_present:
        parsed_rows = [parse_community_tokens(value) for value in assigned["communities"].tolist()]
    else:
        parsed_rows = [
            {
                "community_non_empty": False,
                "community_parse_success": False,
                "community_parse_failure": False,
                "community_token_count": 0,
                "has_large_community": False,
                "has_no_export": False,
                "has_no_advertise": False,
                "has_no_export_subconfed": False,
                "has_nopeer": False,
                "community_token_example": "",
            }
            for _ in range(len(assigned))
        ]
    parsed = pd.DataFrame(parsed_rows, index=assigned.index)
    work = pd.concat([assigned[["event_id"]].reset_index(drop=True), parsed.reset_index(drop=True)], axis=1)
    work["raw_rows_with_community_field"] = 1 if community_field_present else 0

    grouped = work.groupby("event_id").agg(
        raw_rows_matched=("event_id", "size"),
        raw_rows_with_community_field=("raw_rows_with_community_field", "sum"),
        community_non_empty_rows=("community_non_empty", "sum"),
        community_parse_success_rows=("community_parse_success", "sum"),
        community_parse_failure_rows=("community_parse_failure", "sum"),
        community_token_count_sum=("community_token_count", "sum"),
        large_community_rows=("has_large_community", "sum"),
        no_export_rows=("has_no_export", "sum"),
        no_advertise_rows=("has_no_advertise", "sum"),
        no_export_subconfed_rows=("has_no_export_subconfed", "sum"),
        nopeer_rows=("has_nopeer", "sum"),
    )

    examples = (
        work.loc[work["community_token_example"].astype(str).str.len() > 0]
        .groupby("event_id")["community_token_example"]
        .apply(lambda values: "|".join(list(dict.fromkeys(values.astype(str)))[:3]))
    )
    grouped = grouped.join(examples.rename("community_token_examples"), how="left").fillna({"community_token_examples": ""})
    grouped = grouped.reset_index()

    hit_sample_cols = ["event_id"]
    hit_sample = work[
        work[["has_no_export", "has_no_advertise", "has_no_export_subconfed", "has_nopeer"]].any(axis=1)
    ][hit_sample_cols + ["has_no_export", "has_no_advertise", "has_no_export_subconfed", "has_nopeer", "community_token_example"]].head(5000)
    return grouped, hit_sample


def process_sources(
    exploded_events: pd.DataFrame,
    args: argparse.Namespace,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    source_files = sorted(exploded_events["source_file_part"].dropna().astype(str).unique())
    if args.max_files and args.max_files > 0:
        source_files = source_files[: args.max_files]
        exploded_events = exploded_events[exploded_events["source_file_part"].isin(source_files)].copy()

    source_audit_rows: list[dict[str, Any]] = []
    aggregate_chunks: list[pd.DataFrame] = []
    hit_samples: list[pd.DataFrame] = []
    totals = Counter()

    for idx, source_file in enumerate(source_files, start=1):
        source_events = exploded_events[exploded_events["source_file_part"] == source_file].copy()
        read_path = source_to_read_path(source_file, args.source_mode)
        row = {
            "source_file": source_file,
            "read_path": read_path.as_posix(),
            "source_mode": args.source_mode,
            "event_rows_for_source": int(len(source_events)),
            "read_status": "pending",
            "raw_rows_read": 0,
            "assigned_raw_rows": 0,
            "assigned_event_count": 0,
            "community_field_present": False,
            "community_non_empty_rows": 0,
            "community_parse_success_rows": 0,
            "community_parse_failure_rows": 0,
            "no_export_rows": 0,
            "no_advertise_rows": 0,
            "no_export_subconfed_rows": 0,
            "nopeer_rows": 0,
            "notes": "",
        }
        if not read_path.exists():
            row["read_status"] = "missing_source_file"
            source_audit_rows.append(row)
            continue

        wanted = ["ts", "prefix", "as_path", "as_path_clean", "origin_as", "communities"]
        try:
            cols = existing_columns(read_path, wanted)
            missing_required = [col for col in ["ts", "prefix"] if col not in cols]
            if "as_path" not in cols and "as_path_clean" not in cols:
                missing_required.append("as_path_or_as_path_clean")
            if missing_required:
                row["read_status"] = "missing_required_columns"
                row["notes"] = ",".join(missing_required)
                source_audit_rows.append(row)
                continue
            community_field_present = "communities" in cols
            row["community_field_present"] = community_field_present
            raw = pd.read_parquet(read_path, columns=cols)
            row["raw_rows_read"] = int(len(raw))
            raw = normalize_raw_updates(raw)
            assigned = assign_raw_rows_to_events(raw, source_events)
            row["assigned_raw_rows"] = int(len(assigned))
            row["assigned_event_count"] = int(assigned["event_id"].nunique()) if not assigned.empty else 0
            row["read_status"] = "ok"

            agg, hits = aggregate_assigned_rows(assigned, community_field_present)
            if not agg.empty:
                row["community_non_empty_rows"] = int(agg["community_non_empty_rows"].sum())
                row["community_parse_success_rows"] = int(agg["community_parse_success_rows"].sum())
                row["community_parse_failure_rows"] = int(agg["community_parse_failure_rows"].sum())
                row["no_export_rows"] = int(agg["no_export_rows"].sum())
                row["no_advertise_rows"] = int(agg["no_advertise_rows"].sum())
                row["no_export_subconfed_rows"] = int(agg["no_export_subconfed_rows"].sum())
                row["nopeer_rows"] = int(agg["nopeer_rows"].sum())
                aggregate_chunks.append(agg)
            if not hits.empty:
                hits.insert(1, "source_file", source_file)
                hit_samples.append(hits)
        except Exception as exc:
            row["read_status"] = "read_or_join_error"
            row["notes"] = f"{type(exc).__name__}: {exc}"
        source_audit_rows.append(row)

        totals["source_files_seen"] += 1
        if idx % 25 == 0:
            print(f"[R-COMM-CLEAN-0] processed {idx}/{len(source_files)} source files", flush=True)

    source_audit = pd.DataFrame(source_audit_rows)
    if aggregate_chunks:
        all_agg = pd.concat(aggregate_chunks, ignore_index=True)
        combined = all_agg.groupby("event_id").agg(
            raw_rows_matched=("raw_rows_matched", "sum"),
            raw_rows_with_community_field=("raw_rows_with_community_field", "sum"),
            community_non_empty_rows=("community_non_empty_rows", "sum"),
            community_parse_success_rows=("community_parse_success_rows", "sum"),
            community_parse_failure_rows=("community_parse_failure_rows", "sum"),
            community_token_count_sum=("community_token_count_sum", "sum"),
            large_community_rows=("large_community_rows", "sum"),
            no_export_rows=("no_export_rows", "sum"),
            no_advertise_rows=("no_advertise_rows", "sum"),
            no_export_subconfed_rows=("no_export_subconfed_rows", "sum"),
            nopeer_rows=("nopeer_rows", "sum"),
            community_token_examples=("community_token_examples", lambda values: "|".join([v for v in values.astype(str).tolist() if v][:3])),
        ).reset_index()
    else:
        combined = pd.DataFrame(columns=["event_id"])
    hit_sample = pd.concat(hit_samples, ignore_index=True).head(5000) if hit_samples else pd.DataFrame()
    return combined, source_audit, hit_sample, dict(totals)


def build_sidecar(events: pd.DataFrame, aggregate: pd.DataFrame, source_limited: bool) -> pd.DataFrame:
    sidecar_cols = [
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
        "source_file",
        "source_file_count",
    ]
    sidecar = events[sidecar_cols].copy()
    if source_limited and not aggregate.empty:
        sidecar = sidecar[sidecar["event_id"].isin(set(aggregate["event_id"]))].copy()
    sidecar = sidecar.merge(aggregate, on="event_id", how="left")

    numeric_cols = [
        "raw_rows_matched",
        "raw_rows_with_community_field",
        "community_non_empty_rows",
        "community_parse_success_rows",
        "community_parse_failure_rows",
        "community_token_count_sum",
        "large_community_rows",
        "no_export_rows",
        "no_advertise_rows",
        "no_export_subconfed_rows",
        "nopeer_rows",
    ]
    for col in numeric_cols:
        if col not in sidecar.columns:
            sidecar[col] = 0
        sidecar[col] = pd.to_numeric(sidecar[col], errors="coerce").fillna(0).astype(int)
    if "community_token_examples" not in sidecar.columns:
        sidecar["community_token_examples"] = ""
    sidecar["community_token_examples"] = sidecar["community_token_examples"].fillna("")

    sidecar["has_communities"] = sidecar["community_non_empty_rows"] > 0
    sidecar["has_no_export"] = sidecar["no_export_rows"] > 0
    sidecar["has_no_advertise"] = sidecar["no_advertise_rows"] > 0
    sidecar["has_no_export_subconfed"] = sidecar["no_export_subconfed_rows"] > 0
    sidecar["has_nopeer"] = sidecar["nopeer_rows"] > 0

    record = pd.to_numeric(sidecar["record_count"], errors="coerce").fillna(0).astype(int)
    matched = sidecar["raw_rows_matched"]
    sidecar["raw_match_status"] = np.select(
        [
            matched == 0,
            matched == record,
            (matched > 0) & (matched < record),
            matched > record,
        ],
        [
            "no_raw_match",
            "exact_record_count_match",
            "partial_record_count_match",
            "over_record_count_match",
        ],
        default="unknown",
    )
    sidecar["community_evidence_state"] = np.select(
        [
            matched == 0,
            sidecar["raw_rows_with_community_field"] == 0,
            sidecar["community_non_empty_rows"] == 0,
            sidecar["community_parse_success_rows"] > 0,
            sidecar["community_parse_failure_rows"] > 0,
        ],
        [
            "raw_join_unavailable",
            "raw_field_unavailable",
            "observed_no_community_tokens",
            "present_parsed",
            "present_unparsed",
        ],
        default="unknown",
    )
    sidecar["community_join_confidence"] = np.select(
        [
            sidecar["raw_match_status"].eq("exact_record_count_match"),
            sidecar["raw_match_status"].eq("partial_record_count_match") | sidecar["raw_match_status"].eq("over_record_count_match"),
        ],
        [1.0, 0.5],
        default=0.0,
    )
    sidecar["community_provenance"] = "raw_update_communities_joined_by_source_file_prefix_origin_path_time"
    sidecar["allowed_claim"] = "raw community evidence state is available with join provenance"
    sidecar["forbidden_claim"] = "confirmed NO_EXPORT attack; NO_EXPORT absent means safe; low visibility means NO_EXPORT"
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
        "raw_rows_matched",
        "raw_match_status",
        "community_evidence_state",
        "community_join_confidence",
        "has_communities",
        "has_no_export",
        "has_no_advertise",
        "has_no_export_subconfed",
        "has_nopeer",
        "community_non_empty_rows",
        "community_parse_success_rows",
        "community_parse_failure_rows",
        "no_export_rows",
        "no_advertise_rows",
        "no_export_subconfed_rows",
        "nopeer_rows",
        "community_provenance",
        "allowed_claim",
        "forbidden_claim",
    ]
    merged = candidates.merge(event_sidecar[sidecar_cols], on="event_id", how="left", indicator=True)
    join_rate = float((merged["_merge"] == "both").mean()) if len(merged) else 0.0
    merged = merged.drop(columns=["_merge"])
    return merged, join_rate


def distribution(series: pd.Series) -> dict[str, int]:
    return {str(k): int(v) for k, v in series.fillna("missing").value_counts(dropna=False).sort_index().items()}


def write_report(path: Path, summary: dict[str, Any]) -> None:
    state_dist = summary["community_evidence_state_distribution"]
    status_dist = summary["raw_match_status_distribution"]
    lines = [
        "# R-COMM-CLEAN-0 Community / NO_EXPORT Sidecar Report",
        "",
        f"Run id: `{summary['run_id']}`",
        "",
        "## Scope",
        "",
        "This run attaches raw BGP community attributes to event/candidate rows through an independent sidecar.",
        "It does not modify the legacy seven-layer pipeline, does not train learning, and does not claim NO_EXPORT attacks.",
        "",
        "## Inputs",
        "",
        f"- events: `{summary['events_path']}`",
        f"- candidates: `{summary['candidates_path']}`",
        f"- source mode: `{summary['source_mode']}`",
        f"- source files processed: `{summary['source_files_processed']}` / `{summary['source_files_expected']}`",
        "",
        "## Join Quality",
        "",
        f"- event sidecar rows: `{summary['event_sidecar_rows']}`",
        f"- events with raw match: `{summary['events_with_raw_match']}`",
        f"- event raw-match rate: `{summary['event_raw_match_rate']}`",
        f"- exact record-count match rate: `{summary['exact_record_count_match_rate']}`",
        f"- raw rows read: `{summary['raw_rows_read']}`",
        f"- assigned raw rows: `{summary['assigned_raw_rows']}`",
        "",
        "Raw match status distribution:",
        "",
        "| Status | Count |",
        "|---|---:|",
    ]
    lines.extend(f"| `{key}` | `{value}` |" for key, value in status_dist.items())
    lines.extend(
        [
            "",
            "## Community Evidence State",
            "",
            "| State | Count |",
            "|---|---:|",
        ]
    )
    lines.extend(f"| `{key}` | `{value}` |" for key, value in state_dist.items())
    lines.extend(
        [
            "",
            "## Well-known Community Events",
            "",
            f"- NO_EXPORT events: `{summary['well_known_event_counts']['NO_EXPORT']}`",
            f"- NO_ADVERTISE events: `{summary['well_known_event_counts']['NO_ADVERTISE']}`",
            f"- NO_EXPORT_SUBCONFED events: `{summary['well_known_event_counts']['NO_EXPORT_SUBCONFED']}`",
            f"- NOPEER events: `{summary['well_known_event_counts']['NOPEER']}`",
            "",
            "## Scientific Boundary",
            "",
            "Allowed claim: raw community / well-known community evidence is now represented as a provenance-bearing sidecar where raw join succeeded.",
            "",
            "Forbidden claims:",
            "",
            "- NO_EXPORT present is not a confirmed attack.",
            "- NO_EXPORT absent is not safe.",
            "- Missing raw/community evidence is not benign.",
            "- Low visibility is not confirmed NO_EXPORT or stealth evasion.",
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
    output_dir = Path(args.output_dir)

    if not events_path.exists():
        raise FileNotFoundError(f"events parquet not found: {events_path}")
    if not candidates_path.exists():
        raise FileNotFoundError(f"candidates parquet not found: {candidates_path}")
    if output_dir.exists() and any(output_dir.iterdir()) and not args.overwrite:
        raise FileExistsError(f"output directory is not empty; pass --overwrite: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    events, exploded = prepare_events(events_path, args.sample_events)
    if args.max_files and args.max_files > 0:
        selected_sources = sorted(exploded["source_file_part"].dropna().astype(str).unique())[: args.max_files]
        exploded = exploded[exploded["source_file_part"].isin(selected_sources)].copy()
        events = events[events["event_id"].isin(set(exploded["event_id"]))].copy()

    aggregate, source_audit, hit_sample, _ = process_sources(exploded, args)
    event_sidecar = build_sidecar(events, aggregate, source_limited=False)
    candidate_sidecar, candidate_join_rate = build_candidate_sidecar(candidates_path, event_sidecar)

    event_sidecar_path = output_dir / "community_event_sidecar.parquet"
    candidate_sidecar_path = output_dir / "community_candidate_sidecar.parquet"
    preview_path = output_dir / "community_event_sidecar_preview.csv"
    source_audit_path = output_dir / "community_source_join_audit.csv"
    hit_sample_path = output_dir / "well_known_community_event_hits_sample.csv"
    state_dist_path = output_dir / "community_evidence_state_distribution.csv"
    summary_path = output_dir / "community_noexport_summary.json"
    report_path = output_dir / "community_noexport_report.md"

    event_sidecar.to_parquet(event_sidecar_path, index=False)
    candidate_sidecar.to_parquet(candidate_sidecar_path, index=False)
    event_sidecar.head(1000).to_csv(preview_path, index=False)
    source_audit.to_csv(source_audit_path, index=False)
    hit_sample.to_csv(hit_sample_path, index=False)
    event_sidecar["community_evidence_state"].value_counts(dropna=False).rename_axis("community_evidence_state").reset_index(name="count").to_csv(
        state_dist_path, index=False
    )

    raw_rows_read = int(source_audit["raw_rows_read"].sum()) if not source_audit.empty else 0
    assigned_raw_rows = int(source_audit["assigned_raw_rows"].sum()) if not source_audit.empty else 0
    event_rows = int(len(event_sidecar))
    events_with_raw_match = int((event_sidecar["raw_rows_matched"] > 0).sum())
    exact_record_match = int(event_sidecar["raw_match_status"].eq("exact_record_count_match").sum())
    state_dist = distribution(event_sidecar["community_evidence_state"])
    status_dist = distribution(event_sidecar["raw_match_status"])
    well_known_counts = {
        "NO_EXPORT": int(event_sidecar["has_no_export"].sum()),
        "NO_ADVERTISE": int(event_sidecar["has_no_advertise"].sum()),
        "NO_EXPORT_SUBCONFED": int(event_sidecar["has_no_export_subconfed"].sum()),
        "NOPEER": int(event_sidecar["has_nopeer"].sum()),
    }

    if events_with_raw_match == event_rows:
        recommended = "R-COMM-CLEAN-1 can use this sidecar as a clean community evidence input, while preserving the no-attack/no-benign guardrails."
    else:
        recommended = "Before R-COMM-CLEAN-1, inspect raw_join_unavailable rows and decide whether additional raw source discovery is needed."

    summary = {
        "run_id": args.run_id,
        "run_date": args.run_date,
        "events_path": rel_path(events_path),
        "candidates_path": rel_path(candidates_path),
        "output_dir": rel_path(output_dir),
        "source_mode": args.source_mode,
        "sample_events": int(args.sample_events),
        "max_files": int(args.max_files),
        "source_files_expected": int(exploded["source_file_part"].nunique()) if not exploded.empty else 0,
        "source_files_processed": int(len(source_audit)),
        "source_files_ok": int((source_audit["read_status"] == "ok").sum()) if not source_audit.empty else 0,
        "raw_rows_read": raw_rows_read,
        "assigned_raw_rows": assigned_raw_rows,
        "event_sidecar_rows": event_rows,
        "candidate_sidecar_rows": int(len(candidate_sidecar)),
        "candidate_sidecar_join_rate": candidate_join_rate,
        "events_with_raw_match": events_with_raw_match,
        "event_raw_match_rate": (events_with_raw_match / event_rows) if event_rows else 0.0,
        "exact_record_count_match_events": exact_record_match,
        "exact_record_count_match_rate": (exact_record_match / event_rows) if event_rows else 0.0,
        "community_evidence_state_distribution": state_dist,
        "raw_match_status_distribution": status_dist,
        "community_non_empty_events": int((event_sidecar["community_non_empty_rows"] > 0).sum()),
        "community_parse_success_events": int((event_sidecar["community_parse_success_rows"] > 0).sum()),
        "community_parse_failure_events": int((event_sidecar["community_parse_failure_rows"] > 0).sum()),
        "well_known_event_counts": well_known_counts,
        "raw_row_well_known_counts": {
            "NO_EXPORT": int(event_sidecar["no_export_rows"].sum()),
            "NO_ADVERTISE": int(event_sidecar["no_advertise_rows"].sum()),
            "NO_EXPORT_SUBCONFED": int(event_sidecar["no_export_subconfed_rows"].sum()),
            "NOPEER": int(event_sidecar["nopeer_rows"].sum()),
        },
        "allowed_claim": "raw community evidence is joined into an event/candidate sidecar with provenance where raw join succeeds",
        "forbidden_claims": [
            "NO_EXPORT present is confirmed attack",
            "NO_EXPORT absent means safe",
            "missing communities are benign",
            "low visibility means NO_EXPORT",
            "community evidence trains learning labels",
        ],
        "recommended_next_step": recommended,
        "outputs": {
            "event_sidecar": rel_path(event_sidecar_path),
            "candidate_sidecar": rel_path(candidate_sidecar_path),
            "preview": rel_path(preview_path),
            "source_audit": rel_path(source_audit_path),
            "hit_sample": rel_path(hit_sample_path),
            "state_distribution": rel_path(state_dist_path),
            "report": rel_path(report_path),
        },
    }
    write_json(summary_path, summary)
    write_report(report_path, summary)
    print(json.dumps(summary, indent=2, sort_keys=True, default=json_default))


if __name__ == "__main__":
    main()
