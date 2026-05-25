#!/usr/bin/env python
"""Audit possible entry points for Raw Incident Dossier construction.

This script is read-only. It compares old seven-layer pipeline artifacts as
candidate inputs for a future Raw Incident Dossier, without treating any legacy
label as truth and without modifying pipeline outputs.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq


ENTRY_SPECS = {
    "event-entry": ("events", "event_units.parquet"),
    "candidate-entry": ("candidates", "candidate_events.parquet"),
    "scored-entry": ("scores", "scored_candidates.parquet"),
    "gated-entry": ("gating", "gated_candidates.parquet"),
    "augmented-entry": ("augmentation", "augmented_candidates.parquet"),
    "final-entry": ("final", "final_alerts.parquet"),
}

ENTRY_ORDER = list(ENTRY_SPECS)

JUDGMENT_FIELDS = {
    "final_alert_label",
    "gating_label",
    "augmentation_label",
    "risk_bucket",
    "risk_score",
    "certainty_score",
    "conflict_score",
    "evidence_support_score",
    "alert_source_layer",
}

REASON_FIELDS = [
    "trigger_reasons",
    "candidate_reasons",
    "legacy_reasons",
    "score_explanation",
    "gating_explanation",
    "augmentation_explanation",
]

TIME_FIELDS = ["first_seen", "last_seen", "start_time", "end_time", "ts", "timestamp"]
PATH_FIELDS = ["as_path_signature", "as_path_clean", "dominant_path_signature", "path_signature"]


@dataclass
class EntryPaths:
    entry: str
    path: Path | None
    status: str
    note: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--events", default="")
    parser.add_argument("--candidates", default="")
    parser.add_argument("--scores", default="")
    parser.add_argument("--gating", default="")
    parser.add_argument("--augmentation", default="")
    parser.add_argument("--final", default="")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--sample-size", type=int, default=10_000)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def resolve_paths(args: argparse.Namespace) -> dict[str, EntryPaths]:
    explicit = {
        "event-entry": args.events,
        "candidate-entry": args.candidates,
        "scored-entry": args.scores,
        "gated-entry": args.gating,
        "augmented-entry": args.augmentation,
        "final-entry": args.final,
    }
    run_root = Path("data") / "runs" / args.run_id
    resolved: dict[str, EntryPaths] = {}
    for entry, (subdir, filename) in ENTRY_SPECS.items():
        if explicit[entry]:
            path = Path(explicit[entry])
            source = "explicit"
        else:
            path = run_root / subdir / filename
            source = "auto"
        if path.exists():
            resolved[entry] = EntryPaths(entry, path, "present", f"{source} path")
        else:
            resolved[entry] = EntryPaths(entry, path, "missing", f"{source} path not found")
    return resolved


def ensure_output_dir(args: argparse.Namespace) -> Path:
    out = Path(args.output_dir) if args.output_dir else Path("outputs") / "r_agg_entry_0" / args.run_id
    if out.exists():
        if not args.overwrite:
            raise SystemExit(f"Output directory exists; pass --overwrite to replace: {out}")
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    return out


def nonnull_rate(df: pd.DataFrame, columns: list[str]) -> float:
    present = [c for c in columns if c in df.columns]
    if not present or df.empty:
        return 0.0
    mask = pd.Series(False, index=df.index)
    for col in present:
        mask = mask | df[col].notna()
    return float(mask.mean())


def column_rate(df: pd.DataFrame, column: str) -> float:
    if column not in df.columns or df.empty:
        return 0.0
    return float(df[column].notna().mean())


def unique_count(df: pd.DataFrame, column: str) -> int:
    if column not in df.columns or df.empty:
        return 0
    return int(df[column].dropna().astype(str).nunique())


def first_existing(columns: list[str], candidates: list[str]) -> str | None:
    for col in candidates:
        if col in columns:
            return col
    return None


def safe_read(path: Path, sample_size: int) -> tuple[pd.DataFrame, list[str], int]:
    parquet = pq.ParquetFile(path)
    columns = parquet.schema.names
    row_count = int(parquet.metadata.num_rows)
    table = parquet.read()
    df = table.to_pandas()
    if sample_size > 0 and len(df) > sample_size:
        sample = df.head(sample_size).copy()
    else:
        sample = df.copy()
    return df, columns, row_count


def pct(value: float) -> float:
    if pd.isna(value) or math.isinf(value):
        return 0.0
    return round(float(value), 6)


def has_any(columns: list[str], names: list[str]) -> bool:
    return any(name in columns for name in names)


def dossier_group_scores(columns: list[str], df: pd.DataFrame) -> dict[str, float]:
    identity = (int("event_id" in columns or "incident_id" in columns) + int("run_id" in columns)) / 2
    time = (
        int(has_any(columns, ["first_seen", "start_time", "ts", "timestamp"]))
        + int(has_any(columns, ["last_seen", "end_time", "ts", "timestamp"]))
        + int("duration_sec" in columns)
    ) / 3
    obj = (
        int("prefix" in columns)
        + int("origin_as" in columns)
        + int(has_any(columns, PATH_FIELDS))
    ) / 3
    observation = (
        int(has_any(columns, ["collector_set", "collector"]))
        + int("collector_count" in columns)
        + int(has_any(columns, ["visibility_count", "visibility_mode"]))
    ) / 3
    aggregation = (
        int(has_any(columns, ["record_count", "member_event_count"]))
        + int(has_any(columns, ["prefix", "origin_as"]))
        + int(has_any(columns, REASON_FIELDS))
    ) / 3
    weak_hint = (int(has_any(columns, REASON_FIELDS)) + int(has_any(columns, ["top_contributing_factor", "risk_bucket"]))) / 2
    uncertainty = (
        int(has_any(columns, ["conflict_score", "missing_origin_or_path"]))
        + int(has_any(columns, ["certainty_score", "candidate_flag", "matched_rule_count"]))
    ) / 2
    return {
        "identity": pct(identity),
        "time": pct(time),
        "object": pct(obj),
        "observation": pct(observation),
        "aggregation_explanation": pct(aggregation),
        "weak_semantic_hint": pct(weak_hint),
        "uncertainty": pct(uncertainty),
    }


def collector_distribution(df: pd.DataFrame) -> dict[str, int]:
    if "collector_count" in df.columns:
        return {str(k): int(v) for k, v in df["collector_count"].fillna("NA").value_counts().head(20).items()}
    if "collector_set" in df.columns:
        counts = df["collector_set"].fillna("").astype(str).map(lambda x: 0 if not x else len([p for p in x.replace("|", ",").split(",") if p.strip()]))
        return {str(k): int(v) for k, v in counts.value_counts().head(20).items()}
    if "collector" in df.columns:
        return {"1": int(df["collector"].notna().sum())}
    return {}


def compute_scores(entry: str, metrics: dict[str, Any], all_row_counts: dict[str, int]) -> dict[str, float]:
    field = metrics["raw_dossier_min_field_recoverability"]
    contamination = min(1.0, metrics["judgment_field_count"] / 6.0)
    max_rows = max([v for v in all_row_counts.values() if v > 0] or [1])
    row_pressure = metrics["row_count"] / max_rows if max_rows else 0.0
    stage_noise_prior = {
        "event-entry": 1.0,
        "candidate-entry": 0.75,
        "scored-entry": 0.55,
        "gated-entry": 0.45,
        "augmented-entry": 0.35,
        "final-entry": 0.25,
    }[entry]
    noise = min(1.0, 0.65 * stage_noise_prior + 0.35 * row_pressure)
    explain = pct(
        0.25 * float(metrics["unique_event_id_count"] > 0)
        + 0.25 * float(metrics["unique_prefix_origin_count"] > 0)
        + 0.25 * metrics["trigger_or_candidate_reasons_available_rate"]
        + 0.25 * float(metrics["duration_sec_available_rate"] > 0)
    )
    evidence = pct(
        0.25 * float(metrics["unique_prefix_count"] > 0)
        + 0.25 * float(metrics["unique_origin_as_count"] > 0)
        + 0.25 * float(metrics["unique_as_path_signature_count"] > 0)
        + 0.25 * float(metrics["collector_count_distribution"] != {})
    )
    learning = pct(0.4 * field + 0.25 * explain + 0.25 * evidence + 0.10 * (1 - contamination))
    return {
        "field_completeness_score": pct(field),
        "judgment_contamination_score": pct(contamination),
        "noise_exposure_score": pct(noise),
        "aggregation_explainability_score": pct(explain),
        "evidence_readiness_score": pct(evidence),
        "learning_readiness_score": pct(learning),
    }


def audit_entry(entry: str, spec: EntryPaths, sample_size: int, out_dir: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if spec.status == "missing" or spec.path is None:
        base = {
            "entry": entry,
            "status": "missing",
            "file_path": rel(spec.path) if spec.path else "",
            "row_count": 0,
            "unique_event_id_count": 0,
            "unique_prefix_count": 0,
            "unique_origin_as_count": 0,
            "unique_prefix_origin_count": 0,
            "unique_as_path_signature_count": 0,
            "unique_collector_set_count": 0,
            "collector_count_distribution": {},
            "time_coverage_rate": 0.0,
            "duration_sec_available_rate": 0.0,
            "trigger_or_candidate_reasons_available_rate": 0.0,
            "risk_score_available_rate": 0.0,
            "certainty_score_available_rate": 0.0,
            "conflict_score_available_rate": 0.0,
            "evidence_support_score_available_rate": 0.0,
            "final_alert_label_available_rate": 0.0,
            "judgment_field_count": 0,
            "judgment_fields_present": "",
            "raw_dossier_min_field_recoverability": 0.0,
            "notes": spec.note,
        }
        scores = {
            "entry": entry,
            "field_completeness_score": 0.0,
            "judgment_contamination_score": 0.0,
            "noise_exposure_score": 0.0,
            "aggregation_explainability_score": 0.0,
            "evidence_readiness_score": 0.0,
            "learning_readiness_score": 0.0,
        }
        schema = {"entry": entry, "status": "missing", "file_path": base["file_path"], "column_count": 0, "columns": "", "notes": spec.note}
        return base, scores, schema

    df, columns, row_count = safe_read(spec.path, sample_size)
    sample = df.head(sample_size).copy() if sample_size > 0 else df.head(0).copy()
    sample.to_csv(out_dir / f"entry_sample_rows_{entry}.csv", index=False)

    path_col = first_existing(columns, PATH_FIELDS)
    metrics: dict[str, Any] = {
        "entry": entry,
        "status": "present",
        "file_path": rel(spec.path),
        "row_count": row_count,
        "unique_event_id_count": unique_count(df, "event_id"),
        "unique_prefix_count": unique_count(df, "prefix"),
        "unique_origin_as_count": unique_count(df, "origin_as"),
        "unique_prefix_origin_count": 0,
        "unique_as_path_signature_count": unique_count(df, path_col) if path_col else 0,
        "unique_collector_set_count": unique_count(df, "collector_set") or unique_count(df, "collector"),
        "collector_count_distribution": collector_distribution(df),
        "time_coverage_rate": nonnull_rate(df, TIME_FIELDS),
        "duration_sec_available_rate": column_rate(df, "duration_sec"),
        "trigger_or_candidate_reasons_available_rate": nonnull_rate(df, REASON_FIELDS),
        "risk_score_available_rate": column_rate(df, "risk_score"),
        "certainty_score_available_rate": column_rate(df, "certainty_score"),
        "conflict_score_available_rate": column_rate(df, "conflict_score"),
        "evidence_support_score_available_rate": column_rate(df, "evidence_support_score"),
        "final_alert_label_available_rate": column_rate(df, "final_alert_label"),
        "judgment_fields_present": ";".join([c for c in columns if c in JUDGMENT_FIELDS or c.endswith("_label")]),
        "notes": spec.note,
    }
    if "prefix" in df.columns and "origin_as" in df.columns:
        metrics["unique_prefix_origin_count"] = int((df["prefix"].astype(str) + "|" + df["origin_as"].astype(str)).nunique())
    metrics["judgment_field_count"] = len([c for c in metrics["judgment_fields_present"].split(";") if c])
    group_scores = dossier_group_scores(columns, df)
    metrics.update({f"dossier_group_{k}_score": v for k, v in group_scores.items()})
    metrics["raw_dossier_min_field_recoverability"] = pct(sum(group_scores.values()) / len(group_scores))

    schema = {
        "entry": entry,
        "status": "present",
        "file_path": rel(spec.path),
        "column_count": len(columns),
        "columns": ";".join(columns),
        "notes": "schema and sample audited; no pipeline artifact modified",
    }
    return metrics, {}, schema


def choose_recommendations(score_rows: list[dict[str, Any]]) -> dict[str, Any]:
    present = [r for r in score_rows if r.get("status", "present") != "missing"]
    if not present:
        return {
            "recommended_main_entry": "candidate-entry",
            "recommended_auxiliary_entries": ["event-entry", "scored-entry"],
            "not_recommended_entries": ["gated-entry", "augmented-entry", "final-entry"],
            "rationale": "No local old seven-layer artifacts were available; recommendation follows design constraints.",
        }
    candidates = {r["entry"]: r for r in present}
    main = "candidate-entry" if "candidate-entry" in candidates else max(
        present,
        key=lambda r: (
            r["field_completeness_score"]
            + r["aggregation_explainability_score"]
            + r["evidence_readiness_score"]
            + r["learning_readiness_score"]
            - r["judgment_contamination_score"]
            - 0.35 * r["noise_exposure_score"]
        ),
    )["entry"]
    aux = [e for e in ["event-entry", "scored-entry"] if e in candidates]
    not_rec = [e for e in ["gated-entry", "augmented-entry", "final-entry"] if e in candidates]
    return {
        "recommended_main_entry": main,
        "recommended_auxiliary_entries": aux,
        "not_recommended_entries": not_rec,
        "rationale": "candidate-entry best balances weak-trigger explanation, evidence lookup keys, and lower judgment contamination; event-entry remains a raw audit fallback, scored-entry can be an auxiliary weak-signal source.",
    }


def write_markdown(out_dir: Path, args: argparse.Namespace, metrics: list[dict[str, Any]], scores: list[dict[str, Any]], recommendations: dict[str, Any]) -> None:
    score_df = pd.DataFrame(scores)
    metric_df = pd.DataFrame(metrics)
    score_cols = [
        "entry",
        "status",
        "field_completeness_score",
        "judgment_contamination_score",
        "noise_exposure_score",
        "aggregation_explainability_score",
        "evidence_readiness_score",
        "learning_readiness_score",
    ]
    field_cols = [
        "entry",
        "status",
        "row_count",
        "unique_event_id_count",
        "unique_prefix_origin_count",
        "raw_dossier_min_field_recoverability",
        "judgment_field_count",
        "trigger_or_candidate_reasons_available_rate",
    ]
    score_table = markdown_table(score_df[score_cols].to_dict("records"), score_cols)
    field_table = markdown_table(metric_df[field_cols].to_dict("records"), field_cols)
    md = f"""# R-AGG-ENTRY-0 Raw Incident Entry Audit

