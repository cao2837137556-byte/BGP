import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq


QUALITY_THRESHOLDS = {
    "clean_certainty_min": 80.0,
    "noisy_conflict_min": 5.0,
    "noisy_certainty_max_exclusive": 60.0,
}

S1D_EXPANDED_60M_REFERENCE = {
    "label": "s1d_expanded_60m_modern_missing_block",
    "duration_hours": 1.0,
    "candidate_count": 1610525,
    "final_high": 101292,
    "final_needs": 769836,
    "final_low": 739397,
    "high_missing_rate": 0.0,
    "gating_likely_malicious_to_high": 85511,
    "augmentation_promoted_to_high": 15781,
}

FINAL_COLS = [
    "event_id",
    "run_id",
    "prefix",
    "origin_as",
    "risk_score",
    "risk_bucket",
    "gating_label",
    "augmentation_label",
    "final_alert_label",
    "alert_source_layer",
    "top_contributing_factor",
    "missing_origin_or_path",
    "certainty_score",
    "conflict_score",
    "evidence_support_score",
]

EVENT_COLS = [
    "event_id",
    "first_seen",
    "last_seen",
    "duration_sec",
    "record_count",
    "collector_count",
]

AUGMENT_COLS = [
    "event_id",
    "promoted_from_uncertain",
    "demoted_from_uncertain",
    "blocked_missing_promotion",
    "route_leak_review_preserved",
    "multi_view_support_score",
    "historical_deviation_support_score",
    "consistency_recheck_score",
]


def json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def to_bool_series(series: pd.Series) -> pd.Series:
    if series.empty:
        return pd.Series(dtype=bool)
    if series.dtype == bool:
        return series.fillna(False)
    return series.astype(str).str.strip().str.lower().isin({"1", "true", "yes", "y", "on"})


def to_number(df: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in df.columns:
        return pd.Series(default, index=df.index, dtype="float64")
    return pd.to_numeric(df[col], errors="coerce").fillna(default)


def to_text(df: pd.DataFrame, col: str, default: str = "") -> pd.Series:
    if col not in df.columns:
        return pd.Series(default, index=df.index, dtype="object")
    return df[col].fillna(default).astype(str)


def available_columns(path: Path, requested: list[str]) -> list[str]:
    schema_cols = set(pq.ParquetFile(path).schema_arrow.names)
    return [col for col in requested if col in schema_cols]


def read_parquet_existing(path: Path, requested: list[str]) -> pd.DataFrame:
    cols = available_columns(path, requested)
    if not cols:
        raise ValueError(f"none of requested columns exist in {path}: {requested}")
    return pd.read_parquet(path, columns=cols)


def normalize_origin(value) -> str:
    if value is None or pd.isna(value):
        return "NA"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value).strip()
    if numeric.is_integer():
        return str(int(numeric))
    return str(numeric)


def classify_quality_bucket(high_df: pd.DataFrame) -> pd.Series:
    clean_mask = (
        (~high_df["missing_origin_or_path"])
        & (high_df["conflict_score"] == 0.0)
        & (high_df["certainty_score"] >= QUALITY_THRESHOLDS["clean_certainty_min"])
    )
    noisy_mask = (
        high_df["missing_origin_or_path"]
        | (high_df["conflict_score"] >= QUALITY_THRESHOLDS["noisy_conflict_min"])
        | (high_df["certainty_score"] < QUALITY_THRESHOLDS["noisy_certainty_max_exclusive"])
    )
    out = pd.Series("fragile-high", index=high_df.index, dtype="object")
    out.loc[noisy_mask] = "noisy-high"
    out.loc[clean_mask] = "clean-high"
    return out


def add_time_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["first_seen"] = to_number(out, "first_seen")
    out["last_seen"] = to_number(out, "last_seen")
    out["first_seen_dt"] = pd.to_datetime(out["first_seen"], unit="s", utc=True, errors="coerce")
    out["first_seen_hour_utc"] = out["first_seen_dt"].dt.floor("h").dt.strftime("%Y-%m-%dT%H:00:00Z")
    out["first_seen_hour_utc"] = out["first_seen_hour_utc"].fillna("unknown")
    return out


