# 项目文档入口

这个目录是当前仓库的长期维护文档入口，后续默认优先维护这里的核心入口文件：

- `HANDOFF.md`：项目交接与当前状态总览
- `EXPERIMENT_MAINLINE.md`：实验主线总表
- `PROJECT_DECISION_REGISTER.md`：项目级科研决策总表

当前战略状态：

- Phase R 已启动。
- 项目主线从 forged-origin weak-signal detector 重定位为 adversarially robust multi-evidence BGP incident verification and triage。
- S3-A 到 S3-D2B 是 Phase R 的 historical groundwork，不是失败线。
- 新增 Phase R 入口文档：
  - `PHASE_R_PROBLEM_REFRAMING.md`
  - `VERIFIER_REDESIGN_ROADMAP.md`
  - `LEARNING_LAYER_POSITIONING.md`
  - `PAPER_PROBLEM_STATEMENT.md`
- 项目级决策总表：
  - `PROJECT_DECISION_REGISTER.md`
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
- Phase R-AGG-ENTRY-0 Raw Incident entry point audit 文档：
  - `R_AGG_ENTRY_0_RAW_INCIDENT_ENTRY_AUDIT.md`
- Phase R-AGG-1 Raw Incident Dossier schema 文档：
  - `R_AGG_1_RAW_INCIDENT_DOSSIER_SCHEMA.md`
- Phase R-AGG-2 Raw Incident prototype aggregation 文档：
  - `R_AGG_2_RAW_INCIDENT_PROTOTYPE_AGGREGATION.md`
- Phase R architecture lock 文档：
  - `ARCHITECTURE_MINIMALITY_AND_ABLATION_PLAN.md`
  - `SYSTEM_OUTPUT_SCHEMA_SIMPLIFIED.md`
- CCF-A target-line guardrail：
  - `CCFA_TARGET_LINE_AND_EXPERIMENT_GUARDRAILS.md`

## Current Phase Guardrail

Current phase: Phase R-AGG-2 has completed Raw Incident prototype aggregation. The project is no longer optimizing old final labels; it is moving from the legacy event-level detector chain toward explainable incident construction plus evidence grounding. R-AGG-ENTRY-0 compared event, candidate, scored, gated, augmented, and final entry points and recommends `candidate-entry` as the main Raw Incident construction entry, with `event-entry` and `scored-entry` as auxiliary references. R-AGG-1 records the schema groups, candidate-entry field mapping, legacy-reference guardrails, and downstream hooks for Evidence-grounded Incident, poisoning benchmark, and future semantic learning. R-AGG-2 now builds prototype raw incidents using candidate-entry plus event-entry time repair.

R-AGG-ENTRY-0 locks the following guardrail: final labels are weak workflow signals, not truth labels. The old final layer can provide context, but direct final-level 21w aggregation must not become the paper's main incident口径 without entry-point justification. After R-AGG-2, the next step is R-AGG-3 aggregation quality audit, followed by Evidence-grounded Incident construction.

R-AGG-1 locks the following guardrail: candidate-entry is the Raw Incident primary source, but schema design alone does not implement final aggregation, attach external evidence, or train learning. R-AGG-2 keeps that boundary: it performs Raw Incident prototype aggregation only, with event-entry time repair, and still does not use final-entry as the main source. The next step is R-AGG-3 aggregation quality audit or Evidence-grounded Incident design.

