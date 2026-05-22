# Simplified System Output Schema

Status: Phase R-LOCK-1 output schema lock.

This document explains the final system output in one incident-card format. It separates evidence, verifier verdict, learning rank, and Top-K review so later writing does not mix these layers.

## 1. One Incident Card Schema

An incident card is the unit shown to the verifier/ranker and eventually to human review.

```yaml
incident_id: incident_000000
parent_incident_id: incident_000000
component_id: component_000000
stage1_trigger_summary:
  legacy_score: 82.0
  legacy_final_label: high_priority_alert
  legacy_reasons:
    - single_collector_visibility
    - unseen_path_for_prefix_origin
legacy_priority_hint: P1_high

origin_evidence:
  rpki_status: invalid_asn
  rpki_evidence_state: aligned_medium
  why_not_truth: RPKI validates origin authorization only; invalid is not confirmed attack.

path_evidence:
  path_evidence_state: diagnostic_only
  route_leak_like_diagnostic_flag: true
  path_manipulation_like_diagnostic_flag: false
  why_not_truth: CAIDA AS-rel is inferred evidence; path diagnostics are not confirmed route leaks.

component_purity:
  component_purity_class: mixed_but_core_suspicious
  should_split_flag: false

verifier_output:
  verifier_verdict: evidence_supported_suspicious
  confidence_cap: 0.75
  abstain_reason: null
  conflict_reason: null

learning_ranker_output:
  review_priority_score: 0.91
  topk_rank: 17
  topk_bucket: Top-50
  recommended_action: review_component_core
```

The card is not a truth label. It is a compact provenance-preserving triage record.

## 2. Output Meaning Table

| Output field | Plain-language meaning | Used by | Not allowed interpretation |
| --- | --- | --- | --- |
| `rpki_status` | Origin authorization lookup result for prefix-origin pair | verifier, ranker | `valid` is not benign; `invalid` is not confirmed attack; `unknown` is not normal |
| `rpki_evidence_state` | Whether RPKI evidence is aligned, weak, stale, or unavailable | verifier | A medium evidence state is not truth |
| `path_evidence_state` | Strength/availability of AS-path relationship evidence | verifier, ranker | AS-rel matched is not benign; AS-rel violation is not confirmed route leak |
| `route_leak_like_diagnostic_flag` | Path evidence suggests a route-leak review signal | verifier, ranker, Top-K | Not a route-leak verdict |
| `path_manipulation_like_diagnostic_flag` | Path evidence suggests a path-manipulation review signal | verifier, ranker, Top-K | Not a confirmed path attack |
| `component_purity_class` | How clean or mixed the incident's internal components are | verifier, ranker | Mixed does not mean attack; pure does not mean benign |
| `should_split_flag` | Incident may need component splitting before final review | verifier, ranker | Not a verdict |
| `verifier_verdict` | Evidence-constrained verdict candidate | ranker, Top-K, report | Not confirmed ground truth |
| `confidence_cap` | Maximum confidence allowed by evidence quality | verifier, ranker | Not the legacy risk score |
| `abstain_reason` | Why the verifier refuses to overclaim | ranker, review queue | Not manual garbage bin |
| `conflict_reason` | Why evidence sources disagree | ranker, conflict queue | Not something the model can hide |
| `review_priority_score` | Learning-layer ranking/calibration output | Top-K queue | Not a verifier verdict or truth label |
| `topk_bucket` | Human review budget bucket | human review | Not a label quality guarantee |
| `recommended_action` | Next review action such as split, wait, inspect, or sample | analyst workflow | Not automatic mitigation |

## 3. Five Example Incident Cards

These examples are schematic. They should not be read as confirmed attacks or confirmed benign cases.

### Example A: New origin + RPKI invalid + path diagnostic + pure component

```yaml
origin_evidence:
  rpki_status: invalid_asn
  rpki_evidence_state: aligned_medium
path_evidence:
  path_evidence_state: aligned_medium
  route_leak_like_diagnostic_flag: true
component_purity:
  component_purity_class: pure_dominant
verifier_output:
  verifier_verdict: evidence_supported_suspicious
  confidence_cap: 0.75
learning_ranker_output:
  topk_bucket: Top-50
  recommended_action: review_origin_and_path_evidence
```

Interpretation: evidence-supported review candidate. Not a confirmed attack.

### Example B: RPKI valid + path diagnostic + mixed component

```yaml
origin_evidence:
  rpki_status: valid
  rpki_evidence_state: aligned_medium
path_evidence:
  path_evidence_state: diagnostic_only
  path_manipulation_like_diagnostic_flag: true
component_purity:
  component_purity_class: highly_mixed_should_split
verifier_output:
  verifier_verdict: evidence_insufficient
  confidence_cap: 0.50
learning_ranker_output:
  topk_bucket: split_queue
  recommended_action: split_component_before_review
```

Interpretation: path diagnostic exists, but RPKI valid is not benign and the mixed component blocks stronger claims.

### Example C: RPKI unknown + high unknown path + mixed

```yaml
origin_evidence:
  rpki_status: unknown
  rpki_evidence_state: aligned_weak
path_evidence:
  path_evidence_state: evidence_insufficient
component_purity:
  component_purity_class: highly_mixed_should_split
verifier_output:
  verifier_verdict: abstain
  confidence_cap: 0.50
  abstain_reason: high_unknown_path_and_mixed_component
learning_ranker_output:
  topk_bucket: wait_or_split
  recommended_action: wait_for_evidence_or_split
```

Interpretation: abstention is the safe answer, not a failure.

### Example D: Background-like + no evidence support

```yaml
origin_evidence:
  rpki_status: valid
  rpki_evidence_state: aligned_medium
path_evidence:
  path_evidence_state: aligned_weak
component_purity:
  component_purity_class: insufficient_component_signal
verifier_output:
  verifier_verdict: background_like_but_unconfirmed
  confidence_cap: 0.45
learning_ranker_output:
  topk_bucket: sample_only
  recommended_action: low_priority_sampling
```

Interpretation: likely background-like, but not confirmed normal and not a negative training label.

### Example E: Origin/path evidence conflict

```yaml
origin_evidence:
  rpki_status: invalid_length
  rpki_evidence_state: aligned_medium
path_evidence:
  path_evidence_state: conflict
component_purity:
  component_purity_class: mixed_conflicting
verifier_output:
  verifier_verdict: evidence_conflict
  confidence_cap: 0.55
  conflict_reason: origin_path_component_disagreement
learning_ranker_output:
  topk_bucket: conflict_queue
  recommended_action: manual_conflict_review
```

Interpretation: conflict must remain visible and must not be hidden by a model or score.

## 4. Where Learning Layer Sits

Correct ordering:

```text
Verifier
  -> Learning Ranker
  -> Top-K Review Queue
```

Incorrect ordering:

```text
Verifier
  -> Top-K Review Queue
  -> Learning
```

Also incorrect:

```text
Learning
  -> override verifier hard rules
```

The learning layer consumes verifier outputs and evidence features. It ranks, calibrates, and recommends review actions. It does not change `evidence_conflict` into `supported`, convert `background_like_but_unconfirmed` into normal, or treat unavailable evidence as benign.

## 5. Abstain Handling

`abstain` is not a manual garbage bin.

Abstain routes:

- split component;
- wait for evidence;
- conflict queue;
- low-priority sample;
- high-impact Top-K only.

This prevents the system from dumping all hard cases onto analysts. Abstention is a reliability mechanism, and the learning ranker can prioritize abstain cases only when impact, recurrence, component purity, or evidence evolution justifies review.
