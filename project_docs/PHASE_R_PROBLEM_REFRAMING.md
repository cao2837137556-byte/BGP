# Phase R Problem Reframing

Last updated: 2026-05-17

## 1. Why Phase R

Phase R pauses the previous linear experiment expansion and reframes the project before new experiments are launched.

Reasons:
- The current system is still a useful research platform, but its detector capability is not yet strong enough to carry the paper by detector accuracy alone.
- We should not force a paper problem around the existing framework just because the framework runs.
- The 2023-2026 research scan shows that public-monitor-centered anomaly detection is already crowded by DFOH, BEAM, BGPShield, BGPalerter/ARTEMIS-style operational monitors, and related systems.
- Recent work on public BGP data poisoning argues that detectors relying on public monitors and historical public patterns can be evaded by crafted announcements.
- The stronger research opening is not "another detector on public monitors"; it is robust incident verification and triage under adversarial monitor manipulation, incomplete public observability, and partial ground truth.

Phase R is a strategic repositioning, not an experiment failure.

## 2. Old Positioning vs New Positioning

Old positioning:

```text
BGP forged-origin weak-signal layered detection system
```

Problems with the old positioning:
- The attack scope is too narrow.
- Deployment meaning is under-specified.
- It is too close to DFOH / BEAM / BGPShield-style monitor-centric detectors.
- `high_priority_alert / needs_review / low_priority_or_background` are not ground truth.
- `P1 / P2 / P3` priorities are not ground truth.
- The current system is better understood as incident and evidence scaffolding than as a finished strong detector.

New positioning:

```text
Adversarially robust multi-evidence BGP incident verification and triage
```

中文：

```text
对抗鲁棒多证据 BGP 事件验证与分诊系统
```

## 3. New Research Problem

English problem statement:

```text
Public-monitor-based BGP detectors can flag suspicious routing events, but under adaptive announcement manipulation, incomplete public observability, and partial ground truth, they cannot reliably verify whether a candidate incident is a real post-ROV hijack or route leak.
```

中文问题陈述：

```text
基于公共 BGP 监控器的检测器可以发现可疑路由事件，但在攻击者可操纵公告、公开观测不完整、真实标签不完备的条件下，系统很难可靠核验一个候选事件究竟是否为真实的 post-ROV 劫持或路由泄露。
```

## 4. New System Principle

Core principles:
- Public monitor output is a candidate trigger, not the final judge.
- Detector score is an evidence source, not final truth.
- RPKI invalid does not mean confirmed attack.
- RPKI valid does not mean confirmed benign.
- P3 / low / background does not mean confirmed normal.
- Stale AS relationship / IRR evidence cannot be strong evidence.
- Missing evidence should produce `abstain` or `evidence_insufficient`, not benign.
- Final output should include verdict, confidence, provenance, and abstention behavior.

## 5. Target Attack / Incident Families

Phase R covers these incident families:
- post-ROV forged-origin hijack / origin manipulation
- route leak
- path manipulation / valley-free or ASPA-related violation
- low-visibility / monitor-evasive weak-signal incidents
- poisoning / crafted announcement scenarios against public-monitor-based detectors

## 6. New Output Space

Legacy outputs:
- `high_priority_alert`
- `needs_review`
- `low_priority_or_background`
- `P1_high`
- `P2_review`
- `P3_background`

New verification verdict candidates:
- `strongly_supported_suspicious`
- `evidence_supported_suspicious`
- `evidence_conflict`
- `evidence_insufficient`
- `background_like_but_unconfirmed`
- `abstain`
- `external_evidence_unavailable`
- `stale_evidence_only`

These are verification verdict candidates, not confirmed ground truth labels.

## 7. Minimal Closed Loop

Phase R minimal closed loop:

```text
public BGP monitor updates
  -> candidate trigger
  -> incident aggregation
  -> evidence attachment
  -> legality-first verifier
  -> poisoning/evasion robustness test
  -> evidence-supported verdict / abstain
  -> top-K verification / case study
```

## 8. Relationship To Previous S3 Work

Previous S3 work becomes Phase R groundwork:

| Previous asset | Phase R role |
| --- | --- |
| S3-A incident aggregation | Keep as verifier input organizer. |
| S3-B noise audit | Keep as weak-evidence and monitor-noise analysis. |
| S3-C path plausibility / gate evidence | Keep, but downgrade to evidence features. |
| S3-D verification queue | Keep and redesign as an evidence verdict queue. |
| S3-D2 evidence attachment | Keep and upgrade into the verifier evidence layer. |
| S3-D2B evidence alignment | Keep as evidence-cache readiness audit. |
| P1/P2/P3 | Keep as legacy priority only, not truth labels. |
| high/needs/low | Keep as legacy detector outputs only, not final verdicts. |

## 9. Immediate Next Phase

Phase R next sequence:

1. Phase R-1: Verifier State Machine Design
2. Phase R-2: Legality-first Verifier
3. Phase R-3: Poisoning / Evasion Benchmark
4. Phase R-4: Multi-evidence Evaluation

No new detector-centric experiment should be launched before Phase R-1 is defined.
