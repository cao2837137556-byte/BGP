import argparse
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pybgpstream

from run_e8c_known_events_test import load_event_candidates


DEFAULT_MANIFEST = "data/known_events/known_event_candidates_v04.json"
DEFAULT_EVENT_SLUG = "pakistan_youtube_20080224"
DEFAULT_OUTPUT_DIR = "outputs/e9i_pakistan_time_window_audit_v01"
DEFAULT_BASELINE_COLLECTORS = "route-views.sg,rrc00"
DEFAULT_EXPANDED_COLLECTORS = (
    "route-views.sg,route-views2,route-views.eqix,route-views.isc,"
    "rrc00,rrc01,rrc03,rrc10"
)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def iso_utc(ts: Any) -> str:
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return ""


def collect_exact_prefix_rows(
    *,
    from_time: str,
    until_time: str,
    collectors: list[str],
    target_prefix: str,
    sample_limit: int = 30,
) -> pd.DataFrame:
    stream = pybgpstream.BGPStream(
        from_time=from_time,
        until_time=until_time,
        collectors=collectors,
        record_type="updates",
        filter=f"prefix exact {target_prefix}",
    )

    rows: list[dict[str, Any]] = []
    total_rows = 0
    collector_counter: Counter[str] = Counter()
    origin_counter: Counter[str] = Counter()
    path_counter: Counter[str] = Counter()
    first_ts = None
    last_ts = None

    for elem in stream:
        total_rows += 1
        fields = elem.fields
        prefix = str(fields.get("prefix", "") or "")
        as_path = str(fields.get("as-path", "") or "")
        origin = as_path.split()[-1] if as_path else ""
        collector = str(elem.collector)
        ts = float(elem.time)

        collector_counter[collector] += 1
        if origin:
            origin_counter[origin] += 1
        if as_path:
            path_counter[as_path] += 1

        if first_ts is None or ts < first_ts:
            first_ts = ts
        if last_ts is None or ts > last_ts:
            last_ts = ts

        if len(rows) < sample_limit:
            rows.append(
                {
                    "ts": ts,
                    "ts_utc": iso_utc(ts),
                    "collector": collector,
                    "type": str(elem.type),
                    "peer_asn": getattr(elem, "peer_asn", None),
                    "prefix": prefix,
                    "as_path": as_path,
                    "origin_as": origin,
                }
            )

    sample_df = pd.DataFrame(rows)
    sample_df.attrs["total_rows"] = total_rows
    sample_df.attrs["collector_counter"] = dict(collector_counter)
    sample_df.attrs["origin_counter"] = dict(origin_counter)
    sample_df.attrs["path_counter"] = dict(path_counter)
    sample_df.attrs["first_seen_utc"] = iso_utc(first_ts) if first_ts is not None else ""
    sample_df.attrs["last_seen_utc"] = iso_utc(last_ts) if last_ts is not None else ""
    return sample_df


def summarize_setting(
    *,
    setting: str,
    collectors: str,
    from_time: str,
    until_time: str,
    target_prefix: str,
) -> tuple[dict[str, Any], pd.DataFrame]:
    collector_list = [x.strip() for x in collectors.split(",") if x.strip()]
    sample_df = collect_exact_prefix_rows(
        from_time=from_time,
        until_time=until_time,
        collectors=collector_list,
        target_prefix=target_prefix,
    )

    total_rows = int(sample_df.attrs.get("total_rows", 0))
    collector_counter = sample_df.attrs.get("collector_counter", {})
    origin_counter = sample_df.attrs.get("origin_counter", {})
    path_counter = sample_df.attrs.get("path_counter", {})

    summary = {
        "setting": setting,
        "configured_collectors": collectors,
        "configured_collectors_count": len(collector_list),
        "audit_from": from_time,
        "audit_until": until_time,
        "target_prefix": target_prefix,
        "visible_rows": total_rows,
        "visible_collectors": "|".join(sorted(collector_counter.keys())),
        "visible_collectors_count": int(len(collector_counter)),
        "first_seen_utc": str(sample_df.attrs.get("first_seen_utc", "")),
        "last_seen_utc": str(sample_df.attrs.get("last_seen_utc", "")),
        "top_origin_as": json.dumps(origin_counter, ensure_ascii=False),
        "top_as_paths": json.dumps(dict(list(path_counter.items())[:10]), ensure_ascii=False),
        "audit_status": "visible" if total_rows > 0 else "no_visibility",
    }
    return summary, sample_df


