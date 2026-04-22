import argparse
import json
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from gate_scored_candidates import (
    DEFAULT_RUN_ID,
    calc_certainty_score,
    calc_conflict_score,
    ensure_columns,
    gate_label,
    infer_run_id,
    parse_reason_list,
    str2bool,
    to_rel_path,
)


BURST_REASONS = {
    "cross_collector_prefix_origin_burst",
    "single_collector_visibility",
}


OUTPUT_COLS = [
    "event_id",
    "run_id",
    "prefix",
    "origin_as",
    "as_path_clean",
    "risk_score",
    "risk_bucket",
    "structural_novelty_score",
    "weak_signal_score",
    "history_rarity_score",
    "path_consistency_score",
    "top_contributing_factor",
    "matched_rule_count",
    "missing_origin_or_path",
    "certainty_score",
    "conflict_score",
    "gating_label",
    "gating_explanation",
    "promoted_from_low",
    "demoted_from_high",
    "candidate_reasons",
    "path_seen_before",
    "origin_burst_event_count",
    "origin_burst_prefix_count",
]


def normalize_origin_key(value):
    if value is None or pd.isna(value):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value).strip()
    if numeric.is_integer():
        return int(numeric)
    return numeric


def iter_score_batches(scores_path: Path, batch_size: int, columns: list[str] | None = None):
    parquet_file = pq.ParquetFile(scores_path)
    for batch in parquet_file.iter_batches(batch_size=batch_size, columns=columns):
        yield ensure_columns(batch.to_pandas())


def build_burst_origin_stats(scores_path: Path, batch_size: int) -> dict:
    stats = {}
    columns = ["origin_as", "prefix", "candidate_reasons"]
    for batch_df in iter_score_batches(scores_path, batch_size, columns=columns):
        if batch_df.empty:
            continue
        for row in batch_df.itertuples(index=False):
            reasons = set(parse_reason_list(row.candidate_reasons))
            if not BURST_REASONS.issubset(reasons):
                continue
            origin_key = normalize_origin_key(row.origin_as)
            item = stats.get(origin_key)
            if item is None:
                item = {"event_count": 0, "prefixes": set()}
                stats[origin_key] = item
            item["event_count"] += 1
            item["prefixes"].add(str(row.prefix))

    finalized = {}
    for origin_key, item in stats.items():
        finalized[origin_key] = {
            "origin_burst_event_count": float(item["event_count"]),
            "origin_burst_prefix_count": float(len(item["prefixes"])),
        }
    return finalized


def evaluate_record(record: dict, burst_stats: dict) -> dict:
    origin_key = normalize_origin_key(record.get("origin_as"))
    burst = burst_stats.get(
        origin_key,
        {
            "origin_burst_event_count": 0.0,
            "origin_burst_prefix_count": 0.0,
        },
    )
    record["origin_burst_event_count"] = float(burst["origin_burst_event_count"])
    record["origin_burst_prefix_count"] = float(burst["origin_burst_prefix_count"])

    reasons = parse_reason_list(record.get("candidate_reasons", "[]"))
    certainty, certainty_detail = calc_certainty_score(record, reasons)
    conflict, conflict_flags = calc_conflict_score(record, reasons)
    label, promoted, demoted, label_note = gate_label(record, reasons, certainty, conflict)

    explanation = {
        "label_note": label_note,
        "certainty_score": round(certainty, 4),
        "conflict_score": round(conflict, 4),
        "certainty_detail": certainty_detail,
        "conflict_flags": conflict_flags,
        "reasons": reasons,
    }
    return {
        "event_id": record.get("event_id", ""),
        "run_id": record.get("run_id", ""),
        "prefix": record.get("prefix", ""),
        "origin_as": record.get("origin_as"),
        "as_path_clean": record.get("as_path_clean", ""),
        "risk_score": float(record.get("risk_score", 0.0) or 0.0),
        "risk_bucket": record.get("risk_bucket", "low"),
        "structural_novelty_score": float(record.get("structural_novelty_score", 0.0) or 0.0),
        "weak_signal_score": float(record.get("weak_signal_score", 0.0) or 0.0),
        "history_rarity_score": float(record.get("history_rarity_score", 0.0) or 0.0),
        "path_consistency_score": float(record.get("path_consistency_score", 0.0) or 0.0),
        "top_contributing_factor": record.get("top_contributing_factor", ""),
        "matched_rule_count": float(record.get("matched_rule_count", 0.0) or 0.0),
        "missing_origin_or_path": bool(record.get("missing_origin_or_path", False)),
        "certainty_score": round(certainty, 4),
        "conflict_score": round(conflict, 4),
        "gating_label": label,
        "gating_explanation": json.dumps(explanation, ensure_ascii=False),
        "promoted_from_low": bool(promoted),
        "demoted_from_high": bool(demoted),
        "candidate_reasons": record.get("candidate_reasons", "[]"),
        "path_seen_before": bool(record.get("path_seen_before", False)),
        "origin_burst_event_count": float(record["origin_burst_event_count"]),
        "origin_burst_prefix_count": float(record["origin_burst_prefix_count"]),
    }


