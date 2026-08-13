# N-FRONTEND-3A: Background Suppression Contract

Status: draft pending independent review; no suppression policy is implemented
or tuned under this contract.

Date: 2026-08-13.

Review chain:

- Driver: Codex;
- Reviewer: Kimi;
- freeze: pending an independent review of this draft.

## 1. Purpose and Four-Part Gate

N-FRONTEND-3A defines a causal, reversible routing decision between the
existing bounded micro-event layer and the future learning layer. It does not
classify a route as benign or malicious. It asks only whether an input record
adds routing semantics that must be sent to the learning layer.

The operational path is:

```text
canonical observations
  -> reversible exact deduplication
  -> observer-local causal transitions
  -> bounded micro-events
  -> N-FRONTEND-3 suppression routing
       -> semantic_foreground          -> learning input
       -> gray_contract_anomaly         -> audit / investigation
       -> reversible_background_summary -> history query, not learning input
```

The four-part gate is frozen as follows.

### 1.1 Goal

- reduce the number of transition and micro-event rows delivered to learning;
- suppress only records that add no new route-state semantics;
- preserve attack establishment, withdrawal/reannouncement, visibility,
  ambiguity, and poisoning-preparation information;
- keep every routed background member recoverable from immutable provenance;
- preserve every contract-defined past-only metric exactly.

This is **learning-input load reduction**, not disk or archival compression.
Original members remain in immutable background storage. No storage-saving
claim is authorized.

### 1.2 Required Evidence

Suppression eligibility requires only the frozen N-FRONTEND-1 transition
semantics and reversible provenance:

- observer identity: collector, peer address, prefix, and path identifier when
  available;
- transition timestamp and transition family;
- old and new route signatures;
- origin, path, communities, and next-hop change flags;
- same-timestamp ambiguity state;
- member observation and transition identifiers;
- source files and source-copy accounting;
- the observer-prefix route ledger immediately before time `t`.

The following may protect or describe a record, but can never authorize
suppression:

- prefix-origin, AS-edge, or path exposure and maturity;
- RPKI / VRP state;
- AS-relationship diagnostics;
- communities, including NO_EXPORT;
- visibility and collector asymmetry;
- missing, stale, unavailable, or conflicting external evidence.

### 1.3 Stop-Loss Summary

N-FRONTEND-3B cannot be promoted if it changes a past-only value, suppresses
an expected-visible controlled member, loses a scenario phase or semantic
delta, uses future information, loses provenance, contaminates an operational
background denominator with injected truth, or produces a non-zero gray-zone
count without a contract-level root-cause decision. Section 12 gives the full
list.

### 1.4 Forbidden Conclusions

This contract does not authorize claims of:

```text
benign suppression
attack or benign classification
attack detection accuracy
poisoning robustness
poisoning-resistant detection
storage compression
nine-day or production throughput
production readiness
```

## 2. Version Anchors and Frozen Replay

N-FRONTEND-3B must use the following semantic anchors unless a reviewed
contract amendment explicitly replaces one.

| Item | Frozen anchor | Role |
|---|---|---|
| transition schema | `configs/n_frontend1_causal_transition_v01.json`, introduced by `f2cd1617c768cdc480b42f7ac933a8504712d25c`, SHA256 `42f38af0a46e392eeb1d5d23068601c116e8dc7d0ed604ca052e704333780938` | single source of transition taxonomy, state identity, route signature, and change flags |
| transition implementation | `scripts/build_n_frontend1_causal_transitions.py` at mainline anchor `eab351c24e4dca187d6dea7b63b8e058c38e29ae` | causal state machine and bounded micro-event construction |
| paired replay protocol | `configs/n_frontend2b_controlled_pairs_v01.json`, SHA256 `1770f46ed50312f50b66099501a1eb5d6b8ca98382a303d24cb5754ab3da2a51` | controlled safety scenarios |
| formal paired replay | pair `n_frontend2b_20260805T023615Z` | frozen comparison result |
| episode | `2024-04-11 12:00:00-13:00:00 UTC`, selected by row `ts` | N-FRONTEND-3B bounded replay window |
| observer registry | freeze fingerprint `1c14273522bd46a44864526f64cad558d6cf1bbdecc61af9b52f345da2a3a4fc` | observer-local scenario and visibility contract |
| paired protocol result | protocol SHA256 `3b802853042b05cee2283cb82328e6b056552e977e05164cc00352c0f8bbe164` | formal 2B result provenance |

