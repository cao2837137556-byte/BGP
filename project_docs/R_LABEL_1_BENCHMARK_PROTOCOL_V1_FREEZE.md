# R-LABEL-1 Benchmark Protocol v1 Patch and Freeze

Status: protocol v1 frozen for the first controlled-injection smoke.

Date: 2026-06-18.

Supersedes for new experiments:

- `configs/multi_attack_benchmark_protocol_v0.yaml`;
- `configs/attack_scenario_registry_template_v0.yaml`.

The v0 files remain archived for provenance. They must not be silently modified
or used as the active contract after this phase.

## 1. Purpose

R-LABEL-1 closes the protocol gaps identified after the focused deep-research
review of multi-attack BGP benchmarks, controlled injection, historical replay,
and poisoning/evasion experiments.

This phase freezes the schema needed to answer:

```text
For every controlled attack record, where did it go from raw parsing through
event construction, candidate marking, and foreground extraction?
```

R-LABEL-1 does not:

- add attacks to the current 6h data;
- label current 6h events as attack or benign;
- run event/candidate construction;
- run foreground extraction;
- train a model;
- implement route-leak, NO_EXPORT-evasion, or poisoning experiments.

The current 6h data remains `reference_background`, not confirmed benign truth.

## 2. Why v0 Was Not Sufficient

R-LABEL-0 correctly fixed:

- separate benchmark tracks;
- five label layers;
- evidence-versus-truth boundaries;
- raw-level injection as the paper-grade path;
- scenario-aware split guardrails;
- a zero-suppressed-attack smoke stop-loss.

However, v0 did not enforce enough detail to distinguish:

- attack records rejected by the raw parser;
- valid records that never formed an event;
- attack events that were not marked as candidates;
- candidate attacks suppressed by foreground extraction;
- attacks intentionally invisible to public collectors;
- mixed event/candidate containers with only a small attack-member share;
- clean and adversarial variants that do not hold comparison variables constant.

Without these distinctions, a single `missed=true` or event-level attack label
would hide the actual failure layer and could overstate benchmark truth.

## 3. Protocol v1 Additions

### 3.1 Phase and Role Provenance

Every controlled scenario must define an ordered phase timeline.

Required phase values:

- `stable_baseline`;
- `poisoning_preparation`;
- `attack_launch`;
- `mitigation_or_counterannounce`;
- `recovery`.

Only phases used by a scenario need records, but `stable_baseline`,
`attack_launch`, and `recovery` are mandatory for R-ATTACK-0A.

Required raw-record roles:

- `background`;
- `legitimate_announce`;
- `attacker_announce`;
- `attacker_withdraw`;
- `victim_counterannounce`;
- `victim_withdraw`;
- `poison_announce`;
- `recovery_announce`;
- `recovery_withdraw`.

This prevents attack onset, mitigation, and recovery records from being merged
into one undifferentiated attack window.

### 3.2 Observability Contract

Every scenario must declare:

- `expected_visibility_class`;
- `collector_set_id`;
- expected collectors seen;
- expected collectors not seen;
- whether public-monitor visibility is a benchmark assumption or measured result.

Allowed visibility classes:

- `public_visible`;
- `partial_public_visible`;
- `public_invisible`;
- `unavailable`.

R-ATTACK-0A should initially use `public_visible` scenarios so a foreground miss
is not confused with an attack that public monitors were never expected to see.

`public_invisible` is an observability boundary. A public control-plane-only
system cannot claim detection of information that is absent from its inputs.

### 3.3 Mixed Membership

Event and candidate labels must preserve:

- total member count;
- attack member count;
- attack member share;
- membership state.

Allowed membership states:

- `attack_only`;
- `mixed`;
- `background_only`;
- `unavailable`.

An event containing one attack record and many background records is not an
attack-only truth object. It is a mixed container with derived membership.

### 3.4 Layer Outcome and Drop Localization

Every injected record/scenario must support a final layer outcome.

Allowed `drop_stage` values:

- `none`;
- `raw_parser`;
- `event_builder`;
- `candidate_builder`;
- `foreground`;
- `unavailable`;
- `not_applicable`.

Required outcome details:

- `drop_reason_code`;
- `raw_parser_admitted`;
- `raw_event_eligible`;
- `event_id_set`;
- `candidate_event_id_set`;
- `foreground_bucket`;
- `attack_retained`;
- `guardrail_violation`.

Allowed foreground buckets:

- `foreground_high`;
- `foreground_gray`;
- `operational_background_suppressed`;
- `not_reached`;
- `unavailable`.

This makes raw-to-event, event-to-candidate, and candidate-to-foreground failures
separately measurable.

### 3.5 Split and Leakage Guardrails

Required grouping fields:

- `template_id`;
- `scenario_split_group`;
- `victim_prefix_group`;
- `legitimate_origin_group`;
- `attacker_as_group`;
- `incident_group` for historical replay;
- `base_scenario_id` for paired variants.

Random row splitting is forbidden.

The same scenario, injection template, victim prefix group, attacker group, or
historical incident must not leak across incompatible train/dev/test partitions.

### 3.6 Versioned Evidence Binding

Each run/scenario must bind:

- `rpki_snapshot_id`;
- `asrel_snapshot_id`;
- `collector_set_id`;
- `community_extraction_version`;
- `evidence_recomputed`.

For controlled injection, RPKI, AS-rel, communities/NO_EXPORT, event IDs,
candidate IDs, and foreground outcomes are run-bounded artifacts and must be
recomputed after injection.

For historical replay, period-correct evidence may be:

- available and aligned;
- unavailable;
- not applicable.

It must not be backfilled from the 2024 baseline without scientific justification.

## 4. Hard-Negative Contract

Future benchmark expansion must include legal or operationally plausible changes
that resemble attacks:

- legitimate MOAS;
- legitimate prefix ownership or origin transition;
- traffic engineering and AS-path prepending;
- prefix deaggregation;
- normal community use;
- maintenance and planned reconfiguration;
- link failure and route churn;
- operator typo or prepending mistake.

These are not automatically benign truth. They are hard-negative scenario
categories whose provenance and confidence must be recorded.

R-ATTACK-0A is not required to implement the full hard-negative suite, but it
must not claim low false positive performance from attack-only injection.

## 5. R-ATTACK-0A Admission Contract

The first controlled-injection smoke is intentionally narrow.

Required scenarios:

1. clean exact-prefix origin hijack;
2. clean forged-origin hijack.

Optional after the first two pass:

3. clean subprefix hijack.

Deferred:

- paper-grade route-leak injection;
- paper-grade NO_EXPORT / monitor-evasion benchmark;
- detection-data poisoning benchmark;
- multi-attack learning.

The deferred families need stronger propagation, policy, or observability
contracts than a simple raw-field modification.

## 6. R-ATTACK-0A Realism Requirements

Every first-batch scenario must:

- inject syntactically valid records at raw-update level;
- use the same raw parser and event/candidate construction path as background;
- include stable, attack, and recovery phases;
- avoid research-only fingerprints in raw BGP fields;
- avoid one fixed timestamp, duration, victim, attacker, or template pattern;
- declare expected public visibility;
- keep truth in the scenario registry, not in evidence fields;
- recompute all clean evidence sidecars for the derived run;
- mark unavailable evidence as unavailable, not benign.

Controlled injection may use metadata in a separate label sidecar. It must not
add truth-only columns to raw records consumed by the production-like parser.

## 7. Metrics and Stop-Loss

Required first-batch metrics:

- `raw_parser_admission_rate`;
- `raw_to_event_attack_propagation_recall`;
- `event_to_candidate_recall`;
- `candidate_to_foreground_retention`;
- `overall_scenario_retention`;
- `family_wise_retention`;
- `suppressed_attack_count`;
- `gray_zone_attack_rate`;
- `reference_background_suppression_rate`;
- `foreground_workload`;
- `compression_ratio`.

R-ATTACK-0A hard stop-loss:

```text
raw_parser_admission_rate = 1.0
suppressed_attack_count = 0
attack-supporting provenance completeness = 1.0
evidence_recomputed = true for RPKI, AS-rel, and communities
```

Failure at any condition blocks learning and must be localized using
`drop_stage` and `drop_reason_code`.

When confidence intervals are later reported, the resampling unit must be the
scenario, not highly correlated raw rows.

## 8. Paired Poisoning / Evasion Contract

Paired variants are not implemented in R-ATTACK-0A, but v1 fixes their schema.

A clean/adversarial pair must explicitly separate:

- variables held constant;
- variables changed by the adversary;
- base scenario identity;
- poisoning or visibility budget;
- expected failure mode;
- public observability contract.

AS-path poisoning and detection-data poisoning are distinct concepts:

- AS-path poisoning manipulates routing path selection;
- detection-data poisoning contaminates detector history, knowledge, or
  statistics before the actual attack.

They must not share one ambiguous `poisoning=true` field.

## 9. Active Artifacts

Active protocol:

- `configs/multi_attack_benchmark_protocol_v1.yaml`.

Active registry template:

- `configs/attack_scenario_registry_template_v1.yaml`.

Historical v0 artifacts remain available but are superseded for new experiments.

## 10. Next Step

After R-LABEL-1:

```text
R-ATTACK-0A:
Design and execute a minimal raw-level exact-prefix and forged-origin injection
smoke, then measure raw -> event -> candidate -> foreground retention.
```

The experiment must create a new derived run and must not overwrite the clean
6h baseline.
