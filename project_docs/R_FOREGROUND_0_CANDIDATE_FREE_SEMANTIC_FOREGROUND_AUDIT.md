# R-FOREGROUND-0 Candidate-Free Semantic Foreground Audit

Date: 2026-06-29

Status: implementation ready; full run pending.

## 1. Purpose

R-FOREGROUND-0 replaces the confusing candidate-as-compression framing with a
single candidate-free foreground extraction audit.

The question is:

```text
Can event rows plus clean evidence ledger support a useful foreground
compression layer without suppressing controlled attack events?
```

This is an audit stage. It does not produce a production suppression policy, it
does not train learning, and it does not claim attack / benign truth.

## 2. Why Candidate Is Removed From The Main Compression Path

The qualified full-window replay produced:

```text
event rows     = 3,431,117
candidate rows = 3,431,117
```

R-NOISE-CLEAN-1 then showed:

```text
suppressed_attack_count = 0
attack_retention = 1.0
pure_reference_background_suppression_rate = 0.001263748
estimated_compression_ratio = 1.001265
overall_pass = false
```

The result is scientifically useful but operationally weak. The policy was safe
for the controlled origin-family smoke, but almost all background remained in
foreground. The main cause is that `candidate_flag` and broad candidate reasons
acted like blanket protection.

Therefore candidate artifacts are downgraded to historical diagnostics and
ablation references. The mainline compression path is:

```text
raw updates
-> event construction
-> clean evidence ledger
-> semantic foreground extraction
-> learning / deep evidence explanation / incident aggregation
```

## 3. Frontline Literature Signals We Borrow

R-FOREGROUND-0 borrows design principles, not complete detectors:

- DFOH shows that forged-origin detection can be centered on AS-path semantic
  changes such as new or suspicious AS links, rather than all route updates.
- BEAM shows that routing anomalies are better understood as routing-role churn
  than as isolated string-pattern changes.
- ARTEMIS shows the value of a clean legitimate-state ledger, although our
  public-monitor setting lacks operator-private prefix ownership truth.
- NO_EXPORT monitor-evasion work shows low visibility cannot be treated as
  background by itself.
- Public-data poisoning work shows historical recurrence is not automatically
  safe, because monitor histories can be manipulated.

The practical consequence is that the foreground layer must be semantic,
evidence-aware, and novelty-aware, while keeping truth labels out of policy
features.

## 4. Evidence Ledger Inputs

Allowed policy inputs:

- event-native routing and observation fields:
  - prefix;
  - origin AS;
  - AS path;
  - collector count / collector set;
  - timestamp / duration;
  - record count.
- clean RPKI sidecar:
  - `rpki_status`;
  - `rpki_evidence_state`.
- clean 2024-near AS-rel sidecar:
  - `path_relation_diagnostic_2024`;
  - `path_relation_evidence_state_2024`.
- clean raw-derived community sidecar:
  - `has_no_export`;
  - `has_no_advertise`;
  - `has_nopeer`;
  - `community_evidence_state`;
  - `raw_match_status`.
- event-window semantic features:
  - prefix-origin recurrence;
  - path-signature recurrence;
  - prefix-origin-path recurrence;
  - rare route-object flags;
  - stable recurrent route flags;
  - low visibility;
  - short duration.

Forbidden policy inputs:

- `candidate_flag`;
- `candidate_reasons`;
- `matched_rule_count`;
- final / high / needs / low;
- P1 / P2 / P3;
- old 2017-derived `rel_seq`, `rel_unknown_cnt`, `rel_has_unknown`;
- scenario truth fields.

## 5. Candidate-Free Policies

The audit evaluates five policies:

| Policy | Role |
|---|---|
| `external_only_aggressive` | Upper-bound stress test using explicit clean external risk only |
| `novelty_plus_evidence_balanced` | Balanced semantic policy using clean evidence plus rare route objects |
| `stable_recurrence_suppression` | Suppress only stable recurring non-risk route objects |
| `aggressive_recurrence` | More aggressive non-risk recurrence compression |
| `visibility_cautious` | Retain low-visibility risk while still suppressing stable multi-collector recurrence |

These policies are counterfactual candidates. Passing R-FOREGROUND-0 does not
automatically make a policy production-ready.

## 6. Gates

Safety gates:

```text
suppressed_attack_count = 0
attack_retention = 1.0
truth_feature_leakage_count = 0
```

Feasibility gates:

```text
pure_reference_background_suppression_rate >= 0.20
estimated_compression_ratio >= 1.25
gray_zone_rate <= 0.50
```

The feasibility gates intentionally prevent another safe-but-useless policy.

## 7. Outputs

Script:

```text
scripts/audit_r_foreground0_semantic_foreground.py
```

Config:

```text
configs/r_foreground0_semantic_policy_audit_v0.json
```

HPC wrapper:

```text
scripts/hpc/r_foreground0_semantic_foreground_audit.slurm
```

Output directory:

```text
outputs/r_foreground_0/<run_id>/
```

Expected files:

```text
r_foreground0_summary.json
r_foreground0_policy_comparison.csv
r_foreground0_policy_population_audit.csv
r_foreground0_policy_attack_retention_audit.csv
r_foreground0_policy_reason_distribution.csv
r_foreground0_semantic_feature_audit.csv
r_foreground0_assignment_sample.csv
r_foreground0_report.md
```

## 8. Allowed And Forbidden Claims

Allowed:

- candidate-free semantic foreground policies were compared;
- controlled truth was evaluation-only;
- candidate artifacts were excluded from policy features;
- a policy either passed or failed the preregistered safety and feasibility
  gates.

Forbidden:

- suppressed background is benign;
- foreground is attack;
- RPKI invalid is attack truth;
- RPKI valid is benign;
- AS-rel diagnostic is route-leak truth;
- NO_EXPORT present is attack truth;
- NO_EXPORT absent is safe;
- low visibility means NO_EXPORT;
- origin-family smoke proves multi-attack recall;
- poisoning/evasion robustness is proven;
- learning is ready.

## 9. Next Step

If at least one policy passes, promote the best passing policy to
`R-FOREGROUND-1` as a smoke policy.

If no policy passes, stop and repair the evidence / semantic feature layer
before expanding attack families or training learning.
