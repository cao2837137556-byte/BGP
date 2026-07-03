# R-ATTACK-1 Attack Family Expansion Plan

Date: 2026-07-03

Status: feasibility audit completed; bounded materializer and QA are the next
implementation step.

## 1. Purpose

R-FOREGROUND-3 passed on the validated R-ATTACK-0B replay and freezes
`online_path_pressure_v1` as the current online foreground baseline.

R-ATTACK-1 expands attack coverage before learning, historical replay, or
poisoning. The goal is not to make more synthetic rows. The goal is to add
missing attack families that stress different evidence assumptions while
keeping every scenario realistic enough to survive reviewer scrutiny.

## 2. Why This Comes Before Learning

Current foreground evidence is encouraging but incomplete:

- exact-prefix origin hijack, forged-origin hijack, route-leak-like valley,
  and path-manipulation-like known transit were retained;
- subprefix behavior is still missing;
- stealth / NO_EXPORT / monitor-evasion behavior is still missing;
- poisoning/evasion paired variants are still missing.

Training now would only teach a model the attack coverage we already have. It
would not prove that the first layer protects the missing families.

## 3. Current Frozen Foreground Baseline

The current baseline is:

```text
online_path_pressure_v1
```

R-FOREGROUND-3 result:

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

This is a baseline, not a final production claim. It has not yet been tested on
subprefix, NO_EXPORT/stealth, historical attacks, or poisoning variants.

## 4. Required New Attack Families

### 4.1 Subprefix Origin Hijack

Purpose:

- test longest-prefix-match pressure;
- check whether foreground logic over-relies on exact prefix-origin novelty;
- create an origin-family case where RPKI length evidence may matter.

Realism requirements:

- the parent prefix must be observed in the 6h baseline;
- the subprefix must be syntactically valid and operationally plausible;
- the attacker ASN must come from the observed routing universe;
- RPKI is recomputed after injection;
- RPKI invalid-length is evidence, not truth.

### 4.2 Stealth / NO_EXPORT Visibility Scenario

Purpose:

- test whether the foreground layer protects monitor-evasion-like evidence;
- verify the community sidecar path under controlled attack conditions;
- avoid treating low visibility as a synonym for NO_EXPORT.

Realism requirements:

- use recomputed community sidecar fields;
- represent NO_EXPORT as BGP community evidence, not truth;
- define expected public visibility before evaluation;
- distinguish monitor-visible stealth-like rows from fully invisible rows.

Important boundary:

```text
NO_EXPORT present is not confirmed attack.
NO_EXPORT absent is not safe.
Low visibility is not confirmed NO_EXPORT.
```

If a variant is fully invisible to public collectors, it cannot be counted as a
foreground recall miss. It belongs to the observability-boundary analysis.

## 5. Required Hard Negatives

R-ATTACK-1 should also add a small hard-negative/control set:

- normal deaggregation or legitimate more-specific announcement;
- normal community change without attack truth;
- low-visibility non-attack reference pattern;
- legitimate MOAS or origin transition only if available provenance supports it.

These are not benign truth. They are audit cases for foreground pressure and
later offline training/evaluation pools.

## 6. Evidence Contract

After injection, every derived run must recompute or reattach:

- RPKI / VRP snapshot aligned to `2024-04-16`;
- CAIDA AS-rel snapshot `2024-04-01`;
- community / NO_EXPORT sidecar derived from raw updates.

No stale evidence is allowed. Old 2017 `rel_*` fields are forbidden in policy
decisions. Legacy final/high/needs/low labels remain audit references only.

## 7. Realism Gates

R-ATTACK-1 must pass these gates before any HPC full replay is meaningful:

- no documentation ASN shortcut;
- no random AS insertion without AS-rel or observed-routing justification;
- no fixed one-row attack pattern that looks unlike BGP dynamics;
- stable, attack, and recovery phases must exist;
- raw records must flow through the same parser and event construction path as
  background;
- truth labels must stay in sidecars and evaluation metadata;
- policy features must not include truth fields.

## 8. Foreground Validation Gate

R-ATTACK-1 reuses `online_path_pressure_v1` unchanged.

Pass conditions:

```text
suppressed_attack_count = 0
attack_retention = 1.0
truth_feature_leakage_count = 0
```

If any new family is suppressed, the next step is a foreground repair phase.
It is not learning and not poisoning expansion.

## 9. Deferred Scope

R-ATTACK-1 does not:

- implement paired poisoning/evasion variants;
- run historical replay;
- train a model;
- build the final training dataset;
- implement production suppression;
- aggregate attack-like incidents after judgment.

Poisoning/evasion remains a core paper claim, but it needs these base families
first so clean and adversarial pairs can be compared later.

## 10. Feasibility Audit Result

The read-only feasibility audit ran on the clean 6h baseline and the three
clean sidecars:

```text
scripts/audit_r_attack1_family_expansion_feasibility.py
```

Output directory:

```text
outputs/r_attack_1_feasibility/s2a_baseline_v01_pilot_6h_april16/
```

Key result:

| Item | Result |
|---|---:|
| event rows | `3431103` |
| RPKI rows aligned | `3431103` |
| AS-rel rows aligned | `3431103` |
| community rows aligned | `3431103` |
| subprefix parent prefix-origin candidates | `151374` |
| subprefix candidate events | `1435739` |
| NO_EXPORT event count | `1045` |
| NO_EXPORT low-visibility event count | `1045` |
| NO_EXPORT prefix-origin pairs | `764` |
| normal community hard-negative candidates | `3279787` |
| low-visibility reference candidates | `3389627` |

Conclusion:

```text
overall_feasible = true
```

This means the current baseline and clean sidecars contain enough templates to
design realistic R-ATTACK-1 scenarios. It does not mean attacks have already
been materialized or that NO_EXPORT is attack truth.

## 11. Next Step

Immediate next step:

```text
R-ATTACK-1 bounded materializer and QA:
materialize small subprefix and monitor-visible NO_EXPORT/stealth scenarios,
recompute evidence sidecars, and retest the frozen online_path_pressure_v1
foreground baseline.
```

If any new family is suppressed, stop and repair the foreground layer before
learning, historical replay, or poisoning/evasion variants.
