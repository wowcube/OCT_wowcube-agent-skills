<#
.SYNOPSIS
    Build cube_upload.exe: a windowless, silent copy of the Windows simulator that only uploads one .oct.

.DESCRIPTION
    patch.py copies <Octavios>\sim\src + engine into <WorkDir> (octavios is only read) and applies the
    [UPLOAD] patch; MSVC then builds it like apps\build_sim.cmd but WITHOUT an app (the simulator's "blank sim"
    mode), so the uploader needs no app folder and never writes a .oct. Output: <WorkDir>\bin\cube_upload.exe.
    Building starts nothing. run_upload.ps1 builds it on first use.

.PARAMETER Octavios   octavios checkout (dev 609d5ae or later). Default: $env:OCTAVIOS_DIR, else .\octavios.
.PARAMETER Telemetry  wowcube/telemetry checkout. Default: <Octavios>\..\telemetry.
.PARAMETER WorkDir    Default: <Octavios>\..\.cube_upload.
#>
[CmdletBinding()]
param(
    [string] $Octavios,
    [string] $Telemetry,
    [string] $WorkDir
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\sim_headless\safe_paths.ps1')
function Fail($m) { Write-Host "ERROR: $m" -ForegroundColor Red; exit 1 }
function Step($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Q($s) { '"' + $s + '"' }

if (-not $Octavios) { $Octavios = $(if ($env:OCTAVIOS_DIR) { $env:OCTAVIOS_DIR } else { Join-Path (Get-Location).Path 'octavios' }) }
$Octavios = (Resolve-Path -LiteralPath $Octavios -ErrorAction SilentlyContinue).Path
if (-not $Octavios -or -not (Test-Path (Join-Path $Octavios 'sim\src\sim_thread_manager.h'))) { Fail "octavios not found (pass -Octavios)" }
if (-not $Telemetry) { $Telemetry = Join-Path (Split-Path $Octavios -Parent) 'telemetry' }
$Telemetry = (Resolve-Path -LiteralPath $Telemetry -ErrorAction SilentlyContinue).Path
if (-not $Telemetry -or -not (Test-Path (Join-Path $Telemetry 'octavios_simulator\telemetry_sim.cpp'))) {
    Fail "telemetry library not found (pass -Telemetry, or check out wowcube/telemetry next to octavios)"
}
if (-not $WorkDir) { $WorkDir = Join-Path (Split-Path $Octavios -Parent) '.cube_upload' }
# the build rewrites <WorkDir>\sim\src, engine and bin: never the SDK, the telemetry checkout or a home folder
$why = Test-UnsafeWorkDir -WorkDir $WorkDir -Protect @($Octavios, $Telemetry)
if ($why) { Fail $why }
New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
$WorkDir = (Resolve-Path -LiteralPath $WorkDir).Path
# cl.exe response files and the .cmd are ANSI: non-ASCII (e.g. Cyrillic) paths -> 8.3 short form or a clear error
try {
    $WorkDir = Get-AsciiPath -Path $WorkDir -What 'work dir'
    $Telemetry = Get-AsciiPath -Path $Telemetry -What 'telemetry checkout'
} catch { Fail $_.Exception.Message }
$bin = Join-Path $WorkDir 'bin'
New-Item -ItemType Directory -Force -Path $bin | Out-Null

Step "Patching a copy of $Octavios\sim\src"
$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) { $python = (Get-Command py -ErrorAction SilentlyContinue).Source }
if (-not $python) { Fail "python not found on PATH" }
& $python (Join-Path $PSScriptRoot 'patch.py') --octavios $Octavios --out $WorkDir
if ($LASTEXITCODE -ne 0) { Fail "patch.py failed (exit $LASTEXITCODE)" }

$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
if (-not (Test-Path $vswhere)) { Fail "vswhere.exe not found - install Visual Studio C++ build tools (scripts\check_env.ps1)" }
$vs = & $vswhere -latest -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vs) { Fail "Visual Studio with C++ tools not found" }
$vsDevCmd = Join-Path $vs 'Common7\Tools\VsDevCmd.bat'

$simSrc = Join-Path $WorkDir 'sim\src'; $engine = Join-Path $WorkDir 'engine'
$exe = Join-Path $bin 'cube_upload.exe'
$rsp = @('/nologo', '/EHsc', '/std:c++20', '/permissive', '/W4', '/Zi', '/Od', '/MTd',
         '/DOCTSIM', '/D_UNICODE', '/DUNICODE', '/D_CRT_SECURE_NO_WARNINGS', '/D_CRT_NONSTDC_NO_DEPRECATE',
         '/D_ITERATOR_DEBUG_LEVEL=0', '/DSIM_HEADLESS_FORCE',
         "/I$(Q $simSrc)", "/I$(Q $engine)", "/I$(Q (Join-Path $Telemetry 'include'))", "/I$(Q $Telemetry)",
         "/Fe$(Q $exe)", "/Fd$(Q (Join-Path $bin 'cube_upload.pdb'))", "/Fo$(Q ($bin + '\\'))",   # \\" = one backslash + closing quote
         (Q (Join-Path $simSrc 'sim.cpp')), (Q (Join-Path $Telemetry 'octavios_simulator\telemetry_sim.cpp')))
$rspFile = Join-Path $bin 'cl_upload.rsp'
$rsp -join "`r`n" | Set-Content -LiteralPath $rspFile -Encoding ascii
$linkArgs = '/link /SUBSYSTEM:WINDOWS opengl32.lib ws2_32.lib winmm.lib Bthprops.lib Shlwapi.lib Comdlg32.lib user32.lib gdi32.lib shell32.lib ole32.lib'
$buildLog = Join-Path $bin 'compile.log'
$cmdFile = Join-Path $bin 'compile.cmd'
@"
@echo off
call "$vsDevCmd" -arch=amd64 -host_arch=amd64 -no_logo >nul 2>&1
cl.exe @"$rspFile" $linkArgs > "$buildLog" 2>&1
if errorlevel 1 exit /b 1
exit /b 0
"@ | Set-Content -LiteralPath $cmdFile -Encoding ascii

Step "Compiling cube_upload.exe (MSVC, about a minute; log: $buildLog)"
if (Test-Path $exe) { Remove-Item -Force $exe }
& cmd.exe /d /c (Q $cmdFile)
$code = $LASTEXITCODE
if ($code -ne 0 -or -not (Test-Path $exe)) {
    if (Test-Path $buildLog) { Get-Content -LiteralPath $buildLog | Where-Object { $_ -match ' error |fatal error|LNK\d{4}' } | Select-Object -First 40 | Out-Host }
    Fail "compile failed (exit $code) - full log: $buildLog"
}
Write-Host ""
Write-Host "BUILD OK: $exe" -ForegroundColor Green
Write-Host "  upload: run_upload.ps1 -Octavios $Octavios -Mac <cube MAC> -Oct <path to .oct>"
exit 0
