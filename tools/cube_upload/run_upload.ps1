<#
.SYNOPSIS
    Upload one .oct to the user's paired WowCube over Bluetooth SPP, with no window and no dialog.

.DESCRIPTION
    Only when the user asked for an upload, and only to the cube they named. Builds cube_upload.exe on first
    use (build.ps1), starts it hidden (killed by PID if any window ever becomes visible), waits for the result
    and prints the [UPLOAD] log lines. The cube must already be paired in Windows Bluetooth settings.

    Exit codes: 0 SUCCESS | 1 usage/setup error | 2 a window became visible (killed) | 3 timeout (killed)
                | 10 FAILED (cube refused / CRC / flash) | 11 ABORTED (link dropped or stalled: rerun once)
                | 12 NO_CONNECTION (not paired, off, out of range) | 13 no result written

.PARAMETER Mac        Cube address: AA:BB:CC:DD:EE:FF, AA-BB-..., AABBCCDDEEFF or 0xAABBCCDDEEFF.
.PARAMETER Oct        The .oct to upload (normally <workspace>\dist\app_<game>.oct from scripts\build_device.*).
.PARAMETER Name       Label for the log (e.g. the cube's Bluetooth name). Optional.
.PARAMETER Octavios   Needed to build the uploader on first use, and to find the default work dir.
.PARAMETER WorkDir    Default: <Octavios>\..\.cube_upload (same rule as build.ps1).
.PARAMETER ConnectSec Give up when no SPP link comes up within this many seconds. Default 60.
.PARAMETER TimeoutSec Hard limit for the whole run. Default 600.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File tools\cube_upload\run_upload.ps1 -Octavios C:\ws\octavios -Mac AA:BB:CC:DD:EE:FF -Oct C:\ws\dist\app_tetris.oct
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $Mac,
    [Parameter(Mandatory = $true)] [string] $Oct,
    [string] $Name = '',
    [string] $Octavios,
    [string] $WorkDir,
    [int]    $ConnectSec = 60,
    [int]    $TimeoutSec = 600,
    [switch] $Rebuild
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\sim_headless\hidden_launch.ps1')
function Fail($code, $m) { Write-Host "FAIL: $m" -ForegroundColor Red; exit $code }

$hex = ($Mac -replace '^0x', '' -replace '[:\-\s]', '').ToUpperInvariant()
if ($hex -notmatch '^[0-9A-F]{12}$') { Fail 1 "bad -Mac '$Mac' (expected 12 hex digits, e.g. AA:BB:CC:DD:EE:FF)" }
$macArg = "0x$hex"
$Oct = (Resolve-Path -LiteralPath $Oct -ErrorAction SilentlyContinue).Path
if (-not $Oct) { Fail 1 ".oct not found" }
$size = (Get-Item -LiteralPath $Oct).Length
if ($size -le 0 -or $size -gt 50MB) { Fail 1 "$Oct is $size bytes (the uploader takes 1 byte .. 50 MB)" }

if (-not $Octavios -and $env:OCTAVIOS_DIR) { $Octavios = $env:OCTAVIOS_DIR }
if ($Octavios) { $Octavios = (Resolve-Path -LiteralPath $Octavios).Path }
if (-not $WorkDir) {
    if (-not $Octavios) { Fail 1 "pass -Octavios (or -WorkDir of an existing build)" }
    $WorkDir = Join-Path (Split-Path $Octavios -Parent) '.cube_upload'
}
$exe = Join-Path $WorkDir 'bin\cube_upload.exe'
if ($Rebuild -or -not (Test-Path $exe)) {
    if (-not $Octavios) { Fail 1 "$exe not built yet: pass -Octavios" }
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'build.ps1') -Octavios $Octavios -WorkDir $WorkDir
    if ($LASTEXITCODE -ne 0) { Fail 1 "uploader build failed" }
}
$bin = Split-Path $exe -Parent
$resultFile = Join-Path $bin 'upload_result.txt'
Remove-Item $resultFile -ErrorAction SilentlyContinue
$logPath = Join-Path $bin 'log_1.txt'
$logStart = if (Test-Path $logPath) { (Get-Item $logPath).Length } else { 0 }

Write-Host "uploading $Oct ($size bytes) to $(if ($Name) { "$Name " })$macArg over Bluetooth SPP (window hidden, no sound)"
$r = Invoke-Hidden -Exe $exe -WorkDir $bin -TimeoutSec $TimeoutSec -Env @{
    CUBE_UPLOAD_MAC = $macArg; CUBE_UPLOAD_PATH = $Oct; CUBE_UPLOAD_NAME = $Name; CUBE_UPLOAD_CONNECT_SEC = "$ConnectSec" }

if (Test-Path $logPath) {
    $fs = [IO.File]::Open($logPath, 'Open', 'Read', 'ReadWrite')
    try { $null = $fs.Seek([Math]::Min($logStart, $fs.Length), 'Begin'); $buf = New-Object byte[] ($fs.Length - $fs.Position); $null = $fs.Read($buf, 0, $buf.Length) } finally { $fs.Close() }
    ([Text.Encoding]::UTF8.GetString($buf) -split "`r?`n") | Where-Object { $_ -match '\[UPLOAD\]' } | ForEach-Object { "  $_" }
}
"pid $($r.Pid) exit $($r.Exit) max_visible $($r.MaxVisible) (polled every 50 ms)"
if ($r.MaxVisible -gt 0) { Fail 2 "a window of the uploader became visible and was killed: $($r.FirstVisible)" }
if ($r.Exit -eq 'timeout') { Fail 3 "no result within $TimeoutSec s (killed by PID); rerun once, then reboot the cube" }
if (-not (Test-Path $resultFile)) { Fail 13 "no upload_result.txt (exit $($r.Exit)); see $logPath" }
$res = (Get-Content $resultFile -Raw).Trim()
"result: $res"
switch -Regex ($res) {
    '^status=SUCCESS'       { Write-Host "UPLOADED. If the game does not appear in the launcher, or the next upload cannot connect, reboot the cube." -ForegroundColor Green; exit 0 }
    '^status=NO_CONNECTION' { Fail 12 "no SPP link: is the cube paired in Windows Bluetooth settings, switched on, in range, and the MAC that of module 0?" }
    '^status=ABORTED'       { Fail 11 "the upload stopped part-way (e.g. stalled at chunk 0): rerun once; if it fails again, reboot the cube and rerun" }
    '^status=FAILED'        { Fail 10 "the cube rejected the upload (see the RESULT line above)" }
    default                 { Fail 13 "unexpected result: $res" }
}
