# Noise Filter And Multi-Attack Judgment Plan

Last updated: 2026-06-15

Status: R-NOISE-1 foreground smoke complete; R-LEARN-0 / R-POISON-0 design next.

## 1. Goal

This plan defines the next mainline after candidate-first aggregation stop-loss.

The goal is:

```text
obvious noise suppression / foreground extraction
  -> multi-attack judgment layer
  -> attack-like incident aggregation
```

The objective is low false positive, deployable BGP attack judgment under incomplete and poisonable public monitors.

## 2. Stage 1: Obvious Noise Suppression / Foreground Extraction

Stage 1 should suppress only operationally obvious background candidates.

Goals:

- reduce obvious background noise;
- preserve multi-attack weak signals;
- produce a foreground view for judgment learning;
- keep gray-zone samples for audit and drift checks.

Important boundary:

- obvious noise means operational background suppression;
- obvious noise is not confirmed benign;
- background is not ranked in the primary review output;
- suppressed background still needs summary statistics and reproducible sampling.

## 3. Must-Keep Rules

R-NOISE-0 / R-NOISE-1 must preserve events with any of these signals:

- new origin / unseen prefix-origin;
- path novelty / unseen path;
- route-leak-like path diagnostic / valley-like signal;
- low visibility plus another weak signal;
- collector asymmetry;
- NO_EXPORT / community hint if available;
- poisoning/evasion suspicious pattern;
- known-event-like signal if available;
- RPKI invalid or unknown combined with other weak signal;
- AS-rel diagnostic combined with path or origin novelty.

These are must-keep signals, not confirmed attacks.

## 4. May-Suppress Rules

A candidate can only be considered for may-suppress if it has:

- no new origin;
- no path novelty;
- no path diagnostic;
- no visibility anomaly;
- weak or missing candidate reason;
- repetitive historical background-like pattern;
- no external evidence support;
- no poisoning/evasion suspicious pattern;
- no communities / NO_EXPORT / collector-asymmetry hint.

Even then, may-suppress is an operational state. It is not a negative label.

## 5. Gray-Zone Handling

Gray-zone candidates:

- do not enter background;
- do not become attack judgments;
- remain available for evidence attachment, sampling, and drift monitoring;
- may be used to test abstention and uncertainty behavior.

Gray-zone is a reliability mechanism, not failure.

## 6. Stage 2: Multi-Attack Judgment Layer

The learning layer is now a `multi-attack judgment layer`.

It is not semantic ranking. It is also not a single attack/benign classifier.

Expected outputs:

- `suspicious_forged_origin`;
- `suspicious_route_leak`;
- `suspicious_path_manipulation`;
- `suspicious_stealth_visibility`;
- `poisoning_or_evasion_suspected`;
- `background_noise`;
- `uncertain_need_evidence`.

The layer should also output:

- confidence;
- evidence explanation;
- why-not-confirmed reason;
- uncertainty / abstention reason;
- poisoning/evasion risk note.

## 7. Inputs To The Judgment Layer

Candidate inputs:

- candidate reasons and weak-signal tags;
- prefix-origin novelty;
- path novelty and path signatures;
- visibility and collector features;
- RPKI status;
- AS-rel/path diagnostic;
- communities / NO_EXPORT features when propagated;
- temporal repetition / duration features;
- historical background pattern features;
- poisoning/evasion stress-test features.

Forbidden inputs as truth:

- final/high/needs/low;
- P1/P2/P3;
- background-like as benign;
- RPKI invalid as attack truth;
- AS-rel diagnostic as route leak truth.

## 8. Evaluation Metrics

R-NOISE / R-LEARN experiments should report:

- false positive proxy;
- false negative proxy or must-keep miss rate;
- background compression;
- foreground recall for known or high-value weak signals;
- gray-zone rate;
- uncertain / abstain rate;
- poisoning/evasion robustness;
- per-family coverage;
- explanation completeness.

`low false positive` is a core deployment target, not a cosmetic metric.

## 9. Stage 3: Incident Aggregation After Judgment

Attack-like incident aggregation happens after judgment.

Only suspicious / attack-like / poisoning-suspected events should become analyst-facing incidents. Background candidates are summarized, sampled, and audited, but are not ranked.

This avoids repeating the R-AGG-2 failure mode where nearly every candidate became a raw incident.

## 10. R-NOISE-0 Result

R-NOISE-0 completed the first obvious noise separability audit on `s2a_baseline_v01_pilot_6h_april16`.

Core result:

- candidate-entry rows: `3431103`;
- multi-attack must-keep rows: `1812334` (`0.528207`);
- `policy_A_very_conservative` would suppress `1614840` rows (`0.470647`);
- policy_A estimated compression ratio: `1.889100`;
- policy_A suppressed `0` must-keep rows;
- policy_A suppressed `0` legacy high/needs workflow-reference rows;
- policy_A suppressed `0` poisoning/evasion-like proxy rows.

Interpretation:

- R-NOISE-0 is an obvious noise separability audit, not a suppression implementation.
- The objective is safe obvious background suppression, not maximum background count.
- policy_A passes the first safety gate and is the only recommended R-NOISE-1 smoke candidate.
- policy_C remains only an aggressive upper-bound stress test.
- background-like is operational suppression candidate, not confirmed benign.
- RPKI invalid is not attack truth.
- AS-rel diagnostic is not route leak truth.

## 11. R-NOISE-1 Result

R-NOISE-1 completed the conservative foreground extraction smoke using `policy_A_very_conservative`.

Core result:

- candidate-entry rows: `3431103`;
- foreground_protected rows: `1812334` (`0.528207`);
- suppressible_background rows: `1614840` (`0.470647`);
- gray_retained rows: `3929` (`0.001145`);
- foreground_view_total rows: `1816263`;
- estimated compression ratio if suppressible rows are removed from the foreground view: `1.889100`;
- `guardrail_failed=false`;
- suppressed multi-attack must-keep rows: `0`;
- suppressed legacy high/needs workflow-reference rows: `0`;
- suppressed poisoning/evasion proxy rows: `0`.

Scientific boundary:

- R-NOISE-1 reports guardrail safety, not true attack false negatives.
- The 6h clean window has no confirmed attack labels.
- Explicit poisoning/evasion token count is `0` / unavailable.
- Available poisoning/evasion proxy rows are retained, but this is not poisoning/evasion recall.

## 12. Immediate Next Step

Next:

```text
R-LEARN-0 multi-attack judgment layer design
R-POISON-0 controlled poisoning/evasion benchmark design
```

No learning training, production suppression claim, or attack-like incident aggregation should proceed before the benchmark/miss-risk design is explicit.