The frozen nine-day asset keeps the role `unlabeled_operational_background`.
The mixed replay remains `evaluation_only`; truth sidecars are never online
features and never enter suppression-rate denominators.

## 3. Mature Mechanisms Reused and Rejected

This layer is not designed from scratch. It narrows and combines mature
mechanisms under stricter security contracts.

| Source mechanism | Decision | Boundary |
|---|---|---|
| BEAM observer-local routing monitor and route-change semantics | adapt | no BEAM embedding or anomaly score is suppression truth |
| FRRouting `bgp suppress-duplicates` principle | reuse safety kernel | only a route that actually did not change is initially eligible |
| DFOH new-edge / maturity exposure | diagnostic and protection context | historical occurrence or maturity never authorizes suppression |
| RFC 2439 / RIPE-580 / RFC 7196 penalty and decay forms | defer | may summarize chronic churn only after N-FRONTEND-3C demonstrates need; never equate flap with benign noise |
| BGPalerter / ARTEMIS streaming state-machine shape | optional deployment reference | neither detector output is a suppression label |
| old R-FOREGROUND policies | offline comparison only | full-frame recurrence and the old 50 percent gate are not inherited |

The project-specific contribution is the combination of reversible
three-way routing, asymmetric use of evidence, exact history preservation,
and paired adversarial safety gates.

## 4. Suppression Unit and Deterministic Precedence

### 4.1 Transition-First Decision

Every transition is classified before its micro-event. The transition-level
assignment is one of:

- `protected_semantic_foreground`;
- `suppressible_semantic_redundancy`;
- `gray_contract_anomaly`.

Micro-event routing then uses this precedence:

1. if any member is protected, route the complete micro-event to
   `semantic_foreground`;
2. otherwise, if any member is gray, route the complete micro-event to
   `gray_contract_anomaly`;
3. only when every member is suppressible may the micro-event be omitted from
   the learning-input stream and represented by a reversible background
   summary.

This rule prevents a protected observer transition from being hidden inside a
multi-observer micro-event.

### 4.2 Initial Suppression Eligibility

N-FRONTEND-3B has one parameter-free eligibility rule. Every condition is
required:

```text
transition_family == identical_reannouncement
old_route_signature is not null
new_route_signature is not null
old_route_signature == new_route_signature
origin_changed == false
path_changed == false
communities_changed == false
next_hop_changed == false
same_timestamp_ambiguous == false
state_known_before == true
state_known_after == true
observer identity is complete
member identity and source provenance are reversible
```

The meaning of route signature and every change flag comes exclusively from
N-FRONTEND-1. N-FRONTEND-3 must not define a second meaning of "same route".

### 4.3 Mandatory Foreground

All other qualified route transitions remain foreground, including:

- bootstrap announcement or withdrawal;
- announcement changes of any route attribute;
- withdrawal and repeated withdrawal;
- withdrawal followed by same or changed reannouncement;
- same-timestamp ambiguity;
- state-recovery transition;
- more-specific appearance represented by the existing prefix semantics;
- any transition with a community or visibility-relevant state change.

During evaluation, the frozen N-FRONTEND-2B truth sidecar audits whether every
expected-visible member reached foreground under these semantic rules. Truth
membership must not alter an online assignment or act as a protection feature.

RPKI valid, AS-rel matched, NO_EXPORT absent, broad visibility, or historical
recurrence never changes this list.

## 5. Gray Zone as a Contract Tripwire

