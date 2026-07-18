# PROJECT DECISION REGISTER

Last updated: 2026-07-15

Status: active project-level research decision register.

## Purpose

This document records project-level research decisions, architecture boundaries, naming constraints, experiment ordering, and reviewer-risk defenses.

It exists to prevent important decisions from being scattered across chat history or one-off task reports. New topical documents can still exist, but route-changing conclusions must be folded back into this register and `MAINLINE_STATE.md`. The older README/HANDOFF/roadmap documents are navigation or historical references, not per-experiment ledgers.

R-DOC-1 is a documentation consolidation step. It does not run experiments, modify verifier outputs, download evidence, train learning, or change code logic.

## Dual-partition HPC Execution Contract

**Decision:** Queue each approved formal HPC task separately on AMD and Intel
with the same immutable scientific input and one shared logical `pair_id`, but
with partition/job-specific output, temporary, log, checkpoint, and package
paths.

**Rationale:** Either partition may start substantially earlier. Dual submission
reduces queue latency without allowing concurrent jobs to overwrite one
another or silently change the experiment contract.

**Consequence:** The user normally cancels the later-starting copy. If both run
or finish, both must remain valid and their scientific summaries must be
compared. They are redundant executions, not independent samples, replicates,
or extra evidence for a paper claim. Shared evidence and raw inputs remain
read-only. Overwrite flags are not an isolation mechanism.

**Status:** active for future HPC submissions.

## HPC Resource and Fail-fast Decision

**Decision:** Size HPC requests from measured workload needs and require a
bounded real-input liveness gate before a queued formal parser job.

**Rationale:** R-MEM-1C job `151319` consumed about `0.117` CPU seconds during
an hour of wall time and never returned the first BGP element. More CPU, memory,
or wall time would hide an I/O/runtime startup defect rather than improve the
experiment.

**Consequence:**

- do not request larger resources without throughput or memory evidence;
- run syntax/import checks, a real-input first-element probe, and a short smoke
  before formal work;
- require `sbatch --test-only` and the repo preflight to pass before submission;
- require startup and first-element heartbeats, hard timeouts, checkpoints, and
  atomic outputs;
- treat HPC code trees as potentially archive-only: Git metadata is optional,
  while a content fingerprint over executable code and config is mandatory;
- do not rerun a failed command unchanged;
- formal jobs must answer a scientific question, not discover quoting, path,
  dependency, or parser-startup failures.

**Status:** active long-term engineering guardrail.

## R-MEM-1C Single-file Liveness Decision

**Decision:** Insert a two-format, dual-backend liveness gate before repeating
the R-MEM-1C complete-file parser smoke.

**Rationale:** The failed four-file attempt established a stall before the
first element, but did not distinguish a PyBGPStream wrapper issue from a
libBGPStream/WandIO/container issue. The official `bgpreader` CLI provides a
same-library reference path on the same immutable bytes.

**Consequence:** Probe one Route Views `.bz2` and one RRC00 `.gz` with the
documented PyBGPStream single-file configuration and `bgpreader`, cap each at
`100` elements and `60` seconds, write no Parquet, and use only `1` CPU / `2 GB`
for at most `10` minutes. If only `bgpreader` works, repair the Python wrapper;
if neither works, qualify a maintained alternative parser. Complete-file work
is prohibited until liveness passes.

**Status:** passed on HPC job `151381`; source integrity and all four
backend-format liveness probes passed in four seconds.

## R-MEM-1C Local MRT Parser Qualification Decision

**Decision:** Gate the full 10-day parse with a deterministic four-archive
HPC-local smoke: the first and last archive from Route Views SG and RRC00.

**Rationale:** Archive count, SHA256, and compression validation prove transfer
integrity but do not prove that the selected BGPStream runtime preserves update
timestamps, prefixes, AS paths, communities, and source provenance. A bounded
full-file parse catches parser/runtime/schema failures before a costly full run.

**Consequence:**

- stream provider-compressed MRT directly; do not materialize decompressed MRT;
- recheck selected input byte size and SHA256 against the frozen manifest;
- derive origin only from an unambiguous final singleton ASN and leave AS_SET or
  confederation endings null with explicit provenance;
- require both collectors, in-window timestamps, prefix/AS-path coverage, and a
  list-valued communities column;
- reject capped debug runs as formal evidence;
- do not modify foreground, train learning, or treat parsed rows as truth.

**Status:** completed. Jobs `151396/151397` each parsed `2/2` complete archives
and `966,702` rows; all source-integrity and schema gates passed.

## R-MEM-1D Checkpointed 10-day Materialization Decision

**Decision:** Stream all `3,840` immutable provider-compressed MRT archives
directly into Parquet using 20 collector-day tasks. Do not create an
uncompressed MRT copy and do not queue a separate four-file smoke.

**Rationale:** R-MEM-1C already qualified complete-file parsing on both
collectors and measured sufficient one-CPU throughput. Each real collector-day
task can perform a first/last archive boundary parser precheck before its
middle files, so a separate queue cycle would add delay without adding a
distinct scientific check. This precheck is parser/data QA only; it does not
filter routing rows or make attack/background judgments.

**Consequence:**

- process first archive, last archive, then chronological middle files;
- use per-file atomic Parquet and JSON checkpoints;
- allow same-job requeue to resume only after output-size/checkpoint validation;
- require exactly 20 collector-day summaries and 3,840 unique source, audit,
  and Parquet records before promotion;
- submit isolated AMD and Intel arrays with one logical pair ID;
- use measured resources: 1 CPU, 2 GB, 2 hours per task, concurrency 4;
- build the path-memory sidecar only after one partition validates completely;
- do not attach evidence, alter foreground, create truth, or train learning.

**Status:** implementation and local contract tests passed; HPC execution is
next.

### R-MEM-1D-R1 Incremental Recovery Amendment

**Decision:** Preserve and revalidate every completed R-MEM-1D Parquet, parse
only missing archives, and separate archive-container timing from row event
time. Do not rerun the complete 10-day parse from zero.

**Rationale:** The first dual-partition execution established that RRC00 and
the MRT parser are healthy. Its failure was concentrated in the Route Views
archive-boundary gate: across `490` parsed Route Views archives, only `31`
files contained bounded spill, totaling `94` rows with a maximum offset of
`13` seconds. The completed outputs have no observed parse, schema, or source
integrity failure. Discarding them would add compute without improving the
scientific contract.

**Consequence:**

- adopt an old output only after checkpoint status, source size/SHA flags,
  Parquet byte size, footer row count, and exact schema all pass;
- use hard links so adoption does not duplicate large data;
- make adoption resumable if a job stops between link creation and checkpoint
  promotion;
- keep all rows and use row `ts` for downstream time windows;
- allow only empirically bounded archive spill, then compare spill rows with
  adjacent archives and stop on any potential duplicate;
- stop if spill occurs at an outer dataset boundary without an adjacent guard
  archive; missing data cannot establish non-duplication;
- require exact `3,840`-source manifest coverage and re-open every Parquet
  footer before promotion;
- run isolated AMD and Intel copies with measured resources; either copy must
  remain independently valid.

**Status:** HPC recovery completed independently on AMD and Intel. Each produced
`3,840` Parquets. Final qualification stopped on the same `83` adjacent-archive
base-fingerprint matches and now proceeds to R-MEM-1D-QA2.

### R-MEM-1D-QA2 Observation Identity Amendment

**Decision:** Do not delete or canonicalize adjacent-archive fingerprint
matches until raw MRT replay recovers peer identity and reconciles exact row
multiplicity.

**Rationale:** R-MEM-1D-R1 found `83` reproducible base-fingerprint matches,
but the current Parquet schema records `peer_asn` without `peer_address`.
Different peers in one ASN can therefore collapse to the same current
fingerprint. The arbitrary per-file spill-rate threshold also cannot decide
whether the observations are duplicates.

**Consequence:**

- preserve both complete 3,840-file materializations unchanged;
- replay only implicated raw archives and recover peer address plus available
  router identity;
- canonicalize communities order for QA fingerprinting;
- classify same-identity overlap separately from distinct-peer collision;
- if identities differ, add peer address to the canonical observation schema;
- if all identities match, design a non-destructive overlap-exclusion sidecar;
- stop on unresolved raw/Parquet multiplicity;
- do not build path memory before observation identity is qualified.

**Status:** completed. QA2 replayed 28 implicated raw archives and classified
84 candidates: 43 exact archive-overlap candidates, 6 distinct-peer
collisions, and 35 mixed-identity overlaps. All 258 matches recovered
`peer_address`; the old fingerprint is not safe for deletion.

### R-MEM-1E Peer-aware Canonical Schema Amendment

**Decision:** Promote `peer_address` into canonical observation schema v2 and
derive a stable `observation_id` from the semantic update payload plus peer
address. Keep source provenance outside the observation identity and keep
deduplication separate from parsing.

**Rationale:** The QA2 result proves that identical old fingerprints can
represent both same-peer archive overlap and legitimate observations from
different peer sessions. The R-MEM-1E contract smoke identifies exactly 80
same-peer duplicate copies while preserving 91 distinct-peer neighbor
observations, with zero missing peer identities or ID mismatches.

**Consequence:**

