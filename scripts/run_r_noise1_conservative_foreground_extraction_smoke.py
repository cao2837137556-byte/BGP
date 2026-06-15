"""Run R-NOISE-1 conservative foreground extraction smoke.

R-NOISE-1 turns the R-NOISE-0 policy_A counterfactual into auditable views:
foreground/protected, suppressible operational background, and gray retained.
It does not delete source rows, train learning, perform incident aggregation, or
create attack/benign truth labels.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from audit_obvious_noise_separability import (
    MISSING,
    POISONING_TOKENS,
    attach_event_fields,
    attach_legacy_final_reference,
    attach_rpki_status,
    bool_series,
    contains_any,
    derive_masks,
    family_json,
    load_candidates,
    lower_text,
    normalize_text,
    parquet_info,
    reason_json,
    resolve_input,
    run_root,
    safe_rate,
)


OUTPUT_FILES = [
    "r_noise_1_summary.json",
    "candidate_noise_policy_assignment.parquet",
    "foreground_candidates.parquet",
    "suppressed_background_candidates.parquet",
    "gray_zone_retained_candidates.parquet",
    "r_noise_1_safety_audit.csv",
    "r_noise_1_family_guardrail_audit.csv",
    "r_noise_1_legacy_reference_audit.csv",
    "r_noise_1_poisoning_evasion_proxy_audit.csv",
    "r_noise_1_assignment_sample.csv",
    "r_noise_1_policy_report.md",
]

FAMILY_MASKS = [
    ("suspicious_forged_origin", "forged_origin_family"),
    ("suspicious_route_leak", "route_leak_family"),
    ("suspicious_path_manipulation", "path_manipulation_family"),
    ("suspicious_stealth_visibility", "stealth_visibility_family"),
    ("poisoning_or_evasion_suspected", "poisoning_evasion_family"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create R-NOISE-1 conservative foreground extraction smoke outputs."
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--candidates", default=None)
    parser.add_argument("--events", default=None)
    parser.add_argument("--final", default=None)
    parser.add_argument("--rpki", default=None)
    parser.add_argument("--noise0-summary", default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--sample-size", type=int, default=10000)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def resolve_paths(args: argparse.Namespace) -> dict[str, Path | None]:
    root = run_root(args.run_id)
    return {
        "candidates": resolve_input(args.candidates, root / "candidates" / "candidate_events.parquet", required=True),
        "events": resolve_input(args.events, root / "events" / "event_units.parquet"),
        "final": resolve_input(args.final, root / "final" / "final_alerts.parquet"),
        "rpki": resolve_input(args.rpki, Path("data") / "evidence" / "rpki" / "vrp_2024-04-16.parquet"),
        "noise0_summary": resolve_input(
            args.noise0_summary,
            Path("outputs") / "r_noise_0" / args.run_id / "r_noise_0_summary.json",
        ),
    }


def prepare_output_dir(output_dir: Path, overwrite: bool) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    existing = [output_dir / name for name in OUTPUT_FILES if (output_dir / name).exists()]
    if existing and not overwrite:
        raise FileExistsError(
            "output files already exist; pass --overwrite to replace: "
            + ", ".join(str(path) for path in existing)
        )


def read_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def assign_policy(df: pd.DataFrame, masks: dict[str, pd.Series]) -> dict[str, pd.Series]:
    legacy_label = normalize_text(df["legacy_final_alert_label"])
    legacy_high = legacy_label.eq("high_priority_alert")
    legacy_needs = legacy_label.eq("needs_review")
    policy_a_raw = masks["policy_A_very_conservative"]
    hard_guard = masks["must_keep"] | legacy_high | legacy_needs | masks["poisoning_evasion_like"]
    suppressible = policy_a_raw & ~hard_guard
    protected = masks["must_keep"] | (policy_a_raw & hard_guard)
    gray = ~(protected | suppressible)
    guardrail_violation = policy_a_raw & hard_guard
    return {
        "policy_A_raw_suppressible": policy_a_raw,
        "hard_guard": hard_guard,
        "foreground_protected": protected,
        "suppressible_background": suppressible,
        "gray_retained": gray,
        "guardrail_violation_if_suppressed": guardrail_violation,
        "legacy_high_reference": legacy_high,
        "legacy_needs_reference": legacy_needs,
    }


def add_assignment_columns(df: pd.DataFrame, masks: dict[str, pd.Series], assignment: dict[str, pd.Series]) -> None:
    df["noise_policy_id"] = "policy_A_very_conservative"
    df["foreground_assignment"] = "gray_retained"
    df.loc[assignment["suppressible_background"], "foreground_assignment"] = "suppressible_background"
    df.loc[assignment["foreground_protected"], "foreground_assignment"] = "foreground_protected"
    df["is_must_keep"] = masks["must_keep"].astype(bool)
    df["is_policy_A_raw_suppressible"] = assignment["policy_A_raw_suppressible"].astype(bool)
    df["is_foreground_protected"] = assignment["foreground_protected"].astype(bool)
    df["is_suppressible_background"] = assignment["suppressible_background"].astype(bool)
    df["is_gray_retained"] = assignment["gray_retained"].astype(bool)
    df["guardrail_violation_if_suppressed"] = assignment["guardrail_violation_if_suppressed"].astype(bool)
    for output_name, mask_name in FAMILY_MASKS:
        df[f"is_{output_name}"] = masks[mask_name].astype(bool)
    df["has_poisoning_evasion_proxy"] = masks["poisoning_evasion_like"].astype(bool)
    df["truth_boundary_note"] = (
        "clean-window smoke only; foreground is not confirmed attack; "
        "suppressible_background is not confirmed benign"
    )


def output_columns(df: pd.DataFrame) -> list[str]:
    preferred = [
        "event_id",
        "run_id",
        "prefix",
        "origin_as",
        "as_path_clean",
        "duration_sec",
        "collector_set",
        "collector_count",
        "visibility_count",
        "candidate_flag",
        "candidate_reasons",
        "matched_rule_count",
        "path_seen_before",
        "prefix_unique_origins",
        "po_collector_support",
        "rel_unknown_cnt",
        "rpki_status",
        "legacy_final_alert_label",
        "noise_policy_id",
        "foreground_assignment",
        "is_must_keep",
        "is_policy_A_raw_suppressible",
        "is_foreground_protected",
        "is_suppressible_background",
        "is_gray_retained",
        "guardrail_violation_if_suppressed",
        "is_suspicious_forged_origin",
        "is_suspicious_route_leak",
        "is_suspicious_path_manipulation",
        "is_suspicious_stealth_visibility",
        "is_poisoning_or_evasion_suspected",
        "has_poisoning_evasion_proxy",
        "truth_boundary_note",
    ]
    return [column for column in preferred if column in df.columns]


def write_assignment_outputs(
    df: pd.DataFrame,
    assignment: dict[str, pd.Series],
    output_dir: Path,
    sample_size: int,
    masks: dict[str, pd.Series],
) -> dict[str, int]:
    columns = output_columns(df)
    assignment_df = df.loc[:, columns]
    assignment_df.to_parquet(output_dir / "candidate_noise_policy_assignment.parquet", index=False)
    foreground = assignment["foreground_protected"] | assignment["gray_retained"]
    assignment_df.loc[foreground].to_parquet(output_dir / "foreground_candidates.parquet", index=False)
    assignment_df.loc[assignment["suppressible_background"]].to_parquet(
        output_dir / "suppressed_background_candidates.parquet",
        index=False,
    )
    assignment_df.loc[assignment["gray_retained"]].to_parquet(
        output_dir / "gray_zone_retained_candidates.parquet",
        index=False,
    )
    sample = assignment_df.head(sample_size).copy()
    sample["must_keep_family_set"] = family_json(sample, masks)
    sample["protection_reason_set"] = reason_json(
        sample,
        masks,
        [
            "origin_novelty",
            "rpki_invalid",
            "path_novelty",
            "path_length_anomaly",
            "route_leak_like",
            "stealth_visibility_family",
            "poisoning_evasion_like",
        ],
    )
    sample.to_csv(output_dir / "r_noise_1_assignment_sample.csv", index=False)
    return {
        "assignment_rows": int(len(assignment_df)),
        "foreground_rows": int(foreground.sum()),
        "suppressed_background_rows": int(assignment["suppressible_background"].sum()),
        "gray_zone_rows": int(assignment["gray_retained"].sum()),
    }


def write_safety_audit(
    df: pd.DataFrame,
    masks: dict[str, pd.Series],
    assignment: dict[str, pd.Series],
    output_dir: Path,
) -> pd.DataFrame:
    total = len(df)
    suppressible = assignment["suppressible_background"]
    policy_raw = assignment["policy_A_raw_suppressible"]
    legacy_high = assignment["legacy_high_reference"]
    legacy_needs = assignment["legacy_needs_reference"]
    rows = [
        {
            "check": "attack_false_negative_evaluation",
            "count": 0,
            "rate": 0.0,
            "pass": True,
            "notes": "not evaluated in clean-window smoke; no confirmed attack labels are available",
        },
        {
            "check": "must_keep_guardrail_violation",
            "count": int((suppressible & masks["must_keep"]).sum()),
            "rate": safe_rate(int((suppressible & masks["must_keep"]).sum()), total),
            "pass": int((suppressible & masks["must_keep"]).sum()) == 0,
            "notes": "suppressed rows must not include multi-attack must-keep signals",
        },
        {
            "check": "policy_A_raw_guarded_rows",
            "count": int(assignment["guardrail_violation_if_suppressed"].sum()),
            "rate": safe_rate(int(assignment["guardrail_violation_if_suppressed"].sum()), total),
            "pass": True,
            "notes": "rows policy_A would touch but hard guards keep; this is not a failure unless final suppression includes them",
        },
        {
            "check": "legacy_high_reference_suppressed",
            "count": int((suppressible & legacy_high).sum()),
            "rate": safe_rate(int((suppressible & legacy_high).sum()), total),
            "pass": int((suppressible & legacy_high).sum()) == 0,
            "notes": "legacy high is a workflow reference, not truth",
        },
        {
            "check": "legacy_needs_reference_suppressed",
            "count": int((suppressible & legacy_needs).sum()),
            "rate": safe_rate(int((suppressible & legacy_needs).sum()), total),
            "pass": int((suppressible & legacy_needs).sum()) == 0,
            "notes": "legacy needs is a workflow reference, not truth",
        },
        {
            "check": "poisoning_evasion_proxy_suppressed",
            "count": int((suppressible & masks["poisoning_evasion_like"]).sum()),
            "rate": safe_rate(int((suppressible & masks["poisoning_evasion_like"]).sum()), total),
            "pass": int((suppressible & masks["poisoning_evasion_like"]).sum()) == 0,
            "notes": "proxy retention only; not confirmed poisoning/evasion detection",
        },
        {
            "check": "policy_A_raw_suppressible_count",
            "count": int(policy_raw.sum()),
            "rate": safe_rate(int(policy_raw.sum()), total),
            "pass": True,
            "notes": "raw counterfactual policy_A count from R-NOISE-0-compatible logic",
        },
        {
            "check": "final_suppressible_background_count",
            "count": int(suppressible.sum()),
            "rate": safe_rate(int(suppressible.sum()), total),
            "pass": True,
            "notes": "operational background candidate view only; not benign truth",
        },
    ]
    audit = pd.DataFrame(rows)
    audit.to_csv(output_dir / "r_noise_1_safety_audit.csv", index=False)
    return audit


def write_family_guardrail_audit(
    df: pd.DataFrame,
    masks: dict[str, pd.Series],
    assignment: dict[str, pd.Series],
    output_dir: Path,
) -> pd.DataFrame:
    total = len(df)
    rows = []
    for family, mask_name in FAMILY_MASKS:
        mask = masks[mask_name]
        rows.append(
            {
                "operational_family": family,
                "hit_count": int(mask.sum()),
                "hit_rate": safe_rate(int(mask.sum()), total),
                "assigned_foreground_protected": int((mask & assignment["foreground_protected"]).sum()),
                "assigned_suppressible_background": int((mask & assignment["suppressible_background"]).sum()),
                "assigned_gray_retained": int((mask & assignment["gray_retained"]).sum()),
                "guardrail_violation_count": int((mask & assignment["suppressible_background"]).sum()),
                "allowed_claim": f"{family} weak-signal retained for judgment",
                "forbidden_claim": "confirmed attack or clean-window false-negative evaluation",
            }
        )
    audit = pd.DataFrame(rows)
    audit.to_csv(output_dir / "r_noise_1_family_guardrail_audit.csv", index=False)
    return audit


def write_legacy_audit(df: pd.DataFrame, assignment: dict[str, pd.Series], output_dir: Path) -> pd.DataFrame:
    total = len(df)
    label = normalize_text(df["legacy_final_alert_label"])
    rows = []
    for legacy_label in ["high_priority_alert", "needs_review", "low_priority_or_background", MISSING]:
        label_mask = label.eq(legacy_label)
        rows.append(
            {
                "legacy_reference_label": legacy_label,
                "row_count": int(label_mask.sum()),
                "row_rate": safe_rate(int(label_mask.sum()), total),
                "assigned_foreground_protected": int((label_mask & assignment["foreground_protected"]).sum()),
                "assigned_suppressible_background": int((label_mask & assignment["suppressible_background"]).sum()),
                "assigned_gray_retained": int((label_mask & assignment["gray_retained"]).sum()),
                "notes": "legacy labels are workflow references, not truth",
            }
        )
    audit = pd.DataFrame(rows)
    audit.to_csv(output_dir / "r_noise_1_legacy_reference_audit.csv", index=False)
    return audit


def write_poisoning_proxy_audit(
    df: pd.DataFrame,
    masks: dict[str, pd.Series],
    assignment: dict[str, pd.Series],
    output_dir: Path,
) -> pd.DataFrame:
    total = len(df)
    explicit = contains_any(lower_text(df["candidate_reasons"]), POISONING_TOKENS)
    signal_rows = [
        ("explicit_poisoning_evasion_token", explicit, "unavailable" if int(explicit.sum()) == 0 else "available"),
        ("crafted_low_visibility_path_novelty_proxy", masks["poisoning_evasion_like"] & ~explicit, "available_proxy"),
        ("any_poisoning_evasion_relevant_proxy", masks["poisoning_evasion_like"], "available_proxy"),
    ]
    rows = []
    for signal_name, signal_mask, availability in signal_rows:
        rows.append(
            {
                "signal": signal_name,
                "availability": availability,
                "hit_count": int(signal_mask.sum()),
                "hit_rate": safe_rate(int(signal_mask.sum()), total),
                "assigned_foreground_protected": int((signal_mask & assignment["foreground_protected"]).sum()),
                "assigned_suppressible_background": int((signal_mask & assignment["suppressible_background"]).sum()),
                "assigned_gray_retained": int((signal_mask & assignment["gray_retained"]).sum()),
                "forbidden_claim": "confirmed poisoning/evasion detection or clean-window false-negative proof",
            }
        )
    audit = pd.DataFrame(rows)
    audit.to_csv(output_dir / "r_noise_1_poisoning_evasion_proxy_audit.csv", index=False)
    return audit


def summarize(
    args: argparse.Namespace,
    paths: dict[str, Path | None],
    df: pd.DataFrame,
    masks: dict[str, pd.Series],
    assignment: dict[str, pd.Series],
    output_counts: dict[str, int],
    event_info: dict[str, Any],
    final_info: dict[str, Any],
    rpki_info: dict[str, Any],
    noise0_summary: dict[str, Any],
    safety_audit: pd.DataFrame,
) -> dict[str, Any]:
    total = len(df)
    foreground = output_counts["foreground_rows"]
    suppressible = output_counts["suppressed_background_rows"]
    gray = output_counts["gray_zone_rows"]
    guardrail_failed = bool((~safety_audit["pass"]).any())
    explicit_poisoning = contains_any(lower_text(df["candidate_reasons"]), POISONING_TOKENS)
    return {
        "phase": "R-NOISE-1",
        "status": "completed" if not guardrail_failed else "completed_with_guardrail_violation",
        "run_id": args.run_id,
        "policy_id": "policy_A_very_conservative",
        "candidate_entry_path": str(paths["candidates"]),
        "candidate_entry_rows": total,
        "input_inventory": {
            "candidates": parquet_info(paths["candidates"]),
            "events": parquet_info(paths["events"]),
            "final": parquet_info(paths["final"]),
            "rpki": parquet_info(paths["rpki"]),
            "noise0_summary_present": bool(noise0_summary),
        },
        "assignment_counts": {
            "foreground_protected": int(assignment["foreground_protected"].sum()),
            "suppressible_background": suppressible,
            "gray_retained": gray,
            "foreground_view_total": foreground,
        },
        "assignment_rates": {
            "foreground_protected": safe_rate(int(assignment["foreground_protected"].sum()), total),
            "suppressible_background": safe_rate(suppressible, total),
            "gray_retained": safe_rate(gray, total),
            "foreground_view_total": safe_rate(foreground, total),
        },
        "estimated_compression_ratio_if_suppressible_removed_from_foreground": round(
            float(total) / float(foreground), 6
        )
        if foreground
        else 0.0,
        "r_noise_0_policy_A_reference": {
            "expected_suppressible_count": noise0_summary.get("policy_A_suppressible_count"),
            "expected_suppressible_rate": noise0_summary.get("policy_A_suppressible_rate"),
            "expected_compression_ratio": noise0_summary.get("stop_loss_assessment", {}).get(
                "best_safe_policy_compression_ratio"
            ),
        },
        "guardrail_results": {
            row["check"]: {
                "count": int(row["count"]),
                "rate": float(row["rate"]),
                "pass": bool(row["pass"]),
                "notes": row["notes"],
            }
            for row in safety_audit.to_dict("records")
        },
        "multi_attack_guardrail_suppressed_counts": {
            family: int((masks[mask_name] & assignment["suppressible_background"]).sum())
            for family, mask_name in FAMILY_MASKS
        },
        "poisoning_evasion_proxy_status": {
            "explicit_token_count": int(explicit_poisoning.sum()),
            "explicit_token_availability": "unavailable" if int(explicit_poisoning.sum()) == 0 else "available",
            "proxy_count": int(masks["poisoning_evasion_like"].sum()),
            "proxy_suppressed_count": int(
                (masks["poisoning_evasion_like"] & assignment["suppressible_background"]).sum()
            ),
            "interpretation": (
                "available proxies retained; this is not confirmed poisoning/evasion detection"
                if int(masks["poisoning_evasion_like"].sum())
                else "proxy unavailable; no poisoning/evasion recall claim is possible"
            ),
        },
        "context_join_info": {
            "event_info": event_info,
            "final_info": final_info,
            "rpki_info": rpki_info,
        },
        "truth_safety_statement": {
            "clean_window_smoke_only": True,
            "attack_false_negative_evaluated": False,
            "foreground_is_confirmed_attack": False,
            "suppressible_background_is_confirmed_benign": False,
            "legacy_labels_are_truth": False,
            "trained_learning": False,
            "performed_incident_aggregation": False,
            "modified_old_pipeline": False,
            "deleted_source_rows": False,
        },
        "recommended_next_step": (
            "R-LEARN-0 multi-attack judgment layer design and R-POISON-0 benchmark design can proceed as designs, "
            "but no production suppression claim should be made until benchmark-backed recall is available."
            if not guardrail_failed
            else "Stop before R-LEARN-0 implementation; repair policy_A guards and rerun R-NOISE-1."
        ),
        "output_files": OUTPUT_FILES,
    }


def df_to_markdown(df: pd.DataFrame) -> str:
    if df.empty:
        return "_empty_"
    columns = list(df.columns)
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join(["---"] * len(columns)) + " |",
    ]
    for row in df.to_dict("records"):
        values = [str(row.get(column, "")).replace("|", "/") for column in columns]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def write_report(
    output_dir: Path,
    summary: dict[str, Any],
    safety_audit: pd.DataFrame,
    family_audit: pd.DataFrame,
    poisoning_audit: pd.DataFrame,
) -> None:
    lines = [
        "# R-NOISE-1 Conservative Foreground Extraction Smoke",
        "",
        "This report is generated by `scripts/run_r_noise1_conservative_foreground_extraction_smoke.py`.",
        "",
        "## Scope",
        "",
        "R-NOISE-1 creates auditable foreground/suppressible/gray views from the R-NOISE-0 "
        "`policy_A_very_conservative` rule. It is a clean-window smoke, not a detector evaluation.",
        "",
        "Forbidden claims:",
        "",
        "- foreground is not confirmed attack;",
        "- suppressible_background is not confirmed benign;",
        "- guardrail_violation_count is not an attack false-negative count;",
        "- poisoning/evasion proxy retention is not poisoning/evasion recall.",
        "",
        "## Assignment Summary",
        "",
        f"- candidate_entry_rows: `{summary['candidate_entry_rows']}`",
        f"- foreground_protected: `{summary['assignment_counts']['foreground_protected']}`",
        f"- gray_retained: `{summary['assignment_counts']['gray_retained']}`",
        f"- suppressible_background: `{summary['assignment_counts']['suppressible_background']}`",
        f"- foreground_view_total: `{summary['assignment_counts']['foreground_view_total']}`",
        f"- estimated compression if suppressible rows are removed from foreground view: "
        f"`{summary['estimated_compression_ratio_if_suppressible_removed_from_foreground']}`",
        "",
        "## Safety Audit",
        "",
        df_to_markdown(safety_audit),
        "",
        "## Multi-Attack Guardrail Audit",
        "",
        df_to_markdown(family_audit),
        "",
        "## Poisoning / Evasion Proxy Audit",
        "",
        df_to_markdown(poisoning_audit),
        "",
        "## Interpretation",
        "",
        "R-NOISE-1 can support a conservative foreground view if all guardrail checks pass. "
        "It cannot prove recall on real attacks because this 6h window has no confirmed attack labels. "
        "The next attack-miss evaluation must come from known incidents and controlled multi-attack / "
        "poisoning-evasion benchmark design.",
        "",
    ]
    (output_dir / "r_noise_1_policy_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    paths = resolve_paths(args)
    output_dir = Path(args.output_dir) if args.output_dir else Path("outputs") / "r_noise_1" / args.run_id
    prepare_output_dir(output_dir, args.overwrite)

    df = load_candidates(paths["candidates"])
    event_info = attach_event_fields(df, paths["events"])
    final_info = attach_legacy_final_reference(df, paths["final"])
    rpki_info = attach_rpki_status(df, paths["rpki"])
    masks = derive_masks(df)
    assignment = assign_policy(df, masks)
    add_assignment_columns(df, masks, assignment)

    output_counts = write_assignment_outputs(df, assignment, output_dir, args.sample_size, masks)
    safety_audit = write_safety_audit(df, masks, assignment, output_dir)
    family_audit = write_family_guardrail_audit(df, masks, assignment, output_dir)
    legacy_audit = write_legacy_audit(df, assignment, output_dir)
    poisoning_audit = write_poisoning_proxy_audit(df, masks, assignment, output_dir)
    noise0_summary = read_json(paths["noise0_summary"])
    summary = summarize(
        args,
        paths,
        df,
        masks,
        assignment,
        output_counts,
        event_info,
        final_info,
        rpki_info,
        noise0_summary,
        safety_audit,
    )
    (output_dir / "r_noise_1_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    write_report(output_dir, summary, safety_audit, family_audit, poisoning_audit)

    print(
        json.dumps(
            {
                "phase": summary["phase"],
                "status": summary["status"],
                "run_id": summary["run_id"],
                "candidate_entry_rows": summary["candidate_entry_rows"],
                "assignment_counts": summary["assignment_counts"],
                "compression_ratio": summary[
                    "estimated_compression_ratio_if_suppressible_removed_from_foreground"
                ],
                "guardrail_failed": bool((~safety_audit["pass"]).any()),
                "output_dir": str(output_dir),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
