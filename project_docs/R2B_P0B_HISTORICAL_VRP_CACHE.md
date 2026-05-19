# R-2B-P0b Historical VRP/RPKI Cache

Last updated: 2026-05-19

Status: historical VRP cache materialized and full prefix-origin lookup completed.

## 1. Goal

R-2B-P0b materializes the first aligned external evidence cache for Phase R:

```text
2024-04-16 historical VRP/RPKI archive
  -> normalized local VRP cache
  -> offline prefix-origin origin-validation lookup
  -> RPKI evidence status distribution
```

This stage does not generate verifier verdicts. It only creates an external evidence cache and performs dry lookup against R-2B-0 prefix-origin targets.

## 2. Source

Source used:

- RIPE NCC RPKI repository archive: `https://ftp.ripe.net/rpki/`
- Dataset description: `https://github.com/RIPE-NCC/internet-dataset-descriptions/blob/main/rpki-repo-archive.md`

Downloaded TAL files:

- `https://ftp.ripe.net/rpki/afrinic.tal/2024/04/16/roas.csv.xz`
- `https://ftp.ripe.net/rpki/apnic.tal/2024/04/16/roas.csv.xz`
- `https://ftp.ripe.net/rpki/arin.tal/2024/04/16/roas.csv.xz`
- `https://ftp.ripe.net/rpki/lacnic.tal/2024/04/16/roas.csv.xz`
- `https://ftp.ripe.net/rpki/ripencc.tal/2024/04/16/roas.csv.xz`

The source CSV schema is:

```text
URI,ASN,IP Prefix,Max Length,Not Before,Not After
```

## 3. Outputs

Local evidence cache:

- `data/evidence/rpki/vrp_2024-04-16.parquet`
- `data/evidence/rpki/vrp_2024-04-16.csv`
- `data/evidence/rpki/vrp_2024-04-16.metadata.json`

Audit outputs:

- `outputs/r2b_p0b_vrp_materialization_v01/r2b_p0b_summary.json`
- `outputs/r2b_p0b_vrp_materialization_v01/r2b_p0b_report.md`
- `outputs/r2b_p0b_vrp_materialization_v01/r2b_prefix_origin_rpki_lookup.parquet`
- `outputs/r2b_p0b_vrp_materialization_v01/r2b_prefix_origin_rpki_lookup.csv`
- `outputs/r2b_p0b_vrp_materialization_v01/r2b_rpki_status_distribution.csv`
- `outputs/r2b_p0b_vrp_materialization_v01/r2b_invalid_examples.csv`
- `outputs/r2b_p0b_vrp_materialization_v01/r2b_vrp_cache_metadata.json`

Large cache and lookup files are local artifacts. They are not committed to git.

Committed small provenance file:

- `data/evidence/rpki/vrp_2024-04-16.metadata.json`

`.gitignore` excludes generated `data/evidence/**/*.csv`, `data/evidence/**/*.parquet`, and `data/evidence/**/*.xz`.

## 4. Normalized VRP Schema

Normalized fields:

- `vrp_id`
- `prefix`
- `prefix_len`
- `max_length`
- `asn`
- `ta`
- `source`
- `source_url`
- `snapshot_ts`
- `snapshot_date`
- `downloaded_at`
- `aligned_to_run_date`
- `alignment_delta_hours`
- `raw_record_hash`
- `provenance_json`

Full cache records:

- `530187`

Alignment:

- `snapshot_date=2024-04-16`
- `aligned_to_run_date=true`
- `usable_for_r2b_verdict=true`

## 5. Lookup Logic

For each R-2B-0 prefix-origin target:

- `lookup_prefix`
- `lookup_origin_as`

RPKI status is assigned as:

- `valid`: a covering VRP authorizes the origin ASN and target prefix length is within `max_length`.
- `invalid_asn`: a covering VRP exists, but no covering VRP authorizes the target origin ASN.
- `invalid_length`: a covering VRP authorizes the origin ASN, but the target prefix is more specific than `max_length`.
- `unknown`: no covering VRP exists.
- `unavailable`: no usable VRP cache is available.

Mapping to evidence state:

- `valid` -> `aligned_medium`
- `invalid_asn` -> `aligned_medium`
- `invalid_length` -> `aligned_medium`
- `unknown` -> `aligned_weak`
- `unavailable` -> `unavailable`

## 6. Full Lookup Result

Fixed run:

- `s2a_expanded_v01_pilot_6h_april16`

Full lookup:

- total targets: `217165`
- lookup eligible targets: `217162`
- unavailable: `0`
- not time aligned: `0`
- safety violations: `0`

RPKI status distribution:

| RPKI status | Count | Share |
|---|---:|---:|
| valid | `122280` | `0.563082` |
| unknown | `94202` | `0.433787` |
| invalid_asn | `397` | `0.001828` |
| invalid_length | `283` | `0.001303` |

Evidence state distribution:

- `aligned_medium=122960`
- `aligned_weak=94202`

Incident-level counts:

- incidents with valid: `122280`
- incidents with invalid: `680`
- incidents with unknown: `94202`
- incidents with unavailable: `0`

## 7. Hard Safety Rules

R-2B-P0b keeps Phase R safety boundaries:

- RPKI valid is not benign.
- RPKI invalid is not confirmed attack.
- RPKI unknown is not normal.
- Unavailable is not benign.
- This stage does not generate `strongly_supported_suspicious`.
- This stage does not modify R-2A verifier verdicts.
- This stage does not modify legacy S3 outputs.
- This stage does not train a learning model.

## 8. Interpretation

R-2B-P0b resolves the main R-2B-0 blocker for origin authorization evidence:

```text
RPKI/VRP cache: missing
  -> aligned historical VRP cache available for 2024-04-16
```

This does not verify attacks. It makes one aligned external evidence source available to the verifier.

The immediate next step is:

```text
R-2B smoke with aligned VRP evidence
```

R-2C can begin after that smoke confirms that VRP evidence changes only evidence states and confidence/provenance, not hard safety rules.

Learning layer remains blocked until verifier-supported incident targets exist.

## 9. Commands

Compile:

```powershell
python -m py_compile scripts/run_r2b_p0b_materialize_vrp_cache.py
```

Sample:

```powershell
python scripts/run_r2b_p0b_materialize_vrp_cache.py ^
  --run-id s2a_expanded_v01_pilot_6h_april16 ^
  --run-date 2024-04-16 ^
  --targets-file outputs/r2b0_evidence_readiness_audit_v01/r2b_prefix_origin_targets.parquet ^
  --output-dir outputs/r2b_p0b_vrp_materialization_v01 ^
  --evidence-output-dir data/evidence/rpki ^
  --download-mode auto ^
  --sample-rows 50000
```

Full:

```powershell
python scripts/run_r2b_p0b_materialize_vrp_cache.py ^
  --run-id s2a_expanded_v01_pilot_6h_april16 ^
  --run-date 2024-04-16 ^
  --targets-file outputs/r2b0_evidence_readiness_audit_v01/r2b_prefix_origin_targets.parquet ^
  --output-dir outputs/r2b_p0b_vrp_materialization_v01 ^
  --evidence-output-dir data/evidence/rpki ^
  --download-mode auto ^
  --full-run
```
