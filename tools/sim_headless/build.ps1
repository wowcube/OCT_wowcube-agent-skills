<#
.SYNOPSIS
    Build sim_headless.exe: the stock Windows simulator + the [HEADLESS] patch, for one app.

.DESCRIPTION
    1. Snapshots the app (src, index.bin, art\packed, sound\assets, *.target, out\*.bin|.elf) into
       <WorkDir>\<app>. The real app folder is only read; the exe packs from the snapshot, so its compiled
       ids and its assets always match, and nothing a run does can write into the app.
    2. -Define NAME=VALUE (repeatable) overrides "#define NAME ..." lines in the snapshot's sources (works for
       unguarded test hooks too); a NAME that no source defines is passed to the compiler as /DNAME=VALUE.
    3. patch.py copies <Octavios>\sim\src + engine into <WorkDir> and applies the patch (octavios is only read).
    4. Compiles with MSVC exactly like apps\build_sim.cmd (incl. the telemetry library it needs), plus
       /DSIM_HEADLESS_FORCE, into <WorkDir>\bin\sim_headless.exe.
    It never starts the simulator. Run it with run.ps1.

    -Visible builds a NORMAL simulator for the USER to play instead (same copy, the [HEADLESS] code stays
    dormant): <WorkDir>\<app>\bin\<app>.exe, which packs from the snapshot. Agents never start it; tell the
    user the path. (It exists because the stock apps\build_sim.cmd fails under MSVC at octavios dev 609d5ae,
    see the compat note in patch.py.)

.PARAMETER AppDir
    The app_<game> folder (one *.target, packed: index.bin + art\packed).
.PARAMETER Octavios
    octavios checkout (dev 609d5ae or later). Default: <AppDir>\..\octavios.
.PARAMETER Telemetry
    wowcube/telemetry checkout. Default: <Octavios>\..\telemetry (where apps\build_sim.cmd expects it).
.PARAMETER WorkDir
    Build/run folder. Default: <AppDir>\..\.sim_headless\<app>.
.PARAMETER Define
    NAME=VALUE (or NAME) test hooks, e.g. -Define TD_DEBUG_AUTOPLAY=1,TD_MUTE=1.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File tools\sim_headless\build.ps1 -AppDir C:\ws\app_tetris
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $AppDir,
    [string] $Octavios,
    [string] $Telemetry,
    [string] $WorkDir,
    [string[]] $Define = @(),
    [switch] $Visible
)
$ErrorActionPreference = 'Stop'
function Fail($m) { Write-Host "ERROR: $m" -ForegroundColor Red; exit 1 }
function Step($m) { Write-Host "==> $m" -ForegroundColor Cyan }

# --- paths -----------------------------------------------------------------
$AppDir = (Resolve-Path -LiteralPath $AppDir -ErrorAction SilentlyContinue).Path
if (-not $AppDir) { Fail "app folder not found" }
$targets = @(Get-ChildItem -LiteralPath $AppDir -Filter *.target -File)
if ($targets.Count -ne 1) { Fail "$AppDir must hold exactly one *.target marker (found $($targets.Count))" }
$app = [IO.Path]::GetFileNameWithoutExtension($targets[0].Name)
if (-not (Test-Path (Join-Path $AppDir 'src\app.h'))) { Fail "$AppDir\src\app.h not found" }
if (-not (Test-Path (Join-Path $AppDir 'index.bin'))) { Fail "$AppDir\index.bin not found - pack the app first (the simulator loads the packed assets)" }

$ws = Split-Path $AppDir -Parent
if (-not $Octavios) { $Octavios = Join-Path $ws 'octavios' }
$Octavios = (Resolve-Path -LiteralPath $Octavios -ErrorAction SilentlyContinue).Path
if (-not $Octavios -or -not (Test-Path (Join-Path $Octavios 'sim\src\sim_wrap_win.h'))) { Fail "octavios not found (pass -Octavios)" }
if (-not (Test-Path (Join-Path $Octavios 'sim\src\sim_mcp.h'))) { Fail "$Octavios is older than octavios dev (no sim\src\sim_mcp.h): update the SDK" }
if (-not $Telemetry) { $Telemetry = Join-Path (Split-Path $Octavios -Parent) 'telemetry' }
$Telemetry = (Resolve-Path -LiteralPath $Telemetry -ErrorAction SilentlyContinue).Path
if (-not $Telemetry -or -not (Test-Path (Join-Path $Telemetry 'octavios_simulator\telemetry_sim.cpp'))) {
    Fail "telemetry library not found (pass -Telemetry, or check out wowcube/telemetry next to octavios)"
}
if (-not $WorkDir) { $WorkDir = Join-Path $ws ".sim_headless\$app" }
New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
$WorkDir = (Resolve-Path -LiteralPath $WorkDir).Path
$snap = Join-Path $WorkDir $app
$bin  = Join-Path $WorkDir 'bin'
New-Item -ItemType Directory -Force -Path $bin | Out-Null

