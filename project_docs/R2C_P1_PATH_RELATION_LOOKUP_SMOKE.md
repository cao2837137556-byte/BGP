# R-2C-P1 Path Relation Lookup Smoke

Status: fixed S2 full smoke completed.

Run id: `s2a_expanded_v01_pilot_6h_april16`

Run date: `2024-04-16`

AS relationship snapshot: `2024-04-01`

Output directory: `outputs/r2c_p1_path_relation_lookup_smoke_v01/`

## 1. Goal

R-2C-P1 attaches the 2024-near CAIDA AS relationship cache from R-2C-P0b back to AS-pair, AS-triplet, full-path, and incident-level path evidence.

This is still a smoke stage. It does not implement a formal route-leak verifier, does not output confirmed route leaks, and does not modify R-2B verifier verdicts.

## 2. Why Attach AS-rel Back to Incidents

R-2B attached aligned VRP/RPKI origin evidence, but origin authorization cannot validate AS-path legality, route leaks, or path manipulation. R-2C-0 showed that fixed S2 incidents have usable path/triplet/AS-pair lookup keys, and R-2C-P0b materialized a 2024-near CAIDA AS relationship cache.

R-2C-P1 is the bridge between that cache and incident-level verifier logic. It creates path relation evidence with provenance and explicit safety boundaries.

## 3. Why This Is Not a Route-leak Verifier

CAIDA AS relationship data is inferred evidence. Even with a 2024-near snapshot, it is not route-leak truth.

Therefore:

- AS-rel matched does not mean path benign.
- AS-rel unmatched does not mean path suspicious.
- A possible valley/peer-transit transition is diagnostic only.
- No `confirmed_route_leak` or equivalent verdict is generated.
- R-2B verifier verdicts remain unchanged.

Formal route-leak/path-legality behavior is deferred to R-2C-P2 after this smoke output is reviewed.

## 4. Method

### AS-pair Lookup

The script reads `r2c_as_pair_targets.parquet`, expands each adjacent AS pair, and joins against:

```text
data/evidence/as_relationships/as_rel_2024-04-01.parquet
```

Output:

- `r2c_as_pair_relation_lookup.parquet`
- `r2c_as_pair_relation_lookup.csv`
- `r2c_as_pair_relation_summary.json`

### Triplet Lookup

The script converts each AS triplet into two adjacent pairs and records the relation sequence:

```text
a-b
b-c
```

`possible_valley_transition_flag` is conservative and diagnostic. It is not a route-leak verdict.

Output:

- `r2c_triplet_relation_lookup.parquet`
- `r2c_triplet_relation_lookup.csv`
- `r2c_triplet_relation_summary.json`

### Full-path Relation Sequence

Each representative AS path is converted to a relation sequence. The smoke classifies paths into:

- `fully_known_relation_sequence`
- `partially_unknown_relation_sequence`
- `high_unknown_relation_sequence`
- `possible_valley_transition`
- `too_short_or_unusable`

Output:

- `r2c_full_path_relation_sequence.parquet`
- `r2c_full_path_relation_sequence.csv`
- `r2c_full_path_relation_summary.json`

## 5. Full Fixed S2 Results

AS-pair lookup:

| Metric | Value |
| --- | ---: |
| AS-pair target rows | 216922 |
| expanded AS-pair rows | 421989 |
| matched rows | 399839 |
| unmatched rows | 22150 |
| row-level match rate | 0.947510 |

Relation type distribution:

| relation_type | Count |
| --- | ---: |
| p2c_or_c2p_raw | 270770 |
| p2p | 129069 |
| unknown | 22150 |

Triplet lookup:

| Metric | Value |
| --- | ---: |
| triplet target rows | 205067 |
| possible valley/peer-transit diagnostic rows | 34192 |
| aligned_medium triplet evidence | 185571 |
| aligned_weak triplet evidence | 18084 |
| unavailable triplet evidence | 1412 |

Full-path lookup:

