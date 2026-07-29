#!/usr/bin/env python3
"""Materialize and replay bounded N-FRONTEND-2B paired scenarios.

The script freezes a background-only observer registry before writing any
mixed replay artifact. It reuses the canonical observation ID and the existing
N-FRONTEND-1 causal state machine. It does not suppress background, train a
model, or claim poisoning robustness.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_n_frontend1_causal_transitions import (  # noqa: E402
    discover_inputs,
    load_bounded_rows,
    load_config,
    normalize_communities,
    run_pipeline,
    text,
    write_outputs,
)
from r_mem_canonical_observation_v2 import canonical_observation_id  # noqa: E402


DEFAULT_CONFIG = Path("configs/n_frontend2b_controlled_pairs_v01.json")
TRUTH_COLUMNS = {
    "scenario_id",
    "pair_id",
    "variant_role",
    "phase_id",
    "member_id",
    "is_attack_member",
    "is_poisoning_preparation_member",
    "expected_visibility_class",
}
NO_EXPORT_ALIASES = {
    "65535:65281",
    "4294967041",
    "0xffffff01",
    "no_export",
    "no-export",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", default=[])
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--output-dir")
    parser.add_argument("--start-ts", type=float)
    parser.add_argument("--max-files", type=int, default=0)
    parser.add_argument("--max-rows", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=100_000)
    parser.add_argument("--background-sample-rows", type=int, default=100_000)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def validate_protocol_binding(
    config: dict[str, Any],
    repo_root: Path,
) -> tuple[dict[str, Any], str]:
    protocol_path = Path(config["protocol_config"])
    if not protocol_path.is_absolute():
        protocol_path = repo_root / protocol_path
    protocol = load_config(protocol_path)
    pair_status = {
        str(row["pair_id"]): str(row["materialization_status"])
        for row in protocol["pair_templates"]
    }
    missing = sorted(set(config["required_pair_ids"]) - set(pair_status))
    if missing:
        raise ValueError(f"required pairs missing from frozen protocol: {missing}")
    not_ready = sorted(
        pair_id
        for pair_id in config["required_pair_ids"]
        if pair_status[pair_id] == "design_only_needs_policy_semantics"
    )
    if not_ready:
        raise ValueError(f"design-only pairs cannot be replayed: {not_ready}")
    blocked_selected = sorted(
        set(config["required_pair_ids"]) & set(config["blocked_pair_ids"])
    )
    if blocked_selected:
        raise ValueError(f"blocked route-policy pairs selected: {blocked_selected}")
    return protocol, hashlib.sha256(protocol_path.read_bytes()).hexdigest()


def prepare_output_dir(path: Path, overwrite: bool) -> None:
    if path.exists():
        if not overwrite:
            raise FileExistsError(f"output directory exists: {path}")
        shutil.rmtree(path)
    path.mkdir(parents=True)


def observer_key(row: dict[str, Any] | pd.Series) -> tuple[str, str, str, str]:
    return (
        text(row.get("collector")) or "",
        text(row.get("peer_address")) or "",
        text(row.get("prefix")) or "",
        text(row.get("path_id")) or "",
    )


def observer_key_text(key: tuple[str, str, str, str]) -> str:
    return "|".join(key)


def has_no_export(value: Any) -> bool:
    return any(item.lower() in NO_EXPORT_ALIASES for item in normalize_communities(value))


def parse_path(value: Any) -> list[str]:
    return [
        token
        for token in (text(value) or "").replace("{", " ").replace("}", " ").split()
        if token.isdigit()
    ]


def is_documentation_asn(value: str, config: dict[str, Any]) -> bool:
    if not value.isdigit():
        return True
    number = int(value)
    return any(int(low) <= number <= int(high) for low, high in config["documentation_asn_ranges"])


def eligible_announcement(row: dict[str, Any], config: dict[str, Any]) -> bool:
    path = parse_path(row.get("as_path"))
    origin = text(row.get("origin_as"))
    return bool(
        text(row.get("type")) == "A"
        and text(row.get("peer_address"))
        and text(row.get("prefix"))
        and origin
        and path
        and path[-1] == origin
        and not any(is_documentation_asn(item, config) for item in path)
    )


def deterministic_rows(data: pd.DataFrame, limit: int) -> pd.DataFrame:
    if limit <= 0 or len(data) <= limit:
        return data.copy()
    ranked = data.assign(
        _sample_rank=data["observation_id"].map(
            lambda value: hashlib.sha256(str(value).encode("utf-8")).hexdigest()
        )
    )
    return ranked.nsmallest(limit, "_sample_rank").drop(columns="_sample_rank")


def build_template_pool(
    data: pd.DataFrame,
    episode_start: float,
    config: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], list[dict[str, Any]]]]:
    cutoff = episode_start + float(config["episode_template_cutoff_sec"])
    records = data.to_dict(orient="records")
    by_key: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    noexport_by_observer: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        by_key[observer_key(row)].append(row)
        if has_no_export(row.get("communities")):
            noexport_by_observer[
                (text(row.get("collector")) or "", text(row.get("peer_address")) or "")
            ].append(row)

    candidates: list[dict[str, Any]] = []
    for rows in by_key.values():
        rows.sort(key=lambda item: (float(item["ts"]), str(item["observation_id"])))
        early = [
            row
            for row in rows
            if float(row["ts"]) < cutoff and eligible_announcement(row, config)
        ]
        if not early:
            continue
        template = early[-1]
        later = [row for row in rows if float(row["ts"]) > float(template["ts"])]
        if later:
            continue
        candidates.append(template)
    candidates.sort(
        key=lambda row: (
            text(row.get("prefix")) or "",
            text(row.get("collector")) or "",
            text(row.get("peer_address")) or "",
        )
    )
    return candidates, noexport_by_observer


def choose_templates(
    candidates: list[dict[str, Any]],
    noexport_by_observer: dict[tuple[str, str], list[dict[str, Any]]],
    config: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    by_prefix: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        by_prefix[str(row["prefix"])].append(row)

    selected: dict[str, list[dict[str, Any]]] = {}
    used_prefixes: set[str] = set()
    pair_contracts = {row["pair_id"]: row for row in config["pair_contracts"]}

    allocation_order = sorted(
        config["required_pair_ids"],
        key=lambda pair_id: (
            -int(pair_contracts[pair_id]["required_observer_count"]),
            -int(bool(pair_contracts[pair_id]["requires_no_export_template"])),
            str(pair_id),
        ),
    )
    for pair_id in allocation_order:
        contract = pair_contracts[pair_id]
        required = int(contract["required_observer_count"])
        options: list[list[dict[str, Any]]] = []
        for prefix, rows in by_prefix.items():
            if prefix in used_prefixes:
                continue
            distinct: dict[tuple[str, str], dict[str, Any]] = {}
            for row in rows:
                distinct.setdefault(
                    (str(row["collector"]), str(row["peer_address"])), row
                )
            values = list(distinct.values())
            if len({str(row["collector"]) for row in values}) < required:
                continue
            if contract["requires_no_export_template"]:
                values.sort(
                    key=lambda row: (
                        not has_no_export(row.get("communities")),
                        str(row["collector"]),
                    )
                )
                if not has_no_export(values[0].get("communities")):
                    continue
            else:
                values.sort(key=lambda row: (str(row["collector"]), str(row["peer_address"])))
            options.append(values[:required])
        if not options:
            raise ValueError(f"no qualified real template set for {pair_id}")
        options.sort(key=lambda rows: str(rows[0]["prefix"]))
        selected[pair_id] = options[0]
        used_prefixes.add(str(options[0][0]["prefix"]))
    return selected


def choose_attacker(
    template: dict[str, Any],
    observed_asns: list[str],
    reserved: set[str],
) -> str:
    path = set(parse_path(template.get("as_path")))
    for asn in observed_asns:
        if asn not in path and asn not in reserved:
            reserved.add(asn)
            return asn
    for asn in observed_asns:
        if asn not in path:
            return asn
    raise ValueError("no observed non-documentation ASN is available as attacker")


def subprefix(prefix: str) -> str:
    network = ipaddress.ip_network(prefix, strict=False)
    if network.prefixlen >= network.max_prefixlen:
        raise ValueError(f"cannot derive subprefix from host route: {prefix}")
    return str(next(network.subnets(prefixlen_diff=1)))


def transformed_route(
    template: dict[str, Any],
    transform: str,
    attacker: str,
    observed_transit_asns: list[str],
) -> dict[str, Any]:
    result = dict(template)
    path = parse_path(template["as_path"])
    if transform in {"replace_origin", "subprefix_replace_origin"}:
        path[-1] = attacker
        result["origin_as"] = attacker
    elif transform == "insert_attacker_before_origin":
        path.insert(max(0, len(path) - 1), attacker)
        result["origin_as"] = str(template["origin_as"])
    elif transform == "insert_observed_transit":
        inserted = next(
            (
                asn
                for asn in observed_transit_asns
                if asn not in path and asn != attacker
            ),
            None,
        )
        if inserted is None:
            raise ValueError("no observed transit-role ASN is available for path manipulation")
        path.insert(max(1, len(path) - 1), inserted)
        result["origin_as"] = str(template["origin_as"])
    else:
        raise ValueError(f"unsupported transform: {transform}")
    result["as_path"] = " ".join(path)
    result["origin_provenance"] = "terminal_asn"
    if transform == "subprefix_replace_origin":
        result["prefix"] = subprefix(str(template["prefix"]))
    return result


def synthetic_row(
    template: dict[str, Any],
    route: dict[str, Any],
    ts: float,
    update_type: str,
    uri: str,
    no_export: bool,
) -> dict[str, Any]:
    row = {key: route.get(key, template.get(key)) for key in template}
    row["ts"] = float(ts)
    row["type"] = update_type
    row["source_file"] = uri
    row["archive_timestamp_utc"] = None
    row["_input_parquet"] = uri
    row["path_id"] = text(template.get("path_id"))
    if update_type == "W":
        row.update(
            {
                "as_path": None,
                "origin_as": None,
                "origin_provenance": "withdrawal",
                "communities": [],
                "next_hop": None,
            }
        )
    else:
        communities = [
            item
            for item in normalize_communities(route.get("communities"))
            if item.lower() not in NO_EXPORT_ALIASES
        ]
        if no_export:
            communities.append("65535:65281")
        row["communities"] = sorted(set(communities))
    row["observation_id"] = canonical_observation_id(row)
    if row["observation_id"] is None:
        raise ValueError(f"canonical ID unavailable for {uri}")
    return row


def phase_member(
    pair_id: str,
    variant: str,
    phase: str,
    observer_index: int,
    member_index: int,
) -> tuple[str, str]:
    member_id = f"{phase}_{observer_index:02d}_{member_index:02d}"
    uri = f"synthetic://n_frontend2/{pair_id}/{variant}/{phase}/{member_id}"
    return member_id, uri


def build_materialization_plan(
    data: pd.DataFrame,
    selected: dict[str, list[dict[str, Any]]],
    noexport_by_observer: dict[tuple[str, str], list[dict[str, Any]]],
    episode_start: float,
    config: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], list[dict[str, Any]]]]:
    observed_origins = sorted(
        {
            str(origin)
            for origin in data["origin_as"].map(text).dropna().tolist()
            if not is_documentation_asn(str(origin), config)
        },
        key=lambda value: int(value),
    )
    observed_transit_asns = sorted(
        {
            asn
            for path in data["as_path"].map(parse_path).tolist()
            for asn in path[1:-1]
            if not is_documentation_asn(asn, config)
        },
        key=lambda value: int(value),
    )
    contracts = {row["pair_id"]: row for row in config["pair_contracts"]}
    reserved_attackers: set[str] = set()
    registry: list[dict[str, Any]] = []
    rows_by_variant: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)

    for pair_id in config["required_pair_ids"]:
        contract = contracts[pair_id]
        templates = selected[pair_id]
        attacker = choose_attacker(templates[0], observed_origins, reserved_attackers)
        threat = str(contract["threat_model"])
        for observer_index, template in enumerate(templates):
            route = transformed_route(
                template,
                str(contract["transform"]),
                attacker,
                observed_transit_asns,
            )
            collector_peer = (str(template["collector"]), str(template["peer_address"]))
            donor_rows = noexport_by_observer.get(collector_peer, [])
            donor = template if has_no_export(template.get("communities")) else None
            if (
                contract["requires_no_export_template"]
                and observer_index == 0
                and donor is None
            ):
                raise ValueError(
                    f"primary visible observer lacks real NO_EXPORT template: "
                    f"{pair_id} {collector_peer}"
                )
            attack_ts = episode_start + float(config["attack_offset_sec"]) + observer_index
            recovery_ts = episode_start + float(config["recovery_offset_sec"]) + observer_index
            variants = ("clean", "adversarial")
            for variant in variants:
                expected_visible = not (
                    threat == "visibility_evasion"
                    and variant == "adversarial"
                    and observer_index > 0
                )
                expected_family = (
                    "bootstrap_announce"
                    if str(route["prefix"]) != str(template["prefix"])
                    else "announcement_change"
                )
                if threat == "detection_data_poisoning" and variant == "adversarial":
                    expected_family = "withdraw_reannounce_same"
                role = (
                    "paired_attack_observer"
                    if expected_visible
                    else "control_observer"
                )
                ordered = ["stable_L"]
                if threat == "detection_data_poisoning" and variant == "adversarial":
                    ordered += ["poison_P", "withdraw_P"]
                ordered += ["attack_P", "recovery_L"]
                registry_row = {
                    "pair_id": pair_id,
                    "variant_role": variant,
                    "family": contract["family"],
                    "threat_model": threat,
                    "observer_key": observer_key_text(observer_key(template)),
                    "collector": template["collector"],
                    "peer_address": template["peer_address"],
                    "template_prefix": template["prefix"],
                    "prefix": route["prefix"],
                    "path_id": text(template.get("path_id")),
                    "observer_role": role,
                    "ordered_state_sequence": ordered,
                    "intermediate_background_class": "no_legitimate_restore",
                    "expected_attack_transition_family_set": [expected_family],
                    "template_observation_id": template["observation_id"],
                    "template_source_file": template["source_file"],
                    "template_ts": float(template["ts"]),
                    "template_as_path": template["as_path"],
                    "template_origin_as": template["origin_as"],
                    "template_communities": normalize_communities(
                        template.get("communities")
                    ),
                    "no_export_template_observation_id": donor["observation_id"] if donor else None,
                    "attacker_as": attacker,
                    "legitimate_origin_as": template["origin_as"],
                    "attack_origin_as": route["origin_as"],
                    "attack_as_path": route["as_path"],
                    "attack_communities_clean": [
                        item
                        for item in normalize_communities(route.get("communities"))
                        if item.lower() not in NO_EXPORT_ALIASES
                    ],
                    "attack_ts": attack_ts,
                    "recovery_ts": recovery_ts,
                    "expected_visible": expected_visible,
                    "exclusion_reason": None,
                }
                registry.append(registry_row)

                if not expected_visible:
                    rows_by_variant[(pair_id, variant)].append(
                        {
                            "_truth_only": True,
                            "pair_id": pair_id,
                            "variant_role": variant,
                            "phase_id": "attack_launch",
                            "observer_index": observer_index,
                            "expected_visible": False,
                            "template": template,
                            "route": route,
                            "attack_ts": attack_ts,
                            "family": contract["family"],
                            "threat_model": threat,
                        }
                    )
                    continue

                phases: list[tuple[str, float, str, bool, bool]] = []
                if threat == "detection_data_poisoning" and variant == "adversarial":
                    phases.extend(
                        [
                            (
                                "poisoning_preparation",
                                episode_start + float(config["poison_announce_offset_sec"]) + observer_index,
                                "A",
                                False,
                                True,
                            ),
                            (
                                "poisoning_preparation",
                                episode_start + float(config["poison_withdraw_offset_sec"]) + observer_index,
                                "W",
                                False,
                                True,
                            ),
                        ]
                    )
                phases.extend(
                    [
                        ("attack_launch", attack_ts, "A", True, False),
                        ("recovery", recovery_ts, "A", False, False),
                    ]
                )
                for member_index, (phase, ts, update_type, attack, poison) in enumerate(phases):
                    member_id, uri = phase_member(
                        pair_id, variant, phase, observer_index, member_index
                    )
                    active_route = template if phase == "recovery" else route
                    no_export = bool(
                        threat == "visibility_evasion"
                        and variant == "adversarial"
                        and phase == "attack_launch"
                    )
                    row = synthetic_row(
                        template, active_route, ts, update_type, uri, no_export
                    )
                    rows_by_variant[(pair_id, variant)].append(
                        {
                            "canonical_row": row,
                            "pair_id": pair_id,
                            "scenario_id": f"{pair_id}__{variant}",
                            "variant_role": variant,
                            "phase_id": phase,
                            "member_id": member_id,
                            "template_observation_id": template["observation_id"],
                            "template_source_file": template["source_file"],
                            "synthetic_source_uri": uri,
                            "is_attack_member": attack,
                            "is_poisoning_preparation_member": poison,
                            "expected_visibility_class": (
                                "partial_public_visible"
                                if threat == "visibility_evasion" and variant == "adversarial"
                                else "public_visible"
                            ),
                            "expected_visible": True,
                            "collector": template["collector"],
                            "peer_address": template["peer_address"],
                            "family": contract["family"],
                            "threat_model": threat,
                        }
                    )
    return registry, rows_by_variant


def build_background_cadence_audit(
    data: pd.DataFrame,
    registry: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    records = data.to_dict(orient="records")
    by_observer: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        by_observer[observer_key(row)].append(row)

    audit_rows: list[dict[str, Any]] = []
    for row in registry:
        key = (
            str(row["collector"]),
            str(row["peer_address"]),
            str(row["template_prefix"]),
            text(row.get("path_id")) or "",
        )
        observations = sorted(
            by_observer.get(key, []),
            key=lambda item: (float(item["ts"]), str(item["observation_id"])),
        )
        template_id = str(row["template_observation_id"])
        template_matches = [
            item for item in observations if str(item["observation_id"]) == template_id
        ]
        if len(template_matches) != 1:
            raise ValueError(
                f"template identity is not unique in background cadence audit: {template_id}"
            )
        template_ts = float(template_matches[0]["ts"])
        later = [item for item in observations if float(item["ts"]) > template_ts]
        classification = (
            "no_legitimate_restore"
            if not later
            else "unstable_flap_or_ambiguity"
        )
        if classification != str(row["intermediate_background_class"]):
            raise ValueError(
                "background cadence classification diverged from frozen registry plan: "
                f"{row['pair_id']} {row['variant_role']} {row['observer_key']}"
            )
        audit_rows.append(
            {
                "pair_id": row["pair_id"],
                "variant_role": row["variant_role"],
                "observer_key": row["observer_key"],
                "collector": row["collector"],
                "peer_address": row["peer_address"],
                "template_prefix": row["template_prefix"],
                "template_observation_id": template_id,
                "template_ts": template_ts,
                "attack_ts": float(row["attack_ts"]),
                "background_observation_count": len(observations),
                "post_template_background_count": len(later),
                "intermediate_background_class": classification,
                "evidence_scope": "background_only_before_materialization",
                "excluded_from_family_delta": bool(
                    row["observer_role"] == "excluded_observer"
                ),
            }
        )
    return audit_rows


def freeze_registry(
    output_dir: Path,
    registry: list[dict[str, Any]],
    cadence_audit: list[dict[str, Any]],
) -> str:
    registry_path = output_dir / "n_frontend2b_observer_registry.json"
    cadence_path = output_dir / "n_frontend2b_background_cadence_audit.json"
    write_json(registry_path, registry)
    write_json(cadence_path, cadence_audit)
    freeze = {
        "registry_sha256": hashlib.sha256(registry_path.read_bytes()).hexdigest(),
        "cadence_audit_sha256": hashlib.sha256(cadence_path.read_bytes()).hexdigest(),
        "registry_row_count": len(registry),
        "status": "frozen_before_replay",
    }
    freeze["freeze_fingerprint"] = sha256_json(freeze)
    write_json(output_dir / "n_frontend2b_registry_freeze.json", freeze)
    return freeze["freeze_fingerprint"]


def verify_registry_freeze(output_dir: Path, expected_fingerprint: str) -> None:
    freeze = json.loads(
        (output_dir / "n_frontend2b_registry_freeze.json").read_text(encoding="utf-8")
    )
    registry_path = output_dir / "n_frontend2b_observer_registry.json"
    cadence_path = output_dir / "n_frontend2b_background_cadence_audit.json"
    if hashlib.sha256(registry_path.read_bytes()).hexdigest() != freeze["registry_sha256"]:
        raise ValueError("observer registry changed after freeze")
    if hashlib.sha256(cadence_path.read_bytes()).hexdigest() != freeze["cadence_audit_sha256"]:
        raise ValueError("cadence audit changed after freeze")
    check = dict(freeze)
    fingerprint = check.pop("freeze_fingerprint")
    if sha256_json(check) != fingerprint or fingerprint != expected_fingerprint:
        raise ValueError("registry freeze fingerprint mismatch")


def truth_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items:
        if item.get("_truth_only"):
            member_id, uri = phase_member(
                item["pair_id"],
                item["variant_role"],
                item["phase_id"],
                int(item["observer_index"]),
                0,
            )
            rows.append(
                {
                    "observation_id": None,
                    "scenario_id": f"{item['pair_id']}__{item['variant_role']}",
                    "pair_id": item["pair_id"],
                    "variant_role": item["variant_role"],
                    "phase_id": item["phase_id"],
                    "member_id": member_id,
                    "template_observation_id": item["template"]["observation_id"],
                    "template_source_file": item["template"]["source_file"],
                    "synthetic_source_uri": uri,
                    "is_attack_member": True,
                    "is_poisoning_preparation_member": False,
                    "expected_visibility_class": "public_invisible_by_contract",
                    "expected_visible": False,
                    "collector": item["template"]["collector"],
                    "peer_address": item["template"]["peer_address"],
                    "family": item["family"],
                    "threat_model": item["threat_model"],
                }
            )
            continue
        row = {key: value for key, value in item.items() if key != "canonical_row"}
        row["observation_id"] = item["canonical_row"]["observation_id"]
        rows.append(row)
    return rows


def lineage_rows(
    truth: list[dict[str, Any]],
    unique_rows: list[dict[str, Any]],
    transitions: list[dict[str, Any]],
    micro_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    unique_ids = {text(row.get("observation_id")) for row in unique_rows}
    transition_by_observation: dict[str, str] = {}
    transition_family_by_observation: dict[str, str] = {}
    for transition in transitions:
        for observation_id in transition["member_observation_ids"]:
            transition_by_observation[observation_id] = transition["transition_id"]
            transition_family_by_observation[observation_id] = transition["transition_family"]
    micro_by_transition: dict[str, str] = {}
    for event in micro_events:
        for transition_id in event["member_transition_ids"]:
            micro_by_transition[transition_id] = event["micro_event_id"]
    result: list[dict[str, Any]] = []
    for row in truth:
        observation_id = row["observation_id"]
        transition_id = transition_by_observation.get(observation_id)
        expected_visible = bool(row["expected_visible"])
        result.append(
            {
                **row,
                "canonical_survived": bool(observation_id in unique_ids) if expected_visible else None,
                "transition_id": transition_id,
                "transition_family": transition_family_by_observation.get(observation_id),
                "micro_event_id": micro_by_transition.get(transition_id),
                "semantic_survived": (
                    bool(
                        observation_id in unique_ids
                        and transition_id
                        and micro_by_transition.get(transition_id)
                    )
                    if expected_visible
                    else None
                ),
                "observability_boundary": not expected_visible,
            }
        )
    return result


def exposure_rows(
    lineage: list[dict[str, Any]],
    transitions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    transition_by_id = {row["transition_id"]: row for row in transitions}
    truth_by_observation = {
        row["observation_id"]: row for row in lineage if row["observation_id"]
    }
    result: list[dict[str, Any]] = []
    for attack in lineage:
        if not attack["is_attack_member"] or not attack["expected_visible"]:
            continue
        current = transition_by_id[attack["transition_id"]]
        signature = current["new_route_signature"]
        attack_ts = float(current["transition_ts"])
        prior = [
            row
            for row in transitions
            if row["new_route_signature"] == signature
            and float(row["transition_ts"]) < attack_ts
        ]
        if any(float(row["transition_ts"]) >= attack_ts for row in prior):
            raise AssertionError("past-only exposure includes current/future transition")
        prior_ids = [
            observation_id
            for row in prior
            for observation_id in row["member_observation_ids"]
        ]
        prior_truth = [
            truth_by_observation[observation_id]
            for observation_id in prior_ids
            if observation_id in truth_by_observation
        ]
        result.append(
            {
                "pair_id": attack["pair_id"],
                "variant_role": attack["variant_role"],
                "collector": attack["collector"],
                "peer_address": attack["peer_address"],
                "attack_observation_id": attack["observation_id"],
                "attack_ts": attack_ts,
                "route_signature": signature,
                "previously_exposed": bool(prior),
                "prior_exposure_count": len(prior),
                "first_seen_age_sec": (
                    attack_ts - min(float(row["transition_ts"]) for row in prior)
                    if prior
                    else None
                ),
                "last_seen_gap_sec": (
                    attack_ts - max(float(row["transition_ts"]) for row in prior)
                    if prior
                    else None
                ),
                "distinct_prior_peer_count": len(
                    {row["peer_address"] for row in prior}
                ),
                "distinct_prior_collector_count": len(
                    {row["collector"] for row in prior}
                ),
                "exposure_only_in_poisoning_preparation": bool(prior)
                and bool(prior_truth)
                and all(
                    row["is_poisoning_preparation_member"] for row in prior_truth
                ),
                "maximum_contributing_transition_ts": (
                    max(float(row["transition_ts"]) for row in prior)
                    if prior
                    else None
                ),
                "causality_valid": all(
                    float(row["transition_ts"]) < attack_ts for row in prior
                ),
                "bounded_proxy": True,
            }
        )
    return result


def pair_fairness_rows(
    registry: list[dict[str, Any]],
    required_pair_ids: list[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    stable_fields = [
        "family",
        "threat_model",
        "collector",
        "peer_address",
        "prefix",
        "path_id",
        "template_observation_id",
        "attacker_as",
        "legitimate_origin_as",
        "attack_origin_as",
        "attack_as_path",
        "attack_ts",
        "recovery_ts",
    ]
    for pair_id in required_pair_ids:
        clean = {
            (row["collector"], row["peer_address"]): row
            for row in registry
            if row["pair_id"] == pair_id and row["variant_role"] == "clean"
        }
        adversarial = {
            (row["collector"], row["peer_address"]): row
            for row in registry
            if row["pair_id"] == pair_id and row["variant_role"] == "adversarial"
        }
        common = sorted(set(clean) & set(adversarial))
        mismatches = sorted(
            {
                field
                for key in common
                for field in stable_fields
                if clean[key].get(field) != adversarial[key].get(field)
            }
        )
        observer_universe_same = set(clean) == set(adversarial)
        rows.append(
            {
                "pair_id": pair_id,
                "observer_universe_same": observer_universe_same,
                "stable_field_mismatch_count": len(mismatches),
                "stable_field_mismatches": "|".join(mismatches),
                "visibility_difference_preregistered": (
                    clean[common[0]]["threat_model"] == "visibility_evasion"
                    if common
                    else False
                ),
                "background_same": True,
                "passed": observer_universe_same and not mismatches,
            }
        )
    return rows


def run_variant(
    output_dir: Path,
    background: pd.DataFrame,
    items: list[dict[str, Any]],
    frontend_config: dict[str, Any],
    load_meta: dict[str, Any],
) -> dict[str, Any]:
    canonical_items = [item["canonical_row"] for item in items if "canonical_row" in item]
    background_ids = set(background["observation_id"].astype(str))
    synthetic_ids = [str(row["observation_id"]) for row in canonical_items]
    collisions = sorted(background_ids & set(synthetic_ids))
    duplicate_synthetic = len(synthetic_ids) - len(set(synthetic_ids))
    if collisions or duplicate_synthetic:
        raise ValueError(
            f"identity gate failed: collisions={len(collisions)}, "
            f"synthetic_duplicates={duplicate_synthetic}"
        )
    mixed = pd.concat(
        [background, pd.DataFrame(canonical_items)], ignore_index=True, sort=False
    )
    leaked = sorted(TRUTH_COLUMNS & set(mixed.columns))
    if leaked:
        raise ValueError(f"truth leaked into canonical frame: {leaked}")
    mixed = mixed.sort_values(
        ["ts", "collector", "peer_address", "prefix", "observation_id"],
        kind="mergesort",
    ).reset_index(drop=True)
    output_dir.mkdir(parents=True)
    mixed.to_parquet(output_dir / "evaluation_only_mixed_canonical.parquet", index=False)
    replay_load_meta = {
        "input_file_count": int(load_meta.get("input_file_count", 0)),
        "input_files": list(load_meta.get("input_files", [])),
        "source_rows_scanned": int(load_meta.get("source_rows_scanned", len(mixed))),
        "source_rows_scanned_by_file": dict(
            load_meta.get("source_rows_scanned_by_file", {"bounded_replay": len(mixed)})
        ),
        "selected_rows_by_collector": {
            str(key): int(value)
            for key, value in mixed["collector"].value_counts().items()
        },
        "required_collectors": [],
        "missing_required_collectors": [],
        "observed_collectors": sorted(
            str(value) for value in mixed["collector"].dropna().unique().tolist()
        ),
        "observed_projects": sorted(
            str(value) for value in mixed["project"].dropna().unique().tolist()
        ),
        "selected_rows": len(mixed),
        "selected_ts_min": float(mixed["ts"].min()),
        "selected_ts_max": float(mixed["ts"].max()),
        "path_id_column": load_meta.get("path_id_column"),
        "path_id_non_null_rows": int(mixed["path_id"].notna().sum()),
        "path_id_field_present": bool(load_meta.get("path_id_field_present", False)),
        "add_path_support_ready": False,
        "selection_truncated_by_max_rows": bool(
            load_meta.get("selection_truncated_by_max_rows", False)
        ),
        "selection_truncated_by_per_collector_cap": False,
        "state_identity_missing_row_count": int(
            (
                mixed["peer_address"].map(text).isna()
                | mixed["prefix"].map(text).isna()
            ).sum()
        ),
    }
    unique, dedup, transitions, micro_by_window, summary = run_pipeline(
        mixed,
        frontend_config,
        replay_load_meta,
    )
    frontend_output_dir = output_dir / "frontend"
    frontend_output_dir.mkdir(parents=True)
    write_outputs(frontend_output_dir, unique, dedup, transitions, micro_by_window, summary)
    truth = truth_rows(items)
    pd.DataFrame(truth).to_csv(output_dir / "truth_provenance_sidecar.csv", index=False)
    primary_window = int(frontend_config["primary_micro_event_window_sec"])
    lineage = lineage_rows(truth, unique, transitions, micro_by_window[primary_window])
    pd.DataFrame(lineage).to_csv(output_dir / "phase_survival_lineage.csv", index=False)
    exposure = exposure_rows(lineage, transitions)
    pd.DataFrame(exposure).to_csv(output_dir / "past_only_route_exposure.csv", index=False)
    return {
        "summary": summary,
        "truth": truth,
        "lineage": lineage,
        "exposure": exposure,
        "transitions": transitions,
        "identity_audit": {
            "background_injected_collision_count": len(collisions),
            "duplicate_synthetic_observation_count": duplicate_synthetic,
            "unresolved_canonical_id_count": sum(not value for value in synthetic_ids),
            "truth_column_leak_count": len(leaked),
            "passed": not collisions and duplicate_synthetic == 0 and not leaked,
        },
    }


def self_test_background() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    start = 1_720_000_000.0
    specs = [
        ("rrc00", "198.51.100.1", "8.8.0.0/16", "3356 15169", []),
        ("rrc00", "198.51.100.2", "1.1.1.0/24", "1299 2914 13335", []),
        ("rrc00", "198.51.100.3", "9.9.9.0/24", "2914 1299 19281", []),
        ("rrc00", "198.51.100.4", "4.2.2.0/24", "6453 174 3356", ["65535:65281"]),
        ("route-views.sg", "203.0.113.4", "4.2.2.0/24", "3491 3356", []),
        ("rrc00", "198.51.100.5", "208.67.222.0/24", "174 36692", ["65535:65281"]),
        ("route-views.sg", "203.0.113.5", "208.67.222.0/24", "6939 36692", []),
    ]
    for index, (collector, peer, prefix, path, communities) in enumerate(specs):
        origin = path.split()[-1]
        row = {
            "ts": start + 60 + index,
            "collector": collector,
            "project": "ris" if collector == "rrc00" else "routeviews",
            "type": "A",
            "peer_asn": int(path.split()[0]),
            "peer_address": peer,
            "prefix": prefix,
            "as_path": path,
            "origin_as": origin,
            "origin_provenance": "terminal_asn",
            "communities": communities,
            "next_hop": peer,
            "source_file": f"fixture://{collector}/{index}",
            "archive_timestamp_utc": "2024-07-05T00:00:00Z",
            "_input_parquet": f"fixture://{collector}",
            "path_id": None,
        }
        row["observation_id"] = canonical_observation_id(row)
        rows.append(row)
    return pd.DataFrame(rows)


def main() -> None:
    args = parse_args()
    config_path = Path(args.config)
    config = load_config(config_path)
    repo_root = config_path.resolve().parent.parent
    frontend_config_path = Path(config["frontend_config"])
    if not frontend_config_path.is_absolute():
        frontend_config_path = repo_root / frontend_config_path
    frontend_config = load_config(frontend_config_path)
    _, protocol_fingerprint = validate_protocol_binding(config, repo_root)
    if args.self_test:
        data = self_test_background()
        episode_start = float(data["ts"].min()) - 60.0
        output_dir = Path(args.output_dir) if args.output_dir else Path("_n_frontend2b_self_test")
        load_meta = {
            "input_file_count": 0,
            "input_files": ["self_test_fixture"],
            "source_rows_scanned": len(data),
            "observed_collectors": sorted(data["collector"].unique().tolist()),
        }
    else:
        if not args.input or args.start_ts is None or not args.output_dir:
            raise ValueError("--input, --start-ts, and --output-dir are required")
        episode_start = float(args.start_ts)
        episode_end = episode_start + float(config["episode_duration_sec"])
        files = discover_inputs(args.input, args.max_files)
        data, load_meta = load_bounded_rows(
            files,
            frontend_config,
            episode_start,
            episode_end,
            args.max_rows,
            0,
            [],
            args.batch_size,
        )
        output_dir = Path(args.output_dir)

    prepare_output_dir(output_dir, args.overwrite)
    episode_end = episode_start + float(config["episode_duration_sec"])
    if float(data["ts"].min()) < episode_start or float(data["ts"].max()) >= episode_end:
        raise ValueError("loaded background falls outside the frozen episode")

    candidates, noexport_by_observer = build_template_pool(data, episode_start, config)
    selected = choose_templates(candidates, noexport_by_observer, config)
    registry, rows_by_variant = build_materialization_plan(
        data, selected, noexport_by_observer, episode_start, config
    )
    selected_keys = {
        observer_key(row)
        for rows in selected.values()
        for row in rows
    }
    relevant = data[
        data.apply(lambda row: observer_key(row) in selected_keys, axis=1)
    ]
    sampled = deterministic_rows(data, int(args.background_sample_rows))
    background = (
        pd.concat([sampled, relevant], ignore_index=True)
        .drop_duplicates(subset=["observation_id"])
        .sort_values(["ts", "collector", "peer_address", "prefix", "observation_id"])
        .reset_index(drop=True)
    )
    background_manifest = {
        "episode_start_ts": episode_start,
        "episode_end_ts": episode_end,
        "source_row_count": len(data),
        "replay_background_row_count": len(background),
        "selected_template_observation_ids": sorted(
            str(row["observation_id"]) for rows in selected.values() for row in rows
        ),
        "input_files": load_meta.get("input_files", []),
        "input_manifest_fingerprint": sha256_json(load_meta.get("input_files", [])),
        "background_only": True,
        "cadence_classification_counts": {
            "no_legitimate_restore": len(registry),
            "legitimate_restore": 0,
            "unstable_flap_or_ambiguity": 0,
        },
    }
    write_json(output_dir / "n_frontend2b_background_input_manifest.json", background_manifest)
    cadence_audit = build_background_cadence_audit(data, registry)
    freeze_fingerprint = freeze_registry(output_dir, registry, cadence_audit)
    verify_registry_freeze(output_dir, freeze_fingerprint)
    synthetic_manifest_rows = [
        {
            "pair_id": pair_id,
            "variant_role": variant,
            "observation_id": item["canonical_row"]["observation_id"],
            "synthetic_source_uri": item["synthetic_source_uri"],
            "collector": item["collector"],
            "peer_address": item["peer_address"],
            "phase_id": item["phase_id"],
            "type": item["canonical_row"]["type"],
            "ts": item["canonical_row"]["ts"],
        }
        for (pair_id, variant), items in rows_by_variant.items()
        for item in items
        if "canonical_row" in item
    ]
    pd.DataFrame(synthetic_manifest_rows).to_csv(
        output_dir / "n_frontend2b_synthetic_observation_manifest.csv",
        index=False,
    )

    results: dict[tuple[str, str], dict[str, Any]] = {}
    identity_rows: list[dict[str, Any]] = []
    all_lineage: list[dict[str, Any]] = []
    all_exposure: list[dict[str, Any]] = []
    all_truth: list[dict[str, Any]] = []
    for pair_id in config["required_pair_ids"]:
        for variant in ("clean", "adversarial"):
            verify_registry_freeze(output_dir, freeze_fingerprint)
            variant_dir = output_dir / "evaluation_only" / pair_id / variant
            result = run_variant(
                variant_dir,
                background,
                rows_by_variant[(pair_id, variant)],
                frontend_config,
                load_meta,
            )
            results[(pair_id, variant)] = result
            identity_rows.append(
                {
                    "pair_id": pair_id,
                    "variant_role": variant,
                    **result["identity_audit"],
                }
            )
            all_lineage.extend(result["lineage"])
            all_exposure.extend(result["exposure"])
            all_truth.extend(result["truth"])

    registry_index = {
        (
            row["pair_id"],
            row["variant_role"],
            row["collector"],
            row["peer_address"],
        ): row
        for row in registry
    }
    delta_rows: list[dict[str, Any]] = []
    for row in all_lineage:
        if not row["is_attack_member"] or not row["expected_visible"]:
            continue
        key = (row["pair_id"], row["variant_role"], row["collector"], row["peer_address"])
        expected = registry_index[key]["expected_attack_transition_family_set"]
        delta_rows.append(
            {
                "pair_id": row["pair_id"],
                "variant_role": row["variant_role"],
                "collector": row["collector"],
                "peer_address": row["peer_address"],
                "observed_attack_transition_family": row["transition_family"],
                "expected_attack_transition_family_set": "|".join(expected),
                "family_expectation_matched": row["transition_family"] in expected,
                "observer_role": registry_index[key]["observer_role"],
            }
        )

    visibility_rows = [
        {
            "pair_id": row["pair_id"],
            "variant_role": row["variant_role"],
            "collector": row["collector"],
            "peer_address": row["peer_address"],
            "expected_visible": row["expected_visible"],
            "observed": bool(row["observation_id"]),
            "observability_boundary": not row["expected_visible"],
            "contract_satisfied": bool(row["observation_id"]) == bool(row["expected_visible"]),
        }
        for row in all_lineage
        if row["is_attack_member"]
    ]
    survival_pass = all(
        bool(row["semantic_survived"])
        for row in all_lineage
        if row["expected_visible"]
    )
    family_pass = all(row["family_expectation_matched"] for row in delta_rows)
    identity_pass = all(row["passed"] for row in identity_rows)
    visibility_pass = all(row["contract_satisfied"] for row in visibility_rows)
    causality_pass = all(row["causality_valid"] for row in all_exposure)
    ambiguity_pass = not any(
        row["transition_family"] == "same_timestamp_ambiguous"
        for row in all_lineage
        if row["expected_visible"]
    )
    fairness_rows = pair_fairness_rows(registry, config["required_pair_ids"])
    fairness_pass = all(row["passed"] for row in fairness_rows)
    overall_pass = all(
        [
            survival_pass,
            family_pass,
            identity_pass,
            visibility_pass,
            causality_pass,
            ambiguity_pass,
            fairness_pass,
        ]
    )

    pd.DataFrame(all_truth).to_csv(
        output_dir / "n_frontend2b_truth_provenance_sidecar.csv", index=False
    )
    pd.DataFrame(identity_rows).to_csv(
        output_dir / "n_frontend2b_identity_duplicate_audit.csv", index=False
    )
    pd.DataFrame(all_lineage).to_csv(
        output_dir / "n_frontend2b_phase_survival_lineage.csv", index=False
    )
    pd.DataFrame(all_exposure).to_csv(
        output_dir / "n_frontend2b_past_only_route_exposure.csv", index=False
    )
    pd.DataFrame(delta_rows).to_csv(
        output_dir / "n_frontend2b_attack_transition_semantic_delta.csv", index=False
    )
    pd.DataFrame(visibility_rows).to_csv(
        output_dir / "n_frontend2b_visibility_contract_audit.csv", index=False
    )
    pd.DataFrame(
        [
            {
                "stage": "canonical_observation",
                "expected_visible_count": sum(
                    bool(row["expected_visible"]) for row in all_lineage
                ),
                "lost_count": sum(
                    bool(row["expected_visible"]) and not bool(row["canonical_survived"])
                    for row in all_lineage
                ),
            },
            {
                "stage": "causal_transition",
                "expected_visible_count": sum(
                    bool(row["expected_visible"]) for row in all_lineage
                ),
                "lost_count": sum(
                    bool(row["expected_visible"]) and not bool(row["transition_id"])
                    for row in all_lineage
                ),
            },
            {
                "stage": "micro_event",
                "expected_visible_count": sum(
                    bool(row["expected_visible"]) for row in all_lineage
                ),
                "lost_count": sum(
                    bool(row["expected_visible"]) and not bool(row["micro_event_id"])
                    for row in all_lineage
                ),
            },
        ]
    ).to_csv(output_dir / "n_frontend2b_drop_localization.csv", index=False)
    pd.DataFrame(
        [
            {
                "undeclared_same_timestamp_ambiguity_count": sum(
                    row["transition_family"] == "same_timestamp_ambiguous"
                    for row in all_lineage
                    if row["expected_visible"]
                ),
                "passed": ambiguity_pass,
            }
        ]
    ).to_csv(output_dir / "n_frontend2b_ambiguity_intersection_audit.csv", index=False)
    pd.DataFrame(fairness_rows).to_csv(
        output_dir / "n_frontend2b_pair_fairness_audit.csv", index=False
    )

    summary = {
        "phase": config["phase"],
        "config_version": config["config_version"],
        "registry_freeze_fingerprint": freeze_fingerprint,
        "protocol_config_sha256": protocol_fingerprint,
        "registry_frozen_before_replay": True,
        "pair_count": len(config["required_pair_ids"]),
        "variant_count": len(results),
        "source_background_row_count": len(data),
        "replay_background_row_count": len(background),
        "expected_visible_member_count": sum(
            bool(row["expected_visible"]) for row in all_lineage
        ),
        "observability_boundary_member_count": sum(
            not bool(row["expected_visible"]) for row in all_lineage
        ),
        "semantic_phase_survival_pass": survival_pass,
        "past_only_causality_pass": causality_pass,
        "attack_transition_semantic_delta_pass": family_pass,
        "identity_and_duplicate_gate_pass": identity_pass,
        "visibility_contract_pass": visibility_pass,
        "ambiguity_contract_pass": ambiguity_pass,
        "pair_fairness_pass": fairness_pass,
        "overall_pass": overall_pass,
        "allowed_claim": config["allowed_claim"],
        "forbidden_claims": config["forbidden_claims"],
        "route_leak_status": "blocked_diagnostic_only",
        "learning_trained": False,
        "background_suppression_performed": False,
    }
    write_json(output_dir / "n_frontend2b_summary.json", summary)
    report = [
        "# N-FRONTEND-2B Bounded Replay",
        "",
        f"- Overall structural QA pass: `{str(overall_pass).lower()}`.",
        f"- Paired variants: `{len(results)}`.",
        f"- Expected-visible members: `{summary['expected_visible_member_count']}`.",
        f"- Observability-boundary members: `{summary['observability_boundary_member_count']}`.",
        f"- Allowed claim: `{config['allowed_claim']}`.",
        "",
        "This replay validates structural semantic survival and strictly past-only",
        "route exposure inside a bounded episode. It does not validate poisoning",
        "robustness, detection accuracy, background suppression, or learning.",
        "NO_EXPORT remains propagation-control evidence rather than attack truth.",
    ]
    (output_dir / "n_frontend2b_report.md").write_text(
        "\n".join(report) + "\n", encoding="utf-8"
    )
    if not overall_pass:
        raise SystemExit("N-FRONTEND-2B stop-loss: one or more hard gates failed")
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
