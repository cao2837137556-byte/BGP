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

Current active phase:

```text
R-CLEAN-0 documentation governance and clean data/evidence contract locked.
```

Current next recommended action:

```text
R-ASREL-CLEAN-0:
Build a 2024-aligned AS-rel sidecar for candidate/event rows.
```

Current paper goal:

```text
low-false-positive multi-attack BGP judgment under incomplete,
evasive, and poisonable public BGP monitors
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
- phase-specific reports such as `R_NOISE_1_CONSERVATIVE_FOREGROUND_EXTRACTION_SMOKE.md`, `R_CONSIST1_STAGE1_ASREL_PROVENANCE_AUDIT.md`, and `R2D0_COMMUNITIES_FIELD_AVAILABILITY_AUDIT.md`

If an old document conflicts with `MAINLINE_STATE.md`, trust `MAINLINE_STATE.md` unless a newer decision entry explicitly says otherwise.
