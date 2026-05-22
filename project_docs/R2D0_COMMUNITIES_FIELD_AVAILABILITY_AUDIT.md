# R-2D-0 Communities / NO_EXPORT Field Availability Audit

Status: fixed S2 full audit completed.

Run id: `s2a_expanded_v01_pilot_6h_april16`

Run date: `2024-04-16`

Output directory: `outputs/r2d0_communities_field_availability_audit_v01/`

## 1. Goal

R-2D-0 audits whether the current fixed S2 data and pipeline retain BGP community attributes, especially well-known communities such as `NO_EXPORT`, `NO_ADVERTISE`, `NO_EXPORT_SUBCONFED`, and `NOPEER`.

This stage is deliberately limited to field availability and pipeline retention. It does not implement a stealth verifier, does not detect a NO_EXPORT attack, does not modify R-1/R-2B/R-2C verifier outputs, does not run poisoning/evasion, and does not train the learning layer.

## 2. Why Communities / NO_EXPORT Matter

R-2B added time-aligned RPKI/VRP origin evidence. R-2C added 2024-near CAIDA AS relationship path evidence and a conservative path-legality verifier smoke. R-2D starts the stealth / monitor-evasion evidence branch.

Communities are relevant because export-control attributes can affect where a route is visible:

- `NO_EXPORT`: should not be advertised outside a confederation boundary.
- `NO_ADVERTISE`: should not be advertised to other BGP peers.
- `NO_EXPORT_SUBCONFED`: should not be advertised to external confederation peers.
- `NOPEER`: requests that the route not be propagated to bilateral peers.

These attributes can help explain low visibility or monitor asymmetry, but only when the raw attribute is preserved and joinable to incidents/components.

## 3. Safety Boundary

- `NO_EXPORT` present is not a confirmed attack.
- `NO_EXPORT` absent is not safe.
- `NO_ADVERTISE`, `NO_EXPORT_SUBCONFED`, or `NOPEER` present is not a stealth attack label.
- Low visibility does not mean `NO_EXPORT`.
- Collector asymmetry does not prove monitor evasion.
- Missing communities are not benign evidence.
- Community evidence must retain provenance and must be joined to incident/member/component keys before any Stage 2 stealth evidence branch.

## 4. Inputs

The audit scanned the fixed run root and the related local-raw collector runs:

- `data/runs/s2a_expanded_v01_pilot_6h_april16/`
- `data/runs/s2a_expanded_v01_pilot_6h_april16__collector_*/collector=*/date=*/updates__*.parquet`

It also checked existing verifier output tables for retention:

- `outputs/r2b_vrp_aware_verifier_smoke_v01/r2b_vrp_incident_verifier_table.parquet`
- `outputs/r2c_p2_path_legality_verifier_smoke_v01/r2c_p2_incident_verifier_smoke_table.parquet`

No new external evidence was downloaded.

## 5. Field Discovery Result

Full audit scanned `893` local files. Community-like fields were found in `864` files.

All discovered community-like fields were in the raw update chunks:

| Layer | Scanned files | Community field present | Columns |
| --- | ---: | --- | --- |
| raw_updates | 864 | true | `communities` |
| rel_annotated | 0 | false | none |
| event_units | 0 | false | none |
| incident_membership | 1 | false | none |
| incident_tickets | 1 | false | none |
| verifier_outputs | 2 | false | none |

The fixed merged run root currently keeps only incident outputs. The raw updates exist in sibling collector-run directories created by the S2-A local raw collection path.

## 6. Parser Result

Full audit parsed the raw `communities` field over `39,039,005` raw update rows.

| Metric | Count |
| --- | ---: |
| sampled/full rows | 39,039,005 |
| non-empty communities rows | 35,657,850 |
| parse-success rows | 27,843,441 |
| parse-failure rows | 7,814,409 |
| NO_EXPORT rows | 223,410 |
| NO_ADVERTISE rows | 1,240 |
| NO_EXPORT_SUBCONFED rows | 0 |
| NOPEER rows | 5,634 |
| large-community-shaped rows | 0 |

