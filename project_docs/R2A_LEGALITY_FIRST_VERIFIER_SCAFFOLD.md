# R-2A Legality-First Verifier Scaffold

Last updated: 2026-05-17

Status: scaffold + 50k smoke completed. This is not a full verifier and not final attack judgment.

## 1. Goal

R-2A is the first implementation step after Phase R / R-1.

Goal:

```text
legacy incident queue
  -> legality/evidence-aware verifier table
  -> R-1 evidence states
  -> R-1 verdict candidates
  -> confidence caps
  -> abstain/conflict/unavailable/stale reasons
  -> provenance
```

R-2A does not modify legacy detector outputs. It writes a new output table only.

## 2. Research Gap

R-2A directly responds to the Phase R reframing:

- public monitor-only detector output should not be the final judge;
- RPKI / ROA is origin validation only;
- RPKI invalid is not confirmed attack;
- RPKI valid is not confirmed benign;
- route leak and path manipulation require path-legality evidence;
- unavailable, stale, or conflicting evidence must remain explicit instead of being hidden by detector score.

## 3. Why Legality-First Before Full Multi-Evidence

Full multi-evidence verification requires aligned RPKI, IRR, ASPA/BGP Roles, AS relationship, and possibly operator/data-plane evidence.

Current S3-D2/S3-D2B results show that aligned 2024 evidence caches are incomplete:

- no aligned 2024 RPKI/ROA cache is available locally;
- the available CAIDA AS relationship file is `20170701.as-rel2.txt`, stale for a 2024 run;
- known-event matches are not time-aligned for the S2 2024 window.

Therefore R-2A starts with a legality-first scaffold:

- expose missing/stale evidence as verifier states;
- preserve path abnormal and route-leak queues for future legality checks;
- avoid unsupported suspicious/benign claims;
- prepare the schema for R-2B once aligned evidence cache is available.

## 4. Inputs

Fixed run:

- `s2a_expanded_v01_pilot_6h_april16`

Required inputs:

- `outputs/s3d_verification_queue_schema_v01/s3d_incident_verification_queue.parquet`
- `data/runs/s2a_expanded_v01_pilot_6h_april16/incidents/incident_tickets.parquet`
- `data/runs/s2a_expanded_v01_pilot_6h_april16/incidents/incident_membership.parquet`

Optional inputs:

- `outputs/s3d2_external_evidence_attachment_v01/s3d2_incident_evidence_table.parquet`
- `data/evidence/rpki/normalized_vrp_2024-04-16.parquet`
- `data/evidence/as_relationships/as_rel_normalized_2024.parquet`
- `data/evidence/irr/irr_route_objects_2024-04-16.parquet`
- `data/known_events/known_event_candidates_v05.json`
- `data/caida/as-relationships/serial-2/20170701.as-rel2.txt`

Missing optional inputs are warnings, not fatal errors.

## 5. Outputs

Smoke output directory:

- `outputs/r2a_legality_first_verifier_smoke_v01/`

Generated files:

- `r2a_summary.json`
- `r2a_incident_verifier_table.parquet`
- `r2a_incident_verifier_table.csv`
- `r2a_verdict_distribution.csv`
- `r2a_evidence_state_distribution.csv`
- `r2a_confidence_cap_distribution.csv`
- `r2a_abstain_cases.csv`
- `r2a_conflict_cases.csv`
- `r2a_external_unavailable_cases.csv`
- `r2a_route_leak_patternB_candidates.csv`
- `r2a_report.md`

The smoke output is intentionally separate from the future full output directory.

## 6. Verdict Rules

R-2A uses only the R-1 verdict set:

- `strongly_supported_suspicious`
- `evidence_supported_suspicious`
- `evidence_conflict`
- `evidence_insufficient`
- `external_evidence_unavailable`
- `background_like_but_unconfirmed`
- `stale_evidence_only`
- `abstain`

Scaffold rule order:

1. `evidence_conflict` if any evidence state is conflicting.
2. `strongly_supported_suspicious` only if multiple aligned external evidence sources exist with no conflict and no stale-only path.
3. `evidence_supported_suspicious` only if monitor evidence has at least one aligned external support source.
4. `background_like_but_unconfirmed` for low-support background-like queues.
5. `stale_evidence_only` for path-relevant incidents supported only by stale relation evidence.
6. `external_evidence_unavailable` when monitor evidence exists but core external evidence is unavailable.
7. `evidence_insufficient` when monitor signal exists but evidence support remains weak.
8. `abstain` when the state machine cannot safely produce another verdict.

