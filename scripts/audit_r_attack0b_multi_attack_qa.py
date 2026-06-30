#!/usr/bin/env python3
"""QA gate for R-ATTACK-0B multi-attack controlled smoke."""

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


def list_json(values: pd.Series) -> str:
    return json.dumps(sorted({str(value) for value in values.dropna()}))


def bool_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(False, index=frame.index)
    value = frame[column]
    if value.dtype == bool:
        return value.fillna(False)
    return value.fillna("").astype(str).str.lower().isin({"true", "1", "yes"})


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

    scenario_lookup = {row["scenario_id"]: row for row in config["scenarios"]}
    active = mapped[bool_series(mapped, "active_change_member")].copy()
    scenario_rows = []
    active_event_ids = set(active["event_id"].dropna().astype(str))
    active_evidence = evidence[evidence["event_id"].astype(str).isin(active_event_ids)].copy()
    for scenario_id, group in active.groupby("scenario_id", sort=False):
        spec = scenario_lookup[scenario_id]
        event_ids = set(group["event_id"].dropna().astype(str))
        event_rows = group.dropna(subset=["event_id"]).drop_duplicates("event_id")
        event_evidence = active_evidence[active_evidence["event_id"].astype(str).isin(event_ids)]
        observed_collectors = set()
        for value in event_rows["collector_set"].dropna().astype(str):
            observed_collectors.update(token for token in value.split("|") if token)
        rpki_statuses = sorted(set(event_evidence["rpki_status"].dropna().astype(str)))
        asrel_diags = sorted(
            set(event_evidence["path_relation_diagnostic_2024"].dropna().astype(str))
        )
        expected_asrel = spec.get("expected_asrel_active_one_of", [])
        scenario_rows.append(
            {
                "scenario_id": scenario_id,
                "scenario_class": spec["scenario_class"],
                "primary_family": spec["primary_family"],
                "attack_subtype": spec["attack_subtype"],
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
                "expected_collectors": json.dumps(sorted(config["expected_collectors"])),
                "observed_collectors": json.dumps(sorted(observed_collectors)),
                "visibility_contract_met": observed_collectors
                == set(config["expected_collectors"]),
                "expected_rpki_active": spec.get("expected_rpki_active", ""),
                "observed_rpki_statuses": json.dumps(rpki_statuses),
                "rpki_expectation_met": rpki_statuses == [spec.get("expected_rpki_active", "")],
                "expected_asrel_active_one_of": json.dumps(expected_asrel),
                "observed_asrel_diagnostics": json.dumps(asrel_diags),
                "asrel_expectation_met": (
                    True
                    if not expected_asrel
                    else any(value in set(expected_asrel) for value in asrel_diags)
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
    attack_raw = raw[bool_series(raw, "is_attack_member")]
    hard_negative_raw = raw[bool_series(raw, "is_hard_negative_member")]
    attack_scenarios = scenario_df[scenario_df["scenario_class"].eq("attack")]
    hard_negative_scenarios = scenario_df[scenario_df["scenario_class"].eq("hard_negative")]

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
        "All controlled hard-negative records must form exact event membership.",
    )

    attack_event_rows = active[bool_series(active, "is_attack_member")].drop_duplicates("event_id")
    candidate_attack_retention = (
        float(attack_event_rows["candidate_flag"].fillna(False).mean())
        if len(attack_event_rows)
        else 0.0
    )
    add_check(
        checks,
        "candidate_attack_retention_diagnostic",
        "pass",
        "diagnostic",
        candidate_attack_retention,
        "reported only",
        "Candidate is no longer the mainline compression layer; this is not a hard gate.",
    )

    hypothetical_asns = sorted(
        {
            int(value)
            for value in truth["hypothetical_role_as"].dropna().astype(float).astype(int)
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
        "Reserved documentation ASNs must not define scenarios.",
    )

    baseline = pd.read_parquet(args.baseline_events, columns=["origin_as", "as_path_clean"])
    observed_roles = {}
    for asn in hypothetical_asns:
        pattern = rf"(^| ){asn}( |$)"
        observed_roles[str(asn)] = bool(
            baseline["origin_as"].eq(asn).any()
            or baseline["as_path_clean"].astype(str).str.contains(pattern, regex=True).any()
        )
    add_check(
        checks,
        "counterfactual_roles_observed_in_background",
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
        "No attack edge may be unknown solely because of construction.",
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
    add_check(
        checks,
        "required_multi_attack_subtypes_present",
        "pass" if not missing_subtypes else "fail",
        "critical",
        {"observed": attack_subtypes, "missing": missing_subtypes},
        config.get("required_attack_subtypes", []),
        "R-ATTACK-0B must include origin, forged-origin, route-leak-like, and path-manipulation-like scenarios.",
    )
    hard_negative_types = sorted(set(hard_negative_scenarios["attack_subtype"]))
    add_check(
        checks,
        "hard_negative_coverage",
        "pass" if len(hard_negative_types) >= 4 else "fail",
        "critical",
        hard_negative_types,
        "at least four plausible lookalike types",
        "Hard negatives are plausible lookalikes, not confirmed benign truth.",
    )

    route_leak_rows = scenario_df[scenario_df["attack_subtype"].eq("route_leak_like_valley")]
    route_leak_ok = (
        not route_leak_rows.empty
        and route_leak_rows["observed_asrel_diagnostics"].astype(str).str.contains(
            "possible_valley_transition", regex=False
        ).all()
    )
    add_check(
        checks,
        "route_leak_like_requires_valley_diagnostic",
        "pass" if route_leak_ok else "fail",
        "critical",
        route_leak_rows[["scenario_id", "observed_asrel_diagnostics"]].to_dict("records"),
        "possible_valley_transition",
        "Route-leak-like scenarios require AS-rel valley diagnostic evidence; diagnostic is not route-leak truth.",
    )
    path_rows = scenario_df[scenario_df["attack_subtype"].eq("path_manipulation_known_transit")]
    path_ok = (
        not path_rows.empty
        and path_rows["observed_asrel_diagnostics"].astype(str).str.contains(
            "fully_unknown_relation_sequence", regex=False
        ).sum()
        == 0
    )
    add_check(
        checks,
        "path_manipulation_not_unknown_edge_shortcut",
        "pass" if path_ok else "fail",
        "critical",
        path_rows[["scenario_id", "observed_asrel_diagnostics"]].to_dict("records"),
        "not fully_unknown_relation_sequence",
        "Path manipulation must not be identifiable only by synthetic unknown AS-rel edges.",
    )

    visibility_ok = bool(scenario_df["visibility_contract_met"].all())
    add_check(
        checks,
        "scenario_level_visibility",
        "pass" if visibility_ok else "fail",
        "critical",
        scenario_df[["scenario_id", "expected_collectors", "observed_collectors"]].to_dict("records"),
        "all scenario collector sets match",
        "Event-level collector_count is not used as scenario visibility truth.",
    )
    rpki_ok = bool(scenario_df["rpki_expectation_met"].all())
    add_check(
        checks,
        "scenario_rpki_response",
        "pass" if rpki_ok else "fail",
        "critical",
        scenario_df[["scenario_id", "expected_rpki_active", "observed_rpki_statuses"]].to_dict("records"),
        "all expected RPKI responses match",
        "RPKI remains evidence, not scenario truth.",
    )
    asrel_ok = bool(scenario_df["asrel_expectation_met"].all())
    add_check(
        checks,
        "scenario_asrel_response",
        "pass" if asrel_ok else "fail",
        "critical",
        scenario_df[["scenario_id", "expected_asrel_active_one_of", "observed_asrel_diagnostics"]].to_dict("records"),
        "all expected AS-rel diagnostics observed",
        "AS-rel is diagnostic evidence, not route-leak truth.",
    )

    active_no_export = int(active_evidence["has_no_export"].fillna(False).sum())
    add_check(
        checks,
        "no_noexport_or_stealth_introduced",
        "pass" if active_no_export == 0 else "fail",
        "critical",
        active_no_export,
        0,
        "R-ATTACK-0B does not introduce NO_EXPORT/stealth scenarios.",
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

    foreground_checked = bool(foreground_summary)
    foreground_attack_retention = foreground_summary.get("attack_retention")
    foreground_suppressed_attack = foreground_summary.get("suppressed_attack_count")
    if foreground_checked:
        foreground_ok = foreground_attack_retention == 1.0 and foreground_suppressed_attack == 0
        add_check(
            checks,
            "foreground_v1_attack_retention",
            "pass" if foreground_ok else "fail",
            "critical",
            {
                "attack_retention": foreground_attack_retention,
                "suppressed_attack_count": foreground_suppressed_attack,
            },
            {"attack_retention": 1.0, "suppressed_attack_count": 0},
            "Foreground v1 must not suppress controlled attack events.",
        )

    checks_df = pd.DataFrame(checks)
    blockers = checks_df[
        checks_df["status"].eq("fail") & checks_df["severity"].eq("critical")
    ]
    qa_pass = blockers.empty
    hard_negative_candidate_rate = (
        float(hard_negative_scenarios["candidate_event_count"].sum())
        / float(hard_negative_scenarios["active_event_count"].sum())
        if int(hard_negative_scenarios["active_event_count"].sum()) > 0
        else 0.0
    )
    summary = {
        "phase": "R-ATTACK-0B",
        "qa_pass": bool(qa_pass),
        "check_count": int(len(checks_df)),
        "pass_count": int((checks_df["status"] == "pass").sum()),
        "fail_count": int(len(blockers)),
        "failed_check_ids": blockers["check_id"].tolist(),
        "attack_raw_admission_rate": attack_admission,
        "candidate_attack_retention_rate_diagnostic_only": candidate_attack_retention,
        "hard_negative_raw_admission_rate": hard_negative_admission,
        "hard_negative_candidate_event_rate": hard_negative_candidate_rate,
        "attack_subtype_counts": attack_subtypes,
        "scenario_visibility_contract_rate": float(
            scenario_df["visibility_contract_met"].mean()
        ),
        "scenario_rpki_expectation_rate": float(scenario_df["rpki_expectation_met"].mean()),
        "scenario_asrel_expectation_rate": float(scenario_df["asrel_expectation_met"].mean()),
        "foreground_checked": foreground_checked,
        "foreground_attack_retention": foreground_attack_retention,
        "foreground_suppressed_attack_count": foreground_suppressed_attack,
        "full_window_replay_ready": bool(qa_pass),
        "training_ready": False,
        "truth_boundary": (
            "Controlled attack metadata is attack truth. Hard negatives are "
            "provenance-backed plausible lookalikes, not confirmed benign truth."
        ),
        "recommended_next_step": (
            "R-FOREGROUND-1 retest and then R-ATTACK-0B full-window qualification"
            if qa_pass and not foreground_checked
            else (
                "R-ATTACK-0B result can be used for foreground retest analysis"
                if qa_pass
                else "repair failed R-ATTACK-0B QA checks before expansion"
            )
        ),
    }
    checks_df.to_csv(output_dir / "qa_checks.csv", index=False)
    scenario_df.to_csv(output_dir / "scenario_qa.csv", index=False)
    hard_negative_scenarios.to_csv(output_dir / "hard_negative_candidate_audit.csv", index=False)
    (output_dir / "r_attack0b_qa_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
