import argparse
import json
from pathlib import Path

import pandas as pd


RULE_DESCRIPTIONS = {
    "unseen_origin_for_prefix": "Origin not seen in prefix top history.",
    "unusually_low_visibility_for_prefix": "Visibility lower than prefix baseline.",
    "unusually_short_duration_for_prefix": "Duration shorter than prefix baseline.",
    "unseen_path_for_prefix_origin": "Path not in prefix-origin top history.",
    "abnormal_path_length_for_prefix_origin": "Path length deviates from prefix-origin baseline.",
    "unusually_low_visibility_for_prefix_origin": "Visibility lower than prefix-origin baseline.",
    "unseen_exact_path": "Exact prefix-origin-path not seen in path baseline.",
    "weak_path_history": "Path exists but history is weak/stale.",
    "cross_collector_prefix_origin_burst": "Same prefix-origin bursts across multiple collectors with multiple one-off paths in a short span.",
    "single_collector_visibility": "Only one collector observed the event.",
    "sparse_short_lived_event": "Few records and short duration event.",
}

STRUCTURAL_RULES = {
    "unseen_origin_for_prefix",
    "unseen_path_for_prefix_origin",
    "unseen_exact_path",
    "weak_path_history",
    "abnormal_path_length_for_prefix_origin",
    "cross_collector_prefix_origin_burst",
}

WEAK_RULES = {
    "unusually_low_visibility_for_prefix",
    "unusually_short_duration_for_prefix",
    "unusually_low_visibility_for_prefix_origin",
    "sparse_short_lived_event",
}

# Context-only reasons are kept for explainability, but they do not contribute
# to candidate promotion counts.
CONTEXTUAL_RULES = {
    "single_collector_visibility",
}

DEFAULT_THRESHOLDS = {
    "prefix_visibility_ratio": 0.6,
    "prefix_short_duration_ratio": 0.35,
    "prefix_origin_visibility_ratio": 0.6,
    "path_length_delta": 2.0,
    "weak_path_history_max_events": 2,
    "sparse_record_max": 2,
    "sparse_duration_max_sec": 5.0,
    "po_burst_max_events": 2,
    "po_burst_min_unique_paths": 2,
    "po_burst_min_collectors": 2,
    "po_burst_max_time_span_sec": 10.0,
    "po_burst_max_path_events": 1,
}


def str2bool(value: str) -> bool:
    v = str(value).strip().lower()
    if v in {"1", "true", "yes", "y", "on"}:
        return True
    if v in {"0", "false", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"Invalid boolean value: {value}")


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


def infer_run_id(path: Path):
    parts = list(path.resolve().parts)
    for idx, part in enumerate(parts):
        if part == "runs" and idx + 1 < len(parts):
            return parts[idx + 1]
    return None


def ensure_event_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    required_defaults = {
        "event_id": "",
        "run_id": "",
        "prefix": "",
        "origin_as": None,
        "as_path_clean": "",
        "as_path_len": 0,
        "duration_sec": 0.0,
        "record_count": 0,
        "announce_count": 0,
        "withdraw_count": 0,
        "collector_set": "",
        "collector_count": 0,
        "visibility_count": 0,
    }
    for col, default in required_defaults.items():
        if col not in out.columns:
            out[col] = default

    out["origin_as_num"] = pd.to_numeric(out["origin_as"], errors="coerce")
    out["as_path_len"] = pd.to_numeric(out["as_path_len"], errors="coerce").fillna(0.0)
    out["duration_sec"] = pd.to_numeric(out["duration_sec"], errors="coerce").fillna(0.0)
    out["record_count"] = pd.to_numeric(out["record_count"], errors="coerce").fillna(0.0)
    out["announce_count"] = pd.to_numeric(out["announce_count"], errors="coerce").fillna(0.0)
    out["withdraw_count"] = pd.to_numeric(out["withdraw_count"], errors="coerce").fillna(0.0)
    out["collector_count"] = pd.to_numeric(out["collector_count"], errors="coerce").fillna(0.0)
    out["visibility_count"] = pd.to_numeric(out["visibility_count"], errors="coerce").fillna(0.0)
    out["prefix"] = out["prefix"].fillna("").astype(str)
    out["as_path_clean"] = out["as_path_clean"].fillna("").astype(str)
    out["collector_set"] = out["collector_set"].fillna("").astype(str)
    out["run_id"] = out["run_id"].fillna("").astype(str)
    out["event_id"] = out["event_id"].fillna("").astype(str)
    return out