## 7. Confidence Caps

R-2A inherits R-1 caps:

- monitor-only: max `0.45`
- stale diagnostic only: max `0.40`
- evidence insufficient: max `0.50`
- evidence conflict: max `0.55`, and cannot be suspicious
- aligned medium evidence: max `0.75`
- aligned strong consistent evidence: max `0.90`

The smoke run produced no `strongly_supported_suspicious` verdicts, which is the safer result given missing aligned evidence caches.

## 8. Hard Safety Rule Inheritance

R-2A enforces:

- RPKI invalid is not confirmed attack.
- RPKI valid is not confirmed benign.
- Public monitor-only evidence cannot produce `strongly_supported_suspicious`.
- Stale evidence cannot produce a strong verdict.
- Unavailable evidence cannot imply benign.
- P3 / low / background is not confirmed normal.
- Learning layer cannot override verifier safety rules.
- Evidence conflict must remain visible.
- Poisoning-susceptible evidence lowers confidence or requires extra support.
- Abstain is allowed.

## 9. Relationship To R-1

R-1 defines the state machine and allowed vocabulary.

R-2A implements the first scaffold against that vocabulary:

- evidence states are checked against the R-1 set;
- verifier verdicts are checked against the R-1 set;
- learning eligibility values remain conservative;
- provenance is written as JSON per incident.

## 10. Relationship To Learning Layer

R-2A does not train a model.

Learning remains postponed because:

- verifier verdicts are candidate states, not ground truth;
- unavailable and stale evidence are common;
- background-like is not a negative label;
- no reviewed / verifier-supported training target exists yet.

The only safe learning role after R-2A is future incident-level ranking or confidence calibration.

## 11. Smoke Result

Command:

```powershell
python scripts/run_r2a_legality_first_verifier_scaffold.py ^
  --run-id s2a_expanded_v01_pilot_6h_april16 ^
  --output-dir outputs/r2a_legality_first_verifier_smoke_v01 ^
  --s3d-output-dir outputs/s3d_verification_queue_schema_v01 ^
  --s3d2-output-dir outputs/s3d2_external_evidence_attachment_v01 ^
  --legacy-as-rel-file data/caida/as-relationships/serial-2/20170701.as-rel2.txt ^
  --run-date 2024-04-16 ^
  --sample-rows 50000
```

Key smoke results:

- processed incidents: `50000`
- `strongly_supported_suspicious`: `0`
- `evidence_supported_suspicious`: `0`
- `stale_evidence_only`: `43335`
- `external_evidence_unavailable`: `3762`
- `background_like_but_unconfirmed`: `1485`
- `evidence_insufficient`: `1418`
- RPKI status: `unavailable=50000`
- path legality state: `stale_diagnostic=44632`, `not_applicable=5368`
- stale evidence rows: `44807`
- unavailable evidence rows: `50000`
- conflict rows: `0`
- abstain rows: `0`

Interpretation:

R-2A successfully converts legacy incidents into a verifier table, but does not verify attacks. The dominant result is evidence insufficiency/staleness, which is exactly the point of the Phase R reframing: missing or stale evidence must remain visible.

## 12. Current Limitations

- No aligned 2024 RPKI cache was used.
- No aligned 2024 AS relationship / ASPA / BGP Roles cache was used.
- The 2017 CAIDA AS-rel file is diagnostic only.
- IRR cache was unavailable.
- Known-event inventory was not provided to the R-2A smoke command; S3-D2 known-event fields were reused where present.
- No poisoning/evasion benchmark is run in R-2A.
- No full verifier claim is made.

## 13. Next Steps

Recommended order:

1. R-2B legality-first verifier refinement using aligned evidence caches when available.
2. Evidence cache completion for `2024-04-16` RPKI/ROA and 2024-near AS relationship data.
3. R-3 poisoning/evasion benchmark after legality behavior is stable.

Do not launch new detector-score experiments before R-2B is explicitly started.
