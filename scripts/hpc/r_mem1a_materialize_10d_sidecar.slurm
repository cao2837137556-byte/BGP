#!/usr/bin/env bash
#SBATCH -J bgp_r_mem1a_mat
#SBATCH -p intel
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -c 16
#SBATCH --mem=96G
#SBATCH -t 06:00:00
#SBATCH -o /public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/logs/%x_%j.out
#SBATCH -e /public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/logs/%x_%j.err

set -euo pipefail

BASE=${BASE:-/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline}
REPO=${REPO:-$BASE/repo}
IMG=${IMG:-$BASE/containers/bgpstream-py-e9a.sif}
CONFIG=${CONFIG:-configs/r_mem1a_10d_path_memory_v01.json}
SOURCE_ROOT=${SOURCE_ROOT:-data/runs}
OUTPUT_DIR=${OUTPUT_DIR:-outputs/r_mem_1a_10d_path_memory_sidecar_v01}
ALLOW_PARTIAL=${ALLOW_PARTIAL:-0}
MAX_FILES=${MAX_FILES:-0}
OVERWRITE=${OVERWRITE:-0}
LIVE_LOG=${BASE}/logs/r_mem1a_materialize_${SLURM_JOB_ID}.live.log

mkdir -p "$BASE/logs" "$BASE/tmp/apptainer-tmp" "$BASE/tmp/apptainer-cache"
export APPTAINER_TMPDIR=$BASE/tmp/apptainer-tmp
export APPTAINER_CACHEDIR=$BASE/tmp/apptainer-cache
exec > >(tee -a "$LIVE_LOG") 2>&1

echo "job_id=$SLURM_JOB_ID"
echo "node_list=$SLURM_NODELIST"
echo "repo=$REPO"
echo "config=$CONFIG"
echo "source_root=$SOURCE_ROOT"
echo "output_dir=$OUTPUT_DIR"
echo "allow_partial=$ALLOW_PARTIAL"
echo "max_files=$MAX_FILES"
echo "live_log=$LIVE_LOG"

module purge
module load apps/apptainer/1.4.5-2

PARTIAL_FLAG=""
if [ "$ALLOW_PARTIAL" = "1" ]; then
  PARTIAL_FLAG="--allow-partial-history"
fi
OVERWRITE_FLAG=""
if [ "$OVERWRITE" = "1" ]; then
  OVERWRITE_FLAG="--overwrite"
fi
MAX_FILES_FLAG=""
if [ "$MAX_FILES" != "0" ]; then
  MAX_FILES_FLAG="--max-files $MAX_FILES"
fi

apptainer exec --bind "$REPO":/work "$IMG" /bin/bash -lc "
set -euo pipefail
cd /work
PY=/opt/venv/bin/python
PARTIAL_ARG='$PARTIAL_FLAG'
MAX_FILES_ARG='$MAX_FILES_FLAG'
OVERWRITE_ARG='$OVERWRITE_FLAG'
\$PY -m py_compile scripts/materialize_r_mem1a_path_memory_sidecar.py
\$PY -u scripts/materialize_r_mem1a_path_memory_sidecar.py \
  --config '$CONFIG' \
  --source-root '$SOURCE_ROOT' \
  --output-dir '$OUTPUT_DIR' \
  \$PARTIAL_ARG \$MAX_FILES_ARG \$OVERWRITE_ARG

tar -czf \$OUTPUT_DIR/r_mem1a_small_results.tar.gz \
  \$OUTPUT_DIR/r_mem1a_summary.json \
  \$OUTPUT_DIR/r_mem1a_source_coverage_audit.csv \
  \$OUTPUT_DIR/r_mem1a_selected_file_processing_audit.csv \
  \$OUTPUT_DIR/r_mem1a_maturity_bucket_audit.csv \
  \$OUTPUT_DIR/path_memory_sidecar_preview.csv \
  \$OUTPUT_DIR/r_mem1a_report.md
"

echo "summary=$REPO/$OUTPUT_DIR/r_mem1a_summary.json"
echo "small_results=$REPO/$OUTPUT_DIR/r_mem1a_small_results.tar.gz"
