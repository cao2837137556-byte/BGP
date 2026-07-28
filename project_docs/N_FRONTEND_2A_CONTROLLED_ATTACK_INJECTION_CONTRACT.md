# N-FRONTEND-2A: Controlled Attack Injection Contract

Status: design contract drafted for independent review; no attack rows have
been materialized under this contract.

Date: 2026-07-28.

## 1. Purpose

N-FRONTEND-2A proposes the contract for how controlled clean, poisoned, and
visibility-evasive scenarios may enter the new causal frontend. It becomes
frozen only after independent review. This is a design and qualification
phase, not a replay result.

The next bounded replay will exercise:

```text
evaluation-only canonical observations
  -> reversible exact-observation deduplication
  -> past-only per-peer route transitions
  -> fixed-window micro-events
```

The purpose is to determine whether scenario phases and route-history effects
remain semantically traceable. The current frontend has no background
suppression decision and no long-horizon memory. Therefore a retained row or
an attack-retention value near `1.0` cannot establish poisoning robustness.

Allowed conclusion after a successful N-FRONTEND-2B replay:

```text
semantic survival and past-only exposure under paired variants
```

Forbidden conclusions:

```text
poisoning robustness
poisoning-resistant detection
attack detection accuracy
background suppression safety
production readiness
```

## 2. Injection Boundary

Controlled observations enter immediately before
`canonical_observation_v2`. They must pass the same identity, exact-dedup,
transition, and micro-event functions as real observations.

The following are forbidden inputs:

- old candidate, score, gate, augmentation, or final outputs;
- old R-FOREGROUND assignments;
- legacy `high / needs / low` or `P1 / P2 / P3` labels;
- attack rows inserted directly into transition or micro-event outputs;
- detector scores used as attack truth or retention guards.

The frozen nine-day asset remains immutable and keeps the role
`unlabeled_operational_background`. A mixed evaluation asset is a separately
versioned derivative and must never be promoted to benign background or
negative training truth.

## 3. Reused Contracts and Version Anchors

Only scenario semantics and realism constraints are reused. No old
candidate/foreground artifact is a data input.

| Source contract | Version anchor | Reused content |
|---|---|---|
| `configs/r_attack0b_multi_attack_smoke_v01.json` | `2775002a1cc5bc3629036128f36409b6a7f77408` | exact-origin, forged-origin, path-manipulation, hard-negative template constraints |
| `scripts/materialize_r_attack0b_multi_attack_smoke.py` | `2775002a1cc5bc3629036128f36409b6a7f77408` | observed-template and dynamic-role selection ideas only |
| `configs/r_attack1_family_expansion_v01.json` | `4b31b184ff643fef58a4aa836a46b818ab2f2507` | subprefix and NO_EXPORT scenario semantics |
| `scripts/materialize_r_attack1_family_expansion.py` | `4b31b184ff643fef58a4aa836a46b818ab2f2507` | real NO_EXPORT template selection constraints only |
| `configs/r_poison0_paired_benchmark_protocol_v01.json` | `cc9cd18a1d16c2b3d85bf9ac29739f576517b892` | clean/adversarial pairing and threat-model boundaries |
| `scripts/materialize_r_poison1_bounded_pairs.py` | `2e88fb5f7a5f545ea5d31b37a0289665c1f9ac59` | phase vocabulary and pair registry ideas only |

The N-FRONTEND-2 implementation must rematerialize observations against the
new canonical schema. Reusing an old scenario ID does not authorize copying
old materialized rows.

## 4. Formal Coverage Boundary

The bounded replay may make structural-survival observations for:

1. origin hijack, including exact-origin, forged-origin, and subprefix cases;
2. path manipulation;
3. stealth visibility / NO_EXPORT cases that remain publicly observable under
   their declared visibility contracts;
4. paired poisoning/evasion variants as an adversarial threat-model track.

Route-leak-like cases remain path-policy diagnostics. CAIDA AS-rel shape,
valley-like transitions, or suspect triplets are not route-leak truth. Formal
route-leak attack-family coverage is blocked until a bounded policy-semantics
contract based on propagation policy, BGP Roles/OTC, operator confirmation, or
equivalent evidence is available.

## 5. Canonical Identity and Provenance

Every injected observation must:

- contain the same canonical semantic fields as a real observation;
- derive `observation_id` by calling
  `canonical_observation_id()` from
  `scripts/r_mem_canonical_observation_v2.py`;
- never receive a hand-written or scenario-derived observation ID;
- carry a synthetic source reference of the form
  `synthetic://n_frontend2/<scenario_id>/<variant>/<phase>/<member_id>`;
- retain the real source template reference only in an evaluation sidecar;
- keep truth, scenario, phase, attack role, and expected outcomes outside the
  online canonical feature frame.

Required sidecar linkage:

```text
observation_id
scenario_id
pair_id
variant_role
phase_id
member_id
template_observation_id
template_source_file
synthetic_source_uri
is_attack_member
is_poisoning_preparation_member
expected_visibility_class
```

