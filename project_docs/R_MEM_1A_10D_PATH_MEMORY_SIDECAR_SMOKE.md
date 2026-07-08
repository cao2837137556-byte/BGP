# R-MEM-1A 10d Path-Memory Sidecar Smoke

Status: implemented and locally smoke-tested on partial source files.

## Goal

R-MEM-1A is the first concrete data step after R-MEM-0. It prepares a canonical
10-day path-memory sidecar so the project can repair foreground poisoning
robustness without guessing from a 6h window.

The immediate purpose is functional closure:

```text
canonical raw update source
  -> path-memory sidecar
  -> maturity buckets
  -> later R-FOREGROUND-4B targeted guard
```

This is not the final paper-scale evaluation. Thirty days remains the likely
formal foreground test window after the 10-day path-memory pipeline is proven.

## Why 10 Days First

Seven days is useful for debugging but too short to be a strong paper-facing
memory window. Thirty days is better for formal claims, but it is larger and
should not be the first time we test the data contract.

R-MEM-1A therefore uses 10 days to validate:

- source download / source discovery;
- canonical collector selection;
- duplicate avoidance;
- origin derivation from AS_PATH;
- path-memory key construction;
- maturity bucket computation;
- sidecar output schema;
- HPC collection and materialization workflow.

If this passes, the same contract can scale to 30 days.

## Canonical Source Scope

Config:

```text
configs/r_mem1a_10d_path_memory_v01.json
```

Canonical collectors:

- `route-views.sg`;
- `rrc00`.

Window:

- target date: `2024-04-16`;
- history start: `2024-04-07`;
- history days: `10`.

Collection granularity:

- `route-views.sg`: 15-minute chunks;
- `rrc00`: 5-minute chunks.

This follows the native public-data organization: RouteViews-style update dumps
are commonly 15-minute windows, while RIPE RIS update dumps are 5-minute
windows. The project can later report both 5m and 15m replay metrics.

## New Artifacts

Scripts:

- `scripts/collect_r_mem1a_bgpstream_sources.py`
- `scripts/materialize_r_mem1a_path_memory_sidecar.py`

HPC wrappers:

- `scripts/hpc/r_mem1a_collect_10d_sources.slurm`
- `scripts/hpc/r_mem1a_materialize_10d_sidecar.slurm`

Expected source run:

```text
data/runs/r_mem1a_10d_sources_v01/
```

Expected sidecar output:

```text
outputs/r_mem_1a_10d_path_memory_sidecar_v01/
```

## Sidecar Schema

The sidecar stores one row per path-memory key:

- `path_memory_key`;
- `prefix`;
- `origin_as`;
- `as_path_signature`;
- `first_seen_ts`;
- `last_seen_ts`;
- `record_count`;
- `recent_record_count`;
- `active_days`;
- `active_micro_batches`;
- `collector_days`;
- `collector_count`;
- `source_file_count`;
- `collector_set`;
- `origin_provenance`;
- `span_sec`;
- `burstiness_score`;
- `maturity_bucket`;
- `sidecar_semantics`.

`origin_as` may be derived from the final AS in the normalized AS_PATH. This is
recorded as `origin_provenance=derived_from_as_path`.

## Maturity Buckets

Current buckets:

- `mature`;
- `recent_only`;
- `short_lived`;
- `sparse`.

Meaning:

```text
mature recurrence can support suppression permission;
recent_only / short_lived / sparse should not be used as strong background
suppression evidence.
```

Forbidden interpretation:

```text
mature == benign
recent_only == attack
```

## Local Smoke Result

Local command:

```text
python scripts/materialize_r_mem1a_path_memory_sidecar.py \
  --config configs/r_mem1a_10d_path_memory_v01.json \
  --output-dir outputs/r_mem_1a_10d_path_memory_sidecar_smoke_v01 \
  --allow-partial-history \
  --max-files 8 \
  --overwrite
```

Result:

- selected source files: `8`;
- input source rows: `400,000`;
- processed source rows: `374,085`;
- sidecar rows: `144,541`;
- maturity buckets: `recent_only=144,541`;
- complete requested history: `false`.

This is expected because the local smoke intentionally used only a few
2024-04-16 files. It proves the sidecar data contract and origin provenance
logic, not 10-day maturity.

## HPC Workflow

Step 1: collect canonical 10-day sources with array jobs:

```text
scripts/hpc/r_mem1a_collect_10d_sources.slurm
```

Step 2: materialize sidecar:

```text
scripts/hpc/r_mem1a_materialize_10d_sidecar.slurm
```

The materialization script should run with `ALLOW_PARTIAL=0` for the formal
10-day smoke. If source coverage is incomplete, it should fail rather than
silently create a misleading sidecar.

## Stop Rules

Do not proceed to R-FOREGROUND-4B unless:

- all 10 days are present for both canonical collectors;
- sidecar joins can be tested against current foreground events;
- maturity buckets are not dominated by source-missing artifacts;
- origin provenance is recorded;
- the sidecar is treated only as suppression-permission evidence.

Do not proceed to learning from R-MEM-1A outputs.

## Next Step

Run the HPC source collection and sidecar materialization:

```text
R-MEM-1A HPC 10-day canonical sidecar
```

If the sidecar is complete, proceed to:

```text
R-FOREGROUND-4B targeted path-memory poisoning guard smoke
```