- preserve R-MEM-1D-R1 outputs as immutable v1 artifacts;
- require explicit `--schema-version v2` for peer-aware rematerialization;
- never auto-deduplicate a row whose peer address is missing;
- materialize source-complete v2 rows before creating a reversible canonical
  deduplication view;
- do not build the path-memory sidecar from v1 observations.

**Status:** schema contract and targeted smoke passed locally; full v2
materialization and whole-window validation are next.

### 10-day Background Contamination Boundary

**Decision:** Treat the 10-day Route Views / RIS window as
`unlabeled_operational_background`, never as certified benign or attack-free
data.

**Rationale:** Public monitors report real routing observations but do not
provide complete attack ground truth. Absence from a known-event list, RPKI
validity, an AS-rel match, or absence of NO_EXPORT cannot prove benignness.

**Consequence:** After v2 materialization, run a provenance-recorded
contamination audit and quarantine known, suspicious, or unresolved intervals
through a sidecar. The strongest allowed statement is "no known or identified
incident under the declared audit sources." Controlled injection and confirmed
historical replay remain the truth-bearing evaluation tracks.

**Status:** active guardrail; contamination audit follows v2 qualification.

## R-MEM-1B Direct Archive Acquisition Decision

**Decision:** Acquire the 10-day canonical raw MRT window on the local
egress-capable host through the working proxy, then transfer immutable archives
and manifests to HPC for local parsing.

**Rationale:** HPC array `149909` timed out after eight hours with zero source
outputs. Bounded probe `150551` then showed Broker request timeouts and external
stream timeouts for both Route Views and RIS from compute nodes. Local proxy
checks reached the real Route Views SG and RRC00 archive objects. Increasing
Slurm wall time would repeat an egress failure rather than answer the research
question.

**Consequence:**

- keep the frozen 6h repository data in place for reproducibility;
- place new large raw MRT and derived history assets under the external data
  root identified by `configs/data_catalog_v1.json`;
- require a deterministic 3,840-file plan for `2024-04-07` through
  `2024-04-16`;
- require source URL, byte size, SHA256, compressed-stream validation, atomic
  partial files, and durable receipts;
- do not parse or materialize the sidecar until the acquisition manifest is
  complete;
- use HPC for local compute after transfer, not for blocked internet access.

**Result:** The final dataset contains `3,840/3,840` archives (`960` Route
Views SG and `2,880` RRC00), spans all ten requested UTC dates, and totals
`16,502,107,268` bytes. Final all-file SHA256 and compressed-stream
revalidation passed with zero failures and zero residual partial files.

**Status:** completed; R-MEM-1C post-transfer verification and bounded
HPC-local parsing is next.

## R-MEM-1A Acquisition Gate

**Decision:** Treat remote BGP source acquisition as a separately qualified
infrastructure contract before using it for path-memory evidence.

**Rationale:** The first 10-day collection array (`149909`) timed out at the
eight-hour task limit with zero update parquet files and zero day summaries.
The current collector performs a broker-backed PyBGPStream call before it can
write a checkpoint, so a larger wall time would not establish reliable data
acquisition.

**Consequence:** Run a bounded compute-node probe that separates Broker DNS /
metadata access from one real Route Views and one real RIS update retrieval.
Do not restart the 10-day collection until the failure layer is known and the
collector has a per-window timeout, checkpoint manifest, and retry contract.

**Status:** completed infrastructure stop-loss; superseded by R-MEM-1B local
direct archive acquisition.

## Current Locked Architecture

The paper-facing architecture is locked as:

```text
Stage 1: Monitor-triggered Incident Construction
  -> Stage 2: Evidence-constrained Verification
  -> Stage 3: Component-aware Learning Triage
  -> Top-K Review Queue
```

### Stage 1: Monitor-triggered Incident Construction

Plain meaning: make the case file.

Responsibilities:

- construct incidents and components from raw BGP updates;
- preserve weak signals, historical deviation, visibility evidence, path structure, legacy score/gate/augment context;
- extract lookup keys for external evidence;
- provide monitor-side hints for later verification and ranking.

Not responsible for:

- final attack judgment;
- benign judgment;
- ground truth labels.

`high/needs/low` and `P1/P2/P3` are not truth.

### Stage 2: Evidence-constrained Verification

Plain meaning: check the evidence.

Responsibilities:

- attach versioned evidence such as RPKI/VRP, CAIDA AS-rel, future communities/NO_EXPORT, and future ASPA/BGP Roles/OTC;
- preserve provenance, confidence caps, missing evidence, stale evidence, and conflicts;
- output evidence-supported, conflict, insufficient, unavailable, background-like, or abstain states.

Not responsible for:

- confirmed attack labels;
- confirmed benign labels;
- hiding uncertainty inside a score.

### Stage 3: Component-aware Learning Triage

Plain meaning: learn the review order.

Responsibilities:

- sit after the verifier and before Top-K;
- consume unified incident cards from Stage 1 and Stage 2;
- estimate `review_priority_score`, `topk_rank`, component priority, evidence consistency, split priority, and `recommended_action`;
- reduce human review burden under verifier hard rules.

Not responsible for:

- overriding verifier hard rules;
- confirmed attack/benign classification;
- formal training before the output schema and evidence provenance are stable.

### Top-K Review Queue

The Top-K Review Queue is the final human-facing output. It is produced after the learning layer. Top-K is not the learning layer itself.

## Stage 1 vs Stage 2 Boundary

Stage 1 is the trigger, organizer, and weak signal provider. Stage 2 is the evidence verifier and provenance-aware evidence attachment layer.

The same field or data source can appear in both stages without being redundant, because the responsibility is different.

Example: AS-rel in Stage 1:

- legacy weak structural feature;
- helps trigger path-related candidates;
- means "worth checking";
- Stage 1 weak trigger, not truth.

Example: AS-rel in Stage 2:

- versioned external path evidence;
- uses the 2024-near CAIDA AS-rel cache when aligned;
- means "evidence supports, is insufficient, conflicts, or is unavailable";
- Stage 2 verifier evidence, not route-leak truth.

This is not duplication. It is evidence reuse with different roles. But the evidence version must be recorded. Final main experiments should use a consistent AS-rel cache across Stage 1-derived path fields and Stage 2 verifier evidence, or report drift/impact analysis.

## Unified Output Taxonomy Decision

The final output must not use category explosion. Evidence combinations should not become top-level incident categories.

Forbidden main categories include:

- `origin_valid_path_suspicious`
- `no_export_route_leak_origin_xxx`
- `rpki_unknown_path_suspicious`

The unified output schema is:

- `primary_family`
- `secondary_families`
- `observability_mode`
- `verifier_state`
- `evidence_tags`
- `confidence_cap`
- `review_priority_score`
- `topk_rank`
- `recommended_action`
- `why_not_confirmed`

`evidence_tags` carry evidence combinations. They do not manufacture new attack labels.

## Primary Family Taxonomy

The locked `primary_family` set is intentionally small:

- `forged_origin_like`
- `route_leak_like`
- `path_manipulation_like`
- `stealth_evasion_like`
- `mixed_or_conflict`

`forged_origin_like` must explicitly exist. It must not be blurred into `origin_hijack_like`.

`weak_signal` is not an attack category. It belongs to `observability_mode`.

`background_or_insufficient` is not an attack family. It should be expressed through `verifier_state`, `review_bucket`, or `recommended_action`.

## Observability Mode

Locked `observability_mode` values:

- `strong_signal`
- `weak_signal`
- `stealth_signal`
- `mixed_signal`

`forged_origin_like + weak_signal` is one of the core output combinations for this project. It captures the original weak-signal research thread without turning weak evidence into ground truth.

`stealth_signal` may be supported by NO_EXPORT, low visibility, collector asymmetry, or related monitor-evasion evidence after retention and provenance are repaired.

`mixed_signal` usually means component refinement, conflict handling, or abstention is needed.

## Verifier State

Locked `verifier_state` values:

- `evidence_supported_suspicious`
- `evidence_conflict`
- `evidence_insufficient`
- `external_evidence_unavailable`
- `background_like_but_unconfirmed`
- `abstain`

`strongly_supported_suspicious` is not a default main output now. It should appear only if future evidence is strong enough, such as operator confirmation, reliable data-plane validation, or stronger path-legality evidence.

`background_like_but_unconfirmed` is not confirmed benign.

`evidence_supported_suspicious` is not confirmed attack.

## Evidence Tags

`evidence_tags` are extensible evidence carriers, not new categories.

Current and future examples:

- `new_origin_as`
- `prefix_origin_not_in_history`
- `rpki_invalid_asn`
- `rpki_invalid_length`
- `rpki_unknown`
- `path_relation_diagnostic`
- `possible_valley_transition`
- `high_unknown_path`
- `no_export_present`
- `no_advertise_present`
- `low_visibility`
- `collector_asymmetry`
- `component_pure`
- `component_mixed`
- `evidence_conflict`
- `short_duration`

Tags support filtering, ranking, explanation, and ablation. They do not define truth.

## Component Purity Decision

Component purity is an incident purity audit.

Plain model:

- incident = parent case / case bag;
- component = concrete fragment inside the case bag.

Do not split Stage 1 incidents too finely at the beginning. The current strategy is:

1. Stage 1 performs coarse aggregation into incidents and members.
2. Stage 2 performs component purity and refinement.
3. If a mixed pattern appears repeatedly and predictably, feed it back into Stage 1 splitting rules later.

