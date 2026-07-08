#!/usr/bin/env python3
"""Materialize a canonical path-memory sidecar.

R-MEM-1A builds a lightweight historical path-memory sidecar for foreground
poisoning-robustness repair. It is deliberately separate from the legacy
seven-layer pipeline: raw BGP update parquet is used as source material, but the
output is only a sidecar for maturity lookup.

This script does not change foreground policy, does not train learning, and
does not treat maturity as attack/benign truth.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = "configs/r_mem1a_10d_path_memory_v01.json"
DEFAULT_OUTPUT_DIR = "outputs/r_mem_1a_10d_path_memory_sidecar_v01"
UPDATE_RE = re.compile(
    r"updates__(?P<start>\d{2}-\d{2}-\d{2})__(?P<end>\d{2}-\d{2}-\d{2})(?P<rel>__rel)?\.parquet$"
)
AS_RE = re.compile(r"\d+")


@dataclass(frozen=True)
class SourceCandidate:
    path: Path
    run_id: str
    collector: str
    day: str
    start_time: str
    end_time: str
    file_kind: str
    priority: int
    row_count: int
    size_bytes: int
    columns: tuple[str, ...]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--source-root", default=None)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--allow-partial-history", action="store_true")
    parser.add_argument("--max-files", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=200000)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def resolve_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def prepare_output_dir(path: Path, overwrite: bool) -> None:
    if path.exists() and any(path.iterdir()):
        if not overwrite:
            raise FileExistsError(f"output directory not empty; pass --overwrite: {path}")
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def date_range(start: date, end: date) -> list[str]:
    days: list[str] = []
    current = start
    while current <= end:
        days.append(current.isoformat())
        current += timedelta(days=1)
    return days


def infer_run_id(path: Path) -> str:
    parts = list(path.parts)
    if "runs" not in parts:
        return "unknown"
    idx = parts.index("runs")
    if idx + 1 < len(parts):
        return parts[idx + 1]
    return "unknown"


def safe_relative(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def priority_for_run(run_id: str, prefer_run_ids: list[str]) -> int:
    if run_id in prefer_run_ids:
        return prefer_run_ids.index(run_id)
    return len(prefer_run_ids) + 100


def parse_source_candidate(path: Path, prefer_run_ids: list[str]) -> SourceCandidate | None:
    match = UPDATE_RE.match(path.name)
    if not match:
        return None
    collector = "unknown"
    day = "unknown"
    for part in path.parts:
        if part.startswith("collector="):
            collector = part.split("=", 1)[1]
        elif part.startswith("date="):
            day = part.split("=", 1)[1]
    run_id = infer_run_id(path)
    file_kind = "rel" if match.group("rel") else "raw"
    try:
        parquet = pq.ParquetFile(path)
        columns = tuple(parquet.schema_arrow.names)
        row_count = parquet.metadata.num_rows
    except Exception:
        columns = tuple()
        row_count = 0
    return SourceCandidate(
        path=path,
        run_id=run_id,
        collector=collector,
        day=day,
        start_time=match.group("start"),
        end_time=match.group("end"),
        file_kind=file_kind,
        priority=priority_for_run(run_id, prefer_run_ids),
        row_count=row_count,
        size_bytes=path.stat().st_size,
        columns=columns,
    )


def discover_sources(
    source_root: Path,
    collectors: set[str],
    allowed_days: set[str],
    prefer_run_ids: list[str],
    file_kind: str,
) -> tuple[list[SourceCandidate], list[dict[str, Any]]]:
    candidates: list[SourceCandidate] = []
    for path in sorted(source_root.rglob("collector=*/date=*/updates__*.parquet")):
        item = parse_source_candidate(path, prefer_run_ids)
        if item is None:
            continue
        if item.collector not in collectors or item.day not in allowed_days:
            continue
        if item.file_kind != file_kind:
            continue
        candidates.append(item)

    grouped: dict[tuple[str, str, str, str, str], list[SourceCandidate]] = {}
    for item in candidates:
        key = (item.collector, item.day, item.start_time, item.end_time, item.file_kind)
        grouped.setdefault(key, []).append(item)

    selected: list[SourceCandidate] = []
    manifest_rows: list[dict[str, Any]] = []
    for key, items in sorted(grouped.items()):
        ordered = sorted(items, key=lambda x: (x.priority, len(str(x.path)), str(x.path)))
        keep = ordered[0]
        selected.append(keep)
        for idx, item in enumerate(ordered):
            manifest_rows.append(
                {
                    "selected": idx == 0,
                    "duplicate_group": "|".join(key),
                    "file_path": safe_relative(item.path),
                    "run_id": item.run_id,
                    "collector": item.collector,
                    "date": item.day,
                    "start_time": item.start_time,
                    "end_time": item.end_time,
                    "file_kind": item.file_kind,
                    "priority": item.priority,
                    "row_count": item.row_count,
                    "size_bytes": item.size_bytes,
                    "columns": "|".join(item.columns[:40]),
                }
            )
    return sorted(selected, key=lambda x: (x.day, x.collector, x.start_time)), manifest_rows


def pick_column(columns: list[str], candidates: list[str]) -> str | None:
    lower_to_original = {col.lower(): col for col in columns}
    for candidate in candidates:
        if candidate.lower() in lower_to_original:
            return lower_to_original[candidate.lower()]
    return None


def parse_as_path(value: Any, collapse_prepends: bool) -> tuple[str | None, str | None]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None, None
    tokens = AS_RE.findall(str(value))
    if not tokens:
        return None, None
    normalized: list[str] = []
    for token in tokens:
        if collapse_prepends and normalized and normalized[-1] == token:
            continue
        normalized.append(token)
    return " ".join(normalized), normalized[-1]


def stable_key(prefix: str, origin_as: str, as_path_signature: str) -> str:
    text = f"{prefix}|{origin_as}|{as_path_signature}"
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def process_batch(
    frame: pd.DataFrame,
    item: SourceCandidate,
    config: dict[str, Any],
    target_date: date,
) -> pd.DataFrame:
    path_key_cfg = config["path_key"]
    prefix_col = pick_column(list(frame.columns), [path_key_cfg["prefix_field"], "prefix", "pfx"])
    as_path_col = pick_column(list(frame.columns), path_key_cfg["as_path_fields"])
    ts_col = pick_column(list(frame.columns), ["ts", "timestamp", "time"])
    type_col = pick_column(list(frame.columns), ["type", "elem_type"])
    collector_col = pick_column(list(frame.columns), ["collector", "collector_id"])

    if not prefix_col or not as_path_col or not ts_col:
        return pd.DataFrame()

    df = frame[[col for col in [prefix_col, as_path_col, ts_col, type_col, collector_col] if col]].copy()
    df = df.rename(
        columns={
            prefix_col: "prefix",
            as_path_col: "as_path_raw",
            ts_col: "ts",
            type_col or "__missing_type__": "type",
            collector_col or "__missing_collector__": "collector",
        }
    )
    if "collector" not in df.columns:
        df["collector"] = item.collector
    if "type" in df.columns:
        type_text = df["type"].astype(str).str.lower()
        df = df[~type_text.isin(["w", "withdraw", "withdrawal"])]
    df = df[df["prefix"].notna() & df["as_path_raw"].notna()]
    if df.empty:
        return pd.DataFrame()

    parsed = df["as_path_raw"].map(
        lambda value: parse_as_path(
            value, bool(path_key_cfg.get("collapse_consecutive_as_prepends", True))
        )
    )
    df["as_path_signature"] = [value[0] for value in parsed]
    df["origin_as"] = [value[1] for value in parsed]
    df = df[df["as_path_signature"].notna() & df["origin_as"].notna()]
    if df.empty:
        return pd.DataFrame()

    df["prefix"] = df["prefix"].astype(str)
    df["origin_as"] = df["origin_as"].astype(str)
    df["as_path_signature"] = df["as_path_signature"].astype(str)
    df["path_memory_key"] = [
        stable_key(prefix, origin, signature)
        for prefix, origin, signature in zip(
            df["prefix"], df["origin_as"], df["as_path_signature"]
        )
    ]
    df["ts_num"] = pd.to_numeric(df["ts"], errors="coerce")
    df = df[df["ts_num"].notna()]
    if df.empty:
        return pd.DataFrame()

    day = item.day
    batch_id = f"{item.collector}|{item.day}|{item.start_time}|{item.end_time}"
    recent_days = int(config["maturity"].get("recent_only_days", 2))
    recent_start = target_date - timedelta(days=max(0, recent_days - 1))
    is_recent_day = parse_date(day) >= recent_start

    grouped = (
        df.groupby(["path_memory_key", "prefix", "origin_as", "as_path_signature"], dropna=False)
        .agg(
            first_seen_ts=("ts_num", "min"),
            last_seen_ts=("ts_num", "max"),
            record_count=("ts_num", "size"),
        )
        .reset_index()
    )
    grouped["active_day"] = day
    grouped["active_micro_batch"] = batch_id
    grouped["collector"] = item.collector
    grouped["collector_day"] = f"{item.collector}|{day}"
    grouped["source_file_count"] = 1
    grouped["recent_record_count"] = grouped["record_count"] if is_recent_day else 0
    grouped["origin_provenance"] = "derived_from_as_path"
    return grouped


def process_source_file(
    item: SourceCandidate,
    config: dict[str, Any],
    batch_size: int,
    target_date: date,
) -> tuple[list[pd.DataFrame], dict[str, Any]]:
    columns = list(item.columns)
    path_key_cfg = config["path_key"]
    wanted = [
        path_key_cfg["prefix_field"],
        "prefix",
        "pfx",
        *path_key_cfg["as_path_fields"],
        "ts",
        "timestamp",
        "time",
        "type",
        "elem_type",
        "collector",
        "collector_id",
    ]
    selected_columns = [col for col in columns if col in set(wanted)]
    if not selected_columns:
        return [], {
            "file_path": safe_relative(item.path),
            "status": "skipped_no_required_columns",
            "input_rows": item.row_count,
            "partial_rows": 0,
        }

    partials: list[pd.DataFrame] = []
    output_rows = 0
    try:
        parquet = pq.ParquetFile(item.path)
        for batch in parquet.iter_batches(batch_size=batch_size, columns=selected_columns):
            partial = process_batch(batch.to_pandas(), item, config, target_date)
            if not partial.empty:
                output_rows += int(partial["record_count"].sum())
                partials.append(partial)
        status = "processed"
    except Exception as exc:
        status = f"failed:{type(exc).__name__}:{exc}"
    return partials, {
        "file_path": safe_relative(item.path),
        "status": status,
        "input_rows": item.row_count,
        "partial_rows": output_rows,
    }


def join_unique(values: pd.Series) -> str:
    return "|".join(sorted({str(value) for value in values.dropna() if str(value)}))


def build_sidecar(partials: list[pd.DataFrame], config: dict[str, Any], target_date: date) -> pd.DataFrame:
    if not partials:
        return pd.DataFrame()
    work = pd.concat(partials, ignore_index=True)
    grouped = (
        work.groupby(["path_memory_key", "prefix", "origin_as", "as_path_signature"], dropna=False)
        .agg(
            first_seen_ts=("first_seen_ts", "min"),
            last_seen_ts=("last_seen_ts", "max"),
            record_count=("record_count", "sum"),
            recent_record_count=("recent_record_count", "sum"),
            active_days=("active_day", "nunique"),
            active_micro_batches=("active_micro_batch", "nunique"),
            collector_days=("collector_day", "nunique"),
            collector_count=("collector", "nunique"),
            source_file_count=("source_file_count", "sum"),
            collector_set=("collector", join_unique),
            origin_provenance=("origin_provenance", join_unique),
        )
        .reset_index()
    )
    grouped["span_sec"] = grouped["last_seen_ts"] - grouped["first_seen_ts"]
    grouped["burstiness_score"] = (
        grouped["recent_record_count"] / grouped["record_count"].replace(0, pd.NA)
    ).fillna(0.0)

    maturity = config["maturity"]
    mature = (
        grouped["active_days"].ge(int(maturity["mature_min_active_days"]))
        & grouped["active_micro_batches"].ge(
            int(maturity["mature_min_active_micro_batches"])
        )
        & grouped["collector_days"].ge(int(maturity["mature_min_collector_days"]))
        & grouped["span_sec"].ge(float(maturity["mature_min_span_sec"]))
    )
    recent_start_epoch = datetime.combine(
        target_date - timedelta(days=int(maturity["recent_only_days"]) - 1),
        datetime.min.time(),
        tzinfo=timezone.utc,
    ).timestamp()
    recent_only = grouped["first_seen_ts"].ge(recent_start_epoch)
    short_lived = grouped["span_sec"].le(float(maturity["short_lived_span_sec"]))
    grouped["maturity_bucket"] = "sparse"
    grouped.loc[short_lived, "maturity_bucket"] = "short_lived"
    grouped.loc[recent_only, "maturity_bucket"] = "recent_only"
    grouped.loc[mature, "maturity_bucket"] = "mature"
    grouped["sidecar_semantics"] = "suppression_permission_only"
    return grouped.sort_values(
        ["maturity_bucket", "record_count", "active_days"], ascending=[True, False, False]
    )


def coverage_audit(selected: list[SourceCandidate], expected_days: list[str], collectors: list[str]) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str], list[SourceCandidate]] = {}
    for item in selected:
        by_key.setdefault((item.day, item.collector), []).append(item)
    rows: list[dict[str, Any]] = []
    for day in expected_days:
        for collector in collectors:
            items = by_key.get((day, collector), [])
            rows.append(
                {
                    "date": day,
                    "collector": collector,
                    "source_files": len(items),
                    "source_rows": sum(item.row_count for item in items),
                    "source_size_bytes": sum(item.size_bytes for item in items),
                    "coverage_status": "present" if items else "missing",
                }
            )
    return rows


def maturity_rows(sidecar: pd.DataFrame) -> list[dict[str, Any]]:
    if sidecar.empty:
        return []
    rows: list[dict[str, Any]] = []
    total = len(sidecar)
    for bucket, count in sidecar["maturity_bucket"].value_counts().sort_index().items():
        subset = sidecar[sidecar["maturity_bucket"].eq(bucket)]
        rows.append(
            {
                "maturity_bucket": bucket,
                "path_key_count": int(count),
                "path_key_rate": float(count) / float(total) if total else 0.0,
                "record_count": int(subset["record_count"].sum()),
                "active_days_mean": float(subset["active_days"].mean()),
                "collector_count_mean": float(subset["collector_count"].mean()),
                "notes": "maturity is suppression-permission evidence, not truth",
            }
        )
    return rows


def build_report(summary: dict[str, Any]) -> str:
    return f"""# R-MEM-1A 10d Path-Memory Sidecar Smoke

