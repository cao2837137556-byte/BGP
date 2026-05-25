# BGP Platform Handoff

最后更新：2026-05-23
定位：项目唯一长期维护的交接总览文件。

## Current Strategic State

- Current Raw Incident Entry State:
  - Phase R-AGG-1 Raw Incident Dossier schema design has completed as a schema/mapping preview step.
  - `configs/raw_incident_dossier_schema_v0.yaml` is the active schema v0. It uses candidate-entry as the primary source and keeps final-entry as comparison/reference only.
  - `scripts/prototype_raw_incident_schema_mapping.py` ran on local candidate parquet `s2a_baseline_v01_pilot_6h_april16` with `5000` sampled rows. Schema field coverage is `0.904762`; required field missing rate is `0.075059`.
  - Available lookup keys in the sample: `prefix_origin_key`, `as_path_signature`, `collector_set`, and `candidate_reason_set`. `time_scope` is not ready because candidate-entry has `duration_sec` but no `start_time` / `end_time`; R-AGG-2 should repair this via event-entry join or upstream retention.
  - R-AGG-1 does not implement aggregation, does not attach external evidence, does not train learning, and produces no truth label.
  - Next step is R-AGG-2 Raw Incident prototype aggregation, then Evidence-grounded Incident construction after the Raw Incident schema is stable.
  - Phase R-AGG-ENTRY-0 Raw Incident entry point audit has completed as a read-only audit plus documentation update.
  - The system is now re-anchored as explainable incident construction plus evidence grounding, with future semantic learning after the incident/evidence schemas stabilize.
  - R-AGG-ENTRY-0 compared `event-entry`, `candidate-entry`, `scored-entry`, `gated-entry`, `augmented-entry`, and `final-entry` for Raw Incident Dossier construction.
  - Recommended main entry is `candidate-entry`: it keeps trigger reasons and aggregation context while avoiding final/gate/augment judgment contamination.
  - Recommended auxiliary entries are `event-entry` for raw observability recall and `scored-entry` for a diagnostic upper bound, not as truth.
  - Directly using the old final-level 21w ticket aggregation as the paper main口径 is prohibited unless a later audit explicitly justifies it.
  - final labels are weak workflow signals, not truth labels; high/needs/low and P1/P2/P3 remain workflow or priority hints, not truth.
  - background-like is operational suppression, not confirmed benign. family_hint is semantic hint, not confirmed attack label.
  - R-AGG-1 has now turned this into a schema/mapping design. Next candidate step is R-AGG-2 Raw Incident prototype aggregation, then Evidence-grounded Incident construction.
  - poisoning benchmark retained for R-3; learning layer postponed until Raw Incident Dossier and Evidence-grounded Incident are stable, with future direction toward BEAM-style semantic learning for representation/prioritization rather than rule re-scoring.
- Current Decision State:
  - Phase R-DOC-1 research decision consolidation has completed as a documentation-only step.
  - `project_docs/PROJECT_DECISION_REGISTER.md` is now the long-lived decision register for architecture boundaries, output taxonomy, Stage 1 / Stage 2 evidence reuse, component purity, abstain handling, communities / NO_EXPORT propagation, AS-rel consistency, learning-layer timing, and near-term roadmap.
  - Unified output taxonomy is locked to small `primary_family` values plus `observability_mode`, `verifier_state`, and extensible `evidence_tags`; evidence combinations must not become category explosion.
  - Stage 1 remains weak trigger / organizer / lookup-key provider. Stage 2 remains provenance-aware verifier evidence. Evidence reuse across stages is allowed only with clear role and version metadata.
  - Learning remains after verifier and before Top-K; current state is no formal learning training until R-OUT-1 schema, R-CONSIST consistency handling, and R-2D-P0 communities propagation design are stable.
  - Next candidates are R-OUT-1 unified incident output taxonomy design, R-CONSIST-2 aligned AS-rel reannotation / impact comparison, and R-2D-P0-design communities propagation schema design.
- Current R-CONSIST-1 State:
  - Phase R-CONSIST-1 Stage 1 evidence provenance and AS-rel alignment audit has completed.
  - Stage 1 AS-rel source was detected as legacy CAIDA `2017-07-01` via defaults in `scripts/04_annotate_caida_rel.py`, `scripts/run.py`, and `scripts/run_s2a_downstream_from_raw.py`.
  - Stage 2 R-2C uses the versioned 2024-near CAIDA cache `data/evidence/as_relationships/as_rel_2024-04-01.parquet`, snapshot `2024-04-01`, run date `2024-04-16`, delta `15` days.
  - Consistency status is `likely_inconsistent`; risk level is `high` if stale Stage 1 AS-rel-derived weak/path fields are used as final main-result evidence without alignment or drift analysis.
  - Affected fields are primarily `rel_seq`, `rel_unknown_cnt`, `rel_has_unknown`, and S3-C path plausibility fields; current audit did not find direct AS-rel snapshot dependency in incident grouping, which is based on AS-path signatures.
  - Recommended next action is `r_consist2_aligned_reannotation`, not blind full Stage 1 replay. If aligned reannotation changes candidate/gate/incident outputs, escalate to R-CONSIST-2 aligned Stage 1 replay.
  - Final paper main results must use consistent versioned evidence cache snapshots, or explicitly report drift/impact analysis. Unreported mixed AS-rel snapshots are not allowed.