This avoids premature over-engineering while preserving reviewer-safe component awareness.

## Abstain Handling Decision

`abstain` is not a manual garbage bin.

Allowed post-abstain routes:

- split component;
- wait for more evidence;
- conflict queue;
- low-priority sampling;
- high-impact Top-K only.

Forbidden interpretations:

- send every abstain case to analysts;
- treat abstain as the system "shrugging";
- treat abstain as benign;
- treat abstain as attack.

Abstention is a reliability mechanism.

## Communities / NO_EXPORT Decision

R-2D-0 found:

- raw updates retain a `communities` field;
- `NO_EXPORT`, `NO_ADVERTISE`, and `NOPEER` are parseable at raw layer;
- `event_units`, `incident_membership`, and `incident_tickets` currently do not retain communities;
- communities cannot currently be joined to incident/member/component;
- R-2D-1 must not start as an incident-level stealth verifier until retention is repaired.

Design principles:

- do not copy full raw communities blindly into every incident card;
- raw layer keeps full communities;
- event/member layer should carry lightweight flags, counts, and hashes;
- incident/component layer should aggregate share, entropy, and core-share;
- verifier layer should consume only `stealth_evidence_state` and provenance-ready summaries;
- `NO_EXPORT` present is not confirmed attack;
- `NO_EXPORT` absent is not safe;
- low visibility is not confirmed `NO_EXPORT`.

## AS-rel Consistency Decision

Stage 2 already uses the 2024-near CAIDA AS-rel cache:

- snapshot: `2024-04-01`;
- run date: `2024-04-16`;
- delta: `15` days.

Early Stage 1 artifacts may use legacy 2017 AS-rel, unknown AS-rel placeholders, or no substantive AS-rel dependency. This creates evidence consistency risk for final main experiments.

Decision:

- real systems should use a unified versioned evidence cache;
- Stage 1 AS-rel use must record snapshot and role;
- Stage 2 AS-rel use must record snapshot and role;
- if Stage 1 and Stage 2 snapshots differ, perform drift/impact analysis or aligned replay before final main-result claims.

Current repo note:

- R-CONSIST-1 has already audited this risk and found Stage 1 likely used legacy `2017-07-01` defaults while Stage 2 uses `2024-04-01`;
- recommended follow-up is `R-CONSIST-2 aligned reannotation`, escalating to aligned Stage 1 replay only if candidate/gate/incident outputs change.

## Learning Layer Decision

Do not train the learning layer now.

Learning must wait until:

- unified incident card schema is stable;
- evidence provenance is attached;
- R-CONSIST risks are resolved or explicitly documented;
- communities / NO_EXPORT propagation design is clear if stealth evidence is used;
- poisoning/evasion scenarios exist for robustness evaluation.

Learning input:

- unified incident card;
- verifier state;
- component purity;
- evidence tags;
- confidence caps;
- monitor-side weak/context signals;
- provenance and availability fields.

Learning output:

- `review_priority_score`;
- `evidence_consistency_score`;
- `component_priority_score`;
- `should_split_score`;
- `topk_rank`;
- `recommended_action`.

Learning must not output confirmed attack/benign labels and must not override hard verifier rules. Its target is Top-K triage, not an ordinary attack classifier.

Learning before Top-K means:

```text
Stage 2 verifier
  -> Stage 3 learning ranker / calibrator
  -> Top-K Review Queue
```

## Near-term Roadmap Decision

Near-term decision order:

1. R-DOC-1: record the discussion outcomes and decision boundaries.
2. R-OUT-1: Unified Incident Output Taxonomy Design.
3. R-CONSIST-1: Stage 1 AS-rel provenance / alignment audit.
4. R-2D-P0-design: Communities propagation schema design.
5. R-2D-P0-repair: repair communities propagation from raw to event/incident.
6. R-3: Poisoning / evasion benchmark design.
7. L1: Component-aware semantic learner design.

Current repo note:

- R-CONSIST-1 has already completed before R-DOC-1 was consolidated.
- The remaining near-term choices are therefore R-OUT-1, R-CONSIST-2 aligned reannotation, and R-2D-P0-design.

R-CONSIST and R-2D-P0 ordering can be adjusted by future research-control decisions, but both must be resolved before formal learning training.

Do not keep adding external evidence indefinitely. Do not train learning while schema and provenance are unstable.

## R-AGG-ENTRY-0 Raw Incident Entry Decision

Status: active.

Decision:

- Raw Incident Dossier construction must be preceded by an entry point audit.
- Do not default to `final-entry` or the old final-level 21w ticket aggregation.
- Use `candidate-entry` as the current recommended main entry for Raw Incident construction.
- Use `event-entry` as an auxiliary recall / raw observability reference.
- Use `scored-entry` only as an auxiliary diagnostic upper bound, not as truth.
- Avoid `gated-entry`, `augmented-entry`, and `final-entry` as primary Raw Incident entries because they carry increasing judgment contamination.

Rationale:

- final labels are weak workflow signals, not truth labels.
- high/needs/low are workflow outputs, not ground truth.
- P1/P2/P3 are priority hints, not ground truth.
- final/gate/augment layers already encode old system decisions, so using them as the first Raw Incident representation risks circularly reproducing the old detector.
- The new system needs Raw Incident Dossier first, then Evidence-grounded Incident, then verifier/triage outputs.

Consequence:

- The old seven-layer chain becomes a weak-signal source and lookup-key extraction path, not a truth producer.
- Raw Incident Dossier can include `family_hint`, `trigger_reasons`, aggregation keys, and uncertainty fields, but these are hints, not verdicts.
- background-like is operational suppression, not confirmed benign.
- family_hint is semantic hint, not confirmed attack label.
- R-AGG-1 should design the Raw Incident Dossier schema before final incident aggregation or learning starts.

Long-term decisions attached to R-AGG-ENTRY-0:

- poisoning benchmark retained as a core evaluation asset for public-monitor incomplete / poisonable settings.
- learning layer postponed until Raw Incident Dossier and Evidence-grounded Incident schemas are stable.
- Future learning must target semantic representation, prioritization, calibration, and component ranking, not legacy rule re-scoring.
- Future learning should be compatible with BEAM-style semantic learning ideas, while remaining downstream of verifier hard rules.
- no truth label should be produced at Raw Incident construction time.

Updated near-term order:

1. R-AGG-1: Raw Incident Dossier schema design.
2. Evidence-grounded Incident construction and provenance attachment.
3. R-OUT-1: unified incident output taxonomy tightening if needed.
4. R-CONSIST-2 / R-2D-P0 repairs where evidence provenance or community propagation blocks final claims.
5. R-3 poisoning / evasion benchmark.
6. L1 component-aware semantic learner design.

## R-AGG-1 Raw Incident Dossier Schema Decision

Status: active.

Decision:

- Raw Incident Dossier schema v0 uses candidate-entry as the primary source.
- `configs/raw_incident_dossier_schema_v0.yaml` is the active schema design artifact.
- `scripts/prototype_raw_incident_schema_mapping.py` is a mapping preview, not a final aggregation script.
- final-entry remains only a comparison/reference source.

Rationale:

- candidate-entry balances weak-signal context and low judgment contamination.
- candidate-entry preserves prefix, origin AS, AS path, collector, and candidate reason fields needed for later evidence grounding.
- scored/gated/augmented/final entries carry increasing legacy judgment contamination.
- final labels are weak workflow signals, not truth labels.

Consequence:

- Raw Incident Dossier schema v0 contains nine field groups: identity, time_scope, routing_object, observation_scope, aggregation_explanation, weak_semantic_hint, structure_quality, legacy_reference, and downstream_hooks.
- family_hint is semantic hint, not attack label.
- background-like is operational suppression, not confirmed benign.
- legacy score/gate/final fields can be recorded only under `legacy_reference`, not used as truth.
- Evidence-grounded Incident construction starts only after Raw Incident schema is stable.
- R-AGG-2 should prototype aggregation and repair time scope via event-entry join or upstream retention.

Current mapping preview:

- sample source: `s2a_baseline_v01_pilot_6h_april16` candidate-entry;
- sampled rows: `5000`;
- schema field coverage: `0.904762`;
- required field missing rate: `0.075059`;
- available lookup keys: `prefix_origin_key`, `as_path_signature`, `collector_set`, and `candidate_reason_set`;
- `time_scope` is not ready because candidate-entry lacks `start_time` / `end_time`.

Long-term guardrails:

- no truth label at Raw Incident construction time;
- poisoning benchmark retained as a core robustness evaluation path;
- learning layer postponed until Raw Incident Dossier and Evidence-grounded Incident schemas are stable;
- future learning should target BEAM-style semantic learning for incident/component/evidence representation and prioritization, not legacy rule re-scoring.

## R-AGG-2 Raw Incident Prototype Aggregation Decision

Status: active.

Decision:

- Raw Incident prototype aggregation uses candidate-entry as the primary source.
- event-entry is used only for time/observation repair, primarily through `event_id` exact join.
- score/gate/augment/final remain auxiliary references, not aggregation entry points.
- final-entry is not the main Raw Incident source.

Rationale:

- candidate-entry balances low judgment contamination and weak-signal context.
- event-entry preserves original `first_seen` / `last_seen` / collector observation details that candidate-entry lacks.
- R-AGG-1 showed candidate-entry time_scope readiness was `0.0`; R-AGG-2 repairs this by joining event-entry.
- Keeping the aggregation key conservative reduces over-aggregation risk for the first prototype.

