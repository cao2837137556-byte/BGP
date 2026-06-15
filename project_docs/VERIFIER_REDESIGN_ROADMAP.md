# Verifier Redesign Roadmap

Last updated: 2026-06-15

## 1. Architecture

Phase R verifier-centric architecture:

```text
BGP updates
  -> monitor-based candidate trigger
  -> incident builder
  -> evidence collector
  -> evidence state machine
  -> legality-first verifier
  -> robustness evaluator
  -> final verdict / abstain / provenance
  -> optional learning ranker
```

Monitor evidence starts the workflow. It does not close the case.

## 1A. Current Mainline After R-NOISE-1

R-RESET-1, R-NOISE-0, and R-NOISE-1 refine how the verifier roadmap should be read.

Current mainline:

```text
raw / candidate events
  -> conservative obvious noise foreground extraction
  -> multi-attack judgment layer
  -> incident aggregation after judgment
  -> evidence explanation / verifier support
  -> poisoning/evasion robustness evaluation
```

R-NOISE-1 has now run that smoke: `policy_A_very_conservative` produced `1816263` foreground-view rows and `1614840` suppressible operational-background rows from `3431103` candidate-entry rows, with `guardrail_failed=false`. Suppressed rows contained `0` must-keep rows, `0` legacy high/needs workflow-reference rows, and `0` poisoning/evasion-like proxy rows.

Verifier/evidence layers should therefore support the judgment layer and attack-like incident explanation after foreground extraction. They must not be used to turn obvious noise suppression into benign truth, and R-NOISE-1 guardrail success must not be reported as attack false-negative success because the clean 6h window has no confirmed attack labels.

Guardrails:

- final/high/needs/low remain workflow references, not truth.
- RPKI invalid is not attack truth.
- AS-rel diagnostic is not route leak truth.
- background_noise is not confirmed benign.
- poisoning/evasion-like proxies must be retained until robustness benchmarks test them.

## 2. Evidence Types

Every evidence type must carry `strength`, `provenance`, `aligned / stale / unavailable`, `manipulability risk`, and whether it may be used as strong evidence.

| Evidence type | Strength when aligned | Provenance required | Alignment states | Manipulability risk | Strong evidence allowed? |
| --- | --- | --- | --- | --- | --- |
| monitor evidence | weak to medium | collector set, timestamp, path/origin source | aligned / monitor_only | high | no, by itself |
| historical baseline evidence | weak to medium | baseline window, collector coverage | aligned / stale / poisoning_susceptible | high | no, by itself |
| RPKI / ROA / VRP | medium for origin validation | VRP snapshot, valid time, validator/source | aligned / stale / unavailable | lower, but incomplete | yes as component, not truth alone |
| IRR / route object | weak to medium | registry/source, object timestamp | aligned / stale / unavailable | medium | usually no alone |
| AS relationship | medium | snapshot date, provider/source | aligned / stale / unavailable | medium | yes as component if aligned |
| ASPA | strong for path authorization when available | ASPA object snapshot and validation logic | aligned / unavailable | lower | yes as component |
| BGP Roles / OTC | strong for leak semantics when available | role/OTC source and timestamp | aligned / unavailable | lower | yes as component |
| PeeringDB / IXP / facility hints | weak to medium | source snapshot and entity mapping | aligned / stale / unavailable | medium | no alone |
| temporal persistence | weak to medium | event time window and recurrence definition | aligned | medium | no alone |
| collector diversity | weak to medium | collector list and coverage denominator | aligned | medium | no alone |
| path legality | medium to strong | valley-free/ASPA/role logic and snapshot | aligned / stale / unavailable | medium | yes if aligned |
| optional data-plane evidence | strong but costly | probe vantage, timestamp, method | aligned / unavailable | lower | yes as component |
| known-event / operator report evidence | medium to strong | report URL/source, event time, operator context | aligned / out_of_window / unavailable | lower to medium | yes if time-aligned |

## 3. Evidence State Machine

Evidence states:
- `aligned_strong`: time-aligned, provenance complete, low manipulability, can support a strong verdict with other evidence.
- `aligned_medium`: time-aligned and useful, but insufficient alone.
- `aligned_weak`: time-aligned but indirect, biased, or insufficient for strong support.
- `stale_diagnostic`: old or non-time-aligned evidence; useful for explanation, not strong judgment.
- `unavailable`: evidence source absent.
- `conflicting`: evidence sources disagree materially.
- `monitor_only`: only public-monitor evidence is present.
- `poisoning_susceptible`: evidence is derived from monitor history or crafted-announcement-sensitive patterns.
- `external_confirmed_pending`: candidate requires operator/report/data-plane confirmation.
- `not_applicable`: evidence type is not meaningful for the incident or lookup key.

State transition principle:

```text
monitor_only
  -> aligned_medium / aligned_strong when independent evidence arrives
  -> stale_diagnostic when evidence exists but is not time-aligned
  -> conflicting when aligned evidence disagrees
  -> unavailable when evidence cannot be obtained
```

## 4. Verdict Logic v0

Rules:
- If only monitor evidence exists, do not output `strongly_supported_suspicious`.
- If evidence conflicts, output `evidence_conflict` or `abstain`.
- If evidence is unavailable, output `evidence_insufficient` or `external_evidence_unavailable`.
- If RPKI invalid + path legality conflict + temporal/collector support are all present, output `evidence_supported_suspicious`, not confirmed attack.
- If an incident is background-like but lacks external evidence, output `background_like_but_unconfirmed`.
- Do not output `benign` directly.
- Stale evidence may explain a case, but cannot produce a strong verdict.

Verdict candidate set:
- `strongly_supported_suspicious`
- `evidence_supported_suspicious`
- `evidence_conflict`
- `evidence_insufficient`
- `background_like_but_unconfirmed`
- `abstain`
- `external_evidence_unavailable`
- `stale_evidence_only`

## 5. Robustness Evaluation

