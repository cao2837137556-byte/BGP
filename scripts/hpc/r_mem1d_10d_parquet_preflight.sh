#!/usr/bin/env bash
set -euo pipefail

BASE=${BASE:-/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline}
REPO=${REPO:-$BASE/repo}
DATA_ROOT=${DATA_ROOT:-$BASE/data_store}
IMG=${IMG:-$BASE/containers/bgpstream-py-e9a.sif}
PAIR_ID=${1:?usage: r_mem1d_10d_parquet_preflight.sh PAIR_ID}
CONFIG=configs/r_mem1d_10d_parquet_materialization_v01.json
ARRAY_SCRIPT=$REPO/scripts/hpc/r_mem1d_10d_parquet_array.slurm
VALIDATOR_SCRIPT=$REPO/scripts/hpc/r_mem1d_validate_10d_parquet.slurm
SUBMIT_SCRIPT=$REPO/scripts/hpc/submit_r_mem1d_10d_parquet_dual.sh
PAIR_ROOT=$DATA_ROOT/derived/r_mem1d_10d_parquet_v01/pair=$PAIR_ID

if [[ ! "$PAIR_ID" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "Invalid pair ID: $PAIR_ID" >&2
  exit 2
fi
if [ -d "$PAIR_ROOT" ] && [ -n "$(find "$PAIR_ROOT" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
  echo "Refusing duplicate pair ID with existing outputs: $PAIR_ROOT" >&2
  exit 2
fi

for path in \
  "$REPO/scripts/run_r_mem1c_local_mrt_parser_smoke.py" \
  "$REPO/scripts/materialize_r_mem1d_10d_parquet.py" \
  "$REPO/scripts/validate_r_mem1d_10d_parquet.py" \
  "$REPO/$CONFIG" \
  "$ARRAY_SCRIPT" \
  "$VALIDATOR_SCRIPT" \
  "$SUBMIT_SCRIPT" \
  "$IMG" \
  "$DATA_ROOT/manifests/r_mem1b_10d_direct_archive_v01/full/download_manifest.json" \
  "$DATA_ROOT/manifests/r_mem1b_10d_direct_archive_v01/post_transfer_sha256_audit.json"; do
  test -f "$path"
done

RAW_COUNT=$(find "$DATA_ROOT/raw_mrt/r_mem1b_10d_direct_archive_v01" -type f \( -name '*.gz' -o -name '*.bz2' \) | wc -l)
PART_COUNT=$(find "$DATA_ROOT/raw_mrt/r_mem1b_10d_direct_archive_v01" -type f -name '*.part' | wc -l)
echo "raw_archive_count=$RAW_COUNT"
echo "partial_file_count=$PART_COUNT"
test "$RAW_COUNT" -eq 3840
test "$PART_COUNT" -eq 0

bash -n "$ARRAY_SCRIPT"
bash -n "$VALIDATOR_SCRIPT"
bash -n "$SUBMIT_SCRIPT"
bash -n "$0"

module purge
module load apps/apptainer/1.4.5-2
COMMON_BIND=(--bind "$REPO":/work --bind "$DATA_ROOT":/data_store)
apptainer exec "${COMMON_BIND[@]}" "$IMG" /opt/venv/bin/python -m py_compile \
  /work/scripts/run_r_mem1c_local_mrt_parser_smoke.py \
  /work/scripts/materialize_r_mem1d_10d_parquet.py \
  /work/scripts/validate_r_mem1d_10d_parquet.py

apptainer exec "${COMMON_BIND[@]}" "$IMG" /opt/venv/bin/python -c \
  'import json
from collections import Counter
from pathlib import Path
p=Path("/data_store/manifests/r_mem1b_10d_direct_archive_v01/full/download_manifest.json")
rows=json.loads(p.read_text())
assert len(rows)==3840
assert len({r["local_relative_path"] for r in rows})==3840
counts=Counter((r["collector"], r["archive_timestamp_utc"][:10]) for r in rows)
assert len(counts)==20
assert all(n==(96 if c=="route-views.sg" else 288) for (c,_),n in counts.items())
print("manifest_matrix=passed")'

apptainer exec "${COMMON_BIND[@]}" "$IMG" /opt/venv/bin/python -c \
  'import json
from pathlib import Path
roots=list(Path("/data_store/derived/r_mem1c_complete_file_measure_v01").glob("pair=*/partition=*/job=*/r_mem1c_summary.json"))
passed=[]
for path in roots:
    try:
        s=json.loads(path.read_text())
        if s.get("parser_smoke_passed") is True and s.get("parsed_file_count")==2:
            passed.append(str(path))
    except Exception:
        pass
assert passed, "no passed R-MEM-1C complete-file measurement found"
print("complete_file_measurement=passed", passed[-1])'

PREFLIGHT_TMP=$(mktemp -d "$BASE/tmp/r_mem1d_preflight.XXXXXX")
case "$PREFLIGHT_TMP" in "$BASE/tmp/r_mem1d_preflight."*) ;; *) exit 2 ;; esac
trap 'rm -rf "$PREFLIGHT_TMP"' EXIT
PREFLIGHT_REL=${PREFLIGHT_TMP#"$BASE"/}
apptainer exec "${COMMON_BIND[@]}" --bind "$BASE/tmp":/hpc_tmp "$IMG" \
  /opt/venv/bin/python /work/scripts/materialize_r_mem1d_10d_parquet.py \
  --config "/work/$CONFIG" \
  --data-root /data_store \
  --output-dir "/hpc_tmp/${PREFLIGHT_REL#tmp/}/plan" \
  --collector route-views.sg \
  --date 2024-04-07 \
  --plan-only >/dev/null
test -f "$PREFLIGHT_TMP/plan/r_mem1d_task_plan.json"

sbatch --test-only -p amd -J bgp_r_mem1d_amd --array=0-19%4 \
  --export=ALL,R_MEM1D_PAIR_ID="$PAIR_ID" "$ARRAY_SCRIPT"
sbatch --test-only -p intel -J bgp_r_mem1d_intel --array=0-19%4 \
  --export=ALL,R_MEM1D_PAIR_ID="$PAIR_ID" "$ARRAY_SCRIPT"
sbatch --test-only -p amd -J bgp_r_mem1d_val_amd \
  --export=ALL,R_MEM1D_PAIR_ID="$PAIR_ID",R_MEM1D_SOURCE_PARTITION=amd,R_MEM1D_ARRAY_JOB_ID=999999 \
  "$VALIDATOR_SCRIPT"
sbatch --test-only -p intel -J bgp_r_mem1d_val_intel \
  --export=ALL,R_MEM1D_PAIR_ID="$PAIR_ID",R_MEM1D_SOURCE_PARTITION=intel,R_MEM1D_ARRAY_JOB_ID=999999 \
  "$VALIDATOR_SCRIPT"
echo "preflight=passed"