Consequence:

- R-AGG-2 produces Raw Incident prototype records, not final review tickets.
- Prototype key v0 is intentionally conservative: `prefix_origin_key + as_path_signature + family_hint + collector_set + time_bucket_key`.
- The baseline run produced `3128971` prototype raw incidents from `3431103` candidate rows, compression ratio `1.09656`.
- time_scope coverage improved to `1.0` through exact event join.
- The low compression ratio means R-AGG-3 must audit under-aggregation before Evidence-grounded Incident consumes this table.
- family_hint is semantic hint, not attack label.
- background-like remains operational suppression, not confirmed benign.

Current result:

- run: `s2a_baseline_v01_pilot_6h_april16`;
- candidate rows: `3431103`;
- event rows: `3431103`;
- raw incidents: `3128971`;
- time repair: `exact_join=3128971`;
- family_hint distribution: `mixed_unknown=1707486`, `stealth_visibility_like=1406742`, `forged_origin_like=14743`;
- evidence_grounding_ready_rate: `0.948727`.

Next:

- Prefer R-AGG-3 aggregation quality audit before Evidence-grounded Incident design.
- R-AGG-3 should decide whether to add a full raw incident membership table and whether any safe coarser grouping is justified.
- poisoning benchmark retained.
- learning layer postponed and must target BEAM-style semantic learning, not legacy rule re-scoring.

## R-AGG-3 Raw Incident Aggregation Quality Decision

Status: active.

Decision:

- Before optimizing Raw Incident aggregation, run aggregation quality audit.
- R-AGG-3 audits key_fragmentation, background-like operational candidates, merge opportunities, high-value retention risk, and family_hint quality.
- No safe merge or pre-incident filter should be implemented before audit evidence and family_hint mapping repair.
- R-AGG-3 does not change R-AGG-2 aggregation logic and does not produce a truth label.

Rationale:

- R-AGG-2 proved candidate-entry construction and event-entry time repair, but compression is only `1.09656x`.
- The low compression ratio means the prototype is still close to candidate-row granularity.
- Directly returning to final-entry would reintroduce old judgment contamination.
- background-like is operational suppression candidate, not confirmed benign.
- family_hint is semantic hint, not attack label.

Consequence:

- candidate-entry remains the Raw Incident primary source.
- R-AGG-3 estimates safe merge opportunity without executing any merge.
- R-AGG-3 estimates pre-incident filter pressure without implementing background suppression.
- High-value weak signals must be explicitly protected before any background filter or coarser merge is allowed.
- Future learning remains postponed and must target BEAM-style semantic learning for representation/prioritization, not legacy rule re-scoring.

Current result:

- run: `s2a_baseline_v01_pilot_6h_april16`;
- raw incidents: `3128971`;
- estimated best safe group count: `1793817`;
- estimated best safe compression ratio: `1.912739`;
- possible_background_like_count: `3114228`;
- possible_background_like_rate: `0.995288`;
- high_value_candidate_count: `3118030`;
- risky_suppression_count: `3103287`;
- mixed_unknown_count: `1707486`.

Key interpretation:

- `prefix_origin_key` alone offers high apparent compression (`10.707374x`) but carries high over-merge risk.
- `prefix_origin_key + family_hint + dominant_as_path_signature` offers lower-risk compression around `2.088168x`.
- mixed_unknown is mostly a family_hint mapping / priority issue, not missing core lookup keys.
- Because possible background-like rows overlap heavily with high-value weak-signal candidates, a pre-incident filter is needed as a design problem but is not safe to implement blindly.

Next:

- Prefer R-AGG-4 family_hint mapping repair before safe merge / pre-incident filter design.
- Then run a focused safe merge key design or aggregation quality re-audit before Evidence-grounded Incident consumes the Raw Incident table.
- poisoning benchmark retained.
- learning layer postponed and must target BEAM-style semantic learning.

## R-EVID-0 Lightweight Evidence Pre-Triage Decision

Status: active.

Decision:

- Before implementing compression, design lightweight evidence-aware pre-triage.
- R-EVID-0 defines three audit-only states: `protected_suspicious`, `suppressible_background_like`, and `gray_zone_retained`.
- No suppression, deletion, safe merge, or R-EVID-1 implementation should proceed before evidence-aware protection rules pass stop-loss.
- RPKI and AS-rel/path diagnostics may support triage protection, but they are not truth labels.

Rationale:

- R-AGG-3 showed background-like and high-value signals heavily overlap.
- A naive background filter would suppress many weak-signal cases that are exactly the cases the project wants to preserve under partial observability.
- Lightweight evidence can act as a guardrail before compression, but only if it reduces risky overlap instead of hiding it.
- External GPT-style plans are treated as broad direction; final implementation must follow local data, provenance, and safety constraints.

Consequence:

- No suppression before evidence-aware protection rules are audited.
- R-EVID-0 samples detailed audit rows but computes full-population counts and rates.
- `protected_suspicious` means "do not suppress without stronger evidence", not confirmed attack.
- `suppressible_background_like` means "future low-priority candidate", not benign and not deletion.
- `gray_zone_retained` means evidence is insufficient for either protection or suppression.
- Learning remains postponed and must target BEAM-style semantic learning over evidence-grounded incidents, not attack/benign classification or rule re-scoring.

Current result:

- run: `s2a_baseline_v01_pilot_6h_april16`;
- raw incidents: `3128971`;
- RPKI coverage: `0.550384`;
- AS-rel/path diagnostic event join: `1.0`;
- communities / NO_EXPORT in Raw Incident: `0.0`;
- protected_suspicious: `2908323` (`0.929482`);
- suppressible_background_like: `0` (`0.0`);
- gray_zone_retained: `220648` (`0.070518`);
- protected_background_overlap: `2893580` (`0.92477`);
- mixed_unknown_rate: `0.545702`.

Stop-loss:

- triggered: `protected_background_overlap_rate_too_high`;
- triggered: `risky_suppression_rate_too_high`;
- triggered: `family_hint_mixed_unknown_rate_too_high`;
- decision: `do_not_enter_R_EVID_1_yet`.

Next:

- Prefer R-AGG-4 family_hint mapping repair.
- Rerun R-EVID-0 after mapping repair.
- Only then consider R-EVID-1 evidence pre-triage smoke, still with no deletion and no truth labels.
- RPKI invalid is not attack truth.
- AS-rel diagnostic is not route leak truth.
- background-like is not benign.

## R-RESET-1 Mainline Pivot Decision

Status: active.

Decision:

- Move incident aggregation after multi-attack judgment.
- `full candidate-entry incident aggregation stopped` as the paper-facing mainline.
- Use R-AGG/R-EVID as stop-loss evidence, not as failed or deleted work.

Rationale:

- Candidate-first aggregation caused `3.13M` raw incidents and compression ratio `1.09656`.
- R-AGG-3 found possible background-like rate `0.995288`, but high-value weak signals heavily overlapped.
- R-EVID-0 found `protected_suspicious_rate=0.929482`, `suppressible_background_like_rate=0.0`, and `protected_background_overlap_rate=0.92477`.
- Therefore full candidate-entry aggregation and direct pre-triage compression are not safe first-stage mainline designs.

Consequence:

- New mainline is a `noise-filtered multi-attack judgment pipeline`.
- Pipeline order becomes: raw/candidate events -> obvious noise suppression / foreground extraction -> multi-attack judgment layer -> incident aggregation after judgment -> evidence explanation -> poisoning/evasion robustness evaluation.
- Background is not ranked in the primary human-facing output; it is summarized, sampled, and audited.
- background-like / background_noise is not confirmed benign.
- Suspicious / attack-like events are aggregated after judgment.

## R-RESET-1 Learning Layer Decision

Status: active.

Decision:

- Learning layer is a multi-attack judgment layer, not semantic ranking.
- It is not a single attack/benign classifier.

Rationale:

- Ranking does not solve operational decision or background explosion.
- The paper needs low false positive foreground judgment under incomplete and poisonable monitors.
- Learning must preserve abstain / uncertain behavior and evidence explanation.

Consequence:

- Learning output must include attack family / background / uncertain / poisoning-suspected judgments:
  - `suspicious_forged_origin`;
  - `suspicious_route_leak`;
  - `suspicious_path_manipulation`;
  - `suspicious_stealth_visibility`;
  - `poisoning_or_evasion_suspected`;
  - `background_noise`;
  - `uncertain_need_evidence`.
- These are operational judgments, not truth labels.
- Future learning must be deployable, low false positive, robust to poisoning/evasion, and explainable enough for routing security context.

## R-RESET-1 Poisoning / Evasion Decision

Status: active.

Decision:

- Poisoning/evasion robustness is a core paper problem.
- `poisoning/evasion robustness is core`, not an appendix experiment.

Rationale:

- Public-monitor-only systems can be poisoned or evaded.
- NO_EXPORT / communities / collector asymmetry can change what public monitors observe.
- Traditional monitor-only anomaly detectors can either miss stealth events or overreact to crafted background-like artifacts.

Consequence:

