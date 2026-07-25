#!/usr/bin/env bash
set -euo pipefail

BASE=${BASE:-/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline}
REPO=${REPO:-$BASE/repo}
DATA_ROOT=${DATA_ROOT:-$BASE/data_store}
IMG=${IMG:-$BASE/containers/bgpstream-py-e9a.sif}
PAIR_ID=${1:?usage: n_frontend1b_bounded_replay_preflight.sh PAIR_ID [SOURCE_ROOT]}
SOURCE_ROOT=${2:-$DATA_ROOT/derived/r_mem1e_10d_peer_aware_v02/pair=r_mem1e_20260721T130846Z/partition=amd/array_job=153044}
REPLAY_DATE=${N_FRONTEND1B_DATE:-2024-04-09}
WINDOW_MINUTES=${N_FRONTEND1B_WINDOW_MINUTES:-5}
PAIR_ROOT=$DATA_ROOT/derived/n_frontend1b_bounded_replay_v01/pair=$PAIR_ID
JOB_SCRIPT=$REPO/scripts/hpc/n_frontend1b_bounded_replay.slurm
SUBMIT_SCRIPT=$REPO/scripts/hpc/submit_n_frontend1b_bounded_replay_dual.sh

if [[ ! "$PAIR_ID" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "Invalid pair ID: $PAIR_ID" >&2
  exit 2
fi
case "$SOURCE_ROOT" in
  "$DATA_ROOT"/*) ;;
  *) echo "Source root must be under $DATA_ROOT" >&2; exit 2 ;;
esac
if [ -d "$PAIR_ROOT" ] && [ -n "$(find "$PAIR_ROOT" -mindepth 1 -print -quit)" ]; then
  echo "Refusing existing pair outputs: $PAIR_ROOT" >&2
  exit 2
fi

for path in \
  "$REPO/scripts/build_n_frontend1_causal_transitions.py" \
  "$REPO/scripts/validate_n_frontend1b_bounded_replay.py" \
  "$REPO/scripts/r_mem_canonical_observation_v2.py" \
  "$REPO/configs/n_frontend1_causal_transition_v01.json" \
  "$JOB_SCRIPT" \
  "$SUBMIT_SCRIPT" \
  "$IMG"; do
  test -f "$path"
done
test -d "$SOURCE_ROOT"

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

START_TS=$(date -u -d "$REPLAY_DATE 00:00:00" +%s)
END_TS=$((START_TS + WINDOW_MINUTES * 60))
SMOKE_DIR=$BASE/tmp/n_frontend1b_preflight/$PAIR_ID
rm -rf "$SMOKE_DIR"
mkdir -p "$SMOKE_DIR"

bash -n "$JOB_SCRIPT"
bash -n "$SUBMIT_SCRIPT"
bash -n "$0"

module purge
module load apps/apptainer/1.4.5-2
COMMON_BIND=(--bind "$REPO":/work --bind "$DATA_ROOT":/data_store --bind "$BASE/tmp":/hpc_tmp)

apptainer exec "${COMMON_BIND[@]}" "$IMG" \
  /opt/venv/bin/python -m py_compile \
  /work/scripts/build_n_frontend1_causal_transitions.py \
  /work/scripts/validate_n_frontend1b_bounded_replay.py
apptainer exec "${COMMON_BIND[@]}" "$IMG" \
  /opt/venv/bin/python /work/scripts/build_n_frontend1_causal_transitions.py \
  --self-test

declare -a CONTAINER_INPUT_ARGS=()
for INPUT in "${INPUTS[@]}"; do
  INPUT_REL=${INPUT#"$DATA_ROOT"/}
  CONTAINER_INPUT_ARGS+=(--input "/data_store/$INPUT_REL")
done
SMOKE_REL=${SMOKE_DIR#"$BASE/tmp"/}
apptainer exec "${COMMON_BIND[@]}" "$IMG" \
  /opt/venv/bin/python -u /work/scripts/build_n_frontend1_causal_transitions.py \
  "${CONTAINER_INPUT_ARGS[@]}" \
  --config /work/configs/n_frontend1_causal_transition_v01.json \
  --output-dir "/hpc_tmp/$SMOKE_REL/result" \
  --start-ts "$START_TS" \
  --end-ts "$END_TS" \
  --max-rows 0 \
  --max-rows-per-collector 2000 \
  --require-collector route-views.sg \
  --require-collector rrc00

apptainer exec "${COMMON_BIND[@]}" "$IMG" \
  /opt/venv/bin/python /work/scripts/validate_n_frontend1b_bounded_replay.py \
  --output-dir "/hpc_tmp/$SMOKE_REL/result" \
  --expected-collector route-views.sg \
  --expected-collector rrc00 \
  --expected-input-file-count 2 \
  --expected-start-ts "$START_TS" \
  --expected-end-ts "$END_TS" \
  --expect-per-collector-cap \
  --output "/hpc_tmp/$SMOKE_REL/result/n_frontend1b_validation.json"

sbatch --test-only -p amd -J bgp_n_front1b_amd \
  --export=ALL,N_FRONTEND1B_PAIR_ID="$PAIR_ID",N_FRONTEND1B_SOURCE_ROOT="$SOURCE_ROOT",N_FRONTEND1B_DATE="$REPLAY_DATE",N_FRONTEND1B_WINDOW_MINUTES="$WINDOW_MINUTES" \
  "$JOB_SCRIPT"
sbatch --test-only -p intel -J bgp_n_front1b_intel \
  --export=ALL,N_FRONTEND1B_PAIR_ID="$PAIR_ID",N_FRONTEND1B_SOURCE_ROOT="$SOURCE_ROOT",N_FRONTEND1B_DATE="$REPLAY_DATE",N_FRONTEND1B_WINDOW_MINUTES="$WINDOW_MINUTES" \
  "$JOB_SCRIPT"

echo "preflight=passed"
echo "date=$REPLAY_DATE"
echo "start_ts=$START_TS"
echo "end_ts=$END_TS"
printf 'input=%s\n' "${INPUTS[@]}"
