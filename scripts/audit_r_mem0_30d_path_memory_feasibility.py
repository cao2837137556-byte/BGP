#!/usr/bin/env python3
"""Audit feasibility for a 30-day path-memory sidecar.

R-MEM-0 is a read-only planning audit. It checks whether the local data layout
and the current 6h baseline can support a deployment-like path-memory sidecar
for foreground poisoning robustness repair.

It does not download BGP data, does not run the legacy pipeline, does not modify
foreground policy, and does not train learning. The main question is whether
30-day history should be materialized as a lightweight sidecar before attempting
R-FOREGROUND-4B targeted poisoning repair.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN_ID = "s2a_baseline_v01_pilot_6h_april16"
DEFAULT_RUN_ROOT = f"data/runs/{DEFAULT_RUN_ID}"
DEFAULT_HISTORY_ROOT = "data/runs"
DEFAULT_OUTPUT_DIR = "outputs/r_mem_0_30d_path_memory_feasibility_v01"

UPDATE_RE = re.compile(
    r"updates__(?P<start>\d{2}-\d{2}-\d{2})__(?P<end>\d{2}-\d{2}-\d{2})(?P<rel>__rel)?\.parquet$"
)


@dataclass
class SourceFile:
    file_path: str
    run_id: str
    collector: str
    date: str
    file_kind: str
    start_time: str
    end_time: str
    interval_minutes: float | None
    row_count: int | None
    size_bytes: int
    column_count: int | None
    has_prefix: bool
    has_origin_as: bool
    has_origin_derivable_from_as_path: bool
    has_as_path: bool
    has_collector: bool
    has_timestamp: bool
    has_communities: bool
    path_memory_key_ready: bool
    schema_columns_sample: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--run-root", default=DEFAULT_RUN_ROOT)
    parser.add_argument("--history-root", default=DEFAULT_HISTORY_ROOT)
    parser.add_argument("--target-date", default="2024-04-16")
    parser.add_argument("--history-days", type=int, default=30)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-files", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def resolve_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def prepare_output_dir(path: Path, overwrite: bool) -> None:
    if path.exists() and any(path.iterdir()):
        if not overwrite:
            raise FileExistsError(f"output directory not empty; pass --overwrite: {path}")
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


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


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def parse_time_on_day(day: str, value: str) -> datetime:
    return datetime.strptime(f"{day} {value}", "%Y-%m-%d %H-%M-%S")


def minutes_between(day: str, start: str, end: str) -> float:
    start_dt = parse_time_on_day(day, start)
    end_dt = parse_time_on_day(day, end)
    if end_dt < start_dt:
        end_dt += timedelta(days=1)
    return (end_dt - start_dt).total_seconds() / 60.0


def infer_run_id(path: Path) -> str:
    parts = list(path.parts)
    if "runs" not in parts:
        return "unknown"
    idx = parts.index("runs")
    if idx + 1 < len(parts):
        return parts[idx + 1]
    return "unknown"


def parse_source_file(path: Path) -> SourceFile | None:
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

    file_kind = "rel" if match.group("rel") else "raw"
    row_count: int | None = None
    column_count: int | None = None
    columns: list[str] = []
    try:
        metadata = pq.ParquetFile(path)
        row_count = metadata.metadata.num_rows
        schema = metadata.schema_arrow
        columns = list(schema.names)
        column_count = len(columns)
    except Exception:
        columns = []

    lower_columns = {col.lower() for col in columns}
    schema_sample = "|".join(columns[:40])
    has_prefix = any(col in lower_columns for col in {"prefix", "pfx"})
    has_origin_as = any(
        col in lower_columns
        for col in {"origin_as", "origin", "originasn", "origin_asn"}
    )
    has_as_path = any(
        col in lower_columns
        for col in {"as_path", "as_path_clean", "path", "aspath"}
    )
    has_timestamp = any(
        col in lower_columns for col in {"ts", "timestamp", "time", "first_seen"}
    )
    # Raw MRT-derived rows often do not store origin_as explicitly. For a
    # memory sidecar, origin can be derived from the last AS in a normalized
    # AS_PATH, but this must be recorded as derived provenance.
    has_origin_derivable = has_as_path and not has_origin_as

    return SourceFile(
        file_path=str(path.relative_to(REPO_ROOT) if path.is_absolute() else path),
        run_id=infer_run_id(path),
        collector=collector,
        date=day,
        file_kind=file_kind,
        start_time=match.group("start"),
        end_time=match.group("end"),
        interval_minutes=minutes_between(day, match.group("start"), match.group("end"))
        if day != "unknown"
        else None,
        row_count=row_count,
        size_bytes=path.stat().st_size,
        column_count=column_count,
        has_prefix=has_prefix,
        has_origin_as=has_origin_as,
        has_origin_derivable_from_as_path=has_origin_derivable,
        has_as_path=has_as_path,
        has_collector=any(col in lower_columns for col in {"collector", "collector_id"}),
        has_timestamp=has_timestamp,
        has_communities=any("communit" in col for col in lower_columns),
        path_memory_key_ready=has_prefix
        and has_as_path
        and has_timestamp
        and (has_origin_as or has_origin_derivable),
        schema_columns_sample=schema_sample,
    )


def scan_source_files(root: Path, max_files: int) -> list[SourceFile]:
    rows: list[SourceFile] = []
    for path in sorted(root.rglob("collector=*/date=*/updates__*.parquet")):
        parsed = parse_source_file(path)
        if parsed is not None:
            rows.append(parsed)
        if max_files and len(rows) >= max_files:
            break
    return rows


def coverage_rows(files: list[SourceFile], start_date: date, end_date: date) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str], list[SourceFile]] = {}
    for item in files:
        if item.date == "unknown":
            continue
        try:
            item_date = parse_date(item.date)
        except ValueError:
            continue
        if start_date <= item_date <= end_date:
            by_key.setdefault((item.collector, item.date), []).append(item)

    rows: list[dict[str, Any]] = []
    for (collector, day), items in sorted(by_key.items()):
        raw = [item for item in items if item.file_kind == "raw"]
        rel = [item for item in items if item.file_kind == "rel"]
        intervals = sorted(
            {
                f"{item.start_time}->{item.end_time}"
                for item in raw
            }
        )
        interval_minutes = sorted(
            {
                item.interval_minutes
                for item in raw
                if item.interval_minutes is not None
            }
        )
        rows.append(
            {
                "collector": collector,
                "date": day,
                "raw_file_count": len(raw),
                "rel_file_count": len(rel),
                "raw_rows": sum(item.row_count or 0 for item in raw),
                "rel_rows": sum(item.row_count or 0 for item in rel),
                "raw_size_bytes": sum(item.size_bytes for item in raw),
                "rel_size_bytes": sum(item.size_bytes for item in rel),
                "observed_interval_minutes": ";".join(
                    str(value) for value in interval_minutes
                ),
                "first_interval": intervals[0] if intervals else "",
                "last_interval": intervals[-1] if intervals else "",
                "expected_5m_files_per_day": 288,
                "observed_5m_day_fraction": round(len(raw) / 288.0, 6),
                "notes": "local source coverage only; not a 30d claim",
            }
        )
    return rows


def estimate_volume(
    coverage: list[dict[str, Any]], target_date: date, history_days: int
) -> list[dict[str, Any]]:
    target_rows = [row for row in coverage if row["date"] == target_date.isoformat()]
    observed_raw_rows = sum(int(row["raw_rows"]) for row in target_rows)
    observed_raw_bytes = sum(int(row["raw_size_bytes"]) for row in target_rows)
    observed_raw_files = sum(int(row["raw_file_count"]) for row in target_rows)
    observed_collectors = len({row["collector"] for row in target_rows})
    observed_day_fraction = max(
        [float(row["observed_5m_day_fraction"]) for row in target_rows] or [0.0]
    )
    scale_from_observed_to_day = (1.0 / observed_day_fraction) if observed_day_fraction else 0.0
    estimated_daily_rows = int(observed_raw_rows * scale_from_observed_to_day)
    estimated_daily_bytes = int(observed_raw_bytes * scale_from_observed_to_day)
    estimated_daily_files = int(observed_raw_files * scale_from_observed_to_day)
    return [
        {
            "basis": "observed_target_date_local_coverage",
            "target_date": target_date.isoformat(),
            "history_days": history_days,
            "observed_collectors": observed_collectors,
            "observed_raw_files": observed_raw_files,
            "observed_raw_rows": observed_raw_rows,
            "observed_raw_size_bytes": observed_raw_bytes,
            "observed_max_5m_day_fraction": observed_day_fraction,
            "estimated_daily_raw_files_same_collectors": estimated_daily_files,
            "estimated_daily_raw_rows_same_collectors": estimated_daily_rows,
            "estimated_daily_raw_size_bytes_same_collectors": estimated_daily_bytes,
            "estimated_30d_raw_files_same_collectors": estimated_daily_files
            * history_days,
            "estimated_30d_raw_rows_same_collectors": estimated_daily_rows
            * history_days,
            "estimated_30d_raw_size_bytes_same_collectors": estimated_daily_bytes
            * history_days,
            "estimate_boundary": "scale-up from current local 6h/partial-day source files; validate on HPC before formal claims",
        }
    ]


def feature_contract_rows() -> list[dict[str, Any]]:
    return [
        {
            "feature": "path_memory_key",
            "definition": "prefix + origin_as + normalized AS_PATH signature",
            "required": True,
            "use": "join current event to historical path memory",
            "misuse_forbidden": "not an attack label",
        },
        {
            "feature": "first_seen_ts",
            "definition": "earliest historical observation in the sidecar window",
            "required": True,
            "use": "distinguish long-lived path from recent prelude",
            "misuse_forbidden": "old first_seen does not prove benign",
        },
        {
            "feature": "last_seen_ts",
            "definition": "latest historical observation before the current batch",
            "required": True,
            "use": "detect stale vs active memory",
            "misuse_forbidden": "missing last_seen is not attack truth",
        },
        {
            "feature": "active_days",
            "definition": "number of distinct days with observations in the 30d window",
            "required": True,
            "use": "maturity/suppression permission",
            "misuse_forbidden": "active_days alone cannot suppress high-risk signals",
        },
        {
            "feature": "active_micro_batches",
            "definition": "number of distinct 5m/15m batches with observations",
            "required": True,
            "use": "recurrence density",
            "misuse_forbidden": "within-window repetition is not long-term maturity",
        },
        {
            "feature": "collector_days",
            "definition": "distinct collector-date pairs observing the key",
            "required": True,
            "use": "collector-diversity maturity proxy",
            "misuse_forbidden": "single collector absence is not NO_EXPORT proof",
        },
        {
            "feature": "burstiness_score",
            "definition": "concentration of observations near current time",
            "required": False,
            "use": "poisoning-prelude suspicion / guard trigger",
            "misuse_forbidden": "burstiness is not attack truth",
        },
        {
            "feature": "maturity_bucket",
            "definition": "mature / recent_only / short_lived / sparse / unavailable",
            "required": True,
            "use": "suppression permission and ablation",
            "misuse_forbidden": "not a primary attack family",
        },
    ]


def online_plan_rows() -> list[dict[str, Any]]:
    return [
        {
            "source": "RIPE RIS update dumps",
            "native_update_interval": "5 minutes",
            "use_in_project": "preferred micro-batch replay unit when RIS-like collectors are present",
            "source_reference": "https://ris.ripe.net/docs/mrt/",
        },
        {
            "source": "RouteViews update dumps",
            "native_update_interval": "15 minutes",
            "use_in_project": "evaluate 15m native and optionally normalized 5m internal chunks",
            "source_reference": "https://bgpstream.caida.org/docs/overview/data-access",
        },
        {
            "source": "Local 6h parquet chunks",
            "native_update_interval": "5 minutes in current run layout",
            "use_in_project": "debug / smoke replay only",
            "source_reference": "data/runs/s2a_baseline_v01_pilot_6h_april16",
        },
        {
            "source": "30d path-memory sidecar",
            "native_update_interval": "stateful historical sidecar, not foreground input batch",
            "use_in_project": "query historical maturity while current 5m/15m events pass foreground",
            "source_reference": "R-MEM-0 design contract",
        },
    ]


def build_report(summary: dict[str, Any]) -> str:
    return f"""# R-MEM-0 30d Path-Memory Sidecar Feasibility Audit

