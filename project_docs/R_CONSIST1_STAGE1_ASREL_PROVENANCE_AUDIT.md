# R-CONSIST-1 Stage 1 AS-rel Provenance Audit

最后更新：2026-05-23

## 本轮为什么要做

R-LOCK-1 已经把系统锁定为三层架构：

```text
Stage 1 Monitor-triggered Incident Construction
  -> Stage 2 Evidence-constrained Verification
  -> Stage 3 Component-aware Learning Triage
  -> Top-K Review Queue
```

Stage 2 已经使用 2024-near CAIDA AS Relationship cache：

- cache: `data/evidence/as_relationships/as_rel_2024-04-01.parquet`
- metadata: `data/evidence/as_relationships/as_rel_2024-04-01.metadata.json`
- snapshot date: `2024-04-01`
- run date: `2024-04-16`
- alignment delta: `15` days

但 Stage 1 早期工单生成可能使用过旧的 2017 CAIDA AS-rel，也可能只把 AS-rel 当弱特征或上下文字段。如果 Stage 1 与 Stage 2 混用未说明的 AS-rel snapshot，最终论文主实验会被 reviewer 质疑 evidence provenance 不一致。

本轮只做 provenance / consistency audit，不重跑 Stage 1，不修改任何实验结果，不修改 verifier verdict，不下载新证据，不训练 learning layer。

## Stage 1 与 Stage 2 的 AS-rel 使用边界

Stage 1 可以使用 AS-rel 作为 monitor-triggered incident construction 的弱信号或上下文字段。例如：

- `rel_seq`
- `rel_unknown_cnt`
- `rel_has_unknown`
- path plausibility / weak path context

这些字段不能被解释为 route-leak truth，也不能成为 attack/benign label。

Stage 2 使用 AS-rel 时是 verifier evidence。它必须带有：

- provider;
- snapshot date;
- run date alignment;
- evidence state;
- confidence cap;
- conflict / insufficient / abstain behavior。

因此，两层可以消费同类 evidence，但职责不同：Stage 1 是 weak trigger/context，Stage 2 是 evidence-constrained verification。

## 现实系统为什么要统一 evidence cache

最终主实验应尽量使用同一版本 evidence cache，至少要显式报告漂移风险。否则会出现：

- Stage 1 的 weak/path fields 来自旧 AS-rel；
- Stage 2 的 verifier evidence 来自 2024-near AS-rel；
- 同一个 incident 同时携带两个不同时间快照的 AS-rel 语义；
- reviewer 可以质疑输出排序、消融、path evidence 的一致性。

统一 cache 不等于把 AS-rel 当 truth。它只是保证证据来源可追溯、可复现、可防守。

## Source Discovery 结果

审计脚本：

- `scripts/run_r_consist1_stage1_asrel_provenance_audit.py`

输出目录：

- `outputs/r_consist1_stage1_asrel_provenance_audit_v01/`

关键发现：

- Stage 1 AS-rel detected: `yes`
- inferred Stage 1 snapshot: `2017-07-01`
- inferred Stage 1 path: `data/caida/as-relationships/serial-2/20170701.as-rel2.txt`
- Stage 2 snapshot: `2024-04-01`
- consistency status: `likely_inconsistent`
- consistency risk level: `high`

主要证据：

- `scripts/04_annotate_caida_rel.py` 默认 `--caida-rel` 指向 `20170701.as-rel2.txt`。
- `scripts/run.py` 与 `scripts/run_s2a_downstream_from_raw.py` 也保留 2017 CAIDA AS-rel 默认源。
- `scripts/build_event_units.py` 会从 rel-annotated input 保留 `rel_seq`, `rel_unknown_cnt`, `rel_has_unknown`。
- Stage 2 R-2C-P0b/P1/P2 使用 `2024-04-01` versioned AS-rel cache。

## Output Schema Audit 结果

审计扫描了 fixed run root 与相关 S2/S3/R 输出 schema。观察到的 AS-rel / path weak-signal 字段包括：

- `rel_seq`
- `rel_unknown_cnt`
- `rel_has_unknown`
- `path_plausibility`
- `plausibility_bucket`
- `path_signature`
- `triplet_signature`
- `relation_sequence`

解释：

- `rel_seq`, `rel_unknown_cnt`, `rel_has_unknown` 是 AS-rel-derived fields。
- `path_signature` / `triplet_signature` 来自 AS path 文本，不等价于 AS-rel snapshot。
- `path_plausibility` / `plausibility_bucket` 会消费 relation unknown / path plausibility context，因此需要在最终主实验中保证 provenance 清晰。

