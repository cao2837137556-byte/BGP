#!/usr/bin/env bash
#SBATCH -J bgp_r_mem1c_live
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
CONFIG=${CONFIG:-configs/r_mem1c_local_mrt_parser_smoke_v01.json}
OUTPUT_DIR=${OUTPUT_DIR:-$DATA_ROOT/derived/r_mem1c_singlefile_liveness_v01}
MAX_ELEMENTS=${MAX_ELEMENTS:-100}
TIMEOUT_SEC=${TIMEOUT_SEC:-60}
OVERWRITE=${OVERWRITE:-0}
LIVE_LOG=${BASE}/logs/r_mem1c_singlefile_liveness_${SLURM_JOB_ID}.live.log

mkdir -p "$BASE/logs" "$BASE/tmp/apptainer-tmp" "$BASE/tmp/apptainer-cache"
export APPTAINER_TMPDIR=$BASE/tmp/apptainer-tmp
export APPTAINER_CACHEDIR=$BASE/tmp/apptainer-cache
exec > >(tee -a "$LIVE_LOG") 2>&1

echo "job_id=$SLURM_JOB_ID"
echo "node_list=$SLURM_NODELIST"
echo "repo=$REPO"
echo "data_root=$DATA_ROOT"
echo "output_dir=$OUTPUT_DIR"
echo "resources=cpus:${SLURM_CPUS_PER_TASK:-1},memory:2G,time:00:10:00"
echo "max_elements=$MAX_ELEMENTS"
echo "timeout_sec=$TIMEOUT_SEC"

case "$OUTPUT_DIR" in
  "$DATA_ROOT"/*) OUTPUT_REL=${OUTPUT_DIR#"$DATA_ROOT"/} ;;
  *) echo "OUTPUT_DIR must be under DATA_ROOT: $OUTPUT_DIR" >&2; exit 2 ;;
esac

test -f "$REPO/scripts/probe_r_mem1c_singlefile_liveness.py"
test -f "$REPO/$CONFIG"
test -f "$IMG"
test -f "$DATA_ROOT/manifests/r_mem1b_10d_direct_archive_v01/post_transfer_sha256_audit.json"
test "$(find "$DATA_ROOT/raw_mrt/r_mem1b_10d_direct_archive_v01" -type f \( -name '*.gz' -o -name '*.bz2' \) | wc -l)" -eq 3840
test "$(find "$DATA_ROOT/raw_mrt/r_mem1b_10d_direct_archive_v01" -type f -name '*.part' | wc -l)" -eq 0

module purge
module load apps/apptainer/1.4.5-2

OVERWRITE_ARGS=()
if [ "$OVERWRITE" = "1" ]; then
  OVERWRITE_ARGS+=(--overwrite)
fi

COMMON_BIND=(
  --bind "$REPO":/work
  --bind "$DATA_ROOT":/data_store
)

echo "heartbeat=container_static_checks_start"
apptainer exec "${COMMON_BIND[@]}" "$IMG" \
  /opt/venv/bin/python -m py_compile \
  /work/scripts/probe_r_mem1c_singlefile_liveness.py
apptainer exec "${COMMON_BIND[@]}" "$IMG" \
  /opt/venv/bin/python \
  /work/scripts/probe_r_mem1c_singlefile_liveness.py --self-test
apptainer exec "${COMMON_BIND[@]}" "$IMG" /bin/bash -lc \
  'set -euo pipefail; /opt/venv/bin/python -c "import pybgpstream; print(\"pybgpstream_import=passed\")"; command -v bgpreader || true'
echo "heartbeat=container_static_checks_complete"

echo "heartbeat=real_input_probe_start"
apptainer exec "${COMMON_BIND[@]}" "$IMG" \
  /opt/venv/bin/python -u \
  /work/scripts/probe_r_mem1c_singlefile_liveness.py \
  --config "/work/$CONFIG" \
  --data-root /data_store \
  --output-dir "/data_store/$OUTPUT_REL" \
  --max-elements "$MAX_ELEMENTS" \
  --timeout-sec "$TIMEOUT_SEC" \
  "${OVERWRITE_ARGS[@]}"
echo "heartbeat=real_input_probe_complete"

SMALL="$OUTPUT_DIR/r_mem1c_liveness_small_results.tar.gz"
tar -czf "$SMALL" -C "$OUTPUT_DIR" \
  r_mem1c_liveness_plan.json \
  r_mem1c_liveness_summary.json \
  r_mem1c_liveness_probe_audit.csv \
  r_mem1c_liveness_source_audit.csv \
  r_mem1c_liveness_report.md

echo "summary=$OUTPUT_DIR/r_mem1c_liveness_summary.json"
echo "small_results=$SMALL"