Planned robustness scenarios:
- monitor poisoning scenario
- crafted announcements with `0 / 1 / 2 / 3 / 5` injected announcements
- monitor subset manipulation
- stale evidence injection
- missing evidence stress test
- monitor-only baseline degradation
- full verifier degradation
- evasion cost
- top-K retention
- abstention-precision tradeoff

The key comparison is not just detection rate. It is whether the verifier refuses to overclaim when evidence is poisoned, stale, or missing.

## 6. Baselines

Baselines:
- monitor-only legacy detector
- RPKI-only
- AS-rel/path-legality-only
- legality-first verifier
- multi-evidence verifier
- optional BEAM/DFOH-style conceptual baseline if implementation is unavailable
- BGPalerter/ARTEMIS-style rule baseline if feasible

Baseline use:
- Monitor-only shows the vulnerability of public-monitor triggers.
- RPKI-only shows origin validation limits.
- Legality-only shows the value and coverage limits of path semantics.
- Multi-evidence verifier tests whether provenance and abstention improve triage quality.

## 7. Core Metrics

Core metrics:
- verified-event precision proxy
- supported suspicious recall
- abstention rate
- false positive / false burden proxy
- evidence coverage
- stale evidence rate
- unavailable evidence rate
- poisoning robustness drop
- evasion cost
- top-K retention
- human review burden proxy

Metric interpretation:
- `abstention_rate` is not automatically bad; abstention is correct when evidence is missing or conflicting.
- `verified-event precision proxy` must be reported under partial ground truth assumptions.
- `human review burden proxy` should be incident-level, not raw event-row level.

## 8. Phase R Work Plan

Phase R-1: Verifier State Machine Design
- freeze evidence states
- freeze verdict candidates
- map legacy S3 fields into evidence states

Phase R-2: Legality-first Verifier
- implement path legality / triplet / ASPA-ready logic
- handle route leak and path manipulation first
- preserve abstain behavior

Phase R-3: Poisoning / Evasion Benchmark
- build crafted announcement scenarios
- test monitor-only degradation
- test verifier robustness and abstention

Phase R-4: Multi-evidence Evaluation
- compare baselines
- produce top-K case studies
- report coverage, stale evidence, unavailable evidence, and review burden

## 9. R-1 State Machine Decisions

R-1 freezes the design vocabulary that R-2 should implement against. The detailed registries are:

- `project_docs/R1_VERIFIER_STATE_MACHINE.md`
- `project_docs/R1_EVIDENCE_TYPES_AND_VERDICTS.md`

### Evidence State List

The verifier uses per-evidence states:

- `aligned_strong`
- `aligned_medium`
- `aligned_weak`
- `stale_diagnostic`
- `unavailable`
- `conflicting`
- `monitor_only`
- `poisoning_susceptible`
- `external_confirmed_pending`
- `not_applicable`

`poisoning_susceptible` is also a confidence modifier for monitor-history-derived evidence.

### Verdict List

R-1 verdict candidates:

- `strongly_supported_suspicious`
- `evidence_supported_suspicious`
- `evidence_conflict`
- `evidence_insufficient`
- `external_evidence_unavailable`
- `background_like_but_unconfirmed`
- `stale_evidence_only`
- `abstain`

These are verification verdict candidates, not confirmed ground-truth labels.

### Confidence Cap Principle

Verifier confidence measures evidence support quality, not attack risk. The default caps are:

- monitor-only evidence: max `0.45`
- stale evidence only: max `0.40`
- evidence insufficient: max `0.50`
- evidence conflict: max `0.55`, and verdict cannot be suspicious
- aligned medium multi-evidence: max `0.75`
- aligned strong plus consistency: max `0.90`

### Hard Safety Rules

R-1 fixes these non-negotiable rules:

- RPKI invalid is not confirmed attack.
- RPKI valid is not confirmed benign.
- Public monitor-only evidence cannot produce `strongly_supported_suspicious`.
- Stale evidence cannot produce a strong verdict.
- Unavailable evidence cannot imply benign.
- P3 / low / background is not confirmed normal.
- Learning layer cannot override verifier safety rules.
- Evidence conflict must remain visible.
- Poisoning-susceptible evidence must lower confidence or require extra support.
- Abstain is an allowed and expected verifier outcome.

### Learning Layer Relationship

The learning layer is downstream of the verifier. It may rank incidents, calibrate evidence confidence, recommend abstention, and prioritize human review. It must not replace the verifier, hide conflicts, or turn legacy detector outputs into attack/benign labels.

### Next Phase

R-2 should implement a legality-first verifier against the R-1 schema:

- consume legacy S3 queues as verifier input,
- attach evidence state and provenance,
- implement route-leak/path-legality checks first,
- preserve `abstain`, `evidence_conflict`, and `external_evidence_unavailable` as first-class outcomes,
- keep monitor-only detector output as a candidate trigger rather than a final judge.

## 10. R-2A Legality-First Verifier Scaffold

R-2A is the first implementation slice of R-2.

Scope:

- generate an incident-level verifier table from legacy S3-D incidents;
- attach R-1 evidence states for monitor, RPKI, path legality, IRR, and known-event evidence;
- output R-1 verdict candidates, confidence caps, abstain/conflict reasons, learning eligibility, and provenance;
- run scaffold + sample smoke only;
- do not overwrite legacy score/gate/final/incidents;
- do not train a learning model;
- do not run poisoning/evasion benchmark.

Implementation entry:

- `scripts/run_r2a_legality_first_verifier_scaffold.py`
- `project_docs/R2A_LEGALITY_FIRST_VERIFIER_SCAFFOLD.md`

Smoke result:

- output directory: `outputs/r2a_legality_first_verifier_smoke_v01/`
- processed incidents: `50000`
- `strongly_supported_suspicious=0`
- `evidence_supported_suspicious=0`
- `stale_evidence_only=43335`
- `external_evidence_unavailable=3762`
- `background_like_but_unconfirmed=1485`
- `evidence_insufficient=1418`
- RPKI unavailable for all processed smoke incidents
- 2017 CAIDA AS-rel is treated as `stale_diagnostic`, not strong evidence