- Poisoning benchmark must be designed before final model claims.
- Evaluation must include low false positive behavior, false-negative / must-keep miss risk, background compression, per-family coverage, and poisoning/evasion robustness.
- R-NOISE-0 is the next step before learning or incident aggregation implementation.

## R-NOISE-0 Obvious Noise Separability Decision

Status: active.

Decision:

- Before implementing foreground extraction, run an obvious noise separability audit with counterfactual suppression policies.
- R-NOISE-0 must prove that obvious background-like rows can be suppressed without suppressing multi-attack must-keep signals.
- The recommended first smoke policy is `policy_A_very_conservative`, not the most aggressive policy.

Rationale:

- R-EVID-0 showed that lightweight evidence pre-triage failed stop-loss when applied after candidate-first Raw Incident aggregation.
- R-NOISE-0 moves back to candidate-entry event rows and tests separability before aggregation.
- The audit found `3431103` candidate-entry rows, `1812334` must-keep rows (`0.528207`), and `1614840` policy_A suppressible rows (`0.470647`).
- policy_A suppresses `0` must-keep rows, `0` poisoning/evasion-like proxy rows, `0` legacy high rows, and `0` legacy needs rows.

Consequence:

- The next step is `R-NOISE-1 conservative foreground extraction smoke using policy_A_very_conservative with must-keep guards`.
- policy_C remains an upper-bound stress test only.
- Suppressed rows are operational background candidates, not confirmed benign.
- final/high/needs/low remain workflow references, not truth.
- RPKI invalid is not attack truth.
- AS-rel diagnostic is not route leak truth.
- poisoning/evasion-like proxy rows must be retained until a dedicated poisoning benchmark clarifies robustness behavior.

## R-NOISE-1 Conservative Foreground Extraction Smoke Decision

Status: active.

Decision:

- Convert only `policy_A_very_conservative` into auditable foreground / suppressible / gray views.
- Treat R-NOISE-1 as a clean-window smoke, not a production suppression policy.
- Report `guardrail_violation_count`, not attack `false_negative_count`.

Rationale:

- R-NOISE-0 showed policy_A can counterfactually suppress `1614840` candidate-entry rows without hitting must-keep, legacy high/needs, or poisoning/evasion-like proxy guards.
- The 6h baseline window has no confirmed attack labels, so it cannot validate real attack recall or poisoning/evasion detection.
- A reproducible foreground view is still useful as a prerequisite for multi-attack judgment design, as long as the truth boundary is explicit.

Consequence:

- R-NOISE-1 generated `foreground_candidates.parquet`, `suppressed_background_candidates.parquet`, `gray_zone_retained_candidates.parquet`, and full `candidate_noise_policy_assignment.parquet` under `outputs/r_noise_1/s2a_baseline_v01_pilot_6h_april16/`.
- Candidate rows `3431103` become `1816263` foreground-view rows and `1614840` suppressible operational-background rows, estimated compression `1.889100`.
- `guardrail_failed=false`; suppressed rows contain `0` multi-attack must-keep rows, `0` legacy high rows, `0` legacy needs rows, and `0` poisoning/evasion proxy rows.
- Explicit poisoning/evasion token availability is `unavailable` (`0` rows); available proxy rows are retained, but this is not poisoning/evasion recall.
- `suppressed_background` remains operational background pressure only, not confirmed benign.
- The next steps may be R-LEARN-0 design and R-POISON-0 benchmark design, but no learning training or production suppression claim is allowed before benchmark-backed miss-risk evaluation.

## R-CLEAN-0 Data / Evidence Clean Contract Decision

Status: active.

Decision:

- Establish a clean mainline before any further experiment implementation.
- Future paper-facing experiments must follow `CLEAN_MAINLINE_EXPERIMENT_PLAN.md` and `R_CLEAN_0_DATA_EVIDENCE_CLEAN_CONTRACT.md`.
- R-NOISE-1 is preserved as a provisional clean-window smoke, not a final clean result.

Rationale:

- The paper goal requires low-false-positive multi-attack judgment under incomplete, evasive, and poisonable public monitors.
- That goal cannot be supported if new experiments silently mix aligned RPKI, 2024-near AS-rel, stale 2017 AS-rel-derived fields, raw-only communities, and legacy final labels.
- R-CONSIST-1 showed old Stage 1 AS-rel fields likely use CAIDA `2017-07-01`, while the aligned cache is `2024-04-01`.
- R-2D-0 showed NO_EXPORT/community evidence exists in raw updates but is not retained in event/candidate/incident layers.

Consequence:

- RPKI `2024-04-16` is allowed with truth boundaries: RPKI invalid is not attack truth and RPKI valid is not benign.
- CAIDA AS-rel `2024-04-01` is allowed only through a new clean sidecar; old `rel_seq`, `rel_unknown_cnt`, and `rel_has_unknown` are forbidden in new decisions.
- Raw communities / NO_EXPORT are evidence-available at raw layer but decision-unavailable until sidecar or propagation exists.
- Legacy final/high/needs/low and P1/P2/P3 are audit references only, not labels, hard guards, or learning targets.
- The next dependency order is R-ASREL-CLEAN-0 -> R-COMM-CLEAN-0 -> R-LABEL-0 -> R-ATTACK-0 -> R-NOISE-CLEAN-1 -> R-LEARN-0 -> R-LEARN-1 -> R-INC-0.
- No learning, production suppression, recall claim, or poisoning/evasion robustness claim is allowed before the relevant sidecar and benchmark gates pass.

## R-DOC-GOV-1 Lightweight Mainline Documentation Decision

Status: active.

Decision:

- Maintain only one active mainline state document: `project_docs/MAINLINE_STATE.md`.
- Maintain this file, `project_docs/PROJECT_DECISION_REGISTER.md`, only for major route decisions.
- Keep phase-specific experiment documents as evidence archives.
- Stop updating README, HANDOFF, EXPERIMENT_MAINLINE, CCFA, LEARNING, and VERIFIER documents after every experiment.

Rationale:

- Previous documentation practice spread the same state across too many files.
- That made old experiments contaminate current experiment planning and made it easy for humans or agents to follow superseded routes.
- The project now needs a cockpit-style current state file plus an explicit decision log, not multiple competing mainline summaries.

Consequence:

- Normal experiment maintenance is limited to:
  1. the experiment's own phase document;
  2. `MAINLINE_STATE.md`.
- Major route changes additionally update `PROJECT_DECISION_REGISTER.md`.
- README is a navigation pointer only.
- HANDOFF / EXPERIMENT_MAINLINE / CCFA / LEARNING / VERIFIER remain useful historical or topical references, but are not authoritative if they conflict with `MAINLINE_STATE.md`.
- If future work needs to revive or revise an archived document, that must be an explicit task, not a default side effect of every experiment.

## R-LABEL-0 Multi-Attack Benchmark / Label Protocol Decision

Status: active.

Decision:

- Fix the benchmark and label protocol before any attack generation, foreground validation, or learning.
- Keep `reference_background`, `controlled_injection`, `historical_replay`, and `paired_poisoning_evasion` as separate benchmark tracks.
- Use controlled injection metadata and curated historical reports as label sources.
- Use RPKI, AS-rel, communities / NO_EXPORT, low visibility, candidate reasons, and legacy workflow labels only as evidence or audit references, never as truth.

Rationale:

- The 6h clean window can characterize background pressure, but it cannot prove attack recall or benign truth by itself.
- Controlled injection provides exact labels and per-family coverage.
- Historical replay provides external realism in original time windows with date-aligned evidence.
- Poisoning/evasion must be evaluated as paired adversarial variants against the same clean base scenario.

Consequence:

- Paper-grade attack experiments should inject at raw-update level before event/candidate construction.
- Candidate-level injection is allowed only as a diagnostic smoke.
- Foreground policies are judged as high-recall retention / compression stages, not final detectors.
- The first smoke stop-loss is strict: `suppressed_attack_count` must be `0`.
- Learning remains blocked until labeled scenarios prove raw-to-event, event-to-candidate, and candidate-to-foreground retention.

## R-NOISE-CLEAN-1 Preregistered Evaluation Decision

Status: active.

Decision:

- Freeze foreground evaluation populations, denominators, metrics, and stop-loss
  rules before inspecting the R-ATTACK-0A-3 full-window result.
- Require `suppressed_attack_count=0` and keep gray-zone attacks in downstream
  retained workload.
- Compute background compression only on rows with no injected scenario
  membership; mixed-membership rows are audited separately.

Rationale:

- The queued full replay must not be followed by result-dependent threshold or
  denominator changes.
- The archived R-NOISE-1 smoke used legacy final references and old `rel_*`
  context, so it cannot be reused unchanged in the clean mainline.
- Controlled attack truth, hard-negative lookalikes, scenario controls, and
  reference background have different semantics and must remain separate.

Consequence:

- R-NOISE-CLEAN-1 cannot execute until R-ATTACK-0A-3 artifact validation or a
  documented attack-path qualification decision passes.
- Truth metadata is evaluation-only and forbidden from policy features.
- A safe but operationally useless policy also fails feasibility if reference
  background suppression is below `5%` or gray-zone rate exceeds `50%`.
- Passing this gate supports only an origin-family development smoke, not
  multi-attack, real-world, low-false-positive, or poisoning/evasion claims.

## R-ATTACK-0A-3 Full-Window Qualification Decision

Status: active.

Decision:

