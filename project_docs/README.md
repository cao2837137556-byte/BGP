# 项目文档入口

这个目录是当前仓库的长期维护文档入口，后续默认只维护这里的两份核心文件：

- `HANDOFF.md`：项目交接与当前状态总览
- `EXPERIMENT_MAINLINE.md`：实验主线总表

当前战略状态：

- Phase R 已启动。
- 项目主线从 forged-origin weak-signal detector 重定位为 adversarially robust multi-evidence BGP incident verification and triage。
- S3-A 到 S3-D2B 是 Phase R 的 historical groundwork，不是失败线。
- 新增 Phase R 入口文档：
  - `PHASE_R_PROBLEM_REFRAMING.md`
  - `VERIFIER_REDESIGN_ROADMAP.md`
  - `LEARNING_LAYER_POSITIONING.md`
  - `PAPER_PROBLEM_STATEMENT.md`
- Phase R-1 设计文档：
  - `R1_VERIFIER_STATE_MACHINE.md`
  - `R1_EVIDENCE_TYPES_AND_VERDICTS.md`
- Phase R-2A scaffold 文档：
  - `R2A_LEGALITY_FIRST_VERIFIER_SCAFFOLD.md`
- Phase R-2B-0 readiness audit 文档：
  - `R2B0_EVIDENCE_READINESS_AUDIT.md`
- Phase R-2B-P0b historical VRP cache 文档：
  - `R2B_P0B_HISTORICAL_VRP_CACHE.md`
- Phase R-2B verifier smoke 文档：
  - `R2B_VRP_AWARE_VERIFIER_SMOKE.md`
- Phase R-2B-OPS operational guardrail 文档：
  - `R2B_OPS_REALTIME_BURDEN_AUDIT.md`
- Phase R-2C-0 path evidence readiness 文档：
  - `R2C0_PATH_EVIDENCE_READINESS_AUDIT.md`
- Phase R-2C-P0b 2024-near AS relationship cache 文档：
  - `R2C_P0B_2024_ASREL_CACHE.md`
- Phase R-2C-P1 path relation lookup smoke 文档：
  - `R2C_P1_PATH_RELATION_LOOKUP_SMOKE.md`
- Phase R-2C-P2 path-legality verifier smoke 文档：
  - `R2C_P2_PATH_LEGALITY_VERIFIER_SMOKE.md`
- Phase R-2D-0 communities / NO_EXPORT field availability audit 文档：
  - `R2D0_COMMUNITIES_FIELD_AVAILABILITY_AUDIT.md`
- Phase R-CONSIST-1 Stage 1 AS-rel provenance audit 文档：
  - `R_CONSIST1_STAGE1_ASREL_PROVENANCE_AUDIT.md`
- Phase R architecture lock 文档：
  - `ARCHITECTURE_MINIMALITY_AND_ABLATION_PLAN.md`
  - `SYSTEM_OUTPUT_SCHEMA_SIMPLIFIED.md`
- CCF-A target-line guardrail：
  - `CCFA_TARGET_LINE_AND_EXPERIMENT_GUARDRAILS.md`

## Current Phase Guardrail

