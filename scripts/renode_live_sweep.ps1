<#
.SYNOPSIS
    Reproducible live Renode/Zephyr sweep: doctor -> generate/build/run/
    validate-artifacts every zephyr_nano33ble task -> (re)write the tracked
    evidence index -> summarize with the canonical/addition split.

.DESCRIPTION
    The Zephyr/Renode backend had no scripted, repeatable live run: results
    lived only in scattered, untracked verification.json files from a single
    dev session. This script is that missing command. It does not judge the
    harness for you; it just drives the real loop end to end and summarizes
    each task's verdict (BC/BF/CF/IF or an error) so a human can see, in one
    place, what currently passes live.

    Per task it runs generate -> build -> run and then `validate-artifacts`,
    which re-judges the just-produced serial/VCD + verification.json WITHOUT
    re-simulating; a mismatch between that and the run verdict is flagged. At
    the end it calls `evidence-index` to aggregate the (gitignored) per-task
    verification.json manifests into the durable, tracked proof artifact
    docs/zephyr_nano33ble-evidence.json, then prints the readiness split as
    "42 canonical + 1 addition" (the addition `lsm9ds1_read_i2c` is scored-out).
    The per-run dump (-OutFile, default zephyr-live-status.json) stays UNTRACKED
    (.gitignore); the evidence index is the tracked truth.

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
        task_id         = $id
        level           = $lvl
        generate        = $null
        build           = $null
        run             = $null
        result          = $null
        classification  = $null
        reason          = $null
        validate        = $null   # did validate-artifacts reproduce the run verdict?
        validate_result = $null   # result string validate-artifacts reported
        error           = $null
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

        # Re-validate the artifacts the run just produced WITHOUT re-running the
        # simulator. This is the independent provenance/oracle check the
        # evidence index later aggregates: it confirms the on-disk serial/VCD
        # plus verification.json still judge to the same verdict. Pass = it
        # reproduced the run's result (most often BC).
        if ($entry.run -and $entry.result) {
            $valResult = Invoke-BenchJson (@("validate-artifacts") + $sel)
            if ($valResult.Json) {
                $entry.validate_result = $valResult.Json.result
                $entry.validate = ($valResult.Code -eq 0) -and ($valResult.Json.result -eq $entry.result)
            } else {
                $entry.validate = $false
                $entry.error = "validate-artifacts produced no parseable JSON (exit $($valResult.Code))"
            }
        }
    } catch {
        $entry.error = $_.Exception.Message
        Write-Warning "$id failed: $($_.Exception.Message)"
    }

    $report += [pscustomobject]$entry
    $verdict = if ($entry.result) { $entry.result } elseif ($entry.error) { "ERROR" } else { "?" }
    Write-Host "   => $verdict" -ForegroundColor Green
}

# The per-run dump ($OutFile, default zephyr-live-status.json) is a transient,
# UNTRACKED local artifact (.gitignore). The durable, tracked proof artifact is
# the evidence index written below; do not re-track this dump.
$report | ConvertTo-Json -Depth 5 | Out-File -FilePath $OutFile -Encoding utf8

Write-Host "`n== this-run verdicts ==" -ForegroundColor Cyan
$report | Group-Object { if ($_.result) { $_.result } elseif ($_.error) { "ERROR" } else { "?" } } |
    ForEach-Object { Write-Host ("  {0,-6} {1}" -f $_.Name, $_.Count) }
$valFail = @($report | Where-Object { $_.run -and $_.result -and ($_.validate -ne $true) })
if ($valFail.Count -gt 0) {
    Write-Host ("  validate-artifacts MISMATCH on {0} task(s): {1}" -f $valFail.Count, ($valFail.task_id -join ", ")) -ForegroundColor Red
} else {
    Write-Host "  validate-artifacts reproduced every run verdict" -ForegroundColor Green
}
Write-Host "this-run dump written to $OutFile (untracked)"

# Aggregate the gitignored verification.json manifests into the tracked,
# machine-checkable proof artifact docs/<platform>-evidence.json. Its summary
# carries the canonical/addition split (canonical_total / canonical_fresh_bc /
# addition_total) computed against the vendored upstream manifest.
Write-Host "`n== evidence index (proof artifact) ==" -ForegroundColor Cyan
$idxResult = Invoke-BenchJson @("evidence-index", "--platform", $platform)
if ($idxResult.Json) {
    $s = $idxResult.Json.summary
    Write-Host ("  written: {0}" -f $idxResult.Json.output)
    Write-Host ("  canonical: {0} task(s), fresh BC = {1}" -f $s.canonical_total, $s.canonical_fresh_bc) -ForegroundColor Green
    Write-Host ("  addition (non-canonical, scored-out): {0} task(s)" -f $s.addition_total)
    Write-Host ("  all-tasks fresh_bc (incl. addition): {0} / {1}" -f $s.fresh_bc, $s.total)
    if ($s.canonical_fresh_bc -lt $s.canonical_total) {
        Write-Host ("  NOT YET leaderboard-ready: {0} canonical task(s) lack fresh BC" -f ($s.canonical_total - $s.canonical_fresh_bc)) -ForegroundColor Yellow
    } else {
        Write-Host "  all 42 canonical tasks have fresh BC" -ForegroundColor Green
    }
} else {
    Write-Warning "evidence-index produced no parseable JSON (exit $($idxResult.Code)); see output above"
}
