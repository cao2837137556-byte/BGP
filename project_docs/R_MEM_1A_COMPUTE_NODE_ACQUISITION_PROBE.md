# R-MEM-1A Compute-Node Acquisition Probe

## Purpose

This probe is a bounded infrastructure gate for R-MEM-1A. It does not collect
the 10-day source window, materialize a path-memory sidecar, modify a foreground
policy, or train a model.

The first 10-day source-collection attempt (`Slurm array 149909`) reached the
eight-hour limit for every terminal task while writing zero update parquet files
and zero day summaries. The failure is therefore an acquisition-path failure,
not evidence about path-memory maturity or foreground quality.

## Why A Dedicated Probe Is Required

The original collector calls `pybgpstream.BGPStream` once per micro-window and
writes parquet only after an iterator returns. A stall in the first iterator
therefore leaves no checkpoint. Increasing the array wall time would not make
that behavior scientifically or operationally acceptable.

The probe separates four questions:

1. Can a compute node resolve the CAIDA Broker host?
2. Can it retrieve Broker metadata for Route Views and RIPE RIS?
3. Can the same container retrieve one Route Views SG update window?
4. Can it retrieve one RIPE RIS RRC00 update window?

Each subprobe has a bounded external timeout and emits a runner JSON with its
exit code. A `124` exit code means the external timeout fired; it is not
reported as a successful empty-data result.

## Result Interpretation

| Broker metadata | Stream probe | Interpretation | Next action |
|---|---|---|---|
| fails | not applicable or fails | compute-node DNS/egress or Broker access failure | use an egress-capable acquisition host or resolve cluster networking |
| passes | fails or times out | Broker is reachable but provider raw retrieval or PyBGPStream path is not usable | test direct provider archive retrieval; do not restart the 10-day array |
| passes | passes | acquisition is viable | repair collector checkpointing before a bounded re-run |
| passes | completed empty | investigate the requested collector/window before claiming access failure | verify archive coverage and collector naming |

## Safety Boundaries

- No result from this probe is BGP attack evidence.
- A Broker metadata response does not prove raw archive availability.
- A stream timeout does not prove that all HPC data acquisition is impossible.
- Do not restart the 10-day collection merely by increasing wall time.
- If an egress restriction is confirmed, acquire immutable raw MRT files on an
  egress-capable host with URL, collector, time-window, byte-size, and SHA256
  manifest, then use HPC only for local parsing and sidecar materialization.

## Follow-Up Gate

Only after the probe identifies the failing layer should the collector be
repaired. The repair must support per-window timeout, checkpoint/manifest
records, retry accounting, and deterministic source provenance before another
multi-day request is submitted.
