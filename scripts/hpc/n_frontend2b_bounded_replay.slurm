#!/usr/bin/env bash
#SBATCH -J bgp_n_front2b
#SBATCH -p intel
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -c 4
#SBATCH --mem=64G
#SBATCH -t 04:00:00
#SBATCH -o /public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/logs/%x_%j.out
#SBATCH -e /public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/logs/%x_%j.err

set -euo pipefail

BASE=${BASE:-/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline}
REPO=${REPO:-$BASE/repo}
DATA_ROOT=${DATA_ROOT:-$BASE/data_store}
IMG=${IMG:-$BASE/containers/bgpstream-py-e9a.sif}
PAIR_ID=${N_FRONTEND2B_PAIR_ID:?N_FRONTEND2B_PAIR_ID is required}
SOURCE_ROOT=${N_FRONTEND2B_SOURCE_ROOT:?N_FRONTEND2B_SOURCE_ROOT is required}
REPLAY_DATE=${N_FRONTEND2B_DATE:-2024-04-09}
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

OUTPUT_DIR=$DATA_ROOT/derived/n_frontend2b_bounded_replay_v01/pair=$PAIR_ID/partition=$PARTITION/job=$JOB_ID
OUTPUT_REL=${OUTPUT_DIR#"$DATA_ROOT"/}
RESULT_DIR=$OUTPUT_DIR/result
JOB_TMP=$BASE/tmp/n_frontend2b/$PAIR_ID/$PARTITION/$JOB_ID
LIVE_LOG=$BASE/logs/n_frontend2b_${PAIR_ID}_${PARTITION}_${JOB_ID}.live.log
TIME_FILE=$OUTPUT_DIR/n_frontend2b_time_verbose.txt
TIMING_WRAPPER=$REPO/scripts/hpc/run_with_portable_timing.sh
START_TS=$(date -u -d "$REPLAY_DATE 00:00:00" +%s)

test ! -e "$OUTPUT_DIR"
test -f "$TIMING_WRAPPER"
mkdir -p "$OUTPUT_DIR" "$JOB_TMP/apptainer-tmp" "$JOB_TMP/apptainer-cache" "$BASE/logs"
export APPTAINER_TMPDIR=$JOB_TMP/apptainer-tmp
export APPTAINER_CACHEDIR=$JOB_TMP/apptainer-cache
exec > >(tee -a "$LIVE_LOG") 2>&1

echo "phase=N-FRONTEND-2B"
echo "pair_id=$PAIR_ID"
echo "job_id=$JOB_ID"
echo "partition=$PARTITION"
echo "source_root=$SOURCE_ROOT"
echo "date=$REPLAY_DATE"
echo "episode=60_minutes"
echo "output_dir=$OUTPUT_DIR"
echo "resources=cpus:${SLURM_CPUS_PER_TASK:-4},memory:64G,time:04:00:00"

declare -a INPUTS=()
for COLLECTOR in route-views.sg rrc00; do
  mapfile -t MATCHES < <(
    find "$SOURCE_ROOT" -type f \
      -path "*/parsed/collector=$COLLECTOR/date=$REPLAY_DATE/updates__00-*.parquet" \
      | sort
  )
  if [ "${#MATCHES[@]}" -lt 1 ]; then
    echo "No 00:xx parquet inputs for $COLLECTOR/$REPLAY_DATE" >&2
    exit 2
  fi
  INPUTS+=("${MATCHES[@]}")
done
printf '%s\n' "${INPUTS[@]}" > "$OUTPUT_DIR/n_frontend2b_input_manifest.txt"

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

bash "$TIMING_WRAPPER" "$TIME_FILE" \
  apptainer exec "${COMMON_BIND[@]}" "$IMG" \
  /opt/venv/bin/python -u /work/scripts/run_n_frontend2b_controlled_pairs.py \
  "${CONTAINER_INPUT_ARGS[@]}" \
  --config /work/configs/n_frontend2b_controlled_pairs_v01.json \
  --output-dir "/data_store/$OUTPUT_REL/result" \
  --start-ts "$START_TS" \
  --max-rows 0 \
  --background-sample-rows 100000

apptainer exec "${COMMON_BIND[@]}" "$IMG" \
  /opt/venv/bin/python /work/scripts/validate_n_frontend2b_controlled_pairs.py \
  --output-dir "/data_store/$OUTPUT_REL/result" \
  --expected-pair-count 5 \
  --validation-output "/data_store/$OUTPUT_REL/n_frontend2b_validation.json"

tar -czf "$OUTPUT_DIR/n_frontend2b_small_results.tar.gz" \
  -C "$OUTPUT_DIR" \
  n_frontend2b_input_manifest.txt \
  n_frontend2b_time_verbose.txt \
  n_frontend2b_validation.json \
  -C "$RESULT_DIR" \
  n_frontend2b_summary.json \
  n_frontend2b_report.md \
  n_frontend2b_registry_freeze.json \
  n_frontend2b_background_input_manifest.json \
  n_frontend2b_background_cadence_audit.json \
  n_frontend2b_observer_registry.json \
  n_frontend2b_synthetic_observation_manifest.csv \
  n_frontend2b_truth_provenance_sidecar.csv \
  n_frontend2b_identity_duplicate_audit.csv \
  n_frontend2b_pair_fairness_audit.csv \
  n_frontend2b_phase_survival_lineage.csv \
  n_frontend2b_past_only_route_exposure.csv \
  n_frontend2b_attack_transition_semantic_delta.csv \
  n_frontend2b_visibility_contract_audit.csv \
  n_frontend2b_ambiguity_intersection_audit.csv \
  n_frontend2b_drop_localization.csv

echo "validation=$OUTPUT_DIR/n_frontend2b_validation.json"
echo "small_results=$OUTPUT_DIR/n_frontend2b_small_results.tar.gz"
