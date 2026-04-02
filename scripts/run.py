# Run wrapper with chunked collection, per-collector marker resume, and loop mode.

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid

TIME_FMT = "%Y-%m-%d %H:%M:%S"
STOP_REQUESTED = False


def local_now_compact() -> str:
    return datetime.now().strftime("%Y%m%dT%H%M%S")


def now_local_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def make_run_id() -> str:
    return f"{local_now_compact()}_{uuid.uuid4().hex[:8]}"


def safe_collector_name(value: str) -> str:
    return value.replace(":", "-").replace(" ", "_").replace("/", "_")


def parse_collectors(raw: str) -> list[str]:
    items = []
    seen = set()
    for token in (raw or "").split(","):
        collector = token.strip()
        if not collector or collector in seen:
            continue
        items.append(collector)
        seen.add(collector)
    return items


def marker_path(marker_dir: Path, record_type: str, collector: str) -> Path:
    return marker_dir / f"{record_type}__{collector}.txt"


def read_marker(path: Path):
    if not path.exists():
        return None
    content = path.read_text(encoding="utf-8").strip()
    return content or None


def write_marker(path: Path, value: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def parse_time(value: str) -> datetime:
    return datetime.strptime(value, TIME_FMT)


def format_time(value: datetime) -> str:
    return value.strftime(TIME_FMT)


def write_json(path: Path, obj: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def log_line(log_path: Path, message: str):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(message + "\n")


def to_rel_path(path: Path) -> str:
    p = path.resolve()
    work_root = Path("/work")
    if work_root.exists():
        try:
            return p.relative_to(work_root).as_posix()
        except ValueError:
            pass
    try:
        return p.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return p.as_posix()


def run_step(cmd: list[str], log_path: Path, step_name: str) -> int:
    with log_path.open("a", encoding="utf-8") as f:
        f.write(f"[{step_name}] CMD: " + " ".join(cmd) + "\n")
        f.flush()
        proc = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, text=True)
        return proc.returncode


def list_outputs_for_collector(run_dir: Path, collector: str, label_suffix: str):
    updates_outputs = []
    rel_outputs = []
    collector_dir = run_dir / f"collector={safe_collector_name(collector)}"
    if not collector_dir.exists():
        return updates_outputs, rel_outputs

    for path in collector_dir.rglob("*.parquet"):
        name = path.name
        if label_suffix in name:
            rel_outputs.append(path)
            continue
        if ".rel." in name:
            continue
        updates_outputs.append(path)
    return updates_outputs, rel_outputs


def pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _try_create_lock(lock_path: Path, payload: dict) -> bool:
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(str(lock_path), flags)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return True


def acquire_lock(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pid": os.getpid(),
        "started_at": now_local_iso(),
        "mode": "loop",
    }

    if _try_create_lock(lock_path, payload):
        return True, {
            "stale_replaced": False,
            "payload": payload,
            "path": lock_path.as_posix(),
        }

    existing = {}
    try:
        existing = json.loads(lock_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        existing = {}

    existing_pid = int(existing.get("pid", -1)) if str(existing.get("pid", "")).isdigit() else -1
    if pid_is_alive(existing_pid):
        return False, {
            "reason": f"active loop lock detected pid={existing_pid}",
            "path": lock_path.as_posix(),
        }

    try:
        lock_path.unlink(missing_ok=True)
    except OSError:
        return False, {
            "reason": f"failed to remove stale lock: {lock_path.as_posix()}",
            "path": lock_path.as_posix(),
        }

    if _try_create_lock(lock_path, payload):
        return True, {
            "stale_replaced": True,
            "payload": payload,
            "path": lock_path.as_posix(),
        }

    return False, {
        "reason": f"lock race detected: {lock_path.as_posix()}",
        "path": lock_path.as_posix(),
    }


def release_lock(lock_path: Path):
    try:
        lock_path.unlink(missing_ok=True)
    except OSError:
        pass


def safe_sleep(seconds: int) -> bool:
    global STOP_REQUESTED
    for _ in range(max(0, int(seconds))):
        if STOP_REQUESTED:
            return False
        time.sleep(1)
    return not STOP_REQUESTED


def _request_stop(signum, _frame):
    global STOP_REQUESTED
    STOP_REQUESTED = True


def run_one_collector(
    collector: str,
    args: argparse.Namespace,
    out_dir: Path,
    log_path: Path,
    minutes: int,
    bootstrap_from: str | None,
) -> dict:
    summary = {
        "status": "ok",
        "marker_before": None,
        "marker_after": None,
        "updates_outputs": [],
        "rel_outputs": [],
        "errors": [],
    }
    log_line(log_path, f"[collector] START {collector}")

    collector_marker_path = marker_path(Path(args.marker_dir), args.record_type, collector)
    marker_before = read_marker(collector_marker_path)
    summary["marker_before"] = marker_before

    if args.resume:
        if marker_before:
            start_time_str = marker_before
        elif bootstrap_from:
            start_time_str = bootstrap_from
        else:
            summary["status"] = "failed"
            summary["errors"].append(f"resume marker missing: {collector_marker_path.as_posix()}")
            log_line(log_path, f"[collector] END {collector} status=failed")
            return summary
    else:
        if not args.from_time:
            summary["status"] = "failed"
            summary["errors"].append("missing --from when --resume is disabled")
            log_line(log_path, f"[collector] END {collector} status=failed")
            return summary
        start_time_str = args.from_time.strip()

    try:
        start_time = parse_time(start_time_str)
    except ValueError:
        summary["status"] = "failed"
        summary["errors"].append(f"invalid start time: {start_time_str}")
        log_line(log_path, f"[collector] END {collector} status=failed")
        return summary

    end_time = start_time + timedelta(minutes=minutes)
    current_time = start_time

    while current_time < end_time:
        if STOP_REQUESTED:
            summary["status"] = "failed"
            summary["errors"].append("stopped by signal")
            break

        remaining_minutes = int((end_time - current_time).total_seconds() // 60)
        if remaining_minutes <= 0:
            break
        chunk_minutes = min(args.chunk_minutes, remaining_minutes)
        chunk_from = format_time(current_time)
        chunk_until_dt = current_time + timedelta(minutes=chunk_minutes)
        chunk_until = format_time(chunk_until_dt)
        log_line(log_path, f"[chunk] collector={collector} from={chunk_from} until={chunk_until}")

        collect_cmd = [
            sys.executable,
            "scripts/03_collect_updates.py",
            "--from",
            chunk_from,
            "--minutes",
            str(chunk_minutes),
            "--collectors",
            collector,
            "--record-type",
            args.record_type,
            "--format",
            args.format,
            "--out-base",
            out_dir.as_posix(),
            "--print-head",
            str(args.print_head),
        ]
        if args.max_rows is not None:
            collect_cmd.extend(["--max-rows", str(args.max_rows)])
        rc = run_step(collect_cmd, log_path, "collect")
        if rc != 0:
            summary["status"] = "failed"
            summary["errors"].append(f"collect failed: collector={collector} from={chunk_from} returncode={rc}")
            break

        if args.label_caida:
            label_cmd = [
                sys.executable,
                args.label_script,
                "--run-dir",
                out_dir.as_posix(),
                "--caida-rel",
                args.caida_rel,
                "--suffix",
                args.label_suffix,
            ]
            if args.label_overwrite:
                label_cmd.append("--overwrite")
            rc = run_step(label_cmd, log_path, "caida_label")
            if rc != 0:
                summary["status"] = "failed"
                summary["errors"].append(
                    f"caida label failed: collector={collector} from={chunk_from} returncode={rc}"
                )
                break

        # Marker is updated only after successful collect + optional label.
        write_marker(collector_marker_path, chunk_until)
        summary["marker_after"] = chunk_until
        current_time = chunk_until_dt

    updates_outputs, rel_outputs = list_outputs_for_collector(out_dir, collector, args.label_suffix)
    summary["updates_outputs"] = [to_rel_path(p) for p in sorted(updates_outputs, key=lambda p: p.as_posix())]
    summary["rel_outputs"] = [to_rel_path(p) for p in sorted(rel_outputs, key=lambda p: p.as_posix())]

    if summary["status"] == "failed":
        log_line(log_path, f"[collector] END {collector} status=failed")
    else:
        log_line(log_path, f"[collector] END {collector} status=ok")
    return summary


def run_once(
    args: argparse.Namespace,
    loop_cycle_index: int | None = None,
    bootstrap_from: str | None = None,
    lock_note: str | None = None,
):
    mode = "loop" if loop_cycle_index is not None else "once"
    if mode == "loop":
        minutes = args.window_minutes
        run_id = make_run_id()
    else:
        minutes = args.minutes
        run_id = args.run_id or make_run_id()

    out_dir = Path("data") / "runs" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "run.log"

    created_local = now_local_iso()
    tz_offset = datetime.now().astimezone().strftime("%z")
    run_json = {
        "run_id": run_id,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "created_local": created_local,
        "tz_offset": tz_offset,
        "mode": mode,
        "run_status": "failed",
        "loop_cycle_index": loop_cycle_index,
        "interval_minutes": args.interval_minutes if mode == "loop" else None,
        "window_minutes": args.window_minutes if mode == "loop" else None,
        "bootstrap_from": bootstrap_from,
        "started_local": created_local,
        "finished_local": None,
        "record_type": args.record_type,
        "from": args.from_time,
        "minutes": minutes,
        "chunk_minutes": args.chunk_minutes,
        "resume": args.resume,
        "marker_dir": args.marker_dir,
        "collectors": parse_collectors(args.collectors),
        "max_rows": args.max_rows,
        "format": args.format,
        "print_head": args.print_head,
        "label_caida": args.label_caida,
        "caida_rel": args.caida_rel,
        "label_script": args.label_script,
        "label_suffix": args.label_suffix,
        "label_overwrite": args.label_overwrite,
        "out_dir": out_dir.as_posix(),
        "collectors_summary": {},
    }
    run_json_path = out_dir / "run.json"
    write_json(run_json_path, run_json)

    if mode == "loop":
        log_line(
            log_path,
            f"[loop] START cycle={loop_cycle_index} interval={args.interval_minutes} window={args.window_minutes}",
        )
        if lock_note:
            log_line(log_path, lock_note)

    collectors = run_json["collectors"]
    any_failed = False
    any_ok = False
    for collector in collectors:
        summary = run_one_collector(collector, args, out_dir, log_path, minutes, bootstrap_from)
        run_json["collectors_summary"][collector] = summary
        write_json(run_json_path, run_json)
        if summary["status"] == "failed":
            any_failed = True
        else:
            any_ok = True

    if any_failed and any_ok:
        run_status = "partial_failed"
    elif any_failed:
        run_status = "failed"
    else:
        run_status = "ok"

    run_json["run_status"] = run_status
    run_json["finished_local"] = now_local_iso()
    write_json(run_json_path, run_json)

    if mode == "loop":
        log_line(log_path, f"[loop] END cycle={loop_cycle_index} run_status={run_status}")

    return {
        "run_id": run_id,
        "run_status": run_status,
        "out_dir": out_dir,
        "log_path": log_path,
        "run_json_path": run_json_path,
    }


def run_loop(args: argparse.Namespace) -> int:
    global STOP_REQUESTED
    STOP_REQUESTED = False

    args.resume = True
    collectors = parse_collectors(args.collectors)
    if not collectors:
        raise SystemExit("No valid collectors provided.")

    if args.bootstrap_from:
        try:
            parse_time(args.bootstrap_from)
        except ValueError as exc:
            raise SystemExit(f"Invalid --bootstrap-from time format (expected {TIME_FMT})") from exc

    missing_markers = []
    for collector in collectors:
        m_path = marker_path(Path(args.marker_dir), args.record_type, collector)
        if read_marker(m_path) is None:
            missing_markers.append(collector)
    if missing_markers and not args.bootstrap_from:
        raise SystemExit(
            "Missing marker for collectors {0}. First loop run requires --bootstrap-from.".format(
                ",".join(missing_markers)
            )
        )

    if "--minutes" in sys.argv:
        print("[WARN] --minutes is ignored in --loop mode; using --window-minutes.")

    lock_path = Path(args.state_dir) / "run.lock"
    acquired, lock_meta = acquire_lock(lock_path)
    if not acquired:
        print(f"[FAIL] {lock_meta.get('reason', 'failed to acquire lock')}")
        return 1

    stale_note = None
    if lock_meta.get("stale_replaced"):
        stale_note = f"[lock] stale lock replaced path={lock_meta['path']} pid={lock_meta['payload']['pid']}"
    else:
        stale_note = f"[lock] acquired path={lock_meta['path']} pid={lock_meta['payload']['pid']}"

    previous_sigint = signal.getsignal(signal.SIGINT)
    previous_sigterm = signal.getsignal(signal.SIGTERM) if hasattr(signal, "SIGTERM") else None
    signal.signal(signal.SIGINT, _request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _request_stop)

    cycle_index = 0
    last_log_path = None
    try:
        while not STOP_REQUESTED:
            cycle_index += 1
            if args.max_cycles > 0 and cycle_index > args.max_cycles:
                break

            try:
                lock_note = stale_note if cycle_index == 1 else None
                result = run_once(
                    args,
                    loop_cycle_index=cycle_index,
                    bootstrap_from=args.bootstrap_from,
                    lock_note=lock_note,
                )
                last_log_path = result["log_path"]
            except Exception as exc:  # pylint: disable=broad-except
                msg = f"[loop] ERROR cycle={cycle_index} exception={exc!r}"
                if last_log_path is not None:
                    log_line(last_log_path, msg)
                else:
                    print(msg)
                if STOP_REQUESTED:
                    break
                if not safe_sleep(args.sleep_on_error_seconds):
                    break
                continue

            if args.max_cycles > 0 and cycle_index >= args.max_cycles:
                break
            if STOP_REQUESTED:
                break

            sleep_seconds = args.interval_minutes * 60
            log_line(result["log_path"], f"[loop] SLEEP seconds={sleep_seconds}")
            if not safe_sleep(sleep_seconds):
                break
    finally:
        release_lock(lock_path)
        if last_log_path is not None:
            log_line(last_log_path, f"[lock] released path={lock_path.as_posix()}")
        signal.signal(signal.SIGINT, previous_sigint)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, previous_sigterm)

    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="BGP platform runner: chunked collect + optional CAIDA labeling with per-collector markers."
    )
    p.add_argument("--from", dest="from_time", default=None, help="e.g. 2017-07-07 00:00:00")
    p.add_argument("--minutes", type=int, default=5, help="Total duration in minutes.")
    p.add_argument("--chunk-minutes", type=int, default=5, help="Chunk size in minutes.")
    p.add_argument("--collectors", default="route-views.sg", help="Comma-separated collectors.")
    p.add_argument("--record-type", default="updates", choices=["updates", "ribs"])
    p.add_argument("--max-rows", type=int, default=3000)
    p.add_argument("--format", default="parquet", choices=["parquet", "jsonl"])
    p.add_argument("--resume", action="store_true", help="Resume from marker time (ignore --from).")
    p.add_argument("--marker-dir", default="data/markers")
    p.add_argument("--print-head", type=int, default=5)
    p.add_argument("--run-id", default=None, help="optional: provide your own run_id")
    p.add_argument("--label-caida", dest="label_caida", action="store_true", default=True)
    p.add_argument("--no-label-caida", dest="label_caida", action="store_false")
    p.add_argument(
        "--caida-rel",
        default="data/caida/as-relationships/serial-2/20170701.as-rel2.txt",
        help="Path to CAIDA as-rel2 file.",
    )
    p.add_argument(
        "--label-script",
        default="scripts/04_annotate_caida_rel.py",
        help="Labeling script path.",
    )
    p.add_argument("--label-suffix", default="__rel")
    p.add_argument("--label-overwrite", action="store_true")
    p.add_argument("--loop", action="store_true", help="Enable long-running loop mode.")
    p.add_argument("--interval-minutes", type=int, default=5, help="Loop interval between cycles.")
    p.add_argument("--window-minutes", type=int, default=5, help="Per-cycle collection window in loop mode.")
    p.add_argument("--max-cycles", type=int, default=0, help="0 means run forever in loop mode.")
    p.add_argument("--sleep-on-error-seconds", type=int, default=60, help="Sleep seconds after loop-level errors.")
    p.add_argument("--state-dir", default="data/state", help="Loop state directory.")
    p.add_argument(
        "--bootstrap-from",
        default=None,
        help="Initial start time used in resume/loop mode when marker is missing.",
    )
    args = p.parse_args()

    collectors = parse_collectors(args.collectors)
    if not collectors:
        raise SystemExit("No valid collectors provided.")

    if args.chunk_minutes <= 0:
        raise SystemExit("--chunk-minutes must be > 0")
    if args.minutes <= 0:
        raise SystemExit("--minutes must be > 0")
    if args.window_minutes <= 0:
        raise SystemExit("--window-minutes must be > 0")
    if args.interval_minutes < 0:
        raise SystemExit("--interval-minutes must be >= 0")
    if args.max_cycles < 0:
        raise SystemExit("--max-cycles must be >= 0")
    if args.sleep_on_error_seconds < 0:
        raise SystemExit("--sleep-on-error-seconds must be >= 0")
    if args.label_caida and args.format != "parquet":
        raise SystemExit("CAIDA labeling requires --format parquet")

    if args.loop:
        return run_loop(args)

    if (not args.resume) and (not args.from_time):
        raise SystemExit("Please provide --from or use --resume.")
    if args.bootstrap_from:
        try:
            parse_time(args.bootstrap_from)
        except ValueError as exc:
            raise SystemExit(f"Invalid --bootstrap-from time format (expected {TIME_FMT})") from exc

    result = run_once(args, loop_cycle_index=None, bootstrap_from=args.bootstrap_from)
    if result["run_status"] == "ok":
        print(f"[OK] run_id={result['run_id']}")
        print(f"     out_dir={result['out_dir']}")
        return 0

    print(f"[FAIL] run_id={result['run_id']}, see {result['log_path']}")
    print(f"     out_dir={result['out_dir']}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
