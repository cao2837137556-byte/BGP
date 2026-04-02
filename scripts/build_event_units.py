import argparse
import json
import re
from pathlib import Path

import pandas as pd


ASN_RE = re.compile(r"\d+")


def str2bool(value: str) -> bool:
    v = str(value).strip().lower()
    if v in {"1", "true", "yes", "y", "on"}:
        return True
    if v in {"0", "false", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"Invalid boolean value: {value}")


def to_rel_path(path: Path) -> str:
    p = path.resolve()
    work_root = Path("/work")
    if work_root.exists():
        try:
            return p.relative_to(work_root).as_posix()
        except ValueError:
            pass
    try:
        return p.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return p.as_posix()


def infer_run_id(path: Path):
    parts = list(path.resolve().parts)
    for idx, part in enumerate(parts):
        if part == "runs" and idx + 1 < len(parts):
            return parts[idx + 1]
    return None


def is_rel_file(path: Path) -> bool:
    return path.stem.endswith("__rel") or "__rel." in path.name


def parse_as_path(value) -> list[int]:
    if value is None:
        return []
    if pd.isna(value):
        return []
    nums = [int(x) for x in ASN_RE.findall(str(value))]
    if not nums:
        return []
    deduped = []
    prev = None
    for n in nums:
        if n != prev:
            deduped.append(n)
            prev = n
    return deduped


def enrich_path_fields(df: pd.DataFrame) -> pd.DataFrame:
    if "as_path_clean" in df.columns:
        raw_clean_series = df["as_path_clean"]
    else:
        raw_clean_series = pd.Series([""] * len(df), index=df.index)

    if "as_path" in df.columns:
        raw_path_series = df["as_path"]
    else:
        raw_path_series = pd.Series([""] * len(df), index=df.index)

    clean_values = []
    origin_values = []
    length_values = []
    for raw_clean, raw_path in zip(raw_clean_series, raw_path_series):
        seq = parse_as_path(raw_clean)
        if not seq:
            seq = parse_as_path(raw_path)
        clean_values.append(" ".join(str(x) for x in seq))
        origin_values.append(seq[-1] if seq else None)
        length_values.append(len(seq))

    df = df.copy()
    df["as_path_clean"] = clean_values
    if "origin_as" in df.columns:
        df["origin_as"] = df["origin_as"].where(df["origin_as"].notna(), pd.Series(origin_values, index=df.index))
    else:
        df["origin_as"] = origin_values
    if "as_path_len" in df.columns:
        df["as_path_len"] = pd.to_numeric(df["as_path_len"], errors="coerce").fillna(pd.Series(length_values, index=df.index))
    else:
        df["as_path_len"] = length_values

    df["origin_as"] = pd.to_numeric(df["origin_as"], errors="coerce")
    df["as_path_len"] = pd.to_numeric(df["as_path_len"], errors="coerce").fillna(0).astype(int)
    return df


def pick_input_files(input_path: Path, prefer_rel: bool) -> tuple[list[Path], str]:
    if input_path.is_file():
        return [input_path], "rel" if is_rel_file(input_path) else "updates"

    all_parquet = []
    for p in input_path.rglob("*.parquet"):
        if "events" in p.parts:
            continue
        all_parquet.append(p)

    rel_files = [p for p in all_parquet if is_rel_file(p)]
    updates_files = [p for p in all_parquet if not is_rel_file(p)]

    if prefer_rel:
        selected = rel_files if rel_files else updates_files
        input_kind = "rel" if rel_files else "updates"
    else:
        selected = updates_files if updates_files else rel_files
        input_kind = "updates" if updates_files else "rel"

    return sorted(selected), input_kind


