import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from run_e8c_known_events_test import load_event_candidates


def read_csv_or_empty(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def merge_setting_maps(paths: list[str]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    baseline_map: dict[str, dict[str, Any]] = {}
    expanded_map: dict[str, dict[str, Any]] = {}
    for raw_path in paths:
        df = read_csv_or_empty(Path(raw_path))
        if df.empty or "setting" not in df.columns:
            continue
        for _, row in df.iterrows():
            event_name = str(row.get("event_name", "")).strip()
            setting = str(row.get("setting", "")).strip()
            if not event_name:
                continue
            if setting == "baseline_2collectors":
                baseline_map[event_name] = row.to_dict()
            elif setting == "expanded_collectors":
                expanded_map[event_name] = row.to_dict()
    return baseline_map, expanded_map


def build_status_map(df: pd.DataFrame, setting_column: str | None = None) -> dict[tuple[str, str], dict[str, Any]]:
    if df.empty:
        return {}

    out: dict[tuple[str, str], dict[str, Any]] = {}
    for _, row in df.iterrows():
        event_name = str(row.get("event_name", "")).strip()
        setting = str(row.get(setting_column, "")) if setting_column else "default"
        if not event_name:
            continue
        out[(event_name, setting)] = row.to_dict()
    return out


def normalize_hit(row: dict[str, Any] | None) -> str:
    if not row:
        return "not_run"
    hit_status = str(row.get("hit_status", "")).strip()
    if hit_status:
        zone = normalize_zone_value(row.get("primary_landing_zone", ""))
        anchor_type = str(row.get("anchor_type", "")).strip()
        if hit_status == "Hit Expected":
            if anchor_type == "exact_prefix":
                try:
                    if int(float(row.get("high_rows", 0) or 0)) > 0:
                        return "high"
                except (TypeError, ValueError):
                    pass
            return zone if zone in {"high", "needs", "low"} else "hit"
        if hit_status == "Miss":
            return f"miss:{zone}" if zone else "miss"
        return "not_run"
    if str(row.get("system_hit", "")).strip().lower() == "yes":
        return str(row.get("final_label", "")).strip() or "hit"
    reason = str(row.get("no_hit_reason", "")).strip()
    return f"no_hit:{reason}" if reason else "no_hit"


def normalize_result_state(row: dict[str, Any] | None) -> str:
    if not row:
        return "not_run"
    hit_status = str(row.get("hit_status", "")).strip()
    if hit_status:
        if hit_status == "Hit Expected":
            return "hit_expected"
        if hit_status == "Miss":
            return "miss"
        return "not_run"
    return "hit_expected" if str(row.get("system_hit", "")).strip().lower() == "yes" else "miss"


def normalize_primary_zone(row: dict[str, Any] | None) -> str:
    if not row:
        return ""
    if "primary_landing_zone" in row:
        return normalize_zone_value(row.get("primary_landing_zone", ""))
    return normalize_zone_value(row.get("final_label", ""))


def normalize_match_strength(row: dict[str, Any] | None) -> str:
    if not row:
        return ""
    return str(row.get("match_strength", "")).strip()


def normalize_zone_value(value: Any) -> str:
    zone = str(value).strip().lower()
    return "" if zone in {"", "none", "nan"} else zone


def pick_best_row(
    event_name: str,
    fallback_key: tuple[str, str],
    preferred_map: dict[str, dict[str, Any]],
    fallback_map: dict[str, dict[str, Any]] | None = None,
    legacy_map: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> tuple[dict[str, Any] | None, str]:
    if event_name in preferred_map:
        preferred_row = preferred_map[event_name]
        if normalize_result_state(preferred_row) != "not_run":
            return preferred_row, "dual_track"
    if fallback_map and event_name in fallback_map:
        return fallback_map[event_name], "visibility"
    if legacy_map and fallback_key in legacy_map:
        return legacy_map[fallback_key], "legacy_e8c"
    return None, ""


def summarize_counts(df: pd.DataFrame, col: str) -> dict[str, int]:
    if df.empty or col not in df.columns:
        return {}
    return {str(k): int(v) for k, v in df[col].fillna("").value_counts().to_dict().items() if str(k)}


def build_markdown(df: pd.DataFrame, summary: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# E9-C Known Event Inventory")
    lines.append("")
    lines.append("This inventory tracks the current public-event pool for low-cost expansion after E8-C/E9-A.")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- manifest_events: {summary['manifest_events']}")
    lines.append(f"- core_tested: {summary['core_tested']}")
    lines.append(f"- next_batch: {summary['next_batch']}")
    lines.append(f"- backup: {summary['backup']}")
    lines.append(f"- baseline_tested: {summary['baseline_tested']}")
    lines.append(f"- expanded_tested: {summary['expanded_tested']}")
    lines.append(f"- baseline_hit_expected: {summary['baseline_hit_expected']}")
    lines.append(f"- expanded_hit_expected: {summary['expanded_hit_expected']}")
    lines.append(f"- baseline_high: {summary['baseline_high']}")
    lines.append(f"- baseline_needs: {summary['baseline_needs']}")
    lines.append(f"- expanded_high: {summary['expanded_high']}")
    lines.append(f"- expanded_needs: {summary['expanded_needs']}")
    lines.append("")
    lines.append("## Inventory Table")
    lines.append("")
    lines.append("| event_name | event_type | inventory_stage | priority | anchor_type | baseline_status | expanded_status | baseline_source | expanded_source | target_prefixes |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for _, r in df.iterrows():
        lines.append(
            f"| {r['event_name']} | {r['event_type']} | {r['inventory_stage']} | {r['selection_priority']} | "
            f"{r['anchor_type']} | {r['baseline_status']} | {r['expanded_status']} | {r['baseline_eval_source']} | "
            f"{r['expanded_eval_source']} | {r['target_prefixes']} |"
        )
    lines.append("")
    lines.append("## Recommended Next Batch")
    lines.append("")
    next_batch = df[df["inventory_stage"] == "next_batch"].copy()
    if next_batch.empty:
        lines.append("- none")
    else:
        for _, r in next_batch.sort_values(["selection_priority", "event_name"]).iterrows():
            lines.append(
                f"- {r['event_name']}: prefixes={r['target_prefixes']}; repro={r['reproducibility_confidence']}; "
                f"reason={r['selection_reason']}"
            )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build inventory for known public BGP event expansion after E8-C/E9-A.")
    parser.add_argument("--manifest", default="data/known_events/known_event_candidates_v05.json")
    parser.add_argument("--e8c-results", default="outputs/e8c_known_events_test_v01/e8c_known_events_test_results.csv")
    parser.add_argument(
        "--visibility-results",
        nargs="*",
        default=[
            "outputs/e9a_known_event_visibility_v02/e9a_known_event_visibility_results.csv",
            "outputs/e9c_known_event_visibility_v01/e9a_known_event_visibility_results.csv",
            "outputs/e9f_backup_visibility_v01/e9a_known_event_visibility_results.csv",
        ],
    )
    parser.add_argument(
        "--dual-track-results",
        nargs="*",
        default=[
            "outputs/s0_dual_track_eval_v01/s0_dual_track_eval_results.csv",
            "outputs/s0_dual_track_eval_v02/s0_dual_track_eval_results.csv",
        ],
    )
    parser.add_argument("--output-dir", default="outputs/e9c_known_event_inventory_v05")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest_events = load_event_candidates(args.manifest)
    e8c_df = read_csv_or_empty(Path(args.e8c_results))

    e8c_map = build_status_map(e8c_df)
    baseline_visibility_map, expanded_visibility_map = merge_setting_maps(args.visibility_results)
    baseline_dual_track_map, expanded_dual_track_map = merge_setting_maps(args.dual_track_results)

    rows: list[dict[str, Any]] = []
    for event in manifest_events:
        event_name = event["event_name"]
        baseline_row, baseline_source = pick_best_row(
            event_name,
            (event_name, "default"),
            baseline_dual_track_map,
            baseline_visibility_map,
            e8c_map,
        )
        expanded_row, expanded_source = pick_best_row(
            event_name,
            (event_name, "default"),
            expanded_dual_track_map,
            expanded_visibility_map,
            None,
        )
        row = {
            "event_name": event_name,
            "slug": event["slug"],
            "event_type": event.get("event_type", ""),
            "inventory_stage": event.get("inventory_stage", ""),
            "selection_priority": event.get("selection_priority", ""),
            "reproducibility_confidence": event.get("reproducibility_confidence", ""),
            "selected_for_test": "yes" if event.get("selected_for_test", False) else "no",
            "anchor_type": event.get("anchor_type", "exact_prefix"),
            "anchor_chain": " ".join(str(x) for x in event.get("anchor_chain", [])),
            "anchor_origin_as": event.get("anchor_origin_as", ""),
            "target_prefixes": "|".join(event.get("target_prefixes", [])),
            "approximate_time_window": event.get("approximate_time_window", ""),
            "collect_from": event.get("collect_from", ""),
            "minutes": event.get("minutes", ""),
            "known_origin_or_attack_as": event.get("known_origin_or_attack_as", ""),
            "selection_reason": event.get("selection_reason", ""),
            "fit_reason": event.get("fit_reason", ""),
            "source_reference": event.get("source_reference", ""),
            "baseline_status": normalize_hit(baseline_row),
            "expanded_status": normalize_hit(expanded_row),
            "baseline_result_state": normalize_result_state(baseline_row),
            "expanded_result_state": normalize_result_state(expanded_row),
            "baseline_primary_zone": normalize_primary_zone(baseline_row),
            "expanded_primary_zone": normalize_primary_zone(expanded_row),
            "baseline_match_strength": normalize_match_strength(baseline_row),
            "expanded_match_strength": normalize_match_strength(expanded_row),
            "baseline_eval_source": baseline_source,
            "expanded_eval_source": expanded_source,
            "baseline_run_id": "" if not baseline_row else str(baseline_row.get("run_id", "")),
            "expanded_run_id": "" if not expanded_row else str(expanded_row.get("run_id", "")),
        }
        rows.append(row)

    inventory_df = pd.DataFrame(rows)
    inventory_df.to_csv(output_dir / "e9c_known_event_inventory.csv", index=False, encoding="utf-8-sig")

    summary = {
        "manifest_events": int(len(inventory_df)),
        "core_tested": int((inventory_df["inventory_stage"] == "core_tested").sum()),
        "next_batch": int((inventory_df["inventory_stage"] == "next_batch").sum()),
        "backup": int((inventory_df["inventory_stage"] == "backup").sum()),
        "baseline_tested": int((inventory_df["baseline_status"] != "not_run").sum()),
        "expanded_tested": int((inventory_df["expanded_status"] != "not_run").sum()),
        "baseline_hit_expected": int((inventory_df["baseline_result_state"] == "hit_expected").sum()),
        "expanded_hit_expected": int((inventory_df["expanded_result_state"] == "hit_expected").sum()),
        "stage_distribution": summarize_counts(inventory_df, "inventory_stage"),
        "baseline_status_distribution": summarize_counts(inventory_df, "baseline_status"),
        "expanded_status_distribution": summarize_counts(inventory_df, "expanded_status"),
        "baseline_source_distribution": summarize_counts(inventory_df, "baseline_eval_source"),
        "expanded_source_distribution": summarize_counts(inventory_df, "expanded_eval_source"),
        "baseline_high": int((inventory_df["baseline_status"] == "high").sum()),
        "baseline_needs": int((inventory_df["baseline_status"] == "needs").sum()),
        "expanded_high": int((inventory_df["expanded_status"] == "high").sum()),
        "expanded_needs": int((inventory_df["expanded_status"] == "needs").sum()),
    }
    (output_dir / "e9c_known_event_inventory_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "e9c_known_event_inventory.md").write_text(
        build_markdown(inventory_df, summary),
        encoding="utf-8",
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