Current phase: Phase R-CONSIST-1 completed after R-2D-0. R-LOCK-1 locks the paper-facing system as a minimal three-stage architecture: Stage 1 Monitor-triggered Incident Construction, Stage 2 Evidence-constrained Verification, and Stage 3 Component-aware Learning Triage before the Top-K Review Queue. R-CONSIST-1 found a versioned evidence provenance risk: Stage 1 annotation code defaults to CAIDA `2017-07-01` AS-rel (`data/caida/as-relationships/serial-2/20170701.as-rel2.txt`) while Stage 2 R-2C uses the aligned `2024-04-01` AS-rel cache (`data/evidence/as_relationships/as_rel_2024-04-01.parquet`), so consistency status is `likely_inconsistent` and risk level is `high` if stale Stage 1 AS-rel-derived weak/path fields are used in final main results. Recommended next action is `r_consist2_aligned_reannotation`, not immediate full Stage 1 replay, because current audit localizes likely impact to `rel_seq`, `rel_unknown_cnt`, `rel_has_unknown`, and S3-C path plausibility fields rather than direct incident grouping. R-2D-0 also remains important: raw `communities` fields exist in `864` raw-update parquet files with well-known community rows `NO_EXPORT=223410`, `NO_ADVERTISE=1240`, `NO_EXPORT_SUBCONFED=0`, `NOPEER=5634`, but communities are retained only at raw-update layer and are not incident join-ready. Do not continue the legacy S3 detector-quality line unless explicitly requested. Legacy high/needs/low and P1/P2/P3 outputs are not ground truth. R-2A/R-2B/R-2C/R-2D verifier/evidence outputs are not ground truth. RPKI valid is not benign, RPKI invalid is not confirmed attack, RPKI unknown is not normal, stale AS-rel is not strong evidence, AS-rel violation is not confirmed route leak, AS-rel path legality is not benign, AS-rel-only support is not enough for strong verdicts, possible valley-free diagnostics are not confirmed route leaks, missing path evidence is not benign, NO_EXPORT present is not a confirmed attack, NO_EXPORT absent is not safe, and low visibility is not confirmed NO_EXPORT. Final main experiments must use consistent versioned evidence cache snapshots or report drift/impact analysis. The learning layer sits between the verifier and Top-K review; it is an incident/component-aware ranker and calibrator, not an attack/benign classifier and not a verifier override.

维护规则：

- 不再继续新增“按日期拆开的 handoff 文件”作为默认入口。
- 不再把实验主线拆成多张总表。
- 后续新实验结束后，优先更新这两个文件。
- 旧路径下的文档先保留，作为历史归档，不再作为默认阅读入口。

默认阅读顺序：

1. `project_docs/HANDOFF.md`
2. `project_docs/EXPERIMENT_MAINLINE.md`
3. `project_docs/PHASE_R_PROBLEM_REFRAMING.md`
4. `project_docs/VERIFIER_REDESIGN_ROADMAP.md`
5. `project_docs/R1_VERIFIER_STATE_MACHINE.md`
6. `project_docs/R1_EVIDENCE_TYPES_AND_VERDICTS.md`
7. `project_docs/R2A_LEGALITY_FIRST_VERIFIER_SCAFFOLD.md`
8. `project_docs/R2B0_EVIDENCE_READINESS_AUDIT.md`
9. `project_docs/R2B_P0B_HISTORICAL_VRP_CACHE.md`
10. `project_docs/R2B_VRP_AWARE_VERIFIER_SMOKE.md`
11. `project_docs/R2B_OPS_REALTIME_BURDEN_AUDIT.md`
12. `project_docs/R2C0_PATH_EVIDENCE_READINESS_AUDIT.md`
13. `project_docs/R2C_P0B_2024_ASREL_CACHE.md`
14. `project_docs/R2C_P1_PATH_RELATION_LOOKUP_SMOKE.md`
15. `project_docs/R2C_P2_PATH_LEGALITY_VERIFIER_SMOKE.md`
16. `project_docs/ARCHITECTURE_MINIMALITY_AND_ABLATION_PLAN.md`
17. `project_docs/SYSTEM_OUTPUT_SCHEMA_SIMPLIFIED.md`
18. `project_docs/R2D0_COMMUNITIES_FIELD_AVAILABILITY_AUDIT.md`
19. `project_docs/R_CONSIST1_STAGE1_ASREL_PROVENANCE_AUDIT.md`
20. `project_docs/CCFA_TARGET_LINE_AND_EXPERIMENT_GUARDRAILS.md`
21. `project_docs/LEARNING_LAYER_POSITIONING.md`
22. 如需更细的正式资产定位，再看 `论文/实验资产索引_v01.md`
