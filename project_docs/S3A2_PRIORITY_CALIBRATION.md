# S3-A2 Incident Priority Calibration

最后更新：2026-05-06

## 1. Scope

S3-A2 是 S3-A incident layer 之后的 priority calibration，不是新的检测器。

固定 run：

- `s2a_expanded_v01_pilot_6h_april16`

输入：

- `data/runs/s2a_expanded_v01_pilot_6h_april16/incidents/incident_tickets.parquet`
- `data/runs/s2a_expanded_v01_pilot_6h_april16/incidents/incident_membership.parquet`

约束：

- 不重跑 raw/events/baseline/candidate/score/gate/augment/final。
- 不覆盖 S3-A 原始 `incident_priority`。
- 只新增 calibrated 字段，保留 before/after 对比。

## 2. Implementation

新增脚本：

- `scripts/run_s3a2_incident_priority_calibration.py`

默认输出：

- `outputs/s3a2_incident_priority_calibration_v01/s3a2_priority_summary.json`
- `outputs/s3a2_incident_priority_calibration_v01/s3a2_priority_before_after.csv`
- `outputs/s3a2_incident_priority_calibration_v01/s3a2_na_origin_audit.csv`
- `outputs/s3a2_incident_priority_calibration_v01/s3a2_p1_p2_reason_patterns.csv`
- `outputs/s3a2_incident_priority_calibration_v01/s3a2_top_calibrated_incidents.csv`
- `outputs/s3a2_incident_priority_calibration_v01/s3a2_report.md`
- `outputs/s3a2_incident_priority_calibration_v01/s3a2_calibrated_incident_tickets.parquet`

新增字段：

- `original_priority`
- `calibrated_priority`
- `calibrated_subtype`
- `calibration_action`
- `calibration_flags`
- `calibration_reason`

## 3. Calibration Rules

主 priority 仍保持三档：

- `P1_high`
- `P2_review`
- `P3_background`

低置信 review 不新增第四个主 priority，而是通过 `calibrated_subtype` / `calibration_flags` 表达。

默认阈值来自 S3-A tickets 分位数与保护下限：

- affected_prefix p99：`87`
- affected_prefix p99.9：`422`
- `large_fanout_threshold=100`
- `extreme_fanout_threshold=1000`
- `large_member_threshold=1000`
- `large_needs_threshold=1000`
- `low_confidence_threshold=0.55`
- `weak_high_share_threshold=0.05`

主要降级规则：

- `dominant_origin_as=NA` 且 extreme fan-out 且 `high_count=0`：降为 `P3_background`
- P1 且 low confidence + extreme fan-out：降为 `P2_review`
- P1 且 tiny high support + large fan-out：降为 `P2_review`
- P1 且 mostly needs_review + broad fan-out reason：降为 `P2_review`
- P2 且 low-confidence / NA-origin extreme fan-out background：降为 `P3_background`

## 4. Run Result

S3-A2 已基于本地拉回的 S3-A 结果完成运行。

输入一致性：

- tickets：`217165`
- membership rows：`5479303`
- membership incident count：`217165`
- ticket member_count sum：`5479303`
- member count mismatch：`0`

Before / after：

| priority | original tickets | calibrated tickets | ticket delta | original members | calibrated members | member delta |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| P1_high | 42047 | 41885 | -162 | 2775776 | 2565156 | -210620 |
| P2_review | 13039 | 13198 | +159 | 1999368 | 1861280 | -138088 |
| P3_background | 162079 | 162082 | +3 | 704159 | 1052867 | +348708 |

Downgrades：

- downgraded tickets：`165`
- downgraded members：`559328`
- P1 -> P2：`162` tickets
- P2 -> P3：`3` tickets
- NA-origin downgrades：`3` tickets / `348708` members

NA-origin audit：

- NA-origin tickets：`3`
- high rows：`0`
- needs rows：`348708`
- affected_prefix mean：`49726`
- affected_prefix max：`54109`
- incident_score：全部 `100`
- confidence：`0.5065~0.5229`
- dominant reason：`single_collector_visibility+sparse_short_lived_event+structural_novelty_score+unseen_exact_path`

## 5. Interpretation

S3-A2 达成了两个目标：

1. 明确隔离了 S3-A 暴露的 3 个 `dominant_origin_as=NA` 超大 P2 背景工单。
2. 将 162 个 high 支撑很弱的大 fan-out P1 降到 review，减少 calibrated P1 的成员覆盖量。

但 S3-A2 是保守校准，不直接解决检测质量问题：

- calibrated P1 仍有 `41885` tickets；
- calibrated P2 仍有 `13198` tickets；
- P1/P2 仍主要由 `single_collector_visibility + structural_novelty_score + unseen_path_for_prefix_origin` 等 reason pattern 支撑。

因此下一步不应直接进入 24h，也不应把 calibrated P1/P2 当最终人工队列；应进入 S3-B noise source audit。

## 6. Next Step

进入 S3-B：

- 审计 P1/P2 reason signature 分布。
- 审计 needs_review 的主要来源。
- 审计 large fan-out incidents。
- 区分 forged-origin-like 与 route-leak-like 队列。
- 输出哪些模式应进入 score/gate/verification 的检测能力升级。
