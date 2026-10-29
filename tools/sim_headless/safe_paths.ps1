# Path guards shared by tools\sim_headless\build.ps1 / run.ps1 and tools\cube_upload\build.ps1 / run_upload.ps1.
# Dot-source it:  . (Join-Path $PSScriptRoot 'safe_paths.ps1')
#
#   $why = Test-UnsafeWorkDir -WorkDir <dir> -Protect @($AppDir, $Octavios, $Telemetry)
#   if ($why) { Fail $why }
#       The build scripts delete and rewrite folders under -WorkDir (the app snapshot's src, sim\src, engine, bin). A
#       -WorkDir that IS, CONTAINS or LIES INSIDE the app, the SDK or the telemetry checkout would wipe or overwrite
#       real sources, and a drive root or the user's home folder is never a work dir. Answers $null when it is safe.
#
#   $p = Get-AsciiPath -Path <existing path> [-What 'work dir']
#       MSVC response files, cmd.exe batch files and the simulator's getenv()/fopen() use the ANSI/OEM code pages, so
#       a path with characters outside ASCII (e.g. a Cyrillic user name under C:\Users) breaks the compile or the run.
#       Returns the path unchanged when it is ASCII, else its 8.3 short form when the volume keeps short names and
#       that form is ASCII; otherwise it throws a clear error naming the path.

function ConvertTo-NormalDir([string]$p) {
    if (-not $p) { return $null }
    # relative to the PowerShell location (not the process cwd), like Resolve-Path; the dir need not exist
    $full = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($p)
    return ([IO.Path]::GetFullPath($full)).TrimEnd('\', '/')
}

function Test-PathInside([string]$child, [string]$parent) {
    # true when $child equals $parent or lies below it (case-insensitive, Windows paths)
    if (-not $child -or -not $parent) { return $false }
    if ($child.Equals($parent, [StringComparison]::OrdinalIgnoreCase)) { return $true }
    return $child.StartsWith($parent + '\', [StringComparison]::OrdinalIgnoreCase)
}

function Test-UnsafeWorkDir {
    param([Parameter(Mandatory)][string]$WorkDir, [string[]]$Protect = @())
    $w = ConvertTo-NormalDir $WorkDir
    $root = ([IO.Path]::GetPathRoot($w)).TrimEnd('\', '/')
    if (-not $root -or $w.Length -le $root.Length) { return "-WorkDir $WorkDir is a drive root: pick a dedicated folder" }
    foreach ($h in @($env:USERPROFILE, $env:HOME, [Environment]::GetFolderPath('UserProfile'))) {
        $hn = ConvertTo-NormalDir $h
        if ($hn -and (Test-PathInside $hn $w)) { return "-WorkDir $WorkDir is the home folder or contains it: pick a dedicated folder" }
    }
    foreach ($p in $Protect) {
        $pn = ConvertTo-NormalDir $p
        if (-not $pn) { continue }
        if (Test-PathInside $pn $w) { return "-WorkDir $WorkDir is or contains $pn, which the build would overwrite: pick a dedicated folder" }
        if (Test-PathInside $w $pn) { return "-WorkDir $WorkDir lies inside $pn, which must stay untouched: pick a folder outside it" }
    }
    return $null
}

if (-not ('WowcubeShortPath' -as [type])) {
    Add-Type -TypeDefinition @"
using System; using System.Runtime.InteropServices; using System.Text;
public static class WowcubeShortPath {
  [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
  static extern uint GetShortPathName(string longPath, StringBuilder shortPath, uint size);
  public static string Get(string p) {
    StringBuilder sb = new StringBuilder(1024);
    uint n = GetShortPathName(p, sb, (uint)sb.Capacity);
    return (n == 0 || n >= sb.Capacity) ? null : sb.ToString();
  }
}
"@
}

function Get-AsciiPath {
    param([Parameter(Mandatory)][string]$Path, [string]$What = 'path')
    if ($Path -notmatch '[^\x20-\x7E]') { return $Path }
    $short = $null
    if (Test-Path -LiteralPath $Path) { $short = [WowcubeShortPath]::Get((Resolve-Path -LiteralPath $Path).Path) }
    if ($short -and $short -notmatch '[^\x20-\x7E]') { return $short }
    throw ("the $What '$Path' contains non-ASCII characters (e.g. Cyrillic) and has no ASCII 8.3 short name " +
           "(short names are off on this volume, or it does not exist yet). MSVC response files, cmd.exe and the " +
           "simulator cannot carry such a path. Move the workspace to a path with Latin letters only (e.g. " +
           "C:\wowcube\) or pass -WorkDir / -Octavios / -Telemetry / -Oct there.")
}
