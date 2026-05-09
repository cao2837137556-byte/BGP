import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from run_s3c1_visibility_path_plausibility_pilot import (
    BASELINE_PO_COLS,
    CANDIDATE_COLS,
    EVENT_COLS,
    FINAL_COLS,
    GATING_COLS,
    MEMBERSHIP_COLS,
    RUN_ID_DEFAULT,
    SCORE_COLS,
    TICKET_COLS,
    add_baseline_po,
    add_candidate_join,
    add_event_join,
    add_flags,
    add_incident_context,
    add_plausibility_scores,
    add_simple_optional_join,
    add_temporal_confirmation,
    bool_col,
    build_known_event_check,
    bucket_from_score,
    json_default,
    label_col,
    load_score_thresholds,
    normalize_base,
    num_col,
    parquet_row_count,
    read_parquet_limited,
    score_history,
    score_path_length,
    score_relation,
    score_temporal,
    score_visibility,
    str2bool,
    text_col,
    to_rel_path,
)


OUTPUT_DIR_DEFAULT = "outputs/s3c1b_penalty_calibration_v01"

STRATEGIES: list[dict[str, Any]] = [
    {
        "strategy": "strategy_default_s3c1",
        "low_penalty": 15.0,
        "medium_penalty": 5.0,
        "gate_low": False,
        "gate_medium": False,
        "allow_recommend": False,
        "notes": "S3-C1 default upper-bound, forbidden as main recommendation.",
    },
    {
        "strategy": "strategy_low_only_minus15",
        "low_penalty": 15.0,
        "medium_penalty": 0.0,
        "gate_low": False,
        "gate_medium": False,
        "allow_recommend": True,
        "notes": "Only low-plausibility pattern_A receives the original strong penalty.",
    },
    {
        "strategy": "strategy_low_only_minus10",
        "low_penalty": 10.0,
        "medium_penalty": 0.0,
        "gate_low": False,
        "gate_medium": False,
        "allow_recommend": True,
        "notes": "Only low-plausibility pattern_A receives a moderate penalty.",
    },
    {
        "strategy": "strategy_low_minus10_medium_minus2",
        "low_penalty": 10.0,
        "medium_penalty": 2.0,
        "gate_low": False,
        "gate_medium": False,
        "allow_recommend": True,
        "notes": "Soft score penalty for medium-plausibility pattern_A.",
    },
    {
        "strategy": "strategy_low_minus8_medium_minus2",
        "low_penalty": 8.0,
        "medium_penalty": 2.0,
        "gate_low": False,
        "gate_medium": False,
        "allow_recommend": True,
        "notes": "Even softer low penalty plus medium soft penalty.",
    },
    {
        "strategy": "strategy_gate_only",
        "low_penalty": 0.0,
        "medium_penalty": 0.0,
        "gate_low": True,
        "gate_medium": True,
        "allow_recommend": True,
        "notes": "No score change; low/medium pattern_A becomes gate evidence.",
    },
    {
        "strategy": "strategy_medium_gate_only",
        "low_penalty": 10.0,
        "medium_penalty": 0.0,
        "gate_low": False,
        "gate_medium": True,
        "allow_recommend": True,
        "notes": "Low gets a moderate score penalty; medium becomes gate evidence.",
    },
]


def pct(num: float, den: float) -> float:
    return float(num / den) if den else 0.0


