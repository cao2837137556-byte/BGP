# N-FRONTEND-FIT-0A: BGPalerter Runtime Contract Smoke

## Goal

This phase asks one bounded question:

> Can BGPalerter provide a deterministic, provenance-preserving runtime shell
> for a future foreground extractor without modifying its core?

It does not select the final frontend and does not evaluate foreground policy
quality.

## Component Under Test

- component: BGPalerter;
- repository: `https://github.com/nttgin/BGPalerter.git`;
- version: `2.0.1`;
- pinned commit: `9a616c29483ae03eaae219b04773a4288b32db62`;
- license: BSD-3-Clause;
- pre-smoke classification: `adapt_candidate`.

The official research interface supports custom monitors while keeping most of
the pipeline unchanged. Its synchronous `filter` is not allowed to perform
database or API calls. Therefore future versioned evidence must be attached
before dispatch or served from bounded local state; it must not be fetched per
message.

## Reused Boundary

The smoke reuses these native BGPalerter boundaries:

- `Consumer.dispatch`;
- `Monitor.filter`;
- `Monitor.monitor`;
- `Monitor.publishAlert`;
- `PubSub.publish`.

The project adds only:

- an external canonical-observation connector;
- a contract-only passthrough monitor;
- a row-level decision ledger required for exact accounting.

The BGPalerter source tree must remain clean before and after the run.

## Schema Contract

Every `canonical_observation_v2` field must survive two independent replay
passes exactly:

- timestamp, collector, project, type;
- peer ASN and peer address;
- prefix, AS path, origin and origin provenance;
- communities and next hop;
- observation ID;
- source file and archive timestamp.

The order of `observation_id` values must also remain exact.

## Scientific Boundaries

The local default input is a deterministic schema-contract fixture. It is not:

- operational BGP evidence;
- confirmed background;
- benign or attack truth;
- an attack-retention benchmark;
- a scalability benchmark.

The monitor emits only `contract_passthrough`. It does not implement
`foreground`, `gray`, or `suppress` policy.

No RPKI, AS-rel, communities interpretation, historical memory, truth label,
legacy candidate, or old seven-layer output participates in a decision.

## Gates

The contract passes only if:

1. every input row produces exactly one ledger row;
2. observation IDs and order are preserved;
3. all required fields round-trip with zero mismatches;
4. the second replay is byte-semantically deterministic;
5. BGPalerter core remains unmodified;
6. no network connector or evidence API is used;
7. no runtime errors are logged.

## Interpretation

A pass means only:

> BGPalerter remains an adaptation candidate whose runtime boundaries can carry
> the canonical schema without core modification.

It does not mean BGPalerter has been selected. A real frozen-asset replay and
adapter-cost audit must follow before promotion.

The dependency installation also requires a separate security review. A
successful scientific contract does not erase dependency vulnerabilities or
establish production readiness.

## Result

The deterministic local contract smoke passed:

- input rows: `512`;
- output rows: `512` in each of two independent replays;
- exact row accounting: passed;
- `observation_id` order preservation: passed;
- required-field round trip: all `15/15` canonical fields passed;
- deterministic replay: passed;
- logged runtime errors: `0`;
- network connector use: none;
- BGPalerter core modification: none.

The measured adapter contains `207` nonblank, non-comment source lines. The
final local rerun reported about `44.1k` and `45.4k` rows per second with
roughly `92 MB` resident memory. These values are engineering smoke
observations only. The fixture is too small and too synthetic for a
scalability claim.

The post-smoke classification is:

```text
adapt_candidate_contract_passed
```

BGPalerter is not selected as the final frontend.

## Dependency Risk

The pinned installation reported `37` vulnerabilities across development and
runtime dependencies. The runtime-only audit reported:

- low: `2`;
- moderate: `19`;
- high: `7`;
- critical: `0`;
- total: `28`.

This does not invalidate the runtime-contract result, but it blocks any
production-readiness or security-hardening claim. A future promotion decision
must include dependency remediation feasibility or a narrower reuse boundary.

## Next Step

If the local contract passes, run:

`N-FRONTEND-FIT-0B real frozen-asset replay and adapter-cost audit`.

That step should use a bounded slice of the frozen nine-day
`unlabeled_operational_background` asset, preserve the reversible duplicate
exclusions, and measure throughput, memory, provenance loss, and adapter
complexity. It must still avoid learning, attack claims, and foreground policy
promotion.
