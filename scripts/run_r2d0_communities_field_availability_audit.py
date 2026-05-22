#!/usr/bin/env python3
"""R-2D-0 communities / NO_EXPORT field availability audit.

This is an audit-only script. It scans existing local run artifacts for BGP
community-like fields, parses well-known community values when fields exist,
and reports pipeline retention / incident-join readiness. It does not download
external evidence, modify verifier verdicts, implement a stealth verifier, run
poisoning benchmarks, or train a learning layer.
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import math
import re
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


RUN_ID_DEFAULT = "s2a_expanded_v01_pilot_6h_april16"
RUN_DATE_DEFAULT = "2024-04-16"
RUN_ROOT_DEFAULT = "data/runs/s2a_expanded_v01_pilot_6h_april16"
OUTPUT_DIR_DEFAULT = "outputs/r2d0_communities_field_availability_audit_v01"

SUPPORTED_EXTENSIONS = {".parquet", ".csv", ".json", ".jsonl"}
COMMUNITY_FIELD_PATTERNS = [
    "community",
    "communities",
    "bgp_community",
    "bgp_communities",
    "large_community",
    "large_communities",
    "ext_community",
    "ext_communities",
    "raw_community",
    "attrs",
    "attributes",
]

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

KEY_COLUMNS = [
    "incident_id",
    "member_id",
    "event_id",
    "prefix",
    "origin_as",
    "origin_as_norm",
    "as_path",
    "as_path_clean",
    "path_signature",
    "collector",
    "collector_set",
    "ts",
    "timestamp",
    "first_seen",
    "last_seen",
]

EXPECTED_LAYER_FILES = {
    "raw_updates": [
        "data/runs/<run_id>__collector_*/collector=*/date=*/updates__*.parquet",
        "data/runs/<run_id>/collector=*/raw/*.parquet",
    ],
    "rel_annotated": [
        "data/runs/<run_id>/collector=*/rel/*.parquet",
        "data/runs/<run_id>/**/__rel*.parquet",
    ],
    "event_units": ["data/runs/<run_id>/events/event_units.parquet"],
    "incident_membership": ["data/runs/<run_id>/incidents/incident_membership.parquet"],
    "incident_tickets": ["data/runs/<run_id>/incidents/incident_tickets.parquet"],
    "verifier_outputs": [
        "outputs/r2b_vrp_aware_verifier_smoke_v01/r2b_vrp_incident_verifier_table.parquet",
        "outputs/r2c_p2_path_legality_verifier_smoke_v01/r2c_p2_incident_verifier_smoke_table.parquet",
    ],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=RUN_ID_DEFAULT)
    parser.add_argument("--run-date", default=RUN_DATE_DEFAULT)
    parser.add_argument("--run-root", default=RUN_ROOT_DEFAULT)
    parser.add_argument("--output-dir", default=OUTPUT_DIR_DEFAULT)
    parser.add_argument("--sample-rows", type=int, default=0)
    parser.add_argument("--full-run", action="store_true")
    parser.add_argument(
        "--scan-glob",
        action="append",
        default=[],
        help="Optional glob(s) to scan. If omitted, scan run-root plus related collector runs and verifier tables.",
    )
    parser.add_argument("--max-files", type=int, default=0)
    return parser.parse_args()


def json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, (datetime, date, pd.Timestamp, Path)):
        return str(value)
    if isinstance(value, set):
        return sorted(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if pd.isna(value):
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


def file_type(path: Path) -> str:
    suffix = path.suffix.lower()
    return suffix[1:] if suffix else "unknown"


def matches_community_columns(columns: Iterable[str]) -> list[str]:
    out = []
    for col in columns:
        lower = col.lower()
        if any(pattern in lower for pattern in COMMUNITY_FIELD_PATTERNS):
            out.append(col)
    return out


def infer_layer(path: str | Path) -> str:
    text = Path(path).as_posix().lower()
    name = Path(path).name.lower()
    if "r2b_vrp_incident_verifier_table" in name or "r2c_p2_incident_verifier_smoke_table" in name:
        return "verifier_outputs"
    if "incident_membership" in name:
        return "incident_membership"
    if "incident_tickets" in name:
        return "incident_tickets"
    if "event_units" in name or "/events/" in text:
        return "event_units"
    if "__rel" in name or "/rel/" in text or "\\rel\\" in text:
        return "rel_annotated"
    if "updates__" in name or "/collector=" in text:
        return "raw_updates"
    return "other"


def collect_scan_files(args: argparse.Namespace) -> list[Path]:
    files: set[Path] = set()
    cwd = Path.cwd()
    if args.scan_glob:
        for pattern in args.scan_glob:
            files.update(p for p in cwd.glob(pattern) if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS)
    else:
        run_root = Path(args.run_root)
        if run_root.exists():
            files.update(p for p in run_root.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS)

        # Current S2-A local-raw layout stores per-collector update chunks as
        # sibling run directories: <run_id>__collector_<collector>.
        parent = run_root.parent
        if parent.exists():
            for collector_root in parent.glob(f"{args.run_id}__collector_*"):
                files.update(p for p in collector_root.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS)

        for expected in EXPECTED_LAYER_FILES["verifier_outputs"]:
            p = Path(expected)
            if p.exists():
                files.add(p)

    sorted_files = sorted(files, key=lambda p: p.as_posix())
    if args.max_files and args.max_files > 0:
        return sorted_files[: args.max_files]
    return sorted_files


def parquet_schema_inventory(path: Path) -> dict[str, Any]:
    pf = pq.ParquetFile(path)
    schema = pf.schema_arrow
    columns = schema.names
    matched = matches_community_columns(columns)
    schema_sample = {name: str(schema.field(name).type) for name in columns[:50]}
    for name in matched:
        schema_sample[name] = str(schema.field(name).type)
    return {
        "file_path": rel_path(path),
        "file_type": "parquet",
        "pipeline_layer": infer_layer(path),
        "row_count_if_fast": int(pf.metadata.num_rows) if pf.metadata else None,
        "column_count": len(columns),
        "matched_community_columns": "|".join(matched),
        "has_community_like_field": bool(matched),
        "schema_sample": json.dumps(schema_sample, sort_keys=True),
        "notes": "",
        "_columns": columns,
    }


def tabular_head_inventory(path: Path) -> dict[str, Any]:
    notes = ""
    columns: list[str] = []
    row_count: int | None = None
    try:
        if path.suffix.lower() == ".csv":
            head = pd.read_csv(path, nrows=5)
            columns = list(head.columns)
        elif path.suffix.lower() == ".jsonl":
            rows = []
            with path.open("r", encoding="utf-8", errors="replace") as fh:
                for _, line in zip(range(5), fh):
                    line = line.strip()
                    if line:
                        rows.append(json.loads(line))
            columns = sorted({k for row in rows if isinstance(row, dict) for k in row})
        elif path.suffix.lower() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            if isinstance(payload, dict):
                columns = sorted(payload.keys())
                row_count = 1
            elif isinstance(payload, list):
                row_count = len(payload)
                columns = sorted({k for row in payload[:5] if isinstance(row, dict) for k in row})
    except Exception as exc:
        notes = f"schema_read_error={type(exc).__name__}: {exc}"
    matched = matches_community_columns(columns)
    return {
        "file_path": rel_path(path),
        "file_type": file_type(path),
        "pipeline_layer": infer_layer(path),
        "row_count_if_fast": row_count,
        "column_count": len(columns),
        "matched_community_columns": "|".join(matched),
        "has_community_like_field": bool(matched),
        "schema_sample": json.dumps(columns[:50]),
        "notes": notes,
        "_columns": columns,
    }


def build_inventory(files: list[Path]) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    rows = []
    columns_by_file: dict[str, list[str]] = {}
    for path in files:
        if path.suffix.lower() == ".parquet":
            row = parquet_schema_inventory(path)
        else:
            row = tabular_head_inventory(path)
        columns_by_file[row["file_path"]] = list(row.pop("_columns", []))
        rows.append(row)
    return pd.DataFrame(rows), columns_by_file


def flatten_community_value(value: Any) -> list[str]:
    out: list[str] = []
    if is_missing(value):
        return out
    if isinstance(value, (list, tuple, set)):
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
                if isinstance(parsed, (list, tuple, set)):
                    for item in parsed:
                        out.extend(flatten_community_value(item))
                    return out
            except Exception:
                pass
    out.append(text)
    return out


def parse_community_tokens(value: Any) -> tuple[list[str], dict[str, bool], bool, bool]:
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

        # Standard communities: ASN:value. Large communities: ASN:value:value.
        for token in re.findall(r"\b\d+\s*:\s*\d+(?::\s*\d+)?\b", text):
            clean = token.replace(" ", "")
            tokens.append(clean)
            parse_success = True
            if clean.count(":") == 2:
                has_large = True
            for name, spec in WELL_KNOWN_COMMUNITIES.items():
                if clean == spec["pair"]:
                    hits[name] = True

        # Semicolon or comma separated raw collector output often contains
        # individual pair strings, already covered by the regex above.
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

    deduped = list(dict.fromkeys(tokens))
    return deduped, hits, parse_success, has_large


def existing_columns(path: Path, wanted: list[str]) -> list[str]:
    if path.suffix.lower() != ".parquet":
        return wanted
    try:
        cols = set(pq.ParquetFile(path).schema_arrow.names)
    except Exception:
        return []
    return [col for col in wanted if col in cols]


def iter_parquet_batches(path: Path, columns: list[str], row_limit: int | None = None, batch_size: int = 50000) -> Iterable[pd.DataFrame]:
    pf = pq.ParquetFile(path)
    remaining = row_limit
    for batch in pf.iter_batches(batch_size=batch_size, columns=columns):
        df = batch.to_pandas()
        if remaining is not None:
            if remaining <= 0:
                break
            if len(df) > remaining:
                df = df.head(remaining)
            remaining -= len(df)
        yield df
        if remaining is not None and remaining <= 0:
            break


def read_tabular_sample(path: Path, columns: list[str], row_limit: int) -> pd.DataFrame:
    try:
        if path.suffix.lower() == ".csv":
            return pd.read_csv(path, usecols=lambda c: c in columns, nrows=row_limit)
        if path.suffix.lower() == ".jsonl":
            return pd.read_json(path, lines=True, nrows=row_limit)
        if path.suffix.lower() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            if isinstance(payload, list):
                return pd.DataFrame(payload[:row_limit])
            if isinstance(payload, dict):
                return pd.DataFrame([payload])
    except Exception:
        return pd.DataFrame()
    return pd.DataFrame()


def choose_rows_per_file(total_budget: int, matched_file_count: int) -> int | None:
    if total_budget <= 0:
        return 5000
    if matched_file_count <= 0:
        return total_budget
    return max(50, int(math.ceil(total_budget / matched_file_count)))


def summarize_parse_for_column(
    file_path: Path,
    rel_file: str,
    community_col: str,
    dfs: Iterable[pd.DataFrame],
    hit_rows: list[dict[str, Any]],
    hit_limit: int = 5000,
) -> dict[str, Any]:
    sampled_rows = 0
    non_empty_rows = 0
    parse_success_rows = 0
    parse_failure_rows = 0
    hit_counts = Counter()
    unique_tokens: set[str] = set()
    example_values: list[str] = []
    has_large_count = 0

    for df in dfs:
        if community_col not in df.columns:
            continue
        series = df[community_col]
        sampled_rows += int(len(series))
        text = series.fillna("").astype(str)
        stripped = text.str.strip()
        lower = stripped.str.lower()
        non_empty_mask = ~lower.isin(["", "nan", "none", "null", "[]", "{}", "()"])
        non_empty_count = int(non_empty_mask.sum())
        non_empty_rows += non_empty_count
        if non_empty_count == 0:
            continue

        if len(example_values) < 5:
            examples = stripped[non_empty_mask].head(5 - len(example_values)).tolist()
            example_values.extend([safe_str(v)[:240] for v in examples])

        pair_mask = stripped.str.contains(r"\b\d+\s*:\s*\d+(?::\s*\d+)?\b", regex=True, na=False)
        hex_mask = lower.str.contains(r"\b(?:0x)?[0-9a-f]{8}\b", regex=True, na=False)
        decimal_mask = stripped.str.contains(r"\b\d{7,10}\b", regex=True, na=False)
        alias_mask = pd.Series(False, index=df.index)
        for spec in WELL_KNOWN_COMMUNITIES.values():
            for alias in spec["aliases"]:
                alias_mask = alias_mask | lower.str.replace("-", "_", regex=False).str.contains(alias.replace("-", "_"), regex=False, na=False)
        parse_success_mask = non_empty_mask & (pair_mask | hex_mask | decimal_mask | alias_mask)
        batch_parse_success = int(parse_success_mask.sum())
        parse_success_rows += batch_parse_success
        parse_failure_rows += int(non_empty_count - batch_parse_success)

        large_mask = stripped.str.contains(r"\b\d+\s*:\s*\d+\s*:\s*\d+\b", regex=True, na=False)
        has_large_count += int((non_empty_mask & large_mask).sum())

        for name, spec in WELL_KNOWN_COMMUNITIES.items():
            name_mask = (
                stripped.str.contains(re.escape(spec["pair"]), regex=True, na=False)
                | stripped.str.contains(re.escape(spec["decimal"]), regex=True, na=False)
                | lower.str.contains(re.escape(spec["hex"]), regex=True, na=False)
            )
            alias_name_mask = pd.Series(False, index=df.index)
            normalized_lower = lower.str.replace("-", "_", regex=False)
            for alias in spec["aliases"]:
                alias_name_mask = alias_name_mask | normalized_lower.str.contains(alias.replace("-", "_"), regex=False, na=False)
            hit_counts[name] += int((non_empty_mask & (name_mask | alias_name_mask)).sum())

        if len(unique_tokens) < 20000:
            for value in stripped[parse_success_mask].head(500).tolist():
                tokens, _, _, _ = parse_community_tokens(value)
                unique_tokens.update(tokens[:1000])
                if len(unique_tokens) >= 20000:
                    break

        if len(hit_rows) < hit_limit:
            any_hit_mask = pd.Series(False, index=df.index)
            for spec in WELL_KNOWN_COMMUNITIES.values():
                any_hit_mask = (
                    any_hit_mask
                    | stripped.str.contains(re.escape(spec["pair"]), regex=True, na=False)
                    | stripped.str.contains(re.escape(spec["decimal"]), regex=True, na=False)
                    | lower.str.contains(re.escape(spec["hex"]), regex=True, na=False)
                )
                normalized_lower = lower.str.replace("-", "_", regex=False)
                for alias in spec["aliases"]:
                    any_hit_mask = any_hit_mask | normalized_lower.str.contains(alias.replace("-", "_"), regex=False, na=False)
            hit_df = df[non_empty_mask & any_hit_mask].head(hit_limit - len(hit_rows))
            for row in hit_df.itertuples(index=False):
                row_data = row._asdict()
                value = row_data.get(community_col)
                tokens, hits, _, _ = parse_community_tokens(value)
                hit_rows.append(
                    {
                        "file_path": rel_file,
                        "community_column": community_col,
                        "raw_value": safe_str(value)[:500],
                        "parsed_tokens": "|".join(tokens[:50]),
                        "no_export": hits["NO_EXPORT"],
                        "no_advertise": hits["NO_ADVERTISE"],
                        "no_export_subconfed": hits["NO_EXPORT_SUBCONFED"],
                        "nopeer": hits["NOPEER"],
                        "event_id": row_data.get("event_id", ""),
                        "incident_id": row_data.get("incident_id", ""),
                        "prefix": row_data.get("prefix", ""),
                        "origin_as": row_data.get("origin_as", row_data.get("origin_as_norm", "")),
                        "as_path": row_data.get("as_path", row_data.get("as_path_clean", row_data.get("path_signature", ""))),
                        "collector": row_data.get("collector", row_data.get("collector_set", "")),
                        "timestamp": row_data.get("ts", row_data.get("timestamp", row_data.get("first_seen", ""))),
                    }
                )

    parser_notes = []
    if non_empty_rows == 0:
        parser_notes.append("community-like field present but values are empty in sampled rows")
    if parse_failure_rows > 0:
        parser_notes.append("some non-empty rows did not parse into known community token shapes")
    if has_large_count > 0:
        parser_notes.append("large-community-shaped tokens observed")

    return {
        "file_path": rel_file,
        "community_column": community_col,
        "sampled_rows": sampled_rows,
        "non_empty_rows": non_empty_rows,
        "parse_success_rows": parse_success_rows,
        "parse_failure_rows": parse_failure_rows,
        "no_export_rows": int(hit_counts["NO_EXPORT"]),
        "no_advertise_rows": int(hit_counts["NO_ADVERTISE"]),
        "no_export_subconfed_rows": int(hit_counts["NO_EXPORT_SUBCONFED"]),
        "nopeer_rows": int(hit_counts["NOPEER"]),
        "large_community_rows": int(has_large_count),
        "unique_community_count_sample": len(unique_tokens),
        "example_values": " || ".join(example_values),
        "parser_notes": "; ".join(parser_notes),
    }


def parse_community_fields(inventory: pd.DataFrame, args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame]:
    matched = inventory[inventory["has_community_like_field"] == True].copy()  # noqa: E712
    rows = []
    hit_rows: list[dict[str, Any]] = []
    rows_per_file = None if args.full_run else choose_rows_per_file(args.sample_rows, len(matched))

    for inv in matched.itertuples(index=False):
        path = Path(inv.file_path)
        if not path.exists():
            path = Path.cwd() / inv.file_path
        community_cols = [c for c in safe_str(inv.matched_community_columns).split("|") if c]
        if not community_cols:
            continue
        key_cols = existing_columns(path, KEY_COLUMNS) if path.suffix.lower() == ".parquet" else KEY_COLUMNS
        read_cols = list(dict.fromkeys(community_cols + key_cols))

        for community_col in community_cols:
            if path.suffix.lower() == ".parquet":
                columns = existing_columns(path, list(dict.fromkeys([community_col] + key_cols)))
                if community_col not in columns:
                    continue
                dfs = iter_parquet_batches(path, columns, row_limit=rows_per_file)
            else:
                df = read_tabular_sample(path, read_cols, rows_per_file or 5000)
                dfs = [df]
            rows.append(summarize_parse_for_column(path, inv.file_path, community_col, dfs, hit_rows))

    return pd.DataFrame(rows), pd.DataFrame(hit_rows)


def build_pipeline_retention(inventory: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    rows = []
    previous_present = False
    previous_layer = ""
    drop_recorded = False
    layer_order = [
        "raw_updates",
        "rel_annotated",
        "event_units",
        "incident_membership",
        "incident_tickets",
        "verifier_outputs",
    ]
    repair_targets = {
        "rel_annotated": "scripts/04_annotate_caida_rel.py",
        "event_units": "scripts/build_event_units.py",
        "incident_membership": "scripts/build_incident_aggregation.py",
        "incident_tickets": "scripts/build_incident_aggregation.py",
        "verifier_outputs": "scripts/run_r2b_vrp_aware_verifier_smoke.py / scripts/run_r2c_p2_path_legality_verifier_smoke.py",
    }

    for layer in layer_order:
        layer_df = inventory[inventory["pipeline_layer"] == layer]
        present = bool(layer_df["has_community_like_field"].any()) if not layer_df.empty else False
        cols = sorted(
            {
                col
                for value in layer_df.get("matched_community_columns", pd.Series(dtype=str)).fillna("")
                for col in safe_str(value).split("|")
                if col
            }
        )
        expected = [item.replace("<run_id>", args.run_id) for item in EXPECTED_LAYER_FILES[layer]]
        notes = []
        retained = "not_applicable"
        likely_dropped_at = ""
        repair_needed = False
        repair_target = ""

        if previous_present:
            retained = "yes" if present else "no"
            if layer == "rel_annotated" and layer_df.empty:
                retained = "not_applicable_no_rel_files"
                notes.append("no rel-annotated files were found in the current fixed-run layout")
            elif not present and not drop_recorded:
                likely_dropped_at = layer
                repair_needed = True
                repair_target = repair_targets.get(layer, "")
                drop_recorded = True
                notes.append(f"community-like field was present in {previous_layer} but absent in {layer}")
        elif layer != "raw_updates":
            retained = "previous_layer_absent"

        if layer_df.empty:
            notes.append("no scanned file found for this layer")
        if layer == "event_units" and previous_present and not present:
            notes.append("communities likely need propagation from raw updates into event construction")
        if layer in {"incident_membership", "incident_tickets"} and previous_present and not present:
            notes.append("incident builder currently lacks community-bearing member/card fields")

        rows.append(
            {
                "pipeline_layer": layer,
                "expected_files": " | ".join(expected),
                "scanned_files": int(len(layer_df)),
                "community_field_present": present,
                "community_field_columns": "|".join(cols),
                "retained_from_previous_layer": retained,
                "likely_dropped_at": likely_dropped_at,
                "repair_needed": repair_needed,
                "repair_target_script": repair_target,
                "notes": "; ".join(notes),
            }
        )
        if present:
            previous_present = True
            previous_layer = layer
    return pd.DataFrame(rows)


def build_join_feasibility(inventory: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for inv in inventory.itertuples(index=False):
        path = Path(inv.file_path)
        if not path.exists():
            path = Path.cwd() / inv.file_path
        columns = []
        try:
            if path.suffix.lower() == ".parquet":
                columns = pq.ParquetFile(path).schema_arrow.names
            else:
                columns = json.loads(inv.schema_sample) if safe_str(inv.schema_sample).startswith("[") else []
        except Exception:
            columns = []
        colset = set(columns)
        has_comm = bool(inv.has_community_like_field)
        incident_id = "incident_id" in colset
        member_id = "member_id" in colset or "event_id" in colset
        prefix = "prefix" in colset or "dominant_prefix" in colset
        origin = "origin_as" in colset or "origin_as_norm" in colset or "dominant_origin_as" in colset
        as_path = "as_path" in colset or "as_path_clean" in colset or "path_signature" in colset or "dominant_path_signature" in colset
        collector = "collector" in colset or "collector_set" in colset or "collector_union_count" in colset
        timestamp = "ts" in colset or "timestamp" in colset or "first_seen" in colset or "incident_start" in colset
        join_ready = has_comm and (incident_id or member_id) and prefix and (origin or as_path) and timestamp
        blocker = []
        if not has_comm:
            blocker.append("no community-like field")
        if not (incident_id or member_id):
            blocker.append("no incident_id/member_id/event_id in same table")
        if not prefix:
            blocker.append("no prefix key")
        if not (origin or as_path):
            blocker.append("no origin/path key")
        if not timestamp:
            blocker.append("no timestamp key")
        rows.append(
            {
                "file_path": inv.file_path,
                "pipeline_layer": inv.pipeline_layer,
                "join_key_available": join_ready,
                "incident_id_available": incident_id,
                "member_id_available": member_id,
                "prefix_available": prefix,
                "origin_as_available": origin,
                "as_path_available": as_path,
                "collector_available": collector,
                "timestamp_available": timestamp,
                "community_join_feasibility": "ready" if join_ready else "blocked",
                "blocker": "; ".join(blocker),
            }
        )
    return pd.DataFrame(rows)


def aggregate_summary(
    inventory: pd.DataFrame,
    parse_df: pd.DataFrame,
    retention_df: pd.DataFrame,
    join_df: pd.DataFrame,
    args: argparse.Namespace,
) -> dict[str, Any]:
    field_present = bool(inventory["has_community_like_field"].any()) if not inventory.empty else False
    layers_with_communities = sorted(inventory.loc[inventory["has_community_like_field"] == True, "pipeline_layer"].unique()) if field_present else []  # noqa: E712
    parse_totals = {
        "sampled_rows": int(parse_df["sampled_rows"].sum()) if not parse_df.empty else 0,
        "non_empty_rows": int(parse_df["non_empty_rows"].sum()) if not parse_df.empty else 0,
        "parse_success_rows": int(parse_df["parse_success_rows"].sum()) if not parse_df.empty else 0,
        "parse_failure_rows": int(parse_df["parse_failure_rows"].sum()) if not parse_df.empty else 0,
        "no_export_rows": int(parse_df["no_export_rows"].sum()) if not parse_df.empty else 0,
        "no_advertise_rows": int(parse_df["no_advertise_rows"].sum()) if not parse_df.empty else 0,
        "no_export_subconfed_rows": int(parse_df["no_export_subconfed_rows"].sum()) if not parse_df.empty else 0,
        "nopeer_rows": int(parse_df["nopeer_rows"].sum()) if not parse_df.empty else 0,
        "large_community_rows": int(parse_df["large_community_rows"].sum()) if "large_community_rows" in parse_df.columns and not parse_df.empty else 0,
    }
    raw_rows = inventory.loc[inventory["pipeline_layer"] == "raw_updates", "row_count_if_fast"]
    raw_row_count = int(pd.to_numeric(raw_rows, errors="coerce").fillna(0).sum()) if not raw_rows.empty else 0
    raw_parse_rows = parse_df[parse_df["file_path"].str.contains("__collector_", regex=False, na=False)]
    raw_non_empty = int(raw_parse_rows["non_empty_rows"].sum()) if not raw_parse_rows.empty else 0
    raw_sampled = int(raw_parse_rows["sampled_rows"].sum()) if not raw_parse_rows.empty else 0
    incident_join_ready = bool(join_df["join_key_available"].any()) if not join_df.empty else False
    first_drop = retention_df.loc[retention_df["repair_needed"] == True, "likely_dropped_at"]  # noqa: E712
    return {
        "run_id": args.run_id,
        "run_date": args.run_date,
        "run_root": args.run_root,
        "output_dir": args.output_dir,
        "mode": "full" if args.full_run else "sample",
        "sample_rows": int(args.sample_rows),
        "scanned_files": int(len(inventory)),
        "files_with_community_like_field": int(inventory["has_community_like_field"].sum()) if not inventory.empty else 0,
        "community_field_present": field_present,
        "layers_with_communities": layers_with_communities,
        "raw_update_row_count_if_fast": raw_row_count,
        "raw_community_non_empty_rows_observed": raw_non_empty,
        "raw_community_sampled_rows": raw_sampled,
        "raw_community_observed_non_empty_rate": (raw_non_empty / raw_sampled) if raw_sampled else None,
        "parse_totals": parse_totals,
        "well_known_community_rows_observed": {
            "NO_EXPORT": parse_totals["no_export_rows"],
            "NO_ADVERTISE": parse_totals["no_advertise_rows"],
            "NO_EXPORT_SUBCONFED": parse_totals["no_export_subconfed_rows"],
            "NOPEER": parse_totals["nopeer_rows"],
        },
        "incident_join_ready": incident_join_ready,
        "first_likely_drop_layer": str(first_drop.iloc[0]) if not first_drop.empty else "",
        "can_enter_r2d1": bool(field_present and incident_join_ready),
        "pipeline_repair_needed": bool(field_present and not incident_join_ready),
        "no_export_attack_detected": False,
        "verifier_verdict_modified": False,
        "learning_layer_trained": False,
        "new_external_evidence_downloaded": False,
        "stealth_verifier_implemented": False,
    }


def build_readiness_matrix(summary: dict[str, Any], parse_df: pd.DataFrame, join_df: pd.DataFrame, inventory: pd.DataFrame) -> pd.DataFrame:
    join_ready = bool(summary["incident_join_ready"])
    parsed_success = int(summary["parse_totals"]["parse_success_rows"]) > 0
    direct_available = bool(summary["community_field_present"])
    large_direct = bool(
        inventory["matched_community_columns"].fillna("").str.contains("large", case=False).any()
        if not inventory.empty
        else False
    ) or int(summary["parse_totals"].get("large_community_rows", 0)) > 0
    rows = []

    wk_map = {
        "NO_EXPORT": "no_export_rows",
        "NO_ADVERTISE": "no_advertise_rows",
        "NO_EXPORT_SUBCONFED": "no_export_subconfed_rows",
        "NOPEER": "nopeer_rows",
    }
    for item, count_col in wk_map.items():
        hit_count = int(parse_df[count_col].sum()) if count_col in parse_df.columns and not parse_df.empty else 0
        item_parsed = hit_count > 0
        rows.append(
            {
                "evidence_item": item,
                "direct_field_available": direct_available,
                "parsed_successfully": item_parsed,
                "incident_join_ready": join_ready,
                "can_support_stealth_evidence": bool(direct_available and item_parsed and join_ready),
                "evidence_strength": "aligned_raw_attribute_available" if direct_available and item_parsed else "field_available_but_not_observed",
                "current_blocker": "" if join_ready else "community field not retained on incident/member table",
                "next_required_action": "R-2D-1 community-aware stealth evidence branch" if join_ready else "propagate communities from raw updates into event_units and incident_membership",
                "allowed_claim": f"{item} field pattern observed in raw communities" if item_parsed else f"{item} parser supported but no observed rows",
                "forbidden_claim": "confirmed NO_EXPORT attack; NO_EXPORT absent means safe; low visibility means NO_EXPORT",
            }
        )

    rows.extend(
        [
            {
                "evidence_item": "provider_specific_communities",
                "direct_field_available": direct_available,
                "parsed_successfully": parsed_success,
                "incident_join_ready": join_ready,
                "can_support_stealth_evidence": bool(direct_available and parsed_success and join_ready),
                "evidence_strength": "weak_to_medium_if_joined_with_provenance" if direct_available else "unavailable",
                "current_blocker": "" if join_ready else "raw communities are not incident-joined",
                "next_required_action": "retain raw community tokens and add provider-specific interpretation later",
                "allowed_claim": "provider-specific community tokens observed" if direct_available else "provider-specific community evidence unavailable",
                "forbidden_claim": "provider-specific community alone proves stealth attack",
            },
            {
                "evidence_item": "large_communities",
                "direct_field_available": large_direct,
                "parsed_successfully": large_direct,
                "incident_join_ready": join_ready,
                "can_support_stealth_evidence": bool(large_direct and join_ready),
                "evidence_strength": "weak_to_medium_if_semantics_are_decoded" if large_direct else "unavailable_or_not_observed",
                "current_blocker": "" if large_direct and join_ready else "large communities not incident-ready or not observed",
                "next_required_action": "preserve large-community-shaped tokens and decode semantics only in a later branch",
                "allowed_claim": "large-community-shaped tokens observed" if large_direct else "large community evidence unavailable or not observed",
                "forbidden_claim": "large community means NO_EXPORT or confirmed evasion",
            },
            {
                "evidence_item": "low_visibility_symptom",
                "direct_field_available": bool((inventory["pipeline_layer"] == "incident_tickets").any()) if not inventory.empty else False,
                "parsed_successfully": True,
                "incident_join_ready": True,
                "can_support_stealth_evidence": True,
                "evidence_strength": "monitor_only_weak_symptom",
                "current_blocker": "not independent community evidence",
                "next_required_action": "use only as monitor-side context; combine with direct community evidence after repair",
                "allowed_claim": "only monitor-evasion-like symptom available",
                "forbidden_claim": "low visibility means NO_EXPORT",
            },
            {
                "evidence_item": "collector_asymmetry_symptom",
                "direct_field_available": bool((inventory["pipeline_layer"] == "incident_tickets").any()) if not inventory.empty else False,
                "parsed_successfully": True,
                "incident_join_ready": True,
                "can_support_stealth_evidence": True,
                "evidence_strength": "monitor_only_weak_symptom",
                "current_blocker": "not independent community evidence",
                "next_required_action": "treat as Stage 1 context until direct community fields are retained",
                "allowed_claim": "collector asymmetry symptom available",
                "forbidden_claim": "collector asymmetry proves NO_EXPORT or stealth attack",
            },
        ]
    )
    return pd.DataFrame(rows)


def markdown_table(df: pd.DataFrame, columns: list[str]) -> str:
    if df.empty:
        return "_No rows._"
    lines = []
    lines.append("| " + " | ".join(columns) + " |")
    lines.append("| " + " | ".join(["---"] * len(columns)) + " |")
    for _, row in df[columns].iterrows():
        values = [safe_str(row[col]).replace("|", "/") for col in columns]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def write_retention_markdown(path: Path, retention_df: pd.DataFrame) -> None:
    content = [
        "# R-2D-0 Pipeline Community Retention Audit",
        "",
        "This table reports where community-like fields are retained in the current fixed S2 data layout.",
        "",
        markdown_table(
            retention_df,
            [
                "pipeline_layer",
                "scanned_files",
                "community_field_present",
                "community_field_columns",
                "retained_from_previous_layer",
                "likely_dropped_at",
                "repair_needed",
                "repair_target_script",
            ],
        ),
        "",
        "Safety note: field absence is not benign, and field presence is not a confirmed NO_EXPORT attack.",
    ]
    path.write_text("\n".join(content) + "\n", encoding="utf-8")


def write_readiness_markdown(path: Path, readiness_df: pd.DataFrame) -> None:
    content = [
        "# R-2D-0 Stealth Evidence Readiness Matrix",
        "",
        markdown_table(
            readiness_df,
            [
                "evidence_item",
                "direct_field_available",
                "parsed_successfully",
                "incident_join_ready",
                "can_support_stealth_evidence",
                "evidence_strength",
                "current_blocker",
                "next_required_action",
            ],
        ),
        "",
        "Forbidden claims remain explicit: NO_EXPORT present is not a confirmed attack, NO_EXPORT absent is not safe, and low visibility does not mean NO_EXPORT.",
    ]
    path.write_text("\n".join(content) + "\n", encoding="utf-8")


def write_report(path: Path, summary: dict[str, Any], retention_df: pd.DataFrame, readiness_df: pd.DataFrame) -> None:
    layers = ", ".join(summary["layers_with_communities"]) if summary["layers_with_communities"] else "none"
    wk = summary["well_known_community_rows_observed"]
    first_drop = summary["first_likely_drop_layer"] or "not identified"
    can_r2d1 = "yes" if summary["can_enter_r2d1"] else "no"
    repair = "yes" if summary["pipeline_repair_needed"] else "no"
    content = [
        "# R-2D-0 Communities / NO_EXPORT Field Availability Audit Report",
        "",
        f"Run id: `{summary['run_id']}`",
        "",
        f"Run date: `{summary['run_date']}`",
        "",
        "## Answers",
        "",
        f"1. Current data has communities field? `{summary['community_field_present']}`.",
        f"2. Pipeline layers retaining community-like fields: `{layers}`.",
        (
            "3. Well-known community parser result: "
            f"NO_EXPORT `{wk['NO_EXPORT']}`, NO_ADVERTISE `{wk['NO_ADVERTISE']}`, "
            f"NO_EXPORT_SUBCONFED `{wk['NO_EXPORT_SUBCONFED']}`, NOPEER `{wk['NOPEER']}` observed rows."
        ),
        f"4. Join to incident/member/component is ready? `{summary['incident_join_ready']}`.",
        f"5. If missing, likely missing/drop layer: `{first_drop}`.",
        f"6. Can enter R-2D-1 community-aware stealth evidence branch now? `{can_r2d1}`.",
        f"7. Pipeline repair needed? `{repair}`.",
        "8. Did this stage detect a NO_EXPORT attack? `no`.",
        "9. Did this stage modify verifier verdicts? `no`.",
        "10. Did this stage train the learning layer? `no`.",
        "11. Recommended next step: repair community retention from raw updates into event and incident/member tables before R-2D-1 if incident join is not ready; otherwise start a conservative R-2D-1 stealth evidence branch.",
        "12. CCF-A meaning: this audit checks whether stealth/community evidence can become an explicit Stage 2 evidence channel rather than hidden monitor-only symptoms.",
        "",
        "## Pipeline Retention",
        "",
        markdown_table(
            retention_df,
            [
                "pipeline_layer",
                "community_field_present",
                "community_field_columns",
                "retained_from_previous_layer",
                "likely_dropped_at",
                "repair_needed",
                "repair_target_script",
            ],
        ),
        "",
        "## Stealth Evidence Readiness",
        "",
        markdown_table(
            readiness_df,
            [
                "evidence_item",
                "direct_field_available",
                "parsed_successfully",
                "incident_join_ready",
                "can_support_stealth_evidence",
                "current_blocker",
                "allowed_claim",
                "forbidden_claim",
            ],
        ),
        "",
        "## Safety Boundary",
        "",
        "- NO_EXPORT present is not a confirmed attack.",
        "- NO_EXPORT absent is not safe.",
        "- Low visibility is not confirmed NO_EXPORT.",
        "- This audit did not implement a stealth verifier, did not run poisoning/evasion, and did not train learning.",
    ]
    path.write_text("\n".join(content) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    files = collect_scan_files(args)
    inventory_df, _ = build_inventory(files)
    inventory_public = inventory_df.drop(columns=[col for col in inventory_df.columns if col.startswith("_")], errors="ignore")
    inventory_public.to_csv(output_dir / "r2d0_community_field_inventory.csv", index=False)
    write_json(output_dir / "r2d0_community_field_inventory.json", inventory_public.to_dict(orient="records"))

    parse_df, hits_df = parse_community_fields(inventory_public, args)
    parse_df.to_csv(output_dir / "r2d0_community_parse_sample.csv", index=False)
    hits_df.to_csv(output_dir / "r2d0_well_known_community_hits_sample.csv", index=False)

    retention_df = build_pipeline_retention(inventory_public, args)
    retention_df.to_csv(output_dir / "r2d0_pipeline_community_retention_audit.csv", index=False)
    write_retention_markdown(output_dir / "r2d0_pipeline_community_retention_audit.md", retention_df)

    join_df = build_join_feasibility(inventory_public)
    join_df.to_csv(output_dir / "r2d0_community_incident_join_feasibility.csv", index=False)

    summary = aggregate_summary(inventory_public, parse_df, retention_df, join_df, args)
    readiness_df = build_readiness_matrix(summary, parse_df, join_df, inventory_public)
    readiness_df.to_csv(output_dir / "r2d0_stealth_evidence_readiness_matrix.csv", index=False)
    write_readiness_markdown(output_dir / "r2d0_stealth_evidence_readiness_matrix.md", readiness_df)

    write_json(output_dir / "r2d0_summary.json", summary)
    write_report(output_dir / "r2d0_report.md", summary, retention_df, readiness_df)

    print(json.dumps(summary, indent=2, sort_keys=True, default=json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
