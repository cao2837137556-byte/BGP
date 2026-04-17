import argparse
import json
import math
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

try:
    import pyarrow.parquet as pq
except Exception:  # pragma: no cover
    pq = None


DEFAULT_BASE_RUN_ID = "20260313T032554_4f9be28c"
DEFAULT_WINDOW_SEC = 300


def safe_ratio(num: int, den: int) -> float:
    return float(num) / float(den) if den else 0.0


def ensure_bool_col(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series([False] * len(df), index=df.index, dtype=bool)
    return df[col].fillna(False).astype(bool)


def safe_mean(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    return float(values.mean()) if len(values) else 0.0


def sanitize_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", str(name).strip()).strip("_").lower()


def is_rel_file(path: Path) -> bool:
    return path.stem.endswith("__rel") or "__rel." in path.name


def parquet_rows(path: Path) -> int:
    if pq is not None:
        return int(pq.ParquetFile(path).metadata.num_rows)
    return int(len(pd.read_parquet(path)))


def run_cmd(cmd: list[str]):
    print("[RUN]", " ".join(cmd))
    subprocess.run(cmd, check=True)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass
class Setting:
    setting: str
    setting_type: str
    collectors: list[str]
    run_id: str


def list_collectors(base_run_dir: Path) -> list[str]:
    collectors = []
    for p in sorted(base_run_dir.iterdir()):
        if p.is_dir() and p.name.startswith("collector="):
            collectors.append(p.name.split("=", 1)[1])
    return collectors


def pick_collector_files(collector_dir: Path, prefer_rel: bool) -> tuple[list[Path], str]:
    files = sorted(collector_dir.rglob("*.parquet"))
    rel_files = [p for p in files if is_rel_file(p)]
    updates_files = [p for p in files if not is_rel_file(p)]
    if prefer_rel:
        if rel_files:
            return rel_files, "rel"
        return updates_files, "updates"
    if updates_files:
        return updates_files, "updates"
    return rel_files, "rel"


def collect_contribution(base_run_dir: Path, collectors: list[str], prefer_rel: bool) -> list[dict]:
    rows = []
    for c in collectors:
        c_dir = base_run_dir / f"collector={c}"
        files, kind = pick_collector_files(c_dir, prefer_rel)
        total_rows = sum(parquet_rows(p) for p in files)
        rows.append(
            {
                "collector": c,
                "input_kind": kind,
                "file_count": int(len(files)),
                "row_count": int(total_rows),
            }
        )
    rows = sorted(rows, key=lambda x: (-x["row_count"], x["collector"]))
    total = sum(r["row_count"] for r in rows)
    for r in rows:
        r["row_share"] = safe_ratio(int(r["row_count"]), int(total))
    return rows


def build_settings(base_run_id: str, ranked_collectors: list[str]) -> list[Setting]:
    n = len(ranked_collectors)
    settings: list[Setting] = []
    settings.append(
        Setting(
            setting="full",
            setting_type="all_collectors",
            collectors=list(ranked_collectors),
            run_id=f"e7a_{base_run_id}_full",
        )
    )

    if n >= 3:
        medium_n = max(1, min(n - 1, int(math.ceil(n * 0.5))))
        low_n = max(1, min(medium_n - 1, int(math.ceil(n * 0.25))))
        settings.append(
            Setting(
                setting="medium",
                setting_type=f"nested_top_{medium_n}",
                collectors=ranked_collectors[:medium_n],
                run_id=f"e7a_{base_run_id}_medium_top{medium_n}",
            )
        )
        settings.append(
            Setting(
                setting="low",
                setting_type=f"nested_top_{low_n}",
                collectors=ranked_collectors[:low_n],
                run_id=f"e7a_{base_run_id}_low_top{low_n}",
            )
        )
        return settings

    if n == 2:
        primary = ranked_collectors[0]
        secondary = ranked_collectors[1]
        settings.append(
            Setting(
                setting="medium",
                setting_type=f"fallback_single_{sanitize_name(primary)}",
                collectors=[primary],
                run_id=f"e7a_{base_run_id}_single_{sanitize_name(primary)}",
            )
        )
        settings.append(
            Setting(
                setting="low",
                setting_type=f"fallback_single_{sanitize_name(secondary)}",
                collectors=[secondary],
                run_id=f"e7a_{base_run_id}_single_{sanitize_name(secondary)}",
            )
        )
        return settings

    only = ranked_collectors[0]
    settings.append(
        Setting(
            setting="medium",
            setting_type=f"fallback_single_{sanitize_name(only)}",
            collectors=[only],
            run_id=f"e7a_{base_run_id}_single_{sanitize_name(only)}",
        )
    )
    settings.append(
        Setting(
            setting="low",
            setting_type=f"fallback_single_{sanitize_name(only)}",
            collectors=[only],
            run_id=f"e7a_{base_run_id}_single_{sanitize_name(only)}_dup",
        )
    )
    return settings


def prepare_run_dir(
    runs_root: Path,
    base_run_id: str,
    target_run_id: str,
    selected_collectors: list[str],
    overwrite: bool,
) -> Path:
    base_dir = runs_root / base_run_id
    target_dir = runs_root / target_run_id

    if target_dir.exists():
        if (not overwrite) or (not target_run_id.startswith("e7a_")):
            raise RuntimeError(f"Refuse to overwrite existing run dir: {target_dir}")
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    for collector in selected_collectors:
        src = base_dir / f"collector={collector}"
        dst = target_dir / f"collector={collector}"
        if not src.exists():
            raise RuntimeError(f"collector dir missing: {src}")
        shutil.copytree(src, dst)

    for name in ["run.json", "run.log"]:
        src = base_dir / name
        if src.exists():
            shutil.copy2(src, target_dir / name)

    manifest = {
        "base_run_id": base_run_id,
        "derived_run_id": target_run_id,
        "selected_collectors": selected_collectors,
    }
    (target_dir / "visibility_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return target_dir


def rerun_pipeline(run_id: str, window_sec: int):
    py = sys.executable
    run_cmd([py, "scripts/build_event_units.py", "--run-id", run_id, "--window-sec", str(window_sec), "--prefer-rel", "true"])
    run_cmd([py, "scripts/build_historical_baseline.py", "--run-id", run_id, "--min-events", "1", "--overwrite", "true"])
    run_cmd([py, "scripts/build_weak_candidates.py", "--run-id", run_id, "--min-weak-rules", "2", "--overwrite", "true"])
    run_cmd([py, "scripts/score_weak_candidates.py", "--run-id", run_id, "--overwrite", "true"])
    run_cmd([py, "scripts/gate_scored_candidates.py", "--run-id", run_id, "--overwrite", "true"])
    run_cmd([py, "scripts/augment_uncertain_candidates.py", "--run-id", run_id, "--overwrite", "true"])
    run_cmd([py, "scripts/build_final_alerts.py", "--run-id", run_id, "--overwrite", "true"])


def build_event_signature_map(events_df: pd.DataFrame, window_sec: int) -> pd.DataFrame:
    out = events_df.copy()
    out["event_id"] = out["event_id"].fillna("").astype(str)
    out["prefix"] = out["prefix"].fillna("").astype(str)
    out["as_path_clean"] = out["as_path_clean"].fillna("").astype(str)
    out["origin_as_num"] = pd.to_numeric(out["origin_as"], errors="coerce").fillna(-1).astype(int)
    first_slot = (pd.to_numeric(out["first_seen"], errors="coerce").fillna(0.0) // float(window_sec)).astype(int)
    last_slot = (pd.to_numeric(out["last_seen"], errors="coerce").fillna(0.0) // float(window_sec)).astype(int)
    out["signature"] = (
        out["prefix"]
        + "|"
        + out["origin_as_num"].astype(str)
        + "|"
        + out["as_path_clean"]
        + "|"
        + first_slot.astype(str)
        + "|"
        + last_slot.astype(str)
    )
    return out[["event_id", "signature"]].drop_duplicates("event_id")


def extract_setting_metrics(run_dir: Path, setting_name: str, visible_collectors_count: int, window_sec: int) -> dict:
    event_summary = read_json(run_dir / "events" / "event_units_summary.json")
    candidate_summary = read_json(run_dir / "candidates" / "candidate_summary.json")
    score_summary = read_json(run_dir / "scores" / "score_summary.json")
    final_report = read_json(run_dir / "final" / "final_report.json")

    events_df = pd.read_parquet(run_dir / "events" / "event_units.parquet")
    event_sig_df = build_event_signature_map(events_df, window_sec)
    sig_map = dict(zip(event_sig_df["event_id"].astype(str), event_sig_df["signature"].astype(str)))

    candidate_df = pd.read_parquet(run_dir / "candidates" / "candidate_events.parquet")
    if "candidate_flag" in candidate_df.columns:
        candidate_df = candidate_df[candidate_df["candidate_flag"].fillna(False).astype(bool)]
    candidate_ids = candidate_df["event_id"].fillna("").astype(str).tolist()
    candidate_sigs = {sig_map[eid] for eid in candidate_ids if eid in sig_map}

    final_df = pd.read_parquet(run_dir / "final" / "final_alerts.parquet").copy()
    final_df["event_id"] = final_df["event_id"].fillna("").astype(str)
    final_df["signature"] = final_df["event_id"].map(sig_map)
    final_df = final_df[final_df["signature"].notna()].copy()
    final_df["final_alert_label"] = final_df["final_alert_label"].fillna("").astype(str)

    high_sigs = set(final_df.loc[final_df["final_alert_label"] == "high_priority_alert", "signature"].astype(str))
    needs_sigs = set(final_df.loc[final_df["final_alert_label"] == "needs_review", "signature"].astype(str))

    label_by_sig = (
        final_df[["signature", "final_alert_label"]]
        .drop_duplicates("signature", keep="first")
        .set_index("signature")["final_alert_label"]
        .to_dict()
    )

    high_df = final_df[final_df["final_alert_label"] == "high_priority_alert"].copy()
    missing_rate = (
        float(ensure_bool_col(high_df, "missing_origin_or_path").mean()) if len(high_df) else 0.0
    )

    return {
        "setting": setting_name,
        "visible_collectors_count": int(visible_collectors_count),
        "total_events": int(event_summary.get("total_events", 0)),
        "candidate_count": int(candidate_summary.get("candidate_events", 0)),
        "scored_count": int(score_summary.get("output_rows", 0)),
        "final_high": int(final_report.get("high_priority_alert_count", 0)),
        "final_needs": int(final_report.get("needs_review_count", 0)),
        "final_low": int(final_report.get("low_priority_or_background_count", 0)),
        "candidate_sigs": candidate_sigs,
        "high_sigs": high_sigs,
        "needs_sigs": needs_sigs,
        "label_by_sig": label_by_sig,
        "high_quality": {
            "setting": setting_name,
            "high_count": int(len(high_df)),
            "certainty_mean": safe_mean(high_df.get("certainty_score", pd.Series(dtype=float))),
            "conflict_mean": safe_mean(high_df.get("conflict_score", pd.Series(dtype=float))),
            "missing_rate": missing_rate,
        },
    }


def overlap_row(full_set: set[str], target_set: set[str], metric_name: str, setting: str) -> dict:
    overlap = len(full_set & target_set)
    return {
        "setting": setting,
        "metric": metric_name,
        "full_count": int(len(full_set)),
        "setting_count": int(len(target_set)),
        "overlap_count": int(overlap),
        "overlap_rate_over_full": safe_ratio(int(overlap), int(len(full_set))),
        "overlap_rate_over_setting": safe_ratio(int(overlap), int(len(target_set))),
    }


def classify_degradation(full_row: dict, reduced_rows: list[dict], overlap_rows: list[dict]) -> str:
    full_high = int(full_row["final_high"])
    if full_high <= 0:
        return "D"

    delta_high_sum = sum(int(r["final_high"] - full_row["final_high"]) for r in reduced_rows)
    delta_needs_sum = sum(int(r["final_needs"] - full_row["final_needs"]) for r in reduced_rows)

    lost_high_total = 0
    new_high_total = 0
    for r in overlap_rows:
        if r["metric"] == "high_overlap":
            full_count = int(r["full_count"])
            overlap_count = int(r["overlap_count"])
            setting_count = int(r["setting_count"])
            lost_high_total += max(0, full_count - overlap_count)
            new_high_total += max(0, setting_count - overlap_count)

    if lost_high_total <= 2 and new_high_total <= 2 and abs(delta_high_sum) <= 2 and abs(delta_needs_sum) <= 5:
        return "D"
    if new_high_total > lost_high_total and delta_high_sum > 0:
        return "C"
    if lost_high_total >= new_high_total:
        if delta_needs_sum >= 0:
            return "A"
        return "B"
    return "B"


def choose_final_tag(mode: str, full_row: dict, reduced_rows: list[dict]) -> str:
    if mode == "D":
        return "visibility_ablation=部分支持"

    full_high = int(full_row["final_high"])
    reduced_high = [int(r["final_high"]) for r in reduced_rows]
    if not reduced_high:
        return "visibility_ablation=暂不能判断"

    high_drop_exists = any(h < full_high for h in reduced_high)
    if mode in {"A", "B"} and high_drop_exists:
        return "visibility_ablation=支持主线"
    if mode == "C":
        return "visibility_ablation=不支持/需复查"
    return "visibility_ablation=部分支持"


def main():
    parser = argparse.ArgumentParser(
        description="E7-A collector visibility ablation: re-run full chain on deterministic collector subsets."
    )
    parser.add_argument("--base-run-id", default=DEFAULT_BASE_RUN_ID, help="Base run id.")
    parser.add_argument("--runs-root", default="data/runs", help="Runs root directory.")
    parser.add_argument("--output-dir", default=None, help="Output directory.")
    parser.add_argument("--window-sec", type=int, default=DEFAULT_WINDOW_SEC, help="Event window seconds.")
    parser.add_argument("--prefer-rel", default="true", help="Prefer __rel parquet when available (true/false).")
    parser.add_argument("--overwrite", default="true", help="Allow overwriting existing e7a run dirs (true/false).")
    args = parser.parse_args()

    prefer_rel = str(args.prefer_rel).strip().lower() in {"1", "true", "yes", "y", "on"}
    overwrite = str(args.overwrite).strip().lower() in {"1", "true", "yes", "y", "on"}

    runs_root = Path(args.runs_root)
    base_run_id = str(args.base_run_id).strip()
    base_run_dir = runs_root / base_run_id
    if not base_run_dir.exists():
        raise SystemExit(f"base run not found: {base_run_dir}")

    output_dir = Path(args.output_dir) if args.output_dir else Path("outputs") / f"e7a_visibility_ablation_{base_run_id}"
    output_dir.mkdir(parents=True, exist_ok=True)

    collectors = list_collectors(base_run_dir)
    if not collectors:
        raise SystemExit(f"no collector directories found in {base_run_dir}")

    contribution_rows = collect_contribution(base_run_dir, collectors, prefer_rel)
    pd.DataFrame(contribution_rows).to_csv(output_dir / "e7a_collector_contribution.csv", index=False, encoding="utf-8-sig")
    ranked_collectors = [r["collector"] for r in contribution_rows]

    settings = build_settings(base_run_id, ranked_collectors)
    settings_registry = []
    setting_metrics = []

    for setting in settings:
        run_dir = prepare_run_dir(
            runs_root=runs_root,
            base_run_id=base_run_id,
            target_run_id=setting.run_id,
            selected_collectors=setting.collectors,
            overwrite=overwrite,
        )
        rerun_pipeline(setting.run_id, args.window_sec)

        metrics = extract_setting_metrics(
            run_dir=run_dir,
            setting_name=setting.setting,
            visible_collectors_count=len(setting.collectors),
            window_sec=args.window_sec,
        )
        metrics["run_id"] = setting.run_id
        metrics["setting_type"] = setting.setting_type
        metrics["selected_collectors"] = ",".join(setting.collectors)
        setting_metrics.append(metrics)

        contrib_sum = sum(r["row_count"] for r in contribution_rows if r["collector"] in set(setting.collectors))
        settings_registry.append(
            {
                "setting": setting.setting,
                "setting_type": setting.setting_type,
                "run_id": setting.run_id,
                "visible_collectors_count": int(len(setting.collectors)),
                "selected_collectors": ",".join(setting.collectors),
                "selected_collectors_input_rows": int(contrib_sum),
            }
        )

    pd.DataFrame(settings_registry).to_csv(output_dir / "e7a_settings_registry.csv", index=False, encoding="utf-8-sig")

    flow_rows = [
        {
            "setting": m["setting"],
            "run_id": m["run_id"],
            "setting_type": m["setting_type"],
            "visible_collectors_count": int(m["visible_collectors_count"]),
            "total_events": int(m["total_events"]),
            "candidate_count": int(m["candidate_count"]),
            "scored_count": int(m["scored_count"]),
            "final_high": int(m["final_high"]),
            "final_needs": int(m["final_needs"]),
            "final_low": int(m["final_low"]),
        }
        for m in setting_metrics
    ]
    flow_df = pd.DataFrame(flow_rows)
    flow_df.to_csv(output_dir / "e7a_visibility_flow.csv", index=False, encoding="utf-8-sig")

    metric_map = {m["setting"]: m for m in setting_metrics}
    full = metric_map.get("full")
    if full is None:
        raise RuntimeError("missing full setting metrics")

    reduced_settings = [m for m in setting_metrics if m["setting"] != "full"]
    overlap_rows = []
    retention_rows = []

    for m in reduced_settings:
        setting_name = m["setting"]
        overlap_rows.append(overlap_row(full["candidate_sigs"], m["candidate_sigs"], "candidate_overlap", setting_name))
        overlap_rows.append(overlap_row(full["high_sigs"], m["high_sigs"], "high_overlap", setting_name))
        overlap_rows.append(overlap_row(full["needs_sigs"], m["needs_sigs"], "needs_overlap", setting_name))

        full_high = full["high_sigs"]
        target_high = m["high_sigs"]
        overlap_high = full_high & target_high
        lost_high = full_high - target_high
        new_high = target_high - full_high

        target_label_map = m["label_by_sig"]
        full_high_to_needs = sum(1 for sig in full_high if target_label_map.get(sig, "") == "needs_review")
        full_high_to_low = sum(1 for sig in full_high if target_label_map.get(sig, "") == "low_priority_or_background")
        full_high_absent = sum(1 for sig in full_high if sig not in target_label_map)

        full_label_map = full["label_by_sig"]
        new_high_from_full_needs = sum(1 for sig in new_high if full_label_map.get(sig, "") == "needs_review")
        new_high_from_full_low = sum(1 for sig in new_high if full_label_map.get(sig, "") == "low_priority_or_background")
        new_high_absent_in_full = sum(1 for sig in new_high if sig not in full_label_map)

        retention_rows.append(
            {
                "setting": setting_name,
                "full_high_count": int(len(full_high)),
                "full_high_retained_count": int(len(overlap_high)),
                "full_high_retention_rate": safe_ratio(int(len(overlap_high)), int(len(full_high))),
                "reduced_new_high_count": int(len(new_high)),
                "reduced_lost_full_high_count": int(len(lost_high)),
                "full_high_to_needs_count": int(full_high_to_needs),
                "full_high_to_low_count": int(full_high_to_low),
                "full_high_absent_count": int(full_high_absent),
                "new_high_from_full_needs_count": int(new_high_from_full_needs),
                "new_high_from_full_low_count": int(new_high_from_full_low),
                "new_high_absent_in_full_count": int(new_high_absent_in_full),
            }
        )

    overlap_df = pd.DataFrame(overlap_rows)
    overlap_df.to_csv(output_dir / "e7a_overlap_with_full.csv", index=False, encoding="utf-8-sig")

    retention_df = pd.DataFrame(retention_rows)
    retention_df.to_csv(output_dir / "e7a_full_high_retention.csv", index=False, encoding="utf-8-sig")

    quality_rows = [m["high_quality"] for m in setting_metrics]
    quality_df = pd.DataFrame(quality_rows)
    quality_df.to_csv(output_dir / "e7a_high_quality_compare.csv", index=False, encoding="utf-8-sig")

    mode = classify_degradation(
        full_row=full,
        reduced_rows=reduced_settings,
        overlap_rows=overlap_rows,
    )
    final_tag = choose_final_tag(mode, full, reduced_settings)

    summary = {
        "base_run_id": base_run_id,
        "runs_root": str(runs_root.resolve()),
        "output_dir": str(output_dir.resolve()),
        "collector_count": int(len(collectors)),
        "collector_ranking": contribution_rows,
        "settings": settings_registry,
        "flow": flow_rows,
        "degradation_mode": mode,
        "final_tag": final_tag,
    }
    (output_dir / "e7a_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"base_run_id={base_run_id}")
    print(f"collector_count={len(collectors)}")
    print("collector_ranking:")
    for row in contribution_rows:
        print(
            f"  - {row['collector']}: rows={row['row_count']} share={row['row_share']:.4f} "
            f"files={row['file_count']} kind={row['input_kind']}"
        )
    for row in flow_rows:
        print(
            f"setting={row['setting']} collectors={row['visible_collectors_count']} "
            f"events={row['total_events']} candidate={row['candidate_count']} scored={row['scored_count']} "
            f"high={row['final_high']} needs={row['final_needs']} low={row['final_low']} run_id={row['run_id']}"
        )
    print(f"degradation_mode={mode}")
    print(f"final_tag={final_tag}")


if __name__ == "__main__":
    main()
