#!/usr/bin/env bash
set -euo pipefail

BASE=${BASE:-/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline}
REPO=${REPO:-$BASE/repo}
DATA_ROOT=${DATA_ROOT:-$BASE/data_store}
PAIR_ID=${1:-n_frontend2b_$(date -u +%Y%m%dT%H%M%SZ)}
SOURCE_ROOT=${2:-$DATA_ROOT/derived/r_mem1e_10d_peer_aware_v02/pair=r_mem1e_20260721T130846Z/partition=amd/array_job=153044}
REPLAY_DATE=${N_FRONTEND2B_DATE:-2024-04-09}
JOB_SCRIPT=$REPO/scripts/hpc/n_frontend2b_bounded_replay.slurm
RECORD=$BASE/logs/n_frontend2b_pair_${PAIR_ID}.txt

export N_FRONTEND2B_DATE=$REPLAY_DATE
bash "$REPO/scripts/hpc/n_frontend2b_bounded_replay_preflight.sh" \
  "$PAIR_ID" "$SOURCE_ROOT"
mkdir -p "$BASE/logs"
CODE_COMMIT=$(git -C "$REPO" rev-parse HEAD 2>/dev/null || true)
CODE_COMMIT=${CODE_COMMIT:-archive-no-git}
CODE_FINGERPRINT=$(sha256sum \
  "$REPO/scripts/run_n_frontend2b_controlled_pairs.py" \
  "$REPO/scripts/validate_n_frontend2b_controlled_pairs.py" \
  "$REPO/scripts/build_n_frontend1_causal_transitions.py" \
  "$REPO/scripts/r_mem_canonical_observation_v2.py" \
  "$REPO/configs/n_frontend2b_controlled_pairs_v01.json" \
  "$REPO/configs/n_frontend1_causal_transition_v01.json" \
  "$REPO/configs/r_poison0_paired_benchmark_protocol_v01.json" \
  "$REPO/scripts/hpc/n_frontend2b_bounded_replay_preflight.sh" \
  "$REPO/scripts/hpc/n_frontend2b_bounded_replay.slurm" \
  "$REPO/scripts/hpc/run_with_portable_timing.sh" \
  "$REPO/scripts/hpc/submit_n_frontend2b_bounded_replay_dual.sh" \
  | sha256sum | awk '{print $1}')

{
  echo "pair_id=$PAIR_ID"
  echo "submitted_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "commit=$CODE_COMMIT"
  echo "code_fingerprint=$CODE_FINGERPRINT"
  echo "source_root=$SOURCE_ROOT"
  echo "replay_date=$REPLAY_DATE"
  echo "episode_sec=3600"
  echo "resources=cpus:4,memory:64G,time:04:00:00"
} | tee "$RECORD"

AMD_JOB=$(sbatch --parsable -p amd -J bgp_n_front2b_amd \
  --export=ALL,N_FRONTEND2B_PAIR_ID="$PAIR_ID",N_FRONTEND2B_SOURCE_ROOT="$SOURCE_ROOT",N_FRONTEND2B_DATE="$REPLAY_DATE" \
  "$JOB_SCRIPT")
echo "amd_job_id=$AMD_JOB" | tee -a "$RECORD"

INTEL_JOB=$(sbatch --parsable -p intel -J bgp_n_front2b_intel \
  --export=ALL,N_FRONTEND2B_PAIR_ID="$PAIR_ID",N_FRONTEND2B_SOURCE_ROOT="$SOURCE_ROOT",N_FRONTEND2B_DATE="$REPLAY_DATE" \
  "$JOB_SCRIPT")
echo "intel_job_id=$INTEL_JOB" | tee -a "$RECORD"

echo "submission_record=$RECORD"
echo "Both jobs are independently valid and write partition/job-isolated outputs."
