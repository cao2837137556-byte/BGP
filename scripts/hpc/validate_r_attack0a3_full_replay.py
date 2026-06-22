import argparse
import json
from pathlib import Path

import pandas as pd


EXPECTED_RAW_ROWS = 7_200_096
EXPECTED_RAW_FILES = 144
EXPECTED_TRUTH_ROWS = 96


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate complete R-ATTACK-0A-3 full-window artifacts."
    )
    parser.add_argument("--materialization-summary", required=True)
    parser.add_argument("--event-summary", required=True)
    parser.add_argument("--candidate-summary", required=True)
    parser.add_argument("--raw-truth", required=True)
    parser.add_argument("--rpki-summary", required=True)
    parser.add_argument("--asrel-summary", required=True)
    parser.add_argument("--community-summary", required=True)
    parser.add_argument("--qa-summary", required=True)
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
    truth_rows = len(pd.read_parquet(args.raw_truth, columns=["raw_record_id"]))

    checks = {
        "source_raw_files_144": materialization.get("source_raw_chunks")
        == EXPECTED_RAW_FILES,
        "derived_raw_rows_exact": materialization.get("derived_raw_rows")
        == EXPECTED_RAW_ROWS,
        "truth_rows_exact": truth_rows == EXPECTED_TRUTH_ROWS,
        "event_input_rows_exact": events.get("total_records") == EXPECTED_RAW_ROWS,
        "event_input_files_144": len(events.get("input_files", []))
        == EXPECTED_RAW_FILES,
        "event_rows_positive": int(events.get("total_events", 0)) > 0,
        "candidate_rows_equal_events": candidates.get("total_events")
        == events.get("total_events"),
        "rpki_rows_equal_events": rpki.get("event_sidecar_rows")
        == events.get("total_events"),
        "rpki_candidate_join_1": rpki.get("candidate_sidecar_join_rate") == 1.0,
        "asrel_rows_equal_events": asrel.get("sidecar_rows")
        == events.get("total_events"),
        "asrel_event_join_1": asrel.get("event_join_rate") == 1.0,
        "community_rows_equal_events": community.get("event_sidecar_rows")
        == events.get("total_events"),
        "community_event_join_1": community.get("event_raw_match_rate") == 1.0,
        "community_source_files_144": community.get("source_files_expected")
        == EXPECTED_RAW_FILES
        and community.get("source_files_ok") == EXPECTED_RAW_FILES,
        "qa_pass": qa.get("qa_pass") is True,
        "qa_attack_retention_1": qa.get("candidate_attack_retention_rate") == 1.0,
        "no_learning": qa.get("training_ready") is False,
    }
    failed = [name for name, passed in checks.items() if not passed]
    summary = {
        "phase": "R-ATTACK-0A-3",
        "validated": not failed,
        "check_count": len(checks),
        "pass_count": sum(checks.values()),
        "failed_checks": failed,
        "checks": checks,
        "event_rows": events.get("total_events"),
        "candidate_rows": candidates.get("total_events"),
        "candidate_attack_retention_rate": qa.get(
            "candidate_attack_retention_rate"
        ),
        "hard_negative_candidate_event_rate": qa.get(
            "hard_negative_candidate_event_rate"
        ),
        "allowed_claim": (
            "The complete controlled full-window replay and its artifact joins passed."
        ),
        "forbidden_claims": [
            "Do not claim final low false positives",
            "Do not claim hard negatives are confirmed benign",
            "Do not claim poisoning or evasion robustness",
            "Do not claim learning performance",
        ],
        "recommended_next_step": (
            "R-NOISE-CLEAN-1 design using the validated full-window benchmark"
            if not failed
            else "repair failed full-window artifact checks"
        ),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    raise SystemExit(0 if summary["validated"] else 3)


if __name__ == "__main__":
    main()
