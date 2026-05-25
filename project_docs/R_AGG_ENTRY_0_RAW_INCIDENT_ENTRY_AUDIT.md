# R-AGG-ENTRY-0 Raw Incident Entry Audit

Last updated: 2026-05-25

Status: entry point audit completed as a read-only documentation/scaffold step.

## 1. 本轮任务目标

R-AGG-ENTRY-0 审计旧 7 层 pipeline 中哪一层最适合作为未来 Raw Incident Dossier 的构造入口。

本轮只做只读审计和主线文档固化：

- 不修改旧 7 层主链逻辑；
- 不重新跑 raw/events/baseline/candidate/score/gate/augment/final；
- 不把 `high / needs / low` 当 truth；
- 不把 `P1 / P2 / P3` 当 truth；
- 不产生 attack / benign / normal 标签；
- 不实现最终 incident aggregation；
- 不训练 learning。

Key guardrail: final labels are weak workflow signals, not truth labels.

## 2. 旧 7 层角色回顾

旧链路是：

```text
events -> baseline -> candidates -> scores -> gating -> augmentation -> final
```

在新三阶段架构中，它们不再是最终 detector，而是 Stage 1 的历史弱信号来源：

| Old layer | New role |
| --- | --- |
| events | 最接近 raw observation 的事件单位 |
| baseline | 历史上下文和偏离参照 |
| candidates | weak trigger / candidate reason provider |
| scores | legacy weak ranking hint |
| gating | legacy safety / suppression hint |
| augmentation | uncertain subset enrichment hint |
| final | old workflow label, not truth |

## 3. 为什么不能默认沿用 final 后 21w 聚合

final 后的 21w incident tickets 是历史 S3-A 的有用 groundwork，但不能直接作为新论文主口径的 Raw Incident 起点。

原因很简单：`final_alert_label`、`high`、`needs`、`low` 已经带有旧 score/gate/augment/final 的判断性质。如果直接从 final-entry 聚合，就会把旧 detector 的偏差带进新的 incident 表示，后续 Evidence-grounded Incident 和 learning 都可能学到旧规则，而不是学到证据结构。

所以新的路线应该是：

```text
Raw Incident Dossier
  -> Evidence-grounded Incident
  -> Component-aware semantic learning / Top-K triage
```

而不是：

```text
final labels
  -> 21w final-level incidents
  -> paper truth
```

## 4. Audit Run

脚本：

- `scripts/audit_raw_incident_entry_points.py`

完整本地审计 run：

- `s2a_baseline_v01_pilot_6h_april16`

输出目录：

- `outputs/r_agg_entry_0/s2a_baseline_v01_pilot_6h_april16/`

缺失容错检查：

- `s2a_expanded_v01_pilot_6h_april16`
- 当前本地 expanded run root 只保留 incidents，旧 7 层 parquet 在本地目录中缺失；脚本按设计标记 missing，不中断。

## 5. 字段可用性对比

| entry | rows | unique events | unique prefix-origin | reason coverage | risk coverage | final label coverage | judgment fields | Raw Dossier recovery |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| event-entry | 3431103 | 3431103 | 351104 | 0.0 | 0.0 | 0.0 | 0 | 0.666667 |
| candidate-entry | 3431103 | 3431103 | 351104 | 1.0 | 0.0 | 0.0 | 0 | 0.761905 |
| scored-entry | 1804382 | 1804382 | 84661 | 1.0 | 1.0 | 0.0 | 2 | 0.904762 |
| gated-entry | 1804382 | 1804382 | 84661 | 1.0 | 1.0 | 0.0 | 5 | 0.666667 |
| augmented-entry | 959206 | 959206 | 73626 | 1.0 | 1.0 | 0.0 | 6 | 0.595238 |
| final-entry | 1804382 | 1804382 | 84661 | 1.0 | 1.0 | 1.0 | 9 | 0.666667 |

## 6. 污染风险对比

| entry | field completeness | judgment contamination | noise exposure | aggregation explainability | evidence readiness | learning readiness |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| event-entry | 0.666667 | 0.0 | 1.0 | 0.75 | 1.0 | 0.804167 |
| candidate-entry | 0.761905 | 0.0 | 0.8375 | 1.0 | 1.0 | 0.904762 |
| scored-entry | 0.904762 | 0.333333 | 0.541561 | 1.0 | 1.0 | 0.928571 |
| gated-entry | 0.666667 | 0.833333 | 0.476561 | 0.75 | 0.75 | 0.658333 |
| augmented-entry | 0.595238 | 1.0 | 0.325347 | 0.75 | 0.75 | 0.613095 |
| final-entry | 0.666667 | 1.0 | 0.346561 | 0.75 | 0.75 | 0.641667 |

