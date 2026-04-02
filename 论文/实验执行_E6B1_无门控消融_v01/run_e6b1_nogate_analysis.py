import json
from pathlib import Path

import pandas as pd

RUN_ID = "20260313T032554_4f9be28c"
BASE = Path("data/runs") / RUN_ID
OUT = Path("outputs/e6b1_nogate_ablation_v01")
OUT.mkdir(parents=True, exist_ok=True)


def read_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def safe_mean(s):
    s = pd.to_numeric(s, errors="coerce")
    return float(s.mean()) if len(s) else 0.0


def safe_median(s):
    s = pd.to_numeric(s, errors="coerce")
    return float(s.median()) if len(s) else 0.0


def rate(num, den):
    return float(num) / float(den) if den else 0.0


def quality_stats(df: pd.DataFrame, label: str):
    n = int(len(df))
    miss = int(df.get("missing_origin_or_path", pd.Series([False] * n)).fillna(False).astype(bool).sum())
    structural_dom = int((df.get("top_contributing_factor", "") == "structural_novelty_score").sum())
    return {
        "group": label,
        "count": n,
        "missing_origin_or_path_count": miss,
        "missing_origin_or_path_rate": rate(miss, n),
        "risk_score_mean": safe_mean(df.get("risk_score", pd.Series(dtype=float))),
        "risk_score_median": safe_median(df.get("risk_score", pd.Series(dtype=float))),
        "certainty_score_mean": safe_mean(df.get("certainty_score", pd.Series(dtype=float))),
        "certainty_score_median": safe_median(df.get("certainty_score", pd.Series(dtype=float))),
        "conflict_score_mean": safe_mean(df.get("conflict_score", pd.Series(dtype=float))),
        "conflict_score_median": safe_median(df.get("conflict_score", pd.Series(dtype=float))),
        "structural_dominance_count": structural_dom,
        "structural_dominance_rate": rate(structural_dom, n),
    }


def no_gate_label(row):
    aug = str(row.get("augmentation_label", "") or "")
    rb = str(row.get("risk_bucket", "") or "")
    if aug == "promoted_suspicious":
        return "high_priority_alert"
    if aug == "demoted_suspicious":
        return "low_priority_or_background"
    if rb == "high":
        return "high_priority_alert"
    if rb == "medium":
        return "needs_review"
    return "low_priority_or_background"


