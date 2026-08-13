#!/usr/bin/env bash
set -euo pipefail

BASE=${BASE:-/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline}
REPO=${REPO:-$BASE/repo}
DATA_ROOT=${DATA_ROOT:-$BASE/data_store}
PAIR_ID=${1:-n_frontend3b_$(date -u +%Y%m%dT%H%M%SZ)}
SOURCE_PAIR=${2:-n_frontend2b_20260805T023615Z}
AMD_SOURCE=${3:-$DATA_ROOT/derived/n_frontend2b_bounded_replay_v01/pair=$SOURCE_PAIR/partition=amd/job=157343/result}
INTEL_SOURCE=${4:-$DATA_ROOT/derived/n_frontend2b_bounded_replay_v01/pair=$SOURCE_PAIR/partition=intel/job=157344/result}
JOB_SCRIPT=$REPO/scripts/hpc/n_frontend3b_bounded_replay.slurm
RECORD=$BASE/logs/n_frontend3b_pair_${PAIR_ID}.txt

bash "$REPO/scripts/hpc/n_frontend3b_bounded_replay_preflight.sh" \
  "$PAIR_ID" "$AMD_SOURCE" "$INTEL_SOURCE"
mkdir -p "$BASE/logs"
COMMIT=$(python -c 'import json,sys; print(json.load(open(sys.argv[1]))["source_commit"])' "$REPO/N_FRONTEND3B_PACKAGE_MANIFEST.json")
FINGERPRINT=$(sha256sum "$REPO/N_FRONTEND3B_PACKAGE_MANIFEST.json" | awk '{print $1}')
{
  echo "pair_id=$PAIR_ID"
  echo "submitted_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "commit=$COMMIT"
  echo "package_manifest_sha256=$FINGERPRINT"
  echo "source_2b_pair=$SOURCE_PAIR"
  echo "amd_source=$AMD_SOURCE"
  echo "intel_source=$INTEL_SOURCE"
  echo "resources=cpus:2,memory:16G,time:02:00:00"
} | tee "$RECORD"

AMD_JOB=$(sbatch --parsable -p amd -J bgp_n_front3b_amd \
  --export=ALL,N_FRONTEND3B_PAIR_ID="$PAIR_ID",N_FRONTEND3B_SOURCE_2B_ROOT="$AMD_SOURCE" \
  "$JOB_SCRIPT")
echo "amd_job_id=$AMD_JOB" | tee -a "$RECORD"
INTEL_JOB=$(sbatch --parsable -p intel -J bgp_n_front3b_intel \
  --export=ALL,N_FRONTEND3B_PAIR_ID="$PAIR_ID",N_FRONTEND3B_SOURCE_2B_ROOT="$INTEL_SOURCE" \
  "$JOB_SCRIPT")
echo "intel_job_id=$INTEL_JOB" | tee -a "$RECORD"
echo "submission_record=$RECORD"
echo "Both jobs are independently valid and write partition/job-isolated outputs."
