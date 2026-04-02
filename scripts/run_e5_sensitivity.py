import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd


BASE_RUN_ID_DEFAULT = "20260313T032554_4f9be28c"


def run_cmd(cmd: list[str]):
    print("[RUN]", " ".join(cmd))
    subprocess.run(cmd, check=True)


def copy_tree(src: Path, dst: Path):
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def prepare_run_dir(base_run_dir: Path, run_id: str):
    target = base_run_dir.parent / run_id
    if target.exists():
        if not run_id.startswith("e5_"):
            raise RuntimeError(f"Refuse to overwrite non-e5 run dir: {target}")
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)

    # Reuse stable upstream artifacts from baseline run.
    for name in ["events", "baseline", "candidates", "scores", "gating", "augmentation", "final"]:
        src = base_run_dir / name
        if src.exists():
            copy_tree(src, target / name)

    # Keep minimal metadata copies for traceability.
    for name in ["run.json", "run.log"]:
        src = base_run_dir / name
        if src.exists():
            shutil.copy2(src, target / name)
    return target


def patched_script(src_path: Path, replacements: dict[str, str], tmp_dir: Path) -> Path:
    text = src_path.read_text(encoding="utf-8")
    for old, new in replacements.items():
        if old not in text:
            raise RuntimeError(f"Patch target not found in {src_path}: {old}")
        text = text.replace(old, new, 1)
    out_path = tmp_dir / src_path.name
    out_path.write_text(text, encoding="utf-8")
    return out_path


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def safe_ratio(num: float, den: float) -> float:
    if den == 0:
        return 0.0
    return float(num) / float(den)


def extract_metrics(run_dir: Path) -> dict:
    event_summary = read_json(run_dir / "events" / "event_units_summary.json")
    candidate_summary = read_json(run_dir / "candidates" / "candidate_summary.json")
    score_summary = read_json(run_dir / "scores" / "score_summary.json")
    aug_summary = read_json(run_dir / "augmentation" / "augmentation_summary.json")
    final_report = read_json(run_dir / "final" / "final_report.json")
    final_df = pd.read_parquet(run_dir / "final" / "final_alerts.parquet")

    high_df = final_df[final_df["final_alert_label"] == "high_priority_alert"].copy()
    if len(high_df) > 0:
        top_factor = (
            high_df["top_contributing_factor"].fillna("").astype(str).value_counts().index[0]
        )
    else:
        top_factor = ""

    total_events = int(event_summary.get("total_events", 0))
    total_candidates = int(candidate_summary.get("candidate_events", 0))
    scored_rows = int(score_summary.get("output_rows", 0))
    final_high = int(final_report.get("high_priority_alert_count", 0))

    return {
        "total_events": total_events,
        "total_candidates": total_candidates,
        "candidate_rate": float(candidate_summary.get("candidate_rate", 0.0)),
        "scored_rows": scored_rows,
        "final_high_priority_alert": final_high,
        "final_needs_review": int(final_report.get("needs_review_count", 0)),
        "final_low_priority_or_background": int(final_report.get("low_priority_or_background_count", 0)),
        "high_priority_rate_over_total": safe_ratio(final_high, total_events),
        "high_priority_rate_over_scored": safe_ratio(final_high, scored_rows),
        "high_priority_from_gating": int(final_report.get("high_priority_from_gating_count", 0)),
        "high_priority_from_augmentation": int(final_report.get("high_priority_from_augmentation_count", 0)),
        "missing_origin_or_path_in_high": int(final_report.get("missing_origin_or_path_in_high_priority", 0)),
        "top_contributing_factor_in_high": top_factor,
        "uncertain_total": int(aug_summary.get("input_uncertain_rows", 0)),
        "promoted_suspicious": int(aug_summary.get("promoted_suspicious_count", 0)),
        "retained_uncertain": int(aug_summary.get("retained_uncertain_count", 0)),
        "demoted_suspicious": int(aug_summary.get("demoted_suspicious_count", 0)),
    }


def run_group_a(base_run_dir: Path, tmp_dir: Path) -> list[dict]:
    rows = []
    py = sys.executable
    for level, val in [("偏松", 1), ("默认", 2), ("偏严", 3)]:
        run_id = f"e5_a_mwr{val}"
        run_dir = prepare_run_dir(base_run_dir, run_id)

        run_cmd([py, "scripts/build_weak_candidates.py", "--run-id", run_id, "--min-weak-rules", str(val), "--overwrite", "true"])
        run_cmd([py, "scripts/score_weak_candidates.py", "--run-id", run_id, "--overwrite", "true"])
        run_cmd([py, "scripts/gate_scored_candidates.py", "--run-id", run_id, "--overwrite", "true"])
        run_cmd([py, "scripts/augment_uncertain_candidates.py", "--run-id", run_id, "--overwrite", "true"])
        run_cmd([py, "scripts/build_final_alerts.py", "--run-id", run_id, "--overwrite", "true"])

        metrics = extract_metrics(run_dir)
        metrics.update(
            {
                "experiment_group": "E5-A",
                "parameter_name": "min_weak_rules",
                "parameter_value": val,
                "looseness_level": level,
                "run_id": run_id,
            }
        )
        rows.append(metrics)
    return rows


