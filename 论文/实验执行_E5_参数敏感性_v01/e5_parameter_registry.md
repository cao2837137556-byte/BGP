# E5 参数登记（第一轮）

## A. 候选层参数
- 参数名：`min_weak_rules`
- 所在脚本：`scripts/build_weak_candidates.py`
- 默认值：`2`
- 传参方式：CLI 参数 `--min-weak-rules <int>`
- 本轮扫描：`1 / 2 / 3`（对应 loose / default / strict）
- 选择原因：这是候选层唯一显式暴露且直接控制“弱规则命中是否入候选”的主参数。

## B. 门控层参数
- 参数名：`certainty_threshold_high`
- 所在脚本：`scripts/gate_scored_candidates.py`（`GATING_CONFIG`）
- 默认值：`65.0`
- 传参方式：当前无 CLI 参数，为脚本常量
- 本轮扫描：`58.5 / 65.0 / 71.5`（默认值附近 ±10%）
- 选择原因：直接影响样本从 high risk 进入 `likely_malicious` 的门槛，是 high_priority 入口最直接阈值。

## C. 增强层参数
- 参数名：`promoted_threshold`
- 所在脚本：`scripts/augment_uncertain_candidates.py`（`AUGMENT_CONFIG`）
- 默认值：`65.0`
- 传参方式：当前无 CLI 参数，为脚本常量
- 本轮扫描：`58.5 / 65.0 / 71.5`（默认值附近 ±10%）
- 选择原因：直接决定 uncertain 子集中多少样本被 `promoted_suspicious` 上提。

## 实验执行说明
- 本轮严格遵循“每次只改一类参数，其他层保持默认”。
- 门控层与增强层阈值通过临时脚本副本注入，未修改主链规则定义。
- 输出目录：`论文/实验执行_E5_参数敏感性_v01/`
