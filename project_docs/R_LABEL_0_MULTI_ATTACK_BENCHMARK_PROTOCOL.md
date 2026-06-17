# R-LABEL-0 Multi-Attack Benchmark and Label Protocol

Status: completed protocol design.

Run context: `s2a_baseline_v01_pilot_6h_april16`.

Date: 2026-06-17.

## 1. Purpose

R-LABEL-0 defines the benchmark and label protocol before any new attack injection,
foreground validation, learning, or attack-like incident aggregation.

The goal is to make later experiments answer a scientifically valid question:

```text
Can the system preserve multi-attack signals and reduce background load under
incomplete, evasive, and poisonable public BGP monitor observations?
```

This phase does not:

- generate attack data;
- modify raw/event/candidate pipelines;
- run foreground suppression;
- train learning;
- implement poisoning/evasion benchmark;
- treat any evidence signal as truth.

## 2. Current Inputs Fixed Before This Protocol

The current 6h clean-window baseline has clean event/candidate evidence sidecars:

| Evidence | Snapshot | Current Artifact | Allowed Role |
|---|---:|---|---|
| RPKI / VRP | `2024-04-16` | `outputs/r_rpki_clean_0/s2a_baseline_v01_pilot_6h_april16/` | origin authorization evidence |
| CAIDA AS-rel | `2024-04-01` | `outputs/r_asrel_clean_0/s2a_baseline_v01_pilot_6h_april16/` | path diagnostic evidence |
| Communities / NO_EXPORT | raw source, joined to events/candidates | `outputs/r_comm_clean_0/s2a_baseline_v01_pilot_6h_april16/` | propagation / stealth evidence |

These sidecars are evidence features, not labels.

Forbidden truth claims:

- RPKI invalid is not attack truth.
- RPKI valid is not benign truth.
- AS-rel diagnostic is not route leak truth.
- NO_EXPORT present is not attack truth.
- NO_EXPORT absent is not safe.
- Low visibility is not confirmed stealth or NO_EXPORT.
- Legacy `high/needs/low`, `P1/P2/P3`, final labels, and model outputs are not truth.

## 3. Benchmark Tracks

R-LABEL-0 separates benchmark tracks instead of mixing them into one dataset.

### Track A: Reference Background

Purpose:

- characterize clean-window background pressure;
- evaluate foreground load and operational compression;
- provide realistic monitor noise context for controlled injection.

Current default:

- `s2a_baseline_v01_pilot_6h_april16`;
- date: `2024-04-16`;
- duration: 6h.

Allowed claim:

- background reference / OOD pressure in this window.

Forbidden claim:

- confirmed benign labels;
- attack recall;
- poisoning/evasion recall.

### Track B: Controlled Multi-Attack Injection

Purpose:

- create exact labels for attack membership, onset, duration, and family;
- test whether candidate generation and foreground policies retain attacks;
- cover multiple attack families in a controlled way.

Official paper-grade experiments must inject before event/candidate construction
and then rerun the relevant pipeline path. Candidate-level injection may be used
only as a quick smoke test.

Allowed claim:

- controlled attack retention and per-family retention under specified scenarios.

Forbidden claim:

- real-world generality without historical replay;
- model performance if the same scenario/template leaks across train/test.

### Track C: Historical Incident Replay

Purpose:

- test whether results transfer to real-world incidents;
- avoid an experiment that only works on synthetic "laboratory accent" attacks.

Historical incidents must be replayed in their original time windows with their
own date-aligned evidence snapshots.

Forbidden operation:

- do not paste historical incident records into the 2024-04-16 6h baseline.

Allowed claim:

- replay detection/retention on curated, externally documented historical events.

### Track D: Paired Poisoning / Evasion Variants

Purpose:

- quantify robustness loss under public-monitor poisoning or visibility evasion;
- compare each adversarial variant to its clean base scenario.

Poisoning/evasion is an adversarial variant axis, not just another attack family.

Required paired metrics:

- `clean_attack_recall`;
- `poisoned_attack_recall`;
- `recall_drop_under_poisoning`;
- `evasion_success_rate`;
- `foreground_load_change`;
- `gray_zone_shift`.

## 4. Base Attack Families

R-LABEL-0 uses base families for benchmark truth. Evidence sidecars may support
or explain these families, but they do not define them.

