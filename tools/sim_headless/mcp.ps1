<#
.SYNOPSIS
    Send wire commands to a running simulator's MCP control socket (127.0.0.1 only) and print the replies.

.DESCRIPTION
    One command per argument, one reply line per command, e.g.
      mcp.ps1 -Port 8177 ping info "screens faces C:\shots\p3_faces.png" "twist 3" "record 40 50 C:\shots\rec_"
    Commands (octavios dev, sim/src/sim_mcp.h): ping | info | log | screens [faces] <png> | record <n 1..100>
    <ms 20..2000> <prefix> | twist <0..23> | tap <x> <y> | shake | cube <yaw> <pitch> <roll> | turn ... |
    camera <yaw> <pitch> | orbit ... | face <0..5> | reset | unfold <0|1> | idle | shot <max_side> <png>.
    In a hidden instance prefer `screens` / `record` (they read the 24 framebuffers) over `shot` (window
    back buffer). Exit code 1 when any reply starts with "err" or a connection fails.
#>
# Only named parameters bind by name: every bare word is a command (without this, "ping" bound to -TimeoutSec).
[CmdletBinding(PositionalBinding = $false)]
param(
    [int] $Port = 8177,
    [int] $TimeoutSec = 60,
    [Parameter(ValueFromRemainingArguments = $true)] [string[]] $Command
)
if (-not $Command -or $Command.Count -eq 0) { Write-Host "usage: mcp.ps1 [-Port 8177] <command> [<command> ...]"; exit 1 }
$failed = $false
try {
    $client = New-Object System.Net.Sockets.TcpClient
    $client.ReceiveTimeout = $TimeoutSec * 1000
    $client.SendTimeout = 5000
    $client.Connect('127.0.0.1', $Port)
    $stream = $client.GetStream()
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    $writer = New-Object System.IO.StreamWriter($stream, $utf8); $writer.NewLine = "`n"; $writer.AutoFlush = $true
    $reader = New-Object System.IO.StreamReader($stream, $utf8)
    foreach ($c in $Command) {
        $writer.WriteLine($c)
        $reply = $reader.ReadLine()
        "> $c"
        "< $reply"
        if ($null -eq $reply -or $reply.StartsWith('err')) { $failed = $true }
    }
    $client.Close()
} catch {
    "ERROR: $($_.Exception.Message) (is a simulator listening on 127.0.0.1:$($Port)? run.ps1 prints the port)"
    exit 1
}
if ($failed) { exit 1 } else { exit 0 }
