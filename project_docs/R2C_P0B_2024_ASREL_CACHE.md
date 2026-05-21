# R-2C-P0b 2024-near CAIDA AS Relationship Cache

Status: fixed S2 cache materialization completed.

Run id: `s2a_expanded_v01_pilot_6h_april16`

Run date: `2024-04-16`

Snapshot date: `2024-04-01`

Output directory: `outputs/r2c_p0b_asrel_materialization_v01/`

Evidence cache directory: `data/evidence/as_relationships/`

## 1. Why This Stage

R-2C-0 showed that path lookup keys are nearly complete, but aligned path evidence was missing. Therefore R-2C-P0b directly materializes a 2024-near CAIDA AS Relationships serial-2 cache instead of repeating readiness audit.

This stage does not implement route-leak verification. It only creates a versioned local evidence cache and checks that R-2C-0 AS-pair targets can be joined against it.

## 2. Data Source

Source:

```text
https://data.caida.org/datasets/as-relationships/serial-2/20240401.as-rel2.txt.bz2
```

Downloaded file:

```text
data/caida/as-relationships/serial-2/20240401.as-rel2.txt.bz2
```

The download succeeded without manual CAIDA form handling in this run. The raw file remains local and is ignored by Git.

## 3. Snapshot Alignment

| Field | Value |
| --- | --- |
| snapshot_date | `2024-04-01` |
| run_date | `2024-04-16` |
| alignment_delta_days | `15` |
| aligned_to_run_date | `true` |
| is_future_snapshot | `false` |
| usable_for_r2c | `true` |
| usable_evidence_strength | `aligned_medium` |

The snapshot is before the run date and close enough for R-2C path evidence smoke. It is still inferred evidence, not path truth.

## 4. Normalized Schema

Standard cache outputs:

- `data/evidence/as_relationships/as_rel_2024-04-01.parquet`
- `data/evidence/as_relationships/as_rel_2024-04-01.csv`
- `data/evidence/as_relationships/as_rel_2024-04-01.metadata.json`

Core fields include:

- `rel_id`
- `raw_rel_id`
- `as1`
- `as2`
- `rel_raw`
- `rel_type`
- `rel_direction_note`
- `as_left`
- `as_right`
- `relation_from_left_to_right`
- `relation_confidence`
- `source_snapshot_date`
- `snapshot_date`
- `run_date`
- `aligned_to_run_date`
- `alignment_delta_days`
- `is_future_snapshot`
- `raw_record_hash`
- `provenance_json`

The cache stores a bidirectional lookup view. CAIDA `-1` orientation is preserved as raw direction; it is not re-coded into valley-free semantics in this stage.

## 5. Cache Size

| Metric | Count |
| --- | ---: |
| raw AS-rel records | 571330 |
| directed lookup records | 1142660 |
| comment lines | 180 |
| parse warnings | 0 |

Large CSV/parquet files are local artifacts and are not committed.

## 6. Relation Lookup Smoke

R-2C-0 AS-pair targets were joined against the normalized AS-rel cache.

| Metric | Value |
| --- | ---: |
| AS-pair target rows | 216922 |
| unique AS-pairs | 61997 |
| matched unique AS-pairs | 56971 |
| unmatched unique AS-pairs | 5026 |
| match rate | 0.918932 |
| unknown relation rate | 0.081068 |

Relation type distribution:

| rel_type | Count |
| --- | ---: |
| p2c_or_c2p_raw | 33144 |
| p2p | 23827 |
| unknown | 5026 |

This is a lookup smoke only. It does not classify route leaks and does not change verifier verdicts.

## 7. Safety Guardrails

- Inferred AS relationships are not ground truth.
- AS-rel violation is not confirmed route leak.
- AS-rel path legality is not benign.
- Stale or future snapshots cannot be used as strong evidence.
- CAIDA `-1` direction must be interpreted with CAIDA documentation before any valley-free logic is implemented.
- This stage produces path evidence cache readiness, not route-leak verdicts.

## 8. Current Limits

R-2C-P0b only materializes CAIDA AS relationship evidence. It does not attach:

- ASPA;
- BGP Roles / OTC;
- PeeringDB;
- IRR;
- data-plane evidence.

It also does not run poisoning/evasion benchmark or train a learning layer.

## 9. Next Step

Proceed to R-2C-P1 path relation lookup smoke / path-legality smoke. ASPA and BGP Roles / OTC feasibility checks should follow. Learning remains design-only until verifier-supported path/origin targets and robustness scenarios are ready.