- Current Phase R-2D State:
  - Phase R-2D-0 communities / NO_EXPORT field availability audit has completed on fixed S2.
  - Raw update chunks preserve a `communities` field in `864` parquet files; full audit scanned `39039005` raw rows, with `35657850` non-empty community rows and parser success on `27843441` rows.
  - Well-known community rows observed in raw updates: `NO_EXPORT=223410`, `NO_ADVERTISE=1240`, `NO_EXPORT_SUBCONFED=0`, `NOPEER=5634`.
  - Communities are retained only at `raw_updates`; they are not present in `event_units`, `incident_membership`, `incident_tickets`, or R-2B/R-2C verifier outputs, so incident join readiness is `false`.
  - This is not a NO_EXPORT attack detector: NO_EXPORT present is not confirmed attack, NO_EXPORT absent is not safe, and low visibility is not confirmed NO_EXPORT.
  - Next step is pipeline retention repair around `scripts/build_event_units.py` and downstream incident membership propagation, then R-2D-0 rerun before any R-2D-1 community-aware stealth evidence branch.
- Current CCF-A Target State:
  - Main target: CCF-A / top-tier networking or security venue.
  - SCI Q2 is only a fallback, not the design target.
  - Final system positioning: poisoning-robust, evidence-constrained, component-aware semantic BGP incident triage under partial observability.
  - Learning layer must become a component-aware semantic ranker/calibrator after verifier-supported targets exist; it must not become an attack/benign classifier.
- Current Architecture Lock State:
  - Phase R-LOCK-1 completed.
  - Final paper-facing architecture is now locked to three stages: Stage 1 Monitor-triggered Incident Construction, Stage 2 Evidence-constrained Verification, Stage 3 Component-aware Learning Triage, followed by the Top-K Review Queue.
  - The legacy seven-layer pipeline is retained as Stage 1 incident construction and weak-signal context only; it is not the final detector or truth source.
  - The learning layer sits after the verifier and before Top-K review; it ranks/calibrates components and incidents but cannot override verifier hard rules.
  - Every module must map to a failure mode and must be defensible by ablation.
- Phase R has started.
- The previous "BGP forged-origin weak-signal detector" positioning is superseded by "adversarially robust multi-evidence BGP incident verification and triage".
- No new experiments should be launched before Phase R documents are finalized and the verifier redesign entry point is clear.
- Current S3-D2B results are preserved as evidence-alignment groundwork, not final verification.
- Next implementation phase should start with verifier state machine and legality-first verifier, not another detector.
- Legacy `high/needs/low` and `P1/P2/P3` remain useful signals, but they are not truth labels or final verdicts.
- Phase R-1 verifier state machine design is completed as documentation only.
- Current focus is verifier semantics, evidence states, verdict space, confidence caps, and hard safety rules; not detector implementation.
- Next implementation should be R-2 legality-first verifier only after R-1 design is accepted.
- Phase R-2A legality-first verifier scaffold has completed on 50k fixed S2 incidents; it produced a verifier table without modifying legacy high/needs/low, P1/P2/P3, or S3 outputs.
- Phase R-2B-0 evidence readiness audit has completed on all `217165` fixed S2 incidents.
- R-2B-0 found that incident lookup keys are largely ready (`217162` prefix-origin complete, `216922` path-key complete), while aligned external caches are not ready: RPKI/VRP missing, IRR missing, ASPA missing, PeeringDB missing, and only stale 2017 CAIDA AS-rel is available.
- Phase R-2B-P0b historical VRP/RPKI cache materialization has completed for `2024-04-16`: `530187` aligned VRP records, `217162` lookup-eligible prefix-origin targets, RPKI status `valid=122280`, `invalid_asn=397`, `invalid_length=283`, `unknown=94202`, `unavailable=0`, and no hard safety violations.
- Phase R-2B VRP-aware verifier smoke has completed on all `217165` fixed S2 incidents with member/component RPKI audit: `evidence_supported_suspicious=55`, `evidence_conflict=86`, `abstain=4684`, `background_like_but_unconfirmed=156971`, `evidence_insufficient=55366`, `external_evidence_unavailable=3`, `strongly_supported_suspicious=0`, hard safety violations `0`.
- Phase R-2B-OPS operational burden and real-time evidence cache audit has completed: projected daily `evidence_supported_suspicious=220`, `evidence_conflict=344`, `abstain=18736`, `evidence_insufficient=221464`, `background_like_but_unconfirmed=627884`; Top-50 supported density `1.0`, Top-100 `0.53`, Top-500 `0.11`; online path must use local evidence-cache lookup only, not remote per-incident downloads.
- Phase R-2C-0 path evidence readiness audit has completed: `217165` incidents checked; complete path-key incidents `217162` (`0.999986`); AS-pair targets `216922`; triplet targets `205067`; full-path targets `217162`; 2017 CAIDA AS-rel is `ready_stale` only; 2024-near AS-rel, ASPA, BGP Roles/OTC, and PeeringDB caches are missing.
- Phase R-2C-P0b 2024-near CAIDA AS relationship cache materialization has completed: source `https://data.caida.org/datasets/as-relationships/serial-2/20240401.as-rel2.txt.bz2`; snapshot `2024-04-01`, run date `2024-04-16`, delta `15` days; raw AS-rel records `571330`, directed lookup records `1142660`; AS-pair unique match rate `0.918932`; no route-leak verdict generated and no verifier verdict modified.
- Phase R-2C-P1 path relation lookup smoke has completed on fixed S2: expanded AS-pair rows `421989`, row-level AS-pair match rate `0.947510`, triplet rows `205067`, full-path rows `217162`, incident path evidence rows `217165`; path states `aligned_medium=161992`, `diagnostic_only=34192`, `evidence_insufficient=18084`, `unavailable=2897`; route-leak-like diagnostic candidates `34555`; path-manipulation-like diagnostic candidates `44189`; no route-leak verdict generated and no R-2B verifier verdict modified.
- Phase R-2C-P2 path-legality verifier smoke has completed on fixed S2: processed incidents `217165`; verdict smoke distribution `background_like_but_unconfirmed=127889`, `evidence_insufficient=78324`, `abstain=10822`, `evidence_conflict=86`, `evidence_supported_suspicious=44`; route-leak-like review candidates `34555`; path-manipulation-like review candidates `44189`; `strongly_supported_suspicious=0`; hard safety violations `0`; no confirmed route-leak label generated and no R-2B verifier verdict modified.
- Phase R-LOCK-1 architecture minimality and ablation plan has completed: old seven-layer pipeline compressed into Stage 1, verifier locked as Stage 2, learning ranker locked as Stage 3 before Top-K, output card schema simplified, and ablation plan A0-A9 defined for reviewer defense.
- Next default steps are R-AGG-2 Raw Incident prototype aggregation, Evidence-grounded Incident construction, R-OUT-1 unified incident output taxonomy design, R-CONSIST-2 aligned AS-rel reannotation / impact comparison, R-2D-P0 communities propagation schema design / repair plus R-2D-0 rerun, R-3 poisoning benchmark design, and L1 component-aware semantic learner design; do not return to legacy detector-score tuning unless explicitly requested.

