#!/usr/bin/env bash
#SBATCH -J bgp_r_mem1d_mat
#SBATCH -p intel
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -c 1
#SBATCH --mem=2G
#SBATCH -t 02:00:00
#SBATCH --array=0-19%4
#SBATCH -o /public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/logs/%x_%A_%a.out
#SBATCH -e /public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/logs/%x_%A_%a.err

set -euo pipefail

BASE=${BASE:-/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline}
REPO=${REPO:-$BASE/repo}
DATA_ROOT=${DATA_ROOT:-$BASE/data_store}
IMG=${IMG:-$BASE/containers/bgpstream-py-e9a.sif}
CONFIG=${CONFIG:-configs/r_mem1d_10d_parquet_materialization_v01.json}
PAIR_ID=${R_MEM1D_PAIR_ID:?R_MEM1D_PAIR_ID must be exported by the dual submitter}
PARTITION=${SLURM_JOB_PARTITION:?SLURM_JOB_PARTITION is required}
ARRAY_JOB_ID=${SLURM_ARRAY_JOB_ID:?SLURM_ARRAY_JOB_ID is required}
TASK_ID=${SLURM_ARRAY_TASK_ID:?SLURM_ARRAY_TASK_ID is required}

if [[ ! "$PAIR_ID" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "Invalid R_MEM1D_PAIR_ID: $PAIR_ID" >&2
  exit 2
fi
if (( TASK_ID < 0 || TASK_ID > 19 )); then
  echo "Invalid array task ID: $TASK_ID" >&2
  exit 2
fi

DAY_INDEX=$((TASK_ID / 2))
COLLECTOR_INDEX=$((TASK_ID % 2))
DATE=$(date -u -d "2024-04-07 +${DAY_INDEX} days" +%F)
if (( COLLECTOR_INDEX == 0 )); then
  COLLECTOR=route-views.sg
else
  COLLECTOR=rrc00
fi
SAFE_COLLECTOR=${COLLECTOR//[^A-Za-z0-9._-]/_}
OUTPUT_ROOT=$DATA_ROOT/derived/r_mem1d_10d_parquet_v01
ARRAY_ROOT=$OUTPUT_ROOT/pair=$PAIR_ID/partition=$PARTITION/array_job=$ARRAY_JOB_ID
OUTPUT_DIR=$ARRAY_ROOT/task=$TASK_ID/collector=$SAFE_COLLECTOR/date=$DATE
OUTPUT_REL=${OUTPUT_DIR#"$DATA_ROOT"/}
JOB_TMP=$BASE/tmp/r_mem1d/$PAIR_ID/$PARTITION/$ARRAY_JOB_ID/$TASK_ID
LIVE_LOG=$BASE/logs/r_mem1d_${PAIR_ID}_${PARTITION}_${ARRAY_JOB_ID}_${TASK_ID}.live.log

case "$OUTPUT_DIR" in
  "$DATA_ROOT"/*) ;;
  *) echo "OUTPUT_DIR must be under DATA_ROOT: $OUTPUT_DIR" >&2; exit 2 ;;
esac

mkdir -p "$BASE/logs" "$JOB_TMP/apptainer-tmp" "$JOB_TMP/apptainer-cache"
export APPTAINER_TMPDIR=$JOB_TMP/apptainer-tmp
export APPTAINER_CACHEDIR=$JOB_TMP/apptainer-cache
exec > >(tee -a "$LIVE_LOG") 2>&1

test -f "$REPO/scripts/materialize_r_mem1d_10d_parquet.py"
test -f "$REPO/scripts/run_r_mem1c_local_mrt_parser_smoke.py"
test -f "$REPO/$CONFIG"
test -f "$IMG"
test -f "$DATA_ROOT/manifests/r_mem1b_10d_direct_archive_v01/full/download_manifest.json"
test -f "$DATA_ROOT/manifests/r_mem1b_10d_direct_archive_v01/post_transfer_sha256_audit.json"
test "$(find "$DATA_ROOT/raw_mrt/r_mem1b_10d_direct_archive_v01" -type f \( -name '*.gz' -o -name '*.bz2' \) | wc -l)" -eq 3840
test "$(find "$DATA_ROOT/raw_mrt/r_mem1b_10d_direct_archive_v01" -type f -name '*.part' | wc -l)" -eq 0

R_MEM1D_CODE_COMMIT=${R_MEM1D_CODE_COMMIT:-$(git -C "$REPO" rev-parse HEAD 2>/dev/null || true)}
R_MEM1D_CODE_COMMIT=${R_MEM1D_CODE_COMMIT:-archive-no-git}
R_MEM1D_CODE_FINGERPRINT=$(sha256sum \
  "$REPO/scripts/run_r_mem1c_local_mrt_parser_smoke.py" \
  "$REPO/scripts/materialize_r_mem1d_10d_parquet.py" \
  "$REPO/$CONFIG" \
  "$REPO/scripts/hpc/r_mem1d_10d_parquet_array.slurm" | \
  sha256sum | awk '{print $1}')
export R_MEM1D_CODE_COMMIT R_MEM1D_CODE_FINGERPRINT

echo "pair_id=$PAIR_ID"
echo "partition=$PARTITION"
echo "array_job_id=$ARRAY_JOB_ID"
echo "task_id=$TASK_ID"
echo "collector=$COLLECTOR"
echo "date=$DATE"
echo "node_list=$SLURM_NODELIST"
echo "commit=$R_MEM1D_CODE_COMMIT"
echo "code_fingerprint=$R_MEM1D_CODE_FINGERPRINT"
echo "output_dir=$OUTPUT_DIR"
echo "job_tmp=$JOB_TMP"
echo "resources=cpus:${SLURM_CPUS_PER_TASK:-1},memory:2G,time:02:00:00"

module purge
module load apps/apptainer/1.4.5-2

COMMON_BIND=(
  --bind "$REPO":/work
  --bind "$DATA_ROOT":/data_store
)

echo "heartbeat=static_checks_start"
apptainer exec "${COMMON_BIND[@]}" "$IMG" \
  /opt/venv/bin/python -m py_compile \
  /work/scripts/run_r_mem1c_local_mrt_parser_smoke.py \
  /work/scripts/materialize_r_mem1d_10d_parquet.py
echo "heartbeat=static_checks_complete"

if [[ -f "$OUTPUT_DIR/r_mem1d_task_summary.json" ]]; then
  if apptainer exec "${COMMON_BIND[@]}" "$IMG" /opt/venv/bin/python -c \
    "import json; from pathlib import Path; s=json.loads(Path('/data_store/$OUTPUT_REL/r_mem1d_task_summary.json').read_text()); assert s['materialization_passed'] is True; assert s['execution']['code_fingerprint'] == '$R_MEM1D_CODE_FINGERPRINT'; assert str(s['execution']['slurm_array_job_id']) == '$ARRAY_JOB_ID'; assert str(s['execution']['slurm_array_task_id']) == '$TASK_ID'; print('existing_completed_task=passed')"; then
    exit 0
  fi
fi

echo "heartbeat=collector_day_materialization_start"
timeout --signal=TERM --kill-after=30s 110m \
  apptainer exec "${COMMON_BIND[@]}" "$IMG" \
  /opt/venv/bin/python -u \
  /work/scripts/materialize_r_mem1d_10d_parquet.py \
  --config "/work/$CONFIG" \
  --data-root /data_store \
  --output-dir "/data_store/$OUTPUT_REL" \
  --collector "$COLLECTOR" \
  --date "$DATE" \
  --resume
echo "heartbeat=collector_day_materialization_complete"

apptainer exec "${COMMON_BIND[@]}" "$IMG" /opt/venv/bin/python -c \
  "import json; from pathlib import Path; p=Path('/data_store/$OUTPUT_REL/r_mem1d_task_summary.json'); s=json.loads(p.read_text()); assert s['materialization_passed'] is True; assert s['parsed_file_count'] == s['expected_file_count']; print('task_validation=passed')"

SMALL=$OUTPUT_DIR/r_mem1d_task_small_results.tar.gz
tar -czf "$SMALL" -C "$OUTPUT_DIR" \
  r_mem1d_task_plan.json \
  r_mem1d_task_progress.json \
  r_mem1d_boundary_parser_precheck.json \
  r_mem1d_task_summary.json \
  r_mem1d_schema.json \
  r_mem1d_file_audit.csv \
  r_mem1d_preview.csv \
  r_mem1d_task_report.md

echo "summary=$OUTPUT_DIR/r_mem1d_task_summary.json"
echo "small_results=$SMALL"
