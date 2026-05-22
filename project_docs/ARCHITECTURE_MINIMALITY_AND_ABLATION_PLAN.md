# Architecture Minimality and Ablation Plan

Status: Phase R-LOCK-1 architecture lock.

This document locks the minimal system architecture after R-2B/R-2C origin and path evidence work. It does not introduce new experiments or new verifier verdicts.

## 1. Why Architecture Lock Is Needed

The project now has several historical and forward-looking components:

- the legacy seven-layer monitor pipeline;
- incident aggregation and component construction;
- external evidence caches;
- RPKI/VRP origin evidence;
- CAIDA AS relationship path evidence;
- verifier verdicts with abstention and conflict;
- Top-K review queues;
- a planned learning layer.

If described naively, this can look like redundant modules or rule engineering. Reviewers can reasonably ask whether the system is just old detector layers plus many hand-built rules.

This document locks a minimal three-stage architecture. Each stage has a distinct purpose, a distinct failure mode, and a corresponding ablation. The point is not to keep every historical module as a paper contribution. The point is to reinterpret the old detector as the incident-construction trigger stage, then make verification and triage explicitly evidence-constrained.

## 2. Final 3-stage Architecture

```text
Stage 1: Monitor-triggered Incident Construction
  -> Stage 2: Evidence-constrained Verification
  -> Stage 3: Component-aware Learning Triage
  -> Top-K Review Queue
```

### Stage 1: Monitor-triggered Incident Construction

Purpose:

- Convert raw BGP updates into reviewable incidents and components.
- Generate prefix/origin/path/time/collector keys for evidence lookup.
- Preserve legacy weak signals as trigger and context.

Inputs:

- BGP updates / MRT / collector feeds.

Outputs:

- `incident_id`
- `member_id`
- `component_id` candidate
- `prefix`
- `origin_as`
- `as_path`
- `collector`
- `time_window`
- `legacy_score / gate / augment signal`
- legacy `high/needs/low` as priority hint only

Does not:

- decide attack / benign;
- act as ground truth;
- override verifier decisions.

### Stage 2: Evidence-constrained Verification

Purpose:

- Attach versioned external evidence.
- Produce abstention-aware verifier states.
- Preserve conflict, missing evidence, and evidence provenance.

Evidence channels:

- RPKI / VRP = origin evidence
- CAIDA AS Relationship = path evidence
- future communities / NO_EXPORT = stealth evidence
- future ASPA / BGP Roles / OTC = stronger path evidence
- future known-event / data-plane = validation / enrichment evidence

Outputs:

- `evidence_supported_suspicious`
- `evidence_conflict`
- `evidence_insufficient`
- `external_evidence_unavailable`
- `background_like_but_unconfirmed`
- `abstain`

Does not:

- treat RPKI invalid as confirmed attack;
- treat RPKI valid as benign;
- treat AS-rel violation as confirmed route leak;
- treat background-like as confirmed benign;
- train attack/benign classifier.

### Stage 3: Component-aware Learning Triage

Purpose:

- Learn ranking and calibration before Top-K review.
- Prioritize incidents/components under a human review budget.
- Learn component importance and evidence consistency.

Inputs:

- Stage 1 legacy weak signals
- Stage 2 verifier states
- component purity
- origin/path/stealth evidence
- abstain/conflict reasons

Outputs:

- `review_priority_score`
- `topk_rank`
- `should_split_score`
- `evidence_consistency_score`
- `recommended_action`

Does not:

- override verifier hard rules;
- produce confirmed attack/benign labels;
- hide conflict or abstention.

### Top-K Review Queue

The Top-K queue is the human-facing output after the learning ranker:

```text
Verifier output
  -> Learning ranker / calibrator
  -> Top-50 / Top-100 / Top-500 review queues
```

Top-K is not the learning layer itself. It is the budgeted review interface. Not all `evidence_insufficient`, `abstain`, or `background_like_but_unconfirmed` incidents are manually reviewed.

## 3. Old 7-layer Pipeline Reinterpretation

The legacy seven-layer pipeline is retained, but it is compressed into Stage 1.