## 1. 固定工作边界

- 主仓库：`D:\study\paper\bgp-platform`
- 实验 worktree：`D:\study\paper\worktrees\bgp-platform-exp-mainline`
- 固定分支：`codex/bgp-exp-mainline`
- 当前角色：BGP-EXP，只负责实验代码、实验流程、实验资产整理，不负责论文正文。

## 2. 项目一句话定义

Phase R 后，项目主线重定位为：对抗鲁棒多证据 BGP 事件验证与分诊系统。

旧的 forged-origin weak-signal layered detector 仍作为历史 groundwork 保留：它提供 candidate trigger、incident aggregation、noise audit、gate evidence、verification queue 和 evidence attachment 的基础资产。但最终论文问题不再是“再做一个公共监控器上的 detector”，而是在 public monitor 可被操纵、ground truth 不完备、外部证据不完备的条件下，如何输出带 confidence、provenance 和 abstain 的 evidence-supported verification verdict。

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
- S3-B noise source audit 已完成：
  - 新增 `scripts/run_s3b_noise_source_audit.py`
  - 新增 `project_docs/S3B_NOISE_SOURCE_AUDIT.md`
  - 输出目录：`outputs/s3b_noise_source_audit_v01/`
  - 输出：`s3b_noise_summary.json`、`s3b_priority_reason_patterns.csv`、`s3b_needs_review_source_patterns.csv`、`s3b_large_fanout_incidents.csv`、`s3b_origin_prefix_path_hotspots.csv`、`s3b_p1_p2_quality_by_pattern.csv`、`s3b_detection_upgrade_candidates.csv`、`s3b_report.md`
  - calibrated P1/P2：`55083` tickets，`4426436` rows，其中 high `632640`、needs `3793796`
  - large fan-out：`1832` tickets；其中 P1/P2 `1829` tickets / `1102322` rows
  - needs_review 来源：with-high weak support `2826078` rows，single-collector/sparse/short-lived `1242749` rows，large-fanout background-like `764874` rows，route-leak-like `3952` rows，forged-origin-like residual `2102` rows
  - 最大 P1/P2 噪声/弱信号结构：`single_collector_visibility + structural_novelty_score + unseen_path_for_prefix_origin + unusually_short_duration_for_prefix`，覆盖 `27120` tickets / `3943362` rows，weighted high share 约 `0.095`
  - 第二结构：`abnormal_path_length_for_prefix_origin + single_collector_visibility + structural_novelty_score + unseen_path_for_prefix_origin`，覆盖 `24311` tickets / `343856` rows，weighted high share 约 `0.681`
  - 当前判断：S3-B 证明 P1/P2 偏大主要来自低可见度/短时 path novelty 在 clean stable window 中过度贡献；large fan-out 是重要噪声源但不是唯一噪声源；route-leak-like 与 forged-origin-like 应继续分队列。
