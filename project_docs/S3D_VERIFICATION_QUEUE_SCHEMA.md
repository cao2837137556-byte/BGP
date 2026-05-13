# S3-D Incident-Level Verification Queue Schema

Last updated: 2026-05-13

## 1. Scope

S3-D converts S3-A/S3-A2/S3-B/S3-C2 evidence into an incident-level verification queue.

Boundary:
- Do not rerun raw/events/baseline/candidate/score/gate/augment/final.
- Do not overwrite `scored_candidates.parquet`, `gated_candidates.parquet`, `final_alerts.parquet`, or `incident_tickets.parquet`.
- Do not change mainline default behavior.
- Do not treat P1/P2 as confirmed anomalies.
- Do not treat P3/low as confirmed normal.
- Do not claim external verification or precision/recall.
- Treat `weak_label_candidate` as a weak candidate field, not ground truth.

S3-D is a queue/schema stage, not a workload-reduction stage. It reorganizes incident tickets for verification planning.

## 2. Inputs

Fixed run:

```text
s2a_expanded_v01_pilot_6h_april16
```

Primary inputs:
- `data/runs/s2a_expanded_v01_pilot_6h_april16/incidents/incident_tickets.parquet`
- `data/runs/s2a_expanded_v01_pilot_6h_april16/incidents/incident_membership.parquet`
- `outputs/s3a2_incident_priority_calibration_v01/s3a2_calibrated_incident_tickets.parquet`
- `outputs/s3c2_gate_evidence_ablation_v01/`

Important evidence note:
- Local S2 full `scores/gating/final/events/candidates` parquet files are not present.
- S3-D therefore computes incident-level pattern_A / pattern_B evidence from `incident_membership.reason_signature`.
- `pattern_A_gate_evidence_count` is an incident-member fallback for S3-C2 gate evidence: pattern_A member rows excluding pattern_B rows.
- This is suitable for verification queue construction, but it should not be described as exact full-candidate S3-C2 event-level evidence.

## 3. Implementation

New script:
- `scripts/run_s3d_verification_queue_schema.py`

Output directory:
- `outputs/s3d_verification_queue_schema_v01/`

Outputs:
- `s3d_summary.json`
- `s3d_incident_verification_queue.parquet`
- `s3d_incident_verification_queue.csv`
- `s3d_queue_distribution.csv`
- `s3d_top_verification_candidates.csv`
- `s3d_background_like_candidates.csv`
- `s3d_patternA_gate_evidence_incidents.csv`
- `s3d_patternB_verification_incidents.csv`
- `s3d_route_leak_review_incidents.csv`
- `s3d_feature_schema.json`
- `s3d_report.md`

Additional helper output:
- `s3d_queue_priority_crosswalk.csv`

## 4. Queue Schema

`verification_queue` values:
- `high_confidence_candidate`
- `gate_evidence_weak_case`
- `patternB_path_abnormal_verification`
- `background_like_review`
- `route_leak_like_review`
- `unresolved_conflict`
- `low_priority_background`

Queue precedence:

```text
route_leak_like_review
patternB_path_abnormal_verification
high_confidence_candidate
gate_evidence_weak_case
background_like_review
unresolved_conflict
low_priority_background
```

This precedence keeps route leaks and pattern_B in specialist queues, keeps high-confidence non-patternB forged-origin candidates visible, and prevents NA-origin fan-out background incidents from being mistaken for generic unresolved conflicts.

## 5. Full Run Result

Command:

```powershell
python scripts\run_s3d_verification_queue_schema.py ^
  --run-id s2a_expanded_v01_pilot_6h_april16 ^
  --output-dir outputs\s3d_verification_queue_schema_v01 ^
  --s3c2-output-dir outputs\s3c2_gate_evidence_ablation_v01 ^
  --full-run
```

Result:
- total incidents: `217165`
- calibrated P1/P2/P3: `41885 / 13198 / 162082`
- status: `completed_with_warnings`
- warning: S3-D uses `incident_membership.reason_signature` for incident-member pattern evidence because full S3-C2 per-event gate evidence is not present locally.

Queue distribution:

| verification_queue | tickets | members | high | needs | P1 | P2 | P3 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| low_priority_background | 157351 | 720445 | 1429 | 719016 | 130 | 761 | 156460 |
| patternB_path_abnormal_verification | 49852 | 3444514 | 631498 | 2813016 | 40031 | 4480 | 5341 |
| gate_evidence_weak_case | 7192 | 538506 | 1419 | 537087 | 504 | 6688 | 0 |
| high_confidence_candidate | 1216 | 5498 | 5187 | 311 | 1216 | 0 | 0 |
| background_like_review | 1190 | 766386 | 13 | 766373 | 3 | 1184 | 3 |
| route_leak_like_review | 364 | 3954 | 2 | 3952 | 1 | 85 | 278 |

Key counts:
- P1/P2 in `gate_evidence_weak_case`: `7192`
- P1/P2 in `high_confidence_candidate`: `1216`
- pattern_B verification incidents: `49852`
- route-leak-like review incidents: `364`
- pattern_A touched incidents: `174046`
- top-K candidate rows emitted: `250`

## 6. Interpretation

S3-D successfully turns S3-C2 gate evidence into incident-level verification queues.

The result does not reduce final labels or P1/P2 counts:
- final labels are unchanged from S3-C2/mainline.
- calibrated incident priorities are unchanged.
- queue assignment is a new verification planning view.

The main payoff is triage structure:
- `high_confidence_candidate` gives a compact first-pass forged-origin-style validation pool.
- `gate_evidence_weak_case` isolates P1/P2 tickets dominated by low-visibility / short-lived path novelty.
- `patternB_path_abnormal_verification` preserves path-abnormal cases for path/triplet checks instead of downgrading them.
- `background_like_review` captures large fan-out / NA-origin / mostly-needs cases.
- `route_leak_like_review` keeps route leak style events separate from forged-origin-like cases.

## 7. Next Steps

Recommended next actions:
- S3-C3 route-leak triplet legality for `route_leak_like_review` and selected `patternB_path_abnormal_verification`.
- S3-D2 external evidence attachment for top `high_confidence_candidate` and representative `gate_evidence_weak_case`.
- S4 learning-ready high-confidence set only after external verification exists.

Do not use S3-D queue labels as training truth before S3-D2/S4 verification.
