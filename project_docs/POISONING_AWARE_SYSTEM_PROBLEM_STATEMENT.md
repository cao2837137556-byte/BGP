# Poisoning-Aware System Problem Statement

Last updated: 2026-06-01

Status: R-RESET-1 problem statement.

## 1. Problem Statement

The paper problem is not:

```text
Build another BGP anomaly detector.
```

The paper problem is:

```text
Under incomplete, evasible, and poisonable public BGP monitors, how can we
perform low false positive multi-attack foreground judgment and explain
suspicious routing events without treating monitor output as truth?
```

This is a poisoning-aware BGP security system problem.

## 2. Why This Is Not A Normal BGP Detector

A normal public-monitor detector tends to assume:

- monitor visibility is representative;
- anomalies are reliable attack clues;
- background can be learned as benign;
- model scores can be ranked into a review queue.

This project rejects those assumptions.

Public monitor data is partial. Attackers can exploit visibility gaps. Crafted announcements can poison monitor-derived features. NO_EXPORT and communities can shape what monitors see. Therefore the system must make cautious operational judgments, not truth claims.

## 3. Why Poisoning / Evasion Is Core

`poisoning/evasion robustness is core`.

It is not a small ablation and not a late appendix.

The core threat model is:

- attackers can craft announcements that look like background;
- attackers can exploit single-collector or asymmetric visibility;
- attackers can manipulate path novelty and monitor coverage;
- stealth signals such as NO_EXPORT may be absent from later incident tables unless propagated;
- public-monitor-only systems can miss attacks or overreact to background.

Therefore the paper must evaluate robustness against poisoning and evasion, not just clean-window detector quality.

## 4. Impact Of NO_EXPORT And Monitor Evasion

NO_EXPORT / communities matter because they can restrict propagation and make an incident visible only to selected monitors.

Design implications:

- low visibility is not enough to prove stealth;
- NO_EXPORT present is not confirmed attack;
- NO_EXPORT absent is not safe;
- communities must be propagated before community-aware stealth evidence is possible;
- collector asymmetry should be treated as an observability clue, not a truth label.

## 5. Expected Contributions

The expected system contributions are:

- obvious noise suppression with must-keep safeguards;
- foreground extraction that preserves multi-attack weak signals;
- evidence-grounded multi-attack judgment;
- poisoning-aware robustness evaluation;
- suspicious event aggregation and explanation after judgment;
- explicit uncertainty / abstention / gray-zone handling.

The system should produce operational states, not ground-truth labels.

## 6. Stop-Loss Evidence Driving The New Route

R-AGG and R-EVID directly motivated the new route:

- R-AGG-2: `raw_incident_count=3128971`, `compression_ratio=1.09656`.
- R-AGG-3: `possible_background_like_rate=0.995288`, but high-value weak signals overlapped heavily with background-like candidates.
- R-EVID-0: `protected_suspicious_rate=0.929482`, `suppressible_background_like_rate=0.0`, `protected_background_overlap_rate=0.92477`.

This means:

- full candidate-entry incident aggregation stopped;
- direct background suppression is unsafe;
- evidence-aware protection is necessary but not sufficient;
- family/foreground judgment must come before analyst-facing incident aggregation.

## 7. New Paper Line

The concise paper line is:

```text
noise-filtered multi-attack judgment pipeline for poisoning/evasion-aware BGP
security under incomplete public monitors
```

The system should aim for low false positive foreground judgment, multi-family attack coverage, explicit uncertainty, and robustness under crafted monitor-visible artifacts.
