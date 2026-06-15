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
- Clean mainline control 文档：
  - `CLEAN_MAINLINE_EXPERIMENT_PLAN.md`
  - `R_CLEAN_0_DATA_EVIDENCE_CLEAN_CONTRACT.md`
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
- Phase R-AGG-3 Raw Incident aggregation quality audit 文档：
  - `R_AGG_3_RAW_INCIDENT_QUALITY_AUDIT.md`
- Phase R-EVID-0 lightweight evidence pre-triage design 文档：
  - `R_EVID_0_LIGHTWEIGHT_EVIDENCE_PRETRIAGE_DESIGN.md`
- Phase R-RESET-1 mainline pivot 文档：
  - `PIPELINE_RESET_MAINLINE_R_RESET_1.md`
  - `NOISE_FILTER_AND_MULTI_ATTACK_JUDGMENT_PLAN.md`
  - `POISONING_AWARE_SYSTEM_PROBLEM_STATEMENT.md`
- Phase R-NOISE-0 obvious noise separability audit 文档：
  - `R_NOISE_0_OBVIOUS_NOISE_SEPARABILITY_AUDIT.md`
- Phase R-NOISE-1 conservative foreground extraction smoke 文档：
  - `R_NOISE_1_CONSERVATIVE_FOREGROUND_EXTRACTION_SMOKE.md`
- Phase R architecture lock 文档：
  - `ARCHITECTURE_MINIMALITY_AND_ABLATION_PLAN.md`
  - `SYSTEM_OUTPUT_SCHEMA_SIMPLIFIED.md`
- CCF-A target-line guardrail：
  - `CCFA_TARGET_LINE_AND_EXPERIMENT_GUARDRAILS.md`

## Current Phase Guardrail

Current phase: Phase R-CLEAN-0 has locked the clean mainline experiment plan and data/evidence clean contract. R-NOISE-1 remains a completed provisional foreground smoke, not a final clean experiment result. `full candidate-entry incident aggregation stopped` remains the paper-facing mainline. The project now follows a clean dependency chain: clean data/evidence contract -> aligned sidecars -> benchmark/label protocol -> foreground validation -> multi-attack judgment -> attack-like incident explanation.

R-AGG-ENTRY-0 locks the following guardrail: final labels are weak workflow signals, not truth labels. The old final layer can provide context, but direct final-level 21w aggregation must not become the paper's main incident口径 without entry-point justification. R-AGG-3 keeps this boundary: it does not modify aggregation logic, does not implement background suppression, does not implement safe merge, and does not produce any truth label.

R-AGG-1/R-AGG-2/R-AGG-3/R-EVID-0 are preserved as stop-loss evidence. R-AGG-2 produced `3128971` raw incidents with compression ratio `1.09656`; R-AGG-3 found `possible_background_like_rate=0.995288` but high-value overlap was too large; R-EVID-0 found `protected_suspicious_rate=0.929482`, `suppressible_background_like_rate=0.0`, and `protected_background_overlap_rate=0.92477`. These results prove that candidate-first full incident aggregation and direct evidence pre-triage compression are not safe as the first mainline stage.

The new `PROJECT_DECISION_REGISTER.md` remains the project-level decision table. R-RESET-1 supersedes the ranker-first reading of the learning layer: the next learning target is a `multi-attack judgment layer`, not semantic ranking and not a single attack/benign classifier. Expected operational outputs include `suspicious_forged_origin`, `suspicious_route_leak`, `suspicious_path_manipulation`, `suspicious_stealth_visibility`, `poisoning_or_evasion_suspected`, `background_noise`, and `uncertain_need_evidence`. `background is not ranked` in the primary human-facing output, but background is still not confirmed benign. Final main experiments must report low false positive behavior, false-negative / must-keep miss risk, background compression, evidence explanation, and poisoning/evasion robustness.

Poisoning benchmark retained and elevated: `poisoning/evasion robustness is core`, not an appendix. R-2D-0 still matters because NO_EXPORT / communities affect monitor evasion, but communities are not incident-ready yet. RPKI invalid is not attack truth. AS-rel diagnostic is not route leak truth. background-like is not benign. R-CLEAN-0 fixes the current data contract: RPKI `2024-04-16` is aligned and allowed with truth boundaries; CAIDA AS-rel `2024-04-01` is available but must enter through a new 2024-aligned sidecar; old 2017-derived `rel_*` fields are forbidden in new decisions; raw NO_EXPORT exists but is not event/candidate-ready; legacy final/high/needs are audit references only. Next default step is R-ASREL-CLEAN-0 aligned AS-rel sidecar, not learning training and not production suppression.

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
26. `project_docs/R_NOISE_0_OBVIOUS_NOISE_SEPARABILITY_AUDIT.md`
27. `project_docs/R_NOISE_1_CONSERVATIVE_FOREGROUND_EXTRACTION_SMOKE.md`
28. `project_docs/CLEAN_MAINLINE_EXPERIMENT_PLAN.md`
29. `project_docs/R_CLEAN_0_DATA_EVIDENCE_CLEAN_CONTRACT.md`
30. 如需更细的正式资产定位，再看 `论文/实验资产索引_v01.md`
