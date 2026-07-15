# R-MEM-1D 10-day MRT-to-Parquet Materialization

## Goal

R-MEM-1D converts the immutable R-MEM-1B 10-day provider archives into an
audited Parquet data asset for the later path-memory sidecar. It is data
preparation, not attack generation, evidence attachment, foreground repair, or
learning.

The input contract is fixed:

- dates: `2024-04-07` through `2024-04-16` UTC;
- collectors: `route-views.sg` and `rrc00`;
- provider-compressed archives: `3,840`;
- compressed bytes: `16,502,107,268`;
- acquisition integrity: all size, SHA256, and compression checks passed.

## Why There Is No Manual Decompression Stage

The R-MEM-1C parser streams `.bz2` and `.gz` MRT archives directly through
BGPStream and writes Parquet batches. It does not create an uncompressed MRT
copy. This avoids a second large raw-data tree and keeps each Parquet row tied
to the immutable source archive.

## Entry Qualification

R-MEM-1C qualified the exact parser path on complete files:

- AMD job `151396` completed in `23` seconds;
- Intel job `151397` completed in `25` seconds;
- each parsed two complete archives into `966,702` rows;
- both passed all source-integrity and schema gates;
- measured throughput was about `53,073` and `44,449` rows/s.

The failed jobs `151384/151385` are engineering failures only: they exited
before reading MRT because an archive-only code tree lacked `.git`. R-MEM-1D
uses optional commit provenance plus a mandatory executable-content SHA256
fingerprint.

## Work Partition

The full run uses `20` independent collector-day tasks:

- `10` UTC dates times `2` collectors;
- each Route Views SG task processes `96` archives;
- each RRC00 task processes `288` archives;
- array concurrency is capped at `4` per partition;
- each task requests `1` CPU, `2 GB` memory, and `2` hours.

This request follows measured single-file throughput and memory behavior. It is
not enlarged speculatively.

## Boundary Parser Precheck and Resume Contract

Each task processes files in this order:

1. the chronologically first archive;
2. the chronologically last archive;
3. the remaining archives in chronological order.

The first and last archives must pass source size/SHA256, timestamp, prefix,
AS-path, and communities-schema gates before middle files are attempted. This
integrates the earlier four-file boundary check into the real materialization
instead of spending another queue cycle on a separate smoke.

Every source archive receives:

- one atomically promoted Parquet output;
- one atomic JSON checkpoint;
- one file-level audit record.

A requeued task verifies the checkpoint and Parquet byte size before skipping
completed work. Failed checkpoints are reparsed. A capped debug run cannot pass
formal qualification.

## Dual-partition Contract

AMD and Intel receive the same immutable inputs and logical `pair_id`, but use
different array job IDs, output roots, temporary paths, logs, checkpoints, and
validation packages. The user may cancel the later-starting array. If both
finish, both remain valid redundant executions and must not be counted as two
scientific samples.

## Full-run Acceptance Gates

One partition run passes only if the validator observes:

- exactly `20` unique collector-day summaries;
- exactly `3,840` unique source archives;
- exactly `3,840` successful file audits and Parquet outputs;
- no failed collector-day task or boundary parser precheck;
- source-integrity verification for all files;
- one consistent code fingerprint across all tasks;
- the expected array-job provenance on every task.

The final validator also reopens all `3,840` Parquet footers, checks exact
schema and row-count agreement, reconciles all source paths against the frozen
download manifest, and emits a canonical source-to-Parquet manifest.

The validator reads metadata and file counts, not all Parquet rows.
It is submitted with an `afterany` dependency, so it also writes an explicit
missing-task/file report when an array does not finish cleanly.

## First Execution Audit and R-MEM-1D-R1 Recovery

The first materialization attempt is not a qualified 10-day asset, but its
completed outputs are valid reusable work:

- RRC00 complete: `2,880 / 2,880` files;
- Route Views parsed: `490 / 960` files;
- reusable total: `3,370 / 3,840` Parquets;
- remaining parse work: `470` Route Views files;
- Route Views files with archive-boundary spill: `31`;
- bounded spill rows: `94`;
- maximum observed boundary offset: `13` seconds;
- observed parse/schema/source-integrity failures in completed outputs: `0`.

The failure came from treating a provider archive filename as an exact row-time
partition. MRT row timestamps remain the event-time authority. R-MEM-1D-R1
therefore uses this recovery contract:

1. Revalidate old checkpoints and Parquet footers before adoption.
2. Hard-link valid outputs into a new isolated run root.
3. Parse only files without a valid adoptable result.
4. Preserve all bounded spill rows; never silently trim them.
5. Compare spill-row fingerprints with the adjacent archive and stop if a
   potential duplicate is present.
6. Stop if an affected outer-boundary file has no adjacent guard archive to
   audit; do not infer non-duplication from missing data.
7. Promote the asset only after exact `3,840`-file source-manifest, footer,
   schema, provenance, and temporal-alignment validation passes.

The boundary allowance is not a data-cleaning shortcut and is not an attack
signal. It is an archive-container alignment rule guarded by a separate
overlap audit. Until final validation passes, the 10-day asset remains an
active blocker and must not feed path-memory claims.

## Outputs

Large data stay outside Git under:

```text
/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/data_store/
  derived/r_mem1d_10d_parquet_v01/
```

Small task and validation summaries are packaged separately. No large Parquet
output is committed.

## Scientific Boundaries

- Parsed rows are routing observations, not attack or benign truth.
- NO_EXPORT presence remains propagation-control evidence, not attack truth.
- NO_EXPORT absence remains non-conclusive.
- R-MEM-1D does not attach RPKI or AS-rel evidence.
- R-MEM-1D does not modify foreground or train learning.
- Ten days do not by themselves prove long-term path maturity or poisoning
  robustness.

## Next Step

R-MEM-1D-R1 completed both 3,840-file materializations, but final qualification
stopped on 83 adjacent-archive base-fingerprint matches. Run R-MEM-1D-QA2 to
recover peer identity from only the implicated raw archives. Do not delete rows,
relax the validator, or replay all 3,840 archives. Build the 10-day path-memory
sidecar only after observation identity and canonical overlap handling are
qualified. Evidence attachment and learning remain downstream steps.
