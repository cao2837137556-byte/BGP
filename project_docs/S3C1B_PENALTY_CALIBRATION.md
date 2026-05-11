# S3-C1b Penalty Calibration

最后更新：2026-05-09

## 1. Scope

S3-C1b 是 S3-C1 之后的离线 penalty calibration / ablation。

固定目标 run：

- `s2a_expanded_v01_pilot_6h_april16`

边界：

- 不重跑 raw/events/baseline/candidate。
- 不覆盖 `scored_candidates.parquet`。
- 不覆盖 `gated_candidates.parquet`。
- 不覆盖 `final_alerts.parquet`。
- 不修改主链默认行为。
- 不把 P1/P2 当真实异常。
- 不把 P3/low 当绝对正常。
- 不直接采用 S3-C1 default penalty。

## 2. Motivation

S3-C1 full 已证明 visibility-aware path plausibility 能命中主噪声结构：

```text
pattern_A =
single_collector_visibility
  + structural_novelty_score
  + unseen_path_for_prefix_origin
  + unusually_short_duration_for_prefix
```

但 S3-C1 default penalty 太强：

- risk bucket changed：`4576319`
- score high：`2047659 -> 1187117`
- P1/P2 adjusted_down_rows：`3510753`
- touched P1/P2 incidents：`32469`

S3-C1b 的目标不是继续追求最大降幅，而是找到能约束 pattern_A、保护 pattern_B、并把 score migration 控制住的策略。

## 3. Implementation

新增脚本：

- `scripts/run_s3c1b_penalty_calibration.py`
- `scripts/hpc/s3c1b_penalty_calibration.slurm`

输出目录：

- `outputs/s3c1b_penalty_calibration_v01/`

输出文件：

- `s3c1b_summary.json`
- `s3c1b_strategy_comparison.csv`
- `s3c1b_pattern_A_delta_by_strategy.csv`
- `s3c1b_pattern_B_protection.csv`
- `s3c1b_p1_p2_impact_by_strategy.csv`
- `s3c1b_bucket_transition_matrix.csv`
- `s3c1b_known_event_regression_check.csv`
- `s3c1b_recommended_strategy.json`
- `s3c1b_report.md`

实现说明：

- S3-C1b 不用 S3-C1 的 20 万行 sample 做 full。
- full 会重读 fixed-run 的 score/events/candidates/gating/final/incidents，并复用 S3-C1 的 plausibility feature logic。
- known-event inventory 缺失时只 warning，不中断。

## 4. Strategies

| strategy | low plausibility pattern_A | medium plausibility pattern_A | gate evidence | pattern_B |
| --- | ---: | ---: | --- | ---: |
| `strategy_default_s3c1` | -15 | -5 | no | 0 |
| `strategy_low_only_minus15` | -15 | 0 | no | 0 |
| `strategy_low_only_minus10` | -10 | 0 | no | 0 |
| `strategy_low_minus10_medium_minus2` | -10 | -2 | no | 0 |
| `strategy_low_minus8_medium_minus2` | -8 | -2 | no | 0 |
| `strategy_gate_only` | 0 | 0 | low + medium | 0 |
| `strategy_medium_gate_only` | -10 | 0 | medium only | 0 |

`strategy_default_s3c1` 只作为 upper bound，不允许推荐进入主链。

## 5. Local Smoke

本地用 `s1a_expanded_v02_pilot_60m_april16` 20 万行 smoke 通过：

- loaded_rows：`200000`
- default bucket_changed_rows：`84041`
- recommended_strategy：`strategy_medium_gate_only`
- recommended bucket_changed_rows：`28`
- recommended pattern_A_adjusted_down_rows：`144`
- recommended pattern_A_gate_evidence_rows：`122812`
- pattern_B_adjusted_down_rows：`0`
- known_event_available：`true`
- known_event_matched_rows：`0`
- known_event_regression_count：`0`

该 smoke 只验证代码路径和策略选择逻辑，不作为 S2 full 正式结论。

## 6. HPC Execution

超算不是 git repo，不使用 `git pull`。本地改动后用 `scp` 同步到超算。

本地上传：

