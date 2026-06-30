# R-ATTACK-0B Multi-Attack Controlled Smoke

Date: 2026-06-30

Status: implementation ready; full run pending.

## 1. Purpose

R-ATTACK-0B extends the controlled benchmark beyond the initial origin-family
smoke. It directly materializes a small multi-attack replay and immediately
checks whether the current online foreground policy keeps every controlled
attack event.

This phase does not train learning, does not implement poisoning, and does not
claim final multi-attack benchmark coverage.

## 2. Attack Families

R-ATTACK-0B includes four controlled attack subtypes:

| Subtype | Purpose |
|---|---|
| `exact_prefix_origin_hijack` | Ordinary origin hijack; origin changes and RPKI may become invalid |
| `forged_origin_hijack` | Forged-origin style path; origin remains legitimate, path includes counterfactual adjacent AS |
| `route_leak_like_valley` | AS-rel constrained route-leak-like path diagnostic; must trigger `possible_valley_transition` |
| `path_manipulation_known_transit` | Origin-preserved path semantic manipulation; must use all-known, no-valley AS-rel edges |

The key addition is not just "more attacks". The key is that attacks must be
realistic enough to stress the system's evidence assumptions.

## 3. Realism Constraints

The materializer enforces:

- no documentation ASN shortcut;
- counterfactual role ASNs must appear in the observed 6h routing universe;
- inserted AS edges must be known in the 2024 CAIDA AS-rel cache;
- route-leak-like scenarios must produce `possible_valley_transition`;
- path-manipulation scenarios must use `all_pairs_known_no_valley_diagnostic`
  so they test path novelty rather than route-leak or unknown-edge shortcuts;
- communities are preserved from observed legitimate templates;
- NO_EXPORT / stealth / poisoning are not introduced in this phase;
- truth labels are written only to sidecars, never into raw updates.

For dynamic route-leak/path-manipulation scenarios, the role AS is selected
from the observed routing universe and cached per scenario/collector so the
same event does not unrealistically change attacker role every minute.

## 4. Evidence Boundary

R-ATTACK-0B reuses the current clean evidence ledger:

- RPKI / VRP snapshot aligned to `2024-04-16`;
- CAIDA AS-rel snapshot `2024-04-01`;
- raw-derived communities / NO_EXPORT sidecar.

No new external evidence source is added in this phase.

Allowed claims:

- evidence sidecars were recomputed for the derived run;
- route-leak-like scenarios have AS-rel valley diagnostics;
- path-manipulation scenarios preserve origin and use all-known/no-valley path
  evidence;
- foreground v1 either retains or suppresses each controlled attack event.

Forbidden claims:

- RPKI invalid means attack truth;
- AS-rel diagnostic means confirmed route leak;
- NO_EXPORT is an attack label;
- hard negatives are benign;
- this smoke proves poisoning/evasion robustness;
- learning is ready.

## 5. Full Replay Pipeline

The HPC wrapper runs:

```text
materialize controlled raw updates
-> build event units
-> build candidate diagnostics
-> recompute RPKI / AS-rel / community sidecars
-> raw-to-event propagation audit
-> R-FOREGROUND-1 online foreground retest
-> R-ATTACK-0B QA
-> full replay validation
```

Candidate output is diagnostic only. The main foreground check is
R-FOREGROUND-1.

## 6. Outputs

Config:

```text
configs/r_attack0b_multi_attack_smoke_v01.json
```

Scripts:

```text
scripts/materialize_r_attack0b_multi_attack_smoke.py
scripts/audit_r_attack0b_multi_attack_qa.py
scripts/hpc/validate_r_attack0b_full_replay.py
scripts/hpc/r_attack0b_multi_attack_full_replay.slurm
```

Expected output root:

```text
outputs/r_attack_0b/s2a_attack0b_multi_attack_smoke_6h_april16_v01/
```

Important small-result files:

```text
full_replay_validation.json
materialization/materialization_summary.json
materialization/dynamic_role_selection_audit.csv
materialization/inserted_edge_topology_audit.csv
audit/scenario_propagation_audit.csv
audit/scenario_evidence_response_audit.csv
foreground1/r_foreground1_summary.json
qa/r_attack0b_qa_summary.json
qa/qa_checks.csv
qa/scenario_qa.csv
```

Large parquet outputs must not be committed.

## 7. Pass Conditions

R-ATTACK-0B passes only if:

- every controlled attack raw record maps to event membership;
- all required attack subtypes are present;
- inserted edges are known in the 2024 AS-rel cache;
- route-leak-like scenarios have `possible_valley_transition`;
- path-manipulation scenarios produce `all_pairs_known_no_valley_diagnostic`;
- RPKI / AS-rel / community sidecars align with the derived run;
- R-FOREGROUND-1 keeps attack retention at `1.0`;
- `suppressed_attack_count = 0`;
- no learning is trained.

## 8. Next Step

If R-ATTACK-0B passes, analyze foreground v1 per-family retention and
compression. If every attack is retained but compression remains below the
future multi-attack target, design R-FOREGROUND-2. If any family is suppressed,
repair foreground before adding NO_EXPORT / stealth / poisoning scenarios.
