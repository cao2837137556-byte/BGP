# R-1 Evidence Types And Verdicts

Last updated: 2026-05-17

Status: design registry only. This document defines implementation-ready policy tables for the Phase R verifier, but it does not implement the verifier or run any experiment.

## 1. Evidence Type Registry

All evidence rows must preserve provenance and alignment state. Missing evidence is never converted into benign evidence.

| evidence_type | source | required_fields | freshness_requirement | alignment_requirement | manipulability_risk | strong_support_allowed | diagnostic_only_conditions | unavailable_behavior | conflict_behavior | example_verdict_effect |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `monitor_evidence` | public BGP monitors, legacy detector, final labels, incident priorities | event time, collector set, prefix, origin AS, AS path, final label, incident priority | yes | collector/time window must match incident window | high | no | single collector, low visibility, monitor-only, poisoning suspected | output `evidence_insufficient` or `abstain`; do not infer benign | preserve as `evidence_conflict` when external evidence disagrees | candidate trigger and review routing only |
| `historical_baseline_evidence` | prefix/origin/path history from public monitor data | baseline window, collector coverage, historical counts, novelty flags | yes | baseline window must predate and align with incident family | high | no | stale baseline, monitor poisoning risk, sparse history | reduce confidence and require external support | mark poisoning susceptibility or conflict | can explain novelty but cannot close case |
| `rpki_roa_vrp` | RPKI validator, VRP cache, ROA snapshot | prefix, origin AS, max length, status, snapshot time, valid time, cache path | yes | VRP valid time must cover incident time | low-medium | conditional | stale cache, unknown prefix-origin, malformed lookup | `external_evidence_unavailable` or `evidence_insufficient` | conflict remains visible against IRR/operator/path evidence | RPKI invalid can support suspicion, but is not confirmed attack |
| `irr_route_object` | IRR route/route6 objects | prefix, origin AS, source registry, object timestamp, maintainer when available | yes | object validity should cover incident time or be marked stale | medium | conditional | stale object, untrusted registry, ambiguous/multiple route objects | diagnostic gap, not benign | conflict against RPKI/operator evidence goes to `evidence_conflict` | supports ownership context if aligned |
| `as_relationship` | CAIDA or equivalent AS relationship snapshot | AS pair, relationship type, snapshot date, path mapping | yes | snapshot should be near incident time | medium | conditional | stale snapshot, unknown edges, incomplete path mapping | `external_evidence_unavailable` or weak path evidence | conflict against ASPA/roles/operator evidence remains visible | supports path relation reasoning if aligned |
| `aspa` | ASPA object cache and validator | customer/provider authorization, snapshot time, validation result | yes | ASPA data and path validation must align to incident time | low | yes | incomplete deployment coverage, missing AS pair | `external_evidence_unavailable` or `abstain` for path legality | conflict with AS-rel/monitor path is explicit | strong path-legality support when aligned |
| `bgp_roles_otc` | BGP Roles / OTC evidence | role/OTC fields, route direction, timestamp, path segment | yes | role/OTC evidence must be observed or validated for incident path | low | yes | unavailable route attributes, partial deployment | route-leak relation pending | conflict is explicit; do not hide with score | strong route-leak support when aligned |
| `peeringdb_ixp_hints` | PeeringDB, IXP/facility metadata | ASNs, facility/IXP hints, snapshot time, entity mapping | yes | snapshot should be near incident time and mapped to ASNs | medium | no | stale PeeringDB, entity mapping uncertainty | ignore for strong verdict; keep note | conflict lowers confidence but is usually auxiliary | context and explanation only |
| `temporal_persistence` | incident membership and event window | first seen, last seen, duration, recurrence count | yes | computed inside incident time window | medium | no | very short duration without recurrence | can trigger `evidence_insufficient` | conflict with reported event duration should be noted | confidence support and review priority |
| `collector_diversity` | collector coverage and visibility features | collector count, collector set, support ratio, visibility denominator | yes | collector set must match run and incident window | medium-high | no | single collector, biased coverage, unknown denominator | do not infer benign; mark weak support | conflict with external reports remains visible | confidence support and poisoning-risk control |
| `path_legality` | valley-free, triplet, ASPA-ready, role/OTC legality checks | representative path, relation data, legality result, validation method | yes | legality inputs must align to incident time | medium | yes, if inputs aligned | stale AS-rel only, unknown-heavy path, missing ASPA/roles | `external_evidence_unavailable`, `stale_evidence_only`, or `abstain` | conflict produces `evidence_conflict` | main support for route leak/path manipulation verification |
| `known_event_report` | public incident report, operator report, inventory | event id, prefix/origin/path fields, event time, source URL or inventory source | yes | time overlap is required for strong use | low-medium | yes, if time-aligned | out-of-window overlap, ambiguous asset-only match | not matched does not mean no true incident | conflict against monitor/external evidence requires review | case-study and positive-candidate support |
| `dataplane_evidence` | reachability, RTT, traffic, operator-side data-plane signal | vantage, method, timestamp, target, result | yes | measurement time must overlap incident | low | yes | method uncertainty, missing vantages | unavailable is expected and not benign | conflict produces review or abstain | high-value corroboration when available |

