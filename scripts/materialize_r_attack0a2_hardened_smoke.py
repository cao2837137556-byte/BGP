import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

import pandas as pd

from materialize_r_attack0a_origin_smoke import (
    RAW_COLUMNS,
    chunk_bounds,
    clean_path,
    collector_from_path,
    find_target_chunk,
    parse_path,
    parse_utc,
    raw_files,
    rel_path,
    sha256_file,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Materialize the hardened R-ATTACK-0A-2 bounded raw smoke."
    )
    parser.add_argument(
        "--config", default="configs/r_attack0a2_hardened_origin_smoke_v02.yaml"
    )
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--source-run-root", default="")
    parser.add_argument("--derived-run-root", default="")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def read_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def community_fingerprint(value: Any) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]


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
        selected["_path_clean"] = selected["as_path"].map(
            lambda value: " ".join(str(asn) for asn in clean_path(parse_path(value)))
        )
        selected["_community_fp"] = selected["communities"].map(community_fingerprint)
        rows.append(selected)
    if not rows:
        raise ValueError("no raw templates found for configured prefixes")
    return pd.concat(rows, ignore_index=True)


def select_nearest(
    templates: pd.DataFrame,
    prefix: str,
    collector: str,
    origin_as: int,
    target_ts: float,
    required_penultimate_as: int | None = None,
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
    if required_penultimate_as is not None:
        subset = subset[
            subset["_path_clean"].map(
                lambda value: len(parse_path(value)) >= 2
                and parse_path(value)[-2] == required_penultimate_as
            )
        ].copy()
    if subset.empty:
        raise ValueError(
            f"no observed template: prefix={prefix}, collector={collector}, origin={origin_as}"
        )
    subset["_distance"] = (pd.to_numeric(subset["ts"], errors="coerce") - target_ts).abs()
    return subset.sort_values(["_distance", "ts", "_path_clean"]).iloc[0]


def select_alternate_path(
    templates: pd.DataFrame,
    base: pd.Series,
    prefix: str,
    collector: str,
    origin_as: int,
    target_ts: float,
) -> pd.Series:
    subset = templates[
        templates["prefix"].astype(str).eq(prefix)
        & templates["collector"].astype(str).eq(collector)
        & templates["_path_clean"].ne(str(base["_path_clean"]))
    ].copy()
    subset = subset[
        subset["_path_clean"].map(
            lambda value: bool(parse_path(value)) and parse_path(value)[-1] == origin_as
        )
    ].copy()
    if subset.empty:
        raise ValueError(f"no alternate observed path: prefix={prefix}, collector={collector}")
    subset["_distance"] = (pd.to_numeric(subset["ts"], errors="coerce") - target_ts).abs()
    return subset.sort_values(["_distance", "ts", "_path_clean"]).iloc[0]


def select_alternate_community(
    templates: pd.DataFrame,
    base: pd.Series,
    prefix: str,
    collector: str,
    origin_as: int,
    target_ts: float,
) -> pd.Series:
    subset = templates[
        templates["prefix"].astype(str).eq(prefix)
        & templates["collector"].astype(str).eq(collector)
        & templates["_path_clean"].eq(str(base["_path_clean"]))
        & templates["_community_fp"].ne(str(base["_community_fp"]))
    ].copy()
    subset = subset[
        subset["_path_clean"].map(
            lambda value: bool(parse_path(value)) and parse_path(value)[-1] == origin_as
        )
    ].copy()
    if subset.empty:
        # Some collectors legitimately expose a single community representation.
        return base
    subset["_distance"] = (pd.to_numeric(subset["ts"], errors="coerce") - target_ts).abs()
    return subset.sort_values(["_distance", "ts", "_community_fp"]).iloc[0]


def load_asrel_lookup(path: Path) -> dict[tuple[int, int], str]:
    frame = pd.read_parquet(
        path, columns=["as_left", "as_right", "relation_from_left_to_right"]
    ).drop_duplicates(["as_left", "as_right"])
    return {
        (int(row.as_left), int(row.as_right)): str(row.relation_from_left_to_right)
        for row in frame.itertuples(index=False)
    }


def validate_required_edges(
    scenario: dict[str, Any], lookup: dict[tuple[int, int], str]
) -> list[dict[str, Any]]:
    rows = []
    for left, right in scenario.get("required_inserted_edges", []):
        relation = lookup.get((int(left), int(right)))
        rows.append(
            {
                "left_as": int(left),
                "right_as": int(right),
                "relation": relation or "",
                "known": relation is not None,
            }
        )
    if rows and not all(row["known"] for row in rows):
        raise ValueError(
            f"unknown configured inserted edge for {scenario['scenario_id']}: {rows}"
        )
    return rows


def build_active_path(
    observed_path: list[int], transform: str, role_as: int | None
) -> tuple[list[int], list[tuple[int, int]]]:
    path = clean_path(observed_path)
    if transform in {
        "observed_template",
        "observed_alternate_path",
        "observed_alternate_community",
    }:
        return path, []
    if role_as is None:
        raise ValueError(f"{transform} requires hypothetical_role_as")
    if role_as in path:
        raise ValueError(f"hypothetical role ASN already occurs in source path: {role_as}")
    if transform == "replace_origin":
        emitted = [*path[:-1], role_as]
        return emitted, [(path[-2], role_as)]
    if transform == "insert_before_origin":
        emitted = [*path[:-1], role_as, path[-1]]
        return emitted, [(path[-2], role_as), (role_as, path[-1])]
    raise ValueError(f"unsupported active transform: {transform}")


def raw_record_id(scenario_id: str, phase_id: str, collector: str, ts: float) -> str:
    text = f"{scenario_id}|{phase_id}|{collector}|{ts:.3f}"
    return "rawinj2_" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]


