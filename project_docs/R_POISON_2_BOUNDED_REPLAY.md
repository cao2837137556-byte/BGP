# R-POISON-2 Bounded Poisoning / Evasion Replay

Status: bounded event-level replay, not full 6h replay.

## Goal

R-POISON-2 evaluates the R-POISON-1 materialized paired poisoning/evasion
prototypes under the frozen `online_path_pressure_v1` foreground policy.

The goal is to measure likely clean-vs-adversarial foreground retention drop
before spending cluster resources on a full raw-level replay.

## Boundary

This phase:

- uses the five R-POISON-1 feasible pairs;
- uses already validated clean-base evidence / foreground summaries;
- applies the frozen foreground policy logic to bounded event-level rows;
- reports clean-vs-adversarial retention drop;
- triggers stop-loss if any adversarial attack event is suppressed.

This phase does not:

- run the full 6h raw replay;
- train learning;
- change `online_path_pressure_v1`;
- materialize the blocked route-leak policy poisoning pair;
- claim historical poisoning robustness;
- treat NO_EXPORT / RPKI / AS-rel as truth.

## Why Bounded Replay First

R-POISON-1 proved that the paired contracts are fair. The next scientific
question is whether the current foreground layer is likely robust when the
history or visibility signals are manipulated.

Doing this first at bounded event level is useful because it can reveal a
foreground weakness before launching an expensive full replay. If the bounded
test already suppresses an adversarial attack variant, the correct next step
is foreground repair, not learning.

## Replay Logic

The script creates one clean and one adversarial bounded replay row per pair.
It preserves:

- clean base scenario;
- victim / origin / attacker groups;
- evidence snapshot binding;
- foreground policy;
- visibility denominator contract.

It changes only the R-POISON-0 allowed adversarial variables:

- for detection-data poisoning: pre-attack history / novelty / path-memory
  pressure;
- for visibility evasion: collector visibility and NO_EXPORT-related
  observability pressure.

## Metrics

R-POISON-2 reports:

- `clean_attack_retention`;
- `poisoned_or_evasive_attack_retention`;
- `retention_drop_under_poisoning_or_evasion`;
- `suppressed_attack_count`;
- `knowledge_base_drift_score`;
- `novelty_signal_drop`;
- `visibility_contract_satisfied`;
- `unobservable_from_public_control_plane`.

## Observability Rule

Public-invisible variants are not foreground misses. They are
observability-boundary cases and must be reported separately. The current
R-POISON-2 bounded variants are partial/public-visible contract cases.

## Command

```bash
python -m py_compile scripts/run_r_poison2_bounded_replay.py
python scripts/run_r_poison2_bounded_replay.py \
  --output-dir outputs/r_poison_2/s2a_baseline_v01_pilot_6h_april16 \
  --overwrite
```

## Outputs

- `r_poison2_summary.json`
- `r_poison2_bounded_replay_events.csv`
- `r_poison2_bounded_replay_events.parquet` if available
- `r_poison2_pair_metrics.csv`
- `r_poison2_pair_metrics.parquet` if available
- `r_poison2_report.md`

## Stop-Loss

If `suppressed_adversarial_attack_events > 0`, then R-POISON-2 triggers a
stop-loss:

```text
R-FOREGROUND-4 foreground repair before learning or larger poisoning replay.
```

This is not a failure of the project. It is exactly the robustness gap this
phase is supposed to expose.

## Local Run Result

The bounded replay completed on the five R-POISON-1 feasible pairs:

- pair count: `5`;
- event rows: `10`;
- clean attack retention mean: `1.0`;
- adversarial attack retention mean: `0.8`;
- suppressed adversarial attack events: `2`;
- stop-loss triggered: `true`.

The retention drop appears only in:

```text
pair_path_manipulation_history_poisoning_v01
```

Interpretation:

- The clean path-manipulation case is retained because the path is novel.
- The poisoned variant simulates that the path signature has already been
  introduced into history.
- RPKI remains `valid`.
- AS-rel remains `all_pairs_known_no_valley_diagnostic`.
- There is no NO_EXPORT / community risk signal.
- Under `online_path_pressure_v1`, the poisoned variant becomes recurrent
  background-like and is suppressed.

This is a valid robustness gap. It means the current foreground policy can be
history-poisoned for a path-manipulation-like case when no external risk signal
survives.

## Next Step

R-FOREGROUND-4 should repair the foreground policy before learning or larger
poisoning replay. The repair should be narrow: protect poisoning-susceptible
path-memory transitions without reverting to a too-conservative foreground
that loses background compression.
