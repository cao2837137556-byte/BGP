#!/usr/bin/env bash
#SBATCH -J bgp_r_noise_clean1
#SBATCH -p intel
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -c 8
#SBATCH --mem=64G
#SBATCH -t 04:00:00
#SBATCH -o /public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/logs/%x_%j.out
#SBATCH -e /public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/logs/%x_%j.err

set -euo pipefail

BASE=${BASE:-/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline}
REPO=${REPO:-$BASE/repo}
IMG=${IMG:-$BASE/containers/bgpstream-py-e9a.sif}
RUN_ID=${RUN_ID:-s2a_attack0a2_hardened_origin_smoke_6h_april16_v02}
ATTACK_OUTPUT_ROOT=${ATTACK_OUTPUT_ROOT:-outputs/r_attack_0a3_intel/s2a_baseline_v01_pilot_6h_april16}
OUTPUT_DIR=${OUTPUT_DIR:-outputs/r_noise_clean1/$RUN_ID}
LIVE_LOG=${BASE}/logs/r_noise_clean1_${SLURM_JOB_ID}.live.log

mkdir -p "$BASE/logs" "$BASE/tmp/apptainer-tmp" "$BASE/tmp/apptainer-cache"
export APPTAINER_TMPDIR=$BASE/tmp/apptainer-tmp
export APPTAINER_CACHEDIR=$BASE/tmp/apptainer-cache
exec > >(tee -a "$LIVE_LOG") 2>&1

echo "job_id=$SLURM_JOB_ID"
echo "node_list=$SLURM_NODELIST"
echo "repo=$REPO"
echo "run_id=$RUN_ID"
echo "attack_output_root=$ATTACK_OUTPUT_ROOT"
echo "output_dir=$OUTPUT_DIR"
echo "live_log=$LIVE_LOG"

module purge
module load apps/apptainer/1.4.5-2

apptainer exec --bind "$REPO":/work "$IMG" /bin/bash -lc "
set -euo pipefail
cd /work
PY=/opt/venv/bin/python
test -e data/runs/$RUN_ID/candidates/candidate_events.parquet
test -e data/runs/$RUN_ID/events/event_units.parquet
test -e $ATTACK_OUTPUT_ROOT/materialization/injected_raw_truth.parquet
test -e $ATTACK_OUTPUT_ROOT/audit/raw_event_membership.csv
test -e $ATTACK_OUTPUT_ROOT/evidence/rpki/rpki_event_sidecar.parquet
test -e $ATTACK_OUTPUT_ROOT/evidence/asrel/asrel_2024_event_sidecar.parquet
test -e $ATTACK_OUTPUT_ROOT/evidence/community/community_event_sidecar.parquet
test ! -e $OUTPUT_DIR
\$PY -m py_compile scripts/evaluate_r_noise_clean1_foreground.py
\$PY -u scripts/evaluate_r_noise_clean1_foreground.py \
  --run-id $RUN_ID \
  --attack-output-root $ATTACK_OUTPUT_ROOT \
  --output-dir $OUTPUT_DIR \
  --sample-size 10000
tar -czf $OUTPUT_DIR/r_noise_clean1_small_results.tar.gz \
  $OUTPUT_DIR/r_noise_clean1_summary.json \
  $OUTPUT_DIR/r_noise_clean1_population_audit.csv \
  $OUTPUT_DIR/r_noise_clean1_attack_retention_audit.csv \
  $OUTPUT_DIR/r_noise_clean1_hard_negative_audit.csv \
  $OUTPUT_DIR/r_noise_clean1_scenario_control_audit.csv \
  $OUTPUT_DIR/r_noise_clean1_safety_gates.csv \
  $OUTPUT_DIR/r_noise_clean1_assignment_sample.csv \
  $OUTPUT_DIR/r_noise_clean1_report.md
"

echo "summary=$REPO/$OUTPUT_DIR/r_noise_clean1_summary.json"
echo "small_results=$REPO/$OUTPUT_DIR/r_noise_clean1_small_results.tar.gz"