Hard gates:

- accidental observation-ID collisions between injected and background rows:
  `0`;
- accidental exact semantic duplicates between injected and background rows:
  `0`;
- accidental duplicates across scenario members: `0`;
- unresolved canonical IDs: `0`;
- truth columns in the canonical online frame: `0`.

This phase declares no intentional exact-duplicate injection. A later explicit
dedup stress test must preregister its duplicate count instead of hiding it in
the attack replay.

## 6. Realism and Template Qualification

### 6.1 General Template Rules

Every controlled route must be derived from a real canonical observation
template. The materializer may change only fields authorized by the scenario
contract. It must not:

- use documentation ASNs;
- choose arbitrary AS insertion points without a declared path-role rule;
- synthesize an impossible prefix relationship;
- borrow a real source-file URI for a synthetic row;
- alter victim, attacker, prefix family, background window, collector set, or
  attack template between a clean/adversarial pair unless the declared threat
  model requires the visibility difference.

The scenario registry must record the real template observation ID, collector,
peer address, prefix, path, communities, and timestamp before transformation.

### 6.2 NO_EXPORT and Visibility Rules

NO_EXPORT is propagation-control evidence, not attack truth. A low-visibility
observation is not confirmed NO_EXPORT, and missing NO_EXPORT is not safety.

Before N-FRONTEND-2B, the current peer-aware canonical asset must be audited
for a template pool in which normalized communities directly contain
NO_EXPORT. The old April 16 sidecar count demonstrates prior field
availability but does not by itself qualify a new nine-day template.

A NO_EXPORT/stealth scenario must:

- use a `(collector, peer_address)` template observed with NO_EXPORT;
- freeze its expected visible and non-visible collector/peer set before
  materialization;
- keep a public-invisible case outside the observed-attack retention
  denominator and report it as an observability boundary;
- distinguish monitor-visible NO_EXPORT evidence from an Internet-wide attack
  claim.

If no qualified current template exists, the scenario is blocked rather than
silently synthesized.

## 7. Episode and Placement Contract

The old five-minute frontend replay is not an attack-episode template. A
detection-data-poisoning episode needs enough time for:

```text
stable_baseline
  -> poisoning_preparation
  -> attack_launch
  -> recovery
```

N-FRONTEND-2B must use an episode of at least 60 minutes. Exact timestamps are
selected only after an empirical cadence audit confirms that the victim
peer-prefix has suitable real background observations and that every phase is
represented.

Minimum placement constraints:

- attack launch is at least 10 minutes after the episode start;
- attack launch is at least 10 minutes before the episode end;
- poisoning preparation precedes attack launch strictly;
- the last poisoning-preparation observation and attack launch are separated
  by at least 5 minutes;
- recovery follows attack launch strictly;
- clean and adversarial variants use the same episode boundaries;
- all scenario timestamps are declared before replay;
- timestamp selection uses row `ts`, never archive filename time.

These windows are bounded proxies. `first_seen_age` means first seen within the
available episode/history asset, not first seen on the Internet.

## 8. Same-Timestamp Ambiguity Contract

Accidental `(collector, peer_address, prefix, ts)` collisions between injected
and background observations are forbidden.

The primary paired scenarios avoid same-timestamp collisions. A separate
ambiguity stress case may be included only if its registry declares:

```text
ambiguity_stress = true
expected_ambiguous_group_count
expected_ambiguous_member_count
expected_reason
```

Declared ambiguous members must remain `unknown-order` context through
transition and micro-event construction. They are neither attack truth nor
background truth. Undeclared ambiguity is a scenario-QA failure.

## 9. Pair Fairness Contract

For each clean/adversarial pair, freeze before materialization:

- victim, attacker, and prefix family;
- real background episode;
- real route template;
- attack launch and recovery timestamps;
- collector and peer universe;
- evidence snapshot identifiers, if evidence is attached;
- attack transformation;
- visibility contract;
- expected transition pattern.

The adversarial variant may differ only in the preregistered poisoning
preparation or visibility manipulation. Evaluation truth is never an online
feature.

Pair-fairness failures block replay interpretation:

- victim, attacker, or prefix mismatch;
- different background windows;
- different clean attack templates;
- unregistered collector/peer changes;
- evidence snapshot drift;
- phase or timestamp changes not required by the threat model.

## 10. Preregistered Measurements

### 10.1 Semantic Phase Survival

`semantic_phase_survival` is the hard structural gate. For every expected
visible member, the sidecar must trace:

```text
injected canonical observation
  -> exact-dedup membership
  -> transition ID
  -> micro-event ID
```

Report by scenario, variant, phase, collector, peer, and ambiguity membership.
Any loss must be localized to canonicalization, exact deduplication,
transition construction, or micro-event grouping.

A public-invisible member declared by the visibility contract is an
observability boundary, not a frontend miss.

