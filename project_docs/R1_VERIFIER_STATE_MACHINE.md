# R-1 Verifier State Machine

Last updated: 2026-05-17

Status: design only. No experiment has been run for R-1, and no verifier implementation is implied by this document.

## 1. Purpose

R-1 defines the verifier state machine for Phase R.

Goals:
- Convert legacy detector output and incident queues into verifier inputs.
- Define a multi-evidence state machine.
- Define verdict, confidence, provenance, and abstention logic.
- Provide the design base for R-2 legality-first verifier, R-3 poisoning/evasion benchmark, and R-4 multi-evidence evaluation.

Non-goals:
- No experiment code.
- No detector rerun.
- No change to score/gate/final/incident artifacts.
- No claim that these rules are experimentally calibrated.

## 2. Inputs

### Legacy Detector / Monitor-Side Inputs

These are treated as monitor-side evidence, not truth labels:
- candidate event
- `final_label`: `high_priority_alert`, `needs_review`, `low_priority_or_background`
- `incident_priority`: `P1_high`, `P2_review`, `P3_background`
- `pattern_A`
- `pattern_B`
- `path_plausibility_score`
- `gate_evidence_flag`
- monitor visibility / collector count
- temporal duration / recurrence
- historical baseline deviation

### External Evidence Inputs

External evidence can support or constrain a verdict when time-aligned and provenance is present:
- RPKI / ROA / VRP
- IRR / route object
- AS relationship
- ASPA
- BGP Roles / OTC
- PeeringDB / IXP / facility hints
- known-event / operator report
- optional data-plane signal

### Metadata Inputs

Every evidence item must carry metadata:
- evidence timestamp
- run timestamp
- evidence source
- evidence freshness
- cache alignment
- stale / unavailable / conflict flags
- provenance record

Minimum provenance schema:
- `source_name`
- `source_type`
- `snapshot_time`
- `valid_time`
- `cache_path`
- `collector_set`
- `alignment_status`
- `stale_reason`
- `lookup_key`

## 3. Evidence State Machine

R-1 uses per-evidence states. A single incident can have different states for RPKI, IRR, AS relationship, path legality, temporal support, collector diversity, and monitor evidence.

`poisoning_susceptible` is both a state and a modifier. It can be assigned to an evidence source when that evidence is primarily derived from public monitor history or crafted-announcement-sensitive features.

| State | Meaning | Applies to | Strong verdict use | Diagnostic only | Abstain trigger | Learning layer role |
| --- | --- | --- | --- | --- | --- | --- |
| `aligned_strong` | Time-aligned, provenance complete, reliable source, not dependent on a single public monitor. | ASPA, BGP Roles/OTC, data-plane evidence, time-aligned operator report, strong path legality. | Yes, as support, not confirmed truth alone. | No. | No by itself. | Feature and positive-candidate support. |
| `aligned_medium` | Time-aligned and useful, but incomplete or insufficient alone. | RPKI/ROA, AS relationship, IRR, temporal persistence, collector diversity. | Conditional, only with corroboration. | No. | No by itself. | Feature and calibration input. |
| `aligned_weak` | Time-aligned but weak, indirect, or easily biased. | PeeringDB hints, low collector support, weak temporal signal. | No alone. | Usually yes. | Can contribute to insufficient verdict. | Ranking feature only. |
| `stale_diagnostic` | Evidence exists but is not time-aligned or is too old for strong use. | old AS-rel, old IRR, old PeeringDB, out-of-window known event. | No. | Yes. | Yes if no aligned evidence exists. | Provenance/caution feature. |
| `unavailable` | Evidence source is absent or lookup cannot be performed. | any external evidence source. | No. | No. | Yes, can produce `evidence_insufficient`, `external_evidence_unavailable`, or `abstain`. | Missingness feature; not negative label. |
| `conflicting` | Two or more evidence sources disagree materially. | RPKI vs IRR, path legality vs monitor, operator report vs monitor. | No until resolved. | No. | Yes. | Conflict class, preserved as its own category. |
| `monitor_only` | Only public monitor / legacy detector evidence is present. | candidate trigger, high/needs/P1/P2, pattern_A/B without external support. | No. | Yes. | Can trigger abstain or review. | Monitor evidence feature; confidence capped. |
| `poisoning_susceptible` | Evidence depends on crafted-announcement-sensitive public monitor history or public baseline. | historical baseline novelty, path novelty, pattern_A, monitor-derived graph features. | No alone. | Yes unless corroborated. | Can require extra evidence. | Poisoning-risk feature and confidence cap. |
| `external_confirmed_pending` | A candidate requires operator, report, data-plane, or external confirmation before stronger status. | high-impact cases lacking independent evidence. | No until confirmation arrives. | Yes. | Yes. | Review-routing feature. |
| `not_applicable` | Evidence type is not meaningful for this incident or lookup key. | ASPA for unsupported analysis, RPKI for malformed/private/unparseable prefix-origin, data-plane unavailable by design. | No. | No. | Usually no, unless too many core sources are not applicable. | Schema completeness; distinct from unavailable. |

