# R-AGG-2 Raw Incident Prototype Aggregation

Last updated: 2026-05-26

Status: prototype aggregation completed on baseline 6h candidate/event artifacts.

## 1. 本轮目标

R-AGG-2 构建第一版 Raw Incident prototype aggregation。

本轮只做：

- 以 candidate-entry 作为 Raw Incident 主入口；
- 用 event-entry 通过 `event_id` 精确修复 `start_time` / `end_time` / `time_bucket_key`；
- 输出可审计的 `raw_incidents_prototype.parquet` 和 summary；
- 评估 prototype 聚合压缩率、time repair 覆盖、family_hint、visibility、mixedness 和 aggregation_confidence。

本轮不做：

- 不修改旧 7 层 pipeline；
- 不使用 final-entry 作为主入口；
- 不接 RPKI / AS-rel / communities / NO_EXPORT / ASPA；
- 不训练 learning；
- 不实现 final review queue；
- 不做 background suppression；
- 不产生 attack/benign/normal truth label。

## 2. 为什么 candidate-entry 是主入口

R-AGG-ENTRY-0 已确认 candidate-entry 是最合理的 Raw Incident 主入口。它保留 prefix、origin AS、AS path、collector 和 candidate reasons，同时没有 scored/gated/augmented/final 的强判断污染。

final labels are weak workflow signals, not truth labels。

candidate-entry 产生的是 weak trigger / incident construction material，不是最终攻击判断。

## 3. 为什么 event-entry 只用于 time repair / observation repair

candidate-entry 缺少 `start_time` / `end_time`，导致 R-AGG-1 mapping 中 `time_scope` 覆盖率为 `0.0`。

event-entry 保留原始 observation time 和 collector provenance，所以 R-AGG-2 用它修复时间字段。

边界：

- event-entry 不替代 candidate-entry；
- event-entry 不产生 truth label；
- event-entry 只作为 time / observation repair source；
- 如果 event join 失败，prototype 必须保留 `time_repair_status=failed/missing`，不能静默伪造时间。

## 4. 为什么不用 scored/gated/augmented/final 作为主入口

这些层可以作为后续 reference 或 ablation，但不能作为 Raw Incident 主入口：

- scored-entry 已引入 `risk_score` / `risk_bucket`；
- gated-entry 已引入 `gating_label`、certainty/conflict 等旧 gate 判断；
- augmented-entry 是 uncertain subset enrichment，覆盖不完整且带 augmentation 判断；
- final-entry 直接带 `final_alert_label`。

这些字段只能作为 `legacy_reference`，不能参与 Raw Incident truth construction。

## 5. Prototype aggregation key v0

R-AGG-2 使用保守 key：

```text
prefix_origin_key
  + as_path_signature
  + family_hint
  + collector_set
  + time_bucket_key
```

如果 `time_bucket_key` 缺失，则使用：

```text
prefix_origin_key
  + as_path_signature
  + family_hint
  + collector_set
```

并标记 `time_bucket_missing=true` / time repair not ready。

本轮 full run 中 event-id exact join 成功，因此所有 prototype raw incidents 都有 `time_bucket_key`。

## 6. time_scope 修复策略

优先策略：

1. 如果 candidate-entry 有 `event_id`，用 `event_id` join event-entry。
2. 从 event-entry 读取 `first_seen` / `last_seen` / `duration_sec`。
3. 按 `--time-window-minutes=15` 生成 `time_bucket_key`。
4. join 成功标记 `time_repair_status=exact_join`。

fallback 策略：

- events 缺失：`time_repair_status=missing`；
- events 存在但 join 失败：`time_repair_status=failed`；
- 后续如果没有 event_id，可再设计 prefix/origin/path/collector/time-like weak join，但本轮 baseline 不需要。

## 7. Raw Incident 输出字段说明

输出尽量覆盖 R-AGG-1 schema v0：

| group | representative fields |
| --- | --- |
| identity | `raw_incident_id`, `run_id`, `source_entry`, `source_row_count`, `source_candidate_row_ids`, `source_event_ids` |
| time_scope | `start_time`, `end_time`, `duration_sec`, `time_bucket_key`, `time_repair_status` |
| routing_object | `prefix_set`, `dominant_prefix`, `origin_as_set`, `dominant_origin_as`, `prefix_origin_key`, `as_path_signature_set`, `dominant_as_path_signature` |
| observation_scope | `collector_set`, `collector_count`, `visibility_mode` |
| aggregation_explanation | `aggregation_key`, `aggregation_reason`, `member_event_count`, `member_candidate_count`, `candidate_reason_set`, `trigger_reason_set` |
| weak_semantic_hint | `family_hint`, `family_hint_source`, `weak_signal_tags` |
| structure_quality | `mixedness_hint`, `aggregation_confidence`, `component_count_estimate`, `dominant_component_share`, `split_needed_hint` |
| legacy_reference | `legacy_score_fields_present`, `legacy_gate_fields_present`, `legacy_final_fields_present`, `legacy_reference_only_note` |
| downstream_hooks | `evidence_grounding_ready`, `required_lookup_keys`, `learning_ready_features`, `poisoning_benchmark_relevant_fields` |

