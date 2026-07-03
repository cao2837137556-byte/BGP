#!/usr/bin/env python3
"""QA gate for R-ATTACK-1 subprefix and NO_EXPORT family expansion."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


DOCUMENTATION_ASN_RANGES = ((64496, 64511), (65536, 65551))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
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
    parser.add_argument("--foreground-summary", default="")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def is_documentation_asn(asn: int) -> bool:
    return any(start <= asn <= end for start, end in DOCUMENTATION_ASN_RANGES)


def bool_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(False, index=frame.index)
    value = frame[column]
    if value.dtype == bool:
        return value.fillna(False)
    return value.fillna("").astype(str).str.lower().isin({"true", "1", "yes"})


def add_check(rows: list[dict[str, Any]], check_id: str, status: str, severity: str, observed: Any, expected: Any, note: str) -> None:
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


def parse_json_list(value: Any) -> list[str]:
    if value is None or pd.isna(value):
        return []
    try:
        parsed = json.loads(str(value))
        if isinstance(parsed, list):
            return [str(v) for v in parsed]
    except Exception:
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
    rpki_summary = read_json(args.rpki_summary)
    asrel_summary = read_json(args.asrel_summary)
    community_summary = read_json(args.community_summary)
    foreground_summary = read_json(args.foreground_summary) if args.foreground_summary else {}

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
    active = mapped[bool_series(mapped, "active_change_member")].copy()
    active_event_ids = set(active["event_id"].dropna().astype(str))
    active_evidence = evidence[evidence["event_id"].astype(str).isin(active_event_ids)].copy()

    scenario_rows = []
    for scenario_id, group in active.groupby("scenario_id", sort=False):
        event_ids = set(group["event_id"].dropna().astype(str))
        event_rows = group.dropna(subset=["event_id"]).drop_duplicates("event_id")
        event_evidence = active_evidence[active_evidence["event_id"].astype(str).isin(event_ids)]
        observed_collectors = set()
        for value in event_rows["collector_set"].dropna().astype(str):
            observed_collectors.update(token for token in value.split("|") if token)
        expected_collectors = set()
        for value in group["expected_collectors"].dropna().astype(str):
            expected_collectors.update(parse_json_list(value))
        rpki_statuses = sorted(set(event_evidence["rpki_status"].dropna().astype(str)))
        asrel_diags = sorted(
            set(event_evidence["path_relation_diagnostic_2024"].dropna().astype(str))
        )
        no_export_count = int(event_evidence["has_no_export"].fillna(False).sum())
        expected_rpki = set()
        for value in group["expected_rpki_active_one_of"].dropna().astype(str):
            expected_rpki.update(parse_json_list(value))
        expected_asrel = set()
        for value in group["expected_asrel_active_one_of"].dropna().astype(str):
            expected_asrel.update(parse_json_list(value))
        scenario_rows.append(
            {
                "scenario_id": scenario_id,
                "scenario_class": str(group["scenario_class"].dropna().iloc[0]),
                "primary_family": str(group["primary_family"].dropna().iloc[0]),
                "attack_subtype": str(group["attack_subtype"].dropna().iloc[0]),
                "active_raw_rows": int(group["raw_record_id"].nunique()),
                "admitted_raw_rows": int(
                    group.loc[
                        group["raw_parser_admitted"].fillna(False), "raw_record_id"
                    ].nunique()
                ),
                "active_event_count": int(len(event_ids)),
                "candidate_event_count": int(event_rows["candidate_flag"].fillna(False).sum()),
                "candidate_event_rate": (
                    float(event_rows["candidate_flag"].fillna(False).mean())
                    if len(event_rows)
                    else 0.0
                ),
                "expected_collectors": json.dumps(sorted(expected_collectors)),
                "observed_collectors": json.dumps(sorted(observed_collectors)),
                "visibility_contract_met": observed_collectors == expected_collectors,
                "expected_rpki_active_one_of": json.dumps(sorted(expected_rpki)),
                "observed_rpki_statuses": json.dumps(rpki_statuses),
                "rpki_expectation_met": (not expected_rpki) or bool(set(rpki_statuses) & expected_rpki),
                "expected_asrel_active_one_of": json.dumps(sorted(expected_asrel)),
                "observed_asrel_diagnostics": json.dumps(asrel_diags),
                "asrel_expectation_met": (not expected_asrel) or bool(set(asrel_diags) & expected_asrel),
                "no_export_event_count": no_export_count,
                "expected_community_active": str(group["expected_community_active"].dropna().iloc[0])
                if group["expected_community_active"].notna().any()
                else "",
            }
        )
    scenario_df = pd.DataFrame(scenario_rows)

    checks: list[dict[str, Any]] = []
    attack_raw = raw[bool_series(raw, "is_attack_member")]
    hard_negative_raw = raw[bool_series(raw, "is_hard_negative_member")]
    attack_scenarios = scenario_df[scenario_df["scenario_class"].eq("attack")]
    hard_negative_scenarios = scenario_df[scenario_df["scenario_class"].eq("hard_negative")]

    attack_admission = float(attack_raw["raw_parser_admitted"].fillna(False).mean())
    hard_negative_admission = float(hard_negative_raw["raw_parser_admitted"].fillna(False).mean())
    add_check(checks, "attack_raw_admission", "pass" if attack_admission == 1.0 else "fail", "critical", attack_admission, 1.0, "All active attack records must map to events.")
    add_check(checks, "hard_negative_raw_admission", "pass" if hard_negative_admission == 1.0 else "fail", "critical", hard_negative_admission, 1.0, "All hard-negative active records must map to events.")

    hypothetical_asns = sorted(
        {
            int(value)
            for value in truth["hypothetical_role_as"].dropna().astype(float).astype(int)
        }
    )
    documentation = [asn for asn in hypothetical_asns if is_documentation_asn(asn)]
    add_check(checks, "no_documentation_asn_shortcut", "pass" if not documentation else "fail", "critical", documentation, [], "No reserved documentation ASN may define a scenario.")

    baseline = pd.read_parquet(args.baseline_events, columns=["origin_as", "as_path_clean"])
    observed_roles = {}
    for asn in hypothetical_asns:
        pattern = rf"(^| ){asn}( |$)"
        observed_roles[str(asn)] = bool(
            baseline["origin_as"].eq(asn).any()
            or baseline["as_path_clean"].astype(str).str.contains(pattern, regex=True).any()
        )
    add_check(checks, "counterfactual_roles_observed_in_background", "pass" if all(observed_roles.values()) else "fail", "critical", observed_roles, "all true", "Counterfactual roles must come from the observed routing universe.")

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
        "Attack inserted edges must be known in the 2024 AS-rel cache.",
    )

    attack_subtypes = {
        key: int(value)
        for key, value in attack_scenarios["attack_subtype"].value_counts().to_dict().items()
    }
    missing_subtypes = [
        subtype
        for subtype in config.get("required_attack_subtypes", [])
        if attack_subtypes.get(subtype, 0) < 1
    ]
    add_check(checks, "required_r_attack1_attack_subtypes_present", "pass" if not missing_subtypes else "fail", "critical", {"observed": attack_subtypes, "missing": missing_subtypes}, config.get("required_attack_subtypes", []), "R-ATTACK-1 must include subprefix and NO_EXPORT/stealth attack scenarios.")

    hard_negative_types = sorted(set(hard_negative_scenarios["attack_subtype"]))
    missing_hn = [
        subtype
        for subtype in config.get("required_hard_negative_subtypes", [])
        if subtype not in hard_negative_types
    ]
    add_check(checks, "required_hard_negative_subtypes_present", "pass" if not missing_hn else "fail", "critical", {"observed": hard_negative_types, "missing": missing_hn}, config.get("required_hard_negative_subtypes", []), "Hard negatives are plausible lookalikes, not benign truth.")

    visibility_ok = bool(scenario_df["visibility_contract_met"].all())
    add_check(checks, "scenario_level_visibility", "pass" if visibility_ok else "fail", "critical", scenario_df[["scenario_id", "expected_collectors", "observed_collectors"]].to_dict("records"), "collector sets match expected visibility contract", "Partial-public visibility is allowed only when explicitly declared.")

    rpki_ok = bool(scenario_df["rpki_expectation_met"].all())
    add_check(checks, "scenario_rpki_response", "pass" if rpki_ok else "fail", "critical", scenario_df[["scenario_id", "expected_rpki_active_one_of", "observed_rpki_statuses"]].to_dict("records"), "one expected status observed", "RPKI is evidence, not attack truth.")

    asrel_ok = bool(scenario_df["asrel_expectation_met"].all())
    add_check(checks, "scenario_asrel_response", "pass" if asrel_ok else "fail", "critical", scenario_df[["scenario_id", "expected_asrel_active_one_of", "observed_asrel_diagnostics"]].to_dict("records"), "one expected diagnostic observed", "AS-rel is diagnostic evidence, not route-leak truth.")

    noexport_attack = attack_scenarios[attack_scenarios["attack_subtype"].eq("stealth_no_export_visibility")]
    noexport_ok = not noexport_attack.empty and bool((noexport_attack["no_export_event_count"] > 0).all())
    add_check(checks, "stealth_noexport_attack_has_noexport_evidence", "pass" if noexport_ok else "fail", "critical", noexport_attack[["scenario_id", "no_export_event_count"]].to_dict("records"), "NO_EXPORT event evidence present", "NO_EXPORT is required evidence for this scenario but remains non-truth.")

    subprefix_attack = attack_raw[attack_raw["attack_subtype"].eq("subprefix_origin_hijack")]
    subprefix_ok = bool((subprefix_attack["prefix"].astype(str) != subprefix_attack["source_prefix"].astype(str)).all()) if len(subprefix_attack) else False
    add_check(checks, "subprefix_attack_uses_more_specific_prefix", "pass" if subprefix_ok else "fail", "critical", subprefix_attack[["scenario_id", "source_prefix", "prefix"]].drop_duplicates().to_dict("records"), "active prefix differs from observed parent source prefix", "Subprefix attack must not collapse into exact-prefix replay.")

    evidence_binding_ok = (
        rpki_summary.get("run_date") == "2024-04-16"
        and rpki_summary.get("vrp_metadata_aligned_to_run_date") is True
        and asrel_summary.get("asrel_snapshot_date") == "2024-04-01"
        and int(asrel_summary.get("asrel_alignment_delta_days", -1)) == 15
        and community_summary.get("run_date") == "2024-04-16"
        and int(community_summary.get("source_files_ok", 0))
        == int(community_summary.get("source_files_expected", -1))
    )
    add_check(checks, "evidence_snapshot_binding", "pass" if evidence_binding_ok else "fail", "critical", {"rpki": rpki_summary.get("run_date"), "asrel": asrel_summary.get("asrel_snapshot_date"), "community_files": [community_summary.get("source_files_ok"), community_summary.get("source_files_expected")]}, "aligned RPKI, 2024 AS-rel, all community source files", "All evidence must be recomputed and version-bound for the derived run.")

    foreground_checked = bool(foreground_summary)
    if foreground_checked:
        foreground_ok = (
            foreground_summary.get("attack_retention") == 1.0
            and foreground_summary.get("suppressed_attack_count") == 0
            and foreground_summary.get("truth_feature_leakage_count", 0) == 0
        )
        add_check(
            checks,
            "foreground3_attack_retention",
            "pass" if foreground_ok else "fail",
            "critical",
            {
                "attack_retention": foreground_summary.get("attack_retention"),
                "suppressed_attack_count": foreground_summary.get("suppressed_attack_count"),
                "truth_feature_leakage_count": foreground_summary.get("truth_feature_leakage_count"),
            },
            {"attack_retention": 1.0, "suppressed_attack_count": 0, "truth_feature_leakage_count": 0},
            "Frozen online_path_pressure_v1 must retain all R-ATTACK-1 attacks.",
        )

    checks_df = pd.DataFrame(checks)
    blockers = checks_df[
        checks_df["status"].eq("fail") & checks_df["severity"].eq("critical")
    ]
    qa_pass = blockers.empty
    summary = {
        "phase": "R-ATTACK-1",
        "qa_pass": bool(qa_pass),
        "check_count": int(len(checks_df)),
        "pass_count": int((checks_df["status"] == "pass").sum()),
        "fail_count": int(len(blockers)),
        "failed_check_ids": blockers["check_id"].tolist(),
        "attack_raw_admission_rate": attack_admission,
        "hard_negative_raw_admission_rate": hard_negative_admission,
        "attack_subtype_counts": attack_subtypes,
        "hard_negative_subtypes": hard_negative_types,
        "scenario_visibility_contract_rate": float(scenario_df["visibility_contract_met"].mean()),
        "scenario_rpki_expectation_rate": float(scenario_df["rpki_expectation_met"].mean()),
        "scenario_asrel_expectation_rate": float(scenario_df["asrel_expectation_met"].mean()),
        "foreground_checked": foreground_checked,
        "foreground_policy": "online_path_pressure_v1",
        "foreground_attack_retention": foreground_summary.get("attack_retention"),
        "foreground_suppressed_attack_count": foreground_summary.get("suppressed_attack_count"),
        "full_window_replay_ready": bool(qa_pass),
        "training_ready": False,
        "truth_boundary": "Controlled attack metadata is attack truth. NO_EXPORT/RPKI/AS-rel are evidence only. Hard negatives are plausible lookalikes, not confirmed benign.",
        "recommended_next_step": (
            "R-ATTACK-1 full replay can be used for foreground retention analysis"
            if qa_pass
            else "repair failed R-ATTACK-1 QA checks before poisoning, history, or learning"
        ),
    }
    checks_df.to_csv(output_dir / "qa_checks.csv", index=False)
    scenario_df.to_csv(output_dir / "scenario_qa.csv", index=False)
    hard_negative_scenarios.to_csv(output_dir / "hard_negative_candidate_audit.csv", index=False)
    (output_dir / "r_attack1_qa_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