| Primary Family | Subtypes / Examples | Minimum Label Source |
|---|---|---|
| `origin_hijack` | forged origin, unauthorized origin, subprefix hijack | controlled injection metadata or verified historical report |
| `route_leak` | valley-like propagation, provider/customer leak, peer leak | controlled AS-path construction or verified historical report |
| `path_manipulation` | suspicious path change, path prepending manipulation, crafted path pattern | controlled path template or verified historical report |
| `stealth_propagation` | low visibility, monitor evasion, NO_EXPORT-assisted propagation limitation | controlled visibility/community manipulation or verified historical report |

`poisoning_or_evasion` is represented by `adversarial_variant`, because the same
base attack can be clean, poisoned, visibility-limited, or combined.

## 5. Adversarial Variant Axis

Allowed values:

- `none`;
- `history_poisoning`;
- `visibility_evasion`;
- `no_export_evasion`;
- `collector_asymmetry_evasion`;
- `combined_poisoning_evasion`.

This axis must be preserved in labels, splits, and metrics. Do not collapse it
into a generic suspicious class.

## 6. Label Layers

Labels must preserve where truth is known and where truth is derived.

### 6.1 Scenario-Level Labels

Required fields:

- `scenario_id`;
- `benchmark_track`;
- `primary_family`;
- `attack_subtype`;
- `adversarial_variant`;
- `victim_prefix`;
- `legitimate_origin_as`;
- `attacker_as`;
- `start_time`;
- `end_time`;
- `label_source`;
- `label_confidence`;
- `evidence_snapshot_requirements`;
- `split_group_id`;
- `notes`.

### 6.2 Raw-Record-Level Labels

Required for controlled injection:

- `raw_record_id`;
- `scenario_id`;
- `is_injected`;
- `injection_role`;
- `attack_phase`;
- `raw_label_source`.

Allowed `attack_phase` values:

- `pre_attack`;
- `pre_poison`;
- `attack`;
- `evasion`;
- `withdrawal`;
- `recovery`;
- `background_context`.

### 6.3 Event-Level Derived Labels

Event labels are derived from raw membership. They must not invent new truth.

Required fields:

- `event_id`;
- `scenario_id_set`;
- `contains_attack_member`;
- `attack_member_count`;
- `attack_member_share`;
- `family_set`;
- `variant_set`;
- `is_mixed_event`;
- `event_label_confidence`;
- `label_derivation_method`.

### 6.4 Candidate-Level Derived Labels

Candidate labels are derived from event membership. They must not come from
candidate reasons, legacy final labels, or evidence sidecars.

Required fields:

- `event_id`;
- `candidate_contains_attack`;
- `source_attack_event_ids`;
- `candidate_attack_family_set`;
- `candidate_attack_variant_set`;
- `candidate_generation_recall_eligible`;
- `candidate_label_confidence`.

### 6.5 Foreground-Outcome Labels

Foreground assignments are policy outcomes, not truth.

Required fields:

- `foreground_policy_id`;
- `foreground_assignment`;
- `attack_retained`;
- `attack_suppressed`;
- `attack_gray_retained`;
- `suppression_reason`;
- `guardrail_violation`.

Allowed `foreground_assignment` values:

- `foreground_retained`;
- `gray_zone_retained`;
- `operational_background_suppressed`.

## 7. Allowed Label Sources

Allowed truth sources:

- controlled injection scenario metadata;
- controlled experiment logs;
- manually curated historical incident registry;
- public operator-confirmed incident reports;
- independently documented public incident timelines.

Not allowed as truth sources:

- RPKI status;
- AS-rel / valley diagnostic;
- community / NO_EXPORT presence;
- low visibility;
- old high/needs/low or final labels;
- P1/P2/P3;
- foreground policy output;
- learning model output.

## 8. Evidence Features vs Label Sources

Evidence features are allowed for protection, explanation, ablation, and learning
input after labels are fixed.

Allowed evidence feature groups:

- RPKI / VRP sidecar;
- CAIDA AS-rel 2024 sidecar;
- community / NO_EXPORT sidecar;
- native event/candidate routing fields;
- candidate reasons as weak context.

Boundary:

```text
label_source defines what is attack/background/unknown in the benchmark.
evidence_feature helps the system decide or explain after labels are fixed.
```

## 9. Foreground Validation Metrics

The first foreground layer is not the final detector. It is a high-recall
retention and compression stage.

