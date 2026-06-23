#!/usr/bin/env bash
set -euo pipefail

BASE=${BASE:-/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline}
REPO=${REPO:-$BASE/repo}
IMG=${IMG:-$BASE/containers/bgpstream-py-e9a.sif}
MANIFEST=${MANIFEST:-$REPO/configs/r_attack0a3_required_assets_manifest.json}
OUTPUT=${OUTPUT:-$BASE/logs/r_attack0a3_remote_preflight.json}

mkdir -p "$BASE/logs" "$BASE/tmp/apptainer-tmp" "$BASE/tmp/apptainer-cache"

python3 "$REPO/scripts/hpc/verify_r_attack0a3_assets.py" \
  --manifest "$MANIFEST" \
  --repo-root "$REPO" \
  --container "$IMG" \
  --output "$OUTPUT" \
  --summary-only

module purge
module load apps/apptainer/1.4.5-2
export APPTAINER_TMPDIR=$BASE/tmp/apptainer-tmp
export APPTAINER_CACHEDIR=$BASE/tmp/apptainer-cache

apptainer exec --bind "$REPO":/work "$IMG" /bin/bash -lc '
set -euo pipefail
cd /work
/opt/venv/bin/python -c "import pandas, pyarrow; print(\"container_python_ok\")"
/opt/venv/bin/python -m py_compile \
  scripts/materialize_r_attack0a2_hardened_smoke.py \
  scripts/audit_r_attack0a_origin_propagation.py \
  scripts/audit_r_attack0a2_hardened_qa.py \
  scripts/hpc/validate_r_attack0a3_full_replay.py
'

echo "R-ATTACK-0A-3 preflight passed."
