# Prism 交接材料：Experiment Setup / Evaluation Setup（基于真实 run）

## Part A｜当前实验对象与数据来源

1. **当前实验 run_id**
   - `20260313T032554_4f9be28c`
   - 依据：`data/runs/20260313T032554_4f9be28c/run.json`

2. **当前 run 的 collector**
   - `route-views.sg`
   - `rrc00`
   - 依据：`run.json -> collectors` 与 `collectors_summary`

3. **当前数据时间范围/窗口（可确认）**
   - 本 run 为 loop 模式第 2 轮：`mode=loop`，`loop_cycle_index=2`
   - 每轮采集窗口：`window_minutes=5`，`chunk_minutes=5`
   - 本轮实际采集区间（两个 collector 一致）：`2017-07-07 00:15:00` 到 `2017-07-07 00:20:00`
   - 依据：`run.json -> marker_before/marker_after`，`run.log` 的 `[chunk]` 记录，及落盘文件名 `updates__00-15-00__00-20-00...`

4. **当前实验对象层次（已确认）**
   - 事件层样本：`events/event_units.parquet`（4808 行）
   - 候选层样本：`candidates/candidate_events.parquet`（全量 4808 行，`candidate_flag=true` 的为 1106）
   - 评分层样本：`scores/scored_candidates.parquet`（1106 行）
   - 门控层样本：`gating/gated_candidates.parquet`（1106 行）
   - 增强层样本：`augmentation/augmented_candidates.parquet`（645 行，仅 uncertain 子集）
   - 最终样本：`final/final_alerts.parquet`（1106 行）

---

## Part B｜完整检测链与对应产物

### 1) 事件层（Event Construction）
- 脚本：`scripts/build_event_units.py`
- 输入：run 目录内 parquet（优先 `__rel.parquet`，可退化到 updates parquet）
- 输出：
  - `data/runs/<run_id>/events/event_units.parquet`
  - `data/runs/<run_id>/events/event_units_summary.json`
- 当前作用：把 update 记录聚合为事件单元（按 `prefix + origin_as + as_path_clean`，再按时间窗口切分）
- 关键字段：`event_id`, `first_seen`, `last_seen`, `duration_sec`, `record_count`, `collector_count`, `visibility_count`, `rel_*`, `time_window_sec`

### 2) 历史基线层（Historical Baseline）
- 脚本：`scripts/build_historical_baseline.py`
- 输入：`events/event_units.parquet`
- 输出：
  - `baseline/baseline_prefix.parquet`
  - `baseline/baseline_prefix_origin.parquet`
  - `baseline/baseline_path.parquet`
  - `baseline/baseline_summary.json`
- 当前作用：生成 prefix / prefix-origin / path 三层历史画像
- 关键字段：
  - prefix 层：`total_events`, `unique_origins`, `top_origins`, `avg/median_*`
  - prefix-origin 层：`unique_paths`, `top_paths`, `avg/median_path_len`, `rel_unknown_rate`
  - path 层：`total_events`, `total_records`, `first_seen`, `last_seen`, `collector_set`

### 3) 候选层（Weak Candidate Generation）
- 脚本：`scripts/build_weak_candidates.py`
- 输入：`event_units.parquet` + 三层 baseline parquet
- 输出：
  - `candidates/candidate_events.parquet`
  - `candidates/candidate_summary.json`
- 当前作用：规则式高召回初筛（结构性规则优先，弱规则辅助）
- 关键字段：`candidate_flag`, `candidate_reasons`, `matched_rule_count`, `path_seen_before`, `prefix/po/path 历史计数字段`

### 4) 评分层（Weak-Signal Risk Scoring）
- 脚本：`scripts/score_weak_candidates.py`
- 输入：`candidate_events.parquet` + 三层 baseline parquet
- 输出：
  - `scores/scored_candidates.parquet`
  - `scores/score_summary.json`
- 当前作用：将候选分层为可比较风险分，提供可解释子分
- 关键字段：`structural_novelty_score`, `weak_signal_score`, `history_rarity_score`, `path_consistency_score`, `risk_score`, `risk_bucket`, `top_contributing_factor`, `missing_origin_or_path`

### 5) 门控层（Uncertainty-Aware Gating）
- 脚本：`scripts/gate_scored_candidates.py`
- 输入：`scores/scored_candidates.parquet`
- 输出：
  - `gating/gated_candidates.parquet`
  - `gating/gating_summary.json`