Status: completed local/materialization smoke.

## Goal

R-MEM-1A materializes a canonical path-memory sidecar for a 10-day window. This
is the data foundation for R-FOREGROUND-4B targeted path-poisoning repair.

## Boundary

This phase does not modify foreground policy, does not train learning, and does
not treat path maturity as attack or benign truth.

## Scope

- target date: `{summary["target_date"]}`
- requested history window: `{summary["history_start_date"]}` to
  `{summary["history_end_date"]}`
- requested collectors: `{", ".join(summary["canonical_collectors"])}`
- selected source files: `{summary["selected_source_file_count"]}`
- complete requested history: `{summary["complete_requested_history"]}`
- allow partial history: `{summary["allow_partial_history"]}`

## Result

- sidecar rows: `{summary["sidecar_rows"]}`
- input source rows: `{summary["input_source_rows"]}`
- processed source rows: `{summary["processed_source_rows"]}`
- maturity buckets: `{summary["maturity_bucket_counts"]}`

## Important Claims

Allowed claim:

```text
{summary["allowed_claim"]}
```

Forbidden claims:

{chr(10).join("- `" + item + "`" for item in summary["forbidden_claims"])}

## Next Step

`{summary["recommended_next_step"]}`
"""


def main() -> None:
    args = parse_args()
    config_path = resolve_path(args.config)
    config = read_json(config_path)
    source_root = resolve_path(args.source_root or config["source"]["source_root"])
    output_dir = resolve_path(args.output_dir)
    prepare_output_dir(output_dir, args.overwrite)

    target_date = parse_date(config["target_date"])
    history_days = int(config["history_days"])
    history_start = target_date - timedelta(days=history_days - 1)
    expected_days = date_range(history_start, target_date)
    collectors = list(config["canonical_collectors"])
    selected, manifest_rows = discover_sources(
        source_root=source_root,
        collectors=set(collectors),
        allowed_days=set(expected_days),
        prefer_run_ids=list(config["source"].get("prefer_run_ids", [])),
        file_kind=str(config["source"].get("file_kind", "raw")),
    )
    if args.max_files:
        selected = selected[: args.max_files]
        for row in manifest_rows:
            row["selected_after_max_files"] = row["file_path"] in {
                safe_relative(item.path) for item in selected
            }

    coverage = coverage_audit(selected, expected_days, collectors)
    present_by_day: dict[str, int] = {day: 0 for day in expected_days}
    missing_collector_dates: list[str] = []
    for row in coverage:
        if row["coverage_status"] == "present":
            present_by_day[row["date"]] = present_by_day.get(row["date"], 0) + 1
        else:
            missing_collector_dates.append(f"{row['date']}|{row['collector']}")
    dates_without_any_source = sorted(
        [day for day, count in present_by_day.items() if count == 0]
    )
    incomplete_dates = sorted(
        [
            day
            for day, count in present_by_day.items()
            if 0 < count < len(collectors)
        ]
    )
    complete_history = not missing_collector_dates
    allow_partial = bool(args.allow_partial_history)
    if not complete_history and not allow_partial:
        write_csv(output_dir / "r_mem1a_source_manifest.csv", manifest_rows)
        write_csv(output_dir / "r_mem1a_source_coverage_audit.csv", coverage)
        raise SystemExit(
            "requested 10d history is incomplete; pass --allow-partial-history "
            "for a bounded smoke or materialize missing source files first"
        )

    partials: list[pd.DataFrame] = []
    file_rows: list[dict[str, Any]] = []
    processed_rows = 0
    for item in selected:
        new_partials, file_row = process_source_file(
            item, config, args.batch_size, target_date
        )
        partials.extend(new_partials)
        processed_rows += int(file_row.get("partial_rows", 0))
        file_rows.append(file_row)

    sidecar = build_sidecar(partials, config, target_date)
    sidecar_path = output_dir / "path_memory_sidecar.parquet"
    if not sidecar.empty:
        sidecar.to_parquet(sidecar_path, index=False)
        sidecar.head(1000).to_csv(output_dir / "path_memory_sidecar_preview.csv", index=False)
    else:
        pd.DataFrame().to_parquet(sidecar_path, index=False)
        (output_dir / "path_memory_sidecar_preview.csv").write_text("", encoding="utf-8")

    maturity_audit = maturity_rows(sidecar)
    input_rows = sum(item.row_count for item in selected)
    summary = {
        "phase": config["phase"],
        "status": "completed_sidecar_smoke",
        "config": safe_relative(config_path),
        "target_date": target_date.isoformat(),
        "history_days": history_days,
        "history_start_date": history_start.isoformat(),
        "history_end_date": target_date.isoformat(),
        "canonical_collectors": collectors,
        "complete_requested_history": complete_history,
        "dates_without_any_source": dates_without_any_source,
        "incomplete_dates": incomplete_dates,
        "missing_collector_dates": missing_collector_dates,
        "allow_partial_history": allow_partial,
        "source_root": safe_relative(source_root),
        "selected_source_file_count": len(selected),
        "input_source_rows": input_rows,
        "processed_source_rows": processed_rows,
        "sidecar_rows": int(len(sidecar)),
        "maturity_bucket_counts": {
            str(key): int(value)
            for key, value in sidecar["maturity_bucket"].value_counts().to_dict().items()
        }
        if not sidecar.empty
        else {},
        "sidecar_path": safe_relative(sidecar_path),
        "origin_provenance": "origin_as may be derived from final AS in normalized AS_PATH; see sidecar origin_provenance",
        "allowed_claim": "R-MEM-1A materializes or smokes the path-memory sidecar data contract; it does not prove final foreground poisoning robustness.",
        "forbidden_claims": list(config.get("forbidden_claims", [])),
        "recommended_next_step": "If complete 10d history is available, run R-FOREGROUND-4B targeted guard smoke; otherwise materialize missing canonical source data on HPC first.",
    }

    write_csv(output_dir / "r_mem1a_source_manifest.csv", manifest_rows)
    write_csv(output_dir / "r_mem1a_selected_file_processing_audit.csv", file_rows)
    write_csv(output_dir / "r_mem1a_source_coverage_audit.csv", coverage)
    write_csv(output_dir / "r_mem1a_maturity_bucket_audit.csv", maturity_audit)
    write_json(output_dir / "r_mem1a_summary.json", summary)
    (output_dir / "r_mem1a_report.md").write_text(build_report(summary), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
