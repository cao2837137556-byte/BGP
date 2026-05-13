# S3-C2 Gate Evidence Ablation

Last updated: 2026-05-13

## 1. Scope

S3-C2 is an offline scaffold for using S3-C1/S3-C1b path plausibility as gate-layer evidence.

Boundary:
- Do not rerun raw/events/baseline/candidate.
- Do not overwrite `scored_candidates.parquet`.
- Do not overwrite `gated_candidates.parquet`.
- Do not overwrite `final_alerts.parquet`.
- Do not overwrite incident tickets.
- Do not change mainline default behavior.
- Do not treat P1/P2 as confirmed anomalies.
- Do not treat P3/low as confirmed normal.
- Do not treat S3-C1b 60min smoke as a fixed S2 full conclusion.
- Treat all changed labels/priorities as simulated S3-C2 fields.
- P1->P2 transfer is not workload reduction; always report P1+P2 total burden.
- If known-event matched rows are zero, do not claim there is no regression risk.

Fixed S2 full has completed on `s2a_expanded_v01_pilot_6h_april16`. It should be reported as an evidence-routing result, not as workload reduction: the recommended variant adds gate evidence but does not change final labels or incident priorities.

## 2. Motivation

S3-C1 showed that visibility-aware path plausibility can hit the dominant S3-B noise pattern:

```text
pattern_A =
single_collector_visibility
  + structural_novelty_score
  + unseen_path_for_prefix_origin
  + unusually_short_duration_for_prefix
```

But S3-C1 default score penalty was too aggressive on fixed S2 full. S3-C1b therefore calibrates softer penalty strategies. S3-C2 takes the more conservative direction: use plausibility as gate evidence before replacing score behavior.

## 3. Implementation

New script:
- `scripts/run_s3c2_gate_evidence_ablation.py`

Smoke output directory:
- `outputs/s3c2_gate_evidence_ablation_smoke_s1a/`

Formal fixed-run output directory:
- `outputs/s3c2_gate_evidence_ablation_v01/`

Outputs:
- `s3c2_summary.json`
- `s3c2_variant_comparison.csv`
- `s3c2_event_label_delta.csv`
- `s3c2_incident_priority_delta.csv`
- `s3c2_p1_p2_total_burden.csv`
- `s3c2_pattern_A_impact.csv`
- `s3c2_pattern_B_protection.csv`
- `s3c2_review_subtype_distribution.csv`
- `s3c2_p1_p2_impact.csv`
- `s3c2_known_event_regression_check.csv`
- `s3c2_top_adjusted_cases.csv`
- `s3c2_recommended_variant.json`
- `s3c2_report.md`

The script reuses S3-C1b's `build_plausibility_frame`, so feature construction remains aligned with S3-C1/S3-C1b:
- `path_plausibility_score`
- `plausibility_bucket`
- `pattern_A_flag`
- `pattern_B_flag`
- visibility / temporal / history / path-length / relation support fields

## 4. Variants

| variant | intent | score changed | final simulated |
| --- | --- | --- | --- |
| `variant_default` | original labels baseline | no | no |
| `variant_plausibility_gate_soft` | low-plausibility pattern_A needs extra evidence before high | no | high can move to needs only if unsupported |
| `variant_plausibility_gate_medium_review` | low/medium pattern_A require extra evidence | no | unsupported high moves to needs |
| `variant_medium_gate_only` | S3-C1b smoke fallback: low requires evidence; medium is evidence-only | no | usually no label movement in smoke |
| `variant_patternB_protect` | pattern_B is verification-only, never downgraded by plausibility alone | no | protects pattern_B |
| `variant_strict_extra_evidence` | upper-bound strict ablation | no | not recommendable |

Extra evidence is met if any of the following is true:
- `certainty_score >= 65`
- `evidence_support_score >= 65`
- `collector_count > 1`
- `temporal_confirmation_count > 0`
- `path_seen_before_flag = true`

## 5. Local Smoke

Command:

```powershell
cd D:\study\paper\worktrees\bgp-platform-exp-mainline

python scripts\run_s3c2_gate_evidence_ablation.py ^
  --run-id s1a_expanded_v02_pilot_60m_april16 ^
  --output-dir outputs\s3c2_gate_evidence_ablation_smoke_s1a ^
  --sample-rows 200000
```

Result:
- `loaded_rows=200000`
- `status=completed_with_warnings`
- warnings are expected:
  - S1A has no incident membership.
  - S3-C1b fixed S2 full output is still pending.
