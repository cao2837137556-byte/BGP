# R-EVID-0 Lightweight Evidence Pre-Triage Design and Feasibility Audit

Last updated: 2026-05-27

Status: design and feasibility audit completed on `s2a_baseline_v01_pilot_6h_april16`.

## 1. 本轮目标

R-EVID-0 是 R-AGG-3 之后的轻量证据预分诊设计审计。

本轮只回答：

- 当前 Raw Incident prototype 中哪些轻量证据已经可用；
- 是否可以设计 evidence-aware pre-triage；
- `protected_suspicious`、`suppressible_background_like`、`gray_zone_retained` 三路分流是否有可行基础；
- 哪些 stop-loss 条件会阻止进入 R-EVID-1 实现。

本轮不做：

- 不修改旧 7 层 pipeline；
- 不修改 R-AGG-2 / R-AGG-3 逻辑；
- 不真正删除候选；
- 不真正 background suppression；
- 不训练 learning；
- 不输出 attack/benign truth label。

## 2. 为什么 R-AGG-3 后不能直接 filter / merge

R-AGG-3 发现：

| metric | value |
| --- | ---: |
| raw_incident_count | `3128971` |
| estimated_best_safe_compression_ratio | `1.912739` |
| possible_background_like_rate | `0.995288` |
| high_value_candidate_count | `3118030` |
| risky_suppression_count | `3103287` |
| mixed_unknown_count | `1707486` |

这说明当前 Raw Incident 确实过碎，但不能直接压低或合并。

原因很简单：background-like 和 high-value weak signal 高度重叠。很多样本看起来像低可见度、短时、单 collector 背景噪声，但同时又带有 unseen path、origin/path novelty、RPKI 或 AS-rel 诊断信号。直接 filter 会误伤值得查的弱信号。

所以 R-EVID-0 的设计判断是：先做轻量证据保护，再讨论压缩。

## 3. 为什么需要轻量外部证据

仅靠 Stage 1 的 candidate/family_hint 很难区分：

- 真正需要保护的弱可疑样本；
- 可降低优先级的背景样式样本；
- 证据不足、必须保留的灰区样本。

轻量证据的作用不是给真假标签，而是给 pre-triage 一个保护栏：

- 保护 RPKI invalid、origin novelty、path novelty、AS-rel diagnostic 等可疑弱信号；
- 避免因为 single_collector / mixed_unknown 就把样本压掉；
- 明确哪些样本证据不足，只能进入 gray_zone_retained。

## 4. RPKI 的用途和误用边界

本轮使用本地 VRP cache：

`data/evidence/rpki/vrp_2024-04-16.parquet`

脚本对 Raw Incident 的 `dominant_prefix + dominant_origin_as` 做本地 VRP 前缀包含匹配，得到轻量 `rpki_status`：

| rpki_status | count |
| --- | ---: |
| valid | `1715313` |
| unknown | `1257344` |
| missing | `149491` |
| invalid_length | `4817` |
| invalid_asn | `2006` |

RPKI coverage: `0.550384`。

误用边界：

- RPKI invalid is not attack truth。
- RPKI valid is not benign。
- RPKI unknown / missing 不能当 normal。
- RPKI 在本轮只用于 pre-triage protection，不用于 verifier verdict 修改。

## 5. AS-rel / path diagnostic 的用途和误用边界

本轮读取 event-entry 的 `rel_seq`、`rel_unknown_cnt`、`rel_has_unknown`，并通过 R-AGG-2 保存的 `source_event_ids` 做 exact join。

结果：

| metric | value |
| --- | ---: |
| event_join_rate | `1.0` |
| asrel_diagnostic_coverage | `1.0` |
| asrel_diagnostic_signal_rate | `0.773305` |
| aligned_asrel_cache_present | `true` |
| aligned_asrel_incident_join_ready | `false` |

这里要非常谨慎：event 层 `rel_*` 是 Stage 1 诊断字段，受 R-CONSIST-1 指出的 AS-rel snapshot 风险影响。R-EVID-0 可以把它当 path diagnostic signal，但不能把它当 2024-aligned verifier evidence。

误用边界：

- AS-rel diagnostic is not route leak truth。
- AS-rel unknown / suspicious path 不等于 confirmed route leak。
- AS-rel matched 不等于 benign。
- 2024-near AS-rel cache 存在，但 R-EVID-0 不重算 path legality。

## 6. 三路 pre-triage 设计

R-EVID-0 设计的三路分流是：

| state | 含义 | 是否 truth |
| --- | --- | --- |
| `protected_suspicious` | 有轻量证据或强弱信号，不能被背景压制误伤 | 否 |
| `suppressible_background_like` | 当前没有保护信号、也没有明显异常，可作为未来降低优先级候选 | 否 |
| `gray_zone_retained` | 既不能保护为 suspicious，也不能安全压低，保留 | 否 |

