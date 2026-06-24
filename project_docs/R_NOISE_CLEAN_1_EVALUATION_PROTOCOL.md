# R-NOISE-CLEAN-1 Evaluation Protocol Freeze

Date: 2026-06-23

Status: preregistered protocol; not executed.

## 1. Purpose

R-NOISE-CLEAN-1 will test one narrow question after the qualified full-window
replay passes:

```text
Can a clean foreground policy reduce reference-background workload without
suppressing any labeled controlled attack?
```

This document freezes the evaluation units, denominators, safety gates, and
stop-loss rules before the full-window result is inspected. It does not run a
foreground policy and does not select thresholds from the queued result.

## 2. Execution Gate

R-NOISE-CLEAN-1 must not execute until R-ATTACK-0A-3 reports all of the
following:

- full replay validation passes with no failed checks;
- raw parser admission for injected records is `1.0`;
- event-to-candidate attack retention is `1.0`;
- attack provenance is complete;
- RPKI `2024-04-16`, CAIDA AS-rel `2024-04-01`, and raw-derived community
  sidecars were recomputed for the derived run.

If any prerequisite fails, the next action is artifact repair, not foreground
evaluation.

### 2026-06-24 Qualification Addendum

R-ATTACK-0A-3 completed after this protocol was frozen. The strict validation
JSON reports `validated=false` because the global community raw-match check
misses one background event:

```text
events_with_raw_match = 3,431,116 / 3,431,117
event_raw_match_rate = 0.9999997085
failed_checks = [community_event_join_1]
```

The controlled attack path is qualified:

- candidate attack retention is `1.0`;
- RPKI attack evidence join is `1.0`;
- AS-rel attack evidence join is `1.0`;
- community attack evidence join is `1.0`;
- QA passed.

Therefore R-NOISE-CLEAN-1 may execute on the qualified full replay, with the
community caveat reported explicitly. This addendum does not change evaluation
denominators, safety gates, feasibility gates, or stop-loss thresholds. The
foreground policy must not use community absence or unavailable state as a
benign/safe feature.

## 3. Why the Old R-NOISE-1 Cannot Be Reused Unchanged

The archived R-NOISE-1 smoke is useful diagnostic history, but its implementation
references legacy final labels and old `rel_*` fields. Those inputs are forbidden
in the clean mainline.

The clean evaluation may use only:

- native event/candidate routing and observation fields;
- aligned RPKI sidecar;
- 2024-near AS-rel sidecar;
- raw-derived community sidecar with explicit join status.

Truth metadata such as `scenario_id`, `is_attack_member`, and `attack_subtype`
is evaluation-only and must never enter policy features.

## 4. Frozen Evaluation Populations

| Population | Definition | Truth boundary |
|---|---|---|
| active attack | controlled active attack members | controlled truth |
| scenario control | stable/recovery injected controls | not attack truth and not benign truth |
| hard negative | provenance-backed plausible non-attack lookalikes | not confirmed benign |
| reference background | no injected scenario membership | reference workload, not confirmed benign |
| mixed membership | scenario and non-scenario members in one event | excluded from pure background denominators |

Background compression must be computed only on pure reference-background
rows. Mixed events cannot silently inflate either attack retention or
background suppression.

## 5. Foreground Assignment Contract

The future frozen policy may assign:

- `protected_foreground`;
- `gray_retained`;
- `operational_background_suppressed`.

Downstream-retained workload is:

```text
protected_foreground + gray_retained
```

`operational_background_suppressed` is an operational action, not a benign
label. Gray attack members count as retained, but their rate must be reported
separately from explicitly protected attacks.

## 6. Primary Safety Gates

All gates below are mandatory:

| Gate | Required value |
|---|---:|
| suppressed active attack count | `0` |
| candidate-to-downstream attack retention | `1.0` |
| overall attack-scenario retention | `1.0` |
| exact-prefix origin scenario retention | `1.0` |
| forged-origin scenario retention | `1.0` |
| truth-feature leakage count | `0` |
| mixed rows in pure-background denominator | `0` |

Any active attack assigned to `operational_background_suppressed` triggers an
immediate stop-loss. The policy must be revised before learning.

## 7. Feasibility Gates

After all safety gates pass:

- reference-background suppression rate must be at least `0.05`;
- gray-zone rate must not exceed `0.50`.

These are engineering feasibility thresholds, not paper-level low-false-positive
claims. A policy that suppresses no attacks but also reduces almost no workload
is safe yet operationally unhelpful.

Hard-negative and scenario-control assignment distributions are required
diagnostics. They do not create a false-positive metric because these examples
are not confirmed benign.

## 8. Required Reporting

Report exact numerators and denominators at raw-record, event, scenario, and
attack-subtype levels:

- raw-to-event attack retention;
- event-to-candidate attack retention;
- candidate-to-protected attack rate;
- candidate-to-gray attack rate;
- candidate-to-downstream attack retention;
- suppressed attack count;
- reference-background suppression and foreground rates;
- gray-zone rate and foreground workload;
- hard-negative and scenario-control assignment distributions;
- mixed-membership count;
- per-scenario and per-subtype outcomes.

Only four origin-family attack scenarios currently exist. Therefore this phase
is a development gate for exact-prefix and forged-origin scenarios, not
multi-attack or real-world recall evidence.

## 9. Stop-Loss and Versioning

Stop before learning if:

- any attack is suppressed;
- truth metadata leaks into policy features;
- artifact or evidence provenance differs from R-ATTACK-0A-3;
- mixed membership contaminates the background denominator;
- background suppression is below `5%`;
- gray-zone rate exceeds `50%`.

Policy rules and their configuration hash must be frozen before execution. If
rules change after a failure, the rerun must use a new protocol version; this
document's denominators and original result remain unchanged.

## 10. Forbidden Claims

R-NOISE-CLEAN-1 cannot claim:

- reference background or hard negatives are confirmed benign;
- zero suppressed controlled attacks proves real-world recall;
- origin-family retention proves multi-attack retention;
- RPKI, AS-rel, or communities provide truth labels;
- poisoning/evasion robustness;
- learning readiness.

If the protocol passes, the next step is a clean foreground smoke for this
origin-family benchmark only. Additional attack families, historical replay,
and paired poisoning/evasion benchmarks remain required before paper-level
claims.
