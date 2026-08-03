<#
.SYNOPSIS
    Scaffold a WowCube app folder from the template, pack its assets, and verify
    the simulator toolchain -- the "infrastructure ready" gate that must pass
    BEFORE the orchestrator runs the first technical prompt.

.DESCRIPTION
    Mirrors the proven manual procedure:
      1. Copy templates/app_ai_template -> <workspace>/app_<name>
      2. Rename the .target marker and the game/ids headers to app_<name>*
      3. Replace every name-bearing reference (app.h, app_<name>.h)
      4. Guarantee the full beta define set in app.h (APP_VERSION, APP_TITLE,
         APP_GUID1 randomized, APP_CATEGORIES, APP_COLORS)
      5. Pack art assets with the pure-Python packer (scripts/pack.py --emit-raw),
         which writes the generated _ids.h straight into src/
      6. Smoke-build the simulator (octavios/apps/build_sim.cmd) -- simulator ONLY,
         never the ARM/device target
      7. (optional) launch the .exe briefly to confirm it does not crash on start

    Exit code 0 = infrastructure verified. Non-zero = a step failed; the message
    says which one.

.PARAMETER Name
    Game/app name. "tetris" or "app_tetris" both yield the folder app_tetris.

.PARAMETER Workspace
    Root that contains octavios/ and where app_<name>/ is created. Default: CWD.

.PARAMETER Template
    Template app folder to clone. Default: the app_ai_template shipped in this
    repo (..\templates\app_ai_template, relative to scripts/).

.PARAMETER BuildScript
    Path to build_sim.cmd. Default: <Workspace>\octavios\apps\build_sim.cmd.

.PARAMETER Run
    After a successful build, launch the .exe for a few seconds and confirm it
    stays alive (catches missing-asset crashes the compiler cannot see).

.PARAMETER SkipBuild
    Scaffold + pack only; skip the simulator build (e.g. MSVC not installed).

.PARAMETER SkipEnvCheck
    Skip the toolchain check/install (check_env.ps1) at the start.

.PARAMETER SkipMsvc
    Forward to check_env.ps1: don't auto-install MSVC even if it's missing
    (e.g. it's already installing in another window).

.EXAMPLE
    powershell -File .\new_app.ps1 -Name tetris -Run
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $Name,
    [string] $Workspace = (Get-Location).Path,
    [string] $Template,
    [string] $BuildScript,
    [switch] $Run,
    [switch] $SkipBuild,
    [switch] $SkipEnvCheck,
    [switch] $SkipMsvc
)

$ErrorActionPreference = 'Stop'
$TOKEN = 'app_ai_template'   # literal name baked into the template files

function Fail($msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }
function Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

# --- Resolve names and paths ----------------------------------------------
$app = if ($Name -match '^app_') { $Name } else { "app_$Name" }
if ($app -notmatch '^app_[A-Za-z0-9_]+$') {
    Fail "Invalid app name '$app' - expected app_<alphanumeric_or_underscore>"
}

if (-not $Template) {
    $Template = Join-Path $PSScriptRoot '..\templates\app_ai_template'
}
$resolvedTemplate = Resolve-Path $Template -ErrorAction SilentlyContinue
if (-not $resolvedTemplate) { Fail "Template folder not found: $Template (pass -Template)" }
$Template = $resolvedTemplate.Path

$Workspace = (Resolve-Path $Workspace).Path
$AppDir    = Join-Path $Workspace $app
if (-not $BuildScript) {
    $BuildScript = Join-Path $Workspace 'octavios\apps\build_sim.cmd'
}

if (Test-Path $AppDir) {
    Fail "$AppDir already exists - remove it first or pick another name"
}

# --- 0. Verify (and install) the toolchain --------------------------------
# Sim build needs MSVC; the cube .oct deliverable needs ARM GCC + CMake + Ninja.
# check_env.ps1 installs the winget-available device tools if they're missing.
if (-not $SkipEnvCheck) {
    Step "Checking toolchain (check_env.ps1)"
    & (Join-Path $PSScriptRoot 'check_env.ps1') -SkipMsvc:$SkipMsvc
    $envCode = $LASTEXITCODE
    if ($envCode -ne 0) {
        Write-Host "    toolchain check returned $envCode -- some tools missing." -ForegroundColor Yellow
        Write-Host "    Scaffolding continues; the device .oct build may not work until resolved." -ForegroundColor Yellow
    }
}

# --- 1. Clone the template ------------------------------------------------
Step "Cloning template -> $app"
Copy-Item -Recurse $Template $AppDir
# Strip any generated artifacts that may have been committed
foreach ($p in @('bin', 'out', 'art\packed', 'art\exported')) {
    $f = Join-Path $AppDir $p
    if (Test-Path $f) { Remove-Item -Recurse -Force $f }
}
Get-ChildItem -Recurse $AppDir -Include *.log, *.oct -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue

# --- 2. Rename name-bearing files -----------------------------------------
Step "Renaming marker and headers"
Get-ChildItem $AppDir -Recurse -File | Where-Object { $_.Name -like "*$TOKEN*" } | ForEach-Object {
    $newName = $_.Name.Replace($TOKEN, $app)
    Rename-Item $_.FullName $newName
}

