#!/usr/bin/env bash
set -uo pipefail

if [ "$#" -lt 2 ]; then
  echo "usage: run_with_portable_timing.sh TIME_FILE COMMAND [ARG ...]" >&2
  exit 2
fi

TIME_FILE=$1
shift

mkdir -p "$(dirname "$TIME_FILE")"
STARTED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
START_EPOCH=$(date +%s)

set +e
"$@"
STATUS=$?
set -e

FINISHED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
FINISH_EPOCH=$(date +%s)
ELAPSED_SECONDS=$((FINISH_EPOCH - START_EPOCH))

{
  echo "timing_contract=portable_wall_clock_v1"
  echo "started_at=$STARTED_AT"
  echo "finished_at=$FINISHED_AT"
  echo "elapsed_seconds=$ELAPSED_SECONDS"
  echo "command_exit_code=$STATUS"
  echo "resource_usage_source=slurm_sacct"
  echo "resource_usage_note=Use Slurm accounting for MaxRSS and CPU allocation."
} > "$TIME_FILE"

exit "$STATUS"
