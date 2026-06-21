# MAINLINE STATE

Last updated: 2026-06-21

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
| RPKI evidence | clean sidecar built | R-RPKI-CLEAN-0 | high | `2024-04-16`; event/candidate-ready; invalid is not attack; valid is not benign |
| CAIDA AS-rel evidence | clean 2024 sidecar built | R-ASREL-CLEAN-0 | high | `2024-04-01`; event join rate `1.0`; old 2017 `rel_*` remains forbidden |
| Old Stage 1 `rel_*` fields | forbidden in new decisions | R-CONSIST-1 / R-CLEAN-0 | high | Likely `2017-07-01` CAIDA-derived |
| Raw communities / NO_EXPORT | clean sidecar built | R-COMM-CLEAN-0 | high | Candidate/event-ready with provenance; positive hits usable as evidence, absence remains caveated |
| Legacy final/high/needs/low | audit reference only | R-AGG-ENTRY-0 / R-CLEAN-0 | high | Not truth, not labels, not hard guards |
| P1/P2/P3 | audit reference only | R-CLEAN-0 | high | Not truth, not labels |
| Learning | blocked from training | R-CLEAN-0 | high | Design may happen later, training waits for clean sidecars + labels |
| Poisoning/evasion robustness | core goal, not yet proven | R-RESET-1 / R-CLEAN-0 | active blocker | Needs benchmark / controlled scenarios |
| Multi-attack benchmark / label protocol | v1 frozen for controlled injection | R-LABEL-0 / R-LABEL-1 | high | Five label layers plus phase, visibility, mixed membership, drop localization, split, and evidence-binding contracts |
| Controlled origin injection smoke | raw/event/candidate/evidence plumbing passed on 12 rewritten chunks | R-ATTACK-0A | development smoke only | 16 attack records; 4 attack events; candidate retention and three evidence joins all `1.0`; no foreground or full-window claim |

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

- RPKI / VRP `2024-04-16` origin evidence through `outputs/r_rpki_clean_0/s2a_baseline_v01_pilot_6h_april16/rpki_event_sidecar.parquet` and `rpki_candidate_sidecar.parquet`.
  - candidate sidecar join rate: `1.0`;
  - status counts: `valid=1860464`, `unknown=1413696`, `missing=149491`, `invalid_length=4854`, `invalid_asn=2598`;
  - `valid` is not benign; `invalid_*` is not attack truth; `unknown` is not normal.
- CAIDA AS-rel `2024-04-01` path diagnostics through `outputs/r_asrel_clean_0/s2a_baseline_v01_pilot_6h_april16/asrel_2024_event_sidecar.parquet`.
- raw communities / NO_EXPORT through `outputs/r_comm_clean_0/s2a_baseline_v01_pilot_6h_april16/community_event_sidecar.parquet` and `community_candidate_sidecar.parquet`.
  - source mode: raw counterpart of event source files;
  - event raw-match rate: `0.9999997085`;
  - exact record-count match rate: `0.9970056276`;
  - `NO_EXPORT` event hits: `1045`;
  - absence or unavailable states are not safe/benign evidence.

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

1. The first labeled origin-family smoke exists, but it is not yet a qualified
   benchmark result.
   - R-ATTACK-0A used two documentation-AS scenarios and only the 12 rewritten
     raw chunks for the accepted smoke.
   - Full-window replay, scenario-realism QA, clean foreground retention, hard
     negatives, and broader attack families remain missing.

2. Historical replay and paired poisoning/evasion scenarios are missing.
   - The 6h reference window cannot prove real-world attack recall or poisoning/evasion robustness.

3. Community sidecar has a small join-quality caveat.
   - `partial_record_count_match=10273`;
   - `raw_join_unavailable=1`;
   - these rows must not be used for absence claims without extra QA.

## 6. Next Single Recommended Action

```text
R-ATTACK-QA-0:
Qualify the first controlled origin smoke before using it to design or validate
the clean foreground extractor.
```

Allowed scope:

- audit whether documentation ASNs create overly easy shortcuts;
- verify phase, role, visibility, and mixed-membership semantics;
- verify raw schema and source immutability;
- verify mechanism-specific RPKI, AS-rel, and community responses;
- define the qualified full-window execution strategy;
- state whether scenario templates require repair before clean foreground work.

Forbidden scope:

- do not modify old seven-layer pipeline;
- do not use legacy final/high/needs/low as truth or guard;
- do not train learning;
- do not claim NO_EXPORT attack or route-leak truth;
- do not run production suppression;
- do not treat R-NOISE-1 as final;
- do not promote the 12-chunk smoke to paper-grade recall or low-FP evidence;
- do not enter R-NOISE-CLEAN-1 until attack QA passes.