def build_plausibility_frame(args: argparse.Namespace) -> tuple[pd.DataFrame, dict[str, Any]]:
    run_id = args.run_id
    run_dir = Path("data") / "runs" / run_id
    warnings: list[str] = []

    scores_path = Path(args.scores) if args.scores else run_dir / "scores" / "scored_candidates.parquet"
    candidate_path = Path(args.candidates) if args.candidates else run_dir / "candidates" / "candidate_events.parquet"
    event_path = Path(args.events) if args.events else run_dir / "events" / "event_units.parquet"
    gating_path = Path(args.gating) if args.gating else run_dir / "gating" / "gated_candidates.parquet"
    final_path = Path(args.final) if args.final else run_dir / "final" / "final_alerts.parquet"
    membership_path = Path(args.membership) if args.membership else run_dir / "incidents" / "incident_membership.parquet"
    tickets_path = (
        Path(args.tickets)
        if args.tickets
        else Path("outputs") / "s3a2_incident_priority_calibration_v01" / "s3a2_calibrated_incident_tickets.parquet"
    )
    baseline_po_path = Path(args.baseline_prefix_origin) if args.baseline_prefix_origin else run_dir / "baseline" / "baseline_prefix_origin.parquet"

    if not scores_path.exists():
        raise SystemExit(f"required S3-C1b input missing: {to_rel_path(scores_path)}")

    source_rows = parquet_row_count(scores_path)
    sample_rows = None if args.full_run else args.sample_rows
    if not args.full_run and not sample_rows:
        sample_rows = 200_000

    scores = read_parquet_limited(scores_path, SCORE_COLS, sample_rows, warnings)
    if scores.empty:
        raise SystemExit(f"no score rows loaded from {to_rel_path(scores_path)}")
    scores = normalize_base(scores)

    join_info: dict[str, Any] = {}
    base, join_info["candidate_events"] = add_candidate_join(scores, candidate_path, warnings)
    base, join_info["event_units"] = add_event_join(base, event_path, warnings)
    base, join_info["gating"] = add_simple_optional_join(base, gating_path, GATING_COLS, "gated_candidates", warnings, "gating")
    base, join_info["final"] = add_simple_optional_join(base, final_path, FINAL_COLS, "final_alerts", warnings, "final")
    base, join_info["baseline_prefix_origin"] = add_baseline_po(base, baseline_po_path, warnings)
    base, incident_info = add_incident_context(base, membership_path, tickets_path, warnings)
    join_info.update(incident_info)

    base = normalize_base(base)
    base = add_flags(base)
    base = add_temporal_confirmation(base, int(args.temporal_window_sec))
    base["visibility_support_score"] = score_visibility(base)
    base["temporal_support_score"] = score_temporal(base)
    base["history_support_score"] = score_history(base)
    base["path_length_plausibility_score"] = score_path_length(base)
    relation_source_available = bool(
        join_info.get("event_units", {}).get("available")
        and set(join_info.get("event_units", {}).get("columns", [])) & {"rel_unknown_cnt", "rel_has_unknown", "rel_seq"}
    )
    base["relation_support_score"], relation_available = score_relation(base, relation_source_available)
    base = add_plausibility_scores(base, relation_available)

    thresholds = load_score_thresholds(run_dir, base, warnings)
    meta = {
        "run_id": run_id,
        "source_rows": int(source_rows),
        "loaded_rows": int(len(base)),
        "sample_rows": sample_rows,
        "full_run": bool(args.full_run),
        "risk_bucket_thresholds": thresholds,
        "join_info": join_info,
        "warnings": warnings,
    }
    return base, meta


def apply_strategy(df: pd.DataFrame, strategy: dict[str, Any], thresholds: dict[str, float]) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    out["strategy"] = strategy["strategy"]
    penalty_target = df["pattern_A_flag"] & ~df["pattern_B_flag"]
    low_target = penalty_target & df["plausibility_bucket"].eq("low_plausibility")
    medium_target = penalty_target & df["plausibility_bucket"].eq("medium_plausibility")
    penalty = pd.Series(0.0, index=df.index)
    penalty.loc[low_target] = float(strategy["low_penalty"])
    penalty.loc[medium_target] = float(strategy["medium_penalty"])
    out["plausibility_penalty"] = penalty
    out["adjusted_risk_score"] = (num_col(df, "risk_score") - penalty).clip(lower=0.0, upper=100.0).round(4)
    out["adjusted_risk_bucket"] = out["adjusted_risk_score"].map(lambda value: bucket_from_score(float(value), thresholds))
    out["adjusted_down"] = penalty > 0
    out["bucket_changed"] = text_col(df, "risk_bucket").ne(out["adjusted_risk_bucket"])
    gate_flag = pd.Series(False, index=df.index)
    if bool(strategy.get("gate_low")):
        gate_flag = gate_flag | low_target
    if bool(strategy.get("gate_medium")):
        gate_flag = gate_flag | medium_target
    out["gate_evidence_flag"] = gate_flag
    return out


