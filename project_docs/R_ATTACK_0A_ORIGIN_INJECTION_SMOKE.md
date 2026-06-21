# R-ATTACK-0A Controlled Origin Injection Smoke

Date: 2026-06-21

Status: smoke passed for raw admission, event construction, candidate retention,
provenance, and aligned evidence attachment. This is not a paper-grade recall
result.

## 1. Question

R-ATTACK-0A asks a narrow question:

```text
Can controlled exact-prefix and forged-origin records enter through the raw
BGP schema, form auditable events, survive the legacy candidate comparison
gate, and receive newly attached time-aligned evidence?
```

It does not ask whether the system already detects real attacks, achieves low
false positives, or withstands poisoning/evasion.

## 2. Scientific Boundaries

- The source 6h window is reference background, not confirmed benign truth.
- Truth comes only from the separate controlled-injection registry and raw
  label sidecar.
- Truth-only columns are not inserted into production-like raw parquet.
- RPKI, AS-rel, communities, candidate flags, and future foreground outputs are
  evidence or policy outcomes, not truth labels.
- Documentation ASNs are synthetic attacker roles. They do not imply that a
  real AS performed an attack.
- The legacy candidate layer is evaluated only as a comparison gate. It is not
  frozen as the final foreground extractor.
- The old R-NOISE-1 output is not evaluated because it contains forbidden
  workflow-label guards. Clean foreground validation remains pending.

## 3. Inputs and Scenarios

Source background run:

```text
s2a_baseline_v01_pilot_6h_april16
```

Derived run:

```text
s2a_attack0a_origin_smoke_6h_april16_v01
```

The source contains 144 raw chunks and 7,200,000 rows. The derived full run
contains 7,200,024 rows:

- 16 attack-phase announcements;
- 8 injected stable/recovery control announcements;
- 132 unchanged chunks represented by hard links;
- 12 independently rewritten chunks containing controlled records.

Two public-visible scenarios were defined:

| Scenario | Prefix | Legitimate origin | Synthetic attacker | Mechanism |
|---|---|---:|---:|---|
| `r_attack0a_exact_origin_001` | `192.67.68.0/24` | 30382 | 64496 | replace the final origin |
| `r_attack0a_forged_origin_001` | `64.7.160.0/19` | 13549 | 64497 | insert attacker before the legitimate final origin |

Both victim prefix-origin pairs were observed in both collectors during the
reference window and were RPKI-valid before injection.

## 4. Materialization Contract

Configuration:

```text
configs/r_attack0a_origin_smoke_v01.yaml
```

Materializer:

```text
scripts/materialize_r_attack0a_origin_smoke.py
```

The configuration is JSON syntax stored in a YAML-compatible file. This avoids
adding a new PyYAML runtime dependency.

Each scenario contains:

- stable baseline phase;
- attack launch phase;
- recovery phase;
- collector-specific path and peer templates;
- expected public visibility in `route-views.sg` and `rrc00`;
- versioned evidence binding.

Attack announcements deliberately carry an explicit empty community list.
This makes the smoke deterministic but does not mean community absence is safe,
benign, or evidence against stealth behavior.

## 5. Smoke Scope

An attempted full 6h event rebuild remained CPU-active for nearly one hour
without producing a complete event artifact. The unfinished process was
terminated before downstream use.

The accepted smoke therefore reads only the 12 rewritten raw chunks containing
controlled records:

- raw rows: 600,024;
- event rows: 384,828;
- candidate rows: 384,828.

This scope is sufficient for raw admission and attack propagation testing. It
is not a full-window workload, compression, false-positive, or recall result.
The full derived 6h run remains materialized for a later qualified replay.

## 6. Propagation Results

| Metric | Result |
|---|---:|
| Injected raw rows | 24 |
| Injected attack rows | 16 |
| Attack raw/event admission rate | 1.0 |
| Events containing injected members | 12 |
| Attack events | 4 |
| Candidate-marked attack events | 4 |
| Candidate attack retention rate | 1.0 |
| RPKI attack-event join rate | 1.0 |
| AS-rel attack-event join rate | 1.0 |
| Community attack-event join rate | 1.0 |
| Guardrail violations | 0 |

Each scenario produced two attack events, one per collector-specific path.
All attack records were mapped back to exact event membership.

## 7. Mechanism-Specific Evidence Response

### Exact-prefix origin hijack

- RPKI status: `invalid_asn` for both attack events;
- candidate reasons include unseen origin and unseen path;
- AS-rel diagnostic: partially unknown relation sequence due to the synthetic
  attacker edge;
- community state: observed with no community tokens.

### Forged-origin hijack

- RPKI status: `valid` for both attack events because the legitimate origin
  remains at the end of the path;
- candidate reasons include unseen exact/path history, but not unseen origin;
- AS-rel diagnostic: partially unknown relation sequence due to the synthetic
  attacker edge;
- community state: observed with no community tokens.

This contrast is the intended mechanism check:

```text
RPKI can distinguish the exact-origin construction here, but does not expose
the forged-origin construction. RPKI valid is therefore not benign truth.
```

AS-rel unknown edges are expected for documentation ASNs and are not route-leak
truth. NO_EXPORT was not injected and was not detected in these four attack
events; its absence is not a safety claim.

## 8. What Passed and What Did Not

Passed:

- raw schema compatibility;
- immutable source/derived-run separation;
- separate truth sidecar;
- stable/attack/recovery provenance;
- exact raw-to-event membership reconstruction;
- candidate comparison-gate retention;
- aligned 2024 RPKI attachment;
- 2024-near AS-rel attachment;
- raw community re-join;
- mechanism-specific RPKI response.

Not yet passed:

- full 6h end-to-end replay;
- clean foreground retention;
- realistic attacker-AS/path selection without documentation-AS shortcuts;
- hard-negative discrimination;
- route leak, path manipulation, stealth, NO_EXPORT, or poisoning scenarios;
- real-world recall;
- low false-positive performance;
- learning.

## 9. Outputs

Uncommitted experiment outputs are under:

```text
outputs/r_attack_0a/s2a_attack0a_origin_smoke_6h_april16_v01/
```

The derived raw run is under:

```text
data/runs/s2a_attack0a_origin_smoke_6h_april16_v01/
```

Key audit files:

- `materialization_summary.json`;
- `injected_raw_truth.parquet`;
- `smoke/events/event_units.parquet`;
- `smoke/candidates/candidate_events.parquet`;
- `smoke/evidence/`;
- `smoke/audit/r_attack0a_summary.json`;
- `smoke/audit/scenario_propagation_audit.csv`;
- `smoke/audit/scenario_evidence_response_audit.csv`.

Large data and output artifacts are not committed.

## 10. Decision and Next Step

R-ATTACK-0A passes as a development smoke only.

The next action is:

```text
R-ATTACK-QA-0:
audit scenario realism, synthetic shortcuts, phase semantics, membership
correctness, evidence expectations, and the execution plan for a qualified
full-window replay.
```

Do not enter learning or claim foreground safety from this result. Clean
foreground retention must be tested later against controlled attacks under a
new policy that does not use legacy workflow labels as guards.