## 7. Active Experiment Order

```text
R-CLEAN-0
  -> R-RPKI-CLEAN-0 [done]
  -> R-ASREL-CLEAN-0 [done]
  -> R-COMM-CLEAN-0 [done]
  -> R-LABEL-0 [done]
  -> R-LABEL-1 [done]
  -> R-ATTACK-0A [done: development smoke]
  -> R-ATTACK-QA-0 [next]
  -> R-NOISE-CLEAN-1
  -> R-ATTACK-0B
  -> R-HIST-0
  -> R-POISON-0
  -> R-LEARN-0
  -> R-LEARN-1
  -> R-INC-0
```

Do not skip directly to learning, production suppression, or final incident aggregation.

## 8. Short Experiment Map

| Phase | Purpose | Current Verdict | Status | Key Artifact |
|---|---|---|---|---|
| R-2B-P0b | build aligned RPKI cache | usable aligned origin evidence cache | active fact | `data/evidence/rpki/vrp_2024-04-16.parquet` |
| R-RPKI-CLEAN-0 | build clean RPKI event/candidate sidecar | baseline 6h RPKI sidecar built | completed | `project_docs/R_RPKI_CLEAN_0_EVENT_RPKI_SIDECAR.md` |
| R-2C-P0b/P1/P2 | build and test 2024 AS-rel evidence | useful prototype, but new decisions need sidecar | active fact | `data/evidence/as_relationships/as_rel_2024-04-01.parquet` |
| R-2D-0 | audit communities / NO_EXPORT availability | raw available, not candidate-ready | active blocker | `project_docs/R2D0_COMMUNITIES_FIELD_AVAILABILITY_AUDIT.md` |
| R-CONSIST-1 | audit Stage 1 AS-rel provenance | old Stage 1 likely 2017 AS-rel | active blocker | `project_docs/R_CONSIST1_STAGE1_ASREL_PROVENANCE_AUDIT.md` |
| R-AGG-2/3 | candidate-first raw incident aggregation | too fragmented / stop-loss evidence | diagnostic only | `project_docs/R_AGG_3_RAW_INCIDENT_QUALITY_AUDIT.md` |
| R-EVID-0 | lightweight pre-triage after raw incidents | stop-loss; overlap too high | diagnostic only | `project_docs/R_EVID_0_LIGHTWEIGHT_EVIDENCE_PRETRIAGE_DESIGN.md` |
| R-RESET-1 | pivot mainline | full candidate-first aggregation stopped | active decision | `project_docs/PIPELINE_RESET_MAINLINE_R_RESET_1.md` |
| R-NOISE-0/1 | separability + foreground smoke | feasible provisional foreground view | provisional | `project_docs/R_NOISE_1_CONSERVATIVE_FOREGROUND_EXTRACTION_SMOKE.md` |
| R-CLEAN-0 | lock clean data/evidence contract | current mainline control point | active | `project_docs/R_CLEAN_0_DATA_EVIDENCE_CLEAN_CONTRACT.md` |
| R-ASREL-CLEAN-0 | build clean AS-rel sidecar | 2024 sidecar built; old-vs-2024 drift high | completed | `project_docs/R_ASREL_CLEAN_0_2024_ASREL_SIDECAR.md` |
| R-COMM-CLEAN-0 | build communities / NO_EXPORT sidecar | candidate/event-ready sidecar built; absence caveated | completed | `project_docs/R_COMM_CLEAN_0_COMMUNITY_NOEXPORT_SIDECAR.md` |
| R-LABEL-0 | define multi-attack benchmark / label protocol | controlled / historical / poisoning tracks separated; labels isolated from evidence | completed, superseded by v1 for new experiments | `project_docs/R_LABEL_0_MULTI_ATTACK_BENCHMARK_PROTOCOL.md` |
| R-LABEL-1 | patch and freeze benchmark protocol v1 | phase, visibility, mixed membership, drop localization, split, and evidence binding fixed | completed | `project_docs/R_LABEL_1_BENCHMARK_PROTOCOL_V1_FREEZE.md` |
| R-ATTACK-0A | first controlled exact-prefix / forged-origin raw-level injection smoke | parser/event/candidate/evidence plumbing passed on bounded smoke; no foreground/full-window claim | completed development smoke | `project_docs/R_ATTACK_0A_ORIGIN_INJECTION_SMOKE.md` |
| R-ATTACK-QA-0 | qualify scenario realism and full-window replay plan | next step | pending | new phase doc |

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
