#!/usr/bin/env bash
#SBATCH -J bgp_r_attack1
#SBATCH -p intel
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -c 16
#SBATCH --mem=96G
#SBATCH -t 12:00:00
#SBATCH -o /public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/logs/%x_%j.out
#SBATCH -e /public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/logs/%x_%j.err

set -euo pipefail

BASE=${BASE:-/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline}
REPO=${REPO:-$BASE/repo}
IMG=${IMG:-$BASE/containers/bgpstream-py-e9a.sif}
SOURCE_RUN_ID=${SOURCE_RUN_ID:-s2a_baseline_v01_pilot_6h_april16}
RUN_ID=${RUN_ID:-s2a_attack1_family_expansion_6h_april16_v01}
CONFIG=${CONFIG:-configs/r_attack1_family_expansion_v01.json}
OUTPUT_ROOT=${OUTPUT_ROOT:-outputs/r_attack_1/$RUN_ID}
LIVE_LOG=${BASE}/logs/r_attack1_${SLURM_JOB_ID}.live.log

mkdir -p "$BASE/logs" "$BASE/tmp/apptainer-tmp" "$BASE/tmp/apptainer-cache"
export APPTAINER_TMPDIR=$BASE/tmp/apptainer-tmp
export APPTAINER_CACHEDIR=$BASE/tmp/apptainer-cache
exec > >(tee -a "$LIVE_LOG") 2>&1

echo "job_id=$SLURM_JOB_ID"
echo "node_list=$SLURM_NODELIST"
echo "repo=$REPO"
echo "run_id=$RUN_ID"
echo "output_root=$OUTPUT_ROOT"
echo "live_log=$LIVE_LOG"

module purge
module load apps/apptainer/1.4.5-2

apptainer exec --bind "$REPO":/work "$IMG" /bin/bash -lc "
set -euo pipefail
cd /work
PY=/opt/venv/bin/python
SOURCE_RUN_ID='$SOURCE_RUN_ID'
RUN_ID='$RUN_ID'
CONFIG='$CONFIG'
OUTPUT_ROOT='$OUTPUT_ROOT'
MAT_DIR=\$OUTPUT_ROOT/materialization
EVENTS=data/runs/\$RUN_ID/events/event_units.parquet
CAND_DIR=data/runs/\$RUN_ID/candidates
CANDIDATES=\$CAND_DIR/candidate_events.parquet
EVIDENCE=\$OUTPUT_ROOT/evidence
AUDIT=\$OUTPUT_ROOT/audit
QA=\$OUTPUT_ROOT/qa
FG3=\$OUTPUT_ROOT/foreground3

test ! -e data/runs/\$RUN_ID
test ! -e \$OUTPUT_ROOT

\$PY -m py_compile \
  scripts/materialize_r_attack1_family_expansion.py \
  scripts/audit_r_attack1_family_expansion_qa.py \
  scripts/run_r_foreground3_online_foreground_smoke.py \
  scripts/hpc/validate_r_attack1_full_replay.py

\$PY -u scripts/materialize_r_attack1_family_expansion.py \
  --config \$CONFIG \
  --output-dir \$MAT_DIR

\$PY -u scripts/build_event_units.py \
  --run-id \$RUN_ID \
  --input data/runs/\$RUN_ID \
  --output \$EVENTS \
  --window-sec 300 \
  --prefer-rel false

\$PY -u scripts/build_weak_candidates_streaming.py \
  --run-id \$RUN_ID \
  --events \$EVENTS \
  --baseline-prefix data/runs/\$SOURCE_RUN_ID/baseline/baseline_prefix.parquet \
  --baseline-prefix-origin data/runs/\$SOURCE_RUN_ID/baseline/baseline_prefix_origin.parquet \
  --baseline-path data/runs/\$SOURCE_RUN_ID/baseline/baseline_path.parquet \
  --output-dir \$CAND_DIR \
  --batch-size 100000

\$PY -u scripts/build_r_rpki_clean0_sidecar.py \
  --run-id \$RUN_ID \
  --run-date 2024-04-16 \
  --events \$EVENTS \
  --candidates \$CANDIDATES \
  --output-dir \$EVIDENCE/rpki

\$PY -u scripts/build_r_asrel_clean0_sidecar.py \
  --run-id \$RUN_ID \
  --run-date 2024-04-16 \
  --events \$EVENTS \
  --candidates \$CANDIDATES \
  --output-dir \$EVIDENCE/asrel

\$PY -u scripts/build_r_comm_clean0_community_sidecar.py \
  --run-id \$RUN_ID \
  --run-date 2024-04-16 \
  --run-root data/runs/\$RUN_ID \
  --events \$EVENTS \
  --candidates \$CANDIDATES \
  --output-dir \$EVIDENCE/community \
  --source-mode event_source

