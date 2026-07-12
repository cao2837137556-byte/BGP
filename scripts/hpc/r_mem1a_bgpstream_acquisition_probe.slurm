#!/usr/bin/env bash
#SBATCH -J bgp_r_mem_probe
#SBATCH -p intel
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -c 1
#SBATCH --mem=4G
#SBATCH -t 00:08:00
#SBATCH -o /public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/logs/%x_%j.out
#SBATCH -e /public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline/logs/%x_%j.err

set -euo pipefail

BASE=${BASE:-/public/home/jiangxinwei.zr/work/bgp-platform-exp-mainline}
REPO=${REPO:-$BASE/repo}
IMG=${IMG:-$BASE/containers/bgpstream-py-e9a.sif}
OUT_ROOT=${OUT_ROOT:-outputs/r_mem1a_acquisition_probe/$SLURM_JOB_ID}
LIVE_LOG=${BASE}/logs/r_mem1a_probe_${SLURM_JOB_ID}.live.log

mkdir -p "$BASE/logs" "$BASE/tmp/apptainer-tmp" "$BASE/tmp/apptainer-cache" "$REPO/$OUT_ROOT"
export APPTAINER_TMPDIR=$BASE/tmp/apptainer-tmp
export APPTAINER_CACHEDIR=$BASE/tmp/apptainer-cache
exec > >(tee -a "$LIVE_LOG") 2>&1

echo "job_id=$SLURM_JOB_ID"
echo "node_list=$SLURM_NODELIST"
echo "repo=$REPO"
echo "output_root=$OUT_ROOT"
echo "live_log=$LIVE_LOG"

module purge
module load apps/apptainer/1.4.5-2

run_probe() {
  local name=$1
  local hard_timeout=$2
  shift 2
  local started finished exit_code command timed_out
  printf -v command '%q ' \
    /opt/venv/bin/python scripts/probe_r_mem1a_bgpstream_acquisition.py "$@"
  started=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  set +e
  timeout --kill-after=10s "${hard_timeout}s" \
    apptainer exec --bind "$REPO":/work "$IMG" /bin/bash -lc \
      "cd /work && $command"
  exit_code=$?
  set -e
  finished=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  timed_out=false
  if [ "$exit_code" -eq 124 ] || [ "$exit_code" -eq 137 ]; then
    timed_out=true
  fi
  printf '{\n  "probe_name": "%s",\n  "started_at": "%s",\n  "finished_at": "%s",\n  "hard_timeout_sec": %s,\n  "exit_code": %s,\n  "timed_out": %s\n}\n' \
    "$name" "$started" "$finished" "$hard_timeout" "$exit_code" \
    "$timed_out" \
    > "$REPO/$OUT_ROOT/${name}_runner.json"
  echo "probe=$name exit_code=$exit_code"
}

run_probe broker_routeviews 45 \
  --mode broker \
  --project routeviews \
  --http-timeout-sec 20 \
  --output-json "$OUT_ROOT/broker_routeviews.json"

run_probe broker_ris 45 \
  --mode broker \
  --project ris \
  --http-timeout-sec 20 \
  --output-json "$OUT_ROOT/broker_ris.json"

run_probe stream_routeviews_sg 120 \
  --mode stream \
  --collector route-views.sg \
  --from-time '2024-04-16 00:00:00' \
  --until-time '2024-04-16 00:15:00' \
  --max-elements 1 \
  --output-json "$OUT_ROOT/stream_routeviews_sg.json"

run_probe stream_rrc00 120 \
  --mode stream \
  --collector rrc00 \
  --from-time '2024-04-16 00:00:00' \
  --until-time '2024-04-16 00:05:00' \
  --max-elements 1 \
  --output-json "$OUT_ROOT/stream_rrc00.json"

ARCHIVE="$BASE/tmp/r_mem1a_acquisition_probe_${SLURM_JOB_ID}.tar.gz"
tar -czf "$ARCHIVE" -C "$REPO" "$OUT_ROOT"
mv "$ARCHIVE" "$REPO/$OUT_ROOT/r_mem1a_acquisition_probe_small_results.tar.gz"
echo "probe_outcome=diagnostic_complete"
echo "small_results=$REPO/$OUT_ROOT/r_mem1a_acquisition_probe_small_results.tar.gz"
