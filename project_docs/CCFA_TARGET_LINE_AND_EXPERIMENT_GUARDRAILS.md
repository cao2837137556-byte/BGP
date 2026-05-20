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

## 7. Fallback Policy

If the poisoning benchmark or learning ranker is weak, the project can fall back to a strong SCI version.

If component learning shows clear benefit and the poisoning benchmark is strong, keep the CCF-A target.

Fallback does not change the current experimental standard.
