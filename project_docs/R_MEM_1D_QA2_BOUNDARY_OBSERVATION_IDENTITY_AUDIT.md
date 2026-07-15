# R-MEM-1D-QA2 Boundary Observation Identity Audit

## 1. Purpose

R-MEM-1D-R1 completed both isolated AMD and Intel 10-day materializations, but
the final temporal validator found adjacent-archive base-row fingerprint
matches. R-MEM-1D-QA2 determines whether those matches are genuine archive
overlap candidates or separate BGP observations that the current Parquet
schema cannot distinguish.

This is a bounded data-quality audit. It does not reparse the complete 10-day
window, delete rows, attach external evidence, modify foreground, or train a
model.

## 2. Triggering Evidence

Both R-MEM-1D-R1 executions independently produced:

- `20` collector-day summaries;
- `3,840` Parquet files;
- `64` source files with bounded archive-boundary spill;
- `919` spill rows;
- maximum observed boundary offset of `12` seconds;
- `83` potential adjacent-archive fingerprint matches across `14` Route Views
  source files;
- no missing adjacent-file check.

The AMD and Intel results are identical. This is reproducible data behavior,
not a partition-specific parser failure.

Three Route Views collector-day tasks failed only because one or more files
slightly exceeded the preregistered per-file spill-rate threshold of `0.0001`.
That rate gate is not sufficient for scientific qualification: a bounded
offset can be harmless, while even one true duplicate can bias path-history
counts. R-MEM-1D-QA2 therefore prioritizes observation identity over an
arbitrary spill-rate threshold.

## 3. Why the 83 Matches Cannot Be Deleted Directly

The current Parquet observation schema records `peer_asn` but not
`peer_address`. The old temporal fingerprint covers timestamp, collector,
project, type, peer ASN, prefix, path, origin, communities, and next hop, but
cannot distinguish two peers in the same ASN that emitted otherwise identical
updates.

[PyBGPStream's official API](https://bgpstream.caida.org/docs/api/pybgpstream/pybgpstream.html)
exposes `peer_address` for each BGP element. QA2 replays only the small set of
implicated raw MRT archives and recovers:

- `peer_address`;
- record router name when available;
- record router IP when available.

Communities are sorted before QA2 fingerprinting. This prevents set/list order
differences during raw replay from creating false mismatches.

## 4. Classification Contract

Each unique adjacent-file plus canonical-base-fingerprint candidate is assigned
one of four outcomes:

| Classification | Meaning | Allowed action |
|---|---|---|
| `archive_overlap_duplicate_candidate` | Base row and recovered peer/router identity occur in both archives with matching multiplicity | eligible for a later non-destructive canonical exclusion design; not deleted in QA2 |
| `distinct_peer_observation_collision` | Base row matches but recovered observation identities differ | preserve observations and repair canonical schema with peer address |
| `mixed_identity_overlap` | Some identities overlap while others differ | preserve observations and repair schema before canonicalization |
| `unresolved_raw_parquet_multiplicity_mismatch` | Raw replay does not reconcile Parquet multiplicity | stop and repair the audit before dataset qualification |

Even the first classification is a duplicate candidate, not proof that two
protocol messages are semantically interchangeable. QA2 never rewrites source
or derived data.

## 5. Outputs

Each AMD/Intel execution writes to an isolated path under:

```text
data_store/derived/r_mem1d_qa2_boundary_identity_v01/
  pair=<pair_id>/partition=<partition>/job=<job_id>/
```

Small outputs are:

- `r_mem1d_qa2_summary.json`;
- `r_mem1d_qa2_candidate_identity_audit.csv`;
- `r_mem1d_qa2_raw_match_audit.csv`;
- `r_mem1d_qa2_raw_file_audit.csv`;
- `r_mem1d_qa2_report.md`;
- `r_mem1d_qa2_small_results.tar.gz`.

## 6. Execution Guardrails

- Read the already complete R-MEM-1D-R1 Parquets; do not parse all 3,840 raw
  archives again.
- Replay only raw archives implicated by canonical boundary candidates.
- Use at most four workers. The formal request is `4 CPU / 6 GB / 4 hours`.
- Queue isolated AMD and Intel copies under one logical pair ID.
- Treat both completed copies as redundant executions, not two samples.
- Do not relax the existing validator before the identity audit reports why
  matches occur.
- Do not build path memory from the 10-day asset until a canonical observation
  contract is qualified.

## 7. Decision Branch

If every candidate reconciles to the same observation identity, the next step
is a non-destructive archive-overlap exclusion sidecar and metadata-only final
qualification. If any distinct or mixed peer identity is found, add
`peer_address` to the canonical observation schema before qualifying the asset.
If any multiplicity remains unresolved, stop and repair QA2 rather than
guessing or rerunning the full window.

## 8. Current Status

Implementation, Python compilation, classification self-test, shell syntax
checks, and a synthetic adjacent-boundary candidate test passed locally.
Formal HPC execution is pending.