| path pattern class | Count |
| --- | ---: |
| fully_known_relation_sequence | 161992 |
| possible_valley_transition | 34192 |
| high_unknown_relation_sequence | 20738 |
| too_short_or_unusable | 240 |

Mean full-path unknown pair rate: `0.054964`.

## 6. Incident-level Path Evidence

R-2C-P1 generated path evidence for all `217165` fixed S2 incidents.

Path evidence state:

| path_evidence_state | Incident count |
| --- | ---: |
| aligned_medium | 161992 |
| diagnostic_only | 34192 |
| evidence_insufficient | 18084 |
| unavailable | 2897 |

Path component purity:

| path_component_purity_class | Incident count |
| --- | ---: |
| path_pure_dominant | 161992 |
| path_mostly_dominant | 34192 |
| path_high_unknown | 20978 |
| path_unusable | 3 |

Diagnostic candidates:

- route-leak-like diagnostic candidates: `34555`
- path-manipulation-like diagnostic candidates: `44189`

These are review candidates, not route-leak or attack labels.

## 7. Origin + Path Combined Evidence

Combined class distribution:

| combined_origin_path_evidence_class | Count |
| --- | ---: |
| origin_valid_path_suspicious | 108583 |
| origin_unknown_path_suspicious | 86980 |
| background_like_combined | 14603 |
| insufficient_combined_evidence | 6337 |
| path_supported_only | 521 |
| origin_path_conflict | 86 |
| origin_and_path_supported | 46 |
| origin_supported_only | 9 |

Recommended action distribution:

| recommended_r2c_verifier_action | Count |
| --- | ---: |
| upgrade_to_path_review_candidate | 195563 |
| keep_insufficient_wait_more_evidence | 20940 |
| candidate_for_r2c_p2_verifier | 567 |
| mark_conflict_for_review | 86 |
| keep_r2b_verdict | 9 |

These actions are next-step hints for R-2C-P2. They do not change R-2B verifier verdicts.

## 8. Top-K Path-review Smoke

The Top-K path review queue is deterministic and model-free.

| Top-K | route_leak_like_diagnostic | path_supported | combined_supported | review_density |
| ---: | ---: | ---: | ---: | ---: |
| 50 | 50 | 50 | 45 | 0.90 |
| 100 | 100 | 100 | 95 | 0.95 |
| 500 | 500 | 500 | 495 | 0.99 |

This suggests path evidence can produce a dense review queue, but it is not a trained ranking result.

## 9. Hard Safety Guardrails

- No route-leak verdict was generated.
- R-2B verifier verdicts were not modified.
- AS-rel was not treated as ground truth.
- Possible valley-free or peer-transit flags were not treated as confirmed route leaks.
- NO_EXPORT / communities were not executed in this stage.
- AS Hegemony was not executed in this stage.
- Learning was not trained.

## 10. Relationship to CCF-A Target Line

R-2C-P1 strengthens the multi-attack-family verifier branch. RPKI/VRP origin evidence alone cannot support route-leak or path-manipulation claims; R-2C-P1 creates the path relation evidence layer needed for a CCF-A-level verifier.

The stage also preserves the CCF-A guardrail: evidence is explicit, inferred evidence is not truth, and diagnostic candidates remain separated from final verdicts.

## 11. Current Limits

R-2C-P1 does not include:

- ASPA;
- BGP Roles / OTC;
- NO_EXPORT / communities;
- AS Hegemony;
- data-plane evidence;
- poisoning/evasion benchmark;
- learning layer training.

CAIDA `-1` orientation remains raw-orientation evidence. Any later valley-free verifier must define direction semantics explicitly.

## 12. Next Step

Proceed to R-2C-P2 route-leak/path-legality verifier smoke. R-2C-P2 should consume:

- `r2c_incident_path_evidence_table.parquet`
- `r2c_combined_origin_path_evidence_table.parquet`
- `r2c_route_leak_like_diagnostic_candidates.csv`
- R-2B VRP-aware verifier outputs

ASPA / BGP Roles / OTC feasibility should be added before any stronger route-leak legality claim. Learning remains design-only until verifier-supported targets and robustness scenarios exist.
