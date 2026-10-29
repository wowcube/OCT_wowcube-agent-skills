<#
.SYNOPSIS
    Stop a hidden simulator that run.ps1 started (an MCP playtest you are done with), safely.

.DESCRIPTION
    Reads <out>\run_info.json written by run.ps1 and stops that PID only when it still runs the same exe and
    started at the recorded time: a finished run's PID may since belong to another program (PID reuse), and a bare
    kill by PID alone would hit it. Never stops anything by name.

    Exit codes: 0 stopped (or already gone) | 1 usage error | 2 the PID now belongs to another process (left running)

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File tools\sim_headless\stop.ps1 -RunInfo C:\ws\.sim_headless\app_x\frames\20261028_120000\run_info.json
#>
[CmdletBinding()]
param([Parameter(Mandatory = $true)] [string] $RunInfo)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'hidden_launch.ps1')

if (-not (Test-Path -LiteralPath $RunInfo)) { Write-Host "FAIL: $RunInfo not found" -ForegroundColor Red; exit 1 }
$info = Get-Content -LiteralPath $RunInfo -Raw | ConvertFrom-Json
if (-not $info.pid -or -not $info.exe) { Write-Host "FAIL: $RunInfo has no pid/exe" -ForegroundColor Red; exit 1 }
$res = Stop-OwnedProcess -ProcessId ([int]$info.pid) -Exe ([string]$info.exe) -StartTime ([string]$info.start_time)
"pid $($info.pid): $res"
if ($res -like 'mismatch*') { exit 2 }
exit 0
