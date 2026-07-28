# N-FRONTEND-1: Causal Transition Contract

Status: local contract and N-FRONTEND-1B bounded real replay passed. The first
formal submission (`154378/154379`) failed before computation because compute
nodes lacked the unqualified `/usr/bin/time` dependency. The repaired package
uses a preflight-tested repository-owned timing wrapper; paired AMD/Intel jobs
`154385/154386` then completed with aligned validators, counts, and semantic
output fingerprints.

Date: 2026-07-25.

## 1. Goal

N-FRONTEND-1 implements the first non-destructive part of the new frontend:

```text
canonical_observation_v2
  -> reversible exact-observation deduplication
  -> peer-aware, past-only route-state transitions
  -> bounded micro-events
```

This phase does not suppress operational background, attach attack/benign
truth, train learning, or use the old seven-layer pipeline.

## 2. Reused Mechanisms and Local Adaptation

The implementation reuses narrow mechanisms rather than importing a complete
detector:

- RFC 4098 motivates distinguishing identical and changed announcements and
  withdrawal/announcement sequences;
- BEAM motivates comparing the previous route with the new route instead of
  treating every announcement as an independent row;
- DFOH motivates preserving path/link history for later maturity analysis;
- the local R-FOREGROUND work contributes reversible provenance, three-way
  decisions, explicit reasons, and attack-retention stop-loss gates.

References:

- https://datatracker.ietf.org/doc/rfc4098/
- https://www.usenix.org/conference/usenixsecurity24/presentation/chen-yihao
- https://www.usenix.org/conference/nsdi24/presentation/holterbach

None of these sources provides a drop-in background compressor. The causal,
poisoning-aware suppression decision remains project-specific and is not
implemented in this phase.

## 3. Exact Deduplication Contract

Automatic deduplication requires the canonical `observation_id`.

- same ID and same semantic payload: retain one row and preserve all source
  files and input Parquets;
- same ID and different semantic payload: fail as an identity collision;
- missing ID: retain the row; do not infer a duplicate;
- identical route at a later timestamp: retain as a reannouncement.

This makes the first reduction narrow and reversible. It is not background
classification.

## 4. Route-State Identity

The state key is:

```text
(collector, peer_address, prefix, path_id_if_available)
```

`peer_asn` cannot replace `peer_address`, because multiple peer sessions may
share an ASN. An announcement or withdrawal missing peer or prefix identity is
isolated rather than merged, and the contract is marked failed. Non-route
control records (for example peer-state records) are retained in a separate
audit artifact and do not enter the per-prefix route-state machine.

The current canonical v2 files do not expose a qualified Add-Path identifier.
Therefore this phase explicitly forbids an Add-Path-complete claim. A
field-presence check alone is insufficient; parser and peer-capability
metadata are still required.

## 5. Transition Semantics

The transition state uses only observations strictly before the current
timestamp. Supported families include:

- `bootstrap_announce` and `bootstrap_withdrawal`;
- `identical_reannouncement`;
- `announcement_change`;
- `withdrawal` and `repeated_withdrawal`;
- `withdraw_reannounce_same` and `withdraw_reannounce_changed`;
- `same_timestamp_ambiguous`;
- state-recovery and unsupported-type states.

The first update in a bounded window is called `bootstrap`, not novel or
initial on the Internet, because the pre-window RIB is unavailable.

Distinct updates for the same peer-prefix and timestamp are not given a
fabricated order. They become one `same_timestamp_ambiguous` transition, the
state becomes unknown, and the next observable update performs state recovery.

Origin, AS path, communities, and next hop are part of the route signature.
Their change flags are emitted only when both old and new route states are
known and comparable.

## 6. Communities Boundary

Well-known communities, including NO_EXPORT, remain route attributes.

- a NO_EXPORT transition is preserved as an attribute change;
- NO_EXPORT presence is not attack truth;
- NO_EXPORT absence is not safe;
- this phase performs no stealth or attack judgment.

## 7. Bounded Micro-Events

Transitions are grouped after state extraction using fixed causal windows:

- primary: 5 minutes;
- sensitivity: 15 minutes.

The key retains prefix, transition family, old/new route signatures, and
attribute-change flags. Each micro-event preserves member transition IDs,
observation count, peer set, collector set, source files, first/last seen
times, and `available_at_ts=window_end`.

This is bounded event construction, not the final suspicious incident
aggregation.

## 8. Validation Results

### Synthetic Contract

- input rows: `10`;
- exact unique observations: `9`;
- excluded duplicate source copies: `1`;
- transitions: `8`;
- same-timestamp ambiguous batches: `1`;
- 5-minute micro-events: `8`;
- causal violations: `0`;
- accounting: passed;
- deterministic replay: passed.

The fixture covers a source-overlap duplicate, identical reannouncement,
changed announcement, withdrawal/reannouncement, same-timestamp ambiguity,
state recovery, and a NO_EXPORT community transition.

### Existing Canonical Duplicate Pair

The existing two-file canonical overlap fixture produced:

- input rows: `2`;
- exact unique observations: `1`;
- excluded duplicate source copies: `1`;
- transitions: `1` (`bootstrap_announce`);
- 5-minute micro-events: `1`;
- provenance/accounting: passed.

This validates the reversible duplicate contract on an existing
`canonical_observation_v2` artifact. It is not a frozen nine-day performance
or compression result.

### N-FRONTEND-1B Bounded Real Replay

The deterministic window was `2024-04-09 00:00-00:05 UTC`, with one source
Parquet from each frozen collector. AMD job `154385` and Intel job `154386`
both completed with validation passed and no failed checks.

- input observations: `583,663`;
- exact unique observations: `556,049`;
- excluded exact duplicate copies: `27,614`;
- exact-dedup reduction: `4.731%`;
- causal transitions: `469,561`;
- transition reduction from unique observations: `15.554%`;
- primary five-minute micro-events: `335,386`;
- micro-event reduction from transitions: `28.575%`;
- raw-to-micro-event reduction: `42.538%`;
- raw-to-micro-event compression ratio: `1.740272x`;
- non-route observations isolated: `169`;
- same-timestamp ambiguous batches: `66,666`;
- causality violations: `0`.

The paired runs match on the input manifest, all core counts, transition-family
counts, accounting fields, and the three semantic output fingerprints. The
input manifest, summary, transition-count table, exact-dedup audit, and
non-route Parquet also have identical file SHA256 values across AMD and Intel.

This is a structural preprocessing result. It does not prove safe background
suppression, attack retention, poisoning robustness, or nine-day scalability.

## 9. Current Limits

- the bounded replay covers five minutes, not the full nine-day asset;
- the paired wall-clock measurements are `124` and `145` seconds, but no
  nine-day throughput claim is made;
- no pre-window RIB bootstrap is available;
- Add-Path completeness is unqualified;
- `66,666` same-timestamp ambiguous batches require a cause audit before
  suppression tuning;
- no external evidence is joined;
- no foreground/suppression policy is applied;
- no attack or poisoning retention is claimed.

## 10. Next Step

Run `N-FRONTEND-1C` as a read-only audit over the paired bounded replay:

- verify AMD/Intel semantic alignment from validators, core fields, and output
  fingerprints;
- classify same-timestamp ambiguity by update-type and route-attribute
  differences;
- report collector shares, ambiguity rates, and representative groups;
- retain all ambiguous groups as unknown-order context;
- do not infer attack, benign background, or recoverable order;
- audit Add-Path and timestamp-granularity limitations before any suppression
  tuning.

Only after this audit passes may N-FRONTEND-2 replay controlled multi-attack
and poisoning/evasion scenarios through the structural frontend.
