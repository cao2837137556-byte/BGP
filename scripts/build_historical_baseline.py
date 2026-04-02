import argparse
import json
from pathlib import Path

import pandas as pd


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


def ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    required = [
        "run_id",
        "prefix",
        "origin_as",
        "as_path_clean",
        "as_path_len",
        "first_seen",
        "last_seen",
        "duration_sec",
        "record_count",
        "collector_count",
        "visibility_count",
        "collector_set",
    ]
    for col in required:
        if col not in out.columns:
            out[col] = None

    if "rel_unknown_cnt" not in out.columns:
        out["rel_unknown_cnt"] = 0
    if "rel_has_unknown" not in out.columns:
        out["rel_has_unknown"] = False

    out["origin_as"] = pd.to_numeric(out["origin_as"], errors="coerce")
    out["as_path_len"] = pd.to_numeric(out["as_path_len"], errors="coerce").fillna(0)
    out["first_seen"] = pd.to_numeric(out["first_seen"], errors="coerce")
    out["last_seen"] = pd.to_numeric(out["last_seen"], errors="coerce")
    out["duration_sec"] = pd.to_numeric(out["duration_sec"], errors="coerce").fillna(0.0)
    out["record_count"] = pd.to_numeric(out["record_count"], errors="coerce").fillna(0)
    out["collector_count"] = pd.to_numeric(out["collector_count"], errors="coerce").fillna(0)
    out["visibility_count"] = pd.to_numeric(out["visibility_count"], errors="coerce").fillna(0)
    out["rel_unknown_cnt"] = pd.to_numeric(out["rel_unknown_cnt"], errors="coerce").fillna(0)
    out["rel_has_unknown"] = out["rel_has_unknown"].fillna(False).astype(bool)

    out["prefix"] = out["prefix"].fillna("").astype(str)
    out["as_path_clean"] = out["as_path_clean"].fillna("").astype(str)
    out["collector_set"] = out["collector_set"].fillna("").astype(str)
    out["run_id"] = out["run_id"].fillna("").astype(str)

    out = out[out["prefix"] != ""].copy()
    return out


def top_values_as_json(series: pd.Series, topn: int = 5) -> str:
    clean = series.dropna().astype(str)
    if clean.empty:
        return "[]"
    counts = clean.value_counts().head(topn)
    payload = [{"value": idx, "count": int(val)} for idx, val in counts.items()]
    return json.dumps(payload, ensure_ascii=False)


def parse_collector_set(value: str) -> set[str]:
    if value is None:
        return set()
    parts = [x.strip() for x in str(value).split("|")]
    return {x for x in parts if x}


