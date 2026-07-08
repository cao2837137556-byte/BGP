#!/usr/bin/env bash
#SBATCH -J bgp_r_mem1a_src
#SBATCH -p intel
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -c 4
#SBATCH --mem=24G
#SBATCH -t 08:00:00
#SBATCH --array=0-19%4
#SBATCH -o /public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/logs/%x_%A_%a.out
#SBATCH -e /public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/logs/%x_%A_%a.err

set -euo pipefail

BASE=${BASE:-/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline}
REPO=${REPO:-$BASE/repo}
IMG=${IMG:-$BASE/containers/bgpstream-py-e9a.sif}
CONFIG=${CONFIG:-configs/r_mem1a_10d_path_memory_v01.json}
SOURCE_ROOT=${SOURCE_ROOT:-data/runs}
OUTPUT_RUN_ID=${OUTPUT_RUN_ID:-r_mem1a_10d_sources_v01}
PLAN_ONLY=${PLAN_ONLY:-0}
OVERWRITE=${OVERWRITE:-0}
LIVE_LOG=${BASE}/logs/r_mem1a_collect_${SLURM_ARRAY_JOB_ID}_${SLURM_ARRAY_TASK_ID}.live.log

mkdir -p "$BASE/logs" "$BASE/tmp/apptainer-tmp" "$BASE/tmp/apptainer-cache"
export APPTAINER_TMPDIR=$BASE/tmp/apptainer-tmp
export APPTAINER_CACHEDIR=$BASE/tmp/apptainer-cache
exec > >(tee -a "$LIVE_LOG") 2>&1

echo "job_id=$SLURM_JOB_ID"
echo "array_job_id=$SLURM_ARRAY_JOB_ID"
echo "array_task_id=$SLURM_ARRAY_TASK_ID"
echo "node_list=$SLURM_NODELIST"
echo "repo=$REPO"
echo "config=$CONFIG"
echo "source_root=$SOURCE_ROOT"
echo "output_run_id=$OUTPUT_RUN_ID"
echo "live_log=$LIVE_LOG"

module purge
module load apps/apptainer/1.4.5-2

PLAN_FLAG=""
if [ "$PLAN_ONLY" = "1" ]; then
  PLAN_FLAG="--plan-only"
fi
OVERWRITE_FLAG=""
if [ "$OVERWRITE" = "1" ]; then
  OVERWRITE_FLAG="--overwrite"
fi

apptainer exec --bind "$REPO":/work "$IMG" /bin/bash -lc "
set -euo pipefail
cd /work
PY=/opt/venv/bin/python
PLAN_ARG='$PLAN_FLAG'
OVERWRITE_ARG='$OVERWRITE_FLAG'
\$PY -m py_compile scripts/collect_r_mem1a_bgpstream_sources.py
\$PY -u scripts/collect_r_mem1a_bgpstream_sources.py \
  --config '$CONFIG' \
  --source-root '$SOURCE_ROOT' \
  --output-run-id '$OUTPUT_RUN_ID' \
  --array-index '$SLURM_ARRAY_TASK_ID' \
  \$PLAN_ARG \$OVERWRITE_ARG
"

echo "collection_summary_dir=$REPO/$SOURCE_ROOT/$OUTPUT_RUN_ID/_collection_summaries"
