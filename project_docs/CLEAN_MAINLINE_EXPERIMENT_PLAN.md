# Clean Mainline Experiment Plan

Last updated: 2026-06-15

Status: active mainline control plan.

## 1. Purpose

This document resets the paper-facing experimental route around a clean dependency chain:

```text
paper goal -> clean data/evidence contract -> benchmark/label protocol
-> foreground validation -> multi-attack judgment -> attack-like incident explanation
```

It is not another experiment report. It is the control plan that decides which data and evidence are allowed to enter future experiments, what each experiment is allowed to prove, and which claims remain forbidden until the required benchmark exists.

## 2. Paper Goal

The paper target is not:

- another public-monitor BGP anomaly detector;
- a full candidate-entry incident aggregation system;
- a semantic ranking system;
- a replay of legacy `high / needs / low` labels.

The paper target is:

```text
low-false-positive multi-attack BGP judgment under incomplete,
evasive, and poisonable public BGP monitors
```

Attack families that must remain in scope:

- forged-origin / origin hijack;
- route leak / valley-like path;
- path manipulation / suspicious path change;
- stealth visibility / NO_EXPORT / monitor evasion;
- poisoning / crafted announcement evasion.

## 3. Current State To Preserve

R-NOISE-1 is useful but provisional:

- run: `s2a_baseline_v01_pilot_6h_april16`;
- candidate rows: `3431103`;
- foreground view rows: `1816263`;
- suppressible operational-background rows: `1614840`;
- gray retained rows: `3929`;
- estimated compression: `1.889100`;
- guardrail_failed: `false`.

Allowed interpretation:

```text
R-NOISE-1 proves a clean-window foreground smoke can be generated
without triggering the currently defined guardrails.
```

Forbidden interpretation:

```text
R-NOISE-1 proves attack recall, poisoning/evasion recall, or benignness
of suppressed rows.
```

Reason: the 6h clean window has no confirmed attack labels.

## 4. Clean Data / Evidence Contract Summary

The detailed contract lives in:

```text
project_docs/R_CLEAN_0_DATA_EVIDENCE_CLEAN_CONTRACT.md
configs/clean_evidence_contract_v0.yaml
```

Short form:

| Item | Current status | Allowed in new mainline? | Required action |
|---|---|---|---|
| candidate/event native fields | available | yes | preserve provenance |
| RPKI VRP `2024-04-16` | aligned to run date | yes, as evidence/protection feature | never treat as attack/benign truth |
| CAIDA AS-rel `2024-04-01` | 2024-near cache available | yes, but only via new sidecar | do not use old event `rel_*` fields |
| old Stage 1 `rel_seq / rel_unknown_cnt / rel_has_unknown` | likely 2017 AS-rel-derived | no for decisions | replace with 2024 sidecar |
| raw communities / NO_EXPORT | raw layer available | not yet for decisions | build propagation or sidecar join |
| final/high/needs/low | legacy workflow labels | audit reference only | never use as truth or hard guard |
| P1/P2/P3 | legacy priority buckets | audit reference only | never use as truth or labels |
| R-NOISE-1 outputs | provisional foreground smoke | reference only | rerun after clean sidecars / benchmark |

## 5. Dependency Graph

The new mainline must proceed in this order:

```text
R-CLEAN-0
  Data / Evidence Clean Contract
      |
      v
R-ASREL-CLEAN-0
  2024-aligned AS-rel sidecar for candidate/event rows
      |
      v
R-COMM-CLEAN-0
  Communities / NO_EXPORT propagation or sidecar contract
      |
      v
R-LABEL-0
  Multi-attack benchmark and label protocol
      |
      v
R-ATTACK-0
  Controlled multi-attack injection smoke
      |
      v
R-NOISE-CLEAN-1
  Foreground extraction validation against injected/known attacks
      |
      v
R-LEARN-0
  Multi-attack judgment layer design, no training yet
      |
      v
R-LEARN-1
  Minimal training / replay experiment
      |
      v
R-INC-0
  Attack-like incident aggregation and explanation
```

This ordering is mandatory unless a later decision document explicitly changes it with evidence.

## 6. Stage Contracts