def load_inputs(run_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame | None]:
    final_path = run_dir / "final" / "final_alerts.parquet"
    events_path = run_dir / "events" / "event_units.parquet"
    aug_path = run_dir / "augmentation" / "augmented_candidates.parquet"
    for path in [final_path, events_path]:
        if not path.exists():
            raise SystemExit(f"required input not found: {path}")

    final_df = read_parquet_existing(final_path, FINAL_COLS)
    final_df["event_id"] = to_text(final_df, "event_id")
    final_df["run_id"] = to_text(final_df, "run_id")
    final_df["prefix"] = to_text(final_df, "prefix")
    final_df["origin_as_norm"] = final_df.get("origin_as", pd.Series(index=final_df.index)).map(normalize_origin)
    for col in ["risk_bucket", "gating_label", "augmentation_label", "final_alert_label", "alert_source_layer", "top_contributing_factor"]:
        final_df[col] = to_text(final_df, col)
    final_df["risk_score"] = to_number(final_df, "risk_score")
    final_df["certainty_score"] = to_number(final_df, "certainty_score")
    final_df["conflict_score"] = to_number(final_df, "conflict_score")
    final_df["evidence_support_score"] = to_number(final_df, "evidence_support_score", default=float("nan"))
    final_df["missing_origin_or_path"] = to_bool_series(final_df.get("missing_origin_or_path", pd.Series(False, index=final_df.index)))

    events_df = read_parquet_existing(events_path, EVENT_COLS)
    events_df["event_id"] = to_text(events_df, "event_id")
    for col in ["first_seen", "last_seen", "duration_sec", "record_count", "collector_count"]:
        events_df[col] = to_number(events_df, col)
    events_df = add_time_columns(events_df)

    aug_df = None
    if aug_path.exists():
        aug_cols = available_columns(aug_path, AUGMENT_COLS)
        if aug_cols:
            aug_df = pd.read_parquet(aug_path, columns=aug_cols)
            aug_df["event_id"] = to_text(aug_df, "event_id")
            for col in ["promoted_from_uncertain", "demoted_from_uncertain", "blocked_missing_promotion", "route_leak_review_preserved"]:
                if col in aug_df.columns:
                    aug_df[col] = to_bool_series(aug_df[col])
            for col in ["multi_view_support_score", "historical_deviation_support_score", "consistency_recheck_score"]:
                if col in aug_df.columns:
                    aug_df[col] = to_number(aug_df, col, default=float("nan"))
    return final_df, events_df, aug_df


def group_summary(df: pd.DataFrame, group_cols: list[str], denominator: int, analysis_view: str, limit: int = 200) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    grouped = (
        df.groupby(group_cols, dropna=False)
        .agg(
            count=("event_id", "size"),
            risk_mean=("risk_score", "mean"),
            certainty_mean=("certainty_score", "mean"),
            conflict_mean=("conflict_score", "mean"),
            missing_rate=("missing_origin_or_path", "mean"),
            evidence_mean=("evidence_support_score", "mean"),
            collector_count_mean=("collector_count", "mean"),
            duration_sec_mean=("duration_sec", "mean"),
        )
        .reset_index()
        .sort_values("count", ascending=False)
        .head(limit)
        .reset_index(drop=True)
    )
    grouped["pct_within_high"] = grouped["count"] / denominator if denominator else 0.0
    grouped.insert(0, "analysis_view", analysis_view)
    return grouped


def build_label_summary(final_df: pd.DataFrame, total_events: int) -> pd.DataFrame:
    candidate_count = len(final_df)
    grouped = (
        final_df.groupby("final_alert_label", dropna=False)
        .agg(
            count=("event_id", "size"),
            risk_mean=("risk_score", "mean"),
            certainty_mean=("certainty_score", "mean"),
            conflict_mean=("conflict_score", "mean"),
            missing_rate=("missing_origin_or_path", "mean"),
        )
        .reset_index()
        .sort_values("count", ascending=False)
        .reset_index(drop=True)
    )
    grouped["pct_within_candidates"] = grouped["count"] / candidate_count if candidate_count else 0.0
    grouped["pct_within_events"] = grouped["count"] / total_events if total_events else 0.0
    return grouped


