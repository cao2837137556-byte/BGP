# E5 参数敏感性结果概览（基准 run：20260313T032554_4f9be28c）

## E5-A｜候选层（min_weak_rules）
- `min_weak_rules=1 (loose)`：candidates=4808（100.00%），scored=4808，final(high/needs/low)=273/1104/3431，high_from(gating/aug)=243/30，uncertain(p/r/d)=30/1104/1997
- `min_weak_rules=2 (default)`：candidates=4808（100.00%），scored=4808，final(high/needs/low)=273/1104/3431，high_from(gating/aug)=243/30，uncertain(p/r/d)=30/1104/1997
- `min_weak_rules=3 (strict)`：candidates=4808（100.00%），scored=4808，final(high/needs/low)=273/1104/3431，high_from(gating/aug)=243/30，uncertain(p/r/d)=30/1104/1997
- 现象：三档结果完全一致，说明在当前实现/数据口径下，`min_weak_rules` 对结果几乎无影响（被结构性规则覆盖）。

## E5-B｜门控层（certainty_threshold_high）
- `58.5 (loose)`：final(high/needs/low)=25/624/457；high_from(gating/aug)=25/0；missing_in_high=0；top_factor=structural_novelty_score；uncertain=642
- `65.0 (default)`：final(high/needs/low)=24/625/457；high_from(gating/aug)=22/2；missing_in_high=0；top_factor=structural_novelty_score；uncertain=645
- `71.5 (strict)`：final(high/needs/low)=22/627/457；high_from(gating/aug)=0/22；missing_in_high=0；top_factor=structural_novelty_score；uncertain=667
- 现象：阈值越严，门控直接给 high 的样本减少，更多样本进入 uncertain 并由增强层上提；但 high 规模仍小且质量口径稳定。

## E5-C｜增强层（promoted_threshold）
- `58.5 (loose)`：final(high/needs/low)=25/624/457；high_from(gating/aug)=22/3；uncertain(p/r/d)=3/624/18
- `65.0 (default)`：final(high/needs/low)=24/625/457；high_from(gating/aug)=22/2；uncertain(p/r/d)=2/625/18
- `71.5 (strict)`：final(high/needs/low)=22/627/457；high_from(gating/aug)=22/0；uncertain(p/r/d)=0/627/18
- 现象：`promoted_threshold` 主要影响 promoted 数量（3→2→0），retained 始终占主流，demoted 基本稳定。
