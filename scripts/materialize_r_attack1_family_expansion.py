#!/usr/bin/env python3
"""Materialize bounded R-ATTACK-1 family-expansion scenarios.

R-ATTACK-1 adds subprefix and monitor-visible NO_EXPORT/stealth cases after
R-FOREGROUND-3. It keeps attack truth in sidecars and writes raw updates in the
same format as the background run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

import pandas as pd

from build_r_asrel_clean0_sidecar import (
    diagnose_path,
    load_asrel_lookup as load_diagnostic_asrel_lookup,
)
from materialize_r_attack0a_origin_smoke import (
    RAW_COLUMNS,
    clean_path,
    find_target_chunk,
    parse_path,
    parse_utc,
    raw_files,
    rel_path,
    sha256_file,
)


DOCUMENTATION_ASN_RANGES = ((64496, 64511), (65536, 65551))
NO_EXPORT_TOKENS = {"65535:65281", "4294967041", "0xffffff01", "no_export", "no-export"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/r_attack1_family_expansion_v01.json")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--source-run-root", default="")
    parser.add_argument("--derived-run-root", default="")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def is_documentation_asn(asn: int) -> bool:
    return any(start <= asn <= end for start, end in DOCUMENTATION_ASN_RANGES)


def parse_path_text(value: Any) -> str:
    return " ".join(str(asn) for asn in clean_path(parse_path(value)))


def community_fingerprint(value: Any) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]


def has_no_export_community(value: Any) -> bool:
    text = str(value).lower()
    return any(token in text for token in NO_EXPORT_TOKENS)


def load_templates(files: list[Path], prefixes: set[str]) -> pd.DataFrame:
    rows = []
    for path in files:
        frame = pd.read_parquet(path, columns=RAW_COLUMNS)
        selected = frame[
            frame["prefix"].astype(str).isin(prefixes)
            & frame["type"].astype(str).str.upper().eq("A")
            & frame["as_path"].notna()
        ].copy()
        if selected.empty:
            continue
        selected["_source_path"] = str(path.resolve())
        selected["_path_clean"] = selected["as_path"].map(parse_path_text)
        selected["_has_no_export"] = selected["communities"].map(has_no_export_community)
        selected["_community_fp"] = selected["communities"].map(community_fingerprint)
        rows.append(selected)
    if not rows:
        raise ValueError("no raw templates found for configured source prefixes")
    return pd.concat(rows, ignore_index=True)


def load_observed_asns(repo_root: Path, source_run_id: str, files: list[Path]) -> set[int]:
    events = repo_root / "data" / "runs" / source_run_id / "events" / "event_units.parquet"
    observed: set[int] = set()
    if events.exists():
        frame = pd.read_parquet(events, columns=["origin_as", "as_path_clean"])
        observed.update(
            int(value)
            for value in pd.to_numeric(frame["origin_as"], errors="coerce").dropna().astype(int)
        )
        for value in frame["as_path_clean"].dropna().astype(str):
            observed.update(clean_path(parse_path(value)))
        return observed
    for path in files:
        frame = pd.read_parquet(path, columns=["as_path"])
        for value in frame["as_path"].dropna().astype(str):
            observed.update(clean_path(parse_path(value)))
    return observed


def select_template(
    templates: pd.DataFrame,
    prefix: str,
    collector: str,
    origin_as: int,
    target_ts: float,
    require_no_export: bool = False,
) -> pd.Series:
    subset = templates[
        templates["prefix"].astype(str).eq(prefix)
        & templates["collector"].astype(str).eq(collector)
    ].copy()
    subset = subset[
        subset["_path_clean"].map(
            lambda value: bool(parse_path(value)) and parse_path(value)[-1] == origin_as
        )
    ].copy()
    if require_no_export:
        subset = subset[subset["_has_no_export"]].copy()
    if subset.empty:
        raise ValueError(
            f"no observed template: prefix={prefix}, collector={collector}, "
            f"origin={origin_as}, require_no_export={require_no_export}"
        )
    subset["_distance"] = (pd.to_numeric(subset["ts"], errors="coerce") - target_ts).abs()
    return subset.sort_values(["_distance", "ts", "_path_clean"]).iloc[0]


def build_asrel_indexes(
    lookup: dict[tuple[str, str], dict[str, str]]
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    out_index: dict[str, set[str]] = {}
    in_index: dict[str, set[str]] = {}
    for left, right in lookup:
        out_index.setdefault(left, set()).add(right)
        in_index.setdefault(right, set()).add(left)
    return out_index, in_index


def diagnostic_matches(diagnostic: dict[str, Any], allowed: list[str]) -> bool:
    if not allowed:
        return True
    return str(diagnostic["path_relation_diagnostic_2024"]) in set(map(str, allowed))


def select_dynamic_replacement_origin(
    observed_path: list[int],
    allowed_diagnostics: list[str],
    observed_asns: set[int],
    lookup: dict[tuple[str, str], dict[str, str]],
    out_index: dict[str, set[str]],
    max_candidates: int,
) -> tuple[list[int], list[tuple[int, int]], int, dict[str, Any]]:
    path = clean_path(observed_path)
    if len(path) < 2:
        raise ValueError(f"path too short for replacement origin: {path}")
    left = str(path[-2])
    candidates = sorted(
        int(value)
        for value in out_index.get(left, set())
        if value.isdigit()
        and int(value) in observed_asns
        and int(value) not in path
        and not is_documentation_asn(int(value))
    )
    for checked, role_as in enumerate(candidates, start=1):
        if checked > max_candidates:
            break
        emitted = [*path[:-1], role_as]
        diagnostic = diagnose_path(" ".join(str(asn) for asn in emitted), lookup)
        if diagnostic_matches(diagnostic, allowed_diagnostics):
            return emitted, [(path[-2], role_as)], role_as, diagnostic
    raise ValueError(
        f"no observed replacement origin found after {min(len(candidates), max_candidates)} candidates "
        f"for penultimate AS {left}"
    )


def raw_record_id(scenario_id: str, phase_id: str, collector: str, ts: float) -> str:
    text = f"{scenario_id}|{phase_id}|{collector}|{ts:.3f}"
    return "rawinj1_" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]


def assert_output_ready(derived_root: Path, output_dir: Path, overwrite: bool) -> None:
    existing = [path for path in (derived_root, output_dir) if path.exists() and any(path.iterdir())]
    if existing and not overwrite:
        raise FileExistsError(
            "outputs exist; pass --overwrite: " + ", ".join(str(path) for path in existing)
        )
    if overwrite:
        for path in existing:
            shutil.rmtree(path)


def build_active_record(
    selected: pd.Series,
    scenario: dict[str, Any],
    active: bool,
    observed_asns: set[int],
    lookup: dict[tuple[str, str], dict[str, str]],
    out_index: dict[str, set[str]],
    max_candidates: int,
) -> tuple[list[int], list[tuple[int, int]], int | None, dict[str, Any]]:
    observed_path = clean_path(parse_path(selected["as_path"]))
    if not active or scenario["active_transform"] == "observed_template":
        diagnostic = diagnose_path(" ".join(str(asn) for asn in observed_path), lookup)
        return observed_path, [], None, diagnostic
    if scenario["active_transform"] != "replace_origin_dynamic":
        raise ValueError(f"unsupported active transform: {scenario['active_transform']}")
    return select_dynamic_replacement_origin(
        observed_path,
        scenario.get("expected_asrel_active_one_of", []),
        observed_asns,
        lookup,
        out_index,
        max_candidates,
    )


def main() -> None:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    config_path = (repo_root / args.config).resolve()
    config = read_json(config_path)
    source_root = (
        Path(args.source_run_root).resolve()
        if args.source_run_root
        else repo_root / "data" / "runs" / config["source_background_run_id"]
    )
    derived_root = (
        Path(args.derived_run_root).resolve()
        if args.derived_run_root
        else repo_root / "data" / "runs" / config["derived_run_id"]
    )
    output_dir = (
        Path(args.output_dir).resolve()
        if args.output_dir
        else repo_root / "outputs" / "r_attack_1" / config["derived_run_id"] / "materialization"
    )
    if source_root.resolve() == derived_root.resolve():
        raise ValueError("derived and source roots must differ")
    assert_output_ready(derived_root, output_dir, args.overwrite)

    files = raw_files(source_root)
    if len(files) != 144:
        raise ValueError(f"expected 144 source raw chunks, found {len(files)}")
    prefixes = {
        scenario[key]["source_prefix"]
        for scenario in config["scenarios"]
        for key in ("baseline_template", "active_template")
    }
    templates = load_templates(files, prefixes)
    lookup, asrel_metadata = load_diagnostic_asrel_lookup(
        repo_root / config["asrel_cache"],
        repo_root / config["asrel_metadata"],
    )
    out_index, _ = build_asrel_indexes(lookup)
    observed_asns = load_observed_asns(repo_root, config["source_background_run_id"], files)
    max_candidates = int(config.get("role_selection_defaults", {}).get("max_candidates_checked", 5000))

    by_chunk: dict[Path, list[dict[str, Any]]] = {}
    labels: list[dict[str, Any]] = []
    registry: list[dict[str, Any]] = []
    topology_rows: list[dict[str, Any]] = []
    role_rows: list[dict[str, Any]] = []
    dynamic_role_cache: dict[tuple[str, str], int] = {}

    for scenario in config["scenarios"]:
        scenario_class = str(scenario["scenario_class"])
        phase_schedule = config["phase_schedule"][scenario_class]
        collectors = [str(value) for value in scenario["expected_collectors"]]
        registry.append(
            {
                **scenario,
                "phase_schedule": phase_schedule,
                "evidence_snapshot_binding": config["evidence_snapshot_binding"],
                "truth_semantics": (
                    "controlled_attack_truth"
                    if scenario_class == "attack"
                    else "controlled_plausible_non_attack_lookalike_not_confirmed_benign"
                ),
            }
        )

        for phase_id, timestamps in phase_schedule.items():
            active = phase_id == "attack_launch"
            template_spec = scenario["active_template"] if active else scenario["baseline_template"]
            for timestamp in timestamps:
                ts = parse_utc(timestamp)
                for collector in collectors:
                    selected = select_template(
                        templates,
                        str(template_spec["source_prefix"]),
                        collector,
                        int(template_spec["origin_as"]),
                        ts,
                        bool(template_spec.get("require_no_export", False)),
                    )
                    if active and scenario["active_transform"] == "replace_origin_dynamic":
                        cache_key = (str(scenario["scenario_id"]), collector)
                        cached_role = dynamic_role_cache.get(cache_key)
                        if cached_role is not None:
                            observed_path = clean_path(parse_path(selected["as_path"]))
                            emitted_path = [*observed_path[:-1], cached_role]
                            inserted_edges = [(observed_path[-2], cached_role)]
                            selected_role = cached_role
                            diagnostic = diagnose_path(" ".join(str(asn) for asn in emitted_path), lookup)
                        else:
                            emitted_path, inserted_edges, selected_role, diagnostic = build_active_record(
                                selected,
                                scenario,
                                active,
                                observed_asns,
                                lookup,
                                out_index,
                                max_candidates,
                            )
                            if selected_role is not None:
                                dynamic_role_cache[cache_key] = int(selected_role)
                    else:
                        emitted_path, inserted_edges, selected_role, diagnostic = build_active_record(
                            selected,
                            scenario,
                            active,
                            observed_asns,
                            lookup,
                            out_index,
                            max_candidates,
                        )

                    for left, right in inserted_edges:
                        topology_rows.append(
                            {
                                "scenario_id": scenario["scenario_id"],
                                "left_as": int(left),
                                "right_as": int(right),
                                "known_2024": (str(left), str(right)) in lookup,
                                "relation": lookup.get((str(left), str(right)), {}).get(
                                    "relation_from_left_to_right", ""
                                ),
                            }
                        )
                    if active and selected_role is not None:
                        role_rows.append(
                            {
                                "scenario_id": scenario["scenario_id"],
                                "collector": collector,
                                "ts": float(ts),
                                "selected_role_as": int(selected_role),
                                "role_observed_in_background": int(selected_role) in observed_asns,
                                "active_asrel_diagnostic": diagnostic["path_relation_diagnostic_2024"],
                                "active_rel_seq_2024": diagnostic["rel_seq_2024"],
                            }
                        )

                    target = find_target_chunk(files, collector, ts)
                    is_attack = scenario_class == "attack" and active
                    is_hard_negative = scenario_class == "hard_negative" and active
                    output_prefix = str(template_spec["output_prefix"])
                    raw_row = {
                        "ts": float(ts),
                        "collector": collector,
                        "type": "A",
                        "peer_asn": int(selected["peer_asn"]),
                        "prefix": output_prefix,
                        "as_path": " ".join(str(asn) for asn in emitted_path),
                        "communities": selected["communities"],
                        "next_hop": selected["next_hop"],
                    }
                    by_chunk.setdefault(target, []).append(raw_row)
                    labels.append(
                        {
                            "raw_record_id": raw_record_id(scenario["scenario_id"], phase_id, collector, ts),
                            "scenario_id": scenario["scenario_id"],
                            "scenario_class": scenario_class,
                            "phase_id": phase_id,
                            "attack_role": (
                                "attacker_announce"
                                if is_attack
                                else ("hard_negative_announce" if is_hard_negative else "legitimate_announce")
                            ),
                            "is_injected": True,
                            "active_change_member": active,
                            "is_attack_member": is_attack,
                            "is_hard_negative_member": is_hard_negative,
                            "raw_event_eligible": True,
                            "raw_label_source": "controlled_injection_metadata",
                            "truth_semantics": (
                                "controlled_attack_truth"
                                if is_attack
                                else (
                                    "controlled_plausible_non_attack_lookalike_not_confirmed_benign"
                                    if is_hard_negative
                                    else "scenario_control_record"
                                )
                            ),
                            "collector": collector,
                            "ts": float(ts),
                            "source_prefix": str(template_spec["source_prefix"]),
                            "prefix": output_prefix,
                            "as_path": raw_row["as_path"],
                            "origin_as": emitted_path[-1],
                            "legitimate_origin_as": int(template_spec["origin_as"]),
                            "hypothetical_role_as": selected_role,
                            "attack_subtype": scenario["attack_subtype"],
                            "primary_family": scenario["primary_family"],
                            "adversarial_variant": "clean",
                            "expected_visibility_class": scenario["expected_visibility_class"],
                            "expected_collectors": json.dumps(collectors),
                            "expected_rpki_active_one_of": json.dumps(
                                scenario.get("expected_rpki_active_one_of", [])
                            ),
                            "expected_asrel_active_one_of": json.dumps(
                                scenario.get("expected_asrel_active_one_of", [])
                            ),
                            "expected_community_active": scenario.get("expected_community_active", ""),
                            "active_asrel_diagnostic_observed_at_materialization": (
                                diagnostic["path_relation_diagnostic_2024"] if active else ""
                            ),
                            "source_template_path": rel_path(Path(str(selected["_source_path"])), repo_root),
                            "target_chunk": rel_path(target, repo_root),
                            "community_fingerprint": community_fingerprint(raw_row["communities"]),
                            "has_no_export_in_raw_template": bool(selected["_has_no_export"]),
                            "community_semantics": scenario["community_mode"],
                            "inserted_edges": json.dumps(inserted_edges),
                            "inserted_edges_known_2024": all(
                                (str(left), str(right)) in lookup for left, right in inserted_edges
                            ),
                        }
                    )

    derived_root.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    source_rows = 0
    derived_rows = 0
    for source in files:
        target = derived_root / source.relative_to(source_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        source_count = int(pd.read_parquet(source, columns=["ts"]).shape[0])
        source_rows += source_count
        injected = by_chunk.get(source, [])
        if injected:
            frame = pd.read_parquet(source)
            combined = pd.concat(
                [frame, pd.DataFrame(injected, columns=frame.columns)],
                ignore_index=True,
            ).sort_values(["ts", "collector", "prefix", "as_path"], na_position="last")
            combined.to_parquet(target, index=False)
            mode = "rewritten_with_injection"
            digest = sha256_file(target)
            target_count = int(len(combined))
        else:
            os.link(source, target)
            mode = "hardlink_unchanged"
            digest = ""
            target_count = source_count
        derived_rows += target_count
        manifest.append(
            {
                "source_path": rel_path(source, repo_root),
                "derived_path": rel_path(target, repo_root),
                "materialization_mode": mode,
                "source_rows": source_count,
                "injected_rows": len(injected),
                "derived_rows": target_count,
                "derived_sha256_if_rewritten": digest,
            }
        )

    smoke_raw = output_dir / "smoke_raw"
    smoke_raw.mkdir(parents=True, exist_ok=True)
    for source in sorted(by_chunk, key=lambda path: path.as_posix()):
        smoke_target = smoke_raw / source.relative_to(source_root)
        smoke_target.parent.mkdir(parents=True, exist_ok=True)
        os.link(derived_root / source.relative_to(source_root), smoke_target)

    truth = pd.DataFrame(labels)
    topology = pd.DataFrame(topology_rows)
    role_audit = pd.DataFrame(role_rows)
    truth.to_parquet(output_dir / "injected_raw_truth.parquet", index=False)
    truth.to_csv(output_dir / "injected_raw_truth.csv", index=False)
    pd.DataFrame(manifest).to_csv(output_dir / "derived_raw_manifest.csv", index=False)
    topology.to_csv(output_dir / "inserted_edge_topology_audit.csv", index=False)
    role_audit.to_csv(output_dir / "dynamic_role_selection_audit.csv", index=False)
    (output_dir / "scenario_registry.json").write_text(
        json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    active_attack = truth[truth["is_attack_member"]]
    scenario_counts = active_attack.groupby(
        ["primary_family", "attack_subtype"], dropna=False
    )["raw_record_id"].nunique()
    summary = {
        "phase": "R-ATTACK-1",
        "source_background_run_id": config["source_background_run_id"],
        "derived_run_id": config["derived_run_id"],
        "source_raw_chunks": len(files),
        "rewritten_chunks": len(by_chunk),
        "hardlinked_chunks": len(files) - len(by_chunk),
        "source_raw_rows": source_rows,
        "derived_raw_rows": derived_rows,
        "injected_raw_rows": int(len(truth)),
        "injected_attack_rows": int(truth["is_attack_member"].sum()),
        "injected_hard_negative_rows": int(truth["is_hard_negative_member"].sum()),
        "attack_scenario_count": int(
            sum(item["scenario_class"] == "attack" for item in config["scenarios"])
        ),
        "hard_negative_scenario_count": int(
            sum(item["scenario_class"] == "hard_negative" for item in config["scenarios"])
        ),
        "attack_rows_by_family_subtype": {
            "|".join(map(str, key)): int(value)
            for key, value in scenario_counts.to_dict().items()
        },
        "dynamic_role_selection_rows": int(len(role_audit)),
        "all_dynamic_roles_observed": bool(
            role_audit.empty or role_audit["role_observed_in_background"].fillna(False).all()
        ),
        "all_inserted_edges_known_2024": bool(
            topology.empty or topology["known_2024"].fillna(False).all()
        ),
        "active_no_export_attack_rows": int(
            truth[truth["is_attack_member"]]["has_no_export_in_raw_template"].sum()
        ),
        "smoke_raw_root": rel_path(smoke_raw, repo_root),
        "smoke_raw_chunks": len(by_chunk),
        "input_immutable": True,
        "truth_columns_added_to_raw": False,
        "full_window_processed": False,
        "learning_trained": False,
        "asrel_snapshot_date": str(asrel_metadata.get("snapshot_date", "")),
        "allowed_claim": "R-ATTACK-1 raw scenarios were materialized from observed templates with truth in sidecars only.",
        "forbidden_claims": [
            "NO_EXPORT present is attack truth",
            "NO_EXPORT absent is safe",
            "Subprefix feasibility proves historical recall",
            "Hard negatives are confirmed benign",
            "Learning is ready"
        ],
    }
    (output_dir / "materialization_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