- 当前作用：把评分样本分为三类门控标签
- 关键字段：`certainty_score`, `conflict_score`, `gating_label`, `gating_explanation`, `promoted_from_low`, `demoted_from_high`

### 6) 增强层（Evidence Augmentation for Uncertain）
- 脚本：`scripts/augment_uncertain_candidates.py`
- 输入：`gated_candidates.parquet` + `event_units.parquet` + 三层 baseline parquet
- 输出：
  - `augmentation/augmented_candidates.parquet`
  - `augmentation/augmentation_summary.json`
- 当前作用：仅对 uncertain 子集补充低成本内部证据
- 关键字段：`multi_view_support_score`, `historical_deviation_support_score`, `consistency_recheck_score`, `evidence_support_score`, `augmentation_label`, `augmentation_explanation`

### 7) 最终整合层（Final Alert Aggregation）
- 脚本：`scripts/build_final_alerts.py`
- 输入：`scores/scored_candidates.parquet` + `gating/gated_candidates.parquet` + `augmentation/augmented_candidates.parquet`
- 输出：
  - `final/final_alerts.parquet`
  - `final/final_report.json`
- 当前作用：统一输出最终告警标签口径
- 关键字段：`final_alert_label`, `alert_source_layer`, 并保留 `gating_label`、`augmentation_label`、`risk_*`、`certainty/conflict`、`evidence_support_score`

---

## Part C｜当前实验评价口径

1. **`final_alert_label` 三类定义（最终口径）**
   - `high_priority_alert`
   - `needs_review`
   - `low_priority_or_background`

2. **E1 统计口径（主链收敛）**
   - 统计链路：`event -> candidate -> scored -> gated -> augmented -> final`
   - 当前关键数字（来自真实产物）：
     - events: 4808
     - candidate_flag=true: 1106
     - scored: 1106
     - gated: 1106
     - augmented（uncertain 子集）: 645
     - final high / needs / low: 24 / 625 / 457
   - 常用分母：`total_events=4808`（用于收敛率）

3. **E2 统计口径（高优先质量）**
   - 对象：`final_alert_label=high_priority_alert`
   - 关注：
     - 来源分解：来自 gating 与 augmentation 的数量/占比
     - `top_contributing_factor` 构成
     - `missing_origin_or_path` 占比
     - 与 needs/low 在 `risk_score`, `certainty_score`, `conflict_score` 上的对比
   - 当前关键数字：
     - high 总数 24；其中 gating 22（91.67%），augmentation 2（8.33%）
     - high 中 structural top factor 占比 100%
     - high 中 missing_origin_or_path=0（0%）

4. **E3 统计口径（uncertain 处理收益）**
   - 对象：`gating_label=suspicious_but_uncertain` 子集
   - 分流：`promoted_suspicious / retained_uncertain / demoted_suspicious`
   - 关注：
     - uncertain 三向分流数量与占比
     - uncertain 到 final 标签映射
     - 三组在 risk/certainty/conflict/evidence_support 的对比
     - augmentation 对 final high 的边际贡献
   - 当前关键数字：
     - uncertain=645
     - promoted/retained/demoted=2/625/18
     - promoted->high=2/2，retained->needs=625/625，demoted->low=18/18
     - augmentation 对 final high 边际贡献：2/24（8.33%）

---

## Part D｜当前真实参数与口径（仅已确认）

### 1) 事件层参数（`build_event_units.py`）
- `--window-sec` 默认 `300`
- `--prefer-rel` 默认 `true`（存在 `__rel` 时优先使用）
- 事件切分规则：同 `prefix + origin_as + as_path_clean` 下，相邻记录时间差 `<= window_sec` 归并为同一事件

### 2) 基线层参数（`build_historical_baseline.py`）
- `--min-events` 默认 `1`
- 输出三层 baseline（prefix / prefix-origin / path）

### 3) 候选层参数与规则（`build_weak_candidates.py`）
- `--min-weak-rules` 默认 `2`
- 结构性规则集合（代码常量 `STRUCTURAL_RULES`）：
  - `unseen_origin_for_prefix`
  - `unseen_path_for_prefix_origin`
  - `unseen_exact_path`
  - `weak_path_history`
  - `abnormal_path_length_for_prefix_origin`
- 弱规则集合（`WEAK_RULES`）：
  - `unusually_low_visibility_for_prefix`
  - `unusually_short_duration_for_prefix`
  - `unusually_low_visibility_for_prefix_origin`
  - `sparse_short_lived_event`
