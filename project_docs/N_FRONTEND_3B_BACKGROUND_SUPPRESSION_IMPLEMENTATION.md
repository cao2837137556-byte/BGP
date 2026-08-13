# N-FRONTEND-3B Background Suppression Implementation

Status: implementation ready for independent review; formal HPC replay not run

## 1. Scope

N-FRONTEND-3B implements the frozen N-FRONTEND-3A v1 contract without adding
parameters or changing its scientific semantics. It routes only complete,
unambiguous N-FRONTEND-1 `identical_reannouncement` transitions away from the
learning-input foreground. Original records remain in immutable background
storage and are addressable through a reversible index.

This is learning-input load reduction, not raw-storage compression and not a
benign/attack classifier.

## 2. Frozen Inputs

- contract commit: `38b262dd80397f16d6db5d16071036538fed67f6`;
- formal N-FRONTEND-2B pair: `n_frontend2b_20260805T023615Z`;
- episode: `2024-04-11 12:00:00-13:00:00 UTC`;
- observer registry fingerprint:
  `1c14273522bd46a44864526f64cad558d6cf1bbdecc61af9b52f345da2a3a4fc`;
- five pairs, ten variants, 30 expected-visible members, and two declared
  observability-boundary members.

The configuration retains the documented LF/CRLF protocol provenance. Formal
packages are built only from reviewed committed blobs with canonical LF bytes
and a runtime-verified package manifest. The bundle builder also rejects an
incomplete repository-local Python import closure, preventing a package from
passing worktree tests while omitting a transitive runtime dependency.

## 3. Implementation

The primary runner:

1. validates source/config/package anchors;
2. processes transitions in stable time order;
3. gives same-timestamp siblings the same strict-prior ledger view;
4. applies the single frozen eligibility rule without truth fields;
5. applies protected-member precedence at micro-event level;
6. writes foreground, immutable background, gray-tripwire, reversible index,
   and member provenance artifacts;
7. reconstructs the full transition set from persisted routes;
8. recomputes past-only exposure through the joint view and requires exact
   equality;
9. loads injected truth only after routing for denominator and safety audits.

Exact N-FRONTEND-1 source deduplication is reported separately and is never
counted as N-FRONTEND-3B learning-input reduction. Public-invisible members are
checked against the frozen observability-boundary contract and are not counted
as frontend misses.

## 4. Independent Validation

`validate_n_frontend3b_background_suppression.py` independently recomputes
transition eligibility, micro-event precedence, restoration, strict
same-timestamp causality, past-only equality, denominator purity, stage
accounting, non-route bypass, boundary handling, and attack preservation. Its
negative regressions independently tamper with one routing assignment and the
frozen N-FRONTEND-2B exposure baseline; both must be rejected.

`validate_n_frontend3b_dual_parity.py` compares preregistered scientific fields
from AMD and Intel runs while excluding machine paths and wall-clock timing.
AMD and Intel are independent executions of one experiment, not two scientific
seeds.

## 5. Local Regression Result

The complete local fixture replay runs N-FRONTEND-2B and then N-FRONTEND-3B for
all five pairs and ten variants. It deliberately adds a provenance-complete
operational identical reannouncement to every variant so the background route
is exercised.

- py_compile: passed;
- primary 3B self-test: passed;
- independent validator self-test and tamper rejection: passed;
- two complete replay runs: passed;
- scientific parity across the repeated runs: passed;
- expected-visible members: `30`;
- observability-boundary members: `2`;
- suppressed attacks: `0`;
- gray contract anomalies: `0`;
- past-only exposure mismatches: `0`;
- unexplained transition loss: `0`.

The fixture's `0.125` learning-input reduction only proves the routing and
metric paths are exercised. It is synthetic test-fixture behavior and must not
be reported as a scientific compression result.

## 6. Formal HPC Gate

Formal submission remains blocked until independent review and explicit user
authorization. The reviewed workflow will:

- run the same compute-node preflight used by the formal wrapper;
- execute self-tests inside the actual Apptainer image;
- reject missing full N-FRONTEND-2B artifacts before submission;
- dual-submit isolated AMD and Intel jobs with reasonable provisional
  resources (`2 CPU`, `16 GiB`, `2 h`);
- retain both outputs independently if both finish;
- require semantic parity after completion;
- use `sacct` evidence to revise future resource requests.

No HPC job has been submitted by this implementation phase.

## 7. Claim Boundary

If the formal replay passes, the strongest allowed statement remains:

```text
bounded learning-input redundancy reduction with exact past-only history
preservation; the frozen paired variants remain semantically observable under
the parameter-free identical-reannouncement routing rule
```

This phase does not prove benign suppression, attack detection accuracy,
poisoning robustness, storage compression, nine-day throughput, production
readiness, or learning performance.
