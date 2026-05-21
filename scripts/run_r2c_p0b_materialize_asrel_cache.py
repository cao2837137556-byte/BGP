#!/usr/bin/env python3
"""R-2C-P0b 2024-near CAIDA AS relationship cache materialization.

This script materializes a local AS relationship evidence cache and runs a
lookup smoke over R-2C-0 AS-pair targets. It does not produce route-leak
verdicts, modify verifier verdicts, train models, or run poisoning tests.
"""

from __future__ import annotations

import argparse
import bz2
import hashlib
import json
import shutil
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


RUN_ID_DEFAULT = "s2a_expanded_v01_pilot_6h_april16"
RUN_DATE_DEFAULT = "2024-04-16"
SNAPSHOT_DATE_DEFAULT = "2024-04-01"
OUTPUT_DIR_DEFAULT = "outputs/r2c_p0b_asrel_materialization_v01"
EVIDENCE_OUTPUT_DIR_DEFAULT = "data/evidence/as_relationships"
DEFAULT_PAIR_TARGETS = "outputs/r2c0_path_evidence_readiness_audit_v01/r2c_as_pair_targets.parquet"

CAIDA_SOURCE_URLS = [
    "https://data.caida.org/datasets/as-relationships/serial-2/{yyyymmdd}.as-rel2.txt.bz2",
    "https://publicdata.caida.org/datasets/as-relationships/serial-2/{yyyymmdd}.as-rel2.txt.bz2",
]

HARD_SAFETY_NOTES = [
    "inferred AS relationships are not ground truth",
    "AS-rel violation is not confirmed route leak",
    "AS-rel path legality is not benign",
    "stale or future snapshots cannot be used as strong evidence",
    "use AS-rel only as path evidence with provenance",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=RUN_ID_DEFAULT)
    parser.add_argument("--run-date", default=RUN_DATE_DEFAULT)
    parser.add_argument("--snapshot-date", default=SNAPSHOT_DATE_DEFAULT)
    parser.add_argument("--output-dir", default=OUTPUT_DIR_DEFAULT)
    parser.add_argument("--evidence-output-dir", default=EVIDENCE_OUTPUT_DIR_DEFAULT)
    parser.add_argument(
        "--download-mode",
        default="auto",
        choices=["auto", "existing_file", "source_url", "manual_required"],
    )
    parser.add_argument("--source-url", default="")
    parser.add_argument("--existing-asrel-file", default="")
    parser.add_argument("--pair-targets-file", default=DEFAULT_PAIR_TARGETS)
    parser.add_argument("--full-run", action="store_true")
    parser.add_argument("--no-commit-large-outputs", action="store_true", default=True)
    return parser.parse_args()


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, (datetime, date, pd.Timestamp, Path)):
        return str(value)
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=json_default), encoding="utf-8")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def date_delta_days(snapshot_date: str, run_date: str) -> int:
    try:
        return (date.fromisoformat(run_date) - date.fromisoformat(snapshot_date)).days
    except Exception:
        return 999999


def yyyymmdd(snapshot_date: str) -> str:
    return snapshot_date.replace("-", "")


def output_names(evidence_dir: Path, snapshot_date: str) -> dict[str, Path]:
    stem = f"as_rel_{snapshot_date}"
    return {
        "parquet": evidence_dir / f"{stem}.parquet",
        "csv": evidence_dir / f"{stem}.csv",
        "metadata": evidence_dir / f"{stem}.metadata.json",
    }


def local_raw_candidates(snapshot_date: str) -> list[Path]:
    ymd = yyyymmdd(snapshot_date)
    return [
        Path("data/caida/as-relationships/serial-2") / f"{ymd}.as-rel2.txt.bz2",
        Path("data/caida/as-relationships/serial-2") / f"{ymd}.as-rel2.txt",
    ]


def download_url(url: str, dest: Path, timeout: int = 120) -> dict[str, Any]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Veritas-BGP-R2C-P0b/1.0"})
    started = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as response:
        content_type = response.headers.get("Content-Type", "")
        status = getattr(response, "status", None)
        with dest.open("wb") as out:
            shutil.copyfileobj(response, out)
    return {
        "url": url,
        "path": str(dest),
        "status": status,
        "content_type": content_type,
        "bytes": dest.stat().st_size,
        "sha256": sha256_file(dest),
        "elapsed_sec": time.time() - started,
    }


