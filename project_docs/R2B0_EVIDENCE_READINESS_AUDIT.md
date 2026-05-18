# R-2B-0 Evidence Readiness Audit

Last updated: 2026-05-18

Status: full incident-level readiness audit completed.

## 1. Goal

R-2B-0 checks whether the fixed S2 incident queue can be joined to external evidence before implementing new verifier logic.

The audit answers:

- whether incidents have stable prefix-origin/time/path lookup keys;
- whether local evidence caches exist and are aligned to the `2024-04-16` run window;
- which evidence types must remain `unavailable` or `stale_diagnostic`;
- whether the next step should repair incident schema, materialize VRP/RPKI cache, or move to verifier refinement.

R-2B-0 is an audit only. It does not modify legacy detector outputs, verifier verdicts, or S3 artifacts.

## 2. Fixed Scope

Fixed run:

- `s2a_expanded_v01_pilot_6h_april16`

Inputs:

- `outputs/s3d_verification_queue_schema_v01/s3d_incident_verification_queue.parquet`
- `data/runs/s2a_expanded_v01_pilot_6h_april16/incidents/incident_tickets.parquet`
- `data/runs/s2a_expanded_v01_pilot_6h_april16/incidents/incident_membership.parquet`
- optional R-2A and S3-D2 outputs for context/readiness checks
- optional cache directories under `data/evidence/`
- legacy CAIDA AS relationship file `data/caida/as-relationships/serial-2/20170701.as-rel2.txt`

Outputs:

- `outputs/r2b0_evidence_readiness_audit_v01/`

Script:

- `scripts/run_r2b0_evidence_readiness_audit.py`

## 3. Hard Safety Rules

The audit inherits Phase R / R-1 safety rules:

- RPKI/ROA only validates prefix-origin authorization; it does not validate the full AS path.
- RPKI invalid is not confirmed attack.
- RPKI valid is not confirmed benign.
- RPKI unknown is not normal.
- IRR match is not confirmed legitimate.
- IRR miss is not attack.
- RIS/RouteViews/public monitor slices are monitor/context evidence, not independent external truth.
- Unavailable evidence remains unavailable, not benign.
- Legacy `high/needs/low` and `P1/P2/P3` remain legacy signals, not ground truth.
- No learning layer is allowed before verifier-supported incident targets exist.

## 4. Commands

Compile:

```powershell
python -m py_compile scripts/run_r2b0_evidence_readiness_audit.py
```

Smoke:

```powershell
python scripts/run_r2b0_evidence_readiness_audit.py ^
  --run-id s2a_expanded_v01_pilot_6h_april16 ^
  --output-dir outputs/r2b0_evidence_readiness_audit_v01 ^
  --s3d-output-dir outputs/s3d_verification_queue_schema_v01 ^
  --r2a-output-dir outputs/r2a_legality_first_verifier_smoke_v01 ^
  --s3d2-output-dir outputs/s3d2_external_evidence_attachment_v01 ^
  --legacy-as-rel-file data/caida/as-relationships/serial-2/20170701.as-rel2.txt ^
  --run-date 2024-04-16 ^
  --sample-rows 50000
```

Full audit:

```powershell
python scripts/run_r2b0_evidence_readiness_audit.py ^
  --run-id s2a_expanded_v01_pilot_6h_april16 ^
  --output-dir outputs/r2b0_evidence_readiness_audit_v01 ^
  --s3d-output-dir outputs/s3d_verification_queue_schema_v01 ^
  --r2a-output-dir outputs/r2a_legality_first_verifier_smoke_v01 ^
  --s3d2-output-dir outputs/s3d2_external_evidence_attachment_v01 ^
  --legacy-as-rel-file data/caida/as-relationships/serial-2/20170701.as-rel2.txt ^
  --run-date 2024-04-16 ^
  --full-run
```

## 5. Full Audit Result

Full audit processed `217165` incidents.

Lookup key readiness:

- prefix-origin complete: `217162 / 217165` (`0.999986`)
- time-window complete: `217165 / 217165` (`1.000000`)
- path-key complete: `216922 / 217165` (`0.998881`)
- triplet-key complete: `205067 / 217165` (`0.944291`)
- candidate prefix-origin lookup targets: `217162`
- usable path/triplet targets: `216922`

Cache readiness:

- RPKI/VRP: `missing`
- IRR route object: `missing`
- AS relationship: `ready_stale`, because only `20170701.as-rel2.txt` is present
- ASPA: `missing`
- PeeringDB: `missing`
- known-event inventory: `present_unverified_schema`
- incident internal visibility: `ready_aligned`
- public monitor context: `ready_aligned`, but context/trigger only

## 6. Interpretation

Incident schema is not the main blocker.

The fixed S2 incident queue already has enough prefix-origin/time/path keys to support external evidence lookup:

- VRP/RPKI lookup can be attempted for almost all incidents once a historical cache exists.
- Path/triplet legality targets are also nearly complete, but aligned path-legality evidence is not ready.
- The 2017 CAIDA AS relationship file must remain `stale_diagnostic` for 2024 incidents.

The current blocker is aligned evidence cache readiness, especially the missing historical VRP/RPKI cache for `2024-04-16`.

## 7. Readiness Matrix Summary

| Evidence | Lookup readiness | Cache readiness | Current role |
|---|---:|---|---|
| RPKI/VRP | `217162` targets | `missing` | next P0 cache materialization |
| IRR route object | `217162` targets | `missing` | P1 auxiliary context |
| AS relationship | `216922` targets | `ready_stale` | stale diagnostic only |
| ASPA | `216922` targets | `missing` | future path-legality work |
| BGP Roles / OTC | `216922` targets | `missing` | future route-leak evidence |
| PeeringDB | `217162` targets | `missing` | auxiliary context |
| Known events | `217162` targets | `present_unverified_schema` | requires time/object matching |
| Internal visibility | `217165` incidents | `ready_aligned` | diagnostic only |
| Public monitor context | `217165` incidents | `ready_aligned` | trigger/context only |

## 8. Recommendation

Recommended next step:

```text
P0b historical VRP/RPKI cache materialization for 2024-04-16
```

Reason:

- incident lookup keys are already sufficient;
- RPKI/VRP has the best cost-to-signal ratio;
- R-2A currently produces many unavailable/stale verdicts because aligned cache is missing;
- VRP cache can reduce `external_evidence_unavailable` without weakening hard safety rules.

Do not enter the learning layer yet. There are still no verifier-supported training targets.

Do not return to legacy detector-score optimization unless a detector field directly blocks verifier lookup keys or a future R-3 baseline.

## 9. Output Files

Generated under `outputs/r2b0_evidence_readiness_audit_v01/`:

- `r2b_lookup_key_completeness.csv`
- `r2b_lookup_key_completeness_summary.json`
- `r2b_prefix_origin_targets.parquet`
- `r2b_prefix_origin_targets.csv`
- `r2b_prefix_origin_target_summary.json`
- `r2b_path_triplet_targets.parquet`
- `r2b_path_triplet_targets.csv`
- `r2b_path_triplet_target_summary.json`
- `r2b_cache_inventory.csv`
- `r2b_cache_inventory.json`
- `r2b_evidence_readiness_matrix.csv`
- `r2b_evidence_readiness_matrix.md`
- `r2b_minimal_cache_plan.md`
- `r2b_minimal_cache_plan.csv`
- `r2b0_report.md`
- `r2b0_summary.json`

These output files are audit artifacts and are not committed to git.