Interpretation: direct community attributes are present in raw updates and well-known communities are parsable. This is field availability, not attack detection.

## 7. Pipeline Retention Result

The first concrete retention break is `event_units`.

The raw `communities` field is not retained in:

- `event_units`;
- `incident_membership`;
- `incident_tickets`;
- R-2B verifier output;
- R-2C-P2 verifier-smoke output.

Recommended repair target:

- first repair: `scripts/build_event_units.py`;
- follow-on repair: incident aggregation / membership propagation in `scripts/build_incident_aggregation.py` if event-level communities are retained but not carried into incident/member tables.

R-2D-0 did not modify those scripts. It only identifies the required repair.

## 8. Incident Join Feasibility

Current incident join readiness: `false`.

Reason: the raw update files have `communities`, `prefix`, `as_path`, `collector`, and `ts`, but they do not carry `incident_id` or `event_id`. The incident/member tables carry incident keys but do not carry communities.

Therefore community evidence cannot yet be attached to incident cards or verifier tables without a pipeline retention repair.

## 9. Stealth Evidence Readiness Matrix

| Evidence item | Direct field available | Parsed successfully | Incident join ready | Can support stealth evidence now | Current blocker |
| --- | --- | --- | --- | --- | --- |
| NO_EXPORT | true | true | false | false | community field not retained on incident/member table |
| NO_ADVERTISE | true | true | false | false | community field not retained on incident/member table |
| NO_EXPORT_SUBCONFED | true | false | false | false | parser supported, but no observed rows; community field not retained on incident/member table |
| NOPEER | true | true | false | false | community field not retained on incident/member table |
| provider_specific_communities | true | true | false | false | raw communities are not incident-joined |
| large_communities | false | false | false | false | large communities not incident-ready or not observed |
| low_visibility_symptom | true | true | true | true | monitor-only weak symptom, not independent community evidence |
| collector_asymmetry_symptom | true | true | true | true | monitor-only weak symptom, not independent community evidence |

Allowed claims:

- direct community fields are available in raw updates;
- well-known community values can be parsed from raw updates;
- current incident/verifier tables do not retain communities;
- low visibility and collector asymmetry remain monitor-side symptoms only.

Forbidden claims:

- confirmed NO_EXPORT attack;
- NO_EXPORT absent means safe;
- low visibility means NO_EXPORT;
- community presence alone proves stealth attack.

## 10. Current Limits

- No rel-annotated files were present in the fixed run layout.
- The merged fixed run root currently lacks `events/event_units.parquet`.
- Raw communities are not incident-joined.
- Provider-specific community semantics are not decoded.
- Large communities were not observed by the current parser in this run.
- This audit does not evaluate poisoning/evasion robustness.

## 11. Next Step

R-2D-1 should not start as a stealth verifier yet.

Recommended next step:

1. Repair community retention from raw updates into `event_units`.
2. Propagate event-level community summaries into `incident_membership` and, if useful, incident cards.
3. Re-run R-2D-0 to confirm incident join readiness.
4. Only then start a conservative R-2D-1 community-aware stealth evidence branch.

## 12. Relationship to the Three-stage Architecture

R-2D-0 belongs to Stage 2 evidence readiness, but its immediate repair target is Stage 1 incident construction:

- Stage 1 must preserve raw community attributes and produce incident/member lookup keys.
- Stage 2 can only use communities as evidence after they are retained with provenance and incident/component join keys.
- Stage 3 may later rank community-aware stealth evidence, but it cannot infer missing communities or override verifier safety rules.

## 13. Relationship to the CCF-A Target Line

This audit prevents the project from overclaiming stealth detection from monitor symptoms. It shows that the raw evidence channel exists, quantifies well-known community availability, and exposes the current pipeline retention gap.

For the CCF-A target, this is the right shape: stealth evidence must be explicit, provenance-bearing, and component-aware. It cannot be hidden inside low-visibility detector scores, and it cannot become an attack/benign classifier label.
