# R-AGG-3 Raw Incident Aggregation Quality Audit

Last updated: 2026-05-26

Status: read-only aggregation quality audit completed on R-AGG-2 prototype output.

## 1. 本轮目标

R-AGG-3 审计 R-AGG-2 Raw Incident prototype aggregation 的质量。

本轮只回答：

- 为什么 R-AGG-2 压缩率低；
- 哪些 key 导致 raw incidents 过碎；
- 哪些 raw incidents 可能是低价值 background-like operational candidates；
- 哪些相邻 raw incidents 可能存在 safe merge 机会；
- 如果后续做 pre-incident filter 或 safe merge，会不会误伤高价值弱信号；
- 为什么 `mixed_unknown` 很多。

本轮不做：

- 不修改旧 7 层 pipeline；
- 不修改 R-AGG-2 聚合主逻辑；
- 不接 RPKI / AS-rel / communities / NO_EXPORT / ASPA；
- 不使用 final-entry 作为主入口；
- 不训练 learning；
- 不实现 safe merge；
- 不实现 final output；
- 不实现 background suppression；
- 不产生 truth label。

## 2. R-AGG-2 结果回顾

R-AGG-2 使用 candidate-entry 作为主入口，并用 event-entry 通过 `event_id` 修复 time_scope。

R-AGG-2 full baseline 结果：

| metric | value |
| --- | ---: |
| candidate_rows_input | `3431103` |
| raw_incident_count | `3128971` |
| compression_ratio | `1.09656` |
| time_scope_coverage | `1.0` |
| time_repair_status | `exact_join` |

结论：candidate-entry + event-entry time repair 可行，但 key v0 太保守，prototype 几乎仍是 candidate-row-level dossier。

## 3. 为什么不能直接退回 final-entry

不能因为 R-AGG-2 压缩率低就回到 final-entry。

原因：

- final labels are weak workflow signals, not truth labels；
- final-entry 已经继承 score/gate/augment/final 旧判断；
- 直接用 final-entry 会把旧 detector bias 带进 Raw Incident 和后续 learning；
- 论文主线是 explainable incident construction + evidence grounding，不是复述旧 final label。

R-AGG-3 的正确作用是审计如何改进 Raw Incident，而不是回退到 final。

## 4. 为什么需要审计事件爆炸

R-AGG-2 的 `compression_ratio=1.09656` 说明：

- 当前 key 很保守，over-aggregation 风险低；
- 但 raw incident 数量过高，不适合作为最终 analyst-facing ticket 数；
- 后续 Evidence-grounded Incident 如果直接消费这个表，证据接入成本会过高；
- 需要先判断是 key 设计过细、family_hint mapping 问题、背景噪声太多，还是三者都有。

## 5. key_fragmentation 结果

Raw incident count: `3128971`。

Unique counts：

| dimension | unique count |
| --- | ---: |
| prefix_origin_key | `320443` |
| dominant_as_path_signature | `373524` |
| candidate_reason_set | `45` |
| collector_set | `3` |
| time_bucket_key | `24` |

Hypothetical grouping estimates:

| key strategy | hypothetical groups | compression ratio | risk |
| --- | ---: | ---: | --- |
| prefix_origin_key | `320443` | `10.707374` | high |
| prefix_origin_key + family_hint | `380929` | `9.007198` | medium |
| prefix_origin_key + dominant_as_path_signature | `1638486` | `2.094069` | low |
| prefix_origin_key + family_hint + dominant_as_path_signature | `1643116` | `2.088168` | low |
| prefix_origin_key + family_hint + time_bucket_key | `940870` | `3.646734` | medium |
| prefix_origin_key + family_hint + collector_set | `470400` | `7.294011` | medium |

Interpretation:

- `time_bucket_key` and path signature both contribute to fragmentation.
- Dropping time entirely can create compression, but risks merging long-lived unrelated fragments.
- Dropping path entirely is too aggressive for a verifier-ready dossier.
- The most plausible safe direction is controlled adjacent-time merge with path/family/collector constraints.