- S3-C1 visibility-aware path plausibility pilot 已完成 full：
  - 新增 `scripts/run_s3c1_visibility_path_plausibility_pilot.py`
  - 新增 `scripts/hpc/s3c1_visibility_path_plausibility.slurm`
  - 新增 `project_docs/S3C1_VISIBILITY_PATH_PLAUSIBILITY.md`
  - 作用：只读 scored/candidate/event/gate/final/incident inputs，新增离线 plausibility fields 与 `adjusted_risk_score_s3c1`，不覆盖 score/gate/final/incidents。
  - 默认 target：`pattern_A = single_collector_visibility + structural_novelty_score + unseen_path_for_prefix_origin + unusually_short_duration_for_prefix`
  - 默认不强降：`pattern_B = abnormal_path_length_for_prefix_origin + single_collector_visibility + structural_novelty_score + unseen_path_for_prefix_origin`
  - penalty：`pattern_A && !pattern_B && low_plausibility -> -15`，`pattern_A && !pattern_B && medium_plausibility -> -5`
  - S1A 60min expanded 20 万行 smoke 通过：
    - loaded_rows `200000`
    - pattern_A_rows `133289`
    - pattern_B_rows `12938`
    - adjusted_risk_changed_rows `122956`
    - risk_bucket_changed_rows `84041`
    - pattern_B_adjusted_down_rows `0`
  - S2 fixed-run full 已在超算完成并拉回：
    - input / loaded / joined rows `10236431 / 10236431 / 10236431`
    - missing_join_rows `0`
    - pattern_A_rows `7440623`
    - pattern_A_adjusted_down_rows `6885990`
    - pattern_B_rows `659862`
    - pattern_B_adjusted_down_rows `0`
    - risk_bucket_changed_rows `4576319`
    - score high `2047659 -> 1187117`
    - score medium `4094284 -> 937913`
    - score low `4094488 -> 8111401`
    - P1/P2 joined rows `4426436`
    - adjusted_down_rows_in_p1_p2 `3510753`
    - touched_p1_p2_incidents `32469`
  - known-event inventory 未上传到超算，regression check 为空。
  - 当前判断：S3-C1 证明 visibility-aware plausibility 能精准打到 pattern_A 且保护 pattern_B，但默认 penalty 对 bucket 迁移过强；不能直接并入主链，下一步先做 S3-C1b 权重/penalty 校准。
- S3-C1b penalty calibration 已完成本地代码与 smoke：
  - 新增 `scripts/run_s3c1b_penalty_calibration.py`
  - 新增 `scripts/hpc/s3c1b_penalty_calibration.slurm`
  - 新增 `project_docs/S3C1B_PENALTY_CALIBRATION.md`
  - 作用：复用 S3-C1 plausibility feature logic，比较 default、low-only、soft-medium、gate-only、medium-gate-only 等策略；不覆盖任何主链输出。
  - 本地 `s1a_expanded_v02_pilot_60m_april16` 20 万行 smoke 通过：
    - default bucket_changed_rows `84041`
    - recommended_strategy `strategy_medium_gate_only`
    - recommended bucket_changed_rows `28`
    - recommended pattern_A_adjusted_down_rows `144`
    - recommended pattern_A_gate_evidence_rows `122812`
    - pattern_B_adjusted_down_rows `0`
    - known_event_available `true`，matched rows `0`
  - fixed S2 full 已完成并拉回：
    - input/loaded rows `10236431 / 10236431`
    - status `completed`，warnings `0`
    - recommended_strategy `strategy_medium_gate_only`
    - default bucket_changed_rows `4576319`，score-high `2047659 -> 1187117`
    - recommended bucket_changed_rows `5183`，score-high `2047659 -> 2042688`
    - recommended pattern_A_adjusted_down_rows `15294`
    - recommended pattern_A_gate_evidence_rows `6870696`
    - pattern_B_adjusted_down_rows `0`，pattern_B_bucket_changed_rows `0`
    - P1/P2 adjusted_down_rows `31`
    - P1/P2 gate_evidence_rows `3510722`
    - touched_p1_p2_incidents `32469`
    - known-event inventory 可读，但 matched rows `0`，不能据此声称无 regression 风险。
  - 当前判断：S3-C1b fixed S2 full 支持 `strategy_medium_gate_only`；下一步把该推荐接入 S3-C2 fixed S2 gate evidence ablation。
- S3-C2 gate evidence ablation scaffold 已完成本地代码与 smoke：
  - 新增 `scripts/run_s3c2_gate_evidence_ablation.py`
  - 新增 `scripts/hpc/s3c2_gate_evidence_ablation.slurm`
  - 新增 `project_docs/S3C2_GATE_EVIDENCE_ABLATION.md`
  - 作用：把 S3-C1/S3-C1b 的 path plausibility 转成 gate-layer evidence，离线模拟 gate evidence variants；不覆盖 score/gate/final/incidents。
  - 已增强 fixed S2 输出口径：
    - `s3c2_event_label_delta.csv`
    - `s3c2_incident_priority_delta.csv`
    - `s3c2_p1_p2_total_burden.csv`
    - `s3c2_review_subtype_distribution.csv`
    - 所有 label/priority 变化均按 simulated 字段输出。
    - P1->P2 transfer 单独统计，不算 workload reduction。
  - 本地 `s1a_expanded_v02_pilot_60m_april16` 20 万行 smoke 通过：
    - loaded_rows `200000`
    - recommended_variant `variant_medium_gate_only`
    - gate_evidence_rows `122956`
    - final_label_changed_rows `0`
    - pattern_A_gate_evidence_rows `122956`
    - pattern_B_label_changed_rows `0`
    - S3-C1b full output 缺失与 S1A incident membership 缺失均只 warning。
  - fixed S2 full 已完成并拉回：
    - input/loaded rows `10236431 / 10236431`
    - status `completed`，warnings `0`
    - recommended_variant `variant_medium_gate_only`
    - final labels 不变：high `639548 -> 639548`，needs `4839755 -> 4839755`，low `4757128 -> 4757128`
    - final_label_changed_rows `0`
    - gate_evidence_rows `6885990`
    - pattern_A_rows `7440623`
    - pattern_A_gate_evidence_rows `6885990`
    - pattern_A_control_rate `0.9254587955874125`
    - pattern_B_rows `659862`
    - pattern_B_label_changed_rows `0`
    - recommended variant 下 pattern_B_gate_evidence_rows `0`
    - P1/P2 tickets `55083 -> 55083`，members `4426436 -> 4426436`
    - P1->P2 transfer tickets `0`
    - P1/P2 affected rows `3510753`，touched incidents `32469`
    - known-event inventory 可读但 matched rows `0`，不能据此声称无 regression 风险。
  - 当前判断：S3-C2 fixed S2 证明 gate evidence 通道稳定，可大规模标记 pattern_A 并保护 pattern_B；但它不改变 final/P1/P2，因此不能作为 workload reduction 结果。下一步应进入 S3-D incident-level verification queue/schema，或并行做 S3-C3 route-leak triplet legality。
