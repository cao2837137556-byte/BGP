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

代码已实现，fixed-run full 待超算执行。

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

### S3-D Verified High-Confidence Set

在 incident 层做 verification，而不是逐行 event verification。

目标：

- 构造 high-confidence suspicious incident set
- 明确哪些 high/P1 是强信号，哪些只是稳定背景
- 用 verified set 反向校准 score/gate/priority

## 5. Non-Goals

- 不直接进入 24h event-level 主评估。
- 不把 217k tickets 当作最终人工审查队列。
- 不先塞深度学习模型；先用 S3-A/S3-B 暴露的结构问题指导白盒增强。
- 不把低可见度直接当噪声，也不把低可见度直接抬 high。

## 6. Operating Rule

后续所有扩窗和检测增强都应使用 incident / verification 作为评价口径。

可以保持 candidate 宽口径召回，但 score/gate/priority 必须逐步增强语义区分能力，使系统从“能筛很多弱信号”转为“能把值得看的弱信号排到前面”。
