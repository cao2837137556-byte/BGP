# BGP Platform Handoff

最后更新：2026-04-30
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
- S2-A-HPC 执行准备已完成：
  - `scripts/run_s2a_collect_one.py`：单 collector raw collection，支持 marker resume，已完成 collector 自动跳过。
  - `scripts/run_s2a_merge_collector_runs.py`：把 collector-wise raw runs 合并成统一 expanded run。
  - `scripts/run_s2a_downstream_from_raw.py`：从 merged raw 继续跑 CAIDA / event / baseline / candidate / score / gate / fast augment / final，并输出 downstream 报告。
  - `scripts/hpc/s2a_collect_array.slurm`：12 collectors 的 Slurm array 采集模板，默认并发 `%4`。
  - `scripts/hpc/s2a_merge_downstream.slurm`：merge + downstream + bundle 的 Slurm 模板。
  - 设计原则：远端拉取失败不阻塞全实验；失败 collector 可补采；最终报告记录 `successful_collectors / partial_collectors / failed_collectors`。

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
- `scripts/run_s2a_collect_one.py`
- `scripts/run_s2a_merge_collector_runs.py`
- `scripts/run_s2a_downstream_from_raw.py`
- `scripts/hpc/s2a_collect_array.slurm`
- `scripts/hpc/s2a_merge_downstream.slurm`

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

### 2026-04-23

- 固定 S2-A-HPC 超算执行方案。
- 新增 collector-wise collection array，避免 12 collectors 被单个远端超时拖死。
- 新增 collector run merge 与 downstream 分离脚本，保证采集失败时不浪费 downstream 计算。
- 新增 HPC slurm 模板，保持此前固定的超算逻辑：`sbatch` 提交，`live.log` 可观察，bundle 便于下载。

### 2026-04-24

- 通过 S2-A-HPC 首轮尝试确认：超算侧直接在线拉取 2024 RouteViews/RIS 原始 updates 不稳定，多个 collector 会长时间卡在 `scripts/run.py` 原始采集阶段，`live.log` 无新增而 parquet 仅少量落盘。
- 当前默认策略正式切换为：
  1. 本地 / Docker 侧负责 raw parquet 拉取；
  2. 超算只负责 merge、CAIDA、event、baseline、candidate、score、gate、fast augment、final。
- 为此新增本地 orchestrator：`scripts/run_s2a_local_collect.py`
  - 作用：顺序调用 `scripts/run_s2a_collect_one.py`，按 collector 本地拉取 raw 数据；
  - 输出：`outputs/s2a_local_collect_v01/`
  - 目的：减少手工拼 collector/run_id，固定“本地拉 raw -> 上传 -> 超算下游”流程。
- 当前对 S2-A 的执行判断更新为：
  - 不再优先尝试“超算直接在线拉 raw”
  - 后续 modern 大窗口实验默认先在本地完成 raw 采集，再把 `data/runs/<base_run_id>__collector_*` 上传到超算
  - 超算只用 `scripts/hpc/s2a_merge_downstream.slurm` 做计算，不再承担不稳定的网络拉取职责

### 2026-04-29

- 完成 S2-A expanded 12 collectors x 6h 的阶段性定位。
- 已完成并固定的 6h expanded 中间资产：
  - raw/rel chunks：`864`
  - events：`15667871`
  - baseline prefix：`820226`
  - baseline prefix-origin：`928780`
  - baseline path：`8009034`
  - candidate：`10236431`
  - candidate_rate：`65.33%`
- S2-A 超算 downstream 失败位置已明确：不是 raw / events / baseline / candidate，而是 score 阶段在 12h wall time 内未完成。
- 新增 S2-B1：score fast scorer 本地正确性与性能验证。
- 新增 `scripts/score_weak_candidates_streaming_fast.py`：
  - 保留原 scorer 作为 reference；
  - 新增 part/checkpoint/resume 输出：`scores/parts/part_*.parquet` + `score_parts_manifest.json`；
  - 正式 `scored_candidates.parquet` 只在全部 part 完成后生成，避免中途失败产物被误用；
  - 默认 `score_explanation_mode=minimal`，核心审计字段仍由显式 component columns 保留；如需逐行 JSON，可用 `--score-explanation-mode full` 小规模复跑。
- S2-B1 本地 validation 结果：
  - correctness sample：`50000` candidate rows，实际 scored `31556`
  - mismatch：`0`（event_id、四个 score、risk_score、risk_bucket、top factor、missing flag 全对齐）
  - reference sample：`4024.66 rows/sec`
  - fast benchmark：`27162.13 rows/sec`
  - speedup：`6.75x`
  - 估算 full `10236431` candidate score 阶段：约 `376.86s`（约 `6.3min`）
