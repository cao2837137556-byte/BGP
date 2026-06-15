# MAINLINE STATE

Last updated: 2026-06-15

Status: active authoritative mainline state.

This is the first file to read before any new experiment. It records the current trusted state, the active experiment order, and the short experiment map. Detailed phase reports remain in their own files and are not repeatedly edited.

## 1. Documentation Rule

The project now maintains only two active mainline documents:

1. `project_docs/MAINLINE_STATE.md`
   - current truth;
   - active data / evidence contract;
   - current blockers;
   - next single recommended action;
   - short experiment map.

2. `project_docs/PROJECT_DECISION_REGISTER.md`
   - major route decisions only;
   - why a route changed;
   - consequences;
   - active / superseded status.

Every experiment may still create its own detailed phase document. Those phase documents are evidence archives. They should not be repeatedly edited unless a factual correction is needed.

Do not update README, HANDOFF, EXPERIMENT_MAINLINE, CCFA, LEARNING, or VERIFIER docs after every experiment. Treat them as navigation or historical / topical references unless a major paper-level framing change requires an explicit update.

## 2. Current Paper Goal

The current paper goal is:

```text
low-false-positive multi-attack BGP judgment under incomplete,
evasive, and poisonable public BGP monitors
```

This is not:

- a legacy high / needs / low detector;
- a full candidate-entry incident aggregation system;
- a benign / attack classifier trained from workflow labels;
- a pure ranking or review queue system.

Attack families that must remain visible:

- forged-origin / origin hijack;
- route leak / valley-like path;
- path manipulation / suspicious path change;
- stealth visibility / NO_EXPORT / monitor evasion;
- poisoning / crafted announcement evasion.

## 3. Current Truth Table

| Item | Current Status | Source Phase | Confidence | Notes |
|---|---|---|---|---|
| Paper target | low-FP multi-attack judgment under poisonable/incomplete monitors | R-RESET-1 / R-CLEAN-0 | active | Not ordinary detector, not legacy ranking |
| Candidate-first raw incident aggregation | stopped as mainline | R-AGG-2 / R-AGG-3 / R-EVID-0 | high | Useful stop-loss evidence only |
| R-NOISE-1 foreground smoke | provisional smoke only | R-NOISE-1 / R-CLEAN-0 | medium | Not recall proof, not benign proof |
| RPKI evidence | usable as aligned origin evidence | R-2B-P0b / R-CLEAN-0 | high | `2024-04-16`; invalid is not attack; valid is not benign |
| CAIDA AS-rel evidence | clean 2024 sidecar built | R-ASREL-CLEAN-0 | high | `2024-04-01`; event join rate `1.0`; old 2017 `rel_*` remains forbidden |
| Old Stage 1 `rel_*` fields | forbidden in new decisions | R-CONSIST-1 / R-CLEAN-0 | high | Likely `2017-07-01` CAIDA-derived |
| Raw communities / NO_EXPORT | available at raw layer only | R-2D-0 / R-CLEAN-0 | high | Not candidate/event-ready; absence is not safe |
| Legacy final/high/needs/low | audit reference only | R-AGG-ENTRY-0 / R-CLEAN-0 | high | Not truth, not labels, not hard guards |
| P1/P2/P3 | audit reference only | R-CLEAN-0 | high | Not truth, not labels |
| Learning | blocked from training | R-CLEAN-0 | high | Design may happen later, training waits for clean sidecars + labels |
| Poisoning/evasion robustness | core goal, not yet proven | R-RESET-1 / R-CLEAN-0 | active blocker | Needs benchmark / controlled scenarios |

## 4. Active Data / Evidence Contract

Allowed now:

- candidate/event native routing fields with provenance:
  - prefix;
  - origin AS;
  - AS path;
  - collector;
  - timestamp / duration;
  - candidate reasons as weak context only.
- RPKI `2024-04-16` as aligned origin evidence with truth boundaries.

Allowed through clean sidecar:

- CAIDA AS-rel `2024-04-01` path diagnostics through `outputs/r_asrel_clean_0/s2a_baseline_v01_pilot_6h_april16/asrel_2024_event_sidecar.parquet`.

Allowed only after sidecar / propagation:

- communities / NO_EXPORT through raw-to-event/candidate sidecar or propagation.

Audit reference only:

- final/high/needs/low;
- P1/P2/P3;
- R-NOISE-1 foreground/suppressed outputs;
- R-AGG raw incident outputs.

Forbidden in new decision logic:

- old 2017-derived `rel_seq`, `rel_unknown_cnt`, `rel_has_unknown`;
- legacy final labels as hard guards;
- suppressed background as negative training label;
- RPKI valid as benign;
- RPKI invalid as attack;
- AS-rel violation as route-leak truth;
- missing communities as NO_EXPORT absent;
- low visibility as confirmed stealth or NO_EXPORT.