- S3-D incident-level verification queue/schema 已完成：
  - 新增 `scripts/run_s3d_verification_queue_schema.py`
  - 新增 `project_docs/S3D_VERIFICATION_QUEUE_SCHEMA.md`
  - 新增 `project_docs/REALTIME_UPGRADE_ROADMAP.md`
  - 作用：基于 S3-A/S3-A2/S3-B/S3-C2，把 incident tickets 重排为 verification queue；不做外部验证，不覆盖 final/priority，不把 queue 当真实标签。
  - evidence 口径：
    - 本地没有完整 S2 `scores/gating/final/events/candidates` parquet。
    - S3-D 使用 `incident_membership.reason_signature` 计算 incident-member pattern_A/pattern_B evidence。
    - `pattern_A_gate_evidence_count` 是 incident-member fallback，不应描述为 full S3-C2 event-level evidence。
  - fixed S2 full 结果：
    - total incidents `217165`
    - calibrated P1/P2/P3 `41885 / 13198 / 162082`
    - queue_count：
      - `low_priority_background=157351`
      - `patternB_path_abnormal_verification=49852`
      - `gate_evidence_weak_case=7192`
      - `high_confidence_candidate=1216`
      - `background_like_review=1190`
      - `route_leak_like_review=364`
    - P1/P2 in `gate_evidence_weak_case`：`7192`
    - P1/P2 in `high_confidence_candidate`：`1216`
    - pattern_A touched incidents：`174046`
    - pattern_B verification incidents：`49852`
    - top-K emitted rows：`250`
  - 当前判断：S3-D 建立了验证队列/schema，但不降低 final/P1/P2，也不是验证完成。下一步应做 S3-D2 external evidence attachment，或并行做 S3-C3 route-leak triplet legality。
- S3-D2 external evidence attachment 已完成：
  - 新增 `scripts/run_s3d2_external_evidence_attachment.py`
  - 新增 `project_docs/S3D2_EXTERNAL_EVIDENCE_ATTACHMENT.md`
  - 更新 `project_docs/REALTIME_UPGRADE_ROADMAP.md`
  - 作用：给 S3-D verification queue 挂载 RPKI、AS relationship/path relation、history/collector、known-event、composite evidence 字段；不做真假判定，不改主链 priority。
  - fixed S2 full 结果：
    - total incidents `217165`
    - evidence buckets：weak `201329`，medium `15836`，strong `0`
    - RPKI status：`unavailable=217165`
    - path relation evidence：`weak_stale_snapshot=217165`
    - time-aligned known-event matches `0`
    - out-of-window known-event overlaps `5167`
    - high_confidence_candidate_with_strong_evidence `0`
    - gate_weak_case_with_strong_evidence `0`
    - gate_weak_case_evidence_insufficient `7182`
    - patternB_with_path_evidence `49852`
    - route_leak_relation_pending `364`
    - background_like_evidence_supported `1189`
    - external_evidence_unavailable_count `217165`
  - 关键约束：
    - 没有 2024 historical RPKI cache，因此 RPKI 不能作为强证据。
    - 可用 CAIDA AS-rel 文件是 `20170701.as-rel2.txt`，对 2024 run 只作 diagnostic，不作 strong evidence。
    - known-event inventory 与 2024 run 无 time-aligned match；out-of-window overlap 不等于命中。
  - 当前判断：S3-D2 成功打通 evidence attachment schema，但暴露了外部证据缺口。下一步应补 2024 RPKI/IRR/AS-rel cache 后复跑，或先做 S3-C3 route-leak triplet legality。
- S3-D2B evidence alignment 已完成：
  - 新增 `scripts/run_s3d2b_evidence_alignment.py`
  - 新增 `project_docs/S3D2B_EVIDENCE_ALIGNMENT.md`
  - 作用：把 S3-D2 暴露出的证据缺口转成可执行的 cache request、prefix-origin lookup targets、path relation targets 与 S3-D2 rerun manifest；不下载大规模外部数据，不做在线批量请求，不改主链输出。
  - fixed S2 full 结果：
    - inspected incidents `217165`
    - valid prefix-origin lookup targets `40665`
    - path relation targets `168889`
    - local evidence sources found `5`
    - source alignment：`as_relationship:stale=1`，`known_event_inventory:undated=4`
    - RPKI aligned cache available `false`
    - AS relationship aligned snapshot available `false`
    - known-event time-aligned overlaps `0`
    - known-event out-of-window asset overlaps `6`
    - S3-D2 aligned rerun ready `false`
  - 关键约束：
    - 不能用 current online RPKI 状态替代 2024 historical RPKI evidence。
    - `20170701.as-rel2.txt` 比 run start 早 `2481` 天，仍只能作为 stale diagnostic。
    - known-event out-of-window asset overlap 只说明库存里有历史相似资产，不说明当前 2024 事件命中。
  - 当前判断：证据对齐已经从“缺什么不清楚”推进到“缺什么、查什么、如何复跑”明确。下一步要么取得 `2024-04-16` RPKI/ROA cache 与 2024-near AS-rel 后复跑 S3-D2，要么先做 S3-C3 route-leak triplet legality。