# --- 3. Replace name references inside text files -------------------------
Step "Patching name references ($TOKEN -> $app)"
Get-ChildItem $AppDir -Recurse -File -Include *.h, *.txt | ForEach-Object {
    $raw = Get-Content $_.FullName -Raw
    if ($raw -match [regex]::Escape($TOKEN)) {
        ($raw -replace [regex]::Escape($TOKEN), $app) |
            Set-Content $_.FullName -NoNewline -Encoding utf8
    }
}

# --- 4. Guarantee the full beta define set in app.h ------------------------
$appH = Join-Path $AppDir 'src\app.h'
if (-not (Test-Path $appH)) { Fail "expected $appH after clone" }
$appHraw = Get-Content $appH -Raw

# Random non-zero 64-bit GUID for this app
$bytes = [byte[]]::new(8)
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
$guid = '0x{0:X16}ULL' -f [System.BitConverter]::ToUInt64($bytes, 0)

# Replace the template's zero GUID placeholder if present
if ($appHraw -match '0x0000000000000000ULL') {
    $appHraw = $appHraw -replace '0x0000000000000000ULL', $guid
    Step "Set APP_GUID1 = $guid"
}

$required = [ordered]@{
    'APP_VERSION'    = '#define APP_VERSION 100 //v1.00'
    'APP_TITLE'      = "#define APP_TITLE `"$app`""
    'APP_GUID1'      = "#define APP_GUID1 $guid"
    'APP_CATEGORIES' = '#define APP_CATEGORIES (APP_CATEGORY_GAME)'
    'APP_COLORS'     = '#define APP_COLORS 0x00000000'
}
$missing = $required.Keys | Where-Object { $appHraw -notmatch "define\s+$_" }
if ($missing) {
    Step "Adding missing defines to src/app.h: $($missing -join ', ')"
    $lines = $appHraw -split "`r?`n"
    $out = foreach ($l in $lines) {
        $l
        if ($l -match '^\s*#include\s+"app_') {
            foreach ($k in $missing) { $required[$k] }
        }
    }
    $appHraw = $out -join "`r`n"
}
Set-Content -Path $appH -Value $appHraw -Encoding UTF8

# --- 5. Pack assets (pure-Python packer; same on Windows and Linux) -------
# Replaces the legacy art/!pack.bat (psd.exe + utils.exe). The canonical packer
# is scripts/pack.py; it
# exports the PSD + fonts, builds the palette, writes art/packed/*.png and the
# decoded art/packed/*.raw the simulator loads, and emits _ids.h straight into
# src/ via --ids-output (no separate sync step needed).
$artDir = Join-Path $AppDir 'art'
$packPy = Join-Path $PSScriptRoot 'pack.py'
if (Test-Path $packPy) {
    Step "Packing assets (pack.py --emit-raw)"
    Push-Location $AppDir
    python $packPy --export --build-palette --build-ids --emit-raw `
        --art-dir art --exported-dir art\exported `
        --packed-dir art\packed --output-dir art\packed --raw-dir art\packed `
        --ids-output "src\${app}_ids.h" --assets assets | Out-Host
    $packCode = $LASTEXITCODE
    Pop-Location
    if ($packCode -ne 0) { Fail "asset packing failed (pack.py exit $packCode)" }

    $packed = Join-Path $artDir 'packed'
    $rawCount = (Get-ChildItem $packed -Filter *.raw -ErrorAction SilentlyContinue | Measure-Object).Count
    if ($rawCount -eq 0) { Fail "packing produced no .raw assets in $packed" }
    Write-Host "    packed $rawCount .raw assets; ids -> src/${app}_ids.h"
} else {
    Write-Host "    (scripts/pack.py not found at $packPy - skipping pack)" -ForegroundColor Yellow
}

# --- 6. Smoke-build the simulator (NOT arm) -------------------------------
if ($SkipBuild) {
    Step "SkipBuild set - scaffolding done, build skipped"
    Write-Host "INFRA SCAFFOLDED (build not verified): $AppDir" -ForegroundColor Green
    exit 0
}
if (-not (Test-Path $BuildScript)) {
    Fail "build script not found: $BuildScript (pass -BuildScript or -SkipBuild)"
}
Step "Building simulator (build_sim.cmd)"
Push-Location $AppDir
cmd /c "`"$BuildScript`"" | Out-Host
$buildCode = $LASTEXITCODE
Pop-Location
if ($buildCode -ne 0) { Fail "simulator build failed (exit $buildCode)" }

$exe = Join-Path $AppDir "bin\$app.exe"
if (-not (Test-Path $exe)) { Fail "build reported success but $exe is missing" }
Write-Host "    built $exe"

# --- 7. Optional run smoke test -------------------------------------------
if ($Run) {
    Step "Launching simulator (smoke test)"
    $p = Start-Process -FilePath $exe -PassThru
    Start-Sleep -Seconds 4
    if ($p.HasExited) {
        Fail "simulator exited early (code $($p.ExitCode)) - likely missing/unpacked assets"
    }
    Write-Host "    running OK (pid $($p.Id), '$($p.MainWindowTitle)')"
    # Leave it open for the user to inspect; they can close it.
}

Write-Host ""
Write-Host "INFRA READY: $AppDir" -ForegroundColor Green
Write-Host "  marker : $app.target"
Write-Host "  source : src/$app.h  (orchestrator writes game code here)"
Write-Host "  exe    : bin/$app.exe"
exit 0
