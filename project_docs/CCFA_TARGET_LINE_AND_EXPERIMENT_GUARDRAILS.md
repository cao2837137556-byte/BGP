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

## 6. Experiment Roadmap Toward CCF-A

```text
R-2B: VRP-aware verifier smoke + incident purity audit
R-2C: path evidence branch / route-leak legality refinement
R-3: monitor poisoning / evasion benchmark
L1: component-aware semantic learner
L2: evidence-constrained ranker / calibrator
R-4: multi-evidence robustness evaluation
Paper stage: CCF-A claim consolidation
```

R-2B is the first evidence-backed verifier smoke on this path. Its value is not only RPKI lookup coverage; it is the component-aware constraint that prevents mixed incidents from being forced into suspicious or background verdicts.

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

## 8. Minimal Architecture and Ablation Defense

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

## 9. Fallback Policy

If the poisoning benchmark or learning ranker is weak, the project can fall back to a strong SCI version.

If component learning shows clear benefit and the poisoning benchmark is strong, keep the CCF-A target.

Fallback does not change the current experimental standard.