这三个都是 triage state，不是 attack/benign label。

## 7. protected_suspicious 定义

候选保护信号包括：

- origin novelty / unseen prefix-origin；
- RPKI `invalid_asn` / `invalid_length`；
- unseen path / path change / abnormal path length；
- AS-rel/path diagnostic；
- single_collector 或 low_visibility 且伴随其他弱信号；
- community / NO_EXPORT 字段如果未来传递到 incident；
- known-event-like 字段如果未来存在。

Full audit 结果：

| metric | value |
| --- | ---: |
| protected_suspicious_count | `2908323` |
| protected_suspicious_rate | `0.929482` |

解释：当前大部分 Raw Incident 都被保护规则命中，主要来自 path novelty、低可见度伴随弱信号、以及 event 层 path diagnostic。这说明不能直接做 suppression。

## 8. suppressible_background_like 定义

初版 suppressible 候选必须同时满足：

- 没有 protected_suspicious 信号；
- 无 origin novelty / path novelty / RPKI invalid / AS-rel diagnostic；
- RPKI valid 或 unknown，但没有其他弱信号；
- candidate_reason_set 弱或缺失；
- visibility 无明显异常；
- 只作为未来降低优先级候选，不是删除指令。

Full audit 结果：

| metric | value |
| --- | ---: |
| suppressible_background_like_count | `0` |
| suppressible_background_like_rate | `0.0` |

解释：在保守保护规则下，本轮没有找到可以安全压低的样本。这不是失败，而是一个 stop-loss 信号：当前证据和 family_hint mapping 还不足以安全做 background suppression。

background-like is not benign。

## 9. gray_zone_retained 定义

灰区定义：

- protected signal 不够；
- 但也不能安全压成 background-like；
- 需要后续 evidence grounding、抽样或 mapping repair。

Full audit 结果：

| metric | value |
| --- | ---: |
| gray_zone_count | `220648` |
| gray_zone_rate | `0.070518` |

灰区比例不高，说明多数样本被保护规则覆盖。但这也意味着 protection 太宽，当前还不适合直接实现 pre-triage compression。

## 10. overlap risk audit

关键风险：

| metric | value |
| --- | ---: |
| protected_background_overlap_count | `2893580` |
| protected_background_overlap_rate | `0.92477` |
| risky_suppression_count | `2893580` |

这正是 R-AGG-3 暴露的问题：很多样本同时像 background-like，又带保护信号。

因此：

- 不允许直接 background suppression；
- 不允许把 single_collector / mixed_unknown 当低价值；
- 不允许把 RPKI invalid 或 AS-rel diagnostic 写成 truth；
- 下一步必须先修 `family_hint` mapping / signal priority。

## 11. stop-loss 标准和结果

本轮 stop-loss 触发：

| criterion | result |
| --- | --- |
| protected_background_overlap_rate too high | triggered |
| risky_suppression_rate too high | triggered |
| family_hint mixed_unknown rate too high | triggered |

未触发但仍需记录：

- gray_zone_rate = `0.070518`，没有超过 0.5；
- rpki_coverage = `0.550384`，可用于保护性 triage，但不是 truth；
- asrel_diagnostic_coverage = `1.0`，但 aligned AS-rel incident join 仍未完成。

Stop-loss decision:

`do_not_enter_R_EVID_1_yet`

Recommended action:

`R-AGG-4 family_hint mapping repair, then rerun R-EVID-0 before implementation`

## 12. 后续 learning 层定位

learning layer postponed。

未来 learning 必须等 Raw Incident 和 Evidence-grounded Incident 更稳定后再做。它的输入应是 evidence-grounded incidents，而不是旧 final labels 或简单 rule scores。

未来 learning 目标：

- BEAM-style semantic learning；
- semantic priority；
- low false positive triage；
- component / incident ranking；
- should-split / should-review calibration。

禁止：

- 不做 attack/benign classifier；
- 不覆盖 verifier hard rules；
- 不把 protected/suppressible/gray-zone 当 truth label；
- 不用 learning 隐藏 AS-rel snapshot drift 或 RPKI/communities 缺失。

## 13. 本轮结论

R-EVID-0 证明轻量证据通道是可审计的：

- Raw Incident lookup keys 可用；
- RPKI cache 可本地 join，coverage `0.550384`；
- event-entry rel diagnostic 可 exact join，coverage `1.0`；
- time_scope、candidate_reason_set、weak_signal_tags、family_hint 基本可用；
- communities / NO_EXPORT 仍未进入 Raw Incident。

但它也证明现在不能进入实现版 suppression：

- protected_suspicious rate 太高；
- suppressible_background_like 为 0；
- protected/background overlap rate 高达 `0.92477`；
- mixed_unknown 仍然太高；
- family_hint mapping repair 是 R-EVID-1 前置。

本轮不输出 truth label、不训练 learning、不做最终压缩。