- Phase R problem reframing & verifier redesign 已启动：
  - 新增 `project_docs/PHASE_R_PROBLEM_REFRAMING.md`
  - 新增 `project_docs/VERIFIER_REDESIGN_ROADMAP.md`
  - 新增 `project_docs/LEARNING_LAYER_POSITIONING.md`
  - 新增 `project_docs/PAPER_PROBLEM_STATEMENT.md`
  - 核心重定位：public monitor output 降级为 candidate trigger；detector score / high-needs-low / P1-P2-P3 降级为 evidence / legacy priority；最终目标变为 multi-evidence verifier 输出 verdict、confidence、provenance、abstain。
  - 旧 S3-A~S3-D2B 不被解释为失败，而是 Phase R verifier-centric roadmap 的 historical groundwork。
  - 下一步默认从 Phase R-1 verifier state machine design 和 Phase R-2 legality-first verifier 开始，不再继续做纯 detector score 优化。
- Phase R-1 verifier state machine design 已完成：
  - 新增 `project_docs/R1_VERIFIER_STATE_MACHINE.md`
  - 新增 `project_docs/R1_EVIDENCE_TYPES_AND_VERDICTS.md`
  - 作用：冻结 verifier evidence states、verdict space、confidence caps、hard safety rules、learning-layer boundary 与 S3 legacy output 映射。
  - evidence states：`aligned_strong`、`aligned_medium`、`aligned_weak`、`stale_diagnostic`、`unavailable`、`conflicting`、`monitor_only`、`poisoning_susceptible`、`external_confirmed_pending`、`not_applicable`。
  - verdicts：`strongly_supported_suspicious`、`evidence_supported_suspicious`、`evidence_conflict`、`evidence_insufficient`、`external_evidence_unavailable`、`background_like_but_unconfirmed`、`stale_evidence_only`、`abstain`。
  - 核心约束：RPKI invalid 不是 confirmed attack；RPKI valid 不是 confirmed benign；monitor-only 不得产生 strongly supported verdict；stale/unavailable/conflicting evidence 必须显式保留；P3/low/background 不是 confirmed normal；learning layer 不能覆盖 verifier hard rules。
  - 本阶段未写实验代码，未运行实验，未修改任何主链产物。
- Phase R-2A legality-first verifier scaffold 已完成 50k smoke：
  - 新增 `scripts/run_r2a_legality_first_verifier_scaffold.py`
  - 新增 `project_docs/R2A_LEGALITY_FIRST_VERIFIER_SCAFFOLD.md`
  - smoke 输出目录：`outputs/r2a_legality_first_verifier_smoke_v01/`
  - 作用：把 S3-D legacy incident queue 转成 legality/evidence-aware verifier table，输出 R-1 evidence states、verdict、confidence cap、abstain/conflict reason、learning eligibility 与 provenance JSON。
  - smoke 口径：fixed run `s2a_expanded_v01_pilot_6h_april16`，`sample_rows=50000`，只读 S3-D/S3-D2/incident artifacts，不覆盖任何旧产物。
  - smoke 结果：processed `50000` incidents；`strongly_supported_suspicious=0`；`evidence_supported_suspicious=0`；`stale_evidence_only=43335`；`external_evidence_unavailable=3762`；`background_like_but_unconfirmed=1485`；`evidence_insufficient=1418`。
  - evidence 状态：RPKI `unavailable=50000`；path legality `stale_diagnostic=44632`、`not_applicable=5368`；stale evidence rows `44807`；unavailable evidence rows `50000`。
  - 关键解释：R-2A scaffold 成功生成 verifier table，但没有完成真实攻击判定；缺少 aligned 2024 RPKI/ASPA/AS-rel/IRR cache 时，输出 stale/unavailable/insufficient 是正确行为。
- Phase R-2B-0 evidence readiness audit 已完成：
  - 新增 `scripts/run_r2b0_evidence_readiness_audit.py`
  - 新增 `project_docs/R2B0_EVIDENCE_READINESS_AUDIT.md`
  - full 输出目录：`outputs/r2b0_evidence_readiness_audit_v01/`
  - 口径：fixed run `s2a_expanded_v01_pilot_6h_april16`，只读 S3-D queue、incident tickets、incident membership schema、R-2A/S3-D2 context 与本地 evidence cache inventory。
  - 结果：processed `217165` incidents；prefix-origin complete `217162`；time window complete `217165`；path-key complete `216922`；triplet-key complete `205067`。
  - cache readiness：RPKI/VRP `missing`，IRR `missing`，ASPA `missing`，PeeringDB `missing`，known-event `present_unverified_schema`，AS relationship `ready_stale` because only `20170701.as-rel2.txt` exists。
  - 关键解释：incident lookup keys 基本已经足够，当前主阻塞是 aligned external cache；下一步优先 P0b historical VRP/RPKI cache materialization，而不是修旧 detector score。
