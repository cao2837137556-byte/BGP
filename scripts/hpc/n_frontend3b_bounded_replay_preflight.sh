#!/usr/bin/env bash
set -euo pipefail

BASE=${BASE:-/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline}
REPO=${REPO:-$BASE/repo}
DATA_ROOT=${DATA_ROOT:-$BASE/data_store}
IMG=${IMG:-$BASE/containers/bgpstream-py-e9a.sif}
PAIR_ID=${1:?usage: n_frontend3b_bounded_replay_preflight.sh PAIR_ID AMD_2B_ROOT INTEL_2B_ROOT}
AMD_SOURCE=${2:?AMD N-FRONTEND-2B source root is required}
INTEL_SOURCE=${3:?Intel N-FRONTEND-2B source root is required}
JOB_SCRIPT=$REPO/scripts/hpc/n_frontend3b_bounded_replay.slurm
SUBMIT_SCRIPT=$REPO/scripts/hpc/submit_n_frontend3b_bounded_replay_dual.sh

[[ "$PAIR_ID" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "Invalid pair ID" >&2; exit 2; }
for SOURCE in "$AMD_SOURCE" "$INTEL_SOURCE"; do
  case "$SOURCE" in "$DATA_ROOT"/*) ;; *) echo "Invalid source root: $SOURCE" >&2; exit 2 ;; esac
  test -f "$SOURCE/n_frontend2b_summary.json"
  test -f "$SOURCE/n_frontend2b_registry_freeze.json"
  test -f "$SOURCE/n_frontend2b_phase_survival_lineage.csv"
  test -f "$SOURCE/n_frontend2b_attack_transition_semantic_delta.csv"
  mapfile -t VARIANTS < <(find "$SOURCE/evaluation_only" -mindepth 2 -maxdepth 2 -type d | sort)
  test "${#VARIANTS[@]}" -eq 10
  for VARIANT in "${VARIANTS[@]}"; do
    for REQUIRED in \
      frontend/n_frontend1_transitions.parquet \
      frontend/n_frontend1_micro_events.parquet \
      frontend/n_frontend1_non_route_observations.parquet \
      frontend/n_frontend1_summary.json \
      phase_survival_lineage.csv \
      past_only_route_exposure.csv; do
      test -f "$VARIANT/$REQUIRED"
    done
  done
done
test ! -e "$DATA_ROOT/derived/n_frontend3b_bounded_replay_v01/pair=$PAIR_ID"
for FILE in \
  "$REPO/configs/n_frontend3b_background_suppression_v01.json" \
  "$REPO/scripts/run_n_frontend3b_background_suppression.py" \
  "$REPO/scripts/validate_n_frontend3b_background_suppression.py" \
  "$REPO/N_FRONTEND3B_PACKAGE_MANIFEST.json" \
  "$JOB_SCRIPT" "$SUBMIT_SCRIPT" "$IMG"; do test -f "$FILE"; done

bash -n "$JOB_SCRIPT"
bash -n "$SUBMIT_SCRIPT"
bash -n "$0"
if grep -q '/usr/bin/time' "$JOB_SCRIPT"; then
  echo "Formal job must not depend on optional /usr/bin/time." >&2
  exit 2
fi

module purge
module load apps/apptainer/1.4.5-2
COMMON_BIND=(--bind "$REPO":/work --bind "$DATA_ROOT":/data_store --bind "$BASE/tmp":/hpc_tmp)
apptainer exec "${COMMON_BIND[@]}" "$IMG" /opt/venv/bin/python -m py_compile \
  /work/scripts/run_n_frontend3b_background_suppression.py \
  /work/scripts/validate_n_frontend3b_background_suppression.py \
  /work/scripts/validate_n_frontend3b_dual_parity.py
apptainer exec "${COMMON_BIND[@]}" "$IMG" /opt/venv/bin/python \
  /work/scripts/run_n_frontend3b_background_suppression.py --self-test \
  --config /work/configs/n_frontend3b_background_suppression_v01.json
apptainer exec "${COMMON_BIND[@]}" "$IMG" /opt/venv/bin/python \
  /work/scripts/validate_n_frontend3b_background_suppression.py --self-test \
  --config /work/configs/n_frontend3b_background_suppression_v01.json
apptainer exec "${COMMON_BIND[@]}" "$IMG" /opt/venv/bin/python \
  /work/scripts/validate_n_frontend3b_dual_parity.py --self-test

for SPEC in "amd:$AMD_SOURCE" "intel:$INTEL_SOURCE"; do
  PARTITION=${SPEC%%:*}
  SOURCE=${SPEC#*:}
  sbatch --test-only -p "$PARTITION" -J "bgp_n_front3b_$PARTITION" \
    --export=ALL,N_FRONTEND3B_PAIR_ID="$PAIR_ID",N_FRONTEND3B_SOURCE_2B_ROOT="$SOURCE" \
    "$JOB_SCRIPT"
done
echo "preflight=passed"
echo "pair_id=$PAIR_ID"
echo "amd_source=$AMD_SOURCE"
echo "intel_source=$INTEL_SOURCE"