## 2. Verdict Registry

`safe_to_use_as_label` is deliberately conservative. No verifier verdict is a confirmed positive or confirmed negative label.

| verdict | required_evidence | forbidden_conditions | confidence_min | confidence_max | human_review_priority | learning_role | safe_to_use_as_label | notes |
| --- | --- | --- | ---: | ---: | --- | --- | --- | --- |
| `strongly_supported_suspicious` | at least one aligned strong external evidence source or multiple aligned medium sources, plus no key conflict | monitor-only, stale-only, unavailable-only, RPKI invalid alone, unresolved conflict | 0.75 | 0.90 | high | ranking and calibration | positive_candidate | Strong support, not confirmed attack. |
| `evidence_supported_suspicious` | monitor evidence plus aligned RPKI anomaly, path legality conflict, patternB path support, route leak role/OTC/ASPA support, or time-aligned report | monitor-only, stale-only, hidden conflict | 0.55 | 0.80 | high/medium | ranking and calibration | positive_candidate | Useful for top-K review and case study selection. |
| `evidence_conflict` | material disagreement among RPKI, IRR, AS-rel, ASPA, path legality, operator report, or monitor evidence | hiding conflict behind score, forcing suspicious/benign verdict | 0.20 | 0.55 | high | conflict handling | conflict_class | Conflict must remain visible. |
| `evidence_insufficient` | suspicious monitor signal with missing, weak, stale, or insufficient external evidence | benign/normal claim, strong suspicious claim | 0.20 | 0.50 | medium | abstention and review routing | abstain_class | Not benign; often review or defer. |
| `external_evidence_unavailable` | required external source unavailable or lookup impossible for incident family | treating unavailable as normal or harmless | 0.00 | 0.45 | medium/low | missingness calibration | abstain_class | Expected under partial observability. |
| `background_like_but_unconfirmed` | fan-out large, confidence low, high share low, mostly monitor-only or dispersed weak evidence | confirmed normal, negative ground truth, hiding residual risk | 0.20 | 0.55 | low / sampling | burden ranking | ranking_only | Low-priority review only; not a negative label. |
| `stale_evidence_only` | only stale external evidence exists beyond monitor signal | strong verdict, confirmed attack, confirmed benign | 0.00 | 0.40 | low/medium | provenance calibration | ranking_only | Signals evidence readiness problem. |
| `abstain` | evidence unavailable, stale, conflicting, not applicable, or poisoning-susceptible without support | treating abstain as failure or benign | 0.00 | 0.55 | policy-dependent | abstention modeling | abstain_class | A designed reliability outcome. |

## 3. Hard Safety Rules

- H1: RPKI invalid is not confirmed attack.
- H2: RPKI valid is not confirmed benign.
- H3: Public monitor-only evidence cannot produce `strongly_supported_suspicious`.
- H4: Stale evidence cannot produce strong verdict.
- H5: Unavailable evidence cannot imply benign.
- H6: P3 / low / background is not confirmed normal.
- H7: Learning layer cannot override hard verifier safety rules.
- H8: Evidence conflict must remain visible.
- H9: Poisoning-susceptible evidence must lower confidence or require extra support.
- H10: Abstain is an allowed and expected verifier outcome.

## 4. Implementation-Ready Schema Draft

This schema is a draft for future verifier parquet/csv output. R-1 does not implement it.

### Incident Identity

