# R-AGG-1 Raw Incident Dossier Schema

Last updated: 2026-05-25

Status: schema v0 design and candidate-entry mapping prototype completed.

## 1. R-AGG-1 目标

R-AGG-1 只做 Raw Incident Dossier schema v0 和 candidate-entry 到 schema 的字段映射预演。

本轮不实现完整 incident aggregation，不接 RPKI / AS-rel / communities / NO_EXPORT / ASPA，不训练 learning，不修改旧 7 层 pipeline，不产生 attack/benign 或 normal truth label。

核心产物：

- `configs/raw_incident_dossier_schema_v0.yaml`
- `scripts/prototype_raw_incident_schema_mapping.py`
- `outputs/r_agg_1/<run_id>/raw_incident_schema_mapping_preview.csv`
- `outputs/r_agg_1/<run_id>/raw_incident_schema_mapping_summary.json`

## 2. 为什么从 candidate-entry 开始

R-AGG-ENTRY-0 已比较 event/candidate/scored/gated/augmented/final 六个入口。

结论是：candidate-entry 是当前 Raw Incident Dossier 主入口，因为它在三件事之间最平衡：

- 保留 prefix / origin AS / AS path / collector / candidate reasons 等后续 evidence lookup 所需字段；
- 比 event-entry 多了 weak-trigger explanation；
- 比 scored/gated/augmented/final 更少旧判断污染。

final labels are weak workflow signals, not truth labels. Final-entry 只能作为对照或 reference，不能作为 Raw Incident 主入口。

## 3. Raw Incident Dossier 和 Evidence-grounded Incident 边界

Raw Incident Dossier 负责：

- 整理 candidate-entry 的 observation、object、weak trigger、aggregation key 和 uncertainty；
- 输出可以被审计的 incident construction unit；
- 为后续 evidence grounding 准备 lookup keys。

Evidence-grounded Incident 负责：

- 接入 RPKI/VRP、AS-rel、communities/NO_EXPORT、ASPA 等外部或扩展证据；
- 记录证据 snapshot、freshness、availability 和 conflict；
- 输入 Stage 2 verifier。

边界很重要：Raw Incident 只做“案卷结构”，Evidence-grounded Incident 才做“证据接地”。Raw Incident 不输出 attack/benign，不把 family_hint 当 verdict。

## 4. Raw Incident Dossier schema v0

完整机器可读版本见 `configs/raw_incident_dossier_schema_v0.yaml`。

| group | fields | role |
| --- | --- | --- |
| identity | `raw_incident_id`, `run_id`, `source_entry`, `source_row_count`, `source_member_event_ids` | 标识 prototype dossier 与 candidate-entry provenance |
| time_scope | `start_time`, `end_time`, `duration_sec`, `time_bucket_key`, `time_completeness_flag` | 记录时间范围和时间字段完整性 |
| routing_object | `prefix_set`, `dominant_prefix`, `origin_as_set`, `dominant_origin_as`, `prefix_origin_key`, `as_path_signature_set`, `dominant_as_path_signature` | 记录 prefix/origin/path lookup keys |
| observation_scope | `collector_set`, `collector_count`, `visibility_mode`, `visibility_span_hint` | 记录 public monitor 可见性 |
| aggregation_explanation | `aggregation_key`, `aggregation_reason`, `member_event_count`, `candidate_reason_set`, `trigger_reason_set` | 解释为什么这些 candidate 可进入同一 raw dossier |
| weak_semantic_hint | `family_hint`, `family_hint_source`, `weak_signal_tags` | 给后续 component/evidence 分流的弱语义提示 |
| structure_quality | `mixedness_hint`, `aggregation_confidence`, `component_count_estimate`, `dominant_component_share`, `split_needed_hint` | 表示混杂度、聚合可靠性和后续 split 可能性 |
| legacy_reference | `legacy_score_fields_present`, `legacy_gate_fields_present`, `legacy_final_fields_present`, `legacy_reference_only_note` | 显式把旧 score/gate/final 字段降级为 reference |
| downstream_hooks | `evidence_grounding_ready`, `required_lookup_keys`, `learning_ready_features`, `poisoning_benchmark_relevant_fields` | 为证据接入、poisoning benchmark 和未来 learning 预留接口 |

## 5. family_hint 定义与禁止误用

