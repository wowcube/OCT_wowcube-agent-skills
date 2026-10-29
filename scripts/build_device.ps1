<#
.SYNOPSIS
    Build the cube-loadable .oct of an app_<game> folder into <workspace>\dist\, verified. No simulator.

.DESCRIPTION
    Builder "octpack" (default when available): the SDK's official one-command build (octavios dev 609d5ae+):
        uv run --frozen --project <octavios>\octpacker octpack-build <AppDir> --out <Out> --engine <octavios>
      It compiles src\app_metadata.h for the header fields, packs art\octpack.json if the app has one (our
      AI-art apps do not: their art\packed + index.bin from the python packer are used as they are), builds
      the ARM module (cmake + Ninja into out\) and writes the .oct. Needs uv, Python 3.12 (uv-managed),
      clang++ (or g++), cmake, ninja, arm-none-eabi-g++.
    Builder "python" (fallback): cmake + Ninja ARM build, then scripts\pack_beta.py --build-oct. It stamps
      SaveSize from APP_SAVE_SIZE reached through src/app_metadata.h (sizeof(record) read from the
      static_assert of its wire size in app_save.h), like octpack-build's host probe.
    Verification (both, mandatory): the last <size of out\<app>.bin> bytes of the .oct are the ARM code, then
      scripts\pack_beta.py --verify-oct: magic, Size, CRC32, code_size/offset, a non-zero build id, title /
      version / GUID / categories / save size == the app's defines (src\app.h -> app_metadata.h -> app_save.h),
      the launcher map "ico", assets == index.bin. The header comes from octpack-info when it runs, otherwise
      from a local read; any mismatch, or anything that cannot be checked, fails the build (exit 1).
    The deliverable lives in dist\ because the Windows simulator rewrites <app>\<app>.oct on every launch.

.PARAMETER AppDir    The app_<game> folder (one *.target; packed: index.bin + art\packed).
.PARAMETER OctaviOS  octavios SDK. Default: <AppDir>\..\octavios.
.PARAMETER Out       Output .oct. Default: <AppDir>\..\dist\<app>.oct.
.PARAMETER Builder   auto (default) | octpack | python.
.PARAMETER UvEnv     octpacker's Python environment. Default: UV_PROJECT_ENVIRONMENT, else <AppDir>\..\.uv_octpack_venv:
                     never inside octavios. Its first creation downloads the pinned packages (the one-time bootstrap
                     the user approves, AGENT_SAFETY.md); later builds reuse it.
.PARAMETER NoUv      Never start uv (python builder + the local header check); also WOWCUBE_NO_UV=1. repack_app.py
                     passes it when it runs on the Microsoft Store Python: everything that Python starts sees a
                     private copy of AppData, so uv would not find its managed Python and would rebuild the
                     octpacker environment.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\build_device.ps1 -AppDir C:\ws\app_tetris
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $AppDir,
    [string] $OctaviOS,
    [string] $Out,
    [ValidateSet('auto', 'octpack', 'python')] [string] $Builder = 'auto',
    [string] $UvEnv,
    [switch] $NoUv
)

$ErrorActionPreference = 'Stop'
function Fail($m) { Write-Host "ERROR: $m" -ForegroundColor Red; exit 1 }
function Step($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Have($exe) { return [bool](Get-Command $exe -ErrorAction SilentlyContinue) }

# --- resolve ----------------------------------------------------------------
$AppDir = (Resolve-Path -LiteralPath $AppDir -ErrorAction SilentlyContinue).Path
if (-not $AppDir) { Fail "app folder not found" }
$targets = @(Get-ChildItem -LiteralPath $AppDir -Filter *.target -File)
if ($targets.Count -ne 1) { Fail "$AppDir must hold exactly one *.target marker (found $($targets.Count))" }
$app = [IO.Path]::GetFileNameWithoutExtension($targets[0].Name)
if (-not (Test-Path (Join-Path $AppDir 'index.bin'))) { Fail "$AppDir\index.bin missing - pack the assets first (Stage 3)" }

if (-not $OctaviOS) { $OctaviOS = Join-Path $AppDir '..\octavios' }
$OctaviOS = (Resolve-Path -LiteralPath $OctaviOS -ErrorAction SilentlyContinue).Path
if (-not $OctaviOS -or -not (Test-Path (Join-Path $OctaviOS 'apps\CMakeLists.txt'))) { Fail "octavios SDK not found (pass -OctaviOS)" }

if (-not $Out) { $Out = Join-Path (Split-Path $AppDir -Parent) "dist\$app.oct" }
$Out = [IO.Path]::GetFullPath($ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Out))
New-Item -ItemType Directory -Force -Path (Split-Path $Out -Parent) | Out-Null

