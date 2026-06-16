# Project Docs Entry

This directory now uses a lightweight documentation system.

## Default Reading Order

Read only these by default:

1. `project_docs/MAINLINE_STATE.md`
   - current trusted state;
   - active data / evidence contract;
   - current blockers;
   - next single recommended action;
   - short experiment map.

2. `project_docs/PROJECT_DECISION_REGISTER.md`
   - major route decisions;
   - why a direction changed;
   - consequences;
   - active / superseded status.

3. The specific phase document for the current task, as linked from `MAINLINE_STATE.md`.

## Current Active State

Do not store dynamic current-state details in this README.

For the current phase, current blocker, paper goal, and next recommended action, read:

```text
project_docs/MAINLINE_STATE.md
```

## Maintenance Rule

Normal experiment:

1. Create or update the experiment's own phase document.
2. Update `MAINLINE_STATE.md`.
3. Do not update every old mainline document.

Major route change:

1. Do the normal experiment maintenance.
2. Add one entry to `PROJECT_DECISION_REGISTER.md`.

README is only a navigation pointer. It should not become an experiment log.

## Archive / Topic References

The following files are still useful, but they are no longer every-round maintenance targets:

- `HANDOFF.md`
- `EXPERIMENT_MAINLINE.md`
- `CCFA_TARGET_LINE_AND_EXPERIMENT_GUARDRAILS.md`
- `LEARNING_LAYER_POSITIONING.md`
- `VERIFIER_REDESIGN_ROADMAP.md`
- `CLEAN_MAINLINE_EXPERIMENT_PLAN.md`
- `R_CLEAN_0_DATA_EVIDENCE_CLEAN_CONTRACT.md`
- phase-specific reports such as `R_NOISE_1_CONSERVATIVE_FOREGROUND_EXTRACTION_SMOKE.md`, `R_ASREL_CLEAN_0_2024_ASREL_SIDECAR.md`, `R_COMM_CLEAN_0_COMMUNITY_NOEXPORT_SIDECAR.md`, `R_CONSIST1_STAGE1_ASREL_PROVENANCE_AUDIT.md`, and `R2D0_COMMUNITIES_FIELD_AVAILABILITY_AUDIT.md`

If an old document conflicts with `MAINLINE_STATE.md`, trust `MAINLINE_STATE.md` unless a newer decision entry explicitly says otherwise.