# --- 1. snapshot of the app (read-only on the source) ----------------------
Step "Snapshot $AppDir -> $snap"
foreach ($sub in 'src', 'art\packed', 'sound\assets') {
    $from = Join-Path $AppDir $sub; $to = Join-Path $snap $sub
    if (Test-Path $to) { Remove-Item -Recurse -Force $to }
    if (Test-Path $from) {
        New-Item -ItemType Directory -Force -Path (Split-Path $to -Parent) | Out-Null
        Copy-Item -Recurse -LiteralPath $from -Destination $to
    }
}
Get-ChildItem -LiteralPath $snap -File -ErrorAction SilentlyContinue | Remove-Item -Force
Copy-Item -LiteralPath (Join-Path $AppDir 'index.bin') -Destination $snap
Copy-Item -LiteralPath $targets[0].FullName -Destination $snap
$snapOut = Join-Path $snap 'out'
if (Test-Path $snapOut) { Remove-Item -Recurse -Force $snapOut }
foreach ($ext in 'bin', 'elf') {
    $f = Join-Path $AppDir "out\$app.$ext"
    if (Test-Path $f) { New-Item -ItemType Directory -Force -Path $snapOut | Out-Null; Copy-Item -LiteralPath $f -Destination $snapOut }
}

# --- 2. test-hook defines --------------------------------------------------
$extraDefines = @()
foreach ($d in ($Define | ForEach-Object { $_ -split ',' } | Where-Object { $_ })) {
    $name, $value = $d -split '=', 2
    if ($name -notmatch '^[A-Za-z_]\w*$') { Fail "bad -Define '$d' (NAME or NAME=VALUE)" }
    if ($null -eq $value) { $value = '1' }
    $hit = $false
    $rx = "(?m)^([ \t]*#[ \t]*define[ \t]+$name)\b(?![(])[^\r\n]*"
    foreach ($f in @(Get-ChildItem -LiteralPath (Join-Path $snap 'src') -Recurse -File | Where-Object { $_.Extension -in '.h', '.hpp', '.c', '.cpp' })) {
        $bytes = [IO.File]::ReadAllBytes($f.FullName)
        $bom = $bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF
        $raw = [IO.File]::ReadAllText($f.FullName)
        if ([regex]::IsMatch($raw, $rx)) {   # case-sensitive, unlike -match
            $raw = [regex]::Replace($raw, $rx, "`$1 $value   // [sim_headless -Define]")
            [IO.File]::WriteAllText($f.FullName, $raw, (New-Object System.Text.UTF8Encoding($bom)))
            $hit = $true
            Write-Host "    $name = $value  (in $($f.Name))"
        }
    }
    if (-not $hit) { $extraDefines += "`"/D$name=$value`""; Write-Host "    $name = $value  (compiler /D)" }
}

# --- 3. patched simulator sources -----------------------------------------
Step "Patching a copy of $Octavios\sim\src"
$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) { $python = (Get-Command py -ErrorAction SilentlyContinue).Source }
if (-not $python) { Fail "python not found on PATH" }
& $python (Join-Path $PSScriptRoot 'patch.py') --octavios $Octavios --out $WorkDir
if ($LASTEXITCODE -ne 0) { Fail "patch.py failed (exit $LASTEXITCODE)" }

# --- 4. compile (MSVC, same flags as apps\build_sim.cmd) --------------------
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
if (-not (Test-Path $vswhere)) { Fail "vswhere.exe not found - install Visual Studio C++ build tools (check_env.ps1)" }
$vs = & $vswhere -latest -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vs) { Fail "Visual Studio with C++ tools not found (check_env.ps1)" }
$vsDevCmd = Join-Path $vs 'Common7\Tools\VsDevCmd.bat'

$simSrc = Join-Path $WorkDir 'sim\src'; $engine = Join-Path $WorkDir 'engine'
if ($Visible) {
    # a normal simulator: [HEADLESS] code dormant; APP_DIR "..\..\<app>" from <snap>\bin resolves to the snapshot
    $bin = Join-Path $snap 'bin'
    New-Item -ItemType Directory -Force -Path $bin | Out-Null
    $exe = Join-Path $bin "$app.exe"
    $modeDefines = @()
} else {
    $exe = Join-Path $bin 'sim_headless.exe'
    $cfgH = Join-Path $bin 'sim_headless_cfg.h'
    "#define SIM_HEADLESS_APP_DIR_BAKED `"$($snap -replace '\\', '/')`"" | Set-Content -LiteralPath $cfgH -Encoding ascii
    $modeDefines = @('/DSIM_HEADLESS_FORCE', "/FI`"$cfgH`"")
}
function Q($s) { '"' + $s + '"' }
$rspPng = @('/nologo', '/c', '/EHsc', '/std:c++20', '/O2', '/MTd', '/D_CRT_SECURE_NO_WARNINGS', '/D_ITERATOR_DEBUG_LEVEL=0',
            "/I$(Q $simSrc)", "/Fo$(Q (Join-Path $bin 'hl_png.obj'))", (Q (Join-Path $simSrc 'hl_png.cpp')))
$rspSim = @('/nologo', '/EHsc', '/std:c++20', '/permissive', '/W4', '/Zi', '/Od', '/MTd',
            '/DOCTSIM', '/D_UNICODE', '/DUNICODE', '/D_CRT_SECURE_NO_WARNINGS', '/D_CRT_NONSTDC_NO_DEPRECATE',
            '/D_ITERATOR_DEBUG_LEVEL=0', '"/DSIM_APP_HEADER=\"app.h\""') + $modeDefines + $extraDefines + @(
            "/I$(Q $simSrc)", "/I$(Q $engine)", "/I$(Q (Join-Path $snap 'src'))",
            "/I$(Q (Join-Path $Telemetry 'include'))", "/I$(Q $Telemetry)",
            "/Fe$(Q $exe)", "/Fd$(Q ([IO.Path]::ChangeExtension($exe, '.pdb')))", "/Fo$(Q ($bin + '\\'))",   # \\" = one backslash + closing quote
            (Q (Join-Path $simSrc 'sim.cpp')), (Q (Join-Path $Telemetry 'octavios_simulator\telemetry_sim.cpp')),
            (Q (Join-Path $bin 'hl_png.obj')))
# /link stays on the command line: cl does not honour it inside a response file (D9002)
$linkArgs = '/link /SUBSYSTEM:WINDOWS opengl32.lib ws2_32.lib winmm.lib Bthprops.lib Shlwapi.lib Comdlg32.lib user32.lib gdi32.lib shell32.lib ole32.lib'
$rsp1 = Join-Path $bin 'cl_png.rsp'; $rsp2 = Join-Path $bin 'cl_sim.rsp'
$rspPng -join "`r`n" | Set-Content -LiteralPath $rsp1 -Encoding ascii
$rspSim -join "`r`n" | Set-Content -LiteralPath $rsp2 -Encoding ascii
$cmdFile = Join-Path $bin 'compile.cmd'
$buildLog = Join-Path $bin 'compile.log'
@"
@echo off
call "$vsDevCmd" -arch=amd64 -host_arch=amd64 -no_logo >nul 2>&1
cl.exe @"$rsp1" > "$buildLog" 2>&1
if errorlevel 1 exit /b 1
cl.exe @"$rsp2" $linkArgs >> "$buildLog" 2>&1
if errorlevel 1 exit /b 1
exit /b 0
"@ | Set-Content -LiteralPath $cmdFile -Encoding ascii

Step "Compiling $(Split-Path $exe -Leaf) (MSVC, 1-3 min; log: $buildLog)"
if (Test-Path $exe) { Remove-Item -Force $exe }
& cmd.exe /d /c (Q $cmdFile)
$compileCode = $LASTEXITCODE
if ($compileCode -ne 0 -or -not (Test-Path $exe)) {
    if (Test-Path $buildLog) {
        Get-Content -LiteralPath $buildLog | Where-Object { $_ -match ' error |fatal error|LNK\d{4}' } | Select-Object -First 40 | Out-Host
    }
    Fail "compile failed (exit $compileCode) - full log: $buildLog"
}

Write-Host ""
if ($Visible) {
    Write-Host "BUILD OK (visible simulator, for the USER only): $exe" -ForegroundColor Green
    Write-Host "  It opens a window and plays sound. Agents never start it; give the user this path."
    exit 0
}
@{ app = $app; app_dir = $AppDir; snapshot = $snap; octavios = $Octavios; telemetry = $Telemetry;
   defines = @($Define); built = (Get-Date -Format o) } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $WorkDir 'build_info.json') -Encoding utf8
Write-Host "BUILD OK: $exe" -ForegroundColor Green
Write-Host "  app snapshot: $snap"
Write-Host "  next: powershell -NoProfile -ExecutionPolicy Bypass -File $PSScriptRoot\run.ps1 -AppDir $AppDir"
exit 0