Interpretation:

R-2A proves that legacy incidents can be converted into verifier-table form without changing old outputs. It does not prove attacks or benignness. The dominant stale/unavailable verdicts are a useful signal: evidence readiness is now explicit rather than hidden inside detector score.

Next:

- R-2B-0 evidence readiness audit;
- P0b evidence cache completion for aligned 2024 RPKI/ROA and 2024-near AS relationship data;
- R-2B/R-2C legality-first verifier refinement with aligned evidence;
- R-3 poisoning/evasion benchmark only after legality behavior is stable.

## 11. R-2B-0 Evidence Readiness Audit

R-2B-0 is the bridge between the R-2A scaffold and real aligned evidence use.

Scope:

- audit whether fixed S2 incidents have stable lookup keys for external evidence;
- generate prefix-origin targets for RPKI/VRP and IRR lookup;
- generate path/triplet targets for AS relationship, ASPA, BGP Roles/OTC, and route-leak legality work;
- inventory local evidence caches;
- produce a readiness matrix and minimal cache acquisition plan;
- do not download large external datasets;
- do not change verifier verdicts or legacy detector outputs.

Implementation entry:

- `scripts/run_r2b0_evidence_readiness_audit.py`
- `project_docs/R2B0_EVIDENCE_READINESS_AUDIT.md`

Full audit result:

- output directory: `outputs/r2b0_evidence_readiness_audit_v01/`
- processed incidents: `217165`
- prefix-origin complete: `217162`
- time-window complete: `217165`
- path-key complete: `216922`
- triplet-key complete: `205067`
- RPKI/VRP cache: `missing`
- IRR cache: `missing`
- ASPA cache: `missing`
- PeeringDB cache: `missing`
- known-event inventory: `present_unverified_schema`
- AS relationship cache: `ready_stale`, because only the 2017 CAIDA file is present

Interpretation:

The fixed S2 incident schema is ready enough for external evidence lookup. The main blocker is not incident field repair; it is aligned evidence cache materialization.

Next path:

```text
R-2B-0 readiness audit
  -> P0b historical VRP/RPKI cache materialization for 2024-04-16
  -> R-2B/R-2C verifier smoke with aligned RPKI evidence
  -> route-leak/path-legality refinement after origin evidence is aligned
  -> R-3 poisoning/evasion benchmark
```

R-2B-0 does not make attack/benign claims. It keeps missing cache as `missing`, stale AS relationship evidence as diagnostic only, and public monitor context as trigger/context evidence.

## 12. R-2B-P0b Historical VRP/RPKI Cache Materialization

R-2B-P0b resolves the first aligned external-evidence blocker found by R-2B-0.

Scope:

- materialize a `2024-04-16` historical VRP/RPKI cache for fixed S2;
- normalize ROA payloads into a reproducible local VRP schema with provenance;
- run offline origin validation lookup over R-2B-0 prefix-origin targets;
- output RPKI lookup coverage and status distributions;
- do not generate verifier verdicts;
- do not change legacy detector outputs, R-2A outputs, or R-2B-0 outputs.

Implementation entry:

- `scripts/run_r2b_p0b_materialize_vrp_cache.py`
- `project_docs/R2B_P0B_HISTORICAL_VRP_CACHE.md`

Evidence source:

- RIPE NCC RPKI repository archive, 5 TAL files for `2024/04/16/roas.csv.xz`:
  `afrinic.tal`, `apnic.tal`, `arin.tal`, `lacnic.tal`, and `ripencc.tal`.

Full materialization result:

- output directory: `outputs/r2b_p0b_vrp_materialization_v01/`
- local evidence cache: `data/evidence/rpki/vrp_2024-04-16.parquet`
- metadata: `data/evidence/rpki/vrp_2024-04-16.metadata.json`
- normalized VRP records: `530187`
- lookup-eligible prefix-origin targets: `217162`
- RPKI status distribution:
  - `valid=122280`
  - `invalid_asn=397`
  - `invalid_length=283`
  - `unknown=94202`
  - `unavailable=0`
- evidence state distribution:
  - `aligned_medium=122960`
  - `aligned_weak=94202`
- safety violations: `0`

Interpretation:

Aligned origin-authorization evidence is now available for R-2B/R-2C verifier smoke. This does not complete incident verification: RPKI validates origin authorization only, not full AS-path legality. `valid` is not benign, `invalid` is not confirmed attack, and `unknown` is not normal.

Next path:

```text
R-2B-P0b aligned VRP/RPKI cache
  -> R-2B verifier smoke with aligned VRP evidence
  -> R-2C legality/path refinement
  -> 2024-near AS relationship / ASPA / IRR evidence completion
  -> R-3 poisoning/evasion benchmark
```

## 13. R-2B VRP-Aware Verifier Smoke and CCF-A Path

R-2B is the first evidence-backed verifier smoke after aligned RPKI/VRP cache materialization.

Scope:

- join aligned VRP lookup back to S3-D incidents;
- preserve both dominant prefix-origin status and member/component status distribution;
- add incident purity / component mixture audit;
- emit conservative R-1 verdict candidates;
- keep mixed incidents visible through `evidence_conflict`, `abstain`, and `evidence_insufficient`;
- maintain the CCF-A target line and avoid falling back to a simple rule-based anomaly detector.

Implementation entry:

- `scripts/run_r2b_vrp_aware_verifier_smoke.py`
- `project_docs/R2B_VRP_AWARE_VERIFIER_SMOKE.md`
- `project_docs/CCFA_TARGET_LINE_AND_EXPERIMENT_GUARDRAILS.md`

Full fixed S2 result:

- processed incidents: `217165`
- dominant pair RPKI status:
  - `valid=122280`
  - `unknown=94202`
  - `invalid_asn=397`
  - `invalid_length=283`
  - `unavailable=3`
