#!/usr/bin/env bash
#SBATCH -J bgp_n_front2b_feas
#SBATCH -p intel
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -c 2
#SBATCH --mem=32G
#SBATCH -t 02:00:00
#SBATCH -o /public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/logs/%x_%j.out
#SBATCH -e /public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/logs/%x_%j.err

set -euo pipefail

BASE=${BASE:-/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline}
REPO=${REPO:-$BASE/repo}
DATA_ROOT=${DATA_ROOT:-$BASE/data_store}
IMG=${IMG:-$BASE/containers/bgpstream-py-e9a.sif}
SOURCE_ROOT=${N_FRONTEND2B_SOURCE_ROOT:-$DATA_ROOT/derived/r_mem1e_10d_peer_aware_v02/pair=r_mem1e_20260721T130846Z/partition=amd/array_job=153044}
REPLAY_DATE=${N_FRONTEND2B_DATE:-2024-04-09}
DATES=${N_FRONTEND2B_DATES:-$REPLAY_DATE}
HOURS=${N_FRONTEND2B_HOURS:-00}
JOB_ID=${SLURM_JOB_ID:?SLURM_JOB_ID is required}

case "$SOURCE_ROOT" in
  "$DATA_ROOT"/*) ;;
  *) echo "Source root must be under $DATA_ROOT" >&2; exit 2 ;;
esac

OUT_DIR=$DATA_ROOT/derived/n_frontend2b_episode_feasibility/date=$REPLAY_DATE/job=$JOB_ID
JOB_TMP=$BASE/tmp/n_frontend2b_feasibility/$JOB_ID/apptainer-tmp
JOB_CACHE=$BASE/tmp/n_frontend2b_feasibility/$JOB_ID/apptainer-cache
test ! -e "$OUT_DIR"
mkdir -p "$OUT_DIR" "$JOB_TMP" "$JOB_CACHE" "$BASE/logs"
export APPTAINER_TMPDIR=$JOB_TMP
export APPTAINER_CACHEDIR=$JOB_CACHE

echo "phase=N-FRONTEND-2B-FEASIBILITY"
echo "job_id=$JOB_ID"
echo "dates=$DATES"
echo "hours=$HOURS"
echo "source_root=$SOURCE_ROOT"

module purge
module load apps/apptainer/1.4.5-2
COMMON_BIND=(
  --bind "$REPO":/work
  --bind "$DATA_ROOT":/data_store
  --bind "$BASE/tmp":/hpc_tmp
)

for DATE in $DATES; do
  if [[ ! "$DATE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    echo "Invalid date: $DATE" >&2
    exit 2
  fi
  for HOUR in $HOURS; do
    if [[ ! "$HOUR" =~ ^[0-2][0-9]$ ]] || [ "$HOUR" -gt 23 ]; then
      echo "Invalid hour: $HOUR" >&2
      exit 2
    fi
    declare -a INPUTS=()
    for COLLECTOR in route-views.sg rrc00; do
      while IFS= read -r MATCH; do
        INPUT_REL=${MATCH#"$DATA_ROOT"/}
        INPUTS+=(--input "/data_store/$INPUT_REL")
      done < <(
        find "$SOURCE_ROOT" -type f \
          -path "*/parsed/collector=$COLLECTOR/date=$DATE/updates__${HOUR}-*.parquet" \
          | sort
      )
    done
    if [ "${#INPUTS[@]}" -lt 2 ]; then
      echo "SKIP date=$DATE hour=$HOUR: missing collector inputs"
      continue
    fi
    START_TS=$(date -u -d "$DATE $HOUR:00:00" +%s)
    echo "audit date=$DATE hour=$HOUR start_ts=$START_TS inputs=${#INPUTS[@]}"
    apptainer exec "${COMMON_BIND[@]}" "$IMG" \
      /opt/venv/bin/python -u /work/scripts/audit_n_frontend2b_episode_feasibility.py \
      "${INPUTS[@]}" \
      --config /work/configs/n_frontend2b_controlled_pairs_v01.json \
      --start-ts "$START_TS" \
      --output "/data_store/derived/n_frontend2b_episode_feasibility/date=$REPLAY_DATE/job=$JOB_ID/date_${DATE}_hour_${HOUR}.json" \
      || echo "AUDIT_FAILED date=$DATE hour=$HOUR"
  done
done

echo "feasibility_reports=$OUT_DIR"
