# R-NOISE-1 Conservative Foreground Extraction Smoke

Last updated: 2026-06-15

Status: completed smoke.

## 1. Goal

R-NOISE-1 turns the R-NOISE-0 `policy_A_very_conservative` counterfactual into auditable foreground extraction views.

This phase is deliberately narrow:

- generate a foreground view for downstream multi-attack judgment design;
- generate a suppressible operational background view;
- keep a gray retained view;
- report safety guardrail violations.

It does not delete source rows, does not train learning, does not implement final background suppression, does not perform incident aggregation, and does not create attack/benign truth labels.

## 2. Scientific Boundary

The 6h baseline window is treated as a clean-window / unlabeled operational background window. Therefore R-NOISE-1 cannot evaluate real attack false negatives.

Correct wording:

```text
guardrail_violation_count = 0
```

Forbidden wording:

```text
false_negative_count = 0
no attack was missed
poisoning/evasion recall is validated
suppressed rows are benign
foreground rows are attacks
```

This matters because there are no confirmed poisoning/evasion labels in this 6h window. R-NOISE-1 can only check whether available poisoning/evasion-relevant proxies are retained, or mark them unavailable.

## 3. Inputs

Run:

- `s2a_baseline_v01_pilot_6h_april16`

Primary input:

- `data/runs/s2a_baseline_v01_pilot_6h_april16/candidates/candidate_events.parquet`

Context inputs:

- `event_units.parquet` for time and AS-rel diagnostic context;
- `final_alerts.parquet` as legacy workflow reference only;
- local VRP/RPKI cache for RPKI status context;
- R-NOISE-0 summary for policy_A reference counts.

## 4. Policy and Hard Guards

R-NOISE-1 uses only:

```text
policy_A_very_conservative
```

Policy_A is allowed only as a smoke policy. It is not a production suppression policy.

Hard guards:

- multi-attack must-keep signal;
- legacy `high_priority_alert` workflow reference;
- legacy `needs_review` workflow reference;
- poisoning/evasion-relevant proxy.

If a row matches policy_A but also matches a hard guard, it must be retained.

## 5. Assignment States

| State | Meaning | Forbidden claim |
|---|---|---|
| `foreground_protected` | retained for downstream multi-attack judgment because a must-keep or hard-guard signal is present | confirmed attack |
| `suppressible_background` | operationally suppressible background-like row under conservative policy_A and hard guards | confirmed benign |
| `gray_retained` | not protected by current must-keep signals but not safe to suppress under policy_A | benign or attack truth |

## 6. Outputs

Output directory:

- `outputs/r_noise_1/s2a_baseline_v01_pilot_6h_april16/`

Generated files:

- `candidate_noise_policy_assignment.parquet`
- `foreground_candidates.parquet`
- `suppressed_background_candidates.parquet`
- `gray_zone_retained_candidates.parquet`
- `r_noise_1_summary.json`
- `r_noise_1_safety_audit.csv`
- `r_noise_1_family_guardrail_audit.csv`
- `r_noise_1_legacy_reference_audit.csv`
- `r_noise_1_poisoning_evasion_proxy_audit.csv`
- `r_noise_1_assignment_sample.csv`
- `r_noise_1_policy_report.md`

Outputs are experiment artifacts and should not be committed as large files.

## 7. Core Results

| Metric | Value |
|---|---:|
| candidate_entry_rows | `3431103` |
| foreground_protected | `1812334` (`0.528207`) |
| suppressible_background | `1614840` (`0.470647`) |
| gray_retained | `3929` (`0.001145`) |
| foreground_view_total | `1816263` (`0.529353`) |
| estimated compression if suppressible is removed from foreground view | `1.889100` |

The R-NOISE-1 counts exactly match the R-NOISE-0 policy_A reference count for suppressible rows:

```text
policy_A_suppressible_count = 1614840
```

## 8. Safety Audit

| Check | Count | Interpretation |
|---|---:|---|
| attack_false_negative_evaluation | `0` | not evaluated in clean-window smoke; no confirmed attack labels are available |
| must_keep_guardrail_violation | `0` | no suppressible row contains a multi-attack must-keep signal |
| legacy_high_reference_suppressed | `0` | no legacy high workflow-reference row is suppressible |
| legacy_needs_reference_suppressed | `0` | no legacy needs workflow-reference row is suppressible |
| poisoning_evasion_proxy_suppressed | `0` | no available poisoning/evasion proxy row is suppressible |
| final_suppressible_background_count | `1614840` | operational background candidate view only, not benign truth |

The key result is:

```text
guardrail_failed = false
```

This is a safety-gate result, not an attack recall result.

## 9. Multi-Attack Guardrail Coverage

| Operational family | Hit count | Suppressed |
|---|---:|---:|
| `suspicious_forged_origin` | `203892` | `0` |
| `suspicious_route_leak` | `460873` | `0` |
| `suspicious_path_manipulation` | `1796971` | `0` |
| `suspicious_stealth_visibility` | `1781609` | `0` |
| `poisoning_or_evasion_suspected` | `1542485` | `0` |

These are weak-signal operational families, not confirmed attack labels.

## 10. Poisoning / Evasion Proxy Interpretation

Explicit poisoning/evasion token:

```text
explicit_token_count = 0
explicit_token_availability = unavailable
```

Available proxy:

```text
proxy_count = 1542485
proxy_suppressed_count = 0
```

Allowed claim:

```text
available poisoning/evasion-relevant proxies are retained under policy_A.
```

Forbidden claim:

```text
R-NOISE-1 proves poisoning/evasion recall.
```

True poisoning/evasion recall must be evaluated later with known incidents and controlled injection benchmarks.

## 11. Current Limits

- R-NOISE-1 is a clean-window smoke, not a detection benchmark.
- The suppressible view is not a benign label source.
- The foreground view is not an attack label source.
- Communities / NO_EXPORT are still unavailable at candidate-entry / Raw Incident level.
- RPKI and AS-rel are context signals, not truth labels.
- The current result is on baseline 6h; expanded multi-collector foreground extraction needs a separate smoke before broad claims.

## 12. Next Step

R-NOISE-1 supports moving to design work:

- R-LEARN-0 multi-attack judgment layer design;
- R-POISON-0 controlled poisoning/evasion benchmark design.

However, no production suppression claim and no learning training should be made until benchmark-backed recall / miss-risk evaluation exists.

The next technical design must explicitly separate:

```text
clean-window guardrail safety
known-incident replay
controlled multi-attack injection benchmark
poisoning/evasion robustness evaluation
```

## 13. CCF-A Relevance

R-NOISE-1 makes the foreground stage reviewer-defensible:

- it reports compression and guardrail safety together;
- it avoids attack/benign truth claims on clean data;
- it preserves multi-attack weak signals;
- it explicitly admits the missing poisoning/evasion recall evaluation;
- it creates a reproducible foreground view for later judgment-layer and benchmark work.

This keeps the paper line focused on low-false-positive multi-attack judgment under incomplete and poisonable public monitors.
