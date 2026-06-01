# R-RESET-1 Pipeline Mainline Pivot

Last updated: 2026-06-01

Status: documentation-only mainline pivot based on stop-loss evidence.

## 1. Why This Pivot Exists

R-RESET-1 does not delete or invalidate R-AGG / R-EVID. It uses them as stop-loss evidence.

The previous candidate-first direction asked whether we could first aggregate all candidate-entry rows into Raw Incident Dossiers and then attach evidence or learning. That route is now stopped as the mainline:

`full candidate-entry incident aggregation stopped`

The reason is empirical:

- R-AGG-2 showed that full candidate-entry aggregation produced `3,128,971` raw incidents from `3,431,103` candidate rows.
- R-AGG-2 compression ratio was only `1.09656`.
- R-AGG-3 showed `possible_background_like_rate=0.995288`, but also found high-value weak signals heavily overlap with background-like candidates.
- R-EVID-0 showed `protected_suspicious_rate=0.929482`, `suppressible_background_like_rate=0.0`, and `protected_background_overlap_rate=0.92477`.
- R-EVID-0 therefore triggered stop-loss and recommended not entering R-EVID-1 implementation.

Conclusion: candidate-first full incident aggregation is too expensive and too noisy to be the first paper-facing stage.

## 2. What Is Not Changing

This pivot does not:

- modify the old seven-layer pipeline;
- treat `final/high/needs/low` as truth;
- treat `P1/P2/P3` as truth;
- treat background-like as confirmed benign;
- delete R-AGG / R-EVID outputs;
- implement suppression;
- train learning;
- implement poisoning benchmark.

R-AGG / R-EVID remain useful because they prove why the mainline must change.

## 3. New Mainline

The new paper-facing route is:

```text
raw BGP / candidate events
  -> obvious noise suppression / foreground extraction
  -> multi-attack judgment layer
  -> attack-like incident aggregation
  -> evidence explanation
  -> poisoning/evasion robustness evaluation
```

Short label:

`noise-filtered multi-attack judgment pipeline`

This is not a normal ranking pipeline. It is a low false positive, evidence-aware, multi-attack foreground judgment system under incomplete and poisonable public BGP monitors.

## 4. Incident Aggregation Moves Later

`incident aggregation after judgment`

Incident aggregation is no longer the first mainline object for all candidate rows. It moves after foreground extraction and multi-attack judgment.

The new rule is:

- aggregate suspicious / attack-like events;
- keep gray-zone samples for audit and evidence grounding;
- keep background summary statistics for reproducibility;
- do not build analyst-facing incident queues from obvious background.

`background is not ranked`

This means background candidates should not enter the primary human review queue or learning-to-rank output. It does not mean background is confirmed benign. Background remains an operational suppression state with audit sampling and drift monitoring.

## 5. Attack Families Preserved

The new mainline must preserve multiple attack families:

- forged-origin / origin hijack;
- route leak / valley-like path;
- path manipulation / suspicious path change;
- stealth visibility / NO_EXPORT / monitor evasion;
- poisoning / crafted announcement evasion.

The learning and judgment layer must not collapse these into a single attack/benign classifier.

## 6. Multi-Attack Judgment Layer

The new learning layer is a `multi-attack judgment layer`, not semantic ranking.

It should produce operational judgments such as:

- `suspicious_forged_origin`;
- `suspicious_route_leak`;
- `suspicious_path_manipulation`;
- `suspicious_stealth_visibility`;
- `poisoning_or_evasion_suspected`;
- `background_noise`;
- `uncertain_need_evidence`.

These are operational judgments for foreground control and explanation, not ground-truth attack labels.

## 7. Why This Helps The Paper

The previous mainline risked becoming:

```text
candidate explosion -> incident explosion -> ranking problem
```

That would look like a normal triage system.

The new line is sharper:

```text
incomplete / poisonable public monitors
  -> low false positive foreground extraction
  -> multi-attack judgment
  -> evidence explanation
  -> poisoning/evasion robustness is core
```

`poisoning/evasion robustness is core`, not an appendix experiment.

## 8. Next Stage

Next stage:

`R-NOISE-0 obvious noise audit`

R-NOISE-0 should not implement suppression. It should first identify which background patterns are operationally obvious enough to suppress without harming forged-origin, route-leak, path-manipulation, stealth-visibility, or poisoning/evasion weak signals.
