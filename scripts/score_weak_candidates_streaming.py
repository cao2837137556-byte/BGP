import argparse
import json
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from score_weak_candidates import (
    CONTEXTUAL_REASONS,
    DEFAULT_RUN_ID,
    SCORE_WEIGHTS,
    STRUCTURAL_REASONS,
    WEAK_REASONS,
    calc_history_rarity_score,
    calc_path_consistency_score,
    calc_structural_novelty_score,
    calc_weak_signal_score,
    coalesce_numeric,
    derive_bucket_thresholds,
    ensure_baseline_path,
    ensure_baseline_prefix,
    ensure_baseline_prefix_origin,
    ensure_candidate_columns,
    infer_run_id,
    parse_reason_list,
    risk_bucket,
    safe_num,
    str2bool,
    to_rel_path,
)


def build_prefix_map(df: pd.DataFrame) -> dict[str, float]:
    return {str(row.prefix): float(row.total_events) for row in df.itertuples(index=False)}


def build_prefix_origin_map(df: pd.DataFrame) -> dict[tuple[str, float], dict]:
    out = {}
    for row in df.itertuples(index=False):
        key = (str(row.prefix), float(row.origin_as_num) if not pd.isna(row.origin_as_num) else float("nan"))
        out[key] = {
            "bl_po_total_events": float(row.total_events),
            "bl_po_unique_paths": float(row.unique_paths),
            "po_avg_path_len": float(row.avg_path_len),
            "po_median_path_len": float(row.median_path_len),
        }
    return out


def build_path_map(df: pd.DataFrame) -> dict[tuple[str, float, str], float]:
    out = {}
    for row in df.itertuples(index=False):
        key = (
            str(row.prefix),
            float(row.origin_as_num) if not pd.isna(row.origin_as_num) else float("nan"),
            str(row.as_path_clean),
        )
        out[key] = float(row.total_events)
    return out


def iter_candidate_batches(candidates_path: Path, batch_size: int):
    parquet_file = pq.ParquetFile(candidates_path)
    for batch in parquet_file.iter_batches(batch_size=batch_size):
        yield ensure_candidate_columns(batch.to_pandas())


def top_contributing_factor(contrib: dict) -> str:
    if not contrib:
        return "none"
    return max(contrib.items(), key=lambda item: item[1])[0]


def score_record(record: dict) -> dict:
    reasons = parse_reason_list(record.get("candidate_reasons", "[]"))
    structural_score, structural_hits = calc_structural_novelty_score(reasons)
    weak_score, weak_hits, contextual_hits = calc_weak_signal_score(reasons)

    origin_missing = pd.isna(record.get("origin_as_num"))
    path_clean = str(record.get("as_path_clean", "") or "").strip()
    path_missing = path_clean == ""
    missing_origin_or_path = bool(origin_missing or path_missing)

    as_path_len = safe_num(record.get("as_path_len"), 0.0)
    path_len_inconsistent = bool((path_missing and as_path_len > 0) or ((not path_missing) and as_path_len <= 0))

    prefix_total = safe_num(record.get("prefix_total_events"), 0.0)
    po_total = safe_num(record.get("po_total_events"), 0.0)
    path_total = safe_num(record.get("path_total_events"), 0.0)
    path_seen_before = bool(record.get("path_seen_before", False))
    po_avg_path_len = safe_num(record.get("po_avg_path_len"), 0.0)
    po_median_path_len = safe_num(record.get("po_median_path_len"), 0.0)
    po_unique_paths = safe_num(record.get("po_unique_paths"), 0.0)

    history_score = calc_history_rarity_score(path_seen_before, prefix_total, po_total, path_total)
    path_score, path_detail = calc_path_consistency_score(
        as_path_len=as_path_len,
        po_avg_path_len=po_avg_path_len,
        po_median_path_len=po_median_path_len,
        po_unique_paths=po_unique_paths,
        path_seen_before=path_seen_before,
        missing_origin_or_path=missing_origin_or_path,
    )

    component_scores = {
        "structural_novelty_score": structural_score,
        "weak_signal_score": weak_score,
        "history_rarity_score": history_score,
        "path_consistency_score": path_score,
    }
    contributions = {key: component_scores[key] * SCORE_WEIGHTS[key] for key in component_scores}
    risk_score_val = sum(contributions.values())
    if missing_origin_or_path:
        risk_score_val = risk_score_val * 0.92
    risk_score_val = round(min(100.0, max(0.0, risk_score_val)), 4)

    notes = []
    if missing_origin_or_path:
        notes.append("missing_origin_or_path")
    if path_len_inconsistent:
        notes.append("path_length_inconsistent")

    explanation = {
        "structural_reasons": structural_hits,
        "weak_reasons": weak_hits,
        "contextual_reasons": contextual_hits,
        "component_scores": {key: round(value, 4) for key, value in component_scores.items()},
        "weighted_contributions": {key: round(value, 4) for key, value in contributions.items()},
        "path_consistency_detail": path_detail,
        "missing_origin_or_path": missing_origin_or_path,
        "notes": notes,
    }
    return {
        "structural_novelty_score": round(structural_score, 4),
        "weak_signal_score": round(weak_score, 4),
        "history_rarity_score": round(history_score, 4),
        "path_consistency_score": round(path_score, 4),
        "risk_score": risk_score_val,
        "top_contributing_factor": top_contributing_factor(contributions),
        "missing_origin_or_path": missing_origin_or_path,
        "score_explanation": json.dumps(explanation, ensure_ascii=False),
    }