def strategy_metrics(df: pd.DataFrame, result: pd.DataFrame, strategy: dict[str, Any], known: dict[str, Any]) -> dict[str, Any]:
    before_bucket = text_col(df, "risk_bucket")
    after_bucket = result["adjusted_risk_bucket"]
    pattern_a = df["pattern_A_flag"]
    pattern_b = df["pattern_B_flag"]
    p1p2_mask = text_col(df, "calibrated_priority").isin(["P1_high", "P2_review"]) if "calibrated_priority" in df.columns else pd.Series(False, index=df.index)
    adjusted_p1p2 = p1p2_mask & result["adjusted_down"]
    gate_p1p2 = p1p2_mask & result["gate_evidence_flag"]
    out = {
        "strategy": strategy["strategy"],
        "notes": strategy["notes"],
        "low_penalty": float(strategy["low_penalty"]),
        "medium_penalty": float(strategy["medium_penalty"]),
        "gate_low": bool(strategy["gate_low"]),
        "gate_medium": bool(strategy["gate_medium"]),
        "input_rows": int(len(df)),
        "bucket_changed_rows": int(result["bucket_changed"].sum()),
        "bucket_changed_rate": float(result["bucket_changed"].mean()) if len(df) else 0.0,
        "high_before": int(before_bucket.eq("high").sum()),
        "high_after": int(after_bucket.eq("high").sum()),
        "medium_before": int(before_bucket.eq("medium").sum()),
        "medium_after": int(after_bucket.eq("medium").sum()),
        "low_before": int(before_bucket.eq("low").sum()),
        "low_after": int(after_bucket.eq("low").sum()),
        "pattern_A_rows": int(pattern_a.sum()),
        "pattern_A_adjusted_down_rows": int((pattern_a & result["adjusted_down"]).sum()),
        "pattern_A_bucket_changed_rows": int((pattern_a & result["bucket_changed"]).sum()),
        "pattern_A_gate_evidence_rows": int((pattern_a & result["gate_evidence_flag"]).sum()),
        "pattern_B_rows": int(pattern_b.sum()),
        "pattern_B_adjusted_down_rows": int((pattern_b & result["adjusted_down"]).sum()),
        "pattern_B_bucket_changed_rows": int((pattern_b & result["bucket_changed"]).sum()),
        "pattern_B_gate_evidence_rows": int((pattern_b & result["gate_evidence_flag"]).sum()),
        "P1_P2_adjusted_down_rows": int(adjusted_p1p2.sum()),
        "P1_P2_gate_evidence_rows": int(gate_p1p2.sum()),
        "touched_p1_p2_incidents": int(df.loc[adjusted_p1p2 | gate_p1p2, "incident_id"].nunique()) if "incident_id" in df.columns else 0,
        "touched_p1_incidents": int(df.loc[(adjusted_p1p2 | gate_p1p2) & text_col(df, "calibrated_priority").eq("P1_high"), "incident_id"].nunique()) if "incident_id" in df.columns else 0,
        "touched_p2_incidents": int(df.loc[(adjusted_p1p2 | gate_p1p2) & text_col(df, "calibrated_priority").eq("P2_review"), "incident_id"].nunique()) if "incident_id" in df.columns else 0,
        "estimated_high_to_medium": int((before_bucket.eq("high") & after_bucket.eq("medium")).sum()),
        "estimated_medium_to_low": int((before_bucket.eq("medium") & after_bucket.eq("low")).sum()),
        "estimated_high_to_low": int((before_bucket.eq("high") & after_bucket.eq("low")).sum()),
        "known_event_retained_count": known.get("known_event_retained_count"),
        "known_event_regression_count": known.get("known_event_regression_count"),
        "known_event_matched_rows": known.get("known_event_matched_rows"),
        "known_event_available": known.get("known_event_available"),
    }
    out["high_delta"] = out["high_after"] - out["high_before"]
    out["medium_delta"] = out["medium_after"] - out["medium_before"]
    out["low_delta"] = out["low_after"] - out["low_before"]
    return out


