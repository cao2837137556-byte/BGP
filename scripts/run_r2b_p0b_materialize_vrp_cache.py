import argparse
import csv
import hashlib
import ipaddress
import json
import lzma
import os
import re
import shutil
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


RUN_ID_DEFAULT = "s2a_expanded_v01_pilot_6h_april16"
RUN_DATE_DEFAULT = "2024-04-16"
OUTPUT_DIR_DEFAULT = "outputs/r2b_p0b_vrp_materialization_v01"
EVIDENCE_OUTPUT_DIR_DEFAULT = "data/evidence/rpki"
DEFAULT_TARGETS_FILE = "outputs/r2b0_evidence_readiness_audit_v01/r2b_prefix_origin_targets.parquet"

RIPE_RPKI_ARCHIVE_BASE = "https://ftp.ripe.net/rpki"
RIPE_RPKI_ARCHIVE_DOC = "https://github.com/RIPE-NCC/internet-dataset-descriptions/blob/main/rpki-repo-archive.md"
RIPE_RPKI_README = "https://ftp.ripe.net/rpki/README.txt"
RIPE_TALS = ["afrinic.tal", "apnic.tal", "arin.tal", "lacnic.tal", "ripencc.tal"]

NORMALIZED_COLS = [
    "vrp_id",
    "prefix",
    "prefix_len",
    "max_length",
    "asn",
    "ta",
    "source",
    "source_url",
    "snapshot_ts",
    "snapshot_date",
    "downloaded_at",
    "aligned_to_run_date",
    "alignment_delta_hours",
    "raw_record_hash",
    "provenance_json",
]

LOOKUP_COLS = [
    "target_id",
    "incident_id",
    "lookup_prefix",
    "lookup_origin_as",
    "incident_start",
    "incident_end",
    "rpki_status",
    "rpki_evidence_state",
    "matched_vrp_count",
    "matched_authorized_vrp_count",
    "matched_covering_vrp_count",
    "best_match_prefix",
    "best_match_max_length",
    "best_match_asn",
    "rpki_lookup_note",
    "aligned_to_run_date",
    "cache_snapshot_date",
    "provenance_json",
]


def json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=json_default), encoding="utf-8")


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_asn(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text or text.upper() in {"NA", "NAN", "NONE", "NULL"}:
        return None
    if text.upper().startswith("AS"):
        text = text[2:]
    try:
        number = int(float(text))
    except Exception:
        return None
    return number if number > 0 else None


def parse_prefix(value: Any) -> ipaddress._BaseNetwork | None:
    text = str(value or "").strip()
    if not text or text.upper() in {"NA", "NAN", "NONE", "NULL"}:
        return None
    try:
        return ipaddress.ip_network(text, strict=False)
    except Exception:
        return None


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def infer_snapshot_date_from_path(path_text: str) -> str:
    match = re.search(r"(?<!\d)((?:19|20)\d{2})[-_/]?(\d{2})[-_/]?(\d{2})(?!\d)", path_text)
    if not match:
        return ""
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"


def alignment_delta_hours(snapshot_date: str, run_date: str) -> float | None:
    if not snapshot_date:
        return None
    try:
        snapshot = datetime.fromisoformat(snapshot_date)
        run = datetime.fromisoformat(run_date)
        return abs((snapshot - run).total_seconds()) / 3600.0
    except Exception:
        return None


def archive_urls_for_date(run_date: str) -> list[dict[str, str]]:
    dt = date.fromisoformat(run_date)
    return [
        {
            "tal": tal,
            "url": f"{RIPE_RPKI_ARCHIVE_BASE}/{tal}/{dt:%Y/%m/%d}/roas.csv.xz",
            "snapshot_date": run_date,
        }
        for tal in RIPE_TALS
    ]


def download_url(url: str, path: Path, timeout: int = 120) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "Veritas-BGP-R2B-P0b/1.0"})
    started = time.time()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        with path.open("wb") as out:
            shutil.copyfileobj(response, out)
        headers = dict(response.headers.items())
        status = getattr(response, "status", None)
    return {
        "url": url,
        "path": str(path),
        "status": status,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "elapsed_sec": time.time() - started,
        "headers": headers,
    }


