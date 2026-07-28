#!/usr/bin/env bash
#SBATCH -J bgp_n_front1c
#SBATCH -p intel
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -c 2
#SBATCH --mem=16G
#SBATCH -t 00:30:00
#SBATCH -o /public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/logs/%x_%j.out
#SBATCH -e /public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/logs/%x_%j.err

set -euo pipefail

BASE=${BASE:-/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline}
REPO=${REPO:-$BASE/repo}
DATA_ROOT=${DATA_ROOT:-$BASE/data_store}
IMG=${IMG:-$BASE/containers/bgpstream-py-e9a.sif}
PAIR_ID=${N_FRONTEND1C_PAIR_ID:?N_FRONTEND1C_PAIR_ID is required}
SOURCE_PAIR_ID=${N_FRONTEND1C_SOURCE_PAIR_ID:?N_FRONTEND1C_SOURCE_PAIR_ID is required}
AMD_SOURCE_JOB=${N_FRONTEND1C_AMD_SOURCE_JOB:?N_FRONTEND1C_AMD_SOURCE_JOB is required}
INTEL_SOURCE_JOB=${N_FRONTEND1C_INTEL_SOURCE_JOB:?N_FRONTEND1C_INTEL_SOURCE_JOB is required}
JOB_ID=${SLURM_JOB_ID:?SLURM_JOB_ID is required}
PARTITION=${SLURM_JOB_PARTITION:?SLURM_JOB_PARTITION is required}

for value in \
  "$PAIR_ID" "$SOURCE_PAIR_ID" "$AMD_SOURCE_JOB" "$INTEL_SOURCE_JOB" \
  "$JOB_ID" "$PARTITION"; do
  if [[ ! "$value" =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "Invalid identifier: $value" >&2
    exit 2
  fi
done

SOURCE_ROOT=$DATA_ROOT/derived/n_frontend1b_bounded_replay_v01/pair=$SOURCE_PAIR_ID
AMD_DIR=$SOURCE_ROOT/partition=amd/job=$AMD_SOURCE_JOB
INTEL_DIR=$SOURCE_ROOT/partition=intel/job=$INTEL_SOURCE_JOB
OUTPUT_DIR=$DATA_ROOT/derived/n_frontend1c_alignment_ambiguity_v01/pair=$PAIR_ID/partition=$PARTITION/job=$JOB_ID
OUTPUT_REL=${OUTPUT_DIR#"$DATA_ROOT"/}
JOB_TMP=$BASE/tmp/n_frontend1c/$PAIR_ID/$PARTITION/$JOB_ID
LIVE_LOG=$BASE/logs/n_frontend1c_${PAIR_ID}_${PARTITION}_${JOB_ID}.live.log
TIME_FILE=$OUTPUT_DIR/n_frontend1c_time.txt
TIMING_WRAPPER=$REPO/scripts/hpc/run_with_portable_timing.sh

test ! -e "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR" "$JOB_TMP/apptainer-tmp" "$JOB_TMP/apptainer-cache" "$BASE/logs"
export APPTAINER_TMPDIR=$JOB_TMP/apptainer-tmp
export APPTAINER_CACHEDIR=$JOB_TMP/apptainer-cache
exec > >(tee -a "$LIVE_LOG") 2>&1

echo "phase=N-FRONTEND-1C"
echo "pair_id=$PAIR_ID"
echo "job_id=$JOB_ID"
echo "partition=$PARTITION"
echo "source_pair_id=$SOURCE_PAIR_ID"
echo "amd_source_job=$AMD_SOURCE_JOB"
echo "intel_source_job=$INTEL_SOURCE_JOB"
echo "output_dir=$OUTPUT_DIR"
echo "resources=cpus:${SLURM_CPUS_PER_TASK:-2},memory:16G,time:00:30:00"

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
test -f "$TIMING_WRAPPER"

module purge
module load apps/apptainer/1.4.5-2
COMMON_BIND=(
  --bind "$REPO":/work
  --bind "$DATA_ROOT":/data_store
  --bind "$BASE/tmp":/hpc_tmp
)
AMD_REL=${AMD_DIR#"$DATA_ROOT"/}
INTEL_REL=${INTEL_DIR#"$DATA_ROOT"/}

bash "$TIMING_WRAPPER" "$TIME_FILE" \
  apptainer exec "${COMMON_BIND[@]}" "$IMG" \
  /opt/venv/bin/python -u \
  /work/scripts/audit_n_frontend1b_alignment_and_ambiguity.py \
  --amd-output-dir "/data_store/$AMD_REL" \
  --intel-output-dir "/data_store/$INTEL_REL" \
  --output-dir "/data_store/$OUTPUT_REL/result"

apptainer exec "${COMMON_BIND[@]}" "$IMG" \
  /opt/venv/bin/python - \
  "/data_store/$OUTPUT_REL/result/n_frontend1c_summary.json" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
summary = json.loads(path.read_text(encoding="utf-8"))
if not summary.get("audit_passed"):
    raise SystemExit("N-FRONTEND-1C audit gate failed")
print("audit_gate=passed")
PY

tar -czf "$OUTPUT_DIR/n_frontend1c_small_results.tar.gz" \
  -C "$OUTPUT_DIR" \
  n_frontend1c_time.txt \
  -C "$OUTPUT_DIR/result" \
  n_frontend1c_summary.json \
  n_frontend1c_ambiguity_profile.csv \
  n_frontend1c_ambiguity_examples.csv \
  n_frontend1c_report.md

echo "summary=$OUTPUT_DIR/result/n_frontend1c_summary.json"
echo "small_results=$OUTPUT_DIR/n_frontend1c_small_results.tar.gz"
