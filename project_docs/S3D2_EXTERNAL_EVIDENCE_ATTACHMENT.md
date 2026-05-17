# S3-D2 External Evidence Attachment

Last updated: 2026-05-14

Phase R update, 2026-05-17:

S3-D2 is now verifier evidence-layer groundwork. Its result is not a final verification result. The absence of aligned RPKI / AS relationship evidence is not a system failure; it is an evidence-readiness finding that motivates Phase R verifier redesign.

## 1. Scope

S3-D2 attaches first-pass external/provenance evidence fields to the S3-D incident-level verification queue.

Boundary:
- Do not rerun raw/events/baseline/candidate/score/gate/augment/final.
- Do not overwrite score/gate/final/incident outputs.
- Do not modify P1/P2/P3.
- Do not treat RPKI invalid as confirmed attack.
- Do not treat RPKI valid as confirmed benign.
- Do not treat P3/low/background as confirmed normal.
- Do not train a learning model.
- Do not claim final truth judgment.

S3-D2 is evidence attachment, not verification completion.

## 2. Inputs

Fixed run:

```text
s2a_expanded_v01_pilot_6h_april16
```

Primary inputs:
- `outputs/s3d_verification_queue_schema_v01/s3d_incident_verification_queue.parquet`
- `outputs/s3d_verification_queue_schema_v01/s3d_feature_schema.json`
- `outputs/s3d_verification_queue_schema_v01/s3d_summary.json`
- `data/runs/s2a_expanded_v01_pilot_6h_april16/incidents/incident_membership.parquet`
- `outputs/s3a2_incident_priority_calibration_v01/s3a2_calibrated_incident_tickets.parquet`

Optional inputs used:
- `data/caida/as-relationships/serial-2/20170701.as-rel2.txt`
- `data/known_events/known_event_candidates_v05.json`

Important provenance constraints:
- No historical RPKI cache was provided for `2024-04-16`; all RPKI evidence is `unavailable`.
- The available CAIDA AS relationship snapshot is `20170701`, which is stale for the 2024 run. It is diagnostic only and cannot create strong evidence.
- Known-event inventory is mostly historical; time-aligned known-event match is expected to be zero for this 2024 window.

## 3. Implementation

New script:
- `scripts/run_s3d2_external_evidence_attachment.py`

Output directory:
- `outputs/s3d2_external_evidence_attachment_v01/`

Outputs:
- `s3d2_summary.json`
- `s3d2_incident_evidence_table.parquet`
- `s3d2_incident_evidence_table.csv`
- `s3d2_queue_evidence_distribution.csv`
- `s3d2_rpki_evidence_summary.csv`
- `s3d2_path_relation_evidence_summary.csv`
- `s3d2_history_collector_evidence_summary.csv`
- `s3d2_top_high_confidence_with_evidence.csv`
- `s3d2_gate_weak_cases_with_evidence.csv`
- `s3d2_patternB_with_path_evidence.csv`
- `s3d2_route_leak_with_relation_evidence.csv`
- `s3d2_background_like_with_evidence.csv`
- `s3d2_known_event_matching.csv`
- `s3d2_report.md`

## 4. Evidence Fields

RPKI evidence:
- `rpki_status`
- `rpki_is_valid`
- `rpki_is_invalid`
- `rpki_is_unknown`
- `rpki_evidence_strength`
- `rpki_evidence_note`

Path relation evidence:
- `rel_seq_available`
- `rel_unknown_cnt`
- `rel_unknown_ratio`
- `rel_has_unknown`
- `path_relation_risk_score`
- `possible_valley_free_violation`
- `path_relation_evidence_strength`
- `path_relation_note`
- `as_rel_snapshot_stale`

History / collector evidence:
- `collector_support_score`
- `single_collector_incident_flag`
- `temporal_support_score`
- `recurrence_support_score`
- `history_support_score`
- `evidence_density_score`

Known-event evidence:
- `known_event_match_status`
- `known_event_match_strength`
- `known_event_id`
- `known_event_note`

