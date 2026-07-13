#!/usr/bin/env python3
"""Download immutable Route Views/RIS MRT archives with resumable provenance.

The downloader is intentionally independent of PyBGPStream. It materializes
provider archive bytes, verifies compressed-stream integrity, and writes a
deterministic manifest before those bytes are transferred to HPC for parsing.
"""

from __future__ import annotations

import argparse
import bz2
import csv
import gzip
import hashlib
import json
import os
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener


USER_AGENT = "bgp-platform-r-mem1b-archive-acquisition/1.0"
READ_SIZE = 1024 * 1024


@dataclass(frozen=True)
class PlannedFile:
    item_id: str
    project: str
    collector: str
    archive_timestamp_utc: str
    source_url: str
    local_relative_path: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default="configs/r_mem1b_10d_direct_archive_v01.json",
    )
    parser.add_argument(
        "--data-root",
        help="External data root. Defaults to BGP_DATA_ROOT.",
    )
    parser.add_argument(
        "--proxy",
        default=os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY"),
        help="HTTP(S) proxy URL, for example http://127.0.0.1:7897.",
    )
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--timeout-sec", type=float, default=120.0)
    parser.add_argument("--smoke-files-per-collector", type=int)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--skip-compression-check",
        action="store_true",
        help="Development-only escape hatch; formal runs must not use it.",
    )
    return parser.parse_args()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def iter_dates(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def build_plan(config: dict[str, Any]) -> list[PlannedFile]:
    dataset_id = config["dataset_id"]
    start = parse_date(config["start_date"])
    end = parse_date(config["end_date"])
    if end < start:
        raise ValueError("end_date precedes start_date")

    plan: list[PlannedFile] = []
    for source in config["sources"]:
        interval = int(source["interval_minutes"])
        if interval <= 0 or 1440 % interval:
            raise ValueError(f"invalid interval_minutes for {source['collector']}")
        for day in iter_dates(start, end):
            for minute in range(0, 1440, interval):
                stamp = datetime.combine(day, datetime_time(), timezone.utc) + timedelta(
                    minutes=minute
                )
                date_compact = stamp.strftime("%Y%m%d")
                time_compact = stamp.strftime("%H%M")
                substitutions = {
                    "year_month": stamp.strftime("%Y.%m"),
                    "date_compact": date_compact,
                    "time_compact": time_compact,
                }
                filename = f"updates.{date_compact}.{time_compact}{source['extension']}"
                relative = Path(
                    "raw_mrt",
                    dataset_id,
                    source["project"],
                    source["collector"],
                    stamp.strftime("%Y.%m"),
                    filename,
                ).as_posix()
                item_key = f"{source['project']}|{source['collector']}|{stamp.isoformat()}"
                item_id = hashlib.sha256(item_key.encode("utf-8")).hexdigest()[:20]
                plan.append(
                    PlannedFile(
                        item_id=item_id,
                        project=source["project"],
                        collector=source["collector"],
                        archive_timestamp_utc=stamp.isoformat().replace("+00:00", "Z"),
                        source_url=source["url_template"].format(**substitutions),
                        local_relative_path=relative,
                    )
                )
    return sorted(plan, key=lambda item: (item.collector, item.archive_timestamp_utc))


def select_smoke(plan: list[PlannedFile], count: int | None) -> list[PlannedFile]:
    if count is None:
        return plan
    if count <= 0:
        raise ValueError("--smoke-files-per-collector must be positive")
    selected: list[PlannedFile] = []
    collectors = sorted({item.collector for item in plan})
    for collector in collectors:
        candidates = [item for item in plan if item.collector == collector]
        if len(candidates) < count:
            raise ValueError(f"not enough planned files for {collector}")
        selected.extend(candidates[:count])
    return sorted(selected, key=lambda item: (item.collector, item.archive_timestamp_utc))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(READ_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_compressed_stream(path: Path) -> str:
    if path.suffix == ".bz2":
        opener = bz2.open
    elif path.suffix == ".gz":
        opener = gzip.open
    else:
        raise ValueError(f"unsupported compressed archive suffix: {path.suffix}")
    with opener(path, "rb") as handle:
        while handle.read(READ_SIZE):
            pass
    return "passed"


def load_receipt(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def validate_existing(
    destination: Path,
    receipt: dict[str, Any] | None,
    require_compression: bool,
) -> dict[str, Any] | None:
    if not destination.is_file() or destination.stat().st_size <= 0 or not receipt:
        return None
    if receipt.get("size_bytes") != destination.stat().st_size:
        return None
    digest = sha256_file(destination)
    if receipt.get("sha256") != digest:
        return None
    compression_check = (
        verify_compressed_stream(destination) if require_compression else "skipped"
    )
    return {
        **receipt,
        "status": "verified_existing",
        "sha256": digest,
        "compression_check": compression_check,
        "verified_at": utc_now(),
    }


def build_http_opener(proxy: str | None):
    proxies = {"http": proxy, "https": proxy} if proxy else {}
    return build_opener(ProxyHandler(proxies))


def transfer_once(
    item: PlannedFile,
    destination: Path,
    partial: Path,
    proxy: str | None,
    timeout_sec: float,
) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    resume_from = partial.stat().st_size if partial.exists() else 0
    headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
    if resume_from:
        headers["Range"] = f"bytes={resume_from}-"
    request = Request(item.source_url, headers=headers)
    opener = build_http_opener(proxy)
    started = time.monotonic()
    try:
        response = opener.open(request, timeout=timeout_sec)  # nosec B310
    except HTTPError as exc:
        if exc.code == 416 and resume_from:
            content_range = exc.headers.get("Content-Range", "")
            expected = content_range.rsplit("/", 1)[-1]
            if expected.isdigit() and int(expected) == resume_from:
                partial.replace(destination)
                return {
                    "http_status": 416,
                    "resumed_from_bytes": resume_from,
                    "downloaded_bytes": 0,
                    "etag": exc.headers.get("ETag"),
                    "last_modified": exc.headers.get("Last-Modified"),
                    "elapsed_sec": round(time.monotonic() - started, 6),
                }
        raise

    status = getattr(response, "status", response.getcode())
    append = bool(resume_from and status == 206)
    mode = "ab" if append else "wb"
    if resume_from and not append:
        resume_from = 0
    downloaded = 0
    with response, partial.open(mode) as handle:
        while True:
            chunk = response.read(READ_SIZE)
            if not chunk:
                break
            handle.write(chunk)
            downloaded += len(chunk)
        handle.flush()
        os.fsync(handle.fileno())
    if partial.stat().st_size <= 0:
        raise IOError("provider response produced an empty archive")
    partial.replace(destination)
    return {
        "http_status": status,
        "resumed_from_bytes": resume_from,
        "downloaded_bytes": downloaded,
        "etag": response.headers.get("ETag"),
        "last_modified": response.headers.get("Last-Modified"),
        "content_length_header": response.headers.get("Content-Length"),
        "elapsed_sec": round(time.monotonic() - started, 6),
    }


def download_item(
    item: PlannedFile,
    data_root: Path,
    receipt_dir: Path,
    proxy: str | None,
    retries: int,
    timeout_sec: float,
    overwrite: bool,
    require_compression: bool,
) -> dict[str, Any]:
    destination = data_root / Path(item.local_relative_path)
    partial = destination.with_name(destination.name + ".part")
    receipt_path = receipt_dir / f"{item.item_id}.json"
    base = asdict(item)

    if overwrite:
        destination.unlink(missing_ok=True)
        partial.unlink(missing_ok=True)
        receipt_path.unlink(missing_ok=True)
    else:
        existing = validate_existing(
            destination, load_receipt(receipt_path), require_compression
        )
        if existing:
            return existing
        if destination.exists():
            partial.unlink(missing_ok=True)
            shutil.move(str(destination), str(partial))

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            transfer = transfer_once(
                item, destination, partial, proxy, timeout_sec
            )
            size_bytes = destination.stat().st_size
            digest = sha256_file(destination)
            compression_check = (
                verify_compressed_stream(destination)
                if require_compression
                else "skipped"
            )
            receipt = {
                **base,
                **transfer,
                "status": "downloaded",
                "attempt": attempt,
                "size_bytes": size_bytes,
                "sha256": digest,
                "compression_check": compression_check,
                "completed_at": utc_now(),
            }
            write_json(receipt_path, receipt)
            return receipt
        except Exception as exc:  # retain exact type/message in the audit receipt
            last_error = exc
            if destination.exists() and not partial.exists():
                shutil.move(str(destination), str(partial))
            if attempt < retries:
                time.sleep(min(30.0, 2.0 ** (attempt - 1)))

    return {
        **base,
        "status": "failed",
        "attempt": retries,
        "error_type": type(last_error).__name__ if last_error else "unknown",
        "error": str(last_error) if last_error else "unknown failure",
        "partial_size_bytes": partial.stat().st_size if partial.exists() else 0,
        "failed_at": utc_now(),
    }


def write_manifest_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row})
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def main() -> int:
    args = parse_args()
    config_path = Path(args.config).resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    plan = build_plan(config)
    expected_total = int(config.get("expected", {}).get("total_files", len(plan)))
    if len(plan) != expected_total:
        raise ValueError(
            f"generated plan has {len(plan)} files; config expects {expected_total}"
        )
    selected = select_smoke(plan, args.smoke_files_per_collector)

    data_root_value = args.data_root or os.environ.get("BGP_DATA_ROOT")
    if not data_root_value:
        raise SystemExit("--data-root or BGP_DATA_ROOT is required")
    data_root = Path(data_root_value).resolve()
    data_root.mkdir(parents=True, exist_ok=True)
    mode = "smoke" if args.smoke_files_per_collector else "full"
    manifest_dir = data_root / "manifests" / config["dataset_id"] / mode
    receipt_dir = data_root / "manifests" / config["dataset_id"] / "receipts"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    receipt_dir.mkdir(parents=True, exist_ok=True)

    plan_rows = [asdict(item) for item in selected]
    with (manifest_dir / "download_plan.jsonl").open("w", encoding="utf-8") as handle:
        for row in plan_rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    plan_summary = {
        "phase": config["phase"],
        "dataset_id": config["dataset_id"],
        "mode": mode,
        "generated_at": utc_now(),
        "config_path": str(config_path),
        "data_root": str(data_root),
        "full_plan_file_count": len(plan),
        "selected_file_count": len(selected),
        "selected_by_collector": {
            collector: sum(item.collector == collector for item in selected)
            for collector in sorted({item.collector for item in selected})
        },
        "proxy_configured": bool(args.proxy),
        "plan_only": args.plan_only,
    }
    write_json(manifest_dir / "plan_summary.json", plan_summary)
    print(json.dumps(plan_summary, ensure_ascii=False, sort_keys=True), flush=True)
    if args.plan_only:
        return 0
    if args.workers <= 0 or args.retries <= 0:
        raise ValueError("workers and retries must be positive")

    started_at = utc_now()
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                download_item,
                item,
                data_root,
                receipt_dir,
                args.proxy,
                args.retries,
                args.timeout_sec,
                args.overwrite,
                not args.skip_compression_check,
            ): item
            for item in selected
        }
        for completed, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            results.append(result)
            if result["status"] == "failed" or completed == len(selected) or completed % 25 == 0:
                print(
                    f"progress={completed}/{len(selected)} status={result['status']} "
                    f"collector={result['collector']} file={Path(result['local_relative_path']).name}",
                    flush=True,
                )

    results.sort(key=lambda row: (row["collector"], row["archive_timestamp_utc"]))
    failed = [row for row in results if row["status"] == "failed"]
    completed = [row for row in results if row["status"] != "failed"]
    summary = {
        **plan_summary,
        "plan_only": False,
        "started_at": started_at,
        "finished_at": utc_now(),
        "completed_file_count": len(completed),
        "failed_file_count": len(failed),
        "all_selected_files_complete": not failed and len(completed) == len(selected),
        "total_size_bytes": sum(int(row.get("size_bytes", 0)) for row in completed),
        "downloaded_status_count": sum(row["status"] == "downloaded" for row in completed),
        "verified_existing_status_count": sum(
            row["status"] == "verified_existing" for row in completed
        ),
        "compression_check_passed_count": sum(
            row.get("compression_check") == "passed" for row in completed
        ),
        "failed_items": [
            {
                "source_url": row["source_url"],
                "error_type": row.get("error_type"),
                "error": row.get("error"),
            }
            for row in failed
        ],
    }
    write_manifest_csv(manifest_dir / "download_manifest.csv", results)
    write_json(manifest_dir / "download_manifest.json", results)
    write_json(manifest_dir / "download_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)
    return 0 if summary["all_selected_files_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
