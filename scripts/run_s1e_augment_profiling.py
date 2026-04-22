import argparse
import cProfile
import io
import json
import pstats
import time
from contextlib import contextmanager
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

import augment_uncertain_candidates as aug


DEFAULT_RUN_ID = "s1a_expanded_v02_pilot_60m_april16"
DEFAULT_OUTPUT_DIR = Path("outputs") / "s1e_augment_profiling_v01"


@contextmanager
def timed(stage_timings: list[dict], name: str, extra: dict | None = None):
    start = time.perf_counter()
    yield
    elapsed = time.perf_counter() - start
    row = {"stage": name, "seconds": elapsed}
    if extra:
        row.update(extra)
    stage_timings.append(row)


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def sample_uncertain_gating_rows(
    gating_path: Path,
    *,
    target_uncertain_rows: int,
    batch_size: int,
    stage_timings: list[dict],
) -> tuple[pd.DataFrame, dict]:
    batches = []
    scanned_rows = 0
    scanned_batches = 0
    collected_uncertain = 0

    with timed(stage_timings, "sample_gating_batches"):
        parquet_file = pq.ParquetFile(gating_path)
        for batch in parquet_file.iter_batches(batch_size=batch_size):
            scanned_batches += 1
            batch_df = batch.to_pandas()
            scanned_rows += len(batch_df)
            batch_df = aug.ensure_gating_columns(batch_df)
            uncertain = batch_df[batch_df["gating_label"] == aug.UNCERTAIN_LABEL].copy()
            if not uncertain.empty:
                remaining = target_uncertain_rows - collected_uncertain
                batches.append(uncertain.head(remaining))
                collected_uncertain += min(len(uncertain), remaining)
            if collected_uncertain >= target_uncertain_rows:
                break

    if batches:
        sample_df = pd.concat(batches, ignore_index=True)
    else:
        sample_df = pd.DataFrame()

    info = {
        "gating_path": rel(gating_path),
        "target_uncertain_rows": target_uncertain_rows,
        "sample_uncertain_rows": int(len(sample_df)),
        "scanned_gating_rows": int(scanned_rows),
        "scanned_gating_batches": int(scanned_batches),
        "batch_size": int(batch_size),
        "sampling_method": "deterministic first uncertain rows from parquet batches",
    }
    return sample_df, info


