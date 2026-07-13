#!/usr/bin/env bash
#SBATCH -J bgp_r_mem1c_smoke
#SBATCH -p intel
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -c 4
#SBATCH --mem=16G
#SBATCH -t 01:00:00
#SBATCH -o /public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/logs/%x_%j.out
#SBATCH -e /public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/logs/%x_%j.err

set -euo pipefail

BASE=${BASE:-/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline}
REPO=${REPO:-$BASE/repo}
DATA_ROOT=${DATA_ROOT:-$BASE/data_store}
IMG=${IMG:-$BASE/containers/bgpstream-py-e9a.sif}
CONFIG=${CONFIG:-configs/r_mem1c_local_mrt_parser_smoke_v01.json}
OUTPUT_DIR=${OUTPUT_DIR:-$DATA_ROOT/derived/r_mem1c_local_mrt_parser_smoke_v01}
OVERWRITE=${OVERWRITE:-0}
LIVE_LOG=${BASE}/logs/r_mem1c_parser_smoke_${SLURM_JOB_ID}.live.log

mkdir -p "$BASE/logs" "$BASE/tmp/apptainer-tmp" "$BASE/tmp/apptainer-cache"
export APPTAINER_TMPDIR=$BASE/tmp/apptainer-tmp
export APPTAINER_CACHEDIR=$BASE/tmp/apptainer-cache
exec > >(tee -a "$LIVE_LOG") 2>&1

echo "job_id=$SLURM_JOB_ID"
echo "node_list=$SLURM_NODELIST"
echo "repo=$REPO"
echo "data_root=$DATA_ROOT"
echo "output_dir=$OUTPUT_DIR"
echo "live_log=$LIVE_LOG"

case "$OUTPUT_DIR" in
  "$DATA_ROOT"/*) OUTPUT_REL=${OUTPUT_DIR#"$DATA_ROOT"/} ;;
  *) echo "OUTPUT_DIR must be under DATA_ROOT: $OUTPUT_DIR" >&2; exit 2 ;;
esac

test -f "$DATA_ROOT/manifests/r_mem1b_10d_direct_archive_v01/post_transfer_sha256_audit.json"
test "$(find "$DATA_ROOT/raw_mrt/r_mem1b_10d_direct_archive_v01" -type f \( -name '*.gz' -o -name '*.bz2' \) | wc -l)" -eq 3840
test "$(find "$DATA_ROOT/raw_mrt/r_mem1b_10d_direct_archive_v01" -type f -name '*.part' | wc -l)" -eq 0

module purge
module load apps/apptainer/1.4.5-2

OVERWRITE_FLAG=""
if [ "$OVERWRITE" = "1" ]; then
  OVERWRITE_FLAG="--overwrite"
fi

apptainer exec \
  --bind "$REPO":/work \
  --bind "$DATA_ROOT":/data_store \
  "$IMG" /bin/bash -lc "
set -euo pipefail
cd /work
PY=/opt/venv/bin/python
$PY -m py_compile scripts/run_r_mem1c_local_mrt_parser_smoke.py
$PY - <<'PY'
import pyarrow
import pybgpstream
print('pyarrow_version=' + pyarrow.__version__)
print('pybgpstream_import=passed')
PY
$PY -u scripts/run_r_mem1c_local_mrt_parser_smoke.py \
  --config '$CONFIG' \
  --data-root /data_store \
  --output-dir "/data_store/$OUTPUT_REL" \
  $OVERWRITE_FLAG
"

SMALL="$OUTPUT_DIR/r_mem1c_small_results.tar.gz"
tar -czf "$SMALL" -C "$OUTPUT_DIR" \
  r_mem1c_parse_plan.json \
  r_mem1c_summary.json \
  r_mem1c_schema.json \
  r_mem1c_file_audit.csv \
  r_mem1c_preview.csv \
  r_mem1c_report.md

echo "summary=$OUTPUT_DIR/r_mem1c_summary.json"
echo "small_results=$SMALL"
