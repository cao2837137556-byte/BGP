# BGP Platform Handoff

最后更新：2026-04-20
定位：项目唯一长期维护的交接总览文件。

## 1. 固定工作边界

- 主仓库：`D:\study\paper\bgp-platform`
- 实验 worktree：`D:\study\paper\worktrees\bgp-platform-exp-mainline`
- 固定分支：`codex/bgp-exp-mainline`
- 当前角色：BGP-EXP，只负责实验代码、实验流程、实验资产整理，不负责论文正文。

## 2. 项目一句话定义

这是一个面向 BGP weak-signal forged-origin / partial observability 场景的分层检测系统，目标不是做单阈值“全抓高危”，而是通过分层证据链把事件稳定分流到 `high_priority_alert`、`needs_review`、`low_priority_or_background` 三层，并保持可解释、可定位、可追责。

## 3. 固定主链

事件层 -> 历史基线层 -> 候选层 -> 评分层 -> 门控层 -> 增强层 -> 最终输出层

固定最终标签：

- `high_priority_alert`
- `needs_review`
- `low_priority_or_background`

## 4. 当前已稳定的主结论

- `candidate` 已证明真实有效，核心作用是前置压缩，不是最终 high 质量控制。
- `gate` 已证明独立有效，是 high 纯度控制的关键层。
- `augment` 有独立作用，但规模偏小，主要处理 uncertain 子集的边界样本。
- collector 可见度下降时，系统主要表现为 high 丢失或降级，而不是误抬升 new high。
- route-leak 风格事件不应强行要求进入 `high_priority_alert`；稳定落在 `needs_review` 也属于正确系统响应。
- 已知事件评估现在采用双轨制：forged-origin / more-specific 主要看 `high`，route-leak 主要看 `needs/high` 的稳定隔离。

## 5. 当前阶段状态

### 5.1 历史阶段

历史阶段已经基本收口到 E9-I：

- E6：主链因果与消融闭环完成。
- E7：partial observability 与 collector 结构差异闭环完成。
- E8：案例池、外部验证、公开已知事件小规模测试完成。
- E9 / S0：已知事件扩容、route-leak 双轨制评估、backup 池首轮复测、Pakistan 扩窗止损审计完成。

当前历史阶段的可直接对外口径是：

- expanded collectors 下，已知事件已经达到 `3 high + 3 needs + 1 no_visibility` 的主库存结构。
- `Indosat` 应按 route-leak 风格样本解释，其 expanded 落在 `needs_review` 属于正确隔离命中。
- `Pakistan / YouTube` 不是绝对不可见，而是原始 replay 时间窗偏窄；扩窗原始审计已看到可见性，但不再围绕它继续大改主链。

### 5.2 现代阶段

现代数据面 S1-A 首轮 pilot 已完成 60 分钟口径收口。

当前已知状态：

- 计划文件：`data/modern_2024/s1a_modern_2024_plan_v01.json`
- 编排脚本：`scripts/run_s1a_modern_2024.py`
- baseline `pilot_60m_april16` 已跑通到 final。
- expanded `pilot_60m_april16` 已跑通到 final。
- 在 2024 现代 12-collector 口径下，旧版 score / gate / final 脚本暴露出明显规模瓶颈；其中 gate 与 final 已完成流式化替换，augment 仍为原逻辑但已验证可在更长执行窗口下完成。
- 已为此新增 streaming 版本：
  - `scripts/build_weak_candidates_streaming.py`
  - `scripts/score_weak_candidates_streaming.py`
  - `scripts/gate_scored_candidates_streaming.py`
  - `scripts/build_final_alerts_streaming.py`
- S1-A 当前正式输出目录：`outputs/s1a_modern_2024_pilot_60m_v02/`
- S1-A 核心数字：
  - baseline 2 collectors：`total_events=614892`，`candidate=276652`，`final_high=20284`，`final_needs=111201`，`final_low=145167`
  - expanded 12 collectors：`total_events=2628659`，`candidate=1610525`，`final_high=138525`，`final_needs=732603`，`final_low=739397`
