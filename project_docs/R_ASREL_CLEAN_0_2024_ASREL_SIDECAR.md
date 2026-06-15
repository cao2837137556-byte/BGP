# R-ASREL-CLEAN-0 2024-Aligned AS-rel Sidecar

Last updated: 2026-06-15

Status: completed.

## 1. Goal

R-ASREL-CLEAN-0 builds a clean 2024-aligned CAIDA AS relationship sidecar for the 2024-04-16 six-hour candidate/event data.

This stage exists because old Stage 1 `rel_seq`, `rel_unknown_cnt`, and `rel_has_unknown` fields were likely generated from CAIDA `2017-07-01`, while the clean evidence cache is CAIDA `2024-04-01`. The goal is to stop future experiments from mixing stale Stage 1 AS-rel fields with 2024 evidence.

## 2. Scope

Allowed:

- read candidate rows from `data/runs/s2a_baseline_v01_pilot_6h_april16/candidates/candidate_events.parquet`;
- read event rows from `data/runs/s2a_baseline_v01_pilot_6h_april16/events/event_units.parquet`;
- read 2024 AS-rel cache from `data/evidence/as_relationships/as_rel_2024-04-01.parquet`;
- emit an independent sidecar under `outputs/r_asrel_clean_0/`;
- compare old `rel_*` fields against regenerated 2024 fields for audit only.

Forbidden:

- modify old seven-layer pipeline outputs;
- overwrite `event_units.parquet`;
- use old `rel_*` fields for decisions;
- generate confirmed route-leak labels;
- call AS-rel matched paths benign;
- train learning;
- make poisoning/evasion robustness claims.

## 3. Implementation

Script:

```text
scripts/build_r_asrel_clean0_sidecar.py
```

Full command:

```text
python scripts/build_r_asrel_clean0_sidecar.py ^
  --run-id s2a_baseline_v01_pilot_6h_april16 ^
  --run-date 2024-04-16 ^
  --output-dir outputs/r_asrel_clean_0/s2a_baseline_v01_pilot_6h_april16 ^
  --overwrite
```

The script parses `as_path_clean`, looks up adjacent AS pairs in the 2024 CAIDA cache, and emits:

- `rel_seq_2024`;
- `rel_seq_2024_raw`;
- `rel_unknown_cnt_2024`;
- `rel_has_unknown_2024`;
- `rel_unknown_rate_2024`;
- `possible_valley_transition_2024`;
- `path_relation_diagnostic_2024`;
- `path_relation_evidence_state_2024`;
- AS-rel snapshot / run date / provenance fields;
- allowed and forbidden claim notes.

The legacy `rel_seq`, `rel_unknown_cnt`, and `rel_has_unknown` columns are retained only for comparison audit.

## 4. Outputs

Output directory:

```text
outputs/r_asrel_clean_0/s2a_baseline_v01_pilot_6h_april16/
```

Files:

| File | Purpose |
|---|---|
| `asrel_2024_event_sidecar.parquet` | full 2024 AS-rel sidecar |
| `asrel_2024_event_sidecar_preview.csv` | 1000-row preview |
| `asrel_2024_summary.json` | full summary |
| `asrel_2024_path_diagnostic_distribution.csv` | diagnostic distribution |
| `asrel_2024_old_rel_comparison_audit.csv` | old `rel_seq` vs 2024 sidecar comparison |
| `asrel_2024_report.md` | lightweight output report |

Outputs are experiment artifacts and should not be committed.

## 5. Full Run Results

Input:

- candidate rows: `3431103`;
- event rows: `3431103`;
- event join matched rows: `3431103`;
- event join rate: `1.0`.

AS-rel cache:

- snapshot date: `2024-04-01`;
- run date: `2024-04-16`;
- alignment delta days: `15`;
- directed lookup rows: `1142660`;
- directed pair conflict count: `0`.

Sidecar:

- sidecar rows: `3431103`;
- path-pair eligible rows: `3259347`;
- path-pair eligible rate: `0.949941`.

Diagnostic distribution:

| Diagnostic | Count | Share |
|---|---:|---:|
| `all_pairs_known_no_valley_diagnostic` | `2619285` | `0.763394` |
| `possible_valley_transition` | `361138` | `0.105254` |
| `partially_unknown_relation_sequence` | `271960` | `0.079263` |
| `no_usable_as_path` | `171756` | `0.050059` |
| `fully_unknown_relation_sequence` | `6964` | `0.002030` |

Evidence state distribution:

| Evidence state | Count |
|---|---:|
| `aligned_medium` | `2980423` |
| `aligned_weak` | `271960` |
| `unavailable` | `178720` |

## 6. Old vs 2024 AS-rel Comparison

Old `rel_seq` vs regenerated 2024 sequence:

| Comparison status | Count |
|---|---:|
| `old_and_2024_different_sequence` | `2789332` |
| `old_and_2024_same_sequence` | `470015` |
| `both_missing` | `171756` |

The old-vs-2024 different sequence rate is:

```text
0.812955
```

Interpretation:

- This confirms that using old Stage 1 `rel_*` fields in new decision logic would be scientifically unsafe.
- The difference should not be interpreted as attack signal.
- It is evidence-provenance drift, not route-leak truth.

## 7. Scientific Boundary

Allowed claim:

```text
2024-aligned AS-rel path diagnostic sidecar is available for candidate/event rows.
```

Forbidden claims:

- confirmed route leak;
- benign path;
- attack truth;
- low false positive improvement;
- poisoning/evasion robustness;
- learning-ready labels.

AS-rel evidence remains inferred evidence. `possible_valley_transition_2024` is a diagnostic candidate only.

## 8. Pass / Block Assessment

Passed:

- 2024 AS-rel sidecar exists;
- full candidate/event join succeeded;
- old `rel_*` fields are separated into audit-only comparison;
- no old pipeline outputs were modified;
- no labels or learning outputs were produced.

Still blocked:

- communities / NO_EXPORT sidecar is not built;
- benchmark / label protocol is not defined;
- controlled attack/evasion samples are not available;
- foreground validation must be rerun later under clean sidecars and benchmark inputs.

## 9. Next Step

Recommended next step:

```text
R-COMM-CLEAN-0:
Build a raw-to-event/candidate communities / NO_EXPORT sidecar or propagation design.
```

Alternative if we want to settle label semantics first:

```text
R-LABEL-0:
Define benchmark / label protocol before any further foreground validation or learning.
```

No learning, production suppression, or route-leak claim should proceed from this sidecar alone.
