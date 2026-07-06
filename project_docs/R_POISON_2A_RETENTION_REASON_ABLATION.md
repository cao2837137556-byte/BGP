# R-POISON-2A Retention Reason and Signal Ablation Audit

Status: completed read-only audit.

## Goal

R-POISON-2 showed a mixed result:

- four adversarial poisoning/evasion pairs were retained by
  `online_path_pressure_v1`;
- one pair, `pair_path_manipulation_history_poisoning_v01`, was suppressed.

The scientific question after R-POISON-2 is not only "which pairs were
retained". The more important question is:

```text
why were they retained, and would they still be retained if a strong signal
were absent?
```

R-POISON-2A therefore audits retention reasons and counterfactual signal
dependence before any foreground repair.

## Boundary

This phase:

- reads the R-POISON-2 bounded replay outputs;
- decomposes foreground retention reasons into RPKI, AS-rel, community /
  NO_EXPORT, low-visibility, and path-novelty signals;
- runs counterfactual signal ablations;
- identifies single-signal fragility, combined-stress fragility, and current
  foreground failures;
- proposes the repair design boundary for R-FOREGROUND-4.

This phase does not:

- change `online_path_pressure_v1`;
- run a full 6h replay;
- train learning;
- expand the benchmark pairs;
- treat RPKI, AS-rel, or NO_EXPORT as attack truth;
- treat suppressed operational background as benign.

## Inputs

- `outputs/r_poison_2/s2a_baseline_v01_pilot_6h_april16/r_poison2_bounded_replay_events.csv`
- `outputs/r_poison_2/s2a_baseline_v01_pilot_6h_april16/r_poison2_pair_metrics.csv`
- `configs/r_foreground3_online_policy_v1.json`

## Method

R-POISON-2A evaluates each bounded clean/adversarial pair under the frozen
foreground logic and then reruns the assignment under counterfactual masks:

- `mask_rpki_risk`
- `mask_asrel_diagnostic`
- `mask_community_visibility`
- `mask_path_novelty`
- `mask_low_visibility`
- `mask_all_external_evidence`
- `mask_external_and_path_novelty`

These masks are not new experiments and not truth labels. They are diagnostic
tests for whether a retained pair is robust to losing a specific signal.

## Results

Summary:

- pair count: `5`;
- bounded event rows: `10`;
- ablation event rows: `80`;
- adversarial pairs currently retained: `4`;
- adversarial pairs currently suppressed: `1`;
- current failure pair:
  - `pair_path_manipulation_history_poisoning_v01`;
- single-signal fragile retained pair:
  - `pair_forged_origin_history_poisoning_v01`;
- combined-stress fragile retained pairs:
  - `pair_exact_origin_history_poisoning_v01`;
  - `pair_subprefix_noexport_evasion_v01`;
  - `pair_stealth_collector_asymmetry_v01`.

## Retention Reason Interpretation

### Exact-Origin History Poisoning

The adversarial exact-origin pair is retained by:

- RPKI risk;
- AS-rel diagnostic.

It survives single-signal ablations, but fails when all external evidence is
masked. This means it is retained by an evidence bundle, not by a demonstrated
poisoning-aware history guard.

Allowed claim:

```text
current foreground retains this bounded adversarial exact-origin pair because
external evidence remains visible.
```

Forbidden claim:

```text
foreground is robust to origin-history poisoning in general.
```

### Forged-Origin History Poisoning

The adversarial forged-origin pair is retained by AS-rel diagnostic while RPKI
is valid. It drops to zero retention under `mask_asrel_diagnostic`.

This is a single-signal fragility. It does not invalidate the bounded result,
but it means the system cannot yet claim robust forged-origin poisoning
coverage if the adversary can avoid the AS-rel diagnostic.

### Path-Manipulation History Poisoning

This is the current failure.

The clean path-manipulation pair is retained because the path is novel. The
adversarial variant simulates that the path signature has already been
introduced into public-monitor-derived history. After novelty is washed out:

- RPKI remains `valid`;
- AS-rel remains `all_pairs_known_no_valley_diagnostic`;
- community / NO_EXPORT risk is absent;
- the foreground policy suppresses the row as recurrent operational
  background.

This shows the exact robustness gap:

```text
short-lived crafted recurrence is being treated like stable benign history.
```

R-FOREGROUND-4 must repair this before learning or larger poisoning replay.

### Subprefix NO_EXPORT Evasion

The adversarial subprefix pair is retained by an evidence bundle:

- RPKI risk;
- community / NO_EXPORT evidence;
- path novelty;
- low-visibility external evidence.

It survives single-signal ablations but fails under the combined
`mask_external_and_path_novelty` stress test. This is acceptable for R-POISON-2A
as an audit result, but it must be reported as bundle-dependent retention.

NO_EXPORT remains visibility-evasion evidence, not attack truth.

### Stealth Collector-Asymmetry Evasion

The adversarial stealth pair is retained by:

- community / NO_EXPORT evidence;
- AS-rel diagnostic;
- path novelty;
- low-visibility external evidence.

It survives single-signal ablations but fails under combined external +
novelty masking. This means the bounded pair is retained under current
evidence, but stronger evasion variants are still required later.

## Repair Design

R-POISON-2A recommends R-FOREGROUND-4 with a narrow P0 repair:

```text
path_memory_poisoning_guard
```

Required feature direction:

- distinguish long-term stable recurrence from short-lived recent recurrence;
- track path age or first-seen delta;
- track pre-attack path burst / crafted-history indicators;
- separate long-term recurrence counts from recent-window recurrence counts;
- protect poisoning-susceptible path-memory transitions without treating every
  repeated path as suspicious.

Allowed claim:

```text
short-lived recurrence is not the same as long-term benign history.
```

Forbidden claim:

```text
recurrence alone proves path-manipulation attack.
```

## Compression Implication

Foreground compression still matters. The current online baseline reaches
about `0.51` background suppression and about `2.04x` compression on the
controlled full replay. R-FOREGROUND-4 should preserve this pressure as much as
possible.

However, compression must remain subordinate to the adversarial retention
stop-loss:

```text
suppressed_attack_count = 0
adversarial_attack_retention = 1.0
```

Only after the path-memory poisoning gap is repaired should the project try to
push toward the stretch `60%-70%` background-suppression target.

## Outputs

`outputs/r_poison_2a/s2a_baseline_v01_pilot_6h_april16/`

- `r_poison2a_summary.json`
- `r_poison2a_retention_reason_audit.csv`
- `r_poison2a_signal_ablation_audit.csv`
- `r_poison2a_pair_ablation_summary.csv`
- `r_poison2a_pair_fragility_audit.csv`
- `r_poison2a_foreground_repair_design.csv`
- `r_poison2a_report.md`

## Next Step

Proceed to:

```text
R-FOREGROUND-4 targeted path-memory poisoning guard
```

Do not proceed to learning, historical replay expansion, or larger poisoning
replay before this repair is designed and smoke-tested.
