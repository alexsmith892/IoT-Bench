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
    & python -m bench.cli @BenchArgs
    return $LASTEXITCODE
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
    $tasks += [pscustomobject]@{ Id = $Task; Level = $null }
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
    Write-Host "-- $id --" -ForegroundColor Yellow
    $entry = [ordered]@{
        task_id   = $id
        level     = $t.Level
        generate  = $null
        build     = $null
        run       = $null
        result    = $null
        reason    = $null
        error     = $null
    }

    try {
        $entry.generate = (Invoke-Bench @("generate", "--task", $id)) -eq 0
        $entry.build    = (Invoke-Bench @("build", "--task", $id)) -eq 0
        $runCode        = Invoke-Bench @("run", "--task", $id)
        $entry.run      = $runCode -eq 0

        # The run writes verification.json under the case dir; read the verdict.
        $caseGlob = Join-Path $repoRoot "cases\*$($id.Replace('_','-'))*\artifacts\verification.json"
        $vfile = Get-ChildItem -Path $caseGlob -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($vfile) {
            $v = Get-Content $vfile.FullName -Raw | ConvertFrom-Json
            $entry.result = $v.result
            $entry.reason = $v.reason
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