def build_quality_summary(high_df: pd.DataFrame) -> pd.DataFrame:
    if high_df.empty:
        return pd.DataFrame()
    grouped = (
        high_df.groupby("quality_bucket", dropna=False)
        .agg(
            count=("event_id", "size"),
            risk_mean=("risk_score", "mean"),
            certainty_mean=("certainty_score", "mean"),
            conflict_mean=("conflict_score", "mean"),
            missing_rate=("missing_origin_or_path", "mean"),
            evidence_mean=("evidence_support_score", "mean"),
            gating_share=("alert_source_layer", lambda s: (s == "gating_likely_malicious").mean()),
            augmentation_share=("alert_source_layer", lambda s: (s == "augmentation_promoted").mean()),
        )
        .reset_index()
        .sort_values("count", ascending=False)
        .reset_index(drop=True)
    )
    grouped["pct_within_high"] = grouped["count"] / len(high_df) if len(high_df) else 0.0
    return grouped


def build_hourly_summary(final_df: pd.DataFrame, events_df: pd.DataFrame, high_df: pd.DataFrame) -> pd.DataFrame:
    events_hour = events_df.groupby("first_seen_hour_utc", dropna=False).size().rename("total_events")
    candidate_hour = final_df.groupby("first_seen_hour_utc", dropna=False).size().rename("candidate_count")
    label_pivot = (
        final_df.pivot_table(index="first_seen_hour_utc", columns="final_alert_label", values="event_id", aggfunc="size", fill_value=0)
        .rename_axis(None, axis=1)
    )
    source_pivot = (
        high_df.pivot_table(index="first_seen_hour_utc", columns="alert_source_layer", values="event_id", aggfunc="size", fill_value=0)
        .rename_axis(None, axis=1)
    )
    quality_pivot = (
        high_df.pivot_table(index="first_seen_hour_utc", columns="quality_bucket", values="event_id", aggfunc="size", fill_value=0)
        .rename_axis(None, axis=1)
    )
    high_missing = high_df.groupby("first_seen_hour_utc", dropna=False)["missing_origin_or_path"].mean().rename("high_missing_rate")
    high_conflict = high_df.groupby("first_seen_hour_utc", dropna=False)["conflict_score"].mean().rename("high_conflict_mean")
    high_certainty = high_df.groupby("first_seen_hour_utc", dropna=False)["certainty_score"].mean().rename("high_certainty_mean")

    out = pd.concat([events_hour, candidate_hour, label_pivot, source_pivot, quality_pivot, high_missing, high_conflict, high_certainty], axis=1).fillna(0)
    for col in [
        "high_priority_alert",
        "needs_review",
        "low_priority_or_background",
        "gating_likely_malicious",
        "augmentation_promoted",
        "clean-high",
        "fragile-high",
        "noisy-high",
    ]:
        if col not in out.columns:
            out[col] = 0
    out["candidate_rate_vs_events"] = out["candidate_count"] / out["total_events"].where(out["total_events"] != 0, pd.NA)
    out["high_rate_vs_candidates"] = out["high_priority_alert"] / out["candidate_count"].where(out["candidate_count"] != 0, pd.NA)
    out["needs_rate_vs_candidates"] = out["needs_review"] / out["candidate_count"].where(out["candidate_count"] != 0, pd.NA)
    out["low_rate_vs_candidates"] = out["low_priority_or_background"] / out["candidate_count"].where(out["candidate_count"] != 0, pd.NA)
    return out.reset_index().sort_values("first_seen_hour_utc").reset_index(drop=True)


