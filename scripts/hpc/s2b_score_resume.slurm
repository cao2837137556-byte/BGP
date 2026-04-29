#!/usr/bin/env bash
#SBATCH -J bgp_s2b_score
#SBATCH -p amd
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -c 16
#SBATCH --mem=128G
#SBATCH -t 12:00:00
#SBATCH -o /public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/logs/%x_%j.out
#SBATCH -e /public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/logs/%x_%j.err

set -euo pipefail

BASE=${BASE:-/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline}
REPO=${REPO:-$BASE/repo}
IMG=${IMG:-$BASE/containers/bgpstream-py-e9a.sif}
RUN_ID=${RUN_ID:-s2a_expanded_v01_pilot_6h_april16}
OUTPUT_DIR=${OUTPUT_DIR:-outputs/s2b_score_optimization_v01}
SCORE_BATCH_SIZE=${SCORE_BATCH_SIZE:-250000}
DOWNSTREAM_BATCH_SIZE=${DOWNSTREAM_BATCH_SIZE:-100000}
SCORE_RESUME=${SCORE_RESUME:-true}
OVERWRITE=${OVERWRITE:-true}
BUNDLE_NAME=${BUNDLE_NAME:-s2b_score_optimization_bundle}
LIVE_LOG=${BASE}/logs/s2b_score_resume_${SLURM_JOB_ID}.live.log

mkdir -p "$BASE/logs" "$BASE/tmp/apptainer-tmp" "$BASE/tmp/apptainer-cache"
export APPTAINER_TMPDIR=$BASE/tmp/apptainer-tmp
export APPTAINER_CACHEDIR=$BASE/tmp/apptainer-cache

exec > >(tee -a "$LIVE_LOG") 2>&1

echo "job_id=$SLURM_JOB_ID"
echo "node_list=$SLURM_NODELIST"
echo "live_log=$LIVE_LOG"
echo "run_id=$RUN_ID"
echo "output_dir=$OUTPUT_DIR"
echo "score_resume=$SCORE_RESUME"

module purge
module load apps/apptainer/1.4.5-2

apptainer exec --bind "$REPO":/work "$IMG" /bin/bash -lc "
set -euo pipefail
cd /work
/opt/venv/bin/python -u scripts/run_s2b_score_resume.py \
  --run-id '$RUN_ID' \
  --output-dir '$OUTPUT_DIR' \
  --score-batch-size '$SCORE_BATCH_SIZE' \
  --downstream-batch-size '$DOWNSTREAM_BATCH_SIZE' \
  --score-resume '$SCORE_RESUME' \
  --overwrite '$OVERWRITE' \
  --bundle-name '$BUNDLE_NAME'
"

echo "bundle=$REPO/outputs/bundles/${BUNDLE_NAME}.zip"