Status: completed read-only feasibility audit.

## Goal

R-POISON-2 and R-POISON-2A showed that the current foreground can suppress a
path-manipulation poisoning variant when crafted history removes path novelty.
R-FOREGROUND-4A then showed that a broad recent-recurrence guard is too
expensive and that a 6h/smoke window cannot prove long-term path maturity.

R-MEM-0 asks whether the next repair should use a 30-day path-memory sidecar.

## Deployment Model

The repair should follow a streaming model:

```text
current 5m/15m BGP update batch
  -> event / evidence sidecars
  -> foreground policy
  -> query 30d path-memory sidecar for maturity
```

The 30-day history is not a one-shot foreground input. It is a stateful memory
table used to decide whether a recurrent route is mature enough to be safely
suppressed.

This follows public data practice: RIPE RIS publishes update files every 5
minutes, while RouteViews-style updates are commonly modeled as 15-minute
dumps. The project should therefore report both overall replay results and
per-micro-batch p50/p90/p99 foreground load.

## Local Coverage

- target date: `{summary["target_date"]}`
- requested history window: `{summary["history_start_date"]}` to `{summary["target_date"]}`
- local unique dates in the requested window: `{summary["local_unique_dates_in_window"]}`
- local collectors in the requested window: `{summary["local_collectors_in_window"]}`
- covers requested 30d window: `{summary["covers_requested_30d_window"]}`

