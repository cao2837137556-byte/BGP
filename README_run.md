# 运行包装脚本（多 Collector 串行 + 分块 + 断点 + CAIDA 标注）

本项目使用 `scripts/run.py` 作为统一入口，支持：
1) 多 collector 串行采集（同一个 run_id）
2) 按时间分块采集（chunk）
3) 每个 collector 独立 marker 断点续跑
4) 默认执行 CAIDA AS-relationship 标注（可关闭）
5) 标准化输出 `run.json` / `run.log`

## 运行入口
统一入口：`python scripts/run.py ...`

推荐在 Docker 中运行：
```powershell
docker run --rm -v ${PWD}:/work -w /work bgpstream-py python scripts/run.py ...
```

## 参数说明

### 采集参数
- `--collectors`：逗号分隔多个 collector，例如 `route-views.sg,rrc00,rrc10`
- `--from`：起始时间，格式 `YYYY-MM-DD HH:MM:SS`
- `--minutes`：总时长（分钟）
- `--chunk-minutes`：每个 chunk 时长（分钟）
- `--record-type`：`updates` 或 `ribs`
- `--max-rows`：每个 chunk 的最大行数（透传到 `03_collect_updates.py`）
- `--format`：输出格式（开启标注时必须为 `parquet`）
- `--print-head`：采集脚本打印前 N 行
- `--run-id`：可选，手动指定 run_id

### 断点参数
- `--resume`：从 marker 时间继续（启用后忽略 `--from`）
- `--marker-dir`：marker 目录，默认 `data/markers`

marker 文件规则：
- 路径：`data/markers/{record_type}__{collector}.txt`
- 内容：该 collector 最近一次成功 chunk 的结束时间
- 只有“采集成功 +（可选）标注成功”后才更新

### 标注参数
- `--label-caida`：开启 CAIDA 标注（默认开启）
- `--no-label-caida`：关闭 CAIDA 标注
- `--caida-rel`：CAIDA as-rel2 文件路径
- `--label-script`：标注脚本路径，默认 `scripts/04_annotate_caida_rel.py`
- `--label-suffix`：标注输出后缀，默认 `__rel`
- `--label-overwrite`：允许覆盖已存在的标注文件

## 执行逻辑（当前版本）
1. 只生成一次 `run_id`，输出目录为 `data/runs/<run_id>/`
2. 按 `--collectors` 逐个串行执行（不并发）
3. 每个 collector 内部按 chunk 循环采集
4. 每个 chunk 成功后更新该 collector 的 marker
5. 若启用标注，每个 chunk 后调用 `04_annotate_caida_rel.py`
6. 单个 collector 失败不会中断其他 collector
7. 只要任意 collector 失败，`run.py` 进程最终返回非 0

## 输出目录结构
每次 run 产物落在：`data/runs/<run_id>/`

典型结构：
```text
data/runs/<run_id>/
  run.json
  run.log
  collector=route-views.sg/
    date=2017-07-07/
      updates__00-00-00__00-05-00.parquet
      updates__00-00-00__00-05-00__rel.parquet
      ...
  collector=rrc00/
    date=2017-07-07/
      updates__00-00-00__00-05-00.parquet
      updates__00-00-00__00-05-00__rel.parquet
      ...
```

## run.json 关键字段
- 顶层字段：`run_id`、`collectors`、`minutes`、`chunk_minutes`、`label_caida`、`out_dir` 等
- `collectors_summary`：每个 collector 的明细状态

每个 collector 明细包含：
- `status`：`ok` / `failed`
- `marker_before`：本次开始前读取到的 marker
- `marker_after`：本次成功推进到的最后时间
- `updates_outputs`：原始 parquet 列表
- `rel_outputs`：标注 parquet 列表
- `errors`：错误列表

## run.log 关键格式
- `[collector] START <collector>`
- `[chunk] collector=<collector> from=... until=...`
- `[collect] CMD: ...`
- `[caida_label] CMD: ...`
- `[collector] END <collector> status=ok|failed`

## 常用命令

### 1) 多 collector（默认采集 + 标注）
```powershell
docker run --rm -v ${PWD}:/work -w /work bgpstream-py python scripts/run.py \
  --from "2017-07-07 00:00:00" --minutes 10 --chunk-minutes 5 \
  --collectors route-views.sg,rrc00 --record-type updates --format parquet
```

### 2) 多 collector（只采集，不标注）
```powershell
docker run --rm -v ${PWD}:/work -w /work bgpstream-py python scripts/run.py \
  --from "2017-07-07 00:00:00" --minutes 10 --chunk-minutes 5 \
  --collectors route-views.sg,rrc00 --record-type updates --format parquet --no-label-caida
```

### 3) 多 collector 断点续跑
```powershell
docker run --rm -v ${PWD}:/work -w /work bgpstream-py python scripts/run.py \
  --resume --minutes 10 --chunk-minutes 5 \
  --collectors route-views.sg,rrc00 --record-type updates --format parquet
```
