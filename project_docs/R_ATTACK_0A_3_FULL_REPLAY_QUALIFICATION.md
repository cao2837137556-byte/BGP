# R-ATTACK-0A-3 Full Replay Qualification

Date: 2026-06-24

Status: completed with a non-blocking global community join caveat.

## 1. Purpose

R-ATTACK-0A-3 expands the hardened origin-family controlled injection smoke
from the bounded R-ATTACK-0A-2 scope to the complete 6h replay. Its purpose is
to validate that controlled exact-prefix and forged-origin scenarios can move
through the raw -> event -> candidate path and receive aligned evidence sidecars
before R-NOISE-CLEAN-1 foreground evaluation.

This phase does not train learning, does not evaluate final low false positives,
does not prove multi-attack recall, and does not prove poisoning/evasion
robustness.

## 2. Execution Summary

The completed HPC intel run produced the following validated counts:

| Item | Value |
|---|---:|
| source raw files | 144 |
| source raw rows | 7,200,000 |
| derived raw rows | 7,200,096 |
| injected raw rows | 96 |
| injected attack rows | 32 |
| injected hard-negative rows | 32 |
| injected control rows | 32 |
| event rows | 3,431,117 |
| candidate rows | 3,431,117 |
| candidate attack retention rate | 1.0 |
| hard-negative candidate event rate | 0.357142857 |

The event and candidate counts match. The RPKI and AS-rel sidecars both align
with the full event/candidate set.

## 3. Evidence Join Results

| Evidence channel | Result | Interpretation |
|---|---:|---|
| RPKI event/candidate join | pass | Aligned to run date `2024-04-16`. |
| AS-rel event join | pass | Uses 2024-near CAIDA snapshot `2024-04-01`. |
| community sidecar rows = event rows | pass | Sidecar has one row per event. |
| attack community join | 1.0 | Injected attack events have community evidence joined. |
| global community raw-match rate | 0.9999997085 | One background event lacks a raw community match. |

The global validation JSON reports:

```text
validated = false
pass_count = 16 / 17
failed_checks = [community_event_join_1]
```

The failing check is caused by:

```text
events_with_raw_match = 3,431,116 / 3,431,117
raw_join_unavailable = 1
partial_record_count_match = 10,273
exact_record_count_match_rate = 0.9970056399
```

This is the same class of community sidecar caveat already known from the clean
baseline: community presence can be used where joined, but community absence or
missingness must not be treated as safe evidence.

## 4. Qualification Decision

R-ATTACK-0A-3 is qualified for R-NOISE-CLEAN-1 because the failed global
community check does not affect the controlled attack path:

- raw materialization is complete;
- event construction completed over the full replay;
- candidate rows equal event rows;
- candidate attack retention is `1.0`;
- RPKI attack evidence join is `1.0`;
- AS-rel attack evidence join is `1.0`;
- community attack evidence join is `1.0`;
- QA pass is true;
- no learning was trained.

The phase is not a fully clean community-absence benchmark. It is a qualified
origin-family full-window replay with one non-attack global community join
caveat.

## 5. Allowed Claims

Allowed:

- The full 6h controlled origin-family replay completed.
- Event and candidate artifacts were rebuilt for the derived run.
- The controlled attack path retained all injected attack events through
  candidate generation.
- RPKI, 2024-near AS-rel, and community evidence were recomputed for the
  derived run.
- Injected attack events have complete RPKI / AS-rel / community evidence joins.
- One background community raw-match caveat remains and must be reported.

Forbidden:

- Do not claim final low false positives.
- Do not claim hard negatives are confirmed benign.
- Do not claim poisoning/evasion robustness.
- Do not claim multi-attack recall.
- Do not claim learning performance.
- Do not claim NO_EXPORT absence is safe.
- Do not claim missing community evidence is benign.

## 6. Next Step

Proceed to R-NOISE-CLEAN-1 foreground safety evaluation using the qualified
full replay. R-NOISE-CLEAN-1 must still enforce:

- `suppressed_attack_count = 0`;
- candidate-to-downstream attack retention `= 1.0`;
- truth metadata is evaluation-only and must not enter policy features;
- background denominators exclude injected scenario and mixed-membership rows;
- community absence or unavailable state cannot be used as a benign/safe guard.

No full replay rerun is required for the one-row global community caveat.
