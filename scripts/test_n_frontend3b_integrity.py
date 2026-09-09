#!/usr/bin/env python3
"""Permanent regression tests for the five 3B integrity findings."""
from __future__ import annotations

from contextlib import contextmanager
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import pandas as pd

import run_n_frontend3b_background_suppression as runner
import validate_n_frontend3b_background_suppression as validator
from n_frontend3b_contract import (
    PACKAGE_PATHS, canonical, file_hash, read_json, verify_package,
    verify_source, verify_variant_frames,
)

REPO = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO / "configs/n_frontend3b_background_suppression_v01.json"


@contextmanager
def preserve(*paths):
    original = {p: p.read_bytes() for p in paths}
    try:
        yield
    finally:
        for path, data in original.items():
            path.write_bytes(data)


class IntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="n_frontend3b_integrity_")
        cls.root = Path(cls.temp.name)
        cls.output = cls.root / "fixture"
        cls.config = read_json(CONFIG_PATH)
        subprocess.run([
            sys.executable, str(REPO / "scripts/run_n_frontend3b_background_suppression.py"),
            "--self-test", "--config", str(CONFIG_PATH), "--output-dir", str(cls.output),
        ], check=True, cwd=REPO, stdout=subprocess.DEVNULL)
        cls.source = cls.output / "_selftest_source"
        cls.variant = sorted((cls.output / "evaluation_only").glob("*/*"))[0]
        cls.source_variant = cls.source / "evaluation_only" / cls.variant.parent.name / cls.variant.name

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def validation(self):
        return validator.validate(self.output, CONFIG_PATH, allow_self_test=True)

    def assert_rejected(self):
        result = self.validation()
        self.assertFalse(result["validation_passed"], result)
        self.assertTrue(any("independent_artifact_contract" in e for e in result["errors"]), result)

    def test_valid_fixture_and_formal_mode_isolation(self):
        self.assertTrue(self.validation()["validation_passed"])
        self.assertFalse(validator.validate(self.output, CONFIG_PATH)["validation_passed"])

    def test_formal_config_cannot_escape_package(self):
        with self.assertRaisesRegex(ValueError, "receipt-bound packaged config"):
            runner.run_experiment(self.source, self.root / "never_created", self.root / "other_config.json",
                                  None, False, False)
        self.assertFalse((self.root / "never_created").exists())

    def test_every_required_flag_is_present_and_boolean(self):
        frame = pd.read_parquet(self.source_variant / "frontend/n_frontend1_transitions.parquet")
        base = frame[frame.transition_family == "identical_reannouncement"].iloc[0].to_dict()
        self.assertEqual(runner.transition_decision(base, self.config)["eligibility_assignment"], runner.ASSIGN_BACKGROUND)
        fields = self.config["suppression_eligibility"]["required_false_flags"] + self.config["suppression_eligibility"]["required_true_flags"]
        for field in fields:
            for value in (None, "false", "true", 0, 1, "absent"):
                with self.subTest(field=field, value=value):
                    row = dict(base)
                    if value == "absent":
                        row.pop(field)
                    else:
                        row[field] = value
                    self.assertEqual(runner.transition_decision(row, self.config)["eligibility_assignment"], runner.ASSIGN_GRAY)
                    self.assertEqual(validator.independent_assignment(row, self.config), runner.ASSIGN_GRAY)

    def test_persisted_learning_members_and_indexes(self):
        for name in ("semantic_foreground_micro_events.parquet", "immutable_background_transitions.parquet",
                     "n_frontend3b_reversible_background_index.parquet", "n_frontend3b_background_member_manifest.parquet"):
            with self.subTest(artifact=name):
                path = self.variant / name
                with preserve(path):
                    frame = pd.read_parquet(path)
                    self.assertGreater(len(frame), 0)
                    frame.iloc[:0].to_parquet(path, index=False)
                    self.assert_rejected()

    def test_changed_background_history_and_prior_ledger(self):
        for name, column, replacement in (
            ("immutable_background_transitions.parquet", "transition_ts", 1720000901.0),
            ("n_frontend3b_transition_assignments.parquet", "decision_prior_ledger_fingerprint", "fabricated"),
        ):
            with self.subTest(artifact=name):
                path = self.variant / name
                with preserve(path):
                    frame = pd.read_parquet(path)
                    frame[column] = replacement
                    frame.to_parquet(path, index=False)
                    self.assert_rejected()

    def test_post_exposure_is_recomputed(self):
        path = self.variant / "n_frontend3b_past_only_exposure_post.csv"
        with preserve(path):
            frame = pd.read_csv(path)
            frame.loc[0, "prior_exposure_count"] += 999
            frame.to_csv(path, index=False)
            self.assert_rejected()

    def test_denominator_and_reported_rate_are_recomputed(self):
        path = self.output / "n_frontend3b_denominator_audit.csv"
        with preserve(path):
            frame = pd.read_csv(path)
            frame.loc[0, "transition_operational_background_count"] += 1000
            frame.to_csv(path, index=False)
            self.assert_rejected()
        path = self.output / "n_frontend3b_summary.json"
        with preserve(path):
            summary = read_json(path)
            summary["micro_event_learning_input_reduction_rate"] = 0.99
            path.write_text(json.dumps(summary), encoding="utf-8")
            self.assert_rejected()

    def test_crossed_summary_and_registry_are_rejected(self):
        path = self.source / "n_frontend2b_summary.json"
        with preserve(path):
            summary = read_json(path)
            summary["registry_freeze_fingerprint"] = self.config["formal_2b_registry_fingerprint"]
            path.write_text(json.dumps(summary), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "registry fingerprint mismatch"):
                verify_source(self.source, self.config, True)
        path = self.source / "n_frontend2b_observer_registry.json"
        with preserve(path):
            path.write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "source freeze changed"):
                verify_source(self.source, self.config, True)

    def test_truth_omissions_cannot_change_population(self):
        root = self.source / "n_frontend2b_phase_survival_lineage.csv"
        frame = pd.read_csv(root)
        for phase in ("poisoning_preparation", "recovery"):
            row = frame[frame.phase_id == phase].iloc[0]
            local = self.source / "evaluation_only" / row.pair_id / row.variant_role / "phase_survival_lineage.csv"
            with self.subTest(phase=phase), preserve(root, local):
                frame[frame.observation_id != row.observation_id].to_csv(root, index=False)
                local_frame = pd.read_csv(local)
                if phase == "recovery":
                    local_frame[local_frame.observation_id != row.observation_id].to_csv(local, index=False)
                with self.assertRaisesRegex(ValueError, "root truth/lineage membership mismatch"):
                    verify_source(self.source, self.config, True)

    def test_source_times_and_synthetic_provenance(self):
        context = verify_source(self.source, self.config, True)
        source = pd.read_parquet(self.source_variant / "frontend/n_frontend1_transitions.parquet")
        events = pd.read_parquet(self.source_variant / "frontend/n_frontend1_micro_events.parquet")
        lineage = pd.read_csv(self.source_variant / "phase_survival_lineage.csv")
        truth = context["truth"]
        truth = truth[(truth.pair_id == self.variant.parent.name) & (truth.variant_role == self.variant.name)]
        def check(s, m):
            verify_variant_frames(s, m, lineage, truth, context["episode_start_ts"], context["episode_end_ts"])
        check(source, events)
        changed = source.copy()
        changed.loc[0, "transition_ts"] = context["episode_end_ts"]
        with self.assertRaisesRegex(ValueError, "outside episode"):
            check(changed, events)
        changed = source.copy()
        changed.at[0, "source_files"] = ["synthetic://unregistered"]
        with self.assertRaisesRegex(ValueError, "synthetic provenance"):
            check(changed, events)
        changed = events.copy()
        changed.loc[0, "available_at_ts"] = changed.loc[0, "window_start_ts"]
        with self.assertRaisesRegex(ValueError, "premature micro-event"):
            check(source, changed)

    def test_complete_package_inventory_and_receipt(self):
        root = self.root / "package_fixture"
        root.mkdir()
        entries = []
        for name in PACKAGE_PATHS:
            data = (REPO / name).read_bytes().replace(b"\r\n", b"\n")
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            entries.append({"path":name, "packaged_sha256":hashlib.sha256(data).hexdigest(),
                "canonical_lf_sha256":hashlib.sha256(data).hexdigest(),
                "git_blob_oid":hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()})
        commit = "a"*40
        manifest = {"source_commit":commit, "all_entries_passed":True,
            "git_archive_or_lf_normalized":True,"local_python_import_closure_passed":True,"entries":entries}
        path = root / "manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        receipt = file_hash(path)
        self.assertTrue(verify_package(path, root, commit, receipt)["runtime_verification_passed"])
        for kind in ("empty", "omitted", "duplicate", "blob", "commit"):
            with self.subTest(mutation=kind), preserve(path):
                altered = copy.deepcopy(manifest)
                if kind == "empty": altered["entries"] = []
                elif kind == "omitted": altered["entries"].pop()
                elif kind == "duplicate": altered["entries"][-1] = altered["entries"][0]
                elif kind == "blob": altered["entries"][0]["git_blob_oid"] = "b"*40
                else: altered["source_commit"] = "b"*40
                path.write_text(json.dumps(altered), encoding="utf-8")
                with self.assertRaises(ValueError):
                    verify_package(path, root, commit, file_hash(path))
                with self.assertRaisesRegex(ValueError, "receipt hash mismatch"):
                    verify_package(path, root, commit, receipt)
        target = root / "scripts/run_n_frontend3b_background_suppression.py"
        with preserve(target):
            target.write_bytes(target.read_bytes()+b"\n# changed\n")
            with self.assertRaisesRegex(ValueError, "package bytes changed"):
                verify_package(path, root, commit, receipt)


if __name__ == "__main__":
    unittest.main()