- Treat R-ATTACK-0A-3 as qualified for R-NOISE-CLEAN-1 foreground evaluation.
- Preserve the validation fact that the strict global artifact checker reported
  `validated=false` because `community_event_join_1` failed by one background
  row.
- Do not rerun the full replay solely for the one-row global community caveat.

Rationale:

- The completed full replay produced `3,431,117` event rows and `3,431,117`
  candidate rows.
- Candidate attack retention is `1.0`.
- RPKI, AS-rel, and community evidence joins for injected attack events are all
  `1.0`.
- The only failed global check is community raw-match coverage:
  `3,431,116 / 3,431,117` events have a raw match.
- The missing community raw match is a background evidence-availability caveat,
  not an injected attack-path failure.
- Community absence or unavailable state is already forbidden as safe/benign
  evidence.

Consequence:

- R-NOISE-CLEAN-1 may proceed on the qualified full replay.
- The foreground policy must not use community absence or unavailable state as
  a benign/safe guard.
- The caveat must be reported in R-NOISE-CLEAN-1 if community evidence is used.
- This decision does not change R-NOISE-CLEAN-1 denominators, safety gates, or
  stop-loss thresholds.
- This decision does not support low false positive, multi-attack recall,
  poisoning/evasion robustness, or learning claims.

## R-FOREGROUND-0 Candidate-Free Foreground Decision

Status: active.

Decision:

- Remove candidate artifacts from the mainline compression layer.
- Treat `candidate_flag`, `candidate_reasons`, and `matched_rule_count` as
  historical diagnostics / ablation references only.
- Design the next compression audit as candidate-free semantic foreground
  extraction over event rows plus clean evidence sidecars.

Rationale:

- R-ATTACK-0A-3 showed `event rows = candidate rows = 3,431,117`, so candidate
  did not provide meaningful compression.
- R-NOISE-CLEAN-1 passed safety but failed feasibility:
  `suppressed_attack_count=0`, attack retention `1.0`,
  pure reference-background suppression `0.001263748`, and compression ratio
  `1.001265`.
- The failure was caused by an overly conservative policy that treated
  candidate flags and broad candidate reasons as blanket protection.
- Frontline systems suggest better foreground criteria: semantic routing
  changes, clean external evidence, visibility risk, recurrence / rarity, and
  poisoning-aware history caveats.

Consequence:

- The mainline path is now:

```text
raw updates
-> event construction
-> clean evidence ledger
-> semantic foreground extraction
-> learning / deep evidence explanation / incident aggregation
```

- R-FOREGROUND-0 compares multiple candidate-free policies.
- A policy must keep controlled attacks unsuppressed and provide materially
  useful background compression.
- If no policy passes, the project repairs semantic evidence / novelty features
  before expanding attack families or training learning.

## R-FOREGROUND-1 Online Foreground Smoke Decision

Status: active.

Decision:

- Promote the R-FOREGROUND-0 `aggressive_recurrence` policy to
  `online_aggressive_recurrence_v1`.
- Treat it as the current online foreground smoke policy, not as a final
  production suppression system.
- Keep online foreground compression separate from the future offline
  training/evaluation sample-pool construction.

Rationale:

- R-FOREGROUND-0 showed `aggressive_recurrence` is the best passing policy:
  attack retention `1.0`, suppressed attacks `0`, background suppression
  `0.37744629`, and compression ratio `1.606295`.
- A more aggressive policy (`external_only_aggressive`) compressed more but
  suppressed controlled attacks, so it is an unsafe upper-bound stress test.
- The foreground layer should be useful, not merely safe. The current
  origin-family smoke target is background suppression >= `30%`; after
  multi-attack expansion the target becomes >= `50%`, with a stretch target of
  `60%-70%`.

Consequence:

- Hard-negative/control/mixed rows suppressed by the online foreground are not
  automatically policy failures if active attacks are retained.
- Those rows must remain available for a later `R-TRAIN-DATA-0` offline
  training/evaluation pool.
- Suppressed background is operational pressure reduction, not confirmed
  benign.
- The next scientific step after R-FOREGROUND-1 is `R-ATTACK-0B` multi-attack
  controlled scenario expansion, followed by retesting the foreground target.

## R-ATTACK-0B Multi-Attack Controlled Smoke Decision

Status: completed; superseded by R-FOREGROUND-2 compression-improvement audit.

Decision:

- Expand the controlled benchmark directly, without creating another standalone
  protocol-only phase.
- Include exact-origin, forged-origin, route-leak-like, and
  path-manipulation-like attack subtypes in the first multi-attack smoke.
- Embed realism QA and R-FOREGROUND-1 retention QA in the run itself.

Rationale:

- R-FOREGROUND-1 passed only on origin-family attacks. It cannot justify
  learning, poisoning/evasion, or multi-attack claims.
- Route-leak-like scenarios must be AS-rel constrained; otherwise they are just
  random valley-looking paths.
- Path-manipulation-like scenarios must preserve origin and use
  all-known/no-valley AS-rel paths, otherwise the system either learns synthetic
  unknown-edge artifacts or collapses into another route-leak-like case.
- A separate protocol document would add overhead without improving the next
  scientific gate, because the key constraints already exist in R-LABEL and
  R-ATTACK-QA.

Consequence:

- R-ATTACK-0B materializes attacks at raw-update level, recomputes RPKI /
  AS-rel / community sidecars, reruns foreground v1, and reports per-family
  QA.
- Candidate retention is diagnostic only, not a hard mainline compression gate.
- If any controlled attack family is suppressed by foreground v1, foreground
  repair takes priority before learning or poisoning expansion.
- If all families are retained but compression is below the future >=`50%`
  target, design R-FOREGROUND-2.

Result:

- R-ATTACK-0B full replay validated:
  - `validated=true`;
  - `qa_pass=true`;
  - `online_pass=true`;
  - `suppressed_attack_count=0`;
  - `attack_retention=1.0`.
- Exact-origin, forged-origin, route-leak-like, and path-manipulation-like
  controlled attack families were all retained by R-FOREGROUND-1.
- Background suppression remained `0.377447197`, below the future `>=0.50`
  target.

## R-FOREGROUND-2 Policy Improvement Audit Decision

Status: active.

Decision:

- Before learning or poisoning expansion, audit stronger candidate-free
  foreground policies on the validated R-ATTACK-0B replay.
- Treat `suppressed_attack_count=0` and `attack_retention=1.0` as hard safety
  gates.
- Treat background suppression `>=0.50` and compression ratio `>=2.0` as the
  current improvement target.
- Include pressure-test policies, but do not recommend them if they suppress
  controlled attacks.

Rationale:

- R-ATTACK-0B showed multi-attack safety for R-FOREGROUND-1, but not enough
  compression for the intended deployable low-load story.
- The right next step is not learning. Learning would inherit an oversized
  foreground if compression remains weak.
- The right next step is also not blind aggressive filtering. We need to find
  the boundary where compression improves without losing controlled attacks.

Consequence:

- R-FOREGROUND-2 reads existing R-ATTACK-0B event/evidence artifacts and writes
  small audit outputs only.
- It does not retrain learning, add attack families, implement production
  suppression, or use candidate/legacy labels.
- If a recommendable policy passes, it can be promoted to R-FOREGROUND-3 smoke.
- If no policy reaches `>=0.50` without attack suppression, the result is a
  stop-loss that points to feature repair rather than model training.

Result:

- R-FOREGROUND-2 completed on the validated R-ATTACK-0B replay.
- `count3_path2_candidate` was recommendable and safe but below target:
  background suppression `0.434294803`, compression `1.767721`, suppressed
  attacks `0`.
- `path1_pressure_test` reached the current target with background suppression
  `0.510538701`, compression `2.043079`, and suppressed attacks `0`, but it was
  deliberately marked as a pressure test rather than a directly promotable
  policy.
- `external_only_pressure_test` compressed more but suppressed `2` controlled
  attacks and is unsafe.

## R-FOREGROUND-3 Online Path-Pressure Policy Decision

Status: completed; current online foreground baseline frozen.

Decision:

- Formalize the R-FOREGROUND-2 `path1_pressure_test` boundary as
  `online_path_pressure_v1`.
- Rerun it as a single candidate-free online foreground smoke before treating
  it as the current foreground baseline.
- Keep the same hard gates: `suppressed_attack_count=0`,
  `attack_retention=1.0`, background suppression `>=0.50`, and compression
  ratio `>=2.0`.

Rationale:

- A pressure test can reveal a useful boundary, but it should not be promoted
  by interpretation alone.
- R-FOREGROUND-3 makes the boundary explicit, auditable, and reproducible by
  writing full assignment / foreground / suppressed / gray artifacts.
- This protects the project from silently turning an exploratory threshold into
  a mainline result.

Consequence:

- R-FOREGROUND-3 passed and `online_path_pressure_v1` is the current foreground
  baseline for the next controlled-attack expansion.
- The completed run kept `attack_retention=1.0`, `suppressed_attack_count=0`,
  and `truth_feature_leakage_count=0`.
- It reached background suppression `0.510538701` and compression ratio
  `2.043079`.
- Hard-negative, scenario-control, and mixed rows suppressed online are not
  thrown away; they remain candidates for the later offline training/evaluation
  sample pool.
- Suppressed background remains operational workload reduction, not confirmed
  benign.
