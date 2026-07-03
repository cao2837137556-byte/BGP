"""Read-only feasibility audit for R-ATTACK-1 family expansion.

This script does not materialize attacks. It checks whether the current clean
6h baseline and sidecars contain plausible templates for subprefix and
NO_EXPORT / stealth scenario design.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_RUN_ID = "s2a_baseline_v01_pilot_6h_april16"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument(
        "--events",
        default=f"data/runs/{DEFAULT_RUN_ID}/events/event_units.parquet",
    )
    parser.add_argument(
        "--rpki",
        default=f"outputs/r_rpki_clean_0/{DEFAULT_RUN_ID}/rpki_event_sidecar.parquet",
    )
    parser.add_argument(
        "--asrel",
        default=f"outputs/r_asrel_clean_0/{DEFAULT_RUN_ID}/asrel_2024_event_sidecar.parquet",
    )
    parser.add_argument(
        "--communities",
        default=f"outputs/r_comm_clean_0/{DEFAULT_RUN_ID}/community_event_sidecar.parquet",
    )
    parser.add_argument(
        "--output-dir",
        default=f"outputs/r_attack_1_feasibility/{DEFAULT_RUN_ID}",
    )
    parser.add_argument("--sample-size", type=int, default=200)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def ensure_output_dir(path: Path, overwrite: bool) -> None:
    if path.exists() and any(path.iterdir()) and not overwrite:
        raise SystemExit(f"output directory exists and is not empty: {path}")
    path.mkdir(parents=True, exist_ok=True)


def read_required(path: str | Path, columns: list[str] | None = None) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"required input missing: {p}")
    return pd.read_parquet(p, columns=columns)


def parse_network(value: Any) -> ipaddress._BaseNetwork | None:
    try:
        return ipaddress.ip_network(str(value), strict=False)
    except Exception:
        return None


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if pd.isna(value):
            return default
        return int(value)
    except Exception:
        return default


def sample_rows(df: pd.DataFrame, sample_size: int) -> pd.DataFrame:
    if len(df) <= sample_size:
        return df.copy()
    return df.sample(sample_size, random_state=17)


def build_event_base(events: pd.DataFrame, rpki: pd.DataFrame, asrel: pd.DataFrame, comm: pd.DataFrame) -> pd.DataFrame:
    base_cols = [
        "event_id",
        "run_id",
        "collector",
        "prefix",
        "origin_as",
        "as_path_clean",
        "as_path_len",
        "first_seen",
        "last_seen",
        "duration_sec",
        "record_count",
        "collector_count",
    ]
    base = events[[c for c in base_cols if c in events.columns]].copy()

    rpki_cols = [
        "event_id",
        "rpki_status",
        "route_prefix_len",
        "covering_vrp_max_lengths",
        "rpki_evidence_state",
    ]
    asrel_cols = [
        "event_id",
        "possible_valley_transition_2024",
        "path_relation_diagnostic_2024",
        "path_relation_evidence_state_2024",
    ]
    comm_cols = [
        "event_id",
        "has_communities",
        "has_no_export",
        "has_no_advertise",
        "has_nopeer",
        "community_evidence_state",
        "community_join_confidence",
    ]

    for sidecar, cols in ((rpki, rpki_cols), (asrel, asrel_cols), (comm, comm_cols)):
        present = [c for c in cols if c in sidecar.columns]
        base = base.merge(sidecar[present], on="event_id", how="left")
    return base


def audit_subprefix_feasibility(df: pd.DataFrame, sample_size: int) -> tuple[dict[str, Any], pd.DataFrame]:
    work = df[["event_id", "prefix", "origin_as", "collector_count", "rpki_status", "route_prefix_len"]].copy()
    work["network"] = work["prefix"].map(parse_network)
    work = work[work["network"].notna()].copy()
    work["ip_version"] = work["network"].map(lambda n: n.version)
    work["prefix_len"] = work["network"].map(lambda n: n.prefixlen)
    work["max_subprefix_len"] = work["ip_version"].map(lambda v: 24 if v == 4 else 48)
    work["can_make_more_specific"] = work["prefix_len"] < work["max_subprefix_len"]

    plausible = work[work["can_make_more_specific"]].copy()
    grouped = (
        plausible.groupby(["prefix", "origin_as"], dropna=False)
        .agg(
            event_count=("event_id", "count"),
            collector_count_max=("collector_count", "max"),
            rpki_status_sample=("rpki_status", "first"),
            prefix_len=("prefix_len", "first"),
            ip_version=("ip_version", "first"),
        )
        .reset_index()
    )
    grouped["realism_note"] = (
        "parent prefix observed; more-specific child is syntactically possible; "
        "attacker role and RPKI must be selected/recomputed later"
    )
    grouped = grouped.sort_values(["event_count", "collector_count_max"], ascending=False)

    summary = {
        "parent_prefix_origin_candidates": int(len(grouped)),
        "candidate_events": int(len(plausible)),
        "ipv4_candidate_prefix_origin_pairs": int((grouped["ip_version"] == 4).sum()),
        "ipv6_candidate_prefix_origin_pairs": int((grouped["ip_version"] == 6).sum()),
        "subprefix_feasible": bool(len(grouped) > 0),
    }
    return summary, sample_rows(grouped, sample_size)


def audit_noexport_feasibility(df: pd.DataFrame, sample_size: int) -> tuple[dict[str, Any], pd.DataFrame]:
    no_export = df[df.get("has_no_export", False).fillna(False)].copy()
    no_export["low_visibility"] = no_export.get("collector_count", 0).fillna(0).astype(int) <= 1
    sample_cols = [
        "event_id",
        "prefix",
        "origin_as",
        "collector",
        "collector_count",
        "duration_sec",
        "has_no_export",
        "has_no_advertise",
        "has_nopeer",
        "community_evidence_state",
        "community_join_confidence",
        "rpki_status",
        "path_relation_diagnostic_2024",
    ]
    present = [c for c in sample_cols if c in no_export.columns]
    summary = {
        "no_export_event_count": int(len(no_export)),
        "no_export_prefix_origin_pairs": int(
            no_export[["prefix", "origin_as"]].drop_duplicates().shape[0]
        )
        if len(no_export)
        else 0,
        "no_export_low_visibility_event_count": int(no_export["low_visibility"].sum())
        if len(no_export)
        else 0,
        "no_export_feasible_for_monitor_visible_stealth": bool(len(no_export) > 0),
        "forbidden_interpretation": "NO_EXPORT present is not attack truth; low visibility is not confirmed NO_EXPORT.",
    }
    return summary, sample_rows(no_export[present], sample_size)


def audit_hard_negative_feasibility(df: pd.DataFrame, sample_size: int) -> tuple[dict[str, Any], pd.DataFrame]:
    community_normal = df[
        df.get("has_communities", False).fillna(False)
        & ~df.get("has_no_export", False).fillna(False)
        & ~df.get("has_no_advertise", False).fillna(False)
        & ~df.get("has_nopeer", False).fillna(False)
    ].copy()

    low_visibility = df[df.get("collector_count", 0).fillna(0).astype(int) <= 1].copy()
    low_visibility = low_visibility[
        ~low_visibility.get("has_no_export", False).fillna(False)
    ].copy()

    sample = pd.concat(
        [
            community_normal.assign(hard_negative_candidate="normal_community_change").head(sample_size // 2),
            low_visibility.assign(hard_negative_candidate="low_visibility_reference").head(sample_size // 2),
        ],
        ignore_index=True,
    )
    summary = {
        "normal_community_change_candidates": int(len(community_normal)),
        "low_visibility_reference_candidates": int(len(low_visibility)),
        "hard_negative_feasible": bool(len(community_normal) > 0 and len(low_visibility) > 0),
        "truth_boundary": "These are hard-negative/control candidates, not confirmed benign labels.",
    }
    return summary, sample


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def main() -> None:
    args = parse_args()
    out = Path(args.output_dir)
    ensure_output_dir(out, args.overwrite)

    events = read_required(args.events)
    rpki = read_required(args.rpki)
    asrel = read_required(args.asrel)
    comm = read_required(args.communities)
    df = build_event_base(events, rpki, asrel, comm)

    subprefix_summary, subprefix_sample = audit_subprefix_feasibility(df, args.sample_size)
    noexport_summary, noexport_sample = audit_noexport_feasibility(df, args.sample_size)
    hardneg_summary, hardneg_sample = audit_hard_negative_feasibility(df, args.sample_size)

    evidence_summary = {
        "events_rows": int(len(events)),
        "rpki_rows": int(len(rpki)),
        "asrel_rows": int(len(asrel)),
        "community_rows": int(len(comm)),
        "event_to_rpki_rows_aligned": bool(len(events) == len(rpki)),
        "event_to_asrel_rows_aligned": bool(len(events) == len(asrel)),
        "event_to_community_rows_aligned": bool(len(events) == len(comm)),
    }
    summary = {
        "phase": "R-ATTACK-1",
        "run_id": args.run_id,
        "status": "feasibility_audit_only",
        "evidence_summary": evidence_summary,
        "subprefix": subprefix_summary,
        "noexport_stealth": noexport_summary,
        "hard_negative_controls": hardneg_summary,
        "overall_feasible": bool(
            subprefix_summary["subprefix_feasible"]
            and noexport_summary["no_export_feasible_for_monitor_visible_stealth"]
            and hardneg_summary["hard_negative_feasible"]
        ),
        "allowed_claim": "The current baseline and clean sidecars contain templates for designing R-ATTACK-1 scenarios.",
        "forbidden_claims": [
            "This audit materialized attacks.",
            "NO_EXPORT present is attack truth.",
            "NO_EXPORT absent is safe.",
            "Hard-negative candidates are confirmed benign.",
            "Subprefix feasibility proves attack realism without materializer QA.",
            "Learning is ready."
        ],
        "recommended_next_step": "If overall_feasible is true, implement bounded R-ATTACK-1 materializer and QA; otherwise repair template selection.",
    }

    write_json(out / "r_attack1_feasibility_summary.json", summary)
    subprefix_sample.to_csv(out / "subprefix_template_candidates_sample.csv", index=False)
    noexport_sample.to_csv(out / "noexport_stealth_template_candidates_sample.csv", index=False)
    hardneg_sample.to_csv(out / "hard_negative_control_candidates_sample.csv", index=False)

    report = [
        "# R-ATTACK-1 Feasibility Audit",
        "",
        f"run_id: `{args.run_id}`",
        "",
        f"overall_feasible: `{summary['overall_feasible']}`",
        "",
        "## Key Counts",
        "",
        f"- event rows: `{evidence_summary['events_rows']}`",
        f"- subprefix parent prefix-origin candidates: `{subprefix_summary['parent_prefix_origin_candidates']}`",
        f"- NO_EXPORT event count: `{noexport_summary['no_export_event_count']}`",
        f"- NO_EXPORT low-visibility event count: `{noexport_summary['no_export_low_visibility_event_count']}`",
        f"- normal community hard-negative candidates: `{hardneg_summary['normal_community_change_candidates']}`",
        f"- low-visibility reference candidates: `{hardneg_summary['low_visibility_reference_candidates']}`",
        "",
        "## Boundary",
        "",
        "This audit does not materialize attacks, prove attack realism, train learning, or claim NO_EXPORT attack detection.",
    ]
    (out / "r_attack1_feasibility_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
