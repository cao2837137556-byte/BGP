#!/usr/bin/env python3
"""Validate one isolated N-FRONTEND-1B bounded replay result."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--expected-collector", action="append", default=[])
    parser.add_argument("--expected-input-file-count", type=int, required=True)
    parser.add_argument("--expected-start-ts", type=float, required=True)
    parser.add_argument("--expected-end-ts", type=float, required=True)
    parser.add_argument(
        "--expect-per-collector-cap",
        action="store_true",
        help=(
            "Require the balanced preflight cap to have been reached. "
            "Formal replay validation omits this flag and requires no cap."
        ),
    )
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def parquet_rows(path: Path) -> int:
    return int(pq.ParquetFile(path).metadata.num_rows)


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    summary_path = output_dir / "n_frontend1_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    expected_collectors = sorted(set(args.expected_collector))

    checks: dict[str, bool] = {
        "summary_exists": summary_path.is_file(),
        "phase_is_n_frontend1": summary.get("phase") == "N-FRONTEND-1",
        "canonical_schema_v2": summary.get("input_schema")
        == "canonical_observation_v2",
        "contract_passed": summary.get("contract_passed") is True,
        "accounting_passed": summary.get("all_accounting_passed") is True,
        "zero_causality_violations": summary.get("causality_violation_count") == 0,
        "required_collectors_exact": sorted(summary.get("required_collectors", []))
        == expected_collectors,
        "observed_collectors_exact": sorted(summary.get("observed_collectors", []))
        == expected_collectors,
        "no_missing_required_collectors": not summary.get(
            "missing_required_collectors"
        ),
        "each_collector_has_rows": all(
            int(summary.get("selected_rows_by_collector", {}).get(item, 0)) > 0
            for item in expected_collectors
        ),
        "input_file_count_exact": summary.get("input_file_count")
        == args.expected_input_file_count,
        "not_globally_truncated": summary.get("selection_truncated_by_max_rows")
        is False,
        "per_collector_cap_matches_mode": bool(
            summary.get("selection_truncated_by_per_collector_cap")
        )
        is args.expect_per_collector_cap,
        "route_state_identity_complete": int(
            summary.get("state_identity_missing_route_observation_count", -1)
        )
        == 0,
        "selected_start_in_bound": float(summary.get("selected_ts_min", -1))
        >= args.expected_start_ts,
        "selected_end_in_bound": float(summary.get("selected_ts_max", float("inf")))
        < args.expected_end_ts,
        "positive_input_rows": int(summary.get("input_rows", 0)) > 0,
        "positive_transition_rows": int(summary.get("transition_count", 0)) > 0,
        "positive_micro_event_rows": int(
            summary.get("primary_micro_event_count", 0)
        )
        > 0,
    }

    unique_path = output_dir / "n_frontend1_unique_observations.parquet"
    non_route_path = output_dir / "n_frontend1_non_route_observations.parquet"
    transition_path = output_dir / "n_frontend1_transitions.parquet"
    micro_event_path = output_dir / "n_frontend1_micro_events.parquet"
    checks.update(
        {
            "unique_parquet_count_matches": parquet_rows(unique_path)
            == int(summary["exact_unique_observation_count"]),
            "non_route_parquet_count_matches": parquet_rows(non_route_path)
            == int(summary["non_route_observation_count"]),
            "transition_parquet_count_matches": parquet_rows(transition_path)
            == int(summary["transition_count"]),
            "micro_event_parquet_count_matches": parquet_rows(micro_event_path)
            == int(summary["primary_micro_event_count"]),
        }
    )

    validation: dict[str, Any] = {
        "phase": "N-FRONTEND-1B",
        "validation_passed": all(checks.values()),
        "checks": checks,
        "expected_collectors": expected_collectors,
        "input_rows": summary["input_rows"],
        "selected_rows_by_collector": summary["selected_rows_by_collector"],
        "per_collector_cap_expected": args.expect_per_collector_cap,
        "per_collector_cap_observed": summary[
            "selection_truncated_by_per_collector_cap"
        ],
        "non_route_observation_count": summary["non_route_observation_count"],
        "exact_unique_observation_count": summary[
            "exact_unique_observation_count"
        ],
        "transition_count": summary["transition_count"],
        "primary_micro_event_count": summary["primary_micro_event_count"],
        "raw_to_primary_micro_event_compression_ratio": summary[
            "raw_to_primary_micro_event_compression_ratio"
        ],
        "same_timestamp_ambiguous_batch_count": summary[
            "same_timestamp_ambiguous_batch_count"
        ],
        "add_path_support_ready": summary["add_path_support_ready"],
        "claim_boundary": (
            "bounded causal engineering replay; no suppression, attack retention, "
            "or full-window scalability claim"
        ),
    }
    output = Path(args.output)
    output.write_text(
        json.dumps(validation, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(validation, indent=2, sort_keys=True))
    if not validation["validation_passed"]:
        raise SystemExit("N-FRONTEND-1B validation failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
