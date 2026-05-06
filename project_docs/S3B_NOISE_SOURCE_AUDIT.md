# S3-B Noise Source Audit

最后更新：2026-05-06

## 1. Scope

S3-B 是 S3-A / S3-A2 之后的 noise source audit。

固定 run：

- `s2a_expanded_v01_pilot_6h_april16`

边界：

- 不重跑 raw/events/baseline/candidate/score/gate/augment/final。
- 不修改检测主链。
- 不新增检测规则。
- 不声称 P1/P2 是真实异常。
- 不做 precision/recall。

默认输入：

- `data/runs/s2a_expanded_v01_pilot_6h_april16/incidents/incident_membership.parquet`
- `outputs/s3a2_incident_priority_calibration_v01/s3a2_calibrated_incident_tickets.parquet`

本地 `final_alerts.parquet` 未拉回，S3-B 使用 membership 中已有的 `reason_signature/top_contributing_factor/risk_bucket` 完成 needs 来源审计。脚本支持后续补齐 final 后自动 join `candidate_reasons/as_path_clean`。

## 2. Implementation

新增脚本：

- `scripts/run_s3b_noise_source_audit.py`

输出目录：

- `outputs/s3b_noise_source_audit_v01/`

输出文件：

- `s3b_noise_summary.json`
- `s3b_priority_reason_patterns.csv`
- `s3b_needs_review_source_patterns.csv`
- `s3b_large_fanout_incidents.csv`
- `s3b_origin_prefix_path_hotspots.csv`
- `s3b_p1_p2_quality_by_pattern.csv`
- `s3b_detection_upgrade_candidates.csv`
- `s3b_report.md`

## 3. Core Results

输入规模：

- tickets：`217165`
- member rows：`5479303`
- needs_review rows：`4839755`

calibrated P1/P2：

- P1/P2 tickets：`55083`
- P1/P2 member rows：`4426436`
- P1/P2 high rows：`632640`
- P1/P2 needs rows：`3793796`

large fan-out：

- large fan-out tickets：`1832`
- large fan-out P1/P2 tickets：`1829`
- large fan-out P1/P2 member rows：`1102322`

needs_review category：

| category | rows |
| --- | ---: |
| weak_support_needs_with_high_same_incident | 2826078 |
| single_collector_sparse_short_lived_needs | 1242749 |
| large_fanout_background_like_needs | 764874 |
| route_leak_like_review | 3952 |
| forged_origin_like_review | 2102 |

large fan-out by priority/family：

| priority | family | tickets | members | high | needs |
| --- | --- | ---: | ---: | ---: | ---: |
| P1_high | forged_origin_like | 373 | 391600 | 60366 | 331234 |
| P2_review | forged_origin_like | 1451 | 708452 | 22430 | 686022 |
| P2_review | route_leak_like | 5 | 2270 | 0 | 2270 |
| P3_background | forged_origin_like | 3 | 348708 | 0 | 348708 |

## 4. Main Diagnosis

S3-A2 后 P1/P2 仍大的主因不是 route-leak-like，也不是单纯 NA-origin。最大结构是：

```text
single_collector_visibility
  + structural_novelty_score
  + unseen_path_for_prefix_origin
  + unusually_short_duration_for_prefix
```

该 pattern 在 calibrated P1/P2 中覆盖：

- tickets：`27120`
- member rows：`3943362`
- weighted high share：`0.0953`
- weighted needs share：`0.9047`
- large fan-out tickets：`1586`

第二大 pattern 是：

```text
abnormal_path_length_for_prefix_origin
  + single_collector_visibility
  + structural_novelty_score
  + unseen_path_for_prefix_origin
```

覆盖：

- tickets：`24311`
- member rows：`343856`
- weighted high share：`0.6812`
- weighted needs share：`0.3188`

因此当前最大问题不是“聚合不够”，而是低可见度/短时路径新颖性在 clean stable window 中过度支撑 P1/P2。

## 5. Answers

1. S3-A2 后 P1/P2 仍大的主要原因：低可见度结构新颖性 + unseen path 在 forged-origin-like 队列中大规模重复。
2. needs_review 主要来源：与 high 同 incident 的 weak-support needs、单 collector/短时稀疏 needs、large fan-out background-like needs。
3. large fan-out 是重要噪声源，但不是唯一噪声源；它解释了超大背景工单和大量 member coverage，但大量 ticket 数来自小/中型低可见度 novelty。
4. `single_collector_visibility`、`sparse/short-lived`、`structural_novelty_score` 明显过度贡献。
5. route-leak-like 与 forged-origin-like 表现不同：route-leak-like 规模小，应进入 triplet legality / verification；forged-origin-like 是 P1/P2 主体。
6. 低可见度和短时模式不应直接删除，因为它们也是 partial observability 弱信号主线的一部分。
7. 适合 score/gate 增强：visibility-aware path plausibility、path length plausibility、extra evidence requirement。
8. 下一步建议：先做 S3-C detection capability upgrade design，围绕 visibility-aware path plausibility 和 route-leak triplet legality 设计小型校准/消融，再做 verification pilot。

## 6. Upgrade Candidates

Top upgrade candidates：

| pattern | affected tickets | affected members | suggested layer | suggested fix |
| --- | ---: | ---: | --- | --- |
| `single_collector_visibility+structural_novelty_score+unseen_path_for_prefix_origin+unusually_short_duration_for_prefix` | 27120 | 3943362 | score | collector-visibility-aware handling |
| `abnormal_path_length_for_prefix_origin+single_collector_visibility+structural_novelty_score+unseen_path_for_prefix_origin` | 24311 | 343856 | gate | extra evidence requirement |
| `single_collector_visibility+structural_novelty_score+unseen_path_for_prefix_origin+unusually_low_visibility_for_prefix` | 601 | 55563 | gate | extra evidence requirement |
| `structural_novelty_score+unseen_path_for_prefix_origin+unusually_short_duration_for_prefix` | 531 | 27162 | incident_priority | verification-only |
| `cross_collector_prefix_origin_burst+history_rarity_score+single_collector_visibility+unusually_short_duration_for_prefix` | 37 | 2827 | verification | route-leak-specific handling |

## 7. Next Step

进入 S3-C detection capability upgrade design：

- 设计 visibility-aware path plausibility scoring pilot。
- 设计 gate evidence support ablation。
- 设计 route-leak triplet legality pilot。
- 明确哪些增强进入 score，哪些进入 gate，哪些只进入 verification。
