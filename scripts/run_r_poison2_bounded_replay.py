"""Run R-POISON-2 bounded poisoning/evasion replay.

This is a small event-level replay over R-POISON-1 pair prototypes. It does not
modify old pipelines and does not run the full 6h raw replay. It recomputes the
foreground assignment using the frozen online_path_pressure_v1 logic over
bounded clean/adversarial rows, then reports clean-vs-adversarial retention
drop and stop-loss status.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POISON1_ROOT = "outputs/r_poison_1/s2a_baseline_v01_pilot_6h_april16"
DEFAULT_POLICY_CONFIG = "configs/r_foreground3_online_policy_v1.json"
DEFAULT_ATTACK0B_EVIDENCE = (
    r"D:\study\paper\supercompute_transfer\r_attack0b_pullback_2775002"
    r"\outputs\r_attack_0b\s2a_attack0b_multi_attack_smoke_6h_april16_v01"
    r"\audit\scenario_evidence_response_audit.csv"
)
DEFAULT_ATTACK1_EVIDENCE = (
    r"D:\study\paper\supercompute_transfer\r_attack1_pullback_20260705_125817"
    r"\outputs\r_attack_1\s2a_attack1_family_expansion_6h_april16_v01"
    r"\audit\scenario_evidence_response_audit.csv"
)


ASSIGN_PROTECTED = "protected_foreground"
ASSIGN_GRAY = "gray_retained"
ASSIGN_SUPPRESSED = "operational_background_suppressed"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--poison1-root", default=DEFAULT_POISON1_ROOT)
    parser.add_argument("--policy-config", default=DEFAULT_POLICY_CONFIG)
    parser.add_argument("--attack0b-evidence", default=DEFAULT_ATTACK0B_EVIDENCE)
    parser.add_argument("--attack1-evidence", default=DEFAULT_ATTACK1_EVIDENCE)
    parser.add_argument(
        "--output-dir",
        default="outputs/r_poison_2/s2a_baseline_v01_pilot_6h_april16",
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def resolve_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def read_json(path_like: str | Path) -> dict[str, Any] | list[dict[str, Any]]:
    with resolve_path(path_like).open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_parquet_or_note(path: Path, frame: pd.DataFrame) -> str:
    try:
        frame.to_parquet(path, index=False)
        return "written"
    except Exception as exc:  # pragma: no cover
        note = path.with_suffix(path.suffix + ".not_written.txt")
        note.write_text(
            f"Parquet output was not written: {type(exc).__name__}: {exc}\n",
            encoding="utf-8",
        )
        return f"not_written:{type(exc).__name__}"


def prepare_output_dir(path: Path, overwrite: bool) -> None:
    if path.exists() and any(path.iterdir()):
        if not overwrite:
            raise FileExistsError(f"output directory not empty; pass --overwrite: {path}")
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def parse_json_list(value: Any) -> list[str]:
    if value is None:
        return []
    try:
        parsed = json.loads(str(value))
        if isinstance(parsed, list):
            return [str(v) for v in parsed]
    except Exception:
        pass
    if str(value).strip() == "":
        return []
    return [str(value)]


def evidence_lookup(paths: list[Path]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for path in paths:
        if not path.exists():
            continue
        frame = pd.read_csv(path)
        for _, row in frame.iterrows():
            rows[str(row["scenario_id"])] = row.to_dict()
    return rows


def risk_sets(policy: dict[str, Any]) -> tuple[set[str], set[str], set[str]]:
    risk = policy.get("risk_values", {})
    return (
        set(map(str, risk.get("rpki_statuses", []))),
        set(map(str, risk.get("asrel_diagnostics", []))),
        set(map(str, risk.get("community_flags", []))),
    )


def build_replay_rows(
    pair_rows: list[dict[str, Any]],
    truth_rows: pd.DataFrame,
    evidence: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pair in pair_rows:
        base_id = str(pair["clean_base_scenario_id"])
        ev = evidence.get(base_id, {})
        attack_event_count = int(float(ev.get("attack_event_count", 1) or 1))
        rpki_status_set = parse_json_list(ev.get("rpki_status_set")) or ["missing"]
        asrel_set = parse_json_list(ev.get("asrel_diagnostic_set")) or ["missing"]
        community_state_set = parse_json_list(ev.get("community_evidence_state_set"))
        no_export_count = int(float(ev.get("no_export_event_count", 0) or 0))
        expected_clean_collectors = parse_json_list(pair.get("expected_clean_collectors"))
        clean_collector_count = max(1, len(expected_clean_collectors))
        expected_visibility = str(pair.get("expected_visibility_class", "public_visible"))

        truth_subset = truth_rows[
            truth_rows["pair_id"].astype(str).eq(str(pair["pair_id"]))
            & truth_rows["phase_id"].astype(str).eq("attack_launch")
        ].copy()
        if truth_subset.empty:
            phase_rows = [
                {"variant_role": "clean", "variant_scenario_id": pair["clean_variant_scenario_id"]},
                {
                    "variant_role": "adversarial",
                    "variant_scenario_id": pair["adversarial_variant_scenario_id"],
                },
            ]
        else:
            phase_rows = truth_subset.to_dict("records")

        for phase in phase_rows:
            variant_role = str(phase["variant_role"])
            is_adversarial = variant_role == "adversarial"
            threat_model = str(pair["threat_model"])
            variant = "clean" if not is_adversarial else str(pair["adversarial_variant"])
            prefix_origin_event_count = 1
            prefix_origin_path_event_count = 1
            path_signature_event_count = 1
            knowledge_base_drift_score = 0.0
            novelty_signal_drop = 0.0
            visibility_drop = 0.0
            collector_count = clean_collector_count
            visibility_contract_satisfied = True
            unobservable_from_public_control_plane = False
            has_no_export = no_export_count > 0

            if is_adversarial and threat_model == "detection_data_poisoning":
                prefix_origin_event_count = 4
                prefix_origin_path_event_count = 4
                path_signature_event_count = 4
                knowledge_base_drift_score = 0.75
                novelty_signal_drop = 1.0
            elif is_adversarial and threat_model == "visibility_evasion":
                collector_count = 1
                visibility_drop = 0.5 if expected_visibility == "partial_public_visible" else 0.0
                knowledge_base_drift_score = 0.25
                novelty_signal_drop = 0.0
                has_no_export = True
                visibility_contract_satisfied = expected_visibility in {
                    "partial_public_visible",
                    "public_visible",
                }

            rows.append(
                {
                    "pair_id": pair["pair_id"],
                    "clean_base_scenario_id": base_id,
                    "variant_role": variant_role,
                    "variant_scenario_id": phase["variant_scenario_id"],
                    "adversarial_variant": variant,
                    "threat_model": threat_model,
                    "family": pair["family"],
                    "base_attack_subtype": pair["base_attack_subtype"],
                    "expected_visibility_class": expected_visibility,
                    "recall_denominator_policy": pair.get("recall_denominator_policy"),
                    "attack_event_count": attack_event_count,
                    "collector_count": collector_count,
                    "rpki_status": rpki_status_set[0],
                    "path_relation_diagnostic_2024": asrel_set[0],
                    "community_evidence_state": "|".join(community_state_set),
                    "has_no_export": has_no_export,
                    "has_no_advertise": False,
                    "has_nopeer": False,
                    "prefix_origin_event_count": prefix_origin_event_count,
                    "prefix_origin_path_event_count": prefix_origin_path_event_count,
                    "path_signature_event_count": path_signature_event_count,
                    "knowledge_base_drift_score": knowledge_base_drift_score,
                    "novelty_signal_drop": novelty_signal_drop,
                    "public_collector_visibility_drop": visibility_drop,
                    "visibility_contract_satisfied": visibility_contract_satisfied,
                    "unobservable_from_public_control_plane": unobservable_from_public_control_plane,
                    "is_attack_member": True,
                    "replay_scope": "bounded_event_level",
                }
            )
    return rows


def assign_policy(rows: list[dict[str, Any]], policy: dict[str, Any]) -> list[dict[str, Any]]:
    rpki_risk, asrel_risk, community_flags = risk_sets(policy)
    params = policy.get("policy_parameters", {})
    rare_path_max = int(params.get("rare_prefix_origin_path_protect_max", 1))
    suppress_po_min = int(params.get("suppress_prefix_origin_min", 2))
    suppress_pop_min = int(params.get("suppress_prefix_origin_path_min", 2))
    out: list[dict[str, Any]] = []
    for row in rows:
        rpki_signal = str(row["rpki_status"]) in rpki_risk
        asrel_signal = str(row["path_relation_diagnostic_2024"]) in asrel_risk
        community_signal = any(
            [
                row.get("has_no_export") and "has_no_export" in community_flags,
                row.get("has_no_advertise") and "has_no_advertise" in community_flags,
                row.get("has_nopeer") and "has_nopeer" in community_flags,
            ]
        )
        external_risk_signal = bool(rpki_signal or asrel_signal or community_signal)
        low_visibility = int(row["collector_count"]) <= int(
            policy.get("feature_thresholds", {}).get("low_visibility_collector_count", 1)
        )
        rare_prefix_origin_path = int(row["prefix_origin_path_event_count"]) <= rare_path_max
        evidence_unavailable = str(row["rpki_status"]) == "missing" and str(
            row["path_relation_diagnostic_2024"]
        ) == "missing"

        protected = external_risk_signal or rare_prefix_origin_path or (
            low_visibility and external_risk_signal
        )
        suppressed = (
            not protected
            and not evidence_unavailable
            and int(row["prefix_origin_event_count"]) >= suppress_po_min
            and int(row["prefix_origin_path_event_count"]) >= suppress_pop_min
        )
        if protected:
            assignment = ASSIGN_PROTECTED
            reason = "external_or_rare_path_signal"
        elif suppressed:
            assignment = ASSIGN_SUPPRESSED
            reason = "recurrent_after_poisoning_without_external_risk"
        else:
            assignment = ASSIGN_GRAY
            reason = "insufficient_for_safe_suppression"

        new_row = dict(row)
        new_row.update(
            {
                "rpki_risk_signal": rpki_signal,
                "asrel_risk_signal": asrel_signal,
                "community_risk_signal": community_signal,
                "external_risk_signal": external_risk_signal,
                "low_visibility": low_visibility,
                "rare_prefix_origin_path": rare_prefix_origin_path,
                "online_policy_id": policy["policy_id"],
                "online_assignment": assignment,
                "online_assignment_reason": reason,
                "online_downstream_retained": assignment != ASSIGN_SUPPRESSED,
            }
        )
        out.append(new_row)
    return out


def pair_metrics(assigned: list[dict[str, Any]]) -> list[dict[str, Any]]:
    df = pd.DataFrame(assigned)
    rows: list[dict[str, Any]] = []
    for pair_id, group in df.groupby("pair_id", sort=False):
        clean = group[group["variant_role"].eq("clean")]
        adv = group[group["variant_role"].eq("adversarial")]
        clean_events = int(clean["attack_event_count"].sum())
        adv_events = int(adv["attack_event_count"].sum())
        clean_retained = int(
            clean.loc[clean["online_downstream_retained"], "attack_event_count"].sum()
        )
        adv_retained = int(
            adv.loc[adv["online_downstream_retained"], "attack_event_count"].sum()
        )
        clean_rate = clean_retained / clean_events if clean_events else None
        adv_rate = adv_retained / adv_events if adv_events else None
        rows.append(
            {
                "pair_id": pair_id,
                "threat_model": str(group["threat_model"].iloc[0]),
                "family": str(group["family"].iloc[0]),
                "clean_attack_events": clean_events,
                "adversarial_attack_events": adv_events,
                "clean_attack_retention": clean_rate,
                "poisoned_or_evasive_attack_retention": adv_rate,
                "retention_drop_under_poisoning_or_evasion": None
                if clean_rate is None or adv_rate is None
                else round(clean_rate - adv_rate, 6),
                "suppressed_attack_count": adv_events - adv_retained,
                "clean_assignment": "|".join(sorted(set(clean["online_assignment"]))),
                "adversarial_assignment": "|".join(sorted(set(adv["online_assignment"]))),
                "knowledge_base_drift_score": float(
                    adv["knowledge_base_drift_score"].mean()
                )
                if len(adv)
                else 0.0,
                "novelty_signal_drop": float(adv["novelty_signal_drop"].mean())
                if len(adv)
                else 0.0,
                "visibility_contract_satisfied": bool(
                    adv["visibility_contract_satisfied"].fillna(False).all()
                )
                if len(adv)
                else True,
                "unobservable_from_public_control_plane": bool(
                    adv["unobservable_from_public_control_plane"].fillna(False).any()
                )
                if len(adv)
                else False,
            }
        )
    return rows


def write_report(path: Path, summary: dict[str, Any], metrics: list[dict[str, Any]]) -> None:
    lines = [
        "# R-POISON-2 Bounded Replay",
        "",
        "Status: bounded event-level replay; no full 6h replay.",
        "",
        "## Summary",
        "",
        f"- pair count: `{summary['pair_count']}`",
        f"- clean attack retention mean: `{summary['clean_attack_retention_mean']}`",
        f"- adversarial attack retention mean: `{summary['adversarial_attack_retention_mean']}`",
        f"- suppressed adversarial attack events: `{summary['suppressed_adversarial_attack_events']}`",
        f"- stop_loss_triggered: `{summary['stop_loss_triggered']}`",
        "",
        "## Pair Metrics",
        "",
        "| Pair | Threat model | Clean retention | Adversarial retention | Drop | Suppressed attack events |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in metrics:
        lines.append(
            f"| `{row['pair_id']}` | `{row['threat_model']}` | "
            f"`{row['clean_attack_retention']}` | "
            f"`{row['poisoned_or_evasive_attack_retention']}` | "
            f"`{row['retention_drop_under_poisoning_or_evasion']}` | "
            f"`{row['suppressed_attack_count']}` |"
        )
    lines.extend(
        [
            "",
            "## Interpretation Boundary",
            "",
            "- This bounded replay can expose likely foreground weakness under the frozen policy.",
            "- It is not a substitute for a future bounded raw-level replay.",
            "- NO_EXPORT, RPKI, and AS-rel remain evidence or diagnostics, not truth.",
            "- Public-invisible variants are observability-boundary cases, not foreground misses.",
            "",
            "## Next Step",
            "",
            summary["recommended_next_step"],
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    output_dir = resolve_path(args.output_dir)
    prepare_output_dir(output_dir, args.overwrite)

    poison1_root = resolve_path(args.poison1_root)
    pair_rows = read_json(poison1_root / "r_poison1_pair_registry.json")
    if not isinstance(pair_rows, list):
        raise ValueError("R-POISON-1 pair registry must be a JSON list")
    truth_rows = pd.read_csv(poison1_root / "r_poison1_truth_prototype.csv")
    policy = read_json(args.policy_config)
    if not isinstance(policy, dict):
        raise ValueError("policy config must be a JSON object")
    evidence = evidence_lookup(
        [resolve_path(args.attack0b_evidence), resolve_path(args.attack1_evidence)]
    )

    replay_rows = build_replay_rows(pair_rows, truth_rows, evidence)
    assigned = assign_policy(replay_rows, policy)
    metrics = pair_metrics(assigned)

    assigned_df = pd.DataFrame(assigned)
    metrics_df = pd.DataFrame(metrics)
    write_csv(output_dir / "r_poison2_bounded_replay_events.csv", assigned)
    write_csv(output_dir / "r_poison2_pair_metrics.csv", metrics)
    event_parquet_status = write_parquet_or_note(
        output_dir / "r_poison2_bounded_replay_events.parquet", assigned_df
    )
    metrics_parquet_status = write_parquet_or_note(
        output_dir / "r_poison2_pair_metrics.parquet", metrics_df
    )

    clean_mean = float(metrics_df["clean_attack_retention"].mean()) if len(metrics_df) else None
    adv_mean = (
        float(metrics_df["poisoned_or_evasive_attack_retention"].mean())
        if len(metrics_df)
        else None
    )
    suppressed_adv = int(metrics_df["suppressed_attack_count"].sum()) if len(metrics_df) else 0
    stop_loss = suppressed_adv > 0
    summary = {
        "phase": "R-POISON-2",
        "status": "bounded_event_level_replay",
        "pair_count": len(metrics),
        "event_rows": len(assigned),
        "clean_attack_retention_mean": clean_mean,
        "adversarial_attack_retention_mean": adv_mean,
        "suppressed_adversarial_attack_events": suppressed_adv,
        "pairs_with_retention_drop": metrics_df.loc[
            metrics_df["retention_drop_under_poisoning_or_evasion"].fillna(0) > 0,
            "pair_id",
        ].tolist()
        if len(metrics_df)
        else [],
        "stop_loss_triggered": stop_loss,
        "this_phase_full_6h_replay": False,
        "this_phase_trained_learning": False,
        "this_phase_changed_foreground_policy": False,
        "event_parquet_status": event_parquet_status,
        "metrics_parquet_status": metrics_parquet_status,
        "allowed_claim": (
            "R-POISON-2 bounded event-level replay measures likely "
            "clean-vs-adversarial foreground retention under frozen policy."
        ),
        "forbidden_claims": [
            "Do not call this a full 6h replay.",
            "Do not claim historical poisoning robustness.",
            "Do not claim NO_EXPORT is attack truth.",
            "Do not count public-invisible events as foreground misses.",
        ],
        "recommended_next_step": (
            "R-FOREGROUND-4 foreground repair before learning or larger poisoning replay"
            if stop_loss
            else "R-POISON-3 bounded raw-level replay or R-HIST-0 historical replay planning"
        ),
    }
    write_json(output_dir / "r_poison2_summary.json", summary)
    write_report(output_dir / "r_poison2_report.md", summary, metrics)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