Implementation note: for speed and auditability, prototype output stores representative source IDs plus member counts. R-AGG-3 can decide whether an exhaustive membership table is needed for final audit.

## 8. family_hint 定义和禁止误用

Allowed values:

- `forged_origin_like`
- `route_leak_like`
- `path_manipulation_like`
- `stealth_visibility_like`
- `background_like_pattern`
- `mixed_unknown`

`family_hint is semantic hint`, not attack label。

禁止误用：

- forged_origin_like 不是 confirmed hijack；
- route_leak_like 不是 confirmed route leak；
- path_manipulation_like 不是 confirmed path attack；
- stealth_visibility_like 不是 confirmed NO_EXPORT；
- background_like_pattern 不是 confirmed benign；
- mixed_unknown 不是系统失败。

## 9. Prototype 结果

Run:

- `s2a_baseline_v01_pilot_6h_april16`

Outputs:

- `outputs/r_agg_2/s2a_baseline_v01_pilot_6h_april16/raw_incidents_prototype.parquet`
- `outputs/r_agg_2/s2a_baseline_v01_pilot_6h_april16/raw_incidents_prototype_preview.csv`
- `outputs/r_agg_2/s2a_baseline_v01_pilot_6h_april16/raw_incident_prototype_summary.json`
- `outputs/r_agg_2/s2a_baseline_v01_pilot_6h_april16/raw_incident_time_repair_audit.csv`
- `outputs/r_agg_2/s2a_baseline_v01_pilot_6h_april16/raw_incident_grouping_stats.csv`

Summary:

| metric | value |
| --- | ---: |
| candidate_rows_input | `3431103` |
| event_rows_input | `3431103` |
| raw_incident_count | `3128971` |
| compression_ratio | `1.09656` |
| time_scope_coverage | `1.0` |
| evidence_grounding_ready_rate | `0.948727` |
| aggregation_confidence_mean | `0.983492` |
| aggregation_confidence_p50 | `1.0` |
| aggregation_confidence_p90 | `1.0` |

Time repair:

| time_repair_status | raw_incident_count |
| --- | ---: |
| exact_join | `3128971` |

family_hint:

| family_hint | raw_incident_count |
| --- | ---: |
| mixed_unknown | `1707486` |
| stealth_visibility_like | `1406742` |
| forged_origin_like | `14743` |

visibility_mode:

| visibility_mode | raw_incident_count |
| --- | ---: |
| single_collector | `3089300` |
| weak_visibility | `39671` |

mixedness:

| mixedness_hint | raw_incident_count |
| --- | ---: |
| low | `3128971` |

Member distribution:

- mean member_candidate_count: `1.09656`
- p50: `1`
- p90: `1`
- p99: `2`
- max: `3`
- groups with more than one candidate: `278981`

## 10. 当前风险

Over-aggregation risk:

- 当前 key 很保守，over-aggregation 风险低；
- 但 R-AGG-3 仍需检查同一 key 内是否隐藏 mixed component。

Under-aggregation risk:

- 压缩率仅 `1.09656`，说明当前 prototype 更接近 raw dossier construction，而不是 final ticket aggregation；
- 后续如果需要更强 compression，应谨慎放宽 key，例如合并相邻 time bucket 或弱化 path signature，但必须做质量审计。

Time join risk:

- baseline run 使用 `event_id` exact join，time_scope 覆盖从 R-AGG-1 的 `0.0` 改善到 `1.0`；
- 如果未来 run 缺 `event_id`，需要 weak join 设计和失败审计。

Candidate noise risk:

- candidate-entry 本身仍是 weak trigger source；
- 单 collector 占比很高，不能把 low visibility 直接解释为 stealth attack；
- family_hint 不等于 attack label。

Prototype implementation risk:

- 为保证 full run 可执行，source id 列是 representative sample，加 member counts，而不是完整 membership table；
- 如果 R-AGG-3 需要逐成员审计，应新增 raw incident membership output。

## 11. 下一步建议

建议优先进入 R-AGG-3 aggregation quality audit。

R-AGG-3 应检查：

- 当前保守 key 是否过细；
- 是否存在可安全合并的相邻 time buckets；
- mixed_unknown 是否过多；
- single_collector 主导是否只是 observation mode，而不是 stealth verdict；
- 是否需要单独输出 raw incident membership table；
- Evidence-grounded Incident design 是否可以消费当前 prototype。

备选下一步是 Evidence-grounded Incident design，但更稳妥的是先做 R-AGG-3，避免把过细或过粗的 prototype 直接接证据层。

## 12. Relation to Poisoning Benchmark and Learning

poisoning benchmark retained。

R-AGG-2 产出的 `collector_set`、`visibility_mode`、`candidate_reason_set`、`as_path_signature_set` 可作为后续 public monitor incomplete / poisonable 场景下的 benchmark 基础字段。

learning layer postponed and must target BEAM-style semantic learning。

未来 learning 应学习 incident/component/evidence representation、prioritization、split priority 和 calibration，而不是旧规则重打分，也不能覆盖 verifier hard rules。