- Phase R-2B-P0b historical VRP/RPKI cache materialization 已完成：
  - 新增 `scripts/run_r2b_p0b_materialize_vrp_cache.py`
  - 新增 `project_docs/R2B_P0B_HISTORICAL_VRP_CACHE.md`
  - full 输出目录：`outputs/r2b_p0b_vrp_materialization_v01/`
  - 本地 evidence cache：`data/evidence/rpki/vrp_2024-04-16.parquet`、`data/evidence/rpki/vrp_2024-04-16.csv`、`data/evidence/rpki/vrp_2024-04-16.metadata.json`
  - source：RIPE NCC RPKI repository archive，5 个 TAL (`afrinic`、`apnic`、`arin`、`lacnic`、`ripencc`) 的 `2024/04/16/roas.csv.xz`。
  - 结果：VRP cache records `530187`；lookup eligible targets `217162`；RPKI status `valid=122280`、`invalid_asn=397`、`invalid_length=283`、`unknown=94202`、`unavailable=0`。
  - 关键解释：RPKI unavailable blocker 已解除，但 RPKI status 仍只是 origin authorization evidence；`valid` 不是 benign，`invalid` 不是 confirmed attack，`unknown` 不是 normal。本轮没有生成或修改 verifier verdict。
- Phase R-2B VRP-aware verifier smoke 已完成：
  - 新增 `scripts/run_r2b_vrp_aware_verifier_smoke.py`
  - 新增 `project_docs/R2B_VRP_AWARE_VERIFIER_SMOKE.md`
  - 新增 `project_docs/CCFA_TARGET_LINE_AND_EXPERIMENT_GUARDRAILS.md`
  - full 输出目录：`outputs/r2b_vrp_aware_verifier_smoke_v01/`
  - 口径：固定 run `s2a_expanded_v01_pilot_6h_april16`，只接入 R-2B-P0b aligned VRP evidence，不下载新外部证据，不改 R-1 verdict set，不覆盖旧 S3/R-2A/R-2B-0/R-2B-P0b 输出。
  - dominant pair RPKI：`valid=122280`、`unknown=94202`、`invalid_asn=397`、`invalid_length=283`、`unavailable=3`。
  - member/component RPKI：`valid=3048894`、`unknown=2075964`、`unavailable=348708`、`invalid_length=3074`、`invalid_asn=2663`。
  - component purity：`pure_dominant=114237`、`insufficient_component_signal=94666`、`highly_mixed_should_split=4689`、`mostly_dominant=3023`、`mixed_but_core_suspicious=479`、`mixed_conflicting=71`。
  - verdict：`background_like_but_unconfirmed=156971`、`evidence_insufficient=55366`、`abstain=4684`、`evidence_conflict=86`、`evidence_supported_suspicious=55`、`external_evidence_unavailable=3`、`strongly_supported_suspicious=0`。
  - hard safety violations `0`；legacy P1/P2 `55083`，evidence/conflict/abstain candidate review count `4825`，unsupported alert reduction proxy `0.912405`。
  - 关键解释：R-2B 是 first evidence-backed verifier smoke，不是真假判定；混杂 incident 显式进入 conflict/abstain/insufficient，不被粗暴整体判 suspicious 或 background。
- Phase R-2B-OPS operational burden and realtime cache audit 已完成：
  - 新增 `scripts/run_r2b_ops_realtime_burden_audit.py`
  - 新增 `project_docs/R2B_OPS_REALTIME_BURDEN_AUDIT.md`
  - full 输出目录：`outputs/r2b_ops_realtime_burden_audit_v01/`
  - 口径：固定 run `s2a_expanded_v01_pilot_6h_april16`，只读 R-2B verifier table 和 VRP metadata；不下载新证据、不修改 verifier verdict、不训练 learning layer、不做 R-2C/R-3。
  - 日级线性外推：`evidence_supported_suspicious=220`、`evidence_conflict=344`、`abstain=18736`、`evidence_insufficient=221464`、`background_like_but_unconfirmed=627884`、`mixed_should_split=18756`、`mixed_but_core_suspicious=1916`。
  - Top-K smoke：Top-50 evidence-supported density `1.0`，Top-100 `0.53`，Top-500 `0.11`；相对 legacy P1/P2 burden reduction proxy 分别为 `0.9991`、`0.9982`、`0.9909`。
  - 关键解释：真实部署中 online path 不做远程 evidence 下载，只查本地 versioned cache；cache stale/unavailable 不阻塞 monitor trigger，但会降级为 stale/insufficient/unavailable/abstain/conflict。
- Phase R-2C-0 path evidence readiness audit 已完成：
  - 新增 `scripts/run_r2c0_path_evidence_readiness_audit.py`
  - 新增 `project_docs/R2C0_PATH_EVIDENCE_READINESS_AUDIT.md`
  - full 输出目录：`outputs/r2c0_path_evidence_readiness_audit_v01/`
  - 口径：固定 run `s2a_expanded_v01_pilot_6h_april16`，只读 incident tickets/membership、R-2B verifier table、R-2B-0 path targets 和本地 evidence inventory；不下载新证据、不修改 verifier verdict、不训练 learning layer。
  - 结果：checked `217165` incidents；complete path-key `217162` (`0.999986`)；triplet-capable `217162` (`0.999986`)；AS-pair targets `216922`；triplet targets `205067`；full-path targets `217162`。
  - cache readiness：2017 CAIDA AS-rel `ready_stale`/`stale_diagnostic only`；2024-near AS-rel `missing`；ASPA `missing`；BGP Roles/OTC `missing`；PeeringDB `missing`；known-event path context `present_unverified_schema`。
  - 关键解释：path lookup keys 基本不阻塞，阻塞点是 aligned path evidence cache；下一步应做 R-2C-P0b 2024-near AS relationship cache materialization，而不是直接写 route-leak verifier。
