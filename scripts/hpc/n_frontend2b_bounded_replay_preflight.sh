#!/usr/bin/env bash
set -euo pipefail

BASE=${BASE:-/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline}
REPO=${REPO:-$BASE/repo}
DATA_ROOT=${DATA_ROOT:-$BASE/data_store}
IMG=${IMG:-$BASE/containers/bgpstream-py-e9a.sif}
PAIR_ID=${1:?usage: n_frontend2b_bounded_replay_preflight.sh PAIR_ID [SOURCE_ROOT]}
SOURCE_ROOT=${2:-$DATA_ROOT/derived/r_mem1e_10d_peer_aware_v02/pair=r_mem1e_20260721T130846Z/partition=amd/array_job=153044}
REPLAY_DATE=${N_FRONTEND2B_DATE:-2024-04-09}
PAIR_ROOT=$DATA_ROOT/derived/n_frontend2b_bounded_replay_v01/pair=$PAIR_ID
JOB_SCRIPT=$REPO/scripts/hpc/n_frontend2b_bounded_replay.slurm
SUBMIT_SCRIPT=$REPO/scripts/hpc/submit_n_frontend2b_bounded_replay_dual.sh
TIMING_WRAPPER=$REPO/scripts/hpc/run_with_portable_timing.sh

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
  "$REPO/scripts/run_n_frontend2b_controlled_pairs.py" \
  "$REPO/scripts/validate_n_frontend2b_controlled_pairs.py" \
  "$REPO/scripts/build_n_frontend1_causal_transitions.py" \
  "$REPO/scripts/r_mem_canonical_observation_v2.py" \
  "$REPO/configs/n_frontend2b_controlled_pairs_v01.json" \
  "$REPO/configs/n_frontend1_causal_transition_v01.json" \
  "$REPO/configs/r_poison0_paired_benchmark_protocol_v01.json" \
  "$JOB_SCRIPT" \
  "$SUBMIT_SCRIPT" \
  "$TIMING_WRAPPER" \
  "$IMG"; do
  test -f "$path"
done
test -d "$SOURCE_ROOT"

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

bash -n "$JOB_SCRIPT"
bash -n "$SUBMIT_SCRIPT"
bash -n "$TIMING_WRAPPER"
bash -n "$0"
if grep -q '/usr/bin/time' "$JOB_SCRIPT"; then
  echo "Formal job must not depend on optional /usr/bin/time." >&2
  exit 2
fi

SMOKE_DIR=$BASE/tmp/n_frontend2b_preflight/$PAIR_ID
rm -rf "$SMOKE_DIR"
mkdir -p "$SMOKE_DIR"
TIMING_SMOKE=$SMOKE_DIR/portable_timing_smoke.txt
bash "$TIMING_WRAPPER" "$TIMING_SMOKE" /bin/true
grep -qx 'timing_contract=portable_wall_clock_v1' "$TIMING_SMOKE"
grep -qx 'command_exit_code=0' "$TIMING_SMOKE"

module purge
module load apps/apptainer/1.4.5-2
COMMON_BIND=(
  --bind "$REPO":/work
  --bind "$DATA_ROOT":/data_store
  --bind "$BASE/tmp":/hpc_tmp
)
apptainer exec "${COMMON_BIND[@]}" "$IMG" \
  /opt/venv/bin/python -m py_compile \
  /work/scripts/run_n_frontend2b_controlled_pairs.py \
  /work/scripts/validate_n_frontend2b_controlled_pairs.py

SMOKE_REL=${SMOKE_DIR#"$BASE/tmp"/}
apptainer exec "${COMMON_BIND[@]}" "$IMG" \
  /opt/venv/bin/python /work/scripts/run_n_frontend2b_controlled_pairs.py \
  --self-test \
  --config /work/configs/n_frontend2b_controlled_pairs_v01.json \
  --output-dir "/hpc_tmp/$SMOKE_REL/result" \
  --background-sample-rows 1000
apptainer exec "${COMMON_BIND[@]}" "$IMG" \
  /opt/venv/bin/python /work/scripts/validate_n_frontend2b_controlled_pairs.py \
  --output-dir "/hpc_tmp/$SMOKE_REL/result" \
  --expected-pair-count 5 \
  --validation-output "/hpc_tmp/$SMOKE_REL/n_frontend2b_validation.json"

sbatch --test-only -p amd -J bgp_n_front2b_amd \
  --export=ALL,N_FRONTEND2B_PAIR_ID="$PAIR_ID",N_FRONTEND2B_SOURCE_ROOT="$SOURCE_ROOT",N_FRONTEND2B_DATE="$REPLAY_DATE" \
  "$JOB_SCRIPT"
sbatch --test-only -p intel -J bgp_n_front2b_intel \
  --export=ALL,N_FRONTEND2B_PAIR_ID="$PAIR_ID",N_FRONTEND2B_SOURCE_ROOT="$SOURCE_ROOT",N_FRONTEND2B_DATE="$REPLAY_DATE" \
  "$JOB_SCRIPT"

echo "preflight=passed"
echo "date=$REPLAY_DATE"
echo "start_ts=$(date -u -d "$REPLAY_DATE 00:00:00" +%s)"
echo "episode_sec=3600"
echo "input_file_count=${#INPUTS[@]}"
printf 'input=%s\n' "${INPUTS[@]}"
