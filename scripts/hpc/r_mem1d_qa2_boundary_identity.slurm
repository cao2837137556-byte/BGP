#!/usr/bin/env bash
#SBATCH -J bgp_r_mem1d_qa2
#SBATCH -p intel
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -c 4
#SBATCH --mem=6G
#SBATCH -t 04:00:00
#SBATCH -o /public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/logs/%x_%j.out
#SBATCH -e /public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/logs/%x_%j.err

set -euo pipefail

BASE=${BASE:-/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline}
REPO=${REPO:-$BASE/repo}
DATA_ROOT=${DATA_ROOT:-$BASE/data_store}
IMG=${IMG:-$BASE/containers/bgpstream-py-e9a.sif}
CONFIG=${CONFIG:-configs/r_mem1d_qa2_boundary_identity_v01.json}
PAIR_ID=${R_MEM1D_QA2_PAIR_ID:?R_MEM1D_QA2_PAIR_ID is required}
MATERIALIZATION_ROOT=${R_MEM1D_QA2_MATERIALIZATION_ROOT:?R_MEM1D_QA2_MATERIALIZATION_ROOT is required}
JOB_ID=${SLURM_JOB_ID:?SLURM_JOB_ID is required}
PARTITION=${SLURM_JOB_PARTITION:?SLURM_JOB_PARTITION is required}

for value in "$PAIR_ID" "$PARTITION" "$JOB_ID"; do
  if [[ ! "$value" =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "Invalid identifier: $value" >&2
    exit 2
  fi
done
case "$MATERIALIZATION_ROOT" in
  "$DATA_ROOT"/*) ;;
  *) echo "Materialization root must be under $DATA_ROOT" >&2; exit 2 ;;
esac

OUTPUT_DIR=$DATA_ROOT/derived/r_mem1d_qa2_boundary_identity_v01/pair=$PAIR_ID/partition=$PARTITION/job=$JOB_ID
OUTPUT_REL=${OUTPUT_DIR#"$DATA_ROOT"/}
MATERIALIZATION_REL=${MATERIALIZATION_ROOT#"$DATA_ROOT"/}
JOB_TMP=$BASE/tmp/r_mem1d_qa2/$PAIR_ID/$PARTITION/$JOB_ID
LIVE_LOG=$BASE/logs/r_mem1d_qa2_${PAIR_ID}_${PARTITION}_${JOB_ID}.live.log

test ! -e "$OUTPUT_DIR"
mkdir -p "$BASE/logs" "$JOB_TMP/apptainer-tmp" "$JOB_TMP/apptainer-cache"
export APPTAINER_TMPDIR=$JOB_TMP/apptainer-tmp
export APPTAINER_CACHEDIR=$JOB_TMP/apptainer-cache
exec > >(tee -a "$LIVE_LOG") 2>&1

echo "phase=R-MEM-1D-QA2"
echo "pair_id=$PAIR_ID"
echo "job_id=$JOB_ID"
echo "partition=$PARTITION"
echo "materialization_root=$MATERIALIZATION_ROOT"
echo "output_dir=$OUTPUT_DIR"
echo "resources=cpus:${SLURM_CPUS_PER_TASK:-4},memory:6G,time:04:00:00"

module purge
module load apps/apptainer/1.4.5-2
COMMON_BIND=(
  --bind "$REPO":/work
  --bind "$DATA_ROOT":/data_store
  --bind "$BASE/tmp":/hpc_tmp
)

apptainer exec "${COMMON_BIND[@]}" "$IMG" \
  /opt/venv/bin/python -m py_compile \
  /work/scripts/audit_r_mem1d_boundary_observation_identity.py
apptainer exec "${COMMON_BIND[@]}" "$IMG" \
  /opt/venv/bin/python /work/scripts/audit_r_mem1d_boundary_observation_identity.py \
  --self-test
apptainer exec "${COMMON_BIND[@]}" "$IMG" \
  /opt/venv/bin/python -u /work/scripts/audit_r_mem1d_boundary_observation_identity.py \
  --config "/work/$CONFIG" \
  --materialization-root "/data_store/$MATERIALIZATION_REL" \
  --data-root /data_store \
  --output-dir "/data_store/$OUTPUT_REL" \
  --workers "${SLURM_CPUS_PER_TASK:-4}"

test -f "$OUTPUT_DIR/r_mem1d_qa2_summary.json"
test -f "$OUTPUT_DIR/r_mem1d_qa2_candidate_identity_audit.csv"
test -f "$OUTPUT_DIR/r_mem1d_qa2_raw_match_audit.csv"
test -f "$OUTPUT_DIR/r_mem1d_qa2_raw_file_audit.csv"
test -f "$OUTPUT_DIR/r_mem1d_qa2_report.md"

tar -czf "$OUTPUT_DIR/r_mem1d_qa2_small_results.tar.gz" \
  -C "$OUTPUT_DIR" \
  r_mem1d_qa2_summary.json \
  r_mem1d_qa2_candidate_identity_audit.csv \
  r_mem1d_qa2_raw_match_audit.csv \
  r_mem1d_qa2_raw_file_audit.csv \
  r_mem1d_qa2_report.md
echo "summary=$OUTPUT_DIR/r_mem1d_qa2_summary.json"
echo "small_results=$OUTPUT_DIR/r_mem1d_qa2_small_results.tar.gz"
