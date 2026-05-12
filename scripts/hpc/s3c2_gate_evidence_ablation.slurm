#!/usr/bin/env bash
#SBATCH -J bgp_s3c2_gate
#SBATCH -p amd
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -c 16
#SBATCH --mem=256G
#SBATCH -t 08:00:00
#SBATCH -o /public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/logs/%x_%j.out
#SBATCH -e /public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/logs/%x_%j.err

set -euo pipefail

BASE=${BASE:-/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline}
REPO=${REPO:-$BASE/repo}
IMG=${IMG:-$BASE/containers/bgpstream-py-e9a.sif}
RUN_ID=${RUN_ID:-s2a_expanded_v01_pilot_6h_april16}
OUTPUT_DIR=${OUTPUT_DIR:-outputs/s3c2_gate_evidence_ablation_v01}
S3C1B_OUTPUT_DIR=${S3C1B_OUTPUT_DIR:-outputs/s3c1b_penalty_calibration_v01}
MODE=${MODE:-full}
SAMPLE_ROWS=${SAMPLE_ROWS:-200000}
TEMPORAL_WINDOW_SEC=${TEMPORAL_WINDOW_SEC:-600}
KNOWN_EVENT_FILE=${KNOWN_EVENT_FILE:-data/known_events/known_event_candidates_v05.json}
BUNDLE_NAME=${BUNDLE_NAME:-s3c2_gate_evidence_ablation_bundle}
LIVE_LOG=${BASE}/logs/s3c2_gate_evidence_ablation_${SLURM_JOB_ID}.live.log

mkdir -p "$BASE/logs" "$BASE/tmp/apptainer-tmp" "$BASE/tmp/apptainer-cache"
export APPTAINER_TMPDIR=$BASE/tmp/apptainer-tmp
export APPTAINER_CACHEDIR=$BASE/tmp/apptainer-cache

exec > >(tee -a "$LIVE_LOG") 2>&1

echo "job_id=$SLURM_JOB_ID"
echo "node_list=$SLURM_NODELIST"
echo "live_log=$LIVE_LOG"
echo "run_id=$RUN_ID"
echo "output_dir=$OUTPUT_DIR"
echo "s3c1b_output_dir=$S3C1B_OUTPUT_DIR"
echo "mode=$MODE"
echo "sample_rows=$SAMPLE_ROWS"
echo "temporal_window_sec=$TEMPORAL_WINDOW_SEC"
echo "known_event_file=$KNOWN_EVENT_FILE"

module purge
module load apps/apptainer/1.4.5-2

if [[ "$MODE" != "smoke" && "$MODE" != "full" ]]; then
  echo "MODE must be smoke or full, got: $MODE" >&2
  exit 2
fi

for path in \
  "$REPO/data/runs/$RUN_ID/scores/scored_candidates.parquet" \
  "$REPO/data/runs/$RUN_ID/events/event_units.parquet" \
  "$REPO/data/runs/$RUN_ID/candidates/candidate_events.parquet" \
  "$REPO/data/runs/$RUN_ID/gating/gated_candidates.parquet" \
  "$REPO/data/runs/$RUN_ID/final/final_alerts.parquet" \
  "$REPO/data/runs/$RUN_ID/baseline/baseline_prefix_origin.parquet" \
  "$REPO/data/runs/$RUN_ID/incidents/incident_membership.parquet" \
  "$REPO/outputs/s3a2_incident_priority_calibration_v01/s3a2_calibrated_incident_tickets.parquet" \
  "$REPO/$S3C1B_OUTPUT_DIR/s3c1b_summary.json" \
  "$REPO/$S3C1B_OUTPUT_DIR/s3c1b_recommended_strategy.json"; do
  if [[ ! -s "$path" ]]; then
    echo "required input missing or empty: $path" >&2
    exit 3
  fi
done

if [[ ! -s "$REPO/$KNOWN_EVENT_FILE" ]]; then
  echo "warning: known-event file missing or empty: $REPO/$KNOWN_EVENT_FILE"
fi

apptainer exec --bind "$REPO":/work "$IMG" /bin/bash -lc "
set -euo pipefail
cd /work
if [[ '$MODE' == 'smoke' ]]; then
  /opt/venv/bin/python -u scripts/run_s3c2_gate_evidence_ablation.py \
    --run-id '$RUN_ID' \
    --output-dir '$OUTPUT_DIR' \
    --s3c1b-output-dir '$S3C1B_OUTPUT_DIR' \
    --temporal-window-sec '$TEMPORAL_WINDOW_SEC' \
    --known-event-file '$KNOWN_EVENT_FILE' \
    --sample-rows '$SAMPLE_ROWS'
else
  /opt/venv/bin/python -u scripts/run_s3c2_gate_evidence_ablation.py \
    --run-id '$RUN_ID' \
    --output-dir '$OUTPUT_DIR' \
    --s3c1b-output-dir '$S3C1B_OUTPUT_DIR' \
    --temporal-window-sec '$TEMPORAL_WINDOW_SEC' \
    --known-event-file '$KNOWN_EVENT_FILE' \
    --full-run
fi
/opt/venv/bin/python -u scripts/package_experiment_bundle.py \
  --bundle-name '$BUNDLE_NAME' \
  --path '$OUTPUT_DIR' \
  --run-id '$RUN_ID'
"

echo "summary=$REPO/$OUTPUT_DIR/s3c2_summary.json"
echo "report=$REPO/$OUTPUT_DIR/s3c2_report.md"
echo "bundle=$REPO/outputs/bundles/${BUNDLE_NAME}.zip"
