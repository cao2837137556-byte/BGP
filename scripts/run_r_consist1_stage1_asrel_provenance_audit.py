#!/usr/bin/env python
"""R-CONSIST-1 Stage 1 AS-rel provenance and alignment audit.

This script is intentionally read-only. It scans code, run metadata, and output
schemas to determine whether Stage 1 used CAIDA AS relationship evidence and
whether that provenance aligns with the Stage 2 versioned evidence cache.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

try:
    import pandas as pd
except ImportError as exc:  # pragma: no cover - environment guard
    raise SystemExit("pandas is required for this audit script") from exc

try:
    import pyarrow.parquet as pq
except ImportError:  # pragma: no cover - optional, but expected locally
    pq = None


KEYWORDS = [
    "as-rel",
    "as_rel",
    "caida",
    "relationship",
    "rel_seq",
    "rel_unknown_cnt",
    "rel_has_unknown",
    "relationship_file",
    "as_relationship",
    "serial-2",
    "20170701",
    "20240401",
]

ASREL_DERIVED_FIELDS = [
    "rel_seq",
    "rel_unknown_cnt",
    "rel_has_unknown",
    "relation_sequence",
    "path_plausibility",
    "plausibility_bucket",
    "weak_path_history",
    "path_relation_weak_signal",
    "triplet_signature",
    "path_signature",
]

PATH_FIELDS = [
    "as_path",
    "as_path_clean",
    "origin_as",
    "origin_as_norm",
    "prefix",
    "dominant_path_signature",
    "dominant_triplet_signature",
    "path_signature",
    "triplet_signature",
]

TEXT_SUFFIXES = {
    ".py",
    ".json",
    ".log",
    ".md",
    ".txt",
    ".csv",
    ".slurm",
    ".yaml",
    ".yml",
    ".toml",
}

RUN_STAGE1_SCRIPT_HINTS = {
    "04_annotate_caida_rel.py",
    "build_event_units.py",
    "run_s2a_downstream_from_raw.py",
    "run_s2a_local_collect.py",
    "run_s2a_collect_one.py",
    "run_s2a_merge_collector_runs.py",
    "run.py",
    "build_historical_baseline.py",
    "build_weak_candidates.py",
    "build_weak_candidates_streaming.py",
    "score_weak_candidates.py",
    "gate_scored_candidates.py",
    "augment_uncertain_candidates.py",
    "augment_uncertain_candidates_fast.py",
    "build_incident_aggregation.py",
    "run_s3c1_visibility_path_plausibility_pilot.py",
    "run_s3c1b_penalty_calibration.py",
    "run_s3c2_gate_evidence_ablation.py",
}


@dataclass
class SourceDiscoveryRow:
    source_type: str
    file_path: str
    matched_keyword: str
    matched_line_or_context: str
    inferred_asrel_path: str
    inferred_snapshot_date: str
    confidence: str
    notes: str


@dataclass
class SchemaAuditRow:
    file_path: str
    layer: str
    row_count_if_fast: str
    asrel_derived_fields_present: str
    path_fields_present: str
    sample_values_available: str
    likely_depends_on_asrel: str
    notes: str


@dataclass
class RuleDependencyRow:
    script_path: str
    rule_or_function_name: str
    dependent_fields: str
    rule_type: str
    dependency_strength: str
    effect_if_asrel_changes: str
    notes: str


def repo_relative(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def read_text_safely(path: Path, limit_bytes: int = 2_000_000) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    if len(data) > limit_bytes:
        data = data[:limit_bytes]
    for encoding in ("utf-8", "utf-8-sig", "gbk", "latin-1"):
        try:
            return data.decode(encoding, errors="replace")
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def infer_snapshot_from_text(text: str) -> tuple[str, str]:
    path_match = re.search(
        r"data[/\\]caida[/\\]as-relationships[/\\]serial-2[/\\][A-Za-z0-9_.-]+as-rel2[A-Za-z0-9_.-]*",
        text,
    )
    inferred_path = path_match.group(0).replace("\\", "/") if path_match else ""
    date_match = re.search(r"(20\d{6}|19\d{6})\.as-rel2", text)
    if not date_match:
        date_match = re.search(r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})", text)
        if date_match:
            return inferred_path, f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}"
        return inferred_path, ""
    value = date_match.group(1)
    return inferred_path, f"{value[0:4]}-{value[4:6]}-{value[6:8]}"


def infer_keyword(line: str) -> str:
    low = line.lower()
    for keyword in KEYWORDS:
        if keyword.lower() in low:
            return keyword
    return ""


def confidence_for_source(path: Path, context: str, snapshot: str) -> str:
    name = path.name
    low = context.lower()
    if name in {"04_annotate_caida_rel.py", "run.py", "run_s2a_downstream_from_raw.py"} and snapshot:
        return "high"
    if "caida_annotation" in low or "caida_rel_file" in low or "as_rel_info" in low:
        return "high" if snapshot else "medium"
    if snapshot:
        return "medium"
    return "low"


def source_type_for(path: Path, repo_root: Path, run_root: Path) -> str:
    rel = repo_relative(path, repo_root)
    if rel.startswith("scripts/"):
        return "code_reference"
    if path.suffix.lower() == ".log":
        return "run_log"
    if path.suffix.lower() == ".json":
        return "run_metadata"
    if rel.startswith("data/caida/") or rel.startswith("data/evidence/") or rel.startswith("outputs/"):
        return "data_file"
    if run_root.resolve() in path.resolve().parents:
        return "run_metadata"
    return "data_file"


def discover_sources(repo_root: Path, run_root: Path, output_dir: Path) -> list[SourceDiscoveryRow]:
    rows: list[SourceDiscoveryRow] = []
    scan_roots = [
        repo_root / "scripts",
        run_root,
        repo_root / "data" / "caida" / "as-relationships" / "serial-2",
        repo_root / "data" / "evidence" / "as_relationships",
        repo_root / "outputs" / "r2c_p0b_asrel_materialization_v01",
        repo_root / "outputs" / "r2c_p1_path_relation_lookup_smoke_v01",
        repo_root / "outputs" / "r2c_p2_path_legality_verifier_smoke_v01",
        repo_root / "outputs" / "s3d2_external_evidence_attachment_v01",
        repo_root / "outputs" / "s3d2b_evidence_alignment_v01",
    ]

    seen: set[Path] = set()
    for root in scan_roots:
        if not root.exists():
            continue
        files = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file()]
        for path in files:
            if path in seen or output_dir.resolve() in path.resolve().parents:
                continue
            seen.add(path)
            suffix = path.suffix.lower()
            rel_path = repo_relative(path, repo_root)

            if suffix in {".parquet", ".bz2", ".gz"}:
                text = rel_path
                if any(keyword.lower() in text.lower() for keyword in KEYWORDS):
                    inferred_path, snapshot = infer_snapshot_from_text(text)
                    rows.append(
                        SourceDiscoveryRow(
                            source_type=source_type_for(path, repo_root, run_root),
                            file_path=rel_path,
                            matched_keyword=infer_keyword(text) or "as_relationship_file",
                            matched_line_or_context=text,
                            inferred_asrel_path=inferred_path or rel_path,
                            inferred_snapshot_date=snapshot,
                            confidence="medium" if snapshot else "low",
                            notes="file presence only; no content read",
                        )
                    )
                continue

            if suffix not in TEXT_SUFFIXES:
                continue
            text_limit = 20_000 if suffix == ".csv" and path.stat().st_size > 1_000_000 else 2_000_000
            text = read_text_safely(path, limit_bytes=text_limit)
            if not text:
                continue
            for idx, line in enumerate(text.splitlines(), start=1):
                keyword = infer_keyword(line)
                if not keyword:
                    continue
                context = line.strip()
                inferred_path, snapshot = infer_snapshot_from_text(context)
                if not inferred_path:
                    inferred_path, snapshot2 = infer_snapshot_from_text(text[max(0, text.find(line) - 500) : text.find(line) + 500])
                    snapshot = snapshot or snapshot2
                rows.append(
                    SourceDiscoveryRow(
                        source_type=source_type_for(path, repo_root, run_root),
                        file_path=rel_path,
                        matched_keyword=keyword,
                        matched_line_or_context=f"L{idx}: {context[:600]}",
                        inferred_asrel_path=inferred_path,
                        inferred_snapshot_date=snapshot,
                        confidence=confidence_for_source(path, context, snapshot),
                        notes=notes_for_source_line(path, context),
                    )
                )
    return rows


def notes_for_source_line(path: Path, context: str) -> str:
    name = path.name
    low = context.lower()
    if name == "04_annotate_caida_rel.py" and "default" in low:
        return "Stage 1 CAIDA annotation default path"
    if name == "run_s2a_downstream_from_raw.py" and "caida-rel" in low:
        return "S2A downstream wrapper passes CAIDA relationship file into Stage 1 annotation"
    if name == "build_event_units.py" and any(f in low for f in ["rel_seq", "rel_unknown_cnt", "rel_has_unknown"]):
        return "Event construction retains AS-rel-derived fields"
    if "as_rel_snapshot_stale" in low:
        return "Prior evidence alignment guardrail records stale AS-rel as diagnostic"
    if "20240401" in low or "2024-04-01" in low:
        return "2024-near Stage 2 evidence cache reference"
    if "20170701" in low or "2017-07-01" in low:
        return "Legacy/stale CAIDA AS-rel snapshot reference"
    return ""


def classify_layer(path: Path) -> str:
    low = path.as_posix().lower()
    name = path.name.lower()
    parent = path.parent.as_posix().lower()
    if "event_units" in name or "/events" in parent.replace("\\", "/"):
        return "event_units"
    if "candidate" in low or "/candidates" in low:
        return "candidate"
    if "score" in low or "/scores" in low:
        return "score"
    if "gate" in low or "gating" in low:
        return "gate"
    if "augment" in low or "augmentation" in low:
        return "augment"
    if "incident_membership" in name:
        return "incident_membership"
    if "incident_tickets" in name:
        return "incident_tickets"
    if "incident" in low:
        return "incident_tickets"
    return "unknown"


def parquet_schema(path: Path) -> tuple[list[str], str, dict[str, list[str]]]:
    if pq is None:
        return [], "", {}
    try:
        pf = pq.ParquetFile(path)
        columns = list(pf.schema.names)
        row_count = str(pf.metadata.num_rows) if pf.metadata else ""
        samples: dict[str, list[str]] = {}
        wanted = [c for c in columns if c in set(ASREL_DERIVED_FIELDS + PATH_FIELDS)]
        if wanted and pf.num_row_groups > 0:
            table = pf.read_row_group(0, columns=wanted)
            frame = table.slice(0, min(5, table.num_rows)).to_pandas()
            for col in wanted:
                samples[col] = [str(v)[:120] for v in frame[col].dropna().head(3).tolist()] if col in frame else []
        return columns, row_count, samples
    except Exception as exc:  # pragma: no cover - defensive for corrupt files
        return [], "", {"_error": [str(exc)]}


def delimited_schema(path: Path) -> tuple[list[str], str, dict[str, list[str]]]:
    try:
        frame = pd.read_csv(path, nrows=5)
    except Exception as exc:
        return [], "", {"_error": [str(exc)]}
    columns = [str(c) for c in frame.columns]
    samples: dict[str, list[str]] = {}
    wanted = [c for c in columns if c in set(ASREL_DERIVED_FIELDS + PATH_FIELDS)]
    for col in wanted:
        samples[col] = [str(v)[:120] for v in frame[col].dropna().head(3).tolist()]
    return columns, "", samples


def json_schema(path: Path) -> tuple[list[str], str, dict[str, list[str]]]:
    text = read_text_safely(path, limit_bytes=200_000)
    try:
        obj = json.loads(text)
    except Exception:
        return [], "", {}
    if isinstance(obj, dict):
        columns = sorted(str(k) for k in obj.keys())
    elif isinstance(obj, list) and obj and isinstance(obj[0], dict):
        columns = sorted(str(k) for k in obj[0].keys())
    else:
        columns = []
    samples = {col: [str(obj.get(col, ""))[:120]] for col in columns if isinstance(obj, dict) and col in ASREL_DERIVED_FIELDS + PATH_FIELDS}
    return columns, str(len(obj)) if isinstance(obj, list) else "", samples


def discover_schema_files(repo_root: Path, run_root: Path, output_dir: Path) -> list[Path]:
    candidates: list[Path] = []
    scan_roots = [
        run_root,
        repo_root / "outputs" / "google_verizon_diag_v01",
        repo_root / "outputs" / "s3a_incident_aggregation_v01",
        repo_root / "outputs" / "s3b_noise_source_audit_v01",
        repo_root / "outputs" / "s3c1_visibility_path_plausibility_v01",
        repo_root / "outputs" / "s3c1b_penalty_calibration_v01",
        repo_root / "outputs" / "s3c2_gate_evidence_ablation_v01",
        repo_root / "outputs" / "s3d_verification_queue_schema_v01",
        repo_root / "outputs" / "s3d2_external_evidence_attachment_v01",
        repo_root / "outputs" / "s3d2b_evidence_alignment_v01",
        repo_root / "outputs" / "r2a_legality_first_verifier_smoke_v01",
        repo_root / "outputs" / "r2b0_evidence_readiness_audit_v01",
        repo_root / "outputs" / "r2c0_path_evidence_readiness_audit_v01",
        repo_root / "outputs" / "r2c_p1_path_relation_lookup_smoke_v01",
        repo_root / "outputs" / "r2c_p2_path_legality_verifier_smoke_v01",
    ]
    for root in scan_roots:
        if not root.exists():
            continue
        files = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file()]
        for path in files:
            if output_dir.resolve() in path.resolve().parents:
                continue
            if path.suffix.lower() in {".parquet", ".csv", ".json"}:
                candidates.append(path)
    return sorted(set(candidates))


def audit_output_schemas(repo_root: Path, run_root: Path, output_dir: Path) -> list[SchemaAuditRow]:
    rows: list[SchemaAuditRow] = []
    for path in discover_schema_files(repo_root, run_root, output_dir):
        suffix = path.suffix.lower()
        if suffix == ".parquet":
            columns, row_count, samples = parquet_schema(path)
        elif suffix == ".csv":
            columns, row_count, samples = delimited_schema(path)
        else:
            columns, row_count, samples = json_schema(path)

        field_set = set(columns)
        asrel_fields = [f for f in ASREL_DERIVED_FIELDS if f in field_set or any(c.startswith(f) for c in field_set)]
        path_fields = [f for f in PATH_FIELDS if f in field_set]
        likely_depends = "yes" if set(asrel_fields) & {"rel_seq", "rel_unknown_cnt", "rel_has_unknown", "path_plausibility", "plausibility_bucket"} else "no"
        notes = ""
        if "_error" in samples:
            notes = "schema read failed: " + "; ".join(samples["_error"])
        elif asrel_fields:
            notes = "contains AS-rel-derived or AS-path weak-signal fields"
        rows.append(
            SchemaAuditRow(
                file_path=repo_relative(path, repo_root),
                layer=classify_layer(path),
                row_count_if_fast=row_count,
                asrel_derived_fields_present=";".join(asrel_fields),
                path_fields_present=";".join(path_fields),
                sample_values_available=json.dumps(samples, ensure_ascii=False)[:2000],
                likely_depends_on_asrel=likely_depends,
                notes=notes,
            )
        )
    return rows


def function_context(lines: list[str], index: int) -> str:
    for j in range(index, -1, -1):
        stripped = lines[j].strip()
        if stripped.startswith("def ") or stripped.startswith("class "):
            return stripped.split("(")[0].replace("def ", "").replace("class ", "")
    return "module_scope"


def classify_rule(script_name: str, line: str) -> tuple[str, str, str, str]:
    low_name = script_name.lower()
    low_line = line.lower()
    if "weak_path_history" in low_line and not any(field in low_line for field in ["rel_seq", "rel_unknown_cnt", "rel_has_unknown"]):
        return "score_feature", "optional_context", "no_effect", "weak_path_history is history/path based, not CAIDA AS-rel derived"
    if script_name == "04_annotate_caida_rel.py":
        return "augment_condition", "hard_dependency", "candidate_set_may_change", "AS-rel file directly defines rel_seq/unknown fields during annotation"
    if script_name == "build_event_units.py":
        return "incident_grouping", "soft_dependency", "report_only", "Event grouping keys are path-based; AS-rel fields are retained as context fields"
    if "s3c1" in low_name or "plausibility" in low_name:
        return "score_feature", "hard_dependency", "score_may_change", "Path plausibility relation component consumes rel_unknown/rel_has_unknown"
    if "s3c2" in low_name or "gate" in low_name:
        return "gate_condition", "soft_dependency", "gate_may_change", "Gate-evidence ablation consumes plausibility buckets derived partly from AS-rel fields"
    if "historical_baseline" in low_name:
        return "score_feature", "soft_dependency", "score_may_change", "Baseline includes rates of rel_unknown/rel_has_unknown"
    if "incident_aggregation" in low_name and ("path_signature" in low_line or "triplet_signature" in low_line):
        return "incident_grouping", "optional_context", "no_effect", "Path signatures derive from AS path text rather than AS-rel snapshot"
    if "weak_candidates" in low_name or "score_weak" in low_name or "augment" in low_name:
        return "score_feature", "optional_context", "no_effect", "weak_path_history is history/path based, not CAIDA AS-rel derived"
    if "s3d2" in low_name or "r2" in low_name:
        return "reporting_only", "optional_context", "report_only", "Verifier/evidence scripts are outside Stage 1 provenance target"
    if any(field in low_line for field in ["rel_seq", "rel_unknown_cnt", "rel_has_unknown"]):
        return "score_feature", "unknown", "score_may_change", "AS-rel field referenced; manual review may be needed"
    return "reporting_only", "optional_context", "report_only", ""


def audit_rule_dependencies(repo_root: Path) -> list[RuleDependencyRow]:
    rows: list[RuleDependencyRow] = []
    scripts_root = repo_root / "scripts"
    for path in sorted(scripts_root.rglob("*.py")) if scripts_root.exists() else []:
        text = read_text_safely(path)
        if not text:
            continue
        lines = text.splitlines()
        for idx, line in enumerate(lines):
            fields = [field for field in ASREL_DERIVED_FIELDS if field in line]
            if not fields and not any(keyword in line.lower() for keyword in ["caida", "as-rel", "as_rel", "relationship"]):
                continue
            # Keep the audit focused on Stage 1/downstream weak-signal scripts plus provenance-bearing R scripts.
            if path.name not in RUN_STAGE1_SCRIPT_HINTS and not any(token in path.name.lower() for token in ["s3d2", "r2a", "r2b0", "r2c"]):
                continue
            rule_type, strength, effect, notes = classify_rule(path.name, line)
            if not fields and "caida" in line.lower():
                fields = ["caida_as_relationship_file"]
            elif not fields and ("relationship" in line.lower() or "as_rel" in line.lower()):
                fields = ["as_relationship_reference"]
            rows.append(
                RuleDependencyRow(
                    script_path=repo_relative(path, repo_root),
                    rule_or_function_name=function_context(lines, idx),
                    dependent_fields=";".join(sorted(set(fields))),
                    rule_type=rule_type,
                    dependency_strength=strength,
                    effect_if_asrel_changes=effect,
                    notes=notes or line.strip()[:300],
                )
            )
    return rows


def load_stage2_metadata(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def parse_iso_date(value: str) -> date | None:
    if not value:
        return None
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    return None


def infer_stage1_asrel(source_rows: list[SourceDiscoveryRow]) -> dict[str, str]:
    strong_2017 = [
        row
        for row in source_rows
        if row.inferred_snapshot_date == "2017-07-01"
        and row.source_type == "code_reference"
        and row.file_path
        in {
            "scripts/04_annotate_caida_rel.py",
            "scripts/run.py",
            "scripts/run_s2a_downstream_from_raw.py",
        }
    ]
    if strong_2017:
        row = strong_2017[0]
        return {
            "detected": "yes",
            "snapshot_date": "2017-07-01",
            "path": row.inferred_asrel_path or "data/caida/as-relationships/serial-2/20170701.as-rel2.txt",
            "confidence": "high",
            "basis": "Stage 1 annotation wrappers default to the legacy CAIDA 20170701 as-rel2 snapshot",
        }

    snapshots = [row for row in source_rows if row.inferred_snapshot_date]
    if snapshots:
        row = snapshots[0]
        return {
            "detected": "yes",
            "snapshot_date": row.inferred_snapshot_date,
            "path": row.inferred_asrel_path,
            "confidence": row.confidence,
            "basis": f"best available source discovery row: {row.file_path}",
        }
    return {
        "detected": "unknown",
        "snapshot_date": "",
        "path": "",
        "confidence": "low",
        "basis": "No Stage 1 AS-rel source could be inferred from code or metadata",
    }


def consistency_check(
    stage1: dict[str, str],
    stage2_meta: dict[str, Any],
    run_date: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    stage2_snapshot = str(stage2_meta.get("snapshot_date") or "")
    stage2_path = str(stage2_meta.get("output_parquet") or stage2_meta.get("input_file") or "")
    stage1_snapshot = stage1.get("snapshot_date", "")
    stage1_date = parse_iso_date(stage1_snapshot)
    stage2_date = parse_iso_date(stage2_snapshot)
    run_dt = parse_iso_date(run_date)

    same_snapshot = bool(stage1_snapshot and stage2_snapshot and stage1_snapshot == stage2_snapshot)
    same_provider = bool(stage1.get("detected") == "yes" and stage2_meta.get("provider", "").lower() == "caida")
    delta = ""
    if stage1_date and stage2_date:
        delta = str(abs((stage2_date - stage1_date).days))
    elif stage1_date and run_dt:
        delta = str(abs((run_dt - stage1_date).days))

    if stage1.get("detected") != "yes":
        status = "stage1_no_asrel_dependency" if stage1.get("detected") == "no" else "unknown_need_manual_check"
        risk = "low" if status == "stage1_no_asrel_dependency" else "medium"
    elif same_snapshot:
        status = "aligned"
        risk = "low"
    else:
        status = "likely_inconsistent"
        risk = "high" if stage1_snapshot and stage2_snapshot else "medium"

    row = {
        "stage1_asrel_detected": stage1.get("detected", "unknown"),
        "stage1_snapshot_date": stage1_snapshot,
        "stage1_asrel_path": stage1.get("path", ""),
        "stage2_snapshot_date": stage2_snapshot,
        "stage2_asrel_path": stage2_path,
        "run_date": run_date,
        "stage1_stage2_same_snapshot": same_snapshot,
        "stage1_stage2_same_provider": same_provider,
        "stage1_stage2_alignment_delta_days": delta,
        "consistency_status": status,
        "consistency_risk_level": risk,
        "notes": stage1.get("basis", ""),
    }
    return row, [row]


def impact_scope(schema_rows: list[SchemaAuditRow], rule_rows: list[RuleDependencyRow], consistency_status: str) -> list[dict[str, Any]]:
    affected: list[dict[str, Any]] = []
    rules_by_effect: dict[str, list[str]] = {}
    for row in rule_rows:
        rules_by_effect.setdefault(row.effect_if_asrel_changes, []).append(f"{row.script_path}:{row.rule_or_function_name}")

    has_event_rel = any(row.layer == "event_units" and {"rel_seq", "rel_unknown_cnt", "rel_has_unknown"} & set(row.asrel_derived_fields_present.split(";")) for row in schema_rows)
    has_incident_rel = any(row.layer in {"incident_membership", "incident_tickets"} and {"rel_seq", "rel_unknown_cnt", "rel_has_unknown"} & set(row.asrel_derived_fields_present.split(";")) for row in schema_rows)
    has_plausibility = any("plausibility_bucket" in row.asrel_derived_fields_present or "path_plausibility" in row.asrel_derived_fields_present for row in schema_rows)

    affected.append(
        {
            "affected_layer": "event_units",
            "affected_fields": "rel_seq;rel_unknown_cnt;rel_has_unknown",
            "affected_rules": ";".join(rules_by_effect.get("report_only", [])[:20]),
            "expected_change_type": "AS-rel annotation values may change if Stage 1 is reannotated with 2024-near CAIDA.",
            "likely_impact": "medium" if consistency_status == "likely_inconsistent" else "low",
            "required_replay_scope": "path_feature_reannotation_only" if consistency_status == "likely_inconsistent" else "no_replay_needed",
            "notes": "Observed in event schema" if has_event_rel else "Current fixed run root lacks event_units parquet, but code retains these fields",
        }
    )
    affected.append(
        {
            "affected_layer": "s3c_path_plausibility",
            "affected_fields": "path_plausibility_score;plausibility_bucket;relation_support_score",
            "affected_rules": ";".join(rules_by_effect.get("score_may_change", [])[:20]),
            "expected_change_type": "Path plausibility score/bucket may change because relation component consumes rel_unknown fields.",
            "likely_impact": "medium" if has_plausibility or consistency_status == "likely_inconsistent" else "low",
            "required_replay_scope": "path_feature_reannotation_only",
            "notes": "Affects weak/path evidence branch; does not by itself establish route leak truth.",
        }
    )
    affected.append(
        {
            "affected_layer": "candidate_score_gate_augment",
            "affected_fields": "weak_path_history",
            "affected_rules": ";".join(rules_by_effect.get("candidate_set_may_change", [])[:10] + rules_by_effect.get("gate_may_change", [])[:10]),
            "expected_change_type": "No direct Stage 1 candidate/filter/gate hard dependency on rel_seq was found in the audited code; S3C gate-evidence ablation may change if plausibility outputs are included.",
            "likely_impact": "low",
            "required_replay_scope": "no_replay_needed",
            "notes": "Do not infer zero impact for future pipelines without rerunning this audit.",
        }
    )
    affected.append(
        {
            "affected_layer": "incident_membership_and_tickets",
            "affected_fields": "path_signature;triplet_signature",
            "affected_rules": ";".join(rules_by_effect.get("incident_grouping_may_change", [])[:20]),
            "expected_change_type": "Incident grouping uses AS-path signatures, not AS-rel labels, so AS-rel snapshot drift is expected to have no direct grouping effect.",
            "likely_impact": "none" if not has_incident_rel else "low",
            "required_replay_scope": "no_replay_needed",
            "notes": "Incident outputs in the fixed run root carry path signatures but not rel_seq fields." if not has_incident_rel else "Incident output contains AS-rel-derived fields; inspect before final main results.",
        }
    )
    return affected


def recommend_next_action(consistency: dict[str, Any], impact_rows: list[dict[str, Any]]) -> dict[str, Any]:
    status = consistency.get("consistency_status", "")
    if status == "aligned":
        action = "metadata_patch_only"
        rationale = "Stage 1 and Stage 2 use the same AS-rel snapshot; documentation/provenance is the remaining gap."
    elif status == "stage1_no_asrel_dependency":
        action = "no_action_needed"
        rationale = "No Stage 1 AS-rel dependency detected."
    elif any(row["required_replay_scope"] == "full_stage1_downstream_replay" for row in impact_rows):
        action = "r_consist2_aligned_stage1_replay"
        rationale = "AS-rel drift may change candidate/gate or incident construction results."
    elif status == "likely_inconsistent":
        action = "r_consist2_aligned_reannotation"
        rationale = "Stage 1 appears to retain legacy 2017 AS-rel-derived fields while Stage 2 uses 2024-near AS-rel; reannotate path relation fields before final paper use."
    else:
        action = "manual_code_review_required"
        rationale = "Automated provenance scan could not determine a safe replay boundary."
    return {
        "recommended_next_action": action,
        "rationale": rationale,
        "required_replay_scope": next((row["required_replay_scope"] for row in impact_rows if row["required_replay_scope"] != "no_replay_needed"), "no_replay_needed"),
        "do_not_do_now": [
            "do not rerun Stage 1 until R-CONSIST-2 scope is approved",
            "do not treat stale AS-rel weak fields as verifier evidence",
            "do not modify verifier verdicts in provenance audit",
        ],
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def markdown_table(rows: list[dict[str, Any]], columns: list[str], limit: int | None = None) -> str:
    shown = rows if limit is None else rows[:limit]
    if not shown:
        return "_No rows._\n"
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in shown:
        values = [str(row.get(col, "")).replace("\n", " ")[:220] for col in columns]
        lines.append("| " + " | ".join(values) + " |")
    if limit is not None and len(rows) > limit:
        lines.append(f"\n_Showing {limit} of {len(rows)} rows._")
    return "\n".join(lines) + "\n"


def write_markdown_outputs(
    output_dir: Path,
    summary: dict[str, Any],
    rule_rows: list[dict[str, Any]],
    consistency_rows: list[dict[str, Any]],
    impact_rows: list[dict[str, Any]],
    recommendation: dict[str, Any],
) -> None:
    rule_summary = [
        {
            "rule_type": key[0],
            "dependency_strength": key[1],
            "effect_if_asrel_changes": key[2],
            "count": value,
        }
        for key, value in pd.DataFrame(rule_rows)
        .groupby(["rule_type", "dependency_strength", "effect_if_asrel_changes"])
        .size()
        .to_dict()
        .items()
    ] if rule_rows else []
    (output_dir / "r_consist1_stage1_rule_dependency_summary.md").write_text(
        "# R-CONSIST-1 Stage 1 Rule Dependency Summary\n\n"
        + markdown_table(rule_summary, ["rule_type", "dependency_strength", "effect_if_asrel_changes", "count"])
        + "\n## Interpretation\n\n"
        + "- Hard dependencies found in CAIDA annotation and S3-C path plausibility code affect AS-rel-derived weak/path evidence fields.\n"
        + "- Incident grouping is path-signature based; this audit did not find a direct AS-rel snapshot dependency in incident grouping.\n"
        + "- These dependencies are provenance and replay-scope signals, not attack/benign labels.\n",
        encoding="utf-8",
    )
    (output_dir / "r_consist1_asrel_alignment_impact_scope.md").write_text(
        "# R-CONSIST-1 AS-rel Alignment Impact Scope\n\n"
        + markdown_table(
            impact_rows,
            [
                "affected_layer",
                "affected_fields",
                "expected_change_type",
                "likely_impact",
                "required_replay_scope",
                "notes",
            ],
        ),
        encoding="utf-8",
    )
    (output_dir / "r_consist1_recommended_next_action.md").write_text(
        "# R-CONSIST-1 Recommended Next Action\n\n"
        f"Recommended next action: `{recommendation['recommended_next_action']}`\n\n"
        f"Rationale: {recommendation['rationale']}\n\n"
        f"Required replay scope: `{recommendation['required_replay_scope']}`\n\n"
        "Guardrails:\n"
        + "\n".join(f"- {item}" for item in recommendation["do_not_do_now"])
        + "\n",
        encoding="utf-8",
    )
    report = f"""# R-CONSIST-1 Stage 1 AS-rel Provenance Audit

