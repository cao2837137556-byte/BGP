# R-CLEAN-0 Data / Evidence Clean Contract

Last updated: 2026-06-15

Status: active contract.

## 1. Goal

R-CLEAN-0 defines which local data, external evidence, legacy fields, and previous outputs are clean enough to enter the new paper-facing mainline.

This is a documentation and contract step. It does not run experiments, change pipeline logic, train learning, or create labels.

## 2. Why This Contract Exists

The new paper target depends on accurate experiment semantics. A foreground policy or learning layer is not meaningful if it silently mixes:

- stale 2017 AS-rel fields;
- 2024-near AS-rel evidence;
- aligned RPKI evidence;
- raw-only communities that are unavailable upstream;
- legacy final labels used as if they were truth.

R-CLEAN-0 prevents that by forcing every field into one of four states:

```text
allowed
allowed only through clean sidecar
audit reference only
forbidden in decisions
```

## 3. Fixed Runs And Dates

| Item | Value | Notes |
|---|---|---|
| clean background run | `s2a_baseline_v01_pilot_6h_april16` | used by R-NOISE-0/1 foreground smoke |
| expanded evidence run | `s2a_expanded_v01_pilot_6h_april16` | used by R-2D-0, R-CONSIST-1, fixed S2 evidence audits |
| run date | `2024-04-16` | target alignment date |
| RPKI snapshot | `2024-04-16` | aligned to run date |
| CAIDA AS-rel snapshot | `2024-04-01` | 15 days before run date, 2024-near |
| old Stage 1 AS-rel snapshot | `2017-07-01` | forbidden for new decision logic |

## 4. Allowed Data

These fields may enter new mainline experiments if provenance is preserved:

| Data | Source | Allowed use | Forbidden claim |
|---|---|---|---|
| prefix | candidate/event native field | routing object key | attack/benign truth |
| origin_as | candidate/event native field | origin key | attack/benign truth |
| as_path_clean | candidate/event native field | path key / sidecar lookup | path attack truth by itself |
| collector / collector_set / collector_count | candidate/event native field | observability feature | low visibility equals stealth attack |
| timestamp / first_seen / last_seen / duration | event native field | time scope / replay | attack truth |
| candidate_reasons | candidate-entry weak-signal provenance | weak feature / explanation | truth label |
| candidate_flag | candidate-entry workflow flag | audit / weak workflow context | foreground truth |

## 5. Allowed External Evidence

### RPKI / VRP

Current asset:

```text
data/evidence/rpki/vrp_2024-04-16.parquet
data/evidence/rpki/vrp_2024-04-16.metadata.json
```

Verified facts:

- run_date: `2024-04-16`;
- snapshot_date: `2024-04-16`;
- `aligned_to_run_date=true`;
- record_count: `530187`;
- TAL count: `5`.

Allowed use:

- origin authorization evidence;
- protective / evidence feature;
- benchmark feature with provenance.

Forbidden claims:

- RPKI invalid is confirmed attack;
- RPKI valid is benign;
- RPKI unknown is normal.

### CAIDA AS Relationships

Current 2024-near asset:

```text
data/evidence/as_relationships/as_rel_2024-04-01.parquet
data/evidence/as_relationships/as_rel_2024-04-01.metadata.json
```

Verified facts:

- provider: `CAIDA`;
- snapshot_date: `2024-04-01`;
- run_date: `2024-04-16`;
- alignment_delta_days: `15`;
- record_count: `1142660`;
- parse_warning_count: `0`;
- usable_evidence_strength: `aligned_medium`.

Allowed use:

- path relation lookup;
- route-leak-like diagnostic;
- path manipulation diagnostic;
- clean sidecar feature.

Forbidden claims:

- AS-rel violation is confirmed route leak;
- AS-rel matched path is benign;
- AS-rel unknown means suspicious by itself.

## 6. Sidecar Required

### AS-rel sidecar

R-CONSIST-1 found old Stage 1 AS-rel fields likely come from CAIDA `2017-07-01`:

```text
rel_seq
rel_unknown_cnt
rel_has_unknown
path_plausibility_score
plausibility_bucket
relation_support_score
triplet_signature
```

