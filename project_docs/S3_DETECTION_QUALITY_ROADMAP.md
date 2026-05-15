# S3 Detection Quality Roadmap

最后更新：2026-05-06

## 1. Current Judgment

S3-A 已证明 event-level 到 incident-level 的框架可行，但也暴露出新的主矛盾：

```text
S3-A 证明了 event -> incident 框架可行；
但 clean stable window 下 high/needs 仍过大；
当前主矛盾已经从 pipeline scalability 转为 detection quality。
```

这意味着后续不能只继续扩窗或继续聚合。incident layer 是评估与审查口径，真正需要提升的是 candidate -> score -> gate -> verification 的语义区分能力。

## 2. Correct System Frame

更准确的系统闭环应是：

```text
BGP raw data
  -> preprocessing / event units
  -> broad suspicious candidate pool
  -> stronger semantic detection / scoring / gating
  -> incident aggregation / correlation
  -> verification / ranking
  -> top-K human review
```

当前 547.9 万 high/needs rows 不应被称为最终异常，更准确是 suspicious event rows。S3-A 将其压缩为 21.7 万 incident tickets，但这仍不是最终人工审查队列。

## 3. Current Coverage

| Layer | Status | Judgment |
| --- | --- | --- |
| preprocessing / event units | done | modern 6h expanded 已稳定跑通 |
| broad candidate generation | done | candidate 召回宽，但偏宽 |
| score / gate / augment | baseline done | 白盒可解释，但语义检测仍粗 |
| incident aggregation | S3-A done | compression 有效，但 P1/P2 仍大 |
| priority calibration | S3-A2 done | 已隔离 NA-origin 超大背景工单，但 P1/P2 仍大 |
| verification | pending | 需要在 incident 层建立高置信样本 |
| noise source audit | S3-B done | 已定位低可见度/短时 path novelty 为 P1/P2 主体来源 |
| semantic detection upgrade | pending | 需要 visibility-aware path plausibility、path/triplet/verification 特征增强 |

## 4. Next Sequence

### S3-A2 Priority Calibration

已完成。只读现有 S3-A outputs / incidents，未重跑上游检测链。

重点处理：

- `dominant_origin_as=NA`
- 超大 `affected_prefix_count`
- low confidence but high incident_score
- P1/P2 队列规模过大

结果：

- 3 个 `dominant_origin_as=NA` 超大 P2 全部降为 P3，覆盖 `348708` needs、`0` high。
- P1->P2 `162` tickets，P2->P3 `3` tickets。
- calibrated P1 `41885` tickets，calibrated P2 `13198` tickets。

结论：明显坏工单已隔离，但 calibrated P1/P2 仍大，下一步必须进入 S3-B noise source audit。

### S3-B Noise Source Audit

已完成。回答：

```text
547.9 万 high/needs rows 和 21.7 万 tickets 到底由哪些 reason / origin / prefix / path 模式撑起来？
```

重点输出：

核心结果：

- calibrated P1/P2 `55083` tickets / `4426436` rows。
- P1/P2 中 needs `3793796` rows，high `632640` rows。
- 最大结构为 `single_collector_visibility + structural_novelty_score + unseen_path_for_prefix_origin + unusually_short_duration_for_prefix`，覆盖 `27120` tickets / `3943362` rows，weighted high share 约 `0.095`。
- needs_review 主要来源为 with-high weak support、single-collector/sparse/short-lived、large fan-out background-like。
- large fan-out 是重要噪声源，但不是唯一噪声源。
- route-leak-like 与 forged-origin-like 表现不同，应继续分队列。

结论：下一步应进入 S3-C detection capability upgrade design，而不是直接扩 24h。

### S3-C Detection Capability Upgrade Design

基于 S3-B 暴露的噪声结构，设计检测能力增强，而不是盲目加入模型。优先方向从泛泛的 role/path/triplet 扩展，收敛为：

- visibility-aware path plausibility scoring pilot
- gate evidence support ablation
- route-leak triplet legality pilot

#### S3-C1 visibility-aware path plausibility

已完成 fixed-run full。

新增：

- `scripts/run_s3c1_visibility_path_plausibility_pilot.py`
- `scripts/hpc/s3c1_visibility_path_plausibility.slurm`
- `project_docs/S3C1_VISIBILITY_PATH_PLAUSIBILITY.md`

当前状态：

- 脚本只输出离线 `adjusted_risk_score_s3c1 / adjusted_risk_bucket_s3c1`，不覆盖 score/gate/final/incidents。
- pattern_A 默认降权对象为 `single_collector_visibility + structural_novelty_score + unseen_path_for_prefix_origin + unusually_short_duration_for_prefix`。
- pattern_B `abnormal_path_length_for_prefix_origin + single_collector_visibility + structural_novelty_score + unseen_path_for_prefix_origin` 默认只做诊断，不直接强降。
- 本地已用 `s1a_expanded_v02_pilot_60m_april16` 20 万行 smoke 验证脚本路径，`pattern_B_adjusted_down_rows=0`。
- S2 fixed-run full 结果：
  - input / loaded / joined rows：`10236431 / 10236431 / 10236431`
  - pattern_A rows：`7440623`，adjusted down `6885990`
  - pattern_B rows：`659862`，adjusted down `0`
  - risk bucket changed：`4576319`
  - score-high：`2047659 -> 1187117`
  - P1/P2 adjusted-down rows：`3510753`
  - touched P1/P2 incidents：`32469`

