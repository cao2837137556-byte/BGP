# S3-A Incident Aggregation Plan

最后更新：2026-05-06

定位：S3-A 是 `final_alerts.parquet` 之后的 post-processing incident layer，不改变上游检测主链。

## 1. 背景判断

S2-B2 / S2-C 已证明 2024 modern expanded 6h 主链可以稳定跑到 final：

- `total_events=15667871`
- `candidate=scored=gated=10236431`
- `final_high=639548`
- `final_needs=4839755`
- `final_low=4757128`
- `high_missing_rate=0.0`
- S2-C 中 `noisy_high=13`，且不来自 augment promotion

因此当前主要问题不是检测链未跑通，而是 event-level 输出没有工单化。`needs_review` 仍以数百万行直接暴露，评估单位会失真。

## 2. 设计原则

- 不改 raw/events/baseline/candidate/score/gate/augment/final。
- 只消费现有产物：`final/events/scores/gating/augmentation`，首版必须只依赖 `final + events` 即可运行。
- 首版聚合保守，避免 forged-origin 与 route-leak family 混合。
- LLM 只能用于文字润色，不能替代事实抽取。
- RPKI / IRR / PeeringDB / communities 后续进入 verification layer，不作为首版硬真值。

## 3. 输入输出

输入：

- `data/runs/<run_id>/final/final_alerts.parquet`
- `data/runs/<run_id>/events/event_units.parquet`

首版输出：

- `data/runs/<run_id>/incidents/incident_membership.parquet`
- `data/runs/<run_id>/incidents/incident_tickets.parquet`
- `data/runs/<run_id>/incidents/incident_summary.json`
- `outputs/s3a_incident_aggregation_v01/s3a_report.md`
- `outputs/s3a_incident_aggregation_v01/s3a_top_incidents.csv`
- `outputs/bundles/s3a_incident_aggregation_bundle.zip`

## 4. Family Classification

首版 incident family：

- `route_leak_like`：`candidate_reasons` 含 `cross_collector_prefix_origin_burst`
- `forged_origin_like`：`candidate_reasons` 含 `unseen_origin_for_prefix`、`unseen_exact_path`、`unseen_path_for_prefix_origin`、`weak_path_history`、`abnormal_path_length_for_prefix_origin`
- `stealth_visibility_like`：`candidate_reasons` 含低可见度相关规则，或 `collector_count/visibility_count <= 1`
- `unknown_weak_signal`：其余

优先级：route-leak 覆盖 forged-origin，forged-origin 覆盖 stealth，stealth 覆盖 unknown。

## 5. Aggregation

首版采用两级聚合。

Micro incident：

- 按 `family + prefix + origin_as + path_signature` 排序
- 同 key 下若相邻 event 间隔 `<= micro_window_sec`，默认 `900s`，归入同一 micro incident

Macro incident：

- 将 micro incident 再按 family-aware key 与 `macro_window_sec`，默认 `7200s`，聚成 analyst ticket
- `route_leak_like` 使用 `origin_as + triplet_signature + time_bucket`
- `forged_origin_like` 使用 `origin_as + path_signature + time_bucket`
- `stealth_visibility_like` 使用 `origin_as + reason_signature + time_bucket`
- `unknown_weak_signal` 使用 `prefix + origin_as + time_bucket`

这是保守版，不做跨 family 激进合并。

## 6. Ticket Fields

`incident_tickets.parquet` 至少包含：

- `incident_id`
- `family`
- `incident_priority`
- `member_count`
- `micro_incident_count`
- `affected_prefix_count`
- `origin_as_count`
- `collector_union_count`
- `incident_start`
- `incident_end`
- `incident_score`
- `incident_confidence`
- `high_count`
- `needs_count`
- `dominant_prefix`
- `dominant_origin_as`
- `dominant_path_signature`
- `dominant_triplet_signature`
- `dominant_reason_signature`
- `label_distribution`
- `source_layer_distribution`
- `reason_distribution`
- `explanation`

## 7. Metrics

首版 summary 必须输出：

- `raw_alert_count`
- `raw_high_count`
- `raw_needs_count`
- `micro_incident_count`
- `incident_count`
- `compression_ratio = raw_alert_count / incident_count`
- `analyst_workload_reduction = 1 - incident_count / raw_alert_count`
- `incident_count_by_family`
- `incident_count_by_priority`
- `top_incidents_sample`

首轮验收重点不是 incident_count 绝对值是否好看，而是：

1. `compression_ratio` 是否足够高；
2. top incidents 的 family/reason purity 是否合理；
3. `route_leak_like` 与 `forged_origin_like` 是否形成不同审查队列。

## 8. Current Implementation

已准备代码：

- `scripts/build_incident_aggregation.py`
- `scripts/run_s3a_incident_aggregation.py`
- `scripts/hpc/s3a_incident_aggregation.slurm`

默认 run：

- `s2a_expanded_v01_pilot_6h_april16`

默认输出：

- `outputs/s3a_incident_aggregation_v01/`
- `data/runs/s2a_expanded_v01_pilot_6h_april16/incidents/`

## 9. Run Result

S3-A 已在超算完成并拉回本地。

产物：

- `outputs/s3a_incident_aggregation_v01/`
- `data/runs/s2a_expanded_v01_pilot_6h_april16/incidents/`
- `outputs/bundles/s3a_incident_aggregation_bundle.zip`

核心指标：

- `raw_alert_count=5479303`
- `raw_high_count=639548`
- `raw_needs_count=4839755`
- `micro_incident_count=1839957`
- `incident_count=217165`
- `compression_ratio=25.231059`
- `analyst_workload_reduction=0.960366`
- `incident_count_by_family={forged_origin_like:216801, route_leak_like:364}`
- `incident_count_by_priority={P1_high:42047, P2_review:13039, P3_background:162079}`

有效结论：

- incident layer 成功把 547.9 万 high/needs event 压缩为 21.7 万 tickets，证明 event-level 到 incident-level 的评估单位转换有效。
- `route_leak_like` 与 `forged_origin_like` 已经形成不同队列，route-leak-like 规模小且多数停留在 review/background。
- top P1 incidents 主要由 `structural_novelty_score + unseen_path_for_prefix_origin` 相关 reason signature 驱动，整体符合弱信号 forged-origin-like 主线。

风险与不足：

- 3 个 `dominant_origin_as=NA` 的超大 P2 incident 覆盖 `348708` 条 needs、`149178` 个 affected prefix，`incident_score=100` 但 confidence 约 `0.51`，更像 unknown-origin / background artifact。
- P1 tickets 仍有 `42047` 个，虽然比 event-level 大幅压缩，但直接进入人工验证仍偏大。
- 首版 macro key 对 forged-origin-like 使用 `origin_as + path_signature + 2h bucket`，对 NA-origin 或超广 prefix fan-out 需要额外保护。

## 10. Next Step

执行 S3-A2 priority calibration / NA-origin handling：

- 不重跑 raw/events/baseline/candidate/score/gate/augment/final。
- 只读 S3-A `incident_tickets.parquet` / `incident_membership.parquet`，或轻量重跑 incident aggregation 后处理。
- 将 `dominant_origin_as=NA` 且超大 affected-prefix 的背景工单拆出或降级。
- 校准 P1/P2 priority 规则，使 S3-B top-K verification 面向更干净的 incident pool。
