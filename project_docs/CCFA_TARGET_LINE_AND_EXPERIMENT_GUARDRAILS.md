# CCF-A Target Line and Experiment Guardrails

Status: active target-line guardrail.

## 1. Current Target

Main target: CCF-A / top-tier networking or security venue.

SCI Q2 is only a fallback target, not the design target. The project should be designed and evaluated under CCF-A-level expectations. Do not downgrade the problem into a simple rule-based BGP anomaly detector.

## 2. Final System Positioning

English positioning:

Poisoning-robust, evidence-constrained, component-aware semantic triage for BGP routing incidents under partial observability.

Chinese positioning:

部分可观测与公共监控可投毒条件下，面向 BGP 路由事件的证据约束、成分感知、语义分诊系统。

Core principles:

- Public monitor output = trigger, not final judge.
- Incident = case/bag, not ground truth.
- Verifier = evidence boundary and safety layer.
- Learning layer = component-aware semantic ranker/calibrator, not attack/benign classifier.
- Human review = Top-K evidence-supported triage, not full manual inspection.

## 3. Why This Is CCF-A-Oriented

BEAM-like semantics-aware detectors already show strong monitor-centric detection performance. Recent public-data poisoning work shows monitor-centric detectors can be vulnerable to crafted announcements. Therefore the core gap is not "another detector", but robust incident triage under poisonable public observations, incomplete ground truth, and imperfect external evidence.

The system must be evaluated under:

- monitor poisoning / evasion;
- missing evidence;
- stale evidence;
- conflicting evidence;
- component-mixed incidents;
- human burden reduction under evidence constraints.

## 4. Required CCF-A Contributions

Contribution 1: Problem and benchmark

- Formalize poisoning-robust BGP incident triage under partial observability.
- Build monitor poisoning / evasion benchmark.

Contribution 2: Evidence-constrained verifier

- Member-level evidence validation.
- Component-level purity / mixture analysis.
- Incident-level abstention-aware verdict.

Contribution 3: Component-aware semantic learning ranker

- Learn incident internal structure.
- Calibrate verifier-supported weak signals.
- Reduce Top-K human review burden under poisoning.

## 5. Non-Negotiable Guardrails

- Do not train attack/benign classifier from `high/needs/low`.
- Do not treat `P1/P2/P3` as truth.
- Do not treat RPKI invalid as confirmed attack.
- Do not treat RPKI valid as benign.
- Do not treat `background_like` as confirmed normal.
- Do not hide conflict.
- Do not use unavailable or stale evidence as benign.
- Do not let learning override verifier hard rules.
- Do not optimize legacy detector score unless it blocks verifier lookup or poisoning baseline.
- Do not mix unreported AS-rel / evidence-cache snapshots across Stage 1 and Stage 2 in final main results.
- Do not create category explosion by turning every evidence combination into an attack family.
- Do not treat `evidence_tags` as attack labels.
- Do not place learning after Top-K or let learning replace Top-K policy.

## 6. Experiment Roadmap Toward CCF-A

```text
R-DOC-1: decision register and mainline documentation lock
R-OUT-1: unified incident output taxonomy design
R-CONSIST-2: aligned AS-rel reannotation / impact analysis if Stage 1 fields are used
R-2D-P0: communities propagation schema and repair before stealth verifier use
R-2B: VRP-aware verifier smoke + incident purity audit
R-2C: path evidence branch / route-leak legality refinement
R-3: monitor poisoning / evasion benchmark
L1: component-aware semantic learner
L2: evidence-constrained ranker / calibrator
R-4: multi-evidence robustness evaluation
Paper stage: CCF-A claim consolidation
```

R-2B is the first evidence-backed verifier smoke on this path. Its value is not only RPKI lookup coverage; it is the component-aware constraint that prevents mixed incidents from being forced into suspicious or background verdicts.

## 6A. Unified Output Taxonomy Guardrail

R-DOC-1 locks the output shape for CCF-A writing and evaluation.

Small `primary_family` set:

- `forged_origin_like`
- `route_leak_like`
- `path_manipulation_like`
- `stealth_evasion_like`
- `mixed_or_conflict`

Required supporting fields:

- `observability_mode`
- `verifier_state`
- `evidence_tags`
- `confidence_cap`
- `review_priority_score`
- `topk_rank`
- `recommended_action`
- `why_not_confirmed`

No category explosion: combinations such as RPKI status, AS-rel diagnostic, NO_EXPORT presence, low visibility, and component purity belong in `evidence_tags` and verifier fields, not in newly minted primary categories.

Evidence tags are not attack labels. They are provenance-bearing facts used for verification, ranking, explanation, and ablation.