The new `PROJECT_DECISION_REGISTER.md` remains the project-level decision table for architecture boundaries, output taxonomy, Stage 1 / Stage 2 evidence reuse, component purity, abstain handling, communities / NO_EXPORT propagation, AS-rel consistency, learning-layer timing, and Raw Incident entry decisions. R-LOCK-1 still locks the paper-facing system as a minimal three-stage architecture: Stage 1 Monitor-triggered Incident Construction, Stage 2 Evidence-constrained Verification, and Stage 3 Component-aware Learning Triage before the Top-K Review Queue. R-DOC-1 also locks the no-category-explosion output taxonomy: `primary_family`, `observability_mode`, `verifier_state`, `evidence_tags`, confidence, rank, action, and `why_not_confirmed`. R-CONSIST-1 found a versioned evidence provenance risk: Stage 1 annotation code defaults to CAIDA `2017-07-01` AS-rel while Stage 2 R-2C uses the aligned `2024-04-01` AS-rel cache; recommended follow-up remains `r_consist2_aligned_reannotation`. R-2D-0 found raw `communities` fields and parseable `NO_EXPORT` / `NO_ADVERTISE` / `NOPEER`, but communities are retained only at raw-update layer and are not incident join-ready. Do not continue the legacy S3 detector-quality line unless explicitly requested. Legacy high/needs/low and P1/P2/P3 outputs are not ground truth. R-2A/R-2B/R-2C/R-2D verifier/evidence outputs are not ground truth. Final main experiments must use consistent versioned evidence cache snapshots or report drift/impact analysis. The learning layer sits between the verifier and Top-K review; it is an incident/component-aware ranker and calibrator, not an attack/benign classifier and not a verifier override.

Poisoning benchmark retained: R-3 remains a core evaluation direction for showing value under incomplete and poisonable public monitors. Learning layer postponed: formal learning waits until Raw Incident Dossier and Evidence-grounded Incident schemas are stable, and future learning should move toward BEAM-style semantic learning for representation and prioritization rather than legacy rule re-scoring. family_hint is semantic hint, not attack label.

维护规则：

- 不再继续新增“按日期拆开的 handoff 文件”作为默认入口。
- 不再把实验主线拆成多张总表。
- 后续新实验结束后，优先更新这两个文件。
- 旧路径下的文档先保留，作为历史归档，不再作为默认阅读入口。

默认阅读顺序：

1. `project_docs/HANDOFF.md`
2. `project_docs/EXPERIMENT_MAINLINE.md`
3. `project_docs/PROJECT_DECISION_REGISTER.md`
4. `project_docs/PHASE_R_PROBLEM_REFRAMING.md`
5. `project_docs/VERIFIER_REDESIGN_ROADMAP.md`
6. `project_docs/R1_VERIFIER_STATE_MACHINE.md`
7. `project_docs/R1_EVIDENCE_TYPES_AND_VERDICTS.md`
8. `project_docs/R2A_LEGALITY_FIRST_VERIFIER_SCAFFOLD.md`
9. `project_docs/R2B0_EVIDENCE_READINESS_AUDIT.md`
10. `project_docs/R2B_P0B_HISTORICAL_VRP_CACHE.md`
11. `project_docs/R2B_VRP_AWARE_VERIFIER_SMOKE.md`
12. `project_docs/R2B_OPS_REALTIME_BURDEN_AUDIT.md`
13. `project_docs/R2C0_PATH_EVIDENCE_READINESS_AUDIT.md`
14. `project_docs/R2C_P0B_2024_ASREL_CACHE.md`
15. `project_docs/R2C_P1_PATH_RELATION_LOOKUP_SMOKE.md`
16. `project_docs/R2C_P2_PATH_LEGALITY_VERIFIER_SMOKE.md`
17. `project_docs/ARCHITECTURE_MINIMALITY_AND_ABLATION_PLAN.md`
18. `project_docs/SYSTEM_OUTPUT_SCHEMA_SIMPLIFIED.md`
19. `project_docs/R2D0_COMMUNITIES_FIELD_AVAILABILITY_AUDIT.md`
20. `project_docs/R_CONSIST1_STAGE1_ASREL_PROVENANCE_AUDIT.md`
21. `project_docs/R_AGG_ENTRY_0_RAW_INCIDENT_ENTRY_AUDIT.md`
22. `project_docs/R_AGG_1_RAW_INCIDENT_DOSSIER_SCHEMA.md`
23. `project_docs/R_AGG_2_RAW_INCIDENT_PROTOTYPE_AGGREGATION.md`
24. `project_docs/CCFA_TARGET_LINE_AND_EXPERIMENT_GUARDRAILS.md`
25. `project_docs/LEARNING_LAYER_POSITIONING.md`
26. 如需更细的正式资产定位，再看 `论文/实验资产索引_v01.md`
