import argparse
import json
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from build_weak_candidates import (
    CONTEXTUAL_RULES,
    DEFAULT_THRESHOLDS,
    RULE_DESCRIPTIONS,
    STRUCTURAL_RULES,
    WEAK_RULES,
    ensure_baseline_path,
    ensure_baseline_prefix,
    ensure_baseline_prefix_origin,
    ensure_event_columns,
    infer_run_id,
    parse_top_values,
    str2bool,
    to_rel_path,
)


def normalize_origin_label(value) -> str:
    if value is None or pd.isna(value):
        return ""
    try:
        return str(int(float(value)))
    except (TypeError, ValueError):
        return str(value).strip()


def normalize_origin_top_values(raw: str) -> set[str]:
    values = set()
    for item in parse_top_values(raw):
        text = str(item).strip()
        if not text:
            continue
        values.add(text)
        try:
            values.add(str(int(float(text))))
        except (TypeError, ValueError):
            pass
    return values


def build_prefix_map(df: pd.DataFrame) -> dict[str, dict]:
    out = {}
    for row in df.itertuples(index=False):
        out[str(row.prefix)] = {
            "prefix_total_events": float(row.total_events),
            "prefix_unique_origins": float(row.unique_origins),
            "prefix_top_origins_set": normalize_origin_top_values(row.top_origins),
            "prefix_avg_duration_sec": float(row.avg_duration_sec),
            "prefix_median_duration_sec": float(row.median_duration_sec),
            "prefix_avg_visibility_count": float(row.avg_visibility_count),
            "prefix_median_visibility_count": float(row.median_visibility_count),
        }
    return out


def build_prefix_origin_map(df: pd.DataFrame) -> dict[tuple[str, float], dict]:
    out = {}
    for row in df.itertuples(index=False):
        key = (str(row.prefix), float(row.origin_as_num) if not pd.isna(row.origin_as_num) else float("nan"))
        out[key] = {
            "po_total_events": float(row.total_events),
            "po_unique_paths": float(row.unique_paths),
            "po_top_paths_set": parse_top_values(row.top_paths),
            "po_avg_path_len": float(row.avg_path_len),
            "po_median_path_len": float(row.median_path_len),
            "po_avg_visibility_count": float(row.avg_visibility_count),
        }
    return out


def build_path_map(df: pd.DataFrame) -> dict[tuple[str, float, str], dict]:
    out = {}
    for row in df.itertuples(index=False):
        key = (
            str(row.prefix),
            float(row.origin_as_num) if not pd.isna(row.origin_as_num) else float("nan"),
            str(row.as_path_clean),
        )
        out[key] = {
            "path_total_events": float(row.total_events),
            "path_last_seen_run_id": str(row.last_seen_run_id),
        }
    return out


def iter_event_batches(events_path: Path, columns: list[str], batch_size: int):
    parquet_file = pq.ParquetFile(events_path)
    for batch in parquet_file.iter_batches(batch_size=batch_size, columns=columns):
        yield ensure_event_columns(batch.to_pandas())


def build_po_runtime_stats(events_path: Path, batch_size: int) -> dict[tuple[str, float], dict]:
    stats: dict[tuple[str, float], dict] = {}
    columns = ["prefix", "origin_as", "first_seen", "last_seen", "collector_set"]
    for batch_df in iter_event_batches(events_path, columns, batch_size):
        for row in batch_df.itertuples(index=False):
            origin_key = float(row.origin_as_num) if not pd.isna(row.origin_as_num) else float("nan")
            key = (str(row.prefix), origin_key)
            item = stats.get(key)
            if item is None:
                item = {
                    "po_first_seen": float(row.first_seen),
                    "po_last_seen": float(row.last_seen),
                    "collectors": set(),
                }
                stats[key] = item
            else:
                item["po_first_seen"] = min(item["po_first_seen"], float(row.first_seen))
                item["po_last_seen"] = max(item["po_last_seen"], float(row.last_seen))
            collectors = [token for token in str(row.collector_set).split("|") if token]
            item["collectors"].update(collectors)

    for key, item in stats.items():
        item["po_collector_support"] = float(len(item["collectors"]))
        item["po_time_span_sec"] = float(item["po_last_seen"] - item["po_first_seen"])
        del item["collectors"]
    return stats


