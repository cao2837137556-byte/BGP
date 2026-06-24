# PROJECT DECISION REGISTER

Last updated: 2026-06-24

Status: active project-level research decision register.

## Purpose

This document records project-level research decisions, architecture boundaries, naming constraints, experiment ordering, and reviewer-risk defenses.

It exists to prevent important decisions from being scattered across chat history or one-off task reports. New topical documents can still exist, but key decisions must be folded back into this register and the mainline documentation set: `README.md`, `HANDOFF.md`, `EXPERIMENT_MAINLINE.md`, `VERIFIER_REDESIGN_ROADMAP.md`, and `CCFA_TARGET_LINE_AND_EXPERIMENT_GUARDRAILS.md`.

R-DOC-1 is a documentation consolidation step. It does not run experiments, modify verifier outputs, download evidence, train learning, or change code logic.

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
