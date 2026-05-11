# S3-C2 Gate Evidence Ablation

Last updated: 2026-05-10

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

The current stage is scaffold + local smoke only. It should not be reported as the formal fixed S2 6h S3-C2 experiment until S3-C1b full returns and S3-C2 is rerun on `s2a_expanded_v01_pilot_6h_april16`.

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

Formal fixed-run output directory, not produced yet:
- `outputs/s3c2_gate_evidence_ablation_v01/`

Outputs:
- `s3c2_summary.json`
- `s3c2_variant_comparison.csv`
- `s3c2_pattern_A_impact.csv`
- `s3c2_pattern_B_protection.csv`
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

## 6. Fixed S2 Rerun Plan

S3-C1b full has completed and has been pulled back:

```text
outputs/s3c1b_penalty_calibration_v01/
```

It recommends `strategy_medium_gate_only` on fixed S2 full:
- recommended bucket_changed_rows `5183`
- recommended pattern_A_gate_evidence_rows `6870696`
- recommended pattern_B adjusted/bucket changed rows `0`

Then rerun S3-C2 on fixed S2:

```powershell
python scripts\run_s3c2_gate_evidence_ablation.py ^
  --run-id s2a_expanded_v01_pilot_6h_april16 ^
  --output-dir outputs\s3c2_gate_evidence_ablation_v01 ^
  --s3c1b-output-dir outputs\s3c1b_penalty_calibration_v01 ^
  --full-run
```

Do not rerun S3-C1b. The next S2-side action is S3-C2 fixed-run gate evidence ablation.

## 7. Current Judgment

S3-C2 scaffold is ready and smoke-tested. It keeps the layered story intact:

```text
candidate stays broad
score remains broad/white-box
gate consumes plausibility as evidence
incident priority / verification decide analyst workload
```

Next action:
- rerun S3-C2 fixed S2 using `outputs/s3c1b_penalty_calibration_v01/`,
- keep S3-C2 as offline gate evidence ablation,
- do not overwrite score/gate/final/incidents.
