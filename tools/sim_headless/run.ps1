<#
.SYNOPSIS
    Run sim_headless.exe hidden and silent, dump PNGs of all 24 screens, and PROVE no window was ever visible.

.DESCRIPTION
    Starts the exe built by build.ps1 with SW_HIDE + CREATE_NO_WINDOW and --mcp-port <McpPort>, polls its
    top-level windows every 50 ms and kills it BY PID the moment any becomes visible (exit 2). The simulator
    exits by itself after -Seconds; MCP clients may drive it meanwhile (see README.md, mcp.ps1). Run this in
    the background when you want to talk MCP to the instance; it returns when the instance ends.

    Exit codes: 0 ok = the timed run COMPLETED (exit 0 after -Seconds and headless_summary.txt written; with
                -AllowEarlyStop also a run you stopped early) | 1 usage/setup error | 2 a window became visible
                (killed) | 3 did not end in time (killed) | 4 no frames written (-EveryMs > 0) | 5 crashed (exit 99,
                headless_crash.txt) | 6 exe older than the app (run build.ps1 again, or pass -AllowStale)
                | 7 ended before its timed exit (early exit, killed, no summary) without -AllowEarlyStop

.PARAMETER AppDir      The app the exe was built for (locates the default work dir and checks staleness).
.PARAMETER WorkDir     Default: <AppDir>\..\.sim_headless\<app> (same rule as build.ps1).
.PARAMETER Seconds     Lifetime after start-up; the simulator then closes itself. Default 10.
.PARAMETER EveryMs     PNG dump period of all 24 screens; 0 = no periodic dumps (MCP only). Default 500.
.PARAMETER Face        -1 = the six faces as an unfolded cross (default); 0..5 = TOP, FRONT, RIGHT, BACK, LEFT, BOTTOM.
.PARAMETER OutDir      Default: <WorkDir>\frames\<yyyyMMdd_HHmmss>.
.PARAMETER McpPort     First control-socket port to try (the sim takes the next free one up to +15). Default 8177,
                       away from the stock 8077 the user's own simulator uses.
.PARAMETER FreshSaves  Delete the simulated SD-card/flash images first (saves start empty).
.PARAMETER OctOut      Also write the simulator-assembled .oct to this path (diagnostics only; the deliverable
                       comes from scripts/build_device.*).
.PARAMETER AllowEarlyStop  Accept a run that ended before -Seconds without its summary (an MCP playtest you
                       stopped by PID when done). Crashes, visible windows, missing frames and timeouts still fail.
                       Without it such a run fails with exit 7.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File tools\sim_headless\run.ps1 -AppDir C:\ws\app_tetris -Seconds 5 -EveryMs 1000
#>
[CmdletBinding()]
param(
    [string] $AppDir,
    [string] $WorkDir,
    [string] $Exe,
    [int]    $Seconds = 10,
    [int]    $EveryMs = 500,
    [int]    $Face = -1,
    [string] $OutDir,
    [int]    $McpPort = 8177,
    [switch] $FreshSaves,
    [string] $OctOut,
    [switch] $AllowStale,
    [switch] $AllowEarlyStop
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'hidden_launch.ps1')
function Fail($code, $m) { Write-Host "FAIL: $m" -ForegroundColor Red; exit $code }

# --- resolve ---------------------------------------------------------------
$app = $null
if ($AppDir) {
    $AppDir = (Resolve-Path -LiteralPath $AppDir).Path
    $t = @(Get-ChildItem -LiteralPath $AppDir -Filter *.target -File)
    if ($t.Count -ne 1) { Fail 1 "$AppDir must hold exactly one *.target marker" }
    $app = [IO.Path]::GetFileNameWithoutExtension($t[0].Name)
    if (-not $WorkDir) { $WorkDir = Join-Path (Split-Path $AppDir -Parent) ".sim_headless\$app" }
}
if (-not $Exe) {
    if (-not $WorkDir) { Fail 1 "pass -AppDir (or -WorkDir / -Exe)" }
    $Exe = Join-Path $WorkDir 'bin\sim_headless.exe'
}
if (-not (Test-Path -LiteralPath $Exe)) { Fail 1 "$Exe not found - build it first: build.ps1 -AppDir <app>" }
$Exe = (Resolve-Path -LiteralPath $Exe).Path
$bin = Split-Path $Exe -Parent
if (-not $WorkDir) { $WorkDir = Split-Path $bin -Parent }

