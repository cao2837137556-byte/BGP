#!/usr/bin/env bash
#SBATCH -J bgp_r_mem1c_measure
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
CONFIG=${CONFIG:-configs/r_mem1c_complete_file_measure_v01.json}
PAIR_ID=${R_MEM1C_PAIR_ID:?R_MEM1C_PAIR_ID must be exported by the dual submitter}

if [[ ! "$PAIR_ID" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "Invalid R_MEM1C_PAIR_ID: $PAIR_ID" >&2
  exit 2
fi

PARTITION=${SLURM_JOB_PARTITION:?SLURM_JOB_PARTITION is required}
JOB_ID=${SLURM_JOB_ID:?SLURM_JOB_ID is required}
OUTPUT_ROOT=${OUTPUT_ROOT:-$DATA_ROOT/derived/r_mem1c_complete_file_measure_v01}
OUTPUT_DIR=$OUTPUT_ROOT/pair=$PAIR_ID/partition=$PARTITION/job=$JOB_ID
OUTPUT_REL=${OUTPUT_DIR#"$DATA_ROOT"/}
JOB_TMP=$BASE/tmp/r_mem1c_measure/$PAIR_ID/$PARTITION/$JOB_ID
LIVE_LOG=$BASE/logs/r_mem1c_complete_file_measure_${PAIR_ID}_${PARTITION}_${JOB_ID}.live.log

case "$OUTPUT_DIR" in
  "$DATA_ROOT"/*) ;;
  *) echo "OUTPUT_DIR must be under DATA_ROOT: $OUTPUT_DIR" >&2; exit 2 ;;
esac

test ! -e "$OUTPUT_DIR"
mkdir -p "$BASE/logs" "$JOB_TMP/apptainer-tmp" "$JOB_TMP/apptainer-cache"
export APPTAINER_TMPDIR=$JOB_TMP/apptainer-tmp
export APPTAINER_CACHEDIR=$JOB_TMP/apptainer-cache
export R_MEM1C_CODE_COMMIT
R_MEM1C_CODE_COMMIT=$(git -C "$REPO" rev-parse HEAD)
exec > >(tee -a "$LIVE_LOG") 2>&1

echo "pair_id=$PAIR_ID"
echo "job_id=$JOB_ID"
echo "partition=$PARTITION"
echo "node_list=$SLURM_NODELIST"
echo "commit=$R_MEM1C_CODE_COMMIT"
echo "output_dir=$OUTPUT_DIR"
echo "job_tmp=$JOB_TMP"
echo "resources=cpus:${SLURM_CPUS_PER_TASK:-1},memory:2G,time:00:10:00"

test -f "$REPO/scripts/run_r_mem1c_local_mrt_parser_smoke.py"
test -f "$REPO/$CONFIG"
test -f "$IMG"
test -f "$DATA_ROOT/manifests/r_mem1b_10d_direct_archive_v01/post_transfer_sha256_audit.json"
test -f "$DATA_ROOT/derived/r_mem1c_singlefile_liveness_v01/r_mem1c_liveness_summary.json"
test "$(find "$DATA_ROOT/raw_mrt/r_mem1b_10d_direct_archive_v01" -type f \( -name '*.gz' -o -name '*.bz2' \) | wc -l)" -eq 3840
test "$(find "$DATA_ROOT/raw_mrt/r_mem1b_10d_direct_archive_v01" -type f -name '*.part' | wc -l)" -eq 0

module purge
module load apps/apptainer/1.4.5-2

COMMON_BIND=(
  --bind "$REPO":/work
  --bind "$DATA_ROOT":/data_store
)

echo "heartbeat=job_static_checks_start"
apptainer exec "${COMMON_BIND[@]}" "$IMG" \
  /opt/venv/bin/python -m py_compile \
  /work/scripts/run_r_mem1c_local_mrt_parser_smoke.py
apptainer exec "${COMMON_BIND[@]}" "$IMG" \
  /opt/venv/bin/python -c \
  'import json; from pathlib import Path; p=Path("/data_store/derived/r_mem1c_singlefile_liveness_v01/r_mem1c_liveness_summary.json"); s=json.loads(p.read_text()); assert s["pybgpstream_liveness_passed"] is True; assert s["source_integrity_passed"] is True; print("liveness_prerequisite=passed")'
echo "heartbeat=job_static_checks_complete"

echo "heartbeat=complete_file_measure_start"
timeout --signal=TERM --kill-after=30s 8m \
  apptainer exec "${COMMON_BIND[@]}" "$IMG" \
  /opt/venv/bin/python -u \
  /work/scripts/run_r_mem1c_local_mrt_parser_smoke.py \
  --config "/work/$CONFIG" \
  --data-root /data_store \
  --output-dir "/data_store/$OUTPUT_REL"
echo "heartbeat=complete_file_measure_complete"

apptainer exec "${COMMON_BIND[@]}" "$IMG" \
  /opt/venv/bin/python -c \
  "import json; from pathlib import Path; p=Path('/data_store/$OUTPUT_REL/r_mem1c_summary.json'); s=json.loads(p.read_text()); assert s['parser_smoke_passed'] is True; assert s['full_parse_per_selected_file'] is True; assert s['parsed_file_count'] == 2; print('measurement_validation=passed')"

SMALL=$OUTPUT_DIR/r_mem1c_complete_file_measure_small_results.tar.gz
tar -czf "$SMALL" -C "$OUTPUT_DIR" \
  r_mem1c_parse_plan.json \
  r_mem1c_progress.json \
  r_mem1c_summary.json \
  r_mem1c_schema.json \
  r_mem1c_file_audit.csv \
  r_mem1c_preview.csv \
  r_mem1c_report.md

echo "summary=$OUTPUT_DIR/r_mem1c_summary.json"
echo "small_results=$SMALL"