$metadata = Join-Path $AppDir 'src\app_metadata.h'
$octpackProject = Join-Path $OctaviOS 'octpacker'
# octpacker's environment lives in the workspace, never in the SDK tree (uv would otherwise create octpacker\.venv)
if (-not $UvEnv) { $UvEnv = $(if ($env:UV_PROJECT_ENVIRONMENT) { $env:UV_PROJECT_ENVIRONMENT } else { Join-Path (Split-Path $AppDir -Parent) '.uv_octpack_venv' }) }
# absolute from the caller's PowerShell location (uv would resolve a relative one inside octpacker\, the SDK tree;
# [IO.Path]::GetFullPath alone uses the process cwd, which Set-Location does not move)
$env:UV_PROJECT_ENVIRONMENT = [IO.Path]::GetFullPath($ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($UvEnv))
if ($env:WOWCUBE_NO_UV -match '^(1|true|yes)$') { $NoUv = $true }
$useUv = (Have 'uv') -and -not $NoUv
if ($NoUv) { Write-Host "    NOTE: -NoUv / WOWCUBE_NO_UV: uv is not started (python builder, local header check)" -ForegroundColor Yellow }
$octpackReady = (Test-Path (Join-Path $octpackProject 'pyproject.toml')) -and $useUv -and (Test-Path $metadata)
if ($Builder -eq 'auto') { $Builder = $(if ($octpackReady) { 'octpack' } else { 'python' }) }
if ($Builder -eq 'octpack' -and -not $octpackReady) {
    Fail ("octpack-build needs octavios dev (octpacker\pyproject.toml), uv on PATH (and no -NoUv) and src\app_metadata.h " +
          "(scripts\check_env.ps1 lists what is missing); or pass -Builder python")
}

$bin = Join-Path $AppDir "out\$app.bin"
$started = Get-Date

# --- 1. build ----------------------------------------------------------------
if ($Builder -eq 'octpack') {
    if (Test-Path (Join-Path $AppDir 'art\octpack.json')) {
        Write-Host "    NOTE: art\octpack.json present: octpack-build re-packs art from its PSD/raw sources (wipes art\packed and index.bin)." -ForegroundColor Yellow
    }
    Step "octpack-build $app -> $Out"
    $venvState = $(if (Test-Path (Join-Path $env:UV_PROJECT_ENVIRONMENT 'pyvenv.cfg')) { 'reused' } else { 'FIRST USE: uv creates it and downloads the pinned packages' })
    Write-Host "    octpacker environment: $($env:UV_PROJECT_ENVIRONMENT) ($venvState)"
    & uv run --frozen --project $octpackProject octpack-build $AppDir --out $Out --engine $OctaviOS
    if ($LASTEXITCODE -ne 0) { Fail "octpack-build failed (exit $LASTEXITCODE). Stale out\ from another SDK checkout? Delete $AppDir\out and retry." }
} else {
    foreach ($t in 'arm-none-eabi-g++', 'cmake', 'ninja', 'python') {
        if (-not (Have $t)) { Fail "$t not on PATH - run scripts\check_env.ps1" }
    }
    $packPy = Join-Path $PSScriptRoot 'pack_beta.py'
    Step "ARM device build (cmake + Ninja) for $app"
    $outDir = Join-Path $AppDir 'out'
    & cmake -G Ninja -S (Join-Path $OctaviOS 'apps') -B $outDir -DAPP_TELEMETRY=OFF | Out-Host
    if ($LASTEXITCODE -ne 0) { Fail "cmake configure failed. Stale out\ from another SDK checkout? Delete $outDir and retry." }
    & cmake --build $outDir --parallel 4 | Out-Host
    if ($LASTEXITCODE -ne 0) { Fail "ARM build failed (exit $LASTEXITCODE)" }
    Step "Packing .oct (python scripts\pack_beta.py --build-oct)"
    if (Test-Path $Out) { Remove-Item -Force $Out }
    & python $packPy --build-oct --app-dir $AppDir --code $bin --out $Out | Out-Host
    if ($LASTEXITCODE -ne 0) { Fail "python .oct builder failed (exit $LASTEXITCODE)" }
}