- component purity:
  - `pure_dominant=114237`
  - `insufficient_component_signal=94666`
  - `highly_mixed_should_split=4689`
  - `mostly_dominant=3023`
  - `mixed_but_core_suspicious=479`
  - `mixed_conflicting=71`
- verifier verdicts:
  - `background_like_but_unconfirmed=156971`
  - `evidence_insufficient=55366`
  - `abstain=4684`
  - `evidence_conflict=86`
  - `evidence_supported_suspicious=55`
  - `external_evidence_unavailable=3`
  - `strongly_supported_suspicious=0`
- hard safety violations: `0`

Interpretation:

R-2B shows that aligned RPKI evidence can reduce external-unavailable behavior and create evidence-supported candidates while preserving abstention and conflict boundaries. It also shows why incident-level purity matters: thousands of incidents require component split or mixed-evidence handling before any stronger claim is safe.

CCF-A route:

```text
R-2B: VRP-aware verifier smoke + incident purity audit
  -> R-2C: path evidence branch / route-leak legality refinement
  -> R-3: monitor poisoning / evasion benchmark
  -> L1: component-aware semantic learner
  -> L2: evidence-constrained ranker / calibrator
  -> R-4: multi-evidence robustness evaluation
```

The current main target is CCF-A / top-tier networking or security venue. SCI Q2 remains a fallback only. The project should be judged against poisoning robustness, evidence constraints, component awareness, and human-burden reduction under partial observability.

## 14. R-2B-OPS Operational Burden and Real-Time Cache Guardrail

R-2B-OPS is the deployment-facing guardrail after the first VRP-aware verifier smoke.

Scope:

- project fixed S2 six-hour verifier queues into daily workload proxies;
- define which queues can be reviewed directly, which require Top-K, which require sampling, and which should wait for more evidence;
- simulate deterministic Top-K review budgets without training a model;
- define the real-time evidence cache architecture;
- define freshness and fallback behavior for stale, missing, and conflicting evidence;
- draft SLO measurement hooks for future near-real-time deployment;
- do not download new evidence;
- do not modify R-2B verifier verdicts;
- do not train L1/L2.

Implementation entry:

- `scripts/run_r2b_ops_realtime_burden_audit.py`
- `project_docs/R2B_OPS_REALTIME_BURDEN_AUDIT.md`

Full fixed S2 result:

- input incidents: `217165`;
- projected daily evidence-supported suspicious: `220`;
- projected daily conflict queue: `344`;
- projected daily abstain: `18736`;
- projected daily evidence-insufficient: `221464`;
- projected daily background-like but unconfirmed: `627884`;
- projected daily mixed should-split queue: `18756`;
- Top-50 supported density: `1.0`;
- Top-100 supported density: `0.53`;
- Top-500 supported density: `0.11`;
- verifier verdict modified: `false`;
- new external evidence downloaded: `false`.

R-2B-OPS establishes a required deployment constraint for R-2C and R-3: online verification must use local evidence-cache lookups only. External evidence download and normalization belong to asynchronous updaters with versioned caches, index build, atomic cache switch, and provenance/freshness metadata.

Freshness and fallback policy:

- stale RPKI/VRP can lower evidence state but must not imply benignness;
- stale AS relationship evidence is diagnostic only;
- IRR/PeeringDB/known-event evidence must keep provenance and conflict visible;
- data-plane evidence is asynchronous enrichment, not an online-path blocker;
- public monitor context remains trigger/context evidence, not final truth.

Updated CCF-A route:

```text
R-2B: VRP-aware verifier smoke + incident purity audit
  -> R-2B-OPS: operational burden + real-time evidence-cache guardrail
  -> R-2C: path evidence branch / route-leak legality refinement
  -> R-3: monitor poisoning / evasion benchmark
  -> L1: component-aware semantic learner design
  -> L2: evidence-constrained ranker / calibrator
  -> R-4: multi-evidence robustness evaluation
```

This keeps the project from becoming an offline-only verifier demo. R-2C should preserve the same operational constraints: no per-incident remote lookup in the online path, explicit stale/unavailable fallback, and Top-K review rather than full manual inspection.

## 15. R-2C-0 Path Evidence Readiness Audit

R-2C-0 is the gate before implementing path evidence, route-leak legality, or path-manipulation verification.

Scope:

- audit whether fixed S2 incidents have usable path, AS-pair, and AS-triplet lookup keys;
- generate AS-pair, triplet, and full-path lookup targets;
- inventory local path evidence caches;
- distinguish stale diagnostics from aligned evidence;
- produce the minimal R-2C path evidence plan;
- do not download new evidence;
- do not modify R-2B verifier verdicts;
- do not run route-leak verification.

Implementation entry:

- `scripts/run_r2c0_path_evidence_readiness_audit.py`
- `project_docs/R2C0_PATH_EVIDENCE_READINESS_AUDIT.md`

Full fixed S2 result:

- incidents checked: `217165`;
- complete path-key incidents: `217162` (`0.999986`);
- triplet-capable incidents: `217162` (`0.999986`);
- AS-pair targets: `216922`;
- triplet targets: `205067`;
- full-path targets: `217162`;
- legacy 2017 CAIDA AS relationship: `ready_stale` / stale diagnostic only;
- 2024-near AS relationship cache: `missing`;
- ASPA cache: `missing`;
- BGP Roles / OTC cache: `missing`;
- PeeringDB cache: `missing`;
- known-event path context: `present_unverified_schema`.

R-2C-0 shows that lookup keys are not the blocker. The blocker is aligned path evidence. The direct route-leak verifier should not be launched until path evidence is either aligned or deliberately scoped as stale/diagnostic.

Updated route:

```text
R-2C-0 path evidence readiness audit
  -> R-2C-P0b 2024-near AS relationship cache materialization
  -> ASPA / BGP Roles / OTC feasibility checks
  -> R-2C route-leak/path-legality verifier smoke
  -> R-3 poisoning/evasion benchmark
  -> L1 component-aware semantic learner design
```

Hard boundaries for R-2C:

- stale AS relationship evidence cannot be strong evidence;
- valley-free or relationship conflicts are not confirmed route leaks;
- missing path evidence is not benign;
- public monitor path context is not independent truth;
- PeeringDB is diagnostic/context only.

## 16. R-2C-P0b 2024-near AS Relationship Cache

R-2C-P0b materializes the first aligned path evidence cache after R-2C-0.

Scope:

- download or reuse CAIDA AS Relationships serial-2 snapshot `2024-04-01`;
- normalize AS relationship records into a bidirectional local lookup cache;
- preserve CAIDA raw orientation rather than forcing valley-free semantics;
- run AS-pair lookup smoke over R-2C-0 targets;
- do not generate route-leak verdicts;
- do not modify R-2B verifier verdicts;
- do not train learning models.

Implementation entry:

- `scripts/run_r2c_p0b_materialize_asrel_cache.py`
- `project_docs/R2C_P0B_2024_ASREL_CACHE.md`

Full fixed S2 result:

- source: `https://data.caida.org/datasets/as-relationships/serial-2/20240401.as-rel2.txt.bz2`;
- snapshot date: `2024-04-01`;
- run date: `2024-04-16`;
- alignment delta: `15` days;
- future snapshot: `false`;
- raw AS-rel records: `571330`;
- directed lookup records: `1142660`;
- parse warnings: `0`;
- AS-pair target rows: `216922`;
- unique AS-pairs: `61997`;
- matched unique AS-pairs: `56971`;
- unmatched unique AS-pairs: `5026`;
- unique AS-pair match rate: `0.918932`;
- relation distribution: `p2c_or_c2p_raw=33144`, `p2p=23827`, `unknown=5026`.

Updated route:

```text
R-2C-P0b 2024-near CAIDA AS-rel cache
  -> R-2C-P1 path relation lookup smoke / path-legality smoke
  -> ASPA / BGP Roles / OTC feasibility checks
  -> R-2C-P2 route-leak legality smoke
  -> R-3 poisoning/evasion benchmark
```

Safety boundaries:

- AS relationship evidence is inferred evidence, not route-leak truth;
- AS-rel violation is not confirmed route leak;
- AS-rel path legality is not benign;
- CAIDA `-1` orientation must be interpreted with CAIDA documentation before valley-free logic;
- future snapshots are not allowed for formal verifier evidence.

## 17. R-2C-P1 Path Relation Lookup Smoke

R-2C-P1 attaches the R-2C-P0b AS relationship cache back to incident-level path evidence.

Scope:

- expand AS-pair targets and join them against the `2024-04-01` CAIDA AS-rel cache;
- convert triplets into two adjacent relation lookups;
- generate full-path relation sequences;
- aggregate path evidence back to incident level;
- combine origin-side R-2B evidence with path-side diagnostic evidence;
- generate a deterministic Top-K path-review smoke;
- do not generate route-leak verdicts;
- do not modify R-2B verifier verdicts;
- do not train learning models;
- do not run NO_EXPORT/community, AS Hegemony, ASPA, or BGP Roles / OTC branches.

Implementation entry:

- `scripts/run_r2c_p1_path_relation_lookup_smoke.py`
- `project_docs/R2C_P1_PATH_RELATION_LOOKUP_SMOKE.md`

Fixed S2 result:

- expanded AS-pair rows: `421989`;
- matched AS-pair rows: `399839`;
- unmatched AS-pair rows: `22150`;
- row-level AS-pair match rate: `0.947510`;
- relation types: `p2c_or_c2p_raw=270770`, `p2p=129069`, `unknown=22150`;
- triplet rows: `205067`;
- possible valley/peer-transit diagnostic rows: `34192`;
- full-path rows: `217162`;
- mean full-path unknown pair rate: `0.054964`;
- incident path evidence rows: `217165`;
- path evidence states: `aligned_medium=161992`, `diagnostic_only=34192`, `evidence_insufficient=18084`, `unavailable=2897`;
- route-leak-like diagnostic candidates: `34555`;
- path-manipulation-like diagnostic candidates: `44189`;
- route-leak verdict generated: `false`;
- R-2B verifier verdict modified: `false`.

Combined origin + path distribution:

- `origin_valid_path_suspicious=108583`;
- `origin_unknown_path_suspicious=86980`;
- `background_like_combined=14603`;
- `insufficient_combined_evidence=6337`;
- `path_supported_only=521`;
- `origin_path_conflict=86`;
- `origin_and_path_supported=46`;
- `origin_supported_only=9`.

Updated route:

```text
R-2C-P1 path relation lookup smoke
  -> R-2C-P2 route-leak/path-legality verifier smoke
  -> ASPA / BGP Roles / OTC feasibility checks
  -> R-2D-0 communities / NO_EXPORT field availability audit
  -> R-3 poisoning/evasion benchmark
  -> L1 component-aware semantic learner design
```

Safety boundaries:

- AS-rel matched is not path benign;
- AS-rel unmatched is not path suspicious;
- possible valley-free diagnostics are not confirmed route leaks;
- AS relationship evidence is inferred and must keep provenance visible;
- R-2C-P2 may consume R-2C-P1 diagnostic candidates, but it must still preserve abstain/conflict behavior and hard safety rules.

## 18. R-2C-P2 Path-legality Verifier Smoke

R-2C-P2 converts R-2C-P1 path diagnostic evidence into an R-1 verdict-compatible path-legality smoke table.

Scope:

- tighten R-2C-P1 naming so diagnostic classes are not presented as suspicious labels;
- split route-leak-like and path-manipulation-like diagnostics into review, insufficient, conflict, abstain, and background queues;
- combine R-2B origin evidence, R-2C-P1 path evidence, and component purity;
- generate a deterministic Top-K path-legality review smoke;
- do not generate confirmed route-leak labels;
- do not modify R-2B verifier verdicts;
- do not train learning models;
- do not run NO_EXPORT/community, AS Hegemony, ASPA, or BGP Roles / OTC branches.

Implementation entry:

- `scripts/run_r2c_p2_path_legality_verifier_smoke.py`
- `project_docs/R2C_P2_PATH_LEGALITY_VERIFIER_SMOKE.md`

Fixed S2 result:

- processed incidents: `217165`;
- path-legality verdict smoke distribution: `background_like_but_unconfirmed=127889`, `evidence_insufficient=78324`, `abstain=10822`, `evidence_conflict=86`, `evidence_supported_suspicious=44`;
- route-leak-like review candidates: `34555`;
- path-manipulation-like review candidates: `44189`;
- `strongly_supported_suspicious=0`;
- hard safety violations: `0`;
- confirmed route-leak generated: `false`;
- R-2B verifier verdict modified: `false`.

Top-K path-legality smoke:

- Top-50: path review signal density `1.0`, evidence-supported density `0.88`;
- Top-100: path review signal density `1.0`, evidence-supported density `0.44`;
- Top-500: path review signal density `1.0`, evidence-supported density `0.088`.

Updated route:

```text
R-2C-P2 path-legality verifier smoke
  -> R-2D-0 communities / NO_EXPORT field availability audit
  -> L1 component-aware semantic learner design
  -> R-3 poisoning/evasion benchmark early design
  -> ASPA / BGP Roles / OTC feasibility checks
```

Safety boundaries:

- path diagnostics are not confirmed route leaks;
- `path_review_signal_density` is not attack density;
- AS-rel-only evidence cannot trigger a strong verdict;
- `background_like_but_unconfirmed` remains unconfirmed and cannot be used as a negative label;
- learning may consume these fields later for ranking/calibration design, but formal training remains blocked until verifier-supported targets and robustness scenarios exist.

## 19. R-LOCK-1 Architecture Minimality Lock

R-LOCK-1 freezes the paper-facing architecture into three stages plus a human-facing Top-K queue. This prevents the system from being described as a pile of legacy detector layers, evidence scripts, verifier rules, and future learning pieces.

Locked architecture:

```text
Stage 1: Monitor-triggered Incident Construction
  -> Stage 2: Evidence-constrained Verification
  -> Stage 3: Component-aware Learning Triage
  -> Top-K Review Queue
```

Interpretation:

- Stage 1 compresses the old seven-layer pipeline into incident construction, key extraction, and monitor-side weak/context signals.
- Stage 2 is the verifier. It attaches evidence, preserves conflict/insufficient/abstain states, and refuses attack/benign overclaims.
- Stage 3 is the learning ranker/calibrator. It sits after the verifier and before Top-K, learns review priority and component/evidence consistency, and cannot override verifier hard rules.
- Top-K is the human-facing review budget, not the learning layer itself.

Implementation and planning documents:

- `project_docs/ARCHITECTURE_MINIMALITY_AND_ABLATION_PLAN.md`
- `project_docs/SYSTEM_OUTPUT_SCHEMA_SIMPLIFIED.md`

R-LOCK-1 also defines the ablation defense for reviewer criticism:

- A0 full system;
- A1 remove Stage 2 verifier and use old seven-layer output only;
- A2 remove RPKI/VRP origin evidence;
- A3 remove AS-rel path evidence;
- A4 remove component purity;
- A5 remove abstention/conflict and force every case into supported/background;
- A6 remove learning ranker and use deterministic score only;
- A7 remove Top-K budget and show full manual burden;
- A8 compare monitor-only and verifier-constrained systems under poisoning;
- A9 evaluate stealth evidence with and without future communities/NO_EXPORT branch if fields exist.

Locked route after R-LOCK-1:

```text
Architecture Lock
  -> R-2D-0 communities / NO_EXPORT field availability audit
  -> R-CONSIST-1 Stage 1 evidence provenance and AS-rel alignment audit
  -> R-DOC-1 research decision consolidation
  -> R-OUT-1 unified incident output taxonomy design
  -> R-CONSIST-2 aligned AS-rel reannotation or replay if needed
  -> community-retention pipeline repair if incident join is not ready
  -> R-2D-0 rerun / R-2D-1 community-aware stealth evidence branch if ready
  -> R-3 poisoning / evasion benchmark design
  -> L1 component-aware semantic learner design
  -> architecture ablation implementation
  -> R-2D community-aware stealth evidence branch if fields exist
```

This route is now the default. Further legacy detector-score optimization is out of scope unless it is needed to repair Stage 1 lookup keys or to define a poisoning baseline.

## 20. R-2D-0 Communities / NO_EXPORT Field Availability Audit

R-2D-0 starts the stealth / monitor-evasion evidence branch with an audit-only step.

Scope:

- scan fixed S2 raw/event/incident/verifier artifacts for community-like fields;
- parse raw well-known communities: `NO_EXPORT`, `NO_ADVERTISE`, `NO_EXPORT_SUBCONFED`, and `NOPEER`;
- audit pipeline retention from raw updates to event units, incident membership, incident tickets, and verifier outputs;
- check whether community fields can be joined to incident/member/component keys;
- produce a stealth evidence readiness matrix;
- do not implement a stealth verifier;
- do not detect a NO_EXPORT attack;
- do not modify R-2B/R-2C verifier verdicts;
- do not train learning;
- do not run poisoning/evasion.

Implementation entry:

- `scripts/run_r2d0_communities_field_availability_audit.py`
- `project_docs/R2D0_COMMUNITIES_FIELD_AVAILABILITY_AUDIT.md`

Fixed S2 full result:

- scanned files: `893`;
- raw update files with `communities`: `864`;
- raw rows: `39039005`;
- non-empty community rows: `35657850`;
- parser success rows: `27843441`;
- well-known community rows: `NO_EXPORT=223410`, `NO_ADVERTISE=1240`, `NO_EXPORT_SUBCONFED=0`, `NOPEER=5634`;
- layers retaining communities: `raw_updates` only;
- first concrete retention break: `event_units`;
- incident join ready: `false`;
- can enter R-2D-1 now: `false`;
- verifier verdict modified: `false`;
- learning trained: `false`.