def build_events(df: pd.DataFrame, run_id: str, window_sec: int) -> pd.DataFrame:
    if "ts" not in df.columns:
        raise ValueError("Input parquet is missing required column: ts")
    if "collector" not in df.columns:
        raise ValueError("Input parquet is missing required column: collector")
    if "prefix" not in df.columns:
        raise ValueError("Input parquet is missing required column: prefix")
    if "type" not in df.columns:
        raise ValueError("Input parquet is missing required column: type")

    work = df.copy()
    work["ts"] = pd.to_numeric(work["ts"], errors="coerce")
    work = work[work["ts"].notna()].copy()
    work["type"] = work["type"].astype(str).str.upper()
    work["prefix"] = work["prefix"].astype(str)
    work = enrich_path_fields(work)
    work["event_key_path"] = work["as_path_clean"].fillna("")
    work["event_key_origin"] = work["origin_as"].fillna(-1).astype(int)
    work["event_key_prefix"] = work["prefix"]

    grouped = work.sort_values(["event_key_prefix", "event_key_origin", "event_key_path", "ts"]).groupby(
        ["event_key_prefix", "event_key_origin", "event_key_path"], dropna=False, sort=False
    )

    event_rows = []
    event_index = 0

    for (_, _, _), group in grouped:
        current_rows = []
        prev_ts = None
        for row in group.itertuples(index=False):
            ts_val = float(row.ts)
            if prev_ts is None or (ts_val - prev_ts) <= window_sec:
                current_rows.append(row)
            else:
                event_rows.append(aggregate_event_rows(current_rows, run_id, window_sec, event_index))
                event_index += 1
                current_rows = [row]
            prev_ts = ts_val
        if current_rows:
            event_rows.append(aggregate_event_rows(current_rows, run_id, window_sec, event_index))
            event_index += 1

    events_df = pd.DataFrame(event_rows)
    if events_df.empty:
        return events_df
    events_df = events_df.sort_values(["first_seen", "last_seen", "event_id"]).reset_index(drop=True)
    return events_df


def aggregate_event_rows(rows: list, run_id: str, window_sec: int, event_index: int) -> dict:
    first_row = rows[0]
    ts_values = [float(r.ts) for r in rows]
    first_seen = min(ts_values)
    last_seen = max(ts_values)
    duration_sec = float(last_seen - first_seen)

    collectors = sorted({str(getattr(r, "collector", "")) for r in rows if str(getattr(r, "collector", ""))})
    collector_set = "|".join(collectors)
    collector_count = len(collectors)
    primary_collector = collectors[0] if collectors else None

    visibility = set()
    for r in rows:
        collector = str(getattr(r, "collector", ""))
        peer_asn = getattr(r, "peer_asn", None)
        if collector and peer_asn is not None and not pd.isna(peer_asn):
            visibility.add(f"{collector}:{peer_asn}")
        elif collector:
            visibility.add(collector)
    visibility_count = len(visibility)

    rel_seq_values = []
    rel_unknown_values = []
    rel_has_unknown_values = []
    source_files = set()
    for r in rows:
        rel_seq = getattr(r, "rel_seq", None)
        if rel_seq is not None and str(rel_seq).strip() and str(rel_seq).lower() != "nan":
            rel_seq_values.append(str(rel_seq))
        rel_unknown = getattr(r, "rel_unknown_cnt", None)
        if rel_unknown is not None and not pd.isna(rel_unknown):
            rel_unknown_values.append(int(rel_unknown))
        rel_has_unknown = getattr(r, "rel_has_unknown", None)
        if rel_has_unknown is not None and not pd.isna(rel_has_unknown):
            rel_has_unknown_values.append(bool(rel_has_unknown))
        source_file = getattr(r, "source_file", None)
        if source_file is not None and str(source_file).strip():
            source_files.add(str(source_file))

    rel_seq = None
    if rel_seq_values:
        rel_seq = pd.Series(rel_seq_values).value_counts().index[0]
    rel_unknown_cnt = max(rel_unknown_values) if rel_unknown_values else 0
    rel_has_unknown = any(rel_has_unknown_values) if rel_has_unknown_values else False

    types = [str(getattr(r, "type", "")).upper() for r in rows]
    announce_count = sum(1 for t in types if t == "A")
    withdraw_count = sum(1 for t in types if t == "W")

    as_path_len = int(getattr(first_row, "as_path_len", 0) or 0)
    return {
        "event_id": f"{run_id}_evt_{event_index:08d}",
        "run_id": run_id,
        "collector": primary_collector,
        "prefix": str(getattr(first_row, "prefix", "")),
        "origin_as": int(getattr(first_row, "origin_as", -1)) if not pd.isna(getattr(first_row, "origin_as", None)) else None,
        "as_path_clean": str(getattr(first_row, "as_path_clean", "")),
        "as_path_len": as_path_len,
        "first_seen": first_seen,
        "last_seen": last_seen,
        "duration_sec": duration_sec,
        "record_count": len(rows),
        "announce_count": announce_count,
        "withdraw_count": withdraw_count,
        "collector_set": collector_set,
        "collector_count": collector_count,
        "visibility_count": visibility_count,
        "rel_seq": rel_seq,
        "rel_unknown_cnt": rel_unknown_cnt,
        "rel_has_unknown": rel_has_unknown,
        "source_file": "|".join(sorted(source_files)),
        "time_window_sec": window_sec,
    }


