<#
.SYNOPSIS
    Produce the cube-loadable .oct package for an existing app_<game> folder.

.DESCRIPTION
    The .oct is the file you load onto the physical WowCube. It is assembled by
    the SIMULATOR at launch, which packs: the art .raw assets + the sounds +
    (if present) the ARM device code from out/<app>.bin. So producing a
    *loadable* .oct is two steps:

      1. ARM device build  -> app_<game>/out/app_<game>.bin
         (cmake -G Ninja -S <octavios>/apps -B out ; cmake --build out)
      2. Launch the sim once -> it writes app_<game>/app_<game>.oct
         (assets + sounds + ARM code)

    Requires the device toolchain (arm-none-eabi-gcc, cmake, ninja) -- run
    check_env.ps1 first. Without the ARM .bin the sim still writes a .oct, but it
    contains assets only and will NOT run on the cube; this script treats a
    missing .bin as a failure.

.PARAMETER AppDir
    Path to the app_<game> folder (must contain <app>.target and art/packed).

.PARAMETER OctaviOS
    Path to the octavios SDK. Default: <AppDir>\..\octavios.

.EXAMPLE
    powershell -File .\build_device.ps1 -AppDir C:\ws\app_tetris
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $AppDir,
    [string] $OctaviOS
)

$ErrorActionPreference = 'Stop'
function Fail($m) { Write-Host "ERROR: $m" -ForegroundColor Red; exit 1 }
function Step($m) { Write-Host "==> $m" -ForegroundColor Cyan }

$AppDir = (Resolve-Path $AppDir).Path
$target = Get-ChildItem $AppDir -Filter *.target -File -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $target) { Fail "no *.target marker in $AppDir" }
$app = [System.IO.Path]::GetFileNameWithoutExtension($target.Name)

if (-not $OctaviOS) { $OctaviOS = Join-Path $AppDir '..\octavios' }
$OctaviOS = (Resolve-Path $OctaviOS -ErrorAction SilentlyContinue).Path
if (-not $OctaviOS) { Fail "octavios SDK not found (pass -OctaviOS)" }
$appsDir = Join-Path $OctaviOS 'apps'

foreach ($t in 'arm-none-eabi-gcc', 'cmake', 'ninja') {
    if (-not (Get-Command $t -ErrorAction SilentlyContinue)) {
        Fail "$t not on PATH -- run check_env.ps1 to install the device toolchain"
    }
}

# --- 1. ARM device build --------------------------------------------------
Step "ARM device build (cmake + ninja) for $app"
$out = Join-Path $AppDir 'out'
Push-Location $AppDir
try {
    cmake -G Ninja -S "$appsDir" -B "$out" | Out-Host
    if ($LASTEXITCODE -ne 0) { Fail "cmake configure failed (exit $LASTEXITCODE)" }
    cmake --build "$out" | Out-Host
    if ($LASTEXITCODE -ne 0) { Fail "cmake build failed (exit $LASTEXITCODE)" }
} finally { Pop-Location }

$bin = Join-Path $out "$app.bin"
if (-not (Test-Path $bin)) { Fail "device build produced no $bin" }
Write-Host "    built $bin ($((Get-Item $bin).Length) bytes ARM code)"

# --- 2. Pack the .oct by launching the sim once ---------------------------
$exe = Join-Path $AppDir "bin\$app.exe"
if (-not (Test-Path $exe)) {
    Fail "simulator exe missing ($exe) -- run new_app.ps1 / build_sim.cmd first"
}
$oct = Join-Path $AppDir "$app.oct"
if (Test-Path $oct) { Remove-Item $oct -Force }

Step "Packing .oct (launching simulator to assemble the package)"
$p = Start-Process -FilePath $exe -PassThru
Start-Sleep -Seconds 5
if (-not $p.HasExited) { $p | Stop-Process -Force }

if (-not (Test-Path $oct)) {
    Fail "simulator did not produce $oct"
}

Write-Host ""
Write-Host "CUBE PACKAGE READY:" -ForegroundColor Green
Write-Host "  $oct"
Write-Host "  ($((Get-Item $oct).Length) bytes -- assets + sounds + ARM code)"
Write-Host "Load this .oct onto the WowCube."
exit 0