## Rule Dependency Audit 结果

审计发现三类依赖：

1. Hard field creation dependency
   - `scripts/04_annotate_caida_rel.py`
   - 负责从 CAIDA AS-rel 文件生成 `rel_seq`, `rel_unknown_cnt`, `rel_has_unknown`。

2. Weak/path evidence feature dependency
   - `scripts/build_historical_baseline.py`
   - `scripts/run_s3c1_visibility_path_plausibility_pilot.py`
   - `scripts/run_s3c1b_penalty_calibration.py`
   - `scripts/run_s3c2_gate_evidence_ablation.py`
   - 这些脚本可能因为 AS-rel snapshot 改变而改变 path plausibility / gate-evidence ablation 相关输出。

3. Incident grouping mostly no direct AS-rel dependency
   - `scripts/build_incident_aggregation.py` 使用 `path_signature` / `triplet_signature`，主要来自 AS path text。
   - 当前审计未发现 incident grouping 直接依赖 `rel_seq` 改变。

## Consistency Check 结果

| Item | Value |
| --- | --- |
| Stage 1 AS-rel detected | `yes` |
| Stage 1 snapshot | `2017-07-01` |
| Stage 1 path | `data/caida/as-relationships/serial-2/20170701.as-rel2.txt` |
| Stage 2 snapshot | `2024-04-01` |
| Stage 2 path | `data/evidence/as_relationships/as_rel_2024-04-01.parquet` |
| Same snapshot | `false` |
| Same provider | `true` |
| Consistency status | `likely_inconsistent` |
| Consistency risk level | `high` |

## Impact Scope

| Layer | Likely impact | Required replay scope |
| --- | --- | --- |
| `event_units` AS-rel fields | `medium` | `path_feature_reannotation_only` |
| S3-C path plausibility | `medium` | `path_feature_reannotation_only` |
| candidate / score / gate / augment | `low` for direct rel dependency | `no_replay_needed` unless S3-C outputs are included |
| incident membership / tickets | `none` to `low` | `no_replay_needed` |

重要边界：

- 本轮没有证明 candidate set 一定会变。
- 本轮没有证明 incident grouping 一定会变。
- 本轮证明的是：如果最终论文使用 Stage 1 AS-rel-derived weak/path fields，就必须统一 snapshot 或报告 drift/impact analysis。

## Recommended Next Action

推荐下一步：

```text
r_consist2_aligned_reannotation
```

理由：

- Stage 1 看起来保留了 legacy `2017-07-01` AS-rel-derived fields；
- Stage 2 已使用 `2024-04-01` AS-rel cache；
- 当前主要风险集中在 rel annotation fields 与 S3-C path plausibility，不是全链路 incident grouping；
- 因此下一步应先做 aligned reannotation / impact comparison，而不是盲目 full Stage 1 replay。

R-CONSIST-2 可选分支：

- 如果 reannotation 只改变 reporting / weak path fields：保留为 metadata + impact analysis；
- 如果 reannotation 改变 candidate/score/gate/incident membership：再升级为 aligned Stage 1 downstream replay；
- 如果确认某些最终主结果不消费 stale rel fields：可以将旧字段明确降级为 historical diagnostic。

## 当前限制

- 审计依赖代码、metadata 和 schema 发现，不等价于重跑结果比较。
- fixed run root 当前主要保留 incident parquet，event/candidate/gate/final 的部分 provenance 需要从代码和历史输出推断。
- 未比较 2017 vs 2024 AS-rel 对每条 AS path 的具体差异。
- 未改变 verifier verdict，也未新增 route-leak / benign label。

## 与 CCF-A 目标和 Reviewer Defense 的关系

R-CONSIST-1 的价值不是提升检测数值，而是补上顶会审稿会追问的 evidence provenance 严谨性：

- 同类 external evidence 必须 versioned；
- Stage 1 weak trigger 与 Stage 2 verifier evidence 必须分清职责；
- stale AS-rel 不能被包装成 strong evidence；
- final main experiment 不能混用未说明的 AS-rel snapshot；
- 如果混用不可避免，必须报告 drift / impact analysis。

论文写法建议：

> We treat AS relationship data as versioned inferred evidence. Stage 1 may use it only as monitor-side weak context, whereas Stage 2 consumes an aligned evidence cache under explicit confidence caps. Final experiments either use a consistent snapshot across both stages or report a drift/impact analysis.