## 5. Current Blockers

1. Communities / NO_EXPORT are not candidate-ready.
   - Raw data has communities and NO_EXPORT rows.
   - Event/candidate/incident layers do not currently retain join-ready community evidence.

2. Benchmark / label protocol is missing.
   - No recall, false-negative, or poisoning robustness claim is allowed before this exists.

3. Controlled attack / evasion samples are missing.
   - The 6h clean window cannot prove attack recall.

## 6. Next Single Recommended Action

```text
R-COMM-CLEAN-0:
Build a raw-to-event/candidate communities / NO_EXPORT sidecar or propagation design.
```

Allowed scope:

- read raw update community fields;
- read event/candidate keys;
- design or build a sidecar that makes community availability explicit;
- preserve parse status and provenance;
- keep NO_EXPORT present / absent / unavailable separate.

Forbidden scope:

- do not modify old seven-layer pipeline;
- do not use legacy final/high/needs/low as truth or guard;
- do not train learning;
- do not claim NO_EXPORT attack;
- do not run production suppression;
- do not treat R-NOISE-1 as final.

## 7. Active Experiment Order

```text
R-CLEAN-0
  -> R-ASREL-CLEAN-0 [done]
  -> R-COMM-CLEAN-0 [next]
  -> R-LABEL-0
  -> R-ATTACK-0
  -> R-NOISE-CLEAN-1
  -> R-LEARN-0
  -> R-LEARN-1
  -> R-INC-0
```

Do not skip directly to learning, production suppression, or final incident aggregation.

## 8. Short Experiment Map

| Phase | Purpose | Current Verdict | Status | Key Artifact |
|---|---|---|---|---|
| R-2B-P0b | build aligned RPKI cache | usable aligned origin evidence | active fact | `data/evidence/rpki/vrp_2024-04-16.parquet` |
| R-2C-P0b/P1/P2 | build and test 2024 AS-rel evidence | useful prototype, but new decisions need sidecar | active fact | `data/evidence/as_relationships/as_rel_2024-04-01.parquet` |
| R-2D-0 | audit communities / NO_EXPORT availability | raw available, not candidate-ready | active blocker | `project_docs/R2D0_COMMUNITIES_FIELD_AVAILABILITY_AUDIT.md` |
| R-CONSIST-1 | audit Stage 1 AS-rel provenance | old Stage 1 likely 2017 AS-rel | active blocker | `project_docs/R_CONSIST1_STAGE1_ASREL_PROVENANCE_AUDIT.md` |
| R-AGG-2/3 | candidate-first raw incident aggregation | too fragmented / stop-loss evidence | diagnostic only | `project_docs/R_AGG_3_RAW_INCIDENT_QUALITY_AUDIT.md` |
| R-EVID-0 | lightweight pre-triage after raw incidents | stop-loss; overlap too high | diagnostic only | `project_docs/R_EVID_0_LIGHTWEIGHT_EVIDENCE_PRETRIAGE_DESIGN.md` |
| R-RESET-1 | pivot mainline | full candidate-first aggregation stopped | active decision | `project_docs/PIPELINE_RESET_MAINLINE_R_RESET_1.md` |
| R-NOISE-0/1 | separability + foreground smoke | feasible provisional foreground view | provisional | `project_docs/R_NOISE_1_CONSERVATIVE_FOREGROUND_EXTRACTION_SMOKE.md` |
| R-CLEAN-0 | lock clean data/evidence contract | current mainline control point | active | `project_docs/R_CLEAN_0_DATA_EVIDENCE_CLEAN_CONTRACT.md` |
| R-ASREL-CLEAN-0 | build clean AS-rel sidecar | 2024 sidecar built; old-vs-2024 drift high | completed | `project_docs/R_ASREL_CLEAN_0_2024_ASREL_SIDECAR.md` |
| R-COMM-CLEAN-0 | build communities / NO_EXPORT sidecar or propagation design | next step | pending | new phase doc |

Older phase documents remain available as archive, but this table is the active navigation surface.

## 9. Maintenance Protocol

After a normal experiment:

1. Write the experiment's own phase document.
2. Update this file:
   - current truth table if a trusted fact changed;
   - blocker list if a blocker changed;
   - next single action;
   - short experiment map.
3. Do not update other mainline docs unless necessary.

After a major route change:

1. Do the normal experiment maintenance above.
2. Add one decision entry to `PROJECT_DECISION_REGISTER.md`.

README is only a navigation pointer. HANDOFF / EXPERIMENT_MAINLINE / CCFA / LEARNING / VERIFIER are historical or topical references, not every-round maintenance targets.
