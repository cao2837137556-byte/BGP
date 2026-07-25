#!/usr/bin/env python3
"""Build N-FRONTEND-1 peer-aware causal route transitions and micro-events.

This is a bounded contract implementation. It performs reversible exact
observation deduplication, past-only per-peer route-state comparison, and
bounded micro-event aggregation. It does not suppress operational background,
attach attack truth, or train a model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from r_mem_canonical_observation_v2 import canonical_observation_id


DEFAULT_CONFIG = Path("configs/n_frontend1_causal_transition_v01.json")
TRANSITION_COLUMNS = [
    "transition_id",
    "transition_ts",
    "collector",
    "peer_address",
    "peer_asn",
    "prefix",
    "path_id",
    "transition_family",
    "old_route_signature",
    "new_route_signature",
    "origin_changed",
    "path_changed",
    "communities_changed",
    "next_hop_changed",
    "old_origin_as",
    "new_origin_as",
    "old_as_path",
    "new_as_path",
    "old_communities",
    "new_communities",
    "old_next_hop",
    "new_next_hop",
    "has_no_export_before",
    "has_no_export_after",
    "state_age_sec",
    "state_known_before",
    "state_known_after",
    "same_timestamp_ambiguous",
    "member_observation_count",
    "member_observation_ids",
    "source_copy_count",
    "source_files",
]
DEDUP_AUDIT_COLUMNS = [
    "canonical_observation_key",
    "observation_id",
    "source_copy_count",
    "excluded_duplicate_copy_count",
    "source_files",
    "input_parquets",
    "reversible",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        action="append",
        default=[],
        help="Parquet file or directory. Repeat to provide multiple roots.",
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--output-dir")
    parser.add_argument("--start-ts", type=float)
    parser.add_argument("--end-ts", type=float)
    parser.add_argument("--max-files", type=int, default=0)
    parser.add_argument("--max-rows", type=int, default=500_000)
    parser.add_argument(
        "--max-rows-per-collector",
        type=int,
        default=0,
        help=(
            "Optional deterministic cap per collector. Use with "
            "--require-collector for balanced bounded smoke tests."
        ),
    )
    parser.add_argument(
        "--require-collector",
        action="append",
        default=[],
        help="Collector that must be present after row-time filtering. Repeat as needed.",
    )
    parser.add_argument("--batch-size", type=int, default=100_000)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def load_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def stable_hash(value: Any) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def scalar(value: Any) -> Any:
    if hasattr(value, "as_py"):
        value = value.as_py()
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def text(value: Any) -> str | None:
    value = scalar(value)
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def normalize_communities(value: Any) -> list[str]:
    value = scalar(value)
    if value is None:
        return []
    if not isinstance(value, (str, bytes)) and hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, (list, tuple, set)):
        items = value
    else:
        stripped = str(value).strip()
        if not stripped:
            return []
        if stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
                items = parsed if isinstance(parsed, list) else [stripped]
            except json.JSONDecodeError:
                items = stripped.replace(",", " ").split()
        else:
            items = stripped.replace(";", " ").replace(",", " ").split()
    return sorted({str(item).strip() for item in items if str(item).strip()})


def normalize_update_type(value: Any) -> str:
    normalized = (text(value) or "").upper()
    if normalized in {"A", "ANNOUNCEMENT", "ANNOUNCE"}:
        return "A"
    if normalized in {"W", "WITHDRAWAL", "WITHDRAW"}:
        return "W"
    return normalized or "UNKNOWN"


def discover_inputs(values: Iterable[str], max_files: int) -> list[Path]:
    files: set[Path] = set()
    for raw in values:
        path = Path(raw)
        if path.is_file() and path.suffix.lower() == ".parquet":
            files.add(path.resolve())
        elif path.is_dir():
            files.update(item.resolve() for item in path.rglob("*.parquet"))
        else:
            raise FileNotFoundError(f"input does not exist or is not parquet: {path}")
    ordered = sorted(files, key=lambda item: str(item).lower())
    return ordered[:max_files] if max_files > 0 else ordered


def choose_path_id_column(
    schemas: list[set[str]], config: dict[str, Any]
) -> tuple[str | None, list[str]]:
    present = sorted(
        {
            candidate
            for candidate in config["path_id_candidates"]
            if any(candidate in schema for schema in schemas)
        }
    )
    if not present:
        return None, []
    if len(present) > 1:
        raise ValueError(f"multiple path-id columns found; contract is ambiguous: {present}")
    if present and any(present[0] not in schema for schema in schemas):
        raise ValueError(
            f"path-id column is not present in every input schema: {present[0]}"
        )
    return present[0], present


def load_bounded_rows(
    files: list[Path],
    config: dict[str, Any],
    start_ts: float | None,
    end_ts: float | None,
    max_rows: int,
    max_rows_per_collector: int,
    required_collectors: list[str],
    batch_size: int,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if not files:
        raise FileNotFoundError("no parquet inputs discovered")

    required = list(config["required_columns"])
    schemas = [set(pq.ParquetFile(path).schema_arrow.names) for path in files]
    missing_by_file = {
        str(path): sorted(set(required) - schema)
        for path, schema in zip(files, schemas)
        if set(required) - schema
    }
    if missing_by_file:
        raise ValueError(f"required canonical columns missing: {missing_by_file}")

    path_id_column, path_id_columns_present = choose_path_id_column(schemas, config)
    columns = required + ([path_id_column] if path_id_column else [])
    frames: list[pd.DataFrame] = []
    selected_rows = 0
    source_rows_scanned = 0
    selected_rows_by_collector: Counter[str] = Counter()
    source_rows_scanned_by_file: Counter[str] = Counter()
    required_collector_set = {item.strip() for item in required_collectors if item.strip()}

    for path in files:
        parquet_file = pq.ParquetFile(path)
        for batch in parquet_file.iter_batches(batch_size=batch_size, columns=columns):
            frame = batch.to_pandas()
            source_rows_scanned += len(frame)
            source_rows_scanned_by_file[str(path)] += len(frame)
            if start_ts is not None:
                frame = frame[pd.to_numeric(frame["ts"], errors="coerce") >= start_ts]
            if end_ts is not None:
                frame = frame[pd.to_numeric(frame["ts"], errors="coerce") < end_ts]
            if frame.empty:
                continue
            if max_rows_per_collector > 0:
                bounded_parts: list[pd.DataFrame] = []
                for collector_value, group in frame.groupby(
                    "collector", sort=False, dropna=False
                ):
                    collector = text(collector_value)
                    if collector is None:
                        bounded_parts.append(group)
                        continue
                    remaining = (
                        max_rows_per_collector
                        - selected_rows_by_collector[collector]
                    )
                    if remaining > 0:
                        bounded_parts.append(group.iloc[:remaining])
                if not bounded_parts:
                    continue
                frame = pd.concat(bounded_parts).sort_index()
            frame["_input_parquet"] = str(path)
            if max_rows > 0 and selected_rows + len(frame) > max_rows:
                frame = frame.iloc[: max_rows - selected_rows].copy()
            frames.append(frame)
            selected_rows += len(frame)
            selected_rows_by_collector.update(
                collector
                for collector in frame["collector"].map(text).tolist()
                if collector is not None
            )
            if max_rows > 0 and selected_rows >= max_rows:
                break
            if (
                max_rows_per_collector > 0
                and required_collector_set
                and all(
                    selected_rows_by_collector[item] >= max_rows_per_collector
                    for item in required_collector_set
                )
            ):
                break
        if max_rows > 0 and selected_rows >= max_rows:
            break
        if (
            max_rows_per_collector > 0
            and required_collector_set
            and all(
                selected_rows_by_collector[item] >= max_rows_per_collector
                for item in required_collector_set
            )
        ):
            break

    if not frames:
        raise ValueError("no rows selected after applying bounds")

    data = pd.concat(frames, ignore_index=True)
    data["ts"] = pd.to_numeric(data["ts"], errors="coerce")
    if data["ts"].isna().any():
        raise ValueError(f"selected rows contain {int(data['ts'].isna().sum())} invalid timestamps")
    data["communities"] = data["communities"].map(normalize_communities)
    data["type"] = data["type"].map(normalize_update_type)
    data["path_id"] = data[path_id_column].map(text) if path_id_column else None
    observed_collectors = sorted(
        value for value in data["collector"].map(text).dropna().unique().tolist()
    )
    missing_required_collectors = sorted(
        required_collector_set - set(observed_collectors)
    )
    if missing_required_collectors:
        raise ValueError(
            "required collectors absent after row-time filtering: "
            f"{missing_required_collectors}; observed={observed_collectors}"
        )
    sort_columns = [
        "ts",
        "collector",
        "peer_address",
        "prefix",
        "path_id",
        "observation_id",
        "source_file",
        "_input_parquet",
    ]
    data = data.sort_values(sort_columns, kind="mergesort", na_position="last").reset_index(
        drop=True
    )
    metadata = {
        "input_file_count": len(files),
        "input_files": [str(path) for path in files],
        "source_rows_scanned": source_rows_scanned,
        "source_rows_scanned_by_file": dict(
            sorted(source_rows_scanned_by_file.items())
        ),
        "selected_rows": len(data),
        "selected_rows_by_collector": {
            str(key): int(value)
            for key, value in sorted(
                data["collector"].map(text).dropna().value_counts().items()
            )
        },
        "required_collectors": sorted(required_collector_set),
        "missing_required_collectors": missing_required_collectors,
        "observed_collectors": observed_collectors,
        "observed_projects": sorted(
            value for value in data["project"].map(text).dropna().unique().tolist()
        ),
        "selected_ts_min": float(data["ts"].min()),
        "selected_ts_max": float(data["ts"].max()),
        "selection_truncated_by_max_rows": bool(
            max_rows > 0 and selected_rows >= max_rows
        ),
        "selection_truncated_by_per_collector_cap": bool(
            max_rows_per_collector > 0
            and any(
                count >= max_rows_per_collector
                for count in selected_rows_by_collector.values()
            )
        ),
        "path_id_column": path_id_column,
        "path_id_columns_present": path_id_columns_present,
        "path_id_non_null_rows": int(data["path_id"].notna().sum()),
        "path_id_field_present": bool(path_id_column),
        # A populated field alone does not prove that every Add-Path observation
        # was decoded with its path identifier. That requires parser/peer metadata.
        "add_path_support_ready": False,
        "state_identity_missing_row_count": int(
            data["peer_address"].map(text).isna().sum()
            + data["prefix"].map(text).isna().sum()
        ),
    }
    return data, metadata


def semantic_observation_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "ts": float(row["ts"]),
        "collector": text(row.get("collector")),
        "project": text(row.get("project")),
        "type": normalize_update_type(row.get("type")),
        "peer_asn": scalar(row.get("peer_asn")),
        "peer_address": text(row.get("peer_address")),
        "prefix": text(row.get("prefix")),
        "path_id": text(row.get("path_id")),
        "as_path": text(row.get("as_path")),
        "origin_as": text(row.get("origin_as")),
        "origin_provenance": text(row.get("origin_provenance")),
        "communities": normalize_communities(row.get("communities")),
        "next_hop": text(row.get("next_hop")),
    }


def deduplicate_observations(
    data: pd.DataFrame,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    missing_observation_id_count = 0
    for position, row in enumerate(data.to_dict(orient="records")):
        observation_id = text(row.get("observation_id"))
        if observation_id is None:
            missing_observation_id_count += 1
            key = f"missing:{position}:{stable_hash(semantic_observation_payload(row))}"
        else:
            key = f"id:{observation_id}"
        groups.setdefault(key, []).append(row)

    unique_rows: list[dict[str, Any]] = []
    duplicate_audit: list[dict[str, Any]] = []
    collision_count = 0
    for key, rows in groups.items():
        signatures = {
            stable_hash(semantic_observation_payload(row))
            for row in rows
        }
        if len(signatures) != 1:
            collision_count += 1
            raise ValueError(
                f"observation_id collision with different semantic payloads: {key}"
            )
        representative = dict(rows[0])
        source_files = sorted(
            {
                item
                for row in rows
                for item in [text(row.get("source_file"))]
                if item is not None
            }
        )
        input_parquets = sorted(
            {
                item
                for row in rows
                for item in [text(row.get("_input_parquet"))]
                if item is not None
            }
        )
        representative["source_files"] = source_files
        representative["input_parquets"] = input_parquets
        representative["source_copy_count"] = len(rows)
        representative["excluded_duplicate_copy_count"] = max(0, len(rows) - 1)
        representative["canonical_observation_key"] = key
        unique_rows.append(representative)
        if len(rows) > 1:
            duplicate_audit.append(
                {
                    "canonical_observation_key": key,
                    "observation_id": text(representative.get("observation_id")),
                    "source_copy_count": len(rows),
                    "excluded_duplicate_copy_count": len(rows) - 1,
                    "source_files": source_files,
                    "input_parquets": input_parquets,
                    "reversible": True,
                }
            )

    unique_rows.sort(
        key=lambda row: (
            float(row["ts"]),
            text(row.get("collector")) or "",
            text(row.get("peer_address")) or "",
            text(row.get("prefix")) or "",
            text(row.get("path_id")) or "",
            text(row.get("observation_id")) or "",
            text(row.get("source_file")) or "",
        )
    )
    summary = {
        "exact_unique_observation_count": len(unique_rows),
        "duplicate_group_count": len(duplicate_audit),
        "excluded_duplicate_copy_count": sum(
            row["excluded_duplicate_copy_count"] for row in duplicate_audit
        ),
        "missing_observation_id_count": missing_observation_id_count,
        "observation_id_collision_count": collision_count,
    }
    return unique_rows, duplicate_audit, summary


def route_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "origin_as": text(row.get("origin_as")),
        "as_path": text(row.get("as_path")),
        "communities": normalize_communities(row.get("communities")),
        "next_hop": text(row.get("next_hop")),
    }


def route_signature(route: dict[str, Any] | None) -> str | None:
    return stable_hash(route) if route is not None else None


def has_no_export(route: dict[str, Any] | None) -> bool:
    return route is not None and "65535:65281" in route.get("communities", [])


def state_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    peer_address = text(row.get("peer_address"))
    prefix = text(row.get("prefix"))
    if peer_address is None or prefix is None:
        # Never merge observations whose per-peer route identity is incomplete.
        unique_fallback = (
            text(row.get("observation_id"))
            or stable_hash(semantic_observation_payload(row))
        )
        return (
            text(row.get("collector")) or "",
            peer_address or f"missing-peer:{unique_fallback}",
            prefix or f"missing-prefix:{unique_fallback}",
            text(row.get("path_id")) or "",
        )
    return (
        text(row.get("collector")) or "",
        peer_address,
        prefix,
        text(row.get("path_id")) or "",
    )


def transition_identity_payload(
    row: dict[str, Any],
    family: str,
    old_signature: str | None,
    new_signature: str | None,
    member_ids: list[str],
) -> dict[str, Any]:
    return {
        "state_key": state_key(row),
        "ts": float(row["ts"]),
        "transition_family": family,
        "old_route_signature": old_signature,
        "new_route_signature": new_signature,
        "member_observation_ids": member_ids,
    }


def make_transition(
    rows: list[dict[str, Any]],
    family: str,
    old_route: dict[str, Any] | None,
    new_route: dict[str, Any] | None,
    state_known_before: bool,
    state_known_after: bool,
    state_age_sec: float | None,
    ambiguous: bool,
) -> dict[str, Any]:
    representative = rows[0]
    member_ids = sorted(
        text(row.get("observation_id"))
        or stable_hash(semantic_observation_payload(row))
        for row in rows
    )
    old_signature = route_signature(old_route)
    new_signature = route_signature(new_route)
    old_route = old_route or {}
    new_route = new_route or {}
    comparable_routes = bool(old_signature is not None and new_signature is not None)
    transition = {
        "transition_ts": float(representative["ts"]),
        "collector": text(representative.get("collector")),
        "peer_address": text(representative.get("peer_address")),
        "peer_asn": scalar(representative.get("peer_asn")),
        "prefix": text(representative.get("prefix")),
        "path_id": text(representative.get("path_id")),
        "transition_family": family,
        "old_route_signature": old_signature,
        "new_route_signature": new_signature,
        "origin_changed": comparable_routes
        and old_route.get("origin_as") != new_route.get("origin_as"),
        "path_changed": comparable_routes
        and old_route.get("as_path") != new_route.get("as_path"),
        "communities_changed": comparable_routes
        and old_route.get("communities", []) != new_route.get("communities", []),
        "next_hop_changed": comparable_routes
        and old_route.get("next_hop") != new_route.get("next_hop"),
        "old_origin_as": old_route.get("origin_as"),
        "new_origin_as": new_route.get("origin_as"),
        "old_as_path": old_route.get("as_path"),
        "new_as_path": new_route.get("as_path"),
        "old_communities": old_route.get("communities", []),
        "new_communities": new_route.get("communities", []),
        "old_next_hop": old_route.get("next_hop"),
        "new_next_hop": new_route.get("next_hop"),
        "has_no_export_before": has_no_export(old_route),
        "has_no_export_after": has_no_export(new_route),
        "state_age_sec": state_age_sec,
        "state_known_before": state_known_before,
        "state_known_after": state_known_after,
        "same_timestamp_ambiguous": ambiguous,
        "member_observation_count": len(rows),
        "member_observation_ids": member_ids,
        "source_copy_count": sum(int(row["source_copy_count"]) for row in rows),
        "source_files": sorted(
            {
                source
                for row in rows
                for source in row.get("source_files", [])
            }
        ),
    }
    transition["transition_id"] = stable_hash(
        transition_identity_payload(
            representative,
            family,
            old_signature,
            new_signature,
            member_ids,
        )
    )
    return transition


def classify_single(
    row: dict[str, Any],
    previous: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    update_type = normalize_update_type(row.get("type"))
    current_ts = float(row["ts"])
    state_known_before = previous is not None and bool(previous["known"])
    state_age = (
        current_ts - float(previous["last_ts"])
        if previous is not None
        else None
    )
    if state_age is not None and state_age < 0:
        raise ValueError("causality violation: state timestamp exceeds current row")

    if previous is not None and not previous["known"]:
        if update_type == "A":
            new_route = route_payload(row)
            transition = make_transition(
                [row],
                "state_recovery_announce",
                None,
                new_route,
                False,
                True,
                state_age,
                False,
            )
            return transition, {
                "known": True,
                "active": True,
                "route": new_route,
                "last_route": new_route,
                "last_ts": current_ts,
            }
        transition = make_transition(
            [row],
            "state_recovery_withdraw",
            None,
            None,
            False,
            update_type == "W",
            state_age,
            False,
        )
        return transition, {
            "known": update_type == "W",
            "active": False,
            "route": None,
            "last_route": None,
            "last_ts": current_ts,
        }

    if update_type == "A":
        new_route = route_payload(row)
        if previous is None:
            family = "bootstrap_announce"
            old_route = None
        elif previous["active"]:
            old_route = previous["route"]
            family = (
                "identical_reannouncement"
                if route_signature(old_route) == route_signature(new_route)
                else "announcement_change"
            )
        else:
            old_route = previous.get("last_route")
            family = (
                "withdraw_reannounce_same"
                if route_signature(old_route) == route_signature(new_route)
                else "withdraw_reannounce_changed"
            )
        transition = make_transition(
            [row],
            family,
            old_route,
            new_route,
            state_known_before,
            True,
            state_age,
            False,
        )
        return transition, {
            "known": True,
            "active": True,
            "route": new_route,
            "last_route": new_route,
            "last_ts": current_ts,
        }

    if update_type == "W":
        if previous is None:
            family = "bootstrap_withdrawal"
            old_route = None
        elif previous["active"]:
            family = "withdrawal"
            old_route = previous["route"]
        else:
            family = "repeated_withdrawal"
            old_route = previous.get("last_route")
        transition = make_transition(
            [row],
            family,
            old_route,
            None,
            state_known_before,
            True,
            state_age,
            False,
        )
        return transition, {
            "known": True,
            "active": False,
            "route": None,
            "last_route": old_route,
            "last_ts": current_ts,
        }

    transition = make_transition(
        [row],
        "unsupported_update_type",
        previous.get("route") if previous else None,
        None,
        state_known_before,
        False,
        state_age,
        False,
    )
    return transition, {
        "known": False,
        "active": False,
        "route": None,
        "last_route": previous.get("last_route") if previous else None,
        "last_ts": current_ts,
    }


def build_transitions(
    unique_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    states: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    transitions: list[dict[str, Any]] = []
    causality_violations = 0
    ambiguous_batches = 0
    cursor = 0

    while cursor < len(unique_rows):
        row = unique_rows[cursor]
        key = state_key(row)
        timestamp = float(row["ts"])
        batch = [row]
        cursor += 1
        while (
            cursor < len(unique_rows)
            and state_key(unique_rows[cursor]) == key
            and float(unique_rows[cursor]["ts"]) == timestamp
        ):
            batch.append(unique_rows[cursor])
            cursor += 1

        previous = states.get(key)
        if previous is not None and float(previous["last_ts"]) > timestamp:
            causality_violations += 1
            raise ValueError("causality violation while processing sorted observations")

        semantic_variants = {
            stable_hash(
                {
                    "type": normalize_update_type(item.get("type")),
                    "route": route_payload(item),
                }
            )
            for item in batch
        }
        if len(semantic_variants) > 1:
            ambiguous_batches += 1
            state_age = (
                timestamp - float(previous["last_ts"])
                if previous is not None
                else None
            )
            transition = make_transition(
                batch,
                "same_timestamp_ambiguous",
                previous.get("route") if previous and previous["active"] else None,
                None,
                previous is not None and bool(previous["known"]),
                False,
                state_age,
                True,
            )
            states[key] = {
                "known": False,
                "active": False,
                "route": None,
                "last_route": previous.get("last_route") if previous else None,
                "last_ts": timestamp,
            }
        else:
            transition, next_state = classify_single(batch[0], previous)
            states[key] = next_state
        transitions.append(transition)

    return transitions, {
        "transition_count": len(transitions),
        "transition_family_counts": dict(
            sorted(Counter(row["transition_family"] for row in transitions).items())
        ),
        "same_timestamp_ambiguous_batch_count": ambiguous_batches,
        "causality_violation_count": causality_violations,
        "final_state_key_count": len(states),
    }


def micro_event_key(transition: dict[str, Any], window_sec: int) -> tuple[Any, ...]:
    window_start = math.floor(float(transition["transition_ts"]) / window_sec) * window_sec
    return (
        window_start,
        transition["prefix"],
        transition["transition_family"],
        transition["old_route_signature"],
        transition["new_route_signature"],
        bool(transition["origin_changed"]),
        bool(transition["path_changed"]),
        bool(transition["communities_changed"]),
        bool(transition["next_hop_changed"]),
    )


def build_micro_events(
    transitions: list[dict[str, Any]], window_sec: int
) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for transition in transitions:
        grouped.setdefault(micro_event_key(transition, window_sec), []).append(transition)

    events: list[dict[str, Any]] = []
    for key, members in sorted(grouped.items(), key=lambda item: item[0]):
        (
            window_start,
            prefix,
            family,
            old_signature,
            new_signature,
            origin_changed,
            path_changed,
            communities_changed,
            next_hop_changed,
        ) = key
        transition_ids = sorted(row["transition_id"] for row in members)
        first_ts = min(float(row["transition_ts"]) for row in members)
        last_ts = max(float(row["transition_ts"]) for row in members)
        event = {
            "micro_event_id": stable_hash(
                {
                    "window_sec": window_sec,
                    "window_start": window_start,
                    "prefix": prefix,
                    "transition_family": family,
                    "old_route_signature": old_signature,
                    "new_route_signature": new_signature,
                    "member_transition_ids": transition_ids,
                }
            ),
            "window_sec": window_sec,
            "window_start_ts": float(window_start),
            "window_end_ts": float(window_start + window_sec),
            "available_at_ts": float(window_start + window_sec),
            "first_seen_ts": first_ts,
            "last_seen_ts": last_ts,
            "bounded_latency_sec": float(window_start + window_sec - first_ts),
            "prefix": prefix,
            "transition_family": family,
            "old_route_signature": old_signature,
            "new_route_signature": new_signature,
            "origin_changed": origin_changed,
            "path_changed": path_changed,
            "communities_changed": communities_changed,
            "next_hop_changed": next_hop_changed,
            "same_timestamp_ambiguous": any(
                bool(row["same_timestamp_ambiguous"]) for row in members
            ),
            "member_transition_count": len(members),
            "member_transition_ids": transition_ids,
            "member_observation_count": sum(
                int(row["member_observation_count"]) for row in members
            ),
            "source_copy_count": sum(int(row["source_copy_count"]) for row in members),
            "collector_set": sorted(
                {str(row["collector"]) for row in members if row["collector"] is not None}
            ),
            "peer_address_set": sorted(
                {
                    str(row["peer_address"])
                    for row in members
                    if row["peer_address"] is not None
                }
            ),
            "peer_asn_set": sorted(
                {
                    str(row["peer_asn"])
                    for row in members
                    if row["peer_asn"] is not None
                }
            ),
            "source_files": sorted(
                {
                    source
                    for row in members
                    for source in row.get("source_files", [])
                }
            ),
        }
        events.append(event)
    return events


def serializable_frame(rows: list[dict[str, Any]], columns: list[str] | None = None) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    if columns is not None:
        for column in columns:
            if column not in frame.columns:
                frame[column] = None
        frame = frame[columns]
    return frame


def write_parquet(path: Path, rows: list[dict[str, Any]], columns: list[str] | None = None) -> None:
    frame = serializable_frame(rows, columns)
    table = pa.Table.from_pandas(frame, preserve_index=False)
    pq.write_table(table, path, compression="zstd")


def output_fingerprint(rows: list[dict[str, Any]]) -> str:
    return stable_hash(rows)


def build_summary(
    config: dict[str, Any],
    load_meta: dict[str, Any],
    dedup_meta: dict[str, Any],
    transition_meta: dict[str, Any],
    unique_rows: list[dict[str, Any]],
    transitions: list[dict[str, Any]],
    micro_events_by_window: dict[int, list[dict[str, Any]]],
) -> dict[str, Any]:
    input_rows = int(load_meta["selected_rows"])
    unique_count = len(unique_rows)
    transition_count = len(transitions)
    primary_window = int(config["primary_micro_event_window_sec"])
    primary_events = micro_events_by_window[primary_window]
    primary_count = len(primary_events)

    source_copy_accounted = sum(int(row["source_copy_count"]) for row in unique_rows)
    observation_accounted = sum(
        int(row["member_observation_count"]) for row in transitions
    )
    transition_accounted = sum(
        int(row["member_transition_count"]) for row in primary_events
    )
    accounting = {
        "source_copy_accounting_passed": source_copy_accounted == input_rows,
        "unique_observation_accounting_passed": observation_accounted == unique_count,
        "transition_accounting_passed": transition_accounted == transition_count,
        "source_copy_accounted": source_copy_accounted,
        "unique_observation_accounted": observation_accounted,
        "transition_accounted": transition_accounted,
    }
    all_accounting_passed = all(
        accounting[key]
        for key in [
            "source_copy_accounting_passed",
            "unique_observation_accounting_passed",
            "transition_accounting_passed",
        ]
    )
    return {
        "phase": config["phase"],
        "config_version": config["config_version"],
        "input_schema": config["input_schema"],
        "input_file_count": load_meta["input_file_count"],
        "input_files": load_meta["input_files"],
        "source_rows_scanned": load_meta["source_rows_scanned"],
        "source_rows_scanned_by_file": load_meta["source_rows_scanned_by_file"],
        "selected_rows_by_collector": load_meta["selected_rows_by_collector"],
        "required_collectors": load_meta["required_collectors"],
        "missing_required_collectors": load_meta["missing_required_collectors"],
        "observed_collectors": load_meta["observed_collectors"],
        "observed_projects": load_meta["observed_projects"],
        "selected_ts_min": load_meta["selected_ts_min"],
        "selected_ts_max": load_meta["selected_ts_max"],
        "input_rows": input_rows,
        "exact_unique_observation_count": unique_count,
        "exact_duplicate_copy_count": dedup_meta["excluded_duplicate_copy_count"],
        "exact_duplicate_reduction_rate": (
            1.0 - unique_count / input_rows if input_rows else 0.0
        ),
        "transition_count": transition_count,
        "transition_family_counts": transition_meta["transition_family_counts"],
        "same_timestamp_ambiguous_batch_count": transition_meta[
            "same_timestamp_ambiguous_batch_count"
        ],
        "causality_violation_count": transition_meta["causality_violation_count"],
        "path_id_column": load_meta["path_id_column"],
        "path_id_non_null_rows": load_meta["path_id_non_null_rows"],
        "path_id_field_present": load_meta["path_id_field_present"],
        "add_path_support_ready": load_meta["add_path_support_ready"],
        "selection_truncated_by_max_rows": load_meta[
            "selection_truncated_by_max_rows"
        ],
        "selection_truncated_by_per_collector_cap": load_meta[
            "selection_truncated_by_per_collector_cap"
        ],
        "state_identity_missing_row_count": load_meta[
            "state_identity_missing_row_count"
        ],
        "micro_event_count_by_window_sec": {
            str(window): len(rows)
            for window, rows in sorted(micro_events_by_window.items())
        },
        "primary_micro_event_window_sec": primary_window,
        "primary_micro_event_count": primary_count,
        "raw_to_primary_micro_event_compression_ratio": (
            input_rows / primary_count if primary_count else None
        ),
        "raw_to_primary_micro_event_reduction_rate": (
            1.0 - primary_count / input_rows if input_rows else 0.0
        ),
        "accounting": accounting,
        "all_accounting_passed": all_accounting_passed,
        "contract_passed": (
            all_accounting_passed
            and transition_meta["causality_violation_count"] == 0
            and dedup_meta["observation_id_collision_count"] == 0
            and load_meta["state_identity_missing_row_count"] == 0
            and not load_meta["missing_required_collectors"]
        ),
        "claim_boundaries": config["claim_boundaries"],
        "output_fingerprints": {
            "unique_observations": output_fingerprint(unique_rows),
            "transitions": output_fingerprint(transitions),
            "primary_micro_events": output_fingerprint(primary_events),
        },
        "recommended_next_step": (
            "audit_add_path_before_full_promotion"
            if not load_meta["add_path_support_ready"]
            else "replay_controlled_attacks_after_real_bounded_smoke"
        ),
    }


def write_report(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# N-FRONTEND-1 Causal Transition Contract",
        "",
        "This bounded run performs exact observation deduplication, past-only",
        "route-state transition extraction, and bounded micro-event aggregation.",
        "It does not suppress background or produce attack/benign truth.",
        "",
        "## Result",
        "",
        f"- Contract passed: `{str(summary['contract_passed']).lower()}`.",
        f"- Input rows: `{summary['input_rows']}`.",
        f"- Exact unique observations: `{summary['exact_unique_observation_count']}`.",
        f"- Exact duplicate copies excluded: `{summary['exact_duplicate_copy_count']}`.",
        f"- Causal transitions: `{summary['transition_count']}`.",
        f"- Primary micro-events: `{summary['primary_micro_event_count']}`.",
        (
            "- Raw-to-primary compression: "
            f"`{summary['raw_to_primary_micro_event_compression_ratio']}`."
        ),
        f"- Causality violations: `{summary['causality_violation_count']}`.",
        (
            "- Same-timestamp ambiguous batches: "
            f"`{summary['same_timestamp_ambiguous_batch_count']}`."
        ),
        f"- Add-Path support ready: `{str(summary['add_path_support_ready']).lower()}`.",
        "",
        "## Boundary",
        "",
        "- Later identical announcements are route events, not exact source duplicates.",
        "- A first-in-window update is bootstrap state, not route novelty.",
        "- Same-timestamp distinct updates are marked ambiguous, not arbitrarily ordered.",
        "- Missing path identifiers prohibit an Add-Path-complete claim.",
        "- No RPKI, AS-rel, community interpretation, suppression, or learning occurs.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_pipeline(
    data: pd.DataFrame,
    config: dict[str, Any],
    load_meta: dict[str, Any],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[int, list[dict[str, Any]]],
    dict[str, Any],
]:
    unique_rows, duplicate_audit, dedup_meta = deduplicate_observations(data)
    transitions, transition_meta = build_transitions(unique_rows)
    windows = [
        int(config["primary_micro_event_window_sec"]),
        *[int(value) for value in config["sensitivity_micro_event_windows_sec"]],
    ]
    micro_events_by_window = {
        window: build_micro_events(transitions, window) for window in sorted(set(windows))
    }
    summary = build_summary(
        config,
        load_meta,
        dedup_meta,
        transition_meta,
        unique_rows,
        transitions,
        micro_events_by_window,
    )
    return unique_rows, duplicate_audit, transitions, micro_events_by_window, summary


def prepare_output_dir(path: Path, overwrite: bool) -> None:
    if path.exists():
        if not overwrite:
            raise FileExistsError(f"output directory exists: {path}")
        shutil.rmtree(path)
    path.mkdir(parents=True)


def write_outputs(
    output_dir: Path,
    unique_rows: list[dict[str, Any]],
    duplicate_audit: list[dict[str, Any]],
    transitions: list[dict[str, Any]],
    micro_events_by_window: dict[int, list[dict[str, Any]]],
    summary: dict[str, Any],
) -> None:
    primary_window = int(summary["primary_micro_event_window_sec"])
    write_parquet(output_dir / "n_frontend1_unique_observations.parquet", unique_rows)
    write_parquet(
        output_dir / "n_frontend1_transitions.parquet",
        transitions,
        TRANSITION_COLUMNS,
    )
    write_parquet(
        output_dir / "n_frontend1_micro_events.parquet",
        micro_events_by_window[primary_window],
    )
    serializable_frame(duplicate_audit, DEDUP_AUDIT_COLUMNS).to_csv(
        output_dir / "n_frontend1_exact_dedup_audit.csv", index=False
    )
    pd.DataFrame(
        [
            {"transition_family": key, "count": value}
            for key, value in summary["transition_family_counts"].items()
        ]
    ).to_csv(output_dir / "n_frontend1_transition_counts.csv", index=False)
    (output_dir / "n_frontend1_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_report(output_dir / "n_frontend1_report.md", summary)


def fixture_row(
    ts: float,
    update_type: str,
    path: str | None,
    origin: str | None,
    communities: list[str] | None = None,
    peer_address: str = "192.0.2.1",
    source_file: str = "fixture-a.gz",
) -> dict[str, Any]:
    row = {
        "ts": ts,
        "collector": "rrc00",
        "project": "ris",
        "type": update_type,
        "peer_asn": 64500,
        "peer_address": peer_address,
        "prefix": "203.0.113.0/24",
        "as_path": path,
        "origin_as": origin,
        "origin_provenance": "terminal_asn" if origin else "withdrawal",
        "communities": communities or [],
        "next_hop": "192.0.2.254" if update_type == "A" else None,
        "source_file": source_file,
        "archive_timestamp_utc": "2024-04-07T00:00:00Z",
        "_input_parquet": "fixture.parquet",
        "path_id": None,
    }
    row["observation_id"] = canonical_observation_id(row)
    return row


def build_self_test_fixture() -> pd.DataFrame:
    rows = [
        fixture_row(1000, "A", "64500 64496", "64496", ["64500:1"]),
        fixture_row(
            1000,
            "A",
            "64500 64496",
            "64496",
            ["64500:1"],
            source_file="fixture-overlap.gz",
        ),
        fixture_row(1060, "A", "64500 64496", "64496", ["64500:1"]),
        fixture_row(1120, "A", "64500 64497", "64497", ["64500:1"]),
        fixture_row(1180, "W", None, None),
        fixture_row(1240, "A", "64500 64497", "64497", ["64500:1"]),
        fixture_row(1300, "A", "64500 64498", "64498", ["64500:1"]),
        fixture_row(1300, "W", None, None),
        fixture_row(1360, "A", "64500 64498", "64498", ["64500:1"]),
        fixture_row(
            1420,
            "A",
            "64500 64498",
            "64498",
            ["64500:1", "65535:65281"],
        ),
    ]
    return pd.DataFrame(rows).sort_values(
        ["ts", "collector", "peer_address", "prefix", "observation_id"],
        kind="mergesort",
    )


def run_self_test(config: dict[str, Any]) -> int:
    fixture = build_self_test_fixture()
    load_meta = {
        "input_file_count": 1,
        "input_files": ["synthetic.parquet"],
        "source_rows_scanned": len(fixture),
        "source_rows_scanned_by_file": {"synthetic.parquet": len(fixture)},
        "selected_rows": len(fixture),
        "selected_rows_by_collector": {"rrc00": len(fixture)},
        "required_collectors": ["rrc00"],
        "missing_required_collectors": [],
        "observed_collectors": ["rrc00"],
        "observed_projects": ["ris"],
        "selected_ts_min": float(fixture["ts"].min()),
        "selected_ts_max": float(fixture["ts"].max()),
        "path_id_column": None,
        "path_id_non_null_rows": 0,
        "path_id_field_present": False,
        "add_path_support_ready": False,
        "selection_truncated_by_max_rows": False,
        "selection_truncated_by_per_collector_cap": False,
        "state_identity_missing_row_count": 0,
    }
    first = run_pipeline(fixture, config, load_meta)
    second = run_pipeline(fixture, config, load_meta)
    unique_rows, duplicate_audit, transitions, micro_events, summary = first
    assert summary["contract_passed"]
    assert summary["causality_violation_count"] == 0
    assert summary["exact_duplicate_copy_count"] == 1
    assert len(unique_rows) == 9
    assert len(duplicate_audit) == 1
    assert summary["same_timestamp_ambiguous_batch_count"] == 1
    families = Counter(row["transition_family"] for row in transitions)
    assert families["bootstrap_announce"] == 1
    assert families["identical_reannouncement"] == 1
    assert families["announcement_change"] == 2
    assert families["withdrawal"] == 1
    assert families["withdraw_reannounce_same"] == 1
    assert families["same_timestamp_ambiguous"] == 1
    assert families["state_recovery_announce"] == 1
    bootstrap = next(
        row for row in transitions if row["transition_family"] == "bootstrap_announce"
    )
    assert not bootstrap["state_known_before"]
    assert not bootstrap["origin_changed"]
    assert not bootstrap["path_changed"]
    assert not bootstrap["communities_changed"]
    ambiguous = next(
        row
        for row in transitions
        if row["transition_family"] == "same_timestamp_ambiguous"
    )
    assert not ambiguous["state_known_after"]
    assert any(
        row["communities_changed"] and row["has_no_export_after"]
        for row in transitions
    )
    assert output_fingerprint(first[0]) == output_fingerprint(second[0])
    assert output_fingerprint(first[2]) == output_fingerprint(second[2])
    assert output_fingerprint(micro_events[300]) == output_fingerprint(second[3][300])
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        output_dir = tmp_path / "out"
        prepare_output_dir(output_dir, overwrite=False)
        write_outputs(
            output_dir,
            unique_rows,
            duplicate_audit,
            transitions,
            micro_events,
            summary,
        )
        assert (output_dir / "n_frontend1_summary.json").exists()
        assert pq.ParquetFile(
            output_dir / "n_frontend1_transitions.parquet"
        ).metadata.num_rows == len(transitions)
        rrc_fixture = fixture.copy()
        routeviews_fixture = fixture.copy()
        routeviews_fixture["collector"] = "route-views.sg"
        routeviews_fixture["project"] = "routeviews"
        routeviews_fixture["peer_address"] = "198.51.100.2"
        routeviews_fixture["observation_id"] = [
            canonical_observation_id(row)
            for row in routeviews_fixture.to_dict(orient="records")
        ]
        rrc_path = tmp_path / "rrc00.parquet"
        routeviews_path = tmp_path / "routeviews.parquet"
        rrc_fixture.to_parquet(rrc_path, index=False)
        routeviews_fixture.to_parquet(routeviews_path, index=False)
        bounded, bounded_meta = load_bounded_rows(
            [rrc_path, routeviews_path],
            config,
            None,
            None,
            0,
            3,
            ["rrc00", "route-views.sg"],
            2,
        )
        assert len(bounded) == 6
        assert bounded_meta["selected_rows_by_collector"] == {
            "route-views.sg": 3,
            "rrc00": 3,
        }
        assert bounded_meta["missing_required_collectors"] == []
        assert bounded_meta["selection_truncated_by_per_collector_cap"]
    print("self_test=passed")
    print(f"input_rows={summary['input_rows']}")
    print(f"unique_observations={summary['exact_unique_observation_count']}")
    print(f"transitions={summary['transition_count']}")
    print(f"micro_events_300s={summary['primary_micro_event_count']}")
    return 0


def main() -> int:
    args = parse_args()
    config = load_config(Path(args.config))
    if args.self_test:
        return run_self_test(config)
    if not args.input:
        raise SystemExit("--input is required unless --self-test is used")
    if not args.output_dir:
        raise SystemExit("--output-dir is required unless --self-test is used")

    files = discover_inputs(args.input, args.max_files)
    data, load_meta = load_bounded_rows(
        files,
        config,
        args.start_ts,
        args.end_ts,
        args.max_rows,
        args.max_rows_per_collector,
        args.require_collector,
        args.batch_size,
    )
    result = run_pipeline(data, config, load_meta)
    output_dir = Path(args.output_dir)
    prepare_output_dir(output_dir, args.overwrite)
    write_outputs(output_dir, *result[:-1], result[-1])
    print(json.dumps(result[-1], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
