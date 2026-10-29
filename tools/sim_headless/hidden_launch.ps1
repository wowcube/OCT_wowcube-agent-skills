# Hidden launch + visibility watchdog, shared by tools\sim_headless\run.ps1 and tools\cube_upload\run_upload.ps1.
# Dot-source it:  . (Join-Path $PSScriptRoot 'hidden_launch.ps1')
#
#   $procId = Start-HiddenProcess -Exe <exe> -WorkDir <dir> [-Arguments '--mcp-port 8177'] [-Env @{K='v'; X=$null}]
#   $r      = Watch-HiddenProcess -ProcessId $procId -TimeoutSec 60 [-LogFile <txt>] [-OnPoll { param($elapsedMs) ... }]
#   $r      = Invoke-Hidden -Exe <exe> -WorkDir <dir> -TimeoutSec 60 [-Arguments ...] [-Env @{...}]
#
# The process is created with SW_HIDE + CREATE_NO_WINDOW. Every 50 ms its top-level windows are enumerated; the
# moment ANY of them is visible the process is killed (never by name) and the result says 'killed-visible'.
# PID reuse: CreateProcess's process handle stays open until Watch-HiddenProcess holds its own handle on the same
# process (Windows never reuses a PID while a handle is open), Watch checks the image path, and kills go through that
# held handle ($p.Kill()), so a recycled PID can never be hit. Stop-OwnedProcess stops a run later (an MCP playtest)
# only when the PID still names the same exe started at the recorded time.
# Env entries are set for the child only (restored in this process right after CreateProcess); $null unsets one.
# Result: @{ Exit = <exit code | 'killed-visible' | 'timeout' | 'not-running' | 'not-ours'>; MaxVisible; MaxWindows; Polls; FirstVisible; ElapsedMs; Pid }

