"""Audit Raw Incident prototype aggregation quality.

R-AGG-3 is a read-only audit over R-AGG-2 Raw Incident prototypes. It estimates
fragmentation, background-like operational candidates, safe merge opportunity,
high-value retention risk, and family_hint quality without modifying any
pipeline output or implementing merge/filter logic.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq


MISSING = "missing"
STRONG_REASON_TOKENS = [
    "new_origin",
    "origin_change",
    "unseen_path",
    "path_change",
    "path_len",
    "leak",
    "valley",
    "triplet",
    "no_export",
    "community",
    "low_visibility",
    "single_collector",
]

OUTPUT_FILES = [
    "r_agg_3_summary.json",
    "key_fragmentation_audit.csv",
    "background_candidate_audit.csv",
    "merge_opportunity_audit.csv",
    "high_value_retention_audit.csv",
    "family_hint_quality_audit.csv",
    "raw_incident_quality_sample.csv",
    "raw_incident_quality_report.md",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit R-AGG-2 Raw Incident aggregation quality.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--raw-incidents", default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--sample-size", type=int, default=10000)
    parser.add_argument("--top-n", type=int, default=50)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def resolve_input(run_id: str, explicit: str | None) -> Path:
    path = Path(explicit) if explicit else Path("outputs") / "r_agg_2" / run_id / "raw_incidents_prototype.parquet"
    if not path.exists():
        raise FileNotFoundError(f"raw incidents parquet not found: {path}")
    return path


def prepare_output_dir(output_dir: Path, overwrite: bool) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    existing = [output_dir / name for name in OUTPUT_FILES if (output_dir / name).exists()]
    if existing and not overwrite:
        raise FileExistsError(
            "output files already exist; pass --overwrite to replace: "
            + ", ".join(str(path) for path in existing)
        )


def load_raw_incidents(path: Path) -> pd.DataFrame:
    wanted = [
        "raw_incident_id",
        "source_row_count",
        "start_time",
        "end_time",
        "duration_sec",
        "time_bucket_key",
        "time_repair_status",
        "dominant_prefix",
        "dominant_origin_as",
        "prefix_origin_key",
        "dominant_as_path_signature",
        "collector_set",
        "collector_count",
        "visibility_mode",
        "aggregation_key",
        "aggregation_reason",
        "member_event_count",
        "member_candidate_count",
        "candidate_reason_set",
        "trigger_reason_set",
        "family_hint",
        "weak_signal_tags",
        "mixedness_hint",
        "aggregation_confidence",
        "dominant_component_share",
        "split_needed_hint",
        "evidence_grounding_ready",
    ]
    schema_names = set(pq.ParquetFile(path).schema.names)
    columns = [column for column in wanted if column in schema_names]
    return pd.read_parquet(path, columns=columns, engine="pyarrow")


def parse_json_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    if isinstance(value, float) and math.isnan(value):
        return []
    text = str(value).strip()
    if not text or text in {MISSING, "nan", "None"}:
        return []
    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(item) for item in parsed if item is not None]
        except json.JSONDecodeError:
            pass
    return [text]


def normalize_text(series: pd.Series) -> pd.Series:
    return series.fillna(MISSING).astype(str)


def list_text(series: pd.Series) -> pd.Series:
    return normalize_text(series).str.lower()


def contains_any(series: pd.Series, tokens: list[str]) -> pd.Series:
    text = list_text(series)
    result = pd.Series(False, index=series.index)
    for token in tokens:
        result = result | text.str.contains(token, regex=False)
    return result


def safe_ratio(numerator: float, denominator: float) -> float:
    return round(float(numerator / denominator), 6) if denominator else 0.0


def join_key(df: pd.DataFrame, fields: list[str]) -> pd.Series:
    if not fields:
        return pd.Series([MISSING] * len(df), index=df.index)
    parts = [normalize_text(df[field]) if field in df.columns else pd.Series(MISSING, index=df.index) for field in fields]
    key = parts[0]
    for part in parts[1:]:
        key = key + "|" + part
    return key


def over_fragmentation_risk(compression_ratio: float) -> str:
    if compression_ratio >= 10:
        return "high"
    if compression_ratio >= 3:
        return "medium"
    if compression_ratio > 1.25:
        return "low"
    return "minimal"


def audit_key_fragmentation(df: pd.DataFrame, source_row_count: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    raw_count = len(df)
    unique_counts = {
        "unique_prefix_origin_key": int(df["prefix_origin_key"].nunique(dropna=True)),
        "unique_dominant_as_path_signature": int(df["dominant_as_path_signature"].nunique(dropna=True)),
        "unique_candidate_reason_set": int(df["candidate_reason_set"].nunique(dropna=True)),
        "unique_collector_set": int(df["collector_set"].nunique(dropna=True)),
        "unique_time_bucket_key": int(df["time_bucket_key"].nunique(dropna=True)),
    }
    strategies = [
        ("prefix_origin_key", ["prefix_origin_key"]),
        ("prefix_origin_key+family_hint", ["prefix_origin_key", "family_hint"]),
        ("prefix_origin_key+dominant_as_path_signature", ["prefix_origin_key", "dominant_as_path_signature"]),
        ("prefix_origin_key+family_hint+dominant_as_path_signature", ["prefix_origin_key", "family_hint", "dominant_as_path_signature"]),
        ("prefix_origin_key+family_hint+time_bucket_key", ["prefix_origin_key", "family_hint", "time_bucket_key"]),
        ("prefix_origin_key+family_hint+collector_set", ["prefix_origin_key", "family_hint", "collector_set"]),
    ]
    rows = []
    best = None
    for name, fields in strategies:
        group_count = int(join_key(df, fields).nunique(dropna=True))
        compression = safe_ratio(source_row_count, group_count)
        row = {
            "key_strategy": name,
            "key_fields": "+".join(fields),
            "raw_incident_count": raw_count,
            **unique_counts,
            "hypothetical_group_count": group_count,
            "hypothetical_compression_ratio": compression,
            "over_fragmentation_risk": over_fragmentation_risk(compression),
        }
        rows.append(row)
        if best is None or group_count > best["hypothetical_group_count"]:
            # For safety, prefer the finest candidate among meaningfully merged keys.
            best = row
    return pd.DataFrame(rows), {"unique_counts": unique_counts}


def background_risk_score(df: pd.DataFrame) -> pd.Series:
    reason_text = list_text(df["candidate_reason_set"])
    weak_text = list_text(df["weak_signal_tags"])
    single_collector = df["collector_count"].fillna(0).astype(float).le(1)
    family_backgroundish = df["family_hint"].isin(["mixed_unknown", "background_like_pattern", "stealth_visibility_like"])
    no_clear_forged_path = ~contains_any(
        reason_text,
        ["new_origin", "origin_change", "leak", "valley", "triplet", "path_change", "path_manipulation"],
    )
    low_conf = pd.to_numeric(df["aggregation_confidence"], errors="coerce").fillna(0).lt(0.8)
    reason_missing = reason_text.isin(["[]", MISSING.lower(), ""])
    weak_missing = weak_text.isin(["[]", MISSING.lower(), ""])
    score = (
        family_backgroundish.astype(float) * 0.25
        + single_collector.astype(float) * 0.20
        + no_clear_forged_path.astype(float) * 0.20
        + low_conf.astype(float) * 0.20
        + reason_missing.astype(float) * 0.10
        + weak_missing.astype(float) * 0.05
    )
    return score.round(6)


def background_reason(df: pd.DataFrame, score: pd.Series) -> pd.Series:
    reason_text = list_text(df["candidate_reason_set"])
    reasons = []
    single_collector = df["collector_count"].fillna(0).astype(float).le(1)
    for idx, row in df.iterrows():
        parts = []
        if row.get("family_hint") in {"mixed_unknown", "background_like_pattern", "stealth_visibility_like"}:
            parts.append("backgroundish_family_hint")
        if single_collector.loc[idx]:
            parts.append("single_collector")
        if row.get("aggregation_confidence", 0) < 0.8:
            parts.append("low_aggregation_confidence")
        if reason_text.loc[idx] in {"[]", MISSING.lower(), ""}:
            parts.append("candidate_reason_missing")
        if not parts:
            parts.append("low_background_like_risk")
        reasons.append(";".join(parts))
    return pd.Series(reasons, index=df.index)


def audit_background_candidates(df: pd.DataFrame, output_dir: Path, sample_size: int) -> dict[str, Any]:
    score = background_risk_score(df)
    candidate = score.ge(0.45)
    audit = df.loc[candidate, [
        "raw_incident_id",
        "family_hint",
        "collector_count",
        "visibility_mode",
        "aggregation_confidence",
        "candidate_reason_set",
        "weak_signal_tags",
    ]].copy()
    audit["background_like_risk_score"] = score.loc[audit.index]
    audit = audit.sort_values(["background_like_risk_score", "aggregation_confidence"], ascending=[False, True])
    audit = audit.head(sample_size).copy()
    audit["background_like_reason"] = background_reason(audit, score.loc[audit.index])
    audit.head(sample_size).to_csv(output_dir / "background_candidate_audit.csv", index=False)

    single_no_clear = (
        df["collector_count"].fillna(0).astype(float).le(1)
        & ~contains_any(df["candidate_reason_set"], ["new_origin", "origin_change", "leak", "valley", "triplet", "path_change"])
    )
    low_conf_mixed = df["family_hint"].eq("mixed_unknown") & pd.to_numeric(df["aggregation_confidence"], errors="coerce").fillna(0).lt(0.8)
    return {
        "possible_background_like_count": int(candidate.sum()),
        "possible_background_like_rate": safe_ratio(int(candidate.sum()), len(df)),
        "family_backgroundish_rate": safe_ratio(int(df["family_hint"].isin(["mixed_unknown", "background_like_pattern", "stealth_visibility_like"]).sum()), len(df)),
        "candidate_reason_missing_rate": safe_ratio(int(list_text(df["candidate_reason_set"]).isin(["[]", MISSING.lower(), ""]).sum()), len(df)),
        "weak_signal_tags_missing_rate": safe_ratio(int(list_text(df["weak_signal_tags"]).isin(["[]", MISSING.lower(), ""]).sum()), len(df)),
        "single_collector_no_clear_forged_path_count": int(single_no_clear.sum()),
        "low_confidence_mixed_unknown_count": int(low_conf_mixed.sum()),
        "member_candidate_count_distribution": df["member_candidate_count"].describe(percentiles=[0.5, 0.9, 0.99]).to_dict(),
        "collector_count_distribution": df["collector_count"].value_counts().head(20).to_dict(),
        "visibility_mode_distribution": df["visibility_mode"].value_counts().to_dict(),
    }


def merge_safety(row: pd.Series) -> str:
    if row["prefix_count"] == 0 or row["origin_count"] == 0:
        return "unknown"
    if row["prefix_count"] > 1 or row["origin_count"] > 1:
        return "risky_mixed"
    if row["family_hint_count"] > 1 or row["path_signature_count"] > 5 or row["collector_set_count"] > 3:
        return "risky_mixed"
    if row["raw_incident_count_in_group"] > 1 and row["path_signature_count"] <= 3 and row["collector_set_count"] <= 2:
        return "safe_candidate"
    return "unknown"


def audit_merge_opportunities(df: pd.DataFrame, output_dir: Path, top_n: int) -> dict[str, Any]:
    work = df.copy()
    work["start_dt"] = pd.to_datetime(work["start_time"], utc=True, errors="coerce")
    work["end_dt"] = pd.to_datetime(work["end_time"], utc=True, errors="coerce")
    work["merge_group_key"] = join_key(work, ["prefix_origin_key", "family_hint", "dominant_as_path_signature", "collector_set"])
    grouped = work.groupby("merge_group_key", dropna=False).agg(
        raw_incident_count_in_group=("raw_incident_id", "count"),
        start_time=("start_dt", "min"),
        end_time=("end_dt", "max"),
        prefix_count=("dominant_prefix", "nunique"),
        origin_count=("dominant_origin_as", "nunique"),
        path_signature_count=("dominant_as_path_signature", "nunique"),
        collector_set_count=("collector_set", "nunique"),
        family_hint_count=("family_hint", "nunique"),
        family_hint_set=("family_hint", lambda s: json.dumps(sorted(set(s.dropna().astype(str))), ensure_ascii=True)),
    ).reset_index()
    grouped = grouped[grouped["raw_incident_count_in_group"] > 1].copy()
    grouped["time_span_sec"] = (grouped["end_time"] - grouped["start_time"]).dt.total_seconds().fillna(0).astype(float)
    grouped["merge_safety_hint"] = grouped.apply(merge_safety, axis=1)
    grouped["merge_reason"] = grouped["merge_safety_hint"].map({
        "safe_candidate": "same_prefix_origin_family_path_collector_repeated_across_time",
        "risky_mixed": "mixed_prefix_origin_family_path_or_collector",
        "unknown": "insufficient_or_singleton_signal",
    })
    output_cols = [
        "merge_group_key",
        "raw_incident_count_in_group",
        "time_span_sec",
        "prefix_count",
        "origin_count",
        "path_signature_count",
        "collector_set_count",
        "family_hint_set",
        "merge_safety_hint",
        "merge_reason",
    ]
    grouped = grouped.sort_values(["raw_incident_count_in_group", "time_span_sec"], ascending=[False, False])
    grouped[output_cols].head(top_n).to_csv(output_dir / "merge_opportunity_audit.csv", index=False)
    safe = grouped[grouped["merge_safety_hint"] == "safe_candidate"]
    estimated_safe_group_count = int(len(df) - (safe["raw_incident_count_in_group"] - 1).sum())
    source_rows = int(df["source_row_count"].dropna().iloc[0]) if "source_row_count" in df and df["source_row_count"].notna().any() else len(df)
    return {
        "merge_opportunity_group_count": int(len(grouped)),
        "safe_candidate_group_count": int(len(safe)),
        "risky_mixed_group_count": int((grouped["merge_safety_hint"] == "risky_mixed").sum()),
        "unknown_group_count": int((grouped["merge_safety_hint"] == "unknown").sum()),
        "estimated_best_safe_group_count": estimated_safe_group_count,
        "estimated_best_safe_compression_ratio": safe_ratio(source_rows, estimated_safe_group_count),
        "safe_merge_reduction_count": int((safe["raw_incident_count_in_group"] - 1).sum()) if not safe.empty else 0,
    }


def audit_high_value_retention(df: pd.DataFrame, output_dir: Path, sample_size: int, background_score: pd.Series) -> dict[str, Any]:
    reason_text = list_text(df["candidate_reason_set"])
    high_family = df["family_hint"].isin(["forged_origin_like", "route_leak_like", "path_manipulation_like"])
    stealth_strong = df["family_hint"].eq("stealth_visibility_like") & contains_any(reason_text, ["low_visibility", "single_collector", "no_export", "community", "unseen_path"])
    strong_reason = contains_any(reason_text, STRONG_REASON_TOKENS)
    high_conf = pd.to_numeric(df["aggregation_confidence"], errors="coerce").fillna(0).ge(0.9)
    high_value = high_family | stealth_strong | strong_reason | high_conf
    background_like = background_score.ge(0.45)
    risky_suppression = high_value & background_like

    audit = df.loc[high_value, [
        "raw_incident_id",
        "family_hint",
        "collector_count",
        "visibility_mode",
        "aggregation_confidence",
        "candidate_reason_set",
        "weak_signal_tags",
        "prefix_origin_key",
        "dominant_as_path_signature",
    ]].copy()
    audit["overlap_with_background_like"] = background_like.loc[audit.index].values
    audit["background_like_risk_score"] = background_score.loc[audit.index].values
    audit = audit.sort_values(["overlap_with_background_like", "aggregation_confidence"], ascending=[False, False])
    audit.head(sample_size).to_csv(output_dir / "high_value_retention_audit.csv", index=False)

    reason_counts = {}
    for token in STRONG_REASON_TOKENS:
        reason_counts[token] = int((high_value & reason_text.str.contains(token, regex=False)).sum())
    return {
        "high_value_candidate_count": int(high_value.sum()),
        "high_value_by_family_hint": df.loc[high_value, "family_hint"].value_counts().to_dict(),
        "high_value_by_reason": reason_counts,
        "overlap_with_background_like": int((high_value & background_like).sum()),
        "risky_suppression_count": int(risky_suppression.sum()),
        "examples": audit.head(10).to_dict(orient="records"),
    }


def audit_family_hint_quality(df: pd.DataFrame, output_dir: Path) -> dict[str, Any]:
    mixed = df["family_hint"].eq("mixed_unknown")
    reason_text = list_text(df["candidate_reason_set"])
    weak_text = list_text(df["weak_signal_tags"])
    mixed_df = df[mixed]
    reason_missing = reason_text[mixed].isin(["[]", MISSING.lower(), ""])
    weak_missing = weak_text[mixed].isin(["[]", MISSING.lower(), ""])
    has_prefix = normalize_text(mixed_df["prefix_origin_key"]).ne(MISSING)
    has_path = normalize_text(mixed_df["dominant_as_path_signature"]).ne(MISSING)
    has_collector = pd.to_numeric(mixed_df["collector_count"], errors="coerce").fillna(0).gt(0)
    visibility_path_mix = mixed & contains_any(reason_text, ["single_collector", "low_visibility"]) & contains_any(reason_text, ["unseen_path", "path"])
    origin_path_mix = mixed & contains_any(reason_text, ["origin"]) & contains_any(reason_text, ["path"])
    rule_gap = mixed & ~reason_missing.reindex(df.index, fill_value=False)

    rows = []
    for family, count in df["family_hint"].value_counts().items():
        rows.append({
            "metric": "family_hint_distribution",
            "family_hint": family,
            "count": int(count),
            "rate": safe_ratio(int(count), len(df)),
            "notes": "",
        })
    rows.extend([
        {
            "metric": "mixed_unknown_candidate_reason_missing_rate",
            "family_hint": "mixed_unknown",
            "count": int(reason_missing.sum()),
            "rate": safe_ratio(int(reason_missing.sum()), int(mixed.sum())),
            "notes": "candidate_reason_set missing among mixed_unknown",
        },
        {
            "metric": "mixed_unknown_weak_signal_missing_rate",
            "family_hint": "mixed_unknown",
            "count": int(weak_missing.sum()),
            "rate": safe_ratio(int(weak_missing.sum()), int(mixed.sum())),
            "notes": "weak_signal_tags missing among mixed_unknown",
        },
        {
            "metric": "mixed_unknown_complete_core_keys_rate",
            "family_hint": "mixed_unknown",
            "count": int((has_prefix & has_path & has_collector).sum()),
            "rate": safe_ratio(int((has_prefix & has_path & has_collector).sum()), int(mixed.sum())),
            "notes": "prefix/path/collector complete despite mixed_unknown",
        },
        {
            "metric": "mixed_unknown_visibility_path_mix",
            "family_hint": "mixed_unknown",
            "count": int(visibility_path_mix.sum()),
            "rate": safe_ratio(int(visibility_path_mix.sum()), int(mixed.sum())),
            "notes": "likely rule priority gap: visibility + path signals collapsed to mixed_unknown",
        },
        {
            "metric": "mixed_unknown_origin_path_mix",
            "family_hint": "mixed_unknown",
            "count": int(origin_path_mix.sum()),
            "rate": safe_ratio(int(origin_path_mix.sum()), int(mixed.sum())),
            "notes": "likely rule priority gap: origin + path signals collapsed to mixed_unknown",
        },
    ])
    pd.DataFrame(rows).to_csv(output_dir / "family_hint_quality_audit.csv", index=False)

    suggested_rules = [
        "Treat single_collector_visibility as observability_mode unless no stronger reason exists.",
        "Map unseen_path_for_prefix_origin primarily to path_manipulation_like or path-review hint, with visibility as secondary tag.",
        "Map origin-change/new-origin reasons to forged_origin_like before visibility tags.",
        "Keep multi-family cases as mixed_unknown only when two attack-family hints conflict after separating observability tags.",
    ]
    return {
        "mixed_unknown_count": int(mixed.sum()),
        "mixed_unknown_candidate_reason_missing_rate": safe_ratio(int(reason_missing.sum()), int(mixed.sum())),
        "mixed_unknown_weak_signal_missing_rate": safe_ratio(int(weak_missing.sum()), int(mixed.sum())),
        "mixed_unknown_core_keys_complete_rate": safe_ratio(int((has_prefix & has_path & has_collector).sum()), int(mixed.sum())),
        "mixed_unknown_visibility_path_mix_count": int(visibility_path_mix.sum()),
        "mixed_unknown_origin_path_mix_count": int(origin_path_mix.sum()),
        "mixed_unknown_likely_rule_gap_count": int(rule_gap.sum()),
        "mixed_unknown_reason_summary": {
            "candidate_reason_missing": int(reason_missing.sum()),
            "weak_signal_missing": int(weak_missing.sum()),
            "core_keys_complete": int((has_prefix & has_path & has_collector).sum()),
            "visibility_path_mix": int(visibility_path_mix.sum()),
            "origin_path_mix": int(origin_path_mix.sum()),
            "interpretation": "mixed_unknown is mostly a family_hint mapping/priority issue, not missing core keys",
        },
        "suggested_family_hint_mapping_rules": suggested_rules,
    }


def write_quality_sample(df: pd.DataFrame, output_dir: Path, sample_size: int, background_score: pd.Series) -> None:
    sample = df.head(sample_size).copy()
    sample["background_like_risk_score"] = background_score.loc[sample.index].values
    keep = [
        "raw_incident_id",
        "prefix_origin_key",
        "dominant_as_path_signature",
        "time_bucket_key",
        "family_hint",
        "collector_count",
        "visibility_mode",
        "aggregation_confidence",
        "member_candidate_count",
        "candidate_reason_set",
        "background_like_risk_score",
    ]
    sample[keep].to_csv(output_dir / "raw_incident_quality_sample.csv", index=False)


def write_report(output_dir: Path, summary: dict[str, Any]) -> None:
    report = f"""# R-AGG-3 Raw Incident Quality Report

