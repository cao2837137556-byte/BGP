# R-NOISE-0 Obvious Noise Separability Audit

Last updated: 2026-06-01

Status: completed audit.

## 1. Goal

R-NOISE-0 tests whether obvious operational background noise can be separated from multi-attack weak signals before implementing any foreground extraction.

This is not a detector, not a truth-labeling step, and not a suppression implementation. The purpose is a safety gate:

```text
Can we suppress obvious background-like rows
without suppressing multi-attack must-keep signals?
```

The answer from this audit is: yes, a conservative first smoke is feasible, but only with strict must-keep guards.

## 2. Why This Audit Is Needed

R-AGG-2, R-AGG-3, and R-EVID-0 already showed that candidate-first incident aggregation is not a safe mainline:

- R-AGG-2 produced `3128971` raw incidents with compression ratio `1.09656`.
- R-AGG-3 found `possible_background_like_rate=0.995288`, but high-value weak signals overlapped heavily with background-like candidates.
- R-EVID-0 found `protected_suspicious_rate=0.929482`, `suppressible_background_like_rate=0.0`, and `protected_background_overlap_rate=0.92477`, triggering stop-loss.

Therefore R-NOISE-0 does not ask "how many rows look like background?" It asks whether background and multi-attack weak signals are separable enough to justify a conservative foreground extraction smoke.

## 3. Inputs

Run:

- `s2a_baseline_v01_pilot_6h_april16`

Primary input:

- `data/runs/s2a_baseline_v01_pilot_6h_april16/candidates/candidate_events.parquet`

Context inputs:

- `event_units.parquet` for time and AS-rel diagnostic fields.
- local VRP/RPKI cache for RPKI status.
- `final_alerts.parquet` only as a legacy workflow reference.

Forbidden uses:

- final/high/needs/low are not truth.
- RPKI invalid is not attack truth.
- AS-rel diagnostic is not route leak truth.
- background-like/background_noise is not benign.
- missing external evidence is not background evidence.

## 4. Audit Design

R-NOISE-0 adds five safety checks:

1. `multi_attack_must_keep_coverage`
   - Keeps forged-origin, route-leak, path-manipulation, stealth-visibility, and poisoning/evasion-like signals separate.
2. `counterfactual_suppression_policy_audit`
   - Simulates policy_A / policy_B / policy_C without deleting any row.
3. `clean_window_noise_profile`
   - Explains why a nominally clean 6h window still generates many candidate-entry rows.
4. `legacy_signal_reference_audit`
   - Checks whether simulated rules would suppress old workflow high/needs rows, while explicitly treating them as workflow references only.
5. `poisoning_evasion_retention_audit`
   - Enforces the red line that any poisoning/evasion-like signal must not be suppressed in R-NOISE-0.

## 5. Counterfactual Policies

Policy A: very conservative.

- Suppress only non-foreground low-information rows.
- Requires no multi-attack must-keep signal.
- Requires path already seen before.
- Requires no origin multiplicity.
- Recommended as the only R-NOISE-1 smoke candidate.

Policy B: balanced.

- Adds low AS-rel uncertainty to low-information filtering.
- Useful comparison, not the first implementation target.

Policy C: aggressive.

- Suppresses all low-information rows with no must-keep signal.
- Upper-bound stress test only.

## 6. Core Results

| Metric | Value |
|---|---:|
| candidate_entry_rows | `3431103` |
| candidate_flag_true | `1804382` (`0.525890`) |
| must_keep_count | `1812334` (`0.528207`) |
| policy_A_suppressible_count | `1614840` (`0.470647`) |
| policy_A_estimated_compression_ratio | `1.889100` |
| policy_A_must_keep_suppressed | `0` |
| policy_A_legacy_high_suppressed | `0` |
| policy_A_legacy_needs_suppressed | `0` |
| policy_A_poisoning_evasion_like_suppressed | `0` |
| gray_zone_count under policy_A | `3929` (`0.001145`) |

Policy comparison:

| Policy | would_suppress | suppress_rate | keep_count | must_keep_suppressed | estimated_compression |
|---|---:|---:|---:|---:|---:|
| policy_A_very_conservative | `1614840` | `0.470647` | `1816263` | `0` | `1.889100` |
| policy_B_balanced | `1368796` | `0.398938` | `2062307` | `0` | `1.663721` |
| policy_C_aggressive | `1618716` | `0.471777` | `1812387` | `0` | `1.893140` |