- S1-B 纯度审计已完成，正式输出目录：`outputs/s1b_modern_high_audit_v01/`
- S1-B 核心数字：
  - expanded final high 总量：`138525`
  - `clean-high=0`
  - `fragile-high=101279`
  - `noisy-high=37246`
  - noisy-high 中 `37233/37246` 来自 `augmentation_promoted`
  - strict expanded-only high keys=`84188`，relaxed expanded-only high keys=`26411`
- S1-C augment 小步收紧已完成，正式输出目录：`outputs/s1c_augment_tightening_v01/`
- S1-C 核心数字：
  - R0：`high=138525`，`high_missing_rate=0.2688`，`noisy-high=37246`
  - A1（只拦 `missing=true` promotion）：`high=101292`，`high_missing_rate=0`，`noisy-high=13`
  - A2（`missing or conflict>0`）：与 A1 完全一致，无新增收益
  - A3（A1 + promotion threshold 70）：`high=88916`，`noisy-high=13`，但额外压缩了更多 augment-high
- S1-D modern 主流程复测已完成，正式输出目录：`outputs/s1d_modern_new_baseline_v01/`
- S1-D 核心数字：
  - modern end-to-end：`high=101292`，`needs=769836`，`low=739397`
  - 与 S1-C A1 严格对齐：`high_missing_rate=0`，`noisy-high=13`
  - `gating_likely_malicious_to_high=85511` 保持不变，`r0_gating_high_retained_ratio=1.0`
  - 2017 minimal spot-check（`e9a_expanded_v01_rostelecom_20170426`）中，有 `31` 条 `augmentation_promoted + missing=true` 从 high 回落到 needs，但 `gate_high_retained_ratio=1.0`
- 当前最需要收紧的不是 gate，而是 modern 口径下 augment 对 `missing=true` uncertain 样本的上推逻辑。
- S1-E augment 性能剖析已完成，正式输出目录：`outputs/s1e_augment_profiling_v01/`
- S1-E 核心数字：
  - profiling 样本：`20000` 条 uncertain，扫描 gating rows `50000`
  - 总耗时：`207.88s`
  - `core_augment_loop=198.04s`，占 `95.27%`
  - `calc_multi_view_support_score=151.08s`，占核心 loop `76.29%`
  - `near_time=124.35s`，占核心 loop `62.79%`
  - I/O 总计仅 `6.78s`，merge `1.58s`，groupby `1.13s`
- 当前性能瓶颈已定位：不是 I/O，不是 final，不是 gate；主要是 augment 逐行 loop 内反复 DataFrame `take` / bool filter / Series 构造。
- S1-F 已完成保守版性能优化：新增 fast augment 引擎，不替换原始脚本；全量对齐 S1-D，业务输出无差异。
- S1-F 核心结果：
  - augment 全量耗时 `6634.60s -> 399.29s`
  - 提速 `16.62x`
  - final 阶段耗时 `42.02s`
  - augment 输出 `878063` 行完全对齐，label / evidence / subscore / flags mismatch 全为 `0`
  - final 输出 `1610525` 行完全对齐，final label mismatch `0`
  - 新稳态指标保持：`high=101292`，`needs=769836`，`low=739397`，`high_missing_rate=0`，`noisy_high=13`
- 当前现代阶段主要未完成项：基于 `modern_missing_block + fast augment` 重新进入更大时间窗 / 更多 collectors 的 scalability 与 purity 复测，同时继续监控全链路其他阶段耗时。
- S2-A 已做 6h 扩窗首轮尝试：
  - baseline 2 collectors 6h 已完成到 final
  - `events=3431103`
  - `candidate=1804382`
  - `high=123849`
  - `needs=605585`
  - `low=1074948`
  - `high_missing_rate=0`
  - `gating_high=122979`
  - `augment_high=870`
