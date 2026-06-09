<#
.SYNOPSIS
    Verify (and optionally install) the WowCube build toolchain.

.DESCRIPTION
    The simulator build needs MSVC (Visual Studio C++ build tools + a Windows
    SDK). The cube-loadable .oct deliverable additionally needs the ARM device
    toolchain: the ARM GNU embedded compiler, CMake, and Ninja. This script
    checks what's present and installs whatever is missing via winget.

    MSVC is installed as the VS 2022 Build Tools with the "Desktop development
    with C++" (VCTools) workload + Windows 11 SDK. This is a large download
    (several GB) and can take a while, but it runs unattended (--passive) so the
    user is guaranteed the full simulator toolchain at infra-setup time.

.PARAMETER ReportOnly
    Only report status; never run winget. Exit code reflects readiness.

.PARAMETER SkipMsvc
    Skip the MSVC install even if it's missing (e.g. it's being installed
    separately, or you only need the device toolchain).

.OUTPUTS
    Exit 0  = everything needed is present (or was just installed).
    Exit 2  = one or more device-toolchain tools are still missing.
    Exit 3  = winget itself is unavailable, so missing tools can't be installed.
#>
[CmdletBinding()]
param(
    [switch] $ReportOnly,
    [switch] $SkipMsvc
)

function Step($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Have($exe) { return [bool](Get-Command $exe -ErrorAction SilentlyContinue) }

# MSVC (simulator build): VS 2022 Build Tools + "Desktop development with C++"
# (VCTools) workload + Windows 11 SDK. --passive runs unattended with a progress
# UI; --includeRecommended pulls the matching compiler + redist. Installed via
# winget --override so the exact VS components are pinned.
$MSVC_PKG  = 'Microsoft.VisualStudio.2022.BuildTools'
$MSVC_ARGS = '--passive --wait --add Microsoft.VisualStudio.Workload.VCTools ' +
             '--add Microsoft.VisualStudio.Component.Windows11SDK.22621 --includeRecommended'

# device tool -> winget package id
$TOOLS = @(
    @{ Name = 'arm-none-eabi-gcc'; Pkg = 'ARM.GnuArmEmbeddedToolchain'; Purpose = 'ARM device compile (.bin for .oct)' },
    @{ Name = 'cmake';             Pkg = 'Kitware.CMake';               Purpose = 'device build generator' },
    @{ Name = 'ninja';             Pkg = 'Ninja-build.Ninja';           Purpose = 'device build backend' }
)

Step "Checking WowCube toolchain"

# --- MSVC (simulator build) -----------------------------------------------
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$msvcOk = $false
if (Test-Path $vswhere) {
    $vsPath = & $vswhere -latest -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath 2>$null
    if ($vsPath) { $msvcOk = $true }
}
if ($msvcOk) {
    Write-Host "  [ok]      MSVC C++ build tools + Windows SDK (simulator build)"
} elseif ($SkipMsvc) {
    Write-Host "  [skip]    MSVC C++ build tools (simulator build) -- -SkipMsvc set" -ForegroundColor Yellow
} else {
    Write-Host "  [MISSING] MSVC C++ build tools + Windows SDK (simulator build)" -ForegroundColor Yellow
}

# --- Device toolchain (ARM .bin -> .oct) ----------------------------------
$wingetOk = Have 'winget'
$missing = @()
foreach ($t in $TOOLS) {
    if (Have $t.Name) {
        Write-Host "  [ok]      $($t.Name)  ($($t.Purpose))"
    } else {
        Write-Host "  [MISSING] $($t.Name)  ($($t.Purpose))" -ForegroundColor Yellow
        $missing += $t
    }
}

# MSVC counts as "needing action" only when missing and not explicitly skipped.
$needMsvc = (-not $msvcOk) -and (-not $SkipMsvc)

if ($missing.Count -eq 0 -and -not $needMsvc) {
    Write-Host ""
    Write-Host "Toolchain OK." -ForegroundColor Green
    if (-not $msvcOk) { exit 2 }   # device tools fine, but sim can't build (-SkipMsvc)
    exit 0
}

if ($ReportOnly) {
    Write-Host ""
    Write-Host "Missing tools (install with):" -ForegroundColor Yellow
    if ($needMsvc) {
        Write-Host "  winget install --id $MSVC_PKG -e --override `"$MSVC_ARGS`""
    }
    foreach ($t in $missing) { Write-Host "  winget install $($t.Pkg)" }
    exit 2
}

if (-not $wingetOk) {
    Write-Host ""
    Write-Host "winget is not available -- install these manually:" -ForegroundColor Red
    if ($needMsvc) {
        Write-Host "  winget install --id $MSVC_PKG -e --override `"$MSVC_ARGS`""
    }
    foreach ($t in $missing) { Write-Host "  winget install $($t.Pkg)" }
    exit 3
}

# --- Install MSVC (simulator build) via winget ----------------------------
# Large download (several GB); --passive shows progress without prompting.
if ($needMsvc) {
    Step "Installing MSVC build tools  (VS 2022 Build Tools + VCTools + Win11 SDK)"
    Write-Host "    This is a large download and may take several minutes..." -ForegroundColor DarkGray
    winget install --id $MSVC_PKG -e `
        --accept-package-agreements --accept-source-agreements `
        --override $MSVC_ARGS | Out-Host
}

# --- Install missing device tools via winget ------------------------------
foreach ($t in $missing) {
    Step "Installing $($t.Name)  (winget install $($t.Pkg))"
    winget install --id $t.Pkg -e --accept-package-agreements --accept-source-agreements --silent | Out-Host
}

Write-Host ""
Write-Host "Install attempted. NOTE: a freshly installed tool may not be on PATH" -ForegroundColor Yellow
Write-Host "until you open a NEW shell. Re-run this script in a new terminal to confirm." -ForegroundColor Yellow

# Re-check in the current session (best effort). MSVC presence is re-probed via
# vswhere since it doesn't land on PATH as a plain exe.
$stillMissing = @($TOOLS | Where-Object { -not (Have $_.Name) })
$msvcNow = $msvcOk
if ($needMsvc -and (Test-Path $vswhere)) {
    $vsPath2 = & $vswhere -latest -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath 2>$null
    if ($vsPath2) { $msvcNow = $true }
}
if ($stillMissing.Count -eq 0 -and ($msvcNow -or $SkipMsvc)) { exit 0 }
exit 2
