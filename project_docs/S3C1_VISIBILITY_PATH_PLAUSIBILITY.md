# S3-C1 Visibility-Aware Path Plausibility

最后更新：2026-05-07

## 1. Scope

S3-C1 是 S3-B 之后的离线 scoring pilot，目标是为低可见度、短时、unseen-path novelty 样本增加白盒路径可信度评分。

固定目标 run：

- `s2a_expanded_v01_pilot_6h_april16`

严格边界：

- 不重跑 raw/events/baseline/candidate。
- 不覆盖 `scored_candidates.parquet`。
- 不覆盖 `gated_candidates.parquet`。
- 不覆盖 `final_alerts.parquet`。
- 不修改主链默认行为。
- 不把 P1/P2 当真实异常。
- 不把 P3/low 当绝对正常。
- 本阶段只产出离线 `adjusted_risk_score_s3c1` 和 before/after 估计。

## 2. Motivation

S3-B 定位当前最大 P1/P2 噪声/弱信号结构为：

```text
single_collector_visibility
  + structural_novelty_score
  + unseen_path_for_prefix_origin
  + unusually_short_duration_for_prefix
```

该结构覆盖：

- `27120` calibrated P1/P2 tickets
- `3943362` member rows
- weighted high share 约 `0.095`
- weighted needs share 约 `0.905`

因此 S3-C1 不直接删除低可见度事件，而是把它们拆成可解释的 plausibility components，再只对低/中可信的 pattern_A 做离线降权。

## 3. Implementation

新增脚本：

- `scripts/run_s3c1_visibility_path_plausibility_pilot.py`
- `scripts/hpc/s3c1_visibility_path_plausibility.slurm`

输出目录：

- `outputs/s3c1_visibility_path_plausibility_v01/`

输出文件：

- `s3c1_summary.json`
- `s3c1_candidate_plausibility_sample.parquet`
- `s3c1_score_before_after.csv`
- `s3c1_pattern_delta.csv`
- `s3c1_bucket_distribution.csv`
- `s3c1_top_demoted_candidates.csv`
- `s3c1_known_event_regression_check.csv`
- `s3c1_report.md`

新增离线字段：

- `visibility_support_score`
- `collector_visibility_ratio`
- `single_collector_flag`
- `low_visibility_flag`
- `collector_diversity_bucket`
- `temporal_support_score`
- `short_lived_flag`
- `duration_bucket`
- `temporal_confirmation_count`
- `history_support_score`
- `path_seen_before_flag`
- `path_reuse_score`
- `prefix_origin_path_support`
- `path_neighborhood_support`
- `path_length_plausibility_score`
- `path_length_zscore`
- `abnormal_path_length_flag`
- `relation_support_score`
- `rel_unknown_ratio`
- `rel_has_unknown_flag`
- `path_plausibility_score`
- `plausibility_bucket`
- `plausibility_penalty`
- `adjusted_risk_score_s3c1`
- `adjusted_risk_bucket_s3c1`
- `s3c1_adjustment_reason`

## 4. Default Rules

Composite plausibility:

- visibility：25%
- temporal：25%
- history：30%
- path length：15%
- relation：5%

如果 relation fields 不可用，relation 权重重分配给其他四项。

`plausibility_bucket`：

- `high_plausibility`: `>=70`
- `medium_plausibility`: `40~69`
- `low_plausibility`: `<40`

默认 penalty：

- `pattern_A && !pattern_B && low_plausibility`: `risk_score -15`
- `pattern_A && !pattern_B && medium_plausibility`: `risk_score -5`
- `pattern_B`: 默认不降权，只进入并列诊断

`pattern_B` 不默认降权的原因是 S3-B 中该结构 weighted high share 明显更高，需要 S3-C2/S3-C3 的额外证据检查，而不是粗暴套用 pattern_A 的 penalty。

## 5. Current Local Validation

固定 S2 run 的本地主输入尚未拉全：

- 缺失：`data/runs/s2a_expanded_v01_pilot_6h_april16/scores/scored_candidates.parquet`
- 当前本地该 run 只有 `incidents/`

因此 S3-C1 fixed-run full 尚未执行。脚本已用本地完整的 60min expanded run 做 smoke：

```text
run_id=s1a_expanded_v02_pilot_60m_april16
sample_rows=200000
status=completed_with_warnings
```

smoke 结果：

