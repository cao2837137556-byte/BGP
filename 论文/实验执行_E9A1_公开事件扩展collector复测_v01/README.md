# E9-A-1｜公开已知事件扩展 collector 复测

## 1. 问题

E8-C 中公开已知事件仅命中 `1/3`。本轮只改变 collector 可见度，验证这一结果是否主要由 VP/collector 太少导致。

## 2. 固定口径

- baseline collectors：`route-views.sg,rrc00`
- expanded collectors：`route-views.sg,route-views2,route-views.eqix,route-views.isc,rrc00,rrc01,rrc03,rrc10`
- 事件集合：沿用 E8-C 的 3 个已知事件
- 其余主链与参数不变：
  - events
  - baseline
  - candidate
  - scoring
  - gate
  - augment
  - final

## 3. 核心结果

| event_name | baseline | expanded | 变化 |
|---|---|---|---|
| Rostelecom AS12389 suspicious-origin burst | `high` | `high` | 稳定命中 |
| Google-Verizon route leak (Japan impact) | `no_visibility` | `weak_signal_not_enough` | 从不可见变为可见但仍未形成 candidate/final hit |
| Amazon Route53 / MyEtherWallet hijack | `weak_signal_not_enough` | `high` | 扩展 collector 后命中 high |

汇总：

- hit events：`1/3 -> 2/3`
- high hits：`1 -> 2`
- `no_visibility`：`1 -> 0`
- `weak_signal_not_enough`：`1 -> 1`

## 4. 解释

- `1/3` 并不等于系统只会命中一个真实事件。
- 扩展 collector 后，Google-Verizon 至少已经从 `no_visibility` 变成 `event_constructed=yes`，说明 VP 不足是关键原因之一。
- 但 Google-Verizon 仍然没有进入 candidate/final，说明事件类型或信号强度仍然是独立限制，不是简单“多加几个 VP 就全好”。
- Amazon Route53/MEW 在 expanded setting 下命中 `high`，且 `origin_match=yes`、`attacker_as_match=yes`，说明已知事件命中率对 collector 可见度确实敏感。

## 5. 工程记录

- 为支撑 8-collector augmentation，本轮对 `scripts/augment_uncertain_candidates.py` 做了等价内存优化：
  - 只读取增强所需事件列
  - 仅保留 uncertain 相关 prefix
  - groupby 后只保留行号索引，不复制整块 DataFrame
- 该优化不改变增强规则、阈值或 final label 口径。

## 6. 产物

- 主结果目录：`outputs/e9a_known_event_visibility_v01/`
- 关键文件：
  - `e9a_known_event_visibility_results.csv`
  - `e9a_known_event_visibility_summary.json`
  - `e9a_known_event_visibility_report.md`
