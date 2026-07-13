# R-MEM-1B 10-Day Direct Archive Acquisition

## Purpose

R-MEM-1B acquires the immutable raw MRT source needed by the 10-day
path-memory sidecar. It replaces the failed compute-node BGPStream acquisition
route with direct Route Views and RIPE RIS archive downloads on an
egress-capable local host.

This phase is data acquisition and provenance work. It does not establish path
maturity, modify foreground policy, train learning, or produce attack/benign
labels.

## Why The Acquisition Route Changed

The first HPC array (`149909`) reached its eight-hour limit with zero parquet
files and zero completion summaries. The bounded acquisition probe (`150551`)
then separated the failure layers:

- CAIDA Broker metadata requests timed out from the compute node;
- direct PyBGPStream retrieval for both collectors hit the external timeout;
- local proxy checks reached the Route Views SG and RIPE RIS archives and
  returned real archive bytes.

The blocker is therefore compute-node egress, not evidence that the archives
are absent. Increasing Slurm wall time or resubmitting the same collector would
repeat an infrastructure failure.

## Dataset Contract

The canonical smoke window remains `2024-04-07` through `2024-04-16`
inclusive.

| Provider | Collector | Native update interval | Files/day | 10-day files |
|---|---:|---:|---:|---:|
| Route Views | `route-views.sg` | 15 minutes | 96 | 960 |
| RIPE RIS | `rrc00` | 5 minutes | 288 | 2,880 |
| Total | | | 384 | 3,840 |

Provider archive URLs are generated deterministically by
`configs/r_mem1b_10d_direct_archive_v01.json`. The downloader writes every
file beneath the external data root as:

```text
raw_mrt/r_mem1b_10d_direct_archive_v01/<project>/<collector>/<YYYY.MM>/<archive>
```

The recommended local root is `D:/study/paper/bgp_data_store`. The recommended
HPC root is
`/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/data_store`.
`configs/data_catalog_v1.json` is the single logical catalog for both the
frozen repository-local 6h data and new external large data.

## Integrity And Restart Contract

Each acquired archive must have:

- exact source URL, project, collector, and UTC archive timestamp;
- nonzero byte size;
- SHA256 digest;
- successful gzip or bzip2 stream validation;
- atomic `.part` download and rename;
- a durable per-file receipt and aggregate CSV/JSON manifest.

Interrupted `.part` files may be resumed with HTTP Range. Existing files are
not trusted merely because the pathname exists: their size, SHA256, receipt,
and compressed-stream integrity are checked before reuse. A missing archive is
reported as unavailable source data, never as an empty or benign observation.

## Execution Gates

1. Generate the complete plan and require exactly `3,840` files.
2. Download two files from each collector through the local proxy.
3. Require four nonzero archives, four SHA256 receipts, four compression
   checks, and no failed item.
4. Only then start the full 10-day acquisition.
5. Transfer immutable raw archives plus manifests to HPC.
6. Parse locally on HPC and materialize the path-memory sidecar through a
   manifest-bound run.

## Local Smoke Result

The 2026-07-13 local proxy smoke passed:

- complete deterministic plan: `3,840` files;
- selected smoke files: `4` (`2` per collector);
- completed files: `4`;
- failed files: `0`;
- total compressed bytes: `17,972,477`;
- SHA256 receipts: `4`;
- compressed-stream checks passed: `4`;
- residual `.part` files after completion: `0`;
- a second run revalidated all four existing archives instead of blindly
  skipping them.

The full acquisition was started only after these checks passed.

## Full Acquisition Result

The final full revalidation completed on 2026-07-13:

- planned files: `3,840`;
- completed files: `3,840`;
- Route Views SG files: `960`;
- RRC00 files: `2,880`;
- covered UTC dates: `10`, from `2024-04-07` through `2024-04-16`;
- unique item IDs and local paths: `3,840` each;
- total compressed bytes: `16,502,107,268`;
- SHA256 and compressed-stream checks passed: `3,840`;
- failed files: `0`;
- residual `.part` files: `0`;
- durable per-file receipts: `3,840`.

One RRC00 transfer (`updates.20240413.0445.gz`) initially ended early. The
source object advertised `4,156,720` bytes while the partial local transfer had
only `3,702,188` bytes. The downloader was corrected so a compressed-stream
integrity failure discards the damaged partial instead of attempting to resume
from corrupt bytes. The file was then downloaded from byte zero and passed the
same SHA256 and gzip checks. Finally, all `3,840` archives were re-read and
revalidated, not merely counted from receipts.

The authoritative terminal verdict is
`manifests/r_mem1b_10d_direct_archive_v01/full/download_summary.json` beneath
the external data root.

## Claim Boundaries

- Archive availability is not attack evidence.
- A valid compressed archive is not yet a valid parsed BGP row set.
- Ten days is a functional bridge, not the final paper-scale maturity claim.
- Path recurrence is not benign truth; recent recurrence is not attack truth.
- R-MEM-1B does not train learning or modify foreground policy.

## Next Step

R-MEM-1B is complete. Next, transfer the immutable raw archive tree and its
manifest to HPC, verify SHA256 after transfer, and run a bounded local-MRT
parser smoke. Only a successful parser/schema/coverage audit permits full
10-day path-memory sidecar materialization and the subsequent targeted
R-FOREGROUND-4B poisoning-robustness repair.
