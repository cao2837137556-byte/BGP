#!/usr/bin/env bash
set -euo pipefail

BASE=${BASE:-/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline}
REPO=${REPO:-$BASE/repo}
DATA_ROOT=${DATA_ROOT:-$BASE/data_store}
IMG=${IMG:-$BASE/containers/bgpstream-py-e9a.sif}
PAIR_ID=${1:?usage: r_mem1c_complete_file_measure_preflight.sh PAIR_ID}
SLURM_SCRIPT=$REPO/scripts/hpc/r_mem1c_complete_file_measure.slurm
PAIR_ROOT=$DATA_ROOT/derived/r_mem1c_complete_file_measure_v01/pair=$PAIR_ID

if [[ ! "$PAIR_ID" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "Invalid pair ID: $PAIR_ID" >&2
  exit 2
fi

echo "pair_id=$PAIR_ID"
echo "repo=$REPO"
echo "commit=$(git -C "$REPO" rev-parse --short HEAD)"
echo "pair_root=$PAIR_ROOT"

test -f "$SLURM_SCRIPT"
test -f "$REPO/scripts/run_r_mem1c_local_mrt_parser_smoke.py"
test -f "$REPO/configs/r_mem1c_complete_file_measure_v01.json"
test -f "$IMG"
test -f "$DATA_ROOT/manifests/r_mem1b_10d_direct_archive_v01/full/download_manifest.json"
test -f "$DATA_ROOT/manifests/r_mem1b_10d_direct_archive_v01/post_transfer_sha256_audit.json"
test -f "$DATA_ROOT/derived/r_mem1c_singlefile_liveness_v01/r_mem1c_liveness_summary.json"
if [ -d "$PAIR_ROOT" ] && [ -n "$(find "$PAIR_ROOT" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
  echo "Refusing duplicate pair ID with existing outputs: $PAIR_ROOT" >&2
  exit 2
fi

RAW_COUNT=$(find "$DATA_ROOT/raw_mrt/r_mem1b_10d_direct_archive_v01" \
  -type f \( -name '*.gz' -o -name '*.bz2' \) | wc -l)
PART_COUNT=$(find "$DATA_ROOT/raw_mrt/r_mem1b_10d_direct_archive_v01" \
  -type f -name '*.part' | wc -l)
echo "raw_archive_count=$RAW_COUNT"
echo "partial_file_count=$PART_COUNT"
test "$RAW_COUNT" -eq 3840
test "$PART_COUNT" -eq 0

bash -n "$SLURM_SCRIPT"
bash -n "$0"

module purge
module load apps/apptainer/1.4.5-2

COMMON_BIND=(
  --bind "$REPO":/work
  --bind "$DATA_ROOT":/data_store
)

apptainer exec "${COMMON_BIND[@]}" "$IMG" \
  /opt/venv/bin/python -m py_compile \
  /work/scripts/run_r_mem1c_local_mrt_parser_smoke.py
apptainer exec "${COMMON_BIND[@]}" "$IMG" \
  /opt/venv/bin/python -c \
  'import json; from pathlib import Path; p=Path("/data_store/derived/r_mem1c_singlefile_liveness_v01/r_mem1c_liveness_summary.json"); s=json.loads(p.read_text()); assert s["diagnostic_completed"] is True; assert s["pybgpstream_liveness_passed"] is True; assert s["bgpreader_liveness_passed"] is True; assert s["source_integrity_passed"] is True; print("liveness_prerequisite=passed")'

sbatch --test-only -p amd -J bgp_r_mem1c_m_amd \
  --export=ALL,R_MEM1C_PAIR_ID="$PAIR_ID" "$SLURM_SCRIPT"
sbatch --test-only -p intel -J bgp_r_mem1c_m_intel \
  --export=ALL,R_MEM1C_PAIR_ID="$PAIR_ID" "$SLURM_SCRIPT"
echo "preflight=passed"