# --- stale exe? (it runs the app as it was at build time) ------------------
if ($AppDir -and -not $AllowStale) {
    $exeTime = (Get-Item -LiteralPath $Exe).LastWriteTimeUtc
    $inputs = @(Get-ChildItem -LiteralPath (Join-Path $AppDir 'src') -Recurse -File -ErrorAction SilentlyContinue)
    foreach ($p in 'index.bin', "out\$app.bin") { $f = Join-Path $AppDir $p; if (Test-Path $f) { $inputs += Get-Item -LiteralPath $f } }
    foreach ($d in 'art\packed', 'sound\assets') { $inputs += @(Get-ChildItem -LiteralPath (Join-Path $AppDir $d) -File -ErrorAction SilentlyContinue) }
    $newer = @($inputs | Where-Object { $_.LastWriteTimeUtc -gt $exeTime })
    if ($newer.Count) {
        Fail 6 ("$($newer.Count) app file(s) changed after the build (e.g. $($newer[0].FullName)). " +
                "Rebuild: build.ps1 -AppDir $AppDir   (or pass -AllowStale)")
    }
}

if (-not $OutDir) { $OutDir = Join-Path $WorkDir ("frames\" + (Get-Date -Format 'yyyyMMdd_HHmmss')) }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$OutDir = (Resolve-Path -LiteralPath $OutDir).Path

if ($FreshSaves) {
    Get-ChildItem -LiteralPath $bin -File | Where-Object { $_.Name -match '^[ei]\d+_\d+\.raw$' } | Remove-Item -Force
}
foreach ($f in 'headless_summary.txt', 'headless_crash.txt') { Remove-Item (Join-Path $bin $f) -ErrorAction SilentlyContinue }
$logPath = Join-Path $bin 'log_1.txt'
$logStart = if (Test-Path $logPath) { (Get-Item $logPath).Length } else { 0 }

# --- start hidden ----------------------------------------------------------
$envBlock = @{
    SIM_HEADLESS_SECONDS  = "$Seconds"
    SIM_HEADLESS_EVERY_MS = "$EveryMs"
    SIM_HEADLESS_DIR      = $OutDir
    SIM_HEADLESS_FACE     = "$Face"
    SIM_HEADLESS_OCT_OUT  = $(if ($OctOut) { [IO.Path]::GetFullPath($OctOut) } else { $null })
    SIM_HEADLESS_APP_DIR  = $null   # always the snapshot baked in by build.ps1
}
$visLog = Join-Path $OutDir 'visibility_log.txt'
$procId = Start-HiddenProcess -Exe $Exe -WorkDir $bin -Arguments "--mcp-port $McpPort" -Env $envBlock
"pid=$procId exe=$Exe started=$(Get-Date -Format o) mcp_port_requested=$McpPort" | Out-File $visLog -Encoding utf8
$info = [ordered]@{ pid = $procId; exe = $Exe; out_dir = $OutDir; log = $logPath; mcp_port = $null; seconds = $Seconds; every_ms = $EveryMs }
$infoPath = Join-Path $OutDir 'run_info.json'
$info | ConvertTo-Json | Set-Content -LiteralPath $infoPath -Encoding utf8
Write-Host ("started hidden: pid $procId  (stop early: Stop-Process -Id $procId - exit 7 unless -AllowEarlyStop" +
            "$(if ($AllowEarlyStop) { ', given' }))  out: $OutDir")

# --- watch: visibility every 50 ms; learn the MCP port from the log ---------
$script:mcpPort = $null
$onPoll = {
    param($elapsedMs)
    if ($script:mcpPort -or -not (Test-Path $logPath)) { return }
    $len = (Get-Item $logPath).Length
    if ($len -le $logStart) { return }
    $fs = [IO.File]::Open($logPath, 'Open', 'Read', 'ReadWrite')
    try { $null = $fs.Seek($logStart, 'Begin'); $buf = New-Object byte[] ($len - $logStart); $null = $fs.Read($buf, 0, $buf.Length) } finally { $fs.Close() }
    $m = [regex]::Match([Text.Encoding]::UTF8.GetString($buf), '\[mcp\] control socket listening on 127\.0\.0\.1:(\d+)')
    if ($m.Success) {
        $script:mcpPort = [int]$m.Groups[1].Value
        $info.mcp_port = $script:mcpPort
        $info | ConvertTo-Json | Set-Content -LiteralPath $infoPath -Encoding utf8
        Write-Host "mcp: listening on 127.0.0.1:$($script:mcpPort)  (t=$elapsedMs ms; client: mcp.ps1 -Port $($script:mcpPort) ping)"
    }
}
$r = Watch-HiddenProcess -ProcessId $procId -TimeoutSec ($Seconds + 90) -LogFile $visLog -OnPoll $onPoll

# --- report ----------------------------------------------------------------
$frames = @(Get-ChildItem -LiteralPath $OutDir -Filter 'frame_*.png' -ErrorAction SilentlyContinue | Sort-Object Name)
$crash = Join-Path $bin 'headless_crash.txt'
"polls=$($r.Polls) max_windows_owned=$($r.MaxWindows) max_visible=$($r.MaxVisible) exit=$($r.Exit) frames=$($frames.Count) elapsed_ms=$($r.ElapsedMs)" |
    Out-File $visLog -Append -Encoding utf8
"pid:          $procId"
"out dir:      $OutDir"
"visibility:   polls=$($r.Polls) (every 50 ms), windows owned=$($r.MaxWindows), max_visible=$($r.MaxVisible)"
"exit code:    $($r.Exit)"
"mcp port:     $(if ($script:mcpPort) { $script:mcpPort } else { 'not seen in the log' })"
"frames:       $($frames.Count)"
if ($frames.Count) { "last frame:   $($frames[-1].FullName)" }
# thin background lines on screen edges (screen-filling art placed at +-120): a report, never an exit code
$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) { $py = (Get-Command py -ErrorAction SilentlyContinue).Source }
if ($frames.Count -and $py) {
    $seamArgs = @((Join-Path $PSScriptRoot 'seams.py'), $frames[-1].FullName)
    if ($Face -ge 0) { $seamArgs += '--face' }
    & $py @seamArgs | ForEach-Object { "$_" }
}
$summary = Join-Path $bin 'headless_summary.txt'
# the simulator writes the summary only when its timed run completed (it was deleted before the start)
$completed = Test-Path $summary
if ($completed) { "summary:      " + ((Get-Content $summary) -join ' ') }
else { "summary:      none (the timed run did not complete)" }
# this run's own lines: log_1.txt is appended by every run of this work dir, so a grep there mixes runs
$runLog = Join-Path $OutDir 'log.txt'
$logLen = (Get-Item $logPath -ErrorAction SilentlyContinue).Length
if ($logLen -gt $logStart) {
    $fs = [IO.File]::Open($logPath, 'Open', 'Read', 'ReadWrite')
    try { $null = $fs.Seek($logStart, 'Begin'); $buf = New-Object byte[] ($logLen - $logStart); $null = $fs.Read($buf, 0, $buf.Length) } finally { $fs.Close() }
    [IO.File]::WriteAllBytes($runLog, $buf)
    "log:          $runLog (this run only)"
    $tail = Get-Content $runLog | Where-Object { $_ -match 'HEADLESS\]|ERROR|WARNING|\[mcp\]|DIE|assert' } | Select-Object -Last 12
    if ($tail) { "log (filtered tail of this run):"; $tail | ForEach-Object { "  $_" } }
}

if ($r.MaxVisible -gt 0) { Fail 2 "a window of the simulator became VISIBLE and the process was killed: $($r.FirstVisible)" }
if ($r.Exit -eq 'timeout') { Fail 3 "the simulator did not end within $($Seconds + 90) s and was killed by PID" }
if ($r.Exit -eq 99 -or (Test-Path $crash)) { Fail 5 "the simulator crashed (exit $($r.Exit)); see $crash and $logPath" }
if ($EveryMs -gt 0 -and $frames.Count -eq 0) { Fail 4 "no frames written to $OutDir" }
if (-not ($r.Exit -eq 0 -and $completed)) {
    $why = "exit $($r.Exit)$(if (-not $completed) { ', no headless_summary.txt' })"
    if ($AllowEarlyStop -and ($r.Exit -is [int])) {
        Write-Host "NOTE: ended before its timed exit ($why) - accepted: -AllowEarlyStop (a deliberate stop by PID)" -ForegroundColor Yellow
        "OK: never visible; stopped early on purpose (-AllowEarlyStop)"
        exit 0
    }
    Fail 7 ("the simulator ended before its timed exit ($why): an early exit, a kill or a crash without the " +
            "marker - not a completed run. For a deliberate stop by PID (MCP playtest) pass -AllowEarlyStop.")
}
"OK: never visible; timed run completed"
exit 0