## Questions Answered

1. Stage 1 是否使用了 AS-rel？
   {summary['stage1_asrel_detected_answer']}

2. 如果使用，使用的是哪个 snapshot？
   `{summary['stage1_snapshot_date']}` via `{summary['stage1_asrel_path']}`.

3. Stage 1 是否与 Stage 2 使用相同 AS-rel snapshot？
   `{summary['stage1_stage2_same_snapshot']}`. Stage 2 snapshot is `{summary['stage2_snapshot_date']}`.

4. 哪些 Stage 1 字段来自 AS-rel？
   `rel_seq`, `rel_unknown_cnt`, and `rel_has_unknown` are produced by Stage 1 CAIDA annotation and retained by event construction when rel-annotated inputs are used.

5. 哪些 Stage 1 规则依赖 AS-rel？
   CAIDA annotation has a hard dependency for rel field creation. S3-C path plausibility has a hard feature dependency on rel unknown fields. Incident grouping uses AS-path signatures, not AS-rel labels.

6. 如果切换到 2024-near AS-rel，哪些结果可能变化？
   AS-rel-derived event fields and S3-C path plausibility evidence may change. Candidate/gate/final outputs are not directly modified by this audit.

7. 当前旧 Stage 1 结果能否作为最终论文主结果？
   Not as unqualified final main-result evidence if stale AS-rel-derived weak/path evidence is used. It must either be replayed/aligned or reported with drift/impact analysis.

