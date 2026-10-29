<#
.SYNOPSIS
    Scaffold app_<name> from the AI template in the octavios dev layout, pack its assets, and prove the
    simulator builds - the infra gate before the first technical prompt. Never opens a window.

.DESCRIPTION
      0. Toolchain report (check_env.ps1; installs nothing)
      1. Copy templates\app_ai_template -> <Workspace>\app_<name>
      2. Rename the .target marker and the game/ids headers to app_<name>*
      3. Replace the template name in every text file (app.h, app_<name>.h, APP_DIR)
      4. Dev metadata: src\app_metadata.h with a RANDOM APP_GUID1 and the human title (APP_VERSION as
         OCT_APP_SEMVER(MAJOR, MINOR, PATCH)); src\app.h includes it first and defines none of its macros;
         -WithSave enables src\app_save.h (the save area); SIM_SINGLE_THREAD is never defined
      5. Pack the art with the python packer (scripts\pack.py, beta container + launcher "ico" map from
         art\icon.png); _ids.h straight into src\
      6. Build the hidden simulator for the app (tools\sim_headless\build.ps1) - compiles the app, starts nothing
      7. -Smoke (alias -Run): one hidden, silent run of -SmokeSeconds with a PNG of all 24 screens every second
         (tools\sim_headless\run.ps1); prints the last frame for the agent to inspect
    Exit 0 = infrastructure verified. Non-zero = the step named in the message failed.

.PARAMETER Name          "tetris" or "app_tetris" -> folder app_tetris.
.PARAMETER Workspace     Folder holding octavios\, telemetry\ and the apps. Default: current folder.
.PARAMETER Title         APP_TITLE (<= 79 bytes). Default: from the name ("app_my_game" -> "My Game").
.PARAMETER Template      Default: ..\templates\app_ai_template next to this script.
.PARAMETER Octavios      Default: <Workspace>\octavios.
.PARAMETER WithSave      Give the app a save area (app_save.h included by app_metadata.h).
.PARAMETER Smoke         After the build, one hidden smoke run (never a visible window, never sound).
.PARAMETER Run           Old name of -Smoke (it used to open a visible window; it no longer does).
.PARAMETER SmokeSeconds  Length of the smoke run. Default 15 (octavios dev shows a ~3 s boot intro first).
.PARAMETER VisibleSim    Also build the normal simulator for the USER (tools\sim_headless\build.ps1 -Visible).
.PARAMETER SkipBuild     Scaffold + pack only.
.PARAMETER SkipEnvCheck  Skip the toolchain report.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\new_app.ps1 -Name tetris -Workspace C:\ws -Smoke
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $Name,
    [string] $Workspace = (Get-Location).Path,
    [string] $Title,
    [string] $Template,
    [string] $Octavios,
    [switch] $WithSave,
    [switch] $Smoke,
    [switch] $Run,
    [int]    $SmokeSeconds = 15,
    [switch] $VisibleSim,
    [switch] $SkipBuild,
    [switch] $SkipEnvCheck,
    [switch] $SkipMsvc
)

$ErrorActionPreference = 'Stop'
$TOKEN = 'app_ai_template'   # literal name baked into the template files
function Fail($msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }
function Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function ReadText($p) { [IO.File]::ReadAllText($p) }
function WriteText($p, $text) {
    $b = [IO.File]::ReadAllBytes($p)
    $bom = $b.Length -ge 3 -and $b[0] -eq 0xEF -and $b[1] -eq 0xBB -and $b[2] -eq 0xBF
    [IO.File]::WriteAllText($p, $text, (New-Object System.Text.UTF8Encoding($bom)))
}
# first match only (the static [regex]::Replace has no count overload: a 4th argument would be RegexOptions)
function ReplaceOnce($text, $pattern, $replacement) { return ([regex]$pattern).Replace($text, $replacement, 1) }
if ($Run) { $Smoke = $true }

# --- names and paths ----------------------------------------------------------
$app = if ($Name -match '^app_') { $Name } else { "app_$Name" }
if ($app -notmatch '^app_[A-Za-z0-9_]+$') { Fail "invalid app name '$app' (expected app_<letters, digits, _>)" }
$game = $app.Substring(4)
if (-not $Title) { $Title = (($game -split '_' | Where-Object { $_ } | ForEach-Object { $_.Substring(0, 1).ToUpper() + $_.Substring(1) }) -join ' ') }
if ([Text.Encoding]::UTF8.GetByteCount($Title) -gt 79) { Fail "title '$Title' is longer than 79 bytes" }
if ($Title -match '["\\]') { Fail "title must not contain quotes or backslashes" }

