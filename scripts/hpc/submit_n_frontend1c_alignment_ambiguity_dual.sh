#!/usr/bin/env bash
set -euo pipefail

BASE=${BASE:-/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline}
REPO=${REPO:-$BASE/repo}
PAIR_ID=${1:-n_frontend1c_$(date -u +%Y%m%dT%H%M%SZ)}
SOURCE_PAIR_ID=${2:-n_frontend1b_20260725T042216Z}
AMD_SOURCE_JOB=${3:-154385}
INTEL_SOURCE_JOB=${4:-154386}
JOB_SCRIPT=$REPO/scripts/hpc/n_frontend1c_alignment_ambiguity_audit.slurm
RECORD=$BASE/logs/n_frontend1c_pair_${PAIR_ID}.txt

bash "$REPO/scripts/hpc/n_frontend1c_alignment_ambiguity_preflight.sh" \
  "$PAIR_ID" "$SOURCE_PAIR_ID" "$AMD_SOURCE_JOB" "$INTEL_SOURCE_JOB"
mkdir -p "$BASE/logs"
CODE_COMMIT=$(git -C "$REPO" rev-parse HEAD 2>/dev/null || true)
CODE_COMMIT=${CODE_COMMIT:-archive-no-git}
CODE_FINGERPRINT=$(sha256sum \
  "$REPO/scripts/audit_n_frontend1b_alignment_and_ambiguity.py" \
  "$REPO/scripts/hpc/n_frontend1c_alignment_ambiguity_audit.slurm" \
  "$REPO/scripts/hpc/n_frontend1c_alignment_ambiguity_preflight.sh" \
  "$REPO/scripts/hpc/run_with_portable_timing.sh" \
  "$REPO/scripts/hpc/submit_n_frontend1c_alignment_ambiguity_dual.sh" \
  | sha256sum | awk '{print $1}')

{
  echo "pair_id=$PAIR_ID"
  echo "submitted_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "commit=$CODE_COMMIT"
  echo "code_fingerprint=$CODE_FINGERPRINT"
  echo "source_pair_id=$SOURCE_PAIR_ID"
  echo "amd_source_job=$AMD_SOURCE_JOB"
  echo "intel_source_job=$INTEL_SOURCE_JOB"
} | tee "$RECORD"

AMD_JOB=$(sbatch --parsable -p amd -J bgp_n_front1c_amd \
  --export=ALL,N_FRONTEND1C_PAIR_ID="$PAIR_ID",N_FRONTEND1C_SOURCE_PAIR_ID="$SOURCE_PAIR_ID",N_FRONTEND1C_AMD_SOURCE_JOB="$AMD_SOURCE_JOB",N_FRONTEND1C_INTEL_SOURCE_JOB="$INTEL_SOURCE_JOB" \
  "$JOB_SCRIPT")
echo "amd_job_id=$AMD_JOB" | tee -a "$RECORD"

INTEL_JOB=$(sbatch --parsable -p intel -J bgp_n_front1c_intel \
  --export=ALL,N_FRONTEND1C_PAIR_ID="$PAIR_ID",N_FRONTEND1C_SOURCE_PAIR_ID="$SOURCE_PAIR_ID",N_FRONTEND1C_AMD_SOURCE_JOB="$AMD_SOURCE_JOB",N_FRONTEND1C_INTEL_SOURCE_JOB="$INTEL_SOURCE_JOB" \
  "$JOB_SCRIPT")
echo "intel_job_id=$INTEL_JOB" | tee -a "$RECORD"

echo "submission_record=$RECORD"
echo "Both jobs read the same paired source and write partition/job-isolated outputs."
