# R-FOREGROUND-4A Path-Memory Maturity Feasibility Audit

Status: completed read-only audit.

## Goal

R-POISON-2 exposed a foreground robustness gap:

```text
pair_path_manipulation_history_poisoning_v01
```

The clean path-manipulation case was retained because its path was novel. The
poisoned variant simulated that the same path memory had been pre-populated, so
`online_path_pressure_v1` treated it as recurrent operational background and
suppressed it.

R-FOREGROUND-4A audits whether the current foreground artifacts can support the
right repair:

```text
long-term natural recurrence != short-term crafted recurrence
```

This phase only computes path-memory maturity features and impact estimates. It
does not change the foreground policy.

## Boundary

This phase does:

- read the supplied R-ATTACK-1 / R-FOREGROUND-3 assignment artifact;
- compute within-window path-memory maturity proxies;
- check the R-POISON-2 path-memory failure against those proxies;
- estimate how much compression would be lost if the guard were too broad;
- define the safe boundary for R-FOREGROUND-4B.

This phase does not:

- modify `online_path_pressure_v1`;
- train learning;
- run a full 6h replay;
- claim that within-window recurrence proves long-term maturity;
- claim that immature recurrence is attack truth;
- treat RPKI, AS-rel, or NO_EXPORT as labels.

## Input Scope

The local run used:

```text
outputs/r_attack_1/s2a_attack1_family_expansion_6h_april16_v01/
  smoke_replay/foreground3/r_foreground3_assignment.parquet
```

This artifact contains `384,839` assignment rows. It is the supplied local
R-ATTACK-1 smoke-replay foreground artifact, not automatically a full 3.4M-row
mainline replay. Therefore the result is a feature-feasibility and repair-boundary
audit, not a final full-window compression claim.

The audit also reads:

```text
outputs/r_poison_2/s2a_baseline_v01_pilot_6h_april16/
  r_poison2_bounded_replay_events.csv
```

## Maturity Feature Definitions

The audit builds one path-memory row per `prefix_origin_path_key` and computes:

- event count for the path key;
- first / last observed time inside the supplied window;
- observed span in seconds;
- collector diversity from `collector_set`;
- whether the path is seen near the start of the supplied window;
- whether it appears only after the initial grace period;
- whether it is short-lived inside the supplied window;
- whether it is recurrent but not mature;
- whether it has a strong mature proxy.

Important boundary:

```text
within-window maturity proxy != long-term maturity
```

Formal long-term maturity requires a longer historical sidecar. A 6h or
smoke-replay window can only provide local evidence.

## Results

Summary:

- assignment rows audited: `384,839`;
- unique `prefix_origin_path_key`: `239,939`;
- current suppressed rows: `184,772`;
- current suppression rate: `0.480128`;
- current compression ratio: `1.923551`;
- window span: `5,771` seconds;
- within-window span threshold met: `true`;
- supports long-term maturity claim: `false`;
- suppressed recent-suspicious recurrence proxy rows: `67,758`;
- share of suppressed rows that are recent-suspicious recurrence proxy:
  `0.366711`;
- suppressed strong-mature proxy rows: `0`;
- R-POISON-2 path-memory failure classified: `true`.

## Compression Impact

The key lesson is that a broad guard is too expensive.

| Scenario | Suppression Rate | Compression Ratio | Interpretation |
|---|---:|---:|---|
| Current `online_path_pressure_v1` | `0.480128` | `1.923551` | current supplied assignment |
| Guard all recent-suspicious recurrence proxy rows | `0.304060` | `1.436905` | too broad; loses too much compression |
| Allow only strong mature suppression | `0.000000` | `1.000000` | uselessly conservative under current artifact |

This means R-FOREGROUND-4B must not simply retain every recent recurrence. The
repair has to be targeted to poisoning-like path-memory transitions.

## R-POISON-2 Failure Check

The R-POISON-2 failed pair is classified as:

```text
bounded_recent_crafted_history_proxy
```

For the adversarial path-manipulation variant:

- `knowledge_base_drift_score = 0.75`;
- `novelty_signal_drop = 1.0`;
- `prefix_origin_path_event_count = 4`;
- current assignment: `operational_background_suppressed`;
- path-memory failure: `true`.

This bounded pair does not contain real long-term path history. It is still
useful because it tells us the current foreground policy can be fooled when
crafted recurrence removes novelty.

## Repair Boundary for R-FOREGROUND-4B

R-FOREGROUND-4B should implement a targeted guard, not a broad must-keep rule.

Allowed direction:

```text
if recurrence is recent / crafted-like and path memory is not mature,
do not allow it to serve as a strong suppression basis.
```

Forbidden direction:

```text
if recent recurrence, then attack.
```

Maturity can only answer:

```text
is this route mature enough to suppress?
```

It cannot answer:

```text
is this route an attack?
```

## Outputs

`outputs/r_foreground_4a/s2a_attack1_family_expansion_6h_april16_v01/`

- `r_foreground4a_summary.json`
- `r_foreground4a_path_memory_feature_audit.csv`
- `r_foreground4a_maturity_bucket_audit.csv`
- `r_foreground4a_candidate_guard_impact_estimate.csv`
- `r_foreground4a_poison_pair_maturity_audit.csv`
- `r_foreground4a_suppressed_recent_recurrence_sample.csv`
- `r_foreground4a_report.md`

## Next Step

Proceed to:

```text
R-FOREGROUND-4B targeted path-memory poisoning guard smoke
```

R-FOREGROUND-4B should:

- repair `pair_path_manipulation_history_poisoning_v01`;
- keep `suppressed_attack_count = 0`;
- restore adversarial retention to `1.0`;
- preserve useful compression as much as possible;
- avoid protecting all recent recurrence;
- keep maturity as a suppression-permission feature, not an attack score.
