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
- CCF-A target-line guardrail：
  - `CCFA_TARGET_LINE_AND_EXPERIMENT_GUARDRAILS.md`

## Current Phase Guardrail

Current phase: Phase R-2B completed. R-1 verifier state machine design has been completed and accepted. R-2A legality-first verifier scaffold completed a 50k smoke run, R-2B-0 evidence readiness audit completed a full incident-level audit on `217165` fixed S2 incidents, R-2B-P0b materialized aligned historical VRP/RPKI evidence for `2024-04-16`, and R-2B connected that evidence back into a component-aware verifier smoke. The next implementation step is R-2C legality/path refinement, with R-3 poisoning benchmark design and L1 component-aware learner design following. Do not continue the legacy S3 detector-quality line unless explicitly requested. S3-A to S3-D2B are historical groundwork for the verifier-centric redesign, not the active optimization target. Legacy high/needs/low and P1/P2/P3 outputs are not ground truth. R-2A verifier verdicts, R-2B-0 readiness states, R-2B-P0b RPKI lookup statuses, and R-2B VRP-aware verdicts are also not ground truth. RPKI valid is not benign, RPKI invalid is not confirmed attack, and RPKI unknown is not normal. Current target line is CCF-A / top-tier networking or security venue; SCI Q2 is fallback only. The learning layer is postponed and will only be used as an incident-level component-aware ranker/calibrator after verifier-supported targets exist. No new detector-score experiments should be launched before R-2C/R-3 verifier and robustness work is explicitly started.

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
11. `project_docs/CCFA_TARGET_LINE_AND_EXPERIMENT_GUARDRAILS.md`
12. `project_docs/LEARNING_LAYER_POSITIONING.md`
13. 如需更细的正式资产定位，再看 `论文/实验资产索引_v01.md`