def transition_matrix(df: pd.DataFrame, result: pd.DataFrame, strategy_name: str) -> pd.DataFrame:
    return (
        pd.DataFrame(
            {
                "strategy": strategy_name,
                "risk_bucket_before": text_col(df, "risk_bucket"),
                "risk_bucket_after": result["adjusted_risk_bucket"],
            }
        )
        .groupby(["strategy", "risk_bucket_before", "risk_bucket_after"], dropna=False)
        .size()
        .reset_index(name="rows")
    )


def pattern_delta(df: pd.DataFrame, result: pd.DataFrame, strategy_name: str, pattern_col: str, pattern_name: str) -> dict[str, Any]:
    mask = df[pattern_col]
    sub = df[mask]
    res = result[mask]
    return {
        "strategy": strategy_name,
        "pattern_name": pattern_name,
        "rows": int(len(sub)),
        "adjusted_down_rows": int(res["adjusted_down"].sum()),
        "bucket_changed_rows": int(res["bucket_changed"].sum()),
        "gate_evidence_rows": int(res["gate_evidence_flag"].sum()),
        "mean_risk_before": float(num_col(sub, "risk_score").mean()) if len(sub) else 0.0,
        "mean_adjusted_risk": float(res["adjusted_risk_score"].mean()) if len(res) else 0.0,
        "mean_plausibility_score": float(num_col(sub, "path_plausibility_score").mean()) if len(sub) else 0.0,
        "low_plausibility_rows": int(text_col(sub, "plausibility_bucket").eq("low_plausibility").sum()),
        "medium_plausibility_rows": int(text_col(sub, "plausibility_bucket").eq("medium_plausibility").sum()),
        "high_plausibility_rows": int(text_col(sub, "plausibility_bucket").eq("high_plausibility").sum()),
    }


def p1_p2_impact(df: pd.DataFrame, result: pd.DataFrame, strategy_name: str) -> dict[str, Any]:
    priority = text_col(df, "calibrated_priority")
    p1p2 = priority.isin(["P1_high", "P2_review"])
    adjusted = p1p2 & result["adjusted_down"]
    gate = p1p2 & result["gate_evidence_flag"]
    impacted = adjusted | gate
    return {
        "strategy": strategy_name,
        "p1_p2_rows_joined": int(p1p2.sum()),
        "p1_p2_adjusted_down_rows": int(adjusted.sum()),
        "p1_p2_gate_evidence_rows": int(gate.sum()),
        "p1_p2_impacted_rows": int(impacted.sum()),
        "touched_p1_p2_incidents": int(df.loc[impacted, "incident_id"].nunique()) if "incident_id" in df.columns else 0,
        "touched_p1_incidents": int(df.loc[impacted & priority.eq("P1_high"), "incident_id"].nunique()) if "incident_id" in df.columns else 0,
        "touched_p2_incidents": int(df.loc[impacted & priority.eq("P2_review"), "incident_id"].nunique()) if "incident_id" in df.columns else 0,
    }


