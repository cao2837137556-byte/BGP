# N-FRONTEND-2B BOUNDED REPLAY IMPLEMENTATION

Status: implementation ready for independent review; no formal real-data replay
has been executed.

## 1. Goal

N-FRONTEND-2B implements the frozen N-FRONTEND-2A contract on top of the
canonical observation and causal-transition frontend. It materializes bounded
clean/adversarial pairs and checks whether their declared semantic phases
survive canonicalization, exact deduplication, causal transition construction,
and micro-event grouping.

The only authorized result wording is:

```text
semantic survival and past-only exposure under paired variants
```

This phase does not validate poisoning robustness, detection accuracy,
background suppression safety, or learning performance.

## 2. Implemented Pair Set

The bounded registry contains five feasible pairs:

1. exact-origin history poisoning;
2. forged-origin history poisoning;
3. path-manipulation history poisoning;
4. subprefix plus NO_EXPORT visibility evasion;
5. collector-asymmetry stealth visibility.

Route-leak policy poisoning remains blocked and diagnostic-only because an
AS-relationship path shape is not route-leak truth.

## 3. Materialization Boundaries

- Real canonical observations provide prefix, path, collector, peer, community,
  and cadence templates.
- Every synthetic observation reuses `canonical_observation_id()`.
- Synthetic source provenance uses `synthetic://n_frontend2/...`.
- Truth and phase membership are stored in a separate sidecar.
- Mixed artifacts are evaluation-only and cannot become negative training
  background.
- The background-only observer registry and observer-level cadence audit are
  hashed and frozen before any variant replay.
- The registry hash is verified before every clean/adversarial variant.
- Public-invisible members are observability boundaries, not frontend misses.

The bounded 60-minute episode represents short-term crafted-history behavior.
It does not support long-term maturity-poisoning claims.

## 4. Causal Metrics

The implementation produces three principal audit views:

1. `semantic_phase_survival`: stable, preparation, attack, and recovery members
   remain traceable through the structural frontend.
2. `past_only_route_exposure_delta`: only transitions satisfying
   `transition_ts < attack_ts` may contribute to attack-time history.
3. `attack_transition_semantic_delta`: observed transition families are
   compared with observer-local preregistered expectations.

Transition-family differences are explanatory evidence, not a binary
poisoning-robustness claim.

## 5. Local Regression Result

The deterministic local fixture exercised all five pairs and ten variants.
The runner and independent validator passed:

- registry frozen before replay;
- phase survival;
- past-only causality;
- observer-local transition-family expectations;
- identity and accidental-duplicate gates;
- visibility contracts;
- ambiguity accounting;
- clean/adversarial pair fairness.

A negative regression deliberately changed the frozen registry. Freeze
verification rejected the change, and validation passed again after restoring
the original bytes.

These are implementation regressions only. They are not paper results and do
not qualify the real nine-day asset.

## 6. HPC Execution Guard

The formal job is a 60-minute bounded real-data replay over Route Views SG and
RRC00. AMD and Intel jobs:

- use the same code and source asset;
- write partition/job-isolated outputs;
- run the same compute-node-compatible preflight path;
- use the repository portable timing wrapper;
- run an independent artifact validator;
- request four CPUs, 64 GB memory, and four hours.

The allocation is a conservative first real-data bound, not a scalability
claim. `sacct` evidence from the first successful run must determine later
resource adjustment.

## 7. Review Gate

Before formal submission, Kimi must review:

- real-template selection and realism;
- observer-local registry and cadence freeze;
- identity/provenance separation;
- past-only implementation;
- expected transition-family matching;
- visibility/NO_EXPORT semantics;
- pair fairness and stop-loss behavior;
- HPC startup and output isolation.

Formal replay is unlocked only after that review. No suppression policy,
learning layer, evidence-verdict logic, or old seven-layer artifact is modified
in this implementation.