Gray is not a storage drawer for difficult routes. It has one legal trigger:

> A route transition reaches N-FRONTEND-3 with incomplete identity, state, or
> reversible provenance, so semantic redundancy cannot be proved and normal
> foreground accounting cannot be trusted.

Examples are a missing transition/member ID, an incomplete observer-prefix
identity, or unrecoverable source provenance. Same-timestamp ambiguity is not
gray; it is protected unknown-order foreground.

Non-route control records bypass N-FRONTEND-3 entirely and remain in the
N-FRONTEND-1 dedicated non-route audit artifact.

The expected gray-zone count and rate are zero. Any non-zero value is a
contract anomaly that must be investigated. Promotion stops unless an
independently reviewed contract amendment classifies the cause. Gray records
are never silently treated as background or benign.

## 6. Information-Preservation Invariant

Suppression is a routing decision, not deletion. It must preserve both raw
membership and derived causal history.

### 6.1 Storage and Query Architecture

For every suppressed transition or micro-event:

- original member observations and transitions remain in immutable background
  storage;
- the background summary is an index and aggregate view, not a replacement for
  member records;
- the summary preserves member IDs, observer/prefix identity, route signature,
  first and last timestamps, ordered cadence information, member count, source
  files, and a reversible lookup to every original member;
- all downstream historical and exposure queries use a
  `foreground-plus-background joint view`, defined as the union of foreground
  members and immutable background members;
- querying only the foreground stream for route history is forbidden.

### 6.2 Exact Past-Only Equality

For every controlled attack observation and every audited observer-route
query, the pre-suppression and post-suppression joint views must return exactly
the same normalized values for:

- `previously_exposed`;
- `prior_exposure_count`;
- first-seen time and `first_seen_age_sec`;
- last-seen time and last-seen gap / recency;
- ordered inter-arrival gaps or the contract-defined cadence sequence;
- distinct prior time buckets and days when available;
- distinct prior peer and collector sets/counts;
- prior withdrawal and short-lived exposure state;
- poisoning-preparation-only exposure state.

Scalar values must be byte-equivalent after canonical serialization; sets and
sequences must use the frozen deterministic ordering. All contributing
transitions must satisfy `transition_ts < query_ts`.

A count-only summary is insufficient. Any mismatch is information loss and an
immediate stop-loss, even when every attack row remains in foreground.

## 7. Causal Processing Invariant

N-FRONTEND-3 is a single-pass, stable-time-ordered streaming decision.

- a decision at time `t` may read only the observer ledger state produced by
  transitions strictly before or at the current ordered transition according
  to the frozen same-timestamp contract;
- future windows, future recurrence, and the completed-frame population are
  unavailable to the decision;
- full-frame operations such as `groupby(...).transform(...)` are forbidden
  for online eligibility or protection;
- fixed micro-events become available only at their frozen window end;
- same-timestamp ambiguous members remain unordered as a group;
- N-FRONTEND-3B must replay decisions in strict causal order and independently
  compare the assignments and ledger fingerprint.

This invariant applies to future churn or decay extensions as well as v1.

## 8. Attacker-in-the-Loop Analysis

### 8.1 Hiding Attack Semantics

An attacker may try to place an attack in a suppressible category.

- establishment of a new route, changed origin/path/community/next hop,
  withdrawal, and reannouncement after withdrawal are structurally outside
  v1 eligibility;
- the frozen short-term poisoning attacks degrade to
  `withdraw_reannounce_same`, which remains protected;
- only sustained identical reannouncements can enter the background route;
- Section 6 guarantees that such repetitions still contribute exactly to
  historical exposure and cadence, preventing long-term maturity poisoning
  from becoming invisible merely because its carrier rows were routed away
  from learning input.

Every frozen N-FRONTEND-2B pair must be evaluated against this enumeration.

### 8.2 Foreground Exhaustion

An attacker may instead create many semantically changing updates so every
record remains protected and the learning input is exhausted. V1 does not
suppress such changes because doing so would weaken the hiding boundary.