def assert_output_ready(derived_root: Path, output_dir: Path, overwrite: bool) -> None:
    existing = [
        path
        for path in (derived_root, output_dir)
        if path.exists() and any(path.iterdir())
    ]
    if existing and not overwrite:
        raise FileExistsError(
            "outputs exist; pass --overwrite: " + ", ".join(str(path) for path in existing)
        )
    if overwrite:
        for path in existing:
            shutil.rmtree(path)


def main() -> None:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    config_path = (repo_root / args.config).resolve()
    config = read_config(config_path)
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
        else repo_root / "outputs" / "r_attack_0a2" / config["derived_run_id"]
    )
    if source_root.resolve() == derived_root.resolve():
        raise ValueError("derived and source roots must differ")
    assert_output_ready(derived_root, output_dir, args.overwrite)

    files = raw_files(source_root)
    if len(files) != 144:
        raise ValueError(f"expected 144 source raw chunks, found {len(files)}")
    prefixes = {
        scenario[key]["prefix"]
        for scenario in config["scenarios"]
        for key in ("baseline_template", "active_template")
    }
    templates = load_templates(files, prefixes)
    asrel_lookup = load_asrel_lookup(repo_root / config["asrel_cache"])
    collectors = [str(value) for value in config["expected_collectors"]]

    by_chunk: dict[Path, list[dict[str, Any]]] = {}
    labels: list[dict[str, Any]] = []
    registry: list[dict[str, Any]] = []
    topology_rows: list[dict[str, Any]] = []

    for scenario in config["scenarios"]:
        scenario_class = str(scenario["scenario_class"])
        phase_schedule = config["phase_schedule"][scenario_class]
        topology = validate_required_edges(scenario, asrel_lookup)
        for edge in topology:
            topology_rows.append({"scenario_id": scenario["scenario_id"], **edge})
        registry.append(
            {
                **scenario,
                "phase_schedule": phase_schedule,
                "expected_collectors": collectors,
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
            template_spec = (
                scenario["active_template"] if active else scenario["baseline_template"]
            )
            for timestamp in timestamps:
                ts = parse_utc(timestamp)
                for collector in collectors:
                    base = select_nearest(
                        templates,
                        str(template_spec["prefix"]),
                        collector,
                        int(template_spec["origin_as"]),
                        ts,
                        (
                            int(scenario["required_penultimate_as"])
                            if scenario_class == "attack"
                            else None
                        ),
                    )
                    selected = base
                    transform = str(scenario["active_transform"]) if active else "observed_template"
                    if active and transform == "observed_alternate_path":
                        selected = select_alternate_path(
                            templates,
                            base,
                            str(template_spec["prefix"]),
                            collector,
                            int(template_spec["origin_as"]),
                            ts,
                        )
                    elif active and transform == "observed_alternate_community":
                        selected = select_alternate_community(
                            templates,
                            base,
                            str(template_spec["prefix"]),
                            collector,
                            int(template_spec["origin_as"]),
                            ts,
                        )

                    observed_path = clean_path(parse_path(selected["as_path"]))
                    role_as = scenario.get("hypothetical_role_as")
                    emitted_path, inserted_edges = build_active_path(
                        observed_path, transform, int(role_as) if role_as is not None else None
                    )
                    configured_edges = {
                        (int(left), int(right))
                        for left, right in scenario.get("required_inserted_edges", [])
                    }
                    if active and set(inserted_edges) != configured_edges:
                        raise ValueError(
                            f"inserted edge mismatch for {scenario['scenario_id']}: "
                            f"actual={inserted_edges}, configured={sorted(configured_edges)}"
                        )
                    target = find_target_chunk(files, collector, ts)
                    is_attack = scenario_class == "attack" and active
                    is_hard_negative = scenario_class == "hard_negative" and active
                    role = "attacker_announce" if is_attack else "legitimate_announce"
                    raw_row = {
                        "ts": float(ts),
                        "collector": collector,
                        "type": "A",
                        "peer_asn": int(selected["peer_asn"]),
                        "prefix": str(template_spec["prefix"]),
                        "as_path": " ".join(str(asn) for asn in emitted_path),
                        "communities": selected["communities"],
                        "next_hop": selected["next_hop"],
                    }
                    by_chunk.setdefault(target, []).append(raw_row)
                    labels.append(
                        {
                            "raw_record_id": raw_record_id(
                                scenario["scenario_id"], phase_id, collector, ts
                            ),
                            "scenario_id": scenario["scenario_id"],
                            "scenario_class": scenario_class,
                            "phase_id": phase_id,
                            "attack_role": role,
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
                            "prefix": raw_row["prefix"],
                            "as_path": raw_row["as_path"],
                            "origin_as": emitted_path[-1],
                            "legitimate_origin_as": int(template_spec["origin_as"]),
                            "hypothetical_role_as": role_as,
                            "attack_subtype": scenario["attack_subtype"],
                            "primary_family": scenario["primary_family"],
                            "adversarial_variant": "clean",
                            "expected_visibility_class": scenario[
                                "expected_visibility_class"
                            ],
                            "source_template_path": rel_path(
                                Path(str(selected["_source_path"])), repo_root
                            ),
                            "target_chunk": rel_path(target, repo_root),
                            "community_fingerprint": community_fingerprint(
                                raw_row["communities"]
                            ),
                            "community_semantics": (
                                "alternate_observed_legitimate_template"
                                if active and transform == "observed_alternate_community"
                                else "matched_observed_legitimate_template"
                            ),
                            "inserted_edges": json.dumps(inserted_edges),
                            "inserted_edges_known_2024": all(
                                asrel_lookup.get(edge) is not None for edge in inserted_edges
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
                [frame, pd.DataFrame(injected, columns=frame.columns)], ignore_index=True
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
    truth.to_parquet(output_dir / "injected_raw_truth.parquet", index=False)
    truth.to_csv(output_dir / "injected_raw_truth.csv", index=False)
    pd.DataFrame(manifest).to_csv(output_dir / "derived_raw_manifest.csv", index=False)
    pd.DataFrame(topology_rows).to_csv(
        output_dir / "inserted_edge_topology_audit.csv", index=False
    )
    (output_dir / "scenario_registry.json").write_text(
        json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    summary = {
        "phase": "R-ATTACK-0A-2",
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
        "injected_control_rows": int(
            (~truth["active_change_member"].astype(bool)).sum()
        ),
        "attack_scenario_count": int(
            sum(item["scenario_class"] == "attack" for item in config["scenarios"])
        ),
        "hard_negative_scenario_count": int(
            sum(
                item["scenario_class"] == "hard_negative"
                for item in config["scenarios"]
            )
        ),
        "smoke_raw_root": rel_path(smoke_raw, repo_root),
        "smoke_raw_chunks": len(by_chunk),
        "input_immutable": True,
        "truth_columns_added_to_raw": False,
        "all_inserted_edges_known_2024": bool(
            all(row["known"] for row in topology_rows)
        ),
        "full_window_processed": False,
        "learning_trained": False,
    }
    (output_dir / "materialization_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
