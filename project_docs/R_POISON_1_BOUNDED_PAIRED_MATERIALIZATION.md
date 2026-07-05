# R-POISON-1 Bounded Paired Poisoning / Evasion Materialization

Status: bounded materialization, no full replay.

## Goal

R-POISON-1 converts the R-POISON-0 protocol into a small auditable benchmark
asset for the feasible paired poisoning/evasion variants.

This phase does not run a full raw-to-event-to-foreground replay. It creates
pair registries, evaluation-only truth prototypes, comparability audits, and
evidence / foreground contracts so that R-POISON-2 can replay the exact same
pairs without ambiguity.

## Inputs

- `configs/r_poison0_paired_benchmark_protocol_v01.json`
- `configs/r_attack0b_multi_attack_smoke_v01.json`
- `configs/r_attack1_family_expansion_v01.json`
- R-ATTACK-0B validation summary
- R-ATTACK-1 validation summary
- R-FOREGROUND-3 foreground summaries when locally available

## Feasible Pair Scope

R-POISON-1 materializes only the five feasible R-POISON-0 pairs:

| Pair | Threat Model | Variant | Clean Base |
|---|---|---|---|
| `pair_exact_origin_history_poisoning_v01` | detection-data poisoning | `data_poisoned` | `r_attack0b_exact_origin_001` |
| `pair_forged_origin_history_poisoning_v01` | detection-data poisoning | `data_poisoned` | `r_attack0b_forged_origin_001` |
| `pair_path_manipulation_history_poisoning_v01` | detection-data poisoning | `data_poisoned` | `r_attack0b_path_manip_001` |
| `pair_subprefix_noexport_evasion_v01` | visibility evasion | `noexport_evasive` | `r_attack1_subprefix_origin_001` |
| `pair_stealth_collector_asymmetry_v01` | visibility evasion | `visibility_evasive` | `r_attack1_stealth_noexport_001` |

`pair_route_leak_policy_poisoning_v01` remains blocked because route-leak
truth requires a stricter policy-semantics contract. AS-rel diagnostics alone
are not route-leak truth.

## What Was Materialized

The script writes:

- `r_poison1_pair_registry.json`
- `r_poison1_pair_registry.csv`
- `r_poison1_truth_prototype.csv`
- `r_poison1_truth_prototype.parquet` when a parquet engine is available
- `r_poison1_pair_comparability_audit.csv`
- `r_poison1_evidence_foreground_contract.csv`
- `r_poison1_summary.json`
- `r_poison1_report.md`

The truth prototype is evaluation-only. It contains clean and adversarial
variant rows with phase metadata:

- `stable_baseline`
- `poisoning_preparation` for detection-data poisoning variants
- `attack_launch`
- `recovery`

## Fair Pair Contract

The clean and adversarial sides must hold constant:

- victim prefix group;
- legitimate origin group;
- attacker AS group;
- background window;
- collector set or explicit visibility contract;
- evidence snapshot binding;
- foreground policy.

Only explicit R-POISON-0 changed variables may differ:

- poisoning preparation;
- pre-attack origin/path/link/role history;
- NO_EXPORT / visibility constraint;
- expected collector visibility;
- adversarial variant type.

## Evidence / Foreground Contract

R-POISON-1 checks that the clean base scenarios come from validated
R-ATTACK-0B / R-ATTACK-1 runs with foreground retention already established.

For adversarial variants:

- evidence joins are marked `must_recompute_in_replay`;
- foreground retention is marked `pending_replay_validation`;
- no poisoning robustness claim is allowed.

This is deliberate. Without replay, adversarial retention cannot be measured
honestly.

## Observability Boundary

Visibility-evasion pairs must carry an observability denominator:

- public-visible variants are recall-denominator eligible;
- partial-public variants are eligible only for expected visible collectors;
- fully public-invisible variants are observability-boundary cases, not
  foreground misses.

## Forbidden Claims

R-POISON-1 does not support these claims:

- poisoning robustness is proven;
- adversarial foreground retention is proven;
- NO_EXPORT present is attack truth;
- NO_EXPORT absent is safe;
- RPKI invalid is attack truth;
- AS-rel diagnostic is route-leak truth;
- public-invisible events are foreground misses;
- learning is ready.

## Command

```bash
python -m py_compile scripts/materialize_r_poison1_bounded_pairs.py
python scripts/materialize_r_poison1_bounded_pairs.py \
  --output-dir outputs/r_poison_1/s2a_baseline_v01_pilot_6h_april16 \
  --overwrite
```

## Result Interpretation

If `clean_base_validation_pass=true` and `fair_pair_contract_pass=true`, then
R-POISON-2 may run bounded replay for the materialized feasible pairs.

If either fails, repair the benchmark contract before replay.

## Next Step

```text
R-POISON-2:
Bounded replay for the five materialized feasible pairs, with evidence
recomputation and `online_path_pressure_v1` foreground retention evaluation.
```

R-POISON-2 is the first phase that may report adversarial retention drop.
