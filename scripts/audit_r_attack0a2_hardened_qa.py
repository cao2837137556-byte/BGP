import argparse
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd


DOCUMENTATION_ASN_RANGES = ((64496, 64511), (65536, 65551))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="QA gate for the hardened R-ATTACK-0A-2 bounded smoke."
    )
    parser.add_argument("--config", required=True)
    parser.add_argument("--baseline-events", required=True)
    parser.add_argument("--materialization-summary", required=True)
    parser.add_argument("--raw-truth", required=True)
    parser.add_argument("--raw-outcomes", required=True)
    parser.add_argument("--raw-event-membership", required=True)
    parser.add_argument("--candidates", required=True)
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
    status: str,
    severity: str,
    observed: Any,
    expected: Any,
    note: str,
) -> None:
    rows.append(
        {
            "check_id": check_id,
            "status": status,
            "severity": severity,
            "observed": json.dumps(observed, ensure_ascii=False, default=str),
            "expected": json.dumps(expected, ensure_ascii=False, default=str),
            "note": note,
        }
    )


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    if output_dir.exists() and any(output_dir.iterdir()) and not args.overwrite:
        raise FileExistsError(f"output directory is not empty; pass --overwrite: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    config = read_json(args.config)
    materialization = read_json(args.materialization_summary)
    rpki_summary = read_json(args.rpki_summary)
    asrel_summary = read_json(args.asrel_summary)
    community_summary = read_json(args.community_summary)
    truth = pd.read_parquet(args.raw_truth)
    outcomes = pd.read_parquet(args.raw_outcomes)
    membership = pd.read_csv(args.raw_event_membership)
    candidates = pd.read_parquet(
        args.candidates,
        columns=["event_id", "candidate_flag", "candidate_reasons", "collector_set"],
    )
    evidence = pd.read_parquet(args.evidence_audit)

    outcome_cols = outcomes[
        ["raw_record_id", "raw_parser_admitted", "event_id_set", "drop_stage"]
    ].drop_duplicates("raw_record_id")
    raw = truth.merge(outcome_cols, on="raw_record_id", how="left", suffixes=("", "_out"))
    member = membership[["raw_record_id", "event_id"]].drop_duplicates()
    mapped = raw.merge(member, on="raw_record_id", how="left")
    mapped = mapped.merge(candidates, on="event_id", how="left")

    scenario_lookup = {row["scenario_id"]: row for row in config["scenarios"]}
    active = mapped[mapped["active_change_member"].astype(bool)].copy()
    scenario_rows = []
    active_event_ids = set(active["event_id"].dropna().astype(str))
    active_evidence = evidence[evidence["event_id"].astype(str).isin(active_event_ids)].copy()
    for scenario_id, group in active.groupby("scenario_id", sort=False):
        spec = scenario_lookup[scenario_id]
        event_ids = set(group["event_id"].dropna().astype(str))
        event_rows = group.dropna(subset=["event_id"]).drop_duplicates("event_id")
        event_evidence = active_evidence[
            active_evidence["event_id"].astype(str).isin(event_ids)
        ]
        observed_collectors = set()
        for value in event_rows["collector_set"].dropna().astype(str):
            observed_collectors.update(token for token in value.split("|") if token)
        rpki_statuses = sorted(set(event_evidence["rpki_status"].dropna().astype(str)))
        scenario_rows.append(
            {
                "scenario_id": scenario_id,
                "scenario_class": spec["scenario_class"],
                "attack_subtype": spec["attack_subtype"],
                "active_raw_rows": int(group["raw_record_id"].nunique()),
                "admitted_raw_rows": int(
                    group.loc[group["raw_parser_admitted"].fillna(False), "raw_record_id"].nunique()
                ),
                "active_event_count": int(len(event_ids)),
                "candidate_event_count": int(event_rows["candidate_flag"].fillna(False).sum()),
                "candidate_event_rate": (
                    float(event_rows["candidate_flag"].fillna(False).mean())
                    if len(event_rows)
                    else 0.0
                ),
                "expected_collectors": json.dumps(sorted(config["expected_collectors"])),
                "observed_collectors": json.dumps(sorted(observed_collectors)),
                "visibility_contract_met": observed_collectors
                == set(config["expected_collectors"]),
                "expected_rpki_active": spec["expected_rpki_active"],
                "observed_rpki_statuses": json.dumps(rpki_statuses),
                "rpki_expectation_met": rpki_statuses == [spec["expected_rpki_active"]],
                "asrel_diagnostics": json.dumps(
                    sorted(
                        set(
                            event_evidence["path_relation_diagnostic_2024"]
                            .dropna()
                            .astype(str)
                        )
                    )
                ),
                "community_states": json.dumps(
                    sorted(
                        set(
                            event_evidence["community_evidence_state"]
                            .dropna()
                            .astype(str)
                        )
                    )
                ),
                "no_export_event_count": int(
                    event_evidence["has_no_export"].fillna(False).sum()
                ),
            }
        )
    scenario_df = pd.DataFrame(scenario_rows)

    checks: list[dict[str, Any]] = []
    attack_raw = raw[raw["is_attack_member"].astype(bool)]
    hard_negative_raw = raw[raw["is_hard_negative_member"].astype(bool)]
    attack_scenarios = scenario_df[scenario_df["scenario_class"].eq("attack")]
    hard_negative_scenarios = scenario_df[
        scenario_df["scenario_class"].eq("hard_negative")
    ]

    attack_admission = float(attack_raw["raw_parser_admitted"].fillna(False).mean())
    hard_negative_admission = float(
        hard_negative_raw["raw_parser_admitted"].fillna(False).mean()
    )
    add_check(
        checks,
        "attack_raw_admission",
        "pass" if attack_admission == 1.0 else "fail",
        "critical",
        attack_admission,
        1.0,
        "All controlled attack records must form exact event membership.",
    )
    add_check(
        checks,
        "hard_negative_raw_admission",
        "pass" if hard_negative_admission == 1.0 else "fail",
        "critical",
        hard_negative_admission,
        1.0,
        "All controlled lookalike records must form exact event membership.",
    )

    attack_retention = (
        float(
            active[
                active["is_attack_member"].astype(bool)
            ].drop_duplicates("event_id")["candidate_flag"].fillna(False).mean()
        )
        if not attack_scenarios.empty
        else 0.0
    )
    add_check(
        checks,
        "candidate_attack_retention",
        "pass" if attack_retention == 1.0 else "fail",
        "critical",
        attack_retention,
        1.0,
        "The legacy candidate comparison gate must not drop the bounded attack set.",
    )

    hypothetical_asns = sorted(
        {
            int(item["hypothetical_role_as"])
            for item in config["scenarios"]
            if item.get("hypothetical_role_as") is not None
        }
    )
    documentation = [asn for asn in hypothetical_asns if is_documentation_asn(asn)]
    add_check(
        checks,
        "no_documentation_asn_shortcut",
        "pass" if not documentation else "fail",
        "critical",
        documentation,
        [],
        "Reserved documentation ASNs must not define hardened scenarios.",
    )

    baseline = pd.read_parquet(
        args.baseline_events, columns=["origin_as", "as_path_clean"]
    )
    observed_roles = {}
    for asn in hypothetical_asns:
        pattern = rf"(^| ){asn}( |$)"
        observed_roles[str(asn)] = bool(
            baseline["origin_as"].eq(asn).any()
            or baseline["as_path_clean"].astype(str).str.contains(pattern, regex=True).any()
        )
    add_check(
        checks,
        "hypothetical_roles_observed_in_background",
        "pass" if all(observed_roles.values()) else "fail",
        "critical",
        observed_roles,
        "all true",
        "Counterfactual roles must be drawn from the observed routing universe.",
    )
    add_check(
        checks,
        "inserted_edges_known_2024",
        "pass"
        if bool(materialization.get("all_inserted_edges_known_2024"))
        and bool(truth.loc[truth["is_attack_member"], "inserted_edges_known_2024"].all())
        else "fail",
        "critical",
        materialization.get("all_inserted_edges_known_2024"),
        True,
        "No newly inserted attack edge may be unknown solely because of construction.",
    )

    attack_fp = set(
        truth.loc[truth["is_attack_member"], "community_fingerprint"].astype(str)
    )
    nonattack_fp = set(
        truth.loc[~truth["is_attack_member"], "community_fingerprint"].astype(str)
    )
    hard_negative_fp = set(
        truth.loc[truth["is_hard_negative_member"], "community_fingerprint"].astype(str)
    )
    community_overlap = len(attack_fp & nonattack_fp)
    add_check(
        checks,
        "community_phase_leakage_removed",
        "pass" if community_overlap > 0 else "fail",
        "critical",
        {
            "attack_fingerprints": len(attack_fp),
            "nonattack_fingerprints": len(nonattack_fp),
            "overlap": community_overlap,
            "attack_hard_negative_overlap": len(attack_fp & hard_negative_fp),
        },
        "non-empty attack/nonattack overlap",
        "Communities must not perfectly encode attack membership.",
    )
    active_attack_states = set(
        active_evidence.loc[
            active_evidence["scenario_id"].isin(attack_scenarios["scenario_id"]),
            "community_evidence_state",
        ]
        .dropna()
        .astype(str)
    )
    add_check(
        checks,
        "attack_communities_not_forced_empty",
        "pass" if active_attack_states != {"observed_no_community_tokens"} else "fail",
        "critical",
        sorted(active_attack_states),
        "not only observed_no_community_tokens",
        "Ordinary origin scenarios must preserve matched community observations.",
    )
    active_no_export = int(
        active_evidence["has_no_export"].fillna(False).sum()
    )
    add_check(
        checks,
        "no_noexport_evasion_introduced",
        "pass" if active_no_export == 0 else "fail",
        "critical",
        active_no_export,
        0,
        "NO_EXPORT is outside this hardened origin smoke.",
    )

    visibility_ok = bool(scenario_df["visibility_contract_met"].all())
    add_check(
        checks,
        "scenario_level_visibility",
        "pass" if visibility_ok else "fail",
        "critical",
        scenario_df[
            ["scenario_id", "expected_collectors", "observed_collectors"]
        ].to_dict("records"),
        "all scenario collector sets match",
        "Event-level collector_count is not used as scenario visibility truth.",
    )
    rpki_ok = bool(scenario_df["rpki_expectation_met"].all())
    add_check(
        checks,
        "scenario_rpki_response",
        "pass" if rpki_ok else "fail",
        "critical",
        scenario_df[
            ["scenario_id", "expected_rpki_active", "observed_rpki_statuses"]
        ].to_dict("records"),
        "all expected evidence responses match",
        "RPKI remains evidence, not scenario truth.",
    )
    attack_asrel_unknown = bool(
        active_evidence.loc[
            active_evidence["scenario_id"].isin(attack_scenarios["scenario_id"]),
            "path_relation_diagnostic_2024",
        ]
        .astype(str)
        .str.contains("unknown")
        .any()
    )
    add_check(
        checks,
        "no_synthetic_asrel_unknown_shortcut",
        "pass" if not attack_asrel_unknown else "fail",
        "critical",
        attack_asrel_unknown,
        False,
        "Hardened attack paths must not be identifiable by construction-only unknown edges.",
    )

    attack_subtype_counts = {
        key: int(value)
        for key, value in pd.Series(
            [
                item["attack_subtype"]
                for item in config["scenarios"]
                if item["scenario_class"] == "attack"
            ]
        )
        .value_counts()
        .to_dict()
        .items()
    }
    diversity_ok = (
        attack_subtype_counts.get("exact_prefix_origin_hijack", 0) >= 2
        and attack_subtype_counts.get("forged_origin_hijack", 0) >= 2
    )
    add_check(
        checks,
        "minimum_attack_template_diversity",
        "pass" if diversity_ok else "fail",
        "critical",
        attack_subtype_counts,
        {
            "exact_prefix_origin_hijack": ">=2",
            "forged_origin_hijack": ">=2",
        },
        "This is a bounded-smoke minimum, not final benchmark diversity.",
    )
    hard_negative_types = sorted(set(hard_negative_scenarios["attack_subtype"]))
    add_check(
        checks,
        "hard_negative_coverage",
        "pass" if len(hard_negative_types) >= 4 else "fail",
        "critical",
        hard_negative_types,
        "at least four distinct plausible lookalike types",
        "Hard negatives remain controlled plausible non-attack lookalikes, not benign truth.",
    )
    split_fields = [
        "template_id",
        "scenario_split_group",
        "victim_prefix_group",
        "legitimate_origin_group",
        "attacker_as_group",
    ]
    split_complete = all(
        all(str(item.get(field, "")).strip() for field in split_fields)
        for item in config["scenarios"]
    )
    split_unique = (
        len({item["template_id"] for item in config["scenarios"]})
        == len(config["scenarios"])
        and len({item["scenario_split_group"] for item in config["scenarios"]})
        == len(config["scenarios"])
    )
    add_check(
        checks,
        "split_leakage_guardrails",
        "pass" if split_complete and split_unique else "fail",
        "critical",
        {"complete": split_complete, "template_and_split_unique": split_unique},
        {"complete": True, "template_and_split_unique": True},
        "Full replay must preserve scenario/template groups for future split isolation.",
    )

    evidence_binding_ok = (
        rpki_summary.get("run_date") == "2024-04-16"
        and rpki_summary.get("vrp_metadata_aligned_to_run_date") is True
        and asrel_summary.get("asrel_snapshot_date") == "2024-04-01"
        and int(asrel_summary.get("asrel_alignment_delta_days", -1)) == 15
        and community_summary.get("run_date") == "2024-04-16"
        and int(community_summary.get("source_files_ok", 0))
        == int(community_summary.get("source_files_expected", -1))
    )
    add_check(
        checks,
        "evidence_snapshot_binding",
        "pass" if evidence_binding_ok else "fail",
        "critical",
        {
            "rpki": rpki_summary.get("run_date"),
            "asrel": asrel_summary.get("asrel_snapshot_date"),
            "community_files": [
                community_summary.get("source_files_ok"),
                community_summary.get("source_files_expected"),
            ],
        },
        "aligned RPKI, 2024-near AS-rel, all community source files",
        "All evidence must be recomputed and version-bound for the derived run.",
    )

    checks_df = pd.DataFrame(checks)
    blockers = checks_df[checks_df["status"].eq("fail")]
    qa_pass = blockers.empty
    hard_negative_candidate_rate = (
        float(hard_negative_scenarios["candidate_event_count"].sum())
        / float(hard_negative_scenarios["active_event_count"].sum())
        if int(hard_negative_scenarios["active_event_count"].sum()) > 0
        else 0.0
    )
    summary = {
        "phase": "R-ATTACK-0A-2",
        "qa_pass": bool(qa_pass),
        "check_count": int(len(checks_df)),
        "pass_count": int((checks_df["status"] == "pass").sum()),
        "fail_count": int(len(blockers)),
        "failed_check_ids": blockers["check_id"].tolist(),
        "attack_raw_admission_rate": attack_admission,
        "candidate_attack_retention_rate": attack_retention,
        "hard_negative_raw_admission_rate": hard_negative_admission,
        "hard_negative_candidate_event_rate": hard_negative_candidate_rate,
        "community_attack_nonattack_fingerprint_overlap": community_overlap,
        "active_no_export_event_count": active_no_export,
        "scenario_visibility_contract_rate": float(
            scenario_df["visibility_contract_met"].mean()
        ),
        "scenario_rpki_expectation_rate": float(
            scenario_df["rpki_expectation_met"].mean()
        ),
        "full_window_replay_ready": bool(qa_pass),
        "foreground_formal_evaluation_ready": False,
        "training_ready": False,
        "truth_boundary": (
            "Controlled attack metadata is attack truth. Hard negatives are "
            "provenance-backed plausible lookalikes, not confirmed benign truth."
        ),
        "recommended_next_step": (
            "R-ATTACK-0A-3 qualified full-window replay packaging and execution"
            if qa_pass
            else "repair failed R-ATTACK-0A-2 QA checks before further expansion"
        ),
    }
    checks_df.to_csv(output_dir / "qa_checks.csv", index=False)
    scenario_df.to_csv(output_dir / "scenario_qa.csv", index=False)
    hard_negative_scenarios.to_csv(
        output_dir / "hard_negative_candidate_audit.csv", index=False
    )
    pd.DataFrame(
        [
            {
                "attack_fingerprint_count": len(attack_fp),
                "nonattack_fingerprint_count": len(nonattack_fp),
                "hard_negative_fingerprint_count": len(hard_negative_fp),
                "attack_nonattack_overlap": community_overlap,
                "attack_hard_negative_overlap": len(attack_fp & hard_negative_fp),
                "perfectly_separable": community_overlap == 0,
            }
        ]
    ).to_csv(output_dir / "community_leakage_audit.csv", index=False)
    (output_dir / "r_attack0a2_qa_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
