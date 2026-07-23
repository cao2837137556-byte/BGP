# R-DATA-FREEZE-0 Nine-day Development Asset

## Goal

R-DATA-FREEZE-0 closes the prolonged data-preparation loop without pretending
that an incomplete ten-day materialization is complete. It freezes the largest
contiguous, peer-aware, dual-collector subset that already satisfies a bounded
and reproducible contract.

No MRT archive is downloaded or reparsed in this phase. The audit reads only
the pulled R-MEM-1E summaries and the completed R-MEM-1D-QA2 peer-identity
audit.

## Why “Only Six Days” Was an Intermediate Result

The best R-MEM-1E execution produced 19 of 20 collector-day tasks:

- all ten `route-views.sg` days;
- nine `rrc00` days;
- `rrc00/2024-04-16` is missing.

Among the nine complete dual-collector dates, six passed the old per-archive
gate exactly. Three Route Views dates (`2024-04-07`, `2024-04-09`, and
`2024-04-10`) preserved small numbers of rows whose BGP timestamps crossed an
archive-container boundary. The maximum offset was 12 seconds.

This is not source corruption. Route Views archive names describe container
time, while analysis windows must be assigned from each row’s `ts`. The
temporal audit over the 19 available collector-days passed and the parser
preserved every boundary row. R-DATA-FREEZE-0 therefore accepts these three
dates only with an explicit row-time rewindowing contract.

## Frozen Asset

The frozen development interval is:

```text
2024-04-07T00:00:00Z <= row ts < 2024-04-16T00:00:00Z
```

It contains nine complete dates from both:

- `route-views.sg`;
- `rrc00`.

The source is the AMD R-MEM-1E execution because it has the highest completed
collector-day and file coverage. The incomplete `2024-04-16` date is excluded
rather than silently used as a single-collector day.

The completed local freeze audit reports:

| Metric | Result |
|---|---:|
| freeze passed | `true` |
| frozen dual-collector days | `9` |
| frozen source files | `3,456` |
| parsed rows before canonical exclusions | `1,779,700,135` |
| strict-pass dates | `6` |
| row-time rewindow dates | `3` |
| archive-boundary warning files | `63` |
| preserved boundary rows before rewindowing | `917` |
| maximum archive-boundary offset | `12 seconds` |
| reversible duplicate exclusions | `80` |
| excluded incomplete dates | `2024-04-16` |

The audit outputs are under
`outputs/r_data_freeze0_9d_development_v01/` and are intentionally not
committed.

## Canonical Observation Contract

The asset uses `canonical_observation_v2`:

- `peer_address` distinguishes separate BGP peer sessions;
- `observation_id` identifies the same semantic observation across adjacent
  archive containers;
- source rows remain immutable;
- duplicate removal is a reversible consumer-side operation.

The duplicate exclusion sidecar is rebuilt from the QA2 raw peer-identity
audit. Its copy count must equal the R-MEM-1E temporal validator’s canonical
exclusion count. This prevents the old peer-blind fingerprint from deleting
legitimate observations.

## Allowed Use

The frozen asset may be used for:

- bounded frontend/component-fit experiments;
- controlled attack injection and replay;
- online-history and path-memory engineering;
- parser, schema, temporal-causality, and provenance QA.

## Forbidden Claims

The dataset role is `unlabeled_operational_background`.

It is not:

- certified attack-free;
- confirmed benign;
- ready-made negative training truth;
- sufficient for broad Internet visibility claims;
- evidence of poisoning robustness.

Before any row becomes a negative learning example, a separate contamination
audit must check declared incidents and attach time-aligned evidence. Suspicious
or unresolved intervals must be quarantined through a sidecar, not deleted.

## Exit Decision

Once the freeze audit passes, data preparation no longer blocks bounded system
development. Repairing `rrc00/2024-04-16` and expanding to 30 days become
parallel validation work, not prerequisites for starting the frontend and
attack-replay mainline.

The next mainline action is a bounded mature-frontend fit audit. It must compare
reuse/adapt/baseline/reject options under deterministic offline replay before
the project writes another custom compression frontend.