Composite evidence:
- `rpki_score_component`
- `path_relation_score_component`
- `history_collector_score_component`
- `known_event_score_component`
- `verification_evidence_score`
- `verification_evidence_bucket`
- `verification_status_candidate`
- `verification_reason_v01`
- `evidence_source_flags`

## 5. Full Run Result

Command:

```powershell
python scripts\run_s3d2_external_evidence_attachment.py ^
  --run-id s2a_expanded_v01_pilot_6h_april16 ^
  --output-dir outputs\s3d2_external_evidence_attachment_v01 ^
  --s3d-output-dir outputs\s3d_verification_queue_schema_v01 ^
  --as-rel-file data\caida\as-relationships\serial-2\20170701.as-rel2.txt ^
  --known-event-file data\known_events\known_event_candidates_v05.json ^
  --full-run
```

Result:
- total incidents: `217165`
- evidence buckets: weak `201329`, medium `15836`, strong `0`
- RPKI status: unavailable `217165`
- path relation evidence: weak_stale_snapshot `217165`
- time-aligned known-event matches: `0`
- out-of-window known-event overlaps: `5167`
- high_confidence_candidate with strong evidence: `0`
- gate_weak_case with strong evidence: `0`
- gate_weak_case evidence insufficient: `7182`
- patternB with path evidence entry: `49852`
- route_leak relation pending: `364`
- background_like evidence supported: `1189`
- external evidence unavailable count: `217165`

Queue/evidence distribution:

| queue | weak | medium |
| --- | ---: | ---: |
| low_priority_background | 157136 | 215 |
| patternB_path_abnormal_verification | 35050 | 14802 |
| gate_evidence_weak_case | 7182 | 10 |
| high_confidence_candidate | 422 | 794 |
| background_like_review | 1175 | 15 |
| route_leak_like_review | 364 | 0 |

## 6. Interpretation

S3-D2 successfully attaches evidence fields and makes the evidence gaps explicit.

Current result should be read as:
- history/collector evidence exists and can rank queues,
- RPKI evidence is unavailable because no historical cache was supplied,
- AS relationship evidence is stale and diagnostic only,
- known-event matching has zero time-aligned matches, with out-of-window overlaps reported separately,
- no incident is confirmed attack or confirmed benign.

S3-D2 prepares the schema and provenance for later verification. It does not complete external validation.

## 7. Next Steps

Recommended next actions:
- Use S3-D2B to align evidence sources and generate concrete prefix-origin/path lookup targets.
- Evidence cache completion: add time-aligned 2024 RPKI/ROA or IRR cache, add a 2024-near CAIDA AS relationship snapshot, and rerun S3-D2.
- Phase R verifier redesign: use S3-D2 fields as inputs to the evidence state machine and legality-first verifier.
- Run S3-C3/R-2 route-leak triplet legality for `route_leak_like_review` and selected `patternB_path_abnormal_verification`.
- Run S3-D3/S4 only after stronger evidence and Phase R verdict semantics are defined.

## 8. S3-D2B Evidence Alignment Follow-Up

S3-D2B has now been added as the alignment layer between S3-D2 and any future stronger evidence rerun.

New assets:
- `scripts/run_s3d2b_evidence_alignment.py`
- `project_docs/S3D2B_EVIDENCE_ALIGNMENT.md`
- `outputs/s3d2b_evidence_alignment_v01/`

Full-run alignment result:
- incidents inspected: `217165`
- valid prefix-origin lookup targets: `40665`
- path relation targets: `168889`
- RPKI aligned cache available: `false`
- AS relationship aligned snapshot available: `false`
- known-event time-aligned overlaps: `0`
- known-event out-of-window asset overlaps: `6`
- S3-D2 aligned rerun ready: `false`

The concrete rerun requirements are recorded in:
- `outputs/s3d2b_evidence_alignment_v01/s3d2b_required_cache_schema.json`
- `outputs/s3d2b_evidence_alignment_v01/s3d2b_rerun_manifest.json`
