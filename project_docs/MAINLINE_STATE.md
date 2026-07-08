# MAINLINE STATE

Last updated: 2026-07-08

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
| Controlled origin scenario QA | plumbing smoke qualified; scenario v1 blocked from promotion | R-ATTACK-QA-0 | high | Documentation-AS shortcut, community phase leakage, event/scenario visibility mismatch, insufficient diversity, and no hard negatives |
| Hardened controlled origin smoke | v2 bounded smoke passed all 16 QA checks | R-ATTACK-0A-2 | high | 4 attack + 4 hard-negative scenarios; attack retention `1.0`; hard-negative candidate rate `0.357143`; ready for full-window replay only |
| Controlled origin full-window replay | completed and qualified for clean foreground evaluation with one non-blocking community caveat | R-ATTACK-0A-3 | high | 3,431,117 event/candidate rows; attack retention `1.0`; attack RPKI/AS-rel/community joins `1.0`; global community raw-match misses 1 background row |
| Clean foreground evaluation | executed; safety passed but feasibility failed | R-NOISE-CLEAN-1 | high | `suppressed_attack_count=0`, attack retention `1.0`, but background suppression only `0.001263748`; candidate-style blanket protection is too conservative |
| Candidate-free semantic foreground audit | completed; `aggressive_recurrence` is the best passing candidate | R-FOREGROUND-0 | high | Attack retention `1.0`, suppressed attacks `0`, background suppression `0.37744629`, compression `1.606295` |
| Online foreground smoke | completed on origin-family and R-ATTACK-0B replay | R-FOREGROUND-1 | active baseline | `online_aggressive_recurrence_v1`; R-ATTACK-0B attack retention `1.0`, suppressed attacks `0`, background suppression `0.377447197`, compression `1.606292` |
| Multi-attack controlled smoke | validated full replay | R-ATTACK-0B | completed | Exact-origin, forged-origin, route-leak-like, and path-manipulation-like scenarios passed realism QA; all controlled attack families retained by foreground v1 |
| Foreground compression improvement audit | completed; found safe pressure boundary but no recommendable policy passed | R-FOREGROUND-2 | high | `path1_pressure_test` reached background suppression `0.510538701`, compression `2.043079`, suppressed attacks `0`; `external_only_pressure_test` suppressed `2` attacks and is unsafe |
| Online path-pressure foreground smoke | completed and frozen as current baseline | R-FOREGROUND-3 | high | `online_path_pressure_v1`; attack retention `1.0`, suppressed attacks `0`, background suppression about `0.51`, compression about `2.04`; now retested on R-ATTACK-1 full replay |
| Attack-family expansion | full 6h replay validated | R-ATTACK-1 | completed | Subprefix and monitor-visible NO_EXPORT/stealth scenarios passed full replay; attack retention `1.0`, suppressed attacks `0`, background suppression `0.510540519`, compression `2.043065` |
| Paired poisoning/evasion protocol | protocol and feasibility audit passed | R-POISON-0 | high | 5 feasible paired templates for R-POISON-1; route-leak policy poisoning remains design-only until policy semantics are bounded |
| Paired poisoning/evasion bounded materialization | bounded pair prototypes materialized | R-POISON-1 | high | 5 feasible pairs, 33 truth-prototype rows, fair-pair contract passed; no full replay and no adversarial retention claim |
| Paired poisoning/evasion bounded replay | completed; stop-loss triggered | R-POISON-2 | high | Clean retention mean `1.0`, adversarial retention mean `0.8`; path-manipulation history poisoning suppressed 2 adversarial attack events |
| Retention reason / ablation audit | completed; explains why retained pairs were retained | R-POISON-2A | high | 1 current failure pair, 1 single-signal fragile retained pair, 3 combined-stress fragile retained pairs; next remains targeted foreground repair |
| Path-memory maturity feasibility audit | completed; broad guard is too expensive | R-FOREGROUND-4A | high | Supplied assignment rows `384,839`; current compression `1.923551x`; broad recent-recurrence guard would drop compression to `1.436905x`; long-term maturity still needs a longer-history sidecar |
| 30d path-memory sidecar feasibility | completed; local 6h/one-day data is not enough for maturity claims | R-MEM-0 | high | Local target-date scan found 12 collectors and `94,312,168` raw rows; estimated 30d same-collector source volume is `1,741,147,710` raw rows / `15.8GB` parquet; next is HPC sidecar materialization |

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

