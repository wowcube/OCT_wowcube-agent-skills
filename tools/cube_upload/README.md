# cube_upload: install a .oct on the user's cube from Windows, without a window

octavios dev has no Windows command-line uploader (`tools/spptest` builds on Linux only); the stock Windows
simulator uploads only through Shift+C / Shift+S dialogs and a modal result box. This tool builds a patched
**copy** of the simulator (octavios is only read) that does one thing: connect to one paired cube over
Bluetooth SPP, upload one `.oct` as `BLOB_TYPE_SOFTWARE`, log the result, exit.

- Window created invisible and never shown; `run_upload.ps1` polls every 50 ms and kills it **by PID** if a
  window ever becomes visible. File dialogs and message boxes are logged, never shown; crash dialogs suppressed.
- No sound (the simulator's boot chime stays silent), no MCP socket, no settings written, no app compiled in
  (the simulator's "blank sim" mode), no `.oct` written anywhere.
- Files larger than one 64 KB chunk are sent with `BLOB_FLAG_LONG_CHUNK_TIMEOUT` (120 s CHUNK/FLUSH budget
  instead of 10 s), as the Linux simulator does. The old local uploader sent flags 0, the likely cause of its
  "stalls at chunk 0, rerun" symptom.
- The device address and name are parameters; nothing about a particular cube is stored in the repo.

Agents upload only when the user asked for it, and only to the cube the user named (AGENT_SAFETY.md).

## Requirements

Windows, octavios dev 609d5ae or later, `wowcube/telemetry` next to octavios, MSVC, Python 3, and the cube
**paired in Windows Bluetooth settings** (Settings > Bluetooth & devices). The upload goes over Bluetooth only:
the dock is USB power and a serial port, and the upload does not go through it (a docked cube still uploads over
Bluetooth). Only module 0 of a cube is
discoverable over SPP. To read its address, e.g.
`Get-PnpDevice -Class Bluetooth | Where-Object FriendlyName -like 'Wow*' | Select-Object FriendlyName, InstanceId`
(the 12 hex digits after `DEV_` in the instance id; check against the device's properties page).

## Usage

```powershell
# build once (about a minute; starts nothing). run_upload.ps1 also builds on first use.
powershell -NoProfile -ExecutionPolicy Bypass -File <repo>\tools\cube_upload\build.ps1 -Octavios C:\ws\octavios

# upload
powershell -NoProfile -ExecutionPolicy Bypass -File <repo>\tools\cube_upload\run_upload.ps1 `
    -Octavios C:\ws\octavios -Mac <AA:BB:CC:DD:EE:FF> -Oct C:\ws\dist\app_<game>.oct [-Name <cube BT name>]
```

Optional: `-ConnectSec 60` (give up without an SPP link), `-TimeoutSec 600`, `-WorkDir` (default
`<octavios>\..\.cube_upload`), `-Rebuild`. Upload the device build from `scripts\build_device.*`
(`<workspace>\dist\app_<game>.oct`), never a `.oct` a simulator wrote into an app folder.

Output: the `[UPLOAD]` lines of `<WorkDir>\bin\log_1.txt` (mode, connect, size + flags, progress every 2 s,
RESULT) and `<WorkDir>\bin\upload_result.txt`, e.g. `status=SUCCESS fin=1 bytes=551784 elapsed_ms=14602`.

| Exit | Meaning | What to do |
|---|---|---|
| 0 | SUCCESS | tell the user; reboot note below |
| 10 | FAILED: the cube answered with an error (CRC, flash write, validation) | read the RESULT line; rebuild the `.oct` |
| 11 | ABORTED: the transfer stopped part-way, e.g. stalled at chunk 0 | rerun once; if it fails again, ask the user to reboot the cube, then rerun |
| 12 | NO_CONNECTION within `-ConnectSec` | cube paired? switched on, awake, in range? MAC of module 0? |
| 2 / 3 / 13 | window became visible (killed) / timeout (killed) / no result | report with the log path |

## Timing and the reboot note

- About 40-46 KB/s over SPP: a ~550 KB `.oct` takes about 12-15 s with this uploader (measured 2026-10-28 and
  2026-10-29), plus 3 s of settle time before and after.
- The previous uploader sometimes stalled at chunk 0 and gave up after 120 s; simply rerunning fixed it. With
  the long-chunk flag this should be rare; the advice stands: rerun once.
- **Reboot the cube after an upload** when the new version does not show up in the launcher or the next upload
  cannot connect: per octavios `BLUETOOTH.md`, the next SPP connection after an upload often fails until the
  cube reboots (the cube writes flash with interrupts off and loses the disconnect). The uploader keeps the
  link open 3 s after the result to soften this. The owner rebooted after every upload of Shotgun Princess.
- Then the on-device checklist (see `skills/wowcube-boilerplate/SKILL.md`, Stage 5).

## Alternatives

- Linux: `<octavios>/tools/spptest --mac AA:BB:CC:DD:EE:FF --software <app>.oct --long-timeout` (BlueZ; WSL has
  no Bluetooth).
- Stock Windows simulator, done by the user: Shift+C picks the cube (keys 1-9), Shift+S picks the file; hold
  Right-Ctrl while confirming for the long chunk timeout. Agents never press keys for this.
- `wowcube_flash` (MTK DevTool) Install tab or its Python API (not verified here).

## Maintenance

`python patch.py --octavios <dir> --check`: every anchor must match once (24/24 on octavios dev 609d5ae or later).
The patch shares its window/dialog/audio pieces with `tools/sim_headless/patch.py`, picked by `_SHARED_PICKS`:
each pick must select exactly one headless patch, or the import fails. Verified: builds with MSVC against octavios
dev (609d5ae and later); run successfully against a real cube on 2026-10-28 and 2026-10-29 (`BLOB_TYPE_SOFTWARE`
upload over Bluetooth SPP, ~12-15 s for a 550 KB `.oct`, `status=SUCCESS`).

Paths: the build and run scripts pass non-ASCII paths (e.g. Cyrillic) to MSVC, cmd.exe and the uploader in their
8.3 short form, or stop with a clear error; `-WorkDir` may not be a drive root, the home folder, or is / contain
/ lie inside octavios or telemetry.
