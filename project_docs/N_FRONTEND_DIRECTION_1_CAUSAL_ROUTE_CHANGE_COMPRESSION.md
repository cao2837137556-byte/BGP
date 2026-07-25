# N-FRONTEND-DIRECTION-1: Causal Route-Change Compression

Status: direction frozen; implementation and bounded validation are next.

Date: 2026-07-25.

## 1. Decision

The new frontend will be a **peer-aware, causal route-change compression
layer**:

```text
canonical_observation_v2
  -> reversible exact-observation deduplication
  -> per-peer route-state transition extraction
  -> bounded micro-event aggregation
  -> three-way foreground decision
       foreground
       gray_zone
       operational_background_suppressed
```

This layer replaces neither the future multi-attack judgment layer nor the
final suspicious-event aggregation layer. It reduces repetitive operational
updates while preserving attack-like, stealth-like, poisoning-prelude-like,
unavailable-evidence, and genuinely ambiguous changes.

The old seven-layer pipeline is not an input, dependency, or design baseline.
The reusable local experience comes only from the later R-FOREGROUND line.

## 2. Why This Direction

There is no mature off-the-shelf component whose contract is "safely compress
public BGP background while preserving multiple attack families and
poisoning/evasion variants." Reusing a complete detector as the frontend would
silently import its attack assumptions and false-negative boundary.

The efficient path is therefore selective reuse:

- keep the already-qualified `canonical_observation_v2` data contract;
- use the BGP/RIB state model and standard route-change taxonomy instead of
  inventing arbitrary row rules;
- absorb mature mechanisms from BEAM and DFOH without treating their final
  detector scores as suppression truth;
- retain the strongest safety and audit contracts from R-FOREGROUND;
- implement only the missing project-specific compression decision.

## 3. Scientific Correction to the Old Foreground Baseline

R-FOREGROUND-0/1/2/3 computed:

```python
df.groupby(key)["event_id"].transform("count")
```

over the complete evaluation frame before assigning foreground states. Thus an
early row could use occurrences that arrived later in the same frame.

Consequences:

- the reported approximately `51.05%` background suppression and `2.04x`
  compression remain useful **offline policy baselines**;
- they are not strict streaming or deployment claims;
- `online_path_pressure_v1` is no longer the frozen production-facing
  frontend;
- future novelty, recurrence, and maturity features must be computed from
  state available strictly before the current observation.

This correction does not invalidate the controlled attack and poisoning
failure findings. Those findings still identify useful safety boundaries,
especially the path-history poisoning failure.

## 4. Mature Mechanisms to Reuse

### 4.1 Protocol and Parser Contract

The frontend starts from the peer-aware canonical asset. A parser replacement
is not the current problem.

The canonical state key is:

```text
(collector, peer_address, prefix, path_id_if_available)
```

`peer_asn` remains context but cannot replace `peer_address`, because multiple
peer sessions can share an ASN. Add-Path capability and path identifiers must
be audited before assuming one route per peer-prefix.

BGPKIT Parser remains a reference implementation for a streaming BGP element
contract, including peer IP/ASN, announcements/withdrawals, AS path, and
communities:

- https://github.com/bgpkit/bgpkit-parser

### 4.2 Route-State Change Extraction

The frontend borrows BEAM's useful systems idea: compare a new route with the
previous route state and reason about the change, rather than scoring every
announcement independently.

It does not copy BEAM's complete detector or demonstration monitor. The local
contract must also preserve withdrawals, IPv6, peer identity, communities, and
provenance.

- https://www.usenix.org/conference/usenixsecurity24/presentation/chen-yihao
- https://github.com/FIND-Lab/routing-anomaly-detection

The transition vocabulary should begin with the protocol-grounded categories
from RFC 4098:

- initial announcement;
- identical reannouncement / refresh-like duplicate (`AADup`);
- changed announcement (`AADiff`);
- withdrawal followed by same route (`WADup`);
- withdrawal followed by changed route (`WADiff`);
- withdrawal without observed replacement;
- origin, path, next-hop, or community attribute change;
- more-specific appearance and retraction;
- short-lived flap or burst.

An identical route at a later timestamp is not deleted as an exact source
duplicate. It is a meaningful reannouncement and may indicate refresh or
churn.

- https://datatracker.ietf.org/doc/rfc4098/

### 4.3 New-Edge and Historical Maturity Features

DFOH's reusable mechanism is the distinction between newly observed AS edges
and recurrent edges. Its complete forged-origin detector is not the frontend.

- https://github.com/bgproutes-io/forged_origin_hijacks_detection

The causal history sidecar should expose:

- edge/path/prefix-origin first-seen time;
- age before the current observation;
- observation span;
- recurrence across distinct time buckets and days;
- peer and collector diversity;
- recent-only versus mature recurrence;
- short-lived prelude and withdrawal/reannouncement churn.

Raw within-window count is not historical maturity. A path introduced shortly
before an attack must not become suppressible merely because it repeated.

### 4.4 Reusable R-FOREGROUND Contracts

The following local work remains active:

- candidate-free mainline;
- three-way output instead of forced keep/drop;
- controlled truth attached only for evaluation, never as an online feature;
- separate online serving flow and offline training/evaluation pool;
- explicit protection and suppression reason codes;
- zero suppressed controlled attacks as a hard stop-loss gate;
- family-specific and poisoning/evasion retention audits;
- missing or stale evidence cannot authorize suppression;
- all compression must retain reversible provenance.

## 5. Exact Deduplication and Micro-Events

### 5.1 Exact Observation Deduplication

Exact deduplication is narrow and reversible. Its identity includes at least:

```text
timestamp
collector
peer_address
peer_asn
update_type
prefix
AS path
communities
next hop
path identifier when present
```

Only duplicate copies of the same observation, such as archive overlap copies,
may be excluded. The retained row must carry all source references or a
reversible sidecar.

### 5.2 Bounded Micro-Event Aggregation

Repeated transition records may be grouped only after route-state extraction.
The initial contract uses a short causal window, with `5 minutes` as the
primary development value and `15 minutes` as a sensitivity value.

The event key must preserve:

- prefix;
- transition family;
- old and new route signatures;
- first and last timestamps;
- member observation count and identifiers;
- peer set and collector set;
- attribute-change flags;
- exact evidence lookup keys.

Aggregation may reduce repetitive observations. It must not erase
peer/collector asymmetry or merge distinct route changes merely because they
share a prefix.

## 6. Evidence Boundary

Evidence joins occur after exact deduplication or transition extraction, where
possible, and before the three-way decision.

Evidence is a guard and context, not truth:

- RPKI invalid is not attack; RPKI valid is not benign;
- AS-rel diagnostic is not route-leak truth; matched paths are not benign;
- NO_EXPORT presence is not attack; absence is not safe;
- low visibility is not proof of NO_EXPORT;
- unavailable, stale, or conflicting evidence cannot authorize suppression.

Communities are also route attributes. A community transition, including a
well-known-community transition, belongs in the route-change record before
external interpretation.

## 7. Initial Suppression Contract

The frontend may suppress only observations or micro-events supported as
operationally repetitive by past-only state.

Initial suppressible candidates:

- reversible exact source duplicates;
- identical peer-prefix reannouncements with no material attribute change;
- mature recurrent paths/edges observed across separated past buckets or days;
- stable refresh-like bursts with no novel origin, edge, path, visibility, or
  community transition.

Mandatory foreground or gray-zone guards:

- new or recently introduced prefix-origin, path, or AS edge;
- origin/path/community/visibility state change;
- withdrawal/reannouncement or short-lived prelude churn;
- more-specific appearance;
- any controlled attack or poisoning/evasion retention contract;
- evidence unavailable, stale, conflicting, or only weakly joinable.

No item is suppressed because RPKI is valid, AS-rel is matched, NO_EXPORT is
absent, visibility is high, or a legacy label is low.

## 8. Validation Contract

The first bounded implementation must report separate reductions:

1. raw canonical observations to exact unique observations;
2. unique observations to route transitions/micro-events;
3. micro-events to the three foreground states.

Required gates:

- causal leakage violations: `0`;
- input/output/provenance accounting: `100%`;
- unexplained row loss: `0`;
- deterministic replay: exact match;
- suppressed controlled attacks: `0`;
- controlled attack retention: `1.0`;
- observable poisoning/evasion retention: `1.0`;
- public-invisible cases reported as observability boundaries, not misses;
- per-family retention reported separately;
- throughput, peak memory, state size, and event latency reported;
- gray-zone rate and provenance loss reported.

The project target of `50%-70%` operational-background suppression remains an
engineering objective, not a literature guarantee. It may not override the
retention gates.

## 9. Component Decisions

| Component | Decision | Boundary |
|---|---|---|
| `canonical_observation_v2` | reuse | frozen peer-aware input contract |
| BGPKIT Parser | reference/reuse when new parsing is needed | no parser rewrite now |
| RFC 4098 transition taxonomy | reuse | protocol-grounded transition labels |
| BEAM route-change monitor idea | adapt | no BEAM detector score as suppression truth |
| DFOH new-edge/recurrence idea | adapt | no forged-origin-only frontend |
| R-FOREGROUND reason/audit contracts | reuse | full-frame counts are retired |
| `online_path_pressure_v1` | offline baseline only | not a strict online result |
| BGPalerter | optional shell/baseline | not the compression mechanism |
| old seven-layer pipeline | reject from new mainline | no dependency |

## 10. Next Step

Proceed to `N-FRONTEND-1`:

1. define the causal route-state and transition schema;
2. audit Add-Path/path-identifier availability;
3. implement an in-order, past-only bounded replay;
4. validate exact deduplication and transition accounting on a small slice from
   both collectors;
5. compare the causal result with the old offline foreground baseline without
   claiming attack recall;
6. only after the contract passes, replay controlled multi-attack and paired
   poisoning/evasion scenarios.

Do not run the full nine-day asset, train the learning layer, or tune
suppression thresholds before this bounded causal contract passes.
