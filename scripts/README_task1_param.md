# Task 1 - 参数化（演示级可复现）

你现在有两个脚本：

- scripts/03_collect_updates.py  ✅ 参数化主脚本（推荐你后续一直用它）
- scripts/02_updates_to_parquet.py ✅ 一键smoketest（不带参数就跑固定的5分钟样例）

## 1) 一键smoketest（确认环境没问题）
python .\scripts\02_updates_to_parquet.py

## 2) 参数化采集（你想采哪里就采哪里）
python .\scripts\03_collect_updates.py --from "2017-07-07 00:00:00" --minutes 5 --collectors route-views.sg --record-type updates --max-rows 3000 --format parquet

## 3) 快速检查输出
python -c "import pandas as pd; import glob; p=sorted(glob.glob('data/parquet/**/updates__*.parquet', recursive=True))[-1]; print('latest=',p); print(pd.read_parquet(p).head())"
