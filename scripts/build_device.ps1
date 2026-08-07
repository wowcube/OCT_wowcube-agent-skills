<#
.SYNOPSIS
    Produce the cube-loadable .oct package for an existing app_<game> folder.

.DESCRIPTION
    The .oct is the file you load onto the physical WowCube. It is assembled by
    the pure-Python builder (scripts/pack_beta.py --build-oct), which packs:
    the art .raw assets + the sounds + the ARM device code from
    out/<app>.bin. So producing a *loadable* .oct is two steps:

      1. ARM device build  -> app_<game>/out/app_<game>.bin
         (cmake -G Ninja -S <octavios>/apps -B out ; cmake --build out)
      2. python scripts/pack_beta.py --build-oct -> app_<game>/app_<game>.oct
         (assets + sounds + ARM code, deterministic bytes)

    This no longer launches the simulator or needs MSVC -- only the ARM
    device toolchain (arm-none-eabi-gcc, cmake, ninja) and python. Run
    check_env.ps1 first if any of those are missing. Without the ARM .bin
    there is no code to embed; this script treats a missing/empty .bin as a
    failure.

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

foreach ($t in 'arm-none-eabi-gcc', 'cmake', 'ninja', 'python') {
    if (-not (Get-Command $t -ErrorAction SilentlyContinue)) {
        Fail "$t not on PATH -- run check_env.ps1 to install the device toolchain"
    }
}
$packPy = Join-Path $PSScriptRoot 'pack_beta.py'
if (-not (Test-Path $packPy)) { Fail "python builder not found: $packPy" }

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

# --- 2. Pack the .oct with the pure-Python builder -------------------------
# scripts/pack_beta.py --build-oct assembles the pack directly from
# index.bin + art/packed + sound/assets + the ARM code, byte-identical to
# what the simulator used to write (minus its wall-clock BuildDateTime stamp,
# which the python builder pins to 0 for determinism). No simulator launch,
# no MSVC needed.
$oct = Join-Path $AppDir "$app.oct"
if (Test-Path $oct) { Remove-Item $oct -Force }

Step "Packing .oct (python scripts/pack_beta.py --build-oct)"
python $packPy --build-oct --app-dir "$AppDir" --code "$bin" --out "$oct" | Out-Host
if ($LASTEXITCODE -ne 0) { Fail "python .oct builder failed (exit $LASTEXITCODE)" }

if (-not (Test-Path $oct)) {
    Fail "python builder did not produce $oct"
}

# --- 3. Verify the ARM code is actually embedded --------------------------
# This is the whole point: prove the cube package contains the ARM binary, not
# just assets. The builder appends the ARM code as the LAST chunk of the pack
# (assets -> sounds -> code, then header->Size = end), so the final
# <binLen> bytes of the .oct must equal the .bin byte-for-byte. If they don't,
# something upstream (e.g. a stale --code path) produced an asset-only .oct
# and the package would silently fail on the cube -- so we refuse to ship it.
# This check is unchanged from when the simulator wrote the .oct; it now
# verifies our own python builder instead, which is still valuable.
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
# Write-Warning keeps this off stdout, matching build_device.sh's >&2 block.
$strayOct = Get-ChildItem $AppDir -Filter "${app}_*.oct" -File -ErrorAction SilentlyContinue
if ($strayOct) {
    $strayNames = ($strayOct | ForEach-Object { "    $($_.Name)" }) -join "`n"
    Write-Warning ("stray timestamped .oct file(s) in the app root:`n$strayNames`n" +
        "The Linux simulator deletes root .oct files at startup. Keep deliverables`n" +
        "in a pack\ subfolder (or copy them out of the app root) so they survive.")
}

Write-Host ""
Write-Host "CUBE PACKAGE READY:" -ForegroundColor Green
Write-Host "  $oct"
Write-Host "  ($($octBytes.Length) bytes -- assets + sounds + $binLen bytes ARM code)"
Write-Host "Load this .oct onto the WowCube."
Write-Host ""
Write-Host "NOTE: launching the simulator manually will still OVERWRITE this .oct with" -ForegroundColor Yellow
Write-Host "an asset-only pack (no ARM code) -- but device delivery no longer depends" -ForegroundColor Yellow
Write-Host "on the sim. Re-run this script after any sim play-testing session to" -ForegroundColor Yellow
Write-Host "regenerate the cube-loadable .oct as the LAST step before shipping." -ForegroundColor Yellow
exit 0
