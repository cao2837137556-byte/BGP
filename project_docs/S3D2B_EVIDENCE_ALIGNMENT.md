# S3-D2B Evidence Alignment

Last updated: 2026-05-15

## 1. Scope

S3-D2B turns the S3-D2 evidence gap into concrete cache requests and lookup targets.

Boundary:
- Do not rerun raw/events/baseline/candidate/score/gate/augment/final.
- Do not overwrite S3-D or S3-D2 outputs.
- Do not call online RPKI or IRR APIs at scale.
- Do not use current online RPKI status as historical 2024 evidence.
- Do not treat stale AS relationship snapshots as strong evidence.
- Do not treat known-event overlap without time overlap as a match.
- Do not claim external verification is complete.

This is an evidence-alignment planning stage, not a truth-labeling stage.

## 2. Implementation

New script:
- `scripts/run_s3d2b_evidence_alignment.py`

Output directory:
- `outputs/s3d2b_evidence_alignment_v01/`

Primary input:
- `outputs/s3d2_external_evidence_attachment_v01/s3d2_incident_evidence_table.parquet`

Fallback input:
- `outputs/s3d_verification_queue_schema_v01/s3d_incident_verification_queue.parquet`

The script:
- scans local evidence assets under `data/`,
- classifies RPKI/ROA, IRR, AS relationship, and known-event assets,
- checks date alignment against `2024-04-16 00:00:00` to `2024-04-16 06:00:00`,
- emits prefix-origin lookup targets for RPKI/IRR/ROA validation,
- emits dominant path relation targets for time-aligned AS relationship checks,
- emits known-event time-alignment diagnostics,
- emits an S3-D2 rerun manifest with required cache inputs.

## 3. Outputs

Files:
- `s3d2b_summary.json`
- `s3d2b_evidence_source_inventory.csv`
- `s3d2b_prefix_origin_targets.parquet`
- `s3d2b_prefix_origin_targets_top.csv`
- `s3d2b_rpki_lookup_targets.csv`
- `s3d2b_path_relation_targets.csv`
- `s3d2b_known_event_time_alignment.csv`
- `s3d2b_required_cache_schema.json`
- `s3d2b_rerun_manifest.json`
- `s3d2b_report.md`

## 4. Full Run Result

Command:

```powershell
python scripts\run_s3d2b_evidence_alignment.py ^
  --run-id s2a_expanded_v01_pilot_6h_april16 ^
  --output-dir outputs\s3d2b_evidence_alignment_v01 ^
  --s3d2-output-dir outputs\s3d2_external_evidence_attachment_v01 ^
  --s3d-output-dir outputs\s3d_verification_queue_schema_v01 ^
  --full-run
```

Result:
- incidents inspected: `217165`
- valid prefix-origin lookup targets: `40665`
- path relation targets: `168889`
- local evidence sources found: `5`
- source inventory:
  - AS relationship stale snapshot: `1`
  - known-event inventory: `4`
- RPKI aligned cache available: `false`
- AS relationship aligned snapshot available: `false`
- known-event time-aligned overlaps: `0`
- known-event out-of-window asset overlaps: `6`
- S3-D2 aligned rerun ready: `false`

## 5. Required Cache Inputs

S3-D2 cannot produce strong external evidence until these are supplied:

1. Historical RPKI/ROA VRP cache aligned to `2024-04-16`.
   - Accepted formats: parquet/csv/json/jsonl.
   - Required columns: `prefix`, `origin_as` or equivalent, `rpki_status` or equivalent.
   - Accepted status values: `valid`, `invalid_asn`, `invalid_length`, `invalid`, `unknown`, `unavailable`.

2. AS relationship snapshot close to the run date.
   - Current alignment rule: within `45` days of run start.
   - Existing local `20170701.as-rel2.txt` is stale by `2481` days and remains diagnostic only.

Optional but useful:
- IRR route/route6 object cache aligned to `2024-04-16`.
- Modern 2024 known-event/operator report inventory if one exists.

## 6. Interpretation

S3-D2B confirms that the current local workspace is not yet ready for a stronger S3-D2 rerun:
- there is no historical RPKI cache,
- there is no 2024-near AS relationship snapshot,
- the existing known-event inventory is historical and out of the fixed 2024 window.

The positive outcome is operational: the project now has concrete lookup targets and a rerun manifest. Evidence alignment no longer depends on ad hoc manual inspection.

## 7. Next Step

Acquire or build the two required caches in `s3d2b_rerun_manifest.json`, then rerun S3-D2 with:

```powershell
python scripts\run_s3d2_external_evidence_attachment.py ^
  --run-id s2a_expanded_v01_pilot_6h_april16 ^
  --output-dir outputs\s3d2_external_evidence_attachment_aligned_v01 ^
  --s3d-output-dir outputs\s3d_verification_queue_schema_v01 ^
  --rpki-cache <path-to-2024-04-16-rpki-cache.parquet/csv/jsonl> ^
  --as-rel-file <path-to-2024-near-as-rel2.txt> ^
  --known-event-file data\known_events\known_event_candidates_v05.json ^
  --full-run
```

If those caches remain unavailable, the better next experiment is S3-C3 route-leak triplet legality, because it can improve path semantics without claiming external validation.
