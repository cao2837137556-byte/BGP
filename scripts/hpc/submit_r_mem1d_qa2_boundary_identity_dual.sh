#!/usr/bin/env bash
set -euo pipefail

BASE=${BASE:-/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline}
REPO=${REPO:-$BASE/repo}
PAIR_ID=${1:-r_mem1d_qa2_$(date -u +%Y%m%dT%H%M%SZ)}
MATERIALIZATION_ROOT=${2:?usage: submit_r_mem1d_qa2_boundary_identity_dual.sh PAIR_ID MATERIALIZATION_ROOT}
JOB_SCRIPT=$REPO/scripts/hpc/r_mem1d_qa2_boundary_identity.slurm
RECORD=$BASE/logs/r_mem1d_qa2_pair_${PAIR_ID}.txt

bash "$REPO/scripts/hpc/r_mem1d_qa2_boundary_identity_preflight.sh" \
  "$PAIR_ID" "$MATERIALIZATION_ROOT"
mkdir -p "$BASE/logs"
CODE_COMMIT=$(git -C "$REPO" rev-parse HEAD 2>/dev/null || true)
CODE_COMMIT=${CODE_COMMIT:-archive-no-git}
CODE_FINGERPRINT=$(sha256sum \
  "$REPO/scripts/audit_r_mem1d_boundary_observation_identity.py" \
  "$REPO/scripts/audit_r_mem1d_temporal_alignment.py" \
  "$REPO/scripts/run_r_mem1c_local_mrt_parser_smoke.py" \
  "$REPO/configs/r_mem1d_qa2_boundary_identity_v01.json" \
  "$REPO/configs/r_mem1d_10d_parquet_materialization_v01.json" \
  "$REPO/scripts/hpc/r_mem1d_qa2_boundary_identity_preflight.sh" \
  "$REPO/scripts/hpc/submit_r_mem1d_qa2_boundary_identity_dual.sh" \
  "$JOB_SCRIPT" | sha256sum | awk '{print $1}')

{
  echo "pair_id=$PAIR_ID"
  echo "submitted_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "commit=$CODE_COMMIT"
  echo "code_fingerprint=$CODE_FINGERPRINT"
  echo "materialization_root=$MATERIALIZATION_ROOT"
} | tee "$RECORD"

AMD_JOB=$(sbatch --parsable -p amd -J bgp_r_mem1d_qa2_amd \
  --export=ALL,R_MEM1D_QA2_PAIR_ID="$PAIR_ID",R_MEM1D_QA2_MATERIALIZATION_ROOT="$MATERIALIZATION_ROOT" \
  "$JOB_SCRIPT")
echo "amd_job_id=$AMD_JOB" | tee -a "$RECORD"

INTEL_JOB=$(sbatch --parsable -p intel -J bgp_r_mem1d_qa2_intel \
  --export=ALL,R_MEM1D_QA2_PAIR_ID="$PAIR_ID",R_MEM1D_QA2_MATERIALIZATION_ROOT="$MATERIALIZATION_ROOT" \
  "$JOB_SCRIPT")
echo "intel_job_id=$INTEL_JOB" | tee -a "$RECORD"

echo "submission_record=$RECORD"
echo "Both jobs read the same immutable source and write isolated outputs. If both finish, compare them as redundant executions rather than independent samples."