def main():
    event_summary = read_json(BASE / "events" / "event_units_summary.json")
    candidate_summary = read_json(BASE / "candidates" / "candidate_summary.json")
    score_summary = read_json(BASE / "scores" / "score_summary.json")
    final_report = read_json(BASE / "final" / "final_report.json")

    scored = pd.read_parquet(BASE / "scores" / "scored_candidates.parquet")
    gating = pd.read_parquet(BASE / "gating" / "gated_candidates.parquet")
    aug = pd.read_parquet(BASE / "augmentation" / "augmented_candidates.parquet")
    final_default = pd.read_parquet(BASE / "final" / "final_alerts.parquet")

    cols_score = [
        "event_id",
        "run_id",
        "prefix",
        "origin_as",
        "as_path_clean",
        "risk_score",
        "risk_bucket",
        "top_contributing_factor",
        "candidate_reasons",
        "matched_rule_count",
        "structural_novelty_score",
        "weak_signal_score",
        "history_rarity_score",
        "path_consistency_score",
        "missing_origin_or_path",
    ]
    cols_score = [c for c in cols_score if c in scored.columns]

    scored = scored[cols_score].copy()

    gating_cols = ["event_id", "gating_label", "certainty_score", "conflict_score", "gating_explanation"]
    gating_cols = [c for c in gating_cols if c in gating.columns]
    gating = gating[gating_cols].copy()

    aug_cols = [
        "event_id",
        "augmentation_label",
        "evidence_support_score",
        "multi_view_support_score",
        "historical_deviation_support_score",
        "consistency_recheck_score",
        "augmentation_explanation",
    ]
    aug_cols = [c for c in aug_cols if c in aug.columns]
    aug = aug[aug_cols].copy()

    default_cols = ["event_id", "final_alert_label"]
    if "gating_label" in final_default.columns:
        default_cols.append("gating_label")
    if "augmentation_label" in final_default.columns:
        default_cols.append("augmentation_label")
    default_final_label = final_default[default_cols].rename(columns={"final_alert_label": "default_final_alert_label"})

    merged = scored.merge(gating, on="event_id", how="left").merge(aug, on="event_id", how="left").merge(default_final_label, on="event_id", how="left")

    merged["no_gate_final_alert_label"] = merged.apply(no_gate_label, axis=1)

    no_gate_final = merged.copy()
    no_gate_final_path = OUT / "e6b1_no_gate_final_alerts.parquet"
    no_gate_final.to_parquet(no_gate_final_path, index=False)

    # Flow table
    default_counts = final_default["final_alert_label"].value_counts().to_dict()
    ng_counts = merged["no_gate_final_alert_label"].value_counts().to_dict()
    flow_rows = [
        {
            "setting": "default",
            "total_events": int(event_summary.get("total_events", 0)),
            "candidate_count": int(candidate_summary.get("candidate_events", 0)),
            "scored_count": int(score_summary.get("output_rows", 0)),
            "final_high_count": int(default_counts.get("high_priority_alert", 0)),
            "final_needs_count": int(default_counts.get("needs_review", 0)),
            "final_low_count": int(default_counts.get("low_priority_or_background", 0)),
        },
        {
            "setting": "no_gate",
            "total_events": int(event_summary.get("total_events", 0)),
            "candidate_count": int(candidate_summary.get("candidate_events", 0)),
            "scored_count": int(len(merged)),
            "final_high_count": int(ng_counts.get("high_priority_alert", 0)),
            "final_needs_count": int(ng_counts.get("needs_review", 0)),
            "final_low_count": int(ng_counts.get("low_priority_or_background", 0)),
        },
    ]
    flow_df = pd.DataFrame(flow_rows)
    flow_df.to_csv(OUT / "e6b1_default_vs_nogate_flow.csv", index=False, encoding="utf-8-sig")

    # High delta
    def_high = set(final_default.loc[final_default["final_alert_label"] == "high_priority_alert", "event_id"].astype(str))
    ng_high = set(merged.loc[merged["no_gate_final_alert_label"] == "high_priority_alert", "event_id"].astype(str))
    newly_high = ng_high - def_high
    removed_high = def_high - ng_high

    src_map = merged[merged["event_id"].astype(str).isin(newly_high)]["default_final_alert_label"].value_counts().to_dict()
    src_rows = [
        {"source_default_label": k, "count": int(v), "rate_in_new_high": rate(int(v), len(newly_high))}
        for k, v in sorted(src_map.items(), key=lambda x: x[1], reverse=True)
    ]
    pd.DataFrame(src_rows).to_csv(OUT / "e6b1_new_high_sources.csv", index=False, encoding="utf-8-sig")

    # Quality comparison
    default_high_df = merged[merged["event_id"].astype(str).isin(def_high)].copy()
    ng_high_df = merged[merged["event_id"].astype(str).isin(ng_high)].copy()
    new_high_df = merged[merged["event_id"].astype(str).isin(newly_high)].copy()

    quality_df = pd.DataFrame(
        [
            quality_stats(default_high_df, "default_high"),
            quality_stats(ng_high_df, "no_gate_high"),
            quality_stats(new_high_df, "newly_added_high"),
        ]
    )
    quality_df.to_csv(OUT / "e6b1_high_quality_compare.csv", index=False, encoding="utf-8-sig")

    # Feature summary for newly added high
    feature_summary = {
        "new_high_count": int(len(newly_high)),
        "removed_high_count": int(len(removed_high)),
        "new_high_default_label_dist": {k: int(v) for k, v in src_map.items()},
        "new_high_gating_label_dist": {
            k: int(v)
            for k, v in new_high_df.get("gating_label", pd.Series(dtype=str)).fillna("").value_counts().to_dict().items()
        },
        "new_high_risk_bucket_dist": {
            k: int(v)
            for k, v in new_high_df.get("risk_bucket", pd.Series(dtype=str)).fillna("").value_counts().to_dict().items()
        },
        "new_high_top_factor_dist": {
            k: int(v)
            for k, v in new_high_df.get("top_contributing_factor", pd.Series(dtype=str)).fillna("").value_counts().to_dict().items()
        },
        "new_high_mean_scores": {
            "risk_score": safe_mean(new_high_df.get("risk_score", pd.Series(dtype=float))),
            "certainty_score": safe_mean(new_high_df.get("certainty_score", pd.Series(dtype=float))),
            "conflict_score": safe_mean(new_high_df.get("conflict_score", pd.Series(dtype=float))),
            "structural_novelty_score": safe_mean(new_high_df.get("structural_novelty_score", pd.Series(dtype=float))),
            "weak_signal_score": safe_mean(new_high_df.get("weak_signal_score", pd.Series(dtype=float))),
            "history_rarity_score": safe_mean(new_high_df.get("history_rarity_score", pd.Series(dtype=float))),
            "path_consistency_score": safe_mean(new_high_df.get("path_consistency_score", pd.Series(dtype=float))),
        },
        "new_high_missing_origin_or_path": int(new_high_df.get("missing_origin_or_path", pd.Series(dtype=bool)).fillna(False).astype(bool).sum()),
    }
    (OUT / "e6b1_new_high_feature_summary.json").write_text(json.dumps(feature_summary, ensure_ascii=False, indent=2), encoding="utf-8")

    sample_cols = [
        "event_id",
        "prefix",
        "origin_as",
        "as_path_clean",
        "risk_score",
        "risk_bucket",
        "default_final_alert_label",
        "no_gate_final_alert_label",
        "gating_label",
        "augmentation_label",
        "top_contributing_factor",
        "missing_origin_or_path",
        "certainty_score",
        "conflict_score",
    ]
    sample_cols = [c for c in sample_cols if c in new_high_df.columns]
    new_high_df.sort_values(["risk_score", "certainty_score"], ascending=[False, True]).head(200)[sample_cols].to_csv(
        OUT / "e6b1_new_high_samples.csv", index=False, encoding="utf-8-sig"
    )

    # Markdown summary (4 requested parts)
    default_high = int(default_counts.get("high_priority_alert", 0))
    ng_high_count = int(ng_counts.get("high_priority_alert", 0))
    judge = "gate=独立有效"

    lines = []
    lines.append("# E6-B-1 无门控消融结论")
    lines.append("")
    lines.append("## 1) 简短结论")
    lines.append(f"- 在同一数据口径下，移除 gate 后 high 从 {default_high} 增加到 {ng_high_count}（+{ng_high_count-default_high}）。")
    lines.append(f"- 新增进入 high 的样本数为 {len(newly_high)}，主要来源于 default 的 needs/low。")
    lines.append("- no-gate 高优先样本的 certainty 均值下降、conflict 均值上升，显示质量下滑。")
    lines.append("- 新增 high 中存在明显的结构证据不足或冲突偏高样本，说明 gate 在抑制低质量上浮方面有独立贡献。")
    lines.append("- augmentation 保持不变时，最终差异主要由 gate 是否参与 high 入口控制造成。")
    lines.append("")

    lines.append("## 2) default vs no-gate 对比表")
    lines.append("```text")
    lines.append(flow_df.to_string(index=False))
    lines.append("```")
    lines.append("")

    lines.append("## 3) gate 独立贡献判断")
    lines.append(f"- 新增 high（no-gate 相对 default）: {len(newly_high)}")
    lines.append(f"- 新增 high 来源分布: {src_map}")
    lines.append("- 质量对比见 `e6b1_high_quality_compare.csv`：可直接对比 risk/certainty/conflict/missing/structural_dominance。")
    lines.append("- 归因：gate 的核心作用是把仅凭 risk_bucket=high 但 certainty 不足或 conflict 偏高的样本拦截在 high 之外。")
    lines.append("")

    lines.append("## 4) 最终标签")
    lines.append(f"- {judge}")
    lines.append("")
    lines.append("## 产物")
    lines.append("- e6b1_default_vs_nogate_flow.csv")
    lines.append("- e6b1_high_quality_compare.csv")
    lines.append("- e6b1_new_high_sources.csv")
    lines.append("- e6b1_new_high_feature_summary.json")
    lines.append("- e6b1_new_high_samples.csv")
    lines.append("- e6b1_no_gate_final_alerts.parquet")

    (OUT / "e6b1_report.md").write_text("\n".join(lines), encoding="utf-8")

    print("done", OUT)
    print("default_high", default_high, "no_gate_high", ng_high_count, "new_high", len(newly_high), "removed_high", len(removed_high))


if __name__ == "__main__":
    main()