def ensure_baseline_prefix(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    defaults = {
        "prefix": "",
        "total_events": 0,
        "unique_origins": 0,
        "top_origins": "[]",
        "avg_duration_sec": 0.0,
        "median_duration_sec": 0.0,
        "avg_visibility_count": 0.0,
        "median_visibility_count": 0.0,
    }
    for col, default in defaults.items():
        if col not in out.columns:
            out[col] = default
    out["prefix"] = out["prefix"].fillna("").astype(str)
    for c in ["total_events", "unique_origins", "avg_duration_sec", "median_duration_sec", "avg_visibility_count", "median_visibility_count"]:
        out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0.0)
    out["top_origins"] = out["top_origins"].fillna("[]").astype(str)
    return out


def ensure_baseline_prefix_origin(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    defaults = {
        "prefix": "",
        "origin_as": None,
        "total_events": 0,
        "unique_paths": 0,
        "top_paths": "[]",
        "avg_path_len": 0.0,
        "median_path_len": 0.0,
        "avg_visibility_count": 0.0,
    }
    for col, default in defaults.items():
        if col not in out.columns:
            out[col] = default
    out["prefix"] = out["prefix"].fillna("").astype(str)
    out["origin_as_num"] = pd.to_numeric(out["origin_as"], errors="coerce")
    for c in ["total_events", "unique_paths", "avg_path_len", "median_path_len", "avg_visibility_count"]:
        out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0.0)
    out["top_paths"] = out["top_paths"].fillna("[]").astype(str)
    return out


