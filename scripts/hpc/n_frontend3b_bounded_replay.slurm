#!/usr/bin/env bash
#SBATCH -J bgp_n_front3b
#SBATCH -p intel
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -c 2
#SBATCH --mem=16G
#SBATCH -t 02:00:00
#SBATCH -o /public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/logs/%x_%j.out
#SBATCH -e /public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/logs/%x_%j.err

set -euo pipefail

BASE=${BASE:-/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline}
REPO=${REPO:-$BASE/repo}
DATA_ROOT=${DATA_ROOT:-$BASE/data_store}
IMG=${IMG:-$BASE/containers/bgpstream-py-e9a.sif}
PAIR_ID=${N_FRONTEND3B_PAIR_ID:?N_FRONTEND3B_PAIR_ID is required}
SOURCE_2B_ROOT=${N_FRONTEND3B_SOURCE_2B_ROOT:?N_FRONTEND3B_SOURCE_2B_ROOT is required}
JOB_ID=${SLURM_JOB_ID:?SLURM_JOB_ID is required}
PARTITION=${SLURM_JOB_PARTITION:?SLURM_JOB_PARTITION is required}

for value in "$PAIR_ID" "$PARTITION" "$JOB_ID"; do
  [[ "$value" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "Invalid identifier: $value" >&2; exit 2; }
done
case "$SOURCE_2B_ROOT" in
  "$DATA_ROOT"/*) ;;
  *) echo "2B source must be under $DATA_ROOT" >&2; exit 2 ;;
esac

OUTPUT_DIR=$DATA_ROOT/derived/n_frontend3b_bounded_replay_v01/pair=$PAIR_ID/partition=$PARTITION/job=$JOB_ID
OUTPUT_REL=${OUTPUT_DIR#"$DATA_ROOT"/}
SOURCE_REL=${SOURCE_2B_ROOT#"$DATA_ROOT"/}
JOB_TMP=$BASE/tmp/n_frontend3b/$PAIR_ID/$PARTITION/$JOB_ID
LIVE_LOG=$BASE/logs/n_frontend3b_${PAIR_ID}_${PARTITION}_${JOB_ID}.live.log
PACKAGE_MANIFEST=$REPO/N_FRONTEND3B_PACKAGE_MANIFEST.json

test ! -e "$OUTPUT_DIR"
test -f "$PACKAGE_MANIFEST"
mkdir -p "$OUTPUT_DIR" "$JOB_TMP/apptainer-tmp" "$JOB_TMP/apptainer-cache" "$BASE/logs"
export APPTAINER_TMPDIR=$JOB_TMP/apptainer-tmp
export APPTAINER_CACHEDIR=$JOB_TMP/apptainer-cache
exec > >(tee -a "$LIVE_LOG") 2>&1

echo "phase=N-FRONTEND-3B"
echo "pair_id=$PAIR_ID"
echo "job_id=$JOB_ID"
echo "partition=$PARTITION"
echo "source_2b_root=$SOURCE_2B_ROOT"
echo "output_dir=$OUTPUT_DIR"
echo "resources=cpus:${SLURM_CPUS_PER_TASK:-2},memory:16G,time:02:00:00"

module purge
module load apps/apptainer/1.4.5-2
COMMON_BIND=(
  --bind "$REPO":/work
  --bind "$DATA_ROOT":/data_store
  --bind "$BASE/tmp":/hpc_tmp
)
PY=/opt/venv/bin/python

apptainer exec "${COMMON_BIND[@]}" "$IMG" \
  "$PY" -u /work/scripts/run_n_frontend3b_background_suppression.py \
  --n-frontend2b-root "/data_store/$SOURCE_REL" \
  --config /work/configs/n_frontend3b_background_suppression_v01.json \
  --package-manifest /work/N_FRONTEND3B_PACKAGE_MANIFEST.json \
  --output-dir "/data_store/$OUTPUT_REL/result"

apptainer exec "${COMMON_BIND[@]}" "$IMG" \
  "$PY" /work/scripts/validate_n_frontend3b_background_suppression.py \
  --output-dir "/data_store/$OUTPUT_REL/result" \
  --config /work/configs/n_frontend3b_background_suppression_v01.json \
  --validation-output "/data_store/$OUTPUT_REL/n_frontend3b_validation.json"

tar -czf "$OUTPUT_DIR/n_frontend3b_small_results.tar.gz" \
  -C "$OUTPUT_DIR" n_frontend3b_validation.json \
  -C "$OUTPUT_DIR/result" \
  n_frontend3b_summary.json \
  n_frontend3b_report.md \
  n_frontend3b_package_manifest.json \
  n_frontend3b_source_anchor_audit.csv \
  n_frontend3b_frozen_input_manifest.json \
  n_frontend3b_denominator_audit.csv \
  n_frontend3b_transition_learning_load.csv \
  n_frontend3b_micro_event_learning_load.csv \
  n_frontend3b_micro_event_member_distribution.csv \
  n_frontend3b_foreground_family_composition.csv \
  n_frontend3b_upstream_exact_dedup_audit.csv \
  n_frontend3b_observer_prefix_exhaustion_summary.json \
  n_frontend3b_observer_prefix_exhaustion_top.csv \
  n_frontend3b_phase_survival_regression.csv \
  n_frontend3b_restoration_audit.csv \
  n_frontend3b_past_only_exposure_equality.csv \
  n_frontend3b_stage_accounting_audit.csv \
  n_frontend3b_causal_strict_replay_audit.csv \
  n_frontend3b_semantic_delta_regression.csv \
  n_frontend3b_gray_tripwire_audit.csv \
  n_frontend3b_non_route_bypass_audit.csv \
  n_frontend3b_stop_loss_audit.csv \
  n_frontend3b_semantic_output_manifest.json

echo "validation=$OUTPUT_DIR/n_frontend3b_validation.json"
echo "small_results=$OUTPUT_DIR/n_frontend3b_small_results.tar.gz"
