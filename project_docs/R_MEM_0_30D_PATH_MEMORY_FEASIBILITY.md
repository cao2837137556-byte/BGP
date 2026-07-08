# R-MEM-0 30d Path-Memory Sidecar Feasibility Audit

Status: completed read-only feasibility audit.

## Goal

R-POISON-2 showed a concrete poisoning weakness: the
`pair_path_manipulation_history_poisoning_v01` adversarial variant was
suppressed after crafted history washed out path novelty. R-POISON-2A explained
the retained pairs and showed that current retention is not a general poisoning
robustness proof. R-FOREGROUND-4A then showed that a broad recent-recurrence
guard is too expensive.

R-MEM-0 answers the next design question:

```text
Should foreground repair use a 30-day path-memory sidecar before changing the
online policy?
```

The answer is yes. A 6h window is a smoke/debug window. It cannot establish
long-term path maturity. The repair should use a longer historical sidecar that
separates mature natural recurrence from short-lived crafted recurrence.

## Boundary

This phase does:

- scan local source parquet metadata;
- estimate 30-day source volume from available local 2024-04-16 coverage;
- define the path-memory sidecar feature contract;
- define online micro-batch replay semantics;
- update the next experiment order.

This phase does not:

- download 30 days of BGP data;
- materialize the 30-day sidecar;
- run the old seven-layer pipeline;
- modify `online_path_pressure_v1`;
- train learning;
- claim 30-day maturity from local 6h data.

## Why 30 Days

Foreground poisoning repair needs to distinguish:

- a path seen naturally over many days;
- a path that appears only shortly before the attack;
- a single-collector or short-lived churn artifact;
- a crafted prelude intended to poison public-monitor-derived history.

The project should not treat "seen in the current 6h window" as a mature route.
Thirty days is a practical first formal memory window: it is large enough to
observe recurrence and collector diversity, but small enough to materialize as a
sidecar before moving to 90/300-day robustness validation.

## Deployment Model

The online model should be:

```text
current BGP update micro-batch
  -> event/evidence sidecars
  -> foreground policy
  -> lookup 30-day path-memory sidecar
  -> suppress / retain / gray-zone decision
```

The 30-day history is not foreground input. It is a stateful memory table.

This matches public BGP data practice:

- RIPE RIS publishes update dumps every 5 minutes;
- RouteViews update dumps are commonly modeled as 15-minute windows;
- real systems should report per-batch foreground load, not just one offline
  aggregate compression ratio.

## Local Audit Result

Script:

```text
scripts/audit_r_mem0_30d_path_memory_feasibility.py
```

Output:

```text
outputs/r_mem_0_30d_path_memory_feasibility_v01/
```

Summary:

- target date: `2024-04-16`;
- requested history window: `2024-03-18` to `2024-04-16`;
- local unique dates in requested window: `1`;
- local collectors in requested window:
  `route-views.eqix`, `route-views.isc`, `route-views.sg`, `route-views2`,
  `rrc00`, `rrc01`, `rrc03`, `rrc10`, `rrc18`, `rrc19`, `rrc21`, `rrc23`;
- local coverage covers requested 30d window: `false`;
- source parquet files scanned: `3,235`;
- source raw files ready for path-memory key derivation: `2,312`;
- observed target-date raw rows: `94,312,168`;
- observed target-date raw parquet bytes: `855,827,425`;
- estimated 30d raw rows for same collector set: `1,741,147,710`;
- estimated 30d raw parquet bytes for same collector set:
  `15,799,890,900`.

Important nuance:

Raw files usually do not store `origin_as` explicitly, but they contain
`as_path`. The path-memory sidecar may derive origin from the final AS in a
normalized AS path, but the provenance must say `derived_from_as_path`.

## Sidecar Feature Contract

The R-MEM-1 sidecar should expose at least:

- `path_memory_key`: prefix + origin AS + normalized AS path signature;
- `first_seen_ts`;
- `last_seen_ts`;
- `active_days`;
- `active_micro_batches`;
- `collector_days`;
- `burstiness_score`;
- `maturity_bucket`.

Recommended maturity buckets:

- `mature`;
- `recent_only`;
- `short_lived`;
- `sparse`;
- `unavailable`.

Maturity is suppression-permission evidence:

```text
mature recurrence can support suppression;
recent or immature recurrence blocks confident suppression;
neither state is attack/benign truth.
```

## Online Evaluation Metrics

Future foreground repair should report:

- overall compression;
- per-5m or per-15m foreground load;
- per-batch p50 / p90 / p99 foreground rows;
- attack retention by family;
- adversarial attack retention by paired poisoning/evasion template;
- suppressed attack count;
- gray-zone count;
- sidecar lookup coverage;
- sidecar stale/unavailable rate;
- runtime per batch.

## Stop Rules

Do not enter a formal R-FOREGROUND-4B claim unless:

- 30-day source files are materialized or the subset is explicitly bounded;
- path-memory keys are joinable to current events;
- sidecar provenance records derived origin;
- sidecar cost fits HPC resources;
- the targeted guard repairs the path poisoning miss without reverting to
  blanket retention;
- compressed foreground still meets the current operational target.

## Recommended Next Step

R-MEM-1:

```text
materialize a 30-day path-memory sidecar on HPC
```

Then:

```text
R-FOREGROUND-4B targeted path-memory poisoning guard smoke
```

Do not train learning before this repair is validated.

## Outputs

- `r_mem0_summary.json`
- `r_mem0_source_file_inventory.csv`
- `r_mem0_collector_date_coverage.csv`
- `r_mem0_30d_volume_estimate.csv`
- `r_mem0_path_memory_feature_contract.csv`
- `r_mem0_online_replay_plan.csv`
- `r_mem0_report.md`