## 6. background candidate 结果

Possible background-like operational candidates:

- count: `3114228`
- rate: `0.995288`

This is not a benign label.

background-like is operational suppression candidate, not confirmed benign。

Why so high:

- single-collector visibility dominates the prototype output；
- many rows are `mixed_unknown` or `stealth_visibility_like`；
- current family_hint mapping treats combined visibility + path/origin reasons as mixed；
- background score is intentionally broad for audit sensitivity.

Important caution:

- high-value overlap is also very high；
- therefore a pre-incident filter is not safe to implement now；
- it first needs family_hint mapping repair and high-value retention constraints.

## 7. merge opportunity 结果

Merge opportunity audit found:

- safe_candidate_group_count: `304526`
- safe_merge_reduction_count: `1335154`
- estimated_best_safe_group_count: `1793817`
- estimated_best_safe_compression_ratio: `1.912739`

Interpretation:

- There is meaningful safe merge space.
- However, the top largest repeated groups with missing prefix/path keys are `risky_mixed`, not safe.
- Safe candidates are mostly same prefix-origin, same family, same path signature, same collector, repeated across adjacent time buckets.

This supports a future R-AGG-4 safe merge key design, but only after family_hint mapping repair.

## 8. high-value retention 风险

High-value candidate audit:

- high_value_candidate_count: `3118030`
- overlap_with_background_like: `3103287`
- risky_suppression_count: `3103287`

This means a naive background filter would suppress many rows that also carry weak signals such as unseen path, origin/path novelty, or high aggregation confidence.

Conclusion:

- Do not implement background suppression now.
- Do not treat single_collector or mixed_unknown as low-value by itself.
- Any future pre-incident filter must explicitly preserve forged/path/route-leak/stealth weak signal cases.

## 9. mixed_unknown 解释

mixed_unknown count:

- `1707486`
- rate: `0.545702`

Diagnostics:

| metric | value |
| --- | ---: |
| candidate_reason_missing among mixed_unknown | `10941` |
| weak_signal_missing among mixed_unknown | `10941` |
| core keys complete among mixed_unknown | `1557995` |
| visibility + path mix | `1679177` |
| origin + path mix | `1689654` |

Interpretation:

`mixed_unknown` is mostly a family_hint mapping / priority issue, not missing data.

Current R-AGG-2 mapping collapses common combinations such as:

- `single_collector_visibility + unseen_path_for_prefix_origin`
- `unseen_origin_for_prefix + unseen_path_for_prefix_origin`

into `mixed_unknown`, even though core keys are usually present.

Suggested mapping repair:

- Treat `single_collector_visibility` as `observability_mode` unless no stronger reason exists.
- Map `unseen_path_for_prefix_origin` primarily to path-manipulation-like or path-review hint.
- Map origin-change/new-origin reasons to forged_origin_like before visibility tags.
- Keep `mixed_unknown` only when attack-family hints conflict after separating observability tags.

## 10. 下一步建议

Recommended next step:

`R-AGG-4 family_hint mapping repair before safe merge`

Reason:

- safe merge space exists；
- pre-incident filter pressure exists；
- but `mixed_unknown` is too high and high-value overlap with background-like is too large；
- implementing safe merge or filter before fixing family_hint mapping could hide important weak-signal cases.

After mapping repair:

1. rerun R-AGG-2 or a mapping-only refresh;
2. rerun R-AGG-3 quality audit;
3. then choose between:
   - R-AGG-4 safe merge key design;
   - R-AGG-4 pre-incident background filter design;
   - Evidence-grounded Incident design.

## 11. Safety Statement

This round:

- produces no truth label；
- attaches no external evidence；
- trains no learning layer；
- implements no final output；
- implements no safe merge；
- implements no background suppression。

`family_hint is semantic hint`, not attack label。

`background-like is operational suppression candidate`, not confirmed benign。

poisoning benchmark retained。

learning layer postponed and must target BEAM-style semantic learning。
