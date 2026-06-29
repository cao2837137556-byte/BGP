# R-FOREGROUND-1 Online Foreground Smoke

Date: 2026-06-29

Status: implementation ready; full run pending.

## 1. Purpose

R-FOREGROUND-1 promotes the best passing R-FOREGROUND-0 policy,
`aggressive_recurrence`, into a single candidate-free online foreground smoke
policy.

The goal is not to train a model and not to prove final multi-attack coverage.
The goal is narrower:

```text
Can the online foreground layer suppress a useful amount of background while
keeping every controlled origin-family attack event?
```

## 2. Policy Boundary

The online policy is:

```text
online_aggressive_recurrence_v1
```

It uses:

- event-native prefix / origin / AS path / visibility fields;
- recurrence and rarity features computed from the event window;
- clean RPKI sidecar;
- clean 2024-near AS-rel sidecar;
- clean community sidecar.

It does not use:

- `candidate_flag`;
- `candidate_reasons`;
- `matched_rule_count`;
- legacy final / high / needs / low labels;
- P1 / P2 / P3;
- old 2017-derived `rel_*` fields;
- scenario truth fields.

Truth metadata is attached only after policy assignment for evaluation.

## 3. Online Policy Logic

Protected foreground:

```text
external_risk_signal
OR rare_prefix_origin_path
OR low_visibility AND external_risk_signal
```

Operational background suppression:

```text
NOT protected_foreground
AND NOT evidence_unavailable_for_suppression
AND common_nonrare_route
```

Everything else is retained as gray foreground.

Suppressed background is operational pressure reduction, not confirmed benign.
Foreground is not confirmed attack.

## 4. Current Smoke Gates

For the current origin-family controlled smoke, R-FOREGROUND-1 must satisfy:

```text
suppressed_attack_count = 0
attack_retention = 1.0
pure_reference_background_suppression_rate >= 0.30
estimated_compression_ratio >= 1.5
truth_feature_leakage_count = 0
```

These gates reflect the current limited benchmark. They are not the final paper
target.

## 5. Future Multi-Attack Compression Target

After route-leak, path-manipulation, stealth visibility, and
poisoning/evasion scenarios are added, the foreground layer should target:

```text
background suppression >= 50%
```

The stretch target is:

```text
60%-70% background suppression
```

This is not merely a nice-to-have. It is the operational target that should
drive later foreground repair. If multi-attack recall remains safe but
background suppression stays below 50%, the foreground layer is still not
strong enough for the paper's deployable low-false-positive story.

## 6. Online vs Offline Training Data Boundary

R-FOREGROUND and the future training data line are separate.

Online foreground:

- reduces downstream workload;
- may suppress hard-negative/control rows if no active attack is suppressed;
- must remain auditable and low-risk.

Offline training/evaluation pool:

- should retain hard negatives, controls, mixed rows, and future
  poisoning-prelude-like samples;
- is built later under a separate training-data protocol;
- must not treat online suppressed background as a negative truth label.

This separation prevents the foreground layer from becoming too timid while
still preserving hard examples for learning.

## 7. Outputs

Script:

```text
scripts/run_r_foreground1_online_foreground_smoke.py
```

Config:

```text
configs/r_foreground1_online_policy_v1.json
```

HPC wrapper:

```text
scripts/hpc/r_foreground1_online_foreground_smoke.slurm
```

Output directory:

```text
outputs/r_foreground_1/<run_id>/
```

Expected files:

```text
r_foreground1_summary.json
r_foreground1_assignment.parquet
r_foreground1_foreground_events.parquet
r_foreground1_suppressed_background_events.parquet
r_foreground1_gray_retained_events.parquet
r_foreground1_population_audit.csv
r_foreground1_attack_retention_audit.csv
r_foreground1_reason_distribution.csv
r_foreground1_semantic_feature_audit.csv
r_foreground1_assignment_sample.csv
r_foreground1_report.md
```

The full parquet outputs are experiment artifacts and must not be committed.

## 8. Forbidden Claims

R-FOREGROUND-1 does not prove:

- background rows are benign;
- foreground rows are attacks;
- multi-attack recall;
- route-leak detection;
- NO_EXPORT attack detection;
- poisoning/evasion robustness;
- learning readiness.

## 9. Next Step

If R-FOREGROUND-1 passes the current origin-family smoke gates, the next step is:

```text
R-ATTACK-0B: multi-attack controlled scenario expansion
```

The foreground policy must then be retested against the expanded benchmark and
the >=50% background suppression target.
