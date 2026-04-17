# BGP-Platform 实验背景速览 v1（供新对话快速接入）

更新时间：2026-04-08  
适用工作树：`D:\study\paper\worktrees\bgp-platform-exp-mainline`  
固定分支：`codex/bgp-exp-mainline`

## 1) 一屏总览（TL;DR）
- 项目目标：构建并验证一个面向 forged-origin 弱信号场景的分层检测系统，强调 partial observability 条件下的可解释决策，而非单阈值二分类。
- 主链固定：事件层 -> 历史基线层 -> 候选层 -> 评分层 -> 门控层 -> 增强层 -> 最终输出层。
- 当前基线 run：`20260313T032554_4f9be28c`（collectors=`route-views.sg,rrc00`，窗口 `2017-07-07 00:15:00~00:20:00`）。
- 主结论（已收口）：
  - candidate 负责前置压缩，真实有效。
  - gate 对 high 纯度控制独立且关键。
  - augment 存在独立作用但规模较小，偏 uncertain 子集再分流。
  - collector 可见度下降时系统以“丢失/降级 high”为主，未出现高优先误抬升。
- 当前阶段已进入 E8（案例与外部验证）：形成一批 validated suspicious（以 strongly_suspicious 为主），并完成小规模公开已知事件背书测试。

## 2) 仓库总地图（按职责）
- 主链核心脚本：`scripts/`
  - `build_event_units.py`
  - `build_historical_baseline.py`
  - `build_weak_candidates.py`
  - `score_weak_candidates.py`
  - `gate_scored_candidates.py`
  - `augment_uncertain_candidates.py`
  - `build_final_alerts.py`
- 数据采集/标注入口：
  - `scripts/run.py`（多 collector + chunk + marker + CAIDA 标注统一入口）
  - `scripts/03_collect_updates.py`
  - `scripts/04_annotate_caida_rel.py`
- 实验执行脚本（E6~E8）：
  - `scripts/run_e6b1_nogate_ablation.py`
  - `scripts/run_e6b2_noaugment_ablation.py`
  - `scripts/run_e6b3_joint_ablation.py`
  - `scripts/run_e7a_visibility_ablation.py`
  - `scripts/run_e7b_collector_structure.py`
  - `scripts/run_e8a_case_pool.py`
  - `scripts/run_e8b_case_external_validation.py`
  - `scripts/run_e8c_known_events_test.py`
- 结果产物目录：`outputs/`
  - `e6b1_nogate_ablation_v02`
  - `e6b2_noaugment_ablation_v01`
  - `e6b3_joint_ablation_v01`
  - `e7a_visibility_ablation_v01`
  - `e7b_collector_structure_v01`
  - `e8a_case_pool_v01`
  - `e8b_case_external_validation_v01`
  - `e8c_known_events_test_v01`
- 交接目录：`runs/prism_handoffs/`

## 3) 主链 I/O 速记（新对话高频要用）
1. 事件层 `build_event_units.py`
- 输入：`data/runs/<run_id>/collector=*/date=*/updates*(__rel).parquet`
- 输出：`events/event_units.parquet`

2. 历史基线层 `build_historical_baseline.py`
- 输入：`events/event_units.parquet`
- 输出：`baseline/baseline_prefix*.parquet` + `baseline/baseline_path.parquet`

3. 候选层 `build_weak_candidates.py`
- 输入：`events` + `baseline`
- 输出：`candidates/candidate_events.parquet`

4. 评分层 `score_weak_candidates.py`
- 输入：`candidate_events.parquet` + `baseline`
- 输出：`scores/scored_candidates.parquet`

5. 门控层 `gate_scored_candidates.py`
- 输入：`scored_candidates.parquet`
- 输出：`gating/gated_candidates.parquet`

6. 增强层 `augment_uncertain_candidates.py`
- 输入：`gated_candidates.parquet`（uncertain 子集）+ `events/baseline`
- 输出：`augmentation/augmented_candidates.parquet`

7. 最终层 `build_final_alerts.py`
- 输入：`scores + gating + augmentation`
- 输出：`final/final_alerts.parquet` + `final/final_report.json`

最终标签固定：
- `high_priority_alert`
- `needs_review`
- `low_priority_or_background`

## 4) 已完成实验时间线与关键数字

### E6-A：candidate 审计（已通过）
来源：`论文/实验执行_E6A_candidate审计_v01/`
- `min_weak_rules` 变化：1/2/3/10 时，candidate 分别为 1680/1106/1098/1098。
- 但 final high 恒定为 24（gating=22, augmentation=2）。
- 结论：candidate 真实有效（前置压缩），E5 异常来自实验口径污染而非实现失效。