1. The production-facing online foreground baseline is qualified on the current
   controlled multi-attack benchmark, but not yet on historical or adversarial
   poisoning/evasion variants.
   - R-ATTACK-0A-3 completed the full 6h replay on the hardened v2 scenario.
   - It produced `3,431,117` event rows and `3,431,117` candidate rows.
   - Candidate attack retention is `1.0`.
   - RPKI, AS-rel, and community attack evidence joins are each `1.0`.
   - The validation JSON reports `validated=false` only because global
     community raw-match is `3,431,116 / 3,431,117`.
   - R-NOISE-CLEAN-1 then passed safety but failed feasibility:
     `suppressed_attack_count=0`, attack retention `1.0`,
     background suppression `0.001263748`, compression ratio `1.001265`.
   - The failure shows `candidate_flag` and broad candidate reasons are too
     conservative as foreground protection signals.
   - Candidate artifacts are now historical diagnostics / ablation references,
     not the mainline compression layer.
   - R-FOREGROUND-0 candidate-free audit found one passing policy:
     `aggressive_recurrence`.
   - The passing policy kept attack retention at `1.0` and suppressed `0`
     attack rows while suppressing `37.744629%` of pure reference background
     with compression ratio `1.606295`.
   - R-FOREGROUND-1 should now freeze this as
     `online_aggressive_recurrence_v1` and produce auditable online assignment
     artifacts.
   - Origin-family smoke gate was background suppression >= `30%`.
   - The current controlled multi-attack foreground gate is background
     suppression >= `50%`, with stretch target `60%-70%`.
   - R-ATTACK-1 keeps this gate satisfied on the expanded controlled families.

2. Multi-attack foreground retention is qualified, but compression is still
   below the future target.
   - R-ATTACK-0B validated full replay:
     - `validated=true`;
     - `qa_pass=true`;
     - `online_pass=true`;
     - exact-origin, forged-origin, route-leak-like, and path-manipulation-like
       families all have attack retention `1.0`;
     - `suppressed_attack_count=0`.
   - R-FOREGROUND-1 on R-ATTACK-0B produced:
     - total rows `3431121`;
     - foreground rows `2136050`;
     - suppressed rows `1295071`;
     - background suppression `0.377447197`;
     - compression ratio `1.606292`.
   - This is safe enough for the current multi-attack smoke but below the
     future `>=0.50` background-suppression target.
   - R-FOREGROUND-2 completed the stronger candidate-free policy audit:
     - `baseline_v1_replay`: background suppression `0.377447197`,
       compression `1.606292`, suppressed attacks `0`;
     - `count3_path2_candidate`: background suppression `0.434294803`,
       compression `1.767721`, suppressed attacks `0`;
     - `path1_pressure_test`: background suppression `0.510538701`,
       compression `2.043079`, suppressed attacks `0`;
     - `external_only_pressure_test`: background suppression `0.840702662`,
       compression `6.277574`, but suppressed attacks `2`, so unsafe.
   - `path1_pressure_test` met the safety/feasibility gates but was marked as
     a pressure test, not directly recommendable.
   - R-FOREGROUND-3 completed the formal single-policy rerun and freezes
     `online_path_pressure_v1` as the current online foreground baseline:
     - total rows `3431121`;
     - foreground rows `1679387`;
     - suppressed rows `1751734`;
     - pure reference background suppression `0.510538701`;
     - compression ratio `2.043079`;
     - gray-zone rate `0.041341299`;
     - suppressed attack count `0`;
     - attack retention `1.0`;
     - truth feature leakage count `0`.
   - R-ATTACK-1 then validated the missing subprefix and monitor-visible
     NO_EXPORT / stealth families on a full 6h replay:
     - `validated=true`;
     - validation checks `18 / 18` passed;
     - QA checks `14 / 14` passed;
     - event rows `3431117`;
     - foreground rows `1679397`;
     - suppressed rows `1751720`;
     - background suppression `0.510540519`;
     - compression ratio `2.043065`;
     - attack retention `1.0`;
     - suppressed attack count `0`;
     - truth feature leakage count `0`.
   - This validates the current controlled-family foreground gate. It still
     does not prove historical-event recall, fully invisible monitor-evasion
     recall, poisoning robustness, or learning performance.