| Stage | Question | Inputs | Output | Pass condition | If not passed |
|---|---|---|---|---|---|
| R-CLEAN-0 | What data/evidence is clean enough for future experiments? | local inventories, previous audits | clean contract | every allowed/forbidden field has provenance and claim boundary | do not run new experiments |
| R-ASREL-CLEAN-0 | Can path diagnostics use 2024-near AS-rel only? | candidate/event rows, `as_rel_2024-04-01` | sidecar path diagnostics | no old 2017 `rel_*` used in decisions | block route-leak/path claims |
| R-COMM-CLEAN-0 | Can NO_EXPORT/community evidence join candidate/event rows? | raw updates, candidate/event keys | community sidecar or propagation design | NO_EXPORT availability is explicit: present/absent/unavailable | block stealth/NO_EXPORT claims |
| R-LABEL-0 | What labels or weak labels are legitimate? | clean background, known incidents, injection design | label protocol | truth/proxy/reference are separated | do not train or evaluate recall |
| R-ATTACK-0 | Can controlled multi-attack samples be generated? | clean background + injection rules | labeled attack smoke set | each family has reproducible labels | do not validate foreground recall |
| R-NOISE-CLEAN-1 | Does foreground extraction retain attack samples? | clean features + attack smoke | retention audit | suppressed attack count is zero or explicitly bounded | policy not fixed |
| R-LEARN-0 | What should the judgment layer learn? | clean features + label protocol | design only | no truth leakage, deployable metrics defined | no training |
| R-LEARN-1 | Does a minimal model help? | benchmarked data | model smoke | low false positive and per-family recall reported | fallback to rules/benchmark revision |
| R-INC-0 | How to aggregate attack-like judgments? | judged suspicious/uncertain rows | incident cards | explanation/provenance complete | no analyst-facing claim |

## 7. Claim Gates

The following gates are hard:

- No labels -> no recall claim.
- No controlled poisoning benchmark -> no poisoning/evasion robustness claim.
- No propagated or joinable communities -> no NO_EXPORT stealth claim.
- No aligned AS-rel sidecar -> no route-leak/path diagnostic decision claim.
- No known/injected attack replay -> no claim that foreground compression does not suppress attacks.
- No independent evaluation split -> no learning performance claim.

## 8. Clean Mainline Uses Of Previous Results

Previous results are not deleted. They are reassigned:

- R-AGG-2 / R-AGG-3 / R-EVID-0: stop-loss evidence showing candidate-first incident aggregation and direct evidence pre-triage are unsafe.
- R-NOISE-0 / R-NOISE-1: engineering smoke showing conservative foreground views are feasible, but provisional until clean sidecars and attack-retention validation exist.
- R-2B / R-2C: evidence prototypes proving RPKI and AS-rel caches can be attached, but new foreground/judgment experiments must use clean sidecars.
- R-2D-0: raw communities channel exists, but propagation is incomplete.
- R-CONSIST-1: old Stage 1 AS-rel inconsistency is a blocker for future decision logic.

## 9. Immediate Next Step

Next implementation should be:

```text
R-ASREL-CLEAN-0: 2024-aligned AS-rel sidecar for candidate/event rows
```

It should not modify the old pipeline. It should create a separate sidecar with:

- `event_id`;
- `as_path_clean`;
- `asrel_snapshot_date = 2024-04-01`;
- `run_date = 2024-04-16`;
- 2024-aligned path relation diagnostics;
- provenance fields;
- allowed / forbidden claims.

After that:

```text
R-COMM-CLEAN-0 -> R-LABEL-0 -> R-ATTACK-0 -> R-NOISE-CLEAN-1
```

## 10. Literature / Deep Research Gate

Before finalizing R-LABEL-0, R-ATTACK-0, or R-POISON-0, the project should run a focused literature review on:

- semantics-aware BGP anomaly detection;
- ARTEMIS-style hijack detection / mitigation benchmarks;
- NO_EXPORT / stealth hijack monitor evasion;
- BGP poisoning / crafted announcement evasion;
- realistic RouteViews / RIPE RIS replay and injection methodology.

This literature review should guide benchmark design, not override the local clean data contract.
