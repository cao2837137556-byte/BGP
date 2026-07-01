# R-FOREGROUND-2 Policy Improvement Audit

Date: 2026-07-01

Status: implementation ready; full run pending.

## 1. Purpose

R-FOREGROUND-2 follows the validated R-ATTACK-0B multi-attack replay.

R-ATTACK-0B showed:

- four controlled attack families are retained by R-FOREGROUND-1;
- `suppressed_attack_count = 0`;
- `attack_retention = 1.0`;
- background suppression is still about `37.7%`, below the future `>=50%`
  target.

R-FOREGROUND-2 therefore audits stronger foreground policies. It does not
train learning, does not implement production suppression, and does not add new
attack families.

## 2. Scientific Question

The question is not:

```text
How do we suppress the most rows?
```

The question is:

```text
Can a stronger candidate-free foreground policy suppress more background while
retaining every controlled multi-attack event?
```

Any policy that suppresses even one controlled attack event fails, regardless of
compression.

## 3. Input Boundary

R-FOREGROUND-2 reads the validated R-ATTACK-0B replay:

```text
data/runs/s2a_attack0b_multi_attack_smoke_6h_april16_v01/events/event_units.parquet
outputs/r_attack_0b/s2a_attack0b_multi_attack_smoke_6h_april16_v01/
```

It uses:

- event-native prefix / origin / AS path / visibility fields;
- recurrence and rarity counts computed from event rows;
- clean RPKI sidecar aligned to `2024-04-16`;
- clean CAIDA AS-rel sidecar from `2024-04-01`;
- clean community / NO_EXPORT sidecar.

It does not use:

- `candidate_flag`;
- `candidate_reasons`;
- `matched_rule_count`;
- legacy final / high / needs / low labels;
- P1 / P2 / P3;
- old 2017-derived `rel_*` fields;
- scenario truth fields as policy features.

Truth metadata is attached only after policy assignment for safety evaluation.

## 4. Candidate Policies

R-FOREGROUND-2 compares:

| Policy | Role |
|---|---|
| `baseline_v1_replay` | Reproduce R-FOREGROUND-1 on R-ATTACK-0B |
| `count3_path2_candidate` | Protect path novelty seen <=2 times; suppress repeated non-risk paths at >=3 observations |
| `count3_path2_lowvis_cautious` | Same as above but keeps low-visibility rows out of suppression |
| `count2_path2_pressure` | More aggressive recurrence pressure test while protecting <=2-observation path novelty |
| `path1_pressure_test` | Stress test expected to expose path-manipulation miss risk |
| `external_only_pressure_test` | Upper-bound compression test expected to be unsafe for path-only attacks |

The last two are pressure tests, not default candidates.

## 5. Gates

Safety gate:

```text
suppressed_attack_count = 0
attack_retention = 1.0
truth_feature_leakage_count = 0
```

Feasibility gate:

```text
pure_reference_background_suppression_rate >= 0.50
estimated_compression_ratio >= 2.0
gray_zone_rate <= 0.35
```

If no recommendable policy passes both gates, R-FOREGROUND-2 is a stop-loss
result, not a failure to hide.

## 6. Outputs

Script:

```text
scripts/audit_r_foreground2_policy_improvement.py
```

Config:

```text
configs/r_foreground2_policy_audit_v1.json
```

HPC wrapper:

```text
scripts/hpc/r_foreground2_policy_improvement_audit.slurm
```

Expected output directory:

```text
outputs/r_foreground_2/s2a_attack0b_multi_attack_smoke_6h_april16_v01/
```

Expected small outputs:

```text
r_foreground2_summary.json
r_foreground2_policy_comparison.csv
r_foreground2_policy_population_audit.csv
r_foreground2_policy_attack_retention_audit.csv
r_foreground2_policy_reason_distribution.csv
r_foreground2_retained_pressure_audit.csv
r_foreground2_semantic_feature_audit.csv
r_foreground2_assignment_sample.csv
r_foreground2_report.md
```

No full assignment parquet is written in this phase.

## 7. Allowed Claims

If validation passes, allowed claims are:

- policy candidates were audited on the validated R-ATTACK-0B replay;
- controlled attack retention was measured per policy and per attack family;
- compression improvements were measured against the R-FOREGROUND-1 baseline;
- candidate flags and legacy labels were not used as policy features.

## 8. Forbidden Claims

R-FOREGROUND-2 does not prove:

- suppressed rows are benign;
- foreground rows are attacks;
- production suppression is ready;
- stealth / NO_EXPORT attack robustness;
- poisoning/evasion robustness;
- learning readiness.

RPKI invalid is not attack truth. RPKI valid is not benign. AS-rel diagnostics
are not route-leak truth. NO_EXPORT absence is not safe evidence.

## 9. Next Step

If a recommendable policy passes the `>=50%` target with `0` suppressed attacks,
promote it to R-FOREGROUND-3 smoke.

If only safety passes but compression remains below target, inspect the retained
pressure audit and repair foreground features before moving to learning.

If any controlled attack is suppressed, repair the foreground safety logic
before adding stealth, NO_EXPORT, poisoning, or learning.
