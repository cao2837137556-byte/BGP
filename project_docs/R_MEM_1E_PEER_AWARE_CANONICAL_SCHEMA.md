# R-MEM-1E Peer-aware Canonical Observation Schema

## Goal

R-MEM-1E repairs the observation identity contract exposed by R-MEM-1D-QA2.
It adds `peer_address` and a stable `observation_id` without changing the
immutable raw MRT archives or rewriting the two completed R-MEM-1D-R1
materializations in place.

## Why Peer Identity Is Required

The old Parquet schema contains `peer_asn` but not `peer_address`. Two BGP
sessions in the same ASN can therefore emit otherwise identical updates that
collapse under the old fingerprint. Such rows are distinct monitor
observations and must not be deleted as archive overlap.

QA2 recovered peer identity from the 28 implicated raw archives and found:

| Metric | Result |
|---|---:|
| unique boundary candidates | 84 |
| raw matching rows | 258 |
| same-peer duplicate copies | 80 |
| distinct-peer neighbor observations that must be preserved | 91 |
| canonical observations after pair-level deduplication | 178 |
| missing peer addresses | 0 |
| v2 identity mismatches | 0 |

The targeted R-MEM-1E smoke passed these values exactly. This proves that the
old base fingerprint is unsafe for deletion and that peer-aware identity can
separate actual archive overlap from legitimate distinct-peer observations.

## Schema v2

The peer-aware schema preserves all v1 fields and adds:

- `peer_address`: BGPStream peer-session address;
- `observation_id`: SHA-256 of the canonical semantic payload plus
  `peer_address`.

Communities are sorted before identity hashing because community ordering is
not used as routing-event identity. `source_file` and
`archive_timestamp_utc` remain provenance fields and are excluded from
`observation_id`, allowing the same observation copied across adjacent archive
containers to be recognized. A row with missing `peer_address` receives no
automatic observation ID and cannot be automatically deduplicated.

The existing materializer keeps v1 as its default. Schema v2 is enabled only
through explicit `--schema-version v2`, so historical outputs remain
reproducible and are never silently reinterpreted.

## Canonicalization Boundary

The v2 materialization is source-complete: it preserves every parsed row and
its source provenance. Deduplication is a separate, auditable canonical-view
step keyed by `observation_id`. This separation makes exclusions reversible
and prevents a parser from silently destroying distinct observations.

Whole-window temporal validation writes
`r_mem1d_duplicate_exclusion_sidecar.csv`. Each entry identifies the spill
copy, its canonical adjacent archive, and the peer-aware observation
fingerprint. A source-complete v2 parse may pass while still declaring that a
canonical consumer must apply this sidecar; those two states are reported
separately.

## Can the 10-day Window Be Guaranteed Attack-free?

No. Route Views and RIPE RIS provide real public observations, not certified
benign truth. The 2024-04-07 through 2024-04-16 window must be called
`unlabeled_operational_background`.

After schema v2 materialization, a background contamination audit must:

1. check overlap with declared public incidents and known-event sources;
2. attach time-aligned RPKI origin evidence;
3. attach time-aligned AS-rel path diagnostics;
4. preserve and audit communities / NO_EXPORT availability;
5. audit origin, path, and visibility novelty;
6. quarantine suspicious and unresolved intervals through a sidecar rather
   than deleting them.

Even after this audit, the allowed claim is only: no known or identified
incident under the declared sources and checks. It is forbidden to claim that
the window is attack-free or that unflagged rows are confirmed benign.
Controlled injections and confirmed historical replays remain the attack-truth
tracks; the 10-day window supplies operational background and history only.

## Current Result and Next Step

The local deterministic smoke over the pulled QA2 artifacts passed. A later
full execution materialized the peer-aware v2 schema for 19 of 20
collector-days on AMD:

- `3,552` source files;
- `1,851,186,204` parsed rows;
- zero source-integrity failures;
- zero Parquet-footer failures;
- maximum bounded archive offset of `12` seconds;
- `80` peer-aware adjacent-archive exclusions;
- missing task: `rrc00/2024-04-16`.

Six complete dates passed the original zero-boundary gate exactly. Three more
complete dates contained only bounded archive-container spill rows and are
safe for development when consumers reassign windows from row `ts`.
R-DATA-FREEZE-0 therefore freezes `2024-04-07` through `2024-04-15` as a
nine-day dual-collector development asset and excludes the incomplete final
date.

No raw archive needs to be downloaded again. Completing the tenth day and a
formal contamination audit are parallel follow-ups, not blockers for bounded
system development.

This phase does not attach attack truth, modify foreground policy, train the
learning layer, or claim poisoning robustness.
