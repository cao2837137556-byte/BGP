#!/usr/bin/env python3
"""Validate complete R-ATTACK-0B full-window replay artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


EXPECTED_RAW_FILES = 144


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--materialization-summary", required=True)
    parser.add_argument("--event-summary", required=True)
    parser.add_argument("--candidate-summary", required=True)
    parser.add_argument("--raw-truth", required=True)
    parser.add_argument("--rpki-summary", required=True)
    parser.add_argument("--asrel-summary", required=True)
    parser.add_argument("--community-summary", required=True)
    parser.add_argument("--qa-summary", required=True)
    parser.add_argument("--foreground-summary", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def read_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> None:
    args = parse_args()
    materialization = read_json(args.materialization_summary)
    events = read_json(args.event_summary)
    candidates = read_json(args.candidate_summary)
    rpki = read_json(args.rpki_summary)
    asrel = read_json(args.asrel_summary)
    community = read_json(args.community_summary)
    qa = read_json(args.qa_summary)
    foreground = read_json(args.foreground_summary)
    truth = pd.read_parquet(args.raw_truth)
    truth_rows = int(len(truth))
    expected_rows = int(materialization.get("derived_raw_rows", -1))

    checks = {
        "source_raw_files_144": materialization.get("source_raw_chunks") == EXPECTED_RAW_FILES,
        "event_input_rows_match_derived": events.get("total_records") == expected_rows,
        "event_input_files_144": len(events.get("input_files", [])) == EXPECTED_RAW_FILES,
        "event_rows_positive": int(events.get("total_events", 0)) > 0,
        "candidate_rows_equal_events": candidates.get("total_events") == events.get("total_events"),
        "rpki_rows_equal_events": rpki.get("event_sidecar_rows") == events.get("total_events"),
        "rpki_candidate_join_1": rpki.get("candidate_sidecar_join_rate") == 1.0,
        "asrel_rows_equal_events": asrel.get("sidecar_rows") == events.get("total_events"),
        "asrel_event_join_1": asrel.get("event_join_rate") == 1.0,
        "community_rows_equal_events": community.get("event_sidecar_rows") == events.get("total_events"),
        "community_source_files_144": community.get("source_files_expected") == EXPECTED_RAW_FILES
        and community.get("source_files_ok") == EXPECTED_RAW_FILES,
        "qa_pass": qa.get("qa_pass") is True,
        "qa_attack_subtypes_present": len(qa.get("attack_subtype_counts", {})) >= 4,
        "foreground_online_pass": foreground.get("online_pass") is True,
        "foreground_attack_retention_1": foreground.get("attack_retention") == 1.0,
        "foreground_suppressed_attack_0": foreground.get("suppressed_attack_count") == 0,
        "truth_rows_match_materialization": truth_rows == materialization.get("injected_raw_rows"),
        "no_learning": qa.get("training_ready") is False,
    }
    failed = [name for name, passed in checks.items() if not passed]
    summary = {
        "phase": "R-ATTACK-0B",
        "validated": not failed,
        "check_count": len(checks),
        "pass_count": int(sum(bool(value) for value in checks.values())),
        "failed_checks": failed,
        "checks": checks,
        "truth_rows": truth_rows,
        "event_rows": events.get("total_events"),
        "candidate_rows": candidates.get("total_events"),
        "attack_subtype_counts": qa.get("attack_subtype_counts", {}),
        "foreground_attack_retention": foreground.get("attack_retention"),
        "foreground_suppressed_attack_count": foreground.get("suppressed_attack_count"),
        "foreground_background_suppression_rate": foreground.get(
            "pure_reference_background_suppression_rate"
        ),
        "foreground_compression_ratio": foreground.get("estimated_compression_ratio"),
        "allowed_claim": (
            "R-ATTACK-0B multi-attack controlled replay and foreground retention "
            "were validated for this smoke if validated=true."
        ),
        "forbidden_claims": [
            "Do not claim final multi-attack benchmark coverage",
            "Do not claim route-leak confirmation from AS-rel diagnostics",
            "Do not claim hard negatives are benign",
            "Do not claim NO_EXPORT/stealth/poisoning robustness",
            "Do not claim learning performance",
        ],
        "recommended_next_step": (
            "analyze per-family foreground retention and decide whether foreground v2 is needed"
            if not failed
            else "repair failed R-ATTACK-0B artifact checks"
        ),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    raise SystemExit(0 if summary["validated"] else 3)


if __name__ == "__main__":
    main()