Status: completed.

This is a read-only Raw Incident aggregation quality audit. It does not produce
truth labels, attach external evidence, train learning, implement safe merge, or
perform background suppression.

## Key Results

- raw_incident_count: `{summary['raw_incident_count']}`
- estimated_best_safe_group_count: `{summary['estimated_best_safe_group_count']}`
- estimated_best_safe_compression_ratio: `{summary['estimated_best_safe_compression_ratio']}`
- possible_background_like_count: `{summary['possible_background_like_count']}`
- possible_background_like_rate: `{summary['possible_background_like_rate']}`
- high_value_candidate_count: `{summary['high_value_candidate_count']}`
- risky_suppression_count: `{summary['risky_suppression_count']}`
- mixed_unknown_count: `{summary['mixed_unknown_count']}`

## Conclusion

- candidate-entry full aggregation is feasible, but R-AGG-2 key v0 is too fine
  for paper-facing incident compression.
- There is safe merge opportunity, but it must be designed explicitly in
  R-AGG-4 and validated before changing aggregation output.
- A pre-incident filter may be useful, but background-like is operational
  suppression candidate, not confirmed benign.
- family_hint is semantic hint, not attack label.
- poisoning benchmark retained.
- learning layer postponed and must target BEAM-style semantic learning.

Recommended next step: `{summary['recommended_next_step']}`.
"""
    (output_dir / "raw_incident_quality_report.md").write_text(report, encoding="utf-8")


def choose_next_step(summary: dict[str, Any]) -> str:
    if summary["mixed_unknown_count"] / max(1, summary["raw_incident_count"]) > 0.4:
        return "R-AGG-4 family_hint mapping repair before safe merge"
    if summary["possible_background_like_rate"] > 0.5:
        return "R-AGG-4 pre-incident background filter design"
    return "R-AGG-4 safe merge key design"


def main() -> None:
    args = parse_args()
    if args.sample_size <= 0:
        raise ValueError("--sample-size must be positive")
    if args.top_n <= 0:
        raise ValueError("--top-n must be positive")

    raw_path = resolve_input(args.run_id, args.raw_incidents)
    output_dir = Path(args.output_dir) if args.output_dir else Path("outputs") / "r_agg_3" / args.run_id
    prepare_output_dir(output_dir, args.overwrite)

    df = load_raw_incidents(raw_path)
    source_row_count = int(df["source_row_count"].dropna().iloc[0]) if "source_row_count" in df and df["source_row_count"].notna().any() else len(df)

    key_df, key_summary = audit_key_fragmentation(df, source_row_count)
    key_df.to_csv(output_dir / "key_fragmentation_audit.csv", index=False)

    background_score = background_risk_score(df)
    background_summary = audit_background_candidates(df, output_dir, args.sample_size)
    merge_summary = audit_merge_opportunities(df, output_dir, args.top_n)
    high_value_summary = audit_high_value_retention(df, output_dir, args.sample_size, background_score)
    family_summary = audit_family_hint_quality(df, output_dir)
    write_quality_sample(df, output_dir, args.sample_size, background_score)

    summary = {
        "phase": "R-AGG-3",
        "status": "completed",
        "run_id": args.run_id,
        "raw_incidents_path": str(raw_path),
        "raw_incident_count": int(len(df)),
        "source_row_count": source_row_count,
        **key_summary["unique_counts"],
        **merge_summary,
        **background_summary,
        **high_value_summary,
        **family_summary,
        "clear_conclusion": {
            "candidate_entry_full_aggregation_controllable": True,
            "pre_incident_filter_needed": background_summary["possible_background_like_rate"] > 0.5,
            "safe_merge_space_exists": merge_summary["safe_candidate_group_count"] > 0,
            "notes": "audit only; no safe merge/filter implemented",
        },
        "safety": {
            "no_truth_label": True,
            "no_external_evidence_attached": True,
            "learning_trained": False,
            "final_entry_used_as_primary": False,
            "safe_merge_implemented": False,
            "background_suppression_implemented": False,
        },
    }
    summary["recommended_next_step"] = choose_next_step(summary)
    (output_dir / "r_agg_3_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    write_report(output_dir, summary)

    print(json.dumps({
        "status": "completed",
        "phase": "R-AGG-3",
        "raw_incident_count": summary["raw_incident_count"],
        "estimated_best_safe_compression_ratio": summary["estimated_best_safe_compression_ratio"],
        "possible_background_like_rate": summary["possible_background_like_rate"],
        "mixed_unknown_count": summary["mixed_unknown_count"],
        "recommended_next_step": summary["recommended_next_step"],
        "output_dir": str(output_dir),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
