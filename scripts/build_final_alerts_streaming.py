import argparse
import json
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from build_final_alerts import (
    DEFAULT_RUN_ID,
    ensure_augmentation_columns,
    ensure_gating_columns,
    ensure_scores_columns,
    infer_run_id,
    str2bool,
    to_rel_path,
)


OUTPUT_COLS = [
    "event_id",
    "run_id",
    "prefix",
    "origin_as",
    "as_path_clean",
    "risk_score",
    "risk_bucket",
    "gating_label",
    "augmentation_label",
    "final_alert_label",
    "alert_source_layer",
    "top_contributing_factor",
    "candidate_reasons",
    "gating_explanation",
    "augmentation_explanation",
    "missing_origin_or_path",
    "certainty_score",
    "conflict_score",
    "evidence_support_score",
]


def iter_score_batches(scores_path: Path, batch_size: int):
    parquet_file = pq.ParquetFile(scores_path)
    columns = [
        "event_id",
        "run_id",
        "prefix",
        "origin_as",
        "as_path_clean",
        "risk_score",
        "risk_bucket",
        "top_contributing_factor",
        "candidate_reasons",
        "missing_origin_or_path",
    ]
    for batch in parquet_file.iter_batches(batch_size=batch_size, columns=columns):
        yield ensure_scores_columns(batch.to_pandas())


def decide_labels(batch_df: pd.DataFrame) -> pd.DataFrame:
    out = batch_df.copy()
    out["final_alert_label"] = "needs_review"
    out["alert_source_layer"] = "fallback_uncertain"

    aug = out["augmentation_label"]
    gate = out["gating_label"]

    mask_aug_promoted = aug.eq("promoted_suspicious")
    mask_gate_high = gate.eq("likely_malicious") & ~mask_aug_promoted
    mask_aug_demoted = aug.eq("demoted_suspicious") & ~(mask_aug_promoted | mask_gate_high)
    mask_gate_low = gate.eq("likely_benign") & ~(mask_aug_promoted | mask_gate_high | mask_aug_demoted)
    mask_gate_uncertain = gate.eq("suspicious_but_uncertain") & aug.isin(["retained_uncertain", ""]) & ~(
        mask_aug_promoted | mask_gate_high | mask_aug_demoted | mask_gate_low
    )

    out.loc[mask_aug_promoted, "final_alert_label"] = "high_priority_alert"
    out.loc[mask_aug_promoted, "alert_source_layer"] = "augmentation_promoted"

    out.loc[mask_gate_high, "final_alert_label"] = "high_priority_alert"
    out.loc[mask_gate_high, "alert_source_layer"] = "gating_likely_malicious"

    out.loc[mask_aug_demoted, "final_alert_label"] = "low_priority_or_background"
    out.loc[mask_aug_demoted, "alert_source_layer"] = "augmentation_demoted"

    out.loc[mask_gate_low, "final_alert_label"] = "low_priority_or_background"
    out.loc[mask_gate_low, "alert_source_layer"] = "gating_likely_benign"

    out.loc[mask_gate_uncertain, "final_alert_label"] = "needs_review"
    out.loc[mask_gate_uncertain, "alert_source_layer"] = "gating_uncertain"
    return out


def append_samples(sample_store: dict[str, list[dict]], batch_df: pd.DataFrame, label: str, limit: int = 10):
    if len(sample_store[label]) >= limit:
        return
    cols = [
        "event_id",
        "prefix",
        "origin_as",
        "as_path_clean",
        "risk_score",
        "gating_label",
        "augmentation_label",
        "final_alert_label",
        "top_contributing_factor",
    ]
    needed = limit - len(sample_store[label])
    rows = batch_df[batch_df["final_alert_label"] == label].head(needed)[cols].to_dict("records")
    sample_store[label].extend(rows)


def print_samples(samples: list[dict], label: str):
    print(f"{label}_samples:")
    if not samples:
        print("  <empty>")
        return
    for row in samples:
        print("  - " + json.dumps(row, ensure_ascii=False))


def finalize_mean_summaries(sum_map: dict[str, float], count_map: dict[str, int]) -> dict[str, float]:
    out = {}
    for label, total in sum_map.items():
        count = count_map.get(label, 0)
        if count:
            out[str(label)] = float(total / count)
    return out


