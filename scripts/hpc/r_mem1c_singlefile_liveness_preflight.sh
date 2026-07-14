#!/usr/bin/env bash
set -euo pipefail

BASE=${BASE:-/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline}
REPO=${REPO:-$BASE/repo}
DATA_ROOT=${DATA_ROOT:-$BASE/data_store}
IMG=${IMG:-$BASE/containers/bgpstream-py-e9a.sif}
SLURM_SCRIPT=$REPO/scripts/hpc/r_mem1c_singlefile_liveness.slurm
PROBE_SCRIPT=$REPO/scripts/probe_r_mem1c_singlefile_liveness.py

echo "repo=$REPO"
echo "commit=$(git -C "$REPO" rev-parse --short HEAD)"
echo "data_root=$DATA_ROOT"
echo "image=$IMG"

test -f "$SLURM_SCRIPT"
test -f "$PROBE_SCRIPT"
test -f "$IMG"
test -f "$DATA_ROOT/manifests/r_mem1b_10d_direct_archive_v01/full/download_manifest.json"
test -f "$DATA_ROOT/manifests/r_mem1b_10d_direct_archive_v01/post_transfer_sha256_audit.json"

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
  /work/scripts/probe_r_mem1c_singlefile_liveness.py
apptainer exec "${COMMON_BIND[@]}" "$IMG" \
  /opt/venv/bin/python \
  /work/scripts/probe_r_mem1c_singlefile_liveness.py --self-test
apptainer exec "${COMMON_BIND[@]}" "$IMG" /bin/bash -lc \
  'set -euo pipefail; /opt/venv/bin/python -c "import pybgpstream; print(\"pybgpstream_import=passed\")"; if command -v bgpreader >/dev/null; then echo "bgpreader_present=yes"; else echo "bgpreader_present=no"; fi'

sbatch --test-only "$SLURM_SCRIPT"
echo "preflight=passed"
