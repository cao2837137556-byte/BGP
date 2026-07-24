#!/usr/bin/env python3
"""Run a deterministic BGPalerter runtime-contract smoke.

This phase evaluates component boundaries only. It does not implement a
foreground policy, attach evidence, create labels, or claim attack retention.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd

from r_mem_canonical_observation_v2 import (
    canonical_observation_id,
    normalize_communities,
)


DEFAULT_CONFIG = Path("configs/n_frontend_fit0a_bgpalerter_contract_v01.json")
DEFAULT_OUTPUT = Path("outputs/n_frontend_fit0a_bgpalerter_contract_smoke_v01")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bgpalerter-root", required=True, type=Path)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sample-rows", type=int, default=512)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def normalize_scalar(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "as_py"):
        value = value.as_py()
    if isinstance(value, float) and math.isnan(value):
        return None
    if not isinstance(value, (list, tuple, dict, set)):
        missing = pd.isna(value)
        if isinstance(missing, bool) and missing:
            return None
    if hasattr(value, "item"):
        return value.item()
    return value


def normalize_row(row: dict[str, Any], required_fields: list[str]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for field in required_fields:
        value = normalize_scalar(row.get(field))
        if field == "communities":
            value = normalize_communities(value)
        normalized[field] = value
    return normalized


def build_contract_fixture(row_count: int) -> list[dict[str, Any]]:
    if row_count < 4:
        raise ValueError("--sample-rows must be at least 4")
    rows: list[dict[str, Any]] = []
    for index in range(row_count):
        collector = "route-views.sg" if index % 2 == 0 else "rrc00"
        project = "routeviews" if collector == "route-views.sg" else "ris"
        is_withdrawal = index % 11 == 0
        peer_asn = 64500 + index % 17
        origin_as = None if is_withdrawal else str(64400 + index % 23)
        as_path = None if is_withdrawal else f"{peer_asn} 64496 {origin_as}"
        communities = []
        if index % 5 == 0:
            communities.append(f"{peer_asn}:100")
        if index % 19 == 0:
            communities.append("65535:65281")
        row = {
            "ts": 1712448000.0 + index,
            "collector": collector,
            "project": project,
            "type": "W" if is_withdrawal else "A",
            "peer_asn": peer_asn,
            "peer_address": f"192.0.2.{1 + index % 200}",
            "prefix": f"198.51.{index % 200}.0/24",
            "as_path": as_path,
            "origin_as": origin_as,
            "origin_provenance": (
                "withdrawal" if is_withdrawal else "final_singleton_asn"
            ),
            "communities": communities,
            "next_hop": None if is_withdrawal else f"203.0.113.{1 + index % 200}",
            "source_file": (
                "contract_fixture/"
                f"collector={collector}/updates.{index // 100:04d}.mrt"
            ),
            "archive_timestamp_utc": "2024-04-07T00:00:00Z",
        }
        row["observation_id"] = canonical_observation_id(row)
        rows.append(row)
    return rows


def read_input(
    path: Path | None,
    sample_rows: int,
    required_fields: list[str],
) -> tuple[list[dict[str, Any]], str]:
    if path is None:
        return build_contract_fixture(sample_rows), "schema_contract_fixture"
    if not path.exists():
        raise FileNotFoundError(path)
    suffix = path.suffix.lower()
    if suffix == ".parquet" or path.is_dir():
        frame = pd.read_parquet(path, columns=required_fields)
    elif suffix == ".csv":
        frame = pd.read_csv(path)
    elif suffix in {".jsonl", ".ndjson"}:
        rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return (
            [normalize_row(row, required_fields) for row in rows[:sample_rows]],
            "provided_canonical_sample",
        )
    else:
        raise ValueError(f"Unsupported input type: {path}")
    missing = sorted(set(required_fields) - set(frame.columns))
    if missing:
        raise ValueError(f"Input is not canonical_observation_v2; missing={missing}")
    frame = frame.head(sample_rows)
    return (
        [
            normalize_row(row, required_fields)
            for row in frame.to_dict(orient="records")
        ],
        "provided_canonical_sample",
    )


def stable_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=True) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def run_node_replay(
    repo_root: Path,
    component_root: Path,
    input_path: Path,
    output_path: Path,
    metrics_path: Path,
) -> dict[str, Any]:
    node = shutil.which("node")
    if not node:
        raise RuntimeError("node is not available")
    register = component_root / "node_modules" / "@babel" / "register"
    harness = repo_root / "scripts" / "n_frontend_fit0a_bgpalerter_harness.js"
    if not register.exists():
        raise RuntimeError(
            "BGPalerter dependencies are missing; run npm ci in the component cache"
        )
    command = [
        node,
        "-r",
        str(register),
        str(harness),
        "--input",
        str(input_path),
        "--output",
        str(output_path),
        "--metrics",
        str(metrics_path),
    ]
    env = os.environ.copy()
    env["BGPALERTER_ROOT"] = str(component_root)
    completed = subprocess.run(
        command,
        cwd=component_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=90,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "BGPalerter contract replay failed\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return json.loads(metrics_path.read_text(encoding="utf-8"))


def git_value(component_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(component_root), *args],
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def count_source_lines(path: Path) -> int:
    return sum(
        1
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("//")
    )


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    config_path = (repo_root / args.config).resolve()
    output_dir = (repo_root / args.output_dir).resolve()
    component_root = args.bgpalerter_root.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    required_fields = config["runtime_contract"]["required_fields"]

    if output_dir.exists():
        if not args.overwrite:
            raise FileExistsError(
                f"{output_dir} exists; pass --overwrite to replace this smoke output"
            )
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    package = json.loads(
        (component_root / "package.json").read_text(encoding="utf-8")
    )
    commit = git_value(component_root, "rev-parse", "HEAD")
    dirty_before = git_value(component_root, "status", "--short")
    expected = config["component"]
    if commit != expected["pinned_commit"]:
        raise RuntimeError(
            f"BGPalerter commit mismatch: expected={expected['pinned_commit']} "
            f"actual={commit}"
        )
    if package["version"] != expected["expected_version"]:
        raise RuntimeError(
            f"BGPalerter version mismatch: expected={expected['expected_version']} "
            f"actual={package['version']}"
        )
    if dirty_before:
        raise RuntimeError(f"BGPalerter source tree is dirty before smoke:\n{dirty_before}")

    input_arg = args.input.resolve() if args.input else None
    input_rows, data_role = read_input(
        input_arg,
        args.sample_rows,
        required_fields,
    )
    if not input_rows:
        raise RuntimeError("No input rows selected")
    if any(row.get("observation_id") is None for row in input_rows):
        raise RuntimeError("Contract smoke requires non-null observation_id")
    if len({row["observation_id"] for row in input_rows}) != len(input_rows):
        raise RuntimeError("Contract smoke requires unique observation_id values")

    input_path = output_dir / "contract_input.jsonl"
    write_jsonl(input_path, input_rows)
    metrics: list[dict[str, Any]] = []
    outputs: list[list[dict[str, Any]]] = []
    for replay in ("a", "b"):
        output_path = output_dir / f"contract_output_{replay}.jsonl"
        metrics_path = output_dir / f"contract_metrics_{replay}.json"
        metrics.append(
            run_node_replay(
                repo_root,
                component_root,
                input_path,
                output_path,
                metrics_path,
            )
        )
        outputs.append(read_jsonl(output_path))

    field_audit: list[dict[str, Any]] = []
    for field in required_fields:
        mismatch_a = sum(
            source[field] != target.get(field)
            for source, target in zip(input_rows, outputs[0])
        )
        mismatch_b = sum(
            source[field] != target.get(field)
            for source, target in zip(input_rows, outputs[1])
        )
        field_audit.append(
            {
                "field": field,
                "input_non_null_rows": sum(
                    row[field] is not None for row in input_rows
                ),
                "replay_a_mismatch_rows": mismatch_a,
                "replay_b_mismatch_rows": mismatch_b,
                "roundtrip_pass": mismatch_a == 0 and mismatch_b == 0,
            }
        )

    row_accounting_pass = all(
        len(output) == len(input_rows) for output in outputs
    )
    id_order_pass = all(
        [row["observation_id"] for row in output]
        == [row["observation_id"] for row in input_rows]
        for output in outputs
    )
    field_roundtrip_pass = all(row["roundtrip_pass"] for row in field_audit)
    deterministic_replay_pass = outputs[0] == outputs[1]
    dirty_after = git_value(component_root, "status", "--short")
    core_unmodified_pass = not dirty_before and not dirty_after
    logged_errors_pass = all(metric["logged_error_count"] == 0 for metric in metrics)
    node_harness = repo_root / "scripts" / "n_frontend_fit0a_bgpalerter_harness.js"
    overall_pass = all(
        [
            row_accounting_pass,
            id_order_pass,
            field_roundtrip_pass,
            deterministic_replay_pass,
            core_unmodified_pass,
            logged_errors_pass,
        ]
    )

    summary = {
        "phase": "N-FRONTEND-FIT-0A",
        "component": "BGPalerter",
        "component_repository": expected["repository"],
        "component_commit": commit,
        "component_version": package["version"],
        "component_license": package["license"],
        "data_role": data_role,
        "real_nine_day_asset_used": data_role == "provided_canonical_sample",
        "input_rows": len(input_rows),
        "output_rows_replay_a": len(outputs[0]),
        "output_rows_replay_b": len(outputs[1]),
        "row_accounting_pass": row_accounting_pass,
        "observation_id_order_pass": id_order_pass,
        "field_roundtrip_pass": field_roundtrip_pass,
        "deterministic_replay_pass": deterministic_replay_pass,
        "component_core_unmodified_pass": core_unmodified_pass,
        "logged_errors_pass": logged_errors_pass,
        "network_connector_used": False,
        "truth_label_produced": False,
        "foreground_policy_implemented": False,
        "evidence_attached_or_used": False,
        "adapter_nonblank_source_lines": count_source_lines(node_harness),
        "replay_metrics": metrics,
        "input_payload_sha256": stable_hash(input_rows),
        "output_payload_sha256_replay_a": stable_hash(outputs[0]),
        "output_payload_sha256_replay_b": stable_hash(outputs[1]),
        "overall_pass": overall_pass,
        "classification_after_smoke": (
            "adapt_candidate_contract_passed"
            if overall_pass
            else "reject_or_repair_required"
        ),
        "selected_as_final_frontend": False,
        "recommended_next_step": (
            "N-FRONTEND-FIT-0B real frozen-asset replay and adapter-cost audit"
            if overall_pass
            else "stop and repair the runtime contract before real-data replay"
        ),
        "forbidden_claims": [
            "BGPalerter is selected as the final frontend",
            "nine-day throughput or scalability is proven",
            "attack retention is proven",
            "background suppression is proven",
            "production security is proven"
        ],
    }
    with (output_dir / "n_frontend_fit0a_summary.json").open(
        "w", encoding="utf-8"
    ) as handle:
        json.dump(summary, handle, indent=2, sort_keys=True)
        handle.write("\n")

    with (output_dir / "n_frontend_fit0a_field_roundtrip.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(field_audit[0]))
        writer.writeheader()
        writer.writerows(field_audit)

    boundary_rows = [
        {
            "boundary": "component_source",
            "status": "pinned",
            "evidence": f"{expected['repository']}@{commit}",
        },
        {
            "boundary": "native_runtime",
            "status": "reused",
            "evidence": ", ".join(metrics[0]["native_boundaries_reused"]),
        },
        {
            "boundary": "offline_connector",
            "status": "external_adapter",
            "evidence": "canonical JSONL envelope; zero network connector",
        },
        {
            "boundary": "row_level_ledger",
            "status": "external_adapter",
            "evidence": "one decision record per observation_id",
        },
        {
            "boundary": "component_core",
            "status": "unmodified" if core_unmodified_pass else "modified",
            "evidence": "git status before/after smoke",
        },
        {
            "boundary": "scientific_policy",
            "status": "not_implemented",
            "evidence": "contract_passthrough only; no truth or suppression",
        },
    ]
    with (output_dir / "n_frontend_fit0a_component_boundary_audit.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(boundary_rows[0]))
        writer.writeheader()
        writer.writerows(boundary_rows)

    report = f"""# N-FRONTEND-FIT-0A Runtime Contract Smoke

- Component: BGPalerter `{package['version']}` at `{commit}`
- Data role: `{data_role}`
- Input rows: `{len(input_rows)}`
- Exact row accounting: `{row_accounting_pass}`
- Observation order preserved: `{id_order_pass}`
- Required fields preserved: `{field_roundtrip_pass}`
- Deterministic second replay: `{deterministic_replay_pass}`
- Component core unmodified: `{core_unmodified_pass}`
- Overall pass: `{overall_pass}`

This smoke reuses BGPalerter's native `Consumer`, `Monitor`, and `PubSub`
boundaries with an external canonical connector and row-level ledger. It does
not implement foreground logic, attach evidence, create labels, or prove
attack retention, suppression quality, nine-day throughput, or production
security.

Recommended next step: {summary['recommended_next_step']}.
"""
    (output_dir / "n_frontend_fit0a_report.md").write_text(
        report, encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if overall_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
