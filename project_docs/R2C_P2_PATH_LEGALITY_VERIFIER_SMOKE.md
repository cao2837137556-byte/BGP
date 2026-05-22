# R-2C-P2 Path-legality Verifier Smoke

Status: fixed S2 full smoke completed.

Run id: `s2a_expanded_v01_pilot_6h_april16`

Run date: `2024-04-16`

AS relationship snapshot: `2024-04-01`

Output directory: `outputs/r2c_p2_path_legality_verifier_smoke_v01/`

## 1. Goal

R-2C-P2 converts R-2C-P1 path diagnostics into an R-1 verdict-compatible path-legality verifier smoke.

This stage is deliberately conservative. It does not generate confirmed route-leak labels, does not modify R-2B verifier verdicts, does not train the learning layer, and does not add new external evidence. It only creates a safer incident-level review table for route-leak-like and path-manipulation-like candidates.

## 2. Why Move From P1 Diagnostic to P2 Verifier Smoke

R-2C-P1 showed that the `2024-04-01` CAIDA AS relationship cache can be joined back to AS-pair, triplet, full-path, and incident-level path evidence. It produced route-leak-like and path-manipulation-like diagnostic candidates, but those diagnostics were not verdicts.

R-2C-P2 is the next small step: make the diagnostic layer compatible with the R-1 verifier state machine and separate cases into:

- `evidence_supported_suspicious`
- `evidence_conflict`
- `evidence_insufficient`
- `external_evidence_unavailable`
- `background_like_but_unconfirmed`
- `abstain`

`strongly_supported_suspicious` is intentionally not emitted in this stage.

## 3. Why This Is Still Not Confirmed Route Leak

The only path evidence in this branch is CAIDA AS relationship evidence. CAIDA AS-rel is inferred evidence and cannot by itself prove route-leak truth.

Therefore:

- AS-rel matched is not path benign.
- AS-rel unmatched is not path suspicious.
- Possible valley-free diagnostics are not confirmed route leaks.
- AS-rel-only evidence cannot trigger `evidence_supported_suspicious`.
- `background_like_but_unconfirmed` is not a negative label.
- `safe_negative_candidate_flag` is always `false`.

Formal stronger path-legality claims require follow-on evidence such as ASPA, BGP Roles / OTC, operator confirmation, data-plane evidence, or a dedicated poisoning/evasion benchmark.

## 4. Naming Tightening

R-2C-P1 used two names that were too easy to over-read:

| R-2C-P1 legacy name | R-2C-P2 main name |
| --- | --- |
| `origin_valid_path_suspicious` | `origin_valid_with_path_diagnostic` |
| `origin_unknown_path_suspicious` | `origin_unknown_with_path_diagnostic` |
| `review_density` | `path_review_signal_density` |

The old names are retained only in `legacy_combined_origin_path_evidence_class` for traceability. P2 main outputs use diagnostic naming. Diagnostic does not mean suspicious, and `path_review_signal_density` is not attack density.

## 5. Verifier Smoke Rules

R-2C-P2 uses the R-1 verdict set. The main table field is `path_legality_verdict_smoke`.

### evidence_conflict

Used when origin/path evidence conflict is visible, path evidence state is conflict-like, component purity is `mixed_conflicting`, or path diagnostic signal is high while origin/component/visibility evidence is inconsistent. Conflict remains visible and is never hidden by a score.

### evidence_supported_suspicious

This is very restrictive in R-2C-P2. A case must have:

- R-2B `evidence_supported_suspicious`;
- `path_evidence_state = aligned_medium`;
- a route-leak-like or path-manipulation-like diagnostic flag;
- low path unknown-pair rate;
- no severe component mixing;
- no conflict.

This rule prevents AS-rel-only support from becoming a suspicious verdict.

### evidence_insufficient

Used when path diagnostics exist but origin/component/monitor support is not enough, unknown-pair rate is too high, or the incident is not safe to promote.

### external_evidence_unavailable

Used when path evidence is missing or critical path fields cannot be used.

### background_like_but_unconfirmed

Used for R-2B background-like cases when path diagnostics do not support review. This is not a normal or benign label.

### abstain

Used for highly mixed, high-unknown, or otherwise unsafe cases where the state machine should avoid overclaiming.

### strongly_supported_suspicious

Not emitted in this stage. If it appears, it is a safety warning.

## 6. Fixed S2 Full Results

Processed incidents: `217165`

Path-legality verdict smoke distribution:

| verdict | incidents |
| --- | ---: |
| `background_like_but_unconfirmed` | 127889 |
| `evidence_insufficient` | 78324 |
| `abstain` | 10822 |
| `evidence_conflict` | 86 |
| `evidence_supported_suspicious` | 44 |

Review buckets:

| review bucket | incidents |
| --- | ---: |
| `background_sampling` | 127889 |
| `path_manipulation_like_review` | 39539 |
| `route_leak_like_review` | 33355 |
| `abstain_split_or_unknown` | 10822 |
| `path_insufficient_review` | 5430 |
| `conflict_review` | 86 |
| `evidence_supported_path_review` | 44 |

Review candidates:

- route-leak-like review candidates: `34555`
- path-manipulation-like review candidates: `44189`
- `evidence_supported_suspicious`: `44`
- `strongly_supported_suspicious`: `0`
- hard safety violations: `0`

## 7. Top-K Path-legality Review Smoke

The Top-K queue is deterministic and model-free.

| Top-K | path review signal density | evidence-supported density | evidence-supported | route-leak-like review | path-manipulation-like review | conflict | insufficient |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 50 | 1.000 | 0.880 | 44 | 6 | 50 | 5 | 1 |
| 100 | 1.000 | 0.440 | 44 | 56 | 100 | 5 | 51 |
| 500 | 1.000 | 0.088 | 44 | 456 | 493 | 12 | 444 |

These values are review-queue smoke metrics. They are not precision, recall, or attack density.

## 8. Hard Safety Audit

All hard safety checks passed:

- no confirmed route-leak label emitted;
- `strongly_supported_suspicious` count is `0`;
- no AS-rel-only `evidence_supported_suspicious`;
- `safe_negative_candidate_flag` is always `false`;
- P2 main outputs use diagnostic naming rather than P1 suspicious names.

R-2B verifier verdict modified: `false`

New external evidence downloaded: `false`

NO_EXPORT / communities executed: `false`

AS Hegemony executed: `false`

Learning layer trained: `false`

## 9. Relationship to CCF-A Target Line

R-2C-P2 strengthens the multi-attack-family verifier branch without collapsing diagnostics into truth labels. It moves beyond origin-only VRP evidence while preserving the core CCF-A guardrail: evidence must remain component-aware, provenance-visible, and abstention-capable.

The value of this step is not that it proves route leaks. The value is that it creates a safe route-leak/path-legality review layer that can later absorb ASPA, BGP Roles / OTC, communities, operator reports, data-plane evidence, and poisoning/evasion tests.

## 10. Current Limits

R-2C-P2 does not include:

- ASPA;
- BGP Roles / OTC;
- NO_EXPORT / communities;
- AS Hegemony;
- data-plane evidence;
- operator confirmation;
- poisoning/evasion benchmark;
- learning layer training.

The current path legality signal is CAIDA AS-rel based and therefore remains inferred/diagnostic evidence.

## 11. Next Step

Recommended order:

1. R-2D-0 communities / NO_EXPORT field availability audit.
2. L1 component-aware semantic learner design.
3. R-3 poisoning benchmark early design.

Formal learning training remains blocked until verifier-supported targets and robustness scenarios exist.