- loaded_rows：`200000`
- pattern_A_rows：`133289`
- pattern_B_rows：`12938`
- adjusted_risk_changed_rows：`122956`
- risk_bucket_changed_rows：`84041`
- pattern_A_adjusted_down_rows：`122956`
- pattern_B_adjusted_down_rows：`0`

该 smoke 只验证代码路径，不作为 S2-C1 正式实验结果。

## 6. Fixed-Run Commands

### 6.1 超算同步与执行

超算不是 git repo，不使用 `git pull`。本地改动后用 `scp` 同步到超算。

本地上传 S3-C1 代码与文档：

```powershell
cd D:\study\paper\worktrees\bgp-platform-exp-mainline

scp .\scripts\run_s3c1_visibility_path_plausibility_pilot.py jiangxinwei.zr@school-hpc:/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/repo/scripts/
scp .\scripts\hpc\s3c1_visibility_path_plausibility.slurm jiangxinwei.zr@school-hpc:/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/repo/scripts/hpc/
scp .\project_docs\S3C1_VISIBILITY_PATH_PLAUSIBILITY.md jiangxinwei.zr@school-hpc:/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/repo/project_docs/
scp .\project_docs\HANDOFF.md jiangxinwei.zr@school-hpc:/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/repo/project_docs/
scp .\project_docs\EXPERIMENT_MAINLINE.md jiangxinwei.zr@school-hpc:/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/repo/project_docs/
scp .\project_docs\S3_DETECTION_QUALITY_ROADMAP.md jiangxinwei.zr@school-hpc:/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/repo/project_docs/
```

登录超算并确认输入：

```bash
ssh jiangxinwei.zr@school-hpc
cd /public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/repo

ls data/runs/s2a_expanded_v01_pilot_6h_april16/scores/scored_candidates.parquet
ls data/runs/s2a_expanded_v01_pilot_6h_april16/events/event_units.parquet
ls data/runs/s2a_expanded_v01_pilot_6h_april16/candidates/candidate_events.parquet
ls data/runs/s2a_expanded_v01_pilot_6h_april16/gating/gated_candidates.parquet
ls data/runs/s2a_expanded_v01_pilot_6h_april16/final/final_alerts.parquet
ls data/runs/s2a_expanded_v01_pilot_6h_april16/baseline/baseline_prefix_origin.parquet
ls data/runs/s2a_expanded_v01_pilot_6h_april16/incidents/incident_membership.parquet
ls outputs/s3a2_incident_priority_calibration_v01/s3a2_calibrated_incident_tickets.parquet
```

先提交 S2 fixed-run smoke：

```bash
MODE=smoke \
OUTPUT_DIR=outputs/s3c1_visibility_path_plausibility_smoke_s2 \
BUNDLE_NAME=s3c1_visibility_path_plausibility_smoke_bundle \
sbatch scripts/hpc/s3c1_visibility_path_plausibility.slurm
```

查看队列：

```bash
squeue -u $USER
```

实时日志中的 job id 要替换成 `sbatch` 返回的实际 id：

```bash
tail -f /public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/logs/s3c1_visibility_path_plausibility_<实际jobid>.live.log
```

smoke 通过后提交 full：

```bash
MODE=full \
OUTPUT_DIR=outputs/s3c1_visibility_path_plausibility_v01 \
BUNDLE_NAME=s3c1_visibility_path_plausibility_bundle \
sbatch scripts/hpc/s3c1_visibility_path_plausibility.slurm
```

### 6.2 本地拉回 full 输出

full 完成后，在本地 PowerShell 执行：

```powershell
cd D:\study\paper\worktrees\bgp-platform-exp-mainline

New-Item -ItemType Directory -Force .\outputs\s3c1_visibility_path_plausibility_v01 | Out-Null
New-Item -ItemType Directory -Force .\outputs\bundles | Out-Null

scp -r "jiangxinwei.zr@school-hpc:/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/repo/outputs/s3c1_visibility_path_plausibility_v01/*" .\outputs\s3c1_visibility_path_plausibility_v01\
scp "jiangxinwei.zr@school-hpc:/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/repo/outputs/bundles/s3c1_visibility_path_plausibility_bundle.zip" .\outputs\bundles\
scp "jiangxinwei.zr@school-hpc:/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/logs/s3c1_visibility_path_plausibility_<实际jobid>.live.log" .\outputs\s3c1_visibility_path_plausibility_v01\
```