3. R-POISON-2A clarified that retained poisoning/evasion pairs are not yet a
   robustness proof.
   - R-POISON-2 retained four adversarial pairs and suppressed one.
   - R-POISON-2A decomposed the retained cases:
     - `pair_forged_origin_history_poisoning_v01` is single-signal fragile
       under `mask_asrel_diagnostic`;
     - `pair_exact_origin_history_poisoning_v01`,
       `pair_subprefix_noexport_evasion_v01`, and
       `pair_stealth_collector_asymmetry_v01` survive single-signal ablations
       but fail combined external+novelty stress tests;
     - `pair_path_manipulation_history_poisoning_v01` remains a current
       foreground failure.
   - This means foreground repair must add a path-memory poisoning guard and
     later test stronger variants. The retained pairs cannot be described as
     general poisoning robustness.

4. R-FOREGROUND-4A showed the repair must be targeted.
   - The supplied R-ATTACK-1 / R-FOREGROUND-3 assignment artifact has
     `384,839` rows.
   - Current suppression rate is `0.480128` and compression ratio is
     `1.923551` on that supplied artifact.
   - `67,758` suppressed rows are recent-suspicious recurrence proxies,
     about `0.366711` of all suppressed rows.
   - Pulling every such row back to foreground/gray would reduce suppression
     to `0.304060` and compression to `1.436905`.
   - Therefore R-FOREGROUND-4B must not protect all recent recurrence. It must
     target poisoning-like path-memory transitions.
  - The current artifact provides within-window maturity proxies only.
    Formal long-term maturity still requires a longer historical sidecar.

5. R-MEM-0 confirms that the next repair needs a 30-day sidecar before policy
   changes.
   - Local data in the requested 30-day window covers only `2024-04-16`.
   - The local tree still contains enough 2024-04-16 source parquet metadata
     to estimate cost and schema:
     - 12 collectors in the local target-date inventory;
     - `94,312,168` observed target-date raw rows;
     - `855,827,425` observed target-date raw parquet bytes;
     - estimated 30-day same-collector raw rows: `1,741,147,710`;
     - estimated 30-day same-collector raw parquet bytes:
       `15,799,890,900`.
   - Raw files often lack explicit `origin_as`, but `as_path` is available, so
     origin can be derived with explicit provenance.
   - The 30-day history must be a sidecar lookup, not a one-shot foreground
     input blob.
   - Per-batch evaluation must report 5m/15m foreground load and p50/p90/p99,
     not only one aggregate compression number.

5. Historical replay and larger paired poisoning/evasion scenarios are still
   missing.
   - The 6h reference window cannot prove real-world attack recall or
     poisoning/evasion robustness.

6. Community sidecar has a small join-quality caveat.
   - `partial_record_count_match=10273`;
   - `raw_join_unavailable=1`;
   - the R-ATTACK-0A-3 derived run also has `raw_join_unavailable=1`;
   - these rows must not be used for absence claims without extra QA;
   - this caveat does not block origin-family attack retention evaluation
     because attack community evidence join is `1.0`.