def evaluate_rules_from_record(record: dict, min_weak_rules: int, current_run_id: str) -> tuple[bool, list[str], int]:
    reasons = []

    prefix_total_events = float(record.get("prefix_total_events", 0.0) or 0.0)
    prefix_top_origins_set = record.get("prefix_top_origins_set", set())
    origin_label = normalize_origin_label(record.get("origin_as_num"))
    if prefix_total_events <= 0:
        reasons.append("unseen_origin_for_prefix")
    elif origin_label not in prefix_top_origins_set:
        reasons.append("unseen_origin_for_prefix")

    p_avg_vis = float(record.get("prefix_avg_visibility_count", 0.0) or 0.0)
    p_med_vis = float(record.get("prefix_median_visibility_count", 0.0) or 0.0)
    p_vis_ref = max(p_avg_vis, p_med_vis)
    if p_vis_ref >= 1.0:
        low_vis_th = max(1.0, p_vis_ref * DEFAULT_THRESHOLDS["prefix_visibility_ratio"])
        if float(record.get("visibility_count", 0.0) or 0.0) < low_vis_th:
            reasons.append("unusually_low_visibility_for_prefix")

    p_avg_dur = float(record.get("prefix_avg_duration_sec", 0.0) or 0.0)
    p_med_dur = float(record.get("prefix_median_duration_sec", 0.0) or 0.0)
    p_dur_ref = p_med_dur if p_med_dur > 0 else p_avg_dur
    if p_dur_ref > 0:
        short_dur_th = p_dur_ref * DEFAULT_THRESHOLDS["prefix_short_duration_ratio"]
        if float(record.get("duration_sec", 0.0) or 0.0) < short_dur_th:
            reasons.append("unusually_short_duration_for_prefix")

    po_total_events = float(record.get("po_total_events", 0.0) or 0.0)
    if po_total_events <= 0:
        reasons.append("unseen_path_for_prefix_origin")
    elif str(record.get("as_path_clean", "")) not in record.get("po_top_paths_set", set()):
        reasons.append("unseen_path_for_prefix_origin")

    po_med_len = float(record.get("po_median_path_len", 0.0) or 0.0)
    if po_med_len > 0:
        if abs(float(record.get("as_path_len", 0.0) or 0.0) - po_med_len) >= DEFAULT_THRESHOLDS["path_length_delta"]:
            reasons.append("abnormal_path_length_for_prefix_origin")

    po_avg_vis = float(record.get("po_avg_visibility_count", 0.0) or 0.0)
    if po_avg_vis >= 1.0:
        po_low_vis_th = max(1.0, po_avg_vis * DEFAULT_THRESHOLDS["prefix_origin_visibility_ratio"])
        if float(record.get("visibility_count", 0.0) or 0.0) < po_low_vis_th:
            reasons.append("unusually_low_visibility_for_prefix_origin")

    path_seen_before = bool(record.get("path_seen_before", False))
    if not path_seen_before:
        reasons.append("unseen_exact_path")

    path_total_events = float(record.get("path_total_events", 0.0) or 0.0)
    path_last_seen_run = str(record.get("path_last_seen_run_id", "") or "")
    if path_seen_before and path_total_events <= DEFAULT_THRESHOLDS["weak_path_history_max_events"]:
        if path_last_seen_run and path_last_seen_run != current_run_id:
            reasons.append("weak_path_history")

    po_collector_support = float(record.get("po_collector_support", 0.0) or 0.0)
    po_time_span_sec = float(record.get("po_time_span_sec", 0.0) or 0.0)
    if (
        int(float(record.get("collector_count", 0.0) or 0.0)) == 1
        and po_total_events > 0
        and po_total_events <= DEFAULT_THRESHOLDS["po_burst_max_events"]
        and float(record.get("po_unique_paths", 0.0) or 0.0) >= DEFAULT_THRESHOLDS["po_burst_min_unique_paths"]
        and po_collector_support >= DEFAULT_THRESHOLDS["po_burst_min_collectors"]
        and po_time_span_sec <= DEFAULT_THRESHOLDS["po_burst_max_time_span_sec"]
        and path_total_events <= DEFAULT_THRESHOLDS["po_burst_max_path_events"]
    ):
        reasons.append("cross_collector_prefix_origin_burst")

    if int(float(record.get("collector_count", 0.0) or 0.0)) == 1:
        reasons.append("single_collector_visibility")

    rec = float(record.get("record_count", 0.0) or 0.0)
    dur = float(record.get("duration_sec", 0.0) or 0.0)
    wcnt = float(record.get("withdraw_count", 0.0) or 0.0)
    if rec <= DEFAULT_THRESHOLDS["sparse_record_max"] and dur <= DEFAULT_THRESHOLDS["sparse_duration_max_sec"] and wcnt > 0:
        reasons.append("sparse_short_lived_event")

    reason_set = sorted(set(reasons))
    structural_hit_count = sum(1 for r in reason_set if r in STRUCTURAL_RULES)
    weak_hit_count = sum(1 for r in reason_set if r in WEAK_RULES)
    candidate_flag = (structural_hit_count > 0) or (weak_hit_count >= min_weak_rules)
    matched_rule_count = structural_hit_count + weak_hit_count
    return candidate_flag, reason_set, matched_rule_count


