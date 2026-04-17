# BGP Weak-Signal Layered Detection

This repository contains the experiment code and documentation for a layered BGP anomaly detection system focused on:

- weak-signal forged-origin detection
- partial observability
- evidence-incomplete decision making
- layered triage instead of single-threshold alerting

## Main pipeline

The fixed processing chain is:

1. event construction
2. historical baseline
3. candidate generation
4. scoring
5. gating
6. augmentation
7. final alerts

Final labels are fixed as:

- `high_priority_alert`
- `needs_review`
- `low_priority_or_background`

## Repository map

- `scripts/`: core pipeline and experiment runners
- `data/known_events/`: known-event manifests and evaluation anchors
- `data/modern_2024/`: modern-data experiment plans
- `runs/prism_handoffs/`: fast experiment context handoff notes
- `论文/`: experiment ledger, asset index, and reusable experiment writeups
- `README_run.md`: unified multi-collector run entry documentation
- `WORKTREE_SOP.md`: worktree collaboration rules

## Key entry points

Core pipeline:

- `scripts/run.py`
- `scripts/build_event_units.py`
- `scripts/build_historical_baseline.py`
- `scripts/build_weak_candidates.py`
- `scripts/score_weak_candidates.py`
- `scripts/gate_scored_candidates.py`
- `scripts/augment_uncertain_candidates.py`
- `scripts/build_final_alerts.py`

Modern large-run work:

- `scripts/run_s1a_modern_2024.py`
- `scripts/build_weak_candidates_streaming.py`
- `scripts/score_weak_candidates_streaming.py`

Known-event and evaluation work:

- `scripts/run_e8c_known_events_test.py`
- `scripts/run_e9a_known_event_visibility.py`
- `scripts/run_s0_dual_track_eval.py`

## Documentation pointers

Start with these files if you need project context quickly:

- `runs/prism_handoffs/2026-04-08_experiment_context_v1.md`
- `论文/实验总表_v01.md`
- `论文/实验资产索引_v01.md`
- `论文/文献吸收_系统提升规划_v01.md`

## Data policy

Large run outputs are intentionally not tracked in Git:

- `data/runs/`
- `outputs/`
- collector marker directories under `data/markers*`

The repository stores code, manifests, and lightweight experiment documentation needed to reproduce or continue the work.