# --- 2. verify -----------------------------------------------------------------
if (-not (Test-Path $Out)) { Fail "no .oct at $Out" }
if ((Get-Item $Out).LastWriteTime -lt $started) { Fail "$Out was not rewritten by this build" }
if (-not (Test-Path $bin)) { Fail "no ARM module at $bin" }
$binBytes = [IO.File]::ReadAllBytes($bin)
$octBytes = [IO.File]::ReadAllBytes($Out)
if ($binBytes.Length -eq 0) { Fail "$bin is empty - the ARM build produced no code" }
$embedded = $octBytes.Length -ge $binBytes.Length
if ($embedded) {
    $start = $octBytes.Length - $binBytes.Length
    for ($i = 0; $i -lt $binBytes.Length; $i++) { if ($octBytes[$start + $i] -ne $binBytes[$i]) { $embedded = $false; break } }
}
if (-not $embedded) { Fail "the .oct does NOT end with out\$app.bin: no ARM code, dead on the cube" }
Write-Host "    ARM code embedded ($($binBytes.Length) bytes)"

# Header verification is MANDATORY: magic, size, CRC, the ARM tail, a non-zero build id, title/version/GUID/
# categories/save size == the app's defines, MAP "ico", assets == index.bin (scripts\pack_beta.py --verify-oct).
# octpack-info supplies the header when it runs (engine-answered offsets); otherwise the same checks run on a local
# read of the header. Whatever cannot be verified fails the build.
$version = ''
$packPyVerify = Join-Path $PSScriptRoot 'pack_beta.py'
if (-not (Have 'python')) { Fail "cannot verify $Out`: python is not on PATH (scripts\pack_beta.py --verify-oct reads the header) - run scripts\check_env.ps1" }
$infoFile = $null
if ((Test-Path (Join-Path $octpackProject 'pyproject.toml')) -and $useUv) {
    $json = & uv run --frozen --project $octpackProject octpack-info $Out --engine $OctaviOS
    if ($LASTEXITCODE -eq 0 -and $json) {
        $infoFile = Join-Path ([IO.Path]::GetTempPath()) ("octpack_info_{0}.json" -f [guid]::NewGuid().ToString('N'))
        ($json -join "`n") | Set-Content -LiteralPath $infoFile -Encoding UTF8
    } else {
        Write-Host "    octpack-info failed (exit $LASTEXITCODE): verifying with the local header check instead" -ForegroundColor Yellow
    }
} else {
    Write-Host "    uv/octpacker not available$(if ($NoUv) { ' (-NoUv)' }): verifying with the local header check (scripts\pack_beta.py)" -ForegroundColor Yellow
}
$verifyArgs = @($packPyVerify, '--verify-oct', $Out, '--app-dir', $AppDir, '--code', $bin)
if ($infoFile) { $verifyArgs += @('--info-json', $infoFile) }
$verifyOut = @(& python @verifyArgs)
$verifyCode = $LASTEXITCODE
if ($infoFile) { Remove-Item -LiteralPath $infoFile -Force -ErrorAction SilentlyContinue }
foreach ($line in $verifyOut) { Write-Host $line }
if ($verifyCode -ne 0) { Fail ".oct verification failed (exit $verifyCode): see the ERROR lines above - nothing to deliver" }
$vm = [regex]::Match(($verifyOut -join "`n"), '(?m)^VERSION=(\S+)')
if ($vm.Success) { $version = $vm.Groups[1].Value }

Write-Host ""
Write-Host "CUBE PACKAGE READY ($Builder): $Out" -ForegroundColor Green
Write-Host "  $($octBytes.Length) bytes = assets + sounds + $($binBytes.Length) bytes ARM code$(if ($version) { "; version $version" })"
Write-Host "  Upload when the user asks: tools\cube_upload\run_upload.ps1 -Octavios $OctaviOS -Mac <cube MAC> -Oct $Out"
Write-Host "  Deliver this file, never <app>\$app.oct (the Windows simulator rewrites that one on every launch)."
exit 0