- S2-A 资源结论：Docker 容器在 baseline fast augment 阶段被 `-9` 杀掉，host Python fast augment 成功；12 collectors x 6h expanded 未继续本地硬跑。当前新瓶颈是本地串行 collection/orchestration，而不是 augment 业务逻辑。

## 6. 当前最重要的代码与文档入口

### 6.1 主链代码

- `scripts/run.py`
- `scripts/build_event_units.py`
- `scripts/build_historical_baseline.py`
- `scripts/build_weak_candidates.py`
- `scripts/score_weak_candidates.py`
- `scripts/gate_scored_candidates.py`
- `scripts/augment_uncertain_candidates.py`
- `scripts/build_final_alerts.py`

### 6.2 现代大数据面相关代码

- `scripts/run_s1a_modern_2024.py`
- `scripts/build_weak_candidates_streaming.py`
- `scripts/score_weak_candidates_streaming.py`
- `scripts/gate_scored_candidates_streaming.py`
- `scripts/build_final_alerts_streaming.py`
- `scripts/run_s1b_purity_audit.py`
- `scripts/run_s1c_augment_tightening.py`
- `scripts/run_s1d_modern_new_baseline.py`
- `scripts/run_s1e_augment_profiling.py`
- `scripts/augment_uncertain_candidates_fast.py`
- `scripts/run_s1f_augment_optimization.py`

### 6.3 当前默认文档入口

- `project_docs/HANDOFF.md`
- `project_docs/EXPERIMENT_MAINLINE.md`
- `论文/实验资产索引_v01.md`
- `论文/文献吸收_系统提升规划_v01.md`
- `README_run.md`

## 7. 时间顺序更新记录

### 2026-04-08

- 形成第一版新对话接入背景文档。
- 明确主链结构、基线 run、E6~E8 的主要结论与仓库地图。
- 该阶段文档现在视为“历史 handoff 起点”，后续不再按日期拆分新 handoff 文件。

### 2026-04-13

- 历史阶段推进到 E9-I。
- 已知事件评估完成从单一 `exact_prefix` 到双轨制评估的迁移。
- backup 池首轮复测与 Pakistan 扩窗止损审计完成。
- 历史阶段核心矛盾从“看不见已知事件”转移为“如何把系统搬到现代数据面并保持稳定”。

### 2026-04-14

- 启动 S1-A 现代 2024 pilot。
- 在 modern 2024 expanded collectors 口径下，识别出主链在 event / candidate / score 层的规模瓶颈。
- 为 modern run 新增 streaming candidate / score 方案，并改进 modern orchestration 脚本。
- 当前现代阶段进入“工程稳态化”而不是“理论方向不清”。

### 2026-04-17

- 建立 `project_docs/` 作为唯一长期维护文档目录。
- 固定：后续只维护一份 handoff 和一份实验主线表。
- 旧的 `runs/prism_handoffs/` 与 `论文/实验总表_v01.md` 等文件暂保留为历史归档，不再作为默认入口。
- S1-A `pilot_60m_april16` 首轮 modern 2024 pilot 完成收口。
- 新增并验证：
  - `scripts/gate_scored_candidates_streaming.py`
  - `scripts/build_final_alerts_streaming.py`
- 现代 pilot 正式输出目录固定为：`outputs/s1a_modern_2024_pilot_60m_v02/`
- 当前阶段转入：更大时间窗 / 更高 collector 覆盖下的现代稳定性与纯度审计。
- 完成 S1-B modern high purity audit，定位到 high 膨胀的主要来源桶：
  - `augmentation_promoted + missing=true + structural_novelty_score`
  - 目前 noisy-high 几乎全部集中在这一个模式上
- 下步默认动作：先围绕 augment / score 做定向收紧实验，而不是先改 gate。

### 2026-04-20