These fields are forbidden in new decisions until regenerated from the 2024-near AS-rel cache.

Required R-ASREL-CLEAN-0 output:

```text
event_id
as_path_clean
asrel_snapshot_date
run_date
alignment_delta_days
rel_seq_2024
rel_unknown_cnt_2024
rel_has_unknown_2024
path_relation_diagnostic_2024
asrel_provenance
allowed_claim
forbidden_claim
```

### Communities / NO_EXPORT sidecar

R-2D-0 found:

- community-like fields exist in raw updates;
- raw rows scanned: `39039005`;
- non-empty community rows: `35657850`;
- parse_success_rows: `27843441`;
- NO_EXPORT rows: `223410`;
- NO_ADVERTISE rows: `1240`;
- NOPEER rows: `5634`;
- current retained layer: `raw_updates` only;
- first likely drop layer: `event_units`;
- incident_join_ready: `false`.

Therefore:

- raw NO_EXPORT present is real evidence availability;
- candidate/event NO_EXPORT unavailable is not NO_EXPORT absent;
- stealth / NO_EXPORT judgment is blocked until propagation or sidecar join exists.

Required R-COMM-CLEAN-0 output:

```text
event_id or stable raw-to-event join key
has_no_export
has_no_advertise
has_nopeer
community_count
community_parse_status
community_provenance
allowed_claim
forbidden_claim
```

## 7. Audit Reference Only

These may appear in audit tables but must not decide foreground, labels, or learning targets:

| Field / output | Reason |
|---|---|
| `final_alert_label` | legacy workflow output, not truth |
| `high_priority_alert` | workflow reference only |
| `needs_review` | workflow reference only |
| `low_priority_or_background` | not confirmed benign |
| `P1 / P2 / P3` | priority buckets, not truth |
| R-NOISE-1 foreground/suppressed outputs | provisional clean-window smoke only |
| R-AGG raw incident outputs | stop-loss / historical evidence only |

## 8. Forbidden In New Decisions

The following are banned from new paper-facing decision logic:

- 2017 AS-rel-derived event fields;
- `rel_seq`, `rel_unknown_cnt`, `rel_has_unknown` unless suffixed/provenanced as 2024-aligned sidecar fields;
- legacy final/high/needs/low as hard guards;
- P1/P2/P3 as labels;
- suppressed background as negative training labels;
- RPKI valid as benign labels;
- RPKI invalid as attack labels;
- AS-rel violation as route-leak labels;
- missing communities as NO_EXPORT absent;
- low visibility as confirmed NO_EXPORT or stealth attack;
- unavailable evidence as safe / normal.

## 9. Previous Results Reclassification

| Previous phase | New classification |
|---|---|
| R-NOISE-1 | provisional foreground smoke; not final clean result |
| R-NOISE-0 | separability audit; useful for policy design |
| R-EVID-0 | stop-loss against direct evidence pre-triage |
| R-AGG-2 / R-AGG-3 | stop-loss against candidate-first incident aggregation |
| R-CONSIST-1 | blocker showing AS-rel sidecar is required |
| R-2D-0 | blocker showing community propagation / sidecar is required |
| R-2B / R-2C | evidence prototypes; reusable facts, not direct labels |

## 10. Immediate Pass / Block Status

| Contract item | Status | Next action |
|---|---|---|
| RPKI aligned evidence | pass | may be used with truth boundaries |
| 2024-near AS-rel cache | pass | build clean sidecar before use |
| old `rel_*` fields | block | exclude from decisions |
| raw communities available | pass at raw layer | build propagation / sidecar |
| communities at candidate/event | block | do not use NO_EXPORT in decisions yet |
| clean attack labels | block | design R-LABEL-0 / R-ATTACK-0 |
| learning labels | block | wait for benchmark |

## 11. Next Required Work

R-CLEAN-0 selects the next concrete step:

```text
R-ASREL-CLEAN-0: 2024-aligned AS-rel sidecar for candidate/event rows
```

Do not train, do not rerun R-NOISE as final, and do not implement production suppression before this sidecar and the label/benchmark protocol exist.