| Legacy layer | Phase R role |
| --- | --- |
| event layer | Stage 1 input normalization |
| historical baseline | Stage 1 context / weak signal |
| candidate layer | Stage 1 monitor-trigger |
| score layer | Stage 1 legacy priority hint |
| gate layer | Stage 1 safety hint / weak signal |
| augment layer | Stage 1 early enrichment / weak signal |
| final `high/needs/low` | legacy priority hint, not truth |

The old seven-layer pipeline remains useful because it converts raw public-monitor data into structured incidents and evidence lookup keys. It is not the final detector contribution, and it does not output attack/benign truth.

Legacy `high/needs/low` and `P1/P2/P3` are priority and workflow hints only.

## 4. Module Non-overlap Table

| Module | Unique role | Input | Output | What it does not do | Failure if removed |
| --- | --- | --- | --- | --- | --- |
| Stage 1 incident construction | Converts raw monitor stream into reviewable incident/component bags and lookup keys | BGP updates, collector feeds, legacy weak signals | incident/member/component keys, legacy priority hints | Does not verify truth or decide attack/benign | Raw alerts remain too large and unstructured for evidence lookup or human review |
| RPKI/VRP origin evidence | Checks prefix-origin authorization against time-aligned VRP | prefix, origin AS, run date, VRP cache | RPKI status and origin evidence state | Does not validate AS path or prove attack/benign | Forged-origin-like cases lose the main independent origin evidence channel |
| AS-rel path evidence | Provides inferred path relationship evidence for path/route-leak diagnostics | AS pairs, triplets, AS paths, AS-rel cache | path evidence state, relation sequence, diagnostic flags | Does not prove route leak or benign path | Path manipulation and route-leak-like cases collapse back to origin-only evidence |
| Component purity/refinement | Detects mixed incidents before incident-level overclaim | member-level prefix-origin/path/RPKI evidence | purity class, split flags, component shares | Does not assign truth labels | Mixed incidents are overclaimed as suspicious or background |
| Verifier state machine | Enforces evidence states, confidence caps, abstain/conflict behavior | Stage 1 signals and evidence channels | verifier verdict candidates with provenance | Does not train or optimize ranking | Missing/conflicting/stale evidence gets hidden by scores |
| Learning ranker | Learns review priority and calibration under verifier constraints | verifier table, component/evidence features | review score, top-K rank, split/evidence consistency scores | Does not override hard rules or produce confirmed labels | Top-K review remains deterministic and may waste human budget |
| Top-K queue | Human-facing budgeted review interface | ranker scores, verifier verdicts, queue policy | Top-50/100/500 review sets | Does not learn or verify | Analyst burden remains unbounded |
| Future NO_EXPORT branch | Adds stealth/community evidence for monitor-evasive behavior | BGP communities, NO_EXPORT fields, collector visibility | stealth evidence state and diagnostics | Does not replace origin/path verifier | Low-visibility/stealth cases remain monitor-only |
| Future poisoning benchmark | Tests robustness under crafted public-monitor manipulation | monitor-only baseline, verifier variants, crafted announcements | robustness drop, evasion cost, top-K retention | Does not supply operational evidence | The CCF-A robustness claim remains untested |

## 5. Failure Modes and Why Each Module Exists

| Failure mode | Needed module | Why |
| --- | --- | --- |
| Raw monitor data is too large | Stage 1 incident construction | Aggregates event rows into incident/component cases with lookup keys |
| Monitor-only labels are poisonable | Stage 2 verifier | Public monitor output becomes trigger/context, not final judge |
| Origin-only evidence misses path attacks | AS-rel/path evidence | Route-leak/path-manipulation candidates need path semantics |
| Path-only evidence misses forged-origin cases | RPKI/VRP evidence | Origin authorization remains a separate evidence channel |
| Mixed incidents cause overclaim | Component purity/refinement | Incident-level verdicts require component consistency or abstention |
| Evidence missing or conflict | Abstain/conflict states | The system must refuse unsafe decisions instead of forcing labels |
| Too many review candidates | Learning ranker / Top-K queue | Ranking and budgeted review control human burden |
| Public monitor evasion | Future NO_EXPORT / stealth branch | Stealth evidence must not be hidden inside monitor-only score |
| Rule-based system lacks novelty | Poisoning benchmark + learning ablation | Robustness and learned triage must be tested, not asserted |