$hiddenLaunchCode = @"
using System; using System.Runtime.InteropServices; using System.Text;
public static class WowcubeHiddenLaunch2 {
  [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
  public struct STARTUPINFO { public int cb; public string r; public string d; public string t;
    public int x, y, xs, ys, xc, yc, fill; public int flags; public short show; public short r2; public IntPtr r3, i, o, e; }
  [StructLayout(LayoutKind.Sequential)] public struct PI { public IntPtr hp, ht; public int pid, tid; }
  [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
  static extern bool CreateProcess(string app, StringBuilder cmd, IntPtr pa, IntPtr ta, bool inherit, int flags, IntPtr env, string dir, ref STARTUPINFO si, out PI pi);
  [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr h);
  static System.Collections.Generic.Dictionary<int, IntPtr> held = new System.Collections.Generic.Dictionary<int, IntPtr>();
  [DllImport("kernel32.dll", CharSet = CharSet.Unicode)] static extern uint GetLongPathName(string s, StringBuilder l, uint n);
  // the long, full form of a path (8.3 short names expanded) for comparisons
  public static string Long(string p) {
    StringBuilder sb = new StringBuilder(1024); uint n = GetLongPathName(System.IO.Path.GetFullPath(p), sb, 1024);
    return (n == 0 || n >= 1024) ? System.IO.Path.GetFullPath(p) : sb.ToString();
  }
  // closes the creation handle kept by Start (call once the caller holds its own handle on the process)
  [DllImport("kernel32.dll")] static extern bool GetExitCodeProcess(IntPtr h, out int code);
  // exit code read through the creation handle (null while running or when no handle is held): .NET's ExitCode can
  // come back empty for a process that ended before Get-Process attached to it
  public static int? HeldExitCode(int pid) {
    IntPtr h; int c;
    if (!held.TryGetValue(pid, out h) || !GetExitCodeProcess(h, out c) || c == 259) return null;   // 259 = STILL_ACTIVE
    return c;
  }
  public static void Release(int pid) { IntPtr h; if (held.TryGetValue(pid, out h)) { CloseHandle(h); held.Remove(pid); } }
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
    CloseHandle(pi.ht); held[pi.pid] = pi.hp; return pi.pid;   // hp pins the PID until Release
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
if (-not ('WowcubeHiddenLaunch2' -as [type])) { Add-Type -TypeDefinition $hiddenLaunchCode }

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
    try { return [WowcubeHiddenLaunch2]::Start($Exe, $Arguments, $WorkDir) }
    finally { foreach ($k in $saved.Keys) { [Environment]::SetEnvironmentVariable($k, $saved[$k]) } }
}

# Stops a process this tool started, by PID, only when the PID still names the same exe started at the recorded
# time (a finished run's PID may since belong to another program). Returns 'stopped', 'gone' or 'mismatch: ...'.
function Stop-OwnedProcess {
    param([Parameter(Mandatory)][int]$ProcessId, [Parameter(Mandatory)][string]$Exe, [string]$StartTime = '')
    $p = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if (-not $p) { return 'gone' }
    $path = $null; try { $path = $p.Path } catch { }
    if (-not $path -or -not ([WowcubeHiddenLaunch2]::Long($path)).Equals([WowcubeHiddenLaunch2]::Long($Exe), [StringComparison]::OrdinalIgnoreCase)) {
        return "mismatch: PID $ProcessId is '$path', not $Exe - left running"
    }
    if ($StartTime) {
        $want = [DateTime]::Parse($StartTime, $null, [Globalization.DateTimeStyles]::RoundtripKind).ToUniversalTime()
        if ([Math]::Abs(($p.StartTime.ToUniversalTime() - $want).TotalSeconds) -gt 2) {
            return "mismatch: PID $ProcessId started $($p.StartTime.ToString('o')), not $StartTime - left running"
        }
    }
    $p.Kill(); $p.WaitForExit(5000) | Out-Null
    return 'stopped'
}

function Watch-HiddenProcess {
    param([Parameter(Mandatory)][int]$ProcessId, [int]$TimeoutSec = 60, [string]$LogFile = '',
          [scriptblock]$OnPoll = $null, [string]$Exe = '')
    $p = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    $r = @{ Exit = $null; MaxVisible = 0; MaxWindows = 0; Polls = 0; FirstVisible = $null; ElapsedMs = 0; Pid = $ProcessId }
    if (-not $p) {
        # it already ended: the creation handle still holds its exit code (a crash at start must not look clean)
        $code = [WowcubeHiddenLaunch2]::HeldExitCode($ProcessId)
        [WowcubeHiddenLaunch2]::Release($ProcessId)
        $r.Exit = $(if ($null -ne $code) { [int]$code } else { 'not-running' }); return $r
    }
    $null = $p.Handle   # our own handle as well; the creation handle is released at the end (it pins the PID)
    if ($Exe) {
        $path = $null; try { $path = $p.Path } catch { }
        if ($path -and -not ([WowcubeHiddenLaunch2]::Long($path)).Equals([WowcubeHiddenLaunch2]::Long($Exe), [StringComparison]::OrdinalIgnoreCase)) {
            [WowcubeHiddenLaunch2]::Release($ProcessId)
            $r.Exit = 'not-ours'; return $r   # never touch a process we did not start
        }
    }
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while (-not $p.HasExited) {
        $t = 0; $v = 0
        $desc = [WowcubeHiddenLaunch2]::Probe($ProcessId, [ref]$t, [ref]$v)
        $r.Polls++
        if ($t -gt $r.MaxWindows) {
            $r.MaxWindows = $t
            if ($LogFile) { "t=$($sw.ElapsedMilliseconds)ms windows_owned=$t visible=$v" | Out-File $LogFile -Append -Encoding utf8 }
        }
        if ($v -gt $r.MaxVisible) { $r.MaxVisible = $v }
        if ($v -gt 0) {
            $r.FirstVisible = "t=$($sw.ElapsedMilliseconds)ms $desc"
            if ($LogFile) { "VISIBLE $($r.FirstVisible) -> killed by PID $ProcessId" | Out-File $LogFile -Append -Encoding utf8 }
            try { $p.Kill() } catch { }   # our own process, through the handle we hold (no PID reuse)
            $r.Exit = 'killed-visible'
            break
        }
        if ((Get-Date) -gt $deadline) {
            if ($LogFile) { "TIMEOUT after $TimeoutSec s -> killed by PID $ProcessId" | Out-File $LogFile -Append -Encoding utf8 }
            try { $p.Kill() } catch { }
            $r.Exit = 'timeout'
            break
        }
        if ($OnPoll) { & $OnPoll $sw.ElapsedMilliseconds }
        Start-Sleep -Milliseconds 50
    }
    $p.WaitForExit(5000) | Out-Null
    if ($null -eq $r.Exit) {
        $code = $null
        if ($p.HasExited) { $code = $p.ExitCode; if ($null -eq $code) { $code = [WowcubeHiddenLaunch2]::HeldExitCode($ProcessId) } }
        $r.Exit = $(if ($null -ne $code) { [int]$code } else { 'running' })
    }
    [WowcubeHiddenLaunch2]::Release($ProcessId)
    $r.ElapsedMs = $sw.ElapsedMilliseconds
    return $r
}

function Invoke-Hidden {
    param([Parameter(Mandatory)][string]$Exe, [Parameter(Mandatory)][string]$WorkDir, [int]$TimeoutSec = 60,
          [string]$Arguments = '', [hashtable]$Env = @{}, [string]$LogFile = '')
    $procId = Start-HiddenProcess -Exe $Exe -WorkDir $WorkDir -Arguments $Arguments -Env $Env
    return Watch-HiddenProcess -ProcessId $procId -TimeoutSec $TimeoutSec -LogFile $LogFile -Exe $Exe
}
