#!/usr/bin/env bash
set -euo pipefail

BASE=${BASE:-/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline}
REPO=${REPO:-$BASE/repo}
PAIR_ID=${1:-r_mem1c_measure_$(date -u +%Y%m%dT%H%M%SZ)}
SLURM_SCRIPT=$REPO/scripts/hpc/r_mem1c_complete_file_measure.slurm
SUBMISSION_RECORD=$BASE/logs/r_mem1c_measure_pair_${PAIR_ID}.txt

bash "$REPO/scripts/hpc/r_mem1c_complete_file_measure_preflight.sh" "$PAIR_ID"

mkdir -p "$BASE/logs"
CODE_COMMIT=$(git -C "$REPO" rev-parse HEAD 2>/dev/null || true)
CODE_COMMIT=${CODE_COMMIT:-archive-no-git}
CODE_FINGERPRINT=$(sha256sum \
  "$REPO/scripts/run_r_mem1c_local_mrt_parser_smoke.py" \
  "$REPO/configs/r_mem1c_complete_file_measure_v01.json" \
  "$SLURM_SCRIPT" | sha256sum | awk '{print $1}')
{
  echo "pair_id=$PAIR_ID"
  echo "submitted_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "commit=$CODE_COMMIT"
  echo "code_fingerprint=$CODE_FINGERPRINT"
} | tee "$SUBMISSION_RECORD"

AMD_JOB=$(sbatch --parsable -p amd -J bgp_r_mem1c_m_amd \
  --export=ALL,R_MEM1C_PAIR_ID="$PAIR_ID" "$SLURM_SCRIPT")
echo "amd_job_id=$AMD_JOB" | tee -a "$SUBMISSION_RECORD"

INTEL_JOB=$(sbatch --parsable -p intel -J bgp_r_mem1c_m_intel \
  --export=ALL,R_MEM1C_PAIR_ID="$PAIR_ID" "$SLURM_SCRIPT")
echo "intel_job_id=$INTEL_JOB" | tee -a "$SUBMISSION_RECORD"

echo "submission_record=$SUBMISSION_RECORD"
echo "Both jobs are isolated and valid if both finish; cancel the later-starting job when convenient."