if (-not $Template) { $Template = Join-Path $PSScriptRoot '..\templates\app_ai_template' }
$Template = (Resolve-Path -LiteralPath $Template -ErrorAction SilentlyContinue).Path
if (-not $Template) { Fail "template folder not found (pass -Template)" }
$Workspace = (Resolve-Path -LiteralPath $Workspace).Path
$AppDir = Join-Path $Workspace $app
if (-not $Octavios) { $Octavios = Join-Path $Workspace 'octavios' }
if (Test-Path $AppDir) { Fail "$AppDir already exists - remove it first or pick another name" }

# --- 0. toolchain report (installs nothing) ---------------------------------------
if (-not $SkipEnvCheck) {
    Step "Toolchain report (check_env.ps1)"
    & (Join-Path $PSScriptRoot 'check_env.ps1') -Octavios $Octavios -Workspace $Workspace -SkipMsvc:$SkipMsvc
    if ($LASTEXITCODE -ne 0) { Write-Host "    toolchain incomplete (see above); scaffolding continues, later steps may fail" -ForegroundColor Yellow }
}

# --- 1. clone ----------------------------------------------------------------------
Step "Cloning template -> $app"
Copy-Item -Recurse -LiteralPath $Template -Destination $AppDir
foreach ($p in 'bin', 'out', 'build-sim', 'art\packed', 'art\exported', 'index.bin') {
    $f = Join-Path $AppDir $p
    if (Test-Path $f) { Remove-Item -Recurse -Force $f }
}
# (no -Include with -LiteralPath: Windows PowerShell 5.1 ignores the filter there and would match every file)
Get-ChildItem -LiteralPath $AppDir -Recurse -File | Where-Object { $_.Extension -in '.log', '.oct' } | Remove-Item -Force
if (Test-Path (Join-Path $AppDir 'art\octpack.json')) {
    # AI-art apps are packed by scripts\pack.py; octpack-build would re-pack (and wipe) them from these PSD sources
    Rename-Item (Join-Path $AppDir 'art\octpack.json') 'octpack.json.template'
    Write-Host "    art\octpack.json -> octpack.json.template (AI-art apps are packed by scripts\pack.py)"
}

# --- 2. rename name-bearing files ----------------------------------------------------
Step "Renaming marker and headers"
Get-ChildItem -LiteralPath $AppDir -Recurse -File | Where-Object { $_.Name -like "*$TOKEN*" } | ForEach-Object {
    Rename-Item -LiteralPath $_.FullName ($_.Name.Replace($TOKEN, $app))
}

# --- 3. replace name references in text files ------------------------------------------
Step "Patching name references ($TOKEN -> $app)"
Get-ChildItem -LiteralPath $AppDir -Recurse -File | Where-Object { $_.Extension -in '.h', '.txt', '.json', '.md' } | ForEach-Object {
    $raw = ReadText $_.FullName
    if ($raw.Contains($TOKEN)) { WriteText $_.FullName ($raw.Replace($TOKEN, $app)) }
}

# --- 4. dev metadata ----------------------------------------------------------------------
$src = Join-Path $AppDir 'src'
$appH = Join-Path $src 'app.h'
$metaH = Join-Path $src 'app_metadata.h'
$saveH = Join-Path $src 'app_save.h'
if (-not (Test-Path $appH)) { Fail "expected $appH after the clone" }
$bytes = [byte[]]::new(8)
do { [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes); $guidValue = [BitConverter]::ToUInt64($bytes, 0) } while ($guidValue -eq 0)
$guidHex = '0x{0:X16}' -f $guidValue
$metaKeys = 'APP_VERSION_MAJOR', 'APP_VERSION_MINOR', 'APP_VERSION_PATCH', 'APP_VERSION', 'APP_GUID1', 'APP_TITLE', 'APP_CATEGORIES', 'APP_COLORS'
$appText = ReadText $appH