### E6-B-1：no-gate 消融（已通过）
来源：`outputs/e6b1_nogate_ablation_v02/`
- default：high=24, needs=625, low=457。
- no-gate：high=265, needs=385, low=456。
- 新增 high=241，全部来自 default 的 needs。
- high 质量退化：certainty_mean 66.76 -> 39.02；conflict_mean 0.00 -> 23.85；missing_rate 0.00 -> 0.5283。
- 结论：`gate=独立有效`（核心作用是控纯度、抑制低质量上浮）。

### E6-B-2：no-augment 消融（已完成）
来源：`outputs/e6b2_noaugment_ablation_v01/`
- no-augment：high=22, needs=645, low=439。
- default augment 输入 uncertain=645；promoted=2，retained=625，demoted=18。
- 去 augment 后：2 条 default high 回落 needs；18 条 default low 回流 needs。
- 结论：augment 有独立作用但规模小，偏 uncertain 子集再分流。标签：`augment=作用有限`。

### E6-B-3：no-gate + no-augment 联合消融（已完成）
来源：`outputs/e6b3_joint_ablation_v01/`
- no-gate-no-augment：high=266, needs=402, low=438。
- 相比 no-gate 仅多 1 条 high（265 -> 266）。
- 相比 default 新增 high=242（241 来自 default needs，1 来自 default low）。
- 结论：gate 决定性更强；augment 主要在 gate 之后做边界微调。标签：`joint_ablation=支持分层分工`。

### E7-A：可见度消融（已通过）
来源：`outputs/e7a_visibility_ablation_v01/`
- full(2 collectors)：events=4808, candidate=1106, high=24。
- route-views.sg_only：events=2005, candidate=518, high=4。
- rrc00_only：events=2836, candidate=136, high=1。
- reduced visibility 下未出现 reduced-only high（误抬升接近 0），主要是 full-high 丢失/降级。
- 结论：符合 partial observability 下“可解释的渐进退化”。标签：`visibility_ablation=支持主线`。

### E7-B：双 collector 结构差异（已通过）
来源：`outputs/e7b_collector_structure_v01/`
- A/B 真实身份：`route-views.sg_only` vs `rrc00_only`。
- candidate 直接交集：33（Jaccard=0.053）。
- needs 直接交集：33（Jaccard=0.117）。
- high 直接交集：0（Jaccard=0.0）。
- full-high(24)去向：
  - route-views.sg_only：retained 4 / needs 8 / low 6 / missing 6
  - rrc00_only：retained 1 / needs 2 / low 0 / missing 21
- 结论：存在显著视角不对称，且 high 层最敏感。标签：`collector_structure=存在显著差异`。

### E8-A：案例池与模板固化（已完成）
来源：`outputs/e8a_case_pool_v01/`
- 正式池 A/B/C 各 3 条，共 9 条。
- D 类 stealth 候补池 3 条。
- 共 12 条，且模板已固化（含 External Validation Hook）。
- 标签：`case_pool=已可进入正式E8`。

### E8-B：12 条事件外部验证挂载（已完成）
来源：`outputs/e8b_case_external_validation_v01/`
- validated_event_count=12。
- 分级：strongly_suspicious=8，needs_external_review=4。
- topology_violation：no=7，uncertain=5（无强行过判）。
- communities 字段可用：yes=9，no=3。
- 标签：`external_validation=形成初步validated suspicious set`。

### E8-C：公开已知事件小规模测试（已完成）
来源：`outputs/e8c_known_events_test_v01/`
- 候选公开事件 4，入选测试 3，命中 1（命中为 high）。
- 命中事件：Rostelecom AS12389（origin_match=yes, attacker_as_match=yes, match_strength=strong）。
- 未命中 2 条原因：`no_visibility`、`weak_signal_not_enough`。
- 结论：系统对公开已知事件具备可解释响应能力，但受可见度与信号强度约束明显。

### E9-A：公开已知事件扩展 collector 复测（阶段性完成）
来源：`outputs/e9a_known_event_visibility_v02/`
- baseline（2 collectors）命中：1/3。
- expanded（8 collectors）响应：3/3，其中 `high=2`、`needs_review=1`。
- Google-Verizon：`no_visibility -> needs_review`。
- Amazon Route53/MEW：`weak_signal_not_enough -> high`。
- 结论：VP/collector 太少是已知事件漏检的重要原因，但 route-leak 风格事件仍更容易稳定落在 review 层。