def build_reference_comparison(final_df: pd.DataFrame, high_df: pd.DataFrame, total_events: int, planned_hours: float) -> pd.DataFrame:
    label_counts = final_df["final_alert_label"].value_counts().to_dict()
    source_counts = high_df["alert_source_layer"].value_counts().to_dict()
    s2_values = {
        "candidate_count": int(len(final_df)),
        "final_high": int(label_counts.get("high_priority_alert", 0)),
        "final_needs": int(label_counts.get("needs_review", 0)),
        "final_low": int(label_counts.get("low_priority_or_background", 0)),
        "high_missing_rate": float(high_df["missing_origin_or_path"].mean()) if len(high_df) else 0.0,
        "gating_likely_malicious_to_high": int(source_counts.get("gating_likely_malicious", 0)),
        "augmentation_promoted_to_high": int(source_counts.get("augmentation_promoted", 0)),
    }
    rows = []
    for metric, s2_total in s2_values.items():
        ref_total = S1D_EXPANDED_60M_REFERENCE.get(metric)
        if metric == "high_missing_rate":
            rows.append(
                {
                    "metric": metric,
                    "s1d_60m_value": ref_total,
                    "s2_6h_value": s2_total,
                    "s1d_per_hour": ref_total,
                    "s2_per_hour": s2_total,
                    "s2_vs_s1d_per_hour_ratio": None,
                }
            )
            continue
        s1_per_hour = float(ref_total) / float(S1D_EXPANDED_60M_REFERENCE["duration_hours"]) if ref_total is not None else None
        s2_per_hour = float(s2_total) / planned_hours if planned_hours else None
        rows.append(
            {
                "metric": metric,
                "s1d_60m_value": ref_total,
                "s2_6h_value": s2_total,
                "s1d_per_hour": s1_per_hour,
                "s2_per_hour": s2_per_hour,
                "s2_vs_s1d_per_hour_ratio": (s2_per_hour / s1_per_hour) if s1_per_hour else None,
            }
        )
    rows.append(
        {
            "metric": "candidate_rate_vs_events",
            "s1d_60m_value": None,
            "s2_6h_value": float(len(final_df) / total_events) if total_events else 0.0,
            "s1d_per_hour": None,
            "s2_per_hour": None,
            "s2_vs_s1d_per_hour_ratio": None,
        }
    )
    return pd.DataFrame(rows)


def build_augmented_high_audit(high_df: pd.DataFrame, aug_df: pd.DataFrame | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    aug_high = high_df[high_df["alert_source_layer"] == "augmentation_promoted"].copy()
    if aug_df is not None and not aug_df.empty and not aug_high.empty:
        aug_high = aug_high.merge(aug_df, on="event_id", how="left")
    grouped = group_summary(
        aug_high,
        ["quality_bucket", "augmentation_label", "top_contributing_factor", "risk_bucket"],
        len(aug_high),
        "augmented_high_quality_factor",
        limit=200,
    )
    if not grouped.empty and "multi_view_support_score" in aug_high.columns:
        detail = (
            aug_high.groupby(["quality_bucket", "augmentation_label", "top_contributing_factor", "risk_bucket"], dropna=False)
            .agg(
                multi_view_mean=("multi_view_support_score", "mean"),
                historical_deviation_mean=("historical_deviation_support_score", "mean"),
                consistency_recheck_mean=("consistency_recheck_score", "mean"),
                blocked_missing_promotion_rate=("blocked_missing_promotion", "mean"),
                route_leak_review_preserved_rate=("route_leak_review_preserved", "mean"),
            )
            .reset_index()
        )
        grouped = grouped.merge(detail, on=["quality_bucket", "augmentation_label", "top_contributing_factor", "risk_bucket"], how="left")
    return aug_high, grouped


def build_samples(high_df: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "event_id",
        "first_seen_hour_utc",
        "prefix",
        "origin_as_norm",
        "risk_score",
        "risk_bucket",
        "alert_source_layer",
        "gating_label",
        "augmentation_label",
        "top_contributing_factor",
        "quality_bucket",
        "certainty_score",
        "conflict_score",
        "missing_origin_or_path",
        "evidence_support_score",
        "collector_count",
        "duration_sec",
        "record_count",
    ]
    frames = []
    sample_defs = [
        ("noisy_high_low_certainty", high_df[high_df["quality_bucket"] == "noisy-high"].sort_values("certainty_score", ascending=True)),
        (
            "noisy_high_high_conflict",
            high_df[high_df["quality_bucket"] == "noisy-high"].sort_values("conflict_score", ascending=False),
        ),
        (
            "augmentation_promoted_high",
            high_df[high_df["alert_source_layer"] == "augmentation_promoted"].sort_values("evidence_support_score", ascending=False),
        ),
        (
            "gating_likely_malicious_high",
            high_df[high_df["alert_source_layer"] == "gating_likely_malicious"].sort_values("risk_score", ascending=False),
        ),
    ]
    for bucket, sample_df in sample_defs:
        if sample_df.empty:
            continue
        take = sample_df[[col for col in cols if col in sample_df.columns]].head(20).copy()
        take.insert(0, "sample_bucket", bucket)
        frames.append(take)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["sample_bucket"] + cols)