## 6. Next Single Recommended Action

```text
R-MEM-1:
Materialize a 30-day path-memory sidecar on HPC, then use it for
R-FOREGROUND-4B targeted path-memory poisoning guard smoke.
```

Allowed scope:

- materialize path-memory as a sidecar, not a full 30-day foreground input;
- start from the single R-POISON-2 failure mode:
  `pair_path_manipulation_history_poisoning_v01`;
- use the R-POISON-2A ablation audit to distinguish current failures,
  single-signal fragility, and combined-stress fragility;
- use the R-FOREGROUND-4A maturity audit to avoid broad recent-recurrence
  retention;
- use R-MEM-0 to require long-window maturity evidence before a path recurrence
  can support suppression;
- protect poisoning-susceptible path-memory transitions when novelty has been
  artificially washed out;
- report foreground load by 5m/15m micro-batch when the sidecar is used;
- preserve the existing safety boundary: suppressed attack count must be `0`;
- preserve useful background compression and avoid reverting to blanket
  retention;
- keep truth metadata evaluation-only;
- keep route-leak policy poisoning blocked until policy semantics are bounded.

Forbidden scope:

- do not modify old seven-layer pipeline;
- do not use legacy final/high/needs/low as truth or guard;
- do not train learning;
- do not claim NO_EXPORT attack, NO_EXPORT absence as safe, or route-leak
  truth;
- do not run production suppression;
- do not treat R-NOISE-1 or R-NOISE-CLEAN-1 as final;
- do not use candidate as the mainline compression layer;
- do not treat candidate retention as a hard mainline gate;
- do not claim route-leak truth from AS-rel diagnostics;
- do not start `R-TRAIN-DATA-0` or learning before poisoning/historical gates
  are planned;
- do not use community absence or unavailable state as a benign/safe feature.
- do not reuse the archived R-NOISE-1 implementation unchanged because it
  references legacy final labels and old `rel_*` fields.
- do not materialize the route-leak policy poisoning pair until its policy
  semantics contract is bounded.
- do not count public-invisible variants as foreground misses.
- do not train learning or expand historical replay until the R-POISON-2
  stop-loss is repaired.
- do not claim within-window recurrence is long-term maturity.
- do not use maturity as an attack score; it is only suppression-permission
  evidence.
- do not treat 30-day history as labels or as an offline training set.
- do not enter learning before R-MEM-1 and R-FOREGROUND-4B validate the
  foreground poisoning repair.

## 7. Active Experiment Order