判断：S3-C1 成功识别 S3-B dominant pattern，且保护 pattern_B；但 default penalty 导致 bucket migration 过强，不能直接进入主链。

下一步：先做 S3-C1b 权重/penalty 校准，并补 known-event inventory regression；S3-C2 可以继续设计，但应把 S3-C1 plausibility 当作 gate evidence，而不是直接采用当前 default score penalty。

#### S3-C1b penalty calibration

代码已实现，fixed-run full 已完成。

新增：

- `scripts/run_s3c1b_penalty_calibration.py`
- `scripts/hpc/s3c1b_penalty_calibration.slurm`
- `project_docs/S3C1B_PENALTY_CALIBRATION.md`

比较策略：

- default S3-C1 upper bound
- low-only score penalty
- low/medium soft score penalty
- gate-only
- medium-gate-only

本地 60min smoke 显示 `strategy_medium_gate_only` 最稳：只对 low plausibility 小幅动 score，medium plausibility 作为 gate evidence，pattern_B 保持不动。

Fixed S2 full update:
- input/loaded rows `10236431 / 10236431`
- recommended_strategy `strategy_medium_gate_only`
- default bucket_changed_rows `4576319` and score-high `2047659 -> 1187117`
- recommended bucket_changed_rows `5183` and score-high `2047659 -> 2042688`
- recommended pattern_A_adjusted_down_rows `15294`
- recommended pattern_A_gate_evidence_rows `6870696`
- recommended P1/P2 adjusted_down_rows `31`
- recommended P1/P2 gate_evidence_rows `3510722`
- pattern_B adjusted/bucket changed rows `0`

Conclusion: S3-C1b fixed full confirms the gate-evidence direction. Do not adopt S3-C1 default penalty into the mainline.

#### S3-C2 gate evidence ablation scaffold

代码已实现，已完成本地 smoke 与 fixed S2 full。
新增：
- `scripts/run_s3c2_gate_evidence_ablation.py`
- `project_docs/S3C2_GATE_EVIDENCE_ABLATION.md`
- `scripts/hpc/s3c2_gate_evidence_ablation.slurm`

当前定位：
- S3-C2 不是 score replacement。
- S3-C2 把 `path_plausibility_score / plausibility_bucket / pattern_A_flag / pattern_B_flag` 转成 gate-layer evidence。
- S3-C2 fixed S2 结果只作为 gate evidence / verification input，不解释为 P1/P2 workload reduction。

本地 `s1a_expanded_v02_pilot_60m_april16` 20 万行 smoke：
- loaded_rows `200000`
- recommended_variant `variant_medium_gate_only`
- gate_evidence_rows `122956`
- final_label_changed_rows `0`
- pattern_A_gate_evidence_rows `122956`
- pattern_B_label_changed_rows `0`
- known-event inventory 可读但 matched rows `0`

Fixed S2 full：
- input/loaded rows `10236431 / 10236431`
- recommended_variant `variant_medium_gate_only`
- final labels 不变：high `639548 -> 639548`，needs `4839755 -> 4839755`，low `4757128 -> 4757128`
- final_label_changed_rows `0`
- gate_evidence_rows `6885990`
- pattern_A_gate_evidence_rows `6885990`
- pattern_A_control_rate `0.9254587955874125`
- pattern_B label changed rows `0`
- P1/P2 tickets `55083 -> 55083`
- P1/P2 members `4426436 -> 4426436`
- P1->P2 transfer tickets `0`
- P1/P2 affected rows `3510753`
- touched P1/P2 incidents `32469`
- known-event inventory 可读但 matched rows `0`

判断：S3-C2 fixed S2 证明 plausibility 可以作为 gate evidence 通道，而不是继续直接打 score。它不会造成 high->needs 转移，也不会膨胀 needs_review 或把 P1 转成 P2；但它也不降低 P1/P2 总负担。下一步应把 gate evidence 用于 incident-level verification queue/schema。

候选方向：

| Upgrade | Likely Layer |
| --- | --- |
| role churn | score / gate |
| AS Hegemony delta | score / incident explanation |
| forged-origin path plausibility | score |
| route-leak triplet legality | incident / verification |
| RPKI / IRR / PeeringDB | verification |
| NO_EXPORT / communities | augment / verification |
| learning-based scoring | later, after verified set |

### S3-D Incident-Level Verification Queue

已完成 v01 queue/schema。S3-D 在 incident 层做 verification queue 准备，而不是逐行 event verification，也不是 external verification 完成。

