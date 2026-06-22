# R-ATTACK-0A-2 Hardened Origin Smoke

Date: 2026-06-22

Status: bounded smoke and QA passed. The hardened scenario set is qualified for
a full-window replay, but no full-window, foreground, low-FP, or learning claim
has been made.

## 1. Purpose

R-ATTACK-0A-2 repairs only the scenario-quality blockers found by
R-ATTACK-QA-0:

- documentation-AS shortcuts;
- attack-phase empty-community leakage;
- insufficient attack-template diversity;
- missing hard-negative lookalikes;
- confusion between event-level and scenario-level visibility.

It does not add route leak, NO_EXPORT evasion, poisoning, learning, or final
suppression.

## 2. Scenario Set

The bounded smoke contains:

- two exact-prefix origin scenarios;
- two forged-origin scenarios;
- four controlled plausible non-attack lookalikes:
  - observed valid MOAS transition;
  - observed parent/subprefix deaggregation;
  - observed normal community variation;
  - observed traffic-engineering path change.

Hard negatives are not confirmed benign truth. They are provenance-backed
lookalikes used to test whether a later foreground layer overreacts to
legitimate-looking routing changes.

Observed ASNs are used only as topology-consistent counterfactual roles. The
experiment does not allege that any selected real network performed an attack.

## 3. Topology and Community Repairs

All newly inserted attack edges are present in the CAIDA
`2024-04-01` AS-rel cache. Attack templates lock the audited penultimate AS
before choosing a time-near raw record, preventing path drift from silently
changing the topology contract.

Communities are copied from matched legitimate raw templates. They are changed
only in the explicit normal-community-variation hard negative.

Results:

- attack/non-attack community fingerprint overlap: `4`;
- attack communities are no longer forced empty;
- active NO_EXPORT event count: `0`;
- no NO_EXPORT/evasion scenario was introduced.

## 4. Inputs and Execution

Configuration:

```text
configs/r_attack0a2_hardened_origin_smoke_v02.yaml
```

Scripts:

```text
scripts/materialize_r_attack0a2_hardened_smoke.py
scripts/audit_r_attack0a2_hardened_qa.py
```

Derived run:

```text
s2a_attack0a2_hardened_origin_smoke_6h_april16_v02
```

Materialization:

| Metric | Value |
|---|---:|
| Source raw rows | 7,200,000 |
| Derived raw rows | 7,200,096 |
| Injected attack rows | 32 |
| Injected hard-negative rows | 32 |
| Injected stable/recovery controls | 32 |
| Rewritten chunks | 12 |
| Hard-linked unchanged chunks | 132 |
| Inserted edges known in 2024 AS-rel | all |

Only the 12 rewritten chunks were processed in the bounded smoke:

- raw rows: `600,096`;
- event rows: `384,850`;
- candidate rows: `384,850`.

The candidate step used the immutable baseline tables from
`s2a_baseline_v01_pilot_6h_april16`. The injected run did not build its own
history.

## 5. Evidence Binding

The derived event/candidate rows were reattached to:

- RPKI/VRP snapshot `2024-04-16`;
- CAIDA AS-rel snapshot `2024-04-01`, delta 15 days;
- communities from the rewritten raw chunks.

All three event join rates were `1.0`.

Mechanism checks:

- exact-prefix scenarios: RPKI `invalid_asn`;
- forged-origin scenarios: RPKI `valid`;
- hard negatives matched their configured observed RPKI states;
- attack paths had no construction-only AS-rel unknown shortcut.

These are evidence responses, not truth labels.

## 6. QA Results

| Metric | Result |
|---|---:|
| QA checks | 16 |
| Passed | 16 |
| Failed | 0 |
| Attack raw admission | 1.0 |
| Hard-negative raw admission | 1.0 |
| Candidate attack retention | 1.0 |
| Hard-negative candidate event rate | 0.357143 |
| Scenario visibility contract rate | 1.0 |
| Scenario RPKI expectation rate | 1.0 |
| Active NO_EXPORT events | 0 |

All attack events survived the legacy candidate comparison gate.

Five of fourteen active hard-negative events were also marked as candidates:

- observed MOAS transition: `2/2`;
- deaggregation: `1/4`;
- community variation: `1/4`;
- traffic-engineering path change: `1/4`.

This is not a failure of the smoke. It is evidence that the legacy candidate
gate cannot be the final foreground filter and that the later clean foreground
experiment must measure hard-negative retention/suppression explicitly.

## 7. Visibility Interpretation

Each scenario was observed in both declared collectors, so scenario-level
visibility contract coverage is `1.0`.

Collector-specific paths can still produce separate event rows with
`collector_count=1`. Therefore:

```text
single-collector event != low-visibility scenario
```

Future policy logic must use routing-object/time or scenario-level visibility
rather than treating event grouping artifacts as stealth evidence.

## 8. Claims and Limits

Allowed:

- hardened raw/event/candidate/evidence plumbing passed;
- the original ASN and community shortcuts were removed;
- the scenario set contains attack and provenance-backed lookalike controls;
- the scenario set is ready for a qualified full-window replay.

Forbidden:

- current background is confirmed benign;
- hard negatives are confirmed benign;
- candidate output is a final detector;
- low false-positive performance is proven;
- poisoning/evasion robustness is proven;
- learning is ready.

## 9. Next Action

```text
R-ATTACK-0A-3:
Package and execute the qualified full 6h replay, validate complete artifacts,
and measure full-window attack/hard-negative workload before R-NOISE-CLEAN-1.
```

The full replay should run on the supercomputer after a packaging smoke. It
must preserve the immutable clean baseline and the same versioned evidence
snapshots.