```text
R-CLEAN-0
  -> R-RPKI-CLEAN-0 [done]
  -> R-ASREL-CLEAN-0 [done]
  -> R-COMM-CLEAN-0 [done]
  -> R-LABEL-0 [done]
  -> R-LABEL-1 [done]
  -> R-ATTACK-0A [done: development smoke]
  -> R-ATTACK-QA-0 [done: stop-loss for scenario v1 promotion]
  -> R-ATTACK-0A-2 [done: hardened bounded smoke]
  -> R-ATTACK-0A-3 [done: qualified full-window replay with one community caveat]
  -> R-NOISE-CLEAN-1 [done: safety pass, feasibility fail; too conservative]
  -> R-FOREGROUND-0 [done: candidate-free audit; aggressive_recurrence passed]
  -> R-FOREGROUND-1 [done: online foreground smoke passed on origin-family full replay]
  -> R-ATTACK-0B [done: multi-attack controlled smoke validated]
  -> R-FOREGROUND-2 [done: safe pressure boundary found, no direct promotion]
  -> R-FOREGROUND-3 [done: online_path_pressure_v1 baseline frozen]
  -> R-ATTACK-1 [done: full 6h replay of bounded subprefix + stealth/NO_EXPORT scenarios]
  -> R-POISON-0 [done: paired poisoning/evasion protocol and feasibility audit]
  -> R-POISON-1 [done: bounded materialization of feasible poisoning/evasion pairs]
  -> R-POISON-2 [done: bounded replay; stop-loss triggered]
  -> R-POISON-2A [done: retention reason and signal ablation audit]
  -> R-FOREGROUND-4A [done: path-memory maturity feature feasibility audit]
  -> R-MEM-0 [done: 30d path-memory sidecar feasibility audit]
  -> R-MEM-1 [next: materialize 30d path-memory sidecar]
  -> R-FOREGROUND-4B [then: targeted path-memory poisoning guard smoke]
  -> R-HIST-0
  -> R-TRAIN-DATA-0
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
| R-NOISE-CLEAN-1 | clean foreground policy using candidate context | safe but operationally useless | superseded by R-FOREGROUND-0 | `project_docs/R_NOISE_CLEAN_1_EVALUATION_PROTOCOL.md` |
| R-FOREGROUND-0 | candidate-free semantic foreground audit | `aggressive_recurrence` passed; `37.744629%` background suppression and `1.606295x` compression with `0` suppressed attacks | completed | `project_docs/R_FOREGROUND_0_CANDIDATE_FREE_SEMANTIC_FOREGROUND_AUDIT.md` |
| R-FOREGROUND-1 | online foreground smoke | origin-family and R-ATTACK-0B multi-attack replay passed: attack retention `1.0`, suppressed attacks `0`; R-ATTACK-0B background suppression `0.377447197`, compression `1.606292x` | completed baseline | `project_docs/R_FOREGROUND_1_ONLINE_FOREGROUND_SMOKE.md` |
| R-ATTACK-0B | multi-attack controlled smoke | validated full replay; all four controlled attack families retained; background suppression still `0.377447197` | completed | `project_docs/R_ATTACK_0B_MULTI_ATTACK_SMOKE.md` |
| R-FOREGROUND-2 | foreground policy improvement audit | completed; safe pressure boundary at `0.510538701` background suppression and `2.043079x` compression, but pressure-test policy requires formal rerun | completed | `project_docs/R_FOREGROUND_2_POLICY_IMPROVEMENT_AUDIT.md` |
| R-FOREGROUND-3 | formal online foreground smoke | completed; `online_path_pressure_v1` passed with attack retention `1.0`, suppressed attacks `0`, background suppression `0.510538701`, compression `2.043079x` | completed baseline | `project_docs/R_FOREGROUND_3_ONLINE_FOREGROUND_SMOKE.md` |
| R-ATTACK-1 | attack-family expansion | full 6h replay validated; subprefix and monitor-visible NO_EXPORT / stealth families retained; background suppression `0.510540519`, compression `2.043065x` | completed | `project_docs/R_ATTACK_1_ATTACK_FAMILY_EXPANSION_PLAN.md` |
| R-POISON-0 | paired poisoning/evasion protocol | feasibility audit passed; 5 feasible pairs cover detection-data poisoning and visibility evasion; route-leak policy poisoning blocked as design-only | completed design | `project_docs/R_POISON_0_PAIRED_POISONING_EVASION_PROTOCOL.md` |
| R-POISON-1 | bounded paired materialization | materialized 5 feasible pair prototypes; clean-base validation and fair-pair contracts passed; adversarial retention remains pending replay | completed materialization | `project_docs/R_POISON_1_BOUNDED_PAIRED_MATERIALIZATION.md` |
| R-POISON-2 | bounded poisoning/evasion replay | stop-loss triggered: path-manipulation history poisoning dropped from `1.0` clean retention to `0.0` adversarial retention; 2 adversarial attack events suppressed | completed stop-loss | `project_docs/R_POISON_2_BOUNDED_REPLAY.md` |
| R-POISON-2A | retention reason and signal ablation audit | completed; forged-origin retained pair is AS-rel single-signal fragile, three retained pairs are combined-stress fragile, and path-manipulation history poisoning remains current failure | completed audit | `project_docs/R_POISON_2A_RETENTION_REASON_ABLATION.md` |
| R-FOREGROUND-4A | path-memory maturity feature feasibility audit | completed; broad guard would hurt compression, and current artifact only supports within-window maturity proxies | completed audit | `project_docs/R_FOREGROUND_4A_PATH_MEMORY_MATURITY_AUDIT.md` |
| R-MEM-0 | 30d path-memory sidecar feasibility audit | completed; local 6h/one-day data cannot support long-term maturity claim, but schema and cost support an HPC 30d sidecar step | completed audit | `project_docs/R_MEM_0_30D_PATH_MEMORY_FEASIBILITY.md` |
| R-RESET-1 | pivot mainline | full candidate-first aggregation stopped | active decision | `project_docs/PIPELINE_RESET_MAINLINE_R_RESET_1.md` |
| R-NOISE-0/1 | separability + foreground smoke | feasible provisional foreground view | provisional | `project_docs/R_NOISE_1_CONSERVATIVE_FOREGROUND_EXTRACTION_SMOKE.md` |
| R-CLEAN-0 | lock clean data/evidence contract | current mainline control point | active | `project_docs/R_CLEAN_0_DATA_EVIDENCE_CLEAN_CONTRACT.md` |
| R-ASREL-CLEAN-0 | build clean AS-rel sidecar | 2024 sidecar built; old-vs-2024 drift high | completed | `project_docs/R_ASREL_CLEAN_0_2024_ASREL_SIDECAR.md` |
| R-COMM-CLEAN-0 | build communities / NO_EXPORT sidecar | candidate/event-ready sidecar built; absence caveated | completed | `project_docs/R_COMM_CLEAN_0_COMMUNITY_NOEXPORT_SIDECAR.md` |
| R-LABEL-0 | define multi-attack benchmark / label protocol | controlled / historical / poisoning tracks separated; labels isolated from evidence | completed, superseded by v1 for new experiments | `project_docs/R_LABEL_0_MULTI_ATTACK_BENCHMARK_PROTOCOL.md` |
| R-LABEL-1 | patch and freeze benchmark protocol v1 | phase, visibility, mixed membership, drop localization, split, and evidence binding fixed | completed | `project_docs/R_LABEL_1_BENCHMARK_PROTOCOL_V1_FREEZE.md` |
| R-ATTACK-0A | first controlled exact-prefix / forged-origin raw-level injection smoke | parser/event/candidate/evidence plumbing passed on bounded smoke; no foreground/full-window claim | completed development smoke | `project_docs/R_ATTACK_0A_ORIGIN_INJECTION_SMOKE.md` |
| R-ATTACK-QA-0 | qualify scenario realism and full-window replay plan | plumbing qualified; scenario v1 blocked from promotion by synthetic shortcuts and missing hard negatives | completed | `project_docs/R_ATTACK_QA_0_ORIGIN_SCENARIO_QUALIFICATION.md` |
| R-ATTACK-0A-2 | repair controlled origin scenarios and repeat bounded smoke | 16/16 QA passed; attack retention `1.0`; hard-negative candidate rate `0.357143`; no NO_EXPORT scenario | completed | `project_docs/R_ATTACK_0A_2_HARDENED_ORIGIN_SMOKE.md` |
| R-ATTACK-0A-3 | execute qualified full 6h replay and validate artifacts | attack path qualified; global community join has 1-row background caveat | completed | `project_docs/R_ATTACK_0A_3_FULL_REPLAY_QUALIFICATION.md` |
| R-NOISE-CLEAN-1 protocol | preregister attack-retention, background-denominator, and stop-loss rules | protocol frozen; no experiment run | completed design | `project_docs/R_NOISE_CLEAN_1_EVALUATION_PROTOCOL.md` |

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