Learning remains after the verifier and before Top-K. It ranks and calibrates incident cards; it does not output confirmed attack/benign, override hard rules, or hide evidence conflict.

## 7. Operational Deployment Guardrails

R-2B-OPS adds deployment constraints that are part of the CCF-A target line:

- Daily human review must be bounded by Top-K queues, conflict caps, split-candidate review, and sampling. Full manual inspection of all legacy P1/P2, abstain, insufficient, or background-like incidents is not acceptable.
- The online path must use local evidence-cache lookups only. It must not wait for per-incident remote RPKI, IRR, AS relationship, PeeringDB, or data-plane downloads.
- External evidence should be maintained by asynchronous background updaters that normalize sources into versioned local caches, build indexes, switch caches atomically, and preserve provenance/freshness metadata.
- Cache stale/unavailable states do not block monitor-triggered candidate generation. They lower evidence state and can produce `stale_diagnostic`, `evidence_insufficient`, `external_evidence_unavailable`, `abstain`, or `evidence_conflict`.
- `abstain`, `evidence_insufficient`, and `background_like_but_unconfirmed` are not failures and are not direct human-work queues. They require Top-K, enrichment, waiting, or sampling policy.
- Human review is a Top-K evidence-supported triage process, not full manual inspection.

These guardrails must carry into R-2C path evidence, R-3 poisoning/evasion benchmark, and L1/L2 learning design.

Path evidence is a required condition for the multi-attack-family verifier. RPKI/VRP origin evidence alone cannot support route-leak, path-manipulation, valley-free, ASPA, or BGP Roles / OTC claims. R-2C work must therefore attach aligned or explicitly stale path evidence before route-leak verifier claims are made. Stale AS relationship snapshots are diagnostic only, PeeringDB is context only, and missing path evidence is not benign.

CAIDA AS relationship evidence remains inferred evidence even when snapshot-aligned. It may support path-relation diagnostics and route-leak candidates, but it is not route-leak truth. AS-rel violation is not confirmed route leak, AS-rel path legality is not benign, and CAIDA raw orientation must not be silently re-coded into stronger claims without an explicit verifier rule.

R-2C-P1 is the first incident-level path relation smoke on this CCF-A path. It attaches the `2024-04-01` CAIDA AS relationship cache back to AS-pair, triplet, and full-path incident evidence, producing route-leak-like and path-manipulation-like diagnostic candidates without changing R-2B verifier verdicts. This is the right shape for the target line: path evidence becomes explicit, component-aware verifier input, not hidden detector score or claimed route-leak truth.

R-2C-P2 builds a route-leak/path-legality verifier smoke from these diagnostics, but it still preserves these guardrails:

- possible valley-free diagnostics are not confirmed route leaks;
- AS-rel matched is not benign;
- AS-rel unmatched is not suspicious;
- path diagnostic is not confirmed route leak;
- `path_review_signal_density` is not attack density;
- AS-rel-only evidence cannot trigger a strong verdict;
- ASPA / BGP Roles / OTC feasibility should be considered before any stronger path-legality claim;
- NO_EXPORT / communities remain a separate R-2D-0 availability audit;
- AS Hegemony remains downstream impact-aware ranking evidence for L1/L2, not part of R-2C-P1/P2.

R-2C-P2 full fixed S2 smoke processed `217165` incidents and emitted only conservative R-1-compatible verifier-smoke outputs: `evidence_supported_suspicious=44`, `evidence_conflict=86`, `evidence_insufficient=78324`, `abstain=10822`, `background_like_but_unconfirmed=127889`, and `strongly_supported_suspicious=0`. It generated no confirmed route-leak labels, did not modify R-2B verifier verdicts, and passed hard safety audit with `0` violations. This is the correct CCF-A shape: path evidence becomes a review/verifier layer with explicit uncertainty, not a hidden detector score or attack label.

R-2D-0 communities / NO_EXPORT field availability audit starts the stealth evidence branch under the same CCF-A guardrails. It found that raw update chunks preserve `communities` in `864` parquet files, and full audit observed well-known community rows `NO_EXPORT=223410`, `NO_ADVERTISE=1240`, `NO_EXPORT_SUBCONFED=0`, and `NOPEER=5634`. However, communities are retained only at `raw_updates`; they are not present in `event_units`, `incident_membership`, `incident_tickets`, or R-2B/R-2C verifier outputs, so incident join readiness is currently `false`.

The R-2D red lines are:

