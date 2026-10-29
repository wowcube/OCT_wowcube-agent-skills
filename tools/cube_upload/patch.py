#!/usr/bin/env python3
"""Patch a COPY of the octavios Windows simulator into the windowless cube uploader (cube_upload.exe).

    python patch.py --octavios <octavios dir> --out <work dir> [--check]

Copies <octavios>/sim/src and engine into <work> (octavios is only read), adds cu_src/* and
../sim_headless/hl_src/sim_headless.h, and applies the [UPLOAD] patches below. The exe is built WITHOUT an
app (the simulator's supported "blank sim" mode): no app folder, no pack, no .oct is ever written.

What cube_upload.exe does (always; it is compiled with /DSIM_HEADLESS_FORCE):
  * window created without WS_VISIBLE, WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, never shown; no window input;
    global key-state reads return "not pressed", so the user's keyboard cannot trigger anything;
  * crash / assert / WER dialogs suppressed; file dialogs and message boxes logged, never shown;
  * no audio device (the blank sim's boot chime stays silent); no MCP socket; no settings written back;
  * reads CUBE_UPLOAD_MAC / CUBE_UPLOAD_PATH / CUBE_UPLOAD_NAME / CUBE_UPLOAD_CONNECT_SEC, connects SPP to that
    address (the cube must be paired in Windows), waits 3 s, uploads the file as BLOB_TYPE_SOFTWARE with
    BLOB_FLAG_LONG_CHUNK_TIMEOUT for files > 64 KB (what the Linux simulator does; the stock Windows dialog only
    sets it while Right-Ctrl is held), logs progress, writes upload_result.txt, keeps the link 3 s, exits.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HL_DIR = os.path.join(HERE, "..", "sim_headless")

_spec = importlib.util.spec_from_file_location("hl_patch", os.path.join(HL_DIR, "patch.py"))
hl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hl)

# generic pieces shared with the headless simulator (they key on SIM_headless(), true under SIM_HEADLESS_FORCE).
# Each one is picked from hl.PATCHES by (file, a needle in its anchor), and every needle must select EXACTLY ONE
# headless patch: a needle that stops matching, or starts matching two, fails at import instead of silently dropping
# or duplicating a safety patch. Whole-file entries (needle None) take all of that file's patches, at least one.
_SHARED_PICKS: list[tuple[str, str | None]] = [
    ("sim3d_input.h", None),
    ("sim_hal_windows.h", None),
    ("sim_wrap_win.h", "switch(message)"),
    ("sim_wrap_win.h", "(void)(showmode);"),
    ("sim_wrap_win.h", "CreateWindowExA"),
    ("sim_wrap_win.h", "ShowWindow(WND, SW_NORMAL)"),
    ("sim_pcm.h", None),
    ("sim.h", "waveOutSetVolume"),
    ("sim.h", "mciSendStringA"),
    ("sim.h", "VarsToCfg();"),
]


def pick_shared(patches, picks=_SHARED_PICKS) -> list[tuple[str, str, str]]:
    """The headless patches the uploader reuses, in hl.PATCHES order; raises when a pick is not exactly one patch."""
    chosen: list[int] = []
    for fn, needle in picks:
        idx = [i for i, p in enumerate(patches) if p[0] == fn and (needle is None or needle in p[1])]
        if not idx or (needle is not None and len(idx) != 1):
            raise SystemExit(f"PATCH TABLE: {fn} / {needle!r} selects {len(idx)} headless patches (expected "
                             f"{'1' if needle is not None else '>= 1'}): update _SHARED_PICKS in tools/cube_upload/patch.py")
        dup = set(idx) & set(chosen)
        if dup:
            raise SystemExit(f"PATCH TABLE: {fn} / {needle!r} selects a headless patch another pick already took")
        chosen += idx
    return [patches[i] for i in sorted(chosen)]


_SHARED = pick_shared(hl.PATCHES)

PATCHES: list[tuple[str, str, str]] = [
    ('sim.cpp', '#include "sim3d_debug.h"\n',
     '#include "sim3d_debug.h"\n#include "sim_headless.h"   //[UPLOAD] dialog suppression helpers\n'
     '#include "cube_upload.h"    //[UPLOAD]\n'),
] + _SHARED + [
    # --- globals
    ('sim_vars.h', 'simBlob_t SimBlob;\n', r'''simBlob_t SimBlob;

//[UPLOAD] windowless software-upload mode (tools/cube_upload)
volatile bool    AutoUpload          = false;
volatile bool    AutoUploadTriggered = false;
volatile int     AutoUploadResult    = -1000;   //-1000 pending; TXN_RES_* when done; -2 aborted; -3 no connection
DWORD            AutoUploadConnMs    = 0;
DWORD            AutoUploadDoneMs    = 0;
DWORD            AutoUploadLaunchMs  = 0;
DWORD            AutoUploadConnectMs = 60000;
'''),

    # --- no control socket in the uploader; run the loop without activation; pace it
    ('sim_wrap_win.h', '    simMcp::Start(mcp_port);\n',
     '    (void)mcp_port;      //[UPLOAD] no MCP control socket in the uploader\n'
     '    SET.Idle = false;    //[UPLOAD] run without ever being activated\n'),
    ('sim_wrap_win.h', '        if (SET.Idle) { Sleep(1); continue; }\n',
     '        if (SET.Idle) { Sleep(1); continue; }\n'
     '        if (!CU_frame_due()) { Sleep(1); continue; }   //[UPLOAD] ~60 fps, no vsync when hidden\n'),

    # --- configuration from the environment, right after the saved config was applied
    ('sim.h', '''        //Apply saved config
        CfgToVars();
''', r'''        //Apply saved config
        CfgToVars();

        //[UPLOAD] env-driven upload of one SOFTWARE blob (.oct) to one cube; nothing else is ever done
        {
            char mac_s[64] = {}, path_s[MAX_PATH] = {}, name_s[128] = {};
            if (GetEnvironmentVariableA("CUBE_UPLOAD_MAC", mac_s, sizeof(mac_s)) == 0 || GetEnvironmentVariableA("CUBE_UPLOAD_PATH", path_s, sizeof(path_s)) == 0 || _strtoui64(mac_s, NULL, 0) == 0)
            {
                Debug->Trace("[UPLOAD] CUBE_UPLOAD_MAC / CUBE_UPLOAD_PATH not set - nothing to do, exiting\n");
                CU_write_result("NO_ARGS", -4, 0, 0);
                TerminateProcess(GetCurrentProcess(), 4);
            }
            GetEnvironmentVariableA("CUBE_UPLOAD_NAME", name_s, sizeof(name_s));
            AutoUpload = true;
            AutoUploadLaunchMs  = GetTickCount();
            AutoUploadConnectMs = CU_env_ms("CUBE_UPLOAD_CONNECT_SEC", 60);
            BtPreferredAddr.ullLong = _strtoui64(mac_s, NULL, 0);
            MultiByteToWideChar(CP_UTF8, 0, name_s[0] ? name_s : mac_s, -1, BtPreferredName, BT_NAME_SIZE - 1);
            MultiByteToWideChar(CP_UTF8, 0, path_s, -1, SoftwarePath, MAX_PATH - 1);
            OctManagerRole = true;
            SimBlob.Type  = BLOB_TYPE_SOFTWARE;
            SimBlob.Flags = 0;
            Debug->Trace("[UPLOAD] mode ON: target=%S addr=%012llX path=%S type=SOFTWARE connect_timeout=%lus\n", BtPreferredName, BtPreferredAddr.ullLong, SoftwarePath, AutoUploadConnectMs / 1000);
        }
'''),

    # --- trigger once connected; keyboard uploads disabled; result / exit handling
    ('sim.h', '''        //User triggered uploading
        if (IsSppConnected() || BleIsConnected())
        {''', r'''        //[UPLOAD] programmatic trigger + completion/exit handling
        if (AutoUpload)
        {
            DWORD now_ms = GetTickCount();
            if (!AutoUploadTriggered)
            {
                if (IsSppConnected())
                {
                    if (AutoUploadConnMs == 0) { AutoUploadConnMs = now_ms; Debug->Trace("[UPLOAD] SPP connected to %S, settling 3 s before the upload\n", BtPreferredName); }
                    if (now_ms - AutoUploadConnMs > 3000 && SimBlob.State == simUploadState::NONE)
                    {
                        SimBlob.Type  = BLOB_TYPE_SOFTWARE;
                        SimBlob.Flags = 0;   //the long-chunk flag is added in PREPARE, once the size is known
                        AutoUploadTriggered = true;
                        Debug->Trace("[UPLOAD] INITIATE upload of %S\n", SoftwarePath);
                        SimBlob.State = simUploadState::INITIATE;
                    }
                }
                else
                {
                    AutoUploadConnMs = 0;
                    if (AutoUploadResult == -1000 && now_ms - AutoUploadLaunchMs > AutoUploadConnectMs)
                    {
                        AutoUploadResult = -3;
                        Debug->Trace("[UPLOAD] RESULT: NO_CONNECTION (no SPP link to %S within %lu s: paired? switched on? in range?)\n", BtPreferredName, AutoUploadConnectMs / 1000);
                        CU_write_result("NO_CONNECTION", -3, 0, 0);
                    }
                }
            }
            else if (AutoUploadResult == -1000 && SimBlob.State == simUploadState::NONE)
            {
                AutoUploadResult = -2;
                Debug->Trace("[UPLOAD] RESULT: ABORTED (upload state reset without completion; spp=%d)\n", (int)IsSppConnected());
                CU_write_result("ABORTED", -2, 0, 0);
            }

            //keep the link up 3 s after the result: closing right away loses the disconnect while the cube writes flash
            if (AutoUploadResult != -1000 && AutoUploadDoneMs == 0) AutoUploadDoneMs = now_ms;
            if (AutoUploadDoneMs != 0 && AutoUploadDoneMs != 0xFFFFFFFF && now_ms - AutoUploadDoneMs > 3000)
            {
                Debug->Trace("[UPLOAD] exiting, result=%d\n", AutoUploadResult);
                AutoUploadDoneMs = 0xFFFFFFFF;   //post once
                PostMessage(WND, WM_CLOSE, 0, 0);
            }
        }

        //User triggered uploading
        if ((IsSppConnected() || BleIsConnected()) && !AutoUpload)
        {'''),

    # --- dialogs: logged, never shown
    ('sim_dialogs.h', '''{
    CoInitializeEx(NULL, COINIT_APARTMENTTHREADED);''', r'''{
    if (SIM_headless()) { Debug->Trace("[UPLOAD] file dialog suppressed\n"); (void)param; return IDNO; }
    CoInitializeEx(NULL, COINIT_APARTMENTTHREADED);'''),
    ('sim_dialogs.h', '''    WCHAR* txt = (WCHAR*)param;
    int r = MessageBox(NULL, txt, L"Confirm",''', r'''    WCHAR* txt = (WCHAR*)param;
    if (SIM_headless()) { Debug->Trace("[UPLOAD] confirm suppressed (answered NO): %S\n", txt); return IDNO; }
    int r = MessageBox(NULL, txt, L"Confirm",'''),
    ('sim_dialogs.h', '''    WCHAR* txt = (WCHAR*)param;
    int r = MessageBox(NULL, txt, L"Info",''', r'''    WCHAR* txt = (WCHAR*)param;
    if (SIM_headless()) { Debug->Trace("[UPLOAD] message box suppressed: %S\n", txt); return IDOK; }
    int r = MessageBox(NULL, txt, L"Info",'''),

    # --- long chunk timeout for anything bigger than one 64 KB chunk
    ('sim_thread_manager.h', '''            //Some trivial name-based checks
            octTxnRes_t res = OCT_NET_BLOB_validate(SimBlob.Type, SimBlob.BlobSize, name);''', r'''            //[UPLOAD] a 64 KB chunk over real Bluetooth routinely needs more than the default 10 s CHUNK budget (fan-out
            //over the UART mesh + every module's CRC ack): ask for the long budget the way the Linux simulator does
            //(sim_thread_manager_linux.h) and Right-Ctrl does in the stock Windows dialog. The old uploader sent
            //flags 0, the likely cause of its "stalls at chunk 0, rerun" symptom.
            if (AutoUpload && SimBlob.Type == BLOB_TYPE_SOFTWARE && SimBlob.BlobSize > OCT_CHUNK_CAP) SimBlob.Flags |= BLOB_FLAG_LONG_CHUNK_TIMEOUT;
            if (AutoUpload) Debug->Trace("[UPLOAD] %lu bytes, flags=0x%lx (long chunk timeout %s)\n", (unsigned long)SimBlob.BlobSize, (unsigned long)SimBlob.Flags, (SimBlob.Flags & BLOB_FLAG_LONG_CHUNK_TIMEOUT) ? "on" : "off");

            //Some trivial name-based checks
            octTxnRes_t res = OCT_NET_BLOB_validate(SimBlob.Type, SimBlob.BlobSize, name);'''),

    # --- result: logged + upload_result.txt instead of a modal message box
    ('sim_thread_manager.h', '''                Dialogs.MessageBoxDialogShow(msg);
                SimBlob.State = simUploadState::END;''', r'''                if (AutoUpload)
                {
                    unsigned long up_ms = (unsigned long)(OCT_time() - SimBlob.UploadStartMs);
                    Debug->Trace("[UPLOAD] RESULT: %s fin=%d stepPrev=%d bytes=%lu flags=0x%lx elapsed_ms=%lu msg=%S\n", OctBlobTxn.FinResult == TXN_RES_SUCCESS ? "SUCCESS" : "FAILED", (int)OctBlobTxn.FinResult, (int)OctBlobTxn.StepPrev, (unsigned long)SimBlob.BlobSize, (unsigned long)SimBlob.Flags, up_ms, msg);
                    AutoUploadResult = (int)OctBlobTxn.FinResult;
                    CU_write_result(OctBlobTxn.FinResult == TXN_RES_SUCCESS ? "SUCCESS" : "FAILED", (int)OctBlobTxn.FinResult, (unsigned long)SimBlob.BlobSize, up_ms);
                    SimBlob.State = simUploadState::NONE;
                    return;
                }
                Dialogs.MessageBoxDialogShow(msg);
                SimBlob.State = simUploadState::END;'''),

    # --- progress every 2 s
    ('sim_thread_manager.h', '''        if (SimBlob.State == simUploadState::SENDING)
        {''', r'''        if (SimBlob.State == simUploadState::SENDING)
        {
            static uint32_t last_prog_ms = 0;
            if (AutoUpload && OCT_time() - last_prog_ms > 2000)
            {
                last_prog_ms = OCT_time();
                Debug->Trace("[UPLOAD] progress: txnState=%d chunk=%d (~%lu/%lu bytes) elapsed_ms=%lu\n", (int)OctBlobTxn.State, OctBlobTxn.CurChunkIdx, (unsigned long)((OctBlobTxn.CurChunkIdx + 1) * OCT_CHUNK_CAP), (unsigned long)SimBlob.BlobSize, (unsigned long)(OCT_time() - SimBlob.UploadStartMs));
            }'''),
]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--octavios", required=True)
    ap.add_argument("--out")
    ap.add_argument("--check", action="store_true", help="only count the anchors in <octavios>/sim/src")
    a = ap.parse_args(argv)

    oct_dir = os.path.abspath(a.octavios)
    stock_src = os.path.join(oct_dir, "sim", "src")
    if not os.path.isfile(os.path.join(stock_src, "sim_wrap_win.h")):
        print(f"ERROR: {stock_src} has no sim_wrap_win.h - not an octavios checkout", file=sys.stderr)
        return 2
    if a.check:
        bad = 0
        for fn, head, n in hl.count_anchors(stock_src, PATCHES):
            print(f"{'OK ' if n == 1 else 'BAD'} {fn:22s} x{n}  {head!r}")
            bad += n != 1
        print(f"{len(PATCHES) - bad}/{len(PATCHES)} anchors match")
        return 0 if bad == 0 else 1
    if not a.out:
        ap.error("--out is required unless --check")

    work = os.path.abspath(a.out)
    src, eng = os.path.join(work, "sim", "src"), os.path.join(work, "engine")
    for d in (os.path.join(work, "sim"), eng):
        if os.path.isdir(d):
            shutil.rmtree(d)
    shutil.copytree(stock_src, src)
    shutil.copytree(os.path.join(oct_dir, "engine"), eng)
    shutil.copy2(os.path.join(HL_DIR, "hl_src", "sim_headless.h"), os.path.join(src, "sim_headless.h"))
    for f in os.listdir(os.path.join(HERE, "cu_src")):
        shutil.copy2(os.path.join(HERE, "cu_src", f), os.path.join(src, f))
    hl.apply_patches(src, PATCHES)
    for note in hl.apply_compat(eng):
        print(note)
    print(f"upload patch OK ({len(PATCHES)} patches) -> {src}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
