import argparse
import json
import re
from pathlib import Path

import pandas as pd


DEFAULT_E7A_OUTPUT_DIR = "outputs/e7a_visibility_ablation_v01"
DEFAULT_RUNS_ROOT = "data/runs"
DEFAULT_WINDOW_SEC = 300


def safe_ratio(num: int, den: int) -> float:
    return float(num) / float(den) if den else 0.0


def sanitize_label(text: str) -> str:
    out = re.sub(r"[^a-zA-Z0-9]+", "_", str(text).strip())
    out = out.strip("_").lower()
    return out or "unknown"


def to_num_series(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series([0.0] * len(df), index=df.index, dtype=float)
    return pd.to_numeric(df[col], errors="coerce").fillna(0.0)


def load_settings(e7a_dir: Path) -> pd.DataFrame:
    path = e7a_dir / "e7a_settings_registry.csv"
    if not path.exists():
        raise SystemExit(f"missing e7a settings registry: {path}")
    df = pd.read_csv(path)
    required = {"setting", "run_id", "selected_collectors", "visible_collectors_count"}
    missing = required - set(df.columns)
    if missing:
        raise SystemExit(f"invalid settings registry columns, missing: {sorted(missing)}")
    return df


def event_signature_map(run_dir: Path, window_sec: int) -> tuple[dict[str, str], pd.DataFrame]:
    events = pd.read_parquet(run_dir / "events" / "event_units.parquet").copy()
    events["event_id"] = events["event_id"].fillna("").astype(str)
    events["prefix"] = events["prefix"].fillna("").astype(str)
    events["as_path_clean"] = events["as_path_clean"].fillna("").astype(str)
    events["origin_as_num"] = pd.to_numeric(events["origin_as"], errors="coerce").fillna(-1).astype(int)
    first_slot = (pd.to_numeric(events["first_seen"], errors="coerce").fillna(0.0) // float(window_sec)).astype(int)
    last_slot = (pd.to_numeric(events["last_seen"], errors="coerce").fillna(0.0) // float(window_sec)).astype(int)
    events["signature"] = (
        events["prefix"]
        + "|"
        + events["origin_as_num"].astype(str)
        + "|"
        + events["as_path_clean"]
        + "|"
        + first_slot.astype(str)
        + "|"
        + last_slot.astype(str)
    )
    sig_df = events[["event_id", "signature"]].drop_duplicates("event_id")
    return dict(zip(sig_df["event_id"], sig_df["signature"])), events


def candidate_sigs(run_dir: Path, sig_map: dict[str, str]) -> set[str]:
    cand = pd.read_parquet(run_dir / "candidates" / "candidate_events.parquet")
    if "candidate_flag" in cand.columns:
        cand = cand[cand["candidate_flag"].fillna(False).astype(bool)]
    ids = cand["event_id"].fillna("").astype(str)
    return {sig_map[eid] for eid in ids if eid in sig_map}


def final_payload(run_dir: Path, sig_map: dict[str, str]) -> tuple[pd.DataFrame, dict[str, str], set[str], set[str]]:
    final_df = pd.read_parquet(run_dir / "final" / "final_alerts.parquet").copy()
    final_df["event_id"] = final_df["event_id"].fillna("").astype(str)
    final_df["signature"] = final_df["event_id"].map(sig_map)
    final_df = final_df[final_df["signature"].notna()].copy()
    final_df["final_alert_label"] = final_df["final_alert_label"].fillna("").astype(str)
    label_by_sig = (
        final_df[["signature", "final_alert_label"]]
        .drop_duplicates("signature", keep="first")
        .set_index("signature")["final_alert_label"]
        .to_dict()
    )
    high = set(final_df.loc[final_df["final_alert_label"] == "high_priority_alert", "signature"].astype(str))
    needs = set(final_df.loc[final_df["final_alert_label"] == "needs_review", "signature"].astype(str))
    return final_df, label_by_sig, high, needs


def extract_flow_row(settings_row: pd.Series, run_dir: Path) -> dict:
    event_summary = json.loads((run_dir / "events" / "event_units_summary.json").read_text(encoding="utf-8"))
    candidate_summary = json.loads((run_dir / "candidates" / "candidate_summary.json").read_text(encoding="utf-8"))
    score_summary = json.loads((run_dir / "scores" / "score_summary.json").read_text(encoding="utf-8"))
    final_report = json.loads((run_dir / "final" / "final_report.json").read_text(encoding="utf-8"))

    collector_name = str(settings_row.get("selected_collectors", "")).strip()
    if collector_name:
        collector_label = f"{collector_name}_only"
    else:
        collector_label = str(settings_row.get("setting", "unknown"))

    return {
        "setting": str(settings_row["setting"]),
        "display_setting": collector_label if str(settings_row["setting"]) != "full" else "full",
        "run_id": str(settings_row["run_id"]),
        "visible_collectors_count": int(settings_row["visible_collectors_count"]),
        "selected_collectors": str(settings_row.get("selected_collectors", "")),
        "total_events": int(event_summary.get("total_events", 0)),
        "candidate_count": int(candidate_summary.get("candidate_events", 0)),
        "scored_count": int(score_summary.get("output_rows", 0)),
        "final_high": int(final_report.get("high_priority_alert_count", 0)),
        "final_needs": int(final_report.get("needs_review_count", 0)),
        "final_low": int(final_report.get("low_priority_or_background_count", 0)),
    }


def overlap_row(full_set: set[str], target_set: set[str], metric: str, setting: str, display_setting: str) -> dict:
    ov = len(full_set & target_set)
    return {
        "setting": setting,
        "display_setting": display_setting,
        "metric": metric,
        "full_count": int(len(full_set)),
        "setting_count": int(len(target_set)),
        "overlap_count": int(ov),
        "overlap_rate_over_full": safe_ratio(int(ov), int(len(full_set))),
        "overlap_rate_over_setting": safe_ratio(int(ov), int(len(target_set))),
    }


def direct_overlap_row(a_set: set[str], b_set: set[str], metric: str, a_display: str, b_display: str) -> dict:
    inter = len(a_set & b_set)
    union = len(a_set | b_set)
    return {
        "metric": metric,
        "a_setting": a_display,
        "b_setting": b_display,
        "a_count": int(len(a_set)),
        "b_count": int(len(b_set)),
        "intersection_count": int(inter),
        "intersection_rate_over_a": safe_ratio(int(inter), int(len(a_set))),
        "intersection_rate_over_b": safe_ratio(int(inter), int(len(b_set))),
        "jaccard_similarity": safe_ratio(int(inter), int(union)),
    }


def build_score_index(final_df: pd.DataFrame) -> pd.DataFrame:
    out = final_df.copy()
    out["signature"] = out["signature"].astype(str)
    out["risk_score"] = to_num_series(out, "risk_score")
    out["certainty_score"] = to_num_series(out, "certainty_score")
    out["final_alert_label"] = out["final_alert_label"].fillna("").astype(str)
    return out[["signature", "risk_score", "certainty_score", "final_alert_label"]].drop_duplicates("signature").set_index("signature")


def quality_anchor_row(
    full_idx: pd.DataFrame,
    target_idx: pd.DataFrame,
    signatures: set[str],
    setting: str,
    display_setting: str,
    subset: str,
) -> dict:
    sigs = sorted(signatures)
    if not sigs:
        return {
            "setting": setting,
            "display_setting": display_setting,
            "subset": subset,
            "count": 0,
            "full_risk_mean": 0.0,
            "target_risk_mean": 0.0,
            "risk_mean_delta_target_minus_full": 0.0,
            "full_certainty_mean": 0.0,
            "target_certainty_mean": 0.0,
            "certainty_mean_delta_target_minus_full": 0.0,
            "risk_drop_ge_3": False,
            "certainty_drop_ge_3": False,
            "risk_drop_ge_5": False,
            "certainty_drop_ge_5": False,
        }

    full_part = full_idx.loc[sigs]
    target_part = target_idx.loc[sigs]
    full_risk_mean = float(full_part["risk_score"].mean())
    target_risk_mean = float(target_part["risk_score"].mean())
    full_certainty_mean = float(full_part["certainty_score"].mean())
    target_certainty_mean = float(target_part["certainty_score"].mean())
    risk_delta = target_risk_mean - full_risk_mean
    certainty_delta = target_certainty_mean - full_certainty_mean
    return {
        "setting": setting,
        "display_setting": display_setting,
        "subset": subset,
        "count": int(len(sigs)),
        "full_risk_mean": full_risk_mean,
        "target_risk_mean": target_risk_mean,
        "risk_mean_delta_target_minus_full": risk_delta,
        "full_certainty_mean": full_certainty_mean,
        "target_certainty_mean": target_certainty_mean,
        "certainty_mean_delta_target_minus_full": certainty_delta,
        "risk_drop_ge_3": bool(risk_delta <= -3.0),
        "certainty_drop_ge_3": bool(certainty_delta <= -3.0),
        "risk_drop_ge_5": bool(risk_delta <= -5.0),
        "certainty_drop_ge_5": bool(certainty_delta <= -5.0),
    }


def full_high_destination(
    full_high: set[str],
    target_label_by_sig: dict[str, str],
    setting: str,
    display_setting: str,
) -> dict:
    retained = 0
    to_needs = 0
    to_low = 0
    missing = 0
    for sig in full_high:
        val = target_label_by_sig.get(sig, None)
        if val is None:
            missing += 1
        elif val == "high_priority_alert":
            retained += 1
        elif val == "needs_review":
            to_needs += 1
        elif val == "low_priority_or_background":
            to_low += 1
        else:
            missing += 1
    return {
        "setting": setting,
        "display_setting": display_setting,
        "full_high_count": int(len(full_high)),
        "retained_as_high": int(retained),
        "downgraded_to_needs_review": int(to_needs),
        "downgraded_to_low_priority_or_background": int(to_low),
        "missing_not_observed": int(missing),
        "full_high_retention_rate": safe_ratio(int(retained), int(len(full_high))),
        "full_high_lost_count": int(len(full_high) - retained),
        "full_high_lost_rate": safe_ratio(int(len(full_high) - retained), int(len(full_high))),
    }


def choose_examples(
    full_high: set[str],
    full_event_meta: pd.DataFrame,
    full_final_meta: pd.DataFrame,
    a_label_map: dict[str, str],
    b_label_map: dict[str, str],
    a_name: str,
    b_name: str,
    limit: int = 5,
) -> pd.DataFrame:
    full_event_index = full_event_meta.set_index("signature", drop=False)
    full_final_index = full_final_meta.set_index("signature", drop=False)
    rows = []
    for sig in sorted(full_high):
        a_status = a_label_map.get(sig, "missing")
        b_status = b_label_map.get(sig, "missing")
        if a_status == b_status:
            continue
        if sig not in full_event_index.index or sig not in full_final_index.index:
            continue
        e = full_event_index.loc[sig]
        f = full_final_index.loc[sig]
        a_reason = "not_observed_in_single_collector" if a_status == "missing" else f"observed_but_{a_status}"
        b_reason = "not_observed_in_single_collector" if b_status == "missing" else f"observed_but_{b_status}"
        rows.append(
            {
                "signature": sig,
                "full_event_id": str(e["event_id"]),
                "prefix": str(e["prefix"]),
                "origin_as": float(e["origin_as"]) if pd.notna(e["origin_as"]) else None,
                "as_path_clean": str(e["as_path_clean"]),
                "full_collector_set": str(e.get("collector_set", "")),
                "full_risk_score": float(f.get("risk_score", 0.0)),
                "full_certainty_score": float(f.get("certainty_score", 0.0)),
                "full_conflict_score": float(f.get("conflict_score", 0.0)),
                "full_alert_source_layer": str(f.get("alert_source_layer", "")),
                f"{a_name}_status": a_status,
                f"{b_name}_status": b_status,
                f"{a_name}_drop_reason": a_reason,
                f"{b_name}_drop_reason": b_reason,
            }
        )
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows)
    out = out.sort_values(["full_risk_score", "full_certainty_score"], ascending=[False, False]).head(limit)
    return out


def detect_layer_classification(full_row: dict, a_row: dict, b_row: dict) -> str:
    full_events = int(full_row["total_events"])
    full_candidates = int(full_row["candidate_count"])
    full_high = int(full_row["final_high"])

    avg_event_ret = safe_ratio(int(a_row["total_events"]) + int(b_row["total_events"]), full_events * 2)
    avg_cand_ret = safe_ratio(int(a_row["candidate_count"]) + int(b_row["candidate_count"]), full_candidates * 2)
    avg_high_ret = safe_ratio(int(a_row["final_high"]) + int(b_row["final_high"]), full_high * 2)

    # Prefer D when all layers shift but high retention drops most.
    if avg_event_ret < 0.8 and avg_cand_ret < 0.8 and avg_high_ret < avg_cand_ret:
        return "D"
    if avg_event_ret < 0.8 and avg_cand_ret >= 0.8:
        return "A"
    if avg_event_ret >= 0.8 and avg_cand_ret < 0.8:
        return "B"
    if avg_high_ret < 0.5:
        return "C"
    return "D"


def choose_final_tag(high_ret_a: int, high_ret_b: int, cand_a: int, cand_b: int) -> str:
    high_gap = abs(high_ret_a - high_ret_b)
    cand_gap = abs(cand_a - cand_b)
    if high_gap >= 3 or cand_gap >= 150:
        return "collector_structure=存在显著差异"
    if high_gap >= 1 or cand_gap >= 50:
        return "collector_structure=存在一定差异"
    return "collector_structure=差异有限/暂不明显"


def main():
    parser = argparse.ArgumentParser(
        description="E7-B two-collector structural comparison based on E7-A full/single-collector runs."
    )
    parser.add_argument("--e7a-output-dir", default=DEFAULT_E7A_OUTPUT_DIR, help="E7-A output directory.")
    parser.add_argument("--runs-root", default=DEFAULT_RUNS_ROOT, help="Runs root.")
    parser.add_argument("--window-sec", type=int, default=DEFAULT_WINDOW_SEC, help="Window seconds for event signature.")
    parser.add_argument("--output-dir", default="outputs/e7b_collector_structure_v01", help="Output dir.")
    parser.add_argument("--sample-limit", type=int, default=5, help="Max asymmetric full-high samples.")
    args = parser.parse_args()

    e7a_dir = Path(args.e7a_output_dir)
    runs_root = Path(args.runs_root)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    settings = load_settings(e7a_dir)
    full_df = settings[settings["setting"] == "full"].copy()
    reduced_df = settings[settings["setting"] != "full"].copy()
    if len(full_df) != 1 or len(reduced_df) != 2:
        raise SystemExit("E7-B requires exactly one full and two single-collector settings in E7-A registry.")

    full_row = full_df.iloc[0]
    a_row = reduced_df.iloc[0]
    b_row = reduced_df.iloc[1]

    # Keep deterministic order by run_id for stable outputs.
    if str(a_row["run_id"]) > str(b_row["run_id"]):
        a_row, b_row = b_row, a_row

    full_run_dir = runs_root / str(full_row["run_id"])
    a_run_dir = runs_root / str(a_row["run_id"])
    b_run_dir = runs_root / str(b_row["run_id"])
    for p in [full_run_dir, a_run_dir, b_run_dir]:
        if not p.exists():
            raise SystemExit(f"run dir not found: {p}")

    full_sig_map, full_events = event_signature_map(full_run_dir, args.window_sec)
    a_sig_map, _ = event_signature_map(a_run_dir, args.window_sec)
    b_sig_map, _ = event_signature_map(b_run_dir, args.window_sec)

    full_candidate = candidate_sigs(full_run_dir, full_sig_map)
    a_candidate = candidate_sigs(a_run_dir, a_sig_map)
    b_candidate = candidate_sigs(b_run_dir, b_sig_map)

    full_final, full_label_map, full_high, full_needs = final_payload(full_run_dir, full_sig_map)
    a_final, a_label_map, a_high, a_needs = final_payload(a_run_dir, a_sig_map)
    b_final, b_label_map, b_high, b_needs = final_payload(b_run_dir, b_sig_map)

    flow_rows = [
        extract_flow_row(full_row, full_run_dir),
        extract_flow_row(a_row, a_run_dir),
        extract_flow_row(b_row, b_run_dir),
    ]
    flow_df = pd.DataFrame(flow_rows)
    flow_df.to_csv(output_dir / "e7b_three_setting_flow.csv", index=False, encoding="utf-8-sig")

    a_display = flow_rows[1]["display_setting"]
    b_display = flow_rows[2]["display_setting"]

    overlap_rows = [
        overlap_row(full_candidate, a_candidate, "candidate_overlap", str(a_row["setting"]), a_display),
        overlap_row(full_candidate, b_candidate, "candidate_overlap", str(b_row["setting"]), b_display),
        overlap_row(full_high, a_high, "high_overlap", str(a_row["setting"]), a_display),
        overlap_row(full_high, b_high, "high_overlap", str(b_row["setting"]), b_display),
        overlap_row(full_needs, a_needs, "needs_overlap", str(a_row["setting"]), a_display),
        overlap_row(full_needs, b_needs, "needs_overlap", str(b_row["setting"]), b_display),
    ]
    overlap_df = pd.DataFrame(overlap_rows)
    overlap_df.to_csv(output_dir / "e7b_overlap_with_full.csv", index=False, encoding="utf-8-sig")

    direct_rows = [
        direct_overlap_row(a_candidate, b_candidate, "candidate_direct_overlap", a_display, b_display),
        direct_overlap_row(a_needs, b_needs, "needs_direct_overlap", a_display, b_display),
        direct_overlap_row(a_high, b_high, "high_direct_overlap", a_display, b_display),
    ]
    direct_df = pd.DataFrame(direct_rows)
    direct_df.to_csv(output_dir / "e7b_ab_direct_overlap.csv", index=False, encoding="utf-8-sig")

    dest_rows = [
        full_high_destination(full_high, a_label_map, str(a_row["setting"]), a_display),
        full_high_destination(full_high, b_label_map, str(b_row["setting"]), b_display),
    ]
    dest_df = pd.DataFrame(dest_rows)
    dest_df["reduced_only_high_count"] = [
        int(len(a_high - full_high)),
        int(len(b_high - full_high)),
    ]
    dest_df.to_csv(output_dir / "e7b_full_high_destinations.csv", index=False, encoding="utf-8-sig")

    a_retained_sigs = {s for s in full_high if a_label_map.get(s, "") == "high_priority_alert"}
    b_retained_sigs = {s for s in full_high if b_label_map.get(s, "") == "high_priority_alert"}
    a_needs_sigs = {s for s in full_high if a_label_map.get(s, "") == "needs_review"}
    b_needs_sigs = {s for s in full_high if b_label_map.get(s, "") == "needs_review"}

    full_idx = build_score_index(full_final)
    a_idx = build_score_index(a_final)
    b_idx = build_score_index(b_final)
    quality_anchor_rows = [
        quality_anchor_row(full_idx, a_idx, a_retained_sigs, str(a_row["setting"]), a_display, "retained_as_high"),
        quality_anchor_row(full_idx, b_idx, b_retained_sigs, str(b_row["setting"]), b_display, "retained_as_high"),
        quality_anchor_row(full_idx, a_idx, a_needs_sigs, str(a_row["setting"]), a_display, "downgraded_to_needs_review"),
        quality_anchor_row(full_idx, b_idx, b_needs_sigs, str(b_row["setting"]), b_display, "downgraded_to_needs_review"),
    ]
    quality_anchor_df = pd.DataFrame(quality_anchor_rows)
    quality_anchor_df.to_csv(output_dir / "e7b_full_high_quality_anchor.csv", index=False, encoding="utf-8-sig")

    full_event_meta = full_events[
        [
            "event_id",
            "signature",
            "prefix",
            "origin_as",
            "as_path_clean",
            "collector_set",
            "record_count",
            "collector_count",
            "visibility_count",
        ]
    ].drop_duplicates("signature")
    full_final_meta = full_final[
        [
            "event_id",
            "signature",
            "risk_score",
            "certainty_score",
            "conflict_score",
            "gating_label",
            "augmentation_label",
            "alert_source_layer",
        ]
    ].drop_duplicates("signature")
    samples_df = choose_examples(
        full_high=full_high,
        full_event_meta=full_event_meta,
        full_final_meta=full_final_meta,
        a_label_map=a_label_map,
        b_label_map=b_label_map,
        a_name=sanitize_label(a_display),
        b_name=sanitize_label(b_display),
        limit=args.sample_limit,
    )
    if not samples_df.empty:
        samples_df.to_csv(output_dir / "e7b_asymmetric_full_high_samples.csv", index=False, encoding="utf-8-sig")
    else:
        pd.DataFrame(columns=["note"]).to_csv(output_dir / "e7b_asymmetric_full_high_samples.csv", index=False, encoding="utf-8-sig")

    layer_cls = detect_layer_classification(flow_rows[0], flow_rows[1], flow_rows[2])
    final_tag = choose_final_tag(
        high_ret_a=int(dest_rows[0]["retained_as_high"]),
        high_ret_b=int(dest_rows[1]["retained_as_high"]),
        cand_a=int(flow_rows[1]["candidate_count"]),
        cand_b=int(flow_rows[2]["candidate_count"]),
    )

    summary = {
        "base_e7a_output_dir": str(e7a_dir.resolve()),
        "runs_root": str(runs_root.resolve()),
        "output_dir": str(output_dir.resolve()),
        "settings": [
            {"setting": flow_rows[0]["setting"], "display_setting": flow_rows[0]["display_setting"], "run_id": flow_rows[0]["run_id"]},
            {"setting": flow_rows[1]["setting"], "display_setting": flow_rows[1]["display_setting"], "run_id": flow_rows[1]["run_id"]},
            {"setting": flow_rows[2]["setting"], "display_setting": flow_rows[2]["display_setting"], "run_id": flow_rows[2]["run_id"]},
        ],
        "which_collector_keeps_more_candidate": flow_rows[1]["display_setting"]
        if flow_rows[1]["candidate_count"] >= flow_rows[2]["candidate_count"]
        else flow_rows[2]["display_setting"],
        "which_collector_keeps_more_high": flow_rows[1]["display_setting"]
        if flow_rows[1]["final_high"] >= flow_rows[2]["final_high"]
        else flow_rows[2]["display_setting"],
        "ab_direct_overlap": direct_rows,
        "full_high_quality_anchor": quality_anchor_rows,
        "layer_difference_classification": layer_cls,
        "final_tag": final_tag,
    }
    (output_dir / "e7b_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"full={flow_rows[0]['run_id']}")
    print(f"a_only={flow_rows[1]['run_id']} ({flow_rows[1]['display_setting']})")
    print(f"b_only={flow_rows[2]['run_id']} ({flow_rows[2]['display_setting']})")
    print(
        f"candidate_retained_vs_full: {flow_rows[1]['display_setting']}={len(full_candidate & a_candidate)}/{len(full_candidate)} "
        f"{flow_rows[2]['display_setting']}={len(full_candidate & b_candidate)}/{len(full_candidate)}"
    )
    print(
        f"high_retained_vs_full: {flow_rows[1]['display_setting']}={len(full_high & a_high)}/{len(full_high)} "
        f"{flow_rows[2]['display_setting']}={len(full_high & b_high)}/{len(full_high)}"
    )
    print(
        "ab_direct_overlap: "
        f"candidate={direct_rows[0]['intersection_count']} "
        f"needs={direct_rows[1]['intersection_count']} "
        f"high={direct_rows[2]['intersection_count']}"
    )
    print(f"layer_difference_classification={layer_cls}")
    print(f"final_tag={final_tag}")


if __name__ == "__main__":
    main()
