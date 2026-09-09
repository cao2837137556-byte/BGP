"""Input and package integrity contracts; never makes suppression decisions."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd


PACKAGE_PATHS = [
    "configs/n_frontend1_causal_transition_v01.json",
    "configs/n_frontend2b_controlled_pairs_v01.json",
    "configs/n_frontend3b_background_suppression_v01.json",
    "configs/r_poison0_paired_benchmark_protocol_v01.json",
    "scripts/build_n_frontend1_causal_transitions.py",
    "scripts/r_mem_canonical_observation_v2.py",
    "scripts/run_r_mem1c_local_mrt_parser_smoke.py",
    "scripts/run_n_frontend2b_controlled_pairs.py",
    "scripts/n_frontend3b_contract.py",
    "scripts/n_frontend3b_artifact_validation.py",
    "scripts/test_n_frontend3b_integrity.py",
    "scripts/run_n_frontend3b_background_suppression.py",
    "scripts/validate_n_frontend3b_background_suppression.py",
    "scripts/validate_n_frontend3b_dual_parity.py",
    "scripts/hpc/build_n_frontend3b_reviewed_bundle.py",
    "scripts/hpc/finalize_n_frontend3b_dual_pair.sh",
    "scripts/hpc/n_frontend3b_bounded_replay.slurm",
    "scripts/hpc/n_frontend3b_bounded_replay_preflight.sh",
    "scripts/hpc/submit_n_frontend3b_bounded_replay_dual.sh",
]
ROOT_INPUTS = [
    "n_frontend2b_summary.json", "n_frontend2b_registry_freeze.json",
    "n_frontend2b_observer_registry.json", "n_frontend2b_background_cadence_audit.json",
    "n_frontend2b_background_input_manifest.json",
    "n_frontend2b_truth_provenance_sidecar.csv",
    "n_frontend2b_synthetic_observation_manifest.csv",
    "n_frontend2b_phase_survival_lineage.csv",
    "n_frontend2b_attack_transition_semantic_delta.csv",
]
VARIANT_INPUTS = [
    "frontend/n_frontend1_transitions.parquet", "frontend/n_frontend1_micro_events.parquet",
    "frontend/n_frontend1_non_route_observations.parquet", "frontend/n_frontend1_summary.json",
    "phase_survival_lineage.csv", "past_only_route_exposure.csv", "truth_provenance_sidecar.csv",
]
MEMBER_KEYS = ["pair_id", "variant_role", "member_id"]
TRUTH_FIELDS = MEMBER_KEYS + [
    "observation_id", "phase_id", "collector", "peer_address", "synthetic_source_uri",
    "expected_visible", "is_attack_member", "is_poisoning_preparation_member",
]


def normalized(value):
    if isinstance(value, dict):
        return {str(k): normalized(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [normalized(v) for v in value]
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (float, np.floating)):
        return float(value)
    return value


def canonical(value):
    return json.dumps(normalized(value), sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode("ascii")).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def table_records(frame, columns=None):
    if columns is not None:
        if not set(columns) <= set(frame):
            raise ValueError("missing comparison columns")
        frame = frame[columns]
    return sorted((normalized(row) for row in frame.to_dict("records")), key=canonical)


def same_table(left, right):
    return set(left) == set(right) and canonical(table_records(left)) == canonical(table_records(right))


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def verify_package(path, repo_root, expected_commit, expected_manifest_sha256):
    require(path is not None and Path(path).is_file(), "package manifest missing")
    require(bool(re.fullmatch(r"[0-9a-f]{40}", expected_commit or "")), "expected package commit required")
    require(file_hash(path) == expected_manifest_sha256, "package receipt hash mismatch")
    manifest = read_json(path)
    require(manifest.get("source_commit") == expected_commit, "package commit mismatch")
    for flag in ("all_entries_passed", "git_archive_or_lf_normalized", "local_python_import_closure_passed"):
        require(manifest.get(flag) is True, f"package flag invalid:{flag}")
    entries = manifest.get("entries", [])
    names = [entry.get("path") for entry in entries]
    require(len(names) == len(PACKAGE_PATHS) and set(names) == set(PACKAGE_PATHS), "package inventory mismatch")
    for entry in entries:
        data = (repo_root / entry["path"]).read_bytes()
        require(data == data.replace(b"\r\n", b"\n"), "package noncanonical line endings")
        sha = hashlib.sha256(data).hexdigest()
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        require(sha == entry.get("packaged_sha256") == entry.get("canonical_lf_sha256"), f"package bytes changed:{entry['path']}")
        require(blob == entry.get("git_blob_oid"), f"package blob mismatch:{entry['path']}")
    return {**manifest, "runtime_verification_passed": True,
            "receipt_manifest_sha256": expected_manifest_sha256, "receipt_commit": expected_commit}


def verify_source(root, config, self_test=False):
    """Validate frozen metadata and reconcile all root/variant truth before use.

    Formal metadata hashes come from the already completed dual 2B run, not
    from the candidate directory. Large frame contents are checked separately.
    """
    root = Path(root).resolve()
    for name in ROOT_INPUTS:
        require((root / name).is_file(), f"missing source:{name}")
    summary = read_json(root / ROOT_INPUTS[0])
    freeze = read_json(root / "n_frontend2b_registry_freeze.json")
    require(summary.get("overall_pass") is True, "2B source did not pass")
    for name, key in (("n_frontend2b_observer_registry.json", "registry_sha256"),
                      ("n_frontend2b_background_cadence_audit.json", "cadence_audit_sha256")):
        require(file_hash(root / name) == freeze.get(key), f"source freeze changed:{name}")
    freeze_data = dict(freeze)
    fingerprint = freeze_data.pop("freeze_fingerprint", None)
    require(digest(freeze_data) == fingerprint == summary.get("registry_freeze_fingerprint"), "registry fingerprint mismatch")
    registry = read_json(root / "n_frontend2b_observer_registry.json")
    require(len(registry) == freeze.get("registry_row_count"), "registry count mismatch")
    background = read_json(root / "n_frontend2b_background_input_manifest.json")
    require(digest(background["input_files"]) == background["input_manifest_fingerprint"], "background input fingerprint mismatch")
    if not self_test:
        require(fingerprint == config["formal_2b_registry_fingerprint"], "wrong frozen registry")
        require(f"pair={config['formal_2b_pair_id']}" in root.parts, "wrong source pair directory")
        for name, expected in config["formal_2b_artifact_sha256"].items():
            require(file_hash(root / name) == expected, f"frozen input bytes differ:{name}")
        begin, end = (pd.Timestamp(t).timestamp() for t in config["formal_episode_utc"].split("/"))
        require(background["episode_start_ts"] == begin and background["episode_end_ts"] == end, "wrong formal episode")
    else:
        begin, end = background["episode_start_ts"], background["episode_end_ts"]
    truth = pd.read_csv(root / "n_frontend2b_truth_provenance_sidecar.csv")
    lineage = pd.read_csv(root / "n_frontend2b_phase_survival_lineage.csv")
    synthetic = pd.read_csv(root / "n_frontend2b_synthetic_observation_manifest.csv")
    require(not truth.duplicated(MEMBER_KEYS).any(), "duplicate truth member")
    require(table_records(truth, TRUTH_FIELDS) == table_records(lineage, TRUTH_FIELDS), "root truth/lineage membership mismatch")
    for flag in ("expected_visible", "is_attack_member", "is_poisoning_preparation_member"):
        require(truth[flag].map(lambda x: isinstance(x, (bool, np.bool_))).all(), f"invalid truth flag:{flag}")
    visible = truth[truth.expected_visible]
    require(len(visible) == summary["expected_visible_member_count"], "frozen visible member count mismatch")
    require(len(truth) - len(visible) == summary["observability_boundary_member_count"], "boundary member count mismatch")
    synthetic_fields = ["pair_id", "variant_role", "observation_id", "collector", "peer_address", "phase_id", "synthetic_source_uri"]
    require(table_records(visible, synthetic_fields) == table_records(synthetic, synthetic_fields), "synthetic/expected-member mismatch")
    require(not visible.duplicated(["pair_id", "variant_role", "observation_id"]).any(), "duplicate synthetic identity")
    require(synthetic.ts.ge(begin).all() and synthetic.ts.lt(end).all(), "synthetic data outside episode")
    require(truth.synthetic_source_uri.str.startswith("synthetic://").all(), "invalid synthetic provenance")
    expected_pairs = {row["pair_id"] for row in registry}
    expected_variants = {(p, v) for p in expected_pairs for v in ("clean", "adversarial")}
    require(set(map(tuple, truth[["pair_id", "variant_role"]].drop_duplicates().values)) == expected_variants, "truth variant set mismatch")
    actual_variants = {(p.parent.name, p.name) for p in (root / "evaluation_only").glob("*/*") if p.is_dir()}
    require(actual_variants == expected_variants and len(actual_variants) == 10, "source variant set mismatch")
    hashes = {name: file_hash(root / name) for name in ROOT_INPUTS}
    for pair, variant in sorted(expected_variants):
        directory = root / "evaluation_only" / pair / variant
        for name in VARIANT_INPUTS:
            require((directory / name).is_file(), f"missing variant source:{directory / name}")
            hashes[(directory / name).relative_to(root).as_posix()] = file_hash(directory / name)
        selected_truth = truth[(truth.pair_id == pair) & (truth.variant_role == variant)]
        local_truth = pd.read_csv(directory / "truth_provenance_sidecar.csv")
        local_lineage = pd.read_csv(directory / "phase_survival_lineage.csv")
        require(table_records(local_truth, TRUTH_FIELDS) == table_records(selected_truth, TRUTH_FIELDS), "variant truth membership mismatch")
        require(table_records(local_lineage, TRUTH_FIELDS) == table_records(selected_truth, TRUTH_FIELDS), "variant lineage membership mismatch")
        root_part = lineage[(lineage.pair_id == pair) & (lineage.variant_role == variant)]
        require(same_table(local_lineage, root_part), "root/variant lineage disagreement")
    return {"source_2b_root": str(root), "self_test": self_test,
            "registry_fingerprint": fingerprint, "episode_start_ts": begin, "episode_end_ts": end,
            "input_sha256": hashes, "truth": truth, "lineage": lineage}


def verify_variant_frames(transitions, micro, lineage, truth, begin, end):
    require(transitions.transition_id.notna().all() and not transitions.transition_id.duplicated().any(), "invalid transition IDs")
    require(micro.micro_event_id.notna().all() and not micro.micro_event_id.duplicated().any(), "invalid micro-event IDs")
    require(transitions.transition_ts.ge(begin).all() and transitions.transition_ts.lt(end).all(), "transitions outside episode")
    by_observation = {}
    uri_by_observation = dict(zip(truth.observation_id.dropna(), truth.loc[truth.observation_id.notna(), "synthetic_source_uri"]))
    for row in transitions.to_dict("records"):
        members = list(row["member_observation_ids"])
        require(len(members) == row["member_observation_count"] and len(members) == len(set(members)), "observation member count mismatch")
        for member in members:
            require(member not in by_observation, "observation belongs to multiple transitions")
            by_observation[member] = row
        expected_uris = {uri_by_observation[m] for m in members if m in uri_by_observation}
        actual_uris = {s for s in row["source_files"] if s.startswith("synthetic://")}
        require(expected_uris == actual_uris, "unaccounted synthetic provenance")
    transition_by_id = transitions.set_index("transition_id").to_dict("index")
    event_by_transition = {}
    for event in micro.to_dict("records"):
        members = list(event["member_transition_ids"])
        require(len(members) == event["member_transition_count"] and members, "micro member count mismatch")
        require(event["available_at_ts"] == event["window_end_ts"], "premature micro-event availability")
        for member in members:
            require(member in transition_by_id and member not in event_by_transition, "micro membership mismatch")
            t = transition_by_id[member]["transition_ts"]
            require(event["window_start_ts"] <= t < event["available_at_ts"], "micro-event time membership mismatch")
            event_by_transition[member] = event["micro_event_id"]
    require(set(event_by_transition) == set(transition_by_id), "unassigned source transitions")
    for row in lineage.to_dict("records"):
        if row["expected_visible"]:
            observed = by_observation.get(row["observation_id"])
            require(observed is not None and observed["transition_id"] == row["transition_id"], "visible member transition mismatch")
            require(observed["transition_family"] == row["transition_family"], "visible member family mismatch")
            require(event_by_transition[row["transition_id"]] == row["micro_event_id"], "visible member micro-event mismatch")
        else:
            require(pd.isna(row["observation_id"]) and pd.isna(row["transition_id"]) and pd.isna(row["micro_event_id"]), "boundary acquired an observation")