def ensure_baseline_path(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    defaults = {
        "prefix": "",
        "origin_as": None,
        "as_path_clean": "",
        "total_events": 0,
        "last_seen_run_id": "",
    }
    for col, default in defaults.items():
        if col not in out.columns:
            out[col] = default
    out["prefix"] = out["prefix"].fillna("").astype(str)
    out["as_path_clean"] = out["as_path_clean"].fillna("").astype(str)
    out["origin_as_num"] = pd.to_numeric(out["origin_as"], errors="coerce")
    out["total_events"] = pd.to_numeric(out["total_events"], errors="coerce").fillna(0.0)
    out["last_seen_run_id"] = out["last_seen_run_id"].fillna("").astype(str)
    return out


def parse_top_values(raw: str) -> set[str]:
    if raw is None:
        return set()
    text = str(raw).strip()
    if not text:
        return set()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {x.strip() for x in text.split("|") if x.strip()}
    values = set()
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                values.add(str(item.get("value", "")).strip())
            else:
                values.add(str(item).strip())
    return {x for x in values if x}


def normalize_origin_label(value) -> str:
    if value is None or pd.isna(value):
        return ""
    try:
        return str(int(float(value)))
    except (ValueError, TypeError):
        return str(value).strip()


def path_in_top(path_value: str, top_raw: str) -> bool:
    if not path_value:
        return False
    top_values = parse_top_values(top_raw)
    return path_value in top_values


def origin_in_top(origin_value, top_raw: str) -> bool:
    label = normalize_origin_label(origin_value)
    if not label:
        return False
    top_values = parse_top_values(top_raw)
    if label in top_values:
        return True
    # compatibility with strings like "13118.0"
    try:
        label_float = str(float(label))
    except ValueError:
        label_float = ""
    return label_float in top_values


def evaluate_rules(row: pd.Series, min_weak_rules: int, current_run_id: str) -> tuple[bool, list[str], int]:
    reasons = []

    # A1 unseen origin for prefix
    if pd.isna(row.get("prefix_total_events")) or row.get("prefix_total_events", 0) <= 0:
        reasons.append("unseen_origin_for_prefix")
    elif not origin_in_top(row.get("origin_as_num"), row.get("prefix_top_origins", "[]")):
        reasons.append("unseen_origin_for_prefix")

    # A2 low visibility for prefix
    p_avg_vis = float(row.get("prefix_avg_visibility_count", 0.0) or 0.0)
    p_med_vis = float(row.get("prefix_median_visibility_count", 0.0) or 0.0)
    p_vis_ref = max(p_avg_vis, p_med_vis)
    if p_vis_ref >= 1.0:
        low_vis_th = max(1.0, p_vis_ref * DEFAULT_THRESHOLDS["prefix_visibility_ratio"])
        if float(row.get("visibility_count", 0.0) or 0.0) < low_vis_th:
            reasons.append("unusually_low_visibility_for_prefix")

    # A3 short duration for prefix
    p_avg_dur = float(row.get("prefix_avg_duration_sec", 0.0) or 0.0)
    p_med_dur = float(row.get("prefix_median_duration_sec", 0.0) or 0.0)
    p_dur_ref = p_med_dur if p_med_dur > 0 else p_avg_dur
    if p_dur_ref > 0:
        short_dur_th = p_dur_ref * DEFAULT_THRESHOLDS["prefix_short_duration_ratio"]
        if float(row.get("duration_sec", 0.0) or 0.0) < short_dur_th:
            reasons.append("unusually_short_duration_for_prefix")

    # B4 unseen path for prefix-origin
    po_total_events = float(row.get("po_total_events", 0.0) or 0.0)
    if po_total_events <= 0:
        reasons.append("unseen_path_for_prefix_origin")
    elif not path_in_top(str(row.get("as_path_clean", "")), row.get("po_top_paths", "[]")):
        reasons.append("unseen_path_for_prefix_origin")

    # B5 path length deviation for prefix-origin
    po_med_len = float(row.get("po_median_path_len", 0.0) or 0.0)
    if po_med_len > 0:
        if abs(float(row.get("as_path_len", 0.0) or 0.0) - po_med_len) >= DEFAULT_THRESHOLDS["path_length_delta"]:
            reasons.append("abnormal_path_length_for_prefix_origin")

    # B6 low visibility for prefix-origin
    po_avg_vis = float(row.get("po_avg_visibility_count", 0.0) or 0.0)
    if po_avg_vis >= 1.0:
        po_low_vis_th = max(1.0, po_avg_vis * DEFAULT_THRESHOLDS["prefix_origin_visibility_ratio"])
        if float(row.get("visibility_count", 0.0) or 0.0) < po_low_vis_th:
            reasons.append("unusually_low_visibility_for_prefix_origin")

    # C7 unseen exact path
    path_seen_before = bool(row.get("path_seen_before", False))
    if not path_seen_before:
        reasons.append("unseen_exact_path")

    # C8 weak path history
    path_total_events = float(row.get("path_total_events", 0.0) or 0.0)
    path_last_seen_run = str(row.get("path_last_seen_run_id", "") or "")
    if path_seen_before and path_total_events <= DEFAULT_THRESHOLDS["weak_path_history_max_events"]:
        if path_last_seen_run and path_last_seen_run != current_run_id:
            reasons.append("weak_path_history")

    # C9 cross-collector prefix-origin burst
    po_collector_support = float(row.get("po_collector_support", 0.0) or 0.0)
    po_time_span_sec = float(row.get("po_time_span_sec", 0.0) or 0.0)
    if (
        int(float(row.get("collector_count", 0.0) or 0.0)) == 1
        and po_total_events > 0
        and po_total_events <= DEFAULT_THRESHOLDS["po_burst_max_events"]
        and float(row.get("po_unique_paths", 0.0) or 0.0) >= DEFAULT_THRESHOLDS["po_burst_min_unique_paths"]
        and po_collector_support >= DEFAULT_THRESHOLDS["po_burst_min_collectors"]
        and po_time_span_sec <= DEFAULT_THRESHOLDS["po_burst_max_time_span_sec"]
        and path_total_events <= DEFAULT_THRESHOLDS["po_burst_max_path_events"]
    ):
        reasons.append("cross_collector_prefix_origin_burst")

    # D10 single collector (contextual only)
    if int(float(row.get("collector_count", 0.0) or 0.0)) == 1:
        reasons.append("single_collector_visibility")

    # D11 sparse short-lived
    rec = float(row.get("record_count", 0.0) or 0.0)
    dur = float(row.get("duration_sec", 0.0) or 0.0)
    wcnt = float(row.get("withdraw_count", 0.0) or 0.0)
    if rec <= DEFAULT_THRESHOLDS["sparse_record_max"] and dur <= DEFAULT_THRESHOLDS["sparse_duration_max_sec"] and wcnt > 0:
        reasons.append("sparse_short_lived_event")

    reason_set = sorted(set(reasons))
    structural_hit_count = sum(1 for r in reason_set if r in STRUCTURAL_RULES)
    weak_hit_count = sum(1 for r in reason_set if r in WEAK_RULES)
    candidate_flag = (structural_hit_count > 0) or (weak_hit_count >= min_weak_rules)
    matched_rule_count = structural_hit_count + weak_hit_count
    return candidate_flag, reason_set, matched_rule_count


def print_samples(df: pd.DataFrame, title: str, n: int):
    print(f"{title}:")
    if df.empty:
        print("  <empty>")
        return
    cols = ["event_id", "prefix", "origin_as", "as_path_clean", "candidate_flag", "matched_rule_count", "candidate_reasons"]
    for row in df.head(n)[cols].to_dict("records"):
        reasons = json.loads(row["candidate_reasons"]) if row["candidate_reasons"] else []
        reason_text = "; ".join(f"{r}: {RULE_DESCRIPTIONS.get(r, '')}" for r in reasons) if reasons else "none"
        print(f"  - event_id={row['event_id']} candidate={row['candidate_flag']} reasons={reason_text}")


def main():
    ap = argparse.ArgumentParser(description="Build weak anomaly candidates from events + baseline tables.")
    ap.add_argument("--run-id", default=None, help="Run id under data/runs/<run_id>.")
    ap.add_argument("--events", default=None, help="Path to event_units.parquet.")
    ap.add_argument("--baseline-prefix", default=None, help="Path to baseline_prefix.parquet.")
    ap.add_argument("--baseline-prefix-origin", default=None, help="Path to baseline_prefix_origin.parquet.")
    ap.add_argument("--baseline-path", default=None, help="Path to baseline_path.parquet.")
    ap.add_argument("--output-dir", default=None, help="Output candidate directory.")
    ap.add_argument("--min-weak-rules", type=int, default=2, help="Weak-rule threshold to promote non-structural events.")
    ap.add_argument("--overwrite", type=str2bool, default=False, help="Overwrite existing outputs.")
    args = ap.parse_args()

    if args.min_weak_rules <= 0:
        raise SystemExit("--min-weak-rules must be > 0")

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
    baseline_po_path = (
        Path(args.baseline_prefix_origin) if args.baseline_prefix_origin else baseline_dir / "baseline_prefix_origin.parquet"
    )
    baseline_path_path = Path(args.baseline_path) if args.baseline_path else baseline_dir / "baseline_path.parquet"
    for p in [baseline_prefix_path, baseline_po_path, baseline_path_path]:
        if not p.exists():
            raise SystemExit(f"baseline file not found: {p}")

    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        if run_id != "unknown_run":
            output_dir = Path("data") / "runs" / run_id / "candidates"
        else:
            output_dir = Path("outputs") / "candidates"
    output_dir.mkdir(parents=True, exist_ok=True)

    out_candidates = output_dir / "candidate_events.parquet"
    out_summary = output_dir / "candidate_summary.json"
    if not args.overwrite:
        exists = [p for p in [out_candidates, out_summary] if p.exists()]
        if exists:
            raise SystemExit(
                "Output exists, pass --overwrite true to replace: " + ", ".join(to_rel_path(p) for p in exists)
            )

    events = ensure_event_columns(pd.read_parquet(events_path))
    baseline_prefix = ensure_baseline_prefix(pd.read_parquet(baseline_prefix_path))
    baseline_po = ensure_baseline_prefix_origin(pd.read_parquet(baseline_po_path))
    baseline_path_df = ensure_baseline_path(pd.read_parquet(baseline_path_path))

    merged = events.merge(
        baseline_prefix[
            [
                "prefix",
                "total_events",
                "unique_origins",
                "top_origins",
                "avg_duration_sec",
                "median_duration_sec",
                "avg_visibility_count",
                "median_visibility_count",
            ]
        ].rename(
            columns={
                "total_events": "prefix_total_events",
                "unique_origins": "prefix_unique_origins",
                "top_origins": "prefix_top_origins",
                "avg_duration_sec": "prefix_avg_duration_sec",
                "median_duration_sec": "prefix_median_duration_sec",
                "avg_visibility_count": "prefix_avg_visibility_count",
                "median_visibility_count": "prefix_median_visibility_count",
            }
        ),
        on="prefix",
        how="left",
    )

    merged = merged.merge(
        baseline_po[
            [
                "prefix",
                "origin_as_num",
                "total_events",
                "unique_paths",
                "top_paths",
                "avg_path_len",
                "median_path_len",
                "avg_visibility_count",
            ]
        ].rename(
            columns={
                "total_events": "po_total_events",
                "unique_paths": "po_unique_paths",
                "top_paths": "po_top_paths",
                "avg_path_len": "po_avg_path_len",
                "median_path_len": "po_median_path_len",
                "avg_visibility_count": "po_avg_visibility_count",
            }
        ),
        on=["prefix", "origin_as_num"],
        how="left",
    )

    po_runtime_stats = (
        events.groupby(["prefix", "origin_as_num"], dropna=False, sort=False)
        .agg(
            po_first_seen=("first_seen", "min"),
            po_last_seen=("last_seen", "max"),
            po_collector_support=(
                "collector_set",
                lambda s: len({x for v in s.fillna("").astype(str) for x in v.split("|") if x}),
            ),
        )
        .reset_index()
    )
    po_runtime_stats["po_time_span_sec"] = (
        pd.to_numeric(po_runtime_stats["po_last_seen"], errors="coerce").fillna(0.0)
        - pd.to_numeric(po_runtime_stats["po_first_seen"], errors="coerce").fillna(0.0)
    )
    merged = merged.merge(
        po_runtime_stats[["prefix", "origin_as_num", "po_collector_support", "po_time_span_sec"]],
        on=["prefix", "origin_as_num"],
        how="left",
    )

    merged = merged.merge(
        baseline_path_df[
            [
                "prefix",
                "origin_as_num",
                "as_path_clean",
                "total_events",
                "last_seen_run_id",
            ]
        ].rename(
            columns={
                "total_events": "path_total_events",
                "last_seen_run_id": "path_last_seen_run_id",
            }
        ),
        on=["prefix", "origin_as_num", "as_path_clean"],
        how="left",
    )

    merged["path_seen_before"] = merged["path_total_events"].notna()

    eval_result = merged.apply(
        lambda row: evaluate_rules(row, args.min_weak_rules, run_id),
        axis=1,
        result_type="expand",
    )
    merged["candidate_flag"] = eval_result[0].astype(bool)
    merged["candidate_reason_list"] = eval_result[1]
    merged["matched_rule_count"] = eval_result[2].astype(int)
    merged["candidate_reasons"] = merged["candidate_reason_list"].apply(lambda x: json.dumps(x, ensure_ascii=False))

    output_cols = [
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
        "prefix_unique_origins",
        "po_total_events",
        "po_unique_paths",
        "po_collector_support",
        "po_time_span_sec",
        "path_total_events",
        "path_seen_before",
    ]
    output_df = merged[output_cols].copy()

    output_df.to_parquet(out_candidates, index=False)

    total_events = int(len(output_df))
    candidate_events = int(output_df["candidate_flag"].sum())
    candidate_rate = float(candidate_events / total_events) if total_events else 0.0

    candidate_reason_counts = {}
    if candidate_events > 0:
        exploded = output_df[output_df["candidate_flag"]]["candidate_reasons"].apply(json.loads).explode().dropna()
        candidate_reason_counts = exploded.value_counts().to_dict()
        candidate_reason_counts = {str(k): int(v) for k, v in candidate_reason_counts.items()}

    all_reason_counts = {}
    exploded_all = output_df["candidate_reasons"].apply(json.loads).explode().dropna()
    if len(exploded_all):
        all_reason_counts = exploded_all.value_counts().to_dict()
        all_reason_counts = {str(k): int(v) for k, v in all_reason_counts.items()}

    summary = {
        "run_id": run_id,
        "events_path": to_rel_path(events_path),
        "baseline_prefix_path": to_rel_path(baseline_prefix_path),
        "baseline_prefix_origin_path": to_rel_path(baseline_po_path),
        "baseline_path_path": to_rel_path(baseline_path_path),
        "output_candidate_path": to_rel_path(out_candidates),
        "output_summary_path": to_rel_path(out_summary),
        "total_events": total_events,
        "candidate_events": candidate_events,
        "candidate_rate": candidate_rate,
        "min_weak_rules": args.min_weak_rules,
        "structural_rules": sorted(STRUCTURAL_RULES),
        "weak_rules": sorted(WEAK_RULES),
        "contextual_rules": sorted(CONTEXTUAL_RULES),
        "candidate_reason_counts": candidate_reason_counts,
        "all_reason_counts": all_reason_counts,
    }
    out_summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"run_id: {run_id}")
    print(f"input_events: {to_rel_path(events_path)}")
    print(f"total_events: {total_events}")
    print(f"candidate_events: {candidate_events}")
    print(f"candidate_rate: {candidate_rate:.4f}")
    print("rule_trigger_counts:")
    print(json.dumps(all_reason_counts, ensure_ascii=False, indent=2))
    print(f"output_candidate_path: {to_rel_path(out_candidates)}")
    print(f"output_summary_path: {to_rel_path(out_summary)}")

    top10 = sorted(all_reason_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    print("top_10_reasons:")
    for reason, count in top10:
        print(f"  - {reason}: {count} ({RULE_DESCRIPTIONS.get(reason, '')})")

    candidate_sample = output_df[output_df["candidate_flag"]].head(5)
    non_candidate_sample = output_df[~output_df["candidate_flag"]].head(5)
    print_samples(candidate_sample, "candidate_samples", 5)
    print_samples(non_candidate_sample, "non_candidate_samples", 5)


if __name__ == "__main__":
    main()