- 当前判断：S2-B1 已证明 score 阶段可从性能瓶颈转为可续跑阶段；下一步应上传新增 S2-B 脚本到超算，并只从 score 阶段续跑，不重跑 events/baseline/candidate。
- 完成 S2-B2：在超算上从 score 阶段续跑 `s2a_expanded_v01_pilot_6h_april16`，未重跑 raw / events / baseline / candidate。
- S2-B2 正式产物：
  - 远端 run：`/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/repo/data/runs/s2a_expanded_v01_pilot_6h_april16/`
  - 本地报告：`outputs/s2b_score_optimization_v01/s2b_score_optimization_report.md`
  - 本地 summary：`outputs/s2b_score_optimization_v01/s2b_summary.json`
  - bundle：`outputs/bundles/s2b_score_optimization_bundle.zip`
- S2-B2 关键耗时：
  - score stage：`169.87s`
  - scorer core：`123.20s`，`83089.77 rows/sec`
  - gate：`631.36s`
  - fast augment：`2055.74s`
  - final：`1627.28s`
  - score->bundle 总耗时约 `4484.49s`（约 `74.7min`）
- S2-B2 关键结果：
  - total_events：`15667871`
  - candidate_count / scored_count / gated_count：`10236431`
  - final_high：`639548`
  - final_needs：`4839755`
  - final_low：`4757128`
  - high_missing_rate：`0.0`
  - gating_likely_malicious_to_high：`581112`
  - augmentation_promoted_to_high：`58436`
  - score risk buckets：low `4094488`，medium `4094284`，high `2047659`
  - score parts：`63`
- 当前判断：S2-B2 已证明 expanded 6h 全链路可以从已完成 candidate 资产稳定续跑到 final；score 不再是瓶颈，新的主要耗时集中在 fast augment 与 final。`modern_missing_block` 在 6h expanded 上继续把 `high_missing_rate` 保持为 `0`。后续不应回到 score 性能修复，而应转入 S2-C 级别的 6h expanded high composition / purity audit，再决定是否进入 24h。
- S2-C high composition / purity audit 已完成：
  - 新增 `scripts/run_s2c_high_audit.py`
  - 新增 `scripts/hpc/s2c_high_audit.slurm`
  - 作用：只读 S2-B2 已有 `final/events/augmentation` 产物，输出 high composition / purity audit；未重跑检测主链。
  - 输出目录：`outputs/s2c_expanded_6h_high_audit_v01/`
  - bundle：`outputs/bundles/s2c_expanded_6h_high_audit_bundle.zip`
  - total_events：`15667871`
  - candidate_count：`10236431`，candidate_rate：`65.33%`
  - final_high：`639548`，final_needs：`4839755`，final_low：`4757128`
  - high_missing_rate：`0.0`
  - clean_high：`0`
  - fragile_high：`639535`
  - noisy_high：`13`
  - gating_likely_malicious_to_high：`581112`（约 `90.86%` high）
  - augmentation_promoted_to_high：`58436`（约 `9.14%` high）
  - hourly high rate vs candidates 在 `5.72%~6.67%` 区间，未见小时级尖峰失稳。
  - 与 S1-D/S1-F 60min 参考按小时对比：candidate `1.059x`，final_high `1.052x`，final_needs `1.048x`，final_low `1.072x`，整体近线性；gate high `1.133x`，augment high `0.617x`。
  - noisy-high 的 `13` 条全部来自 `gating_likely_malicious + structural_novelty_score + conflict_score=30`，不来自 augment promotion；augmentation-promoted high 全部为 `fragile-high`，missing/conflict 均为 `0`。
  - 当前判断：S2-C 通过，6h expanded high 池没有复发 S1 的 missing=true noisy-high 膨胀，也未发现新的 augment noisy-high 模式；可以进入 S2-D 24h 扩窗的资源规划与执行准备，但不要改检测主链。
- 吸收 GPT 深度调研报告 `gpt调研/BGP 弱信号系统升级与事件聚合研究报告.docx` 后，下一步顺序修正：
  - 不直接先跑 24h event-level 主评估。
  - 先做 S3-A incident aggregation / ticketization，把 `high_priority_alert + needs_review` 从 event-level 输出聚合为 incident tickets。
  - 原因：S2-C 已证明 6h high purity 稳定，当前瓶颈是 `needs_review=4839755` 仍以逐条 event 暴露，评估单位不对。
  - S3-A 不改上游检测主链，只在 final 之后新增 post-processing layer。
- S3-A incident aggregation 已在超算完成并拉回：
  - 新增 `project_docs/S3A_INCIDENT_AGGREGATION.md`
  - 新增 `scripts/build_incident_aggregation.py`
  - 新增 `scripts/run_s3a_incident_aggregation.py`
  - 新增 `scripts/hpc/s3a_incident_aggregation.slurm`
  - 默认输入：`data/runs/s2a_expanded_v01_pilot_6h_april16/final/final_alerts.parquet` 与 `events/event_units.parquet`
  - 输出：`data/runs/s2a_expanded_v01_pilot_6h_april16/incidents/`、`outputs/s3a_incident_aggregation_v01/`、`outputs/bundles/s3a_incident_aggregation_bundle.zip`
  - 输入 raw alerts：`5479303`，其中 high `639548`、needs `4839755`
  - micro incidents：`1839957`
  - incident tickets：`217165`
  - compression_ratio：`25.231059`
  - analyst_workload_reduction：`0.960366`
  - family tickets：`forged_origin_like=216801`，`route_leak_like=364`
  - priority tickets：`P1_high=42047`，`P2_review=13039`，`P3_background=162079`
  - priority event coverage：P1 `2775776` rows，P2 `1999368` rows，P3 `704159` rows
  - 关键观察：incident layer 成功把 547.9 万 high/needs event 压缩为 21.7 万 tickets，证明评估单位转换有效；route-leak-like 与 forged-origin-like 已形成不同队列。
  - 关键风险：3 个 `dominant_origin_as=NA` 的超大 P2 incident 覆盖 `348708` 条 needs、`149178` 个 affected prefix，`incident_score=100` 但 confidence 约 `0.51`，更像 unknown-origin / background artifact；P1 tickets 仍有 `42047` 个，直接进入人工验证仍偏大。
  - 当前判断：S3-A 首版完成且有效，但需要 S3-A2 做 priority calibration / NA-origin handling，再进入 S3-B verification pilot；不需要重跑 raw/events/baseline/candidate/score/gate/augment/final。
