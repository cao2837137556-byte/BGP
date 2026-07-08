#!/usr/bin/env python3
"""Collect canonical BGP update parquet sources for R-MEM-1A.

This is a source-data helper, not a detector and not the legacy seven-layer
pipeline. It writes raw BGP update rows in the repository's collector/date
layout so the R-MEM-1A sidecar materializer can consume them.

The script intentionally imports pybgpstream lazily so local py_compile can run
without the HPC BGPStream container.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = "configs/r_mem1a_10d_path_memory_v01.json"
TIME_FMT = "%Y-%m-%d %H:%M:%S"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--source-root", default=None)
    parser.add_argument("--output-run-id", default=None)
    parser.add_argument("--collector", default=None)
    parser.add_argument("--date", default=None)
    parser.add_argument("--array-index", type=int, default=None)
    parser.add_argument("--plan-only", action="store_true")
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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def safe_collector(value: str) -> str:
    return value.replace(":", "-").replace(" ", "_").replace("/", "_")


def date_range(start: str, days: int) -> list[str]:
    current = datetime.strptime(start, "%Y-%m-%d").date()
    return [(current + timedelta(days=offset)).isoformat() for offset in range(days)]


def task_grid(config: dict[str, Any]) -> list[dict[str, str]]:
    target = datetime.strptime(config["target_date"], "%Y-%m-%d").date()
    start = target - timedelta(days=int(config["history_days"]) - 1)
    days = date_range(start.isoformat(), int(config["history_days"]))
    tasks: list[dict[str, str]] = []
    for day in days:
        for collector in config["canonical_collectors"]:
            tasks.append({"date": day, "collector": collector})
    return tasks


def output_path(
    source_root: Path,
    run_id: str,
    collector: str,
    start_dt: datetime,
    end_dt: datetime,
    record_type: str,
) -> Path:
    date_text = start_dt.date().isoformat()
    start = start_dt.strftime("%H-%M-%S")
    end = end_dt.strftime("%H-%M-%S")
    return (
        source_root
        / run_id
        / f"collector={safe_collector(collector)}"
        / f"date={date_text}"
        / f"{record_type}__{start}__{end}.parquet"
    )


def elem_to_row(elem: Any) -> dict[str, Any]:
    fields = elem.fields
    communities = fields.get("communities")
    if communities is None:
        comm_list: list[str] = []
    elif isinstance(communities, list):
        comm_list = [str(value) for value in communities]
    else:
        comm_list = [str(communities)]
    return {
        "ts": elem.time,
        "collector": elem.collector,
        "type": elem.type,
        "peer_asn": getattr(elem, "peer_asn", None),
        "prefix": fields.get("prefix"),
        "as_path": fields.get("as-path"),
        "communities": comm_list,
        "next_hop": fields.get("next-hop"),
    }


def collect_interval(
    collector: str,
    start_dt: datetime,
    end_dt: datetime,
    record_type: str,
    max_rows: int,
) -> pd.DataFrame:
    import pybgpstream  # type: ignore

    stream = pybgpstream.BGPStream(
        from_time=start_dt.strftime(TIME_FMT),
        until_time=end_dt.strftime(TIME_FMT),
        collectors=[collector],
        record_type=record_type,
    )
    rows: list[dict[str, Any]] = []
    for elem in stream:
        rows.append(elem_to_row(elem))
        if max_rows and len(rows) >= max_rows:
            break
    return pd.DataFrame(rows)


def collect_day(
    config: dict[str, Any],
    source_root: Path,
    output_run_id: str,
    collector: str,
    day: str,
    overwrite: bool,
    plan_only: bool,
) -> dict[str, Any]:
    source_cfg = config["source_collection"]
    record_type = str(source_cfg.get("record_type", "updates"))
    chunk_minutes = int(
        source_cfg.get("collector_chunk_minutes", {}).get(
            collector, source_cfg.get("default_chunk_minutes", 15)
        )
    )
    max_rows = int(source_cfg.get("max_rows_per_chunk", 0))
    skip_existing = bool(source_cfg.get("skip_existing", True))
    day_start = datetime.strptime(f"{day} 00:00:00", TIME_FMT)
    chunks = int((24 * 60) / chunk_minutes)
    rows: list[dict[str, Any]] = []
    for idx in range(chunks):
        start_dt = day_start + timedelta(minutes=idx * chunk_minutes)
        end_dt = start_dt + timedelta(minutes=chunk_minutes)
        out = output_path(source_root, output_run_id, collector, start_dt, end_dt, record_type)
        row = {
            "collector": collector,
            "date": day,
            "chunk_index": idx,
            "chunk_minutes": chunk_minutes,
            "from_time": start_dt.strftime(TIME_FMT),
            "until_time": end_dt.strftime(TIME_FMT),
            "output": str(out),
            "status": "planned",
            "rows": 0,
        }
        if out.exists() and skip_existing and not overwrite:
            row["status"] = "exists_skipped"
            try:
                row["rows"] = int(pd.read_parquet(out, columns=["ts"]).shape[0])
            except Exception:
                row["rows"] = -1
            rows.append(row)
            continue
        if plan_only:
            rows.append(row)
            continue
        frame = collect_interval(collector, start_dt, end_dt, record_type, max_rows)
        out.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(out, index=False)
        row["status"] = "collected"
        row["rows"] = int(len(frame))
        rows.append(row)

    summary = {
        "collector": collector,
        "date": day,
        "output_run_id": output_run_id,
        "record_type": record_type,
        "chunk_minutes": chunk_minutes,
        "planned_chunks": chunks,
        "collected_chunks": sum(1 for row in rows if row["status"] == "collected"),
        "existing_skipped_chunks": sum(1 for row in rows if row["status"] == "exists_skipped"),
        "total_rows": sum(int(row["rows"]) for row in rows if int(row["rows"]) > 0),
        "plan_only": plan_only,
        "max_rows_per_chunk": max_rows,
        "rows": rows,
    }
    summary_path = (
        source_root
        / output_run_id
        / "_collection_summaries"
        / f"{safe_collector(collector)}__{day}.json"
    )
    write_json(summary_path, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return summary


def main() -> None:
    args = parse_args()
    config_path = resolve_path(args.config)
    config = read_json(config_path)
    source_root = resolve_path(args.source_root or config["source"]["source_root"])
    output_run_id = args.output_run_id or str(config["source"]["source_run_id"])

    collector = args.collector
    day = args.date
    if args.array_index is not None:
        tasks = task_grid(config)
        if args.array_index < 0 or args.array_index >= len(tasks):
            raise SystemExit(f"array index out of range: {args.array_index} / {len(tasks)}")
        task = tasks[args.array_index]
        collector = task["collector"]
        day = task["date"]

    if not collector or not day:
        tasks = task_grid(config)
        write_json(
            source_root / output_run_id / "r_mem1a_collection_plan.json",
            {
                "task_count": len(tasks),
                "output_run_id": output_run_id,
                "tasks": tasks,
            },
        )
        print(json.dumps({"task_count": len(tasks), "tasks": tasks}, ensure_ascii=False, indent=2))
        return

    collect_day(
        config=config,
        source_root=source_root,
        output_run_id=output_run_id,
        collector=collector,
        day=day,
        overwrite=args.overwrite,
        plan_only=args.plan_only,
    )


if __name__ == "__main__":
    main()
