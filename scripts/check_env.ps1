<#
.SYNOPSIS
    Check the WowCube toolchain against the pipeline's minimum SDK (octavios dev 609d5ae, 2026-10-21).

.DESCRIPTION
    Reports, never changes anything unless -Install is given (and then only winget packages: ask the user
    first, these are downloads):
      SDK        octavios dev: engine\oct_app_version.h (OCT_APP_SEMVER), octpacker\ (octpack-build),
                 tools\mcp\ (simulator MCP), sim\src\sim_mcp.h; git checkouts must contain 609d5ae
                 wowcube/telemetry checked out NEXT TO octavios (the dev simulator links it)
      .oct build uv, Python 3.12 (uv-managed), clang++ or g++ (octpack's host probes; MSVC cl is not enough),
                 cmake, ninja, arm-none-eabi-g++
      simulator  MSVC C++ build tools (tools\sim_headless and the user's visible simulator)
      assets     python + Pillow, numpy, pytoshop, psd-tools (scripts\pack.py); ffmpeg (sound encoding)
      info       Codex CLI logged in with ChatGPT (image generation), long-path risk
    Exit 0 = everything required is present; 2 = something required is missing; 3 = -Install without winget.

.PARAMETER Octavios  octavios checkout. Default: $env:OCTAVIOS_DIR, else <Workspace>\octavios.
.PARAMETER Workspace Default: the current folder.
.PARAMETER Install   Install the missing winget-installable tools (uv, LLVM, CMake, Ninja, Arm GNU toolchain,
                     FFmpeg, VS 2022 Build Tools). Only after the user agreed. Installs are unattended and
                     windowless: winget --silent, the VS installer --quiet --norestart (never --passive).
.PARAMETER SkipMsvc  Do not count/install MSVC.
.PARAMETER ReportOnly  Accepted for compatibility; reporting is the default.
#>
[CmdletBinding()]
param(
    [string] $Octavios,
    [string] $Workspace = (Get-Location).Path,
    [switch] $Install,
    [switch] $SkipMsvc,
    [switch] $ReportOnly
)

function Step($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Have($exe) { return [bool](Get-Command $exe -ErrorAction SilentlyContinue) }
$missing = New-Object System.Collections.ArrayList   # @{ What; Fix; Pkg }
function Ok($m)   { Write-Host "  [ok]      $m" }
function Info($m) { Write-Host "  [info]    $m" -ForegroundColor DarkGray }
function Warn($m) { Write-Host "  [warn]    $m" -ForegroundColor Yellow }
function Miss($what, $fix, $pkg = $null) {
    Write-Host "  [MISSING] $what  -> $fix" -ForegroundColor Yellow
    [void]$missing.Add(@{ What = $what; Fix = $fix; Pkg = $pkg })
}

Step "WowCube toolchain (minimum SDK: octavios dev 609d5ae, 2026-10-21)"

# --- SDK -------------------------------------------------------------------
if (-not $Octavios) { $Octavios = $(if ($env:OCTAVIOS_DIR) { $env:OCTAVIOS_DIR } else { Join-Path $Workspace 'octavios' }) }
$oct = (Resolve-Path -LiteralPath $Octavios -ErrorAction SilentlyContinue).Path
if (-not $oct -or -not (Test-Path (Join-Path $oct 'engine'))) {
    Miss "octavios SDK at $Octavios" "git clone https://github.com/wowcube/octavios.git (branch dev) next to your apps, or pass -Octavios"
} else {
    $features = [ordered]@{
        'engine\oct_app_version.h'      = 'OCT_APP_SEMVER versions (app_metadata.h layout)'
        'octpacker\pyproject.toml'      = 'octpack-build (official .oct build)'
        'tools\mcp\octavios_mcp.py'     = 'simulator MCP bridge'
        'sim\src\sim_mcp.h'             = 'simulator MCP control socket'
        'tools\new_app.ps1'             = 'octpack-new scaffold, app_metadata.h template (PR #137)'
    }
    $old = @()
    foreach ($f in $features.Keys) { if (-not (Test-Path (Join-Path $oct $f))) { $old += "$f ($($features[$f]))" } }
    # the 609d5ae import set: also answers for an export without git history
    $mod = Join-Path $oct 'engine\oct_app_module.h'
    if ((Test-Path $mod) -and -not (Select-String -Quiet -SimpleMatch 'cube_pose_visual' -LiteralPath $mod)) {
        $old += 'engine\oct_app_module.h without cube_pose_visual (the 609d5ae import set)'
    }
    $commit = ''
    if ((Test-Path (Join-Path $oct '.git')) -and (Have 'git')) {
        $commit = (& git -C $oct log -1 --format='%h %cs' 2>$null) -join ''
        & git -C $oct cat-file -e '609d5ae^{commit}' 2>$null
        if ($LASTEXITCODE -ne 0) { $old += 'commit 609d5ae not in this clone (fetch + pull dev)' }
        else {
            & git -C $oct merge-base --is-ancestor 609d5ae HEAD 2>$null
            if ($LASTEXITCODE -ne 0) { $old += 'HEAD does not contain 609d5ae' }
        }
    }
    if ($old.Count) {
        Miss "octavios at $oct is older than dev 609d5ae$(if ($commit) { " (HEAD $commit)" }): lacks $($old -join '; ')" `
             "git -C $oct pull --ff-only origin dev; then delete every app_*\out (CMake caches bind to the old checkout)"
    } else {
        Ok "octavios dev at $oct$(if ($commit) { " (HEAD $commit)" })"
    }
    $tel = Join-Path (Split-Path $oct -Parent) 'telemetry'
    if (Test-Path (Join-Path $tel 'octavios_simulator\telemetry_sim.cpp')) { Ok "telemetry next to octavios ($tel)" }
    else { Miss "wowcube/telemetry next to octavios ($tel)" "git clone https://github.com/wowcube/telemetry.git $tel (the dev simulator will not build without it)" }
    if ($oct.Length -gt 90) { Warn "octavios path is $($oct.Length) chars: octpack (Python) fails past MAX_PATH; prefer a short checkout path" }
}

# --- .oct build (octpack-build) ----------------------------------------------
if (Have 'uv') {
    Ok "uv ($((& uv --version) -join ''))"
    $py312 = (& uv python find 3.12 2>$null) -join ''
    if ($LASTEXITCODE -eq 0 -and $py312) { Ok "Python 3.12 for octpacker ($py312)" }
    else { Info "no uv-managed Python 3.12 yet: the first octpack run downloads it (uv python install 3.12)" }
} else { Miss "uv (runs octavios\octpacker)" "winget install astral-sh.uv" 'astral-sh.uv' }

$cxx = $null
if ($env:CXX) { $cxx = $env:CXX }
elseif (Have 'clang++') { $cxx = (Get-Command clang++).Source }
elseif (Test-Path 'C:\Program Files\LLVM\bin\clang++.exe') { $cxx = 'C:\Program Files\LLVM\bin\clang++.exe' }
elseif (Have 'g++') { $cxx = (Get-Command g++).Source }
else {
    $vswhere0 = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (Test-Path $vswhere0) {
        $vsp = & $vswhere0 -latest -property installationPath 2>$null
        foreach ($c in "$vsp\VC\Tools\Llvm\x64\bin\clang++.exe", "$vsp\VC\Tools\Llvm\bin\clang++.exe") { if ($vsp -and (Test-Path $c)) { $cxx = $c; break } }
    }
}
if ($cxx) { Ok "host C++ compiler for octpack probes ($cxx)" } else { Miss "clang++ or g++ (octpack compiles small probes; MSVC cl is not supported)" "winget install LLVM.LLVM" 'LLVM.LLVM' }

foreach ($t in @(
        @{ Name = 'cmake';             Pkg = 'Kitware.CMake';               What = 'cmake (ARM build)' },
        @{ Name = 'ninja';             Pkg = 'Ninja-build.Ninja';           What = 'ninja (ARM build)' },
        @{ Name = 'arm-none-eabi-g++'; Pkg = 'Arm.GnuArmEmbeddedToolchain'; What = 'arm-none-eabi-g++ (ARM module in the .oct)' })) {
    if (Have $t.Name) { Ok $t.What } else { Miss $t.What "winget install $($t.Pkg)" $t.Pkg }
}

# --- simulator (MSVC) ----------------------------------------------------------
$MSVC_PKG  = 'Microsoft.VisualStudio.2022.BuildTools'
# --quiet: no installer window at all (--passive would show its progress UI over the user's screen);
# --norestart: an unattended install never reboots the machine
$MSVC_ARGS = '--quiet --wait --norestart --add Microsoft.VisualStudio.Workload.VCTools --add Microsoft.VisualStudio.Component.Windows11SDK.22621 --includeRecommended'
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$msvcOk = $false
if (Test-Path $vswhere) { if (& $vswhere -latest -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath 2>$null) { $msvcOk = $true } }
if ($msvcOk) { Ok "MSVC C++ build tools (tools\sim_headless, visible simulator)" }
elseif ($SkipMsvc) { Info "MSVC not checked (-SkipMsvc)" }
else { Miss "MSVC C++ build tools + Windows SDK (simulator builds; several GB)" "winget install --id $MSVC_PKG -e --override `"$MSVC_ARGS`"" 'MSVC' }

# --- assets ----------------------------------------------------------------
$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) { Miss "python 3 (pipeline scripts)" "install Python 3.10+ (python.org or the Microsoft Store)" }
else {
    $code = "import importlib.util as u; print(' '.join(m for m in ['PIL', 'numpy', 'pytoshop', 'psd_tools'] if u.find_spec(m) is None))"
    $absent = (& $python -c $code 2>$null) -join ''
    if ($LASTEXITCODE -ne 0) { Warn "could not query python packages with $python" }
    elseif ($absent.Trim()) { Miss "python packages: $($absent.Trim())" "python -m pip install -r <skills repo>\scripts\requirements.txt" }
    else { Ok "python + Pillow/numpy/pytoshop/psd-tools ($python)" }
}
if (Have 'ffmpeg') { Ok "ffmpeg (sound encoding: scripts\sound_kit.py, gen_sounds.py)" } else { Miss "ffmpeg (sound encoding)" "winget install Gyan.FFmpeg" 'Gyan.FFmpeg' }

# --- informational ------------------------------------------------------------
$codex = $null
$codexDir = Join-Path $env:LOCALAPPDATA 'OpenAI\Codex\bin'
if (Test-Path $codexDir) { $codex = Get-ChildItem $codexDir -Recurse -Filter codex.exe -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName }
if (-not $codex -and (Have 'codex')) { $codex = (Get-Command codex).Source }
if ($codex) {
    $status = (cmd /d /c "`"$codex`" login status 2>&1" | Out-String).Trim()   # cmd merges stderr; PS 5.1 would wrap it in error records
    if ($status -match 'ChatGPT') { Info "Codex CLI logged in ($status) - default image provider" }
    else { Info "Codex CLI found but not logged in with ChatGPT ($status): the user runs 'codex login' themselves" }
} else { Info "Codex CLI not found: image generation falls back to the paid-API providers (cube_art-director)" }
try {
    $lp = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' -Name LongPathsEnabled -ErrorAction Stop).LongPathsEnabled
    if ($lp -ne 1) { Info "LongPathsEnabled=0: keep the workspace path short (Python and cl.exe fail past 260 chars)" }
} catch { }

# --- result / install ---------------------------------------------------------------
Write-Host ""
if ($missing.Count -eq 0) { Write-Host "Toolchain OK." -ForegroundColor Green; exit 0 }
if (-not $Install) {
    Write-Host "Missing $($missing.Count) item(s). Fix with the commands above; winget-installable ones: re-run with -Install (after the user agreed)." -ForegroundColor Yellow
    exit 2
}
if (-not (Have 'winget')) { Write-Host "winget is not available - install the items above manually." -ForegroundColor Red; exit 3 }
foreach ($m in $missing) {
    if (-not $m.Pkg) { continue }
    if ($m.Pkg -eq 'MSVC') {
        Step "Installing MSVC build tools (large download)"
        winget install --id $MSVC_PKG -e --accept-package-agreements --accept-source-agreements --override $MSVC_ARGS | Out-Host
    } else {
        Step "Installing $($m.Pkg)"
        winget install --id $m.Pkg -e --accept-package-agreements --accept-source-agreements --silent | Out-Host
    }
}
Write-Host "Install attempted. Open a NEW shell (PATH changes) and re-run this check." -ForegroundColor Yellow
exit 2
