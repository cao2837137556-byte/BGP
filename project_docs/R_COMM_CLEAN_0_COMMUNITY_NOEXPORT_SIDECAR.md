# R-COMM-CLEAN-0 Community / NO_EXPORT Sidecar

Last updated: 2026-06-16

Status: completed.

## 1. Goal

R-COMM-CLEAN-0 builds a clean raw-to-event/candidate sidecar for BGP community attributes on the 2024-04-16 six-hour baseline run.

This stage exists because R-2D-0 proved that raw updates contain `communities`, including well-known values such as `NO_EXPORT`, but event/candidate layers did not retain those fields. The goal here is to make community evidence joinable without modifying the legacy seven-layer pipeline.

## 2. Scope

Allowed:

- read raw update chunks under `data/runs/s2a_baseline_v01_pilot_6h_april16/`;
- read `events/event_units.parquet` as the event key/time index;
- read `candidates/candidate_events.parquet` only for `event_id` attachment;
- emit an independent sidecar under `outputs/r_comm_clean_0/`;
- preserve parse status, raw join quality, and provenance.

Forbidden:

- modify `build_event_units.py` or old seven-layer outputs;
- use final/high/needs/low as truth;
- claim a NO_EXPORT attack;
- treat NO_EXPORT absence as safe;
- treat missing community evidence as benign;
- train learning;
- run suppression or incident aggregation.

## 3. Method

Script:

```text
scripts/build_r_comm_clean0_community_sidecar.py
```

Full command:

```text
python scripts/build_r_comm_clean0_community_sidecar.py ^
  --run-id s2a_baseline_v01_pilot_6h_april16 ^
  --run-date 2024-04-16 ^
  --run-root data/runs/s2a_baseline_v01_pilot_6h_april16 ^
  --output-dir outputs/r_comm_clean_0/s2a_baseline_v01_pilot_6h_april16 ^
  --overwrite
```

The script uses event `source_file` as provenance, splits multi-source events, then reads the raw counterpart of each `__rel.parquet` source chunk. It does not use old `rel_seq`, `rel_unknown_cnt`, or `rel_has_unknown`.

Raw rows are joined to events by:

- source chunk provenance;
- `prefix`;
- normalized `origin_as`;
- normalized `as_path_clean`;
- event time interval `[first_seen, last_seen]`.

Candidate rows are joined through `event_id`.

## 4. Outputs

Output directory:

```text
outputs/r_comm_clean_0/s2a_baseline_v01_pilot_6h_april16/
```

Files:

| File | Purpose |
|---|---|
| `community_event_sidecar.parquet` | event-level community / well-known community sidecar |
| `community_candidate_sidecar.parquet` | candidate-level sidecar joined by `event_id` |
| `community_event_sidecar_preview.csv` | 1000-row preview |
| `community_source_join_audit.csv` | source-file read and raw join audit |
| `community_evidence_state_distribution.csv` | community evidence state counts |
| `well_known_community_event_hits_sample.csv` | sample rows with well-known community hits |
| `community_noexport_summary.json` | machine-readable summary |
| `community_noexport_report.md` | lightweight output report |

Outputs are experiment artifacts and should not be committed.

## 5. Full Run Results

Input:

- event rows: `3431103`;
- candidate rows: `3431103`;
- source files expected: `144`;
- source files processed successfully: `144`;
- raw rows read: `7200000`;
- assigned raw rows: `7177476`.

Join quality:

| Metric | Value |
|---|---:|
| candidate sidecar join rate | `1.0` |
| events with raw match | `3431102` |
| event raw-match rate | `0.9999997085` |
| exact record-count match events | `3420829` |
| exact record-count match rate | `0.9970056276` |
| partial record-count match events | `10273` |
| no raw match events | `1` |

Interpretation:

- Community evidence is now candidate/event-ready for almost all rows.
- `partial_record_count_match` rows retain community evidence, but their exact raw record coverage is incomplete and must not be treated as full absence evidence.
- The one `raw_join_unavailable` event remains unavailable, not benign and not NO_EXPORT-absent.

## 6. Community Evidence State

| State | Count |
|---|---:|
| `present_parsed` | `2350715` |
| `present_unparsed` | `930897` |
| `observed_no_community_tokens` | `149490` |
| `raw_join_unavailable` | `1` |

The `present_unparsed` state mostly reflects community field shapes that contain non-empty raw values but do not parse into the conservative token patterns used here. This is not a benign signal.

## 7. Well-known Communities

Event-level hits:

| Well-known community | Event count |
|---|---:|
| `NO_EXPORT` | `1045` |
| `NO_ADVERTISE` | `988` |
| `NO_EXPORT_SUBCONFED` | `0` |
| `NOPEER` | `780` |

Assigned raw-row hits:

| Well-known community | Raw-row count |
|---|---:|
| `NO_EXPORT` | `3481` |
| `NO_ADVERTISE` | `1240` |
| `NO_EXPORT_SUBCONFED` | `0` |
| `NOPEER` | `921` |

These counts are evidence availability counts. They are not attack counts.

## 8. Scientific Boundary

Allowed claim:

```text
Raw community / well-known community evidence is now represented as a provenance-bearing event/candidate sidecar where raw join succeeds.
```

Forbidden claims:

- `NO_EXPORT` present is a confirmed attack.
- `NO_EXPORT` absent means safe.
- Missing communities are benign.
- Low visibility means `NO_EXPORT`.
- Community evidence creates learning labels.

## 9. Current Limits

- Exact record-count coverage is `0.9970056276`, not `1.0`.
- `930897` events have non-empty communities but conservative parsing did not extract valid token patterns.
- Provider-specific community semantics are not decoded.
- This sidecar does not prove stealth attack, poisoning/evasion robustness, recall, or false-positive reduction.

## 10. Next Step

R-COMM-CLEAN-0 removes the main community/NO_EXPORT join blocker for the clean six-hour baseline.

Recommended mainline next step:

```text
R-LABEL-0:
Define the multi-attack benchmark / label protocol before foreground validation or learning.
```

Before a future community-specific verifier branch uses absence claims, inspect the `partial_record_count_match` and `raw_join_unavailable` rows. Until then, only positive well-known community presence and explicit evidence-state fields should be used.
