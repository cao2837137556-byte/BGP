# N-FRONTEND-3B Code and Package Review

Date: 2026-09-09.

Historical verdict for `63a9792`: **FAIL**.

Resolution, 2026-09-09: F1-F5 are repaired and covered by permanent automated
regressions. See `N_FRONTEND_3B_INTEGRITY_REPAIR.md`. The user explicitly waived
an additional manual review cycle; passing implementation checks close the
repair. Formal HPC execution still requires its own user authorization.

Reviewed commit: `63a97925b9a2053e22d719d78a28ac273d42de13`.

Reviewed bundle: `n_frontend3b_repo_63a9792.tar.gz`.

SHA256: `3aa2cf10523da1cf16b8b91423d83616ffaea5fdbdc186179aa0795e633705dc`.

This is a Codex code review with separately written counterexamples and
artifact checks. It is not external independent review. The user has retired
the Kimi dependency and assigned implementation and review responsibility to
Codex. Historical Kimi reviews remain historical facts.

No production code, frozen contract, original input, or historical experiment
output was changed during this review. No formal HPC job was submitted.
All counterexamples use new local review directories.

## 1. Conclusion

The original local tests pass, the package can be rebuilt byte-for-byte, and
the worktree/package fixture outputs agree. These facts do not establish the
documented independent validation guarantees: deliberately incomplete or
inconsistent artifacts can still pass both the runner's gates and validator.

The five original findings below concerned enforcement of the
existing frozen contract, not a proposed change to suppression policy.
There is no evidence here that the archived formal 2B data was corrupted, or
that a real attack has already been lost by a formal 3B run. Such a run has
not occurred.

## 2. Findings

### F1 — P1: Validate actual learning and background artifacts independently

Locations:

- `scripts/validate_n_frontend3b_background_suppression.py:286-313`
- `scripts/run_n_frontend3b_background_suppression.py:738-759`

The validator compares restoration IDs rather than complete member content.
It checks the `exact_equal` column produced by the runner instead of
recomputing post-routing exposure. The foreground micro-event files,
background index, and background-member manifest are required to exist but
their contents are not independently checked against source membership.
Checking micro-event precedence in a separate routing table does not prove
that the actual learning-input Parquet contains those events.

Counterexamples, each starting from a fresh passing fixture copy:

| Mutation | Observed validation |
|---|---|
| Empty one variant's foreground micro-event file, removing 11 learning-input events | passed |
| Move a persisted background transition timestamp back by 1,800 seconds without changing its ID | passed |
| Empty a nonempty reversible-background index | passed |
| Increase a post-routing exposure count by 999 while leaving the equality table unchanged | passed |
| Replace every prior-ledger fingerprint in a variant with one arbitrary string | passed |

Required repair: reconstruct the complete foreground/background/gray
partition from source transitions and source micro-events; compare full
canonical row content, membership, provenance, availability time, and index
coverage; independently recompute history and the causal fingerprint from
the persisted members. Recompute reported fingerprints instead of trusting
their stored values. Negative tests must exercise each actual consumer file.

### F2 — P1: Bind the formal replay to the actual frozen input

Locations:

- `scripts/run_n_frontend3b_background_suppression.py:834-850`
- `scripts/hpc/n_frontend3b_bounded_replay_preflight.sh:15-35`

The runner compares the fingerprint string in the source summary to the
configured constant, but does not recompute the registry freeze or validate
the observer registry and cadence files it binds. `registry_freeze` is loaded
and then unused. The configured formal episode and pair ID are not enforced
against the actual source data. Recording fresh hashes of whatever inputs
are supplied does not verify that they belong to the frozen experiment.

Counterexample: generate a separate 2B self-test source, retain its test
registry and transitions, and copy only the real archived formal 2B summary
into that review directory. Invoke the **packaged formal entry** with the
original configuration, original valid package manifest, and
`self_test=False`. Both runner and validator pass. The actual fixture registry
fingerprint starts `3a0302b0`, while the accepted summary claims the frozen
formal fingerprint `1c142735`. The fixture timestamps also lie outside the
frozen April episode.

Required repair: verify the registry/cadence bytes and recompute the freeze
fingerprint; bind the episode, observer registry, pair/variant identities,
lineage and input manifest to the actual frozen source. Reject crossed
directories before writing scientific output or submitting formal jobs.
Reuse the existing 2B `verify_registry_freeze` semantics where appropriate;
its implementation already verifies the underlying files.

### F3 — P1: Reconcile truth membership before computing safety and denominators

Locations:

- `scripts/run_n_frontend3b_background_suppression.py:892-952`
- `scripts/run_n_frontend3b_background_suppression.py:1097-1099`
- `scripts/run_n_frontend3b_background_suppression.py:1215-1218`
- `scripts/validate_n_frontend3b_background_suppression.py:357-359`

The suppression denominator excludes IDs from the root lineage CSV, whereas
phase survival uses per-variant lineage files. These populations are not
reconciled with each other, the truth sidecar, synthetic provenance, or the
frozen expected membership. A Boolean written as
`truth_used_only_after_routing=True` is then treated as the denominator-purity
gate. This tests an assertion, not the denominator population.

Counterexamples:

- Remove one poisoning-preparation member only from the root lineage table.
  Keep the variant lineage and transitions intact. The formal runner and
  validator pass, but the operational-background transition denominator
  increases from **80 to 81**: the injected preparation member is miscounted
  as background.
