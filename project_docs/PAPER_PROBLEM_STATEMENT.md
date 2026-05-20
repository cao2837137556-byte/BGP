# Paper Problem Statement

Last updated: 2026-05-20

This is a planning note for Phase R. It is not the paper text.

## 1. English Title Candidates

1. Beyond Public Monitors: Adversarially Robust BGP Incident Verification under Partial Ground Truth
2. Veritas-BGP: Multi-Evidence Verification of Post-ROV Hijacks and Route Leaks
3. From Alerts to Evidence: Robust Verification for BGP Routing Incidents
4. Seeing Through Poisoned Monitors: Multi-Evidence Verification for BGP Security Events
5. Trust but Verify: Robust BGP Event Triage with RPKI, ASPA, and Cross-Plane Evidence

## 2. Chinese Title Candidates

1. 超越公共监控器：部分真值下的对抗鲁棒 BGP 事件验证
2. Veritas-BGP：面向后 ROV 劫持与路由泄露的多证据核验系统
3. 从告警到证据：面向 BGP 路由安全事件的鲁棒验证框架
4. 看穿被投毒的监控器：BGP 安全事件的多证据验证方法
5. 信而后证：融合 RPKI、ASPA 与跨平面证据的 BGP 事件核验

## 3. One-Sentence Problem

English:

```text
Public-monitor-based BGP detectors can flag anomalies, but under adaptive announcement manipulation and incomplete ground truth they cannot reliably verify whether a candidate event is a real post-ROV hijack or route leak.
```

Chinese:

```text
基于公共 BGP 监控器的检测器可以发现异常候选，但在攻击者可操纵路由公告且真值不完备的现实环境中，它们无法可靠核验一个候选事件究竟是否为真实的后 ROV 劫持或路由泄露。
```

## 4. Three Contributions

1. Problem contribution:
   Formalize adversarially robust BGP incident verification under partial ground truth, moving beyond detector accuracy on public monitor streams.

2. System contribution:
   Design a multi-evidence verifier that combines monitor triggers, time-aligned RPKI/ROA, path legality/ASPA-ready evidence, AS relationship/IRR/PeeringDB-style auxiliary evidence, temporal and collector support, provenance, confidence, and abstention.

3. Evaluation contribution:
   Build a poisoning / evasion / legality / human-burden evaluation matrix comparing monitor-only, RPKI-only, legality-only, and multi-evidence verification under incomplete evidence.

## 4A. CCF-A Contribution Version

Current main target: CCF-A / top-tier networking or security venue. SCI Q2 is a fallback only.

Contribution 1: Problem and benchmark

- Formalize poisoning-robust BGP incident triage under partial observability.
- Build a monitor poisoning / evasion benchmark for public-monitor-based BGP evidence.

Contribution 2: Evidence-constrained verifier

- Validate evidence at member/component level, not only at incident dominant-pair level.
- Audit component purity and mixture before issuing incident-level verdicts.
- Output abstention-aware verdicts with provenance and confidence caps.

Contribution 3: Component-aware semantic learning ranker

- Learn incident internal structure after verifier-supported targets exist.
- Calibrate evidence-supported weak signals without replacing verifier hard rules.
- Reduce Top-K human review burden under poisoning and missing/conflicting evidence.

The CCF-A claim is not "we built another detector." The claim is that the system turns poisonable monitor alerts into evidence-constrained, component-aware, abstention-capable incident triage.

## 5. Minimum Experiment Matrix

| Dimension | Minimum design |
| --- | --- |
| Incident families | post-ROV forged-origin, route leak, normal/conflict/unknown |
| Data sources | RouteViews/RIPE RIS, time-aligned ROA/VRP if available, AS-rel/IRR, optional ASPA/BGP Roles/OTC |
| Adversarial scenarios | monitor poisoning with `0/1/2/3/5` crafted announcements, monitor subset manipulation, stale evidence injection |
| Evidence settings | monitor-only, RPKI-only, legality-only, multi-evidence, missing-evidence stress |
| Outputs | verdict candidates, confidence, provenance, abstain |
| Metrics | precision proxy, supported suspicious recall, abstention rate, evidence coverage, stale/unavailable rate, robustness drop, evasion cost, top-K retention, human review burden proxy |

## 6. Likely Reviewer Questions

Question: You do not have complete ground truth.

Answer: Partial ground truth is part of the problem. The system explicitly separates confirmed, evidence-supported, conflicting, insufficient, and abstained outcomes instead of forcing binary attack/benign labels.

Question: Is this just engineering integration?

Answer: The novelty is the threat model and verification objective: public monitor poisoning plus partial ground truth plus multi-evidence triage with provenance and abstention. The system is evaluated under robustness and review-burden metrics, not just detector AUC.

Question: Why not build a stronger detector?

Answer: Public-monitor-centered detectors can be poisoned. A stronger detector still inherits monitor manipulation unless it is backed by independent, time-aligned evidence and abstention-aware verification.

Question: ASPA and path-legality evidence may be unavailable.

Answer: The verifier models unavailable evidence explicitly. It can abstain or emit `external_evidence_unavailable`; it does not assume universal ASPA deployment.

Question: Does RPKI invalid prove attack?

Answer: No. RPKI invalid is an evidence component, not a final truth label.

Question: Does background-like mean benign?

Answer: No. The correct verdict is `background_like_but_unconfirmed` unless external evidence supports a stronger conclusion.

## 7. Answer Strategy

Use S3-A to S3-D2B as groundwork:
- incident aggregation shows how raw alerts become reviewable cases,
- noise audit exposes public-monitor weakness,
- gate evidence and plausibility become evidence features,
- evidence attachment and alignment show the need for time-aligned external evidence,
- Phase R turns this into a verifier-centric research problem.

Avoid claiming:
- final truth labels from detector outputs,
- benign labels from low priority,
- strong evidence from stale sources,
- robustness without poisoning/evasion tests.
