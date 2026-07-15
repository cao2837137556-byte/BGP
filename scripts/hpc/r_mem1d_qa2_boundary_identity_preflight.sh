#!/usr/bin/env bash
set -euo pipefail

BASE=${BASE:-/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline}
REPO=${REPO:-$BASE/repo}
DATA_ROOT=${DATA_ROOT:-$BASE/data_store}
IMG=${IMG:-$BASE/containers/bgpstream-py-e9a.sif}
PAIR_ID=${1:?usage: r_mem1d_qa2_boundary_identity_preflight.sh PAIR_ID MATERIALIZATION_ROOT}
MATERIALIZATION_ROOT=${2:?usage: r_mem1d_qa2_boundary_identity_preflight.sh PAIR_ID MATERIALIZATION_ROOT}
CONFIG=configs/r_mem1d_qa2_boundary_identity_v01.json
JOB_SCRIPT=$REPO/scripts/hpc/r_mem1d_qa2_boundary_identity.slurm
SUBMIT_SCRIPT=$REPO/scripts/hpc/submit_r_mem1d_qa2_boundary_identity_dual.sh
PAIR_ROOT=$DATA_ROOT/derived/r_mem1d_qa2_boundary_identity_v01/pair=$PAIR_ID

if [[ ! "$PAIR_ID" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "Invalid pair ID: $PAIR_ID" >&2
  exit 2
fi
case "$MATERIALIZATION_ROOT" in
  "$DATA_ROOT"/*) ;;
  *) echo "Materialization root must be under $DATA_ROOT" >&2; exit 2 ;;
esac
if [ -d "$PAIR_ROOT" ] && [ -n "$(find "$PAIR_ROOT" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
  echo "Refusing duplicate pair ID with existing outputs: $PAIR_ROOT" >&2
  exit 2
fi

for path in \
  "$REPO/scripts/audit_r_mem1d_boundary_observation_identity.py" \
  "$REPO/scripts/audit_r_mem1d_temporal_alignment.py" \
  "$REPO/scripts/run_r_mem1c_local_mrt_parser_smoke.py" \
  "$REPO/$CONFIG" \
  "$REPO/configs/r_mem1d_10d_parquet_materialization_v01.json" \
  "$JOB_SCRIPT" \
  "$SUBMIT_SCRIPT" \
  "$IMG"; do
  test -f "$path"
done
test -d "$MATERIALIZATION_ROOT"
test "$(find "$MATERIALIZATION_ROOT" -type f -name '*.parquet' | wc -l)" -eq 3840
test "$(find "$MATERIALIZATION_ROOT" -type f -name r_mem1d_task_summary.json | wc -l)" -eq 20
test "$(find "$DATA_ROOT/raw_mrt/r_mem1b_10d_direct_archive_v01" -type f \( -name '*.gz' -o -name '*.bz2' \) | wc -l)" -eq 3840

bash -n "$JOB_SCRIPT"
bash -n "$SUBMIT_SCRIPT"
bash -n "$0"

module purge
module load apps/apptainer/1.4.5-2
COMMON_BIND=(--bind "$REPO":/work --bind "$DATA_ROOT":/data_store)
apptainer exec "${COMMON_BIND[@]}" "$IMG" \
  /opt/venv/bin/python -m py_compile \
  /work/scripts/audit_r_mem1d_boundary_observation_identity.py
apptainer exec "${COMMON_BIND[@]}" "$IMG" \
  /opt/venv/bin/python /work/scripts/audit_r_mem1d_boundary_observation_identity.py \
  --self-test

sbatch --test-only -p amd -J bgp_r_mem1d_qa2_amd \
  --export=ALL,R_MEM1D_QA2_PAIR_ID="$PAIR_ID",R_MEM1D_QA2_MATERIALIZATION_ROOT="$MATERIALIZATION_ROOT" \
  "$JOB_SCRIPT"
sbatch --test-only -p intel -J bgp_r_mem1d_qa2_intel \
  --export=ALL,R_MEM1D_QA2_PAIR_ID="$PAIR_ID",R_MEM1D_QA2_MATERIALIZATION_ROOT="$MATERIALIZATION_ROOT" \
  "$JOB_SCRIPT"
echo "preflight=passed"
