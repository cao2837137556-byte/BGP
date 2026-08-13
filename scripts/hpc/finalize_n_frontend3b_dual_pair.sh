#!/usr/bin/env bash
set -euo pipefail

BASE=${BASE:-/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline}
REPO=${REPO:-$BASE/repo}
DATA_ROOT=${DATA_ROOT:-$BASE/data_store}
IMG=${IMG:-$BASE/containers/bgpstream-py-e9a.sif}
RECORD=${1:-$(find "$BASE/logs" -maxdepth 1 -type f -name 'n_frontend3b_pair_*.txt' -printf '%T@ %p\n' | sort -nr | head -1 | cut -d' ' -f2-)}

test -n "$RECORD"
test -f "$RECORD"
value() { awk -F= -v key="$1" '$1 == key {print substr($0, length(key) + 2)}' "$RECORD" | tail -1; }
PAIR_ID=$(value pair_id)
AMD_JOB=$(value amd_job_id)
INTEL_JOB=$(value intel_job_id)
for VALUE in "$PAIR_ID" "$AMD_JOB" "$INTEL_JOB"; do
  [[ "$VALUE" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "Invalid submission record value: $VALUE" >&2; exit 2; }
done

state() {
  sacct -X -n -j "$1" --format=State | awk 'NF {sub(/\+.*/, "", $1); print $1; exit}'
}
exit_code() {
  sacct -X -n -j "$1" --format=ExitCode | awk 'NF {print $1; exit}'
}
for JOB in "$AMD_JOB" "$INTEL_JOB"; do
  STATE=$(state "$JOB")
  CODE=$(exit_code "$JOB")
  echo "job=$JOB state=$STATE exit_code=$CODE"
  test "$STATE" = "COMPLETED"
  test "$CODE" = "0:0"
done

PAIR_ROOT=$DATA_ROOT/derived/n_frontend3b_bounded_replay_v01/pair=$PAIR_ID
AMD_ROOT=$PAIR_ROOT/partition=amd/job=$AMD_JOB
INTEL_ROOT=$PAIR_ROOT/partition=intel/job=$INTEL_JOB
for ROOT in "$AMD_ROOT" "$INTEL_ROOT"; do
  test -f "$ROOT/n_frontend3b_validation.json"
  test -f "$ROOT/n_frontend3b_small_results.tar.gz"
  test -f "$ROOT/result/n_frontend3b_summary.json"
done

module purge
module load apps/apptainer/1.4.5-2
PARITY_DIR=$PAIR_ROOT/parity
mkdir -p "$PARITY_DIR"
apptainer exec \
  --bind "$REPO":/work \
  --bind "$DATA_ROOT":/data_store \
  "$IMG" /opt/venv/bin/python \
  /work/scripts/validate_n_frontend3b_dual_parity.py \
  --amd-result "/data_store/${AMD_ROOT#"$DATA_ROOT"/}/result" \
  --intel-result "/data_store/${INTEL_ROOT#"$DATA_ROOT"/}/result" \
  --output "/data_store/${PARITY_DIR#"$DATA_ROOT"/}/n_frontend3b_dual_parity.json"

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
STAGE=$BASE/tmp/n_frontend3b_pullback_stage_${PAIR_ID}_$STAMP
ARCHIVE=$BASE/tmp/n_frontend3b_pullback_${PAIR_ID}_$STAMP.tar.gz
mkdir -p "$STAGE/amd" "$STAGE/intel" "$STAGE/logs"
cp "$RECORD" "$STAGE/submission_record.txt"
cp "$PARITY_DIR/n_frontend3b_dual_parity.json" "$STAGE/"
cp "$AMD_ROOT/n_frontend3b_validation.json" "$STAGE/amd/"
cp "$AMD_ROOT/n_frontend3b_small_results.tar.gz" "$STAGE/amd/"
cp "$INTEL_ROOT/n_frontend3b_validation.json" "$STAGE/intel/"
cp "$INTEL_ROOT/n_frontend3b_small_results.tar.gz" "$STAGE/intel/"
find "$BASE/logs" -maxdepth 1 -type f \
  \( -name "*_${AMD_JOB}.*" -o -name "*_${INTEL_JOB}.*" \) \
  -exec cp {} "$STAGE/logs/" \;
tar -czf "$ARCHIVE" -C "$STAGE" .
sha256sum "$ARCHIVE" | tee "$ARCHIVE.sha256"
echo "__TAR__=$ARCHIVE"
echo "stage_retained_for_audit=$STAGE"