def make_summary(raw_df: pd.DataFrame, events_df: pd.DataFrame) -> dict:
    total_records = int(len(raw_df))
    total_events = int(len(events_df))
    avg_duration_sec = float(events_df["duration_sec"].mean()) if total_events else 0.0
    avg_collector_count = float(events_df["collector_count"].mean()) if total_events else 0.0
    avg_records_per_event = float(events_df["record_count"].mean()) if total_events else 0.0
    announce_records = int((raw_df["type"].astype(str).str.upper() == "A").sum()) if "type" in raw_df.columns else 0
    withdraw_records = int((raw_df["type"].astype(str).str.upper() == "W").sum()) if "type" in raw_df.columns else 0
    return {
        "total_records": total_records,
        "total_events": total_events,
        "avg_duration_sec": avg_duration_sec,
        "avg_collector_count": avg_collector_count,
        "avg_records_per_event": avg_records_per_event,
        "announce_records": announce_records,
        "withdraw_records": withdraw_records,
    }


def main():
    ap = argparse.ArgumentParser(description="Build event-unit table from updates/rel parquet in run directory.")
    ap.add_argument("--run-id", default=None, help="Run id under data/runs/<run_id>.")
    ap.add_argument("--input", default=None, help="Input file or directory. If omitted, use data/runs/<run_id>.")
    ap.add_argument("--output", default=None, help="Output parquet path.")
    ap.add_argument("--window-sec", type=int, default=300, help="Event split window in seconds.")
    ap.add_argument("--prefer-rel", type=str2bool, default=True, help="Prefer rel parquet if available.")
    args = ap.parse_args()

    if args.window_sec <= 0:
        raise SystemExit("--window-sec must be > 0")
    if not args.run_id and not args.input:
        raise SystemExit("Please provide --run-id or --input.")

    if args.input:
        input_path = Path(args.input)
    else:
        input_path = Path("data") / "runs" / args.run_id

    if not input_path.exists():
        raise SystemExit(f"Input path not found: {input_path}")

    run_id = args.run_id or infer_run_id(input_path) or "unknown_run"
    input_files, input_kind = pick_input_files(input_path, args.prefer_rel)
    if not input_files:
        raise SystemExit(f"No parquet files found in: {input_path}")

    if args.output:
        output_path = Path(args.output)
    else:
        if run_id != "unknown_run":
            output_path = Path("data") / "runs" / run_id / "events" / "event_units.parquet"
        else:
            output_path = Path("outputs") / "event_units.parquet"
    summary_path = output_path.with_name("event_units_summary.json")

    dataframes = []
    total_records = 0
    for path in input_files:
        df = pd.read_parquet(path)
        df["source_file"] = to_rel_path(path)
        dataframes.append(df)
        total_records += len(df)
    raw_df = pd.concat(dataframes, ignore_index=True) if dataframes else pd.DataFrame()
    events_df = build_events(raw_df, run_id, args.window_sec)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    events_df.to_parquet(output_path, index=False)

    summary = make_summary(raw_df, events_df)
    summary["run_id"] = run_id
    summary["input_kind"] = input_kind
    summary["input_files"] = [to_rel_path(p) for p in input_files]
    summary["output_path"] = to_rel_path(output_path)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"run_id: {run_id}")
    print(f"input_kind: {input_kind}")
    print("input_files:")
    for file_path in input_files:
        print(f"  - {to_rel_path(file_path)}")
    print(f"input_records: {total_records}")
    print(f"output_events: {len(events_df)}")
    print(f"avg_duration_sec: {summary['avg_duration_sec']:.3f}")
    print(f"avg_records_per_event: {summary['avg_records_per_event']:.3f}")
    print(f"output_path: {to_rel_path(output_path)}")
    print("summary:")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