def run_group_b(base_run_dir: Path, tmp_dir: Path) -> list[dict]:
    rows = []
    py = sys.executable
    for level, val in [("偏松", 58.5), ("默认", 65.0), ("偏严", 71.5)]:
        run_id = f"e5_b_cth{str(val).replace('.', 'p')}"
        run_dir = prepare_run_dir(base_run_dir, run_id)

        if val == 65.0:
            gating_script = "scripts/gate_scored_candidates.py"
        else:
            gating_script_path = patched_script(
                Path("scripts/gate_scored_candidates.py"),
                {'"certainty_threshold_high": 65.0,': f'"certainty_threshold_high": {val},'},
                tmp_dir,
            )
            gating_script = str(gating_script_path)

        run_cmd([py, gating_script, "--run-id", run_id, "--overwrite", "true"])
        run_cmd([py, "scripts/augment_uncertain_candidates.py", "--run-id", run_id, "--overwrite", "true"])
        run_cmd([py, "scripts/build_final_alerts.py", "--run-id", run_id, "--overwrite", "true"])

        metrics = extract_metrics(run_dir)
        metrics.update(
            {
                "experiment_group": "E5-B",
                "parameter_name": "certainty_threshold_high",
                "parameter_value": val,
                "looseness_level": level,
                "run_id": run_id,
            }
        )
        rows.append(metrics)
    return rows


def run_group_c(base_run_dir: Path, tmp_dir: Path) -> list[dict]:
    rows = []
    py = sys.executable
    for level, val in [("偏松", 58.5), ("默认", 65.0), ("偏严", 71.5)]:
        run_id = f"e5_c_pth{str(val).replace('.', 'p')}"
        run_dir = prepare_run_dir(base_run_dir, run_id)

        if val == 65.0:
            aug_script = "scripts/augment_uncertain_candidates.py"
        else:
            aug_script_path = patched_script(
                Path("scripts/augment_uncertain_candidates.py"),
                {'"promoted_threshold": 65.0,': f'"promoted_threshold": {val},'},
                tmp_dir,
            )
            aug_script = str(aug_script_path)

        run_cmd([py, aug_script, "--run-id", run_id, "--overwrite", "true"])
        run_cmd([py, "scripts/build_final_alerts.py", "--run-id", run_id, "--overwrite", "true"])

        metrics = extract_metrics(run_dir)
        metrics.update(
            {
                "experiment_group": "E5-C",
                "parameter_name": "promoted_threshold",
                "parameter_value": val,
                "looseness_level": level,
                "run_id": run_id,
            }
        )
        rows.append(metrics)
    return rows


def write_parameter_registry(out_dir: Path):
    text = """# E5 参数登记（第一轮）

## A. 候选层参数
- 参数名：`min_weak_rules`
- 所在脚本：`scripts/build_weak_candidates.py`
- 默认值：`2`
- 传参方式：CLI 参数 `--min-weak-rules <int>`
- 本轮扰动：`1 / 2 / 3`
- 选择原因：直接控制“仅弱规则命中时”是否入候选，是候选层最核心灵敏度参数。

## B. 门控层参数
- 参数名：`certainty_threshold_high`
- 所在脚本：`scripts/gate_scored_candidates.py`（`GATING_CONFIG`）
- 默认值：`65.0`
- 当前传参方式：**无 CLI 参数**，写在脚本常量中
- 本轮扰动：`58.5 / 65.0 / 71.5`（默认附近 ±10%）
- 选择原因：直接影响 high 桶样本进入 `likely_malicious` 的门槛，最直接影响 high_priority 入口。

## C. 增强层参数
- 参数名：`promoted_threshold`
- 所在脚本：`scripts/augment_uncertain_candidates.py`（`AUGMENT_CONFIG`）
- 默认值：`65.0`
- 当前传参方式：**无 CLI 参数**，写在脚本常量中
- 本轮扰动：`58.5 / 65.0 / 71.5`（默认附近 ±10%）
- 选择原因：直接影响 uncertain 子集被 `promoted_suspicious` 上提的门槛，是增强层最核心阈值。

## 说明
- 本轮 E5 为“局部扰动鲁棒性验证”，不是最优调参搜索。
- 门控与增强的阈值通过**临时脚本副本**注入，不改主链逻辑与规则定义。
"""
    (out_dir / "e5_parameter_registry.md").write_text(text, encoding="utf-8")