Run id: `{args.run_id}`

Output directory: `{out_dir.as_posix()}`

## Goal

This read-only audit compares old seven-layer artifacts as possible entry points for future Raw Incident Dossier construction. It produces no truth label, does not train learning, and does not implement final incident aggregation.

## Entry Score Summary

{score_table}

## Field Availability Summary

{field_table}

## Recommendation

- Recommended main entry: `{recommendations['recommended_main_entry']}`
- Recommended auxiliary entries: `{', '.join(recommendations['recommended_auxiliary_entries']) or 'none'}`
- Not recommended as primary entries: `{', '.join(recommendations['not_recommended_entries']) or 'none'}`

Rationale: {recommendations['rationale']}

## Why Final-entry Is Not The Default

final labels are weak workflow signals, not truth labels. `final_alert_label`, `high`, `needs`, and `low` already reflect legacy gate/augment/final judgment. Using final-entry as the Raw Incident constructor would risk carrying old detector bias into the new incident representation.

## Safety Notes

- no truth label is produced;
- no attack/benign label is produced;
- no old seven-layer artifact is modified;
- poisoning benchmark retained as a later core evaluation;
- learning layer postponed until Raw Incident Dossier and Evidence-grounded Incident schemas are stable;
- future learning should move toward BEAM-style semantic learning for representation and prioritization, not rule re-scoring.
"""
    (out_dir / "R_AGG_ENTRY_0_RAW_INCIDENT_ENTRY_AUDIT.md").write_text(md, encoding="utf-8")


def markdown_table(rows: list[dict[str, Any]], columns: list[str]) -> str:
    if not rows:
        return "_No rows._"
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in rows:
        vals = [str(row.get(col, "")).replace("\n", " ") for col in columns]
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    out_dir = ensure_output_dir(args)
    paths = resolve_paths(args)

    metrics: list[dict[str, Any]] = []
    schemas: list[dict[str, Any]] = []
    partial_scores: list[dict[str, Any]] = []
    for entry in ENTRY_ORDER:
        metric, score, schema = audit_entry(entry, paths[entry], args.sample_size, out_dir)
        metrics.append(metric)
        schemas.append(schema)
        if score:
            partial_scores.append(score)

    row_counts = {m["entry"]: int(m["row_count"]) for m in metrics}
    scores: list[dict[str, Any]] = []
    for metric in metrics:
        if metric["status"] == "missing":
            base = next(s for s in partial_scores if s["entry"] == metric["entry"])
            base["status"] = "missing"
            scores.append(base)
            continue
        score_values = compute_scores(metric["entry"], metric, row_counts)
        scores.append({"entry": metric["entry"], "status": metric["status"], **score_values})

    recommendations = choose_recommendations(scores)
    summary = {
        "phase": "R-AGG-ENTRY-0",
        "run_id": args.run_id,
        "output_dir": out_dir.as_posix(),
        "entries": metrics,
        "recommendations": recommendations,
        "guardrails": {
            "no_truth_label": True,
            "old_pipeline_modified": False,
            "learning_trained": False,
            "final_labels_are_weak_workflow_signals": True,
            "poisoning_benchmark_retained": True,
            "learning_layer_postponed": True,
        },
    }

    (out_dir / "entry_audit_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(scores).to_csv(out_dir / "entry_audit_scores.csv", index=False)
    pd.DataFrame(schemas).to_csv(out_dir / "entry_schema_availability.csv", index=False)
    write_markdown(out_dir, args, metrics, scores, recommendations)

    print(json.dumps({"run_id": args.run_id, "recommendations": recommendations, "output_dir": out_dir.as_posix()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