- `recommended_variant=variant_medium_gate_only`
- recommended `gate_evidence_rows=122956`
- recommended `final_label_changed_rows=0`
- recommended `pattern_A_gate_evidence_rows=122956`
- recommended `pattern_B_label_changed_rows=0`
- known-event inventory is readable, but matched rows are `0`; this must not be interpreted as no regression risk.

Interpretation:
- Smoke validates the scaffold and fallback behavior.
- Smoke does not prove S3-C2 fixed-run effectiveness.
- In this smoke, S3-C2 mainly opens a gate evidence channel rather than moving labels.

## 6. Fixed S2 Full Results

S3-C1b full completed and was used as input:

```text
outputs/s3c1b_penalty_calibration_v01/
```

S3-C1b recommends `strategy_medium_gate_only` on fixed S2 full:
- recommended bucket_changed_rows `5183`
- recommended pattern_A_gate_evidence_rows `6870696`
- recommended pattern_B adjusted/bucket changed rows `0`

S3-C2 fixed S2 full output:
- `outputs/s3c2_gate_evidence_ablation_v01/`

Run summary:
- `run_id=s2a_expanded_v01_pilot_6h_april16`
- `input_rows=10236431`
- `loaded_rows=10236431`
- `status=completed`
- `warnings=[]`
- `recommended_variant=variant_medium_gate_only`
- S3-C1b full recommendation was available and matched the current run.

Recommended `variant_medium_gate_only`:
- final labels unchanged: high `639548 -> 639548`, needs `4839755 -> 4839755`, low `4757128 -> 4757128`
- `final_label_changed_rows=0`
- `gate_evidence_rows=6885990`
- `extra_evidence_required_rows=15294`
- `extra_evidence_missing_rows=2077`
- `pattern_A_rows=7440623`
- `pattern_A_gate_evidence_rows=6885990`
- `pattern_A_control_rate=0.9254587955874125`
- `pattern_A_label_changed_rows=0`
- `pattern_B_rows=659862`
- `pattern_B_gate_evidence_rows=0`
- `pattern_B_label_changed_rows=0`
- P1/P2 joined rows `4426436`
- P1/P2 affected rows `3510753`
- touched P1/P2 incidents `32469` (`20242` P1, `12227` P2)
- P1/P2 ticket burden unchanged: `55083 -> 55083`
- P1/P2 member burden unchanged: `4426436.0 -> 4426436.0`
- P1->P2 transfer tickets `0`

Pattern detail:
- pattern_A baseline labels: high `553974`, needs `4326074`, low `2560575`
- pattern_A plausibility: low `19504`, medium `7420471`, high `648`
- pattern_B baseline labels: high `598021`, needs `61841`, low `0`
- pattern_B plausibility: low `4789`, medium `655073`, high `0`

Review subtype evidence under the recommended variant:
- `background_fanout_review`: `1360331` needs rows, `1130010` gate evidence rows
- `low_visibility_review`: `3410106` needs rows, `3196041` gate evidence rows
- `pattern_B_verification_review`: `61841` needs rows, `0` gate evidence rows in the recommended variant
- `route_leak_like_review`: `3952` needs rows, `0` gate evidence rows

Known-event regression:
- inventory readable: `data/known_events/known_event_candidates_v05.json`
- known events: `7`
- matched events/rows: `0 / 0`
- This does not prove there is no regression risk.

## 7. Current Judgment

S3-C2 fixed S2 full is completed and keeps the layered story intact:

```text
candidate stays broad
score remains broad/white-box
gate consumes plausibility as evidence
incident priority / verification decide analyst workload
```

Judgment:
- S3-C2 is not just high -> needs transfer: there is no final label movement.
- It does not inflate `needs_review`.
- It does not move P1 into P2 and does not reduce P1+P2 burden by itself.
- It successfully marks the dominant pattern_A as gate evidence while protecting pattern_B from plausibility-only downgrade.
- The result should feed S3-D verification queue construction or S3-C3 route-leak triplet legality, not be treated as a standalone priority reduction.

Next action:
- keep S3-C2 as offline gate evidence output,
- do not overwrite score/gate/final/incidents,
- use `gate_evidence_rows` and pattern_A/pattern_B flags to design incident-level verification in S3-D,
- consider S3-C3 route-leak triplet legality as a separate route-leak-specific line.