N-FRONTEND-3B must therefore report per-observer-prefix foreground share and
volume, including p50, p90, p99, maximum, top contributors, and transition
family composition. This is monitoring evidence, not a mitigation claim.
Decay, rate limiting, or churn suppression remains forbidden in 3B.

## 9. Preregistered Metrics and Denominators

### 9.1 Meaning of Compression

All suppression and compression metrics describe **learning-input row load**.
They do not describe raw storage bytes, immutable archive size, or retained
provenance volume.

### 9.2 Eligible Operational-Background Population

The suppression-rate denominator contains only rows whose lineage is entirely
from the frozen `unlabeled_operational_background` asset.

- injected observations and transitions are excluded;
- micro-events containing any injected member are excluded in full;
- truth sidecar rows are excluded;
- evaluation-only scenario members participate only in safety and retention
  gates;
- the denominator is never called benign or normal truth.

### 9.3 Transition-Level Load

Report:

```text
transition_background_input_count
transition_background_suppressed_count
transition_learning_input_count
transition_learning_input_reduction_rate
transition_learning_input_compression_ratio
```

where reduction is suppressed operational-background transitions divided by
eligible operational-background transitions, and compression ratio is input
count divided by learning-input count. Exact-dedup reduction is reported
separately and must not be counted again.

### 9.4 Micro-Event-Level Load

Report the corresponding background-only micro-event counts, reduction rate,
and compression ratio after deterministic member-level precedence. This is the
primary learning-layer load result.

Transition and micro-event rates must both be shown. A high transition-level
rate with a low micro-event-level rate indicates protected members are sharing
events with redundant transitions; it is not silently reported as success or
failure.

### 9.5 Composition and Exhaustion Metrics

Also report:

- foreground, suppressed-background, and gray counts/rates;
- foreground and suppressed counts by transition family;
- micro-event member-count distribution;
- per-observer-prefix foreground share and volume distribution;
- top observer-prefix contributors;
- public-invisible members as observability boundaries, not drops;
- all denominators and exclusions as explicit audit tables.

The old 50-70 percent operational-background target is an engineering
objective only. It is neither a passing gate nor a literature guarantee.

## 10. Frozen N-FRONTEND-2B Safety Gate

N-FRONTEND-3B reuses the same episode, pair registry, and expected-visible
membership as the formal N-FRONTEND-2B result.

Required safety results are:

- `suppressed_attack_count == 0`;
- every expected-visible stable, poisoning-preparation, attack, and recovery
  member remains traceable;
- every public-invisible member remains an observability boundary;
- clean/adversarial transition-family matrices remain observable after
  routing;
- all three poisoning pairs retain their preregistered
  `announcement_change -> withdraw_reannounce_same` difference;
- the pre/post joint-view past-only exposure table is exactly equal under
  Section 6.2;
- ambiguity membership and observer visibility contracts remain unchanged;
- no truth field participates in an online assignment.

This gate proves bounded semantic preservation under v1 routing. It does not
prove detection accuracy or poisoning robustness.

## 11. Required N-FRONTEND-3B Artifacts

The bounded implementation must produce at least:

- versioned suppression configuration and code fingerprint;
- immutable input and frozen pair-registry manifests;
- transition-level assignment table with eligibility/protection reason codes;
- micro-event-level routing table with member-decision precedence;
- reversible background-summary index;
- immutable background-member manifest and restoration audit;
- non-route bypass audit;
- gray-tripwire audit;
- causal strict-replay assignment and ledger-fingerprint audit;
- background-only denominator and exclusion audit;
- transition-level learning-input load report;
- micro-event-level learning-input load report;
- foreground family-composition report;
- observer-prefix foreground-exhaustion report;
- N-FRONTEND-2B phase-survival and transition-delta regression;
- pre/post past-only exposure equality table;
- per-stage unexplained-loss and provenance audit;
- deterministic replay and, when run on HPC, AMD/Intel parity audit;
- stop-loss summary and allowed/forbidden-claim report.