- Remove one recovery member from both lineage levels while leaving the
  actual routing data unchanged. Expected-visible coverage shrinks from
  **30 to 29**, yet all runner gates and validator pass. The code does not
  enforce the complete frozen expected-member set.
- Change a denominator count by 1,000 and the summary reduction from `0.125`
  to `0.99` without changing the routing data. The validator accepts both.

Required repair: establish an immutable expected-member set independently of
the output tables; reconcile root/variant truth and synthetic provenance;
assert exact phase/member coverage, not only traceability of surviving rows;
then independently derive exclusion IDs, all denominator counts, and reported
rates. Truth remains evaluation-only and must never change online routing.

### F4 — P1: Missing change flags must not authorize suppression

Locations:

- `scripts/run_n_frontend3b_background_suppression.py:285-307`
- `scripts/validate_n_frontend3b_background_suppression.py:194-204`

Presence checks cover the two state flags and ambiguity flag, but not
`origin_changed`, `path_changed`, `communities_changed`, or `next_hop_changed`.
The subsequent Boolean helper converts missing/null flags to false. Thus a
nominal identical reannouncement with incomplete change information can be
classified as suppressible. The independent assignment function repeats the
same omission.

Counterexample: for each of the four flags, either remove the key or set it
to null on an otherwise eligible transition. All **8 cases** are classified
as `suppressible_semantic_redundancy` by both implementations.

Required repair: validate presence and Boolean type of all required flags
before evaluating suppression. Incomplete contract state must trigger gray
or an explicit input rejection, with promotion blocked. Add absent, null,
and malformed-value tests against the frozen schema.

### F5 — P2: Runtime package verification accepts an empty file manifest

Location: `scripts/run_n_frontend3b_background_suppression.py:219-247`.

The manifest validator checks whichever entries are listed, but does not
require the complete reviewed file set or validate the source/blob binding.
With `entries=[]` and the existing success flags retained,
`runtime_verification_passed` becomes true without checking any runtime file.

The reviewed package itself is complete and byte-correct; this finding is
about the runtime gate's failure to reject a truncated or replaced manifest.

Required repair: require an exact, nonempty, unique file inventory, validate
each byte/blob binding and the reviewed commit, and bind the manifest digest
to the approved package receipt. Run the same validation during preflight
and on the compute node. Test missing entries and changed code/config bytes.

## 3. Checks That Passed

- Python 3.10.0, pandas 2.3.1, NumPy 2.2.6, PyArrow 23.0.1.
- Original runner end-to-end self-test: passed.
- Original validator self-test, including its assignment and frozen-exposure
  negative tests: passed.
- Original dual-parity validator self-test: passed.
- Rebuilt committed bundle: exactly the original SHA256.
- Original bundle manifest: all 16 file entries verified against bytes.
- Extracted package end-to-end fixture: passed using only packaged project
  dependencies.
- Worktree versus packaged fixture: all 15 declared parity artifacts/field
  groups matched.
- All four packaged shell wrappers passed Git Bash `bash -n`.
- A fixture with zero operational-background reduction was accepted; no
  minimum positive compression claim is made from it.
- Removing a preparation member from local lineage correctly failed the
  frozen-exposure comparison. This is a useful existing gate, but it does
  not replace complete member-set validation: the recovery-member omission
  above was accepted.

Normal-path review confirms that the v1 rule uses route-transition fields,
that protected-member precedence exists, and that truth membership is applied
to evaluation accounting rather than the routing function. The ledger audit
is still insufficiently independent, as F1 shows; no current future-data
leakage in the pure eligibility function was established by this review.

HPC module availability, the actual Apptainer image, Slurm scheduling,
compute-node resource usage, and the complete real 2B Parquets were not
executed or inspected remotely in this local review. Shell syntax and local
package execution do not qualify those environment properties.

## 4. Reproduction Evidence

All paths below are relative to the repository:

```text
outputs/n_frontend3b_review_20260909/
  review_probes.py
  review_probe_results.json
  formal_input_probes.py
  formal_input_probe_results.json
  additional_probes.py
  additional_probe_results.json
  worktree_package_parity.json
  baseline_fixture/
  packaged_repo/
  crossed_formal_metadata_result/
  root_truth_omission_result/
  missing_recovery_member_result/
```

These are review-only fixtures and counterexamples, not scientific results.
The scripts intentionally use fresh output directories; reproduce them in a
new review root rather than overwriting the archived evidence. Existing
tracked source and archived experiment assets remain unchanged.

The original self-test commands were:

```text
python scripts/run_n_frontend3b_background_suppression.py --self-test --output-dir outputs/n_frontend3b_review_20260909/baseline_fixture
python scripts/validate_n_frontend3b_background_suppression.py --self-test
python scripts/validate_n_frontend3b_dual_parity.py --self-test
python scripts/hpc/build_n_frontend3b_reviewed_bundle.py --repo-root . --expected-commit 63a97925b9a2053e22d719d78a28ac273d42de13 --output outputs/n_frontend3b_review_20260909/rebuilt_bundle.tar.gz
```

## 5. Original Repair Requirements (Now Implemented)

The repair implements F1-F5 under the existing frozen suppression semantics,
adds permanent counterexample regressions, and produces a committed package
with an external byte receipt. The user has removed the additional manual
review gate. The next experiment remains the same-episode AMD/Intel replay
after user authorization for formal execution.

Do not tune thresholds, add suppression families, train learning, revise the
scientific contract silently, or treat this review as a formal 3B result.
