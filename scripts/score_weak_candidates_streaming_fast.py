import argparse
import json
import shutil
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from score_weak_candidates import (
    CONTEXTUAL_REASONS,
    CONTEXTUAL_WEAK_WEIGHTS,
    DEFAULT_RUN_ID,
    MISSING_DAMPEN_RATIO,
    SCORE_WEIGHTS,
    STRUCTURAL_REASONS,
    STRUCTURAL_REASON_WEIGHTS,
    WEAK_REASONS,
    WEAK_REASON_WEIGHTS,
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


SCORER_VERSION = "score_streaming_fast_v1"

OUTPUT_COLS = [
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
    "candidate_reasons",
    "matched_rule_count",
    "structural_novelty_score",
    "weak_signal_score",
    "history_rarity_score",
    "path_consistency_score",
    "risk_score",
    "top_contributing_factor",
    "missing_origin_or_path",
    "path_seen_before",
    "path_total_events",
    "po_total_events",
    "po_collector_support",
    "po_time_span_sec",
    "prefix_total_events",
    "score_explanation",
]

ORDERED_COLS = OUTPUT_COLS[:18] + ["risk_bucket"] + OUTPUT_COLS[18:]

TOP_FACTOR_ORDER = [
    "structural_novelty_score",
    "weak_signal_score",
    "history_rarity_score",
    "path_consistency_score",
]


def iter_candidate_batches(candidates_path: Path, batch_size: int):
    parquet_file = pq.ParquetFile(candidates_path)
    for batch in parquet_file.iter_batches(batch_size=batch_size):
        yield ensure_candidate_columns(batch.to_pandas())


def file_signature(path: Path) -> dict:
    stat = path.stat()
    return {
        "path": to_rel_path(path),
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
    }


def build_run_signature(args, candidates_path: Path, baseline_prefix_path: Path, baseline_po_path: Path, baseline_path_path: Path) -> dict:
    return {
        "scorer_version": SCORER_VERSION,
        "run_id": args.run_id,
        "batch_size": int(args.batch_size),
        "score_explanation_mode": args.score_explanation_mode,
        "candidates": file_signature(candidates_path),
        "baseline_prefix": file_signature(baseline_prefix_path),
        "baseline_prefix_origin": file_signature(baseline_po_path),
        "baseline_path": file_signature(baseline_path_path),
        "score_weights": SCORE_WEIGHTS,
        "structural_reasons": sorted(STRUCTURAL_REASONS),
        "weak_reasons": sorted(WEAK_REASONS),
        "contextual_reasons": sorted(CONTEXTUAL_REASONS),
    }


def load_manifest(manifest_path: Path) -> dict | None:
    if not manifest_path.exists():
        return None
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def write_manifest(manifest_path: Path, manifest: dict) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = manifest_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(manifest_path)


def reset_output(output_dir: Path, parts_dir: Path, paths: list[Path]) -> None:
    for path in paths:
        if path.exists():
            path.unlink()
    if parts_dir.exists():
        shutil.rmtree(parts_dir)
    parts_dir.mkdir(parents=True, exist_ok=True)


def build_prefix_map(df: pd.DataFrame) -> dict[str, float]:
    return dict(zip(df["prefix"].astype(str), pd.to_numeric(df["total_events"], errors="coerce").fillna(0.0)))


def build_tuple_map(df: pd.DataFrame, key_cols: list[str], value_col: str) -> dict[tuple, float]:
    keys = list(zip(*(df[col].tolist() for col in key_cols)))
    values = pd.to_numeric(df[value_col], errors="coerce").fillna(0.0).tolist()
    return dict(zip(keys, values))


def build_reason_cache(values: pd.Series) -> dict[str, dict]:
    cache: dict[str, dict] = {}
    for value in values.dropna().astype(str).unique().tolist():
        reasons = parse_reason_list(value)
        structural_hits = sorted({r for r in reasons if r in STRUCTURAL_REASONS})
        weak_hits = sorted({r for r in reasons if r in WEAK_REASONS})
        contextual_hits = sorted({r for r in reasons if r in CONTEXTUAL_REASONS})

        structural_base = sum(STRUCTURAL_REASON_WEIGHTS.get(r, 0.0) for r in reasons if r in STRUCTURAL_REASON_WEIGHTS)
        if len(structural_hits) >= 2:
            structural_base += 0.10
        if "unseen_exact_path" in structural_hits and "unseen_path_for_prefix_origin" in structural_hits:
            structural_base += 0.08
        structural_score = min(100.0, structural_base * 100.0)

        weak_base = sum(WEAK_REASON_WEIGHTS.get(r, 0.0) for r in weak_hits)
        if len(set(weak_hits)) >= 2:
            weak_base += 0.08
        weak_base += min(0.05, sum(CONTEXTUAL_WEAK_WEIGHTS.get(r, 0.0) for r in contextual_hits))
        weak_score = min(100.0, weak_base * 100.0)

        cache[value] = {
            "reasons": reasons,
            "structural_score": float(structural_score),
            "structural_hits": structural_hits,
            "weak_score": float(weak_score),
            "weak_hits": weak_hits,
            "contextual_hits": contextual_hits,
        }
    if "[]" not in cache:
        cache["[]"] = {
            "reasons": [],
            "structural_score": 0.0,
            "structural_hits": [],
            "weak_score": 0.0,
            "weak_hits": [],
            "contextual_hits": [],
        }
    return cache


def rarity_from_counts(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce").fillna(0.0).astype(float)
    out = pd.Series(np.ones(len(numeric), dtype=float), index=numeric.index)
    mask = numeric > 0
    out.loc[mask] = 1.0 / (1.0 + np.log10(numeric.loc[mask] + 1.0))
    return out


def safe_bool_series(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series.fillna(False)
    return series.fillna(False).astype(bool)


def tuple_lookup(df: pd.DataFrame, cols: list[str], mapping: dict[tuple, float]) -> pd.Series:
    if not mapping:
        return pd.Series(np.nan, index=df.index, dtype=float)
    keys = zip(*(df[col].tolist() for col in cols))
    return pd.Series([mapping.get(tuple(key), np.nan) for key in keys], index=df.index, dtype=float)


def coalesce_series(primary: pd.Series, fallback: pd.Series) -> pd.Series:
    p = pd.to_numeric(primary, errors="coerce")
    f = pd.to_numeric(fallback, errors="coerce")
    return p.where(p.notna(), f)


def score_batch(
    batch_df: pd.DataFrame,
    prefix_map: dict[str, float],
    po_total_map: dict[tuple, float],
    po_unique_paths_map: dict[tuple, float],
    po_avg_path_len_map: dict[tuple, float],
    po_median_path_len_map: dict[tuple, float],
    path_total_map: dict[tuple, float],
    score_explanation_mode: str = "minimal",
) -> pd.DataFrame:
    if "candidate_flag" in batch_df.columns:
        batch_df = batch_df[batch_df["candidate_flag"]].copy()
    else:
        batch_df = batch_df.copy()
    if batch_df.empty:
        return pd.DataFrame(columns=OUTPUT_COLS)

    out = batch_df.reset_index(drop=True).copy()
    out["origin_as_num"] = pd.to_numeric(out["origin_as_num"], errors="coerce")
    out["prefix"] = out["prefix"].fillna("").astype(str)
    out["as_path_clean"] = out["as_path_clean"].fillna("").astype(str)

    prefix_fallback = out["prefix"].map(prefix_map)
    po_keys = ["prefix", "origin_as_num"]
    path_keys = ["prefix", "origin_as_num", "as_path_clean"]
    out["prefix_total_events"] = coalesce_series(out["prefix_total_events"], prefix_fallback)
    out["po_total_events"] = coalesce_series(out["po_total_events"], tuple_lookup(out, po_keys, po_total_map))
    out["po_unique_paths"] = coalesce_series(out["po_unique_paths"], tuple_lookup(out, po_keys, po_unique_paths_map))
    out["po_avg_path_len"] = tuple_lookup(out, po_keys, po_avg_path_len_map).fillna(0.0)
    out["po_median_path_len"] = tuple_lookup(out, po_keys, po_median_path_len_map).fillna(0.0)
    out["path_total_events"] = coalesce_series(out["path_total_events"], tuple_lookup(out, path_keys, path_total_map))
    out["path_seen_before"] = safe_bool_series(out["path_seen_before"])

    reason_cache = build_reason_cache(out["candidate_reasons"])
    reason_info = out["candidate_reasons"].fillna("[]").astype(str).map(lambda value: reason_cache.get(value, reason_cache["[]"]))
    structural_score = reason_info.map(lambda item: item["structural_score"]).astype(float)
    weak_score = reason_info.map(lambda item: item["weak_score"]).astype(float)

    path_clean_stripped = out["as_path_clean"].fillna("").astype(str).str.strip()
    origin_missing = out["origin_as_num"].isna()
    path_missing = path_clean_stripped.eq("")
    missing_origin_or_path = origin_missing | path_missing
    as_path_len = pd.to_numeric(out["as_path_len"], errors="coerce").fillna(0.0).astype(float)
    path_len_inconsistent = (path_missing & (as_path_len > 0)) | (~path_missing & (as_path_len <= 0))

    prefix_total = pd.to_numeric(out["prefix_total_events"], errors="coerce").fillna(0.0).astype(float)
    po_total = pd.to_numeric(out["po_total_events"], errors="coerce").fillna(0.0).astype(float)
    path_total = pd.to_numeric(out["path_total_events"], errors="coerce").fillna(0.0).astype(float)
    path_seen_before = safe_bool_series(out["path_seen_before"])
    po_avg_path_len = pd.to_numeric(out["po_avg_path_len"], errors="coerce").fillna(0.0).astype(float)
    po_median_path_len = pd.to_numeric(out["po_median_path_len"], errors="coerce").fillna(0.0).astype(float)
    po_unique_paths = pd.to_numeric(out["po_unique_paths"], errors="coerce").fillna(0.0).astype(float)

    history_score = (
        0.25 * rarity_from_counts(prefix_total)
        + 0.35 * rarity_from_counts(po_total)
        + 0.40 * pd.Series(np.where(path_seen_before, rarity_from_counts(path_total), 1.0), index=out.index)
    ) * 100.0
    history_score = history_score.clip(upper=100.0)

    ref_len = po_median_path_len.where(po_median_path_len > 0, po_avg_path_len)
    dev_score = pd.Series(np.zeros(len(out), dtype=float), index=out.index)
    ref_mask = ref_len > 0
    dev_score.loc[ref_mask] = (
        (as_path_len.loc[ref_mask] - ref_len.loc[ref_mask]).abs() / np.maximum(1.0, ref_len.loc[ref_mask] * 0.5)
    ).clip(upper=1.0)
    no_ref_mask = ~ref_mask & (as_path_len > 0)
    dev_score.loc[no_ref_mask] = (as_path_len.loc[no_ref_mask] / 8.0).clip(upper=1.0)

    unseen_score = pd.Series(np.where(path_seen_before, 0.0, 1.0), index=out.index)
    diversity_score = pd.Series(np.where(po_unique_paths <= 0, 0.8, 0.25), index=out.index)
    diversity_score.loc[(po_unique_paths > 0) & (po_unique_paths <= 2)] = 1.0
    diversity_score.loc[(po_unique_paths > 2) & (po_unique_paths <= 5)] = 0.6

    path_score_raw = (0.60 * dev_score) + (0.25 * unseen_score) + (0.15 * diversity_score)
    path_score_raw = pd.Series(np.where(missing_origin_or_path, np.maximum(path_score_raw, 0.65), path_score_raw), index=out.index)
    path_score = (path_score_raw * 100.0).clip(upper=100.0)

    component_df = pd.DataFrame(
        {
            "structural_novelty_score": structural_score,
            "weak_signal_score": weak_score,
            "history_rarity_score": history_score,
            "path_consistency_score": path_score,
        },
        index=out.index,
    )
    contribution_df = pd.DataFrame(
        {key: component_df[key] * SCORE_WEIGHTS[key] for key in TOP_FACTOR_ORDER},
        index=out.index,
    )
    risk_score_val = contribution_df.sum(axis=1)
    risk_score_val = pd.Series(
        np.where(missing_origin_or_path, risk_score_val * MISSING_DAMPEN_RATIO, risk_score_val),
        index=out.index,
    ).clip(lower=0.0, upper=100.0).round(4)

    top_idx = np.argmax(contribution_df[TOP_FACTOR_ORDER].to_numpy(), axis=1)
    top_factor = pd.Series([TOP_FACTOR_ORDER[idx] for idx in top_idx], index=out.index)

    # score_explanation is not used downstream. The fast default keeps the
    # column schema-compatible while relying on explicit component-score columns
    # for auditability; full row-level JSON remains available for small forensic
    # reruns.
    if score_explanation_mode == "full":
        explanations = []
        structural_hits_list = reason_info.map(lambda item: item["structural_hits"]).tolist()
        weak_hits_list = reason_info.map(lambda item: item["weak_hits"]).tolist()
        contextual_hits_list = reason_info.map(lambda item: item["contextual_hits"]).tolist()
        component_values = component_df[TOP_FACTOR_ORDER].to_numpy()
        contribution_values = contribution_df[TOP_FACTOR_ORDER].to_numpy()
        dev_values = dev_score.to_numpy()
        unseen_values = unseen_score.to_numpy()
        diversity_values = diversity_score.to_numpy()
        ref_len_values = ref_len.to_numpy()
        missing_values = missing_origin_or_path.to_numpy()
        path_len_inconsistent_values = path_len_inconsistent.to_numpy()
        for i in range(len(out)):
            notes = []
            if bool(missing_values[i]):
                notes.append("missing_origin_or_path")
            if bool(path_len_inconsistent_values[i]):
                notes.append("path_length_inconsistent")
            explanation = {
                "structural_reasons": structural_hits_list[i],
                "weak_reasons": weak_hits_list[i],
                "contextual_reasons": contextual_hits_list[i],
                "component_scores": {
                    key: round(float(component_values[i, pos]), 4)
                    for pos, key in enumerate(TOP_FACTOR_ORDER)
                },
                "weighted_contributions": {
                    key: round(float(contribution_values[i, pos]), 4)
                    for pos, key in enumerate(TOP_FACTOR_ORDER)
                },
                "path_consistency_detail": {
                    "deviation_component": round(float(dev_values[i]), 4),
                    "unseen_component": round(float(unseen_values[i]), 4),
                    "diversity_component": round(float(diversity_values[i]), 4),
                    "reference_path_len": round(float(ref_len_values[i]), 4),
                },
                "missing_origin_or_path": bool(missing_values[i]),
                "notes": notes,
            }
            explanations.append(json.dumps(explanation, ensure_ascii=False))
    else:
        explanations = json.dumps(
            {
                "mode": "fast_minimal",
                "note": "Component columns preserve score auditability; rerun with --score-explanation-mode full for row-level JSON.",
            },
            ensure_ascii=False,
        )

    out["structural_novelty_score"] = structural_score.round(4)
    out["weak_signal_score"] = weak_score.round(4)
    out["history_rarity_score"] = history_score.round(4)
    out["path_consistency_score"] = path_score.round(4)
    out["risk_score"] = risk_score_val
    out["top_contributing_factor"] = top_factor
    out["missing_origin_or_path"] = missing_origin_or_path.astype(bool)
    out["score_explanation"] = explanations
    return out[OUTPUT_COLS].copy()


def write_part(part_path: Path, df: pd.DataFrame) -> None:
    tmp = part_path.with_suffix(".tmp.parquet")
    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, tmp)
    tmp.replace(part_path)


def finalize_parts(parts: list[dict], out_scored: Path, out_summary: Path, summary_base: dict, batch_size: int) -> dict:
    part_paths = [Path(part["path"]) for part in parts if part.get("path")]
    if not part_paths:
        raise RuntimeError("no scored part files to finalize")

    risk_chunks = []
    for path in part_paths:
        risk_chunks.append(pd.read_parquet(path, columns=["risk_score"])["risk_score"])
    risk_scores = pd.concat(risk_chunks, ignore_index=True)
    thresholds = derive_bucket_thresholds(risk_scores)

    bucket_counts: dict[str, int] = {}
    top_factor_counts: dict[str, int] = {}
    missing_count = 0
    output_rows = 0
    risk_sum = 0.0
    high_samples: list[dict] = []
    medium_samples: list[dict] = []
    low_samples: list[dict] = []
    missing_samples: list[dict] = []

    if out_scored.exists():
        out_scored.unlink()
    final_writer = None
    try:
        for path in part_paths:
            parquet_file = pq.ParquetFile(path)
            for batch in parquet_file.iter_batches(batch_size=batch_size):
                batch_df = batch.to_pandas()
                bucket = batch_df["risk_score"].map(lambda value: risk_bucket(safe_num(value, 0.0), thresholds))
                batch_df.insert(18, "risk_bucket", bucket)
                final_df = batch_df[ORDERED_COLS].copy()
                table = pa.Table.from_pandas(final_df, preserve_index=False)
                if final_writer is None:
                    final_writer = pq.ParquetWriter(out_scored, table.schema)
                final_writer.write_table(table)

                output_rows += int(len(final_df))
                risk_sum += float(pd.to_numeric(final_df["risk_score"], errors="coerce").fillna(0.0).sum())
                for key, value in final_df["risk_bucket"].value_counts().to_dict().items():
                    bucket_counts[str(key)] = bucket_counts.get(str(key), 0) + int(value)
                for key, value in final_df["top_contributing_factor"].value_counts().to_dict().items():
                    top_factor_counts[str(key)] = top_factor_counts.get(str(key), 0) + int(value)
                missing_count += int(final_df["missing_origin_or_path"].fillna(False).sum())

                if len(high_samples) < 10:
                    high_samples.extend(final_df[final_df["risk_bucket"] == "high"].head(10 - len(high_samples)).to_dict("records"))
                if len(medium_samples) < 10:
                    medium_samples.extend(final_df[final_df["risk_bucket"] == "medium"].head(10 - len(medium_samples)).to_dict("records"))
                if len(low_samples) < 10:
                    low_samples.extend(final_df[final_df["risk_bucket"] == "low"].head(10 - len(low_samples)).to_dict("records"))
                if len(missing_samples) < 5:
                    missing_samples.extend(final_df[final_df["missing_origin_or_path"]].head(5 - len(missing_samples)).to_dict("records"))
    finally:
        if final_writer is not None:
            final_writer.close()

    summary = {
        **summary_base,
        "output_scored_path": to_rel_path(out_scored),
        "output_summary_path": to_rel_path(out_summary),
        "output_rows": int(output_rows),
        "avg_risk_score": float(risk_sum / output_rows) if output_rows else 0.0,
        "bucket_counts": {str(key): int(value) for key, value in bucket_counts.items()},
        "top_contributing_factor_counts": {str(key): int(value) for key, value in top_factor_counts.items()},
        "missing_origin_or_path_count": int(missing_count),
        "risk_bucket_thresholds": thresholds,
        "score_weights": SCORE_WEIGHTS,
        "structural_reasons": sorted(STRUCTURAL_REASONS),
        "weak_reasons": sorted(WEAK_REASONS),
        "contextual_reasons": sorted(CONTEXTUAL_REASONS),
        "part_count": int(len(part_paths)),
    }
    out_summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "summary": summary,
        "samples": {
            "high_risk_samples": high_samples,
            "medium_risk_samples": medium_samples,
            "low_risk_samples": low_samples,
            "missing_origin_or_path_samples": missing_samples,
        },
    }


def print_samples(samples: list[dict], title: str) -> None:
    print(f"{title}:")
    if not samples:
        print("  <empty>")
        return
    sample_cols = [
        "event_id",
        "prefix",
        "origin_as",
        "as_path_clean",
        "candidate_reasons",
        "risk_score",
        "structural_novelty_score",
        "weak_signal_score",
        "history_rarity_score",
        "path_consistency_score",
        "score_explanation",
    ]
    for row in samples[:10]:
        print("  - " + json.dumps({key: row.get(key) for key in sample_cols}, ensure_ascii=False))


def main() -> int:
    ap = argparse.ArgumentParser(description="Fast checkpointable streaming scorer for large candidate pools.")
    ap.add_argument("--run-id", default=DEFAULT_RUN_ID)
    ap.add_argument("--candidates", default=None)
    ap.add_argument("--baseline-prefix", default=None)
    ap.add_argument("--baseline-prefix-origin", default=None)
    ap.add_argument("--baseline-path", default=None)
    ap.add_argument("--output-dir", default=None)
    ap.add_argument("--overwrite", type=str2bool, default=False)
    ap.add_argument("--resume", type=str2bool, default=False)
    ap.add_argument("--batch-size", type=int, default=250000)
    ap.add_argument("--score-explanation-mode", choices=["minimal", "full"], default="minimal")
    args = ap.parse_args()

    if args.batch_size <= 0:
        raise SystemExit("--batch-size must be > 0")

    if args.candidates:
        candidates_path = Path(args.candidates)
        run_id = args.run_id or infer_run_id(candidates_path) or DEFAULT_RUN_ID
    else:
        run_id = args.run_id or DEFAULT_RUN_ID
        candidates_path = Path("data") / "runs" / run_id / "candidates" / "candidate_events.parquet"
    args.run_id = run_id
    if not candidates_path.exists():
        raise SystemExit(f"candidate file not found: {candidates_path}")

    baseline_root = Path("data") / "runs" / run_id / "baseline"
    baseline_prefix_path = Path(args.baseline_prefix) if args.baseline_prefix else baseline_root / "baseline_prefix.parquet"
    baseline_po_path = Path(args.baseline_prefix_origin) if args.baseline_prefix_origin else baseline_root / "baseline_prefix_origin.parquet"
    baseline_path_path = Path(args.baseline_path) if args.baseline_path else baseline_root / "baseline_path.parquet"
    for path in [baseline_prefix_path, baseline_po_path, baseline_path_path]:
        if not path.exists():
            raise SystemExit(f"baseline file not found: {path}")

    output_dir = Path(args.output_dir) if args.output_dir else Path("data") / "runs" / run_id / "scores"
    output_dir.mkdir(parents=True, exist_ok=True)
    parts_dir = output_dir / "parts"
    out_scored = output_dir / "scored_candidates.parquet"
    out_summary = output_dir / "score_summary.json"
    manifest_path = output_dir / "score_parts_manifest.json"

    if not args.overwrite:
        exists = [path for path in [out_scored, out_summary] if path.exists()]
        if exists:
            raise SystemExit("Output exists, pass --overwrite true to replace: " + ", ".join(to_rel_path(path) for path in exists))

    signature = build_run_signature(args, candidates_path, baseline_prefix_path, baseline_po_path, baseline_path_path)
    manifest = load_manifest(manifest_path)
    if args.resume and manifest:
        if manifest.get("signature") != signature:
            raise SystemExit("Existing score manifest signature does not match current inputs/config; do not resume with stale parts.")
        parts_dir.mkdir(parents=True, exist_ok=True)
    else:
        reset_output(output_dir, parts_dir, [out_scored, out_summary, manifest_path, output_dir / "scored_candidates_tmp.parquet"])
        manifest = {
            "signature": signature,
            "completed_parts": [],
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        write_manifest(manifest_path, manifest)

    completed_by_index = {int(item["part_index"]): item for item in manifest.get("completed_parts", [])}

    baseline_prefix = ensure_baseline_prefix(pd.read_parquet(baseline_prefix_path))
    baseline_po = ensure_baseline_prefix_origin(pd.read_parquet(baseline_po_path))
    baseline_path_df = ensure_baseline_path(pd.read_parquet(baseline_path_path))
    prefix_map = build_prefix_map(baseline_prefix)
    po_total_map = build_tuple_map(baseline_po, ["prefix", "origin_as_num"], "total_events")
    po_unique_paths_map = build_tuple_map(baseline_po, ["prefix", "origin_as_num"], "unique_paths")
    po_avg_path_len_map = build_tuple_map(baseline_po, ["prefix", "origin_as_num"], "avg_path_len")
    po_median_path_len_map = build_tuple_map(baseline_po, ["prefix", "origin_as_num"], "median_path_len")
    path_total_map = build_tuple_map(baseline_path_df, ["prefix", "origin_as_num", "as_path_clean"], "total_events")

    input_rows = 0
    input_candidate_rows = 0
    score_started = time.perf_counter()
    for part_index, batch_df in enumerate(iter_candidate_batches(candidates_path, args.batch_size)):
        raw_rows = int(len(batch_df))
        candidate_rows = int(batch_df["candidate_flag"].fillna(False).astype(bool).sum()) if "candidate_flag" in batch_df else raw_rows
        input_rows += raw_rows
        input_candidate_rows += candidate_rows

        if part_index in completed_by_index:
            print(f"[skip] part={part_index:06d} rows={completed_by_index[part_index].get('output_rows', 0)}", flush=True)
            continue

        part_started = time.perf_counter()
        scored_df = score_batch(
            batch_df,
            prefix_map,
            po_total_map,
            po_unique_paths_map,
            po_avg_path_len_map,
            po_median_path_len_map,
            path_total_map,
            score_explanation_mode=args.score_explanation_mode,
        )
        part_path = parts_dir / f"part_{part_index:06d}.parquet"
        part_rel = ""
        if not scored_df.empty:
            write_part(part_path, scored_df)
            part_rel = to_rel_path(part_path)
        part_meta = {
            "part_index": int(part_index),
            "input_rows": raw_rows,
            "output_rows": int(len(scored_df)),
            "path": part_rel,
            "seconds": round(time.perf_counter() - part_started, 4),
        }
        manifest["completed_parts"].append(part_meta)
        completed_by_index[part_index] = part_meta
        write_manifest(manifest_path, manifest)
        print(f"[part] {part_index:06d} input={raw_rows} output={len(scored_df)} seconds={part_meta['seconds']}", flush=True)

    score_seconds = time.perf_counter() - score_started
    parts = sorted(manifest.get("completed_parts", []), key=lambda item: int(item["part_index"]))
    summary_base = {
        "run_id": run_id,
        "scorer_version": SCORER_VERSION,
        "candidates_path": to_rel_path(candidates_path),
        "baseline_prefix_path": to_rel_path(baseline_prefix_path),
        "baseline_prefix_origin_path": to_rel_path(baseline_po_path),
        "baseline_path_path": to_rel_path(baseline_path_path),
        "input_rows": int(input_rows or sum(int(item.get("input_rows", 0)) for item in parts)),
        "input_candidate_rows": int(input_candidate_rows or sum(int(item.get("output_rows", 0)) for item in parts)),
        "score_seconds": float(score_seconds),
        "score_rows_per_sec": float((input_candidate_rows or sum(int(item.get("output_rows", 0)) for item in parts)) / score_seconds)
        if score_seconds > 0
        else 0.0,
        "manifest_path": to_rel_path(manifest_path),
    }
    finalized = finalize_parts(parts, out_scored, out_summary, summary_base, args.batch_size)
    manifest["finalized_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    manifest["output_scored_path"] = to_rel_path(out_scored)
    manifest["output_summary_path"] = to_rel_path(out_summary)
    write_manifest(manifest_path, manifest)

    summary = finalized["summary"]
    print(f"run_id: {run_id}")
    print(f"input_candidates_path: {to_rel_path(candidates_path)}")
    print(f"input_rows: {summary['input_rows']}")
    print(f"input_candidate_rows: {summary['input_candidate_rows']}")
    print(f"output_scored_rows: {summary['output_rows']}")
    print(f"score_seconds: {summary['score_seconds']:.4f}")
    print(f"score_rows_per_sec: {summary['score_rows_per_sec']:.4f}")
    print(f"avg_risk_score: {summary['avg_risk_score']:.4f}")
    print("bucket_counts:")
    print(json.dumps(summary["bucket_counts"], ensure_ascii=False, indent=2))
    print("top_contributing_factor_counts:")
    print(json.dumps(summary["top_contributing_factor_counts"], ensure_ascii=False, indent=2))
    print(f"missing_origin_or_path_count: {summary['missing_origin_or_path_count']}")
    print(f"output_scored_path: {to_rel_path(out_scored)}")
    print(f"output_summary_path: {to_rel_path(out_summary)}")
    for title, samples in finalized["samples"].items():
        print_samples(samples, title)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