### State Precedence

Hard-rule precedence:

```text
conflicting
  > stale_diagnostic / unavailable
  > poisoning_susceptible / monitor_only
  > aligned_weak
  > aligned_medium
  > aligned_strong
```

This means:
- conflict remains visible even when some strong evidence exists,
- stale evidence cannot become strong through scoring,
- unavailable evidence cannot imply benign,
- monitor-only evidence cannot produce `strongly_supported_suspicious`,
- poisoning-susceptible evidence lowers confidence or requires extra support.

## 4. Evidence Type Policy

| evidence_name | description | manipulability_risk | freshness_required | can_be_strong_evidence | can_trigger_abstain | can_support_suspicious | can_support_background_like | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| monitor evidence | Public BGP monitor updates, AS paths, collector observations, legacy final labels. | high | yes | no | yes | conditional | conditional | Candidate trigger only. |
| historical baseline evidence | Prior path/origin/prefix behavior from public monitors. | high | yes | no | yes | conditional | conditional | Poisoning risk is high. |
| RPKI / ROA / VRP | Origin validation evidence. | low-medium | yes | conditional | yes | conditional | no | Validates origin only, not full AS path. Invalid is not confirmed attack; valid is not confirmed benign. |
| IRR / route object | Registry route/route6 authorization and descriptive metadata. | medium | yes | conditional | yes | conditional | conditional | Stale IRR is diagnostic only. |
| AS relationship | Provider/customer/peer relationship snapshot. | medium | yes | conditional | yes | conditional | conditional | Stale AS-rel snapshot is diagnostic only. |
| ASPA | Path authorization evidence when deployed and time-aligned. | low | yes | yes | yes | yes | conditional | Strong path-legality candidate when available and aligned. |
| BGP Roles / OTC | Route leak semantics and OTC/role evidence. | low | yes | yes | yes | yes | conditional | Strong route-leak support when available and aligned. |
| PeeringDB / IXP hints | Facility, IXP, and peering metadata. | medium | yes | no | yes | conditional | conditional | Auxiliary only; cannot close a case alone. |
| temporal persistence | Duration and recurrence of incident evidence. | medium | yes | no | yes | conditional | yes | Supports confidence and review priority. |
| collector diversity | Number and diversity of collectors/vantage points. | medium-high | yes | no | yes | conditional | yes | Public monitor coverage can be biased. |
| path legality | Valley-free, triplet, ASPA-ready, role/OTC legality checks. | medium | yes | yes | yes | yes | conditional | Strong only if source snapshots are aligned. |
| known-event report | Time-aligned public report or operator report. | low-medium | yes | yes | yes | yes | no | Out-of-window overlap is diagnostic only. |
| optional data-plane evidence | RTT/reachability/traffic or operator-side observation. | low | yes | yes | yes | yes | conditional | High value but may be unavailable. |

Family-specific hints:
- Forged-origin verification should prioritize RPKI/ROA, IRR, origin ownership, operator report, temporal/collector support, and path plausibility.
- Route-leak verification should prioritize path legality, ASPA, BGP Roles/OTC, AS relationship, triplet checks, and temporal/collector support.
- Low-visibility or monitor-evasive incidents should preserve abstention rather than forcing background labels.