\$PY -u scripts/audit_r_attack0a_origin_propagation.py \
  --run-id \$RUN_ID \
  --raw-truth \$MAT_DIR/injected_raw_truth.parquet \
  --events \$EVENTS \
  --candidates \$CANDIDATES \
  --rpki-sidecar \$EVIDENCE/rpki/rpki_event_sidecar.parquet \
  --asrel-sidecar \$EVIDENCE/asrel/asrel_2024_event_sidecar.parquet \
  --community-sidecar \$EVIDENCE/community/community_event_sidecar.parquet \
  --output-dir \$AUDIT

\$PY -u scripts/run_r_foreground3_online_foreground_smoke.py \
  --run-id \$RUN_ID \
  --events \$EVENTS \
  --raw-truth \$MAT_DIR/injected_raw_truth.parquet \
  --raw-event-membership \$AUDIT/raw_event_membership.csv \
  --rpki-sidecar \$EVIDENCE/rpki/rpki_event_sidecar.parquet \
  --asrel-sidecar \$EVIDENCE/asrel/asrel_2024_event_sidecar.parquet \
  --community-sidecar \$EVIDENCE/community/community_event_sidecar.parquet \
  --attack-output-root \$OUTPUT_ROOT \
  --output-dir \$FG3

\$PY -u scripts/audit_r_attack1_family_expansion_qa.py \
  --config \$CONFIG \
  --baseline-events data/runs/\$SOURCE_RUN_ID/events/event_units.parquet \
  --materialization-summary \$MAT_DIR/materialization_summary.json \
  --raw-truth \$MAT_DIR/injected_raw_truth.parquet \
  --raw-outcomes \$AUDIT/raw_record_layer_outcomes.parquet \
  --raw-event-membership \$AUDIT/raw_event_membership.csv \
  --candidates \$CANDIDATES \
  --evidence-audit \$AUDIT/attack_event_evidence_audit.parquet \
  --rpki-summary \$EVIDENCE/rpki/rpki_clean0_summary.json \
  --asrel-summary \$EVIDENCE/asrel/asrel_2024_summary.json \
  --community-summary \$EVIDENCE/community/community_noexport_summary.json \
  --foreground-summary \$FG3/r_foreground3_summary.json \
  --output-dir \$QA

\$PY -u scripts/hpc/validate_r_attack1_full_replay.py \
  --materialization-summary \$MAT_DIR/materialization_summary.json \
  --event-summary data/runs/\$RUN_ID/events/event_units_summary.json \
  --candidate-summary \$CAND_DIR/candidate_summary.json \
  --raw-truth \$MAT_DIR/injected_raw_truth.parquet \
  --rpki-summary \$EVIDENCE/rpki/rpki_clean0_summary.json \
  --asrel-summary \$EVIDENCE/asrel/asrel_2024_summary.json \
  --community-summary \$EVIDENCE/community/community_noexport_summary.json \
  --qa-summary \$QA/r_attack1_qa_summary.json \
  --foreground-summary \$FG3/r_foreground3_summary.json \
  --output \$OUTPUT_ROOT/full_replay_validation.json

tar -czf \$OUTPUT_ROOT/r_attack1_small_results.tar.gz \
  \$OUTPUT_ROOT/full_replay_validation.json \
  \$MAT_DIR/materialization_summary.json \
  \$MAT_DIR/scenario_registry.json \
  \$MAT_DIR/dynamic_role_selection_audit.csv \
  \$MAT_DIR/inserted_edge_topology_audit.csv \
  data/runs/\$RUN_ID/events/event_units_summary.json \
  \$CAND_DIR/candidate_summary.json \
  \$EVIDENCE/rpki/rpki_clean0_summary.json \
  \$EVIDENCE/asrel/asrel_2024_summary.json \
  \$EVIDENCE/community/community_noexport_summary.json \
  \$AUDIT/r_attack0a_summary.json \
  \$AUDIT/scenario_propagation_audit.csv \
  \$AUDIT/scenario_evidence_response_audit.csv \
  \$FG3/r_foreground3_summary.json \
  \$FG3/r_foreground3_population_audit.csv \
  \$FG3/r_foreground3_attack_retention_audit.csv \
  \$QA/r_attack1_qa_summary.json \
  \$QA/qa_checks.csv \
  \$QA/scenario_qa.csv \
  \$QA/hard_negative_candidate_audit.csv
"

echo "validation=$REPO/$OUTPUT_ROOT/full_replay_validation.json"
echo "small_results=$REPO/$OUTPUT_ROOT/r_attack1_small_results.tar.gz"
