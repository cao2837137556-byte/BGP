#!/usr/bin/env python3
"""Run bounded R-MEM-1A BGPStream acquisition probes inside the HPC container.

This is a diagnostic helper. It never materializes a dataset and deliberately
keeps the broker and stream probes separate so an external timeout can identify
a stalled BGPStream call without conflating it with broker reachability.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


BROKER_HOST = "broker.bgpstream.caida.org"
BROKER_BASE_URL = f"https://{BROKER_HOST}/v2"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=("broker", "stream"))
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--project", choices=("routeviews", "ris"))
    parser.add_argument("--collector")
    parser.add_argument("--from-time")
    parser.add_argument("--until-time")
    parser.add_argument("--max-elements", type=int, default=1)
    parser.add_argument("--http-timeout-sec", type=float, default=20.0)
    return parser.parse_args()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def probe_broker(args: argparse.Namespace) -> dict[str, Any]:
    if not args.project:
        raise ValueError("--project is required in broker mode")

    started = time.monotonic()
    addresses = sorted(
        {
            item[4][0]
            for item in socket.getaddrinfo(BROKER_HOST, 443, type=socket.SOCK_STREAM)
        }
    )
    url = f"{BROKER_BASE_URL}/meta/projects/{args.project}"
    request = Request(url, headers={"User-Agent": "bgp-platform-r-mem1a-probe/1"})
    with urlopen(request, timeout=args.http_timeout_sec) as response:  # nosec B310
        body = response.read()
        decoded = json.loads(body.decode("utf-8"))

    return {
        "status": "success",
        "mode": "broker",
        "broker_host": BROKER_HOST,
        "broker_url": url,
        "project": args.project,
        "resolved_addresses": addresses,
        "http_status": getattr(response, "status", None),
        "response_bytes": len(body),
        "broker_error_field": decoded.get("error"),
        "elapsed_sec": round(time.monotonic() - started, 6),
    }


def probe_stream(args: argparse.Namespace) -> dict[str, Any]:
    if not args.collector or not args.from_time or not args.until_time:
        raise ValueError(
            "--collector, --from-time, and --until-time are required in stream mode"
        )
    if args.max_elements <= 0:
        raise ValueError("--max-elements must be positive")

    started = time.monotonic()
    import pybgpstream  # type: ignore

    stream = pybgpstream.BGPStream(
        from_time=args.from_time,
        until_time=args.until_time,
        collectors=[args.collector],
        record_type="updates",
    )
    observed: list[dict[str, Any]] = []
    for element in stream:
        fields = element.fields
        observed.append(
            {
                "collector": element.collector,
                "element_type": element.type,
                "peer_asn": getattr(element, "peer_asn", None),
                "prefix": fields.get("prefix"),
                "as_path_present": bool(fields.get("as-path")),
            }
        )
        if len(observed) >= args.max_elements:
            break

    return {
        "status": "success" if observed else "completed_empty",
        "mode": "stream",
        "collector": args.collector,
        "from_time": args.from_time,
        "until_time": args.until_time,
        "requested_max_elements": args.max_elements,
        "observed_element_count": len(observed),
        "observed_elements": observed,
        "elapsed_sec": round(time.monotonic() - started, 6),
    }


def main() -> int:
    args = parse_args()
    output = Path(args.output_json)
    base = {
        "probe_started_at": utc_now(),
        "hostname": socket.gethostname(),
        "python_version": sys.version,
    }
    try:
        result = probe_broker(args) if args.mode == "broker" else probe_stream(args)
        result.update(base)
        result["probe_finished_at"] = utc_now()
        write_json(output, result)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        result = {
            **base,
            "probe_finished_at": utc_now(),
            "status": "error",
            "mode": args.mode,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        write_json(output, result)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
