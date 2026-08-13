#!/usr/bin/env python3
"""Run bounded, reversible N-FRONTEND-3B background routing.

The only suppressible semantic unit is a complete, unambiguous
``identical_reannouncement`` transition.  Truth sidecars are loaded only
after online routing has completed and are used solely for safety audits.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


DEFAULT_CONFIG = Path("configs/n_frontend3b_background_suppression_v01.json")
ASSIGN_FOREGROUND = "protected_semantic_foreground"
ASSIGN_BACKGROUND = "suppressible_semantic_redundancy"
ASSIGN_GRAY = "gray_contract_anomaly"
FINAL_FOREGROUND = "semantic_foreground"
FINAL_BACKGROUND = "reversible_background_summary"
FINAL_GRAY = "gray_contract_anomaly"
WITHDRAWAL_FAMILIES = {
    "bootstrap_withdrawal",
    "withdrawal",
    "repeated_withdrawal",
    "state_recovery_withdraw",
}
TRUTH_COLUMNS = {
    "pair_id",
    "scenario_id",
    "variant_role",
    "phase_id",
    "is_attack_member",
    "is_poisoning_preparation_member",
    "expected_visible",
    "expected_visibility_class",
    "family",
    "threat_model",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n-frontend2b-root")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--package-manifest")
    parser.add_argument("--output-dir")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def stable_json(value: Any) -> str:
    return json.dumps(
        normalize_json(value), ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )


def normalize_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if math.isnan(float(value)) else float(value)
    if isinstance(value, np.ndarray):
        return [normalize_json(item) for item in value.tolist()]
    if isinstance(value, (list, tuple, set)):
        values = [normalize_json(item) for item in value]
        return sorted(values, key=stable_json) if isinstance(value, set) else values
    if isinstance(value, dict):
        return {str(key): normalize_json(item) for key, item in value.items()}
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if pd.isna(value):
        return None
    return str(value) if not isinstance(value, str) else value


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(stable_json(value).encode("ascii"))


def text(value: Any) -> str | None:
    value = normalize_json(value)
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value) if not pd.isna(value) else False


def present_bool(value: Any) -> tuple[bool, bool]:
    normalized = normalize_json(value)
    return normalized is not None, bool(normalized) if normalized is not None else False


def as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, np.ndarray):
        value = value.tolist()
    if isinstance(value, (list, tuple, set)):
        return [item for item in (text(part) for part in value) if item]
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        if stripped.startswith("["):
            try:
                return as_list(json.loads(stripped))
            except json.JSONDecodeError:
                pass
        return [stripped]
    if pd.isna(value):
        return []
    return [str(value)]


def prepare_output_dir(path: Path, overwrite: bool) -> None:
    if path.exists():
        if not overwrite:
            raise FileExistsError(f"output directory exists: {path}")
        shutil.rmtree(path)
    path.mkdir(parents=True)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(normalize_json(value), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_frame(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".parquet":
        frame.to_parquet(path, index=False)
    else:
        serial = frame.copy()
        for column in serial.columns:
            if serial[column].dtype == object:
                serial[column] = serial[column].map(
                    lambda value: stable_json(value)
                    if isinstance(value, (list, tuple, set, dict, np.ndarray))
                    else value
                )
        serial.to_csv(path, index=False)


def load_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_source_anchors(config: dict[str, Any], repo_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path_key, sha_key in (
        ("frontend1_config", "frontend1_config_sha256"),
        ("frontend2b_config", "frontend2b_config_sha256"),
        ("poisoning_protocol_config", "poisoning_protocol_canonical_sha256"),
    ):
        path = repo_root / config[path_key]
        observed = sha256_file(path)
        expected = config[sha_key]
        rows.append(
            {
                "artifact": path_key,
                "file_path": str(path),
                "expected_sha256": expected,
                "observed_sha256": observed,
                "passed": observed == expected,
            }
        )
    if not all(row["passed"] for row in rows):
        raise ValueError("frozen source anchor mismatch")
    return rows


def validate_package_manifest(
    path: Path | None, self_test: bool, repo_root: Path
) -> dict[str, Any]:
    if self_test:
        return {
            "manifest_mode": "self_test",
            "git_archive_or_lf_normalized": True,
            "all_entries_passed": True,
        }
    if path is None or not path.is_file():
        raise ValueError("formal run requires --package-manifest")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "source_commit",
        "line_ending_policy",
        "git_archive_or_lf_normalized",
        "all_entries_passed",
        "entries",
    }
    if not required <= set(manifest):
        raise ValueError("package manifest is incomplete")
    if not manifest["git_archive_or_lf_normalized"] or not manifest["all_entries_passed"]:
        raise ValueError("package manifest line-ending/hash gate failed")
    observed_failures: list[str] = []
    for entry in manifest["entries"]:
        packaged_path = repo_root / entry["path"]
        if not packaged_path.is_file():
            observed_failures.append(f"missing:{entry['path']}")
            continue
        packaged_bytes = packaged_path.read_bytes()
        if sha256_bytes(packaged_bytes) != entry["packaged_sha256"]:
            observed_failures.append(f"packaged_sha256:{entry['path']}")
        normalized = packaged_bytes.replace(b"\r\n", b"\n")
        if sha256_bytes(normalized) != entry["canonical_lf_sha256"]:
            observed_failures.append(f"canonical_lf_sha256:{entry['path']}")
        if not entry.get("git_blob_oid"):
            observed_failures.append(f"git_blob_oid:{entry['path']}")
    if observed_failures:
        raise ValueError(f"package manifest runtime verification failed: {observed_failures}")
    manifest["runtime_verification_passed"] = True
    return manifest


def discover_variants(root: Path) -> list[tuple[str, str, Path]]:
    rows: list[tuple[str, str, Path]] = []
    evaluation_root = root / "evaluation_only"
    for pair_dir in sorted(evaluation_root.glob("*")):
        if not pair_dir.is_dir():
            continue
        for variant in ("clean", "adversarial"):
            variant_dir = pair_dir / variant
            required = [
                variant_dir / "frontend" / "n_frontend1_transitions.parquet",
                variant_dir / "frontend" / "n_frontend1_micro_events.parquet",
                variant_dir / "frontend" / "n_frontend1_non_route_observations.parquet",
                variant_dir / "frontend" / "n_frontend1_summary.json",
                variant_dir / "phase_survival_lineage.csv",
                variant_dir / "past_only_route_exposure.csv",
            ]
            if all(path.is_file() for path in required):
                rows.append((pair_dir.name, variant, variant_dir))
    return rows


def transition_decision(row: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    eligibility = config["suppression_eligibility"]
    missing: list[str] = []
    for field in eligibility["required_identity_fields"]:
        if not text(row.get(field)):
            missing.append(field)
    for field in eligibility["required_reversible_fields"]:
        if not as_list(row.get(field)):
            missing.append(field)
    for field in eligibility["required_positive_count_fields"]:
        value = normalize_json(row.get(field))
        if value is None or int(value) < 1:
            missing.append(field)
    for field in ("state_known_before", "state_known_after", "same_timestamp_ambiguous"):
        is_present, _ = present_bool(row.get(field))
        if not is_present:
            missing.append(field)
    if missing:
        return {
            "eligibility_assignment": ASSIGN_GRAY,
            "eligibility_reason": "incomplete_contract_fields",
            "eligibility_detail": sorted(set(missing)),
        }

    family = text(row.get("transition_family"))
    old_signature = text(row.get("old_route_signature"))
    new_signature = text(row.get("new_route_signature"))
    false_flags_pass = all(not as_bool(row.get(field)) for field in eligibility["required_false_flags"])
    true_flags_pass = all(as_bool(row.get(field)) for field in eligibility["required_true_flags"])
    exact = (
        family == eligibility["transition_family"]
        and old_signature is not None
        and new_signature is not None
        and old_signature == new_signature
        and false_flags_pass
        and true_flags_pass
    )
    if exact:
        return {
            "eligibility_assignment": ASSIGN_BACKGROUND,
            "eligibility_reason": "exact_identical_reannouncement",
            "eligibility_detail": [],
        }

    reasons: list[str] = []
    if as_bool(row.get("same_timestamp_ambiguous")):
        reasons.append("same_timestamp_ambiguity")
    if family != eligibility["transition_family"]:
        reasons.append(f"transition_family:{family or 'missing'}")
    if old_signature != new_signature or old_signature is None or new_signature is None:
        reasons.append("route_signature_not_equal_non_null")
    for field in eligibility["required_false_flags"]:
        if as_bool(row.get(field)):
            reasons.append(field)
    for field in eligibility["required_true_flags"]:
        if not as_bool(row.get(field)):
            reasons.append(f"{field}=false")
    return {
        "eligibility_assignment": ASSIGN_FOREGROUND,
        "eligibility_reason": "protected_route_semantics",
        "eligibility_detail": sorted(set(reasons)),
    }


def route_transitions(
    transitions: pd.DataFrame, config: dict[str, Any]
) -> tuple[pd.DataFrame, str]:
    sort_columns = ["transition_ts", "transition_id"]
    ordered = transitions.sort_values(sort_columns, kind="mergesort").reset_index(drop=True)
    running_fingerprint = sha256_json({"ledger": "n_frontend3b_empty_v1"})
    assignments: list[dict[str, Any]] = []
    for transition_ts, batch in ordered.groupby("transition_ts", sort=False, dropna=False):
        prior_fingerprint = running_fingerprint
        batch_updates: list[dict[str, Any]] = []
        for row in batch.to_dict("records"):
            decision = transition_decision(row, config)
            assignments.append(
                {
                    "transition_id": row["transition_id"],
                    "transition_ts": float(row["transition_ts"]),
                    "collector": row.get("collector"),
                    "peer_address": row.get("peer_address"),
                    "prefix": row.get("prefix"),
                    "transition_family": row.get("transition_family"),
                    "old_route_signature": row.get("old_route_signature"),
                    "new_route_signature": row.get("new_route_signature"),
                    "member_observation_ids": as_list(row.get("member_observation_ids")),
                    "source_files": as_list(row.get("source_files")),
                    "decision_prior_ledger_fingerprint": prior_fingerprint,
                    **decision,
                }
            )
            batch_updates.append(
                {
                    "transition_id": row["transition_id"],
                    "transition_ts": float(transition_ts),
                    "state_key": [
                        text(row.get("collector")),
                        text(row.get("peer_address")),
                        text(row.get("prefix")),
                        text(row.get("path_id")) or "",
                    ],
                    "new_route_signature": text(row.get("new_route_signature")),
                    "transition_family": text(row.get("transition_family")),
                    "eligibility_assignment": decision["eligibility_assignment"],
                }
            )
        # Same-timestamp siblings share the same prior fingerprint.  The batch
        # becomes visible only after every decision at that timestamp is fixed.
        running_fingerprint = sha256_json(
            {
                "prior": running_fingerprint,
                "batch": sorted(batch_updates, key=lambda item: item["transition_id"]),
            }
        )
    return pd.DataFrame(assignments), running_fingerprint


def route_micro_events(
    micro_events: pd.DataFrame, transition_assignments: pd.DataFrame
) -> pd.DataFrame:
    assignment_by_id = dict(
        zip(
            transition_assignments["transition_id"].astype(str),
            transition_assignments["eligibility_assignment"].astype(str),
        )
    )
    rows: list[dict[str, Any]] = []
    for event in micro_events.to_dict("records"):
        member_ids = as_list(event.get("member_transition_ids"))
        member_assignments = [assignment_by_id.get(member_id) for member_id in member_ids]
        missing = [member_id for member_id, value in zip(member_ids, member_assignments) if value is None]
        if missing or not member_ids:
            eligibility = ASSIGN_GRAY
            final_route = FINAL_GRAY
            reason = "missing_member_transition_assignment"
        elif ASSIGN_FOREGROUND in member_assignments:
            eligibility = ASSIGN_FOREGROUND
            final_route = FINAL_FOREGROUND
            reason = "protected_member_precedence"
        elif ASSIGN_GRAY in member_assignments:
            eligibility = ASSIGN_GRAY
            final_route = FINAL_GRAY
            reason = "gray_member_precedence"
        elif all(value == ASSIGN_BACKGROUND for value in member_assignments):
            eligibility = ASSIGN_BACKGROUND
            final_route = FINAL_BACKGROUND
            reason = "all_members_exact_redundancy"
        else:
            eligibility = ASSIGN_GRAY
            final_route = FINAL_GRAY
            reason = "unexpected_member_assignment_set"
        rows.append(
            {
                "micro_event_id": event.get("micro_event_id"),
                "window_start_ts": event.get("window_start_ts"),
                "available_at_ts": event.get("available_at_ts"),
                "prefix": event.get("prefix"),
                "transition_family": event.get("transition_family"),
                "member_transition_ids": member_ids,
                "member_transition_count": len(member_ids),
                "member_assignment_set": sorted(set(value for value in member_assignments if value)),
                "missing_member_transition_ids": missing,
                "eligibility_assignment": eligibility,
                "final_route": final_route,
                "routing_reason": reason,
            }
        )
    return pd.DataFrame(rows)


def attach_final_transition_routes(
    assignments: pd.DataFrame, micro_routing: pd.DataFrame
) -> pd.DataFrame:
    event_by_transition: dict[str, tuple[str, str]] = {}
    for event in micro_routing.to_dict("records"):
        for transition_id in as_list(event["member_transition_ids"]):
            if transition_id in event_by_transition:
                raise ValueError(f"transition appears in multiple primary micro-events: {transition_id}")
            event_by_transition[transition_id] = (event["micro_event_id"], event["final_route"])
    result = assignments.copy()
    result["micro_event_id"] = result["transition_id"].map(
        lambda value: event_by_transition.get(str(value), (None, FINAL_GRAY))[0]
    )
    result["final_route"] = result["transition_id"].map(
        lambda value: event_by_transition.get(str(value), (None, FINAL_GRAY))[1]
    )
    return result


def strict_replay_audit(
    transitions: pd.DataFrame,
    primary: pd.DataFrame,
    primary_fingerprint: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    replay, replay_fingerprint = route_transitions(transitions, config)
    columns = ["transition_id", "eligibility_assignment", "eligibility_reason", "decision_prior_ledger_fingerprint"]
    left = primary[columns].sort_values("transition_id").reset_index(drop=True)
    right = replay[columns].sort_values("transition_id").reset_index(drop=True)
    matched = left.equals(right)
    return {
        "transition_count": len(primary),
        "assignment_table_equal": matched,
        "primary_ledger_fingerprint": primary_fingerprint,
        "replay_ledger_fingerprint": replay_fingerprint,
        "ledger_fingerprint_equal": primary_fingerprint == replay_fingerprint,
        "passed": matched and primary_fingerprint == replay_fingerprint,
    }


def build_background_index(background: pd.DataFrame, source_path: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if background.empty:
        return pd.DataFrame(
            columns=[
                "collector", "peer_address", "prefix", "route_signature",
                "first_ts", "last_ts", "member_count", "ordered_transition_ids",
                "ordered_transition_ts", "ordered_inter_arrival_gaps_sec",
                "member_observation_ids", "source_files", "immutable_member_store",
            ]
        )
    grouped = background.groupby(
        ["collector", "peer_address", "prefix", "new_route_signature"],
        dropna=False,
        sort=False,
    )
    for key, members in grouped:
        ordered = members.sort_values(["transition_ts", "transition_id"], kind="mergesort")
        times = [float(value) for value in ordered["transition_ts"].tolist()]
        rows.append(
            {
                "collector": normalize_json(key[0]),
                "peer_address": normalize_json(key[1]),
                "prefix": normalize_json(key[2]),
                "route_signature": normalize_json(key[3]),
                "first_ts": min(times),
                "last_ts": max(times),
                "member_count": len(ordered),
                "ordered_transition_ids": ordered["transition_id"].astype(str).tolist(),
                "ordered_transition_ts": times,
                "ordered_inter_arrival_gaps_sec": [
                    times[index] - times[index - 1] for index in range(1, len(times))
                ],
                "member_observation_ids": sorted(
                    {
                        observation_id
                        for value in ordered["member_observation_ids"].tolist()
                        for observation_id in as_list(value)
                    }
                ),
                "source_files": sorted(
                    {
                        source
                        for value in ordered["source_files"].tolist()
                        for source in as_list(value)
                    }
                ),
                "immutable_member_store": str(source_path),
            }
        )
    return pd.DataFrame(rows)


def canonical_exposure_rows(
    lineage: pd.DataFrame, transitions: pd.DataFrame
) -> pd.DataFrame:
    transition_records = transitions.to_dict("records")
    transition_by_id = {str(row["transition_id"]): row for row in transition_records}
    truth_by_observation = {
        str(row["observation_id"]): row
        for row in lineage.to_dict("records")
        if text(row.get("observation_id"))
    }
    result: list[dict[str, Any]] = []
    for attack in lineage.to_dict("records"):
        if not as_bool(attack.get("is_attack_member")) or not as_bool(attack.get("expected_visible")):
            continue
        transition_id = text(attack.get("transition_id"))
        if not transition_id or transition_id not in transition_by_id:
            raise ValueError("visible attack transition is unavailable for exposure query")
        current = transition_by_id[transition_id]
        signature = text(current.get("new_route_signature"))
        attack_ts = float(current["transition_ts"])
        prior = sorted(
            [
                row
                for row in transition_records
                if text(row.get("new_route_signature")) == signature
                and float(row["transition_ts"]) < attack_ts
            ],
            key=lambda row: (float(row["transition_ts"]), str(row["transition_id"])),
        )
        times = [float(row["transition_ts"]) for row in prior]
        prior_ids = [
            observation_id
            for row in prior
            for observation_id in as_list(row.get("member_observation_ids"))
        ]
        prior_truth = [truth_by_observation[value] for value in prior_ids if value in truth_by_observation]
        same_observer_withdrawals = [
            row
            for row in transition_records
            if text(row.get("collector")) == text(current.get("collector"))
            and text(row.get("peer_address")) == text(current.get("peer_address"))
            and text(row.get("prefix")) == text(current.get("prefix"))
            and text(row.get("transition_family")) in WITHDRAWAL_FAMILIES
            and float(row["transition_ts"]) < attack_ts
        ]
        peer_set = sorted({text(row.get("peer_address")) for row in prior if text(row.get("peer_address"))})
        collector_set = sorted({text(row.get("collector")) for row in prior if text(row.get("collector"))})
        result.append(
            {
                "pair_id": attack.get("pair_id"),
                "variant_role": attack.get("variant_role"),
                "collector": attack.get("collector"),
                "peer_address": attack.get("peer_address"),
                "attack_observation_id": attack.get("observation_id"),
                "attack_ts": attack_ts,
                "route_signature": signature,
                "previously_exposed": bool(prior),
                "prior_exposure_count": len(prior),
                "first_seen_ts": min(times) if times else None,
                "first_seen_age_sec": attack_ts - min(times) if times else None,
                "last_seen_ts": max(times) if times else None,
                "last_seen_gap_sec": attack_ts - max(times) if times else None,
                "ordered_prior_transition_ids": [str(row["transition_id"]) for row in prior],
                "ordered_prior_transition_ts": times,
                "ordered_inter_arrival_gaps_sec": [times[index] - times[index - 1] for index in range(1, len(times))],
                "distinct_prior_300s_bucket_count": len({math.floor(value / 300.0) for value in times}),
                "distinct_prior_utc_day_count": len({datetime.fromtimestamp(value, tz=timezone.utc).date().isoformat() for value in times}),
                "distinct_prior_peer_count": len(peer_set),
                "distinct_prior_peer_set": peer_set,
                "distinct_prior_collector_count": len(collector_set),
                "distinct_prior_collector_set": collector_set,
                "prior_withdrawal_count": len(same_observer_withdrawals),
                "exposure_only_in_poisoning_preparation": bool(prior)
                and bool(prior_truth)
                and all(as_bool(row.get("is_poisoning_preparation_member")) for row in prior_truth),
                "maximum_contributing_transition_ts": max(times) if times else None,
                "causality_valid": all(value < attack_ts for value in times),
                "bounded_proxy": True,
            }
        )
    return pd.DataFrame(result)


def compare_exposure(pre: pd.DataFrame, post: pd.DataFrame) -> pd.DataFrame:
    keys = ["pair_id", "variant_role", "collector", "peer_address", "attack_observation_id"]
    metric_columns = [column for column in pre.columns if column not in keys]
    pre_rows = {tuple(str(row.get(key)) for key in keys): row for row in pre.to_dict("records")}
    post_rows = {tuple(str(row.get(key)) for key in keys): row for row in post.to_dict("records")}
    rows: list[dict[str, Any]] = []
    for key in sorted(set(pre_rows) | set(post_rows)):
        before = pre_rows.get(key)
        after = post_rows.get(key)
        mismatches = []
        if before is None or after is None:
            mismatches = ["missing_row"]
        else:
            mismatches = [
                column
                for column in metric_columns
                if stable_json(before.get(column)) != stable_json(after.get(column))
            ]
        rows.append(
            {
                **dict(zip(keys, key)),
                "pre_row_sha256": sha256_json(before) if before is not None else None,
                "post_row_sha256": sha256_json(after) if after is not None else None,
                "mismatch_columns": mismatches,
                "exact_equal": not mismatches,
            }
        )
    return pd.DataFrame(rows)


def compare_frozen_2b_exposure(recomputed: pd.DataFrame, baseline_path: Path) -> bool:
    baseline = pd.read_csv(baseline_path)
    shared = [column for column in baseline.columns if column in recomputed.columns]
    keys = ["pair_id", "variant_role", "collector", "peer_address", "attack_observation_id"]
    left = recomputed[shared].sort_values(keys).reset_index(drop=True).to_dict("records")
    right = baseline[shared].sort_values(keys).reset_index(drop=True).to_dict("records")
    return stable_json(left) == stable_json(right)


def process_variant(
    pair_id: str,
    variant_role: str,
    source_dir: Path,
    output_dir: Path,
    config: dict[str, Any],
) -> dict[str, Any]:
    transitions_path = source_dir / "frontend" / "n_frontend1_transitions.parquet"
    micro_path = source_dir / "frontend" / "n_frontend1_micro_events.parquet"
    lineage_path = source_dir / "phase_survival_lineage.csv"
    exposure_path = source_dir / "past_only_route_exposure.csv"
    non_route_path = source_dir / "frontend" / "n_frontend1_non_route_observations.parquet"
    frontend_summary_path = source_dir / "frontend" / "n_frontend1_summary.json"
    transitions = pd.read_parquet(transitions_path)
    micro_events = pd.read_parquet(micro_path)
    lineage = pd.read_csv(lineage_path)
    non_route = pd.read_parquet(non_route_path)
    non_route_count = len(non_route)
    non_route_observation_ids = {
        str(value)
        for value in non_route.get("observation_id", pd.Series(dtype=object)).dropna()
    }
    frontend_summary = json.loads(frontend_summary_path.read_text(encoding="utf-8"))
    output_dir.mkdir(parents=True)

    assignments, ledger_fingerprint = route_transitions(transitions, config)
    online_columns = set(assignments.columns)
    truth_leak = sorted(online_columns & set(config["truth_columns_forbidden_online"]))
    if truth_leak:
        raise ValueError(f"truth fields leaked into online assignment: {truth_leak}")
    replay_audit = strict_replay_audit(transitions, assignments, ledger_fingerprint, config)
    micro_routing = route_micro_events(micro_events, assignments)
    assignments = attach_final_transition_routes(assignments, micro_routing)
    routed_observation_ids = {
        observation_id
        for value in assignments["member_observation_ids"].tolist()
        for observation_id in as_list(value)
    }
    non_route_consumed_count = len(non_route_observation_ids & routed_observation_ids)

    source_by_id = transitions.set_index("transition_id", drop=False)
    foreground_ids = assignments.loc[assignments["final_route"] == FINAL_FOREGROUND, "transition_id"]
    background_ids = assignments.loc[assignments["final_route"] == FINAL_BACKGROUND, "transition_id"]
    gray_ids = assignments.loc[assignments["final_route"] == FINAL_GRAY, "transition_id"]
    foreground = source_by_id.loc[list(foreground_ids)].reset_index(drop=True) if len(foreground_ids) else transitions.iloc[0:0].copy()
    background = source_by_id.loc[list(background_ids)].reset_index(drop=True) if len(background_ids) else transitions.iloc[0:0].copy()
    gray = source_by_id.loc[list(gray_ids)].reset_index(drop=True) if len(gray_ids) else transitions.iloc[0:0].copy()

    micro_by_id = micro_events.set_index("micro_event_id", drop=False)
    foreground_event_ids = micro_routing.loc[micro_routing["final_route"] == FINAL_FOREGROUND, "micro_event_id"]
    background_event_ids = micro_routing.loc[micro_routing["final_route"] == FINAL_BACKGROUND, "micro_event_id"]
    foreground_events = micro_by_id.loc[list(foreground_event_ids)].reset_index(drop=True) if len(foreground_event_ids) else micro_events.iloc[0:0].copy()
    background_events = micro_by_id.loc[list(background_event_ids)].reset_index(drop=True) if len(background_event_ids) else micro_events.iloc[0:0].copy()

    foreground_path = output_dir / "semantic_foreground_transitions.parquet"
    background_path = output_dir / "immutable_background_transitions.parquet"
    gray_path = output_dir / "gray_contract_anomaly_transitions.parquet"
    write_frame(foreground_path, foreground)
    write_frame(background_path, background)
    write_frame(gray_path, gray)
    write_frame(output_dir / "semantic_foreground_micro_events.parquet", foreground_events)
    write_frame(output_dir / "reversible_background_micro_events.parquet", background_events)
    write_frame(output_dir / "n_frontend3b_transition_assignments.parquet", assignments)
    write_frame(output_dir / "n_frontend3b_micro_event_routing.parquet", micro_routing)
    background_index = build_background_index(background, background_path)
    write_frame(output_dir / "n_frontend3b_reversible_background_index.parquet", background_index)
    background_member_manifest = assignments.loc[
        assignments["final_route"] == FINAL_BACKGROUND,
        [
            "transition_id", "transition_ts", "collector", "peer_address", "prefix",
            "new_route_signature", "member_observation_ids", "source_files",
            "micro_event_id", "final_route",
        ],
    ].copy()
    background_member_manifest["immutable_member_store"] = str(background_path)
    write_frame(
        output_dir / "n_frontend3b_background_member_manifest.parquet",
        background_member_manifest,
    )

    # Reconstruct from persisted routes rather than reusing the in-memory input.
    restored_parts = [pd.read_parquet(path) for path in (foreground_path, background_path, gray_path)]
    restored = pd.concat(restored_parts, ignore_index=True, sort=False)
    original_ids = sorted(transitions["transition_id"].astype(str).tolist())
    restored_ids = sorted(restored["transition_id"].astype(str).tolist())
    restoration_audit = {
        "pair_id": pair_id,
        "variant_role": variant_role,
        "input_transition_count": len(transitions),
        "restored_transition_count": len(restored),
        "unique_input_transition_count": len(set(original_ids)),
        "unique_restored_transition_count": len(set(restored_ids)),
        "id_multiset_equal": original_ids == restored_ids,
        "input_transition_id_sha256": sha256_json(original_ids),
        "restored_transition_id_sha256": sha256_json(restored_ids),
        "passed": original_ids == restored_ids,
    }

    pre_exposure = canonical_exposure_rows(lineage, transitions)
    post_exposure = canonical_exposure_rows(lineage, restored)
    exposure_equality = compare_exposure(pre_exposure, post_exposure)
    frozen_2b_match = compare_frozen_2b_exposure(pre_exposure, exposure_path)
    write_frame(output_dir / "n_frontend3b_past_only_exposure_pre.csv", pre_exposure)
    write_frame(output_dir / "n_frontend3b_past_only_exposure_post.csv", post_exposure)
    write_frame(output_dir / "n_frontend3b_past_only_exposure_equality.csv", exposure_equality)

    write_json(
        output_dir / "n_frontend3b_variant_manifest.json",
        {
            "pair_id": pair_id,
            "variant_role": variant_role,
            "source_transition_path": str(transitions_path),
            "source_transition_sha256": sha256_file(transitions_path),
            "source_micro_event_path": str(micro_path),
            "source_micro_event_sha256": sha256_file(micro_path),
            "source_lineage_path": str(lineage_path),
            "source_lineage_sha256": sha256_file(lineage_path),
            "source_exposure_path": str(exposure_path),
            "source_exposure_sha256": sha256_file(exposure_path),
            "transition_count": len(transitions),
            "micro_event_count": len(micro_events),
            "truth_column_leak_count": len(truth_leak),
            "final_ledger_fingerprint": ledger_fingerprint,
        },
    )
    return {
        "pair_id": pair_id,
        "variant_role": variant_role,
        "source_dir": str(source_dir),
        "output_dir": str(output_dir),
        "transition_count": len(transitions),
        "micro_event_count": len(micro_events),
        "assignments": assignments,
        "micro_routing": micro_routing,
        "lineage": lineage,
        "restoration_audit": restoration_audit,
        "strict_replay_audit": {"pair_id": pair_id, "variant_role": variant_role, **replay_audit},
        "exposure_equality": exposure_equality,
        "frozen_2b_exposure_match": frozen_2b_match,
        "truth_leak_count": len(truth_leak),
        "non_route_input_count": non_route_count,
        "non_route_consumed_count": non_route_consumed_count,
        "non_route_source_path": str(non_route_path),
        "frontend_summary": frontend_summary,
        "frontend_summary_path": str(frontend_summary_path),
    }


def percentile(values: Iterable[float], q: float) -> float:
    values = list(values)
    return float(np.percentile(values, q)) if values else 0.0


def run_experiment(
    source_root: Path,
    output_dir: Path,
    config_path: Path,
    package_manifest_path: Path | None,
    overwrite: bool,
    self_test: bool,
) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[1]
    config = load_config(config_path)
    prepare_output_dir(output_dir, overwrite)
    anchor_rows = validate_source_anchors(config, repo_root)
    package_manifest = validate_package_manifest(package_manifest_path, self_test, repo_root)
    write_frame(output_dir / "n_frontend3b_source_anchor_audit.csv", pd.DataFrame(anchor_rows))
    write_json(output_dir / "n_frontend3b_package_manifest.json", package_manifest)

    summary_path = source_root / "n_frontend2b_summary.json"
    registry_path = source_root / "n_frontend2b_registry_freeze.json"
    root_lineage_path = source_root / "n_frontend2b_phase_survival_lineage.csv"
    delta_path = source_root / "n_frontend2b_attack_transition_semantic_delta.csv"
    for path in (summary_path, registry_path, root_lineage_path, delta_path):
        if not path.is_file():
            raise FileNotFoundError(path)
    source_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    registry_freeze = json.loads(registry_path.read_text(encoding="utf-8"))
    registry_fingerprint = source_summary.get("registry_freeze_fingerprint")
    if not self_test and registry_fingerprint != config["formal_2b_registry_fingerprint"]:
        raise ValueError("2B observer registry fingerprint differs from frozen contract")
    if not source_summary.get("overall_pass"):
        raise ValueError("source N-FRONTEND-2B replay did not pass")
    protocol_sha = source_summary.get("protocol_config_sha256")
    if protocol_sha not in {
        config["poisoning_protocol_canonical_sha256"],
        config["poisoning_protocol_formal_2b_crlf_sha256"],
    }:
        raise ValueError("2B protocol byte hash is neither frozen LF nor documented CRLF")
    frozen_inputs = []
    for path in (summary_path, registry_path, root_lineage_path, delta_path):
        frozen_inputs.append(
            {"path": str(path), "size_bytes": path.stat().st_size, "sha256": sha256_file(path)}
        )
    write_json(
        output_dir / "n_frontend3b_frozen_input_manifest.json",
        {
            "source_2b_root": str(source_root),
            "registry_fingerprint": registry_fingerprint,
            "protocol_config_sha256": protocol_sha,
            "inputs": frozen_inputs,
        },
    )

    variants = discover_variants(source_root)
    if len(variants) != 10:
        raise ValueError(f"expected 10 complete pair variants, found {len(variants)}")
    variant_results: list[dict[str, Any]] = []
    for pair_id, variant_role, source_dir in variants:
        variant_output = output_dir / "evaluation_only" / pair_id / variant_role
        variant_result = process_variant(
            pair_id,
            variant_role,
            source_dir,
            variant_output,
            config,
        )
        if self_test:
            source_snapshot = variant_output / "_selftest_source_transitions.parquet"
            exposure_snapshot = variant_output / "_selftest_source_exposure.csv"
            pd.read_parquet(
                source_dir / "frontend" / "n_frontend1_transitions.parquet"
            ).to_parquet(source_snapshot, index=False)
            shutil.copyfile(source_dir / "past_only_route_exposure.csv", exposure_snapshot)
            manifest_path = variant_output / "n_frontend3b_variant_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["source_transition_path"] = str(source_snapshot)
            manifest["source_transition_sha256"] = sha256_file(source_snapshot)
            manifest["source_exposure_path"] = str(exposure_snapshot)
            manifest["source_exposure_sha256"] = sha256_file(exposure_snapshot)
            manifest["self_test_source_snapshot"] = True
            write_json(manifest_path, manifest)
        variant_results.append(variant_result)

    root_lineage = pd.read_csv(root_lineage_path)
    truth_observations_by_variant: dict[tuple[str, str], set[str]] = {}
    for (pair_id, variant_role), frame in root_lineage.groupby(["pair_id", "variant_role"]):
        truth_observations_by_variant[(pair_id, variant_role)] = {
            str(value) for value in frame["observation_id"].dropna().astype(str)
        }

    denominator_rows: list[dict[str, Any]] = []
    transition_load_rows: list[dict[str, Any]] = []
    micro_load_rows: list[dict[str, Any]] = []
    composition_rows: list[dict[str, Any]] = []
    micro_member_distribution_rows: list[dict[str, Any]] = []
    upstream_dedup_rows: list[dict[str, Any]] = []
    exhaustion_groups: list[dict[str, Any]] = []
    safety_rows: list[dict[str, Any]] = []
    restoration_rows = [result["restoration_audit"] for result in variant_results]
    strict_replay_rows = [result["strict_replay_audit"] for result in variant_results]
    all_exposure_equal = True
    all_exposure_equality_frames: list[pd.DataFrame] = []
    semantic_assignment_rows: list[dict[str, Any]] = []
    semantic_micro_rows: list[dict[str, Any]] = []
    for result in variant_results:
        pair_id = result["pair_id"]
        variant_role = result["variant_role"]
        injected_observation_ids = truth_observations_by_variant[(pair_id, variant_role)]
        assignments = result["assignments"].copy()
        semantic_assignment_rows.extend(
            {
                "pair_id": pair_id,
                "variant_role": variant_role,
                "transition_id": row["transition_id"],
                "eligibility_assignment": row["eligibility_assignment"],
                "eligibility_reason": row["eligibility_reason"],
                "micro_event_id": row["micro_event_id"],
                "final_route": row["final_route"],
            }
            for row in assignments.to_dict("records")
        )
        assignments["contains_injected_member"] = assignments["member_observation_ids"].map(
            lambda value: bool(set(as_list(value)) & injected_observation_ids)
        )
        eligible = assignments[~assignments["contains_injected_member"]].copy()
        micro = result["micro_routing"].copy()
        semantic_micro_rows.extend(
            {
                "pair_id": pair_id,
                "variant_role": variant_role,
                "micro_event_id": row["micro_event_id"],
                "eligibility_assignment": row["eligibility_assignment"],
                "final_route": row["final_route"],
                "routing_reason": row["routing_reason"],
            }
            for row in micro.to_dict("records")
        )
        injected_transition_ids = set(
            assignments.loc[assignments["contains_injected_member"], "transition_id"].astype(str)
        )
        micro["contains_injected_member"] = micro["member_transition_ids"].map(
            lambda value: bool(set(as_list(value)) & injected_transition_ids)
        )
        eligible_micro = micro[~micro["contains_injected_member"]].copy()
        upstream = result["frontend_summary"]
        upstream_dedup_rows.append(
            {
                "pair_id": pair_id,
                "variant_role": variant_role,
                "population": "complete_N-FRONTEND-1_variant_input; not the N-FRONTEND-3B suppression denominator",
                "source_summary_path": result["frontend_summary_path"],
                "input_rows": int(upstream["input_rows"]),
                "exact_unique_observation_count": int(
                    upstream["exact_unique_observation_count"]
                ),
                "exact_duplicate_copy_count": int(
                    upstream["exact_duplicate_copy_count"]
                ),
                "exact_duplicate_reduction_rate": float(
                    upstream["exact_duplicate_reduction_rate"]
                ),
                "counted_in_3b_learning_input_reduction": False,
            }
        )
        denominator_rows.append(
            {
                "pair_id": pair_id,
                "variant_role": variant_role,
                "transition_total_count": len(assignments),
                "transition_injected_exclusion_count": int(assignments["contains_injected_member"].sum()),
                "transition_operational_background_count": len(eligible),
                "micro_event_total_count": len(micro),
                "micro_event_injected_exclusion_count": int(micro["contains_injected_member"].sum()),
                "micro_event_operational_background_count": len(eligible_micro),
                "truth_used_only_after_routing": True,
            }
        )
        transition_suppressed = int((eligible["final_route"] == FINAL_BACKGROUND).sum())
        transition_foreground = int((eligible["final_route"] == FINAL_FOREGROUND).sum())
        transition_load_rows.append(
            {
                "pair_id": pair_id,
                "variant_role": variant_role,
                "population": "unlabeled_operational_background",
                "background_input_count": len(eligible),
                "suppressible_eligibility_count": int((eligible["eligibility_assignment"] == ASSIGN_BACKGROUND).sum()),
                "background_routed_count": transition_suppressed,
                "learning_input_count": transition_foreground,
                "gray_count": int((eligible["final_route"] == FINAL_GRAY).sum()),
                "learning_input_reduction_rate": transition_suppressed / len(eligible) if len(eligible) else 0.0,
                "learning_input_compression_ratio": len(eligible) / transition_foreground if transition_foreground else None,
            }
        )
        micro_suppressed = int((eligible_micro["final_route"] == FINAL_BACKGROUND).sum())
        micro_foreground = int((eligible_micro["final_route"] == FINAL_FOREGROUND).sum())
        micro_load_rows.append(
            {
                "pair_id": pair_id,
                "variant_role": variant_role,
                "population": "unlabeled_operational_background",
                "background_input_count": len(eligible_micro),
                "background_routed_count": micro_suppressed,
                "learning_input_count": micro_foreground,
                "gray_count": int((eligible_micro["final_route"] == FINAL_GRAY).sum()),
                "learning_input_reduction_rate": micro_suppressed / len(eligible_micro) if len(eligible_micro) else 0.0,
                "learning_input_compression_ratio": len(eligible_micro) / micro_foreground if micro_foreground else None,
            }
        )
        for (member_count, route), count in eligible_micro.groupby(
            ["member_transition_count", "final_route"], dropna=False
        ).size().items():
            micro_member_distribution_rows.append(
                {
                    "pair_id": pair_id,
                    "variant_role": variant_role,
                    "population": "unlabeled_operational_background",
                    "member_transition_count": int(member_count),
                    "final_route": route,
                    "micro_event_count": int(count),
                }
            )
        for (family, route), count in eligible.groupby(["transition_family", "final_route"]).size().items():
            composition_rows.append(
                {
                    "pair_id": pair_id,
                    "variant_role": variant_role,
                    "transition_family": family,
                    "final_route": route,
                    "count": int(count),
                }
            )
        for key, frame in eligible.groupby(["collector", "peer_address", "prefix"], dropna=False):
            foreground_count = int((frame["final_route"] == FINAL_FOREGROUND).sum())
            exhaustion_groups.append(
                {
                    "pair_id": pair_id,
                    "variant_role": variant_role,
                    "collector": normalize_json(key[0]),
                    "peer_address": normalize_json(key[1]),
                    "prefix": normalize_json(key[2]),
                    "transition_count": len(frame),
                    "foreground_count": foreground_count,
                    "background_count": int((frame["final_route"] == FINAL_BACKGROUND).sum()),
                    "foreground_share": foreground_count / len(frame),
                }
            )
        lineage = result["lineage"]
        final_by_transition = dict(zip(assignments["transition_id"].astype(str), assignments["final_route"]))
        for row in lineage.to_dict("records"):
            transition_id = text(row.get("transition_id"))
            final_route = final_by_transition.get(transition_id)
            safety_rows.append(
                {
                    "pair_id": pair_id,
                    "variant_role": variant_role,
                    "phase_id": row.get("phase_id"),
                    "observation_id": row.get("observation_id"),
                    "collector": row.get("collector"),
                    "peer_address": row.get("peer_address"),
                    "transition_id": transition_id,
                    "transition_family": row.get("transition_family"),
                    "is_attack_member": as_bool(row.get("is_attack_member")),
                    "is_poisoning_preparation_member": as_bool(row.get("is_poisoning_preparation_member")),
                    "expected_visible": as_bool(row.get("expected_visible")),
                    "observability_boundary": as_bool(row.get("observability_boundary")),
                    "final_route": final_route,
                    "traceable_after_routing": bool(transition_id and final_route),
                    "attack_suppressed": as_bool(row.get("is_attack_member"))
                    and as_bool(row.get("expected_visible"))
                    and final_route == FINAL_BACKGROUND,
                }
            )
        all_exposure_equal = all_exposure_equal and bool(result["exposure_equality"]["exact_equal"].all())
        equality = result["exposure_equality"].copy()
        equality.insert(0, "source_variant_role", variant_role)
        equality.insert(0, "source_pair_id", pair_id)
        all_exposure_equality_frames.append(equality)

    denominator = pd.DataFrame(denominator_rows)
    transition_load = pd.DataFrame(transition_load_rows)
    micro_load = pd.DataFrame(micro_load_rows)
    composition = pd.DataFrame(composition_rows)
    micro_member_distribution = pd.DataFrame(micro_member_distribution_rows)
    upstream_dedup = pd.DataFrame(upstream_dedup_rows)
    exhaustion = pd.DataFrame(exhaustion_groups)
    safety = pd.DataFrame(safety_rows)
    restoration = pd.DataFrame(restoration_rows)
    strict_replay = pd.DataFrame(strict_replay_rows)
    gray_count = sum(int((result["assignments"]["final_route"] == FINAL_GRAY).sum()) for result in variant_results)
    suppressed_attack_count = int(safety["attack_suppressed"].sum())
    expected_visible_traceable = bool(safety.loc[safety["expected_visible"], "traceable_after_routing"].all())
    delta = pd.read_csv(delta_path)
    delta_index = {
        (row["pair_id"], row["variant_role"], row["collector"], row["peer_address"]): row
        for row in delta.to_dict("records")
    }
    delta_routes = []
    for row in safety.loc[safety["is_attack_member"] & safety["expected_visible"]].to_dict("records"):
        key = (row["pair_id"], row["variant_role"], row.get("collector"), row.get("peer_address"))
        candidate = delta_index.get(key)
        candidates = [candidate] if candidate and candidate.get("observed_attack_transition_family") == row["transition_family"] else []
        delta_routes.append(bool(candidates) and row["final_route"] == FINAL_FOREGROUND)
    semantic_delta_observable = bool(delta_routes) and all(delta_routes) and bool(delta["family_expectation_matched"].map(as_bool).all())

    exhaustion_summary = {
        "population": "unlabeled_operational_background",
        "observer_prefix_count": len(exhaustion),
        "foreground_share_p50": percentile(exhaustion["foreground_share"], 50),
        "foreground_share_p90": percentile(exhaustion["foreground_share"], 90),
        "foreground_share_p99": percentile(exhaustion["foreground_share"], 99),
        "foreground_share_max": float(exhaustion["foreground_share"].max()) if len(exhaustion) else 0.0,
    }
    top_exhaustion = exhaustion.sort_values(
        ["foreground_count", "transition_count"], ascending=False, kind="mergesort"
    ).head(100)

    write_frame(output_dir / "n_frontend3b_denominator_audit.csv", denominator)
    write_frame(output_dir / "n_frontend3b_transition_learning_load.csv", transition_load)
    write_frame(output_dir / "n_frontend3b_micro_event_learning_load.csv", micro_load)
    write_frame(output_dir / "n_frontend3b_foreground_family_composition.csv", composition)
    write_frame(
        output_dir / "n_frontend3b_micro_event_member_distribution.csv",
        micro_member_distribution,
    )
    write_frame(
        output_dir / "n_frontend3b_upstream_exact_dedup_audit.csv",
        upstream_dedup,
    )
    write_frame(output_dir / "n_frontend3b_observer_prefix_exhaustion.csv", exhaustion)
    write_frame(output_dir / "n_frontend3b_observer_prefix_exhaustion_top.csv", top_exhaustion)
    write_json(output_dir / "n_frontend3b_observer_prefix_exhaustion_summary.json", exhaustion_summary)
    write_frame(output_dir / "n_frontend3b_phase_survival_regression.csv", safety)
    write_frame(output_dir / "n_frontend3b_restoration_audit.csv", restoration)
    write_frame(
        output_dir / "n_frontend3b_past_only_exposure_equality.csv",
        pd.concat(all_exposure_equality_frames, ignore_index=True, sort=False),
    )
    write_frame(output_dir / "n_frontend3b_causal_strict_replay_audit.csv", strict_replay)
    write_frame(output_dir / "n_frontend3b_semantic_delta_regression.csv", delta)
    write_frame(
        output_dir / "n_frontend3b_gray_tripwire_audit.csv",
        pd.DataFrame([{"gray_count": gray_count, "expected_gray_count": 0, "passed": gray_count == 0}]),
    )
    write_frame(
        output_dir / "n_frontend3b_non_route_bypass_audit.csv",
        pd.DataFrame(
            [
                {
                    "pair_id": result["pair_id"],
                    "variant_role": result["variant_role"],
                    "non_route_source_path": result["non_route_source_path"],
                    "non_route_record_count": result["non_route_input_count"],
                    "non_route_records_consumed_by_suppression": result[
                        "non_route_consumed_count"
                    ],
                    "bypass_contract": "N-FRONTEND-1 dedicated audit",
                    "passed": result["non_route_consumed_count"] == 0,
                }
                for result in variant_results
            ]
        ),
    )
    stage_accounting = restoration.rename(
        columns={
            "input_transition_count": "stage_input_count",
            "restored_transition_count": "stage_output_count",
        }
    )[["pair_id", "variant_role", "stage_input_count", "stage_output_count", "passed"]].copy()
    stage_accounting["stage"] = "transition_routing_and_restoration"
    stage_accounting["unexplained_loss_count"] = (
        stage_accounting["stage_input_count"] - stage_accounting["stage_output_count"]
    )
    write_frame(output_dir / "n_frontend3b_stage_accounting_audit.csv", stage_accounting)

    exposure_match = all(result["frozen_2b_exposure_match"] for result in variant_results)
    stage_accounting_pass = bool(
        stage_accounting["passed"].map(as_bool).all()
        and (stage_accounting["unexplained_loss_count"] == 0).all()
    )
    non_route_bypass_pass = all(
        result["non_route_consumed_count"] == 0 for result in variant_results
    )
    boundary = safety[safety["observability_boundary"]].copy()
    expected_boundary_count = int(
        source_summary.get("observability_boundary_member_count", len(boundary))
    )
    boundary_not_miss_pass = bool(
        len(boundary) == expected_boundary_count
        and not boundary["expected_visible"].map(as_bool).any()
        and boundary["transition_id"].isna().all()
        and boundary["final_route"].isna().all()
        and not boundary["attack_suppressed"].map(as_bool).any()
    )
    stop_loss = {
        "source_anchor_pass": all(row["passed"] for row in anchor_rows),
        "package_manifest_pass": bool(package_manifest["all_entries_passed"]),
        "source_2b_pass": bool(source_summary["overall_pass"]),
        "variant_count_pass": len(variant_results) == 10,
        "truth_not_online_pass": all(result["truth_leak_count"] == 0 for result in variant_results),
        "gray_tripwire_pass": gray_count == 0,
        "restoration_pass": bool(restoration["passed"].all()),
        "stage_accounting_pass": stage_accounting_pass,
        "non_route_bypass_pass": non_route_bypass_pass,
        "causal_strict_replay_pass": bool(strict_replay["passed"].all()),
        "past_only_joint_view_exact_pass": all_exposure_equal,
        "frozen_2b_exposure_regression_pass": exposure_match,
        "suppressed_attack_count_pass": suppressed_attack_count == 0,
        "phase_traceability_pass": expected_visible_traceable,
        "semantic_delta_observable_pass": semantic_delta_observable,
        "denominator_purity_pass": bool(denominator["truth_used_only_after_routing"].all()),
        "observability_boundary_not_miss_pass": boundary_not_miss_pass,
    }
    overall_pass = all(stop_loss.values())
    stop_loss_rows = [{"gate": key, "passed": value} for key, value in stop_loss.items()]
    write_frame(output_dir / "n_frontend3b_stop_loss_audit.csv", pd.DataFrame(stop_loss_rows))

    semantic_manifest = {
        "assignment_count": len(semantic_assignment_rows),
        "micro_event_count": len(semantic_micro_rows),
        "assignment_fingerprint": sha256_json(
            sorted(semantic_assignment_rows, key=lambda row: (row["pair_id"], row["variant_role"], row["transition_id"]))
        ),
        "micro_event_fingerprint": sha256_json(
            sorted(semantic_micro_rows, key=lambda row: (row["pair_id"], row["variant_role"], row["micro_event_id"]))
        ),
        "stop_loss_fingerprint": sha256_json(stop_loss),
    }
    semantic_manifest["combined_semantic_fingerprint"] = sha256_json(semantic_manifest)
    write_json(output_dir / "n_frontend3b_semantic_output_manifest.json", semantic_manifest)

    transition_input = int(transition_load["background_input_count"].sum())
    transition_suppressed = int(transition_load["background_routed_count"].sum())
    micro_input = int(micro_load["background_input_count"].sum())
    micro_suppressed = int(micro_load["background_routed_count"].sum())
    summary = {
        "phase": config["phase"],
        "config_version": config["config_version"],
        "frozen_contract_commit": config["frozen_contract_commit"],
        "source_2b_root": str(source_root),
        "source_2b_registry_fingerprint": registry_fingerprint,
        "source_2b_protocol_sha256": protocol_sha,
        "pair_count": len({result["pair_id"] for result in variant_results}),
        "variant_count": len(variant_results),
        "count_scope": "variant_expanded_bounded_replay; shared background is repeated once per paired variant",
        "transition_operational_background_input_count": transition_input,
        "transition_operational_background_suppressed_count": transition_suppressed,
        "transition_learning_input_reduction_rate": transition_suppressed / transition_input if transition_input else 0.0,
        "micro_event_operational_background_input_count": micro_input,
        "micro_event_operational_background_suppressed_count": micro_suppressed,
        "micro_event_learning_input_reduction_rate": micro_suppressed / micro_input if micro_input else 0.0,
        "suppressed_attack_count": suppressed_attack_count,
        "gray_count": gray_count,
        "expected_visible_member_count": int(safety["expected_visible"].sum()),
        "observability_boundary_member_count": int(safety["observability_boundary"].sum()),
        "upstream_exact_duplicate_copy_count_variant_expanded": int(
            upstream_dedup["exact_duplicate_copy_count"].sum()
        ),
        "upstream_exact_dedup_counted_in_3b_reduction": False,
        "stop_loss_gates": stop_loss,
        "overall_pass": overall_pass,
        "allowed_claim": config["allowed_claim"] if overall_pass else None,
        "forbidden_claims": config["forbidden_claims"],
        "learning_trained": False,
        "attack_or_benign_truth_produced": False,
        "storage_compression_claimed": False,
        "semantic_output_fingerprint": semantic_manifest["combined_semantic_fingerprint"],
    }
    write_json(output_dir / "n_frontend3b_summary.json", summary)
    report = [
        "# N-FRONTEND-3B Bounded Background Routing",
        "",
        f"- Overall stop-loss pass: `{str(overall_pass).lower()}`.",
        f"- Transition-level operational-background learning-input reduction: `{summary['transition_learning_input_reduction_rate']:.6f}`.",
        f"- Micro-event-level operational-background learning-input reduction: `{summary['micro_event_learning_input_reduction_rate']:.6f}`.",
        f"- Suppressed controlled attacks: `{suppressed_attack_count}`.",
        f"- Gray contract anomalies: `{gray_count}`.",
        "",
        "These rates describe bounded learning-input row reduction, not benign",
        "classification or storage compression. Original background members remain",
        "recoverable and all audited past-only values are compared through the",
        "foreground-plus-background joint view.",
    ]
    (output_dir / "n_frontend3b_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    if not overall_pass:
        raise SystemExit("N-FRONTEND-3B stop-loss: one or more hard gates failed")
    return summary


def run_self_test(config_path: Path, output_dir: Path | None) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    config = load_config(config_path)
    # Unit fixture explicitly exercises the only suppressible family, a
    # protected semantic change, same-timestamp batching, and the gray tripwire.
    base = {
        "collector": "rrc00",
        "peer_address": "198.51.100.1",
        "peer_asn": 64500,
        "prefix": "203.0.113.0/24",
        "path_id": None,
        "old_route_signature": "route-a",
        "new_route_signature": "route-a",
        "origin_changed": False,
        "path_changed": False,
        "communities_changed": False,
        "next_hop_changed": False,
        "state_known_before": True,
        "state_known_after": True,
        "same_timestamp_ambiguous": False,
        "member_observation_count": 1,
        "source_copy_count": 1,
    }
    fixture = pd.DataFrame(
        [
            {**base, "transition_id": "t-identical-1", "transition_ts": 10.0, "transition_family": "identical_reannouncement", "member_observation_ids": ["o1"], "source_files": ["fixture://a"]},
            {**base, "transition_id": "t-identical-2", "transition_ts": 10.0, "transition_family": "identical_reannouncement", "member_observation_ids": ["o2"], "source_files": ["fixture://b"]},
            {**base, "transition_id": "t-change", "transition_ts": 20.0, "transition_family": "announcement_change", "new_route_signature": "route-b", "path_changed": True, "member_observation_ids": ["o3"], "source_files": ["fixture://c"]},
        ]
    )
    routed, fingerprint = route_transitions(fixture, config)
    assert routed.set_index("transition_id").loc["t-identical-1", "eligibility_assignment"] == ASSIGN_BACKGROUND
    assert routed.set_index("transition_id").loc["t-change", "eligibility_assignment"] == ASSIGN_FOREGROUND
    assert routed.loc[routed["transition_ts"] == 10.0, "decision_prior_ledger_fingerprint"].nunique() == 1
    assert strict_replay_audit(fixture, routed, fingerprint, config)["passed"]
    gray_probe = {**base, "transition_id": "t-gray", "transition_family": "identical_reannouncement", "member_observation_ids": [], "source_files": []}
    assert transition_decision(gray_probe, config)["eligibility_assignment"] == ASSIGN_GRAY

    with tempfile.TemporaryDirectory(prefix="n_frontend3b_self_test_") as temp:
        temp_root = Path(temp)
        source = temp_root / "n_frontend2b"
        subprocess.run(
            [
                sys.executable,
                str(repo_root / "scripts" / "run_n_frontend2b_controlled_pairs.py"),
                "--self-test",
                "--config",
                str(repo_root / "configs" / "n_frontend2b_controlled_pairs_v01.json"),
                "--output-dir",
                str(source),
                "--background-sample-rows",
                "1000",
            ],
            check=True,
            cwd=repo_root,
        )
        # The upstream 2B fixture intentionally has no recurring operational
        # background. Add one provenance-complete redundant transition and its
        # primary micro-event per variant so the end-to-end suppression route,
        # immutable member store, and denominator arithmetic are exercised.
        for pair_id, variant_role, variant_dir in discover_variants(source):
            transitions_path = variant_dir / "frontend" / "n_frontend1_transitions.parquet"
            micro_path = variant_dir / "frontend" / "n_frontend1_micro_events.parquet"
            transitions = pd.read_parquet(transitions_path)
            micro_events = pd.read_parquet(micro_path)
            seed = transitions.iloc[0].to_dict()
            sequence = sha256_json(
                {"pair_id": pair_id, "variant_role": variant_role}
            )[:12]
            ts = float(transitions["transition_ts"].max()) + 1.0
            transition_id = f"selftest-redundant-{sequence}"
            route_signature = f"selftest-route-{sequence}"
            seed.update(
                {
                    "transition_id": transition_id,
                    "transition_ts": ts,
                    "collector": "selftest-collector",
                    "peer_address": "198.51.100.254",
                    "prefix": "203.0.113.0/24",
                    "transition_family": "identical_reannouncement",
                    "old_route_signature": route_signature,
                    "new_route_signature": route_signature,
                    "origin_changed": False,
                    "path_changed": False,
                    "communities_changed": False,
                    "next_hop_changed": False,
                    "state_known_before": True,
                    "state_known_after": True,
                    "same_timestamp_ambiguous": False,
                    "member_observation_count": 1,
                    "member_observation_ids": [f"selftest-observation-{sequence}"],
                    "source_copy_count": 1,
                    "source_files": [f"fixture://n_frontend3b/{sequence}"],
                }
            )
            transitions = pd.concat([transitions, pd.DataFrame([seed])], ignore_index=True)
            event = micro_events.iloc[0].to_dict()
            window_sec = int(event["window_sec"])
            window_start = math.floor(ts / window_sec) * window_sec
            event.update(
                {
                    "micro_event_id": f"selftest-micro-{sequence}",
                    "window_start_ts": float(window_start),
                    "window_end_ts": float(window_start + window_sec),
                    "available_at_ts": float(window_start + window_sec),
                    "first_seen_ts": ts,
                    "last_seen_ts": ts,
                    "prefix": seed["prefix"],
                    "transition_family": seed["transition_family"],
                    "old_route_signature": route_signature,
                    "new_route_signature": route_signature,
                    "origin_changed": False,
                    "path_changed": False,
                    "communities_changed": False,
                    "next_hop_changed": False,
                    "same_timestamp_ambiguous": False,
                    "member_transition_count": 1,
                    "member_transition_ids": [transition_id],
                    "member_observation_count": 1,
                    "source_copy_count": 1,
                    "collector_set": [seed["collector"]],
                    "peer_address_set": [seed["peer_address"]],
                    "peer_asn_set": [str(seed["peer_asn"])],
                    "source_files": seed["source_files"],
                }
            )
            micro_events = pd.concat([micro_events, pd.DataFrame([event])], ignore_index=True)
            transitions.to_parquet(transitions_path, index=False)
            micro_events.to_parquet(micro_path, index=False)
        destination = output_dir or temp_root / "n_frontend3b"
        summary = run_experiment(source, destination, config_path, None, True, True)
        assert summary["overall_pass"]
        assert summary["suppressed_attack_count"] == 0
        assert summary["gray_count"] == 0
        assert summary["transition_operational_background_suppressed_count"] == 10
        assert summary["micro_event_operational_background_suppressed_count"] == 10
        if output_dir:
            print(json.dumps(summary, sort_keys=True))
    print("self_test=passed")


def main() -> None:
    args = parse_args()
    config_path = Path(args.config).resolve()
    if args.self_test:
        run_self_test(config_path, Path(args.output_dir).resolve() if args.output_dir else None)
        return
    if not args.n_frontend2b_root or not args.output_dir:
        raise ValueError("--n-frontend2b-root and --output-dir are required")
    summary = run_experiment(
        Path(args.n_frontend2b_root).resolve(),
        Path(args.output_dir).resolve(),
        config_path,
        Path(args.package_manifest).resolve() if args.package_manifest else None,
        args.overwrite,
        False,
    )
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
