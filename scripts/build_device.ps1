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
$binLen = (Get-Item $bin).Length
if ($binLen -le 0) { Fail "$bin is empty -- ARM build produced no code" }
Write-Host "    built $bin ($binLen bytes ARM code)"

# --- 2. Pack the .oct by launching the sim once ---------------------------
# The simulator assembles the .oct at launch. It embeds out/<app>.bin ONLY if
# that file exists (sim.h treats ARM code as optional -- a sim-only launch
# writes an asset-only .oct that runs on the PC but is DEAD on the cube). We
# just built the .bin above, so this launch must embed it -- and we verify it.
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

# --- 3. Verify the ARM code is actually embedded --------------------------
# This is the whole point: prove the cube package contains the ARM binary, not
# just assets. The sim appends the ARM code as the LAST chunk of the pack
# (sim.h: assets -> sounds -> code, then header->Size = end), so the final
# <binLen> bytes of the .oct must equal the .bin byte-for-byte. If they don't,
# the sim packed an asset-only .oct (e.g. it couldn't find the .bin) and the
# package would silently fail on the cube -- so we refuse to ship it.
$binBytes = [System.IO.File]::ReadAllBytes($bin)
$octBytes = [System.IO.File]::ReadAllBytes($oct)
$embedded = $false
if ($octBytes.Length -ge $binBytes.Length) {
    $start = $octBytes.Length - $binBytes.Length
    $embedded = $true
    for ($i = 0; $i -lt $binBytes.Length; $i++) {
        if ($octBytes[$start + $i] -ne $binBytes[$i]) { $embedded = $false; break }
    }
}
if (-not $embedded) {
    Fail ("the .oct does NOT contain the ARM code (asset-only pack). It would run " +
          "in the simulator but is dead on the cube. Check that out\$app.bin exists " +
          "and that APP_DIR in src\app.h points back at this app folder.")
}
Write-Host "    verified ARM code embedded ($binLen bytes) in the .oct"

# --- 4. Warn about stray timestamped .oct files in the app root ------------
# The Linux simulator deletes root .oct files at startup, so anything like
# <app>_20250101.oct left in the app root can silently vanish. Warning only.
$strayOct = Get-ChildItem $AppDir -Filter "${app}_*.oct" -File -ErrorAction SilentlyContinue
if ($strayOct) {
    Write-Host "WARNING: stray timestamped .oct file(s) in the app root:" -ForegroundColor Yellow
    foreach ($s in $strayOct) { Write-Host "    $($s.Name)" -ForegroundColor Yellow }
    Write-Host "The Linux simulator deletes root .oct files at startup. Keep deliverables" -ForegroundColor Yellow
    Write-Host "in a pack\ subfolder (or copy them out of the app root) so they survive." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "CUBE PACKAGE READY:" -ForegroundColor Green
Write-Host "  $oct"
Write-Host "  ($($octBytes.Length) bytes -- assets + sounds + $binLen bytes ARM code)"
Write-Host "Load this .oct onto the WowCube."
Write-Host ""
Write-Host "NOTE: launching the simulator again will OVERWRITE this .oct with an" -ForegroundColor Yellow
Write-Host "asset-only pack (no ARM code). Re-run this script after any sim testing" -ForegroundColor Yellow
Write-Host "to regenerate the cube-loadable .oct as the LAST step before shipping." -ForegroundColor Yellow
exit 0
