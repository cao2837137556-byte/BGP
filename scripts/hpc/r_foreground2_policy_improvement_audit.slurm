#!/usr/bin/env bash
#SBATCH -J bgp_r_fg2
#SBATCH -p intel
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -c 16
#SBATCH --mem=96G
#SBATCH -t 04:00:00
#SBATCH -o /public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/logs/%x_%j.out
#SBATCH -e /public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/logs/%x_%j.err

set -euo pipefail

BASE=${BASE:-/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline}
REPO=${REPO:-$BASE/repo}
IMG=${IMG:-$BASE/containers/bgpstream-py-e9a.sif}
RUN_ID=${RUN_ID:-s2a_attack0b_multi_attack_smoke_6h_april16_v01}
ATTACK_OUTPUT_ROOT=${ATTACK_OUTPUT_ROOT:-outputs/r_attack_0b/$RUN_ID}
CONFIG=${CONFIG:-configs/r_foreground2_policy_audit_v1.json}
OUTPUT_DIR=${OUTPUT_DIR:-outputs/r_foreground_2/$RUN_ID}
LIVE_LOG=${BASE}/logs/r_foreground2_${SLURM_JOB_ID}.live.log

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
RUN_ID='$RUN_ID'
ATTACK_OUTPUT_ROOT='$ATTACK_OUTPUT_ROOT'
CONFIG='$CONFIG'
OUTPUT_DIR='$OUTPUT_DIR'

test -e data/runs/\$RUN_ID/events/event_units.parquet
test -e \$ATTACK_OUTPUT_ROOT/materialization/injected_raw_truth.parquet
test -e \$ATTACK_OUTPUT_ROOT/audit/raw_event_membership.csv
test -e \$ATTACK_OUTPUT_ROOT/evidence/rpki/rpki_event_sidecar.parquet
test -e \$ATTACK_OUTPUT_ROOT/evidence/asrel/asrel_2024_event_sidecar.parquet
test -e \$ATTACK_OUTPUT_ROOT/evidence/community/community_event_sidecar.parquet
test ! -e \$OUTPUT_DIR

\$PY -m py_compile scripts/audit_r_foreground2_policy_improvement.py

\$PY -u scripts/audit_r_foreground2_policy_improvement.py \
  --run-id \$RUN_ID \
  --attack-output-root \$ATTACK_OUTPUT_ROOT \
  --policy-config \$CONFIG \
  --output-dir \$OUTPUT_DIR

tar -czf \$OUTPUT_DIR/r_foreground2_small_results.tar.gz \
  \$OUTPUT_DIR/r_foreground2_summary.json \
  \$OUTPUT_DIR/r_foreground2_policy_comparison.csv \
  \$OUTPUT_DIR/r_foreground2_policy_population_audit.csv \
  \$OUTPUT_DIR/r_foreground2_policy_attack_retention_audit.csv \
  \$OUTPUT_DIR/r_foreground2_policy_reason_distribution.csv \
  \$OUTPUT_DIR/r_foreground2_retained_pressure_audit.csv \
  \$OUTPUT_DIR/r_foreground2_semantic_feature_audit.csv \
  \$OUTPUT_DIR/r_foreground2_assignment_sample.csv \
  \$OUTPUT_DIR/r_foreground2_report.md
"

echo "summary=$REPO/$OUTPUT_DIR/r_foreground2_summary.json"
echo "small_results=$REPO/$OUTPUT_DIR/r_foreground2_small_results.tar.gz"
