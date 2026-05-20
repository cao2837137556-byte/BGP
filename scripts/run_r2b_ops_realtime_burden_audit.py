#!/usr/bin/env python3
"""R-2B-OPS operational burden and real-time evidence cache audit.

This is an audit-only script. It does not download evidence, modify verifier
verdicts, train models, or run R-2C path-refinement logic.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd


VERDICT_POLICIES = {
    "strongly_supported_suspicious": ("page_immediately", "page_immediately", "highest-confidence queue; still not confirmed attack"),
    "evidence_supported_suspicious": ("high-priority Top-K queue", "review_topk", "review after deterministic Top-K ordering"),
    "evidence_conflict": ("bounded conflict queue", "review_topk", "review capped conflict cases; do not hide conflict"),
    "abstain": ("selective review only", "wait_for_more_evidence", "do not hand all abstain cases to humans"),
    "evidence_insufficient": ("ranker/top-K or wait", "wait_for_more_evidence", "do not hand all insufficient cases to humans"),
    "background_like_but_unconfirmed": ("sampling audit only", "review_sample_only", "not confirmed normal"),
    "external_evidence_unavailable": ("cache-health and selective review", "wait_for_more_evidence", "evidence missing is not benign"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-date", default="2024-04-16")
    parser.add_argument("--r2b-verifier-table", required=True)
    parser.add_argument("--r2b-summary-file", default="")
    parser.add_argument("--vrp-metadata-file", default="")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--window-hours", type=float, default=6.0)
    parser.add_argument("--daily-scale-factor", type=float, default=4.0)
    parser.add_argument("--topk-list", default="50,100,500")
    parser.add_argument("--full-run", action="store_true")
    return parser.parse_args()


def read_json(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")


def distribution(series: pd.Series) -> dict[str, int]:
    return {str(k): int(v) for k, v in series.fillna("NA").value_counts().sort_index().items()}


def safe_float(value: Any, default: float = 0.0) -> float:
    if pd.isna(value):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_topk(text: str) -> list[int]:
    out: list[int] = []
    for token in text.split(","):
        token = token.strip()
        if not token:
            continue
        out.append(int(token))
    return sorted(set(out))


def load_table(args: argparse.Namespace) -> pd.DataFrame:
    p = Path(args.r2b_verifier_table)
    if not p.exists():
        raise FileNotFoundError(f"required R-2B verifier table missing: {p}")
    table = pd.read_parquet(p)
    required = ["incident_id", "verifier_verdict_vrp"]
    missing = [c for c in required if c not in table.columns]
    if missing:
        raise ValueError(f"R-2B verifier table missing required columns: {missing}")
    return table.copy()


def add_ops_fields(table: pd.DataFrame) -> pd.DataFrame:
    df = table.copy()
    for col in [
        "rpki_invalid_share",
        "high_count",
        "needs_count",
        "member_count",
        "incident_score",
        "triage_score_vrp",
    ]:
        if col not in df.columns:
            df[col] = 0.0
    for col in ["component_purity_class", "verifier_verdict_vrp", "calibrated_incident_priority"]:
        if col not in df.columns:
            df[col] = "NA"
    if "should_split_incident_flag" not in df.columns:
        df["should_split_incident_flag"] = False

    verdict_priority = {
        "strongly_supported_suspicious": 100.0,
        "evidence_supported_suspicious": 90.0,
        "evidence_conflict": 80.0,
        "abstain": 65.0,
        "external_evidence_unavailable": 50.0,
        "evidence_insufficient": 45.0,
        "background_like_but_unconfirmed": 15.0,
    }
    purity_bonus = {
        "mixed_but_core_suspicious": 18.0,
        "mixed_conflicting": 12.0,
        "highly_mixed_should_split": 10.0,
        "pure_dominant": 4.0,
        "mostly_dominant": 3.0,
        "insufficient_component_signal": 0.0,
    }
    df["ops_verdict_priority"] = df["verifier_verdict_vrp"].map(verdict_priority).fillna(20.0)
    df["ops_purity_bonus"] = df["component_purity_class"].map(purity_bonus).fillna(0.0)
    df["ops_impact_score"] = (
        df["high_count"].map(lambda x: math.log1p(max(safe_float(x), 0.0)) * 3.0)
        + df["member_count"].map(lambda x: math.log1p(max(safe_float(x), 0.0)) * 1.5)
        + df["needs_count"].map(lambda x: math.log1p(max(safe_float(x), 0.0)) * 0.5)
    )
    df["ops_triage_score"] = (
        df["ops_verdict_priority"]
        + df["rpki_invalid_share"].map(lambda x: safe_float(x) * 25.0)
        + df["ops_purity_bonus"]
        + df["ops_impact_score"]
        + df["should_split_incident_flag"].astype(bool).astype(float) * 6.0
    )
    df["high_impact_insufficient_flag"] = (
        (df["verifier_verdict_vrp"] == "evidence_insufficient")
        & (
            df["calibrated_incident_priority"].isin(["P1_high", "P2_review"])
            | (df["high_count"].map(lambda x: safe_float(x)) > 0)
            | (df["member_count"].map(lambda x: safe_float(x)) >= 500)
            | (df["incident_score"].map(lambda x: safe_float(x)) >= 80)
        )
    )
    return df


def daily_burden_projection(df: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    total = max(len(df), 1)
    rows: list[dict[str, Any]] = []

    def add(queue_type: str, count: int, policy: str, budget: str, notes: str) -> None:
        rows.append(
            {
                "queue_type": queue_type,
                "count_in_window": int(count),
                "projected_daily_count": float(count * args.daily_scale_factor),
                "percent_of_total": float(count / total),
                "human_review_policy": policy,
                "review_budget_class": budget,
                "notes": notes,
            }
        )

    for verdict, (policy, budget, notes) in VERDICT_POLICIES.items():
        add(verdict, int((df["verifier_verdict_vrp"] == verdict).sum()), policy, budget, notes)

    add(
        "mixed_should_split",
        int(df["should_split_incident_flag"].sum()),
        "split-candidate queue",
        "review_topk",
        "component split queue; not direct attack review",
    )
    add(
        "mixed_but_core_suspicious",
        int((df["component_purity_class"] == "mixed_but_core_suspicious").sum()),
        "component-review queue",
        "review_topk",
        "review core suspicious components before incident-level conclusions",
    )
    add(
        "high_impact_insufficient",
        int(df["high_impact_insufficient_flag"].sum()),
        "ranked evidence-gap queue",
        "review_topk",
        "high-impact but insufficient; prioritize only through Top-K or enrichment",
    )
    return pd.DataFrame(rows)


def write_projection_md(path: Path, projection: pd.DataFrame, args: argparse.Namespace) -> None:
    lines = [
        "# R-2B Daily Alert Burden Projection",
        "",
        f"Window hours: `{args.window_hours}`",
        f"Daily scale factor: `{args.daily_scale_factor}`",
        "",
        "This is a linear workload proxy, not a measured deployment result.",
        "",
        "| Queue type | Count in window | Projected daily | Review policy | Budget class |",
        "| --- | ---: | ---: | --- | --- |",
    ]
    for _, row in projection.iterrows():
        lines.append(
            f"| {row['queue_type']} | {int(row['count_in_window'])} | {row['projected_daily_count']:.1f} | {row['human_review_policy']} | {row['review_budget_class']} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def topk_simulation(df: pd.DataFrame, topks: list[int]) -> tuple[pd.DataFrame, pd.DataFrame]:
    ranked = df.sort_values("ops_triage_score", ascending=False).copy()
    all_count = max(len(df), 1)
    legacy_p1p2 = max(int(df["calibrated_incident_priority"].isin(["P1_high", "P2_review"]).sum()), 1)
    rows: list[dict[str, Any]] = []
    for k in topks:
        subset = ranked.head(k)
        rows.append(
            {
                "topk": k,
                "evidence_supported_count": int((subset["verifier_verdict_vrp"] == "evidence_supported_suspicious").sum()),
                "conflict_count": int((subset["verifier_verdict_vrp"] == "evidence_conflict").sum()),
                "mixed_core_count": int((subset["component_purity_class"] == "mixed_but_core_suspicious").sum()),
                "abstain_count": int((subset["verifier_verdict_vrp"] == "abstain").sum()),
                "insufficient_count": int((subset["verifier_verdict_vrp"] == "evidence_insufficient").sum()),
                "background_like_count": int((subset["verifier_verdict_vrp"] == "background_like_but_unconfirmed").sum()),
                "evidence_supported_density": float((subset["verifier_verdict_vrp"] == "evidence_supported_suspicious").mean()) if len(subset) else 0.0,
                "review_burden_reduction_vs_legacy_p1p2": 1.0 - (min(k, len(subset)) / legacy_p1p2),
                "review_burden_reduction_vs_all_incidents": 1.0 - (min(k, len(subset)) / all_count),
                "notes": "deterministic smoke triage, not trained ranking",
            }
        )
    candidate_cols = [
        "incident_id",
        "ops_triage_score",
        "verifier_verdict_vrp",
        "component_purity_class",
        "calibrated_incident_priority",
        "verification_queue",
        "member_count",
        "high_count",
        "needs_count",
        "rpki_invalid_share",
        "dominant_pair_rpki_status",
        "should_split_incident_flag",
        "abstain_reason",
        "conflict_reason",
    ]
    candidate_cols = [c for c in candidate_cols if c in ranked.columns]
    return pd.DataFrame(rows), ranked.head(max(topks))[candidate_cols].copy()


def realtime_architecture_md(path: Path, metadata: dict[str, Any]) -> None:
    source = metadata.get("source", "RPKI/VRP cache") if metadata else "RPKI/VRP cache"
    lines = [
        "# Real-Time Evidence Cache Architecture",
        "",
        "The online path must not perform remote evidence downloads per incident.",
        "",
        "## Online Path",
        "",
        "```text",
        "BGP stream / MRT updates",
        "  -> event window",
        "  -> candidate trigger",
        "  -> incident/component builder",
        "  -> local evidence cache lookup",
        "  -> verifier verdict",
        "  -> queue manager",
        "  -> dashboard/report",
        "```",
        "",
        "Online lookup uses local cache and indexes only. If evidence is stale or unavailable, the verifier lowers evidence state, emits insufficient/unavailable/abstain/conflict as needed, and does not block monitor-triggered alerting.",
        "",
        "## Async Evidence Path",
        "",
        "```text",
        "RPKI/VRP updater",
        "AS-rel updater",
        "IRR updater",
        "PeeringDB updater",
        "known-event updater",
        "optional data-plane updater",
        "  -> normalize",
        "  -> versioned local cache",
        "  -> index build",
        "  -> atomic cache switch",
        "  -> provenance/freshness metadata",
        "```",
        "",
        "## Evidence-Specific Notes",
        "",
        "- RPKI/VRP can be maintained by a relying-party / RTR-style validated data pipeline.",
        "- AS relationship, IRR, and PeeringDB are lower-frequency caches and should be refreshed by day/week/month depending on source properties.",
        "- Data-plane evidence is async enrichment and is not in the R-2B online critical path.",
        "- Public monitor context remains trigger/context evidence, not independent external truth.",
        "",
        f"Current VRP metadata source hint: `{source}`.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def freshness_policy() -> pd.DataFrame:
    rows = [
        {
            "evidence_type": "RPKI/VRP",
            "expected_refresh_interval": "minutes-to-hourly",
            "max_allowed_staleness": "24h for research replay; shorter for online deployment",
            "online_lookup_mode": "local prefix-origin index",
            "if_fresh": "aligned_medium origin-authorization evidence",
            "if_stale": "stale_diagnostic or evidence_insufficient",
            "if_missing": "external_evidence_unavailable; do not infer benign",
            "if_conflict": "evidence_conflict or abstain",
            "blocks_alerting": "no",
            "notes": "valid is not benign; invalid is not confirmed attack",
        },
        {
            "evidence_type": "AS-rel",
            "expected_refresh_interval": "monthly or source snapshot cadence",
            "max_allowed_staleness": "snapshot-dependent; old snapshots diagnostic only",
            "online_lookup_mode": "local AS pair/triplet index",
            "if_fresh": "path-legality component evidence",
            "if_stale": "diagnostic_only",
            "if_missing": "path evidence unavailable",
            "if_conflict": "evidence_conflict",
            "blocks_alerting": "no",
            "notes": "2017 CAIDA snapshot is stale diagnostic for 2024",
        },
        {
            "evidence_type": "IRR",
            "expected_refresh_interval": "daily-to-weekly",
            "max_allowed_staleness": "source-dependent",
            "online_lookup_mode": "local route-object index",
            "if_fresh": "weak/medium corroborating evidence",
            "if_stale": "diagnostic_only",
            "if_missing": "do not infer attack",
            "if_conflict": "conflict or insufficient",
            "blocks_alerting": "no",
            "notes": "IRR match is not confirmed legitimate; IRR miss is not attack",
        },
        {
            "evidence_type": "ASPA",
            "expected_refresh_interval": "minutes-to-hourly when deployed",
            "max_allowed_staleness": "24h or deployment-specific",
            "online_lookup_mode": "local ASPA object index",
            "if_fresh": "strong path-authorization component evidence",
            "if_stale": "stale_diagnostic",
            "if_missing": "not_applicable or unavailable",
            "if_conflict": "evidence_conflict",
            "blocks_alerting": "no",
            "notes": "future R-2C/R-3 evidence branch",
        },
        {
            "evidence_type": "BGP Roles/OTC",
            "expected_refresh_interval": "stream/cache dependent",
            "max_allowed_staleness": "short for online route-leak semantics",
            "online_lookup_mode": "local role/OTC state",
            "if_fresh": "route-leak semantic evidence",
            "if_stale": "diagnostic_only",
            "if_missing": "route-leak evidence unavailable",
            "if_conflict": "evidence_conflict",
            "blocks_alerting": "no",
            "notes": "do not hide role/OTC conflict",
        },
        {
            "evidence_type": "PeeringDB",
            "expected_refresh_interval": "weekly-to-monthly",
            "max_allowed_staleness": "context only",
            "online_lookup_mode": "local organization/facility/IXP context",
            "if_fresh": "context evidence",
            "if_stale": "context only",
            "if_missing": "no block",
            "if_conflict": "diagnostic conflict",
            "blocks_alerting": "no",
            "notes": "not strong attack evidence",
        },
        {
            "evidence_type": "known-event",
            "expected_refresh_interval": "manual/as available",
            "max_allowed_staleness": "case-dependent",
            "online_lookup_mode": "local case inventory",
            "if_fresh": "case-study/provenance support",
            "if_stale": "diagnostic_only",
            "if_missing": "no match does not mean no real event",
            "if_conflict": "case review",
            "blocks_alerting": "no",
            "notes": "coverage is incomplete by design",
        },
        {
            "evidence_type": "data-plane",
            "expected_refresh_interval": "on demand / async",
            "max_allowed_staleness": "measurement-specific",
            "online_lookup_mode": "async enrichment result cache",
            "if_fresh": "high-value corroborating evidence",
            "if_stale": "diagnostic_only",
            "if_missing": "no block; async enrichment",
            "if_conflict": "evidence_conflict",
            "blocks_alerting": "no",
            "notes": "not in R-2B online critical path",
        },
        {
            "evidence_type": "public monitor context",
            "expected_refresh_interval": "streaming",
            "max_allowed_staleness": "window-dependent",
            "online_lookup_mode": "current monitor/event window",
            "if_fresh": "candidate trigger/context",
            "if_stale": "stale monitor context",
            "if_missing": "no candidate or low observability",
            "if_conflict": "visibility conflict",
            "blocks_alerting": "yes for candidate trigger only",
            "notes": "trigger only, not final truth",
        },
    ]
    return pd.DataFrame(rows)


def policy_md(path: Path, policy: pd.DataFrame) -> None:
    lines = [
        "# Evidence Freshness and Fallback Policy",
        "",
        "Freshness and unavailable states must be explicit verifier inputs. Missing evidence is never benign.",
        "",
        "| Evidence type | Refresh interval | If stale | If missing | Blocks alerting |",
        "| --- | --- | --- | --- | --- |",
    ]
    for _, row in policy.iterrows():
        lines.append(
            f"| {row['evidence_type']} | {row['expected_refresh_interval']} | {row['if_stale']} | {row['if_missing']} | {row['blocks_alerting']} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def slo_metrics() -> pd.DataFrame:
    rows = [
        ("online_event_to_candidate_latency", "latency", "target/measure", "measure from stream ingest to candidate trigger"),
        ("incident_update_interval", "latency", "target/measure", "rolling incident update cadence"),
        ("local_evidence_lookup_latency", "latency", "target/measure", "local cache lookup only, no remote call"),
        ("queue_update_interval", "latency", "target/measure", "verdict queue refresh cadence"),
        ("cache_refresh_interval", "freshness", "target/measure", "per evidence type"),
        ("cache_staleness_rate", "freshness", "measure", "share of lookups using stale evidence"),
        ("unsupported_alert_ratio", "quality", "measure", "insufficient/unavailable over total incidents"),
        ("daily_human_review_budget", "ops", "target", "page/review budget by queue"),
        ("topk_supported_density", "ops", "measure", "evidence-supported share in top-K"),
        ("conflict_queue_size", "ops", "measure", "bounded conflict review queue size"),
        ("abstain_queue_size", "ops", "measure", "not full manual; selective policy"),
        ("background_sampling_rate", "ops", "target", "sample only, not full manual"),
        ("evidence_cache_failure_fallback_rate", "resilience", "measure", "fallback to unavailable/stale states"),
    ]
    return pd.DataFrame(rows, columns=["metric", "category", "status", "measurement_plan"])


def slo_md(path: Path, slo: pd.DataFrame) -> None:
    lines = [
        "# Operational SLO Draft",
        "",
        "These are targets and measurement hooks, not achieved deployment SLOs.",
        "",
        "| Metric | Category | Status | Measurement plan |",
        "| --- | --- | --- | --- |",
    ]
    for _, row in slo.iterrows():
        lines.append(f"| {row['metric']} | {row['category']} | {row['status']} | {row['measurement_plan']} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_ops_report(path: Path, summary: dict[str, Any]) -> None:
    burden = summary["daily_burden_projection"]
    topk = summary["topk_review_simulation"]
    lines = [
        "# R-2B-OPS Operational Burden and Real-Time Cache Audit",
        "",
        f"Run id: `{summary['run_id']}`",
        f"Run date: `{summary['run_date']}`",
        f"Status: `{summary['status']}`",
        "",
        "## 1. Daily Queue Projection",
        "",
        "This is a linear projection from the fixed 6h window, not a production measurement.",
        "",
        "| Queue | Window count | Projected daily | Policy |",
        "| --- | ---: | ---: | --- |",
    ]
    for row in burden:
        lines.append(
            f"| {row['queue_type']} | {row['count_in_window']} | {row['projected_daily_count']:.1f} | {row['human_review_policy']} |"
        )
    lines.extend(
        [
            "",
            "Queues that can be fully reviewed are limited to very small high-confidence/page queues. Evidence-supported, conflict, split-candidate, and high-impact insufficient queues require Top-K caps. Abstain, insufficient, and background-like queues must not be handed to humans in full.",
            "",
            "## 2. Top-K Review Simulation",
            "",
            "| K | Evidence-supported | Conflict | Abstain | Insufficient | Background-like | Supported density | Reduction vs P1/P2 | Reduction vs all |",
            "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in topk:
        lines.append(
            f"| {row['topk']} | {row['evidence_supported_count']} | {row['conflict_count']} | {row['abstain_count']} | {row['insufficient_count']} | {row['background_like_count']} | {row['evidence_supported_density']:.4f} | {row['review_burden_reduction_vs_legacy_p1p2']:.4f} | {row['review_burden_reduction_vs_all_incidents']:.4f} |"
        )
    lines.extend(
        [
            "",
            "## 3. Real-Time Evidence Cache Answer",
            "",
            "External evidence affects real-time performance if the online path performs remote requests. The intended design avoids that: background updaters maintain versioned local caches and the online verifier performs local indexed lookups only.",
            "",
            "RPKI/VRP does not need to be downloaded per incident. It should be maintained by a relying-party / RTR-style updater or equivalent background cache materialization pipeline.",
            "",
            "Cache stale/unavailable behavior is safe degradation: the verifier emits stale_diagnostic, evidence_insufficient, external_evidence_unavailable, abstain, or conflict. It does not infer benignness and it does not block monitor-triggered alerting.",
            "",
            "## 4. Deployment Status",
            "",
            "This step does not complete real deployment. It defines deployment constraints, workload proxies, freshness/fallback policy, and SLO measurement hooks.",
            "",
            f"Can enter R-2C: `{summary['can_enter_r2c']}`",
            f"Can enter learning layer: `{summary['can_enter_learning_layer']}`",
            "",
            "Learning cannot be trained yet, but L1 component-aware learner design can begin.",
            "",
            "Recommended next step: R-2C path evidence branch / route-leak legality refinement, with R-3 poisoning benchmark and L1 learner design in parallel planning.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    warnings: list[str] = []
    table = load_table(args)
    table = add_ops_fields(table)
    summary_in = read_json(args.r2b_summary_file) if args.r2b_summary_file else {}
    vrp_meta = read_json(args.vrp_metadata_file) if args.vrp_metadata_file else {}
    if args.r2b_summary_file and not Path(args.r2b_summary_file).exists():
        warnings.append(f"optional R-2B summary missing: {args.r2b_summary_file}")
    if args.vrp_metadata_file and not Path(args.vrp_metadata_file).exists():
        warnings.append(f"optional VRP metadata missing: {args.vrp_metadata_file}")

    projection = daily_burden_projection(table, args)
    projection.to_csv(out / "r2b_daily_alert_burden_projection.csv", index=False)
    write_projection_md(out / "r2b_daily_alert_burden_projection.md", projection, args)

    topks = parse_topk(args.topk_list)
    topk_df, top_candidates = topk_simulation(table, topks)
    topk_df.to_csv(out / "r2b_topk_review_budget_simulation.csv", index=False)
    top_candidates.to_csv(out / "r2b_topk_review_candidates_ops.csv", index=False)

    realtime_architecture_md(out / "r2b_realtime_evidence_cache_architecture.md", vrp_meta)

    policy = freshness_policy()
    policy.to_csv(out / "r2b_evidence_freshness_fallback_policy.csv", index=False)
    policy_md(out / "r2b_evidence_freshness_fallback_policy.md", policy)

    slo = slo_metrics()
    slo.to_csv(out / "r2b_operational_slo_metrics.csv", index=False)
    slo_md(out / "r2b_operational_slo_draft.md", slo)

    queue_counts = distribution(table["verifier_verdict_vrp"])
    daily_rows = projection.to_dict(orient="records")
    topk_rows = topk_df.to_dict(orient="records")
    summary = {
        "run_id": args.run_id,
        "run_date": args.run_date,
        "window_hours": args.window_hours,
        "daily_scale_factor": args.daily_scale_factor,
        "input_incidents": int(len(table)),
        "verdict_distribution": queue_counts,
        "daily_burden_projection": daily_rows,
        "topk_review_simulation": topk_rows,
        "online_path_remote_lookup_allowed": False,
        "new_external_evidence_downloaded": False,
        "verifier_verdict_modified": False,
        "learning_layer_trained": False,
        "can_enter_r2c": True,
        "can_enter_learning_layer": False,
        "recommended_next_step": "R-2C path evidence branch / route-leak legality refinement; R-3 and L1 design can proceed in parallel",
        "source_r2b_status": summary_in.get("status", ""),
        "vrp_metadata_present": bool(vrp_meta),
        "warnings": warnings,
        "status": "completed",
    }
    write_json(out / "r2b_ops_summary.json", summary)
    write_ops_report(out / "r2b_ops_report.md", summary)
    print(out / "r2b_ops_summary.json")


if __name__ == "__main__":
    main()