- NO_EXPORT present is not a confirmed attack.
- NO_EXPORT absent is not safe.
- NO_ADVERTISE / NO_EXPORT_SUBCONFED / NOPEER present is not a stealth label.
- low visibility does not mean NO_EXPORT.
- collector asymmetry does not prove monitor evasion.
- missing communities are not benign.
- provider-specific communities require later semantic decoding and provenance.
- learning cannot infer missing communities or convert community absence into normal traffic.
- R-2D-1 must wait for community retention into event and incident/member tables, or it must remain explicitly raw-only and not incident-verifier-ready.

For the CCF-A target, this result is useful precisely because it prevents overclaiming: stealth evidence exists in raw data, but the current Stage 1 pipeline does not yet preserve it for Stage 2 verification. The next step is community-retention pipeline repair, not a stealth detector claim.

R-CONSIST-1 adds an evidence cache consistency guardrail. Stage 1 provenance audit found that Stage 1 AS-rel annotation code defaults to CAIDA `2017-07-01`, while Stage 2 R-2C uses the aligned `2024-04-01` AS-rel cache. This does not invalidate the verifier design, but it creates a high reviewer-risk condition if stale Stage 1 AS-rel-derived weak/path fields are used in final main results without alignment or drift analysis.

The evidence cache consistency red lines are:

- Stage 1 AS-rel use is weak trigger/context, not verifier truth.
- Stage 2 AS-rel use is versioned verifier evidence, not route-leak truth.
- Final main experiments should use a consistent AS-rel snapshot across Stage 1-derived path fields and Stage 2 evidence when those fields are jointly reported.
- If consistency is impossible for a historical artifact, the paper must report snapshot provenance and drift/impact analysis.
- Stale Stage 1 AS-rel fields cannot support strong evidence claims.
- Learning cannot hide AS-rel snapshot drift inside ranking features.
- R-CONSIST-2 aligned reannotation should run before using Stage 1 AS-rel-derived weak/path fields as final paper evidence.

## 8. Raw Incident Construction Guardrail

R-AGG-ENTRY-0 adds a Raw Incident Dossier entry point audit before any new incident-level aggregation claim. This is necessary because the project must not become a normal detector that simply repackages old final labels.

CCF-A line:

- the contribution is explainable incident construction plus evidence grounding under partial observability, not ordinary event-level detector tuning;
- final labels are weak workflow signals, not truth labels;
- high/needs/low and P1/P2/P3 are workflow/priority hints, not truth labels;
- no truth label is created by Raw Incident construction;
- Raw Incident Dossier should begin from an entry with enough fields for aggregation and evidence lookup, but low judgment contamination;
- current recommended main entry is `candidate-entry`;
- `event-entry` and `scored-entry` are auxiliary references;
- `gated-entry`, `augmented-entry`, and `final-entry` should not be the main Raw Incident entry because they carry old judgment decisions.

Research red lines:

- Do not default to the old final-level 21w ticket aggregation as the paper main result.
- Do not optimize legacy final label quality as the core contribution.
- Do not let final/gate/augment labels become attack labels.
- background-like is operational suppression, not confirmed benign.
- family_hint is semantic hint, not confirmed attack label.

Forward-looking CCF-A assets:

- poisoning benchmark retained as the key experiment for showing robustness under incomplete and poisonable public monitors;
- learning layer postponed until Raw Incident Dossier and Evidence-grounded Incident schemas are stable;
- future learning should aim at BEAM-style semantic learning for incident representation and prioritization, not rule re-scoring.

## 9. Lightweight Evidence Pre-Triage Guardrail

R-EVID-0 adds a lightweight evidence pre-triage design gate before any Raw Incident compression, safe merge, or background suppression implementation.

This gate exists because R-AGG-3 found that background-like operational candidates and high-value weak signals overlap heavily. A CCF-A-quality system cannot simply discard or suppress low-visibility / mixed_unknown cases, because those are also where partial observability and monitor poisoning matter most.

R-EVID-0 result:

- protected_suspicious rate: `0.929482`;
- suppressible_background_like rate: `0.0`;
- gray_zone_retained rate: `0.070518`;
- protected_background_overlap_rate: `0.92477`;
- stop-loss decision: `do_not_enter_R_EVID_1_yet`.

CCF-A line:

- lightweight evidence pre-triage is a reliability guardrail, not a detector;
- RPKI invalid is not attack truth;
- AS-rel diagnostic is not route leak truth;
- background-like is not benign;
- protected_suspicious is not confirmed attack;
- suppressible_background_like is not a deletion instruction;
- gray_zone_retained is not failure;
- no compression should be implemented until high-value weak signals are protected.

Next required guardrail:

- repair `family_hint` mapping before R-EVID-1;
- rerun R-EVID-0 after mapping repair;
- only then consider a no-deletion evidence pre-triage smoke.

## 10. R-RESET-1 CCF-A Mainline Guardrail

