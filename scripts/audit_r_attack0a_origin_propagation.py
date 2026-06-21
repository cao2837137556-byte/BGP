import argparse
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd


ATTACK_ROLE = "attacker_announce"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit raw-to-event-to-candidate propagation for R-ATTACK-0A."
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--raw-truth", required=True)
    parser.add_argument("--events", required=True)
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--rpki-sidecar", default="")
    parser.add_argument("--asrel-sidecar", default="")
    parser.add_argument("--community-sidecar", default="")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def parse_path(value: Any) -> str:
    values = [int(token) for token in re.findall(r"\d+", str(value))]
    result = []
    for value in values:
        if not result or result[-1] != value:
            result.append(value)
    return " ".join(str(value) for value in result)


def list_json(values: pd.Series) -> str:
    return json.dumps(sorted({str(value) for value in values if pd.notna(value)}))


def load_optional(path_value: str, columns: list[str]) -> pd.DataFrame | None:
    if not path_value:
        return None
    path = Path(path_value)
    if not path.exists():
        raise FileNotFoundError(path)
    available = pd.read_parquet(path).columns
    selected = [column for column in columns if column in available]
    return pd.read_parquet(path, columns=selected)


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    if output_dir.exists() and any(output_dir.iterdir()) and not args.overwrite:
        raise FileExistsError(f"output directory is not empty; pass --overwrite: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    truth = pd.read_parquet(args.raw_truth)
    events = pd.read_parquet(
        args.events,
        columns=[
            "event_id",
            "prefix",
            "origin_as",
            "as_path_clean",
            "first_seen",
            "last_seen",
            "record_count",
            "collector_set",
            "collector_count",
            "source_file",
        ],
    )
    candidates = pd.read_parquet(
        args.candidates,
        columns=["event_id", "candidate_flag", "candidate_reasons", "matched_rule_count"],
    )
    truth["as_path_clean"] = truth["as_path"].map(parse_path)
    events["origin_as"] = pd.to_numeric(events["origin_as"], errors="coerce")
    truth["origin_as"] = pd.to_numeric(truth["origin_as"], errors="coerce")

    event_groups = {
        key: group
        for key, group in events.groupby(
            ["prefix", "origin_as", "as_path_clean"], dropna=False, sort=False
        )
    }
    membership_rows = []
    raw_outcomes = []
    for row in truth.itertuples(index=False):
        key = (str(row.prefix), float(row.origin_as), str(row.as_path_clean))
        matches = event_groups.get(key, pd.DataFrame())
        if not matches.empty:
            matches = matches[
                (matches["first_seen"] <= float(row.ts))
                & (matches["last_seen"] >= float(row.ts))
            ].copy()
        event_ids = sorted(matches["event_id"].astype(str).unique()) if not matches.empty else []
        raw_outcomes.append(
            {
                **row._asdict(),
                "raw_parser_admitted": bool(event_ids),
                "event_id_set": json.dumps(event_ids),
                "event_match_count": len(event_ids),
                "drop_stage": "none" if event_ids else "event_builder",
                "drop_reason_code": "" if event_ids else "no_exact_event_membership_match",
            }
        )
        for event_id in event_ids:
            membership_rows.append(
                {
                    "event_id": event_id,
                    "raw_record_id": row.raw_record_id,
                    "scenario_id": row.scenario_id,
                    "phase_id": row.phase_id,
                    "attack_role": row.attack_role,
                    "is_attack_member": bool(row.is_attack_member),
                    "primary_family": row.primary_family,
                    "attack_subtype": row.attack_subtype,
                    "adversarial_variant": row.adversarial_variant,
                }
            )

    raw_outcomes_df = pd.DataFrame(raw_outcomes)
    membership = pd.DataFrame(membership_rows)
    if membership.empty:
        event_labels = pd.DataFrame()
    else:
        grouped = membership.groupby("event_id", sort=False)
        event_labels = grouped.agg(
            injected_member_count=("raw_record_id", "nunique"),
            attack_member_count=("is_attack_member", "sum"),
            scenario_id_set=("scenario_id", list_json),
            phase_id_set=("phase_id", list_json),
            family_set=("primary_family", list_json),
            subtype_set=("attack_subtype", list_json),
            variant_set=("adversarial_variant", list_json),
        ).reset_index()
        event_labels["attack_member_share_of_injected"] = (
            event_labels["attack_member_count"] / event_labels["injected_member_count"]
        )
        event_labels["event_membership_state"] = event_labels.apply(
            lambda row: (
                "attack_only"
                if row["attack_member_count"] == row["injected_member_count"]
                else ("mixed" if row["attack_member_count"] > 0 else "background_only")
            ),
            axis=1,
        )
        event_labels = event_labels.merge(
            events[
                [
                    "event_id",
                    "prefix",
                    "origin_as",
                    "as_path_clean",
                    "first_seen",
                    "last_seen",
                    "record_count",
                    "collector_set",
                    "collector_count",
                ]
            ],
            on="event_id",
            how="left",
        )

    candidate_labels = event_labels.merge(candidates, on="event_id", how="left")
    candidate_labels["candidate_flag"] = candidate_labels["candidate_flag"].fillna(False)
    candidate_labels["candidate_contains_attack"] = candidate_labels["attack_member_count"] > 0
    candidate_labels["attack_retained_at_candidate"] = (
        candidate_labels["candidate_contains_attack"] & candidate_labels["candidate_flag"]
    )

    rpki = load_optional(
        args.rpki_sidecar,
        ["event_id", "rpki_status", "rpki_evidence_state", "rpki_snapshot_date"],
    )
    asrel = load_optional(
        args.asrel_sidecar,
        [
            "event_id",
            "path_relation_diagnostic_2024",
            "path_relation_evidence_state_2024",
            "asrel_snapshot_date",
            "rel_unknown_rate_2024",
            "rel_seq_2024",
        ],
    )
    community = load_optional(
        args.community_sidecar,
        [
            "event_id",
            "community_evidence_state",
            "raw_match_status",
            "has_no_export",
            "has_no_advertise",
            "has_nopeer",
        ],
    )
    evidence_audit = candidate_labels.copy()
    evidence_audit["scenario_id"] = evidence_audit["scenario_id_set"].map(
        lambda value: (json.loads(value)[0] if len(json.loads(value)) == 1 else "mixed")
    )
    for sidecar in [rpki, asrel, community]:
        if sidecar is not None:
            evidence_audit = evidence_audit.merge(sidecar, on="event_id", how="left")

    attack_truth = truth[truth["attack_role"].eq(ATTACK_ROLE)].copy()
    attack_raw_admitted = raw_outcomes_df[raw_outcomes_df["attack_role"].eq(ATTACK_ROLE)]
    attack_events = candidate_labels[candidate_labels["candidate_contains_attack"]].copy()
    scenario_rows = []
    for scenario_id, scenario_truth in attack_truth.groupby("scenario_id", sort=False):
        scenario_events = attack_events[
            attack_events["scenario_id_set"].astype(str).str.contains(scenario_id, regex=False)
        ]
        scenario_raw = attack_raw_admitted[attack_raw_admitted["scenario_id"].eq(scenario_id)]
        scenario_rows.append(
            {
                "scenario_id": scenario_id,
                "attack_subtype": scenario_truth["attack_subtype"].iloc[0],
                "injected_attack_rows": int(len(scenario_truth)),
                "raw_parser_admitted_rows": int(scenario_raw["raw_parser_admitted"].sum()),
                "attack_event_count": int(len(scenario_events)),
                "candidate_attack_event_count": int(scenario_events["candidate_flag"].sum()),
                "candidate_attack_retention_rate": (
                    float(scenario_events["candidate_flag"].mean())
                    if len(scenario_events)
                    else 0.0
                ),
                "collectors_injected": list_json(scenario_truth["collector"]),
                "collectors_observed": list_json(scenario_events["collector_set"]),
            }
        )
    scenario_audit = pd.DataFrame(scenario_rows)

    attack_event_count = int(len(attack_events))
    candidate_attack_count = int(attack_events["candidate_flag"].sum())
    parser_admission_rate = (
        float(attack_raw_admitted["raw_parser_admitted"].mean())
        if len(attack_raw_admitted)
        else 0.0
    )
    candidate_retention_rate = (
        float(candidate_attack_count / attack_event_count) if attack_event_count else 0.0
    )
    evidence_join_rates = {}
    for name, sidecar in [("rpki", rpki), ("asrel", asrel), ("community", community)]:
        if sidecar is not None and attack_event_count:
            evidence_join_rates[name] = float(
                attack_events["event_id"].isin(set(sidecar["event_id"].astype(str))).mean()
            )
        else:
            evidence_join_rates[name] = None

    guardrail_violations = []
    if parser_admission_rate != 1.0:
        guardrail_violations.append("attack_raw_parser_admission_below_1")
    if candidate_retention_rate != 1.0:
        guardrail_violations.append("candidate_attack_retention_below_1")
    for name, rate in evidence_join_rates.items():
        if rate is not None and rate != 1.0:
            guardrail_violations.append(f"{name}_attack_event_join_below_1")

    evidence_response_rows = []
    attack_evidence = evidence_audit[evidence_audit["attack_member_count"] > 0].copy()
    for scenario_id, group in attack_evidence.groupby("scenario_id", sort=False):
        subtype = str(
            truth.loc[truth["scenario_id"].eq(scenario_id), "attack_subtype"].iloc[0]
        )
        rpki_status_set = sorted(set(group.get("rpki_status", pd.Series(dtype=str)).dropna().astype(str)))
        asrel_diagnostic_set = sorted(
            set(
                group.get("path_relation_diagnostic_2024", pd.Series(dtype=str))
                .dropna()
                .astype(str)
            )
        )
        community_state_set = sorted(
            set(
                group.get("community_evidence_state", pd.Series(dtype=str))
                .dropna()
                .astype(str)
            )
        )
        no_export_count = int(
            group.get("has_no_export", pd.Series([False] * len(group))).fillna(False).sum()
        )
        expected_rpki = (
            ["invalid_asn"]
            if subtype == "exact_prefix_origin_hijack"
            else (["valid"] if subtype == "forged_origin_hijack" else [])
        )
        rpki_expectation_met = rpki_status_set == expected_rpki
        if not rpki_expectation_met:
            guardrail_violations.append(f"{scenario_id}_rpki_mechanism_response_unexpected")
        evidence_response_rows.append(
            {
                "scenario_id": scenario_id,
                "attack_subtype": subtype,
                "attack_event_count": int(len(group)),
                "rpki_status_set": json.dumps(rpki_status_set),
                "expected_rpki_status_set": json.dumps(expected_rpki),
                "rpki_mechanism_expectation_met": rpki_expectation_met,
                "asrel_diagnostic_set": json.dumps(asrel_diagnostic_set),
                "community_evidence_state_set": json.dumps(community_state_set),
                "no_export_event_count": no_export_count,
                "interpretation": (
                    "Evidence response audit only; no evidence field is attack or benign truth."
                ),
            }
        )
    evidence_response = pd.DataFrame(evidence_response_rows)

    summary = {
        "phase": "R-ATTACK-0A",
        "run_id": args.run_id,
        "injected_raw_rows": int(len(truth)),
        "injected_attack_rows": int(len(attack_truth)),
        "attack_raw_parser_admission_rate": parser_admission_rate,
        "derived_event_count_with_injected_members": int(len(event_labels)),
        "attack_event_count": attack_event_count,
        "candidate_attack_event_count": candidate_attack_count,
        "candidate_attack_retention_rate": candidate_retention_rate,
        "evidence_attack_event_join_rates": evidence_join_rates,
        "scenario_evidence_response": evidence_response_rows,
        "foreground_evaluated": False,
        "foreground_reason": (
            "Legacy R-NOISE-1 uses forbidden workflow-label guards; clean foreground "
            "retention is deferred to R-NOISE-CLEAN-1."
        ),
        "guardrail_violations": guardrail_violations,
        "smoke_pass": not guardrail_violations,
        "truth_boundary": (
            "Controlled injection metadata is truth. RPKI, AS-rel, communities, "
            "candidate flags, and future foreground outputs are evidence or policy outcomes."
        ),
        "recommended_next_step": (
            "R-ATTACK-QA-0 if smoke passes; otherwise repair the first failing propagation layer."
        ),
    }

    raw_outcomes_df.to_parquet(output_dir / "raw_record_layer_outcomes.parquet", index=False)
    raw_outcomes_df.to_csv(output_dir / "raw_record_layer_outcomes.csv", index=False)
    membership.to_csv(output_dir / "raw_event_membership.csv", index=False)
    event_labels.to_parquet(output_dir / "event_derived_labels.parquet", index=False)
    candidate_labels.to_parquet(output_dir / "candidate_derived_labels.parquet", index=False)
    evidence_audit.to_parquet(output_dir / "attack_event_evidence_audit.parquet", index=False)
    evidence_audit.to_csv(output_dir / "attack_event_evidence_audit.csv", index=False)
    evidence_response.to_csv(output_dir / "scenario_evidence_response_audit.csv", index=False)
    scenario_audit.to_csv(output_dir / "scenario_propagation_audit.csv", index=False)
    (output_dir / "r_attack0a_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
