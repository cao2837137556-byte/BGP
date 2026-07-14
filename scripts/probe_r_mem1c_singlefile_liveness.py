#!/usr/bin/env python3
"""Bounded liveness gate for local compressed MRT parsing.

The driver compares the documented PyBGPStream single-file setup with the
official bgpreader CLI on one immutable archive per collector. Each backend is
isolated in its own process group and receives a hard timeout. This is a parser
startup diagnostic, not a parsing benchmark or an experiment result.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = "configs/r_mem1c_local_mrt_parser_smoke_v01.json"
DEFAULT_OUTPUT_RELATIVE = "derived/r_mem1c_singlefile_liveness_v01"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--data-root", default="/data_store")
    parser.add_argument("--manifest")
    parser.add_argument("--output-dir")
    parser.add_argument("--max-elements", type=int, default=100)
    parser.add_argument("--timeout-sec", type=float, default=60.0)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--worker-pybgpstream", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--input-file", help=argparse.SUPPRESS)
    parser.add_argument("--worker-output", help=argparse.SUPPRESS)
    return parser.parse_args()


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def prepare_output(path: Path, overwrite: bool) -> None:
    if path.exists() and any(path.iterdir()):
        if not overwrite:
            raise FileExistsError(f"output directory is not empty: {path}")
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def select_first_per_collector(
    manifest: list[dict[str, Any]], collectors: list[str]
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for collector in collectors:
        matches = sorted(
            (row for row in manifest if str(row.get("collector")) == collector),
            key=lambda row: str(row["archive_timestamp_utc"]),
        )
        if not matches:
            raise ValueError(f"manifest has no file for collector {collector}")
        selected.append(matches[0])
    return selected


def terminate_process_group(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "posix":
        os.killpg(process.pid, signal.SIGTERM)
    else:
        process.kill()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait(timeout=2)


def run_bounded_command(command: list[str], timeout_sec: float) -> dict[str, Any]:
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=os.name == "posix",
        creationflags=(
            subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        ),
    )
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        timed_out = True
        terminate_process_group(process)
        stdout, stderr = process.communicate()
    return {
        "exit_code": process.returncode,
        "timed_out": timed_out,
        "elapsed_sec": round(time.monotonic() - started, 6),
        "stdout": stdout,
        "stderr": stderr,
    }


def run_pybgpstream_worker(args: argparse.Namespace) -> int:
    if not args.input_file or not args.worker_output:
        raise ValueError("worker mode requires --input-file and --worker-output")
    source = Path(args.input_file).resolve()
    output = Path(args.worker_output).resolve()
    started = time.monotonic()
    print(f"heartbeat=worker_start input={source}", flush=True)
    import pybgpstream  # type: ignore

    print("heartbeat=pybgpstream_imported", flush=True)
    stream = pybgpstream.BGPStream(data_interface="singlefile")
    print("heartbeat=stream_constructed", flush=True)
    stream.set_data_interface_option("singlefile", "upd-file", str(source))
    print("heartbeat=singlefile_option_set", flush=True)
    count = 0
    first_element_latency_sec: float | None = None
    first_element: dict[str, Any] | None = None
    print("heartbeat=before_first_element", flush=True)
    for elem in stream:
        count += 1
        if first_element is None:
            fields = elem.fields
            first_element_latency_sec = time.monotonic() - started
            first_element = {
                "type": str(elem.type),
                "timestamp": float(elem.time),
                "prefix": fields.get("prefix"),
                "field_names": sorted(str(name) for name in fields),
            }
            print(
                f"heartbeat=first_element latency_sec={first_element_latency_sec:.6f}",
                flush=True,
            )
        if count >= args.max_elements:
            break
    payload = {
        "status": "passed" if count > 0 else "failed",
        "element_count": count,
        "first_element_latency_sec": first_element_latency_sec,
        "first_element": first_element,
        "elapsed_sec": round(time.monotonic() - started, 6),
    }
    write_json(output, payload)
    print(f"heartbeat=worker_complete elements={count}", flush=True)
    return 0 if count > 0 else 2


def tail_text(value: str, limit: int = 2000) -> str:
    return value[-limit:]


def probe_pybgpstream(
    source_path: Path,
    worker_output: Path,
    max_elements: int,
    timeout_sec: float,
) -> dict[str, Any]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker-pybgpstream",
        "--input-file",
        str(source_path),
        "--worker-output",
        str(worker_output),
        "--max-elements",
        str(max_elements),
    ]
    result = run_bounded_command(command, timeout_sec)
    payload: dict[str, Any] = {}
    if worker_output.is_file():
        payload = json.loads(worker_output.read_text(encoding="utf-8"))
    status = "timed_out" if result["timed_out"] else str(payload.get("status", "failed"))
    return {
        "engine": "pybgpstream",
        "status": status,
        "timed_out": result["timed_out"],
        "exit_code": result["exit_code"],
        "elapsed_sec": result["elapsed_sec"],
        "element_count": int(payload.get("element_count", 0)),
        "first_element_latency_sec": payload.get("first_element_latency_sec"),
        "first_element": payload.get("first_element"),
        "stdout_tail": tail_text(result["stdout"]),
        "stderr_tail": tail_text(result["stderr"]),
    }


def probe_bgpreader(
    source_path: Path, max_elements: int, timeout_sec: float
) -> dict[str, Any]:
    bgpreader = shutil.which("bgpreader")
    if not bgpreader:
        return {
            "engine": "bgpreader",
            "status": "unavailable",
            "timed_out": False,
            "exit_code": None,
            "elapsed_sec": 0.0,
            "element_count": 0,
            "stdout_tail": "",
            "stderr_tail": "bgpreader is not installed in the runtime",
        }
    pipeline = (
        "set -o pipefail; "
        f"{shlex.quote(bgpreader)} -d singlefile "
        f"-o {shlex.quote('upd-file=' + str(source_path))} "
        f"| head -n {max_elements}"
    )
    result = run_bounded_command(["/bin/bash", "-lc", pipeline], timeout_sec)
    lines = [line for line in result["stdout"].splitlines() if line.strip()]
    data_lines = [
        line
        for line in lines
        if line.split("|", 1)[0] in {"U", "R"} and line.count("|") >= 5
    ]
    if result["timed_out"]:
        status = "timed_out"
    elif data_lines:
        status = "passed"
    else:
        status = "failed"
    return {
        "engine": "bgpreader",
        "status": status,
        "timed_out": result["timed_out"],
        "exit_code": result["exit_code"],
        "elapsed_sec": result["elapsed_sec"],
        "element_count": len(data_lines),
        "stdout_tail": tail_text(result["stdout"]),
        "stderr_tail": tail_text(result["stderr"]),
    }


def source_integrity(source: dict[str, Any], data_root: Path) -> dict[str, Any]:
    relative = str(source["local_relative_path"])
    path = data_root / relative
    exists = path.is_file()
    actual_size = path.stat().st_size if exists else None
    expected_size = int(source["size_bytes"])
    size_matches = actual_size == expected_size
    actual_sha256 = sha256_file(path) if size_matches else None
    sha256_matches = actual_sha256 == str(source["sha256"]).lower()
    return {
        "source_path": path,
        "source_relative_path": relative,
        "source_exists": exists,
        "actual_size_bytes": actual_size,
        "expected_size_bytes": expected_size,
        "size_matches": size_matches,
        "actual_sha256": actual_sha256,
        "expected_sha256": str(source["sha256"]).lower(),
        "sha256_matches": sha256_matches,
        "integrity_passed": bool(exists and size_matches and sha256_matches),
    }


def recommendation(rows: list[dict[str, Any]], collectors: list[str]) -> str:
    if not collectors:
        return "repair the liveness plan before any parser execution"
    py_pass = all(
        any(
            row["collector"] == collector
            and row["engine"] == "pybgpstream"
            and row["status"] == "passed"
            for row in rows
        )
        for collector in collectors
    )
    cli_pass = all(
        any(
            row["collector"] == collector
            and row["engine"] == "bgpreader"
            and row["status"] == "passed"
            for row in rows
        )
        for collector in collectors
    )
    if py_pass and cli_pass:
        return "measure one complete file with the documented PyBGPStream setup before restoring the four-file smoke"
    if cli_pass:
        return "repair the Python wrapper against the working bgpreader reference before any formal parser smoke"
    if py_pass:
        return "qualify one complete file through PyBGPStream; bgpreader CLI absence/failure is non-blocking"
    return "stop R-MEM-1C formal replay and evaluate the container singlefile stack or a maintained alternative parser"


def render_report(summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    lines = [
        "# R-MEM-1C Single-file Liveness Report",
        "",
        "## Result",
        "",
        f"- diagnostic completed: `{str(summary['diagnostic_completed']).lower()}`",
        f"- PyBGPStream liveness passed: `{str(summary['pybgpstream_liveness_passed']).lower()}`",
        f"- bgpreader liveness passed: `{str(summary['bgpreader_liveness_passed']).lower()}`",
        f"- usable backend found: `{str(summary['usable_backend_found']).lower()}`",
        f"- next action: `{summary['recommended_next_step']}`",
        "",
        "## Probe Matrix",
        "",
        "| collector | suffix | engine | status | elements | elapsed sec | first element sec |",
        "|---|---:|---|---|---:|---:|---:|",
    ]
    for row in rows:
        first = row.get("first_element_latency_sec")
        lines.append(
            f"| {row['collector']} | {row['source_suffix']} | {row['engine']} | "
            f"{row['status']} | {row['element_count']} | {row['elapsed_sec']} | "
            f"{'' if first is None else first} |"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "This gate tests startup and first-element liveness only. It does not qualify",
            "complete-file parsing, materialize path memory, modify foreground policy,",
            "produce attack truth, or train learning.",
        ]
    )
    return "\n".join(lines) + "\n"


def run_self_test() -> int:
    quick = run_bounded_command(
        [sys.executable, "-c", "print('ok', flush=True)"], timeout_sec=2
    )
    if quick["timed_out"] or quick["exit_code"] != 0 or "ok" not in quick["stdout"]:
        raise AssertionError("bounded command success path failed")
    slow = run_bounded_command(
        [sys.executable, "-c", "import time; time.sleep(2)"], timeout_sec=0.1
    )
    if not slow["timed_out"]:
        raise AssertionError("bounded command timeout path failed")
    print("self_test=passed")
    return 0


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test()
    if args.worker_pybgpstream:
        return run_pybgpstream_worker(args)
    if args.max_elements <= 0:
        raise ValueError("max-elements must be positive")
    if args.timeout_sec <= 0:
        raise ValueError("timeout-sec must be positive")

    config_path = resolve_repo_path(args.config)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    data_root = Path(args.data_root).resolve()
    manifest_path = (
        Path(args.manifest).resolve()
        if args.manifest
        else data_root / config["manifest_relative_path"]
    )
    output_dir = (
        Path(args.output_dir).resolve()
        if args.output_dir
        else data_root / DEFAULT_OUTPUT_RELATIVE
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if len(manifest) != 3840:
        raise ValueError(f"expected complete 3,840-file manifest, found {len(manifest)}")
    collectors = [str(value) for value in config["gates"]["required_collectors"]]
    selected = select_first_per_collector(manifest, collectors)
    prepare_output(output_dir, args.overwrite)

    plan = {
        "phase": "R-MEM-1C-LIVENESS",
        "dataset_id": config["dataset_id"],
        "config_path": str(config_path),
        "manifest_path": str(manifest_path),
        "output_dir": str(output_dir),
        "selected_file_count": len(selected),
        "selected_files": selected,
        "max_elements_per_backend": args.max_elements,
        "timeout_sec_per_backend": args.timeout_sec,
        "plan_only": args.plan_only,
    }
    write_json(output_dir / "r_mem1c_liveness_plan.json", plan)
    print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True), flush=True)
    if args.plan_only:
        return 0

    rows: list[dict[str, Any]] = []
    source_audit: list[dict[str, Any]] = []
    for source in selected:
        integrity = source_integrity(source, data_root)
        source_audit.append(
            {
                "collector": source["collector"],
                "archive_timestamp_utc": source["archive_timestamp_utc"],
                **{key: str(value) if isinstance(value, Path) else value for key, value in integrity.items()},
            }
        )
        print(
            f"heartbeat=source_integrity collector={source['collector']} "
            f"passed={integrity['integrity_passed']}",
            flush=True,
        )
        if not integrity["integrity_passed"]:
            continue
        source_path = Path(integrity["source_path"])
        safe_collector = str(source["collector"]).replace(".", "_").replace("/", "_")
        worker_output = output_dir / "workers" / f"{safe_collector}_pybgpstream.json"
        for engine in ("pybgpstream", "bgpreader"):
            print(
                f"heartbeat=probe_start collector={source['collector']} engine={engine}",
                flush=True,
            )
            if engine == "pybgpstream":
                result = probe_pybgpstream(
                    source_path, worker_output, args.max_elements, args.timeout_sec
                )
            else:
                result = probe_bgpreader(
                    source_path, args.max_elements, args.timeout_sec
                )
            row = {
                "collector": source["collector"],
                "project": source["project"],
                "archive_timestamp_utc": source["archive_timestamp_utc"],
                "source_relative_path": source["local_relative_path"],
                "source_suffix": source_path.suffix,
                **result,
            }
            if isinstance(row.get("first_element"), (dict, list)):
                row["first_element"] = json.dumps(row["first_element"], sort_keys=True)
            rows.append(row)
            print(
                f"heartbeat=probe_complete collector={source['collector']} engine={engine} "
                f"status={result['status']} elements={result['element_count']} "
                f"elapsed_sec={result['elapsed_sec']}",
                flush=True,
            )

    by_engine = Counter(
        row["engine"] for row in rows if row["status"] == "passed"
    )
    source_integrity_passed = all(row["integrity_passed"] for row in source_audit)
    py_passed = source_integrity_passed and by_engine["pybgpstream"] == len(collectors)
    cli_passed = source_integrity_passed and by_engine["bgpreader"] == len(collectors)
    summary = {
        "phase": "R-MEM-1C-LIVENESS",
        "dataset_id": config["dataset_id"],
        "diagnostic_completed": len(rows) == len(collectors) * 2,
        "source_integrity_passed": source_integrity_passed,
        "selected_file_count": len(selected),
        "collectors": collectors,
        "max_elements_per_backend": args.max_elements,
        "timeout_sec_per_backend": args.timeout_sec,
        "pybgpstream_liveness_passed": py_passed,
        "bgpreader_liveness_passed": cli_passed,
        "usable_backend_found": py_passed or cli_passed,
        "timed_out_probe_count": sum(int(row["timed_out"]) for row in rows),
        "probe_status_counts": dict(Counter(row["status"] for row in rows)),
        "recommended_next_step": recommendation(rows, collectors),
        "claims": {
            "complete_file_parse_qualified": False,
            "path_memory_materialized": False,
            "foreground_modified": False,
            "attack_truth_produced": False,
            "learning_trained": False,
        },
    }
    write_json(output_dir / "r_mem1c_liveness_summary.json", summary)
    write_csv(output_dir / "r_mem1c_liveness_probe_audit.csv", rows)
    write_csv(output_dir / "r_mem1c_liveness_source_audit.csv", source_audit)
    (output_dir / "r_mem1c_liveness_report.md").write_text(
        render_report(summary, rows), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