R-RESET-1 changes the paper-facing mainline.

Do not write the contribution as an ordinary ranking / triage system. The core goal is:

```text
low-false-positive multi-attack judgment under poisonable and incomplete public monitors
```

Required wording:

- `full candidate-entry incident aggregation stopped` as the mainline;
- new route is a `noise-filtered multi-attack judgment pipeline`;
- `incident aggregation after judgment`;
- `background is not ranked` in the primary human-facing output;
- `multi-attack judgment layer`, not semantic ranking;
- `poisoning/evasion robustness is core`.

Attack families that must remain visible:

- `suspicious_forged_origin`;
- `suspicious_route_leak`;
- `suspicious_path_manipulation`;
- `suspicious_stealth_visibility`;
- `poisoning_or_evasion_suspected`;
- `background_noise`;
- `uncertain_need_evidence`.

Evaluation red lines:

- report low false positive behavior;
- report false-negative or must-keep miss risk;
- report background compression;
- report poisoning/evasion robustness;
- report per-family coverage;
- report uncertainty / abstain / gray-zone behavior;
- never treat background_noise as confirmed benign;
- never train from final/high/needs/low or P1/P2/P3 as truth.

## 11. R-NOISE-0 Separability Guardrail

R-NOISE-0 adds a CCF-A guardrail before any foreground extraction implementation:

```text
safe obvious background suppression requires separability evidence
```

R-NOISE-0 result on `s2a_baseline_v01_pilot_6h_april16`:

- candidate-entry rows: `3431103`;
- multi-attack must-keep rows: `1812334` (`0.528207`);
- `policy_A_very_conservative` suppressible rows: `1614840` (`0.470647`);
- estimated compression ratio: `1.889100`;
- policy_A suppressed `0` must-keep rows;
- policy_A suppressed `0` legacy high/needs workflow-reference rows;
- policy_A suppressed `0` poisoning/evasion-like proxy rows.

CCF-A red lines:

- R-NOISE-0 is a separability audit, not a detector.
- policy_A can enter only a conservative R-NOISE-1 smoke.
- policy_C is an upper-bound stress test, not a default implementation.
- may-suppress/background_noise is operational, not confirmed benign.
- final/high/needs/low are workflow references, not truth.
- poisoning/evasion-like proxies must be retained until the poisoning benchmark is designed.
- foreground extraction must report compression and must-keep miss risk together.

## 12. Minimal Architecture and Ablation Defense

R-LOCK-1 freezes the final paper-facing system as a minimal three-stage architecture:

```text
Stage 1: Monitor-triggered Incident Construction
  -> Stage 2: Evidence-constrained Verification
  -> Stage 3: Component-aware Learning Triage
  -> Top-K Review Queue
```

This is the guardrail against a "module pile" critique:

- Stage 1 keeps the old seven-layer pipeline only as monitor-triggered incident construction, evidence lookup key extraction, and weak/context signal generation. It is not the final detector and does not output attack/benign truth.
- Stage 2 is the verifier. It attaches RPKI/VRP origin evidence, AS-rel path evidence, future stealth/path evidence, and emits evidence-supported, conflict, insufficient, unavailable, background-like, or abstain outcomes.
- Stage 3 is the component-aware learning ranker/calibrator. It sits after the verifier and before Top-K. It ranks, calibrates, and prioritizes components/incidents without overriding hard verifier rules.
- Top-K is the human-facing review budget, not the learning layer.

Each module must defend a distinct failure mode:

- monitor-only labels are poisonable, so Stage 2 verifier is required;
- origin-only evidence misses path attacks, so AS-rel/path evidence is required;
- path-only evidence misses forged-origin evidence, so RPKI/VRP remains required;
- mixed incidents cause overclaim, so component purity is required;
- missing/conflicting evidence requires abstain/conflict, not forced labels;
- too many review candidates require learning ranker plus Top-K budget.

The CCF-A evaluation must therefore include ablations that remove the verifier, origin evidence, path evidence, component purity, abstention/conflict handling, learning ranker, and Top-K budget. The defense is not "every module sounds useful"; it is measurable degradation under unsupported alert ratio, evidence-supported density, Top-K density, conflict preservation, abstain safety, mixed incident overclaim, human review burden, and poisoning robustness.

R-RESET-1 updates the interpretation: Stage 3 is no longer primarily a semantic ranker. It is a low false positive multi-attack judgment layer, with any ranking or Top-K budget downstream of foreground judgment.

## 13. Fallback Policy

If the poisoning benchmark or learning ranker is weak, the project can fall back to a strong SCI version.

If component learning shows clear benefit and the poisoning benchmark is strong, keep the CCF-A target.

Fallback does not change the current experimental standard.