- This decision does not prove stealth / NO_EXPORT robustness, subprefix
  coverage, historical replay recall, poisoning/evasion robustness, or learning
  readiness.

## R-ATTACK-1 Attack Family Expansion Decision

Status: completed; full 6h replay validated.

Decision:

- Expand the controlled benchmark before learning or poisoning.
- Add realistic subprefix origin hijack and stealth / NO_EXPORT visibility
  scenarios.
- Keep `online_path_pressure_v1` frozen for the first R-ATTACK-1 retention
  check.
- Run a feasibility audit before writing any materializer so attack templates
  come from observed baseline/evidence structure rather than hand-written fake
  rows.

Rationale:

- R-ATTACK-0B covered exact-prefix origin hijack, forged-origin hijack,
  route-leak-like valley, and path-manipulation-like known transit.
- It explicitly deferred subprefix and stealth / NO_EXPORT cases.
- R-FOREGROUND-3 passing on four controlled families is not enough to justify
  learning, historical recall, or poisoning/evasion claims.
- NO_EXPORT is a key monitor-evasion evidence channel, but it is not attack
  truth and cannot be evaluated without explicit observability boundaries.

Consequence:

- The read-only feasibility audit passed:
  - `151374` subprefix parent prefix-origin candidates;
  - `1045` NO_EXPORT events;
  - `764` NO_EXPORT prefix-origin pairs;
  - aligned RPKI / AS-rel / community rows for all `3431103` baseline events.
- Bounded R-ATTACK-1 scenario materialization and 12-chunk smoke QA are now
  implemented:
  - injected raw rows `36`;
  - injected attack rows `12`;
  - injected hard-negative rows `12`;
  - required subprefix and monitor-visible NO_EXPORT / stealth attack subtypes
    are present;
  - normal subprefix deaggregation and normal NO_EXPORT community-use hard
    negatives are present;
  - QA checks `14 / 14` passed;
  - foreground attack retention `1.0`;
  - foreground suppressed attack count `0`.
- The full 6h R-ATTACK-1 replay is now validated:
  - `validated=true`;
  - validation checks `18 / 18` passed;
  - QA checks `14 / 14` passed;
  - event rows `3431117`;
  - candidate rows `3431117`;
  - foreground rows `1679397`;
  - suppressed rows `1751720`;
  - background suppression `0.510540519`;
  - compression ratio `2.043065`;
  - foreground attack retention `1.0`;
  - foreground suppressed attack count `0`;
  - truth feature leakage count `0`.
- Subprefix scenarios must use observed parent prefixes and realistic attacker
  AS choices.
- Stealth / NO_EXPORT scenarios must use recomputed community sidecar evidence
  and distinguish monitor-visible cases from fully invisible observability
  boundary cases.
- The next implementation step is `R-POISON-0` paired poisoning/evasion
  benchmark design, not `R-TRAIN-DATA-0`.
- Historical replay remains required for external validity.
- Paired poisoning/evasion remains core to the paper and can now start because
  the base controlled families are realistic and retained.

## R-POISON-0 Paired Poisoning / Evasion Protocol Decision

Status: completed design; R-POISON-1 materialization may proceed for feasible
pairs only.

Decision:

- Treat poisoning/evasion as paired adversarial variants, not as unpaired extra
  attack rows.
- Separate detection-data poisoning from visibility evasion:
  - detection-data poisoning manipulates public-monitor-derived history,
    novelty, path, link, or routing-role memory before the actual attack;
  - visibility evasion manipulates what public collectors are expected to see,
    for example through NO_EXPORT / collector asymmetry contracts.
- Keep classical AS-path poisoning for traffic engineering as a terminology
  caveat, not the central paper target.
- Require every R-POISON-1 variant to hold the clean base victim, origin,
  attacker, background window, foreground policy, and evidence snapshot fixed.
- Only the explicit poisoning preparation or visibility constraint may change.

Rationale:

- The current controlled families are now realistic enough and retained by
  `online_path_pressure_v1`, so poisoning/evasion design can start.
- Public-monitor-derived systems can fail if history or observability is
  manipulated; this is different from ordinary attack-family expansion.
- A paired benchmark is the only scientifically clean way to measure
  retention drop, novelty-signal drop, knowledge-base drift, and visibility
  effects.
- Unpaired poisoned/evasive rows would blur template realism, background
  differences, evidence snapshots, and denominator definitions.

Result:

- `configs/r_poison0_paired_benchmark_protocol_v01.json` defines six pair
  templates.
- `scripts/audit_r_poison0_feasibility.py` checks clean-base availability,
  validation status, held constants, changed variables, observability
  contracts, denominator policy, poisoning memory targets, drift metrics, and
  forbidden shortcuts.
- The local audit passed overall:
  - `overall_feasible=true`;
  - feasible pairs: `5`;
  - blocked pairs: `1`;
  - covered threat models: `detection_data_poisoning`,
    `visibility_evasion`;
  - base validations available and passing for R-ATTACK-0B and R-ATTACK-1.
- The blocked pair is `pair_route_leak_policy_poisoning_v01`, deliberately
  held at design-only because AS-rel diagnostics are not route-leak truth and
  policy semantics need a stricter contract.

Consequence:

- Next step is `R-POISON-1` bounded materialization for feasible pairs only.
- R-POISON-1 must not materialize the route-leak policy poisoning pair until
  the policy-semantics contract is bounded.
- R-POISON-0 produced no attack data, trained no learning model, and changed
  no foreground policy.
- `NO_EXPORT` present remains evidence, not attack truth.
- Public-invisible variants must not be counted as foreground misses unless
  the observability contract says the public monitor should see them.
- Learning remains blocked until poisoned/evasive variants are materialized
  and foreground retention is retested.

## R-POISON-1 Bounded Pair Materialization Decision

Status: completed materialization; adversarial replay still pending.

Decision:

- Materialize only the five R-POISON-0 feasible pairs:
  - exact-origin history poisoning;
  - forged-origin history poisoning;
  - path-manipulation history poisoning;
  - subprefix NO_EXPORT evasion;
  - stealth collector-asymmetry evasion.
- Keep `pair_route_leak_policy_poisoning_v01` blocked because policy semantics
  remain under-specified.
- Treat R-POISON-1 as bounded materialization, not as a full replay or a
  poisoning robustness result.
- Clean-base evidence and foreground status may be inherited from validated
  R-ATTACK-0B / R-ATTACK-1 summaries.
- Adversarial evidence joins and foreground retention must remain
  `pending_replay_validation` until R-POISON-2.

Rationale:

- The paper needs paired clean-vs-adversarial poisoning/evasion evidence, but
  the first materialization step should not be entangled with a 144-file replay.
- The fair-pair contract must be frozen before replay: victim, origin,
  attacker, background window, evidence snapshot, and foreground policy stay
  fixed; only poisoning preparation or visibility constraints may change.
- Claiming poisoned/evasive foreground retention before replay would be a
  scientific error.

Result:

- `scripts/materialize_r_poison1_bounded_pairs.py` writes the bounded asset.
- The local bounded materialization produced:
  - materialized feasible pairs: `5`;
  - truth prototype rows: `33`;
  - variant contract rows: `10`;
  - clean-base validation pass: `true`;
  - fair-pair contract pass: `true`;
  - route-leak policy poisoning skipped: `true`;
  - full replay: `false`;
  - learning trained: `false`;
  - foreground policy changed: `false`.

Consequence:

- Next step is `R-POISON-2` bounded replay for the five materialized feasible
  pairs.
- R-POISON-2 must recompute evidence sidecars and rerun
  `online_path_pressure_v1` without changing the policy.
- Only R-POISON-2 may report clean-vs-adversarial retention drop.
- If R-POISON-2 suppresses an adversarial attack member, foreground repair
  takes priority before learning or historical replay expansion.

## R-POISON-2 Bounded Replay Stop-Loss Decision

Status: completed; stop-loss triggered.

Decision:

- Run a bounded event-level replay for the five R-POISON-1 feasible pairs.
- Use the frozen `online_path_pressure_v1` logic.
- Do not call this a full 6h replay.
- Use the result as a foreground robustness stop-loss gate before learning or
  larger poisoning replay.

Result:

- Pair count: `5`.
- Bounded replay event rows: `10`.
- Clean attack retention mean: `1.0`.
- Adversarial attack retention mean: `0.8`.
- Suppressed adversarial attack events: `2`.
- Stop-loss triggered: `true`.
- The only pair with retention drop is
  `pair_path_manipulation_history_poisoning_v01`:
  - clean retention: `1.0`;
  - poisoned/evasive retention: `0.0`;
  - retention drop: `1.0`;
  - suppressed attack events: `2`.

Interpretation:

- The path-manipulation clean case is retained by novelty.
- The data-poisoned variant simulates that the path signature has already been
  introduced into public-monitor-derived history.
- RPKI remains `valid`.
- AS-rel remains `all_pairs_known_no_valley_diagnostic`.
- There is no NO_EXPORT / community risk signal.
- With novelty washed out and no surviving external risk signal, the frozen
  foreground policy suppresses the poisoned variant as recurrent background.

Consequence:

- This is a real robustness gap in the current foreground layer.
- Do not proceed to learning, historical replay expansion, or larger poisoning
  replay before repair.
- Next step is `R-FOREGROUND-4`:
  repair poisoning-susceptible path-memory foreground protection while
  preserving useful background compression.