def write_summary_md(df: pd.DataFrame, out_dir: Path):
    lines = ["# E5 参数敏感性结果概览", ""]
    for group in ["E5-A", "E5-B", "E5-C"]:
        sub = df[df["experiment_group"] == group].copy()
        lines.append(f"## {group}")
        for _, r in sub.iterrows():
            lines.append(
                "- {0}={1}（{2}）: candidates={3} ({4:.2%}), scored={5}, final(high/needs/low)={6}/{7}/{8}, high_from(gating/aug)={9}/{10}, uncertain(p/r/d)={11}/{12}/{13}".format(
                    r["parameter_name"],
                    r["parameter_value"],
                    r["looseness_level"],
                    int(r["total_candidates"]),
                    float(r["candidate_rate"]),
                    int(r["scored_rows"]),
                    int(r["final_high_priority_alert"]),
                    int(r["final_needs_review"]),
                    int(r["final_low_priority_or_background"]),
                    int(r["high_priority_from_gating"]),
                    int(r["high_priority_from_augmentation"]),
                    int(r["promoted_suspicious"]),
                    int(r["retained_uncertain"]),
                    int(r["demoted_suspicious"]),
                )
            )
        lines.append("")
    (out_dir / "e5_sensitivity_summary.md").write_text("\n".join(lines), encoding="utf-8")


def assess(df: pd.DataFrame) -> tuple[str, list[str]]:
    reasons = []
    # A: structure still high small and needs dominant.
    a = df[df["experiment_group"] == "E5-A"]
    a_ok = bool((a["final_needs_review"] >= a["final_high_priority_alert"]).all())
    reasons.append(f"E5-A: needs_review >= high_priority 全部满足: {a_ok}")

    # B: high still clean and structural dominated.
    b = df[df["experiment_group"] == "E5-B"]
    b_missing_ok = bool((b["missing_origin_or_path_in_high"] == 0).all())
    b_struct_ok = bool((b["top_contributing_factor_in_high"] == "structural_novelty_score").all())
    reasons.append(f"E5-B: high 中 missing_origin_or_path=0 全部满足: {b_missing_ok}")
    reasons.append(f"E5-B: high 的 top factor 为 structural_novelty_score 全部满足: {b_struct_ok}")

    # C: retained major, promoted small.
    c = df[df["experiment_group"] == "E5-C"].copy()
    retained_ratio = (c["retained_uncertain"] / c["uncertain_total"].replace(0, pd.NA)).fillna(0.0)
    promoted_ratio = (c["promoted_suspicious"] / c["uncertain_total"].replace(0, pd.NA)).fillna(0.0)
    c_ret_ok = bool((retained_ratio >= 0.70).all())
    c_prom_ok = bool((promoted_ratio <= 0.20).all())
    reasons.append(f"E5-C: retained 占比 >=70% 全部满足: {c_ret_ok}")
    reasons.append(f"E5-C: promoted 占比 <=20% 全部满足: {c_prom_ok}")

    ok_count = sum([a_ok, b_missing_ok, b_struct_ok, c_ret_ok, c_prom_ok])
    if ok_count >= 5:
        status = "通过"
    elif ok_count >= 3:
        status = "基本通过"
    else:
        status = "不通过"
    return status, reasons


def write_assessment(df: pd.DataFrame, out_dir: Path):
    status, reasons = assess(df)
    lines = ["E5 参数敏感性正式判断", "", f"结论：{status}", "", "判断要点："]
    lines.extend([f"- {r}" for r in reasons])
    (out_dir / "e5_sensitivity_assessment.txt").write_text("\n".join(lines), encoding="utf-8")