if (-not (Test-Path $metaH)) {
    # legacy template: the pack-header defines sit in app.h -> move them into a dev-layout app_metadata.h
    Step "Legacy template: moving the APP_* defines from app.h into app_metadata.h"
    $ma, $mi, $pa = 1, 0, 0
    $m = [regex]::Match($appText, '(?m)^\s*#\s*define\s+APP_VERSION\s+OCT_APP_SEMVER\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)')
    if ($m.Success) { $ma, $mi, $pa = [int]$m.Groups[1].Value, [int]$m.Groups[2].Value, [int]$m.Groups[3].Value }
    $cat = [regex]::Match($appText, '(?m)^\s*#\s*define\s+APP_CATEGORIES\s+(.+?)\s*(//.*)?$')
    $col = [regex]::Match($appText, '(?m)^\s*#\s*define\s+APP_COLORS\s+(\S+)')
    $meta = @(
        '#pragma once',
        '// Pack-header fields, a leaf header (octpack-build compiles it alone): include only oct_app_version.h,',
        '// oct_app_categories.h and app_save.h here. See templates/app_ai_template/API.md.',
        '#include "oct_app_version.h"', '#include "oct_app_categories.h"', '',
        "#define APP_VERSION_MAJOR $ma", "#define APP_VERSION_MINOR $mi", "#define APP_VERSION_PATCH $pa",
        '#define APP_VERSION OCT_APP_SEMVER(APP_VERSION_MAJOR, APP_VERSION_MINOR, APP_VERSION_PATCH)', '',
        '// permanent identity of this game (installs and saves are keyed by it): never copy it to another app',
        "#define APP_GUID1 $guidHex", '#define APP_TITLE "x"',
        "#define APP_CATEGORIES $(if ($cat.Success) { $cat.Groups[1].Value } else { '(APP_CATEGORY_GAME)' })",
        "#define APP_COLORS $(if ($col.Success) { $col.Groups[1].Value } else { '0x00000000' })", '',
        '// #include "app_save.h"          // the save area (APP_SAVE_SIZE), see app_save.h',
        '// #define APP_HAS_ON_SAVE         // optional exports: the game header must then define the callback',
        '// #define APP_HAS_ON_SAVE_SYNCED', '// #define APP_HAS_PROC_DRAW', '')
    [IO.File]::WriteAllText($metaH, ($meta -join "`r`n"), (New-Object System.Text.UTF8Encoding($false)))
    foreach ($k in $metaKeys) { $appText = [regex]::Replace($appText, "(?m)^[ \t]*#[ \t]*define[ \t]+$k\b[^\r\n]*(\r?\n)?", '') }
}
if ($appText -notmatch '(?m)^\s*#\s*include\s+"app_metadata\.h"') {
    $appText = ReplaceOnce $appText '(?m)^([ \t]*#[ \t]*pragma[ \t]+once[^\r\n]*\r?\n)' "`$1#include `"app_metadata.h`"`r`n"
    if ($appText -notmatch '(?m)^\s*#\s*include\s+"app_metadata\.h"') { $appText = "#include `"app_metadata.h`"`r`n" + $appText }
}
foreach ($k in $metaKeys) {
    if ([regex]::IsMatch($appText, "(?m)^[ \t]*#[ \t]*define[ \t]+$k\b")) { Fail "src\app.h still defines ${k} - the pack-header defines belong in app_metadata.h only (a second, different value fails the build)" }
}
WriteText $appH $appText

