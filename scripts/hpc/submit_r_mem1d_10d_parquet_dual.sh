#!/usr/bin/env bash
set -euo pipefail

BASE=${BASE:-/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline}
REPO=${REPO:-$BASE/repo}
PAIR_ID=${1:-r_mem1d_$(date -u +%Y%m%dT%H%M%SZ)}
ADOPT_ROOT=${R_MEM1D_ADOPT_ROOT:-}
ARRAY_SCRIPT=$REPO/scripts/hpc/r_mem1d_10d_parquet_array.slurm
VALIDATOR_SCRIPT=$REPO/scripts/hpc/r_mem1d_validate_10d_parquet.slurm
RECORD=$BASE/logs/r_mem1d_pair_${PAIR_ID}.txt

bash "$REPO/scripts/hpc/r_mem1d_10d_parquet_preflight.sh" "$PAIR_ID"
if [[ -n "$ADOPT_ROOT" ]]; then
  case "$ADOPT_ROOT" in
    "$BASE/data_store"/*) ;;
    *) echo "R_MEM1D_ADOPT_ROOT must be under $BASE/data_store" >&2; exit 2 ;;
  esac
  test -d "$ADOPT_ROOT"
  test "$(find "$ADOPT_ROOT" -type f -name r_mem1d_task_summary.json | wc -l)" -eq 20
fi
mkdir -p "$BASE/logs"
CODE_COMMIT=$(git -C "$REPO" rev-parse HEAD 2>/dev/null || true)
CODE_COMMIT=${CODE_COMMIT:-archive-no-git}
CODE_FINGERPRINT=$(sha256sum \
  "$REPO/scripts/run_r_mem1c_local_mrt_parser_smoke.py" \
  "$REPO/scripts/materialize_r_mem1d_10d_parquet.py" \
  "$REPO/scripts/audit_r_mem1d_temporal_alignment.py" \
  "$REPO/scripts/validate_r_mem1d_10d_parquet.py" \
  "$REPO/configs/r_mem1d_10d_parquet_materialization_v01.json" \
  "$REPO/scripts/hpc/r_mem1d_10d_parquet_preflight.sh" \
  "$REPO/scripts/hpc/submit_r_mem1d_10d_parquet_dual.sh" \
  "$ARRAY_SCRIPT" "$VALIDATOR_SCRIPT" | sha256sum | awk '{print $1}')

{
  echo "pair_id=$PAIR_ID"
  echo "submitted_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "commit=$CODE_COMMIT"
  echo "code_fingerprint=$CODE_FINGERPRINT"
  echo "adopt_root=${ADOPT_ROOT:-none}"
} | tee "$RECORD"

AMD_ARRAY=$(sbatch --parsable -p amd -J bgp_r_mem1d_amd --array=0-19%4 \
  --export=ALL,R_MEM1D_PAIR_ID="$PAIR_ID",R_MEM1D_ADOPT_ROOT="$ADOPT_ROOT" "$ARRAY_SCRIPT")
echo "amd_array_job_id=$AMD_ARRAY" | tee -a "$RECORD"
AMD_VALIDATOR=$(sbatch --parsable -p amd -J bgp_r_mem1d_val_amd \
  --dependency=afterany:"$AMD_ARRAY" \
  --export=ALL,R_MEM1D_PAIR_ID="$PAIR_ID",R_MEM1D_SOURCE_PARTITION=amd,R_MEM1D_ARRAY_JOB_ID="$AMD_ARRAY" \
  "$VALIDATOR_SCRIPT")
echo "amd_validator_job_id=$AMD_VALIDATOR" | tee -a "$RECORD"

INTEL_ARRAY=$(sbatch --parsable -p intel -J bgp_r_mem1d_intel --array=0-19%4 \
  --export=ALL,R_MEM1D_PAIR_ID="$PAIR_ID",R_MEM1D_ADOPT_ROOT="$ADOPT_ROOT" "$ARRAY_SCRIPT")
echo "intel_array_job_id=$INTEL_ARRAY" | tee -a "$RECORD"
INTEL_VALIDATOR=$(sbatch --parsable -p intel -J bgp_r_mem1d_val_intel \
  --dependency=afterany:"$INTEL_ARRAY" \
  --export=ALL,R_MEM1D_PAIR_ID="$PAIR_ID",R_MEM1D_SOURCE_PARTITION=intel,R_MEM1D_ARRAY_JOB_ID="$INTEL_ARRAY" \
  "$VALIDATOR_SCRIPT")
echo "intel_validator_job_id=$INTEL_VALIDATOR" | tee -a "$RECORD"

echo "submission_record=$RECORD"
echo "Both partition runs are isolated and scientifically duplicate. Cancel the later-starting array when convenient; either complete run is independently valid."
