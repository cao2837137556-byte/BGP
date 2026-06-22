# R-ATTACK-QA-0 Origin Scenario Qualification

Date: 2026-06-22

Status: R-ATTACK-0A is qualified as a development plumbing smoke. Scenario v1
is not qualified for full-window replay, foreground evaluation, learning, or
paper claims.

## 1. Purpose

R-ATTACK-QA-0 checks whether the successful R-ATTACK-0A run is scientifically
safe to promote beyond a plumbing smoke.

The audit separates two questions:

1. Did controlled records move correctly through raw, event, candidate, and
   evidence attachment?
2. Are the scenarios realistic and diverse enough to evaluate a foreground
   extractor or model?

The first answer is yes. The second answer is no.

## 2. Inputs

- scenario configuration:
  `configs/r_attack0a_origin_smoke_v01.yaml`;
- materialization summary and raw truth sidecar;
- raw-to-event outcomes;
- event and candidate derived labels;
- joined RPKI, AS-rel, and community evidence.

Audit script:

```text
scripts/audit_r_attack_qa0.py
```

Outputs:

```text
outputs/r_attack_qa_0/s2a_attack0a_origin_smoke_6h_april16_v01/
```

## 3. Overall Result

| Item | Result |
|---|---|
| QA checks | 19 |
| Passed | 12 |
| Warnings | 2 |
| Blocking/failing | 5 |
| Development smoke qualified | yes |
| Full-window replay ready | no |
| Foreground evaluation ready | no |
| Training ready | no |
| Stop-loss triggered | yes |

The stop-loss applies to promotion of scenario v1. It does not invalidate the
R-ATTACK-0A plumbing result.

## 4. What Passed

The following contracts passed:

- reference background remained immutable;
- truth fields stayed outside production-like raw input;
- all 24 raw truth IDs were unique;
- raw/event admission rate was 1.0;
- total event membership was reconstructable;
- all four attack events had attack-member share 1.0;
- stable, attack, and recovery phases were ordered correctly;
- both public-visible scenarios were observed in both declared collectors at
  scenario level;
- all attack events were candidate-retained for structural reasons;
- exact-prefix and forged-origin produced the expected different RPKI
  responses.

Candidate retention did not depend on `single_collector_visibility`. That field
is contextual only in the legacy candidate implementation. Every attack event
also had an unseen origin or unseen path structural reason.

## 5. Blocking Risks

### 5.1 Documentation ASN shortcut

The attackers are RFC 5398 documentation ASNs 64496 and 64497.

This is appropriate for safe plumbing tests, but not for benchmark evaluation:

- the ASNs create synthetic out-of-distribution values;
- CAIDA AS-rel naturally cannot describe the new synthetic edges;
- a foreground rule or model could learn the reserved-ASN shortcut instead of
  attack semantics.

Required repair:

```text
Use topology-consistent hypothetical attacker roles based on observed ASNs, or
use a simulation-backed topology contract. Never imply that the selected real
ASN performed an attack.
```

### 5.2 Community phase leakage

Attack announcements were assigned an explicit empty community list, while
stable and recovery records copied legitimate communities.

Observed separation:

- attack events: `observed_no_community_tokens`;
- control events: `present_parsed` or `present_unparsed`.

This makes attack/control phase perfectly separable from an artificial field.
It is label leakage for any foreground or learning experiment.

Required repair:

```text
Preserve matched legitimate community distributions for ordinary origin
scenarios. Change communities only when communities/NO_EXPORT are the explicit
experimental variable.
```

### 5.3 Insufficient scenario diversity

There is one template for exact-prefix and one for forged-origin. This is enough
to test code paths, but it cannot expose template-specific shortcuts.

The next qualified smoke needs at least two independent victims/templates per
included subtype, with different legitimate origins, hypothetical attackers,
path shapes, and collector views.

This minimum only qualifies the next smoke. It is not the final benchmark size.

### 5.4 No hard negatives

The current run contains attack scenarios and reference background, but no
controlled attack-like legitimate changes.

Before evaluating a foreground extractor, add provenance-backed lookalikes such
as:

- legitimate origin transition or MOAS-like change;
- traffic-engineering path change;
- path prepending;
- normal community variation.

These are hard-negative scenarios, not automatically confirmed benign truth.

### 5.5 Full-window execution not qualified

The local 7.2M-row event rebuild remained active for nearly one hour without a
complete artifact. More importantly, running the flawed v1 scenarios at full
scale would waste compute without improving scientific validity.

Full replay is postponed until scenario shortcuts are repaired. The repaired
version should pass a bounded local smoke, then run as a packaged HPC job with
complete logs and artifact validation.

## 6. Observability Warning

Both scenarios satisfy the declared public-visible contract at scenario level:
`route-views.sg` and `rrc00` both observed the attack.

However, collector-specific AS paths generate separate event rows, and all four
attack events have `collector_count=1`.

Therefore:

```text
event-level single collector != scenario-level low visibility
```

Future foreground logic must compute visibility at a routing-object/time or
scenario level. It must not infer stealth merely from these event rows.

## 7. Evidence Interpretation

The evidence response remains useful as a mechanism check:

- exact-prefix: RPKI `invalid_asn`;
- forged-origin: RPKI `valid`;
- both: AS-rel partially unknown because of synthetic edges;
- both: no community tokens by construction.

Only controlled injection metadata is truth. None of these evidence states is
an attack or benign label.

## 8. Decision

R-ATTACK-0A remains a successful development smoke:

- parser/event/candidate/evidence plumbing is operational;
- provenance and layer-localized accounting work;
- exact and forged-origin paths produce distinct evidence behavior.

Scenario v1 must not be used for:

- full-window replay;
- clean foreground policy validation;
- attack recall or low-FP claims;
- learning;
- poisoning/evasion claims.

## 9. Next Action

```text
R-ATTACK-0A-2:
Harden the controlled origin scenarios, rerun a bounded smoke, and repeat the
QA gate before full-window replay.
```

Required changes:

1. remove documentation-AS shortcuts;
2. remove community phase leakage;
3. preserve scenario-level visibility semantics;
4. add at least two independent templates per subtype;
5. add a small controlled hard-negative set;
6. only after the repaired smoke passes, package full 6h replay for HPC.