def print_samples(samples: list[dict], title: str):
    print(f"{title}:")
    if not samples:
        print("  <empty>")
        return
    for row in samples[:10]:
        print("  - " + json.dumps(row, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description="Streaming scorer for large candidate pools.")
    ap.add_argument("--run-id", default=DEFAULT_RUN_ID)
    ap.add_argument("--candidates", default=None)
    ap.add_argument("--baseline-prefix", default=None)
    ap.add_argument("--baseline-prefix-origin", default=None)
    ap.add_argument("--baseline-path", default=None)
    ap.add_argument("--output-dir", default=None)
    ap.add_argument("--overwrite", type=str2bool, default=False)
    ap.add_argument("--batch-size", type=int, default=100000)
    args = ap.parse_args()

    if args.batch_size <= 0:
        raise SystemExit("--batch-size must be > 0")

    if args.candidates:
        candidates_path = Path(args.candidates)
        run_id = args.run_id or infer_run_id(candidates_path) or DEFAULT_RUN_ID
    else:
        run_id = args.run_id or DEFAULT_RUN_ID
        candidates_path = Path("data") / "runs" / run_id / "candidates" / "candidate_events.parquet"
    if not candidates_path.exists():
        raise SystemExit(f"candidate file not found: {candidates_path}")

    baseline_root = Path("data") / "runs" / run_id / "baseline"
    baseline_prefix_path = Path(args.baseline_prefix) if args.baseline_prefix else baseline_root / "baseline_prefix.parquet"
    baseline_po_path = Path(args.baseline_prefix_origin) if args.baseline_prefix_origin else baseline_root / "baseline_prefix_origin.parquet"
    baseline_path_path = Path(args.baseline_path) if args.baseline_path else baseline_root / "baseline_path.parquet"
    for path in [baseline_prefix_path, baseline_po_path, baseline_path_path]:
        if not path.exists():
            raise SystemExit(f"baseline file not found: {path}")

    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = Path("data") / "runs" / run_id / "scores"
    output_dir.mkdir(parents=True, exist_ok=True)

    out_scored = output_dir / "scored_candidates.parquet"
    out_summary = output_dir / "score_summary.json"
    temp_scored = output_dir / "scored_candidates_tmp.parquet"
    if not args.overwrite:
        exists = [path for path in [out_scored, out_summary] if path.exists()]
        if exists:
            raise SystemExit("Output exists, pass --overwrite true to replace: " + ", ".join(to_rel_path(path) for path in exists))
    for path in [out_scored, out_summary, temp_scored]:
        if path.exists():
            path.unlink()

    baseline_prefix = ensure_baseline_prefix(pd.read_parquet(baseline_prefix_path))
    baseline_po = ensure_baseline_prefix_origin(pd.read_parquet(baseline_po_path))
    baseline_path_df = ensure_baseline_path(pd.read_parquet(baseline_path_path))
    prefix_map = build_prefix_map(baseline_prefix)
    po_map = build_prefix_origin_map(baseline_po)
    path_map = build_path_map(baseline_path_df)

    risk_scores: list[float] = []
    temp_writer = None
    input_rows = 0
    input_candidate_rows = 0
    top_factor_counts: dict[str, int] = {}
    missing_count = 0

    base_cols = [
        "event_id",
        "run_id",
        "prefix",
        "origin_as",
        "as_path_clean",
        "as_path_len",
        "duration_sec",
        "record_count",
        "collector_set",
        "collector_count",
        "visibility_count",
        "candidate_flag",
        "candidate_reasons",
        "matched_rule_count",
        "prefix_total_events",
        "po_total_events",
        "po_unique_paths",
        "po_collector_support",
        "po_time_span_sec",
        "path_total_events",
        "path_seen_before",
    ]

    try:
        for batch_df in iter_candidate_batches(candidates_path, args.batch_size):
            input_rows += int(len(batch_df))
            if "candidate_flag" in batch_df.columns:
                batch_df = batch_df[batch_df["candidate_flag"]].copy()
            if batch_df.empty:
                continue
            input_candidate_rows += int(len(batch_df))

            output_rows = []
            for row in batch_df.itertuples(index=False):
                origin_key = float(row.origin_as_num) if not pd.isna(row.origin_as_num) else float("nan")
                prefix_total = coalesce_numeric(pd.Series([row.prefix_total_events]), pd.Series([prefix_map.get(str(row.prefix))])).iloc[0]
                po_info = po_map.get((str(row.prefix), origin_key), {})
                path_total = path_map.get((str(row.prefix), origin_key, str(row.as_path_clean)))

                record = {
                    "origin_as_num": origin_key,
                    "as_path_clean": row.as_path_clean,
                    "as_path_len": row.as_path_len,
                    "prefix_total_events": prefix_total,
                    "po_total_events": coalesce_numeric(pd.Series([row.po_total_events]), pd.Series([po_info.get("bl_po_total_events")])).iloc[0],
                    "po_unique_paths": coalesce_numeric(pd.Series([row.po_unique_paths]), pd.Series([po_info.get("bl_po_unique_paths")])).iloc[0],
                    "po_avg_path_len": po_info.get("po_avg_path_len"),
                    "po_median_path_len": po_info.get("po_median_path_len"),
                    "path_total_events": coalesce_numeric(pd.Series([row.path_total_events]), pd.Series([path_total])).iloc[0],
                    "path_seen_before": bool(row.path_seen_before) if not pd.isna(row.path_seen_before) else bool(path_total and path_total > 0),
                    "candidate_reasons": row.candidate_reasons,
                }
                scored = score_record(record)
                risk_scores.append(float(scored["risk_score"]))
                top_factor_counts[scored["top_contributing_factor"]] = top_factor_counts.get(scored["top_contributing_factor"], 0) + 1
                if scored["missing_origin_or_path"]:
                    missing_count += 1

                output_rows.append(
                    {
                        "event_id": row.event_id,
                        "run_id": row.run_id,
                        "prefix": row.prefix,
                        "origin_as": row.origin_as,
                        "as_path_clean": row.as_path_clean,
                        "as_path_len": row.as_path_len,
                        "duration_sec": row.duration_sec,
                        "record_count": row.record_count,
                        "collector_set": row.collector_set,
                        "collector_count": row.collector_count,
                        "visibility_count": row.visibility_count,
                        "candidate_reasons": row.candidate_reasons,
                        "matched_rule_count": row.matched_rule_count,
                        "structural_novelty_score": scored["structural_novelty_score"],
                        "weak_signal_score": scored["weak_signal_score"],
                        "history_rarity_score": scored["history_rarity_score"],
                        "path_consistency_score": scored["path_consistency_score"],
                        "risk_score": scored["risk_score"],
                        "top_contributing_factor": scored["top_contributing_factor"],
                        "missing_origin_or_path": scored["missing_origin_or_path"],
                        "path_seen_before": record["path_seen_before"],
                        "path_total_events": record["path_total_events"],
                        "po_total_events": record["po_total_events"],
                        "po_collector_support": row.po_collector_support,
                        "po_time_span_sec": row.po_time_span_sec,
                        "prefix_total_events": record["prefix_total_events"],
                        "score_explanation": scored["score_explanation"],
                    }
                )

            table = pa.Table.from_pandas(pd.DataFrame(output_rows), preserve_index=False)
            if temp_writer is None:
                temp_writer = pq.ParquetWriter(temp_scored, table.schema)
            temp_writer.write_table(table)
    finally:
        if temp_writer is not None:
            temp_writer.close()

    thresholds = derive_bucket_thresholds(pd.Series(risk_scores))
    bucket_counts: dict[str, int] = {}
    high_samples: list[dict] = []
    medium_samples: list[dict] = []
    low_samples: list[dict] = []
    missing_samples: list[dict] = []
    final_writer = None
    try:
        parquet_file = pq.ParquetFile(temp_scored)
        for batch in parquet_file.iter_batches(batch_size=args.batch_size):
            batch_df = batch.to_pandas()
            batch_df["risk_bucket"] = batch_df["risk_score"].apply(lambda value: risk_bucket(safe_num(value, 0.0), thresholds))
            for bucket_name, count in batch_df["risk_bucket"].value_counts().to_dict().items():
                bucket_counts[str(bucket_name)] = bucket_counts.get(str(bucket_name), 0) + int(count)

            ordered_cols = base_cols[:18] + ["risk_bucket"] + base_cols[18:]
            final_df = batch_df[ordered_cols]
            table = pa.Table.from_pandas(final_df, preserve_index=False)
            if final_writer is None:
                final_writer = pq.ParquetWriter(out_scored, table.schema)
            final_writer.write_table(table)

            for row in final_df.to_dict("records"):
                if row["risk_bucket"] == "high" and len(high_samples) < 10:
                    high_samples.append(row)
                if row["risk_bucket"] == "medium" and len(medium_samples) < 10:
                    medium_samples.append(row)
                if row["risk_bucket"] == "low" and len(low_samples) < 10:
                    low_samples.append(row)
                if row["missing_origin_or_path"] and len(missing_samples) < 5:
                    missing_samples.append(row)
    finally:
        if final_writer is not None:
            final_writer.close()
    if temp_scored.exists():
        temp_scored.unlink()

    summary = {
        "run_id": run_id,
        "candidates_path": to_rel_path(candidates_path),
        "baseline_prefix_path": to_rel_path(baseline_prefix_path),
        "baseline_prefix_origin_path": to_rel_path(baseline_po_path),
        "baseline_path_path": to_rel_path(baseline_path_path),
        "output_scored_path": to_rel_path(out_scored),
        "output_summary_path": to_rel_path(out_summary),
        "input_rows": int(input_rows),
        "input_candidate_rows": int(input_candidate_rows),
        "output_rows": int(input_candidate_rows),
        "avg_risk_score": float(pd.Series(risk_scores).mean()) if risk_scores else 0.0,
        "bucket_counts": {str(key): int(value) for key, value in bucket_counts.items()},
        "top_contributing_factor_counts": {str(key): int(value) for key, value in top_factor_counts.items()},
        "missing_origin_or_path_count": int(missing_count),
        "risk_bucket_thresholds": thresholds,
        "score_weights": SCORE_WEIGHTS,
        "structural_reasons": sorted(STRUCTURAL_REASONS),
        "weak_reasons": sorted(WEAK_REASONS),
        "contextual_reasons": sorted(CONTEXTUAL_REASONS),
    }
    out_summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"run_id: {run_id}")
    print(f"input_candidates_path: {to_rel_path(candidates_path)}")
    print(f"input_rows: {input_rows}")
    print(f"input_candidate_rows: {input_candidate_rows}")
    print(f"output_scored_rows: {input_candidate_rows}")
    print(f"avg_risk_score: {summary['avg_risk_score']:.4f}")
    print("bucket_counts:")
    print(json.dumps(summary["bucket_counts"], ensure_ascii=False, indent=2))
    print("top_contributing_factor_counts:")
    print(json.dumps(summary["top_contributing_factor_counts"], ensure_ascii=False, indent=2))
    print(f"missing_origin_or_path_count: {missing_count}")
    print(f"output_scored_path: {to_rel_path(out_scored)}")
    print(f"output_summary_path: {to_rel_path(out_summary)}")
    print_samples(high_samples, "high_risk_samples")
    print_samples(medium_samples, "medium_risk_samples")
    print_samples(low_samples, "low_risk_samples")
    print_samples(missing_samples, "missing_origin_or_path_samples")


if __name__ == "__main__":
    main()
