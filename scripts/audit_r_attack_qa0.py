import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


DOCUMENTATION_ASN_RANGES = (
    (64496, 64511),
    (65536, 65551),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Qualify R-ATTACK-0A scenario realism and benchmark readiness."
    )
    parser.add_argument("--config", required=True)
    parser.add_argument("--materialization-summary", required=True)
    parser.add_argument("--raw-truth", required=True)
    parser.add_argument("--raw-outcomes", required=True)
    parser.add_argument("--raw-event-membership", required=True)
    parser.add_argument("--event-labels", required=True)
    parser.add_argument("--candidate-labels", required=True)
    parser.add_argument("--evidence-audit", required=True)
    parser.add_argument("--rpki-summary", required=True)
    parser.add_argument("--asrel-summary", required=True)
    parser.add_argument("--community-summary", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def read_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def is_documentation_asn(asn: int) -> bool:
    return any(start <= asn <= end for start, end in DOCUMENTATION_ASN_RANGES)


def add_check(
    rows: list[dict[str, Any]],
    check_id: str,
    category: str,
    status: str,
    severity: str,
    observed: Any,
    expected: Any,
    consequence: str,
) -> None:
    rows.append(
        {
            "check_id": check_id,
            "category": category,
            "status": status,
            "severity": severity,
            "observed": json.dumps(observed, ensure_ascii=False, default=str)
            if not isinstance(observed, str)
            else observed,
            "expected": json.dumps(expected, ensure_ascii=False, default=str)
            if not isinstance(expected, str)
            else expected,
            "consequence": consequence,
        }
    )


def parse_json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    try:
        parsed = json.loads(str(value))
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    except json.JSONDecodeError:
        pass
    return [str(value)]


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    if output_dir.exists() and any(output_dir.iterdir()) and not args.overwrite:
        raise FileExistsError(f"output directory is not empty; pass --overwrite: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    config = read_json(args.config)
    materialization = read_json(args.materialization_summary)
    truth = pd.read_parquet(args.raw_truth)
    raw_outcomes = pd.read_parquet(args.raw_outcomes)
    event_labels = pd.read_parquet(args.event_labels)
    candidate_labels = pd.read_parquet(args.candidate_labels)
    evidence = pd.read_parquet(args.evidence_audit)
    rpki_summary = read_json(args.rpki_summary)
    asrel_summary = read_json(args.asrel_summary)
    community_summary = read_json(args.community_summary)

    checks: list[dict[str, Any]] = []
    shortcuts: list[dict[str, Any]] = []
    scenario_rows: list[dict[str, Any]] = []

    add_check(
        checks,
        "source_immutable",
        "provenance",
        "pass" if materialization.get("input_immutable") else "fail",
        "critical",
        materialization.get("input_immutable"),
        True,
        "The reference background must remain immutable.",
    )
    add_check(
        checks,
        "truth_columns_isolated",
        "provenance",
        "pass" if not materialization.get("truth_columns_added_to_raw") else "fail",
        "critical",
        materialization.get("truth_columns_added_to_raw"),
        False,
        "Truth must remain in a sidecar and must not leak into production-like raw input.",
    )
    unique_raw_ids = int(truth["raw_record_id"].nunique())
    add_check(
        checks,
        "raw_record_id_unique",
        "provenance",
        "pass" if unique_raw_ids == len(truth) else "fail",
        "critical",
        unique_raw_ids,
        int(len(truth)),
        "Duplicate truth IDs make layer-localized loss accounting ambiguous.",
    )
    admission_rate = float(raw_outcomes["raw_parser_admitted"].mean())
    add_check(
        checks,
        "raw_event_admission",
        "propagation",
        "pass" if admission_rate == 1.0 else "fail",
        "critical",
        admission_rate,
        1.0,
        "All controlled smoke records must reach an exact event membership.",
    )
    expected_event_ids = set()
    for value in raw_outcomes["event_id_set"]:
        expected_event_ids.update(parse_json_list(value))
    labeled_event_ids = set(event_labels["event_id"].astype(str))
    add_check(
        checks,
        "event_label_coverage",
        "membership",
        "pass" if expected_event_ids == labeled_event_ids else "fail",
        "critical",
        {
            "expected_event_count": len(expected_event_ids),
            "labeled_event_count": len(labeled_event_ids),
            "missing": sorted(expected_event_ids - labeled_event_ids),
            "unexpected": sorted(labeled_event_ids - expected_event_ids),
        },
        "exact event-id coverage",
        "Every event reached by an injected record must receive a derived label record.",
    )

    attack_events = candidate_labels[candidate_labels["attack_member_count"] > 0].copy()
    attack_events["attack_member_share_total"] = (
        attack_events["attack_member_count"] / attack_events["record_count"]
    )
    total_membership_complete = bool(
        (attack_events["attack_member_count"] <= attack_events["record_count"]).all()
        and attack_events["record_count"].notna().all()
    )
    add_check(
        checks,
        "total_membership_reconstructable",
        "membership",
        "pass" if total_membership_complete else "fail",
        "critical",
        attack_events[
            ["event_id", "attack_member_count", "record_count", "attack_member_share_total"]
        ].to_dict("records"),
        "attack_member_count <= total event record_count",
        "Protocol v1 requires attack share against total event members, not injected members only.",
    )
    pure_attack_rate = (
        float((attack_events["attack_member_share_total"] == 1.0).mean())
        if len(attack_events)
        else 0.0
    )
    add_check(
        checks,
        "attack_event_purity",
        "membership",
        "pass" if pure_attack_rate == 1.0 else "warn",
        "medium",
        pure_attack_rate,
        1.0,
        "Mixed containers are allowed but must not be mislabeled as attack-only.",
    )

    required_phases = {"stable_baseline", "attack_launch", "recovery"}
    phase_order_ok = True
    for scenario in config["scenarios"]:
        phase_schedule = scenario["phase_schedule"]
        phases_present = set(phase_schedule)
        timestamps = {
            phase: [
                pd.Timestamp(value).timestamp() for value in phase_schedule[phase]["timestamps"]
            ]
            for phase in phase_schedule
        }
        ordered = (
            max(timestamps["stable_baseline"]) < min(timestamps["attack_launch"])
            and max(timestamps["attack_launch"]) < min(timestamps["recovery"])
        )
        phase_order_ok = phase_order_ok and required_phases.issubset(phases_present) and ordered
    add_check(
        checks,
        "phase_contract",
        "scenario_contract",
        "pass" if phase_order_ok else "fail",
        "critical",
        phase_order_ok,
        True,
        "Stable, attack, and recovery phases must exist and be time ordered.",
    )

    documentation_asns = [
        int(scenario["attacker_as"])
        for scenario in config["scenarios"]
        if is_documentation_asn(int(scenario["attacker_as"]))
    ]
    shortcuts.append(
        {
            "shortcut_id": "documentation_attacker_asn",
            "present": bool(documentation_asns),
            "risk_level": "high",
            "observed": json.dumps(documentation_asns),
            "why_it_matters": (
                "Reserved documentation ASNs are safe for plumbing smoke but create "
                "out-of-distribution and AS-rel-unknown shortcuts."
            ),
            "required_repair": (
                "Use topology-consistent synthetic roles mapped to observed ASNs or a "
                "simulation-backed propagation contract before benchmark evaluation."
            ),
        }
    )
    add_check(
        checks,
        "attacker_asn_realism",
        "scenario_realism",
        "block" if documentation_asns else "pass",
        "high",
        documentation_asns,
        [],
        "Documentation ASNs block benchmark, foreground, and learning claims.",
    )

    membership = pd.read_csv(args.raw_event_membership)
    truth_membership = membership.merge(
        truth[["raw_record_id", "is_attack_member"]], on="raw_record_id", suffixes=("", "_truth")
    )
    attack_col = (
        "is_attack_member_truth"
        if "is_attack_member_truth" in truth_membership.columns
        else "is_attack_member"
    )
    community_states = evidence[
        ["event_id", "community_evidence_state"]
    ].drop_duplicates()
    truth_membership = truth_membership.merge(community_states, on="event_id", how="left")
    attack_community_states = sorted(
        truth_membership.loc[
            truth_membership[attack_col].astype(bool), "community_evidence_state"
        ]
        .dropna()
        .astype(str)
        .unique()
    )
    control_community_states = sorted(
        truth_membership.loc[
            ~truth_membership[attack_col].astype(bool), "community_evidence_state"
        ]
        .dropna()
        .astype(str)
        .unique()
    )
    community_perfectly_separable = bool(
        attack_community_states
        and control_community_states
        and set(attack_community_states).isdisjoint(control_community_states)
    )
    shortcuts.append(
        {
            "shortcut_id": "phase_correlated_empty_communities",
            "present": community_perfectly_separable,
            "risk_level": "critical",
            "observed": json.dumps(
                {
                    "attack": attack_community_states,
                    "control": control_community_states,
                }
            ),
            "why_it_matters": (
                "Attack records were forced to empty communities while controls copied "
                "legitimate communities, making phase membership trivially learnable."
            ),
            "required_repair": (
                "Preserve matched legitimate community distributions unless community "
                "manipulation is the explicit experimental variable."
            ),
        }
    )
    add_check(
        checks,
        "community_phase_leakage",
        "label_leakage",
        "block" if community_perfectly_separable else "pass",
        "critical",
        {
            "attack": attack_community_states,
            "control": control_community_states,
        },
        "overlapping or explicitly controlled distributions",
        "Perfect attack/control community separation blocks foreground and learning evaluation.",
    )

    scenario_collector_coverage_ok = True
    event_single_collector_rate = (
        float((attack_events["collector_count"] == 1).mean()) if len(attack_events) else 0.0
    )
    for scenario in config["scenarios"]:
        scenario_id = scenario["scenario_id"]
        injected_collectors = set(
            truth.loc[
                truth["scenario_id"].eq(scenario_id) & truth["is_attack_member"], "collector"
            ].astype(str)
        )
        scenario_events = attack_events[
            attack_events["scenario_id_set"].map(
                lambda value: scenario_id in parse_json_list(value)
            )
        ]
        observed_collectors = set()
        for value in scenario_events["collector_set"].dropna():
            observed_collectors.update(str(value).split("|"))
        expected_collectors = set(config["expected_collectors"])
        visibility_ok = injected_collectors == expected_collectors == observed_collectors
        scenario_collector_coverage_ok = scenario_collector_coverage_ok and visibility_ok
        scenario_rows.append(
            {
                "scenario_id": scenario_id,
                "attack_subtype": scenario["attack_subtype"],
                "attacker_as": int(scenario["attacker_as"]),
                "documentation_attacker_asn": is_documentation_asn(
                    int(scenario["attacker_as"])
                ),
                "expected_collectors": json.dumps(sorted(expected_collectors)),
                "observed_collectors": json.dumps(sorted(observed_collectors)),
                "scenario_visibility_contract_met": visibility_ok,
                "attack_event_count": int(len(scenario_events)),
                "candidate_retention_rate": (
                    float(scenario_events["candidate_flag"].mean())
                    if len(scenario_events)
                    else 0.0
                ),
                "attack_member_share_total_min": (
                    float(scenario_events["attack_member_share_total"].min())
                    if len(scenario_events)
                    else 0.0
                ),
            }
        )
    add_check(
        checks,
        "scenario_visibility_contract",
        "observability",
        "pass" if scenario_collector_coverage_ok else "fail",
        "critical",
        scenario_collector_coverage_ok,
        True,
        "Public-visible scenarios must be observed across the declared collector set.",
    )
    shortcuts.append(
        {
            "shortcut_id": "event_level_single_collector_artifact",
            "present": event_single_collector_rate == 1.0,
            "risk_level": "high",
            "observed": event_single_collector_rate,
            "why_it_matters": (
                "Collector-specific AS paths split a public-visible scenario into separate "
                "single-collector events. Event-level collector_count is not scenario visibility."
            ),
            "required_repair": (
                "Evaluate visibility at scenario/object-time level or explicitly preserve "
                "cross-path collector membership before using low visibility."
            ),
        }
    )
    add_check(
        checks,
        "event_visibility_semantics",
        "observability",
        "warn" if event_single_collector_rate == 1.0 else "pass",
        "high",
        event_single_collector_rate,
        "event visibility must not contradict scenario visibility",
        "Do not interpret single-collector event rows as stealth in this smoke.",
    )

    candidate_retention = (
        float(attack_events["candidate_flag"].mean()) if len(attack_events) else 0.0
    )
    structural_tokens = (
        "unseen_origin_for_prefix",
        "unseen_path_for_prefix_origin",
        "unseen_exact_path",
        "weak_path_history",
        "abnormal_path_length_for_prefix_origin",
        "cross_collector_prefix_origin_burst",
    )
    structural_retained = attack_events["candidate_reasons"].map(
        lambda value: any(token in str(value) for token in structural_tokens)
    )
    add_check(
        checks,
        "candidate_structural_retention",
        "propagation",
        "pass"
        if candidate_retention == 1.0 and bool(structural_retained.all())
        else "fail",
        "critical",
        {
            "retention_rate": candidate_retention,
            "all_have_structural_reason": bool(structural_retained.all()),
        },
        {"retention_rate": 1.0, "all_have_structural_reason": True},
        "Retention must not depend only on contextual single-collector visibility.",
    )

    evidence_attack = evidence[evidence["attack_member_count"] > 0].copy()
    exact = evidence_attack[
        evidence_attack["subtype_set"].astype(str).str.contains(
            "exact_prefix_origin_hijack", regex=False
        )
    ]
    forged = evidence_attack[
        evidence_attack["subtype_set"].astype(str).str.contains(
            "forged_origin_hijack", regex=False
        )
    ]
    rpki_mechanism_ok = (
        set(exact["rpki_status"].dropna().astype(str)) == {"invalid_asn"}
        and set(forged["rpki_status"].dropna().astype(str)) == {"valid"}
    )
    add_check(
        checks,
        "rpki_mechanism_response",
        "evidence",
        "pass" if rpki_mechanism_ok else "fail",
        "critical",
        {
            "exact": sorted(set(exact["rpki_status"].dropna().astype(str))),
            "forged": sorted(set(forged["rpki_status"].dropna().astype(str))),
        },
        {"exact": ["invalid_asn"], "forged": ["valid"]},
        "This is an evidence-response check, not attack or benign truth.",
    )
    observed_rpki_snapshot = str(rpki_summary.get("run_date", ""))
    observed_asrel_snapshot = str(asrel_summary.get("asrel_snapshot_date", ""))
    evidence_binding_ok = (
        observed_rpki_snapshot == "2024-04-16"
        and rpki_summary.get("vrp_metadata_aligned_to_run_date") is True
        and observed_asrel_snapshot == "2024-04-01"
        and int(asrel_summary.get("asrel_alignment_delta_days", -1)) == 15
        and str(community_summary.get("run_date", "")) == "2024-04-16"
        and int(community_summary.get("source_files_ok", 0))
        == int(community_summary.get("source_files_expected", -1))
        and bool(config["evidence_snapshot_binding"]["evidence_recomputed"])
    )
    add_check(
        checks,
        "evidence_snapshot_binding",
        "evidence",
        "pass" if evidence_binding_ok else "fail",
        "critical",
        {
            "rpki": observed_rpki_snapshot,
            "rpki_aligned": rpki_summary.get("vrp_metadata_aligned_to_run_date"),
            "asrel": observed_asrel_snapshot,
            "asrel_alignment_delta_days": asrel_summary.get(
                "asrel_alignment_delta_days"
            ),
            "community_run_date": community_summary.get("run_date"),
            "community_source_files_ok": community_summary.get("source_files_ok"),
            "community_source_files_expected": community_summary.get(
                "source_files_expected"
            ),
            "evidence_recomputed": config["evidence_snapshot_binding"][
                "evidence_recomputed"
            ],
        },
        {
            "rpki": "2024-04-16",
            "rpki_aligned": True,
            "asrel": "2024-04-01",
            "asrel_alignment_delta_days": 15,
            "community_run_date": "2024-04-16",
            "community_source_files_ok": "all expected files",
            "evidence_recomputed": True,
        },
        "Controlled runs must bind period-correct, versioned evidence.",
    )
    asrel_unknown_all = bool(
        evidence_attack["path_relation_diagnostic_2024"]
        .astype(str)
        .str.contains("unknown")
        .all()
    )
    add_check(
        checks,
        "asrel_synthetic_edge_response",
        "evidence",
        "warn" if asrel_unknown_all else "pass",
        "high",
        asrel_unknown_all,
        False,
        "All-unknown synthetic edges are expected for documentation ASNs but are not benchmark realism.",
    )

    scenario_count = len(config["scenarios"])
    subtype_counts = pd.Series(
        [str(scenario["attack_subtype"]) for scenario in config["scenarios"]]
    ).value_counts()
    diversity_minimum_met = bool(
        len(subtype_counts) >= 2 and int(subtype_counts.min()) >= 2
    )
    add_check(
        checks,
        "scenario_diversity",
        "benchmark_readiness",
        "block" if not diversity_minimum_met else "pass",
        "critical",
        {
            "scenario_count": scenario_count,
            "subtype_counts": subtype_counts.to_dict(),
        },
        "at least two independent templates per included subtype for the next qualified smoke",
        "One template per subtype cannot expose template-specific shortcuts.",
    )
    add_check(
        checks,
        "hard_negative_coverage",
        "benchmark_readiness",
        "block",
        "critical",
        0,
        "> 0 before foreground evaluation",
        "No low-false-positive claim is allowed without plausible non-attack lookalikes.",
    )
    add_check(
        checks,
        "full_window_execution",
        "execution_readiness",
        "block",
        "high",
        "local full rebuild exceeded about one hour and produced no complete artifact",
        "qualified reproducible full-window job",
        "Do not run full replay until scenario shortcuts are repaired and the job is packaged for HPC.",
    )

    checks_df = pd.DataFrame(checks)
    shortcut_df = pd.DataFrame(shortcuts)
    scenario_df = pd.DataFrame(scenario_rows)
    blocking_checks = checks_df[checks_df["status"].isin(["fail", "block"])]
    warning_checks = checks_df[checks_df["status"].eq("warn")]
    smoke_qualified = not bool(
        checks_df[
            checks_df["check_id"].isin(
                [
                    "source_immutable",
                    "truth_columns_isolated",
                    "raw_record_id_unique",
                    "raw_event_admission",
                    "event_label_coverage",
                    "total_membership_reconstructable",
                    "phase_contract",
                    "scenario_visibility_contract",
                    "candidate_structural_retention",
                    "rpki_mechanism_response",
                    "evidence_snapshot_binding",
                ]
            )
            & checks_df["status"].isin(["fail", "block"])
        ].shape[0]
    )
    summary = {
        "phase": "R-ATTACK-QA-0",
        "source_phase": "R-ATTACK-0A",
        "development_smoke_qualified": smoke_qualified,
        "full_window_replay_ready": False,
        "foreground_policy_evaluation_ready": False,
        "training_ready": False,
        "check_count": int(len(checks_df)),
        "pass_count": int((checks_df["status"] == "pass").sum()),
        "warning_count": int(len(warning_checks)),
        "blocking_or_fail_count": int(len(blocking_checks)),
        "blocking_check_ids": blocking_checks["check_id"].tolist(),
        "shortcut_risks": shortcut_df.loc[
            shortcut_df["present"].astype(bool), "shortcut_id"
        ].tolist(),
        "key_findings": [
            "The raw/event/candidate/evidence plumbing smoke is valid.",
            "Documentation ASNs create synthetic topology and evidence shortcuts.",
            "Empty attack communities are perfectly phase-correlated label leakage.",
            "Event-level single-collector rows do not represent scenario-level visibility.",
            "Two attack-only scenarios cannot support low-FP or generalization claims.",
        ],
        "stop_loss_triggered": True,
        "stop_loss_scope": (
            "Block full-window replay, clean foreground evaluation, and learning for scenario v1; "
            "retain R-ATTACK-0A only as a development smoke."
        ),
        "recommended_next_step": "R-ATTACK-0A-2 scenario hardening before any full-window replay",
        "required_repairs": [
            "Replace documentation-AS shortcuts with topology-consistent attacker roles.",
            "Match community distributions unless communities are the controlled variable.",
            "Separate scenario-level visibility from event-level path grouping.",
            "Add multiple victims, attackers, templates, and hard-negative lookalikes.",
            "Package the repaired full-window replay for HPC after a bounded local smoke.",
        ],
    }

    checks_df.to_csv(output_dir / "qa_checks.csv", index=False)
    shortcut_df.to_csv(output_dir / "shortcut_risk_audit.csv", index=False)
    scenario_df.to_csv(output_dir / "scenario_qa.csv", index=False)
    attack_events.to_csv(output_dir / "attack_event_membership_qa.csv", index=False)
    (output_dir / "r_attack_qa0_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