- contextual（不计入提升计数）：`single_collector_visibility`
- 入候选逻辑（可确认）：`candidate_flag = (命中任一结构规则) OR (弱规则命中数 >= min_weak_rules)`

### 4) 评分层参数与口径（`score_weak_candidates.py`）
- 子分权重（`SCORE_WEIGHTS`）：
  - structural 0.45
  - weak 0.20
  - history_rarity 0.20
  - path_consistency 0.15
- `missing_origin_or_path` 触发时有分数抑制（`MISSING_DAMPEN_RATIO=0.92`）
- 风险桶阈值由当次分布分位数推导（`high=0.80分位`, `medium=0.40分位`；见 `derive_bucket_thresholds`）

### 5) 门控层参数与口径（`gate_scored_candidates.py`）
- 三类门控输出：`likely_malicious / suspicious_but_uncertain / likely_benign`
- 关键阈值（`GATING_CONFIG`）：
  - `certainty_threshold_high=65`
  - `certainty_threshold_medium=45`
  - `conflict_threshold_high=35`
  - `conflict_threshold_medium=50`
  - `promote_low_structural_min=45`
  - `promote_low_certainty_min=45`

### 6) 增强层参数与口径（`augment_uncertain_candidates.py`）
- **仅处理 uncertain**（`gating_label == suspicious_but_uncertain`）
- 证据分权重（`AUGMENT_WEIGHTS`）：
  - multi_view 0.35
  - historical_deviation 0.40
  - consistency_recheck 0.25
- 标签阈值（`AUGMENT_CONFIG`）：
  - `promoted_threshold=65`
  - `demoted_threshold=35`
  - `related_window_sec=300`

### 7) 最终整合口径（`build_final_alerts.py`）
- `promoted_suspicious -> high_priority_alert`
- `gating likely_malicious -> high_priority_alert`
- `demoted_suspicious -> low_priority_or_background`
- `gating likely_benign -> low_priority_or_background`
- `gating suspicious_but_uncertain + (retained 或空 augmentation) -> needs_review`

---

## Part E｜当前实验边界与复现说明

1. **当前实验范围**
- 单个 run：`20260313T032554_4f9be28c`
- 非多 run 聚合实验

2. **collector 规模**
- 当前为 2 个 collector（`route-views.sg`, `rrc00`）
- 不代表大规模全网 collector 覆盖

3. **是否引入外部数据面验证**
- 当前链路未引入外部数据面探测（如 traceroute/RTT/IHR 等）
- 增强层使用的是内部控制面与历史统计信息

4. **当前设置适合支持的结论**
- 适合：
  - 链路端到端可运行性与收敛性（E1）
  - 高优先输出的结构证据主导与质量特征（E2）
  - uncertain 子集的保守分流与边际收益（E3）
- 不适合：
  - 大规模全网泛化结论
  - 跨长期时间、多区域、多运营商全面外推
  - 带外部数据面强验证的最终攻击确认结论

5. **复现最核心目录/文件**
- 运行元信息：`data/runs/20260313T032554_4f9be28c/run.json`, `run.log`
- 主链产物：`events/`, `baseline/`, `candidates/`, `scores/`, `gating/`, `augmentation/`, `final/`
- 统计汇总：各层 `*_summary.json` + `final/final_report.json`
- 论文资产：`论文/实验资产_E1E2E3_v01/`

---

## Part F｜写作时应强调的点

### 写作时应强调的点

1. **应克制表述**
- 明确写“当前为单 run、双 collector、固定历史窗口下的链路实验结果”。
- 强调是“主链可运行性 + 分层质量 + uncertain 收益”验证，不是全网结论。

2. **可以明确写的内容**
- 全链路各层输入/输出和标签定义（均有真实脚本与真实产物支撑）。
- E1/E2/E3 的分子分母口径与关键数字（见本文件 Part C 和 `论文/实验资产_E1E2E3_v01/`）。
- final 标签如何由 gating/augmentation 合并得到（代码中可直接追溯）。

3. **需要保守的内容**
- 不把当前结果表述为“对互联网全局长期稳定有效”。
- 不将 high_priority 直接等价为“已验证攻击”，应写为“高优先告警/高可疑样本”。
- 不夸大 augmentation 的绝对提升幅度，建议用“保守但有边际贡献”表述。

4. **不要写成的样子**
- 不要写成“大规模全网泛化结论”或“最终攻击定性结论”。
- 不要忽略实验边界（单 run、2 collectors、无外部数据面验证）。
