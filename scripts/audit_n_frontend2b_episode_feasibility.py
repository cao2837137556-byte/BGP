#!/usr/bin/env python3
"""Audit N-FRONTEND-2B episode template feasibility before HPC submission.

This is a read-only reconnaissance step. It loads one bounded episode of real
canonical observations, rebuilds the template pool, and reports per-pair
qualification with explicit failure reasons. It writes no attack rows, no
mixed assets, and no replay artifacts. The goal is to choose an episode that
can actually support all five frozen pairs before any formal dual submission.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_n_frontend1_causal_transitions import (  # noqa: E402
    discover_inputs,
    load_bounded_rows,
    load_config,
    text,
)
from run_n_frontend2b_controlled_pairs import (  # noqa: E402
    build_template_pool,
    choose_templates,
    has_no_export,
)

DEFAULT_CONFIG = Path("configs/n_frontend2b_controlled_pairs_v01.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", required=True)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--start-ts", type=float, required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--batch-size", type=int, default=100_000)
    return parser.parse_args()


def pair_options_diagnostic(
    pair_id: str,
    contract: dict[str, Any],
    candidates: list[dict[str, Any]],
    noexport_by_observer: dict[tuple[str, str], list[dict[str, Any]]],
) -> dict[str, Any]:
    required = int(contract["required_observer_count"])
    needs_noexport = bool(contract["requires_no_export_template"])
    by_prefix: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        by_prefix[str(row["prefix"])].append(row)

    prefixes_seen = len(by_prefix)
    prefixes_with_collectors = 0
    strict_options = 0
    relaxed_options = 0
    for prefix, rows in by_prefix.items():
        distinct: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            distinct.setdefault((str(row["collector"]), str(row["peer_address"])), row)
        values = list(distinct.values())
        if len({str(row["collector"]) for row in values}) < required:
            continue
        prefixes_with_collectors += 1
        if not needs_noexport:
            strict_options += 1
            relaxed_options += 1
            continue
        values.sort(
            key=lambda row: (
                not has_no_export(row.get("communities")),
                str(row["collector"]),
            )
        )
        if has_no_export(values[0].get("communities")):
            strict_options += 1
        # Relaxed rule: the primary observer has any real NO_EXPORT observation
        # anywhere in this episode, not necessarily on the template row.
        if any(
            noexport_by_observer.get((str(row["collector"]), str(row["peer_address"])))
            for row in values
        ):
            relaxed_options += 1
    return {
        "pair_id": pair_id,
        "required_observer_count": required,
        "requires_no_export_template": needs_noexport,
        "quiet_candidate_prefixes": prefixes_seen,
        "prefixes_spanning_required_collectors": prefixes_with_collectors,
        "strict_qualified_option_count": strict_options,
        "observer_level_noexport_option_count": relaxed_options,
    }


def main() -> None:
    args = parse_args()
    config_path = Path(args.config)
    config = load_config(config_path)
    repo_root = config_path.resolve().parent.parent
    frontend_config_path = Path(config["frontend_config"])
    if not frontend_config_path.is_absolute():
        frontend_config_path = repo_root / frontend_config_path
    frontend_config = load_config(frontend_config_path)

    episode_start = float(args.start_ts)
    episode_end = episode_start + float(config["episode_duration_sec"])
    files = discover_inputs(args.input, 0)
    data, load_meta = load_bounded_rows(
        files,
        frontend_config,
        episode_start,
        episode_end,
        0,
        0,
        [],
        args.batch_size,
    )

    candidates, noexport_by_observer = build_template_pool(data, episode_start, config)
    contracts = {row["pair_id"]: row for row in config["pair_contracts"]}
    diagnostics = [
        pair_options_diagnostic(pair_id, contracts[pair_id], candidates, noexport_by_observer)
        for pair_id in config["required_pair_ids"]
    ]
    try:
        selected = choose_templates(candidates, noexport_by_observer, config)
        strict_verdict = {"passed": True, "failed_pair": None}
        selected_summary = {
            pair_id: [str(row["prefix"]) for row in rows]
            for pair_id, rows in selected.items()
        }
    except ValueError as exc:
        strict_verdict = {"passed": False, "failed_pair": str(exc)}
        selected_summary = {}

    noexport_observers = sorted(
        f"{collector}|{peer}" for (collector, peer) in noexport_by_observer
    )
    report = {
        "phase": "N-FRONTEND-2B-FEASIBILITY",
        "episode_start_ts": episode_start,
        "episode_end_ts": episode_end,
        "input_files": load_meta.get("input_files", []),
        "source_rows": len(data),
        "observed_collectors": sorted(
            str(value) for value in data["collector"].dropna().unique().tolist()
        ) if len(data) else [],
        "quiet_template_candidate_count": len(candidates),
        "noexport_observer_count": len(noexport_observers),
        "noexport_observers": noexport_observers,
        "pair_diagnostics": diagnostics,
        "strict_selection_passed": strict_verdict["passed"],
        "strict_selection_error": strict_verdict["failed_pair"],
        "strict_selected_prefixes": selected_summary,
        "read_only_audit": True,
        "attack_rows_written": 0,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
