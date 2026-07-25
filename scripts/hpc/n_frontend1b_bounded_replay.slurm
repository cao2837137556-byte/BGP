#!/usr/bin/env bash
#SBATCH -J bgp_n_front1b
#SBATCH -p intel
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -c 2
#SBATCH --mem=32G
#SBATCH -t 02:00:00
#SBATCH -o /public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/logs/%x_%j.out
#SBATCH -e /public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/logs/%x_%j.err

set -euo pipefail

BASE=${BASE:-/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline}
REPO=${REPO:-$BASE/repo}
DATA_ROOT=${DATA_ROOT:-$BASE/data_store}
IMG=${IMG:-$BASE/containers/bgpstream-py-e9a.sif}
PAIR_ID=${N_FRONTEND1B_PAIR_ID:?N_FRONTEND1B_PAIR_ID is required}
SOURCE_ROOT=${N_FRONTEND1B_SOURCE_ROOT:?N_FRONTEND1B_SOURCE_ROOT is required}
REPLAY_DATE=${N_FRONTEND1B_DATE:-2024-04-09}
WINDOW_MINUTES=${N_FRONTEND1B_WINDOW_MINUTES:-5}
JOB_ID=${SLURM_JOB_ID:?SLURM_JOB_ID is required}
PARTITION=${SLURM_JOB_PARTITION:?SLURM_JOB_PARTITION is required}

for value in "$PAIR_ID" "$PARTITION" "$JOB_ID"; do
  if [[ ! "$value" =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "Invalid identifier: $value" >&2
    exit 2
  fi
done
case "$SOURCE_ROOT" in
  "$DATA_ROOT"/*) ;;
  *) echo "Source root must be under $DATA_ROOT" >&2; exit 2 ;;
esac

OUTPUT_DIR=$DATA_ROOT/derived/n_frontend1b_bounded_replay_v01/pair=$PAIR_ID/partition=$PARTITION/job=$JOB_ID
OUTPUT_REL=${OUTPUT_DIR#"$DATA_ROOT"/}
JOB_TMP=$BASE/tmp/n_frontend1b/$PAIR_ID/$PARTITION/$JOB_ID
LIVE_LOG=$BASE/logs/n_frontend1b_${PAIR_ID}_${PARTITION}_${JOB_ID}.live.log
TIME_FILE=$OUTPUT_DIR/n_frontend1b_time_verbose.txt
START_TS=$(date -u -d "$REPLAY_DATE 00:00:00" +%s)
END_TS=$((START_TS + WINDOW_MINUTES * 60))

test ! -e "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR" "$JOB_TMP/apptainer-tmp" "$JOB_TMP/apptainer-cache" "$BASE/logs"
export APPTAINER_TMPDIR=$JOB_TMP/apptainer-tmp
export APPTAINER_CACHEDIR=$JOB_TMP/apptainer-cache
exec > >(tee -a "$LIVE_LOG") 2>&1

echo "phase=N-FRONTEND-1B"
echo "pair_id=$PAIR_ID"
echo "job_id=$JOB_ID"
echo "partition=$PARTITION"
echo "source_root=$SOURCE_ROOT"
echo "date=$REPLAY_DATE"
echo "window_utc=$REPLAY_DATE 00:00:00/$WINDOW_MINUTES minutes"
echo "output_dir=$OUTPUT_DIR"
echo "resources=cpus:${SLURM_CPUS_PER_TASK:-2},memory:32G,time:02:00:00"

declare -a INPUTS=()
for COLLECTOR in route-views.sg rrc00; do
  mapfile -t MATCHES < <(
    find "$SOURCE_ROOT" -type f \
      -path "*/parsed/collector=$COLLECTOR/date=$REPLAY_DATE/updates__00-00-00__*.parquet" \
      | sort
  )
  if [ "${#MATCHES[@]}" -ne 1 ]; then
    echo "Expected one midnight input for $COLLECTOR/$REPLAY_DATE; found ${#MATCHES[@]}" >&2
    printf '%s\n' "${MATCHES[@]}" >&2
    exit 2
  fi
  INPUTS+=("${MATCHES[0]}")
done
printf '%s\n' "${INPUTS[@]}" > "$OUTPUT_DIR/n_frontend1b_input_manifest.txt"

module purge
module load apps/apptainer/1.4.5-2
COMMON_BIND=(
  --bind "$REPO":/work
  --bind "$DATA_ROOT":/data_store
  --bind "$BASE/tmp":/hpc_tmp
)
declare -a CONTAINER_INPUT_ARGS=()
for INPUT in "${INPUTS[@]}"; do
  INPUT_REL=${INPUT#"$DATA_ROOT"/}
  CONTAINER_INPUT_ARGS+=(--input "/data_store/$INPUT_REL")
done

/usr/bin/time -v -o "$TIME_FILE" \
  apptainer exec "${COMMON_BIND[@]}" "$IMG" \
  /opt/venv/bin/python -u /work/scripts/build_n_frontend1_causal_transitions.py \
  "${CONTAINER_INPUT_ARGS[@]}" \
  --config /work/configs/n_frontend1_causal_transition_v01.json \
  --output-dir "/data_store/$OUTPUT_REL/result" \
  --start-ts "$START_TS" \
  --end-ts "$END_TS" \
  --max-rows 0 \
  --require-collector route-views.sg \
  --require-collector rrc00

apptainer exec "${COMMON_BIND[@]}" "$IMG" \
  /opt/venv/bin/python /work/scripts/validate_n_frontend1b_bounded_replay.py \
  --output-dir "/data_store/$OUTPUT_REL/result" \
  --expected-collector route-views.sg \
  --expected-collector rrc00 \
  --expected-input-file-count 2 \
  --expected-start-ts "$START_TS" \
  --expected-end-ts "$END_TS" \
  --output "/data_store/$OUTPUT_REL/n_frontend1b_validation.json"

tar -czf "$OUTPUT_DIR/n_frontend1b_small_results.tar.gz" \
  -C "$OUTPUT_DIR" \
  n_frontend1b_input_manifest.txt \
  n_frontend1b_time_verbose.txt \
  n_frontend1b_validation.json \
  -C "$OUTPUT_DIR/result" \
  n_frontend1_summary.json \
  n_frontend1_report.md \
  n_frontend1_transition_counts.csv \
  n_frontend1_exact_dedup_audit.csv

echo "validation=$OUTPUT_DIR/n_frontend1b_validation.json"
echo "small_results=$OUTPUT_DIR/n_frontend1b_small_results.tar.gz"