允许的 `family_hint` v0：

- `forged_origin_like`
- `route_leak_like`
- `path_manipulation_like`
- `stealth_visibility_like`
- `background_like_pattern`
- `mixed_unknown`

`family_hint is semantic hint`, not attack label.

禁止误用：

- `forged_origin_like` 不是 confirmed hijack；
- `route_leak_like` 不是 confirmed route leak；
- `path_manipulation_like` 不是 confirmed path attack；
- `stealth_visibility_like` 不是 confirmed NO_EXPORT 或 monitor evasion；
- `background_like_pattern` 是操作压制方向，不是 confirmed benign；
- `mixed_unknown` 是后续 component split / abstain 的提示，不是失败。

## 6. legacy_reference 规则

Raw Incident Dossier 可以记录 legacy score/gate/final 字段是否存在，但只能 reference。

规则：

- high/needs/low 不是 truth；
- P1/P2/P3 不是 truth；
- final labels are weak workflow signals, not truth labels；
- scored-entry 可以作为辅助诊断，不是主入口；
- gated/augmented/final 不参与 Raw Incident 主构造。

## 7. Prototype mapping 结果

本轮 sample mapping 使用本地完整 candidate parquet：

- run: `s2a_baseline_v01_pilot_6h_april16`
- source: `data/runs/s2a_baseline_v01_pilot_6h_april16/candidates/candidate_events.parquet`
- sample rows: `5000`
- total candidate rows: `3431103`

字段覆盖：

- schema fields: `42`
- covered fields: `38`
- schema field coverage: `0.904762`
- required field missing rate: `0.075059`

可用 lookup keys：

| lookup key | coverage |
| --- | ---: |
| `prefix_origin_key` | `0.9912` |
| `as_path_signature` | `0.9912` |
| `collector_set` | `1.0` |
| `candidate_reason_set` | `0.9996` |
| `time_scope` | `0.0` |

`time_scope` 被保守标记为 not ready，因为 candidate-entry 当前有 `duration_sec`，但没有 `start_time` / `end_time`。后续 R-AGG-2 应通过 event-entry join 或上游 retention 修复时间 bucket。

Sample `family_hint` 分布：

| family_hint | sample count |
| --- | ---: |
| `forged_origin_like` | `3624` |
| `stealth_visibility_like` | `1373` |
| `path_manipulation_like` | `3` |

这些只是 heuristic preview，不是 attack label。

## 8. Downstream hooks

Evidence grounding:

- `prefix_origin_key` 支持未来 RPKI/VRP origin lookup；
- `as_path_signature_set` 支持 AS-rel / ASPA / Roles path evidence lookup；
- `collector_set` 支持 monitor observability 和 asymmetry analysis；
- `candidate_reason_set` 保留 weak trigger provenance；
- `time_scope` 仍需修复后才能更稳地接 snapshot / window evidence。

Poisoning benchmark retained:

- `collector_set`
- `visibility_mode`
- `candidate_reason_set`
- `as_path_signature_set`

这些字段可用于后续 public monitor incomplete / poisonable 场景下的 robustness benchmark。

Future semantic learning:

learning layer postponed until Raw Incident Dossier and Evidence-grounded Incident schemas are stable.

未来 learning 应面向 BEAM-style semantic learning：学习 incident/component/evidence representation、Top-K prioritization、split priority 和 calibration，而不是给旧规则重新打分。

## 9. 本轮不实现完整聚合的原因

R-AGG-1 只证明 schema 和字段映射可行。完整聚合需要额外决定：

- time bucket 粒度；
- prefix-origin-path 聚合 key；
- component split 策略；
- mixedness 和 dominant share 统计；
- candidate-entry 与 event-entry 的时间/provenance join；
- 是否引入 scored-entry 作为 reference-only diagnostic。

这些属于 R-AGG-2，不应在 schema design 阶段偷跑。

## 10. 下一步

建议进入 R-AGG-2: Raw Incident prototype aggregation。

R-AGG-2 应该：

- 以 candidate-entry 为主入口；
- 通过 event-entry join 修复 `start_time` / `end_time` / `time_bucket_key`；
- 生成 prototype raw incidents；
- 继续坚持 no truth label；
- 仍不接外部 evidence；
- 为 Evidence-grounded Incident 留出干净接口。
