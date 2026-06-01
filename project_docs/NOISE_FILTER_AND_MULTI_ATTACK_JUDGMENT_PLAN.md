# Noise Filter And Multi-Attack Judgment Plan

Last updated: 2026-06-01

Status: R-RESET-1 design plan. No implementation yet.

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

## 10. Immediate Next Step

Next:

`R-NOISE-0 obvious noise audit`

R-NOISE-0 should be read-only. It should estimate must-keep, may-suppress, gray-zone, and poisoning/evasion-sensitive groups before any suppression implementation.