The current local tree contains enough 6h source files to estimate cost and
schema, but it does not contain a complete 30-day history for formal maturity
claims.

## Volume Estimate

- observed target-date raw rows: `{summary["observed_target_date_raw_rows"]}`
- estimated 30d raw rows for same collector set: `{summary["estimated_30d_raw_rows_same_collectors"]}`
- estimated 30d raw bytes for same collector set: `{summary["estimated_30d_raw_size_bytes_same_collectors"]}`

This estimate is for source planning only. It must be validated on HPC before
formal paper claims.

## Feature Contract

The sidecar should expose:

- `path_memory_key`;
- `first_seen_ts`;
- `last_seen_ts`;
- `active_days`;
- `active_micro_batches`;
- `collector_days`;
- `burstiness_score`;
- `maturity_bucket`.

Maturity is suppression-permission evidence. It is not an attack score and not a
benign label.

## Stop Rules

Do not enter R-FOREGROUND-4B implementation unless:

- 30d source coverage is available or a clearly bounded subset is declared;
- path key fields are present;
- collector/time coverage can be reported;
- sidecar generation cost fits HPC resources;
- maturity buckets can be joined to current foreground events.

## Recommended Next Step

`{summary["recommended_next_step"]}`

## Outputs

- `r_mem0_summary.json`
- `r_mem0_source_file_inventory.csv`
- `r_mem0_collector_date_coverage.csv`
- `r_mem0_30d_volume_estimate.csv`
- `r_mem0_path_memory_feature_contract.csv`
- `r_mem0_online_replay_plan.csv`
- `r_mem0_report.md`
"""


def main() -> None:
    args = parse_args()
    run_root = resolve_path(args.run_root)
    history_root = resolve_path(args.history_root)
    output_dir = resolve_path(args.output_dir)
    prepare_output_dir(output_dir, args.overwrite)

    target_date = parse_date(args.target_date)
    history_start = target_date - timedelta(days=args.history_days - 1)

    source_files = scan_source_files(history_root, args.max_files)
    inventory = [asdict(item) for item in source_files]
    coverage = coverage_rows(source_files, history_start, target_date)
    volume = estimate_volume(coverage, target_date, args.history_days)
    feature_contract = feature_contract_rows()
    online_plan = online_plan_rows()

    local_dates = sorted({row["date"] for row in coverage})
    local_collectors = sorted({row["collector"] for row in coverage})
    expected_dates = {
        (history_start + timedelta(days=offset)).isoformat()
        for offset in range(args.history_days)
    }
    local_date_set = set(local_dates)
    covers_30d = expected_dates.issubset(local_date_set)
    volume_row = volume[0]

    schema_ready_files = [
        row
        for row in inventory
        if row["file_kind"] == "raw"
        and row["path_memory_key_ready"]
    ]
    summary = {
        "phase": "R-MEM-0",
        "status": "completed_read_only_feasibility_audit",
        "run_id": args.run_id,
        "run_root": str(run_root.relative_to(REPO_ROOT)) if run_root.exists() else str(run_root),
        "history_root": str(history_root.relative_to(REPO_ROOT)) if history_root.exists() else str(history_root),
        "target_date": target_date.isoformat(),
        "history_days": args.history_days,
        "history_start_date": history_start.isoformat(),
        "local_unique_dates_in_window": len(local_dates),
        "local_dates_in_window": local_dates,
        "local_collectors_in_window": local_collectors,
        "covers_requested_30d_window": covers_30d,
        "source_file_count_scanned": len(inventory),
        "source_schema_ready_raw_file_count": len(schema_ready_files),
        "observed_target_date_raw_rows": volume_row[
            "observed_raw_rows"
        ],
        "observed_target_date_raw_size_bytes": volume_row[
            "observed_raw_size_bytes"
        ],
        "estimated_30d_raw_rows_same_collectors": volume_row[
            "estimated_30d_raw_rows_same_collectors"
        ],
        "estimated_30d_raw_size_bytes_same_collectors": volume_row[
            "estimated_30d_raw_size_bytes_same_collectors"
        ],
        "online_micro_batch_model": "current batches should be replayed at 5m/15m; 30d history is a sidecar lookup, not a foreground input blob",
        "allowed_claim": "local data supports R-MEM-1 planning and sidecar schema design; it does not yet support a complete 30d maturity claim unless 30d source files are materialized",
        "forbidden_claims": [
            "Do not claim 6h recurrence is long-term path maturity.",
            "Do not claim mature path means benign.",
            "Do not claim recent-only path means attack.",
            "Do not use path memory as a truth label.",
            "Do not train learning in R-MEM-0.",
        ],
        "recommended_next_step": "R-MEM-1 materialize a 30d path-memory sidecar on HPC, then run R-FOREGROUND-4B targeted poisoning guard smoke.",
    }

    write_csv(output_dir / "r_mem0_source_file_inventory.csv", inventory)
    write_csv(output_dir / "r_mem0_collector_date_coverage.csv", coverage)
    write_csv(output_dir / "r_mem0_30d_volume_estimate.csv", volume)
    write_csv(output_dir / "r_mem0_path_memory_feature_contract.csv", feature_contract)
    write_csv(output_dir / "r_mem0_online_replay_plan.csv", online_plan)
    write_json(output_dir / "r_mem0_summary.json", summary)
    (output_dir / "r_mem0_report.md").write_text(build_report(summary), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
