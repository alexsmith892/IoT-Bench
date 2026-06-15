<#
.SYNOPSIS
    Reproducible live Renode/Zephyr sweep: doctor -> generate/build/run every
    zephyr_nano33ble task -> collect a status report.

.DESCRIPTION
    The Zephyr/Renode backend had no scripted, repeatable live run: results
    lived only in scattered, untracked verification.json files from a single
    dev session. This script is that missing command. It does not judge the
    harness for you; it just drives the real loop end to end and summarizes
    each task's verdict (BC/BF/CF/IF or an error) so a human can see, in one
    place, what currently passes live.

    The verdict for each task is taken from the JSON the `run` command prints on
    stdout -- NOT by globbing for a verification.json file. An earlier version
    globbed `cases\*<task-with-dashes>*\artifacts\verification.json`, which
    silently matched same-named cases on OTHER platforms (e.g. the Wokwi Arduino
    or ESP32 build of the same task), reporting their BC verdicts as if they were
    Renode results. It also called `generate/build/run` without `--platform` /
    `--level`, so every invocation defaulted to arduino_mega/level1. Both bugs
    are fixed here: every CLI call is pinned to zephyr_nano33ble + the task's
    real level, and the verdict comes straight from the run payload.

    Requires Renode, west, and a Zephyr workspace (run the doctor step first).
    Nothing here runs in CI; it is local/manual by design.

.PARAMETER Level
    Restrict to a single level: level1 | level2 | level3. Default: all.

.PARAMETER Task
    Restrict to a single task id (overrides -Level).

.PARAMETER OutFile
    Where to write the JSON status report. Default: zephyr-live-status.json.

.PARAMETER SkipDoctor
    Skip the doctor precheck (use when you have already verified tooling).

.EXAMPLE
    pwsh scripts/renode_live_sweep.ps1
.EXAMPLE
    pwsh scripts/renode_live_sweep.ps1 -Level level1
.EXAMPLE
    pwsh scripts/renode_live_sweep.ps1 -Task blink_led_1hz
#>
[CmdletBinding()]
param(
    [ValidateSet("level1", "level2", "level3")]
    [string]$Level,
    [string]$Task,
    [string]$OutFile = "zephyr-live-status.json",
    [switch]$SkipDoctor
)

$ErrorActionPreference = "Stop"
$platform = "zephyr_nano33ble"

# Repo root = parent of this script's directory.
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

function Invoke-Bench {
    param([string[]]$BenchArgs)
    # Echo command output to the host (for live visibility) without letting it
    # leak into the function's return value; return only the exit code.
    & python -m bench.cli @BenchArgs | Out-Host
    return $LASTEXITCODE
}

# Run a bench command and return both its exit code and parsed JSON stdout.
function Invoke-BenchJson {
    param([string[]]$BenchArgs)
    $raw = & python -m bench.cli @BenchArgs 2>$null
    $code = $LASTEXITCODE
    $parsed = $null
    try {
        $parsed = ($raw | Out-String | ConvertFrom-Json)
    } catch {
        $parsed = $null
    }
    return [pscustomobject]@{ Code = $code; Json = $parsed; Raw = ($raw | Out-String) }
}

function Resolve-TaskLevel {
    param([string]$TaskId)
    foreach ($lvl in @("level1", "level2", "level3")) {
        $p = Join-Path $repoRoot "tasks/$platform/$lvl/$TaskId.yaml"
        if (Test-Path $p) { return $lvl }
    }
    return $null
}

if (-not $SkipDoctor) {
    Write-Host "== doctor ($platform) ==" -ForegroundColor Cyan
    $code = Invoke-Bench @("doctor", "--platform", $platform)
    if ($code -ne 0) {
        Write-Warning "doctor reported problems (exit $code). Tooling may be incomplete; continuing so partial results are still captured."
    }
}

# Resolve the task list from the task tree.
$levels = if ($Level) { @($Level) } else { @("level1", "level2", "level3") }
$tasks = @()
if ($Task) {
    $tasks += [pscustomobject]@{ Id = $Task; Level = (Resolve-TaskLevel $Task) }
} else {
    foreach ($lvl in $levels) {
        $dir = Join-Path $repoRoot "tasks/$platform/$lvl"
        if (-not (Test-Path $dir)) { continue }
        Get-ChildItem -Path $dir -Filter *.yaml | ForEach-Object {
            $tasks += [pscustomobject]@{ Id = $_.BaseName; Level = $lvl }
        }
    }
}

Write-Host "== sweeping $($tasks.Count) task(s) ==" -ForegroundColor Cyan
$report = @()

foreach ($t in $tasks) {
    $id = $t.Id
    $lvl = $t.Level
    Write-Host "-- $id ($lvl) --" -ForegroundColor Yellow
    $entry = [ordered]@{
        task_id        = $id
        level          = $lvl
        generate       = $null
        build          = $null
        run            = $null
        result         = $null
        classification = $null
        reason         = $null
        error          = $null
    }

    if (-not $lvl) {
        $entry.error = "could not resolve level for task '$id' under tasks/$platform"
        $report += [pscustomobject]$entry
        Write-Host "   => ERROR (no level)" -ForegroundColor Red
        continue
    }

    $sel = @("--task", $id, "--platform", $platform, "--level", $lvl)

    try {
        $entry.generate = (Invoke-Bench (@("generate") + $sel)) -eq 0
        $entry.build    = (Invoke-Bench (@("build") + $sel)) -eq 0

        $runResult      = Invoke-BenchJson (@("run") + $sel)
        $entry.run      = $runResult.Code -eq 0
        if ($runResult.Json) {
            $entry.result         = $runResult.Json.result
            $entry.classification = $runResult.Json.classification
            $entry.reason         = $runResult.Json.reason
        } else {
            $entry.error = "run produced no parseable JSON (exit $($runResult.Code))"
        }
    } catch {
        $entry.error = $_.Exception.Message
        Write-Warning "$id failed: $($_.Exception.Message)"
    }

    $report += [pscustomobject]$entry
    $verdict = if ($entry.result) { $entry.result } elseif ($entry.error) { "ERROR" } else { "?" }
    Write-Host "   => $verdict" -ForegroundColor Green
}

$report | ConvertTo-Json -Depth 5 | Out-File -FilePath $OutFile -Encoding utf8
Write-Host "`n== summary ==" -ForegroundColor Cyan
$report | Group-Object { if ($_.result) { $_.result } elseif ($_.error) { "ERROR" } else { "?" } } |
    ForEach-Object { Write-Host ("  {0,-6} {1}" -f $_.Name, $_.Count) }
Write-Host "report written to $OutFile"