Required metrics:

- `background_suppression_rate`;
- `attack_retention_rate`;
- `family_retention_rate`;
- `suppressed_attack_count`;
- `gray_attack_rate`;
- `candidate_generation_recall`;
- `foreground_load`;
- `compression_ratio`;
- `raw_to_event_attack_retention`;
- `event_to_candidate_attack_retention`;
- `candidate_to_foreground_attack_retention`.

Smoke-stage stop-loss:

```text
suppressed_attack_count must be 0.
```

If any attack family is systematically dropped at raw-to-event, event-to-candidate,
or candidate-to-foreground, stop and diagnose that layer before learning.

## 10. Train / Dev / Test Split Guardrails

Do not randomly split rows.

Split isolation must consider:

- `scenario_id`;
- `victim_prefix`;
- `legitimate_origin_as`;
- `attacker_as`;
- `time_window`;
- `historical_incident_id`;
- `injection_template_id`;
- `adversarial_variant`.

No train/test leakage:

- same controlled scenario cannot appear in both train and test;
- near-duplicate injected rows cannot be split across train/test;
- the same historical incident cannot be split across train/test;
- paired clean/poisoned variants must be split intentionally and reported.

## 11. Controlled Injection Realism Requirements

Controlled injection must record:

- source background window;
- raw-update generation method;
- expected collector visibility;
- expected RPKI relation to victim/origin;
- expected AS-rel relation assumptions;
- expected community / NO_EXPORT behavior if used;
- expected event/candidate path through the pipeline;
- exact attack onset and end.

If a scenario relies on external evidence, the evidence snapshot must be aligned
to the scenario date. A historical event must not reuse the 2024-04-16 evidence
unless the historical event actually occurred on that date.

## 12. Historical Replay Requirements

Historical replay requires:

- incident source and citation in a curated registry;
- exact or bounded incident time window;
- victim prefix and legitimate origin if known;
- attacker/leaker AS if known;
- original RouteViews/RIS collection plan;
- date-aligned RPKI evidence;
- date-near AS-rel evidence;
- community availability audit if stealth/NO_EXPORT is studied;
- documented uncertainty if any field is unknown.

Historical replay may use lower label confidence than controlled injection, but
that lower confidence must be explicit.

## 13. Poisoning / Evasion Requirements

Paired variants must preserve the base scenario identity.

Required fields:

- `base_scenario_id`;
- `variant_scenario_id`;
- `adversarial_variant`;
- `manipulated_feature_family`;
- `expected_failure_mode`;
- `poisoning_budget`;
- `visibility_budget`;
- `expected_recall_drop_direction`.

Required paired report:

- clean base result;
- adversarial variant result;
- recall drop;
- foreground load shift;
- whether failure occurs at candidate generation, foreground, learning, or evidence explanation.

## 14. Stop-Loss Rules

Do not proceed to learning if:

- benchmark labels are missing for controlled attack scenarios;
- any attack family lacks at least one controlled smoke scenario;
- historical replay uses misaligned evidence snapshots without explicit caveat;
- candidate-level injection is promoted as paper-grade main result;
- foreground smoke suppresses any labeled attack in the initial conservative policy;
- poisoning/evasion is evaluated without paired clean baseline;
- labels are derived from RPKI/AS-rel/NO_EXPORT/legacy final outputs.

## 15. Next Experiment Sequence

Recommended sequence after R-LABEL-0:

1. `R-ATTACK-0A`: controlled origin hijack / forged-origin raw-level injection smoke.
2. `R-ATTACK-0B`: route leak, path manipulation, and stealth scenario generator design.
3. `R-ATTACK-QA-0`: injection realism and evidence consistency audit.
4. `R-NOISE-CLEAN-1`: attack-retention foreground validation with labels.
5. `R-HIST-0`: curated historical incident replay protocol and first replay.
6. `R-POISON-0`: paired poisoning/evasion benchmark design.
7. `R-LEARN-0`: multi-attack judgment learning design only after retention proof.

## 16. Reviewer Defense

R-LABEL-0 exists so the paper can defend:

- why clean 6h data is not called benign truth;
- why evidence signals are not used as labels;
- how controlled attacks provide exact truth;
- how historical replay provides external realism;
- how poisoning/evasion is evaluated as a paired robustness problem;
- why learning is postponed until the benchmark and label protocol are fixed.