def markdown_table(df: pd.DataFrame, cols: list[str], limit: int = 10) -> list[str]:
    if df.empty:
        return ["<empty>"]
    use_cols = [col for col in cols if col in df.columns]
    rows = df[use_cols].head(limit).copy()
    lines = []
    lines.append("| " + " | ".join(use_cols) + " |")
    lines.append("| " + " | ".join("---" for _ in use_cols) + " |")
    for row in rows.to_dict("records"):
        values = []
        for col in use_cols:
            value = row.get(col, "")
            if isinstance(value, float):
                values.append(f"{value:.4f}")
            else:
                values.append(str(value))
        lines.append("| " + " | ".join(values) + " |")
    return lines


def write_report(
    path: Path,
    summary: dict,
    label_summary: pd.DataFrame,
    quality_summary: pd.DataFrame,
    source_summary: pd.DataFrame,
    hourly_summary: pd.DataFrame,
    noisy_patterns: pd.DataFrame,
    augmented_summary: pd.DataFrame,
    reference_comparison: pd.DataFrame,
) -> None:
    lines = []
    lines.append("# S2-C Expanded 6h High Composition Audit")
    lines.append("")
    lines.append("## Scope")
    lines.append("")
    lines.append(f"- run_id: `{summary['run_id']}`")
    lines.append("- input: S2-B2 final outputs; no raw/events/baseline/candidate rerun")
    lines.append("- clean-high: `missing=false and conflict=0 and certainty>=80`")
    lines.append("- noisy-high: `missing=true or conflict>=5 or certainty<60`")
    lines.append("- fragile-high: all remaining high records")
    lines.append("")
    lines.append("## Totals")
    lines.append("")
    for key in [
        "total_events",
        "candidate_count",
        "candidate_rate",
        "final_high",
        "final_needs",
        "final_low",
        "high_missing_rate",
        "gating_likely_malicious_to_high",
        "augmentation_promoted_to_high",
    ]:
        value = summary.get(key)
        if isinstance(value, float):
            lines.append(f"- {key}: `{value:.6f}`")
        else:
            lines.append(f"- {key}: `{value}`")
    lines.append("")
    lines.append("## Label Summary")
    lines.append("")
    lines.extend(markdown_table(label_summary, ["final_alert_label", "count", "pct_within_candidates", "pct_within_events", "risk_mean", "missing_rate"]))
    lines.append("")
    lines.append("## High Quality Buckets")
    lines.append("")
    lines.extend(
        markdown_table(
            quality_summary,
            ["quality_bucket", "count", "pct_within_high", "certainty_mean", "conflict_mean", "missing_rate", "gating_share", "augmentation_share"],
        )
    )
    lines.append("")
    lines.append("## Top High Sources")
    lines.append("")
    top_sources = source_summary[source_summary["analysis_view"] == "alert_source_layer"]
    lines.extend(markdown_table(top_sources, ["alert_source_layer", "count", "pct_within_high", "certainty_mean", "conflict_mean", "missing_rate"]))
    lines.append("")
    lines.append("## Hourly Stability")
    lines.append("")
    lines.extend(
        markdown_table(
            hourly_summary,
            [
                "first_seen_hour_utc",
                "total_events",
                "candidate_count",
                "high_priority_alert",
                "needs_review",
                "low_priority_or_background",
                "high_rate_vs_candidates",
                "high_missing_rate",
                "gating_likely_malicious",
                "augmentation_promoted",
            ],
            limit=12,
        )
    )
    lines.append("")
    lines.append("## 60m Reference Comparison")
    lines.append("")
    lines.extend(
        markdown_table(
            reference_comparison,
            ["metric", "s1d_60m_value", "s2_6h_value", "s1d_per_hour", "s2_per_hour", "s2_vs_s1d_per_hour_ratio"],
            limit=20,
        )
    )
    lines.append("")
    lines.append("## Noisy-high Patterns")
    lines.append("")
    lines.extend(
        markdown_table(
            noisy_patterns,
            [
                "alert_source_layer",
                "gating_label",
                "augmentation_label",
                "top_contributing_factor",
                "risk_bucket",
                "count",
                "pct_within_high",
                "certainty_mean",
                "conflict_mean",
                "missing_rate",
            ],
        )
    )
    lines.append("")
    lines.append("## Augmentation-promoted High")
    lines.append("")
    lines.extend(
        markdown_table(
            augmented_summary,
            [
                "quality_bucket",
                "augmentation_label",
                "top_contributing_factor",
                "risk_bucket",
                "count",
                "pct_within_high",
                "evidence_mean",
                "certainty_mean",
                "conflict_mean",
                "missing_rate",
            ],
        )
    )
    lines.append("")
    lines.append("## Interpretation")
    lines.append("")
    lines.append("- S2-B2 already established that score resume reaches final; this audit checks whether the 6h high pool changes composition.")
    lines.append("- `high_missing_rate=0` remains the first-pass stability guard for the modern missing block.")
    lines.append("- If noisy-high is materially larger than the S1-D/S1-F 60m baseline, inspect `s2c_noisy_high_patterns.csv` before expanding to 24h.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="S2-C high composition and purity audit for expanded 6h modern run.")
    ap.add_argument("--run-id", default="s2a_expanded_v01_pilot_6h_april16")
    ap.add_argument("--runs-root", default="data/runs")
    ap.add_argument("--output-dir", default="outputs/s2c_expanded_6h_high_audit_v01")
    ap.add_argument("--planned-hours", type=float, default=6.0)
    args = ap.parse_args()

    run_dir = Path(args.runs_root) / args.run_id
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    final_df, events_df, aug_df = load_inputs(run_dir)
    total_events = int(len(events_df))
    final_df = final_df.merge(
        events_df[["event_id", "first_seen", "last_seen", "duration_sec", "record_count", "collector_count", "first_seen_hour_utc"]],
        on="event_id",
        how="left",
        validate="many_to_one",
    )
    final_df["first_seen_hour_utc"] = final_df["first_seen_hour_utc"].fillna("unknown")
    final_df["collector_count"] = to_number(final_df, "collector_count")
    final_df["duration_sec"] = to_number(final_df, "duration_sec")
    final_df["record_count"] = to_number(final_df, "record_count")

    high_df = final_df[final_df["final_alert_label"] == "high_priority_alert"].copy()
    high_df["quality_bucket"] = classify_quality_bucket(high_df)

    label_counts = final_df["final_alert_label"].value_counts().to_dict()
    source_counts = high_df["alert_source_layer"].value_counts().to_dict()
    quality_counts = high_df["quality_bucket"].value_counts().to_dict()
    summary = {
        "run_id": args.run_id,
        "run_dir": str(run_dir),
        "total_events": total_events,
        "candidate_count": int(len(final_df)),
        "candidate_rate": float(len(final_df) / total_events) if total_events else 0.0,
        "final_high": int(label_counts.get("high_priority_alert", 0)),
        "final_needs": int(label_counts.get("needs_review", 0)),
        "final_low": int(label_counts.get("low_priority_or_background", 0)),
        "high_missing_rate": float(high_df["missing_origin_or_path"].mean()) if len(high_df) else 0.0,
        "high_certainty_mean": float(high_df["certainty_score"].mean()) if len(high_df) else 0.0,
        "high_conflict_mean": float(high_df["conflict_score"].mean()) if len(high_df) else 0.0,
        "gating_likely_malicious_to_high": int(source_counts.get("gating_likely_malicious", 0)),
        "augmentation_promoted_to_high": int(source_counts.get("augmentation_promoted", 0)),
        "clean_high": int(quality_counts.get("clean-high", 0)),
        "fragile_high": int(quality_counts.get("fragile-high", 0)),
        "noisy_high": int(quality_counts.get("noisy-high", 0)),
        "planned_hours": float(args.planned_hours),
    }

    label_summary = build_label_summary(final_df, total_events)
    quality_summary = build_quality_summary(high_df)
    source_frames = [
        group_summary(high_df, ["alert_source_layer"], len(high_df), "alert_source_layer"),
        group_summary(high_df, ["gating_label"], len(high_df), "gating_label"),
        group_summary(high_df, ["augmentation_label"], len(high_df), "augmentation_label"),
        group_summary(high_df, ["risk_bucket"], len(high_df), "risk_bucket"),
        group_summary(high_df, ["top_contributing_factor"], len(high_df), "top_contributing_factor"),
        group_summary(
            high_df,
            ["quality_bucket", "alert_source_layer", "gating_label", "augmentation_label", "top_contributing_factor", "risk_bucket"],
            len(high_df),
            "combined_high_patterns",
        ),
    ]
    source_summary = pd.concat([frame for frame in source_frames if not frame.empty], ignore_index=True, sort=False)

    noisy_patterns = group_summary(
        high_df[high_df["quality_bucket"] == "noisy-high"].copy(),
        ["alert_source_layer", "gating_label", "augmentation_label", "top_contributing_factor", "risk_bucket"],
        len(high_df),
        "noisy_high_patterns",
        limit=200,
    )
    hourly_summary = build_hourly_summary(final_df, events_df, high_df)
    reference_comparison = build_reference_comparison(final_df, high_df, total_events, args.planned_hours)
    aug_high, augmented_summary = build_augmented_high_audit(high_df, aug_df)

    top_prefix_origin = (
        high_df.groupby(["prefix", "origin_as_norm"], dropna=False)
        .agg(
            high_count=("event_id", "size"),
            gating_high=("alert_source_layer", lambda s: int((s == "gating_likely_malicious").sum())),
            augmentation_high=("alert_source_layer", lambda s: int((s == "augmentation_promoted").sum())),
            risk_mean=("risk_score", "mean"),
            certainty_mean=("certainty_score", "mean"),
            conflict_mean=("conflict_score", "mean"),
            missing_rate=("missing_origin_or_path", "mean"),
            first_hour=("first_seen_hour_utc", "min"),
            last_hour=("first_seen_hour_utc", "max"),
        )
        .reset_index()
        .sort_values("high_count", ascending=False)
        .head(200)
        .reset_index(drop=True)
    )
    samples = build_samples(high_df)

    label_summary.to_csv(output_dir / "s2c_label_summary.csv", index=False, encoding="utf-8-sig")
    quality_summary.to_csv(output_dir / "s2c_high_quality_buckets.csv", index=False, encoding="utf-8-sig")
    source_summary.to_csv(output_dir / "s2c_high_source_buckets.csv", index=False, encoding="utf-8-sig")
    noisy_patterns.to_csv(output_dir / "s2c_noisy_high_patterns.csv", index=False, encoding="utf-8-sig")
    hourly_summary.to_csv(output_dir / "s2c_hourly_summary.csv", index=False, encoding="utf-8-sig")
    reference_comparison.to_csv(output_dir / "s2c_s1d_reference_comparison.csv", index=False, encoding="utf-8-sig")
    augmented_summary.to_csv(output_dir / "s2c_augmented_high_audit.csv", index=False, encoding="utf-8-sig")
    top_prefix_origin.to_csv(output_dir / "s2c_top_prefix_origin_high.csv", index=False, encoding="utf-8-sig")
    samples.to_csv(output_dir / "s2c_high_samples.csv", index=False, encoding="utf-8-sig")
    (output_dir / "s2c_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=json_default), encoding="utf-8")
    write_report(
        output_dir / "s2c_high_composition_audit_report.md",
        summary,
        label_summary,
        quality_summary,
        source_summary,
        hourly_summary,
        noisy_patterns,
        augmented_summary,
        reference_comparison,
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2, default=json_default), flush=True)
    print(f"output_dir={output_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
