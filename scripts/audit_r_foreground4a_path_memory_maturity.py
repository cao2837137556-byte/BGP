#!/usr/bin/env python3
"""Audit path-memory maturity features before repairing foreground policy.

R-FOREGROUND-4A is a read-only feasibility audit. It checks whether the current
foreground assignment artifacts contain enough evidence to distinguish mature
recurrent routes from short-lived or potentially crafted recurrence.

It does not change online_path_pressure_v1, does not train learning, and does
not claim that immature recurrence is an attack. Immature recurrence only means
that the route should not be used as a strong suppression basis without a
longer-history contract.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ASSIGNMENT = (
    "outputs/r_attack_1/s2a_attack1_family_expansion_6h_april16_v01/"
    "smoke_replay/foreground3/r_foreground3_assignment.parquet"
)
DEFAULT_POISON2_EVENTS = (
    "outputs/r_poison_2/s2a_baseline_v01_pilot_6h_april16/"
    "r_poison2_bounded_replay_events.csv"
)
DEFAULT_OUTPUT_DIR = (
    "outputs/r_foreground_4a/s2a_attack1_family_expansion_6h_april16_v01"
)

ASSIGN_SUPPRESSED = "operational_background_suppressed"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assignment", default=DEFAULT_ASSIGNMENT)
    parser.add_argument("--poison2-events", default=DEFAULT_POISON2_EVENTS)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--mature-min-event-count", type=int, default=10)
    parser.add_argument("--mature-min-span-sec", type=float, default=3600.0)
    parser.add_argument("--mature-min-collector-count", type=int, default=2)
    parser.add_argument("--recent-grace-sec", type=float, default=900.0)
    parser.add_argument("--short-lived-span-sec", type=float, default=900.0)
    parser.add_argument("--sample-size", type=int, default=10000)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def resolve_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def prepare_output_dir(path: Path, overwrite: bool) -> None:
    if path.exists() and any(path.iterdir()):
        if not overwrite:
            raise FileExistsError(f"output directory not empty; pass --overwrite: {path}")
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def safe_rate(numerator: int | float, denominator: int | float) -> float:
    if not denominator:
        return 0.0
    return float(numerator) / float(denominator)


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def normalize_assignment(frame: pd.DataFrame) -> pd.DataFrame:
    required = [
        "event_id",
        "prefix_origin_path_key",
        "as_path_signature",
        "first_seen",
        "last_seen",
        "collector_set",
        "collector_count",
        "online_assignment",
        "external_risk_signal",
        "prefix_origin_event_count",
        "prefix_origin_path_event_count",
        "path_signature_event_count",
    ]
    missing = [col for col in required if col not in frame.columns]
    if missing:
        raise ValueError(f"assignment artifact missing required columns: {missing}")

    df = frame.copy()
    df["first_seen_num"] = pd.to_numeric(df["first_seen"], errors="coerce")
    df["last_seen_num"] = pd.to_numeric(df["last_seen"], errors="coerce")
    df["collector_count_num"] = pd.to_numeric(
        df["collector_count"], errors="coerce"
    ).fillna(0)
    for col in [
        "prefix_origin_event_count",
        "prefix_origin_path_event_count",
        "path_signature_event_count",
    ]:
        df[col + "_num"] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    df["external_risk_signal_bool"] = df["external_risk_signal"].map(as_bool)
    df["suppressed_bool"] = df["online_assignment"].eq(ASSIGN_SUPPRESSED)
    return df


def collector_diversity(series: pd.Series) -> int:
    values: set[str] = set()
    for value in series.dropna():
        text = str(value)
        for sep in ["|", ",", ";"]:
            if sep in text:
                values.update(part.strip() for part in text.split(sep) if part.strip())
                break
        else:
            if text.strip():
                values.add(text.strip())
    return len(values)


def build_path_memory_table(df: pd.DataFrame, args: argparse.Namespace) -> tuple[pd.DataFrame, dict[str, Any]]:
    window_start = float(df["first_seen_num"].min())
    window_end = float(df["last_seen_num"].max())
    window_span = max(0.0, window_end - window_start)

    grouped = df.groupby("prefix_origin_path_key", dropna=False)
    memory = grouped.agg(
        event_count=("event_id", "count"),
        first_seen_min=("first_seen_num", "min"),
        last_seen_max=("last_seen_num", "max"),
        row_collector_max=("collector_count_num", "max"),
        external_risk_rows=("external_risk_signal_bool", "sum"),
        suppressed_rows=("suppressed_bool", "sum"),
        path_signature_count_max=("path_signature_event_count_num", "max"),
        prefix_origin_count_max=("prefix_origin_event_count_num", "max"),
        prefix_origin_path_count_max=("prefix_origin_path_event_count_num", "max"),
    ).reset_index()
    collector_counts = grouped["collector_set"].apply(collector_diversity).reset_index()
    collector_counts = collector_counts.rename(columns={"collector_set": "collector_diversity"})
    memory = memory.merge(collector_counts, on="prefix_origin_path_key", how="left")

    memory["observed_span_sec"] = (
        pd.to_numeric(memory["last_seen_max"], errors="coerce")
        - pd.to_numeric(memory["first_seen_min"], errors="coerce")
    ).fillna(0)
    memory["first_seen_offset_sec"] = (
        pd.to_numeric(memory["first_seen_min"], errors="coerce") - window_start
    ).fillna(0)
    memory["last_seen_gap_to_window_end_sec"] = (
        window_end - pd.to_numeric(memory["last_seen_max"], errors="coerce")
    ).fillna(0)
    memory["seen_at_window_start_proxy"] = (
        memory["first_seen_offset_sec"] <= float(args.recent_grace_sec)
    )
    memory["recent_first_seen_proxy"] = (
        memory["first_seen_offset_sec"] > float(args.recent_grace_sec)
    )
    memory["short_lived_span_proxy"] = (
        memory["observed_span_sec"] <= float(args.short_lived_span_sec)
    )
    memory["count_recurrent_proxy"] = memory["event_count"] >= 2
    memory["time_mature_proxy"] = (
        (memory["event_count"] >= int(args.mature_min_event_count))
        & (memory["observed_span_sec"] >= float(args.mature_min_span_sec))
    )
    memory["multi_collector_mature_proxy"] = (
        memory["collector_diversity"] >= int(args.mature_min_collector_count)
    )
    memory["strong_mature_route_proxy"] = (
        memory["time_mature_proxy"] & memory["multi_collector_mature_proxy"]
    )
    memory["recent_suspicious_recurrence_proxy"] = (
        memory["count_recurrent_proxy"]
        & ~memory["strong_mature_route_proxy"]
        & (
            memory["recent_first_seen_proxy"]
            | memory["short_lived_span_proxy"]
            | ~memory["seen_at_window_start_proxy"]
        )
    )
    memory["maturity_bucket"] = "insufficient_or_singleton"
    memory.loc[memory["count_recurrent_proxy"], "maturity_bucket"] = (
        "recurrent_but_not_mature"
    )
    memory.loc[memory["time_mature_proxy"], "maturity_bucket"] = (
        "time_mature_single_or_unknown_collector"
    )
    memory.loc[memory["strong_mature_route_proxy"], "maturity_bucket"] = (
        "strong_mature_proxy"
    )
    memory.loc[memory["recent_suspicious_recurrence_proxy"], "maturity_bucket"] = (
        "recent_suspicious_recurrence_proxy"
    )

    metadata = {
        "window_start_epoch": window_start,
        "window_end_epoch": window_end,
        "window_span_sec": window_span,
        "window_meets_within_window_maturity_span_threshold": window_span
        >= float(args.mature_min_span_sec),
        "window_supports_long_term_maturity_claim": False,
        "long_term_maturity_boundary": (
            "Current artifact can only provide within-window maturity proxies; "
            "formal long-term maturity requires a longer historical sidecar."
        ),
    }
    return memory, metadata


def attach_maturity(df: pd.DataFrame, memory: pd.DataFrame) -> pd.DataFrame:
    keep_cols = [
        "prefix_origin_path_key",
        "event_count",
        "observed_span_sec",
        "first_seen_offset_sec",
        "collector_diversity",
        "seen_at_window_start_proxy",
        "recent_first_seen_proxy",
        "short_lived_span_proxy",
        "time_mature_proxy",
        "multi_collector_mature_proxy",
        "strong_mature_route_proxy",
        "recent_suspicious_recurrence_proxy",
        "maturity_bucket",
    ]
    return df.merge(memory[keep_cols], on="prefix_origin_path_key", how="left")


def bucket_rows(frame: pd.DataFrame, population_name: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    total = len(frame)
    suppressed_total = int(frame["suppressed_bool"].sum()) if total else 0
    for bucket, group in frame.groupby("maturity_bucket", dropna=False):
        rows.append(
            {
                "population": population_name,
                "maturity_bucket": str(bucket),
                "rows": int(len(group)),
                "row_rate": safe_rate(len(group), total),
                "suppressed_rows": int(group["suppressed_bool"].sum()),
                "suppressed_row_rate_within_bucket": safe_rate(
                    int(group["suppressed_bool"].sum()), len(group)
                ),
                "share_of_all_suppressed_rows": safe_rate(
                    int(group["suppressed_bool"].sum()), suppressed_total
                ),
            }
        )
    return rows


def impact_estimate(df: pd.DataFrame) -> list[dict[str, Any]]:
    total = len(df)
    suppressed = int(df["suppressed_bool"].sum())
    foreground = total - suppressed
    recent_suppressed = int(
        (df["suppressed_bool"] & df["recent_suspicious_recurrence_proxy"]).sum()
    )
    strong_mature_suppressed = int(
        (df["suppressed_bool"] & df["strong_mature_route_proxy"]).sum()
    )
    rows = []
    scenarios = [
        (
            "current_online_path_pressure_v1",
            0,
            "Current frozen foreground assignment.",
        ),
        (
            "guard_all_recent_suspicious_recurrence_proxy",
            recent_suppressed,
            "Worst case if every suppressed recent-suspicious proxy row is retained.",
        ),
        (
            "allow_only_strong_mature_suppression",
            suppressed - strong_mature_suppressed,
            "Very strict stress test: only strong mature proxy rows remain suppressible.",
        ),
    ]
    for scenario_id, pulled_back, notes in scenarios:
        new_suppressed = max(0, suppressed - pulled_back)
        new_foreground = total - new_suppressed
        rows.append(
            {
                "scenario_id": scenario_id,
                "total_rows": total,
                "current_suppressed_rows": suppressed,
                "rows_pulled_back_to_foreground_or_gray": int(pulled_back),
                "estimated_suppressed_rows_after_guard": int(new_suppressed),
                "estimated_foreground_rows_after_guard": int(new_foreground),
                "estimated_suppression_rate_after_guard": safe_rate(new_suppressed, total),
                "estimated_compression_ratio_after_guard": safe_rate(total, new_foreground),
                "notes": notes,
            }
        )
    return rows


def poison_pair_audit(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return [
            {
                "pair_id": "missing_poison2_events",
                "variant_role": "missing",
                "maturity_proxy_available": False,
                "bounded_poisoning_proxy_class": "missing_input",
                "notes": f"R-POISON-2 events not found: {path}",
            }
        ]
    events = pd.read_csv(path)
    rows: list[dict[str, Any]] = []
    for row in events.to_dict("records"):
        variant_role = str(row.get("variant_role", ""))
        pair_id = str(row.get("pair_id", ""))
        current_assignment = str(row.get("online_assignment", ""))
        drift = float(row.get("knowledge_base_drift_score", 0) or 0)
        novelty_drop = float(row.get("novelty_signal_drop", 0) or 0)
        path_count = int(float(row.get("prefix_origin_path_event_count", 0) or 0))
        if variant_role == "adversarial" and drift > 0 and novelty_drop > 0:
            proxy_class = "bounded_recent_crafted_history_proxy"
        elif path_count <= 1:
            proxy_class = "bounded_novel_path_proxy"
        else:
            proxy_class = "bounded_recurrent_proxy"
        rows.append(
            {
                "pair_id": pair_id,
                "variant_role": variant_role,
                "family": row.get("family", ""),
                "threat_model": row.get("threat_model", ""),
                "current_assignment": current_assignment,
                "current_retained": current_assignment != ASSIGN_SUPPRESSED,
                "maturity_proxy_available": False,
                "bounded_poisoning_proxy_class": proxy_class,
                "knowledge_base_drift_score": drift,
                "novelty_signal_drop": novelty_drop,
                "prefix_origin_path_event_count": path_count,
                "path_memory_failure": (
                    pair_id == "pair_path_manipulation_history_poisoning_v01"
                    and variant_role == "adversarial"
                    and current_assignment == ASSIGN_SUPPRESSED
                ),
                "allowed_claim": (
                    "bounded pair exposes whether current foreground can be "
                    "fooled by simulated history poisoning"
                ),
                "forbidden_claim": (
                    "bounded row does not provide real long-term path maturity"
                ),
            }
        )
    return rows


def sample_rows(df: pd.DataFrame, sample_size: int) -> pd.DataFrame:
    cols = [
        "event_id",
        "prefix",
        "origin_as",
        "as_path_signature",
        "collector_set",
        "first_seen",
        "last_seen",
        "online_assignment",
        "online_assignment_reason",
        "external_risk_signal",
        "event_count",
        "observed_span_sec",
        "collector_diversity",
        "maturity_bucket",
        "recent_suspicious_recurrence_proxy",
        "strong_mature_route_proxy",
        "population",
    ]
    available = [col for col in cols if col in df.columns]
    focus = df[df["suppressed_bool"] & df["recent_suspicious_recurrence_proxy"]]
    if focus.empty:
        focus = df[df["suppressed_bool"]]
    if len(focus) > sample_size:
        focus = focus.head(sample_size)
    return focus[available].copy()


def write_report(
    path: Path,
    summary: dict[str, Any],
    impact_rows: list[dict[str, Any]],
    poison_rows: list[dict[str, Any]],
) -> None:
    lines = [
        "# R-FOREGROUND-4A Path-Memory Maturity Feasibility Audit",
        "",
        "Status: read-only feature feasibility audit; no policy change.",
        "",
        "## Goal",
        "",
        "R-FOREGROUND-4A checks whether the current foreground artifacts can support a path-memory maturity guard.",
        "The guard is intended to prevent short-lived crafted recurrence from being treated as stable operational background.",
        "",
        "## Key Result",
        "",
        f"- assignment rows audited: `{summary['assignment_rows']}`",
        f"- current suppressed rows: `{summary['current_suppressed_rows']}`",
        f"- current suppression rate: `{summary['current_suppression_rate']}`",
        f"- window span seconds: `{summary['window_span_sec']}`",
        f"- meets within-window maturity span threshold: `{summary['window_meets_within_window_maturity_span_threshold']}`",
        f"- supports long-term maturity claim: `{summary['window_supports_long_term_maturity_claim']}`",
        f"- suppressed recent-suspicious proxy rows: `{summary['suppressed_recent_suspicious_recurrence_rows']}`",
        f"- suppressed strong-mature proxy rows: `{summary['suppressed_strong_mature_proxy_rows']}`",
        f"- path poisoning failure classified: `{summary['path_poisoning_failure_classified']}`",
        "",
        "## Impact Estimate",
        "",
        "| Scenario | Pulled back rows | Suppression rate | Compression ratio |",
        "|---|---:|---:|---:|",
    ]
    for row in impact_rows:
        lines.append(
            f"| `{row['scenario_id']}` | `{row['rows_pulled_back_to_foreground_or_gray']}` | "
            f"`{row['estimated_suppression_rate_after_guard']:.6f}` | "
            f"`{row['estimated_compression_ratio_after_guard']:.6f}` |"
        )
    lines.extend(
        [
            "",
            "## R-POISON-2 Failure Check",
            "",
            "| Pair | Variant | Proxy class | Assignment | Path-memory failure |",
            "|---|---|---|---|---|",
        ]
    )
    for row in poison_rows:
        if row.get("pair_id") != "pair_path_manipulation_history_poisoning_v01":
            continue
        lines.append(
            f"| `{row['pair_id']}` | `{row['variant_role']}` | "
            f"`{row['bounded_poisoning_proxy_class']}` | "
            f"`{row['current_assignment']}` | `{row['path_memory_failure']}` |"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- Maturity is only evidence for whether suppression is allowed.",
            "- Immature or recent recurrence is not attack truth.",
            "- The current artifact provides within-window maturity proxies only.",
            "- Formal long-term maturity requires a longer historical sidecar.",
            "- R-FOREGROUND-4B should add a targeted guard only after this feasibility boundary is respected.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    assignment_path = resolve_path(args.assignment)
    poison2_path = resolve_path(args.poison2_events)
    output_dir = resolve_path(args.output_dir)
    prepare_output_dir(output_dir, args.overwrite)

    if not assignment_path.exists():
        raise FileNotFoundError(assignment_path)
    assignment = normalize_assignment(pd.read_parquet(assignment_path))
    memory, window_meta = build_path_memory_table(assignment, args)
    enriched = attach_maturity(assignment, memory)

    bucket_audit: list[dict[str, Any]] = []
    bucket_audit.extend(bucket_rows(enriched, "all_rows"))
    bucket_audit.extend(bucket_rows(enriched[enriched["suppressed_bool"]], "suppressed_rows"))
    if "population" in enriched.columns:
        for population, subset in enriched.groupby("population", dropna=False):
            bucket_audit.extend(bucket_rows(subset, f"population:{population}"))

    impact_rows = impact_estimate(enriched)
    poison_rows = poison_pair_audit(poison2_path)
    sample = sample_rows(enriched, int(args.sample_size))

    memory.to_csv(output_dir / "r_foreground4a_path_memory_feature_audit.csv", index=False)
    write_csv(output_dir / "r_foreground4a_maturity_bucket_audit.csv", bucket_audit)
    write_csv(output_dir / "r_foreground4a_candidate_guard_impact_estimate.csv", impact_rows)
    write_csv(output_dir / "r_foreground4a_poison_pair_maturity_audit.csv", poison_rows)
    sample.to_csv(output_dir / "r_foreground4a_suppressed_recent_recurrence_sample.csv", index=False)

    total = len(enriched)
    suppressed = int(enriched["suppressed_bool"].sum())
    recent_suppressed = int(
        (enriched["suppressed_bool"] & enriched["recent_suspicious_recurrence_proxy"]).sum()
    )
    strong_mature_suppressed = int(
        (enriched["suppressed_bool"] & enriched["strong_mature_route_proxy"]).sum()
    )
    path_failure = any(bool(row.get("path_memory_failure")) for row in poison_rows)

    summary = {
        "phase": "R-FOREGROUND-4A",
        "status": "path_memory_maturity_feature_feasibility_audit",
        "assignment_path": str(assignment_path),
        "poison2_events_path": str(poison2_path),
        "assignment_scope_note": (
            "This audit covers the supplied foreground assignment artifact. "
            "If the artifact is a smoke_replay or pullback subset, the result "
            "is a feature-feasibility audit rather than a full-window claim."
        ),
        "assignment_rows": total,
        "unique_prefix_origin_path_keys": int(memory["prefix_origin_path_key"].nunique()),
        "current_suppressed_rows": suppressed,
        "current_suppression_rate": safe_rate(suppressed, total),
        "current_compression_ratio": safe_rate(total, total - suppressed),
        "suppressed_recent_suspicious_recurrence_rows": recent_suppressed,
        "suppressed_recent_suspicious_recurrence_rate": safe_rate(
            recent_suppressed, suppressed
        ),
        "suppressed_strong_mature_proxy_rows": strong_mature_suppressed,
        "suppressed_strong_mature_proxy_rate": safe_rate(
            strong_mature_suppressed, suppressed
        ),
        "path_poisoning_failure_classified": path_failure,
        "mature_min_event_count": int(args.mature_min_event_count),
        "mature_min_span_sec": float(args.mature_min_span_sec),
        "mature_min_collector_count": int(args.mature_min_collector_count),
        "recent_grace_sec": float(args.recent_grace_sec),
        "short_lived_span_sec": float(args.short_lived_span_sec),
        **window_meta,
        "this_phase_changed_foreground_policy": False,
        "this_phase_trained_learning": False,
        "this_phase_full_6h_replay": False,
        "allowed_claim": (
            "R-FOREGROUND-4A audits whether path-memory maturity proxies are "
            "available for a targeted foreground repair."
        ),
        "forbidden_claims": [
            "Do not claim within-window recurrence is long-term maturity.",
            "Do not claim immature recurrence is attack truth.",
            "Do not change online_path_pressure_v1 in this phase.",
            "Do not treat RPKI, AS-rel, or NO_EXPORT as labels.",
        ],
        "recommended_next_step": (
            "R-FOREGROUND-4B targeted guard smoke, but only with a maturity "
            "boundary that avoids using within-window count as long-term proof."
        ),
    }
    write_json(output_dir / "r_foreground4a_summary.json", summary)
    write_report(
        output_dir / "r_foreground4a_report.md",
        summary,
        impact_rows,
        poison_rows,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