- 吸收 2026-05-06 GPT 讨论后的项目级判断：
  - 新增 `project_docs/S3_DETECTION_QUALITY_ROADMAP.md`
  - 500 多万 high/needs rows 不应被视为最终异常，更准确是宽口径 suspicious event rows。
  - S3-A 证明 event -> incident 框架可行，但 clean stable window 下 high/needs 仍过大；当前主矛盾已经从 pipeline scalability 转为 detection quality。
  - 后续不能只继续聚合或直接扩到 24h，而要用 S3-A 暴露出的噪声结构，反向指导 score/gate/verification 的检测能力升级。
  - candidate 可以保持宽口径召回，但 score/gate/priority 必须增强语义区分能力，使系统从“能筛很多弱信号”转为“能把值得看的弱信号排到前面”。
- S3-A2 priority calibration 已完成：
  - 新增 `scripts/run_s3a2_incident_priority_calibration.py`
  - 新增 `project_docs/S3A2_PRIORITY_CALIBRATION.md`
  - 输出目录：`outputs/s3a2_incident_priority_calibration_v01/`
  - 不重跑上游检测链，只读 S3-A `incident_tickets.parquet` 与 `incident_membership.parquet`
  - membership 校验：rows `5479303`，incident count `217165`，ticket member_count sum `5479303`，mismatch `0`
  - 校准前 tickets：P1 `42047`，P2 `13039`，P3 `162079`
  - 校准后 tickets：P1 `41885`，P2 `13198`，P3 `162082`
  - 校准前 member coverage：P1 `2775776`，P2 `1999368`，P3 `704159`
  - 校准后 member coverage：P1 `2565156`，P2 `1861280`，P3 `1052867`
  - 降级：共 `165` tickets / `559328` members；P1->P2 `162` tickets；P2->P3 `3` tickets
  - 3 个 `dominant_origin_as=NA` 超大 P2 全部降为 P3，覆盖 `348708` needs、`0` high，confidence `0.5065~0.5229`
  - 当前判断：S3-A2 成功隔离明显坏工单，但 calibrated P1/P2 仍大；下一步进入 S3-B noise source audit，而不是 24h。

## 8. 下一步默认动作

如果后续继续推进实验，默认顺序如下：

1. 先看 `project_docs/EXPERIMENT_MAINLINE.md` 确认当前做到哪一步。
2. 保持 `modern_missing_block` 作为 modern profile 默认；历史 default profile 暂不改写。
3. S1-F 已证明 fast augment 业务无损，后续 modern 扩窗优先使用 fast augment 路径，同时保留原始 augment 脚本作为回归参照。
4. S2-A expanded 6h 的 raw/events/baseline/candidate 已经是重要资产，不要删除或重建。
5. S2-B2 已完成；不要再重跑 raw/events/baseline/candidate，也不要把旧的 `scores/scored_candidates_tmp.parquet` 当正式结果。
6. S2-C 已完成并通过；不要为 6h high purity 再反复重跑主链。
7. S3-A 已完成；不要重复运行首版 incident aggregation，除非代码参数改动后做 S3-A2。
8. S3-A2 已完成；不要重复运行，除非调整 calibration thresholds/rules。
9. 下一轮默认执行 S3-B noise source audit：审 P1/P2、needs_review、large fan-out incidents 的 reason/origin/prefix/path 模式，回答 clean stable window 为什么仍有大量 suspicious rows。
10. S3-B 后执行 S3-C detection capability upgrade design：围绕 role churn、AS Hegemony delta、forged-origin path plausibility、route-leak triplet legality、RPKI/IRR/PeeringDB、NO_EXPORT/communities 等，决定哪些进入 score/gate/augment/verification。
11. S3-D 再做 incident-level verification，形成 high-confidence set，反向校准 score/gate/priority。
12. 24h expanded 应作为 `S2-D 24h with incidents`，不要回到纯 event-level 评估。
13. 扩展稳定后，再进入 stealth / NO_EXPORT / 2024 隐蔽狩猎所需的特征扩展与数据准备。
14. 不回头为历史事件口径反复折腾；历史阶段默认视为已收口资产。

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
