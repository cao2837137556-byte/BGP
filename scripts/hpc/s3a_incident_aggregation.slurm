#!/usr/bin/env bash
#SBATCH -J bgp_s3a_inc
#SBATCH -p amd
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -c 8
#SBATCH --mem=128G
#SBATCH -t 04:00:00
#SBATCH -o /public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/logs/%x_%j.out
#SBATCH -e /public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/logs/%x_%j.err

set -euo pipefail

BASE=${BASE:-/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline}
REPO=${REPO:-$BASE/repo}
IMG=${IMG:-$BASE/containers/bgpstream-py-e9a.sif}
RUN_ID=${RUN_ID:-s2a_expanded_v01_pilot_6h_april16}
OUTPUT_DIR=${OUTPUT_DIR:-outputs/s3a_incident_aggregation_v01}
MICRO_WINDOW_SEC=${MICRO_WINDOW_SEC:-900}
MACRO_WINDOW_SEC=${MACRO_WINDOW_SEC:-7200}
BUNDLE_NAME=${BUNDLE_NAME:-s3a_incident_aggregation_bundle}
LIVE_LOG=${BASE}/logs/s3a_incident_aggregation_${SLURM_JOB_ID}.live.log

mkdir -p "$BASE/logs" "$BASE/tmp/apptainer-tmp" "$BASE/tmp/apptainer-cache"
export APPTAINER_TMPDIR=$BASE/tmp/apptainer-tmp
export APPTAINER_CACHEDIR=$BASE/tmp/apptainer-cache

exec > >(tee -a "$LIVE_LOG") 2>&1

echo "job_id=$SLURM_JOB_ID"
echo "node_list=$SLURM_NODELIST"
echo "live_log=$LIVE_LOG"
echo "run_id=$RUN_ID"
echo "output_dir=$OUTPUT_DIR"
echo "micro_window_sec=$MICRO_WINDOW_SEC"
echo "macro_window_sec=$MACRO_WINDOW_SEC"

module purge
module load apps/apptainer/1.4.5-2

apptainer exec --bind "$REPO":/work "$IMG" /bin/bash -lc "
set -euo pipefail
cd /work
/opt/venv/bin/python -u scripts/run_s3a_incident_aggregation.py \
  --run-id '$RUN_ID' \
  --output-dir '$OUTPUT_DIR' \
  --micro-window-sec '$MICRO_WINDOW_SEC' \
  --macro-window-sec '$MACRO_WINDOW_SEC' \
  --overwrite true
/opt/venv/bin/python -u scripts/package_experiment_bundle.py \
  --bundle-name '$BUNDLE_NAME' \
  --path '$OUTPUT_DIR' \
  --path 'data/runs/$RUN_ID/incidents' \
  --run-id '$RUN_ID'
"

echo "bundle=$REPO/outputs/bundles/${BUNDLE_NAME}.zip"