def main():
    ap = argparse.ArgumentParser(description="Streaming final-alert builder for large scored pools.")
    ap.add_argument("--run-id", default=DEFAULT_RUN_ID, help="Run id under data/runs/<run_id>.")
    ap.add_argument("--gating", default=None, help="Path to gated_candidates.parquet.")
    ap.add_argument("--augmentation", default=None, help="Path to augmented_candidates.parquet.")
    ap.add_argument("--scores", default=None, help="Path to scored_candidates.parquet.")
    ap.add_argument("--output-dir", default=None, help="Output directory for final artifacts.")
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

    gating_path = Path(args.gating) if args.gating else Path("data") / "runs" / run_id / "gating" / "gated_candidates.parquet"
    augmentation_path = (
        Path(args.augmentation)
        if args.augmentation
        else Path("data") / "runs" / run_id / "augmentation" / "augmented_candidates.parquet"
    )

    for p in [scores_path, gating_path, augmentation_path]:
        if not p.exists():
            raise SystemExit(f"required input file not found: {p}")

    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = Path("data") / "runs" / run_id / "final"
    output_dir.mkdir(parents=True, exist_ok=True)

    out_parquet = output_dir / "final_alerts.parquet"
    out_report = output_dir / "final_report.json"
    temp_parquet = output_dir / "final_alerts_tmp.parquet"
    if not args.overwrite:
        exists = [p for p in [out_parquet, out_report] if p.exists()]
        if exists:
            raise SystemExit("Output exists, pass --overwrite true to replace: " + ", ".join(to_rel_path(p) for p in exists))
    for path in [out_parquet, out_report, temp_parquet]:
        if path.exists():
            path.unlink()

    gating_df = ensure_gating_columns(
        pd.read_parquet(
            gating_path,
            columns=[
                "event_id",
                "gating_label",
                "gating_explanation",
                "certainty_score",
                "conflict_score",
                "missing_origin_or_path",
            ],
        )
    ).rename(columns={"missing_origin_or_path": "gating_missing_origin_or_path"})
    gating_df = gating_df.set_index("event_id", drop=True)

    aug_df = ensure_augmentation_columns(
        pd.read_parquet(
            augmentation_path,
            columns=[
                "event_id",
                "augmentation_label",
                "augmentation_explanation",
                "evidence_support_score",
            ],
        )
    ).set_index("event_id", drop=True)

    total_scored_rows = 0
    total_gated_rows = int(len(gating_df))
    total_augmented_rows = int(len(aug_df))
    label_counts = {}
    high_priority_from_gating_count = 0
    high_priority_from_augmentation_count = 0
    missing_origin_or_path_in_high_priority = 0
    risk_sum = {}
    risk_count = {}
    evidence_sum = {}
    evidence_count = {}
    samples = {
        "high_priority_alert": [],
        "needs_review": [],
        "low_priority_or_background": [],
    }

    writer = None
    try:
        for batch_df in iter_score_batches(scores_path, args.batch_size):
            total_scored_rows += int(len(batch_df))
            if batch_df.empty:
                continue

            merged = batch_df.join(gating_df, on="event_id", how="left")
            merged = merged.join(aug_df, on="event_id", how="left")

            merged["gating_label"] = merged["gating_label"].fillna("").astype(str)
            merged["augmentation_label"] = merged["augmentation_label"].fillna("").astype(str)
            merged["gating_explanation"] = merged["gating_explanation"].fillna("").astype(str)
            merged["augmentation_explanation"] = merged["augmentation_explanation"].fillna("").astype(str)
            merged["certainty_score"] = pd.to_numeric(merged["certainty_score"], errors="coerce").fillna(0.0)
            merged["conflict_score"] = pd.to_numeric(merged["conflict_score"], errors="coerce").fillna(0.0)
            merged["evidence_support_score"] = pd.to_numeric(merged["evidence_support_score"], errors="coerce")
            merged["gating_missing_origin_or_path"] = merged["gating_missing_origin_or_path"].fillna(False).astype(bool)
            merged["missing_origin_or_path"] = merged["missing_origin_or_path"] | merged["gating_missing_origin_or_path"]

            labeled = decide_labels(merged)
            out_df = labeled[OUTPUT_COLS].copy()

            for label, count in out_df["final_alert_label"].value_counts().to_dict().items():
                label_counts[str(label)] = int(label_counts.get(str(label), 0)) + int(count)

            high_priority_from_gating_count += int(
                ((out_df["final_alert_label"] == "high_priority_alert") & (out_df["alert_source_layer"] == "gating_likely_malicious")).sum()
            )
            high_priority_from_augmentation_count += int(
                ((out_df["final_alert_label"] == "high_priority_alert") & (out_df["alert_source_layer"] == "augmentation_promoted")).sum()
            )
            missing_origin_or_path_in_high_priority += int(
                ((out_df["final_alert_label"] == "high_priority_alert") & (out_df["missing_origin_or_path"])).sum()
            )

            for label, grp in out_df.groupby("final_alert_label", dropna=False):
                label_key = str(label)
                risk_sum[label_key] = float(risk_sum.get(label_key, 0.0) + grp["risk_score"].sum())
                risk_count[label_key] = int(risk_count.get(label_key, 0) + len(grp))

                evidence_series = pd.to_numeric(grp["evidence_support_score"], errors="coerce").dropna()
                evidence_sum[label_key] = float(evidence_sum.get(label_key, 0.0) + evidence_series.sum())
                evidence_count[label_key] = int(evidence_count.get(label_key, 0) + len(evidence_series))

            append_samples(samples, out_df, "high_priority_alert")
            append_samples(samples, out_df, "needs_review")
            append_samples(samples, out_df, "low_priority_or_background")

            table = pa.Table.from_pandas(out_df, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(temp_parquet, table.schema)
            writer.write_table(table)
    finally:
        if writer is not None:
            writer.close()

    if not temp_parquet.exists():
        raise SystemExit("No final outputs were written.")

    temp_parquet.replace(out_parquet)

    high_priority_alert_count = int(label_counts.get("high_priority_alert", 0))
    needs_review_count = int(label_counts.get("needs_review", 0))
    low_priority_or_background_count = int(label_counts.get("low_priority_or_background", 0))

    report = {
        "run_id": run_id,
        "scores_path": to_rel_path(scores_path),
        "gating_path": to_rel_path(gating_path),
        "augmentation_path": to_rel_path(augmentation_path),
        "output_final_alerts_path": to_rel_path(out_parquet),
        "output_final_report_path": to_rel_path(out_report),
        "total_scored_rows": total_scored_rows,
        "total_gated_rows": total_gated_rows,
        "total_augmented_rows": total_augmented_rows,
        "high_priority_alert_count": high_priority_alert_count,
        "needs_review_count": needs_review_count,
        "low_priority_or_background_count": low_priority_or_background_count,
        "high_priority_from_gating_count": high_priority_from_gating_count,
        "high_priority_from_augmentation_count": high_priority_from_augmentation_count,
        "missing_origin_or_path_in_high_priority": missing_origin_or_path_in_high_priority,
        "avg_risk_score_by_final_label": finalize_mean_summaries(risk_sum, risk_count),
        "avg_evidence_support_by_final_label": finalize_mean_summaries(evidence_sum, evidence_count),
    }
    out_report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"run_id: {run_id}")
    print(f"scores_path: {to_rel_path(scores_path)}")
    print(f"gating_path: {to_rel_path(gating_path)}")
    print(f"augmentation_path: {to_rel_path(augmentation_path)}")
    print(f"total_scored_rows: {total_scored_rows}")
    print(f"high_priority_alert: {high_priority_alert_count}")
    print(f"needs_review: {needs_review_count}")
    print(f"low_priority_or_background: {low_priority_or_background_count}")
    print(f"output_final_alerts_path: {to_rel_path(out_parquet)}")
    print(f"output_final_report_path: {to_rel_path(out_report)}")

    print_samples(samples["high_priority_alert"], "high_priority_alert")
    print_samples(samples["needs_review"], "needs_review")
    print_samples(samples["low_priority_or_background"], "low_priority_or_background")


if __name__ == "__main__":
    main()
