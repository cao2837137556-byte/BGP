# E5 最小运行索引

## 复用与重跑策略
- 基准 run：`20260313T032554_4f9be28c`
- E5-A（候选层）：复用 `events/` + `baseline/`，重跑 `candidates -> scores -> gating -> augmentation -> final`
- E5-B（门控层）：复用 `events/` + `baseline/` + `candidates/` + `scores/`，重跑 `gating -> augmentation -> final`
- E5-C（增强层）：复用 `events/` + `baseline/` + `candidates/` + `scores/` + `gating/`，重跑 `augmentation -> final`

## 配置与关键产物

### E5-A
- `e5_a_mwr1`：`min_weak_rules=1 (loose)`
- `e5_a_mwr2`：`min_weak_rules=2 (default)`
- `e5_a_mwr3`：`min_weak_rules=3 (strict)`

### E5-B
- `e5_b_cth58p5`：`certainty_threshold_high=58.5 (loose)`
- `e5_b_cth65p0`：`certainty_threshold_high=65.0 (default)`
- `e5_b_cth71p5`：`certainty_threshold_high=71.5 (strict)`

### E5-C
- `e5_c_pth58p5`：`promoted_threshold=58.5 (loose)`
- `e5_c_pth65p0`：`promoted_threshold=65.0 (default)`
- `e5_c_pth71p5`：`promoted_threshold=71.5 (strict)`

## 每个配置可追踪文件
- `data/runs/<run_id>/candidates/candidate_summary.json`
- `data/runs/<run_id>/scores/score_summary.json`
- `data/runs/<run_id>/gating/gating_summary.json`
- `data/runs/<run_id>/augmentation/augmentation_summary.json`
- `data/runs/<run_id>/final/final_report.json`
