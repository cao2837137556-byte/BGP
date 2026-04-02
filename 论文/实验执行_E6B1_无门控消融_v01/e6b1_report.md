# E6-B-1 无门控消融结论

## 1) 简短结论
- 在同一数据口径下，移除 gate 后 high 从 24 增加到 266（+242）。
- 新增进入 high 的样本数为 242，主要来源于 default 的 needs/low。
- no-gate 高优先样本的 certainty 均值下降、conflict 均值上升，显示质量下滑。
- 新增 high 中存在明显的结构证据不足或冲突偏高样本，说明 gate 在抑制低质量上浮方面有独立贡献。
- augmentation 保持不变时，最终差异主要由 gate 是否参与 high 入口控制造成。

## 2) default vs no-gate 对比表
```text
setting  total_events  candidate_count  scored_count  final_high_count  final_needs_count  final_low_count
default          4808             1106          1106                24                625              457
no_gate          4808             1106          1106               266                402              438
```

## 3) gate 独立贡献判断
- 新增 high（no-gate 相对 default）: 242
- 新增 high 来源分布: {'needs_review': 241, 'low_priority_or_background': 1}
- 质量对比见 `e6b1_high_quality_compare.csv`：可直接对比 risk/certainty/conflict/missing/structural_dominance。
- 归因：gate 的核心作用是把仅凭 risk_bucket=high 但 certainty 不足或 conflict 偏高的样本拦截在 high 之外。

## 4) 最终标签
- gate=独立有效

## 产物
- e6b1_default_vs_nogate_flow.csv
- e6b1_high_quality_compare.csv
- e6b1_new_high_sources.csv
- e6b1_new_high_feature_summary.json
- e6b1_new_high_samples.csv
- e6b1_no_gate_final_alerts.parquet