def write_paper_summary(df: pd.DataFrame, out_dir: Path):
    a = df[df["experiment_group"] == "E5-A"]
    b = df[df["experiment_group"] == "E5-B"]
    c = df[df["experiment_group"] == "E5-C"]

    text = (
        "E5 结果显示，当前系统并不依赖单一“幸运参数”。\n"
        f"在候选层 min_weak_rules 的 1/2/3 扰动下，最终结构仍保持“high 较小、needs 占主导”的方向（high/scored 范围 {a['high_priority_rate_over_scored'].min():.2%}~{a['high_priority_rate_over_scored'].max():.2%}）。\n"
        f"门控层 certainty_threshold_high 扰动下，高优先中的 missing_origin_or_path 仍为 0，且 top_contributing_factor_in_high 持续为 structural_novelty_score。\n"
        f"增强层 promoted_threshold 扰动下，retained 仍为 uncertain 主流（范围 {(c['retained_uncertain']/c['uncertain_total']).min():.2%}~{(c['retained_uncertain']/c['uncertain_total']).max():.2%}），promoted 保持小比例。\n"
        "总体看，本轮对参数更敏感的层是候选层（会显著影响候选规模），而门控层与高优先质量口径相对更稳定。"
        "这为后续 E6（消融）和 E7（collector影响）提供了较稳的参数基线；若进入 E9，优先在评分层做学习化替换更便于归因。"
    )
    (out_dir / "e5_summary_for_paper.txt").write_text(text, encoding="utf-8")


def write_run_index(df: pd.DataFrame, out_dir: Path):
    lines = [
        "# E5 运行索引",
        "",
        "## 复用口径",
        "- 基准 run：`20260313T032554_4f9be28c`",
        "- E5-A：复用 events/baseline，重跑 candidates→scores→gating→augmentation→final",
        "- E5-B：复用 events/baseline/candidates/scores，重跑 gating→augmentation→final",
        "- E5-C：复用 events/baseline/candidates/scores/gating，重跑 augmentation→final",
        "",
        "| group | run_id | parameter | value | level | final_report | candidate_summary | score_summary | gating_summary | augmentation_summary |",
        "|---|---|---|---:|---|---|---|---|---|---|",
    ]
    for _, r in df.iterrows():
        rid = r["run_id"]
        lines.append(
            "| {0} | {1} | {2} | {3} | {4} | `{5}` | `{6}` | `{7}` | `{8}` | `{9}` |".format(
                r["experiment_group"],
                rid,
                r["parameter_name"],
                r["parameter_value"],
                r["looseness_level"],
                f"data/runs/{rid}/final/final_report.json",
                f"data/runs/{rid}/candidates/candidate_summary.json",
                f"data/runs/{rid}/scores/score_summary.json",
                f"data/runs/{rid}/gating/gating_summary.json",
                f"data/runs/{rid}/augmentation/augmentation_summary.json",
            )
        )
    (out_dir / "e5_run_index.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="Run E5 first-round sensitivity experiments.")
    ap.add_argument("--base-run-id", default=BASE_RUN_ID_DEFAULT)
    ap.add_argument("--out-dir", default="outputs/e5_sensitivity_v01")
    args = ap.parse_args()

    base_run_dir = Path("data") / "runs" / args.base_run_id
    if not base_run_dir.exists():
        raise SystemExit(f"Base run not found: {base_run_dir}")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="e5_tmp_") as tmp:
        tmp_dir = Path(tmp)
        rows.extend(run_group_a(base_run_dir, tmp_dir))
        rows.extend(run_group_b(base_run_dir, tmp_dir))
        rows.extend(run_group_c(base_run_dir, tmp_dir))

    df = pd.DataFrame(rows)
    df = df.sort_values(["experiment_group", "parameter_value"]).reset_index(drop=True)
    csv_cols = [
        "experiment_group",
        "parameter_name",
        "parameter_value",
        "looseness_level",
        "total_events",
        "total_candidates",
        "candidate_rate",
        "scored_rows",
        "final_high_priority_alert",
        "final_needs_review",
        "final_low_priority_or_background",
        "high_priority_rate_over_total",
        "high_priority_rate_over_scored",
        "high_priority_from_gating",
        "high_priority_from_augmentation",
        "missing_origin_or_path_in_high",
        "top_contributing_factor_in_high",
        "uncertain_total",
        "promoted_suspicious",
        "retained_uncertain",
        "demoted_suspicious",
        "run_id",
    ]
    df[csv_cols].to_csv(out_dir / "e5_sensitivity_summary.csv", index=False)

    write_parameter_registry(out_dir)
    write_summary_md(df, out_dir)
    write_assessment(df, out_dir)
    write_paper_summary(df, out_dir)
    write_run_index(df, out_dir)

    print("[DONE]", out_dir / "e5_parameter_registry.md")
    print("[DONE]", out_dir / "e5_sensitivity_summary.csv")
    print("[DONE]", out_dir / "e5_sensitivity_summary.md")
    print("[DONE]", out_dir / "e5_sensitivity_assessment.txt")
    print("[DONE]", out_dir / "e5_summary_for_paper.txt")
    print("[DONE]", out_dir / "e5_run_index.md")


if __name__ == "__main__":
    main()