新增：

- `scripts/run_s3d_verification_queue_schema.py`
- `project_docs/S3D_VERIFICATION_QUEUE_SCHEMA.md`
- `project_docs/REALTIME_UPGRADE_ROADMAP.md`

固定 run：

```text
s2a_expanded_v01_pilot_6h_april16
```

结果：
- total incidents `217165`
- calibrated P1/P2/P3 `41885 / 13198 / 162082`
- `high_confidence_candidate=1216`
- `gate_evidence_weak_case=7192`
- `patternB_path_abnormal_verification=49852`
- `background_like_review=1190`
- `route_leak_like_review=364`
- `low_priority_background=157351`
- P1/P2 in `gate_evidence_weak_case`：`7192`
- P1/P2 in `high_confidence_candidate`：`1216`
- pattern_A touched incidents：`174046`
- pattern_B verification incidents：`49852`

证据口径：
- 本地缺完整 S2 scored/gated/final/events/candidates parquet。
- S3-D 使用 `incident_membership.reason_signature` 计算 incident-member pattern evidence。
- `weak_label_candidate` 仅为未来学习层候选字段，不是真实标签。

当前目标：

- 构造 high-confidence suspicious incident set
- 明确哪些 high/P1 是强信号，哪些只是稳定背景
- 用 verified set 反向校准 score/gate/priority

下一步：
- S3-D2 external evidence attachment
- S3-C3 route-leak triplet legality
- S4 learning-ready high-confidence set after verification

### S3-D2 External Evidence Attachment

已完成 v01 evidence attachment。S3-D2 给 S3-D verification queue 挂载第一批证据字段，但不完成真假判定。

新增：

- `scripts/run_s3d2_external_evidence_attachment.py`
- `project_docs/S3D2_EXTERNAL_EVIDENCE_ATTACHMENT.md`

固定 run：

```text
s2a_expanded_v01_pilot_6h_april16
```

结果：
- total incidents `217165`
- evidence buckets：weak `201329`，medium `15836`，strong `0`
- RPKI status：`unavailable=217165`
- path relation evidence：`weak_stale_snapshot=217165`
- time-aligned known-event matches：`0`
- out-of-window known-event overlaps：`5167`
- high_confidence_candidate with strong evidence：`0`
- gate_weak_case with strong evidence：`0`
- gate_weak_case evidence insufficient：`7182`
- patternB with path evidence entry：`49852`
- route_leak relation pending：`364`
- background_like evidence supported：`1189`

证据口径：
- 未提供 `2024-04-16` historical RPKI cache，因此 RPKI 不进入强证据。
- `20170701.as-rel2.txt` 对 2024 run 是 stale snapshot，只能作为 diagnostic path relation evidence。
- known-event inventory 与当前 2024 fixed run 没有 time-aligned match；out-of-window overlap 不能解释为命中。

当前判断：
- S3-D2 成功打通 evidence attachment schema。
- 当前主要结论是外部证据缺口明确，不是 external verification 完成。
- 下一步应补 2024-aligned RPKI/IRR/AS relationship cache 后复跑，或做 S3-C3 route-leak triplet legality。

### S3-D2B Evidence Alignment

Completed v01 evidence alignment layer.

Added:
- `scripts/run_s3d2b_evidence_alignment.py`
- `project_docs/S3D2B_EVIDENCE_ALIGNMENT.md`
- `outputs/s3d2b_evidence_alignment_v01/`

Fixed run:
```text
s2a_expanded_v01_pilot_6h_april16
```

Result:
- inspected incidents `217165`
- valid prefix-origin lookup targets `40665`
- path relation targets `168889`
- local evidence sources `5`
- `as_relationship:stale=1`
- `known_event_inventory:undated=4`
- RPKI aligned cache available `false`
- AS relationship aligned snapshot available `false`
- known-event time-aligned overlaps `0`
- known-event out-of-window asset overlaps `6`
- S3-D2 aligned rerun ready `false`

Interpretation:
- S3-D2B does not validate incidents.
- It converts the evidence gap into cache requirements, lookup targets, and an S3-D2 rerun manifest.
- The next useful external-evidence step requires a `2024-04-16` historical RPKI/ROA cache and a 2024-near AS relationship snapshot.
- If those caches are not available, proceed to S3-C3 route-leak triplet legality rather than claiming stronger external evidence.

## 5. Non-Goals

- 不直接进入 24h event-level 主评估。
- 不把 217k tickets 当作最终人工审查队列。
- 不先塞深度学习模型；先用 S3-A/S3-B 暴露的结构问题指导白盒增强。
- 不把低可见度直接当噪声，也不把低可见度直接抬 high。

## 6. Operating Rule

后续所有扩窗和检测增强都应使用 incident / verification 作为评价口径。

可以保持 candidate 宽口径召回，但 score/gate/priority 必须逐步增强语义区分能力，使系统从“能筛很多弱信号”转为“能把值得看的弱信号排到前面”。
