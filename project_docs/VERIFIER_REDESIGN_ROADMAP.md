# Verifier Redesign Roadmap

Last updated: 2026-05-17

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