All evaluation products must be written to a new versioned output root. The
frozen nine-day asset, N-FRONTEND-1 artifacts, N-FRONTEND-2B results, and old
foreground outputs are immutable inputs or references.

## 12. N-FRONTEND-3B Stop-Loss Gates

Do not interpret or promote the result if any of the following occurs:

- any expected-visible controlled attack member is background-routed;
- any stable, preparation, attack, or recovery phase loses traceability;
- a frozen clean/adversarial semantic delta is no longer observable;
- any Section 6.2 pre/post past-only value differs;
- a history query reads foreground only or cannot restore a background member;
- an ambiguity group is ordered, split unsafely, or background-routed;
- a withdrawal, reannouncement-after-withdrawal, bootstrap, route change, or
  state-recovery transition is background-routed;
- a missing/stale external evidence value authorizes suppression;
- a decision uses a transition at or after its query time or any future-frame
  statistic;
- causal strict replay disagrees with the primary assignment;
- truth or injected membership enters an online feature or suppression-rate
  denominator;
- gray-zone count is non-zero without a reviewed contract amendment;
- input/output/provenance accounting is incomplete or unexplained loss is
  non-zero;
- deterministic replay or required cross-partition semantic parity fails;
- public-invisible members are counted as frontend misses;
- the report uses benign-suppression, poisoning-robustness, storage-compression,
  or scale-generalization language.

Failure before suppression assignment is an engineering/input failure, not a
scientific suppression result.

## 13. Allowed and Forbidden Reporting

After all N-FRONTEND-3B gates pass, the strongest allowed claim is:

```text
bounded learning-input redundancy reduction with exact past-only history
preservation; the frozen paired variants remain semantically observable under
the parameter-free identical-reannouncement routing rule
```

Allowed measurements include transition-level and micro-event-level
unlabeled operational-background learning-input reduction, reversible lineage,
gray-tripwire state, and foreground-exhaustion profiles.

Forbidden interpretations include:

- suppressed rows are benign or safe;
- unsuppressed rows are attacks;
- RPKI, AS-rel, communities, visibility, or maturity proves either class;
- attack detection or learning performance has been measured;
- short-term paired survival proves long-term or general poisoning robustness;
- learning-input reduction saves raw storage;
- one bounded episode proves nine-day or production scalability.

## 14. Staged Next Actions

1. **N-FRONTEND-3A**: independently review and freeze this design. No policy
   implementation or threshold tuning is allowed before freeze.
2. **N-FRONTEND-3B**: implement the parameter-free
   `identical_reannouncement` rule and replay the frozen one-hour episode.
3. **N-FRONTEND-3C**: after 3B passes, evaluate one day and then the frozen
   nine-day asset, reporting load, latency, memory, state size, and temporal
   stability.
4. Only if 3C demonstrates insufficient load reduction may a new reviewed
   contract investigate chronic-churn summaries, decay, or maturity-aware
   routing. Such mechanisms must repeat the hiding and exhaustion audits.

This phase does not implement suppression, train learning, modify the old
seven-layer pipeline, or change any verifier verdict.

## 15. Primary Research and Engineering Anchors

- BEAM, USENIX Security 2024:
  <https://www.usenix.org/conference/usenixsecurity24/presentation/chen-yihao>
- DFOH, NSDI 2024:
  <https://www.usenix.org/conference/nsdi24/presentation/holterbach>
- public-history poisoning threat analysis:
  <https://arxiv.org/abs/2507.20434>
- Route Flap Damping specifications and operational correction:
  <https://www.rfc-editor.org/rfc/rfc2439.html>,
  <https://www.ripe.net/publications/docs/ripe-580/>, and
  <https://www.rfc-editor.org/rfc/rfc7196.html>
- FRRouting duplicate-suppression engineering reference:
  <https://docs.frrouting.org/en/latest/bgp.html>
