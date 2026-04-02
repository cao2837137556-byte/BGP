# README｜实验资产说明（E1 / E2 / E3）

- run_id: `20260313T032554_4f9be28c`
- 资产目录: `论文/实验资产_E1E2E3_v01/`

## 文件清单与用途

### E1（主链收敛）
- `e1_main_table.csv` / `e1_main_table.tex`：主链核心计数与占比（论文主实验总览表）。
- `e1_funnel_table.csv`：漏斗完整数据（含 ratio_vs_event、ratio_vs_prev）。
- `e1_funnel_plot_data.csv`：漏斗画图数据（stage + count）。
- `e1_caption.txt`：E1 图表配文草稿。

### E2（高优先质量）
- `e2_high_priority_quality_table.csv` / `e2_high_priority_quality_table.tex`：高优先来源分解、主导因子、缺失占比、质量对比。
- `e2_caption.txt`：E2 图表配文草稿。

### E3（uncertain 增强收益）
- `e3_uncertain_gain_table.csv` / `e3_uncertain_gain_table.tex`：uncertain 分流、映射、组间质量、边际收益。
- `e3_caption.txt`：E3 图表配文草稿。

### 写作辅助
- `e123_numbers_for_writing.md`：E1/E2/E3 高频引用数字清单。

## 论文放置建议
- E1：方法总览后的主实验首表（展示端到端收敛与输出规模）。
- E2：高优先质量分析小节（支撑“结构主导 + 证据完整”）。
- E3：uncertain 处理收益小节（支撑“保守但有效”）。

## 口径说明
- 本目录只做结果收口，不改算法、不改参数、不新增实验。
- 数字来源：`final/`、`phase4_e2/`、`phase4_e3/` 及上游 summary 文件。
