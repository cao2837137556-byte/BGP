#!/usr/bin/env bash
set -euo pipefail

BASE=${BASE:-/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline}
REPO=${REPO:-$BASE/repo}
DATA_ROOT=${DATA_ROOT:-$BASE/data_store}
IMG=${IMG:-$BASE/containers/bgpstream-py-e9a.sif}
PAIR_ID=${1:?usage: n_frontend1c_alignment_ambiguity_preflight.sh PAIR_ID SOURCE_PAIR_ID AMD_JOB INTEL_JOB}
SOURCE_PAIR_ID=${2:?SOURCE_PAIR_ID is required}
AMD_SOURCE_JOB=${3:?AMD_JOB is required}
INTEL_SOURCE_JOB=${4:?INTEL_JOB is required}
PAIR_ROOT=$DATA_ROOT/derived/n_frontend1c_alignment_ambiguity_v01/pair=$PAIR_ID
SOURCE_ROOT=$DATA_ROOT/derived/n_frontend1b_bounded_replay_v01/pair=$SOURCE_PAIR_ID
AMD_DIR=$SOURCE_ROOT/partition=amd/job=$AMD_SOURCE_JOB
INTEL_DIR=$SOURCE_ROOT/partition=intel/job=$INTEL_SOURCE_JOB
JOB_SCRIPT=$REPO/scripts/hpc/n_frontend1c_alignment_ambiguity_audit.slurm
SUBMIT_SCRIPT=$REPO/scripts/hpc/submit_n_frontend1c_alignment_ambiguity_dual.sh
AUDIT_SCRIPT=$REPO/scripts/audit_n_frontend1b_alignment_and_ambiguity.py
TIMING_WRAPPER=$REPO/scripts/hpc/run_with_portable_timing.sh

for value in "$PAIR_ID" "$SOURCE_PAIR_ID" "$AMD_SOURCE_JOB" "$INTEL_SOURCE_JOB"; do
  if [[ ! "$value" =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "Invalid identifier: $value" >&2
    exit 2
  fi
done
if [ -d "$PAIR_ROOT" ] && [ -n "$(find "$PAIR_ROOT" -mindepth 1 -print -quit)" ]; then
  echo "Refusing existing pair outputs: $PAIR_ROOT" >&2
  exit 2
fi

for path in \
  "$AUDIT_SCRIPT" "$JOB_SCRIPT" "$SUBMIT_SCRIPT" "$TIMING_WRAPPER" "$IMG"; do
  test -f "$path"
done
for source_dir in "$AMD_DIR" "$INTEL_DIR"; do
  for path in \
    "$source_dir/n_frontend1b_validation.json" \
    "$source_dir/n_frontend1b_input_manifest.txt" \
    "$source_dir/result/n_frontend1_summary.json" \
    "$source_dir/result/n_frontend1_unique_observations.parquet" \
    "$source_dir/result/n_frontend1_transitions.parquet" \
    "$source_dir/result/n_frontend1_micro_events.parquet"; do
    test -s "$path"
  done
done

bash -n "$JOB_SCRIPT"
bash -n "$SUBMIT_SCRIPT"
bash -n "$TIMING_WRAPPER"
bash -n "$0"
if grep -q '/usr/bin/time' "$JOB_SCRIPT"; then
  echo "Formal job must not depend on optional /usr/bin/time." >&2
  exit 2
fi

module purge
module load apps/apptainer/1.4.5-2
COMMON_BIND=(
  --bind "$REPO":/work
  --bind "$DATA_ROOT":/data_store
  --bind "$BASE/tmp":/hpc_tmp
)
apptainer exec "${COMMON_BIND[@]}" "$IMG" \
  /opt/venv/bin/python -m py_compile \
  /work/scripts/audit_n_frontend1b_alignment_and_ambiguity.py
apptainer exec "${COMMON_BIND[@]}" "$IMG" \
  /opt/venv/bin/python \
  /work/scripts/audit_n_frontend1b_alignment_and_ambiguity.py \
  --self-test

for partition in amd intel; do
  sbatch --test-only -p "$partition" -J "bgp_n_front1c_$partition" \
    --export=ALL,N_FRONTEND1C_PAIR_ID="$PAIR_ID",N_FRONTEND1C_SOURCE_PAIR_ID="$SOURCE_PAIR_ID",N_FRONTEND1C_AMD_SOURCE_JOB="$AMD_SOURCE_JOB",N_FRONTEND1C_INTEL_SOURCE_JOB="$INTEL_SOURCE_JOB" \
    "$JOB_SCRIPT"
done

echo "preflight=passed"
echo "source_pair_id=$SOURCE_PAIR_ID"
echo "amd_source_dir=$AMD_DIR"
echo "intel_source_dir=$INTEL_DIR"