def read_csv_records(path: Path) -> list[dict[str, str]]:
    opener = lzma.open if path.suffix == ".xz" else open
    with opener(path, "rt", encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def normalize_vrp_records(
    records: list[dict[str, str]],
    *,
    source: str,
    source_url: str,
    tal: str,
    snapshot_date: str,
    downloaded_at: str,
    aligned_to_run_date: bool,
    run_date: str,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    delta = alignment_delta_hours(snapshot_date, run_date)
    for raw in records:
        prefix_raw = raw.get("IP Prefix") or raw.get("prefix") or raw.get("Prefix") or raw.get("ip_prefix")
        asn_raw = raw.get("ASN") or raw.get("asn") or raw.get("AS") or raw.get("origin_as")
        max_len_raw = raw.get("Max Length") or raw.get("maxLength") or raw.get("max_length") or raw.get("max_len")
        uri = raw.get("URI") or raw.get("uri") or raw.get("roa_uri") or ""
        network = parse_prefix(prefix_raw)
        asn = normalize_asn(asn_raw)
        if network is None or asn is None:
            continue
        try:
            max_length = int(float(str(max_len_raw).strip())) if str(max_len_raw or "").strip() else network.prefixlen
        except Exception:
            max_length = network.prefixlen
        max_length = max(max_length, network.prefixlen)
        raw_for_hash = json.dumps(raw, sort_keys=True, ensure_ascii=False)
        provenance = {
            "tal": tal,
            "uri": uri,
            "raw_not_before": raw.get("Not Before", ""),
            "raw_not_after": raw.get("Not After", ""),
            "source": source,
            "source_url": source_url,
            "source_doc": RIPE_RPKI_ARCHIVE_DOC if source == "ripe_rpki_archive_roas_csv" else "",
        }
        rows.append(
            {
                "prefix": str(network),
                "prefix_len": int(network.prefixlen),
                "max_length": int(max_length),
                "asn": int(asn),
                "ta": tal,
                "source": source,
                "source_url": source_url,
                "snapshot_ts": f"{snapshot_date}T00:00:00Z" if snapshot_date else "",
                "snapshot_date": snapshot_date,
                "downloaded_at": downloaded_at,
                "aligned_to_run_date": bool(aligned_to_run_date),
                "alignment_delta_hours": "" if delta is None else float(delta),
                "raw_record_hash": sha256_text(raw_for_hash),
                "provenance_json": json.dumps(provenance, sort_keys=True),
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(columns=NORMALIZED_COLS)
    frame = frame.drop_duplicates(
        subset=["prefix", "max_length", "asn", "ta", "snapshot_date", "raw_record_hash"]
    ).reset_index(drop=True)
    frame.insert(0, "vrp_id", [f"vrp_{i:09d}" for i in range(len(frame))])
    return frame[NORMALIZED_COLS]


def normalize_existing_file(path: Path, run_date: str, downloaded_at: str, aligned_to_run_date: bool) -> tuple[pd.DataFrame, dict[str, Any]]:
    suffixes = "".join(path.suffixes).lower()
    snapshot_date = infer_snapshot_date_from_path(str(path))
    source = "existing_vrp_file"
    companion_metadata = Path(str(path.with_suffix("")) + ".metadata.json")
    if not companion_metadata.exists() and path.suffix:
        companion_metadata = Path(str(path) + ".metadata.json")
    prior_metadata: dict[str, Any] = {}
    if companion_metadata.exists():
        try:
            prior_metadata = json.loads(companion_metadata.read_text(encoding="utf-8"))
        except Exception:
            prior_metadata = {}
    if suffixes.endswith(".parquet"):
        raw = pd.read_parquet(path)
        if set(NORMALIZED_COLS).issubset(raw.columns):
            frame = raw[NORMALIZED_COLS].copy()
            if "aligned_to_run_date" in frame.columns:
                frame["aligned_to_run_date"] = frame["aligned_to_run_date"].astype(bool)
            metadata = {
                **prior_metadata,
                "source_mode": "existing_normalized_vrp_file",
                "source_path": str(path),
                "source_sha256": sha256_file(path),
                "snapshot_date": snapshot_date or (str(frame["snapshot_date"].dropna().iloc[0]) if len(frame) else ""),
                "aligned_to_run_date": bool(aligned_to_run_date and not frame.empty),
            }
            return frame, metadata
        records = raw.to_dict(orient="records")
    elif suffixes.endswith(".csv") or suffixes.endswith(".csv.xz"):
        raw = pd.read_csv(path)
        if set(NORMALIZED_COLS).issubset(raw.columns):
            frame = raw[NORMALIZED_COLS].copy()
            frame["aligned_to_run_date"] = frame["aligned_to_run_date"].astype(str).str.lower().isin({"true", "1", "yes"})
            metadata = {
                **prior_metadata,
                "source_mode": "existing_normalized_vrp_file",
                "source_path": str(path),
                "source_sha256": sha256_file(path),
                "snapshot_date": snapshot_date or (str(frame["snapshot_date"].dropna().iloc[0]) if len(frame) else ""),
                "aligned_to_run_date": bool(aligned_to_run_date and not frame.empty),
            }
            return frame, metadata
        records = raw.fillna("").to_dict(orient="records")
    elif suffixes.endswith(".json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        records = data if isinstance(data, list) else data.get("records", [])
    else:
        raise ValueError(f"unsupported existing VRP file format: {path}")
    frame = normalize_vrp_records(
        records,
        source=source,
        source_url=str(path),
        tal="unknown",
        snapshot_date=snapshot_date or run_date,
        downloaded_at=downloaded_at,
        aligned_to_run_date=aligned_to_run_date,
        run_date=run_date,
    )
    metadata = {
        "source_mode": "existing_file",
        "source_path": str(path),
        "source_sha256": sha256_file(path),
        "snapshot_date": snapshot_date,
        "aligned_to_run_date": aligned_to_run_date,
    }
    return frame, metadata


def normalize_lookup_output(lookup: pd.DataFrame) -> pd.DataFrame:
    out = lookup.copy()
    text_cols = [
        "target_id",
        "incident_id",
        "lookup_prefix",
        "lookup_origin_as",
        "rpki_status",
        "rpki_evidence_state",
        "best_match_prefix",
        "best_match_max_length",
        "best_match_asn",
        "rpki_lookup_note",
        "cache_snapshot_date",
        "provenance_json",
    ]
    for col in text_cols:
        if col in out.columns:
            out[col] = out[col].fillna("").astype(str)
    int_cols = ["matched_vrp_count", "matched_authorized_vrp_count", "matched_covering_vrp_count"]
    for col in int_cols:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0).astype("int64")
    for col in ["incident_start", "incident_end"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    if "aligned_to_run_date" in out.columns:
        out["aligned_to_run_date"] = out["aligned_to_run_date"].astype(bool)
    return out[LOOKUP_COLS]


def discover_existing_aligned(evidence_output_dir: Path, run_date: str) -> Path | None:
    candidates = [
        evidence_output_dir / f"vrp_{run_date}.parquet",
        evidence_output_dir / f"vrp_{run_date}.csv",
        evidence_output_dir / f"normalized_vrp_{run_date}.parquet",
        evidence_output_dir / f"vrp_{run_date.replace('-', '')}.parquet",
        evidence_output_dir / f"vrp_{run_date.replace('-', '')}.csv",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def materialize_from_archive(args: argparse.Namespace, downloaded_at: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    urls = archive_urls_for_date(args.run_date)
    if args.source_url:
        urls = [{"tal": "custom", "url": args.source_url, "snapshot_date": infer_snapshot_date_from_path(args.source_url) or args.run_date}]
    download_dir = Path(args.output_dir) / "source_downloads"
    frames: list[pd.DataFrame] = []
    downloads: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for item in urls:
        tal = item["tal"]
        url = item["url"]
        target = download_dir / tal / "roas.csv.xz"
        try:
            info = download_url(url, target)
            downloads.append({**info, "tal": tal})
            records = read_csv_records(target)
            frame = normalize_vrp_records(
                records,
                source="ripe_rpki_archive_roas_csv",
                source_url=url,
                tal=tal,
                snapshot_date=item["snapshot_date"],
                downloaded_at=downloaded_at,
                aligned_to_run_date=item["snapshot_date"] == args.run_date,
                run_date=args.run_date,
            )
            frames.append(frame)
        except Exception as exc:
            failures.append({"tal": tal, "url": url, "error": str(exc)})
    if not frames:
        metadata = {
            "source_mode": "historical_archive",
            "source_base": RIPE_RPKI_ARCHIVE_BASE,
            "source_doc": RIPE_RPKI_ARCHIVE_DOC,
            "downloads": downloads,
            "failures": failures,
            "aligned_to_run_date": False,
        }
        return pd.DataFrame(columns=NORMALIZED_COLS), metadata
    vrp = pd.concat(frames, ignore_index=True)
    vrp = vrp.drop_duplicates(subset=["prefix", "max_length", "asn", "ta", "snapshot_date"]).reset_index(drop=True)
    vrp["vrp_id"] = [f"vrp_{i:09d}" for i in range(len(vrp))]
    metadata = {
        "source_mode": "historical_archive",
        "source_base": RIPE_RPKI_ARCHIVE_BASE,
        "source_doc": RIPE_RPKI_ARCHIVE_DOC,
        "readme_url": RIPE_RPKI_README,
        "downloads": downloads,
        "failures": failures,
        "tal_count": int(vrp["ta"].nunique()) if not vrp.empty else 0,
        "aligned_to_run_date": bool(not failures and not vrp.empty and vrp["aligned_to_run_date"].all()),
    }
    return vrp[NORMALIZED_COLS], metadata


def materialize_vrp_cache(args: argparse.Namespace, warnings: list[str]) -> tuple[pd.DataFrame, dict[str, Any]]:
    downloaded_at = now_utc_iso()
    evidence_output_dir = Path(args.evidence_output_dir)
    evidence_output_dir.mkdir(parents=True, exist_ok=True)
    mode = args.download_mode
    if mode == "auto":
        existing = discover_existing_aligned(evidence_output_dir, args.run_date)
        if existing:
            frame, metadata = normalize_existing_file(existing, args.run_date, downloaded_at, aligned_to_run_date=True)
            metadata["source_discovery"] = "existing aligned file found before download"
            return frame, metadata
        frame, metadata = materialize_from_archive(args, downloaded_at)
        if not frame.empty:
            return frame, metadata
        warnings.append("historical archive download failed; no current VRP fallback used without explicit allow-current-vrp-smoke")
        return frame, metadata
    if mode == "historical_archive":
        return materialize_from_archive(args, downloaded_at)
    if mode == "existing_file":
        if not args.existing_vrp_file:
            raise SystemExit("--existing-vrp-file is required with --download-mode existing_file")
        snapshot = infer_snapshot_date_from_path(args.existing_vrp_file)
        aligned = snapshot == args.run_date
        if not aligned and not args.allow_current_vrp_smoke:
            warnings.append("existing VRP file is not aligned to run date; materialized as not usable for R-2B verdict")
        return normalize_existing_file(Path(args.existing_vrp_file), args.run_date, downloaded_at, aligned_to_run_date=aligned)
    if mode in {"validator_export", "current_schema_smoke_only"}:
        if not args.existing_vrp_file:
            warnings.append(f"{mode} requires --existing-vrp-file in this implementation; no VRP cache materialized")
            return pd.DataFrame(columns=NORMALIZED_COLS), {"source_mode": mode, "aligned_to_run_date": False}
        frame, metadata = normalize_existing_file(Path(args.existing_vrp_file), args.run_date, downloaded_at, aligned_to_run_date=False)
        metadata["source_mode"] = mode
        metadata["usable_for_r2b_verdict"] = False
        return frame, metadata
    raise SystemExit(f"unsupported download mode: {mode}")


def write_vrp_outputs(vrp: pd.DataFrame, metadata: dict[str, Any], args: argparse.Namespace) -> dict[str, str]:
    evidence_dir = Path(args.evidence_output_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    aligned = bool(metadata.get("aligned_to_run_date")) and not vrp.empty and bool(vrp["aligned_to_run_date"].all())
    if aligned:
        base = evidence_dir / f"vrp_{args.run_date}"
    else:
        base = evidence_dir / "vrp_current_not_aligned_schema_smoke"
    parquet_path = base.with_suffix(".parquet")
    csv_path = base.with_suffix(".csv")
    metadata_path = Path(str(base) + ".metadata.json")
    if not vrp.empty:
        vrp.to_parquet(parquet_path, index=False)
        vrp.to_csv(csv_path, index=False)
    else:
        pd.DataFrame(columns=NORMALIZED_COLS).to_parquet(parquet_path, index=False)
        pd.DataFrame(columns=NORMALIZED_COLS).to_csv(csv_path, index=False)
    payload = {
        **metadata,
        "run_date": args.run_date,
        "record_count": int(len(vrp)),
        "aligned_to_run_date": bool(aligned),
        "usable_for_r2b_verdict": bool(aligned),
        "schema": NORMALIZED_COLS,
        "outputs": {
            "parquet": str(parquet_path),
            "csv": str(csv_path),
            "metadata": str(metadata_path),
        },
    }
    write_json(metadata_path, payload)
    return {"parquet": str(parquet_path), "csv": str(csv_path), "metadata": str(metadata_path)}


def network_key(network: ipaddress._BaseNetwork) -> tuple[int, int, int]:
    return (network.version, int(network.network_address), int(network.prefixlen))


def build_vrp_index(vrp: pd.DataFrame) -> tuple[dict[tuple[int, int, int], list[int]], dict[str, Any]]:
    index: dict[tuple[int, int, int], list[int]] = defaultdict(list)
    parsed_networks: list[ipaddress._BaseNetwork | None] = []
    for idx, row in vrp.iterrows():
        network = parse_prefix(row["prefix"])
        parsed_networks.append(network)
        if network is not None:
            index[network_key(network)].append(idx)
    return index, {"parsed_networks": parsed_networks}


def covering_indices(network: ipaddress._BaseNetwork, index: dict[tuple[int, int, int], list[int]]) -> list[int]:
    matched: list[int] = []
    max_bits = network.max_prefixlen
    address_int = int(network.network_address)
    for plen in range(network.prefixlen, -1, -1):
        if plen == 0:
            masked = 0
        else:
            mask = ((1 << plen) - 1) << (max_bits - plen)
            masked = address_int & mask
        matched.extend(index.get((network.version, masked, plen), []))
    return matched


def pick_best(vrp: pd.DataFrame, indices: list[int]) -> pd.Series | None:
    if not indices:
        return None
    subset = vrp.iloc[indices].copy()
    subset["_prefix_len_sort"] = pd.to_numeric(subset["prefix_len"], errors="coerce").fillna(-1)
    subset = subset.sort_values(["_prefix_len_sort", "max_length"], ascending=[False, True])
    return subset.iloc[0]


def lookup_targets(targets: pd.DataFrame, vrp: pd.DataFrame, metadata: dict[str, Any], args: argparse.Namespace) -> pd.DataFrame:
    aligned = bool(metadata.get("aligned_to_run_date")) and not vrp.empty and bool(vrp["aligned_to_run_date"].all())
    snapshot_dates = sorted(vrp["snapshot_date"].dropna().astype(str).unique().tolist()) if not vrp.empty else []
    cache_snapshot_date = snapshot_dates[0] if len(snapshot_dates) == 1 else ";".join(snapshot_dates[:5])
    if vrp.empty:
        rows = []
        for _, target in targets.iterrows():
            rows.append(unavailable_lookup_row(target, aligned, cache_snapshot_date, "VRP cache unavailable or empty"))
        return pd.DataFrame(rows, columns=LOOKUP_COLS)

    index, _ = build_vrp_index(vrp)
    rows: list[dict[str, Any]] = []
    for _, target in targets.iterrows():
        target_id = target.get("target_id", "")
        prefix = parse_prefix(target.get("lookup_prefix", ""))
        origin_as = normalize_asn(target.get("lookup_origin_as", ""))
        if target.get("key_quality") not in {"complete", "missing_time"} or prefix is None or origin_as is None:
            rows.append(unavailable_lookup_row(target, aligned, cache_snapshot_date, "target prefix-origin key not lookup eligible"))
            continue
        if not aligned:
            rows.append(unavailable_lookup_row(target, aligned, cache_snapshot_date, "VRP cache is not aligned to run date"))
            continue
        matched = covering_indices(prefix, index)
        if not matched:
            status = "unknown"
            state = "aligned_weak"
            best = None
            note = "no covering VRP found"
            authorized = []
            valid = []
        else:
            subset = vrp.iloc[matched]
            authorized = subset.index[subset["asn"].astype(int).eq(int(origin_as))].tolist()
            valid = subset.index[
                subset["asn"].astype(int).eq(int(origin_as))
                & (pd.to_numeric(subset["max_length"], errors="coerce").fillna(subset["prefix_len"]) >= int(prefix.prefixlen))
            ].tolist()
            if valid:
                status = "valid"
                state = "aligned_medium"
                best = pick_best(vrp, valid)
                note = "covering VRP authorizes origin ASN and prefix length"
            elif authorized:
                status = "invalid_length"
                state = "aligned_medium"
                best = pick_best(vrp, authorized)
                note = "covering VRP matches origin ASN but target prefix length exceeds max_length"
            else:
                status = "invalid_asn"
                state = "aligned_medium"
                best = pick_best(vrp, matched)
                note = "covering VRP exists but none authorize target origin ASN"
        provenance = {
            "cache_snapshot_date": cache_snapshot_date,
            "vrp_cache_aligned": aligned,
            "source_mode": metadata.get("source_mode", ""),
            "source_doc": metadata.get("source_doc", RIPE_RPKI_ARCHIVE_DOC),
        }
        rows.append(
            {
                "target_id": target_id,
                "incident_id": target.get("incident_id", ""),
                "lookup_prefix": target.get("lookup_prefix", ""),
                "lookup_origin_as": "" if origin_as is None else int(origin_as),
                "incident_start": target.get("incident_start", ""),
                "incident_end": target.get("incident_end", ""),
                "rpki_status": status,
                "rpki_evidence_state": state,
                "matched_vrp_count": int(len(matched)),
                "matched_authorized_vrp_count": int(len(authorized)),
                "matched_covering_vrp_count": int(len(matched)),
                "best_match_prefix": "" if best is None else best.get("prefix", ""),
                "best_match_max_length": "" if best is None else int(best.get("max_length", "")),
                "best_match_asn": "" if best is None else int(best.get("asn", "")),
                "rpki_lookup_note": note,
                "aligned_to_run_date": bool(aligned),
                "cache_snapshot_date": cache_snapshot_date,
                "provenance_json": json.dumps(provenance, sort_keys=True),
            }
        )
    return pd.DataFrame(rows, columns=LOOKUP_COLS)


def unavailable_lookup_row(target: pd.Series, aligned: bool, snapshot_date: str, note: str) -> dict[str, Any]:
    state = "unavailable" if not aligned else "unavailable"
    status = "unavailable" if "not aligned" not in note else "not_time_aligned"
    return {
        "target_id": target.get("target_id", ""),
        "incident_id": target.get("incident_id", ""),
        "lookup_prefix": target.get("lookup_prefix", ""),
        "lookup_origin_as": target.get("lookup_origin_as", ""),
        "incident_start": target.get("incident_start", ""),
        "incident_end": target.get("incident_end", ""),
        "rpki_status": status,
        "rpki_evidence_state": state,
        "matched_vrp_count": 0,
        "matched_authorized_vrp_count": 0,
        "matched_covering_vrp_count": 0,
        "best_match_prefix": "",
        "best_match_max_length": "",
        "best_match_asn": "",
        "rpki_lookup_note": note,
        "aligned_to_run_date": bool(aligned),
        "cache_snapshot_date": snapshot_date,
        "provenance_json": json.dumps({"cache_snapshot_date": snapshot_date, "vrp_cache_aligned": aligned}, sort_keys=True),
    }


def load_targets(path: Path, args: argparse.Namespace) -> pd.DataFrame:
    targets = pd.read_parquet(path)
    if args.sample_rows and not args.full_run:
        targets = targets.head(args.sample_rows).copy()
    return targets


def status_distribution(lookup: pd.DataFrame) -> pd.DataFrame:
    rows = []
    total = max(len(lookup), 1)
    for status, count in lookup["rpki_status"].value_counts(dropna=False).items():
        rows.append({"rpki_status": str(status), "count": int(count), "share": float(count) / total})
    return pd.DataFrame(rows)


def safety_violations(output_dir: Path, lookup: pd.DataFrame) -> list[str]:
    violations = []
    forbidden_terms = ["confirmed_attack", "confirmed benign", "confirmed_benign", "benign=true", "strongly_supported_suspicious"]
    for file_name in ["r2b_p0b_report.md", "r2b_p0b_summary.json"]:
        path = output_dir / file_name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace").lower()
        for term in forbidden_terms:
            if term in text:
                violations.append(f"forbidden term found in {file_name}: {term}")
    if "verifier_verdict" in lookup.columns:
        violations.append("lookup output unexpectedly contains verifier_verdict column")
    return violations


def write_report(
    path: Path,
    args: argparse.Namespace,
    summary: dict[str, Any],
    metadata: dict[str, Any],
    warnings: list[str],
) -> None:
    dist = summary["rpki_status_distribution"]
    dist_lines = [f"- `{k}`: `{v}`" for k, v in dist.items()]
    lines = [
        "# R-2B-P0b Historical VRP/RPKI Cache Materialization Report",
        "",
        f"Run ID: `{args.run_id}`",
        f"Run date: `{args.run_date}`",
        f"Mode: `{'full' if args.full_run else 'sample'}`",
        "",
        "## Required Questions",
        "",
        f"1. Historical aligned VRP cache built: `{str(summary['vrp_cache_aligned']).lower()}`.",
        f"2. Failure reason if not built: `{summary.get('failure_reason', '')}`.",
        f"3. Current not-aligned VRP used: `{str(summary['used_current_not_aligned_vrp']).lower()}`. If true, it is not usable for verdict.",
        f"4. VRP cache records: `{summary['vrp_cache_records']}`.",
        f"5. Prefix-origin targets lookup eligible: `{summary['lookup_eligible_targets']}`.",
        "6. RPKI status distribution:",
        *dist_lines,
        f"7. invalid_asn: `{summary['invalid_asn_count']}`; invalid_length: `{summary['invalid_length_count']}`.",
        f"8. unknown: `{summary['unknown_count']}`.",
        f"9. unavailable count: `{summary['unavailable_count']}`.",
        f"10. Hard safety violations: `{len(summary['safety_violations'])}`.",
        "11. Verifier verdict modified: `false`.",
        f"12. Can enter R-2B smoke with VRP: `{str(summary['can_run_r2b_smoke_with_vrp']).lower()}`.",
        f"13. Can enter R-2C: `{str(summary['can_run_r2c_next']).lower()}`.",
        "14. Can enter learning layer: `false`; verifier-supported targets are still required.",
        f"15. Next step: `{summary['next_step']}`.",
        "",
        "## Safety Notes",
        "",
        "- RPKI valid is not benign.",
        "- RPKI invalid is not confirmed attack.",
        "- RPKI unknown is not normal.",
        "- Unavailable is not benign.",
        "- This stage does not generate verifier verdicts.",
        "",
        "## Source Metadata",
        "",
        f"- source mode: `{metadata.get('source_mode', '')}`",
        f"- source base: `{metadata.get('source_base', metadata.get('source_path', ''))}`",
        f"- source doc: `{metadata.get('source_doc', '')}`",
        f"- aligned to run date: `{str(metadata.get('aligned_to_run_date', False)).lower()}`",
        "",
        "## Warnings",
        "",
    ]
    lines.extend(f"- {warning}" for warning in warnings)
    if not warnings:
        lines.append("- none")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="R-2B-P0b historical VRP/RPKI cache materialization")
    parser.add_argument("--run-id", default=RUN_ID_DEFAULT)
    parser.add_argument("--run-date", default=RUN_DATE_DEFAULT)
    parser.add_argument("--targets-file", default=DEFAULT_TARGETS_FILE)
    parser.add_argument("--output-dir", default=OUTPUT_DIR_DEFAULT)
    parser.add_argument("--evidence-output-dir", default=EVIDENCE_OUTPUT_DIR_DEFAULT)
    parser.add_argument("--sample-rows", type=int, default=0)
    parser.add_argument("--full-run", action="store_true")
    parser.add_argument(
        "--download-mode",
        default="auto",
        choices=["auto", "historical_archive", "validator_export", "existing_file", "current_schema_smoke_only"],
    )
    parser.add_argument("--source-url", default="")
    parser.add_argument("--existing-vrp-file", default="")
    parser.add_argument("--allow-current-vrp-smoke", action="store_true", default=False)
    parser.add_argument("--no-commit-large-outputs", action="store_true", default=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    warnings.append("R-2B-P0b materializes RPKI/VRP evidence only; it does not generate verifier verdicts.")
    warnings.append("RPKI valid is not benign; RPKI invalid is not confirmed attack; RPKI unknown is not normal.")

    targets_path = Path(args.targets_file)
    if not targets_path.exists():
        raise SystemExit(f"required targets file missing: {targets_path}")
    targets = load_targets(targets_path, args)
    eligible = targets[targets["key_quality"].isin(["complete", "missing_time"])].copy()

    vrp, source_metadata = materialize_vrp_cache(args, warnings)
    evidence_paths = write_vrp_outputs(vrp, source_metadata, args)
    source_metadata = {**source_metadata, "evidence_paths": evidence_paths}
    write_json(output_dir / "r2b_vrp_cache_metadata.json", source_metadata)

    lookup = lookup_targets(eligible, vrp, source_metadata, args)
    lookup = normalize_lookup_output(lookup)
    lookup.to_parquet(output_dir / "r2b_prefix_origin_rpki_lookup.parquet", index=False)
    lookup.to_csv(output_dir / "r2b_prefix_origin_rpki_lookup.csv", index=False)
    dist_df = status_distribution(lookup)
    dist_df.to_csv(output_dir / "r2b_rpki_status_distribution.csv", index=False)

    invalid_examples = lookup[lookup["rpki_status"].isin(["invalid_asn", "invalid_length"])].head(200).copy()
    invalid_examples.to_csv(output_dir / "r2b_invalid_examples.csv", index=False)

    status_counts = {str(k): int(v) for k, v in lookup["rpki_status"].value_counts(dropna=False).to_dict().items()}
    state_counts = {str(k): int(v) for k, v in lookup["rpki_evidence_state"].value_counts(dropna=False).to_dict().items()}
    incident_status = lookup.groupby("incident_id")["rpki_status"].agg(lambda s: sorted(set(map(str, s)))).reset_index()
    incidents_with_valid = int(incident_status["rpki_status"].map(lambda vals: "valid" in vals).sum())
    incidents_with_invalid = int(incident_status["rpki_status"].map(lambda vals: any(v in vals for v in ["invalid_asn", "invalid_length", "invalid"])).sum())
    incidents_with_unknown = int(incident_status["rpki_status"].map(lambda vals: "unknown" in vals).sum())
    incidents_with_unavailable = int(incident_status["rpki_status"].map(lambda vals: "unavailable" in vals or "not_time_aligned" in vals).sum())
    source_aligned = bool(source_metadata.get("aligned_to_run_date")) and not vrp.empty and bool(vrp["aligned_to_run_date"].all())
    summary = {
        "run_id": args.run_id,
        "run_date": args.run_date,
        "targets_file": str(targets_path),
        "total_targets": int(len(targets)),
        "lookup_eligible_targets": int(len(eligible)),
        "vrp_cache_records": int(len(vrp)),
        "vrp_cache_aligned": bool(source_aligned),
        "used_current_not_aligned_vrp": bool(not source_aligned and not vrp.empty),
        "rpki_status_distribution": status_counts,
        "rpki_evidence_state_distribution": state_counts,
        "valid_count": int(status_counts.get("valid", 0)),
        "invalid_asn_count": int(status_counts.get("invalid_asn", 0)),
        "invalid_length_count": int(status_counts.get("invalid_length", 0)),
        "unknown_count": int(status_counts.get("unknown", 0)),
        "unavailable_count": int(status_counts.get("unavailable", 0)),
        "not_time_aligned_count": int(status_counts.get("not_time_aligned", 0)),
        "incidents_with_valid": incidents_with_valid,
        "incidents_with_invalid": incidents_with_invalid,
        "incidents_with_unknown": incidents_with_unknown,
        "incidents_with_unavailable": incidents_with_unavailable,
        "top_invalid_asn_examples": lookup[lookup["rpki_status"].eq("invalid_asn")].head(10).to_dict(orient="records"),
        "top_invalid_length_examples": lookup[lookup["rpki_status"].eq("invalid_length")].head(10).to_dict(orient="records"),
        "safety_violations": [],
        "verifier_verdict_modified": False,
        "can_run_r2b_smoke_with_vrp": bool(source_aligned),
        "can_run_r2c_next": bool(source_aligned),
        "can_train_learning_layer": False,
        "next_step": "run R-2B verifier smoke with aligned VRP evidence" if source_aligned else "fix VRP source alignment before verifier smoke",
        "failure_reason": "" if source_aligned else "no aligned historical VRP cache materialized",
        "warnings": warnings,
        "status": "completed",
        "evidence_paths": evidence_paths,
        "no_commit_large_outputs": bool(args.no_commit_large_outputs),
    }
    write_report(output_dir / "r2b_p0b_report.md", args, summary, source_metadata, warnings)
    summary["safety_violations"] = safety_violations(output_dir, lookup)
    write_json(output_dir / "r2b_p0b_summary.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True, default=json_default))


if __name__ == "__main__":
    main()