def build_markdown(event: dict[str, Any], results_df: pd.DataFrame, before_minutes: int, after_minutes: int) -> str:
    lines: list[str] = []
    lines.append("# E9-I Pakistan/YouTube Extended-Window Audit")
    lines.append("")
    lines.append(f"Event: `{event['event_name']}`")
    lines.append(f"Target prefix: `{event['target_prefixes'][0]}`")
    lines.append(f"Original window: `{event['collect_from']}` +{event['minutes']}m")
    lines.append(f"Audit window expansion: before `{before_minutes}` minutes, after `{after_minutes}` minutes")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| setting | configured_collectors_count | visible_rows | visible_collectors_count | audit_status | first_seen_utc | last_seen_utc |")
    lines.append("|---|---:|---:|---:|---|---|---|")
    for _, row in results_df.iterrows():
        lines.append(
            f"| {row['setting']} | {int(row['configured_collectors_count'])} | {int(row['visible_rows'])} | "
            f"{int(row['visible_collectors_count'])} | {row['audit_status']} | {row['first_seen_utc']} | {row['last_seen_utc']} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Extended-window raw visibility audit for Pakistan/YouTube event.")
    ap.add_argument("--manifest", default=DEFAULT_MANIFEST)
    ap.add_argument("--event-slug", default=DEFAULT_EVENT_SLUG)
    ap.add_argument("--before-minutes", type=int, default=120)
    ap.add_argument("--after-minutes", type=int, default=120)
    ap.add_argument("--baseline-collectors", default=DEFAULT_BASELINE_COLLECTORS)
    ap.add_argument("--expanded-collectors", default=DEFAULT_EXPANDED_COLLECTORS)
    ap.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    args = ap.parse_args()

    output_dir = Path(args.output_dir)
    ensure_dir(output_dir)

    events = load_event_candidates(args.manifest)
    event = next((e for e in events if str(e.get("slug", "")).strip() == args.event_slug), None)
    if event is None:
        raise SystemExit(f"event slug not found in manifest: {args.event_slug}")

    target_prefixes = event.get("target_prefixes", [])
    if not target_prefixes:
        raise SystemExit("target_prefixes missing")

    base_start = datetime.strptime(str(event["collect_from"]), "%Y-%m-%d %H:%M:%S")
    base_end = base_start + timedelta(minutes=int(event["minutes"]))
    audit_start = base_start - timedelta(minutes=args.before_minutes)
    audit_end = base_end + timedelta(minutes=args.after_minutes)

    from_time = audit_start.strftime("%Y-%m-%d %H:%M:%S")
    until_time = audit_end.strftime("%Y-%m-%d %H:%M:%S UTC")
    target_prefix = str(target_prefixes[0])

    rows: list[dict[str, Any]] = []
    sample_tables: dict[str, pd.DataFrame] = {}
    for setting, collectors in [
        ("baseline_2collectors", args.baseline_collectors),
        ("expanded_collectors", args.expanded_collectors),
    ]:
        summary, sample_df = summarize_setting(
            setting=setting,
            collectors=collectors,
            from_time=from_time,
            until_time=until_time,
            target_prefix=target_prefix,
        )
        rows.append(summary)
        sample_tables[setting] = sample_df

    results_df = pd.DataFrame(rows)
    results_df.to_csv(output_dir / "e9i_pakistan_time_window_audit_results.csv", index=False, encoding="utf-8-sig")
    for setting, sample_df in sample_tables.items():
        sample_df.to_csv(output_dir / f"{setting}_sample_rows.csv", index=False, encoding="utf-8-sig")

    summary = {
        "event_name": event["event_name"],
        "event_slug": event["slug"],
        "target_prefix": target_prefix,
        "original_collect_from": event["collect_from"],
        "original_minutes": int(event["minutes"]),
        "audit_from": from_time,
        "audit_until": until_time,
        "before_minutes": args.before_minutes,
        "after_minutes": args.after_minutes,
        "baseline_status": str(results_df.loc[results_df["setting"].eq("baseline_2collectors"), "audit_status"].iloc[0]),
        "expanded_status": str(results_df.loc[results_df["setting"].eq("expanded_collectors"), "audit_status"].iloc[0]),
        "baseline_visible_rows": int(results_df.loc[results_df["setting"].eq("baseline_2collectors"), "visible_rows"].iloc[0]),
        "expanded_visible_rows": int(results_df.loc[results_df["setting"].eq("expanded_collectors"), "visible_rows"].iloc[0]),
    }
    (output_dir / "e9i_pakistan_time_window_audit_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "e9i_pakistan_time_window_audit.md").write_text(
        build_markdown(event, results_df, args.before_minutes, args.after_minutes),
        encoding="utf-8",
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