Even though policy_C gives a slightly higher simulated compression, R-NOISE-1 should start from policy_A because the project needs a conservative, reviewer-defensible smoke before any foreground extraction implementation.

## 7. Multi-Attack Must-Keep Coverage

| Family | Count | Rate | Interpretation |
|---|---:|---:|---|
| suspicious_forged_origin | `203892` | `0.059425` | origin novelty or RPKI invalid plus weak signal; not confirmed hijack |
| suspicious_route_leak | `460873` | `0.134322` | AS-rel/path diagnostic proxy; not route leak truth |
| suspicious_path_manipulation | `1796971` | `0.523730` | path novelty/path-length anomaly; not confirmed manipulation |
| suspicious_stealth_visibility | `1781609` | `0.519253` | low visibility plus other weak signal; not confirmed stealth |
| poisoning_or_evasion_suspected | `1542485` | `0.449560` | crafted-looking proxy; not confirmed poisoning |

No must-keep family is suppressed by policy_A, policy_B, or policy_C in this audit.

## 8. Clean Window Noise Profile

The clean 6h baseline still produces many candidate-entry rows because the window is dominated by low-visibility and repeated structural patterns:

- `single_collector_short_rows=2937760` (`0.856214`)
- `weak_or_missing_reason_rows=1627160` (`0.474238`)
- `repeated_prefix_origin_rows=3303446` (`0.962794`)
- `repeated_path_signature_rows=3254673` (`0.948579`)
- top low-information reason: `["single_collector_visibility"]`, `972370` rows
- second low-information reason: `["single_collector_visibility", "unusually_short_duration_for_prefix"]`, `638738` rows

This explains the event explosion without turning these rows into benign truth. They are operational background candidates only.

## 9. Legacy Reference Audit

Legacy final labels are workflow references, not truth labels.

R-NOISE-0 checks them only to catch obvious conflict with old strong workflow signals:

- high_priority_alert rows: `123849`, policy_A suppresses `0`.
- needs_review rows: `605585`, policy_A suppresses `0`.
- low_priority_or_background rows: `1074948`, policy_A suppresses `0`.
- missing final-reference rows: `1626721`, policy_A suppresses `1614840`.

This supports the interpretation that policy_A mainly suppresses rows that never entered the old downstream candidate/scoring path, while still not treating that path as truth.

## 10. Poisoning / Evasion Retention

Explicit poisoning/evasion tokens are not present in current candidate reasons.

The audit therefore uses a conservative proxy:

- low visibility;
- path novelty;
- short duration;
- historical multi-collector support.

Proxy count:

- `poisoning_or_evasion_suspected=1542485` (`0.449560`)

Suppressed by all simulated policies:

- `0`

This does not claim confirmed poisoning. It only preserves poisoning/evasion-sensitive rows for later robustness evaluation.

## 11. Decision

R-NOISE-0 decision:

```text
eligible_for_R_NOISE_1_conservative_smoke
```

Recommended next step:

```text
R-NOISE-1 foreground extraction smoke using policy_A_very_conservative with must-keep guards
```

Policy_A is allowed only as an audit-backed smoke. It is not a final suppression policy and must not be used to delete source data.

## 12. Current Limits

- The poisoning/evasion signal is a proxy, not a confirmed poisoning label.
- Communities / NO_EXPORT are still unavailable at candidate-entry.
- AS-rel diagnostics are inherited event-layer diagnostics, not aligned verifier truth.
- RPKI status is useful for retention/protection, not attack truth.
- policy_A relies partly on `candidate_flag=false`, so R-NOISE-1 must frame this as conservative foreground extraction, not as proof that those rows are benign.
- This audit is on the baseline 6h run. Expanded multi-collector settings still need their own smoke before final claims.

## 13. CCF-A Relevance

R-NOISE-0 strengthens the paper line because it turns the background-explosion problem into a measurable separability gate:

- compression is reported;
- must-keep miss risk is reported;
- poisoning/evasion retention is reported;
- legacy workflow labels are checked only as references;
- no truth claim is created.

This is the right direction for a deployable low-false-positive multi-attack judgment system under incomplete and poisonable public monitors.
