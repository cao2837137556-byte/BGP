#!/usr/bin/env python3
"""R-2C-P2 path-legality verifier smoke.

This script converts R-2C-P1 path diagnostics into R-1-compatible verifier
smoke outputs. It does not generate confirmed route-leak labels, does not
modify R-2B verdicts, does not train a model, and does not treat inferred AS
relationship data as ground truth.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd


RUN_ID_DEFAULT = "s2a_expanded_v01_pilot_6h_april16"
RUN_DATE_DEFAULT = "2024-04-16"
OUTPUT_DIR_DEFAULT = "outputs/r2c_p2_path_legality_verifier_smoke_v01"

R1_VERDICTS = {
    "strongly_supported_suspicious",
    "evidence_supported_suspicious",
    "evidence_conflict",
    "evidence_insufficient",
    "external_evidence_unavailable",
    "background_like_but_unconfirmed",
    "stale_evidence_only",
    "abstain",
}

RENAMING_MAP = {
    "origin_valid_path_suspicious": "origin_valid_with_path_diagnostic",
    "origin_unknown_path_suspicious": "origin_unknown_with_path_diagnostic",
}

HARD_SAFETY_NOTES = [
    "no confirmed route-leak label is generated",
    "R-2B verifier verdict is not modified",
    "AS relationship evidence is inferred evidence, not ground truth",
    "AS-rel matched is not path benign",
    "AS-rel unmatched is not path suspicious",
    "possible valley-free diagnostics are not confirmed route leaks",
    "RPKI valid is not benign",
    "RPKI invalid is not confirmed attack",
    "safe_negative_candidate_flag must remain false",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=RUN_ID_DEFAULT)
    parser.add_argument("--run-date", default=RUN_DATE_DEFAULT)
    parser.add_argument("--incident-path-evidence-file", required=True)
    parser.add_argument("--combined-origin-path-file", required=True)
    parser.add_argument("--full-path-relation-file", required=True)
    parser.add_argument("--triplet-relation-file", required=True)
    parser.add_argument("--as-pair-relation-file", required=True)
    parser.add_argument("--r2b-verifier-table", required=True)
    parser.add_argument("--asrel-metadata-file", required=True)
    parser.add_argument("--output-dir", default=OUTPUT_DIR_DEFAULT)
    parser.add_argument("--sample-rows", type=int, default=0)
    parser.add_argument("--full-run", action="store_true")
    return parser.parse_args()


def json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, (datetime, date, Path)):
        return str(value)
    if pd.isna(value):
        return None
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def read_json(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=json_default), encoding="utf-8")


def write_table(df: pd.DataFrame, parquet_path: Path, csv_path: Path) -> None:
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(parquet_path, index=False)
    df.to_csv(csv_path, index=False)


def read_parquet_required(path: str | Path) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"required input missing: {p}")
    return pd.read_parquet(p)


def maybe_filter(df: pd.DataFrame, incident_ids: set[str] | None) -> pd.DataFrame:
    if incident_ids is None or "incident_id" not in df.columns:
        return df
    return df[df["incident_id"].astype(str).isin(incident_ids)].copy()


def distribution(series: pd.Series) -> dict[str, int]:
    if series.empty:
        return {}
    return {str(k): int(v) for k, v in series.fillna("NA").value_counts().sort_index().items()}


def safe_float(value: Any, default: float = 0.0) -> float:
    if value is None or pd.isna(value):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    if value is None or pd.isna(value):
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def mode_or_empty(series: pd.Series) -> str:
    if series.empty:
        return ""
    mode = series.dropna().astype(str).mode()
    return str(mode.iloc[0]) if not mode.empty else ""


def build_field_renaming_audit() -> dict[str, Any]:
    return {
        "status": "completed",
        "renamed_classes": RENAMING_MAP,
        "renamed_metrics": {"review_density": "path_review_signal_density"},
        "legacy_alias_policy": "legacy R-2C-P1 names are retained only in legacy_combined_origin_path_evidence_class",
        "safety_note": "diagnostic does not mean suspicious; path_review_signal_density is not attack density",
        "forbidden_as_main_output": sorted(RENAMING_MAP.keys()) + ["review_density"],
    }


def load_inputs(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any], list[str]]:
    warnings: list[str] = []
    incident_path = read_parquet_required(args.incident_path_evidence_file)
    combined = read_parquet_required(args.combined_origin_path_file)
    full_path = read_parquet_required(args.full_path_relation_file)
    triplet = read_parquet_required(args.triplet_relation_file)
    as_pair = read_parquet_required(args.as_pair_relation_file)
    r2b = read_parquet_required(args.r2b_verifier_table)
    asrel_metadata = read_json(args.asrel_metadata_file)

    if not args.full_run and args.sample_rows and len(incident_path) > args.sample_rows:
        incident_path = incident_path.head(args.sample_rows).copy()
        sample_ids = set(incident_path["incident_id"].astype(str))
        combined = maybe_filter(combined, sample_ids)
        full_path = maybe_filter(full_path, sample_ids)
        triplet = maybe_filter(triplet, sample_ids)
        as_pair = maybe_filter(as_pair, sample_ids)
        r2b = maybe_filter(r2b, sample_ids)
    else:
        sample_ids = None

    required_incident_cols = {"incident_id", "path_evidence_state", "unknown_pair_rate"}
    missing = sorted(required_incident_cols - set(incident_path.columns))
    if missing:
        raise ValueError(f"incident path evidence missing required columns: {missing}")
    if "combined_origin_path_evidence_class" not in combined.columns:
        warnings.append("combined table missing combined_origin_path_evidence_class; using insufficient_combined_evidence")
        combined["combined_origin_path_evidence_class"] = "insufficient_combined_evidence"
    if sample_ids is not None:
        warnings.append(f"sample mode active: {len(sample_ids)} incidents processed")
    return incident_path, combined, full_path, triplet, as_pair, r2b, asrel_metadata, warnings


def normalize_combined_class(value: Any) -> str:
    text = "" if pd.isna(value) else str(value)
    return RENAMING_MAP.get(text, text or "insufficient_combined_evidence")


def prepare_base_table(incident_path: pd.DataFrame, combined: pd.DataFrame, r2b: pd.DataFrame) -> pd.DataFrame:
    combined_cols = [
        "incident_id",
        "combined_origin_path_evidence_class",
        "combined_evidence_note",
        "recommended_r2c_verifier_action",
    ]
    combined_cols = [c for c in combined_cols if c in combined.columns]
    df = incident_path.merge(combined[combined_cols].drop_duplicates("incident_id"), on="incident_id", how="left")

    r2b_cols = [
        "incident_id",
        "verification_queue",
        "verifier_verdict_vrp",
        "component_purity_class",
        "triage_score_vrp",
        "incident_confidence",
        "collector_union_count",
        "rpki_invalid_share",
        "rpki_valid_share",
        "rpki_unknown_share",
        "safe_positive_candidate_flag",
    ]
    r2b_cols = [c for c in r2b_cols if c in r2b.columns]
    extra = r2b[r2b_cols].drop_duplicates("incident_id")
    df = df.merge(extra, on="incident_id", how="left", suffixes=("", "_r2b_extra"))

    if "combined_origin_path_evidence_class" not in df.columns:
        df["combined_origin_path_evidence_class"] = "insufficient_combined_evidence"
    df["legacy_combined_origin_path_evidence_class"] = df["combined_origin_path_evidence_class"].fillna("insufficient_combined_evidence")
    df["combined_origin_path_evidence_class_p2"] = df["legacy_combined_origin_path_evidence_class"].map(normalize_combined_class)

    if "r2b_verifier_verdict" not in df.columns and "verifier_verdict_vrp" in df.columns:
        df["r2b_verifier_verdict"] = df["verifier_verdict_vrp"]
    if "r2b_component_purity_class" not in df.columns and "component_purity_class" in df.columns:
        df["r2b_component_purity_class"] = df["component_purity_class"]

    bool_cols = [
        "route_leak_like_diagnostic_flag",
        "path_manipulation_like_diagnostic_flag",
        "safe_for_verifier_candidate_flag",
    ]
    for col in bool_cols:
        if col not in df.columns:
            df[col] = False
        df[col] = df[col].fillna(False).astype(bool)

    numeric_defaults = {
        "unknown_pair_rate": 1.0,
        "possible_valley_transition_share": 0.0,
        "member_count": 0,
        "high_count": 0,
        "needs_count": 0,
        "high_share": 0.0,
        "pattern_B_member_count": 0,
        "route_leak_like_review_count": 0,
    }
    for col, default in numeric_defaults.items():
        if col not in df.columns:
            df[col] = default
        df[col] = df[col].fillna(default)

    for col in [
        "r2b_verifier_verdict",
        "r2b_component_purity_class",
        "dominant_pair_rpki_status",
        "path_evidence_state",
        "path_component_purity_class",
        "dominant_path_relation_pattern_class",
        "dominant_relation_sequence",
        "verification_queue",
    ]:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].fillna("").astype(str)

    return df


def assign_verdicts(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    path_diag = out["route_leak_like_diagnostic_flag"] | out["path_manipulation_like_diagnostic_flag"]
    conflict = (
        out["legacy_combined_origin_path_evidence_class"].eq("origin_path_conflict")
        | out["path_evidence_state"].eq("conflict")
        | out["r2b_verifier_verdict"].eq("evidence_conflict")
        | out["r2b_component_purity_class"].isin(["mixed_conflicting"])
    )
    unsafe_component = out["r2b_component_purity_class"].isin(["highly_mixed_should_split", "mixed_conflicting"]) | out[
        "path_component_purity_class"
    ].isin(["path_high_unknown"])
    path_unavailable = out["path_evidence_state"].isin(["unavailable"]) | out["path_component_purity_class"].isin(["path_unusable"])
    low_unknown = out["unknown_pair_rate"].astype(float) <= 0.10
    medium_unknown = out["unknown_pair_rate"].astype(float) <= 0.35
    monitor_origin_support = out["r2b_verifier_verdict"].isin(["evidence_supported_suspicious"])
    high_confidence_monitor = (
        out["verification_queue"].isin(["high_confidence_candidate", "patternB_path_abnormal_verification"])
        & (out["high_count"].astype(float) > 0)
    )

    # Conservative by design: AS-rel cannot create support alone.
    supported = (
        monitor_origin_support
        & out["path_evidence_state"].eq("aligned_medium")
        & path_diag
        & low_unknown
        & ~unsafe_component
        & ~conflict
    )

    verdict = pd.Series("evidence_insufficient", index=out.index, dtype="object")
    verdict[conflict] = "evidence_conflict"
    verdict[path_unavailable & ~conflict & ~path_diag] = "external_evidence_unavailable"
    verdict[unsafe_component & ~conflict] = "abstain"
    verdict[supported] = "evidence_supported_suspicious"
    background = out["r2b_verifier_verdict"].eq("background_like_but_unconfirmed") & ~path_diag & ~conflict & ~supported
    verdict[background] = "background_like_but_unconfirmed"
    # Path diagnostics with too little corroboration remain insufficient, not suspicious.
    insufficient = path_diag & ~supported & ~conflict & ~unsafe_component
    verdict[insufficient] = "evidence_insufficient"

    out["path_legality_verdict_smoke"] = verdict
    cap_map = {
        "evidence_supported_suspicious": 0.75,
        "evidence_conflict": 0.55,
        "evidence_insufficient": 0.50,
        "external_evidence_unavailable": 0.45,
        "background_like_but_unconfirmed": 0.45,
        "abstain": 0.50,
        "stale_evidence_only": 0.40,
        "strongly_supported_suspicious": 0.90,
    }
    out["path_legality_confidence_cap"] = out["path_legality_verdict_smoke"].map(cap_map).fillna(0.50)

    reasons: list[str] = []
    buckets: list[str] = []
    actions: list[str] = []
    eligibility: list[str] = []
    for row in out.itertuples(index=False):
        v = getattr(row, "path_legality_verdict_smoke")
        route_flag = bool(getattr(row, "route_leak_like_diagnostic_flag"))
        manip_flag = bool(getattr(row, "path_manipulation_like_diagnostic_flag"))
        if v == "evidence_supported_suspicious":
            reasons.append("R-2B evidence-supported origin/monitor evidence plus aligned path diagnostic; not AS-rel-only")
            buckets.append("evidence_supported_path_review")
            actions.append("candidate_for_r2c_case_study")
            eligibility.append("positive_candidate")
        elif v == "evidence_conflict":
            reasons.append("origin/path/component evidence conflict remains visible")
            buckets.append("conflict_review")
            actions.append("preserve_conflict_for_review")
            eligibility.append("conflict_class")
        elif v == "abstain":
            reasons.append("mixed component or high-unknown path makes a safe path-legality smoke verdict unsafe")
            buckets.append("abstain_split_or_unknown")
            actions.append("split_component_or_wait_for_stronger_evidence")
            eligibility.append("abstain_class")
        elif v == "external_evidence_unavailable":
            reasons.append("path evidence unavailable or unusable; unavailable is not benign")
            buckets.append("wait_for_path_evidence")
            actions.append("wait_for_path_evidence_cache_or_component_split")
            eligibility.append("no")
        elif v == "background_like_but_unconfirmed":
            reasons.append("background-like under R-2B and no strong path diagnostic; not a negative label")
            buckets.append("background_sampling")
            actions.append("sample_or_wait_for_more_evidence")
            eligibility.append("ranking_only")
        else:
            if route_flag:
                buckets.append("route_leak_like_review")
            elif manip_flag:
                buckets.append("path_manipulation_like_review")
            else:
                buckets.append("path_insufficient_review")
            reasons.append("path diagnostic exists but lacks enough non-AS-rel corroboration for supported suspicious")
            actions.append("keep_insufficient_wait_for_aspa_roles_otc_or_operator_evidence")
            eligibility.append("ranking_only")
    out["path_legality_confidence_reason"] = reasons
    out["path_review_bucket"] = buckets
    out["recommended_next_action"] = actions
    out["learning_eligibility"] = eligibility
    out["safe_positive_candidate_flag"] = out["path_legality_verdict_smoke"].eq("evidence_supported_suspicious")
    out["safe_negative_candidate_flag"] = False
    out["evidence_conflict_flag"] = out["path_legality_verdict_smoke"].eq("evidence_conflict")
    out["evidence_insufficient_flag"] = out["path_legality_verdict_smoke"].eq("evidence_insufficient")
    out["abstain_flag"] = out["path_legality_verdict_smoke"].eq("abstain")
    out["background_like_flag"] = out["path_legality_verdict_smoke"].eq("background_like_but_unconfirmed")
    out["route_leak_like_review_candidate_flag"] = out["route_leak_like_diagnostic_flag"] & out["path_legality_verdict_smoke"].isin(
        ["evidence_supported_suspicious", "evidence_insufficient", "abstain", "evidence_conflict"]
    )
    out["path_manipulation_like_review_candidate_flag"] = out["path_manipulation_like_diagnostic_flag"] & out[
        "path_legality_verdict_smoke"
    ].isin(["evidence_supported_suspicious", "evidence_insufficient", "abstain", "evidence_conflict"])
    out["hard_safety_notes"] = "; ".join(HARD_SAFETY_NOTES)
    out["is_asrel_only_supported"] = out["path_legality_verdict_smoke"].eq("evidence_supported_suspicious") & ~monitor_origin_support
    out["high_confidence_monitor_side_trigger"] = high_confidence_monitor
    out["path_unknown_pair_rate"] = out["unknown_pair_rate"].astype(float)
    return out


def review_priority(verdict: str, possible_share: float, unknown_rate: float, high_share: float, supported: bool) -> str:
    if supported:
        return "high"
    if verdict == "evidence_conflict":
        return "high"
    if possible_share >= 0.50 and unknown_rate <= 0.10 and high_share >= 0.25:
        return "high"
    if possible_share > 0 or unknown_rate <= 0.35:
        return "medium"
    return "low"


def build_route_leak_queue(df: pd.DataFrame) -> pd.DataFrame:
    q = df[df["route_leak_like_review_candidate_flag"]].copy()
    if q.empty:
        return pd.DataFrame(
            columns=[
                "incident_id",
                "review_reason",
                "path_evidence_state",
                "possible_valley_transition_share",
                "unknown_pair_rate",
                "dominant_relation_sequence",
                "r2b_verifier_verdict",
                "dominant_pair_rpki_status",
                "component_purity_class",
                "recommended_manual_review_priority",
                "why_not_confirmed_route_leak",
            ]
        )
    q["review_reason"] = q.apply(
        lambda r: "possible valley/peer-transit diagnostic with path evidence; review candidate only"
        if safe_float(r.get("possible_valley_transition_share")) > 0
        else "route-leak-like queue/context evidence with insufficient path legality proof",
        axis=1,
    )
    q["component_purity_class"] = q["r2b_component_purity_class"]
    q["recommended_manual_review_priority"] = q.apply(
        lambda r: review_priority(
            str(r["path_legality_verdict_smoke"]),
            safe_float(r["possible_valley_transition_share"]),
            safe_float(r["unknown_pair_rate"]),
            safe_float(r["high_share"]),
            bool(r["safe_positive_candidate_flag"]),
        ),
        axis=1,
    )
    q["why_not_confirmed_route_leak"] = (
        "Missing ASPA/BGP Roles/OTC/operator or data-plane corroboration; CAIDA AS-rel is inferred diagnostic evidence only."
    )
    return q[
        [
            "incident_id",
            "review_reason",
            "path_evidence_state",
            "possible_valley_transition_share",
            "unknown_pair_rate",
            "dominant_relation_sequence",
            "r2b_verifier_verdict",
            "dominant_pair_rpki_status",
            "component_purity_class",
            "recommended_manual_review_priority",
            "why_not_confirmed_route_leak",
        ]
    ]


def build_path_manip_queue(df: pd.DataFrame) -> pd.DataFrame:
    q = df[df["path_manipulation_like_review_candidate_flag"]].copy()
    if q.empty:
        return pd.DataFrame(
            columns=[
                "incident_id",
                "review_reason",
                "path_manipulation_like_diagnostic_flag",
                "path_relation_pattern_class",
                "unknown_pair_rate",
                "relation_sequence_compact",
                "component_purity_class",
                "origin_evidence_class",
                "recommended_manual_review_priority",
                "why_not_confirmed_path_attack",
            ]
        )
    q["review_reason"] = "patternB/path-abnormal diagnostic with AS-rel path evidence; review candidate only"
    q["path_relation_pattern_class"] = q["dominant_path_relation_pattern_class"]
    q["relation_sequence_compact"] = q["dominant_relation_sequence"]
    q["component_purity_class"] = q["r2b_component_purity_class"]
    q["origin_evidence_class"] = q["combined_origin_path_evidence_class_p2"]
    q["recommended_manual_review_priority"] = q.apply(
        lambda r: review_priority(
            str(r["path_legality_verdict_smoke"]),
            safe_float(r["possible_valley_transition_share"]),
            safe_float(r["unknown_pair_rate"]),
            safe_float(r["high_share"]),
            bool(r["safe_positive_candidate_flag"]),
        ),
        axis=1,
    )
    q["why_not_confirmed_path_attack"] = (
        "Missing ASPA/BGP Roles/OTC/operator/data-plane corroboration; AS-rel evidence is inferred and diagnostic."
    )
    return q[
        [
            "incident_id",
            "review_reason",
            "path_manipulation_like_diagnostic_flag",
            "path_relation_pattern_class",
            "unknown_pair_rate",
            "relation_sequence_compact",
            "component_purity_class",
            "origin_evidence_class",
            "recommended_manual_review_priority",
            "why_not_confirmed_path_attack",
        ]
    ]


def build_topk(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    score_map = {
        "evidence_supported_suspicious": 60,
        "evidence_conflict": 40,
        "evidence_insufficient": 25,
        "abstain": 15,
        "external_evidence_unavailable": 5,
        "background_like_but_unconfirmed": 0,
    }
    ranked = df.copy()
    ranked["path_legality_review_score"] = (
        ranked["path_legality_verdict_smoke"].map(score_map).fillna(10).astype(float)
        + ranked["route_leak_like_review_candidate_flag"].astype(int) * 18
        + ranked["path_manipulation_like_review_candidate_flag"].astype(int) * 12
        + ranked["safe_positive_candidate_flag"].astype(int) * 25
        + ranked["possible_valley_transition_share"].astype(float).clip(0, 1) * 15
        + (1.0 - ranked["unknown_pair_rate"].astype(float).clip(0, 1)) * 8
        + ranked["high_count"].fillna(0).map(lambda x: min(math.log1p(max(float(x), 0.0)) * 1.5, 12.0))
    )
    ranked = ranked.sort_values(["path_legality_review_score", "member_count"], ascending=[False, False])
    top_candidates = ranked.head(500).copy()

    rows = []
    for k in [50, 100, 500]:
        top = ranked.head(k)
        if top.empty:
            rows.append({"topk": k, "path_review_signal_density": 0.0, "evidence_supported_density": 0.0, "notes": "no candidates"})
            continue
        signal = top["route_leak_like_review_candidate_flag"] | top["path_manipulation_like_review_candidate_flag"]
        supported = top["path_legality_verdict_smoke"].eq("evidence_supported_suspicious")
        rows.append(
            {
                "topk": k,
                "evidence_supported_count": int(supported.sum()),
                "route_leak_like_review_count": int(top["route_leak_like_review_candidate_flag"].sum()),
                "path_manipulation_like_review_count": int(top["path_manipulation_like_review_candidate_flag"].sum()),
                "conflict_count": int(top["path_legality_verdict_smoke"].eq("evidence_conflict").sum()),
                "abstain_count": int(top["path_legality_verdict_smoke"].eq("abstain").sum()),
                "insufficient_count": int(top["path_legality_verdict_smoke"].eq("evidence_insufficient").sum()),
                "background_like_count": int(top["path_legality_verdict_smoke"].eq("background_like_but_unconfirmed").sum()),
                "path_review_signal_density": float(signal.sum() / len(top)),
                "evidence_supported_density": float(supported.sum() / len(top)),
                "notes": "deterministic smoke score; path_review_signal_density is not attack density",
            }
        )
    return pd.DataFrame(rows), top_candidates


def hard_safety_audit(df: pd.DataFrame) -> pd.DataFrame:
    checks = [
        {
            "rule": "no_confirmed_route_leak",
            "violation_count": 0,
            "status": "pass",
            "note": "script does not emit confirmed route-leak labels",
        },
        {
            "rule": "strongly_supported_suspicious_zero",
            "violation_count": int(df["path_legality_verdict_smoke"].eq("strongly_supported_suspicious").sum()),
            "note": "R-2C-P2 should not emit strong verdict without ASPA/Roles/OTC/operator/data-plane support",
        },
        {
            "rule": "no_asrel_only_evidence_supported",
            "violation_count": int(df["is_asrel_only_supported"].sum()),
            "note": "evidence_supported_suspicious requires R-2B evidence-supported support plus path diagnostic",
        },
        {
            "rule": "safe_negative_always_false",
            "violation_count": int(df["safe_negative_candidate_flag"].astype(bool).sum()),
            "note": "background-like is not confirmed normal",
        },
        {
            "rule": "p2_main_class_names_do_not_use_p1_suspicious_terms",
            "violation_count": int(
                df["combined_origin_path_evidence_class_p2"].isin(
                    ["origin_valid_path_suspicious", "origin_unknown_path_suspicious"]
                ).sum()
            ),
            "note": "P2 main fields use diagnostic naming",
        },
    ]
    out = pd.DataFrame(checks)
    out["status"] = out["violation_count"].map(lambda x: "pass" if int(x) == 0 else "fail")
    return out


def write_report(path: Path, summary: dict[str, Any]) -> None:
    topk = summary["topk_summary"]
    lines = [
        "# R-2C-P2 Path-legality Verifier Smoke Report",
        "",
        f"Run id: `{summary['run_id']}`",
        f"Run date: `{summary['run_date']}`",
        f"Mode: `{'full' if summary['full_run'] else 'sample'}`",
        "",
        "## Required Safety Answers",
        "",
        "- Did R-2C-P2 generate a confirmed route-leak label? No.",
        "- Did it modify the R-2B verifier verdict? No.",
        "- Did it treat AS-rel as ground truth? No.",
        "- Did it treat possible valley-free diagnostics as confirmed route leaks? No.",
        "- Did it train the learning layer? No; formal training remains blocked.",
        "",
        "## Naming Tightening",
        "",
        "`origin_valid_path_suspicious` and `origin_unknown_path_suspicious` from R-2C-P1 are renamed to `origin_valid_with_path_diagnostic` and `origin_unknown_with_path_diagnostic` in P2 main outputs. Diagnostic does not mean suspicious. `path_review_signal_density` is a review-signal density, not attack density.",
        "",
        "## Verdict Distribution",
        "",
        f"`{summary['path_legality_verdict_distribution']}`",
        "",
        "## Review Candidate Counts",
        "",
        f"- route-leak-like review candidates: `{summary['route_leak_like_review_candidate_count']}`",
        f"- path-manipulation-like review candidates: `{summary['path_manipulation_like_review_candidate_count']}`",
        f"- evidence_supported_suspicious: `{summary['evidence_supported_suspicious_count']}`",
        f"- strongly_supported_suspicious: `{summary['strongly_supported_suspicious_count']}`",
        f"- hard safety violations: `{summary['hard_safety_violations']}`",
        "",
        "## Top-K Review Smoke",
        "",
        f"`{topk}`",
        "",
        "## Interpretation",
        "",
        "R-2C-P2 turns path diagnostics into a conservative verifier-smoke queue. It separates review candidates, insufficient cases, conflict, background-like, and abstain. It still does not claim route-leak truth because the current path evidence is CAIDA AS-rel only and lacks ASPA, BGP Roles / OTC, operator confirmation, or data-plane corroboration.",
        "",
        "## Next Step",
        "",
        "Recommended order: R-2D-0 communities / NO_EXPORT field availability audit, L1 component-aware semantic learner design, and R-3 poisoning benchmark early design. Formal learning training remains blocked until verifier-supported targets and robustness scenarios are ready.",
        "",
        "## Warnings",
        "",
    ]
    for warning in summary.get("warnings", []):
        lines.append(f"- {warning}")
    if not summary.get("warnings"):
        lines.append("- None.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    incident_path, combined, full_path, triplet, as_pair, r2b, asrel_metadata, warnings = load_inputs(args)
    base = prepare_base_table(incident_path, combined, r2b)
    table = assign_verdicts(base)

    route_queue = build_route_leak_queue(table)
    manip_queue = build_path_manip_queue(table)
    topk_summary, topk_candidates = build_topk(table)
    safety = hard_safety_audit(table)

    verifier_cols = [
        "incident_id",
        "r2b_verifier_verdict",
        "path_legality_verdict_smoke",
        "path_review_bucket",
        "path_legality_confidence_cap",
        "path_legality_confidence_reason",
        "legacy_combined_origin_path_evidence_class",
        "combined_origin_path_evidence_class_p2",
        "route_leak_like_review_candidate_flag",
        "path_manipulation_like_review_candidate_flag",
        "evidence_conflict_flag",
        "evidence_insufficient_flag",
        "abstain_flag",
        "background_like_flag",
        "learning_eligibility",
        "safe_positive_candidate_flag",
        "safe_negative_candidate_flag",
        "hard_safety_notes",
        "dominant_pair_rpki_status",
        "path_evidence_state",
        "path_unknown_pair_rate",
        "possible_valley_transition_share",
        "r2b_component_purity_class",
        "path_component_purity_class",
        "recommended_next_action",
    ]
    verifier_cols = [c for c in verifier_cols if c in table.columns]
    verifier_table = table[verifier_cols].copy()

    write_table(verifier_table, out_dir / "r2c_p2_incident_verifier_smoke_table.parquet", out_dir / "r2c_p2_incident_verifier_smoke_table.csv")
    write_table(route_queue, out_dir / "r2c_route_leak_like_review_candidates.parquet", out_dir / "r2c_route_leak_like_review_candidates.csv")
    write_table(manip_queue, out_dir / "r2c_path_manipulation_like_review_candidates.parquet", out_dir / "r2c_path_manipulation_like_review_candidates.csv")
    topk_summary.to_csv(out_dir / "r2c_p2_topk_path_legality_review_simulation.csv", index=False)
    topk_candidates.to_csv(out_dir / "r2c_p2_topk_review_candidates.csv", index=False)
    table["path_legality_verdict_smoke"].value_counts().rename_axis("path_legality_verdict_smoke").reset_index(name="incident_count").to_csv(
        out_dir / "r2c_p2_verdict_distribution.csv", index=False
    )
    table["path_review_bucket"].value_counts().rename_axis("path_review_bucket").reset_index(name="incident_count").to_csv(
        out_dir / "r2c_p2_review_bucket_distribution.csv", index=False
    )
    safety.to_csv(out_dir / "r2c_p2_hard_safety_audit.csv", index=False)
    write_json(out_dir / "r2c_p2_field_renaming_audit.json", build_field_renaming_audit())

    hard_safety_violations = int(safety["violation_count"].sum())
    if int(table["path_legality_verdict_smoke"].eq("strongly_supported_suspicious").sum()) > 0:
        warnings.append("strongly_supported_suspicious appeared in R-2C-P2; this should remain zero without ASPA/Roles/OTC/operator/data-plane support")
    if hard_safety_violations > 0:
        warnings.append(f"hard safety audit reported {hard_safety_violations} violations")

    summary = {
        "run_id": args.run_id,
        "run_date": args.run_date,
        "full_run": bool(args.full_run),
        "sample_rows": 0 if args.full_run else int(args.sample_rows or 0),
        "processed_incidents": int(len(table)),
        "asrel_snapshot_date": asrel_metadata.get("snapshot_date", ""),
        "asrel_alignment_delta_days": asrel_metadata.get("alignment_delta_days"),
        "path_legality_verdict_distribution": distribution(table["path_legality_verdict_smoke"]),
        "review_bucket_distribution": distribution(table["path_review_bucket"]),
        "route_leak_like_review_candidate_count": int(table["route_leak_like_review_candidate_flag"].sum()),
        "path_manipulation_like_review_candidate_count": int(table["path_manipulation_like_review_candidate_flag"].sum()),
        "evidence_supported_suspicious_count": int(table["path_legality_verdict_smoke"].eq("evidence_supported_suspicious").sum()),
        "evidence_conflict_count": int(table["path_legality_verdict_smoke"].eq("evidence_conflict").sum()),
        "evidence_insufficient_count": int(table["path_legality_verdict_smoke"].eq("evidence_insufficient").sum()),
        "abstain_count": int(table["path_legality_verdict_smoke"].eq("abstain").sum()),
        "background_like_count": int(table["path_legality_verdict_smoke"].eq("background_like_but_unconfirmed").sum()),
        "external_unavailable_count": int(table["path_legality_verdict_smoke"].eq("external_evidence_unavailable").sum()),
        "strongly_supported_suspicious_count": int(table["path_legality_verdict_smoke"].eq("strongly_supported_suspicious").sum()),
        "hard_safety_violations": hard_safety_violations,
        "topk_summary": topk_summary.to_dict(orient="records"),
        "field_renaming_audit": build_field_renaming_audit(),
        "confirmed_route_leak_generated": False,
        "r2b_verifier_verdict_modified": False,
        "asrel_used_as_ground_truth": False,
        "learning_layer_trained": False,
        "no_export_or_communities_executed": False,
        "as_hegemony_executed": False,
        "new_external_evidence_downloaded": False,
        "can_enter_r2d0_communities_audit": True,
        "can_enter_l1_design": True,
        "can_train_learning_layer": False,
        "recommended_next_step": "R-2D-0 communities field availability audit, L1 component-aware semantic learner design, and R-3 poisoning benchmark early design; do not train until verifier-supported targets exist.",
        "warnings": warnings,
        "status": "completed",
    }
    write_json(out_dir / "r2c_p2_summary.json", summary)
    write_report(out_dir / "r2c_p2_report.md", summary)
    print(json.dumps(summary, indent=2, sort_keys=True, default=json_default))


if __name__ == "__main__":
    main()