### 6.3 本地直接执行，仅用于已拉回完整输入时

先确认固定 run 输入是否已拉回：

```powershell
Test-Path .\data\runs\s2a_expanded_v01_pilot_6h_april16\scores\scored_candidates.parquet
Test-Path .\data\runs\s2a_expanded_v01_pilot_6h_april16\events\event_units.parquet
Test-Path .\data\runs\s2a_expanded_v01_pilot_6h_april16\candidates\candidate_events.parquet
Test-Path .\data\runs\s2a_expanded_v01_pilot_6h_april16\gating\gated_candidates.parquet
Test-Path .\data\runs\s2a_expanded_v01_pilot_6h_april16\final\final_alerts.parquet
```

如缺失，需要从超算拉回对应目录。用户手动执行时使用：

```powershell
cd D:\study\paper\worktrees\bgp-platform-exp-mainline

New-Item -ItemType Directory -Force .\data\runs\s2a_expanded_v01_pilot_6h_april16\scores | Out-Null
New-Item -ItemType Directory -Force .\data\runs\s2a_expanded_v01_pilot_6h_april16\events | Out-Null
New-Item -ItemType Directory -Force .\data\runs\s2a_expanded_v01_pilot_6h_april16\candidates | Out-Null
New-Item -ItemType Directory -Force .\data\runs\s2a_expanded_v01_pilot_6h_april16\gating | Out-Null
New-Item -ItemType Directory -Force .\data\runs\s2a_expanded_v01_pilot_6h_april16\final | Out-Null
New-Item -ItemType Directory -Force .\data\runs\s2a_expanded_v01_pilot_6h_april16\baseline | Out-Null

scp "jiangxinwei.zr@school-hpc:/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/repo/data/runs/s2a_expanded_v01_pilot_6h_april16/scores/scored_candidates.parquet" .\data\runs\s2a_expanded_v01_pilot_6h_april16\scores\
scp "jiangxinwei.zr@school-hpc:/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/repo/data/runs/s2a_expanded_v01_pilot_6h_april16/scores/score_summary.json" .\data\runs\s2a_expanded_v01_pilot_6h_april16\scores\
scp "jiangxinwei.zr@school-hpc:/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/repo/data/runs/s2a_expanded_v01_pilot_6h_april16/events/event_units.parquet" .\data\runs\s2a_expanded_v01_pilot_6h_april16\events\
scp "jiangxinwei.zr@school-hpc:/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/repo/data/runs/s2a_expanded_v01_pilot_6h_april16/candidates/candidate_events.parquet" .\data\runs\s2a_expanded_v01_pilot_6h_april16\candidates\
scp "jiangxinwei.zr@school-hpc:/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/repo/data/runs/s2a_expanded_v01_pilot_6h_april16/gating/gated_candidates.parquet" .\data\runs\s2a_expanded_v01_pilot_6h_april16\gating\
scp "jiangxinwei.zr@school-hpc:/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/repo/data/runs/s2a_expanded_v01_pilot_6h_april16/final/final_alerts.parquet" .\data\runs\s2a_expanded_v01_pilot_6h_april16\final\
scp "jiangxinwei.zr@school-hpc:/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/repo/data/runs/s2a_expanded_v01_pilot_6h_april16/baseline/baseline_prefix_origin.parquet" .\data\runs\s2a_expanded_v01_pilot_6h_april16\baseline\
```

然后先 smoke：

```powershell
python scripts\run_s3c1_visibility_path_plausibility_pilot.py `
  --run-id s2a_expanded_v01_pilot_6h_april16 `
  --output-dir outputs\s3c1_visibility_path_plausibility_v01 `
  --sample-rows 200000
```

再 full：

```powershell
python scripts\run_s3c1_visibility_path_plausibility_pilot.py `
  --run-id s2a_expanded_v01_pilot_6h_april16 `
  --output-dir outputs\s3c1_visibility_path_plausibility_v01 `
  --full-run
```

## 7. Next Judgment

S3-C1 代码已 ready，但固定 S2 run full 结果待补齐输入后执行。

full 结果出来后再判断：

- 若 pattern_A 的 bucket change 合理，进入 S3-C2 gate evidence support ablation。
- 若 pattern_A 降权过强，先调 S3-C1 权重。
- 若 known-event / verification 输入不足，先补 final / inventory / incident join 后复跑。