Interpretation:

The raw evidence channel exists, and well-known communities are parseable. However, the evidence is not yet incident-ready because communities are dropped before event/incident construction. R-2D-1 should not start as a verifier branch until community retention is repaired.

Updated route:

```text
R-2D-0 audit
  -> repair Stage 1 community retention in event construction
  -> propagate community summaries into incident membership/cards
  -> rerun R-2D-0 to verify incident join readiness
  -> R-2D-1 community-aware stealth evidence branch if ready
  -> R-3 poisoning/evasion benchmark design
  -> L1 component-aware semantic learner design
```

Safety boundaries:

- `NO_EXPORT` present is not a confirmed attack;
- `NO_EXPORT` absent is not safe;
- `NO_ADVERTISE`, `NO_EXPORT_SUBCONFED`, and `NOPEER` are not stealth labels by themselves;
- low visibility does not mean `NO_EXPORT`;
- collector asymmetry does not prove monitor evasion;
- missing community evidence is not benign;
- community evidence must keep provenance and incident/component join keys before Stage 2 can consume it.

## 21. R-CONSIST-1 Stage 1 AS-rel Provenance and Alignment Audit

R-CONSIST-1 was added after R-2D-0 because Stage 2 now uses a versioned 2024-near CAIDA AS-rel cache, while Stage 1 may have retained older AS-rel-derived weak fields.

Scope:

- scan Stage 1 code, run metadata, logs, and output schemas for AS-rel provenance;
- identify whether Stage 1 references CAIDA AS-rel and which snapshot is implied;
- audit whether Stage 1 output fields depend on AS-rel-derived fields such as `rel_seq`, `rel_unknown_cnt`, and `rel_has_unknown`;
- compare Stage 1 inferred AS-rel snapshot against Stage 2 `2024-04-01` AS-rel metadata;
- estimate replay scope;
- do not rerun Stage 1;
- do not modify verifier verdicts;
- do not download new evidence;
- do not train learning.

Implementation entry:

- `scripts/run_r_consist1_stage1_asrel_provenance_audit.py`
- `project_docs/R_CONSIST1_STAGE1_ASREL_PROVENANCE_AUDIT.md`

Full audit result:

- Stage 1 AS-rel detected: `yes`;
- inferred Stage 1 snapshot: `2017-07-01`;
- inferred Stage 1 path: `data/caida/as-relationships/serial-2/20170701.as-rel2.txt`;
- Stage 2 snapshot: `2024-04-01`;
- Stage 2 path: `data/evidence/as_relationships/as_rel_2024-04-01.parquet`;
- consistency status: `likely_inconsistent`;
- consistency risk level: `high`;
- primary affected fields: `rel_seq`, `rel_unknown_cnt`, `rel_has_unknown`, and S3-C path plausibility fields;
- required replay scope: `path_feature_reannotation_only`;
- recommended next action: `r_consist2_aligned_reannotation`.

Updated R-CONSIST branch:

```text
R-CONSIST-1 provenance audit
  -> no_action_needed / metadata_patch_only if Stage 1 has no relevant AS-rel dependency or is already aligned
  -> R-CONSIST-2 aligned reannotation if only AS-rel-derived weak/path fields need refresh
  -> R-CONSIST-2 aligned Stage 1 replay if candidate, gate, or incident construction depends on stale AS-rel fields
  -> report drift / impact analysis before final paper main results if any mixed snapshot remains
```

Safety boundaries:

- Stage 1 AS-rel is a weak trigger/context source, not verifier truth.
- Stage 2 AS-rel is versioned verifier evidence with confidence caps, not route-leak truth.
- Final main experiments must use consistent evidence cache snapshots or report drift/impact analysis.
- Unreported mixed AS-rel snapshots are not allowed in the final paper claim.

## 22. R-DOC-1 Decision Consolidation and Near-term Gates

R-DOC-1 consolidates recent research-control decisions into long-lived documents before more implementation work proceeds.

Decision register:

- `project_docs/PROJECT_DECISION_REGISTER.md`

Locked decisions:

- three-stage architecture remains the final paper-facing structure;
- Stage 1 is weak trigger / organizer / lookup-key provider;
- Stage 2 is provenance-aware verifier evidence;
- Stage 3 learning is after verifier and before Top-K;
- Top-K is the human-facing output, not the learning layer;
- final outputs use a unified taxonomy with `primary_family`, `observability_mode`, `verifier_state`, and `evidence_tags`;
- no category explosion from evidence combinations;
- `forged_origin_like + weak_signal` remains a core output combination;
- communities / NO_EXPORT require propagation schema design before verifier use;
- AS-rel versioned evidence cache consistency must be resolved or reported before final main-result claims.

Updated near-term route:

```text
R-DOC-1 decision consolidation
  -> R-OUT-1 unified incident output taxonomy design
  -> R-CONSIST-2 aligned AS-rel reannotation / impact comparison
  -> R-2D-P0-design communities propagation schema
  -> R-2D-P0-repair and R-2D-0 rerun
  -> R-3 poisoning/evasion benchmark design
  -> L1 component-aware semantic learner design
```

Do not directly enter learning. Formal learning waits until R-OUT-1, R-CONSIST handling, and R-2D-P0 propagation design are stable.

## 23. R-AGG-ENTRY-0 Raw Incident Entry Point Audit

R-AGG-ENTRY-0 was added because Stage 1 cannot be treated as "whatever final labels already produced". The old seven-layer chain remains useful, but Raw Incident Dossier construction must avoid inheriting hidden gate/augment/final judgment as if it were truth.

Scope:

- compare event, candidate, scored, gated, augmented, and final entry points;
- audit field availability, judgment contamination, noise exposure, aggregation explainability, evidence readiness, and learning readiness;
- do not rerun raw/events/baseline/candidate/score/gate/augment/final;
- do not modify old verifier/evidence outputs;
- do not create attack/benign truth labels;
- do not train learning.

Implementation entry:

- `scripts/audit_raw_incident_entry_points.py`
- `project_docs/R_AGG_ENTRY_0_RAW_INCIDENT_ENTRY_AUDIT.md`

Core route change:

```text
legacy seven-layer pipeline
  -> Raw Incident Dossier
  -> Evidence-grounded Incident
  -> Evidence-constrained Verification
  -> Component-aware Learning Triage
  -> Top-K Review Queue
```

Verification / evidence grounding must not connect directly to old final labels. External evidence should enter Evidence-grounded Incident records and verifier evidence states, not rewrite `final_alert_label`.

R-AGG-ENTRY-0 result:

- recommended main entry: `candidate-entry`;
- recommended auxiliary entries: `event-entry` and `scored-entry`;
- not recommended as main Raw Incident entry: `gated-entry`, `augmented-entry`, `final-entry`;
- final labels are weak workflow signals, not truth labels;
- final-entry has high judgment contamination because it already carries final/gating/augmentation workflow decisions.

Safety boundaries:

- high/needs/low are not truth;
- P1/P2/P3 are not truth;
- no truth label is produced by R-AGG-ENTRY-0;
- background-like is operational suppression, not confirmed benign;
- family_hint is semantic hint, not confirmed attack label;
- Raw Incident Dossier may carry weak hints, but Stage 2 verifier state must remain evidence-constrained;
- poisoning benchmark retained as the key robustness evaluation path;
- learning layer postponed until Raw Incident Dossier and Evidence-grounded Incident schemas are stable;
- future learning should move toward BEAM-style semantic learning for representation/prioritization, not legacy rule re-scoring.

Updated near-term route:

```text
R-AGG-ENTRY-0 entry point audit
  -> R-AGG-1 Raw Incident Dossier schema design
  -> Evidence-grounded Incident construction
  -> R-OUT-1 unified output taxonomy if schema fields need further tightening
  -> R-CONSIST-2 / R-2D-P0 repairs where evidence provenance blocks final claims
  -> R-3 poisoning/evasion benchmark design
  -> L1 component-aware semantic learner design
```

## 24. R-EVID-0 Lightweight Evidence Pre-Triage Gate

R-EVID-0 was added after R-AGG-3 because Raw Incident compression cannot safely proceed from Stage 1 hints alone. R-AGG-3 showed that background-like operational candidates and high-value weak signals heavily overlap, so any pre-incident filter or safe merge needs evidence-aware protection first.

Scope:

- audit lightweight evidence availability over R-AGG-2 Raw Incident prototypes;
- use local RPKI / VRP cache as origin evidence for triage protection only;
- use event-entry `rel_*` fields as path diagnostic signals only;
- design `protected_suspicious`, `suppressible_background_like`, and `gray_zone_retained`;
- do not delete rows, implement suppression, implement safe merge, modify verifier outputs, or train learning.

R-EVID-0 result:

- raw incidents: `3128971`;
- RPKI coverage: `0.550384`;
- AS-rel/path diagnostic event join: `1.0`;
- communities / NO_EXPORT in Raw Incident: `0.0`;
- protected_suspicious: `2908323` (`0.929482`);
- suppressible_background_like: `0` (`0.0`);
- gray_zone_retained: `220648` (`0.070518`);
- protected_background_overlap_rate: `0.92477`;
- stop-loss decision: `do_not_enter_R_EVID_1_yet`.

Safety boundaries:

- RPKI invalid is not attack truth.
- AS-rel diagnostic is not route leak truth.
- background-like is not benign.
- `protected_suspicious` is a triage protection state, not a confirmed attack.
- `suppressible_background_like` is a future low-priority candidate state, not deletion.
- `gray_zone_retained` is reliability control, not model failure.
- Learning remains downstream of Evidence-grounded Incident and must target BEAM-style semantic learning, not rule re-scoring.

Updated route:

```text
R-AGG-3 quality audit
  -> R-EVID-0 lightweight evidence pre-triage design
  -> stop-loss triggered
  -> R-AGG-4 family_hint mapping repair
  -> rerun R-EVID-0
  -> R-EVID-1 evidence pre-triage smoke only if overlap risk is reduced
  -> Evidence-grounded Incident construction
```

## 25. R-RESET-1 Mainline Pivot

R-RESET-1 pivots the mainline based on R-AGG/R-EVID stop-loss evidence.

Decision:

- `full candidate-entry incident aggregation stopped` as the paper-facing mainline.
- The new route is a `noise-filtered multi-attack judgment pipeline`.
- Evidence grounding serves judgment and explanation first, not final/high/needs/low rewriting and not pure ranking.
- `incident aggregation after judgment` becomes the main aggregation path.

New route:

```text
raw BGP / candidate events
  -> obvious noise suppression / foreground extraction
  -> multi-attack judgment layer
  -> attack-like incident aggregation
  -> evidence explanation
  -> poisoning/evasion robustness evaluation
```

Safety boundaries:

- background is not ranked in the primary human-facing output;
- background_noise is not confirmed benign;
- RPKI invalid is not attack truth;
- AS-rel diagnostic is not route leak truth;
- multi-attack judgment layer is not semantic ranking;
- poisoning/evasion robustness is core.

Judgment outputs:

- `suspicious_forged_origin`;
- `suspicious_route_leak`;
- `suspicious_path_manipulation`;
- `suspicious_stealth_visibility`;
- `poisoning_or_evasion_suspected`;
- `background_noise`;
- `uncertain_need_evidence`.

Updated near-term route:

```text
R-RESET-1 mainline pivot
  -> R-NOISE-0 obvious noise audit
  -> R-NOISE-1 conservative foreground extraction smoke
  -> R-LEARN-0 multi-attack judgment layer design
  -> R-POISON-0 poisoning benchmark design
  -> R-INC-0 attack-like incident aggregation after judgment
```

R-NOISE-1 is complete as a smoke and guardrail check. It does not provide attack recall or poisoning/evasion recall; those require known-incident replay and controlled benchmark design.
