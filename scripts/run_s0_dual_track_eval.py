import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from run_e8c_known_events_test import load_event_candidates


DEFAULT_MANIFEST = "data/known_events/known_event_candidates_v04.json"
DEFAULT_BASELINE_RESULTS = [
    "outputs/e8c_known_events_test_v01/e8c_known_events_test_results.csv",
    "outputs/e9c_known_event_visibility_v01/e9a_known_event_visibility_results.csv",
]
DEFAULT_EXPANDED_RESULTS = [
    "outputs/e9a_known_event_visibility_v02/e9a_known_event_visibility_results.csv",
    "outputs/e9c_known_event_visibility_v01/e9a_known_event_visibility_results.csv",
]
DEFAULT_OUTPUT_DIR = "outputs/s0_dual_track_eval_v01"


def read_csv_or_empty(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def merge_run_maps(paths: list[str], target_setting: str | None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for raw_path in paths:
        df = read_csv_or_empty(Path(raw_path))
        if df.empty or "event_name" not in df.columns:
            continue
        if target_setting is not None and "setting" in df.columns:
            df = df[df["setting"].astype(str).eq(target_setting)].copy()
        elif target_setting is not None and "setting" not in df.columns:
            if target_setting != "baseline_2collectors":
                continue
        for _, row in df.iterrows():
            event_name = str(row.get("event_name", "")).strip()
            run_id = str(row.get("run_id", "")).strip()
            if not event_name or not run_id:
                continue
            out[event_name] = row.to_dict()
    return out


def normalize_tokens(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text or text.lower() == "nan":
        return []
    return [token for token in text.split() if token]


def chain_match(path_text: Any, anchor_chain: list[str]) -> bool:
    tokens = normalize_tokens(path_text)
    if not tokens or not anchor_chain or len(tokens) < len(anchor_chain):
        return False
    width = len(anchor_chain)
    for idx in range(len(tokens) - width + 1):
        if tokens[idx : idx + width] == anchor_chain:
            return True
    return False


def landing_zone(label: str) -> str:
    mapping = {
        "high_priority_alert": "High",
        "needs_review": "Needs",
        "low_priority_or_background": "Low",
    }
    return mapping.get(str(label), "None")


def primary_landing_zone(df: pd.DataFrame) -> str:
    if df.empty or "final_alert_label" not in df.columns:
        return "None"
    counts = df["final_alert_label"].value_counts()
    if counts.empty:
        return "None"
    return landing_zone(str(counts.index[0]))


def build_exact_prefix_mask(final_df: pd.DataFrame, prefixes: list[str]) -> pd.Series:
    if final_df.empty or "prefix" not in final_df.columns:
        return pd.Series([], dtype=bool)
    prefix_set = {str(x) for x in prefixes}
    return final_df["prefix"].astype(str).isin(prefix_set)


def build_chain_mask(final_df: pd.DataFrame, anchor_chain: list[str]) -> pd.Series:
    if final_df.empty or "as_path_clean" not in final_df.columns:
        return pd.Series([], dtype=bool)
    return final_df["as_path_clean"].apply(lambda value: chain_match(value, anchor_chain))


def filter_by_anchor_origin(df: pd.DataFrame, anchor_origin_as: Any) -> pd.DataFrame:
    if df.empty or anchor_origin_as in (None, "", "nan"):
        return df
    if "origin_as" not in df.columns:
        return df.iloc[0:0].copy()
    try:
        expected = int(anchor_origin_as)
    except (TypeError, ValueError):
        return df
    mask = pd.to_numeric(df["origin_as"], errors="coerce").fillna(-1).astype(int).eq(expected)
    return df.loc[mask].copy()


def eval_exact_prefix(
    event: dict[str, Any],
    run_id: str,
    final_df: pd.DataFrame,
) -> dict[str, Any]:
    prefixes = [str(x) for x in event.get("target_prefixes", [])]
    matched = final_df.loc[build_exact_prefix_mask(final_df, prefixes)].copy()

    high_rows = int((matched.get("final_alert_label", pd.Series(dtype=str)) == "high_priority_alert").sum()) if not matched.empty else 0
    needs_rows = int((matched.get("final_alert_label", pd.Series(dtype=str)) == "needs_review").sum()) if not matched.empty else 0
    low_rows = int((matched.get("final_alert_label", pd.Series(dtype=str)) == "low_priority_or_background").sum()) if not matched.empty else 0
    matched_prefixes = int(matched["prefix"].astype(str).nunique()) if not matched.empty else 0

    return {
        "run_id": run_id,
        "matched_rows": int(len(matched)),
        "matched_prefixes": matched_prefixes,
        "impact_radius": matched_prefixes,
        "high_rows": high_rows,
        "needs_rows": needs_rows,
        "low_rows": low_rows,
        "retained_ratio": round((high_rows + needs_rows) / len(matched), 4) if len(matched) else 0.0,
        "primary_landing_zone": primary_landing_zone(matched),
        "hit_status": "Hit Expected" if high_rows > 0 else "Miss",
        "reason": "exact_prefix matched in high_priority_alert" if high_rows > 0 else "exact_prefix not retained in high_priority_alert",
    }


def eval_ordered_leak_chain(
    event: dict[str, Any],
    run_id: str,
    final_df: pd.DataFrame,
    min_prefixes: int,
    min_retained_ratio: float,
) -> dict[str, Any]:
    anchor_chain = [str(x) for x in event.get("anchor_chain", [])]
    matched = final_df.loc[build_chain_mask(final_df, anchor_chain)].copy()
    anchor_origin_as = event.get("anchor_origin_as")
    matched = filter_by_anchor_origin(matched, anchor_origin_as)

    high_rows = int((matched.get("final_alert_label", pd.Series(dtype=str)) == "high_priority_alert").sum()) if not matched.empty else 0
    needs_rows = int((matched.get("final_alert_label", pd.Series(dtype=str)) == "needs_review").sum()) if not matched.empty else 0
    low_rows = int((matched.get("final_alert_label", pd.Series(dtype=str)) == "low_priority_or_background").sum()) if not matched.empty else 0
    matched_prefixes = int(matched["prefix"].astype(str).nunique()) if not matched.empty else 0
    retained_ratio = round((high_rows + needs_rows) / len(matched), 4) if len(matched) else 0.0
    primary_zone = primary_landing_zone(matched)
    hit = matched_prefixes > min_prefixes and retained_ratio >= min_retained_ratio and primary_zone in {"High", "Needs"}

    return {
        "run_id": run_id,
        "matched_rows": int(len(matched)),
        "matched_prefixes": matched_prefixes,
        "impact_radius": matched_prefixes,
        "high_rows": high_rows,
        "needs_rows": needs_rows,
        "low_rows": low_rows,
        "retained_ratio": retained_ratio,
        "primary_landing_zone": primary_zone,
        "hit_status": "Hit Expected" if hit else "Miss",
        "reason": (
            f"ordered_leak_chain retained_ratio={retained_ratio:.4f}, impact_radius={matched_prefixes}, anchor_origin_as={anchor_origin_as}"
            if len(matched)
            else "ordered_leak_chain not found in final alerts"
        ),
    }


def evaluate_event(
    event: dict[str, Any],
    setting: str,
    run_id: str,
    run_dir: Path,
    min_chain_prefixes: int,
    min_chain_retained_ratio: float,
) -> dict[str, Any]:
    final_df = pd.read_parquet(run_dir / "final" / "final_alerts.parquet")
    anchor_type = str(event.get("anchor_type", "exact_prefix"))

    if anchor_type == "ordered_leak_chain":
        result = eval_ordered_leak_chain(
            event,
            run_id,
            final_df,
            min_prefixes=min_chain_prefixes,
            min_retained_ratio=min_chain_retained_ratio,
        )
    else:
        result = eval_exact_prefix(event, run_id, final_df)

    return {
        "event_name": event["event_name"],
        "event_type": event.get("event_type", ""),
        "setting": setting,
        "anchor_type": anchor_type,
        "anchor_origin_as": event.get("anchor_origin_as", ""),
        "target_prefixes": "|".join(str(x) for x in event.get("target_prefixes", [])),
        "anchor_chain": " ".join(str(x) for x in event.get("anchor_chain", [])),
        **result,
    }


def evaluate_not_run(event: dict[str, Any], setting: str) -> dict[str, Any]:
    return {
        "event_name": event["event_name"],
        "event_type": event.get("event_type", ""),
        "setting": setting,
        "anchor_type": str(event.get("anchor_type", "exact_prefix")),
        "anchor_origin_as": event.get("anchor_origin_as", ""),
        "target_prefixes": "|".join(str(x) for x in event.get("target_prefixes", [])),
        "anchor_chain": " ".join(str(x) for x in event.get("anchor_chain", [])),
        "run_id": "",
        "matched_rows": 0,
        "matched_prefixes": 0,
        "impact_radius": 0,
        "high_rows": 0,
        "needs_rows": 0,
        "low_rows": 0,
        "retained_ratio": 0.0,
        "primary_landing_zone": "None",
        "hit_status": "Not Run",
        "reason": "run_id unavailable for this setting",
    }


def build_markdown(results_df: pd.DataFrame, summary: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# S0 Dual-Track Known Event Evaluation")
    lines.append("")
    lines.append("Scope: upgrade known-event grading from single exact-prefix reading to a dual-track rubric.")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    for key in [
        "evaluated_rows",
        "hit_expected_rows",
        "miss_rows",
        "not_run_rows",
        "exact_prefix_hits",
        "ordered_leak_chain_hits",
    ]:
        lines.append(f"- {key}: {summary[key]}")
    lines.append("")
    lines.append("## Result Table")
    lines.append("")
    lines.append("| event_name | setting | anchor_type | anchor_origin_as | hit_status | primary_landing_zone | impact_radius | matched_rows | high_rows | needs_rows | low_rows | retained_ratio | run_id |")
    lines.append("|---|---|---|---:|---|---|---:|---:|---:|---:|---:|---:|---|")
    for _, row in results_df.iterrows():
        lines.append(
            f"| {row['event_name']} | {row['setting']} | {row['anchor_type']} | {row['anchor_origin_as']} | {row['hit_status']} | "
            f"{row['primary_landing_zone']} | {int(row['impact_radius'])} | {int(row['matched_rows'])} | "
            f"{int(row['high_rows'])} | {int(row['needs_rows'])} | {int(row['low_rows'])} | "
            f"{float(row['retained_ratio']):.4f} | {row['run_id']} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="S0 dual-track grading for known-event benchmark.")
    ap.add_argument("--manifest", default=DEFAULT_MANIFEST)
    ap.add_argument("--baseline-results", nargs="*", default=DEFAULT_BASELINE_RESULTS)
    ap.add_argument("--expanded-results", nargs="*", default=DEFAULT_EXPANDED_RESULTS)
    ap.add_argument("--runs-root", default="data/runs")
    ap.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    ap.add_argument("--chain-min-prefixes", type=int, default=10)
    ap.add_argument("--chain-min-retained-ratio", type=float, default=0.8)
    args = ap.parse_args()

    output_dir = Path(args.output_dir)
    ensure_dir(output_dir)
    runs_root = Path(args.runs_root)

    manifest_events = load_event_candidates(args.manifest)
    baseline_map = merge_run_maps(args.baseline_results, "baseline_2collectors")
    expanded_map = merge_run_maps(args.expanded_results, "expanded_collectors")

    rows: list[dict[str, Any]] = []
    for event in manifest_events:
        for setting, run_map in [
            ("baseline_2collectors", baseline_map),
            ("expanded_collectors", expanded_map),
        ]:
            run_info = run_map.get(event["event_name"])
            run_id = str(run_info.get("run_id", "")).strip() if run_info else ""
            if not run_id:
                rows.append(evaluate_not_run(event, setting))
                continue
            run_dir = runs_root / run_id
            if not (run_dir / "final" / "final_alerts.parquet").exists():
                rows.append(evaluate_not_run(event, setting))
                continue
            rows.append(
                evaluate_event(
                    event,
                    setting,
                    run_id,
                    run_dir,
                    min_chain_prefixes=args.chain_min_prefixes,
                    min_chain_retained_ratio=args.chain_min_retained_ratio,
                )
            )

    results_df = pd.DataFrame(rows)
    results_df.to_csv(output_dir / "s0_dual_track_eval_results.csv", index=False, encoding="utf-8-sig")

    summary = {
        "evaluated_rows": int(len(results_df)),
        "hit_expected_rows": int((results_df["hit_status"] == "Hit Expected").sum()),
        "miss_rows": int((results_df["hit_status"] == "Miss").sum()),
        "not_run_rows": int((results_df["hit_status"] == "Not Run").sum()),
        "exact_prefix_hits": int(((results_df["anchor_type"] == "exact_prefix") & (results_df["hit_status"] == "Hit Expected")).sum()),
        "ordered_leak_chain_hits": int(((results_df["anchor_type"] == "ordered_leak_chain") & (results_df["hit_status"] == "Hit Expected")).sum()),
        "chain_min_prefixes": args.chain_min_prefixes,
        "chain_min_retained_ratio": args.chain_min_retained_ratio,
    }
    (output_dir / "s0_dual_track_eval_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "s0_dual_track_eval_report.md").write_text(
        build_markdown(results_df, summary),
        encoding="utf-8",
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