### E9-B：Google-Verizon route-leak review 审计（已完成）
来源：`outputs/e9b_route_leak_review_audit_v01/`
- target_prefix=`114.154.133.0/24`
- target_event_count=`2`
- target_final_label_counts=`needs_review=2`
- 结论：该事件当前不是 visibility miss，而是稳定的 review 层事件。

### E9-C：known-event benchmark 扩容清单与 next-batch 复测（已完成）
来源：`outputs/e9c_known_event_visibility_v01/`、`outputs/e9c_known_event_inventory_v02/`
- manifest_events=7
- core_tested=3
- next_batch=2
- backup=2
- baseline_tested=5，expanded_tested=5
- baseline：high=2 / needs=0
- expanded：high=3 / needs=1
- MainOne / Google route leak：baseline / expanded 均 `no_hit:no_visibility`
- D-Vois Amazon more-specific hijack：baseline / expanded 均命中 `high`
- 结论：后续扩已知事件池时，已不需要继续改脚本常量；next_batch 已完成，后续应进入 backup 池复测与 MainOne 锚点专项审计。

### E9-D：MainOne route-leak 锚点缺口审计（已完成）
来源：`outputs/e9d_route_leak_gap_audit_v01/`
- exact target prefix：`8.8.8.0/24`
- ordered leak-chain：`20485 -> 4809 -> 37282 -> 15169`
- exact-prefix 在 baseline / expanded 中都未出现：event_rows=`0 / 0`
- 但 leak-chain 原始样本大量可见：raw_chain_rows=`1193 -> 4213`
- leak-chain Google-origin 前缀：`203 -> 203`
- 进入 final 的 leak-chain 样本：`588 -> 1758`
- label 分布：baseline `needs=420 / low=168`；expanded `needs=1718 / low=40`
- 结论：MainOne 当前不是“系统看不见 route leak”，而是“单前缀锚点选窄”；扩展 collectors 的真实作用是显著增强 route-leak `needs_review` 覆盖。

### S0-A：已知事件双轨制评估口径升级（已完成）
来源：`outputs/s0_dual_track_eval_v01/`
- 新增 manifest：`data/known_events/known_event_candidates_v03.json`
- 规则：
  - exact_prefix：命中并进入 `high` 才算 `Hit Expected`
  - ordered_leak_chain：impact_radius `> 10` 且 `(high+needs)/total >= 0.8` 才算 `Hit Expected`
- evaluated_rows=`14`，hit_expected_rows=`6`，miss_rows=`4`，not_run_rows=`4`
- MainOne：baseline=`Miss`，expanded=`Hit Expected`
- MainOne expanded：primary_landing_zone=`Needs`，impact_radius=`195`，retained_ratio=`0.9772`
- 结论：route-leak 的成功标准应改成“稳定落在 review 隔离区”，而不是强行要求进入 `high_priority_alert`。

### E9-E：Google-Verizon chain-anchor 审计（已完成）
来源：`outputs/e9e_google_verizon_chain_audit_v01/`
- exact target prefix：`114.154.133.0/24`
- ordered leak-chain：`286 -> 701 -> 15169 -> 4713`
- anchor_origin_as：`4713`
- baseline：chain raw Google-origin prefixes=`5199`，final Google-origin prefixes=`0`
- expanded：chain raw Google-origin prefixes=`23411`，final Google-origin prefixes=`9407`
- expanded label 分布：`needs=17438 / low=187 / high=0`
- retained_ratio=`0.9894`
- 结论：Google-Verizon 应迁到 route-leak 的 ordered leak-chain 口径；在 expanded collectors 下是强 `needs_review` 命中，但 baseline 2-collector 仍不足以保留到 final。

### S0-B：双轨制评估 v02（已完成）
来源：`outputs/s0_dual_track_eval_v02/`
- 新增 manifest：`data/known_events/known_event_candidates_v04.json`
- 给 route-leak 锚点新增可选字段：`anchor_origin_as`
- evaluated_rows=`14`
- hit_expected_rows：`6 -> 7`
- miss_rows：`4 -> 3`
- ordered_leak_chain_hits：`1 -> 2`
- Google-Verizon：baseline=`Miss`，expanded=`Hit Expected`
- Google-Verizon expanded：primary_landing_zone=`Needs`，impact_radius=`9407`，retained_ratio=`0.9894`
- 结论：在 expanded collectors 口径下，三个 core 已知事件现在都已命中各自的预期落点；其中 route-leak 事件应以 `needs_review` 稳定隔离为成功标准。

