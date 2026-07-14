# R-MEM-1C Local MRT Parser Smoke

## Goal

R-MEM-1C qualifies local parsing of the verified 10-day raw MRT dataset before
any full parse or path-memory materialization. It reads a bounded sample from
both Route Views SG and RRC00 through BGPStream's `singlefile` interface.

The parser never contacts the BGPStream Broker and never writes an uncompressed
MRT intermediate. It streams compressed provider archives directly into
partitioned Parquet.

## Why This Gate Is Necessary

R-MEM-1B proves that all `3,840` provider archives were acquired and transferred
byte-for-byte. SHA256 equality does not prove that the selected parser/runtime
understands the MRT encoding or preserves the fields needed by the path-memory
and later evidence layers.

A bounded smoke prevents a multi-hour full parse from silently producing zero
rows, wrong timestamps, missing AS paths, or dropped communities.

## Failed Formal Attempt and Revised Entry Gate

Formal job `151319` timed out after `01:00:04`, but used only about `0.117`
CPU seconds, emitted no parsed-row heartbeat, and left only a four-byte Parquet
header. Imports and deterministic file selection had already passed. The
supported conclusion is therefore narrow: the process blocked during
single-file startup or first-element retrieval. This run produced no parser
qualification result and increasing CPU, memory, or wall time would not address
the observed failure mode.

Before another complete-file smoke, R-MEM-1C now requires a fail-fast liveness
gate:

- one immutable Route Views `.bz2` and one RRC00 `.gz` archive;
- byte-size and SHA256 verification against the frozen manifest;
- the documented PyBGPStream single-file configuration compared with the
  official `bgpreader` CLI on the same bytes;
- at most `100` elements per backend and a `60`-second hard timeout;
- heartbeats before each backend and at first-element completion;
- no Parquet materialization;
- `1` CPU, `2 GB` memory, and a `10`-minute Slurm limit.

The liveness job is diagnostic. A timeout is recorded in its result package
instead of leaving an empty output directory. Only a passing backend may move
to a measured one-complete-file parse. Submission is additionally gated by
`scripts/hpc/r_mem1c_singlefile_liveness_preflight.sh`, which checks shell
syntax, paths, the 3,840-file archive contract, container imports, timeout
self-tests, and Slurm admission without submitting the job.

## Deterministic Sample

The default smoke selects the chronologically first and last archive for each
collector:

- two `route-views.sg` archives;
- two `rrc00` archives.

Each selected file is parsed completely. `--max-rows-per-file` exists only for
debugging and must remain zero for the formal smoke.

Before parsing, each selected archive is checked against its manifest-bound
byte size and SHA256. This makes the smoke a test of the transferred immutable
input, not merely a test that some file at the expected path can be opened.

## Output Contract

The parsed Parquet schema retains:

- timestamp;
- collector and project;
- announcement/withdrawal type;
- peer ASN;
- prefix;
- raw AS path;
- conservatively derived origin ASN plus derivation provenance;
- standard communities, including well-known community hits;
- next hop;
- immutable source-file and archive-time provenance.

Origin ASN is derived only when the final AS_PATH segment is a single decimal
ASN. AS_SET, confederation, missing, or unrecognized endings remain null with an
explicit provenance state. The parser does not guess.

## Smoke Gates

- both collectors must parse;
- every selected file must produce rows;
- timestamps must be present and remain inside the archive interval;
- update prefix coverage must be at least `0.999`;
- announcement AS_PATH coverage must be at least `0.95`;
- community list must remain part of the output schema;
- selected source size and SHA256 must match the acquisition manifest;
- capped debug runs cannot qualify as the formal smoke;
- no failed selected file is allowed.

The result reports input/output bytes so the full 10-day Parquet footprint can
be estimated before allocating the full job.

## Boundaries

- This is parser/schema qualification, not attack detection.
- Parsed updates are not attack or benign truth.
- NO_EXPORT presence is propagation-control evidence, not attack truth.
- NO_EXPORT absence or missing communities do not imply safety.
- R-MEM-1C does not modify foreground policy, build the final sidecar, or train
  learning.

## Next Step

Run `scripts/hpc/r_mem1c_singlefile_liveness.slurm`. If PyBGPStream and/or
`bgpreader` returns elements for both compressed formats, parse one complete
file with the passing backend and measure throughput and peak memory. Use those
measurements to size the later four-file smoke. If neither backend passes, stop
the current parser route and qualify a maintained alternative before any full
parse or path-memory materialization.