## 5. Verdict Space

| Verdict | Trigger conditions | Forbidden conditions | Confidence range | Learning layer use | Positive candidate | Negative candidate | Human review | Top-K case study |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `strongly_supported_suspicious` | Not monitor-only; at least one aligned strong external evidence or multiple aligned medium evidence sources agree; no key conflict. | RPKI invalid alone; stale-only; unavailable-only; monitor-only; unresolved conflict. | 0.75-0.90 | positive_candidate | yes, candidate only | no | high | yes |
| `evidence_supported_suspicious` | Monitor evidence plus aligned RPKI/ROA anomaly, path legality conflict, patternB with path support, or route leak-like with Roles/OTC/ASPA support. | monitor-only; stale-only; conflict hidden by score. | 0.55-0.80 | positive_candidate | yes, candidate only | no | high/medium | yes |
| `evidence_conflict` | RPKI/IRR/AS-rel/path-legality/monitor evidence materially disagree. | Any rule that hides conflict. | 0.20-0.55 | conflict_class | no | no | high | yes if illustrative |
| `evidence_insufficient` | Suspicious monitor signal exists but aligned external evidence is missing or too weak. | Labeling as benign or confirmed normal. | 0.20-0.50 | abstain_class / ranking_only | no | no | medium | sometimes |
| `external_evidence_unavailable` | Required evidence source is unavailable for the incident family. | Treating unavailable as benign. | 0.00-0.45 | abstain_class | no | no | medium/low | no unless coverage study |
| `background_like_but_unconfirmed` | Large fan-out, low confidence, low high share, monitor-only or dispersed weak evidence. | Confirmed normal, negative ground truth. | 0.20-0.55 | ranking_only | no | no | low / sampling | sometimes |
| `stale_evidence_only` | Only stale external evidence exists beyond monitor evidence. | Strong verdict; confirmed attack/benign. | 0.00-0.40 | ranking_only | no | no | low/medium | no |
| `abstain` | Evidence unavailable, stale, conflicting, not applicable to core question, or poisoning risk too high. | Treating abstention as failure or benign. | 0.00-0.55 | abstain_class | no | no | policy-dependent | yes if abstention behavior is evaluated |

`strongly_supported_suspicious` still does not mean confirmed attack. It means the verifier has strong support under current evidence and provenance.

## 6. Verdict Transition Table

| Scenario | Evidence state | Allowed verdict | Forbidden verdict | Confidence cap | Review priority | Learning eligibility | Rationale |
| --- | --- | --- | --- | ---: | --- | --- | --- |
| monitor-only suspicious | `monitor_only` + possible `poisoning_susceptible` | `evidence_insufficient`, `abstain` | `strongly_supported_suspicious`, confirmed attack | 0.45 | medium | abstain_class / ranking_only | Monitor output is trigger only. |
| RPKI invalid only | `aligned_medium` RPKI, no other support | `evidence_insufficient`, `external_evidence_unavailable` if others missing | confirmed attack, `strongly_supported_suspicious` | 0.55 | medium | ranking_only | RPKI invalid is origin evidence, not full incident truth. |
| RPKI valid + suspicious monitor | RPKI `aligned_medium`, monitor suspicious | `evidence_conflict`, `evidence_insufficient` | confirmed benign | 0.55 | high/medium | conflict_class or ranking_only | RPKI valid does not validate path or benignness. |
| RPKI unknown + suspicious monitor | RPKI `unavailable`/unknown, monitor suspicious | `external_evidence_unavailable`, `evidence_insufficient`, `abstain` | benign | 0.45 | medium | abstain_class | Unknown evidence cannot resolve the incident. |
| path-legality violation + monitor support | path legality `aligned_strong`/`aligned_medium`, monitor support | `evidence_supported_suspicious`, maybe `strongly_supported_suspicious` if corroborated | confirmed attack | 0.80 | high | positive_candidate | Stronger for route leak/path manipulation. |
| path-legality unavailable + patternB | patternB monitor evidence, path legality `unavailable` | `evidence_insufficient`, `external_evidence_unavailable`, `abstain` | `strongly_supported_suspicious` | 0.50 | medium | abstain_class / ranking_only | PatternB needs path-legality evidence. |
| stale AS-rel only | `stale_diagnostic` | `stale_evidence_only`, `evidence_insufficient` | strong verdict | 0.40 | low/medium | ranking_only | Stale AS-rel is explanation only. |
| conflicting RPKI and IRR | `conflicting` | `evidence_conflict`, `abstain` | suspicious/benign verdict hiding conflict | 0.55 | high | conflict_class | Conflict must remain visible. |
| public monitor poisoning suspected | `poisoning_susceptible` | `evidence_insufficient`, `abstain`, or supported verdict only with external evidence | monitor-only strong verdict | 0.45 without external evidence | high/medium | poisoning feature, not truth | Crafted-announcement risk lowers confidence. |
| low visibility + short duration + new path | monitor-only / `poisoning_susceptible` / aligned weak | `evidence_insufficient`, `background_like_but_unconfirmed`, `abstain` | confirmed normal, strong suspicious | 0.50 | medium/low | ranking_only | Could be weak signal or noise; do not overclaim. |
| route leak-like with OTC/Role support | BGP Roles/OTC `aligned_strong`, monitor support | `evidence_supported_suspicious`, maybe `strongly_supported_suspicious` with no conflict | confirmed attack | 0.85 | high | positive_candidate | Roles/OTC can strongly support route-leak verdict. |
| background-like fan-out with no high support | monitor-only weak / unavailable external evidence | `background_like_but_unconfirmed`, `evidence_insufficient` | benign / confirmed normal | 0.45 | low / sampling | ranking_only | Background-like is not normal ground truth. |

