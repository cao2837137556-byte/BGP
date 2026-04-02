# WORKTREE SOP（bgp-platform）

## 目标
- 固定“实验线”和“论文线”两条并行工作线，减少互相污染。
- 实验代码、产物整理、论文交接分离推进。

## 分支与工作树
- 主仓库主分支：`main`
- 实验分支：`codex/bgp-exp-mainline`
- 论文分支：`codex/bgp-paper-handoff`

建议工作树路径（仓库外）：
- `D:\study\paper\worktrees\bgp-platform-exp-mainline`
- `D:\study\paper\worktrees\bgp-platform-paper-handoff`

## 职责边界
- `codex/bgp-exp-mainline`：只做实验代码、实验执行、指标汇总脚本。
- `codex/bgp-paper-handoff`：只做图表、结果整理、Prism 交接文档。
- 不在论文分支改实验主逻辑；不在实验分支改论文正文结构。

## 目录约定
- 交接文档目录：`runs/prism_handoffs/`
- 实验执行汇总：`论文/实验执行_*`
- 项目总控文档：`论文/实验总表_v01.md`

## 合流原则
- 实验分支稳定后，先提交实验分支。
- 论文分支只消费已确认产物与结论，不反向改动实验逻辑。
- 需要跨分支同步时，优先 `cherry-pick` 小提交，不做大范围混合合并。

## 触发收口口令
- `开始总控固化：<run_tag>`

## 最小日常操作
```powershell
# 查看全部工作树
git worktree list

# 进入实验树
cd D:\study\paper\worktrees\bgp-platform-exp-mainline

# 进入论文树
cd D:\study\paper\worktrees\bgp-platform-paper-handoff
```