def print_samples(samples: list[dict], title: str):
    print(f"{title}:")
    if not samples:
        print("  <empty>")
        return
    for row in samples[:5]:
        reasons = json.loads(row["candidate_reasons"]) if row["candidate_reasons"] else []
        reason_text = "; ".join(f"{r}: {RULE_DESCRIPTIONS.get(r, '')}" for r in reasons) if reasons else "none"
        print(f"  - event_id={row['event_id']} candidate={row['candidate_flag']} reasons={reason_text}")


def main():
    ap = argparse.ArgumentParser(description="Streaming weak anomaly candidate builder for large modern runs.")
    ap.add_argument("--run-id", default=None, help="Run id under data/runs/<run_id>.")
    ap.add_argument("--events", default=None, help="Path to event_units.parquet.")
    ap.add_argument("--baseline-prefix", default=None, help="Path to baseline_prefix.parquet.")
    ap.add_argument("--baseline-prefix-origin", default=None, help="Path to baseline_prefix_origin.parquet.")
    ap.add_argument("--baseline-path", default=None, help="Path to baseline_path.parquet.")
    ap.add_argument("--output-dir", default=None, help="Output candidate directory.")
    ap.add_argument("--min-weak-rules", type=int, default=2)
    ap.add_argument("--overwrite", type=str2bool, default=False)
    ap.add_argument("--batch-size", type=int, default=100000)
    args = ap.parse_args()

    if args.min_weak_rules <= 0:
        raise SystemExit("--min-weak-rules must be > 0")
    if args.batch_size <= 0:
        raise SystemExit("--batch-size must be > 0")

    if args.events:
        events_path = Path(args.events)
    else:
        if not args.run_id:
            raise SystemExit("Please provide --run-id or --events.")
        events_path = Path("data") / "runs" / args.run_id / "events" / "event_units.parquet"
    if not events_path.exists():
        raise SystemExit(f"events file not found: {events_path}")

    run_id = args.run_id or infer_run_id(events_path) or "unknown_run"
    baseline_dir = events_path.parent.parent / "baseline" if events_path.parent.name == "events" else Path("baseline")
    baseline_prefix_path = Path(args.baseline_prefix) if args.baseline_prefix else baseline_dir / "baseline_prefix.parquet"
    baseline_po_path = Path(args.baseline_prefix_origin) if args.baseline_prefix_origin else baseline_dir / "baseline_prefix_origin.parquet"
    baseline_path_path = Path(args.baseline_path) if args.baseline_path else baseline_dir / "baseline_path.parquet"
    for path in [baseline_prefix_path, baseline_po_path, baseline_path_path]:
        if not path.exists():
            raise SystemExit(f"baseline file not found: {path}")

    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = Path("data") / "runs" / run_id / "candidates" if run_id != "unknown_run" else Path("outputs") / "candidates"
    output_dir.mkdir(parents=True, exist_ok=True)

    out_candidates = output_dir / "candidate_events.parquet"
    out_summary = output_dir / "candidate_summary.json"
    if not args.overwrite:
        exists = [path for path in [out_candidates, out_summary] if path.exists()]
        if exists:
            raise SystemExit("Output exists, pass --overwrite true to replace: " + ", ".join(to_rel_path(path) for path in exists))

    baseline_prefix = ensure_baseline_prefix(pd.read_parquet(baseline_prefix_path))
    baseline_po = ensure_baseline_prefix_origin(pd.read_parquet(baseline_po_path))
    baseline_path_df = ensure_baseline_path(pd.read_parquet(baseline_path_path))
    prefix_map = build_prefix_map(baseline_prefix)
    po_map = build_prefix_origin_map(baseline_po)
    path_map = build_path_map(baseline_path_df)
    po_runtime_stats = build_po_runtime_stats(events_path, args.batch_size)

    event_columns = [
        "event_id",
        "run_id",
        "prefix",
        "origin_as",
        "as_path_clean",
        "as_path_len",
        "duration_sec",
        "record_count",
        "withdraw_count",
        "collector_set",
        "collector_count",
        "visibility_count",
    ]

    writer = None
    total_events = 0
    candidate_events = 0
    candidate_reason_counts: dict[str, int] = {}
    all_reason_counts: dict[str, int] = {}
    candidate_samples: list[dict] = []
    non_candidate_samples: list[dict] = []

    try:
        for batch_df in iter_event_batches(events_path, event_columns, args.batch_size):
            output_rows = []
            for row in batch_df.itertuples(index=False):
                origin_key = float(row.origin_as_num) if not pd.isna(row.origin_as_num) else float("nan")
                prefix_info = prefix_map.get(str(row.prefix), {})
                po_info = po_map.get((str(row.prefix), origin_key), {})
                path_info = path_map.get((str(row.prefix), origin_key, str(row.as_path_clean)), {})
                runtime_info = po_runtime_stats.get((str(row.prefix), origin_key), {})

                record = {
                    "origin_as_num": origin_key,
                    "duration_sec": float(row.duration_sec),
                    "visibility_count": float(row.visibility_count),
                    "as_path_clean": str(row.as_path_clean),
                    "as_path_len": float(row.as_path_len),
                    "collector_count": float(row.collector_count),
                    "record_count": float(row.record_count),
                    "withdraw_count": float(row.withdraw_count),
                    **prefix_info,
                    **po_info,
                    **runtime_info,
                    **path_info,
                    "path_seen_before": bool(path_info),
                }
                candidate_flag, reason_set, matched_rule_count = evaluate_rules_from_record(record, args.min_weak_rules, run_id)
                candidate_reasons = json.dumps(reason_set, ensure_ascii=False)

                out_row = {
                    "event_id": row.event_id,
                    "run_id": row.run_id,
                    "prefix": row.prefix,
                    "origin_as": row.origin_as,
                    "as_path_clean": row.as_path_clean,
                    "as_path_len": int(float(row.as_path_len) or 0),
                    "duration_sec": float(row.duration_sec),
                    "record_count": float(row.record_count),
                    "collector_set": row.collector_set,
                    "collector_count": float(row.collector_count),
                    "visibility_count": float(row.visibility_count),
                    "candidate_flag": bool(candidate_flag),
                    "candidate_reasons": candidate_reasons,
                    "matched_rule_count": int(matched_rule_count),
                    "prefix_total_events": float(record.get("prefix_total_events", 0.0) or 0.0),
                    "prefix_unique_origins": float(record.get("prefix_unique_origins", 0.0) or 0.0),
                    "po_total_events": float(record.get("po_total_events", 0.0) or 0.0),
                    "po_unique_paths": float(record.get("po_unique_paths", 0.0) or 0.0),
                    "po_collector_support": float(record.get("po_collector_support", 0.0) or 0.0),
                    "po_time_span_sec": float(record.get("po_time_span_sec", 0.0) or 0.0),
                    "path_total_events": float(record.get("path_total_events", 0.0) or 0.0),
                    "path_seen_before": bool(record.get("path_seen_before", False)),
                }
                output_rows.append(out_row)

                total_events += 1
                for reason in reason_set:
                    all_reason_counts[reason] = all_reason_counts.get(reason, 0) + 1
                if candidate_flag:
                    candidate_events += 1
                    for reason in reason_set:
                        candidate_reason_counts[reason] = candidate_reason_counts.get(reason, 0) + 1
                    if len(candidate_samples) < 5:
                        candidate_samples.append(out_row)
                elif len(non_candidate_samples) < 5:
                    non_candidate_samples.append(out_row)

            output_df = pd.DataFrame(output_rows)
            table = pa.Table.from_pandas(output_df, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(out_candidates, table.schema)
            writer.write_table(table)
    finally:
        if writer is not None:
            writer.close()

    candidate_rate = float(candidate_events / total_events) if total_events else 0.0
    summary = {
        "run_id": run_id,
        "events_path": to_rel_path(events_path),
        "baseline_prefix_path": to_rel_path(baseline_prefix_path),
        "baseline_prefix_origin_path": to_rel_path(baseline_po_path),
        "baseline_path_path": to_rel_path(baseline_path_path),
        "output_candidate_path": to_rel_path(out_candidates),
        "output_summary_path": to_rel_path(out_summary),
        "total_events": int(total_events),
        "candidate_events": int(candidate_events),
        "candidate_rate": candidate_rate,
        "min_weak_rules": args.min_weak_rules,
        "structural_rules": sorted(STRUCTURAL_RULES),
        "weak_rules": sorted(WEAK_RULES),
        "contextual_rules": sorted(CONTEXTUAL_RULES),
        "candidate_reason_counts": {str(k): int(v) for k, v in candidate_reason_counts.items()},
        "all_reason_counts": {str(k): int(v) for k, v in all_reason_counts.items()},
    }
    out_summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"run_id: {run_id}")
    print(f"input_events: {to_rel_path(events_path)}")
    print(f"total_events: {total_events}")
    print(f"candidate_events: {candidate_events}")
    print(f"candidate_rate: {candidate_rate:.4f}")
    print("rule_trigger_counts:")
    print(json.dumps(summary["all_reason_counts"], ensure_ascii=False, indent=2))
    print(f"output_candidate_path: {to_rel_path(out_candidates)}")
    print(f"output_summary_path: {to_rel_path(out_summary)}")

    top10 = sorted(all_reason_counts.items(), key=lambda item: item[1], reverse=True)[:10]
    print("top_10_reasons:")
    for reason, count in top10:
        print(f"  - {reason}: {count} ({RULE_DESCRIPTIONS.get(reason, '')})")

    print_samples(candidate_samples, "candidate_samples")
    print_samples(non_candidate_samples, "non_candidate_samples")


if __name__ == "__main__":
    main()