$metaText = ReadText $metaH
$rxGuid = '(?m)^([ \t]*#[ \t]*define[ \t]+APP_GUID1[ \t]+)0x[0-9A-Fa-f]+([uUlL]*)'
if (-not [regex]::IsMatch($metaText, $rxGuid)) { Fail "no '#define APP_GUID1 0x...' in $metaH" }
$metaText = ReplaceOnce $metaText $rxGuid "`${1}$guidHex`${2}"
$rxTitle = '(?m)^([ \t]*#[ \t]*define[ \t]+APP_TITLE[ \t]+)"[^"\r\n]*"'
if ([regex]::IsMatch($metaText, $rxTitle)) { $metaText = ReplaceOnce $metaText $rxTitle "`${1}`"$Title`"" }
else { $metaText = $metaText.TrimEnd() + "`r`n#define APP_TITLE `"$Title`"`r`n" }
if ($metaText -notmatch 'OCT_APP_SEMVER') { Write-Host "    WARNING: APP_VERSION is not OCT_APP_SEMVER(...) in app_metadata.h" -ForegroundColor Yellow }
if ($WithSave) {
    if (-not (Test-Path $saveH)) {
        $saveLines = @('#pragma once', '#include <stdint.h>', '// The saved game, a leaf header: app_metadata.h includes it. Read the header FIRST; fixed-width fields only.',
            '#define SAVE_MAGIC   0x00000000u', '#define SAVE_VERSION 1', '',
            'typedef struct { uint32_t magic; uint16_t version; uint16_t size; } saveHeader_t;',
            'typedef struct { saveHeader_t header; uint32_t best; } saveRecord_t;', '',
            'static_assert(sizeof(saveHeader_t) == 8,  "the record header is eight bytes on the wire");',
            'static_assert(sizeof(saveRecord_t) == 12, "update this when the record changes");', '',
            '#define APP_SAVE_SIZE sizeof(saveRecord_t)', '')
        [IO.File]::WriteAllText($saveH, ($saveLines -join "`r`n"), (New-Object System.Text.UTF8Encoding($false)))
    }
    $letters = (($game.ToUpper() -replace '[^A-Z0-9]', '') + 'XXX').Substring(0, 3) + '1'
    $magic = '0x' + (($letters.ToCharArray() | ForEach-Object { '{0:X2}' -f [int]$_ }) -join '') + 'u'
    $saveText = ReplaceOnce (ReadText $saveH) '(?m)^([ \t]*#[ \t]*define[ \t]+SAVE_MAGIC[ \t]+)0x[0-9A-Fa-f]+u?[^\r\n]*' "`${1}$magic     // `"$letters`" (new_app): four bytes of this game, never 0"
    WriteText $saveH $saveText
    if ($metaText -match '(?m)^[ \t]*//[ \t]*#[ \t]*include[ \t]+"app_save\.h"') {
        $metaText = ReplaceOnce $metaText '(?m)^[ \t]*//[ \t]*(#[ \t]*include[ \t]+"app_save\.h")' '$1'
    } elseif ($metaText -notmatch '(?m)^[ \t]*#[ \t]*include[ \t]+"app_save\.h"') {
        $metaText = $metaText.TrimEnd() + "`r`n#include `"app_save.h`"`r`n"
    }
    Write-Host "    save area on: app_save.h (SAVE_MAGIC $magic '$letters') included by app_metadata.h"
}
WriteText $metaH $metaText
Step "APP_GUID1 = $guidHex, APP_TITLE = `"$Title`""

# never SIM_SINGLE_THREAD: only module 0 would run the app in the simulator (hides lockstep bugs)
Get-ChildItem -LiteralPath $src -File -Filter *.h | ForEach-Object {
    $t = ReadText $_.FullName
    if ($t -match '(?m)^[ \t]*#[ \t]*define[ \t]+SIM_SINGLE_THREAD\b') {
        WriteText $_.FullName ([regex]::Replace($t, '(?m)^([ \t]*)#([ \t]*define[ \t]+SIM_SINGLE_THREAD\b)', '$1// removed by new_app (hides lockstep bugs): #$2'))
        Write-Host "    removed #define SIM_SINGLE_THREAD from $($_.Name)"
    }
}

# --- 5. pack (python packer, beta container + launcher icon map) -----------------------------
$packPy = Join-Path $PSScriptRoot 'pack.py'
if (-not (Test-Path $packPy)) { Fail "scripts\pack.py not found" }
# BMFont glyphs are exported only from <art-dir>\fonts\ (the asset stage copies them into assets_<game>\fonts the
# same way); without them every OCT_label_set draws nothing
$fontFiles = @(Get-ChildItem -LiteralPath (Join-Path $AppDir 'art') -File -Filter 'font_*' | Where-Object { $_.Extension -in '.fnt', '.png' })
if ($fontFiles.Count) {
    $fontsDir = Join-Path $AppDir 'art\fonts'
    New-Item -ItemType Directory -Force -Path $fontsDir | Out-Null
    foreach ($f in $fontFiles) { Copy-Item -LiteralPath $f.FullName -Destination $fontsDir -Force }
}
Step "Packing assets (pack.py beta container)"
$betaArgs = @('--beta-app-dir', $AppDir, '--app-name', $app)
$iconPng = Join-Path $AppDir 'art\icon.png'
if (Test-Path $iconPng) { $betaArgs += @('--icon', $iconPng) }
Push-Location $AppDir
try {
    & python $packPy --export --build-palette --build-ids --art-dir art --exported-dir art\exported `
        --packed-dir art\packed --output-dir art\packed --ids-output "src\${app}_ids.h" --assets assets @betaArgs | Out-Host
    $packCode = $LASTEXITCODE
} finally { Pop-Location }
if ($packCode -ne 0) { Fail "asset packing failed (pack.py exit $packCode)" }
$rawCount = @(Get-ChildItem (Join-Path $AppDir 'art\packed') -Filter *.raw -ErrorAction SilentlyContinue).Count
if ($rawCount -eq 0) { Fail "packing produced no .raw assets" }
$indexBin = Join-Path $AppDir 'index.bin'
if (-not (Test-Path $indexBin)) { Fail "index.bin missing - the simulator and the .oct builders need it" }
$idx = [IO.File]::ReadAllBytes($indexBin)
$hasIco = $false
for ($i = 0; $i -lt [BitConverter]::ToInt32($idx, 0); $i++) {
    $off = 4 + $i * 28
    if ([BitConverter]::ToInt32($idx, $off) -eq 3 -and [Text.Encoding]::ASCII.GetString($idx, $off + 4, 24).Split([char]0)[0] -eq 'ico') { $hasIco = $true; break }
}
if (-not $hasIco) { Fail "no MAP 'ico' in index.bin: the launcher would show an empty slot (art\icon.png missing?)" }
$idsText = ReadText (Join-Path $src "${app}_ids.h")
$glyphs = ([regex]::Matches($idsText, '(?i)\bBMP_font_\d+_\d+')).Count
if ($fontFiles.Count -and $glyphs -eq 0) { Fail "the fonts in art\ did not reach src\${app}_ids.h (no BMP_font_* glyphs): labels would draw nothing" }
Write-Host "    packed $rawCount .raw assets; index.bin with the launcher map 'ico'; $glyphs font glyphs; ids -> src\${app}_ids.h"
Write-Host "    the launcher icon is still the TEMPLATE's: Stage 3 replaces art\icon.png with the game's 160x160 badge"