def build_baseline_prefix(events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for prefix, grp in events.groupby("prefix", dropna=False, sort=False):
        rows.append(
            {
                "prefix": prefix,
                "total_events": int(len(grp)),
                "unique_origins": int(grp["origin_as"].dropna().nunique()),
                "top_origins": top_values_as_json(grp["origin_as"]),
                "avg_duration_sec": float(grp["duration_sec"].mean()),
                "median_duration_sec": float(grp["duration_sec"].median()),
                "avg_record_count": float(grp["record_count"].mean()),
                "median_record_count": float(grp["record_count"].median()),
                "avg_visibility_count": float(grp["visibility_count"].mean()),
                "median_visibility_count": float(grp["visibility_count"].median()),
                "avg_collector_count": float(grp["collector_count"].mean()),
                "first_seen": float(grp["first_seen"].min()),
                "last_seen": float(grp["last_seen"].max()),
            }
        )
    return pd.DataFrame(rows)


def build_baseline_prefix_origin(events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (prefix, origin_as), grp in events.groupby(["prefix", "origin_as"], dropna=False, sort=False):
        has_unknown = grp["rel_has_unknown"].fillna(False).astype(bool)
        unknown_positive = grp["rel_unknown_cnt"].fillna(0) > 0
        rows.append(
            {
                "prefix": prefix,
                "origin_as": origin_as,
                "total_events": int(len(grp)),
                "unique_paths": int(grp["as_path_clean"].replace("", pd.NA).dropna().nunique()),
                "top_paths": top_values_as_json(grp["as_path_clean"].replace("", pd.NA)),
                "avg_path_len": float(grp["as_path_len"].mean()),
                "median_path_len": float(grp["as_path_len"].median()),
                "avg_duration_sec": float(grp["duration_sec"].mean()),
                "avg_record_count": float(grp["record_count"].mean()),
                "avg_visibility_count": float(grp["visibility_count"].mean()),
                "rel_unknown_rate": float(unknown_positive.mean()),
                "rel_has_unknown_rate": float(has_unknown.mean()),
                "first_seen": float(grp["first_seen"].min()),
                "last_seen": float(grp["last_seen"].max()),
            }
        )
    return pd.DataFrame(rows)


def build_baseline_path(events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    group_cols = ["prefix", "origin_as", "as_path_clean"]
    for (prefix, origin_as, as_path_clean), grp in events.groupby(group_cols, dropna=False, sort=False):
        collector_union = set()
        for value in grp["collector_set"]:
            collector_union.update(parse_collector_set(value))
        if not collector_union and "collector" in grp.columns:
            collector_union.update(x for x in grp["collector"].dropna().astype(str) if x)

        idx_last = grp["last_seen"].idxmax()
        last_seen_run_id = str(grp.loc[idx_last, "run_id"]) if idx_last in grp.index else ""

        rows.append(
            {
                "prefix": prefix,
                "origin_as": origin_as,
                "as_path_clean": as_path_clean,
                "total_events": int(len(grp)),
                "total_records": int(grp["record_count"].sum()),
                "avg_duration_sec": float(grp["duration_sec"].mean()),
                "avg_visibility_count": float(grp["visibility_count"].mean()),
                "first_seen": float(grp["first_seen"].min()),
                "last_seen": float(grp["last_seen"].max()),
                "last_seen_run_id": last_seen_run_id,
                "collector_set": "|".join(sorted(collector_union)),
            }
        )
    return pd.DataFrame(rows)


def print_sample(label: str, df: pd.DataFrame):
    if df.empty:
        print(f"{label} sample: <empty>")
    else:
        print(f"{label} sample: {df.head(1).to_dict('records')[0]}")


def main():
    ap = argparse.ArgumentParser(description="Build historical baseline tables from event_units parquet.")
    ap.add_argument("--run-id", default=None, help="Run id under data/runs/<run_id>.")
    ap.add_argument("--input", default=None, help="Path to event_units.parquet.")
    ap.add_argument("--output-dir", default=None, help="Output baseline directory.")
    ap.add_argument("--min-events", type=int, default=1, help="Minimum total_events to keep baseline row.")
    ap.add_argument("--overwrite", type=str2bool, default=False, help="Overwrite existing outputs.")
    args = ap.parse_args()

    if args.min_events <= 0:
        raise SystemExit("--min-events must be > 0")

    if args.input:
        input_path = Path(args.input)
    else:
        if not args.run_id:
            raise SystemExit("Please provide --run-id or --input.")
        input_path = Path("data") / "runs" / args.run_id / "events" / "event_units.parquet"

    if not input_path.exists():
        raise SystemExit(f"Input event file not found: {input_path}")

    run_id = args.run_id or infer_run_id(input_path) or "unknown_run"
    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        if run_id != "unknown_run":
            output_dir = Path("data") / "runs" / run_id / "baseline"
        else:
            output_dir = Path("outputs") / "baseline"

    output_dir.mkdir(parents=True, exist_ok=True)

    out_prefix = output_dir / "baseline_prefix.parquet"
    out_prefix_origin = output_dir / "baseline_prefix_origin.parquet"
    out_path = output_dir / "baseline_path.parquet"
    out_summary = output_dir / "baseline_summary.json"

    output_files = [out_prefix, out_prefix_origin, out_path, out_summary]
    if not args.overwrite:
        exists = [p for p in output_files if p.exists()]
        if exists:
            raise SystemExit(
                "Output exists, pass --overwrite true to replace: " + ", ".join(to_rel_path(p) for p in exists)
            )

    events_raw = pd.read_parquet(input_path)
    events = ensure_columns(events_raw)

    baseline_prefix = build_baseline_prefix(events)
    baseline_prefix_origin = build_baseline_prefix_origin(events)
    baseline_path = build_baseline_path(events)

    baseline_prefix = baseline_prefix[baseline_prefix["total_events"] >= args.min_events].copy()
    baseline_prefix_origin = baseline_prefix_origin[baseline_prefix_origin["total_events"] >= args.min_events].copy()
    baseline_path = baseline_path[baseline_path["total_events"] >= args.min_events].copy()

    baseline_prefix = baseline_prefix.sort_values(["total_events", "prefix"], ascending=[False, True]).reset_index(drop=True)
    baseline_prefix_origin = baseline_prefix_origin.sort_values(
        ["total_events", "prefix", "origin_as"], ascending=[False, True, True]
    ).reset_index(drop=True)
    baseline_path = baseline_path.sort_values(
        ["total_events", "prefix", "origin_as", "as_path_clean"], ascending=[False, True, True, True]
    ).reset_index(drop=True)

    baseline_prefix.to_parquet(out_prefix, index=False)
    baseline_prefix_origin.to_parquet(out_prefix_origin, index=False)
    baseline_path.to_parquet(out_path, index=False)

    summary = {
        "run_id": run_id,
        "input_path": to_rel_path(input_path),
        "output_dir": to_rel_path(output_dir),
        "min_events": args.min_events,
        "total_event_rows": int(len(events)),
        "total_prefixes": int(events["prefix"].nunique()),
        "total_prefix_origin_pairs": int(events[["prefix", "origin_as"]].drop_duplicates().shape[0]),
        "total_unique_paths": int(events[["prefix", "origin_as", "as_path_clean"]].drop_duplicates().shape[0]),
        "prefix_rows": int(len(baseline_prefix)),
        "prefix_origin_rows": int(len(baseline_prefix_origin)),
        "path_rows": int(len(baseline_path)),
        "avg_events_per_prefix": float(baseline_prefix["total_events"].mean()) if not baseline_prefix.empty else 0.0,
        "avg_events_per_prefix_origin": float(baseline_prefix_origin["total_events"].mean())
        if not baseline_prefix_origin.empty
        else 0.0,
    }
    out_summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"run_id: {run_id}")
    print(f"input_event_file: {to_rel_path(input_path)}")
    print(f"input_event_rows: {len(events)}")
    print(f"prefix_baseline_rows: {len(baseline_prefix)}")
    print(f"prefix_origin_baseline_rows: {len(baseline_prefix_origin)}")
    print(f"path_baseline_rows: {len(baseline_path)}")
    print(f"output_dir: {to_rel_path(output_dir)}")
    print("summary:")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print_sample("prefix", baseline_prefix)
    print_sample("prefix_origin", baseline_prefix_origin)
    print_sample("path", baseline_path)


if __name__ == "__main__":
    main()