### E9-F：known-event inventory v03 同步（已完成）
来源：`outputs/e9c_known_event_inventory_v03/`
- inventory 默认口径已切到：`manifest_v04 + s0_dual_track_eval_v02`
- manifest_events=`7`
- baseline_tested=`5`，expanded_tested=`5`
- baseline_hit_expected=`2`
- expanded_hit_expected=`5`
- baseline：`high=2 / needs=0`
- expanded：`high=3 / needs=2`
- Google-Verizon：`baseline=miss`，`expanded=needs`
- MainOne：`baseline=miss:needs`，`expanded=needs`
- 结论：known-event inventory 已与当前双轨制阅卷标准完全对齐，后续 backup 池复测应直接复用该库存，不再回到旧的单前缀口径。

### E9-G：backup 池首轮复测（已完成）
来源：`outputs/e9f_backup_visibility_v01/`
- 测试事件：`Indosat 2014`、`Pakistan Telecom / YouTube 2008`
- baseline hit events=`0`
- expanded hit events=`1`
- baseline no_visibility=`1`
- expanded no_visibility=`1`
- baseline weak_signal_not_enough=`1`
- expanded weak_signal_not_enough=`0`
- `Indosat`：baseline=`weak_signal_not_enough`，expanded=`needs_review`，且 `origin_match=yes`、`attacker_as_match=yes`
- `Pakistan / YouTube`：baseline / expanded 均=`no_visibility`
- 工程补丁：`04_annotate_caida_rel.py` 已修复为空 parquet 直接跳过，避免 old-window 数据在 CAIDA 标注阶段崩溃
- 结论：`Indosat` 应按 route-leak 风格样本解释，其 expanded 落在 `needs_review` 属于双轨制下的正确隔离命中；`Pakistan` 的原始 `no_visibility` 结论需要扩窗审计再校正。

### E9-H：known-event inventory v04（已完成）
来源：`outputs/e9c_known_event_inventory_v04/`
- baseline_tested=`7`
- expanded_tested=`7`
- baseline_hit_expected=`2`
- expanded_hit_expected=`6`
- expanded 状态分布：`high=3 / needs=3 / no_hit:no_visibility=1`
- backup 子集：
  - `Indosat`：baseline=`no_hit:weak_signal_not_enough`，expanded=`needs`（按 route-leak 风格样本解释）
  - `Pakistan`：baseline=`no_hit:no_visibility`，expanded=`no_hit:no_visibility`
- 结论：known-event inventory 已覆盖 core / next_batch / backup 全部事件，后续可直接基于 v04 清单继续做 backup 补救或 modern 扩容。

### E9-I：Pakistan / YouTube 扩大时间窗审计（已完成）
来源：`outputs/e9i_pakistan_time_window_audit_v01/`
- 审计窗口：`2008-02-24 16:00:00 ~ 20:20:00 UTC`（相对原始 20 分钟窗前后各扩 120 分钟）
- baseline_status=`visible`，expanded_status=`visible`
- baseline_visible_rows=`35`
- expanded_visible_rows=`201`
- baseline_visible_collectors=`rrc00`
- expanded_visible_collectors_count=`7`
- first_seen_utc：baseline=`2008-02-24 18:47:57 UTC`，expanded=`2008-02-24 18:47:53 UTC`
- 结论：`Pakistan / YouTube` 不是绝对不可见，而是原始回放窗口偏窄；按止损线，本轮记录“窄窗导致的历史 miss”即可，不再为该 2008 事件继续大改主链。

## 5) 新对话接手建议（最小上下文包）
新对话建议先读取以下文件（按顺序）：
1. `README_run.md`
2. `论文/handoff_for_prism_experiment_setup.md`
3. `outputs/e6b3_joint_ablation_v01/e6b3_summary.json`
4. `outputs/e7b_collector_structure_v01/e7b_summary.json`
5. `outputs/e8b_case_external_validation_v01/e8b_case_validation_summary.json`
6. `outputs/e8c_known_events_test_v01/e8c_known_events_summary.json`

然后默认使用这些固定口径：
- base run：`20260313T032554_4f9be28c`
- 主链结构与标签不改
- 结果目录优先写入 `outputs/`
- 不把 high 直接写成“已确认攻击”，用“high-confidence suspicious / validated suspicious”

## 6) 当前边界与注意事项
- 本工作树存在未跟踪实验脚本（`scripts/run_e6b1...run_e8c...`）；不要在新对话里误当作“未实现功能”。
- 可见度实验当前只基于 2 collectors，不可外推为全网覆盖结论。
- 若后续继续 E8/E9，请优先复用既有 run 与中间产物，避免大规模重跑。

## 7) 本文件定位
本文件用于“新对话快速接入”，不是论文正文，不替代详细实验报告。
