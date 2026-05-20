# R-2B VRP-Aware Verifier Smoke

Status: fixed S2 full run completed.

Run id: `s2a_expanded_v01_pilot_6h_april16`

Run date: `2024-04-16`

Output directory: `outputs/r2b_vrp_aware_verifier_smoke_v01/`

## 1. Goal

R-2B connects the aligned historical VRP/RPKI evidence from R-2B-P0b back into the R-2A verifier scaffold.

The goal is not to prove attacks. The goal is to test whether the verifier can combine:

- legacy monitor-side incident triggers;
- dominant prefix-origin RPKI status;
- member/component RPKI status distributions;
- incident purity / mixture audit;
- R-1 verdict and confidence boundaries.

## 2. Why VRP-Aware Smoke

R-2A showed that a verifier table can be generated, but RPKI evidence was unavailable. R-2B-P0b resolved that blocker by materializing aligned `2024-04-16` VRP evidence.

R-2B tests whether this aligned evidence can be used without violating Phase R hard rules:

- RPKI invalid is not confirmed attack.
- RPKI valid is not benign.
- RPKI unknown is not normal.
- RPKI validates origin authorization only, not the full AS path.

## 3. Why Incident Purity / Component Audit Is Required

An incident is a bag/case, not a truth label. A single incident can contain multiple prefix-origin components and multiple RPKI states. Therefore R-2B keeps two views:

1. Dominant prefix-origin RPKI status.
2. Member/component RPKI status distribution.

The verifier must not let a dominant pair overwrite mixed evidence inside the incident. Mixed incidents are routed to `evidence_conflict`, `abstain`, or `evidence_insufficient` when the component structure is not safe enough.

## 4. Inputs

Required inputs:

- `outputs/r2b_p0b_vrp_materialization_v01/r2b_prefix_origin_rpki_lookup.parquet`
- `outputs/r2b0_evidence_readiness_audit_v01/r2b_prefix_origin_targets.parquet`
- `outputs/s3d_verification_queue_schema_v01/s3d_incident_verification_queue.parquet`
- `data/runs/s2a_expanded_v01_pilot_6h_april16/incidents/incident_tickets.parquet`
- `data/runs/s2a_expanded_v01_pilot_6h_april16/incidents/incident_membership.parquet`

The script also reuses the local aligned VRP cache at:

- `data/evidence/rpki/vrp_2024-04-16.parquet`

This is not a new download. It is the cache materialized by R-2B-P0b.

## 5. Outputs

Main outputs:

- `r2b_vrp_verifier_summary.json`
- `r2b_vrp_incident_verifier_table.parquet`
- `r2b_vrp_incident_verifier_table.csv`
- `r2b_vrp_verdict_distribution.csv`
- `r2b_rpki_incident_status_distribution.csv`
- `r2b_component_purity_distribution.csv`
- `r2b_mixed_incident_cases.csv`
- `r2b_evidence_supported_candidates.csv`
- `r2b_conflict_cases.csv`
- `r2b_abstain_cases.csv`
- `r2b_topk_review_candidates.csv`
- `r2b_human_burden_proxy.csv`
- `r2b_vrp_smoke_report.md`

Large output files remain local and are not committed.

## 6. Verdict Rules

R-2B uses the R-1 verdict set:

- `strongly_supported_suspicious`
- `evidence_supported_suspicious`
- `evidence_conflict`
- `evidence_insufficient`
- `external_evidence_unavailable`
- `background_like_but_unconfirmed`
- `stale_evidence_only`
- `abstain`

R-2B is conservative:

- `strongly_supported_suspicious=0` in the full run.
- `evidence_supported_suspicious` requires monitor-side trigger plus aligned RPKI invalid component evidence plus component consistency.
- RPKI invalid alone cannot trigger suspicious.
- Mixed incidents are not forced into suspicious or background.
- `safe_negative_candidate_flag` remains false for all rows.

## 7. Full Run Result

Processed incidents: `217165`

Dominant prefix-origin RPKI status:

| Status | Count |
| --- | ---: |
| valid | 122280 |
| unknown | 94202 |
| invalid_asn | 397 |
| invalid_length | 283 |
| unavailable | 3 |

Member/component RPKI status:

| Status | Member rows |
| --- | ---: |
| valid | 3048894 |
| unknown | 2075964 |
| unavailable | 348708 |
| invalid_length | 3074 |
| invalid_asn | 2663 |

Component purity:

| Class | Count |
| --- | ---: |
| pure_dominant | 114237 |
| insufficient_component_signal | 94666 |
| highly_mixed_should_split | 4689 |
| mostly_dominant | 3023 |
| mixed_but_core_suspicious | 479 |
| mixed_conflicting | 71 |

Verifier verdict distribution:

| Verdict | Count |
| --- | ---: |
| background_like_but_unconfirmed | 156971 |
| evidence_insufficient | 55366 |
| abstain | 4684 |
| evidence_conflict | 86 |
| evidence_supported_suspicious | 55 |
| external_evidence_unavailable | 3 |

Hard safety violations: `0`

Strongly supported suspicious: `0`

## 8. Human Burden Proxy

Legacy calibrated P1/P2 incidents: `55083`

Evidence/conflict/abstain candidate review count: `4825`

Unsupported alert reduction proxy: `0.912405`

Top-K evidence-supported density:

- top 50: `0.08`
- top 100: `0.12`
- top 500: `0.052`

This is a smoke-level burden proxy, not a final human-burden experiment.

## 9. Relationship to CCF-A Target Line

R-2B is the first evidence-backed verifier smoke in the CCF-A path:

```text
R-2B: VRP-aware verifier smoke + incident purity audit
  -> R-2C: path evidence / route-leak legality
  -> R-3: poisoning / evasion benchmark
  -> L1/L2: component-aware semantic ranker and calibrator
```

The key CCF-A-relevant move is component awareness. The system now explicitly distinguishes dominant status, member distribution, mixed conflicts, should-split incidents, and verifier abstention.

## 10. Current Limits

- R-2B only uses RPKI/VRP evidence.
- It does not attach IRR, ASPA, PeeringDB, data-plane, or aligned AS relationship evidence.
- It does not perform route-leak legality checking.
- It does not run poisoning/evasion benchmark.
- It does not train learning models.
- It does not produce confirmed attack/benign labels.

## 11. Next Step

Recommended order:

1. R-2C path evidence branch / route-leak legality refinement.
2. R-3 poisoning benchmark early design.
3. L1 component-aware semantic learner design.

Formal learning remains blocked until verifier-supported targets and robustness settings are stronger.
