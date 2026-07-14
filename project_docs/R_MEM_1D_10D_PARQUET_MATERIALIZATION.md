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

## Early Gate and Resume Contract

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
- no failed collector-day task or early gate;
- source-integrity verification for all files;
- one consistent code fingerprint across all tasks;
- the expected array-job provenance on every task.

The validator reads metadata and file counts, not all Parquet rows.
It is submitted with an `afterany` dependency, so it also writes an explicit
missing-task/file report when an array does not finish cleanly.

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

After one partition produces a passing 20-task validation summary, build the
10-day path-memory sidecar from the qualified Parquet asset. Only then return
to the targeted path-history poisoning repair in R-FOREGROUND-4B. Evidence
attachment and learning remain downstream steps.
