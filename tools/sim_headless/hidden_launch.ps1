# Hidden launch + visibility watchdog, shared by tools\sim_headless\run.ps1 and tools\cube_upload\run_upload.ps1.
# Dot-source it:  . (Join-Path $PSScriptRoot 'hidden_launch.ps1')
#
#   $procId = Start-HiddenProcess -Exe <exe> -WorkDir <dir> [-Arguments '--mcp-port 8177'] [-Env @{K='v'; X=$null}]
#   $r      = Watch-HiddenProcess -ProcessId $procId -TimeoutSec 60 [-LogFile <txt>] [-OnPoll { param($elapsedMs) ... }]
#   $r      = Invoke-Hidden -Exe <exe> -WorkDir <dir> -TimeoutSec 60 [-Arguments ...] [-Env @{...}]
#
# The process is created with SW_HIDE + CREATE_NO_WINDOW. Every 50 ms its top-level windows are enumerated; the
# moment ANY of them is visible the process is killed BY PID (never by name) and the result says 'killed-visible'.
# Env entries are set for the child only (restored in this process right after CreateProcess); $null unsets one.
# Result: @{ Exit = <exit code | 'killed-visible' | 'timeout'>; MaxVisible; MaxWindows; Polls; FirstVisible; ElapsedMs; Pid }

$hiddenLaunchCode = @"
using System; using System.Runtime.InteropServices; using System.Text;
public static class WowcubeHiddenLaunch {
  [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
  public struct STARTUPINFO { public int cb; public string r; public string d; public string t;
    public int x, y, xs, ys, xc, yc, fill; public int flags; public short show; public short r2; public IntPtr r3, i, o, e; }
  [StructLayout(LayoutKind.Sequential)] public struct PI { public IntPtr hp, ht; public int pid, tid; }
  [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
  static extern bool CreateProcess(string app, StringBuilder cmd, IntPtr pa, IntPtr ta, bool inherit, int flags, IntPtr env, string dir, ref STARTUPINFO si, out PI pi);
  [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr h);
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc cb, IntPtr l);
  [DllImport("user32.dll")] static extern int GetWindowThreadProcessId(IntPtr h, out int pid);
  [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetClassName(IntPtr h, StringBuilder s, int n);

  public static int Start(string exe, string args, string dir) {
    STARTUPINFO si = new STARTUPINFO(); si.cb = Marshal.SizeOf(si);
    si.flags = 1;   // STARTF_USESHOWWINDOW
    si.show  = 0;   // SW_HIDE
    PI pi;
    StringBuilder cmd = new StringBuilder("\"" + exe + "\"" + (String.IsNullOrEmpty(args) ? "" : " " + args));
    // CREATE_NO_WINDOW (0x08000000): no console either
    if (!CreateProcess(exe, cmd, IntPtr.Zero, IntPtr.Zero, false, 0x08000000, IntPtr.Zero, dir, ref si, out pi))
      throw new Exception("CreateProcess failed: " + Marshal.GetLastWin32Error());
    CloseHandle(pi.hp); CloseHandle(pi.ht); return pi.pid;
  }

  // Top-level windows owned by pid: total, visible, and a description of the visible ones
  public static string Probe(int pid, out int total, out int visible) {
    int t = 0, v = 0; StringBuilder sb = new StringBuilder();
    EnumWindows(delegate(IntPtr h, IntPtr l) {
      int p; GetWindowThreadProcessId(h, out p);
      if (p == pid) { t++; if (IsWindowVisible(h)) { v++;
        StringBuilder tt = new StringBuilder(256), cc = new StringBuilder(256);
        GetWindowText(h, tt, 256); GetClassName(h, cc, 256); sb.Append("[" + h + " '" + tt + "' " + cc + "]"); } }
      return true; }, IntPtr.Zero);
    total = t; visible = v; return sb.ToString();
  }
}
"@
if (-not ('WowcubeHiddenLaunch' -as [type])) { Add-Type -TypeDefinition $hiddenLaunchCode }

function Start-HiddenProcess {
    param([Parameter(Mandatory)][string]$Exe, [Parameter(Mandatory)][string]$WorkDir,
          [string]$Arguments = '', [hashtable]$Env = @{})
    $Exe = (Resolve-Path -LiteralPath $Exe).Path
    $WorkDir = (Resolve-Path -LiteralPath $WorkDir).Path
    $saved = @{}
    foreach ($k in $Env.Keys) {
        $saved[$k] = [Environment]::GetEnvironmentVariable($k)
        $v = $Env[$k]
        [Environment]::SetEnvironmentVariable($k, $(if ($null -eq $v) { $null } else { [string]$v }))
    }
    try { return [WowcubeHiddenLaunch]::Start($Exe, $Arguments, $WorkDir) }
    finally { foreach ($k in $saved.Keys) { [Environment]::SetEnvironmentVariable($k, $saved[$k]) } }
}

function Watch-HiddenProcess {
    param([Parameter(Mandatory)][int]$ProcessId, [int]$TimeoutSec = 60, [string]$LogFile = '',
          [scriptblock]$OnPoll = $null)
    $p = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    $r = @{ Exit = $null; MaxVisible = 0; MaxWindows = 0; Polls = 0; FirstVisible = $null; ElapsedMs = 0; Pid = $ProcessId }
    if (-not $p) { $r.Exit = 'not-running'; return $r }
    $null = $p.Handle   # keep a handle so ExitCode stays readable
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while (-not $p.HasExited) {
        $t = 0; $v = 0
        $desc = [WowcubeHiddenLaunch]::Probe($ProcessId, [ref]$t, [ref]$v)
        $r.Polls++
        if ($t -gt $r.MaxWindows) {
            $r.MaxWindows = $t
            if ($LogFile) { "t=$($sw.ElapsedMilliseconds)ms windows_owned=$t visible=$v" | Out-File $LogFile -Append -Encoding utf8 }
        }
        if ($v -gt $r.MaxVisible) { $r.MaxVisible = $v }
        if ($v -gt 0) {
            $r.FirstVisible = "t=$($sw.ElapsedMilliseconds)ms $desc"
            if ($LogFile) { "VISIBLE $($r.FirstVisible) -> killed by PID $ProcessId" | Out-File $LogFile -Append -Encoding utf8 }
            Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue   # our own process, by PID only
            $r.Exit = 'killed-visible'
            break
        }
        if ((Get-Date) -gt $deadline) {
            if ($LogFile) { "TIMEOUT after $TimeoutSec s -> killed by PID $ProcessId" | Out-File $LogFile -Append -Encoding utf8 }
            Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
            $r.Exit = 'timeout'
            break
        }
        if ($OnPoll) { & $OnPoll $sw.ElapsedMilliseconds }
        Start-Sleep -Milliseconds 50
    }
    $p.WaitForExit(5000) | Out-Null
    if ($null -eq $r.Exit) { $r.Exit = $(if ($p.HasExited) { $p.ExitCode } else { 'running' }) }
    $r.ElapsedMs = $sw.ElapsedMilliseconds
    return $r
}

function Invoke-Hidden {
    param([Parameter(Mandatory)][string]$Exe, [Parameter(Mandatory)][string]$WorkDir, [int]$TimeoutSec = 60,
          [string]$Arguments = '', [hashtable]$Env = @{}, [string]$LogFile = '')
    $procId = Start-HiddenProcess -Exe $Exe -WorkDir $WorkDir -Arguments $Arguments -Env $Env
    return Watch-HiddenProcess -ProcessId $procId -TimeoutSec $TimeoutSec -LogFile $LogFile
}