def match_known_events(df: pd.DataFrame, known_event_file: Path, warnings: list[str]) -> tuple[pd.DataFrame, dict[str, Any]]:
    columns = [
        "event_name",
        "slug",
        "event_type",
        "anchor_type",
        "matched_rows",
        "status",
    ]
    if not known_event_file.exists():
        warnings.append(f"known-event inventory not found: {to_rel_path(known_event_file)}")
        return pd.DataFrame(columns=columns), {"available": False, "reason": "file_not_found", "path": to_rel_path(known_event_file)}
    try:
        data = json.loads(known_event_file.read_text(encoding="utf-8"))
    except Exception as exc:
        warnings.append(f"could not parse known-event inventory: {exc}")
        return pd.DataFrame(columns=columns), {"available": False, "reason": "parse_failed", "path": to_rel_path(known_event_file)}

    rows = []
    known_mask = pd.Series(False, index=df.index)
    event_masks: dict[str, pd.Series] = {}
    for item in data.get("events", []):
        prefixes = {str(p) for p in item.get("target_prefixes", [])}
        actors = {str(v) for v in item.get("known_attacker_asns", []) if v is not None}
        for key in ["known_malicious_origin_asn", "anchor_origin_as"]:
            value = item.get(key)
            if value is not None:
                actors.add(str(value))
        mask = text_col(df, "prefix").isin(prefixes)
        if actors:
            mask = mask & text_col(df, "origin_as_norm").isin(actors)
        slug = str(item.get("slug", ""))
        event_masks[slug] = mask
        known_mask = known_mask | mask
        rows.append(
            {
                "event_name": str(item.get("event_name", "")),
                "slug": slug,
                "event_type": str(item.get("event_type", "")),
                "anchor_type": str(item.get("anchor_type", "")),
                "matched_rows": int(mask.sum()),
                "status": "matched" if int(mask.sum()) else "not_visible_in_loaded_run",
            }
        )
    base = pd.DataFrame(rows, columns=columns)
    return base, {
        "available": True,
        "path": to_rel_path(known_event_file),
        "event_count": int(len(base)),
        "matched_event_count": int((base["matched_rows"] > 0).sum()) if not base.empty else 0,
        "matched_rows": int(known_mask.sum()),
        "known_mask": known_mask,
        "event_masks": event_masks,
    }


