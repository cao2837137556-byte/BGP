# R-FOREGROUND-3 Online Foreground Smoke

Date: 2026-07-02

Status: completed; `online_path_pressure_v1` is frozen as the current online
foreground baseline for the next controlled-attack expansion.

## 1. Purpose

R-FOREGROUND-3 follows the completed R-FOREGROUND-2 policy-improvement audit.

R-FOREGROUND-2 found:

- `baseline_v1_replay`: background suppression `0.377447197`,
  compression `1.606292`, suppressed attacks `0`;
- `count3_path2_candidate`: background suppression `0.434294803`,
  compression `1.767721`, suppressed attacks `0`;
- `path1_pressure_test`: background suppression `0.510538701`,
  compression `2.043079`, suppressed attacks `0`;
- `external_only_pressure_test`: background suppression `0.840702662`,
  compression `6.277574`, but suppressed attacks `2`, therefore unsafe.

The important result is not that R-FOREGROUND-2 can blindly promote a pressure
test. The important result is that a candidate-free policy boundary exists near
`>=50%` background suppression without suppressing the current controlled
multi-attack rows.

R-FOREGROUND-3 formalizes that boundary as `online_path_pressure_v1` and reruns
it as a single auditable online foreground smoke policy.

## 2. Scientific Question

The question is:

```text
Can the best safe R-FOREGROUND-2 pressure-test policy become a formal
candidate-free online foreground baseline while retaining every controlled
multi-attack event?
```

This is still not a production deployment claim.

## 3. Policy

Policy id:

```text
online_path_pressure_v1
```

Source:

```text
R-FOREGROUND-2 path1_pressure_test
```

Protected foreground:

- explicit clean external risk signal:
  - RPKI invalid ASN / invalid length;
  - 2024 AS-rel path diagnostic;
  - well-known community flags such as `NO_EXPORT`, `NO_ADVERTISE`, or
    `NOPEER`;
- rare prefix-origin-path:
  - `prefix_origin_path_event_count <= 1`;
- low visibility only when paired with external risk.

Operational background suppression:

- not protected;
- clean evidence is not unavailable;
- prefix-origin recurrence:
  - `prefix_origin_event_count >= 2`;
- prefix-origin-path recurrence:
  - `prefix_origin_path_event_count >= 2`.

All other rows remain `gray_retained`.

## 4. Input Boundary

R-FOREGROUND-3 reads the validated R-ATTACK-0B replay:

```text
data/runs/s2a_attack0b_multi_attack_smoke_6h_april16_v01/events/event_units.parquet
outputs/r_attack_0b/s2a_attack0b_multi_attack_smoke_6h_april16_v01/
```

It uses:

- event-native prefix / origin / AS path / time / visibility fields;
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

If the policy fails either gate, it is not promoted.

## 6. Outputs

Script:

```text
scripts/run_r_foreground3_online_foreground_smoke.py
```

Config:

```text
configs/r_foreground3_online_policy_v1.json
```

HPC wrapper:

```text
scripts/hpc/r_foreground3_online_foreground_smoke.slurm
```

Expected output directory:

```text
outputs/r_foreground_3/s2a_attack0b_multi_attack_smoke_6h_april16_v01/
```

Expected outputs:

```text
r_foreground3_summary.json
r_foreground3_population_audit.csv
r_foreground3_attack_retention_audit.csv
r_foreground3_reason_distribution.csv
r_foreground3_semantic_feature_audit.csv
r_foreground3_policy_qualification_audit.csv
r_foreground3_assignment_sample.csv
r_foreground3_assignment.parquet
r_foreground3_foreground_events.parquet
r_foreground3_suppressed_background_events.parquet
r_foreground3_gray_retained_events.parquet
r_foreground3_report.md
```

The `small_results` tarball contains only small summary/audit/report files.
Full parquet outputs remain on HPC unless explicitly pulled back.

## 7. Online vs Offline Data Boundary

R-FOREGROUND-3 is an online workload-reduction step.

Hard-negative, scenario-control, and mixed-membership rows may be suppressed
online if active attacks are retained. That does not mean those rows are
unimportant. They must remain available for a later offline training/evaluation
pool.

This keeps the two tracks separate:

```text
online foreground: reduce downstream load without suppressing attacks
offline data pool: retain hard negatives / controls / mixed / poisoning-prelude
                   examples for future learning and evaluation
```

## 8. Result

R-FOREGROUND-3 completed on the validated R-ATTACK-0B replay.

| Metric | Value |
|---|---:|
| total rows | `3431121` |
| foreground rows | `1679387` |
| suppressed rows | `1751734` |
| compression ratio | `2.043079` |
| pure reference background suppression | `0.510538701` |
| gray-zone rate | `0.041341299` |
| active attack events | `10` |
| suppressed attack count | `0` |
| attack retention | `1.0` |
| truth feature leakage count | `0` |

Per-family controlled attack retention remained `1.0` for the R-ATTACK-0B
families covered so far: exact-prefix origin hijack, forged-origin hijack,
route-leak-like valley, and path-manipulation-like known transit.

This passes the R-FOREGROUND-3 online, safety, and feasibility gates. It does
not prove robustness for subprefix, stealth / NO_EXPORT, historical attacks, or
poisoning/evasion variants.

## 9. Allowed Claims

If validation passes, allowed claims are:

- `online_path_pressure_v1` was evaluated on the validated R-ATTACK-0B replay;
- controlled multi-attack retention was measured per family;
- background suppression and compression were measured on pure reference
  background;
- candidate and legacy workflow labels were not used as policy features;
- suppressed background is an operational workload-reduction state.

## 10. Forbidden Claims

R-FOREGROUND-3 does not prove:

- suppressed rows are benign;
- foreground rows are attacks;
- production suppression is ready;
- historical-event recall;
- stealth / NO_EXPORT attack robustness;
- poisoning/evasion robustness;
- learning readiness.

RPKI invalid is not attack truth. RPKI valid is not benign. AS-rel diagnostics
are not route-leak truth. NO_EXPORT absence is not safe evidence.

## 11. Next Step

Because R-FOREGROUND-3 passed:

- freeze `online_path_pressure_v1` as the current online foreground baseline;
- move to `R-ATTACK-1` attack-family expansion before learning;
- explicitly add subprefix and stealth / NO_EXPORT scenarios with realism QA;
- keep poisoning/evasion paired variants deferred until the base attack
  families are realistic and retained.

If any R-ATTACK-1 family is suppressed by the frozen baseline, the next step is
foreground repair, not learning.
