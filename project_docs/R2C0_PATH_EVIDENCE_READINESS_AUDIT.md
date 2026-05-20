# R-2C-0 Path Evidence Readiness Audit

Status: fixed S2 full audit completed.

Run id: `s2a_expanded_v01_pilot_6h_april16`

Run date: `2024-04-16`

Output directory: `outputs/r2c0_path_evidence_readiness_audit_v01/`

## 1. Goal

R-2C-0 is the readiness gate before the path evidence branch. R-2B attached aligned VRP/RPKI origin evidence, but origin authorization does not verify AS-path legality, route leaks, path manipulation, or valley-free/ASPA-related behavior.

This stage checks whether fixed S2 incidents have usable path/triplet/AS-pair lookup keys and whether local path-evidence caches are ready. It does not download evidence, does not modify verifier verdicts, does not train models, and does not implement a route-leak verifier.

## 2. Why R-2B Is Not Enough

RPKI/VRP answers prefix-origin authorization only. It cannot validate:

- provider/customer/peer transition legality;
- AS triplet legality;
- ASPA path authorization;
- BGP Roles / OTC route-leak semantics;
- route-leak or path-manipulation evidence for patternB/path-abnormal incidents.

Therefore a CCF-A-level verifier needs a path evidence branch after origin evidence is aligned.

## 3. Path-Key Audit Result

Full audit scope: `217165` incidents.

| Metric | Count | Rate |
| --- | ---: | ---: |
| complete path-key incidents | 217162 | 0.999986 |
| triplet-capable incidents | 217162 | 0.999986 |
| AS-pair targets | 216922 | - |
| triplet targets | 205067 | - |
| full-path targets | 217162 | - |

The incident and membership artifacts are ready enough for path evidence lookup. Missing or partial path keys remain explicit target-quality states; they are not interpreted as benign.

## 4. Path Evidence Cache Inventory

| Evidence cache | Readiness | Interpretation |
| --- | --- | --- |
| legacy 2017 CAIDA AS relationship | `ready_stale` | stale diagnostic only for the 2024 run |
| 2024-near AS relationship | `missing` | main blocker for R-2C path materialization |
| ASPA | `missing` | feasibility/schema check needed |
| BGP Roles / OTC | `missing` | feasibility/schema check needed |
| PeeringDB | `missing` | context only even when present |
| known-event path context | `present_unverified_schema` | diagnostic only until time/object aligned |

The 2017 CAIDA AS-rel file must not be treated as aligned or strong evidence. PeeringDB cannot be strong path evidence; it is context/diagnostic only.

## 5. Readiness Matrix Summary

R-2C-0 concludes:

- `caida_as_relationship`: usable only as stale diagnostic smoke.
- `as_relationship_2024_near`: missing and should be the P0b materialization target.
- `aspa`: missing; useful as a P1 feasibility check.
- `bgp_roles_otc`: missing; useful as a P1 feasibility check.
- `peeringdb_context`: context/diagnostic only.
- `known_event_path_context`: present but schema/time alignment is unverified.
- `internal_path_novelty` and `public_monitor_path_context`: monitor-side context, not independent truth.

## 6. Minimal Path Evidence Plan

Recommended order:

1. R-2C-P0b: materialize a 2024-near AS relationship cache.
2. R-2C-P1a: ASPA schema readiness / feasibility check.
3. R-2C-P1b: BGP Roles / OTC evidence availability check.
4. R-2C-P2: PeeringDB and path-aware known-event context inventory.
5. R-2C verifier smoke: only after aligned or explicitly scoped path evidence is available.

Forbidden shortcuts:

- Do not use 2017 CAIDA AS-rel as aligned strong evidence.
- Do not call valley-free or relationship violations confirmed route leaks.
- Do not treat missing path evidence as benign.
- Do not treat public monitor path context as independent truth.

## 7. Relationship to CCF-A Target

The CCF-A target requires multi-attack-family verification, not only origin validation. R-2C-0 shows that the data plane for path lookup is largely ready, but the evidence-cache layer is not. This is exactly the verifier-centric gap: evidence availability, freshness, provenance, and safe fallback must be explicit.

## 8. Current Limits

R-2C-0 is not a route-leak detector and not a path-legality verifier. It does not:

- download AS relationship, ASPA, BGP Roles, OTC, PeeringDB, or data-plane evidence;
- modify R-2B verifier verdicts;
- train a learning layer;
- run poisoning/evasion benchmark;
- produce confirmed route-leak or path-manipulation labels.

## 9. Next Step

Proceed to R-2C-P0b 2024-near AS relationship cache materialization. ASPA and BGP Roles / OTC feasibility checks can follow. L1 learning can continue as design only; formal training remains blocked until verifier-supported path/origin targets and robustness settings exist.