def discover_source(args: argparse.Namespace, evidence_dir: Path, out_dir: Path) -> dict[str, Any]:
    names = output_names(evidence_dir, args.snapshot_date)
    if names["parquet"].exists() and names["metadata"].exists():
        return {
            "status": "normalized_cache_exists",
            "input_file": str(names["parquet"]),
            "source_url": "",
            "normalized_exists": True,
            "manual_required": False,
            "download_attempts": [],
        }

    if args.download_mode == "manual_required":
        return manual_required(args, [], "download-mode manual_required")

    if args.download_mode == "existing_file":
        if not args.existing_asrel_file:
            return manual_required(args, [], "--existing-asrel-file required for existing_file mode")
        p = Path(args.existing_asrel_file)
        if not p.exists():
            return manual_required(args, [], f"existing file missing: {p}")
        return {
            "status": "existing_file",
            "input_file": str(p),
            "source_url": "",
            "normalized_exists": False,
            "manual_required": False,
            "download_attempts": [],
        }

    for p in local_raw_candidates(args.snapshot_date):
        if p.exists():
            return {
                "status": "local_raw_exists",
                "input_file": str(p),
                "source_url": "",
                "normalized_exists": False,
                "manual_required": False,
                "download_attempts": [],
            }

    attempts: list[dict[str, Any]] = []
    urls: list[str] = []
    if args.download_mode == "source_url":
        if not args.source_url:
            return manual_required(args, attempts, "--source-url required for source_url mode")
        urls.append(args.source_url)
    elif args.download_mode == "auto":
        if args.source_url:
            urls.append(args.source_url)
        for template in CAIDA_SOURCE_URLS:
            urls.append(template.format(yyyymmdd=yyyymmdd(args.snapshot_date)))

    raw_dest = Path("data/caida/as-relationships/serial-2") / f"{yyyymmdd(args.snapshot_date)}.as-rel2.txt.bz2"
    for url in urls:
        try:
            result = download_url(url, raw_dest)
            attempts.append({"url": url, "status": "downloaded", **result})
            # Guard against HTML login pages saved as .bz2.
            with raw_dest.open("rb") as f:
                magic = f.read(8)
            if raw_dest.suffix == ".bz2" and not magic.startswith(b"BZh"):
                attempts[-1]["status"] = "downloaded_non_bzip_payload"
                attempts[-1]["note"] = "payload is not bzip2; CAIDA may require login/authorization"
                raw_dest.unlink(missing_ok=True)
                continue
            return {
                "status": "downloaded",
                "input_file": str(raw_dest),
                "source_url": url,
                "normalized_exists": False,
                "manual_required": False,
                "download_attempts": attempts,
            }
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
            attempts.append({"url": url, "status": "failed", "error": repr(exc)})

    return manual_required(args, attempts, "CAIDA download unavailable or requires authorization")


def manual_required(args: argparse.Namespace, attempts: list[dict[str, Any]], reason: str) -> dict[str, Any]:
    target = Path("data/caida/as-relationships/serial-2") / f"{yyyymmdd(args.snapshot_date)}.as-rel2.txt.bz2"
    return {
        "status": "manual_required",
        "input_file": "",
        "source_url": args.source_url,
        "normalized_exists": False,
        "manual_required": True,
        "manual_reason": reason,
        "manual_download_target": str(target),
        "manual_dataset_hint": "Download CAIDA AS Relationships serial-2 snapshot and place it at the target path.",
        "download_attempts": attempts,
    }


def open_asrel_text(path: Path):
    if path.suffix == ".bz2":
        return bz2.open(path, "rt", encoding="utf-8", errors="replace")
    return path.open("rt", encoding="utf-8", errors="replace")


def relation_type(rel_raw: str) -> str:
    if rel_raw == "0":
        return "p2p"
    if rel_raw == "-1":
        return "p2c_or_c2p_raw"
    return "unknown"


def relation_from_left_to_right(rel_raw: str, direction: str) -> str:
    if rel_raw == "0":
        return "p2p"
    if rel_raw == "-1":
        return "raw_-1_forward_as1_to_as2" if direction == "forward" else "raw_-1_reverse_as2_to_as1"
    return f"raw_{rel_raw}_{direction}"