### 10.2 Past-Only Route Exposure Delta

The canonical metric name is `past_only_route_exposure_delta`.

For detection-data-poisoning pairs, compute before each attack observation:

- whether the attack route signature was previously exposed;
- prior exposure count;
- first-seen age within the bounded history;
- last-seen gap;
- distinct prior peer count;
- distinct prior collector count;
- whether prior exposure was short-lived and withdrawn;
- whether exposure occurred only in the poisoning-preparation phase.

Every value must be derived from causal transition records satisfying:

```text
transition_ts < attack_ts
```

Full-frame operations such as
`groupby(...).transform("count")` are forbidden. The validator must assert that
no transition at or after `attack_ts` contributes to a past-only feature.

`first_seen_age`, recurrence, and recency are explicitly reported as
within-window bounded proxies because the episode has no pre-window RIB or
Internet-wide history.

For visibility-evasion pairs, this metric is optional context and must not
replace the collector/peer visibility contract.

### 10.3 Attack Transition Semantic Delta

The canonical metric name is `attack_transition_semantic_delta`.

For every pair, report a clean-versus-adversarial transition-family matrix for
the attack phase. This is explanatory evidence, not a binary robustness gate.

Each scenario must preregister one implementation mode and its expected
adversarial family set:

| Pair | Required implementation mode | Expected clean attack family | Expected adversarial family set | Primary interpretation |
|---|---|---|---|---|
| `pair_exact_origin_history_poisoning_v01` | legitimate route active; poison announce, withdraw, then attack | `announcement_change` | `{withdraw_reannounce_same}` | attacker route was exposed and withdrawn before launch |
| `pair_forged_origin_history_poisoning_v01` | legitimate route active; forged route announce, withdraw, then attack | `announcement_change` | `{withdraw_reannounce_same}` | forged route history was deliberately pre-exposed |
| `pair_path_manipulation_history_poisoning_v01` | manipulated path announce, withdraw, then attack | `announcement_change` | `{withdraw_reannounce_same}` | path novelty was converted into recent route history |
| `pair_subprefix_noexport_evasion_v01` | visibility manipulation only | preregistered from selected template | same family for each expected-visible observer, unless a declared community change causes `announcement_change` | collector visibility, not route-history poisoning |
| `pair_stealth_collector_asymmetry_v01` | collector/peer visibility manipulation only | preregistered from selected template | same family for each expected-visible observer | public-monitor asymmetry |

An implementation may use an alternative mode, such as keeping the poison
route active or restoring the legitimate route, only by changing the
preregistered expected set before replay:

- active poison route may yield `identical_reannouncement`;
- legitimate restoration may leave the attack as `announcement_change`;
- withdrawn poison route may yield `withdraw_reannounce_same`.

If the observed family is outside the preregistered set, including no
unexpected difference or an adversarial route that appears more novel than
the clean route, the result is a scenario-materialization QA failure. It is
not evidence that the frontend is robust or fragile.

## 11. N-FRONTEND-2B Stop-Loss Gates

Do not interpret or promote the replay if any of the following occurs:

- a source template is not present in the immutable canonical asset;
- an injected observation does not use the canonical ID function;
- accidental collision or duplicate count is non-zero;
- truth leaks into online fields;
- a pair-fairness field changes outside its threat-model allowance;
- a scenario phase is missing or cannot be traced;
- a past-only metric uses data at or after attack time;
- an undeclared same-timestamp ambiguity is created;
- a poisoning pair falls outside its preregistered transition pattern;
- a NO_EXPORT scenario lacks a qualified real NO_EXPORT peer/collector
  template;
- a public-invisible member is counted as a frontend miss;
- route-leak diagnostic output is promoted to route-leak truth;
- the report uses poisoning-robustness language.

Failure before canonical replay is an input/scenario engineering failure, not
a scientific frontend result.

## 12. Required N-FRONTEND-2B Artifacts

The future bounded replay must produce at least:

- versioned scenario registry;
- immutable background input manifest;
- synthetic observation manifest;
- truth/provenance sidecar;
- identity-collision and exact-duplicate audit;
- pair-fairness audit;
- phase-survival lineage table;
- past-only exposure table with causality validation;
- clean/adversarial transition-family delta matrix;
- visibility-contract audit;
- ambiguity-intersection audit;
- per-stage drop-localization table;
- summary and allowed/forbidden-claim report.

All mixed canonical data and replay outputs must be written below an
`evaluation_only`-named, versioned directory. They must not modify the frozen
nine-day asset, old attack outputs, or future training pools.

## 13. Next Action

1. Independent review of this contract checks causality, expected transition
   patterns, template realism, and contamination boundaries.
2. After review acceptance, freeze the contract without materializing data.
3. Implement N-FRONTEND-2B bounded materialization and replay.
4. Design background suppression only after structural survival and
   adversarial semantic-delta QA pass.

This phase does not train learning, attach attack truth to online features,
implement suppression, or claim poisoning robustness.