## 6. Ablation Plan

The paper evaluation should include ablations that map each module to a failure mode.

| Ablation | Removed / changed module | Expected degradation | Metric to measure | Redundancy defense |
| --- | --- | --- | --- | --- |
| A0 full system | none | Best evidence-supported triage under the full architecture | all core metrics | Reference point |
| A1 old seven-layer only | remove Stage 2 verifier and Stage 3 ranker | More unsupported alerts, hidden conflict, monitor-poisoning sensitivity | unsupported alert ratio, poisoning robustness drop, mixed incident overclaim rate | Shows legacy detector is not enough |
| A2 remove RPKI/VRP | remove origin evidence | Forged-origin-like evidence support drops; origin-invalid cases become insufficient/unknown | evidence-supported density, known-event retention, external unavailable rate | Shows origin evidence is not redundant with path evidence |
| A3 remove AS-rel path evidence | remove path evidence | Route-leak/path-manipulation review support drops | route-leak review density, path evidence coverage, Top-K supported density | Shows path evidence is not redundant with RPKI |
| A4 remove component purity | no component audit/split flags | Mixed incidents overclaimed as suspicious/background | mixed incident overclaim rate, conflict preservation rate | Shows component-awareness is needed |
| A5 remove abstention/conflict | force all cases into supported/background | Unsafe precision proxy and hidden uncertainty | conflict preservation rate, abstain safety rate, unsupported alert ratio | Shows abstention is a reliability mechanism |
| A6 remove learning ranker | deterministic score only | Lower Top-K supported density and weaker calibration | Top-K supported density, human review burden | Shows learning adds ranking value without replacing verifier |
| A7 remove Top-K budget | full manual review | Human workload explodes | human review burden, daily review count | Shows Top-K is necessary for deployability |
| A8 poisoning setting | monitor-only vs verifier-constrained | Monitor-only degrades more under crafted announcements | poisoning robustness drop, evasion cost, top-K retention | Shows verifier matters under adversarial monitors |
| A9 stealth setting | with/without communities/NO_EXPORT branch if fields available | Monitor-evasive weak cases remain under-supported without stealth evidence | stealth evidence coverage, known-event retention, unsupported alert ratio | Shows stealth branch is not decorative if data exists |

Core metrics:

- unsupported alert ratio
- evidence-supported density
- Top-K supported density
- conflict preservation rate
- abstain safety rate
- human review burden
- poisoning robustness drop
- known-event retention
- mixed incident overclaim rate
- runtime / online lookup latency

## 7. Reviewer Attack and Defense

| Reviewer attack | Defense |
| --- | --- |
| Too many modules / redundant architecture | The architecture is locked to three stages. Each stage maps to a distinct failure mode and has a planned ablation. |
| Rule engineering | Rules are verifier safety constraints, not learned truth. The learning ranker is explicitly reserved for component/evidence priority under hard verifier rules. |
| No complete ground truth | The paper targets evidence-supported triage under partial ground truth. Evaluation uses Top-K density, known-event retention, conflict/abstain preservation, and poisoning robustness rather than binary attack/benign accuracy. |
| Human burden remains high | Insufficient/abstain/background cases are not fully manual. Human review is budgeted through Top-K queues, conflict caps, split queues, and sampling. |
| AS-rel/RPKI are not truth | They are evidence channels with provenance, confidence caps, and abstention. RPKI invalid is not confirmed attack; AS-rel violation is not confirmed route leak. |
| Learning may hide unsafe evidence | The learning layer sits after the verifier and before Top-K. It cannot override hard safety rules or hide conflict/abstention. |
| Old seven-layer detector is still there | It is Stage 1 incident construction and weak-signal context, not the final detector or the paper's truth source. |

## 8. Next Roadmap After Architecture Lock

Recommended order:

1. R-2D-0 communities / NO_EXPORT field availability audit.
2. R-3 poisoning / evasion benchmark design.
3. L1 component-aware semantic learner design.
4. Architecture ablation implementation.
5. R-2D community-aware stealth evidence branch if fields exist.

R-LOCK-1 is a paper-safety step. It keeps the system from drifting into a module pile and gives each future experiment an ablation reason.
