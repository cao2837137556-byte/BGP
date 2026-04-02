"""02_updates_to_parquet.py

A safe, one-command smoke test.

- Running with *no args* executes the same 5-minute smoketest as before:
  collector=route-views.sg, 2017-07-07 00:00:00 for 5 minutes, max_rows=3000,
  output: <out-base>/updates_smoketest.parquet

- If you pass ANY args, we forward them to 03_collect_updates.py directly.
  (So you can use 03's parameters without remembering the filename.)
"""

import os
import sys
import subprocess


def choose_default_out_base() -> str:
    return "/work/data/parquet" if os.path.isdir("/work") else "data/parquet"


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    target = os.path.join(script_dir, "03_collect_updates.py")

    if len(sys.argv) == 1:
        out_base = choose_default_out_base()
        out_path = os.path.join(out_base, "updates_smoketest.parquet")

        cmd = [
            sys.executable,
            target,
            "--from", "2017-07-07 00:00:00",
            "--minutes", "5",
            "--collectors", "route-views.sg",
            "--record-type", "updates",
            "--max-rows", "3000",
            "--format", "parquet",
            "--out-base", out_base,
            "--out", out_path,
            "--print-head", "5",
        ]
        print("🚀 smoketest:", " ".join(cmd))
        raise SystemExit(subprocess.call(cmd))

    # Forward all args to 03_collect_updates.py
    cmd = [sys.executable, target] + sys.argv[1:]
    raise SystemExit(subprocess.call(cmd))


if __name__ == "__main__":
    main()
