# N-FRONTEND-3B Integrity Repair

Date: 2026-09-09.

Status: F1-F5 repaired; local automated validation passed. No additional
manual review gate, per the user's instruction. Formal HPC replay not run.

## Changes

| Finding | Implemented repair |
|---|---|
| F1: validator trusted IDs/audit claims | Independently reconstruct source micro-event routing, compare full persisted transitions/events, validate index and member provenance, recompute strict-prior exposure and ledger hashes, and regenerate result fingerprints. The runner now requires this validation before returning success. |
| F2: crossed formal source accepted | Verify actual registry/cadence bytes and freeze fingerprint, pin eight byte-identical AMD/Intel 2B metadata artifacts, enforce the formal pair directory and episode, check transition timestamps, complete variant identities, synthetic membership, and micro-event availability. Preflight applies these checks before either submission. |
| F3: truth omission changed denominator | Reconcile root and variant truth/lineage against the synthetic manifest, require complete expected membership, match synthetic provenance to actual source members, and independently recalculate denominators, exclusions, coverage, counts, and reduction rates. |
| F4: missing flags allowed suppression | Every required change/state flag must be an actual Boolean. Missing, null, numeric, and string values produce a gray contract anomaly; any such transition stops promotion even if its micro-event is foreground. |
| F5: empty/incomplete runtime package passed | Require an exact nonempty unique inventory, verify every SHA256 and Git blob identity, and match the commit and manifest digest against a separately supplied local package receipt. Formal execution cannot select a different configuration outside the packaged contract. |

Routing remains parameter-free `identical_reannouncement` with protected
micro-event precedence. No new suppression family, threshold, training, or
scientific claim is introduced.

Input validation may read evaluation-only truth to reject incomplete source
assets. The online routing function does not receive or use truth membership.
Denominator and safety calculations occur after routing.

## Files and Execution

- `scripts/n_frontend3b_contract.py`: package/source integrity and membership
  contracts; contains no suppression decision.
- `scripts/n_frontend3b_artifact_validation.py`: independent reconstruction
  from source and persisted artifacts; does not import the routing runner.
- `scripts/test_n_frontend3b_integrity.py`: permanent counterexamples and
  positive controls for all five findings.
- Updated runner, validator, bundle builder, config, and preflight/submission
  wrappers apply the contracts consistently.

Fixture runs retain their actual upstream inputs under `_selftest_source`.
The validator never reconstructs a supposed source from its own outputs.
Standalone fixture validation requires `--allow-self-test-source`; formal
validation rejects fixture-mode artifacts by default.

## Validation

```text
python scripts/test_n_frontend3b_integrity.py -v
python scripts/validate_n_frontend3b_background_suppression.py --self-test
python scripts/validate_n_frontend3b_dual_parity.py --self-test
```

The integrity suite contains 11 tests, including 42 required-flag value cases,
actual learning/background/index loss, changed history and ledger hashes,
post-exposure tampering, denominator/rate changes, crossed source metadata,
preparation/recovery omissions, source time/provenance errors, premature
micro-event publication, incomplete packages, and configuration escape.

The end-to-end fixture keeps 30 expected-visible members and 2 boundary
members with zero suppressed attacks, zero gray anomalies, and unchanged
scientific output fingerprint:

```text
9758f9d65c46594303ae50ac5db8b1f32c2ba6e465c8bf3c7a0554069ad96ab1
```

The fixture's `0.125` reduction remains a test result only. It does not measure
formal background compression or establish poisoning robustness.

## Package Receipt and Next Experiment

The deterministic builder writes three companion artifacts:

```text
n_frontend3b_repo_<commit>.tar.gz
n_frontend3b_repo_<commit>.tar.gz.sha256
n_frontend3b_repo_<commit>.tar.gz.receipt.json
```

The receipt is produced locally from committed bytes and records
`source_commit`, `bundle_sha256`, and `package_manifest_sha256`. Before the
authorized formal submission, set these two values from that local receipt:

```bash
export N_FRONTEND3B_PACKAGE_COMMIT=<source_commit>
export N_FRONTEND3B_MANIFEST_SHA256=<package_manifest_sha256>
```

Do not derive the expected digest from the unverified remote manifest.
Both preflight and the formal compute job verify the same receipt. The
previous `63a9792` package is historical and cannot satisfy the new inventory.

The next experiment is still the frozen `2024-04-11 12:00-13:00 UTC` replay
using completed 2B AMD `157343` and Intel `157344` sources. Local tests do not
qualify the remote image, full real Parquets, memory demand, or scheduler;
the actual preflight checks those inputs before submission. This repair did
not submit or cancel an HPC job, overwrite historical outputs, or modify
unrelated dirty files.