def known_strategy_rows(
    df: pd.DataFrame,
    result: pd.DataFrame,
    strategy_name: str,
    known_base: pd.DataFrame,
    known_info: dict[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if not known_info.get("available"):
        out = known_base.copy()
        out["strategy"] = strategy_name
        return out, {
            "known_event_available": False,
            "known_event_matched_rows": None,
            "known_event_retained_count": None,
            "known_event_regression_count": None,
        }
    rows = []
    known_mask = known_info.get("known_mask", pd.Series(False, index=df.index))
    before = text_col(df, "risk_bucket")
    after = result["adjusted_risk_bucket"]
    regress_mask = known_mask & result["bucket_changed"] & (
        (before.eq("high") & after.isin(["medium", "low"])) | (before.eq("medium") & after.eq("low"))
    )
    for _, row in known_base.iterrows():
        mask = known_info["event_masks"].get(str(row["slug"]), pd.Series(False, index=df.index))
        event_regress = mask & regress_mask
        event_adjust = mask & result["adjusted_down"]
        rows.append(
            {
                **row.to_dict(),
                "strategy": strategy_name,
                "adjusted_down_rows": int(event_adjust.sum()),
                "bucket_changed_rows": int((mask & result["bucket_changed"]).sum()),
                "regression_rows": int(event_regress.sum()),
                "retained_rows": int(mask.sum() - event_regress.sum()),
            }
        )
    return pd.DataFrame(rows), {
        "known_event_available": True,
        "known_event_matched_rows": int(known_mask.sum()),
        "known_event_retained_count": int(known_mask.sum() - regress_mask.sum()),
        "known_event_regression_count": int(regress_mask.sum()),
    }


def choose_recommended_strategy(comparison: pd.DataFrame) -> dict[str, Any]:
    default = comparison[comparison["strategy"] == "strategy_default_s3c1"].iloc[0].to_dict()
    candidates = comparison[(comparison["strategy"] != "strategy_default_s3c1") & (comparison["pattern_B_adjusted_down_rows"] == 0)].copy()
    if "known_event_available" in candidates.columns and candidates["known_event_available"].fillna(False).any():
        candidates = candidates[candidates["known_event_regression_count"].fillna(0) <= 0]
    if candidates.empty:
        row = comparison[comparison["strategy"] == "strategy_gate_only"].iloc[0].to_dict()
        return {
            "recommended_strategy": row["strategy"],
            "reason": "Fallback to gate-only because score-changing candidates failed protection/regression filters.",
            "metrics": row,
        }

    high_before = float(default["high_before"])
    default_bucket_changed = float(default["bucket_changed_rows"])
    default_p1p2 = float(default["P1_P2_adjusted_down_rows"])
    preferred = [
        "strategy_medium_gate_only",
        "strategy_low_only_minus10",
        "strategy_low_only_minus15",
        "strategy_low_minus8_medium_minus2",
        "strategy_low_minus10_medium_minus2",
        "strategy_gate_only",
    ]
    candidates["bucket_ratio_vs_default"] = candidates["bucket_changed_rows"] / max(default_bucket_changed, 1.0)
    candidates["p1p2_score_down_ratio_vs_default"] = candidates["P1_P2_adjusted_down_rows"] / max(default_p1p2, 1.0)
    candidates["high_drop_ratio"] = (candidates["high_before"] - candidates["high_after"]) / max(high_before, 1.0)
    candidates["still_affects_pattern_A"] = (candidates["pattern_A_adjusted_down_rows"] + candidates["pattern_A_gate_evidence_rows"]) > 0

    for name in preferred:
        subset = candidates[candidates["strategy"] == name]
        if subset.empty:
            continue
        row = subset.iloc[0]
        if not bool(row["still_affects_pattern_A"]):
            continue
        if name in {"strategy_medium_gate_only", "strategy_low_only_minus10", "strategy_low_only_minus15", "strategy_gate_only"}:
            if float(row["bucket_ratio_vs_default"]) <= 0.35 and float(row["high_drop_ratio"]) <= 0.20:
                return {
                    "recommended_strategy": name,
                    "reason": "Balances reduced bucket migration with continued pattern_A control and keeps pattern_B protected.",
                    "metrics": row.to_dict(),
                }
        if float(row["bucket_ratio_vs_default"]) <= 0.55 and float(row["high_drop_ratio"]) <= 0.30:
            return {
                "recommended_strategy": name,
                "reason": "Best available score-changing compromise under migration/high-drop caps.",
                "metrics": row.to_dict(),
            }

    gate = comparison[comparison["strategy"] == "strategy_gate_only"].iloc[0].to_dict()
    return {
        "recommended_strategy": "strategy_gate_only",
        "reason": "All score-changing strategies still migrate too many rows; use plausibility as S3-C2 gate evidence only.",
        "metrics": gate,
    }


def write_report(path: Path, summary: dict[str, Any], comparison: pd.DataFrame, recommendation: dict[str, Any]) -> None:
    default = comparison[comparison["strategy"] == "strategy_default_s3c1"].iloc[0]
    rec_name = recommendation["recommended_strategy"]
    rec = comparison[comparison["strategy"] == rec_name].iloc[0]
    lines = [
        "# S3-C1b Penalty Calibration",
        "",
        f"run_id: `{summary['run_id']}`",
        f"status: `{summary['status']}`",
        "",
        "## Summary",
        "",
        f"- loaded_rows: `{summary['loaded_rows']}`",
        f"- default bucket_changed_rows: `{int(default['bucket_changed_rows'])}`",
        f"- recommended_strategy: `{rec_name}`",
        f"- recommended bucket_changed_rows: `{int(rec['bucket_changed_rows'])}`",
        f"- recommended P1/P2 adjusted_down_rows: `{int(rec['P1_P2_adjusted_down_rows'])}`",
        f"- recommended P1/P2 gate_evidence_rows: `{int(rec['P1_P2_gate_evidence_rows'])}`",
        "",
        "## Required Answers",
        "",
        "### 1. Why is S3-C1 default too aggressive?",
        "",
        f"The default changes `{int(default['bucket_changed_rows'])}` risk buckets and moves score-high from `{int(default['high_before'])}` to `{int(default['high_after'])}`. It is useful as an upper bound, not as a mainline replacement.",
        "",
        "### 2. Which strategy is most stable?",
        "",
        f"`{rec_name}` is recommended. {recommendation['reason']}",
        "",
        "### 3. Is pattern_A still constrained?",
        "",
        f"The recommended strategy has `pattern_A_adjusted_down_rows={int(rec['pattern_A_adjusted_down_rows'])}` and `pattern_A_gate_evidence_rows={int(rec['pattern_A_gate_evidence_rows'])}`.",
        "",
        "### 4. Is pattern_B protected?",
        "",
        f"Yes. The recommended strategy has `pattern_B_adjusted_down_rows={int(rec['pattern_B_adjusted_down_rows'])}` and `pattern_B_bucket_changed_rows={int(rec['pattern_B_bucket_changed_rows'])}`.",
        "",
        "### 5. Is P1/P2 impact controllable?",
        "",
        f"Recommended P1/P2 score-down rows are `{int(rec['P1_P2_adjusted_down_rows'])}` and gate-evidence rows are `{int(rec['P1_P2_gate_evidence_rows'])}`. This separates hard score movement from S3-C2 evidence routing.",
        "",
        "### 6. Known-event regression",
        "",
        f"known_event_available=`{bool(summary['known_event_info'].get('available'))}`. Regression count for recommended strategy is `{rec.get('known_event_regression_count')}`.",
        "",
        "### 7. Next step",
        "",
        "Use the recommended strategy as S3-C2 gate evidence input. Do not directly adopt `strategy_default_s3c1` into the main score path.",
        "",
        "### 8. Score replacement or gate evidence?",
        "",
        "The recommended path is gate evidence. This preserves the layered-decision story: score remains broad, gate consumes plausibility as corroboration.",
    ]
    if summary.get("warnings"):
        lines.extend(["", "## Warnings", ""])
        lines.extend([f"- {item}" for item in summary["warnings"]])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    df, meta = build_plausibility_frame(args)
    warnings = list(meta["warnings"])
    known_base, known_info = match_known_events(df, Path(args.known_event_file), warnings)

    comparison_rows = []
    pattern_rows = []
    p1p2_rows = []
    transition_frames = []
    known_frames = []
    strategy_results: dict[str, pd.DataFrame] = {}
    for strategy in STRATEGIES:
        result = apply_strategy(df, strategy, meta["risk_bucket_thresholds"])
        strategy_results[strategy["strategy"]] = result
        known_rows, known_metrics = known_strategy_rows(df, result, strategy["strategy"], known_base, known_info)
        known_frames.append(known_rows)
        comparison_rows.append(strategy_metrics(df, result, strategy, known_metrics))
        pattern_rows.append(pattern_delta(df, result, strategy["strategy"], "pattern_A_flag", "pattern_A_single_collector_short_unseen_path"))
        pattern_rows.append(pattern_delta(df, result, strategy["strategy"], "pattern_B_flag", "pattern_B_abnormal_length_single_collector_unseen_path"))
        p1p2_rows.append(p1_p2_impact(df, result, strategy["strategy"]))
        transition_frames.append(transition_matrix(df, result, strategy["strategy"]))

    comparison = pd.DataFrame(comparison_rows)
    pattern_delta_df = pd.DataFrame(pattern_rows)
    pattern_a_delta = pattern_delta_df[pattern_delta_df["pattern_name"].str.startswith("pattern_A")].copy()
    pattern_b_protection = pattern_delta_df[pattern_delta_df["pattern_name"].str.startswith("pattern_B")].copy()
    p1p2_impact = pd.DataFrame(p1p2_rows)
    transition = pd.concat(transition_frames, ignore_index=True)
    known_check = pd.concat(known_frames, ignore_index=True) if known_frames else pd.DataFrame()
    recommendation = choose_recommended_strategy(comparison)

    recommended_strategy = recommendation["recommended_strategy"]
    recommended_result = strategy_results[recommended_strategy]
    sample_cols = [
        "event_id",
        "run_id",
        "prefix",
        "origin_as",
        "as_path_clean",
        "risk_score",
        "risk_bucket",
        "path_plausibility_score",
        "plausibility_bucket",
        "pattern_A_flag",
        "pattern_B_flag",
    ]
    top = df.loc[recommended_result["adjusted_down"] | recommended_result["gate_evidence_flag"], [c for c in sample_cols if c in df.columns]].head(2000)
    if not top.empty:
        top = top.copy()
        top["recommended_strategy"] = recommended_strategy
        top["adjusted_risk_score"] = recommended_result.loc[top.index, "adjusted_risk_score"]
        top["adjusted_risk_bucket"] = recommended_result.loc[top.index, "adjusted_risk_bucket"]
        top["gate_evidence_flag"] = recommended_result.loc[top.index, "gate_evidence_flag"]
        top.to_csv(output_dir / "s3c1b_recommended_strategy_samples.csv", index=False)

    summary = {
        "run_id": args.run_id,
        "input_rows": int(meta["source_rows"]),
        "loaded_rows": int(meta["loaded_rows"]),
        "full_run": bool(args.full_run),
        "risk_bucket_thresholds": meta["risk_bucket_thresholds"],
        "strategy_count": int(len(STRATEGIES)),
        "recommended_strategy": recommended_strategy,
        "recommendation_reason": recommendation["reason"],
        "known_event_info": {k: v for k, v in known_info.items() if k not in {"known_mask", "event_masks"}},
        "join_info": meta["join_info"],
        "warnings": warnings,
        "status": "completed_with_warnings" if warnings else "completed",
    }

    comparison.to_csv(output_dir / "s3c1b_strategy_comparison.csv", index=False)
    pattern_a_delta.to_csv(output_dir / "s3c1b_pattern_A_delta_by_strategy.csv", index=False)
    pattern_b_protection.to_csv(output_dir / "s3c1b_pattern_B_protection.csv", index=False)
    p1p2_impact.to_csv(output_dir / "s3c1b_p1_p2_impact_by_strategy.csv", index=False)
    transition.to_csv(output_dir / "s3c1b_bucket_transition_matrix.csv", index=False)
    known_check.to_csv(output_dir / "s3c1b_known_event_regression_check.csv", index=False)
    (output_dir / "s3c1b_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=json_default), encoding="utf-8")
    (output_dir / "s3c1b_recommended_strategy.json").write_text(
        json.dumps(recommendation, ensure_ascii=False, indent=2, default=json_default),
        encoding="utf-8",
    )
    write_report(output_dir / "s3c1b_report.md", summary, comparison, recommendation)
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="S3-C1b offline penalty calibration over S3-C1 plausibility features.")
    ap.add_argument("--run-id", default=RUN_ID_DEFAULT, help="Run id under data/runs/<run_id>.")
    ap.add_argument("--output-dir", default=OUTPUT_DIR_DEFAULT, help="Output directory for S3-C1b artifacts.")
    ap.add_argument("--scores", default=None)
    ap.add_argument("--candidates", default=None)
    ap.add_argument("--events", default=None)
    ap.add_argument("--gating", default=None)
    ap.add_argument("--final", default=None)
    ap.add_argument("--membership", default=None)
    ap.add_argument("--tickets", default=None)
    ap.add_argument("--baseline-prefix-origin", default=None)
    ap.add_argument("--known-event-file", default="data/known_events/known_event_candidates_v05.json")
    ap.add_argument("--sample-rows", type=int, default=200_000)
    ap.add_argument("--full-run", action="store_true")
    ap.add_argument("--temporal-window-sec", type=int, default=600)
    args = ap.parse_args()

    if args.sample_rows is not None and args.sample_rows <= 0:
        raise SystemExit("--sample-rows must be > 0")
    if args.temporal_window_sec <= 0:
        raise SystemExit("--temporal-window-sec must be > 0")

    summary = run(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=json_default))


if __name__ == "__main__":
    main()