def parse_asrel(path: Path, args: argparse.Namespace, source_status: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    comment_count = 0
    parse_warning_count = 0
    downloaded_at = now_utc_iso()
    delta_days = date_delta_days(args.snapshot_date, args.run_date)
    is_future = delta_days < 0
    aligned = (not is_future) and delta_days <= 45
    source_url = str(source_status.get("source_url", ""))

    with open_asrel_text(path) as handle:
        raw_idx = 0
        for line in handle:
            raw_line = line.strip()
            if not raw_line:
                continue
            if raw_line.startswith("#"):
                comment_count += 1
                continue
            parts = raw_line.split("|")
            if len(parts) < 3:
                parse_warning_count += 1
                continue
            try:
                as1 = int(parts[0])
                as2 = int(parts[1])
            except ValueError:
                parse_warning_count += 1
                continue
            rel_raw = parts[2].strip()
            if as1 <= 0 or as2 <= 0:
                parse_warning_count += 1
                continue
            raw_hash = sha256_text(raw_line)
            raw_id = f"asrelraw_{raw_idx:09d}"
            provenance = {
                "raw_line_hash": raw_hash,
                "raw_extra_fields": parts[3:],
                "source_status": source_status.get("status", ""),
                "direction_warning": "CAIDA -1 orientation preserved as raw; interpret with CAIDA README before valley-free logic.",
            }
            common = {
                "raw_rel_id": raw_id,
                "as1": as1,
                "as2": as2,
                "rel_raw": rel_raw,
                "rel_type": relation_type(rel_raw),
                "rel_direction_note": "CAIDA raw orientation preserved; -1 direction is not re-coded in this cache.",
                "source": "CAIDA AS Relationships serial-2",
                "source_url": source_url,
                "snapshot_date": args.snapshot_date,
                "run_date": args.run_date,
                "aligned_to_run_date": aligned,
                "alignment_delta_days": delta_days,
                "is_future_snapshot": is_future,
                "raw_record_hash": raw_hash,
                "provenance_json": json.dumps(provenance, sort_keys=True),
                "relation_confidence": "aligned_medium" if aligned else ("future_not_allowed" if is_future else "stale_diagnostic"),
                "source_snapshot_date": args.snapshot_date,
            }
            rows.append(
                {
                    "rel_id": f"{raw_id}_fwd",
                    "direction": "forward",
                    "as_left": as1,
                    "as_right": as2,
                    "relation_from_left_to_right": relation_from_left_to_right(rel_raw, "forward"),
                    **common,
                }
            )
            rows.append(
                {
                    "rel_id": f"{raw_id}_rev",
                    "direction": "reverse",
                    "as_left": as2,
                    "as_right": as1,
                    "relation_from_left_to_right": relation_from_left_to_right(rel_raw, "reverse"),
                    **common,
                }
            )
            raw_idx += 1

    df = pd.DataFrame(rows)
    stats = {
        "raw_record_count": int(len(rows) / 2),
        "directed_record_count": int(len(rows)),
        "comment_line_count": int(comment_count),
        "parse_warning_count": int(parse_warning_count),
        "aligned_to_run_date": bool(aligned),
        "alignment_delta_days": int(delta_days),
        "is_future_snapshot": bool(is_future),
    }
    return df, stats


def load_normalized(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path)


def save_cache(df: pd.DataFrame, args: argparse.Namespace, source_status: dict[str, Any], stats: dict[str, Any]) -> dict[str, Any]:
    evidence_dir = Path(args.evidence_output_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    names = output_names(evidence_dir, args.snapshot_date)
    df.to_parquet(names["parquet"], index=False)
    df.to_csv(names["csv"], index=False)
    metadata = {
        "dataset_name": "CAIDA AS Relationships serial-2",
        "provider": "CAIDA",
        "dataset_type": "AS Relationships serial-2",
        "snapshot_date": args.snapshot_date,
        "run_date": args.run_date,
        "aligned_to_run_date": bool(stats["aligned_to_run_date"]),
        "alignment_delta_days": int(stats["alignment_delta_days"]),
        "is_future_snapshot": bool(stats["is_future_snapshot"]),
        "source_url": source_status.get("source_url", ""),
        "downloaded_at": now_utc_iso(),
        "input_file": source_status.get("input_file", ""),
        "output_parquet": str(names["parquet"]),
        "output_csv": str(names["csv"]),
        "record_count": int(stats["directed_record_count"]),
        "raw_record_count": int(stats["raw_record_count"]),
        "comment_line_count": int(stats["comment_line_count"]),
        "parse_warning_count": int(stats["parse_warning_count"]),
        "usable_for_r2c": bool(stats["aligned_to_run_date"] and not stats["is_future_snapshot"]),
        "usable_evidence_strength": "aligned_medium" if stats["aligned_to_run_date"] and not stats["is_future_snapshot"] else ("future_not_allowed_for_verdict" if stats["is_future_snapshot"] else "diagnostic"),
        "hard_safety_notes": HARD_SAFETY_NOTES,
        "source_status": source_status,
        "no_commit_large_outputs": bool(args.no_commit_large_outputs),
    }
    write_json(names["metadata"], metadata)
    return metadata


def load_pair_targets(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"R-2C-0 AS-pair targets missing: {path}")
    cols = ["target_id", "incident_id", "adjacent_as_pairs", "source_queue", "legacy_priority", "member_count", "high_count", "needs_count", "r2b_verdict", "r2b_component_purity_class"]
    df = pd.read_parquet(path)
    return df[[c for c in cols if c in df.columns]].copy()


def expand_unique_pairs(targets: pd.DataFrame) -> pd.DataFrame:
    counter: Counter[tuple[int, int]] = Counter()
    examples: dict[tuple[int, int], dict[str, Any]] = {}
    for _, row in targets.iterrows():
        pairs = str(row.get("adjacent_as_pairs", "") or "").split(";")
        for pair in pairs:
            pair = pair.strip()
            if not pair or "-" not in pair:
                continue
            left, right = pair.split("-", 1)
            try:
                as_left = int(left)
                as_right = int(right)
            except ValueError:
                continue
            key = (as_left, as_right)
            counter[key] += 1
            if key not in examples:
                examples[key] = {
                    "example_incident_id": row.get("incident_id", ""),
                    "example_target_id": row.get("target_id", ""),
                    "example_source_queue": row.get("source_queue", ""),
                    "example_r2b_verdict": row.get("r2b_verdict", ""),
                }
    rows = [
        {
            "as_left": left,
            "as_right": right,
            "pair": f"{left}-{right}",
            "target_occurrence_count": int(count),
            **examples[(left, right)],
        }
        for (left, right), count in counter.items()
    ]
    return pd.DataFrame(rows)


def relation_lookup_smoke(asrel_df: pd.DataFrame, args: argparse.Namespace, out_dir: Path) -> dict[str, Any]:
    targets = load_pair_targets(Path(args.pair_targets_file))
    unique_pairs = expand_unique_pairs(targets)
    if unique_pairs.empty:
        summary = {
            "total_as_pair_targets": int(len(targets)),
            "total_unique_as_pairs": 0,
            "matched_unique_as_pairs": 0,
            "unmatched_unique_as_pairs": 0,
            "match_rate": 0.0,
            "rel_type_distribution": {},
            "unknown_relation_rate": 1.0,
        }
        write_json(out_dir / "r2c_relation_lookup_summary.json", summary)
        return summary

    rel_cols = [
        "as_left",
        "as_right",
        "rel_type",
        "rel_raw",
        "relation_from_left_to_right",
        "relation_confidence",
        "source_snapshot_date",
    ]
    rel_lookup = asrel_df[rel_cols].drop_duplicates(["as_left", "as_right"])
    merged = unique_pairs.merge(rel_lookup, on=["as_left", "as_right"], how="left")
    merged["matched"] = merged["rel_type"].notna()
    merged["rel_type"] = merged["rel_type"].fillna("unknown")
    merged["relation_from_left_to_right"] = merged["relation_from_left_to_right"].fillna("unmatched")
    merged["relation_confidence"] = merged["relation_confidence"].fillna("unavailable")
    merged["source_snapshot_date"] = merged["source_snapshot_date"].fillna(args.snapshot_date)

    merged.to_csv(out_dir / "r2c_as_pair_relation_lookup_smoke.csv", index=False)
    unmatched = merged.loc[~merged["matched"]].sort_values("target_occurrence_count", ascending=False).head(500)
    matched = merged.loc[merged["matched"]].sort_values("target_occurrence_count", ascending=False).head(500)
    unmatched.to_csv(out_dir / "r2c_unmatched_as_pairs.csv", index=False)
    matched.to_csv(out_dir / "r2c_matched_as_pairs_sample.csv", index=False)

    rel_dist = {str(k): int(v) for k, v in merged["rel_type"].value_counts().sort_index().items()}
    summary = {
        "total_as_pair_targets": int(len(targets)),
        "total_unique_as_pairs": int(len(merged)),
        "matched_unique_as_pairs": int(merged["matched"].sum()),
        "unmatched_unique_as_pairs": int((~merged["matched"]).sum()),
        "match_rate": float(merged["matched"].mean()),
        "rel_type_distribution": rel_dist,
        "unknown_relation_rate": float((~merged["matched"]).mean()),
        "top_unmatched_pairs": unmatched[["pair", "target_occurrence_count", "example_incident_id"]].head(20).to_dict(orient="records"),
        "top_matched_pairs": matched[["pair", "target_occurrence_count", "rel_type", "relation_from_left_to_right"]].head(20).to_dict(orient="records"),
    }
    write_json(out_dir / "r2c_relation_lookup_summary.json", summary)
    return summary


def write_report(out_dir: Path, summary: dict[str, Any]) -> None:
    source = summary["source_discovery"]
    rel = summary.get("relation_lookup_summary", {})
    metadata = summary.get("cache_metadata", {})
    lines = [
        "# R-2C-P0b 2024-near AS Relationship Cache Materialization",
        "",
        f"Run id: `{summary['run_id']}`",
        f"Run date: `{summary['run_date']}`",
        f"Snapshot date: `{summary['snapshot_date']}`",
        f"Status: `{summary['status']}`",
        "",
        "## 1. Source Discovery",
        "",
        f"Source status: `{source.get('status')}`",
        f"Manual required: `{source.get('manual_required', False)}`",
        f"Input file: `{source.get('input_file', '')}`",
        f"Source URL: `{source.get('source_url', '')}`",
        "",
    ]
    if source.get("manual_required"):
        lines.extend(
            [
                "CAIDA download was not available without manual action or authorization.",
                "",
                f"Manual reason: `{source.get('manual_reason', '')}`",
                f"Download target path: `{source.get('manual_download_target', '')}`",
                "",
                "Place the CAIDA serial-2 snapshot at the target path and rerun with `--download-mode existing_file`.",
            ]
        )
    else:
        lines.extend(
            [
                "## 2. Cache",
                "",
                f"Record count: `{metadata.get('record_count', 0)}` directed rows (`{metadata.get('raw_record_count', 0)}` raw records)",
                f"Aligned to run date: `{metadata.get('aligned_to_run_date', False)}`",
                f"Alignment delta days: `{metadata.get('alignment_delta_days', '')}`",
                f"Future snapshot: `{metadata.get('is_future_snapshot', False)}`",
                f"Usable for R-2C: `{metadata.get('usable_for_r2c', False)}`",
                f"Evidence strength: `{metadata.get('usable_evidence_strength', '')}`",
                "",
                "## 3. AS-pair Lookup Smoke",
                "",
                f"Total AS-pair target rows: `{rel.get('total_as_pair_targets', 0)}`",
                f"Unique AS-pairs: `{rel.get('total_unique_as_pairs', 0)}`",
                f"Matched unique AS-pairs: `{rel.get('matched_unique_as_pairs', 0)}`",
                f"Unmatched unique AS-pairs: `{rel.get('unmatched_unique_as_pairs', 0)}`",
                f"Match rate: `{rel.get('match_rate', 0.0)}`",
                f"Relation type distribution: `{rel.get('rel_type_distribution', {})}`",
            ]
        )
    lines.extend(
        [
            "",
            "## 4. Safety Boundaries",
            "",
            "- This stage did not generate route-leak verdicts.",
            "- This stage did not modify R-2B verifier verdicts.",
            "- AS relationship evidence is inferred evidence, not ground truth.",
            "- AS-rel violation is not confirmed route leak.",
            "- AS-rel path legality is not benign.",
            "- Future snapshots are not allowed for formal verifier evidence.",
            "",
            "## 5. Next Step",
            "",
            summary.get("recommended_next_step", ""),
        ]
    )
    (out_dir / "r2c_p0b_asrel_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir = Path(args.evidence_output_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)

    source_status = discover_source(args, evidence_dir, out_dir)
    summary: dict[str, Any] = {
        "run_id": args.run_id,
        "run_date": args.run_date,
        "snapshot_date": args.snapshot_date,
        "download_mode": args.download_mode,
        "source_discovery": source_status,
        "route_leak_verdict_generated": False,
        "verifier_verdict_modified": False,
        "learning_layer_trained": False,
        "hard_safety_notes": HARD_SAFETY_NOTES,
        "manual_required": bool(source_status.get("manual_required", False)),
        "warnings": [],
    }

    names = output_names(evidence_dir, args.snapshot_date)
    if source_status.get("manual_required"):
        summary.update(
            {
                "status": "manual_required",
                "can_enter_r2c_p1": False,
                "can_train_learning_layer": False,
                "recommended_next_step": f"Manually download CAIDA serial-2 snapshot to {source_status.get('manual_download_target')}, then rerun existing_file mode.",
            }
        )
        write_json(out_dir / "r2c_p0b_asrel_summary.json", summary)
        write_report(out_dir, summary)
        print(json.dumps(summary, indent=2, sort_keys=True, default=json_default))
        return

    if source_status.get("normalized_exists"):
        asrel_df = load_normalized(names["parquet"])
        metadata = json.loads(names["metadata"].read_text(encoding="utf-8"))
    else:
        input_file = Path(source_status["input_file"])
        asrel_df, stats = parse_asrel(input_file, args, source_status)
        if asrel_df.empty:
            summary.update(
                {
                    "status": "manual_required",
                    "manual_required": True,
                    "source_discovery": manual_required(args, source_status.get("download_attempts", []), f"parsed zero AS-rel records from {input_file}"),
                    "can_enter_r2c_p1": False,
                    "can_train_learning_layer": False,
                    "recommended_next_step": "Provide a valid CAIDA AS relationship file and rerun existing_file mode.",
                }
            )
            write_json(out_dir / "r2c_p0b_asrel_summary.json", summary)
            write_report(out_dir, summary)
            print(json.dumps(summary, indent=2, sort_keys=True, default=json_default))
            return
        metadata = save_cache(asrel_df, args, source_status, stats)

    relation_summary = relation_lookup_smoke(asrel_df, args, out_dir)
    safety_violations: list[str] = []
    if summary["route_leak_verdict_generated"]:
        safety_violations.append("route_leak_verdict_generated")
    if summary["verifier_verdict_modified"]:
        safety_violations.append("verifier_verdict_modified")
    if metadata.get("is_future_snapshot") and metadata.get("usable_for_r2c"):
        safety_violations.append("future_snapshot_marked_usable")

    summary.update(
        {
            "status": "completed",
            "cache_metadata": metadata,
            "asrel_cache_paths": {
                "parquet": str(names["parquet"]),
                "csv": str(names["csv"]),
                "metadata": str(names["metadata"]),
            },
            "record_count": int(metadata.get("record_count", 0)),
            "raw_record_count": int(metadata.get("raw_record_count", 0)),
            "aligned_to_run_date": bool(metadata.get("aligned_to_run_date", False)),
            "alignment_delta_days": int(metadata.get("alignment_delta_days", 999999)),
            "is_future_snapshot": bool(metadata.get("is_future_snapshot", False)),
            "usable_for_r2c": bool(metadata.get("usable_for_r2c", False)),
            "relation_lookup_summary": relation_summary,
            "safety_violations": safety_violations,
            "can_enter_r2c_p1": bool(metadata.get("usable_for_r2c", False) and not safety_violations),
            "can_train_learning_layer": False,
            "recommended_next_step": "R-2C-P1 path relation lookup smoke / path-legality smoke; learning remains design-only.",
        }
    )
    write_json(out_dir / "r2c_p0b_asrel_summary.json", summary)
    write_json(out_dir / "r2c_asrel_cache_metadata.json", metadata)
    write_report(out_dir, summary)
    print(json.dumps(summary, indent=2, sort_keys=True, default=json_default))


if __name__ == "__main__":
    main()
