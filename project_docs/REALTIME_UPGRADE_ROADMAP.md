# Realtime Upgrade Roadmap

Last updated: 2026-05-13

## 1. Current System Position

The current system is an offline batch research platform.

Current mode:
- fixed-window BGP update processing
- MRT/parquet inputs
- event construction
- historical baseline
- candidate generation
- white-box score/gate/augment/final
- incident aggregation
- calibrated priority
- verification queue

Current priority is detection quality, incident aggregation, and verification readiness. It is not a production realtime alerting system.

## 2. Why Realtime Matters Later

Realtime or near-realtime capability has engineering value because operational BGP monitoring needs fast detection of:
- prefix hijack / forged-origin behavior
- route leaks
- visibility loss
- fast-changing weak signals under partial observability

Realtime support could become a future engineering extension and a useful thesis future-work direction. It should not distract from the current S3/S4 goal: making the detector and verification queue trustworthy.

## 3. Systems To Borrow Ideas From

Relevant realtime or operational systems:
- RIPE RIS Live: realtime BGP message feed over WebSocket JSON.
- ARTEMIS: realtime BGP prefix hijacking monitoring/detection/mitigation.
- BGPalerter: monitoring based on public route collector data, including hijack and visibility-loss style checks.

These are references for future architecture, not dependencies for the current S3-D implementation.

## 4. Upgrade Path

Current batch mode:

```text
MRT / parquet / fixed windows
  -> event builder
  -> baseline
  -> candidate
  -> score / gate / augment / final
  -> incident aggregation
  -> verification queue
```

Near-real-time mode:

```text
RIS Live or BGPStream update stream
  -> sliding-window event builder
  -> incremental baseline cache
  -> incremental candidate generation
  -> incremental score / gate
  -> rolling incident queue
  -> verification queue refresh
```

Online mode:

```text
rolling incident queue
  -> alert queue
  -> dashboard
  -> notification / operator workflow
```

## 5. Current Non-Goals

Do not implement realtime in the current stage:
- no live collector
- no new data ingress
- no dashboard
- no notification system
- no rewrite of score/gate/incident logic

Realtime is a later S5 / engineering-extension direction. S3/S4 should first stabilize verification and high-confidence evidence.

## 6. Future Metrics

Useful realtime metrics:
- ingest latency
- event construction latency
- scoring latency
- gate / augment latency
- incident update latency
- end-to-end detection latency
- throughput rows/sec
- memory usage
- rolling baseline update cost
- alert queue churn

## 7. Relationship To Current Experiments

S3/S4 should make the offline detector and incident verification loop reliable first.

Realtime upgrade should reuse, not replace:
- event schema
- baseline schema
- candidate reasons
- score/gate evidence
- incident aggregation logic
- verification queue schema

The intended migration is from batch pipeline to streaming/sliding-window pipeline, while preserving the same layered decision story.