- Phase R-2C-P0b 2024-near CAIDA AS relationship cache materialization 已完成：
  - 新增 `scripts/run_r2c_p0b_materialize_asrel_cache.py`
  - 新增 `project_docs/R2C_P0B_2024_ASREL_CACHE.md`
  - full 输出目录：`outputs/r2c_p0b_asrel_materialization_v01/`
  - 本地 evidence cache：`data/evidence/as_relationships/as_rel_2024-04-01.parquet`、`data/evidence/as_relationships/as_rel_2024-04-01.csv`、`data/evidence/as_relationships/as_rel_2024-04-01.metadata.json`
  - source：CAIDA AS Relationships serial-2 `https://data.caida.org/datasets/as-relationships/serial-2/20240401.as-rel2.txt.bz2`；raw file `data/caida/as-relationships/serial-2/20240401.as-rel2.txt.bz2`
  - 结果：snapshot `2024-04-01`，run date `2024-04-16`，alignment delta `15` days，future snapshot `false`，usable for R-2C `true`，raw AS-rel records `571330`，directed lookup records `1142660`，parse warnings `0`。
  - AS-pair lookup smoke：target rows `216922`，unique pairs `61997`，matched unique pairs `56971`，unmatched `5026`，match rate `0.918932`；rel type distribution `p2c_or_c2p_raw=33144`、`p2p=23827`、`unknown=5026`。
  - 关键解释：AS relationship 是 inferred evidence，不是 route-leak truth；本轮没有生成 route-leak verdict，没有修改 R-2B verifier verdict，learning 仍不能训练。

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
9. S3-B 已完成；不要重复做泛化噪声审计，除非 S3-C 后检测逻辑发生变化。
10. S3-C1b fixed S2 full 已完成；不要重复提交 S3-C1b。
11. S3-C2 fixed S2 full 已完成；不要把它解读为 P1/P2 workload reduction，它是 gate evidence / verification input。
12. S3-D verification queue/schema 已完成；不要把 queue 当真实标签，不要声称 external verification 完成。
13. S3-D2 external evidence attachment 已完成；不要把 `verification_status_candidate` 当真假标签。
14. S3-D2B evidence alignment 已完成；不要把对齐清单当作外部验证结果，它只是 cache request / lookup target / rerun manifest。
15. Phase R 已启动；旧 detector-centric 线性推进进入 strategic pause。
16. Phase R-1 verifier state machine design 已完成。
17. Phase R-2A legality-first verifier scaffold 50k smoke 已完成；不要把 R-2A verdict 当真实攻击判定，也不要把 smoke 输出当 full run。
18. R-2B-0 evidence readiness audit 已完成：fixed S2 `217165` incidents 中 `217162` 有 prefix-origin complete key，`217165` 有 time window，`216922` 有 complete path key，`205067` 有 complete triplet key；本地 RPKI/VRP、IRR、ASPA、PeeringDB cache 当时缺失，known-event inventory 仅 `present_unverified_schema`，2017 CAIDA AS-rel 只能是 `stale_diagnostic`。
19. R-2B-P0b historical VRP/RPKI cache materialization 已完成：`2024-04-16` aligned VRP `530187` 条；`217162` prefix-origin targets 完成离线 RPKI lookup；status 为 `valid=122280`、`invalid_asn=397`、`invalid_length=283`、`unknown=94202`、`unavailable=0`；没有 hard safety violation，没有修改 verifier verdict。
20. R-2B VRP-aware verifier smoke 已完成：固定 S2 `217165` incidents 上输出 component-aware verifier table；`evidence_supported_suspicious=55`、`evidence_conflict=86`、`abstain=4684`、`strongly_supported_suspicious=0`、hard safety violations `0`；should-split incidents `4689`。
21. R-2B-OPS operational burden and realtime cache audit 已完成：Top-K review 是控制人工负担的默认口径；online path 不允许每个 incident 远程查证据，必须走本地 evidence cache；abstain/insufficient/background-like 不全量交给人工。
22. R-2C-0 path evidence readiness audit 已完成：path/triplet lookup keys 基本 ready，但 2024-near AS-rel/ASPA/Roles evidence cache 缺失；2017 CAIDA AS-rel 只能 stale diagnostic。
23. R-2C-P0b 2024-near CAIDA AS relationship cache materialization 已完成：`2024-04-01` snapshot 可用，AS-pair lookup smoke match rate `0.918932`；AS-rel 仍只是 inferred path evidence，不是 route-leak truth。
24. 当前 CCF-A target line 已冻结：主目标为 CCF-A/top-tier networking or security venue，SCI Q2 仅 fallback；最终系统不是普通 BGP anomaly detector，而是 poisoning-robust, evidence-constrained, component-aware semantic triage。
25. R-2D-0 communities / NO_EXPORT field availability audit 已完成：raw updates 保留 `communities`，但 event/incidents/verifier 层未保留，incident join 不 ready；下一步默认不是继续优化 raw detector score，而是先做 community-retention pipeline repair、复跑 R-2D-0，再决定是否进入 R-2D-1 community-aware stealth evidence branch，并同步推进 R-3 poisoning benchmark 与 L1 component-aware semantic learner design。
26. S3-D3/S4 形成 high-confidence set 后，再考虑正式训练 incident-level learning ranker / evidence calibrator。
27. 24h expanded 应作为 `S2-D 24h with incidents/verifier`，不要回到纯 event-level 评估。
28. 扩展稳定后，再进入 stealth / NO_EXPORT / 2024 隐蔽狩猎所需的特征扩展与数据准备。
29. 不回头为历史事件口径反复折腾；历史阶段默认视为已收口资产。

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