def load_context(
    *,
    run_root: Path,
    uncertain_df: pd.DataFrame,
    stage_timings: list[dict],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    event_cols = [
        "event_id",
        "prefix",
        "origin_as",
        "as_path_clean",
        "first_seen",
        "last_seen",
        "collector_set",
        "collector_count",
    ]
    with timed(stage_timings, "read_events_selected_columns"):
        events_df = aug.ensure_event_columns(pd.read_parquet(run_root / "events" / "event_units.parquet", columns=event_cols))

    with timed(stage_timings, "read_baseline_prefix"):
        baseline_prefix_df = aug.ensure_baseline_prefix(pd.read_parquet(run_root / "baseline" / "baseline_prefix.parquet"))

    with timed(stage_timings, "read_baseline_prefix_origin"):
        baseline_po_df = aug.ensure_baseline_prefix_origin(pd.read_parquet(run_root / "baseline" / "baseline_prefix_origin.parquet"))

    with timed(stage_timings, "read_baseline_path"):
        baseline_path_df = aug.ensure_baseline_path(pd.read_parquet(run_root / "baseline" / "baseline_path.parquet"))

    with timed(stage_timings, "filter_events_to_sample_prefixes"):
        relevant_prefixes = set(uncertain_df["prefix"].dropna().astype(str).unique())
        events_df = events_df[events_df["prefix"].isin(relevant_prefixes)].reset_index(drop=True)

    return events_df, baseline_prefix_df, baseline_po_df, baseline_path_df


def prepare_uncertain_context(
    *,
    uncertain_df: pd.DataFrame,
    events_df: pd.DataFrame,
    baseline_prefix_df: pd.DataFrame,
    baseline_po_df: pd.DataFrame,
    baseline_path_df: pd.DataFrame,
    stage_timings: list[dict],
) -> pd.DataFrame:
    with timed(stage_timings, "merge_event_columns"):
        uncertain_df = uncertain_df.merge(
            events_df[["event_id", "first_seen", "last_seen", "collector_set", "collector_count"]].rename(
                columns={
                    "collector_set": "event_collector_set",
                    "collector_count": "event_collector_count",
                }
            ),
            on="event_id",
            how="left",
        )

    with timed(stage_timings, "merge_baseline_prefix"):
        uncertain_df = uncertain_df.merge(
            baseline_prefix_df[["prefix", "total_events"]].rename(columns={"total_events": "prefix_total_events"}),
            on="prefix",
            how="left",
        )

    with timed(stage_timings, "merge_baseline_prefix_origin"):
        uncertain_df = uncertain_df.merge(
            baseline_po_df[["prefix", "origin_as_num", "total_events", "unique_paths"]].rename(
                columns={"total_events": "po_total_events", "unique_paths": "po_unique_paths"}
            ),
            on=["prefix", "origin_as_num"],
            how="left",
        )

    with timed(stage_timings, "merge_baseline_path"):
        uncertain_df = uncertain_df.merge(
            baseline_path_df[["prefix", "origin_as_num", "as_path_clean", "total_events"]].rename(
                columns={"total_events": "path_total_events"}
            ),
            on=["prefix", "origin_as_num", "as_path_clean"],
            how="left",
        )
        uncertain_df["path_seen_before"] = uncertain_df["path_total_events"].fillna(0) > 0

    return uncertain_df


def build_event_indexes(events_df: pd.DataFrame, stage_timings: list[dict]) -> dict:
    with timed(stage_timings, "groupby_event_indexes"):
        empty_events = events_df.iloc[0:0]
        return {
            "empty_events": empty_events,
            "prefix_index": events_df.groupby("prefix", sort=False).indices,
            "po_index": events_df.groupby(["prefix", "origin_as_num"], dropna=False, sort=False).indices,
            "path_index": events_df.groupby(["prefix", "origin_as_num", "as_path_clean"], dropna=False, sort=False).indices,
            "event_row_pos": {event_id: idx for idx, event_id in enumerate(events_df["event_id"].tolist())},
        }


def indexed_events(events_df: pd.DataFrame, indexes: dict, index_name: str, key) -> pd.DataFrame:
    positions = indexes[index_name].get(key)
    if positions is None:
        return indexes["empty_events"]
    return events_df.take(positions)


def run_core_augment_loop(
    uncertain_df: pd.DataFrame,
    events_df: pd.DataFrame,
    indexes: dict,
    *,
    profile: str,
) -> pd.DataFrame:
    active_config = aug.build_augment_config(profile)
    results = []
    for row in uncertain_df.itertuples(index=False):
        row_s = pd.Series(row._asdict())
        event_id = str(row_s.get("event_id", ""))
        reasons = aug.parse_reason_list(row_s.get("candidate_reasons", "[]"))

        if event_id in indexes["event_row_pos"]:
            evt_row = events_df.iloc[indexes["event_row_pos"][event_id]]
        else:
            evt_row = pd.Series(
                {
                    "event_id": event_id,
                    "prefix": row_s.get("prefix", ""),
                    "origin_as_num": row_s.get("origin_as_num", None),
                    "as_path_clean": row_s.get("as_path_clean", ""),
                    "first_seen": row_s.get("first_seen", 0.0),
                    "last_seen": row_s.get("last_seen", 0.0),
                    "collector_set": row_s.get("event_collector_set", ""),
                    "collector_count": row_s.get("event_collector_count", 0.0),
                }
            )

        prefix = str(row_s.get("prefix", ""))
        origin = row_s.get("origin_as_num", float("nan"))
        path = str(row_s.get("as_path_clean", ""))
        prefix_events = indexed_events(events_df, indexes, "prefix_index", prefix)
        po_events = indexed_events(events_df, indexes, "po_index", (prefix, origin))
        path_events = indexed_events(events_df, indexes, "path_index", (prefix, origin, path))

        multi_score, _ = aug.calc_multi_view_support_score(row_s, evt_row, prefix_events, po_events, path_events)
        hist_score, _ = aug.calc_historical_deviation_support_score(row_s, reasons)
        cons_score, _ = aug.calc_consistency_recheck_score(row_s, reasons)

        evidence = (
            aug.AUGMENT_WEIGHTS["multi_view_support_score"] * multi_score
            + aug.AUGMENT_WEIGHTS["historical_deviation_support_score"] * hist_score
            + aug.AUGMENT_WEIGHTS["consistency_recheck_score"] * cons_score
        )
        evidence = round(aug.clip_0_100(evidence), 4)
        aug_label, blocked_missing_promotion = aug.choose_augmentation_outcome(
            evidence,
            missing_origin_or_path=bool(row_s.get("missing_origin_or_path", False)),
            config=active_config,
        )
        if aug_label == "demoted_suspicious" and aug.should_preserve_route_leak_review(row_s, reasons, evidence):
            aug_label = "retained_uncertain"

        results.append(
            {
                "event_id": event_id,
                "evidence_support_score": evidence,
                "augmentation_label": aug_label,
                "blocked_missing_promotion": bool(blocked_missing_promotion),
            }
        )

    return pd.DataFrame(results)


def profile_core_loop(*, uncertain_df: pd.DataFrame, events_df: pd.DataFrame, indexes: dict, profile: str, stage_timings: list[dict]):
    profiler = cProfile.Profile()
    with timed(stage_timings, "core_augment_loop"):
        profiler.enable()
        out_df = run_core_augment_loop(uncertain_df, events_df, indexes, profile=profile)
        profiler.disable()
    return out_df, profiler


def pstats_top(profiler: cProfile.Profile, limit: int) -> tuple[list[dict], str]:
    stream = io.StringIO()
    stats = pstats.Stats(profiler, stream=stream).strip_dirs().sort_stats("cumtime")
    stats.print_stats(limit)
    rows = []
    for func, stat in stats.stats.items():
        cc, nc, tt, ct, callers = stat
        filename, line, name = func
        rows.append(
            {
                "function": f"{filename}:{line}:{name}",
                "primitive_calls": cc,
                "total_calls": nc,
                "total_seconds": tt,
                "cumulative_seconds": ct,
            }
        )
    rows.sort(key=lambda x: x["cumulative_seconds"], reverse=True)
    return rows[:limit], stream.getvalue()


def write_report(
    *,
    output_dir: Path,
    run_id: str,
    profile: str,
    sample_info: dict,
    stage_timings: list[dict],
    top_functions: list[dict],
    pstats_text: str,
    out_df: pd.DataFrame,
    sample_profile: dict,
    total_seconds: float,
):
    output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(stage_timings).to_csv(output_dir / "s1e_stage_timings.csv", index=False)
    pd.DataFrame(top_functions).to_csv(output_dir / "s1e_top_functions.csv", index=False)
    (output_dir / "s1e_pstats_top10.txt").write_text(pstats_text, encoding="utf-8")

    core_seconds = next((x["seconds"] for x in stage_timings if x["stage"] == "core_augment_loop"), 0.0)
    io_seconds = sum(x["seconds"] for x in stage_timings if x["stage"].startswith("read_") or x["stage"] == "sample_gating_batches")
    merge_seconds = sum(x["seconds"] for x in stage_timings if x["stage"].startswith("merge_"))
    groupby_seconds = sum(x["seconds"] for x in stage_timings if x["stage"] == "groupby_event_indexes")
    profile_summary = {
        "total_seconds": total_seconds,
        "sample_info": sample_info,
        "sample_profile": sample_profile,
        "core_loop_seconds": core_seconds,
        "io_seconds": io_seconds,
        "merge_seconds": merge_seconds,
        "groupby_seconds": groupby_seconds,
        "output_rows": int(len(out_df)),
        "augmentation_label_counts": out_df["augmentation_label"].value_counts().to_dict() if not out_df.empty else {},
        "blocked_missing_promotion_count": int(out_df.get("blocked_missing_promotion", pd.Series(dtype=bool)).fillna(False).astype(bool).sum()),
    }
    (output_dir / "s1e_profile_summary.json").write_text(json.dumps(profile_summary, ensure_ascii=False, indent=2), encoding="utf-8")

    stage_df = pd.DataFrame(stage_timings).sort_values("seconds", ascending=False)
    top_df = pd.DataFrame(top_functions)

    bottleneck_type = "row-wise computation"
    if io_seconds > core_seconds and io_seconds > merge_seconds + groupby_seconds:
        bottleneck_type = "I/O"
    elif merge_seconds + groupby_seconds > core_seconds:
        bottleneck_type = "merge/groupby"

    total_for_pct = max(total_seconds, 1e-9)
    stage_lines = []
    for row in stage_df.to_dict("records"):
        pct = row["seconds"] / total_for_pct * 100
        stage_lines.append(f"| `{row['stage']}` | {row['seconds']:.4f} | {pct:.2f}% |")

    fn_lines = []
    for row in top_df.head(10).to_dict("records"):
        pct = row["cumulative_seconds"] / max(core_seconds, 1e-9) * 100
        fn_lines.append(
            f"| `{row['function']}` | {row['cumulative_seconds']:.4f} | {pct:.2f}% | {row['total_calls']} |"
        )

    report = f"""# S1-E Augment Profiling Report

## Scope

- run_id: `{run_id}`
- profile: `{profile}`
- sampling: {sample_info['sampling_method']}
- target_uncertain_rows: {sample_info['target_uncertain_rows']}
- sample_uncertain_rows: {sample_info['sample_uncertain_rows']}
- scanned_gating_rows: {sample_info['scanned_gating_rows']}
- scanned_gating_batches: {sample_info['scanned_gating_batches']}
- total_seconds: {total_seconds:.4f}

## Sample Representativeness

- sample_missing_rate: {sample_profile['missing_rate']:.4f}
- sample_conflict_mean: {sample_profile['conflict_mean']:.4f}
- sample_certainty_mean: {sample_profile['certainty_mean']:.4f}
- sample_unique_prefixes: {sample_profile['unique_prefixes']}
- sample_unique_prefix_origin_paths: {sample_profile['unique_prefix_origin_paths']}

This profiling run uses a deterministic bounded slice instead of the full modern candidate set. The timing is suitable for locating hot spots, not for claiming absolute full-run wall time.

## Stage Timing

| stage | seconds | pct_total |
|---|---:|---:|
{chr(10).join(stage_lines)}

## Top 10 Time-consuming Functions

| function | cumulative_seconds | pct_core_loop | calls |
|---|---:|---:|---:|
{chr(10).join(fn_lines)}

## Bottleneck Diagnosis

- primary_bottleneck_type: `{bottleneck_type}`
- io_seconds: {io_seconds:.4f}
- merge_seconds: {merge_seconds:.4f}
- groupby_seconds: {groupby_seconds:.4f}
- core_loop_seconds: {core_seconds:.4f}

The dominant cost is the per-row augmentation loop. The profile shows repeated `pandas.Series` construction, DataFrame slicing/take, collector-set parsing, and time-window filtering inside `calc_multi_view_support_score`. This matches the S1-D full run behavior: performance is not limited by final labeling and is unlikely to be fixed by changing gate/score/candidate.

## S1-F Optimization Plan

1. Replace per-row `pd.Series(row._asdict())` with direct tuple or dict access, and avoid allocating Series for every uncertain row.
2. Pre-parse `candidate_reasons` and `collector_set` once into compact columns or sets; do not call JSON parsing and split logic inside every scoring pass.
3. Replace repeated `events_df.take(...); near_time(...)` DataFrame materialization with precomputed lightweight arrays keyed by prefix / prefix-origin / exact path.
4. Precompute per-event nearby support counts and collector-union features in vectorized/grouped form before the row loop.
5. Keep the `modern_missing_block` profile unchanged while optimizing implementation, then validate S1-F against S1-D exact output counts.

## Output Files

- `s1e_stage_timings.csv`
- `s1e_top_functions.csv`
- `s1e_pstats_top10.txt`
- `s1e_profile_summary.json`
"""
    (output_dir / "s1e_profiling_report.md").write_text(report, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="S1-E profiling for augment_uncertain_candidates.py.")
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--sample-uncertain-rows", type=int, default=20000)
    parser.add_argument("--batch-size", type=int, default=50000)
    parser.add_argument("--profile", default="modern_missing_block", choices=sorted(aug.AUGMENT_PROFILES.keys()))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    run_root = Path("data") / "runs" / args.run_id
    gating_path = run_root / "gating" / "gated_candidates.parquet"
    if not gating_path.exists():
        raise SystemExit(f"missing gating parquet: {gating_path}")

    stage_timings: list[dict] = []
    total_start = time.perf_counter()

    uncertain_df, sample_info = sample_uncertain_gating_rows(
        gating_path,
        target_uncertain_rows=args.sample_uncertain_rows,
        batch_size=args.batch_size,
        stage_timings=stage_timings,
    )
    if uncertain_df.empty:
        raise SystemExit("no uncertain rows sampled")

    sample_profile = {
        "missing_rate": float(uncertain_df["missing_origin_or_path"].fillna(False).astype(bool).mean()),
        "conflict_mean": float(pd.to_numeric(uncertain_df["conflict_score"], errors="coerce").fillna(0).mean()),
        "certainty_mean": float(pd.to_numeric(uncertain_df["certainty_score"], errors="coerce").fillna(0).mean()),
        "unique_prefixes": int(uncertain_df["prefix"].nunique()),
        "unique_prefix_origin_paths": int(
            uncertain_df[["prefix", "origin_as_num", "as_path_clean"]].drop_duplicates().shape[0]
        ),
    }

    events_df, baseline_prefix_df, baseline_po_df, baseline_path_df = load_context(
        run_root=run_root,
        uncertain_df=uncertain_df,
        stage_timings=stage_timings,
    )
    uncertain_df = prepare_uncertain_context(
        uncertain_df=uncertain_df,
        events_df=events_df,
        baseline_prefix_df=baseline_prefix_df,
        baseline_po_df=baseline_po_df,
        baseline_path_df=baseline_path_df,
        stage_timings=stage_timings,
    )
    indexes = build_event_indexes(events_df, stage_timings)

    out_df, profiler = profile_core_loop(
        uncertain_df=uncertain_df,
        events_df=events_df,
        indexes=indexes,
        profile=args.profile,
        stage_timings=stage_timings,
    )
    top_functions, pstats_text = pstats_top(profiler, 10)
    total_seconds = time.perf_counter() - total_start
    write_report(
        output_dir=output_dir,
        run_id=args.run_id,
        profile=args.profile,
        sample_info=sample_info,
        stage_timings=stage_timings,
        top_functions=top_functions,
        pstats_text=pstats_text,
        out_df=out_df,
        sample_profile=sample_profile,
        total_seconds=total_seconds,
    )

    top3 = pd.DataFrame(top_functions).head(3)
    print(f"output_dir={rel(output_dir)}")
    print(f"total_seconds={total_seconds:.4f}")
    print(f"sample_uncertain_rows={sample_info['sample_uncertain_rows']}")
    print("top3_functions:")
    for row in top3.to_dict("records"):
        print(f"- {row['function']} cumulative_seconds={row['cumulative_seconds']:.4f}")


if __name__ == "__main__":
    main()
