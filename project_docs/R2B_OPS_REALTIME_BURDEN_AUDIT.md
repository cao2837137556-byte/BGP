# R-2B-OPS Operational Burden and Real-Time Evidence Cache Audit

Status: fixed S2 full audit completed.

Run id: `s2a_expanded_v01_pilot_6h_april16`

Run date: `2024-04-16`

Output directory: `outputs/r2b_ops_realtime_burden_audit_v01/`

## 1. Why This Stage

R-2B showed that aligned VRP/RPKI evidence can be attached to all fixed S2 incidents while preserving Phase R hard safety rules. The next CCF-A-relevant question is operational: a verifier-centric system must not only produce safer verdicts; it must also define how many cases a deployment can review, how Top-K queues are controlled, and how evidence caches behave in near-real-time operation.

R-2B-OPS is therefore not a new verifier experiment. It is an operational audit over the R-2B verifier table. It does not download new evidence, does not modify verifier verdicts, does not train a learning layer, and does not implement R-2C path legality.

## 2. Real Deployment Human Burden Constraints

The fixed S2 window is six hours. Daily counts below use a simple linear scale factor of `4`. They are workload proxies, not production measurements.

| Queue type | 6h count | Projected daily count | Review policy |
| --- | ---: | ---: | --- |
| strongly_supported_suspicious | 0 | 0 | page immediately |
| evidence_supported_suspicious | 55 | 220 | high-priority Top-K queue |
| evidence_conflict | 86 | 344 | bounded conflict queue |
| abstain | 4684 | 18736 | selective review only |
| evidence_insufficient | 55366 | 221464 | ranker / Top-K / wait for more evidence |
| background_like_but_unconfirmed | 156971 | 627884 | sampling audit only |
| external_evidence_unavailable | 3 | 12 | cache-health and selective review |
| mixed_should_split | 4689 | 18756 | split-candidate queue |
| mixed_but_core_suspicious | 479 | 1916 | component-review queue |
| high_impact_insufficient | 53694 | 214776 | ranked evidence-gap queue |

The key guardrail is that `abstain`, `evidence_insufficient`, and `background_like_but_unconfirmed` must not be handed to humans in full. They are control states for safe degradation and deferred enrichment, not direct manual-review obligations.

## 3. Top-K Review Policy

R-2B-OPS uses a deterministic smoke triage score. It is not a trained model. It prioritizes evidence-supported verdicts, mixed-core suspicious components, conflict visibility, and high-impact insufficient cases.

| Top-K | Evidence-supported | Conflict | Abstain | Insufficient | Background-like | Supported density | Reduction vs legacy P1/P2 | Reduction vs all incidents |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 50 | 50 | 0 | 0 | 0 | 0 | 1.0000 | 0.9991 | 0.9998 |
| 100 | 53 | 11 | 36 | 0 | 0 | 0.5300 | 0.9982 | 0.9995 |
| 500 | 55 | 65 | 380 | 0 | 0 | 0.1100 | 0.9909 | 0.9977 |

This result supports the verifier-centric workload claim: human review should be a Top-K evidence-supported triage queue, not full inspection of all legacy P1/P2, abstain, or insufficient cases.

## 4. External Evidence Cache Architecture

The intended deployment architecture separates the online path from evidence acquisition.

Online path:

```text
BGP stream / MRT updates
  -> event window
  -> candidate trigger
  -> incident and component builder
  -> local evidence cache lookup
  -> verifier verdict
  -> queue manager
  -> dashboard / report
```

Async evidence path:

```text
RPKI/VRP updater
AS-rel updater
IRR updater
PeeringDB updater
known-event updater
optional data-plane updater
  -> normalize
  -> versioned local cache
  -> index build
  -> atomic cache switch
  -> provenance and freshness metadata
```

The online verifier must not perform per-incident remote downloads. RPKI/VRP should be maintained by a relying-party / RTR-style background updater or an equivalent cache materialization process. IRR, AS relationship, PeeringDB, known-event, and optional data-plane sources can be lower-frequency asynchronous enrichments.

## 5. Freshness and Fallback Policy

Cache stale or unavailable states must not block monitor-triggered candidate generation. They lower evidence state and may produce `evidence_insufficient`, `external_evidence_unavailable`, `stale_evidence_only`, `abstain`, or `evidence_conflict`.

| Evidence type | Expected refresh | Stale behavior | Missing behavior | Blocks alerting |
| --- | --- | --- | --- | --- |
| RPKI/VRP | minutes to hours | stale diagnostic / evidence insufficient | external evidence unavailable | no |
| AS relationship | monthly or release-based | diagnostic only | unavailable | no |
| IRR | daily to weekly | diagnostic or conflict | unavailable | no |
| ASPA | minutes to daily when available | stale diagnostic | unavailable | no |
| BGP Roles / OTC | daily to weekly when available | stale diagnostic | unavailable | no |
| PeeringDB | weekly to monthly | context only | unavailable | no |
| known-event reports | async/manual | provenance-limited | unavailable | no |
| data-plane evidence | async/on demand | not applicable or stale diagnostic | no block | no |
| public monitor context | streaming/windowed | trigger/context only | reduce confidence | no |

No stale or unavailable evidence state can be interpreted as benign.

## 6. Real-Time SLO Draft

R-2B-OPS does not claim that the system already satisfies production SLOs. It defines measurement hooks for a future near-real-time implementation:

- online event-to-candidate latency;
- incident update interval;
- local evidence lookup latency;
- queue update interval;
- cache refresh interval;
- cache staleness rate;
- unsupported alert ratio;
- daily human review budget;
- Top-K supported density;
- conflict queue size;
- abstain queue size;
- background sampling rate;
- evidence cache failure fallback rate.

The key implementation target is that online evidence lookup is local and indexed. External downloads belong to background cache updaters.

## 7. Relationship to the CCF-A Target

The CCF-A claim cannot stop at an offline verifier table. It must address deployment burden and robust degradation. R-2B-OPS turns that into explicit constraints:

- daily human review must be bounded by Top-K and sampling policy;
- online path must not depend on remote evidence downloads;
- cache stale/unavailable states must remain visible;
- abstain and insufficient states are not failures but safety-preserving outcomes;
- background-like incidents are not confirmed normal and should be sampled, not treated as negative ground truth.

## 8. Current Limits

R-2B-OPS is a workload proxy and architecture audit only. It does not:

- complete real deployment;
- measure live BGP stream latency;
- implement a cache updater;
- attach new evidence sources;
- modify R-2B verifier verdicts;
- train L1/L2 learning components;
- perform R-3 poisoning/evasion evaluation.

## 9. Next Step

Recommended next steps:

1. R-2C path evidence branch / route-leak legality refinement.
2. R-3 poisoning benchmark design in parallel.
3. L1 component-aware semantic learner design in parallel.

Formal learning training remains blocked. L1 design can begin, but training requires verifier-supported targets, robustness scenarios, and provenance-aware evaluation.
