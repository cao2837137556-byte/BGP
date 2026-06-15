# Learning Layer Positioning

Last updated: 2026-06-15

## 1. Core Judgment

The learning layer is not removed. R-RESET-1 changes its role.

Before reliable foreground/explanation targets exist, do not train an attack/benign classifier.

For the current CCF-A target line, the learning layer is a `multi-attack judgment layer`, not semantic ranking. It should make low false positive foreground judgments across multiple BGP attack families, preserve uncertainty, and produce evidence explanations.

Current R-NOISE-1 decision: do not train the learning layer yet. R-NOISE-1 completed a conservative foreground extraction smoke using `policy_A_very_conservative`: `3431103` candidate rows became `1816263` foreground-view rows and `1614840` suppressible operational-background rows, with `0` must-keep / legacy-high / legacy-needs / poisoning-evasion proxy guardrail violations. This is clean-window guardrail evidence, not attack false-negative evidence. Learning must wait for R-LEARN-0 design, R-POISON-0 benchmark design, and evidence-grounded feature stability.

## 2. Why Not Train Now

Do not train an attack/benign classifier from current outputs because:
- `P1 / P2 / P3` are not truth labels.
- `high_priority_alert / needs_review / low_priority_or_background` are not truth labels.
- `P3 / low / background` is not confirmed normal.
- RPKI valid or invalid is not direct ground truth.
- Monitor-centric historical patterns can be poisoned by crafted announcements.
- Training now would learn legacy rule bias and public-monitor bias.
- Unavailable evidence must not be converted into normal/benign labels.

## 3. New Role Of Learning Layer After R-RESET-1

Learning layer input:
- foreground event or candidate view
- evidence-grounded event features
- evidence state
- provenance
- `evidence_tags`
- monitor evidence
- RPKI / IRR / ASPA / path-legality evidence
- temporal and collector features
- poisoning susceptibility features
- communities / NO_EXPORT features when propagated
- historical background pattern features

Learning layer output:
- `suspicious_forged_origin`
- `suspicious_route_leak`
- `suspicious_path_manipulation`
- `suspicious_stealth_visibility`
- `poisoning_or_evasion_suspected`
- `background_noise`
- `uncertain_need_evidence`
- confidence / evidence explanation

The model makes operational foreground judgments. It is not semantic ranking, not a single attack/benign classifier, and not a verifier override.

## 3A. Placement In The R-RESET-1 Pipeline

R-RESET-1 fixes the new placement:

```text
raw BGP / candidate events
  -> obvious noise suppression / foreground extraction
  -> multi-attack judgment layer
  -> attack-like incident aggregation
  -> evidence explanation
  -> poisoning/evasion robustness evaluation
```

Incident aggregation after judgment is the new main path. Background is not ranked in the primary human-facing output, but background remains auditable through summary statistics and samples.

## 3B. Superseded Ranker-First Placement

Earlier R-LOCK-1 / R-DOC-1 documents placed learning as a component-aware ranker / calibrator between verifier and Top-K:

```text
Stage 2 verifier
  -> Stage 3 component-aware learning ranker / calibrator
  -> Top-K Review Queue
```

R-RESET-1 weakens that as the main paper route. Ranking may still exist inside a review budget after judgment, but it is no longer the core learning claim.

It is not allowed to:

- override verifier hard rules;
- turn `background_like_but_unconfirmed` into a negative label;
- hide `evidence_conflict` or `abstain`;
- convert unavailable evidence into benignness;
- replace foreground judgment with pure ranking;
- become a primary attack/benign detector trained from `high/needs/low` or `P1/P2/P3`.

Short form: multi-attack judgment first; ranking is optional and downstream, not the main learning definition.

## 4. When To Train

Train only after these conditions are met:
- R-NOISE-0 obvious noise separability audit is complete
- R-NOISE-1 foreground extraction smoke preserves must-keep signals
- R-NOISE-1 outputs are treated as foreground/suppression views, not truth labels
- multi-attack operational labels or weak supervision targets are defined without truth leakage
- poisoning and evasion scenarios exist
- held-out windows exist
- evidence provenance is attached
- unavailable evidence is not treated as normal
- R-CONSIST evidence-cache risks are handled or explicitly documented
- R-2D-P0 communities propagation schema is designed if stealth evidence is included

Minimum trainable unit:

```text
foreground event / evidence-grounded candidate
  -> multi-attack operational judgment
  -> optional attack-like incident aggregation
```

Not trainable as truth:

```text
legacy detector score
legacy high/needs/low label
legacy P1/P2/P3 priority
```

## 5. Possible Models

Candidate models, not current implementation targets:
- logistic regression / calibrated linear model
- gradient boosting classifier with abstention
- cost-sensitive multi-class model
- graph representation over AS/path evidence
- semi-supervised anomaly foregrounding
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
low false positive multi-attack foreground judgment with abstention
```

It should answer:
- Is this foreground event suspicious_forged_origin, suspicious_route_leak, suspicious_path_manipulation, suspicious_stealth_visibility, poisoning_or_evasion_suspected, background_noise, or uncertain_need_evidence?
- Which evidence explains the operational judgment?
- Which cases should abstain until external evidence is attached?
- Which background_noise cases are operationally suppressible but not confirmed benign?
- Which poisoning/evasion-sensitive cases must be preserved?

It should not answer:
- Is this confirmed attack or confirmed benign?
- Can this low-priority incident be used as a negative label?
- Can the model ignore missing evidence?

## 9. CCF-A Multi-Attack Judgment Target

For the CCF-A target line, learning is positioned as:

```text
multi-attack foreground judgment layer with abstention and evidence explanation
```

It should consume foreground event features and evidence-grounded diagnostics, including:

- dominant prefix-origin evidence;
- path legality / route-leak diagnostic evidence;
- stealth visibility / NO_EXPORT evidence when available;
- `evidence_conflict` and abstention signals;
- poisoning susceptibility features when R-3 is complete.

It should optimize deployable, low false alarm, multi-family foreground judgment under verifier hard rules. It must not emit final confirmed attack/benign labels, hide mixed evidence, or override abstention.
