#!/usr/bin/env bash
#SBATCH -J bgp_r_mem1d_val
#SBATCH -p intel
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -c 1
#SBATCH --mem=2G
#SBATCH -t 00:10:00
#SBATCH -o /public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/logs/%x_%j.out
#SBATCH -e /public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/logs/%x_%j.err

set -euo pipefail

BASE=${BASE:-/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline}
REPO=${REPO:-$BASE/repo}
DATA_ROOT=${DATA_ROOT:-$BASE/data_store}
IMG=${IMG:-$BASE/containers/bgpstream-py-e9a.sif}
CONFIG=${CONFIG:-configs/r_mem1d_10d_parquet_materialization_v01.json}
PAIR_ID=${R_MEM1D_PAIR_ID:?R_MEM1D_PAIR_ID is required}
SOURCE_PARTITION=${R_MEM1D_SOURCE_PARTITION:?R_MEM1D_SOURCE_PARTITION is required}
ARRAY_JOB_ID=${R_MEM1D_ARRAY_JOB_ID:?R_MEM1D_ARRAY_JOB_ID is required}
JOB_ID=${SLURM_JOB_ID:?SLURM_JOB_ID is required}
PARTITION=${SLURM_JOB_PARTITION:?SLURM_JOB_PARTITION is required}

for value in "$PAIR_ID" "$SOURCE_PARTITION" "$ARRAY_JOB_ID"; do
  if [[ ! "$value" =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "Invalid identifier: $value" >&2
    exit 2
  fi
done

MATERIALIZATION_ROOT=$DATA_ROOT/derived/r_mem1d_10d_parquet_v01/pair=$PAIR_ID/partition=$SOURCE_PARTITION/array_job=$ARRAY_JOB_ID
VALIDATION_DIR=$DATA_ROOT/derived/r_mem1d_10d_parquet_v01/pair=$PAIR_ID/validation_partition=$PARTITION/validation_job=$JOB_ID/source_partition=$SOURCE_PARTITION/source_array_job=$ARRAY_JOB_ID
MATERIALIZATION_REL=${MATERIALIZATION_ROOT#"$DATA_ROOT"/}
VALIDATION_REL=${VALIDATION_DIR#"$DATA_ROOT"/}
JOB_TMP=$BASE/tmp/r_mem1d_validation/$PAIR_ID/$PARTITION/$JOB_ID
LIVE_LOG=$BASE/logs/r_mem1d_validation_${PAIR_ID}_${PARTITION}_${JOB_ID}.live.log

test ! -e "$VALIDATION_DIR"
mkdir -p "$BASE/logs" "$JOB_TMP/apptainer-tmp" "$JOB_TMP/apptainer-cache"
export APPTAINER_TMPDIR=$JOB_TMP/apptainer-tmp
export APPTAINER_CACHEDIR=$JOB_TMP/apptainer-cache
exec > >(tee -a "$LIVE_LOG") 2>&1

test -f "$REPO/scripts/validate_r_mem1d_10d_parquet.py"
test -f "$REPO/$CONFIG"
test -f "$IMG"
mkdir -p "$MATERIALIZATION_ROOT"

echo "pair_id=$PAIR_ID"
echo "validation_job_id=$JOB_ID"
echo "validation_partition=$PARTITION"
echo "source_partition=$SOURCE_PARTITION"
echo "source_array_job_id=$ARRAY_JOB_ID"
echo "materialization_root=$MATERIALIZATION_ROOT"
echo "validation_dir=$VALIDATION_DIR"
echo "resources=cpus:${SLURM_CPUS_PER_TASK:-1},memory:2G,time:00:10:00"

module purge
module load apps/apptainer/1.4.5-2
COMMON_BIND=(--bind "$REPO":/work --bind "$DATA_ROOT":/data_store)

apptainer exec "${COMMON_BIND[@]}" "$IMG" \
  /opt/venv/bin/python -m py_compile /work/scripts/validate_r_mem1d_10d_parquet.py
apptainer exec "${COMMON_BIND[@]}" "$IMG" \
  /opt/venv/bin/python -u /work/scripts/validate_r_mem1d_10d_parquet.py \
  --config "/work/$CONFIG" \
  --materialization-root "/data_store/$MATERIALIZATION_REL" \
  --output-dir "/data_store/$VALIDATION_REL" \
  --expected-array-job-id "$ARRAY_JOB_ID"

SMALL=$VALIDATION_DIR/r_mem1d_validation_small_results.tar.gz
tar -czf "$SMALL" -C "$VALIDATION_DIR" \
  r_mem1d_validation_summary.json \
  r_mem1d_task_validation_audit.csv \
  r_mem1d_validation_report.md
echo "validation_summary=$VALIDATION_DIR/r_mem1d_validation_summary.json"
echo "small_results=$SMALL"