# --- 6. build the hidden simulator (compiles the app; starts nothing) ---------------------------
$tools = Join-Path $PSScriptRoot '..\tools\sim_headless'
if ($SkipBuild) {
    Write-Host ""; Write-Host "INFRA SCAFFOLDED (build not verified): $AppDir" -ForegroundColor Green; exit 0
}
Step "Building the hidden simulator (tools\sim_headless\build.ps1)"
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $tools 'build.ps1') -AppDir $AppDir -Octavios $Octavios
if ($LASTEXITCODE -ne 0) { Fail "simulator build failed (see above): toolchain, telemetry next to octavios, or the app code" }
if ($VisibleSim) {
    Step "Building the visible simulator for the user (not started)"
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $tools 'build.ps1') -AppDir $AppDir -Octavios $Octavios -Visible
    if ($LASTEXITCODE -ne 0) { Fail "visible simulator build failed" }
}

# --- 7. hidden smoke run --------------------------------------------------------------------------
if ($Smoke) {
    Step "Hidden smoke run ($SmokeSeconds s, PNG of all 24 screens every second, no window, no sound)"
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $tools 'run.ps1') -AppDir $AppDir -Seconds $SmokeSeconds -EveryMs 1000 -FreshSaves
    if ($LASTEXITCODE -ne 0) { Fail "hidden smoke run failed (exit $LASTEXITCODE, see above)" }
    Write-Host "    LOOK at the last frames (Read tool): every face as the template intends, no black screens, no garbage"
}

Write-Host ""
Write-Host "INFRA READY: $AppDir" -ForegroundColor Green
Write-Host "  marker   : $app.target"
Write-Host "  metadata : src\app_metadata.h (APP_GUID1 $guidHex, `"$Title`")"
Write-Host "  source   : src\$app.h  (the orchestrator writes game code here)"
Write-Host "  sim      : $Workspace\.sim_headless\$app\bin\sim_headless.exe (hidden; tools\sim_headless\run.ps1)"
exit 0