def append_sample(samples: list[dict], row: dict, limit: int = 10):
    if len(samples) < limit:
        samples.append(row)


def print_samples(samples: list[dict], title: str):
    print(f"{title}:")
    if not samples:
        print("  <empty>")
        return
    sample_cols = [
        "event_id",
        "prefix",
        "origin_as",
        "as_path_clean",
        "risk_score",
        "risk_bucket",
        "certainty_score",
        "conflict_score",
        "gating_label",
        "gating_explanation",
    ]
    for row in samples:
        print("  - " + json.dumps({k: row.get(k) for k in sample_cols}, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description="Streaming gating for large scored candidate pools.")
    ap.add_argument("--run-id", default=DEFAULT_RUN_ID, help="Run id under data/runs/<run_id>.")
    ap.add_argument("--scores", default=None, help="Path to scored_candidates.parquet.")
    ap.add_argument("--output-dir", default=None, help="Output directory for gating files.")
    ap.add_argument("--overwrite", type=str2bool, default=False, help="Overwrite existing outputs.")
    ap.add_argument("--batch-size", type=int, default=100000, help="Parquet batch size.")
    args = ap.parse_args()

    if args.batch_size <= 0:
        raise SystemExit("--batch-size must be > 0")

    if args.scores:
        scores_path = Path(args.scores)
        run_id = args.run_id or infer_run_id(scores_path) or DEFAULT_RUN_ID
    else:
        run_id = args.run_id or DEFAULT_RUN_ID
        scores_path = Path("data") / "runs" / run_id / "scores" / "scored_candidates.parquet"

    if not scores_path.exists():
        raise SystemExit(f"scores file not found: {scores_path}")

    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = Path("data") / "runs" / run_id / "gating"
    output_dir.mkdir(parents=True, exist_ok=True)

    out_gated = output_dir / "gated_candidates.parquet"
    out_summary = output_dir / "gating_summary.json"
    temp_gated = output_dir / "gated_candidates_tmp.parquet"
    if not args.overwrite:
        exists = [p for p in [out_gated, out_summary] if p.exists()]
        if exists:
            raise SystemExit(
                "Output exists, pass --overwrite true to replace: " + ", ".join(to_rel_path(p) for p in exists)
            )
    for path in [out_gated, out_summary, temp_gated]:
        if path.exists():
            path.unlink()

    burst_stats = build_burst_origin_stats(scores_path, args.batch_size)

    input_rows = 0
    label_counts = {}
    missing_count = 0
    promoted_count = 0
    demoted_count = 0
    certainty_total = 0.0
    conflict_total = 0.0
    malicious_top_factor = {}

    likely_samples = []
    uncertain_samples = []
    benign_samples = []
    demoted_samples = []
    promoted_samples = []

    writer = None
    try:
        for batch_df in iter_score_batches(scores_path, args.batch_size):
            input_rows += int(len(batch_df))
            if batch_df.empty:
                continue

            output_rows = []
            for row in batch_df.itertuples(index=False):
                record = row._asdict()
                out = evaluate_record(record, burst_stats)
                output_rows.append(out)

                label = str(out["gating_label"])
                label_counts[label] = int(label_counts.get(label, 0)) + 1
                certainty_total += float(out["certainty_score"])
                conflict_total += float(out["conflict_score"])
                missing_count += int(bool(out["missing_origin_or_path"]))
                promoted_count += int(bool(out["promoted_from_low"]))
                demoted_count += int(bool(out["demoted_from_high"]))
                if label == "likely_malicious":
                    top_factor = str(out["top_contributing_factor"])
                    malicious_top_factor[top_factor] = int(malicious_top_factor.get(top_factor, 0)) + 1
                    append_sample(likely_samples, out)
                elif label == "suspicious_but_uncertain":
                    append_sample(uncertain_samples, out)
                else:
                    append_sample(benign_samples, out)
                if out["demoted_from_high"]:
                    append_sample(demoted_samples, out, limit=5)
                if out["promoted_from_low"]:
                    append_sample(promoted_samples, out, limit=5)

            out_df = pd.DataFrame(output_rows, columns=OUTPUT_COLS)
            table = pa.Table.from_pandas(out_df, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(temp_gated, table.schema)
            writer.write_table(table)
    finally:
        if writer is not None:
            writer.close()

    if not temp_gated.exists():
        raise SystemExit("No gating outputs were written.")

    temp_gated.replace(out_gated)

    likely_malicious_count = int(label_counts.get("likely_malicious", 0))
    uncertain_count = int(label_counts.get("suspicious_but_uncertain", 0))
    benign_count = int(label_counts.get("likely_benign", 0))
    avg_certainty = float(certainty_total / input_rows) if input_rows else 0.0
    avg_conflict = float(conflict_total / input_rows) if input_rows else 0.0

    summary = {
        "run_id": run_id,
        "scores_path": to_rel_path(scores_path),
        "output_gated_path": to_rel_path(out_gated),
        "output_summary_path": to_rel_path(out_summary),
        "input_rows": int(input_rows),
        "label_counts": {str(k): int(v) for k, v in label_counts.items()},
        "likely_malicious_count": likely_malicious_count,
        "suspicious_but_uncertain_count": uncertain_count,
        "likely_benign_count": benign_count,
        "avg_certainty_score": avg_certainty,
        "avg_conflict_score": avg_conflict,
        "missing_origin_or_path_count": int(missing_count),
        "promoted_from_low_count": int(promoted_count),
        "demoted_from_high_count": int(demoted_count),
        "likely_malicious_top_contributing_factor": {str(k): int(v) for k, v in malicious_top_factor.items()},
    }
    out_summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"run_id: {run_id}")
    print(f"input_scores: {to_rel_path(scores_path)}")
    print(f"input_rows: {input_rows}")
    print(f"likely_malicious: {likely_malicious_count}")
    print(f"suspicious_but_uncertain: {uncertain_count}")
    print(f"likely_benign: {benign_count}")
    print(f"avg_certainty_score: {avg_certainty:.4f}")
    print(f"avg_conflict_score: {avg_conflict:.4f}")
    print(f"missing_origin_or_path: {missing_count}")
    print(f"output_gated_path: {to_rel_path(out_gated)}")
    print(f"output_summary_path: {to_rel_path(out_summary)}")

    print_samples(likely_samples, "likely_malicious_samples")
    print_samples(uncertain_samples, "suspicious_but_uncertain_samples")
    print_samples(benign_samples, "likely_benign_samples")
    print_samples(demoted_samples, "demoted_from_high_samples")
    print_samples(promoted_samples, "promoted_from_low_samples")


if __name__ == "__main__":
    main()
