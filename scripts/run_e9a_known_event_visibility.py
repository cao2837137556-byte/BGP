import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from run_e8c_known_events_test import (
    CAIDA_REL_DEFAULT,
    evaluate_event_result,
    load_event_candidates,
    run_pipeline_for_event,
    select_event_candidates,
    to_bool,
)


DEFAULT_EXPANDED_COLLECTORS = (
    "route-views.sg,route-views2,route-views.eqix,route-views.isc,"
    "rrc00,rrc01,rrc03,rrc10"
)


def read_parquet_or_empty(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def normalize_collectors(value: Any) -> set[str]:
    text = str(value or "").strip()
    if not text or text.lower() == "nan":
        return set()
    for ch in ["|", ";", ","]:
        text = text.replace(ch, " ")
    text = text.replace("[", " ").replace("]", " ").replace("'", " ").replace('"', " ")
    return {x.strip() for x in text.split() if x.strip()}


def label_counts(final_df: pd.DataFrame) -> dict[str, int]:
    if final_df.empty or "final_alert_label" not in final_df.columns:
        return {"high": 0, "needs": 0, "low": 0}
    counts = final_df["final_alert_label"].value_counts().to_dict()
    return {
        "high": int(counts.get("high_priority_alert", 0)),
        "needs": int(counts.get("needs_review", 0)),
        "low": int(counts.get("low_priority_or_background", 0)),
    }


def collect_layer_diagnostics(event: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    targets = set(str(x) for x in event["target_prefixes"])
    events_df = read_parquet_or_empty(run_dir / "events" / "event_units.parquet")
    candidates_df = read_parquet_or_empty(run_dir / "candidates" / "candidate_events.parquet")
    scored_df = read_parquet_or_empty(run_dir / "scores" / "scored_candidates.parquet")
    gated_df = read_parquet_or_empty(run_dir / "gating" / "gated_candidates.parquet")
    final_df = read_parquet_or_empty(run_dir / "final" / "final_alerts.parquet")

    event_rows = events_df[events_df.get("prefix", pd.Series(dtype=str)).astype(str).isin(targets)].copy() if not events_df.empty else pd.DataFrame()
    candidate_rows = candidates_df[candidates_df.get("prefix", pd.Series(dtype=str)).astype(str).isin(targets)].copy() if not candidates_df.empty else pd.DataFrame()
    scored_rows = scored_df[scored_df.get("prefix", pd.Series(dtype=str)).astype(str).isin(targets)].copy() if not scored_df.empty else pd.DataFrame()
    gated_rows = gated_df[gated_df.get("prefix", pd.Series(dtype=str)).astype(str).isin(targets)].copy() if not gated_df.empty else pd.DataFrame()
    final_rows = final_df[final_df.get("prefix", pd.Series(dtype=str)).astype(str).isin(targets)].copy() if not final_df.empty else pd.DataFrame()

    target_collectors: set[str] = set()
    if not event_rows.empty:
        if "collector" in event_rows.columns:
            target_collectors.update(str(x) for x in event_rows["collector"].dropna().unique())
        if "collector_set" in event_rows.columns:
            for v in event_rows["collector_set"].dropna().tolist():
                target_collectors.update(normalize_collectors(v))

    candidate_hit = "no"
    if not candidate_rows.empty:
        if "candidate_flag" in candidate_rows.columns:
            candidate_hit = "yes" if candidate_rows["candidate_flag"].fillna(False).astype(bool).any() else "no"
        else:
            candidate_hit = "yes"

    counts = label_counts(final_df)
    target_counts = label_counts(final_rows)

    return {
        "total_events": int(len(events_df)),
        "candidate_count": int(len(candidates_df)),
        "scored_count": int(len(scored_df)),
        "gated_count": int(len(gated_df)),
        "final_high": counts["high"],
        "final_needs": counts["needs"],
        "final_low": counts["low"],
        "target_event_rows": int(len(event_rows)),
        "target_candidate_rows": int(len(candidate_rows)),
        "target_scored_rows": int(len(scored_rows)),
        "target_gated_rows": int(len(gated_rows)),
        "target_final_rows": int(len(final_rows)),
        "target_final_high": target_counts["high"],
        "target_final_needs": target_counts["needs"],
        "target_final_low": target_counts["low"],
        "event_constructed": "yes" if not event_rows.empty else "no",
        "candidate_hit": candidate_hit,
        "target_visible_collectors": "|".join(sorted(target_collectors)),
        "target_collector_count": int(len(target_collectors)),
        "target_avg_collector_count": float(pd.to_numeric(event_rows.get("collector_count", pd.Series(dtype=float)), errors="coerce").mean()) if not event_rows.empty else 0.0,
        "target_avg_visibility_count": float(pd.to_numeric(event_rows.get("visibility_count", pd.Series(dtype=float)), errors="coerce").mean()) if not event_rows.empty else 0.0,
    }


def build_markdown(results_df: pd.DataFrame, summary: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# E9-A-1 Known Event Visibility Retest")
    lines.append("")
    lines.append("Scope: re-test the three E8-C selected known public events with expanded collectors; no model or pipeline architecture changes.")
    lines.append("`system_hit=yes` means the target prefix received any final response (`high` or `needs_review`), not only `high`.")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    for k in [
        "tested_events",
        "baseline_hit_events",
        "expanded_hit_events",
        "baseline_high_hits",
        "baseline_review_hits",
        "expanded_high_hits",
        "expanded_review_hits",
        "baseline_no_visibility",
        "expanded_no_visibility",
        "baseline_weak_signal_not_enough",
        "expanded_weak_signal_not_enough",
    ]:
        lines.append(f"- {k}: {summary[k]}")
    lines.append("")
    lines.append("## Visibility Comparison")
    lines.append("")
    lines.append("| event_name | setting | collectors | event_constructed | candidate_hit | system_hit | final_label | risk | certainty | origin_match | attacker_as_match | match_strength | no_hit_reason | target_event_rows | target_collector_count | target_final_high | target_final_needs | target_final_low |")
    lines.append("|---|---|---:|---|---|---|---|---:|---:|---|---|---|---|---:|---:|---:|---:|---:|")
    for _, r in results_df.iterrows():
        lines.append(
            f"| {r['event_name']} | {r['setting']} | {r['configured_collectors_count']} | "
            f"{r['event_constructed']} | {r['candidate_hit']} | {r['system_hit']} | {r['final_label']} | "
            f"{float(r['risk']):.2f} | {float(r['certainty']):.2f} | {r['origin_match']} | {r['attacker_as_match']} | "
            f"{r['match_strength']} | {r['no_hit_reason']} | {int(r['target_event_rows'])} | {int(r['target_collector_count'])} | "
            f"{int(r['target_final_high'])} | {int(r['target_final_needs'])} | {int(r['target_final_low'])} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="E9-A-1: retest E8-C known events with expanded collectors.")
    parser.add_argument("--output-dir", default="outputs/e9a_known_event_visibility_v01")
    parser.add_argument("--runs-root", default="data/runs")
    parser.add_argument("--manifest", default="data/known_events/known_event_candidates_v02.json")
    parser.add_argument("--selected-only", default="true")
    parser.add_argument("--inventory-stage", default="")
    parser.add_argument("--event-slugs", default="")
    parser.add_argument("--baseline-run-prefix", default="e8c")
    parser.add_argument("--expanded-run-prefix", default="e9a_expanded_v01")
    parser.add_argument("--baseline-collectors", default="route-views.sg,rrc00")
    parser.add_argument("--expanded-collectors", default=DEFAULT_EXPANDED_COLLECTORS)
    parser.add_argument("--max-rows", type=int, default=50000)
    parser.add_argument("--caida-rel", default=CAIDA_REL_DEFAULT)
    parser.add_argument("--execute-baseline", default="false")
    parser.add_argument("--execute-expanded", default="true")
    parser.add_argument("--force-expanded", default="false")
    parser.add_argument("--force-baseline", default="false")
    args = parser.parse_args()

    workdir = Path.cwd()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    runs_root = Path(args.runs_root)
    event_candidates = load_event_candidates(args.manifest)
    selected = select_event_candidates(
        event_candidates,
        selected_only=to_bool(args.selected_only),
        inventory_stage=args.inventory_stage,
        event_slugs=args.event_slugs,
    )

    rows: list[dict[str, Any]] = []
    for event in selected:
        for setting, run_prefix, collectors in [
            ("baseline_2collectors", args.baseline_run_prefix, args.baseline_collectors),
            ("expanded_collectors", args.expanded_run_prefix, args.expanded_collectors),
        ]:
            run_id = f"{run_prefix}_{event['slug']}"
            should_execute = (
                setting == "baseline_2collectors" and to_bool(args.execute_baseline)
            ) or (
                setting == "expanded_collectors" and to_bool(args.execute_expanded)
            )
            if should_execute:
                run_id = run_pipeline_for_event(
                    event=event,
                    workdir=workdir,
                    runs_root=runs_root,
                    collectors=collectors,
                    max_rows=args.max_rows,
                    caida_rel=args.caida_rel,
                    force=to_bool(args.force_baseline if setting == "baseline_2collectors" else args.force_expanded),
                    run_id_prefix=run_prefix,
                    marker_dir_name="markers_e9a_baseline" if setting == "baseline_2collectors" else "markers_e9a",
                )
            run_dir = runs_root / run_id
            result = evaluate_event_result(event, run_dir)
            diag = collect_layer_diagnostics(event, run_dir)
            row = {
                "setting": setting,
                "run_id": run_id,
                "configured_collectors": collectors,
                "configured_collectors_count": len([x for x in collectors.split(",") if x.strip()]),
                **result,
                **diag,
            }
            rows.append(row)

    results_df = pd.DataFrame(rows)
    results_df.to_csv(output_dir / "e9a_known_event_visibility_results.csv", index=False, encoding="utf-8-sig")

    baseline = results_df[results_df["setting"] == "baseline_2collectors"].copy()
    expanded = results_df[results_df["setting"] == "expanded_collectors"].copy()
    summary = {
        "tested_events": int(len(selected)),
        "baseline_collectors": args.baseline_collectors,
        "expanded_collectors": args.expanded_collectors,
        "baseline_hit_events": int((baseline["system_hit"] == "yes").sum()),
        "expanded_hit_events": int((expanded["system_hit"] == "yes").sum()),
        "baseline_high_hits": int(((baseline["system_hit"] == "yes") & (baseline["final_label"] == "high")).sum()),
        "baseline_review_hits": int(((baseline["system_hit"] == "yes") & (baseline["final_label"] == "needs")).sum()),
        "expanded_high_hits": int(((expanded["system_hit"] == "yes") & (expanded["final_label"] == "high")).sum()),
        "expanded_review_hits": int(((expanded["system_hit"] == "yes") & (expanded["final_label"] == "needs")).sum()),
        "baseline_no_visibility": int((baseline["no_hit_reason"] == "no_visibility").sum()),
        "expanded_no_visibility": int((expanded["no_hit_reason"] == "no_visibility").sum()),
        "baseline_weak_signal_not_enough": int((baseline["no_hit_reason"] == "weak_signal_not_enough").sum()),
        "expanded_weak_signal_not_enough": int((expanded["no_hit_reason"] == "weak_signal_not_enough").sum()),
        "expanded_run_ids": expanded["run_id"].tolist(),
    }
    (output_dir / "e9a_known_event_visibility_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "e9a_known_event_visibility_report.md").write_text(build_markdown(results_df, summary), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
