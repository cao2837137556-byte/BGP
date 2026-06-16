# R-RPKI-CLEAN-0 Event-level RPKI Sidecar

Last updated: 2026-06-16

Status: completed.

## 1. Goal

R-RPKI-CLEAN-0 converts the aligned `2024-04-16` VRP cache into a clean event/candidate RPKI sidecar for the six-hour baseline run.

This stage exists to align evidence granularity. AS-rel and communities / NO_EXPORT now have event/candidate sidecars; RPKI should use the same sidecar contract rather than relying on older verifier-smoke outputs.

## 2. Scope

Allowed:

- read `data/evidence/rpki/vrp_2024-04-16.parquet`;
- read baseline `event_units.parquet` and `candidate_events.parquet`;
- classify event `prefix + origin_as` pairs as RPKI origin-authorization evidence;
- emit independent sidecars under `outputs/r_rpki_clean_0/`;
- preserve lookup notes, evidence state, and forbidden-claim guardrails.

Forbidden:

- reuse old verifier outputs as the main clean artifact;
- produce attack or benign truth labels;
- treat RPKI invalid as confirmed attack;
- treat RPKI valid as benign;
- treat RPKI unknown as normal;
- train learning or run suppression.

## 3. Implementation

Script:

```text
scripts/build_r_rpki_clean0_sidecar.py
```

Full command:

```text
python scripts/build_r_rpki_clean0_sidecar.py ^
  --run-id s2a_baseline_v01_pilot_6h_april16 ^
  --run-date 2024-04-16 ^
  --run-root data/runs/s2a_baseline_v01_pilot_6h_april16 ^
  --output-dir outputs/r_rpki_clean_0/s2a_baseline_v01_pilot_6h_april16 ^
  --overwrite
```

The script builds a VRP prefix index from `prefix`, `asn`, and `max_length`, checks each unique event prefix-origin pair once, then maps the result back to all event and candidate rows through `event_id`.

RPKI status logic:

- `valid`: a covering VRP authorizes the event origin AS and route prefix length is within `max_length`;
- `invalid_length`: the origin AS matches a covering VRP but the event prefix is too specific;
- `invalid_asn`: covering VRP exists, but for a different origin AS;
- `unknown`: no covering VRP exists;
- `missing`: event prefix or origin AS is unavailable.

## 4. Outputs

Output directory:

```text
outputs/r_rpki_clean_0/s2a_baseline_v01_pilot_6h_april16/
```

Files:

| File | Purpose |
|---|---|
| `rpki_event_sidecar.parquet` | event-level RPKI origin evidence |
| `rpki_candidate_sidecar.parquet` | candidate-level RPKI sidecar joined by `event_id` |
| `rpki_prefix_origin_lookup_audit.csv` | unique prefix-origin lookup audit |
| `rpki_status_distribution.csv` | event-level status distribution |
| `rpki_event_sidecar_preview.csv` | 1000-row preview |
| `rpki_clean0_summary.json` | machine-readable summary |
| `rpki_clean0_report.md` | lightweight output report |

Outputs are experiment artifacts and should not be committed.

## 5. Full Run Results

Inputs:

- event rows: `3431103`;
- candidate rows: `3431103`;
- VRP records: `530187`;
- VRP metadata aligned to run date: `true`;
- unique prefix-origin pairs checked: `351104`.

Join quality:

| Metric | Value |
|---|---:|
| event sidecar rows | `3431103` |
| candidate sidecar rows | `3431103` |
| candidate sidecar join rate | `1.0` |

RPKI status distribution:

| Status | Count |
|---|---:|
| `valid` | `1860464` |
| `unknown` | `1413696` |
| `missing` | `149491` |
| `invalid_length` | `4854` |
| `invalid_asn` | `2598` |

Evidence state distribution:

| Evidence state | Count |
|---|---:|
| `aligned_medium` | `1867916` |
| `aligned_weak` | `1413696` |
| `unavailable` | `149491` |

## 6. Interpretation

RPKI is now event/candidate-ready under the same clean sidecar style as AS-rel and communities.

Important boundaries:

- `invalid_asn` and `invalid_length` are origin-authorization evidence, not attack truth.
- `valid` is not benign.
- `unknown` means no covering VRP, not normal.
- `missing` means the event lacks a usable lookup key, not benign and not unknown.

## 7. Current Limits

- This sidecar validates only prefix-origin authorization, not AS-path legality.
- It does not handle temporal ROA changes inside the six-hour window; it uses the aligned daily snapshot already materialized for `2024-04-16`.
- It does not prove low false positive, attack recall, or poisoning/evasion robustness.
- It should be combined with AS-rel and community sidecars only after the benchmark / label protocol defines valid claims.

## 8. Next Step

The three baseline clean evidence channels are now available at event/candidate granularity:

- RPKI / VRP origin authorization;
- CAIDA AS-rel path diagnostics;
- communities / NO_EXPORT attributes.

Recommended next step:

```text
R-LABEL-0:
Define the multi-attack benchmark / label protocol before foreground validation or learning.
```

No learning, production suppression, or final paper metric should proceed before that label protocol exists.
