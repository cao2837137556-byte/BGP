# R-POISON-0 Paired Poisoning / Evasion Protocol

Status: protocol and feasibility audit only.

Generated artifacts:

- `configs/r_poison0_paired_benchmark_protocol_v01.json`
- `scripts/audit_r_poison0_feasibility.py`
- `outputs/r_poison_0/s2a_baseline_v01_pilot_6h_april16/` after the audit script is run

## Goal

R-POISON-0 defines the poisoning/evasion benchmark contract before any
poisoned or evasive BGP data is generated.

This phase is not a detector, not a learning experiment, and not a foreground
policy update. It answers one narrow question:

Can the now-validated controlled attack families be extended into strict
clean-vs-adversarial paired scenarios without changing the wrong variables or
making unsupported truth claims?

## Why This Phase Exists

The current online foreground baseline, `online_path_pressure_v1`, has passed
the controlled family gate:

- R-ATTACK-0B covered exact-prefix origin hijack, forged-origin hijack,
  route-leak-like path diagnostic, and path-manipulation-like scenarios.
- R-ATTACK-1 added subprefix origin hijack and monitor-visible
  NO_EXPORT / stealth visibility scenarios.
- The full R-ATTACK-1 replay retained all controlled attack events:
  `foreground_attack_retention=1.0`, `suppressed_attack_count=0`,
  background suppression `0.510540519`, and compression `2.043065`.

That is enough to start poisoning/evasion benchmark design, but not enough to
claim poisoning robustness. Poisoning changes the meaning of historical
memory; monitor evasion changes what public monitors are expected to see.
Those cannot be evaluated by unpaired synthetic rows.

## Threat-Model Boundary

R-POISON-0 separates three concepts that are easy to confuse:

| Concept | Role in This Project | Boundary |
|---|---|---|
| detection-data poisoning | core target | crafted pre-attack announcements pollute public-monitor-derived history, novelty, role, or path memory |
| visibility evasion | core target | the attacker constrains what public collectors see, for example with subprefix + NO_EXPORT or collector asymmetry |
| AS-path poisoning for traffic engineering | terminology caveat | relevant BGP term, but not the main benchmark target here |

The core paper claim is about low false positive multi-attack judgment under
incomplete, evasive, and poisonable public monitors. Therefore the benchmark
must test whether the same clean attack becomes harder after history or
visibility is manipulated.

## Paired Benchmark Rule

Every poisoning/evasion scenario must have a clean counterpart.

Held constant:

- victim prefix group;
- legitimate origin group;
- attacker AS group;
- background window;
- collector set or explicit visibility contract;
- evidence snapshot binding;
- foreground policy.

Changed variables:

- poisoning preparation;
- pre-attack origin/path/link/role history;
- NO_EXPORT / visibility constraint;
- expected collector visibility;
- adversarial variant type.

If a result is not paired, it cannot support the poisoning/evasion claim.

## Pair Templates

The protocol currently defines six pair templates.

| Pair | Clean Base | Variant | Threat Model | R-POISON-1 Status |
|---|---|---|---|---|
| `pair_exact_origin_history_poisoning_v01` | `r_attack0b_exact_origin_001` | `data_poisoned` | detection-data poisoning | ready pending materialization |
| `pair_forged_origin_history_poisoning_v01` | `r_attack0b_forged_origin_001` | `data_poisoned` | detection-data poisoning | ready pending materialization |
| `pair_path_manipulation_history_poisoning_v01` | `r_attack0b_path_manip_001` | `data_poisoned` | detection-data poisoning | ready pending materialization |
| `pair_subprefix_noexport_evasion_v01` | `r_attack1_subprefix_origin_001` | `noexport_evasive` | visibility evasion | ready pending materialization |
| `pair_stealth_collector_asymmetry_v01` | `r_attack1_stealth_noexport_001` | `visibility_evasive` | visibility evasion | ready pending materialization |
| `pair_route_leak_policy_poisoning_v01` | `r_attack0b_route_leak_001` | `data_poisoned` | detection-data poisoning | design only; needs policy semantics |

The route-leak pair is intentionally not promoted yet. AS-rel valley-like
diagnostics are useful evidence, but they are not route-leak truth. A route
leak poisoning benchmark needs a more explicit policy-semantics contract.

## Required Metrics

R-POISON-1 and later phases must report:

- `clean_attack_retention`;
- `poisoned_or_evasive_attack_retention`;
- `retention_drop_under_poisoning_or_evasion`;
- `clean_foreground_rate`;
- `poisoned_or_evasive_foreground_rate`;
- `knowledge_base_drift_score`;
- `novelty_signal_drop`;
- `visibility_contract_satisfied`;
- `unobservable_from_public_control_plane`;
- `suppressed_attack_count`;
- `foreground_workload_change`.

The important metric is not only whether the attack is detected. The benchmark
must show whether the adversarial preparation reduces or removes the signals
that the clean counterpart relied on.

## Observability Denominator

Public-invisible control-plane events are not ordinary false negatives.

For visibility evasion:

- `public_visible` variants are included in the foreground recall denominator.
- `partial_public_visible` variants are included only for collectors that the
  scenario contract says should see the event.
- `public_invisible` variants are excluded from foreground recall and reported
  as an observability-boundary case.

This prevents the system from being punished for not detecting a route that no
public monitor was expected to observe.

## Evidence Boundary

The following are evidence or diagnostics only:

- RPKI / VRP status;
- AS-rel path diagnostics;
- communities and NO_EXPORT;
- collector visibility;
- path or origin novelty;
- historical memory drift.

Forbidden claims:

- `NO_EXPORT` present is not attack truth.
- `NO_EXPORT` absent is not safe.
- RPKI invalid is not attack truth.
- RPKI valid is not benign.
- AS-rel diagnostic is not route leak truth.
- Background suppression is not confirmed benign.
- Legacy final/high/needs/low labels are not truth or guards.

## Feasibility Audit

Run:

```bash
python -m py_compile scripts/audit_r_poison0_feasibility.py
python scripts/audit_r_poison0_feasibility.py \
  --config configs/r_poison0_paired_benchmark_protocol_v01.json \
  --output-dir outputs/r_poison_0/s2a_baseline_v01_pilot_6h_april16 \
  --overwrite
```

Expected outputs:

- `r_poison0_summary.json`
- `r_poison0_pair_feasibility.csv`
- `r_poison0_required_protocol_fields.csv`
- `r_poison0_forbidden_shortcut_audit.csv`
- `r_poison0_next_action.md`

The audit checks clean-base availability, validation status, held constants,
changed variables, observability contracts, denominator policy, poisoning
memory targets, drift metrics, and forbidden shortcuts.

## Stop-Loss Rules

Do not enter R-POISON-1 if any of the following happen:

- a required clean base scenario is missing;
- clean-base validation is unavailable or failed;
- held constants are incomplete;
- changed variables are unclear;
- a poisoned/evasive variant is unpaired;
- public-invisible events are counted as foreground misses;
- detection-data poisoning lacks knowledge-base targets or drift metrics;
- visibility evasion lacks expected seen / not-seen collector contracts;
- the phase starts training or modifies online foreground policy.

## Relationship to Foreground and Learning

R-POISON-0 does not change `online_path_pressure_v1`.

If R-POISON-1 later shows that poisoning or visibility evasion suppresses
attack variants, the next step is foreground repair or poisoning-aware
evidence design, not learning. Learning remains blocked until the benchmark
can show that foreground safety holds across clean and adversarial variants.

## Literature Anchors

The design follows the project deep-research report and these source anchors:

- [Is Crunching Public Data the Right Approach to Detect BGP Hijacks?](https://arxiv.org/abs/2507.20434)
- [Global BGP Attacks that Evade Route Monitoring](https://arxiv.org/abs/2408.09622)
- [BEAM: Learning with Semantics](https://www.usenix.org/conference/usenixsecurity24/presentation/chen-yihao)
- [DFOH](https://www.usenix.org/conference/nsdi24/presentation/holterbach)
- [RFC 1997 BGP Communities](https://datatracker.ietf.org/doc/html/rfc1997)
- [RFC 7908 Route Leak Definition](https://www.rfc-editor.org/info/rfc7908)
- [RFC 9234 BGP Roles / OTC](https://datatracker.ietf.org/doc/html/rfc9234)

## Next Step

If the R-POISON-0 audit passes, proceed to:

```text
R-POISON-1:
Bounded materialization of feasible paired poisoning/evasion variants.
```

R-POISON-1 should materialize only the feasible pairs. The route-leak policy
poisoning pair should remain design-only until its policy-semantics contract is
tight enough.
