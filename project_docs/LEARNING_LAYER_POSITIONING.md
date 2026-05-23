# Learning Layer Positioning

Last updated: 2026-05-23

## 1. Core Judgment

The learning layer is not removed. It is moved later.

Before reliable verification labels exist, do not train an attack/benign classifier. The learning layer should become an incident-level ranker and evidence calibrator, not the primary detector or final judge.

For the current CCF-A target line, the learning layer must become a component-aware semantic ranker/calibrator. It should learn incident internal structure and verifier-supported weak signals; it must not downgrade the project into a detector-score classifier.

Current R-DOC-1 decision: do not train the learning layer yet. Learning must wait for the unified incident card schema, output taxonomy, evidence provenance, AS-rel consistency handling, and communities propagation design to stabilize.

## 2. Why Not Train Now

Do not train an attack/benign classifier from current outputs because:
- `P1 / P2 / P3` are not truth labels.
- `high_priority_alert / needs_review / low_priority_or_background` are not truth labels.
- `P3 / low / background` is not confirmed normal.
- RPKI valid or invalid is not direct ground truth.
- Monitor-centric historical patterns can be poisoned by crafted announcements.
- Training now would learn legacy rule bias and public-monitor bias.
- Unavailable evidence must not be converted into normal/benign labels.

## 3. New Role Of Learning Layer

Learning layer input:
- unified incident card
- incident evidence table
- evidence state
- provenance
- `primary_family`
- `observability_mode`
- `evidence_tags`
- component purity / mixture class
- dominant pair evidence and member-level evidence distribution
- monitor evidence
- RPKI / IRR / ASPA / path-legality evidence
- temporal and collector features
- poisoning susceptibility features
- verifier verdict candidates

Learning layer output:
- `review_priority_score`
- `evidence_consistency_score`
- `component_priority_score`
- `should_split_score`
- `topk_rank`
- `recommended_action`

The model ranks and calibrates. It does not override verifier safety rules.

## 3A. Placement Between Verifier And Top-K

R-LOCK-1 fixes the learning-layer position:

```text
Stage 2 verifier
  -> Stage 3 component-aware learning ranker / calibrator
  -> Top-K Review Queue
```

The learning layer is before Top-K, not after Top-K. It is the mechanism that orders and calibrates verifier-supported, conflict, insufficient, abstain, and background-like incident/component records under a review budget.

It is not allowed to:

- override verifier hard rules;
- turn `background_like_but_unconfirmed` into a negative label;
- hide `evidence_conflict` or `abstain`;
- convert unavailable evidence into benignness;
- replace the Top-K review queue with an unbounded manual workload;
- become a primary attack/benign detector trained from `high/needs/low` or `P1/P2/P3`.

Top-K is the human-facing queue produced after ranking. It is not the learning model itself.

Short form: Learning before Top-K, after the verifier.

```text
Verifier output
  -> Learning before Top-K
  -> Top-K Review Queue
```

## 4. When To Train

Train only after these conditions are met:
- verified or evidence-supported incident set exists
- supported suspicious / background-like-but-unconfirmed / conflict / insufficient strata are defined
- poisoning and evasion scenarios exist
- held-out windows exist
- evidence provenance is attached
- unavailable evidence is not treated as normal
- R-OUT-1 unified output taxonomy is settled
- R-CONSIST evidence-cache risks are handled or explicitly documented
- R-2D-P0 communities propagation schema is designed if stealth evidence is included

Minimum trainable unit:

```text
incident-level evidence record
  -> verifier verdict candidate
  -> optional human/operator review outcome
```

Not trainable as truth:

```text
legacy detector score
legacy high/needs/low label
legacy P1/P2/P3 priority
```

## 5. Possible Models

Candidate models, not current implementation targets:
- logistic regression / calibrated linear ranker
- gradient boosting ranker
- learning-to-rank
- graph representation over AS/path evidence
- semi-supervised anomaly ranking
- conformal prediction / abstention-aware calibration

Start simple. The first learning model should be interpretable enough to debug evidence leakage and label bias.

## 6. Safety Rule

The learning layer cannot override verifier hard safety rules:
- RPKI invalid is not confirmed attack.
- RPKI valid is not confirmed benign.
- stale evidence is not strong evidence.
- evidence conflict must not be hidden.
- unavailable evidence can trigger abstain.
- monitor-only evidence cannot produce `strongly_supported_suspicious`.
- background-like does not mean confirmed normal.

## 7. Relationship To S3 Outputs

S3 outputs become features, not labels:

| S3 field | Learning-layer role |
| --- | --- |
| detector risk score | monitor-derived evidence feature |
| final high/needs/low | legacy detector output feature |
| P1/P2/P3 | legacy triage priority feature |
| S3-C plausibility | evidence feature |
| S3-D queue | verifier workflow feature |
| S3-D2 evidence status | evidence state feature |
| S3-D2B alignment readiness | evidence provenance / coverage feature |

## 8. First Safe Learning Target

The first safe learning task is:

```text
incident-level review prioritization under verifier constraints
```

It should answer:
- Which incidents deserve top-K human review first?
- Which evidence conflicts need operator attention?
- Which cases should abstain until external evidence is attached?
- Which background-like cases are low priority but not confirmed normal?
- Which component-mixed incidents should be split before any incident-level verdict?
- Which verifier-supported components carry semantic evidence worth preserving under poisoning?

It should not answer:
- Is this attack or benign?
- Can this low-priority incident be used as a negative label?
- Can the model ignore missing evidence?

## 9. CCF-A Component-Aware Learning Target

For the CCF-A target line, learning is positioned as:

```text
component-aware semantic ranker / evidence calibrator
```

It should consume R-2B/R-2C style verifier tables, including:

- dominant prefix-origin evidence;
- member/component evidence distribution;
- `component_purity_class`;
- `should_split_incident_flag`;
- `evidence_conflict` and `abstain` outcomes;
- path legality / route-leak evidence when R-2C is complete;
- poisoning susceptibility features when R-3 is complete.

It should optimize human review ordering and evidence calibration under verifier hard rules. It must not emit final attack/benign labels, hide mixed evidence, or override abstention.