- `incident_id`
- `run_id`
- `incident_family`
- `legacy_priority`
- `legacy_final_label_distribution`

### Evidence State Fields

- `monitor_evidence_state`
- `rpki_evidence_state`
- `irr_evidence_state`
- `asrel_evidence_state`
- `aspa_evidence_state`
- `bgp_role_otc_evidence_state`
- `path_legality_state`
- `temporal_evidence_state`
- `collector_evidence_state`
- `known_event_evidence_state`
- `dataplane_evidence_state`

### Verdict Fields

- `verifier_verdict`
- `verifier_confidence`
- `confidence_cap_reason`
- `abstain_reason`
- `conflict_reason`
- `evidence_provenance_json`
- `evidence_strength_summary`
- `poisoning_susceptibility_score`
- `learning_eligibility`

### Suggested Provenance JSON Keys

- `source_name`
- `source_type`
- `snapshot_time`
- `valid_time`
- `lookup_key`
- `cache_path`
- `alignment_state`
- `staleness_days`
- `manipulability_risk`
- `failure_reason`

## 5. Examples

### Example 1: Monitor-Only Forged-Origin-Looking Event

Evidence states:
- monitor: `monitor_only`
- historical baseline: `poisoning_susceptible`
- RPKI/IRR/path legality: `unavailable`

Allowed verdict:
- `evidence_insufficient`
- `external_evidence_unavailable`
- `abstain`

Forbidden verdict:
- `strongly_supported_suspicious`
- confirmed attack
- confirmed benign

Confidence cap:
- 0.45

Review recommendation:
- Keep in review if impact is high; otherwise sample from lower-priority queue.

### Example 2: RPKI-Invalid But IRR / Route-Object Ambiguous Event

Evidence states:
- monitor: suspicious trigger
- RPKI: `aligned_medium`
- IRR: `conflicting` or `aligned_weak`
- path legality: `unavailable`

Allowed verdict:
- `evidence_supported_suspicious` if corroborated by temporal/collector/path support
- `evidence_conflict` if IRR materially disagrees
- `evidence_insufficient` if no corroboration exists

Forbidden verdict:
- confirmed attack from RPKI invalid alone
- `strongly_supported_suspicious` without additional aligned evidence

Confidence cap:
- 0.55 without corroboration
- 0.75 with aligned medium multi-evidence

Review recommendation:
- High review priority if impact or recurrence is high.

### Example 3: Route Leak-Like Event With BGP Roles / OTC Support

Evidence states:
- monitor: suspicious route leak-like trigger
- BGP Roles / OTC: `aligned_strong`
- path legality: `aligned_medium` or `aligned_strong`
- RPKI: `not_applicable` or `aligned_medium` for origin-only context

Allowed verdict:
- `evidence_supported_suspicious`
- `strongly_supported_suspicious` if there is no key conflict and multiple aligned sources agree

Forbidden verdict:
- confirmed attack
- benign because RPKI is valid

Confidence cap:
- 0.85

Review recommendation:
- High priority route-leak/path-legality review and top-K case-study candidate.

### Example 4: PatternB Path-Abnormal Event With Stale AS-Rel Only

Evidence states:
- monitor: patternB path-abnormal trigger
- AS relationship: `stale_diagnostic`
- path legality: `stale_diagnostic` or `unavailable`
- ASPA/BGP Roles: `unavailable`

Allowed verdict:
- `stale_evidence_only`
- `evidence_insufficient`
- `abstain`

Forbidden verdict:
- `strongly_supported_suspicious`
- confirmed route leak
- confirmed benign

Confidence cap:
- 0.40

Review recommendation:
- Keep as path-legality verification candidate, but require aligned AS-rel/ASPA/role evidence before stronger verdict.

### Example 5: Background-Like Fan-Out Incident With Unavailable External Evidence

Evidence states:
- monitor: low-confidence broad fan-out
- collector diversity: weak or dispersed
- RPKI/IRR/path legality: `unavailable`
- temporal persistence: weak or mixed

Allowed verdict:
- `background_like_but_unconfirmed`
- `external_evidence_unavailable`
- `evidence_insufficient`

Forbidden verdict:
- confirmed normal
- negative training label
- strong suspicious without aligned support

Confidence cap:
- 0.45

Review recommendation:
- Low-priority queue or sampled audit. Keep provenance so future evidence can revise the verdict.
