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
- `stale_diagnostic`: old or non-time-aligned evidence; useful for explanation, not strong judgment.
- `unavailable`: evidence source absent.
- `conflicting`: evidence sources disagree materially.
- `monitor_only`: only public-monitor evidence is present.
- `poisoning_susceptible`: evidence is derived from monitor history or crafted-announcement-sensitive patterns.
- `external_confirmed_pending`: candidate requires operator/report/data-plane confirmation.

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
