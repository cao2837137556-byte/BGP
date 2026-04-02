param(
    [string]$Image = "bgpstream-py",
    [string]$Windows = "2017-07-07 00:00:00;2017-07-07 00:05:00;2017-07-07 00:10:00;2017-07-07 00:20:00",
    [int]$Minutes = 5,
    [string]$Collectors = "route-views.sg,rrc00",
    [int]$MaxRows = 3000
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-DockerPython {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$PyArgs
    )
    $cmd = @("run", "--rm", "-v", "${PWD}:/work", "-w", "/work", $Image, "python") + $PyArgs
    Write-Host "[RUN] docker $($cmd -join ' ')"
    docker @cmd
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: python $($PyArgs -join ' ')"
    }
}

$outDir = Join-Path "论文" "实验执行_E4_稳定性_v01"
New-Item -ItemType Directory -Path $outDir -Force | Out-Null

$starts = $Windows.Split(";") | ForEach-Object { $_.Trim() } | Where-Object { $_ }
if (-not $starts -or $starts.Count -eq 0) {
    throw "No valid windows found in --Windows."
}

$newRunIds = @()

foreach ($startStr in $starts) {
    $start = [datetime]::ParseExact($startStr, "yyyy-MM-dd HH:mm:ss", $null)
    $end = $start.AddMinutes($Minutes)
    $runId = "e4_{0}_{1}" -f $start.ToString("yyyyMMddTHHmmss"), $end.ToString("HHmmss")
    Write-Host ""
    Write-Host "=== E4 window $startStr -> $($end.ToString('yyyy-MM-dd HH:mm:ss')) run_id=$runId ==="

    Invoke-DockerPython -PyArgs @(
        "scripts/run.py",
        "--run-id", $runId,
        "--from", $startStr,
        "--minutes", "$Minutes",
        "--chunk-minutes", "$Minutes",
        "--collectors", $Collectors,
        "--record-type", "updates",
        "--format", "parquet",
        "--max-rows", "$MaxRows",
        "--print-head", "5"
    )

    Invoke-DockerPython -PyArgs @("scripts/build_event_units.py", "--run-id", $runId, "--window-sec", "300", "--prefer-rel", "true")
    Invoke-DockerPython -PyArgs @("scripts/build_historical_baseline.py", "--run-id", $runId, "--min-events", "1", "--overwrite", "true")
    Invoke-DockerPython -PyArgs @("scripts/build_weak_candidates.py", "--run-id", $runId, "--min-weak-rules", "2", "--overwrite", "true")
    Invoke-DockerPython -PyArgs @("scripts/score_weak_candidates.py", "--run-id", $runId, "--overwrite", "true")
    Invoke-DockerPython -PyArgs @("scripts/gate_scored_candidates.py", "--run-id", $runId, "--overwrite", "true")
    Invoke-DockerPython -PyArgs @("scripts/augment_uncertain_candidates.py", "--run-id", $runId, "--overwrite", "true")
    Invoke-DockerPython -PyArgs @("scripts/build_final_alerts.py", "--run-id", $runId, "--overwrite", "true")

    $newRunIds += $runId
}

$newRunIdsPath = Join-Path $outDir "e4_new_run_ids.txt"
$newRunIds | Set-Content -Path $newRunIdsPath -Encoding utf8
Write-Host ""
Write-Host "[DONE] New run_ids written to $newRunIdsPath"