- The repair must stay narrow; it should not revert to blanket retention.
- Route-leak policy poisoning remains blocked until policy semantics are
  explicitly bounded.

## R-POISON-2A Retention Reason / Ablation Decision

Status: completed audit; R-FOREGROUND-4 remains the next implementation step.

Decision:

- Do not interpret the four retained R-POISON-2 adversarial pairs as a general
  poisoning-robustness proof.
- Audit retained pairs by their foreground protection reason before changing
  the policy.
- Use counterfactual signal ablation to separate:
  - current foreground failures;
  - single-signal fragile retained pairs;
  - combined-stress fragile retained pairs;
  - retained pairs that survive single-signal removal.
- Keep RPKI, AS-rel, NO_EXPORT, low visibility, and path novelty as evidence
  or diagnostics, not attack truth.

Rationale:

- R-POISON-2 showed one clear miss, but the retained pairs may be retained
  because strong independent evidence remains visible.
- A foreground repair that only patches the failed path-manipulation pair could
  miss fragile retained families.
- A foreground repair that keeps every possible weak signal would destroy the
  compression goal. The project needs a narrow repair with explicit stop-loss
  gates.

Result:

- `scripts/audit_r_poison2a_retention_ablation.py` reads R-POISON-2 bounded
  replay outputs and reruns the frozen assignment under signal masks.
- The local audit produced:
  - pair count: `5`;
  - bounded event rows: `10`;
  - ablation event rows: `80`;
  - adversarial pairs currently retained: `4`;
  - adversarial pairs currently suppressed: `1`;
  - current failure pair:
    `pair_path_manipulation_history_poisoning_v01`;
  - single-signal fragile retained pair:
    `pair_forged_origin_history_poisoning_v01`;
  - combined-stress fragile retained pairs:
    `pair_exact_origin_history_poisoning_v01`,
    `pair_subprefix_noexport_evasion_v01`, and
    `pair_stealth_collector_asymmetry_v01`.

Consequence:

- R-FOREGROUND-4 must first repair the path-memory poisoning failure:
  short-lived crafted recurrence must not be treated as long-term benign
  history.
- The forged-origin retained pair needs a secondary guard before any broad
  robustness claim because it is AS-rel single-signal fragile.
- The exact-origin, subprefix/NO_EXPORT, and stealth pairs can remain retained
  under current bounded evidence, but their protection must be written as an
  evidence-bundle contract, not as standalone poisoning robustness.
- Do not proceed to learning, larger poisoning replay, or historical replay
  expansion before the R-FOREGROUND-4 repair smoke passes the stop-loss gates.

## R-FOREGROUND-4A Path-Memory Maturity Feasibility Decision

Status: completed audit; R-FOREGROUND-4B targeted guard smoke is next.

Decision:

- Repair the R-POISON-2 path-manipulation history-poisoning weakness by
  changing what counts as a suppressible background recurrence.
- Do not add a broad rule that retains every recent recurrence.
- Treat path-memory maturity as suppression-permission evidence only:
  - mature recurrence can support operational background suppression;
  - immature or recent recurrence blocks confident suppression;
  - immature or recent recurrence is not attack truth.
- Do not claim long-term maturity from the supplied foreground artifact alone.
  It only supports within-window maturity proxies.

Rationale:

- R-POISON-2 showed that crafted history can wash out path novelty and cause a
  path-manipulation-like attack to be suppressed.
- R-POISON-2A showed that retained poisoning/evasion pairs are not a general
  robustness proof.
- R-FOREGROUND-4A shows that a broad recent-recurrence guard would damage
  compression too much, so the repair must be targeted.

Result:

- `scripts/audit_r_foreground4a_path_memory_maturity.py` computes path-memory
  maturity proxies and impact estimates from the supplied R-ATTACK-1 /
  R-FOREGROUND-3 assignment artifact.
- Local audit results:
  - assignment rows: `384,839`;
  - unique `prefix_origin_path_key`: `239,939`;
  - current suppressed rows: `184,772`;
  - current suppression rate: `0.480128`;
  - current compression ratio: `1.923551`;
  - suppressed recent-suspicious recurrence proxy rows: `67,758`;
  - share of suppressed rows that are recent-suspicious recurrence proxies:
    `0.366711`;
  - broad guard retaining all recent-suspicious recurrence proxy rows would
    reduce suppression to `0.304060` and compression to `1.436905`;
  - R-POISON-2 path-memory failure is classified as
    `bounded_recent_crafted_history_proxy`;
  - long-term maturity claim supported by current artifact: `false`.

Consequence:

- R-FOREGROUND-4B must implement a targeted path-memory poisoning guard, not a
  general recent-recurrence must-keep.
- R-FOREGROUND-4B should repair
  `pair_path_manipulation_history_poisoning_v01`, keep suppressed attack count
  at `0`, restore adversarial retention to `1.0`, and preserve useful
  compression as much as possible.
- Formal long-term maturity needs a longer historical sidecar. If R-FOREGROUND
  later relies on mature recurrence for strong suppression, the sidecar must
  record first-seen age, long-window span, collector diversity, and recent-vs-
  long-term recurrence separation.

## R-MEM-0 30d Path-Memory Sidecar Feasibility Decision

Status: completed feasibility audit; R-MEM-1 sidecar materialization is next.

Decision:

- Do not repair path-memory poisoning robustness using only the 6h foreground
  artifact.
- Use a 30-day path-memory sidecar before changing the foreground policy.
- Treat 30-day history as a stateful sidecar lookup, not as a one-shot
  foreground input and not as training labels.
- Keep maturity as suppression-permission evidence:
  - mature recurrence can support operational background suppression;
  - recent-only or immature recurrence blocks confident suppression;
  - neither state is attack truth or benign truth.

Rationale:

- R-FOREGROUND-4A showed that broad protection of recent recurrence would
  damage compression too much.
- The poisoning failure is specifically about confusing short-lived crafted
  recurrence with stable path history.
- A 6h window cannot distinguish long-term natural recurrence from an attack
  prelude.
- Front-end compression must be evaluated like an online system: current 5m or
  15m batches query historical memory, rather than consuming all historical data
  as the active foreground input.

Result:

- `scripts/audit_r_mem0_30d_path_memory_feasibility.py` scans local source
  parquet metadata, estimates 30-day sidecar volume, and emits the sidecar
  feature contract.
- Local audit result:
  - target date: `2024-04-16`;
  - requested history window: `2024-03-18` to `2024-04-16`;
  - local dates available in that window: `1`;
  - local collectors on the target date: `12`;
  - source parquet files scanned: `3,235`;
  - source raw files ready for path-memory key derivation: `2,312`;
  - observed target-date raw rows: `94,312,168`;
  - observed target-date raw parquet bytes: `855,827,425`;
  - estimated 30-day same-collector raw rows: `1,741,147,710`;
  - estimated 30-day same-collector raw parquet bytes: `15,799,890,900`.

Consequence:

- R-MEM-1 should materialize the 30-day path-memory sidecar on HPC.
- The sidecar must record origin provenance because raw rows may need to derive
  `origin_as` from the final AS in `as_path`.
- R-FOREGROUND-4B should then use the sidecar for a targeted poisoning guard
  smoke.
- Do not train learning or claim poisoning robustness until the 30-day memory
  sidecar and targeted foreground repair pass.

## R-MEM-1A 10d Canonical Path-Memory Sidecar Decision

Status: implemented; local partial smoke passed; full HPC source collection is
next.

Decision:

- Use a 10-day canonical path-memory sidecar as the functional bridge between
  R-MEM-0 and R-FOREGROUND-4B.
- Keep the first canonical source scope narrow:
  - `route-views.sg`;
  - `rrc00`.
- Use native-like public-data chunking:
  - `route-views.sg` in 15-minute chunks;
  - `rrc00` in 5-minute chunks.
- Keep 30 days as the formal validation target after the 10-day data contract
  works.

Rationale:

- Seven days is too thin for paper-facing maturity claims.
- Thirty days is the right formal direction but should not be the first time
  the source collection and sidecar contract are tested.
- A 10-day smoke is large enough to expose path-memory and source-coverage
  issues while keeping debugging affordable.
- Foreground repair should not proceed from a 6h partial artifact.

Result:

- Added config:
  `configs/r_mem1a_10d_path_memory_v01.json`.
- Added source collector:
  `scripts/collect_r_mem1a_bgpstream_sources.py`.
- Added sidecar materializer:
  `scripts/materialize_r_mem1a_path_memory_sidecar.py`.
- Added HPC wrappers:
  `scripts/hpc/r_mem1a_collect_10d_sources.slurm`;
  `scripts/hpc/r_mem1a_materialize_10d_sidecar.slurm`.
- Local partial materialization smoke passed:
  - selected source files: `8`;
  - input source rows: `400,000`;
  - processed source rows: `374,085`;
  - sidecar rows: `144,541`;
  - maturity bucket: `recent_only=144,541`;
  - complete requested history: `false`.

Consequence:

- The next operational step is to run the HPC source collection array and then
  the sidecar materialization job.
- The local partial smoke proves only the data contract and provenance logic.
  It does not prove 10-day maturity.
- Do not proceed to learning.
- Do not run R-FOREGROUND-4B until the 10-day sidecar is complete and joinable.