## 7. Confidence and Abstention

Confidence is not risk score. It measures evidence support quality.

Principles:
- unavailable, stale, and conflicting evidence lower confidence;
- aligned strong evidence can raise confidence;
- monitor-only confidence must be capped;
- poisoning-susceptible evidence must be capped or require external evidence;
- abstention is a reliability mechanism, not a failure.

Recommended confidence caps:

| Condition | Max confidence |
| --- | ---: |
| `monitor_only` | 0.45 |
| `stale_diagnostic` only | 0.40 |
| `evidence_insufficient` | 0.50 |
| `evidence_conflict` | 0.55, but verdict cannot be suspicious |
| aligned medium multi-evidence | 0.75 |
| aligned strong + consistency | 0.90 |
| poisoning-susceptible without independent evidence | 0.45 |
| background-like without external evidence | 0.45 |

## 8. Relationship To Learning Layer

R-1 does not train a model.

Learning layer rules:
- learning layer happens after verifier design;
- learning layer cannot override hard safety rules;
- learning input is incident evidence + verdict candidate + provenance;
- learning output is ranking, calibration, and review priority;
- learning output is not confirmed attack/benign;
- `strongly_supported_suspicious` and `evidence_supported_suspicious` can be positive candidates, not confirmed truth;
- `background_like_but_unconfirmed` cannot be used as negative ground truth;
- `abstain` and `evidence_conflict` must be preserved as separate categories.

## 9. Relationship To Previous S3 Outputs

| S3 output | R-1 role |
| --- | --- |
| high/needs/low | monitor-side legacy signal |
| P1/P2/P3 | legacy priority |
| pattern_A | weak / poisoning-susceptible / low-visibility evidence |
| pattern_B | path-abnormal verification candidate |
| S3-D queue | verifier input queue |
| S3-D2 evidence table | evidence attachment groundwork |
| S3-D2B alignment | cache readiness / provenance audit |

## 10. R-1 Deliverables

R-1 deliverables:
- `project_docs/R1_VERIFIER_STATE_MACHINE.md`
- `project_docs/R1_EVIDENCE_TYPES_AND_VERDICTS.md`
- updated `project_docs/VERIFIER_REDESIGN_ROADMAP.md`
- updated `project_docs/HANDOFF.md`
- updated `project_docs/EXPERIMENT_MAINLINE.md`
- updated `project_docs/README.md`

R-1 acceptance boundary:
- design accepted before R-2 implementation;
- no code changes;
- no experiment runs;
- no changes to old experiment outputs.