```powershell
cd D:\study\paper\worktrees\bgp-platform-exp-mainline

scp .\scripts\run_s3c1b_penalty_calibration.py jiangxinwei.zr@school-hpc:/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/repo/scripts/
scp .\scripts\run_s3c1_visibility_path_plausibility_pilot.py jiangxinwei.zr@school-hpc:/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/repo/scripts/
scp .\scripts\hpc\s3c1b_penalty_calibration.slurm jiangxinwei.zr@school-hpc:/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/repo/scripts/hpc/
scp .\data\known_events\known_event_candidates_v05.json jiangxinwei.zr@school-hpc:/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/repo/data/known_events/
scp .\project_docs\S3C1B_PENALTY_CALIBRATION.md jiangxinwei.zr@school-hpc:/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/repo/project_docs/
```

登录并先跑 smoke：

```bash
ssh jiangxinwei.zr@school-hpc
cd /public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/repo

MODE=smoke \
OUTPUT_DIR=outputs/s3c1b_penalty_calibration_smoke_s2 \
BUNDLE_NAME=s3c1b_penalty_calibration_smoke_bundle \
sbatch -c 4 --mem=32G -t 01:00:00 scripts/hpc/s3c1b_penalty_calibration.slurm
```

smoke 成功后跑 full：

```bash
MODE=full \
OUTPUT_DIR=outputs/s3c1b_penalty_calibration_v01 \
BUNDLE_NAME=s3c1b_penalty_calibration_bundle \
sbatch -c 8 --mem=128G -t 08:00:00 scripts/hpc/s3c1b_penalty_calibration.slurm
```

看队列：

```bash
squeue -u $USER
```

看日志：

```bash
tail -f "$(ls -t /public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/logs/s3c1b_penalty_calibration_*.live.log | head -1)"
```

## 7. Pullback

full 完成后本地拉回：

```powershell
cd D:\study\paper\worktrees\bgp-platform-exp-mainline

New-Item -ItemType Directory -Force .\outputs\s3c1b_penalty_calibration_v01 | Out-Null
New-Item -ItemType Directory -Force .\outputs\bundles | Out-Null

scp -r "jiangxinwei.zr@school-hpc:/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/repo/outputs/s3c1b_penalty_calibration_v01/*" .\outputs\s3c1b_penalty_calibration_v01\
scp "jiangxinwei.zr@school-hpc:/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/repo/outputs/bundles/s3c1b_penalty_calibration_bundle.zip" .\outputs\bundles\
scp "jiangxinwei.zr@school-hpc:/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/logs/s3c1b_penalty_calibration_*.live.log" .\outputs\s3c1b_penalty_calibration_v01\
```

## 8. Next Judgment

S3-C1b full 完成后判断：

- 若 `strategy_medium_gate_only` 仍稳定，进入 S3-C2 gate evidence support ablation。
- 若所有 score-changing strategy 仍迁移过大，则使用 `strategy_gate_only`。
- 不推荐 `strategy_default_s3c1` 直接进入主链。

## 9. S3-C2 Scaffold Note

- `scripts/run_s3c2_gate_evidence_ablation.py` has been added.
- Local S1A 200k smoke passed under `outputs/s3c2_gate_evidence_ablation_smoke_s1a/`.
- This is only scaffold/smoke. Do not treat it as fixed S2 full evidence until S3-C1b full is pulled back and S3-C2 is rerun on `s2a_expanded_v01_pilot_6h_april16`.

## 10. Fixed S2 Full Result

Full result pulled back on 2026-05-11:
- run_id `s2a_expanded_v01_pilot_6h_april16`
- input/loaded rows `10236431 / 10236431`
- status `completed`
- warnings `0`
- recommended_strategy `strategy_medium_gate_only`
- default bucket_changed_rows `4576319`
- default score-high `2047659 -> 1187117`
- recommended bucket_changed_rows `5183`
- recommended score-high `2047659 -> 2042688`
- recommended pattern_A_adjusted_down_rows `15294`
- recommended pattern_A_gate_evidence_rows `6870696`
- recommended pattern_B_adjusted_down_rows `0`
- recommended pattern_B_bucket_changed_rows `0`
- recommended P1/P2 adjusted_down_rows `31`
- recommended P1/P2 gate_evidence_rows `3510722`
- touched P1/P2 incidents `32469`
- known-event inventory was readable, but matched rows were `0`; this should not be interpreted as no regression risk.

Conclusion: `strategy_medium_gate_only` is stable on fixed S2 full. Use it as S3-C2 gate evidence input; do not adopt S3-C1 default penalty as mainline behavior.