Interpretation:

- `scored-entry` has strong field completeness, but already contains `risk_score` / `risk_bucket` judgment.
- `candidate-entry` keeps weak-trigger explanation with no legacy judgment fields in this run.
- `final-entry` has the highest judgment contamination and is not suitable as the Raw Incident main entry.

## 7. 六个入口优缺点

### event-entry

Pros:

- closest to raw observation;
- strong evidence lookup readiness: prefix, origin, path, collector, timing;
- no legacy judgment contamination.

Cons:

- noise exposure is highest;
- lacks trigger / candidate reasons;
- requires more aggregation design before becoming a dossier.

### candidate-entry

Pros:

- keeps event-level object keys and collector visibility;
- adds candidate reasons / weak trigger explanation;
- has low judgment contamination;
- best balance for Raw Incident Dossier entry.

Cons:

- still broad and noisy;
- timing is weaker than event-entry in the local schema and may need event join;
- candidate reasons are hints, not labels.

### scored-entry

Pros:

- field completeness is high;
- useful auxiliary weak semantic hints exist.

Cons:

- introduces `risk_score` / `risk_bucket`;
- starts to inherit old scoring bias;
- should not be the primary Raw Incident constructor.

### gated-entry

Pros:

- contains certainty/conflict hints.

Cons:

- strong judgment contamination through `gating_label`;
- inherits gate suppression behavior;
- not suitable as primary Raw Incident entry.

### augmented-entry

Pros:

- has evidence support style fields for uncertain subset.

Cons:

- only covers a subset;
- high judgment contamination;
- augmentation decisions should be auxiliary hints only.

### final-entry

Pros:

- convenient and already compact.

Cons:

- includes `final_alert_label`;
- inherits score/gate/augment/final bias;
- final labels are weak workflow signals, not truth labels;
- not suitable for Raw Incident main entry.

## 8. 推荐主入口

Recommended main entry: `candidate-entry`.

Reason:

- it preserves candidate reasons as weak semantic hints;
- it keeps key object fields for RPKI / AS-rel / communities / NO_EXPORT / ASPA lookup;
- it has much lower judgment contamination than scored/gated/augmented/final;
- it is less raw/noisy than event-entry.

Candidate-entry should create Raw Incident Dossier members, not truth labels.

## 9. 推荐辅助入口

Recommended auxiliary entries:

- `event-entry`: raw observation fallback and timing/collector provenance recovery;
- `scored-entry`: optional weak semantic/ranking hint, with explicit contamination guardrail.

Scored fields may be useful later, but only as legacy weak workflow signals. They should not define incident truth.

## 10. 不推荐入口及原因

Not recommended as primary entries:

- `gated-entry`: gate judgment contamination is high;
- `augmented-entry`: partial subset and high augmentation-label contamination;
- `final-entry`: highest contamination and directly carries old final workflow labels.

These layers may remain as auxiliary features or ablation baselines, but they should not define the Raw Incident Dossier entry point.

## 11. 是否进入 Raw Incident 字段设计

Yes. The next step should be R-AGG-1: Raw Incident Dossier schema design.

Recommended design direction:

- main members from candidate-entry;
- event-entry join for timing and raw observation provenance;
- optional scored-entry weak semantic hints;
- no truth label;
- no final-label-driven aggregation;
- no learning training yet.

## 12. Safety Boundaries

This round:

- does not produce truth label;
- does not train learning;
- does not implement final incident aggregation;
- does not modify old seven-layer pipeline outputs;
- does not claim attack/benign/normal labels.

`background-like is operational suppression`, not confirmed benign.

`family_hint is semantic hint`, not confirmed attack label.

## 13. Relation to Poisoning Benchmark and Learning

Poisoning benchmark retained as a core future evaluation. The reason is that public monitors are incomplete and poisonable, so a top-tier claim needs to show that Raw Incident + Evidence-grounded Incident is more robust than monitor-only/final-label-driven systems.

Learning layer postponed until Raw Incident Dossier and Evidence-grounded Incident schemas are stable.

Future learning should move toward BEAM-style semantic learning: learn incident/component/evidence representation and Top-K prioritization, not rule re-scoring of old final labels.