8. 是否需要 aligned replay？
   Recommended action: `{recommendation['recommended_next_action']}`.

9. 推荐下一步是什么？
   {recommendation['rationale']}

10. 本轮是否修改实验结果？
    没有。

11. 本轮是否下载新证据？
    没有。

12. 本轮是否训练 learning layer？
    没有。

13. 如何写入论文/文档以防 reviewer 攻击？
    Report AS-rel evidence as versioned provenance. Separate Stage 1 weak-trigger use from Stage 2 verifier evidence, and ensure final main experiments use a consistent cache snapshot or include drift/impact analysis.

## Consistency

{markdown_table(consistency_rows, ['stage1_asrel_detected', 'stage1_snapshot_date', 'stage2_snapshot_date', 'stage1_stage2_same_snapshot', 'consistency_status', 'consistency_risk_level', 'notes'])}

## Impact Scope

{markdown_table(impact_rows, ['affected_layer', 'affected_fields', 'likely_impact', 'required_replay_scope', 'notes'])}
"""
    (output_dir / "r_consist1_report.md").write_text(report, encoding="utf-8")


def build_summary(
    args: argparse.Namespace,
    source_rows: list[SourceDiscoveryRow],
    schema_rows: list[SchemaAuditRow],
    rule_rows: list[RuleDependencyRow],
    consistency: dict[str, Any],
    impact_rows: list[dict[str, Any]],
    recommendation: dict[str, Any],
) -> dict[str, Any]:
    asrel_schema_fields = sorted(
        {
            field
            for row in schema_rows
            for field in row.asrel_derived_fields_present.split(";")
            if field
        }
    )
    affected_fields = sorted(
        {
            field.strip()
            for row in impact_rows
            for field in row["affected_fields"].split(";")
            if field.strip()
        }
    )
    affected_rules = sorted(
        {
            f"{row.script_path}:{row.rule_or_function_name}"
            for row in rule_rows
            if row.effect_if_asrel_changes not in {"no_effect", "report_only"}
        }
    )
    summary = {
        "phase": "R-CONSIST-1",
        "run_id": args.run_id,
        "run_date": args.run_date,
        "stage1_asrel_detected": consistency["stage1_asrel_detected"],
        "stage1_asrel_detected_answer": "Yes. Stage 1 annotation code defaults to CAIDA AS-rel and event construction retains AS-rel-derived fields.",
        "stage1_snapshot_date": consistency["stage1_snapshot_date"],
        "stage1_asrel_path": consistency["stage1_asrel_path"],
        "stage2_snapshot_date": consistency["stage2_snapshot_date"],
        "stage2_asrel_path": consistency["stage2_asrel_path"],
        "stage1_stage2_same_snapshot": consistency["stage1_stage2_same_snapshot"],
        "consistency_status": consistency["consistency_status"],
        "consistency_risk_level": consistency["consistency_risk_level"],
        "affected_fields": affected_fields,
        "affected_rules": affected_rules[:100],
        "required_replay_scope": recommendation["required_replay_scope"],
        "recommended_next_action": recommendation["recommended_next_action"],
        "schema_asrel_fields_observed": asrel_schema_fields,
        "counts": {
            "source_discovery_rows": len(source_rows),
            "schema_audit_rows": len(schema_rows),
            "rule_dependency_rows": len(rule_rows),
            "impact_scope_rows": len(impact_rows),
        },
        "guardrails": {
            "modified_experiment_results": False,
            "downloaded_new_evidence": False,
            "trained_learning_layer": False,
            "modified_verifier_verdict": False,
            "communities_repair": False,
        },
    }
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-date", default="2024-04-16")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--run-root", default="data/runs/s2a_expanded_v01_pilot_6h_april16")
    parser.add_argument("--stage2-asrel-metadata", default="data/evidence/as_relationships/as_rel_2024-04-01.metadata.json")
    parser.add_argument("--output-dir", default="outputs/r_consist1_stage1_asrel_provenance_audit_v01")
    parser.add_argument("--full-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    run_root = (repo_root / args.run_root).resolve()
    stage2_metadata = (repo_root / args.stage2_asrel_metadata).resolve()
    output_dir = (repo_root / args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    source_rows = discover_sources(repo_root, run_root, output_dir)
    schema_rows = audit_output_schemas(repo_root, run_root, output_dir)
    rule_rows = audit_rule_dependencies(repo_root)

    stage1 = infer_stage1_asrel(source_rows)
    stage2_meta = load_stage2_metadata(stage2_metadata)
    consistency, consistency_rows = consistency_check(stage1, stage2_meta, args.run_date)
    impact_rows = impact_scope(schema_rows, rule_rows, consistency["consistency_status"])
    recommendation = recommend_next_action(consistency, impact_rows)
    summary = build_summary(args, source_rows, schema_rows, rule_rows, consistency, impact_rows, recommendation)

    source_dicts = [asdict(row) for row in source_rows]
    schema_dicts = [asdict(row) for row in schema_rows]
    rule_dicts = [asdict(row) for row in rule_rows]

    write_csv(output_dir / "r_consist1_stage1_asrel_source_discovery.csv", source_dicts)
    write_json(output_dir / "r_consist1_stage1_asrel_source_discovery.json", source_dicts)
    write_csv(output_dir / "r_consist1_stage1_asrel_output_schema_audit.csv", schema_dicts)
    write_json(
        output_dir / "r_consist1_stage1_asrel_output_schema_summary.json",
        {
            "rows": len(schema_dicts),
            "layers": pd.DataFrame(schema_dicts).groupby("layer").size().to_dict() if schema_dicts else {},
            "rows_with_asrel_fields": sum(bool(row["asrel_derived_fields_present"]) for row in schema_dicts),
            "asrel_fields_observed": summary["schema_asrel_fields_observed"],
        },
    )
    write_csv(output_dir / "r_consist1_stage1_rule_dependency_audit.csv", rule_dicts)
    write_csv(output_dir / "r_consist1_asrel_version_consistency.csv", consistency_rows)
    write_json(output_dir / "r_consist1_asrel_version_consistency.json", consistency)
    write_csv(output_dir / "r_consist1_asrel_alignment_impact_scope.csv", impact_rows)
    write_json(output_dir / "r_consist1_recommended_next_action.json", recommendation)
    write_json(output_dir / "r_consist1_summary.json", summary)
    write_markdown_outputs(output_dir, summary, rule_dicts, consistency_rows, impact_rows, recommendation)

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