- 完成 S1-C modern augment 收紧小步实验。
- 在不改 score / gate / candidate 的前提下，验证了只拦 `missing=true` 的 augment promotion 就足以把 noisy-high 从 `37246` 压到 `13`。
- `A2_missing_or_conflict_block` 与 `A1_missing_block` 完全等价，说明额外 conflict 约束在当前 modern 60 分钟口径下没有新增价值。
- `A3_missing_block_plus_threshold70` 虽然进一步把 high 压到 `88916`，但属于更激进的收缩，不适合作为第一步止血方案。
- 当前默认最优变体固定为：`A1_missing_block`。
- 完成 S1-D modern end-to-end rerun，确认 `modern_missing_block` profile 在真实主流程中可稳定复现 S1-C A1 的离线最优结果。
- 新增做法：`augment_uncertain_candidates.py` 引入 profile 机制，默认 `default` 不变，`modern_missing_block` 专用于现代数据面。
- 最小历史兼容性 spot-check 显示：31 条 `missing=true` 的 augmentation-high 被打回 needs，但 gate 主体高优未受伤；因此该规则可以作为 modern profile 默认，不宜无条件覆盖历史 default。

### 2026-04-21

- 完成 S1-E augment 性能剖析。
- 确认 S1-D 暴露的 `60 分钟 modern 数据 -> augment 约 110 分钟` 不是 I/O 主导，而是逐行规则计算主导。
- profiling 小样本结果显示：`core_augment_loop` 占总耗时 `95.27%`，其中 `calc_multi_view_support_score` / `near_time` 是第一瓶颈。
- 完成 S1-F 保守版性能优化。
- 新增 `augment_uncertain_candidates_fast.py`，使用数组化 interval index / `numpy.searchsorted` 替代核心近时间窗逐行 DataFrame 过滤。
- S1-F 全量回归严格通过：augment 与 final 输出完全对齐 S1-D，最终 `high=101292`、`missing_rate=0`、`noisy=13`。
- 性能从 `6634.60s` 降至 `399.29s`，提速 `16.62x`；可以恢复扩窗实验，但需要继续监控全链路其他阶段。
- 启动 S2-A 6h 扩窗复测。
- 新增 `pilot_6h_april16` 到 `data/modern_2024/s1a_modern_2024_plan_v01.json`。
- `run_s1a_modern_2024.py` 增加 `--augment-script` 参数，默认仍使用原始 augment；S2 显式使用 fast augment。
- S2-A baseline 2 collectors 6h 完成，但 expanded 12 collectors 6h 因本地串行耗时过高暂停。产物固定在 `outputs/s2a_modern_2024_6h_v01/`。

## 8. 下一步默认动作

如果后续继续推进实验，默认顺序如下：

1. 先看 `project_docs/EXPERIMENT_MAINLINE.md` 确认当前做到哪一步。
2. 保持 `modern_missing_block` 作为 modern profile 默认；历史 default profile 暂不改写。
3. S1-F 已证明 fast augment 业务无损，后续 modern 扩窗优先使用 fast augment 路径，同时保留原始 augment 脚本作为回归参照。
4. 下一轮不要继续本地串行跑 expanded 12 collectors x 6h。优先二选一：
   - HPC `sbatch`：用容器 + live log 方式跑 expanded 6h。
   - 本地工程优化：先做 collector 并行化 / 分阶段计时脚本，再重跑 expanded。
5. expanded 6h 完成后，再决定是否进入 24h；不要直接跳 24h。
6. 扩展稳定后，再进入 stealth / NO_EXPORT / 2024 隐蔽狩猎所需的特征扩展与数据准备。
7. 不回头为历史事件口径反复折腾；历史阶段默认视为已收口资产。

## 9. 使用规则

- 后续新增实验，不要新建 dated handoff。
- 后续新增实验，不要再新开第二张实验总表。
- handoff 负责“新对话快速接手 + 当前状态 + 时间线更新记录”。
- 主线总表负责“按实验顺序记录问题、口径、结论、状态与产物路径”。

## 10. 归档说明

以下旧文件先保留，但不再作为默认维护入口：

- `runs/prism_handoffs/2026-04-08_experiment_context_v1.md`
- `论文/实验总表_v01.md`

后续如果需要继续减目录，可以再把这些旧文件改成简短跳转说明。
