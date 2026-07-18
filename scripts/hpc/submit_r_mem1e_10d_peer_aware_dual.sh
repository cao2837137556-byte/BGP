#!/usr/bin/env bash
set -euo pipefail

export CONFIG=${CONFIG:-configs/r_mem1e_10d_peer_aware_materialization_v02.json}
export R_MEM1D_SCHEMA_VERSION=${R_MEM1D_SCHEMA_VERSION:-v2}
export R_MEM1D_OUTPUT_DATASET=${R_MEM1D_OUTPUT_DATASET:-r_mem1e_10d_peer_aware_v02}
export R_MEM1D_ADOPT_ROOT=${R_MEM1D_ADOPT_ROOT:-}

BASE=${BASE:-/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline}
PAIR_ID=${1:-r_mem1e_$(date -u +%Y%m%dT%H%M%SZ)}

exec bash "$BASE/repo/scripts/hpc/submit_r_mem1d_10d_parquet_dual.sh" "$PAIR_ID"
