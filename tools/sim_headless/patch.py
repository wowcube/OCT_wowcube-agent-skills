#!/usr/bin/env python3
"""Patch a COPY of the octavios Windows simulator into the hidden simulator (sim_headless.exe).

    python patch.py --octavios <octavios dir> --out <work dir> [--check]

Copies <octavios>/sim/src -> <work>/sim/src and <octavios>/engine -> <work>/engine (the engine includes
../sim/src/sim_hal_windows.h, so it has to sit next to the patched copy), adds hl_src/* and applies the
[HEADLESS] patches below. octavios itself is only read. --check counts the anchors in <octavios>/sim/src and
writes nothing (exit 0 = every anchor matches exactly once).

What the patched simulator does when SIM_headless() is true (always, in sim_headless.exe):
  * the window is created without WS_VISIBLE, with WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, and never shown;
    window input, minimize/maximize/restore and global key-state reads (GetKeyState) are ignored;
  * the main loop runs without ever being activated (stock: it idles until WM_ACTIVATE), paced to ~60 fps;
  * the stock MCP control socket (--mcp-port N) stays on, so an agent can drive the hidden instance;
  * no audio device is opened (waveOut / MCI), sound starts are still logged for MCP `record`;
  * crash, assert, abort, invalid-parameter and WER dialogs are suppressed (exit code 99 + headless_crash.txt);
    file dialogs and message boxes are logged instead of shown;
  * no Bluetooth auto-connect, no settings written back, no global single-instance mutex;
  * the pack is built from the snapshot folder baked in at build time (or env SIM_HEADLESS_APP_DIR), and a
    .oct is written ONLY to env SIM_HEADLESS_OCT_OUT (never next to an app, never deleted);
  * PNG dumps of all 24 screens every SIM_HEADLESS_EVERY_MS, exit after SIM_HEADLESS_SECONDS.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# (file, anchor, replacement). Every anchor must occur exactly once in the stock sources; line endings are
# normalised to the file's own. Checked against octavios dev 609d5ae (2026-10-21).
PATCHES: list[tuple[str, str, str]] = [
    # --- helpers visible to everything after sim3d_debug.h (Debug is declared there)
    ('sim.cpp', '#include "sim3d_debug.h"\n',
     '#include "sim3d_debug.h"\n#include "sim_headless.h"   //[HEADLESS]\n'),

    # --- global key state: a hidden instance must never react to the user's own keyboard or mouse buttons
    ('sim3d_input.h', '\tbool\tKeyDown(uint8_t iVKey)\t\t\t{return (GetKeyState(iVKey) & 0x8000) != 0;};\n',
     '\tbool\tKeyDown(uint8_t iVKey)\t\t\t{return !SIM_headless() && (GetKeyState(iVKey) & 0x8000) != 0;};   //[HEADLESS]\n'),
    ('sim3d_input.h', '\tbool\tKeyDownAsync(uint8_t iVKey)\t    {return (GetAsyncKeyState(iVKey) & 0x8000) != 0;};\n',
     '\tbool\tKeyDownAsync(uint8_t iVKey)\t    {return !SIM_headless() && (GetAsyncKeyState(iVKey) & 0x8000) != 0;};   //[HEADLESS]\n'),
    ('sim3d_input.h', '#include "sim3d_scene.h"\n',
     '#include "sim3d_scene.h"\n#if defined(_WIN32)\n#include "sim_headless.h"   //[HEADLESS]\n#endif\n'),

    # --- window: never shown, never activated, no input; the loop runs anyway; lifetime + capture hooks
    ('sim_wrap_win.h', '#include "Shlwapi.h"\n',
     '#include "Shlwapi.h"\n#include "sim_headless_capture.h"   //[HEADLESS]\n'),
    ('sim_wrap_win.h', '''    POINT p;
    static bool resized = false;
    static bool user_moved = false;
    switch(message)
    {''', '''    POINT p;
    static bool resized = false;
    static bool user_moved = false;
    //[HEADLESS] no input, no min/max/restore (each would show the window)
    if (SIM_headless())
    {
        if (message == WM_SYSCOMMAND || message == WM_KEYDOWN || message == WM_KEYUP || message == WM_LBUTTONDOWN || message == WM_RBUTTONDOWN || message == WM_MOUSEWHEEL) return 0;
    }
    switch(message)
    {'''),
    ('sim_wrap_win.h', '''    (void)(showmode);
    timeBeginPeriod(1);''', '''    (void)(showmode);
    SIM_headless_early_init();   //[HEADLESS] no WER/CRT/abort dialogs
    timeBeginPeriod(1);'''),
    ('sim_wrap_win.h', '    WND = CreateWindowExA(NULL, SET.WinClass,',
     '    WND = CreateWindowExA(SIM_headless() ? (WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE) : 0, SET.WinClass,'),   # style has no WS_VISIBLE
    ('sim_wrap_win.h', '    ShowWindow(WND, SW_NORMAL);\n',
     '    if (!SIM_headless()) ShowWindow(WND, SW_NORMAL);   //[HEADLESS] never shown\n'),
    # dev moved the MCP start between Resize() and the loop: hook in right after it, so the socket is up first
    ('sim_wrap_win.h', '    simMcp::Start(mcp_port);\n',
     '    simMcp::Start(mcp_port);\n    if (SIM_headless()) { SET.Idle = false; HL_init(); }   //[HEADLESS] run without ever being activated\n'),
    ('sim_wrap_win.h', '        if (SET.Idle) { Sleep(1); continue; }\n',
     '        if (SET.Idle) { Sleep(1); continue; }\n        if (SIM_headless() && !HL_frame_due()) { Sleep(1); continue; }   //[HEADLESS] ~60 fps, no vsync when hidden\n'),
    ('sim_wrap_win.h', '\t\tGE->Render();\n',
     '\t\tGE->Render();\n        if (SIM_headless()) HL_tick();   //[HEADLESS] frame dump + timed exit\n'),

    # --- settings: no BT auto-connect, never persist the hidden window's placement
    ('sim.h', '''        //Apply saved config
        CfgToVars();
''', '''        //Apply saved config
        CfgToVars();
        if (SIM_headless()) { BtPreferredAddr.ullLong = 0; BtPreferredName[0] = 0; }   //[HEADLESS] no BT activity
'''),
    ('sim.h', '''        BleDeinit();
        VarsToCfg();''', '''        BleDeinit();
        if (!SIM_headless()) VarsToCfg();   //[HEADLESS]'''),

    # --- pack: the snapshot app dir, and a .oct only to an explicit path (never written or deleted elsewhere)
    ('sim.h', 'if (!SIM_build_pack(APP_DIR))   return false;',
     'if (!SIM_build_pack(SIM_headless() ? SIM_headless_app_dir() : APP_DIR))   return false;   //[HEADLESS]'),
    ('sim.h', '''        if (have_code)
        {
            std::ofstream oct(oct_path''', r'''        if (SIM_headless())
        {
            //[HEADLESS] .oct only to an explicit path (env SIM_HEADLESS_OCT_OUT), never next to the app
            char oct_out[MAX_PATH] = {};
            if (have_code && GetEnvironmentVariableA("SIM_HEADLESS_OCT_OUT", oct_out, MAX_PATH) > 0 && oct_out[0])
            {
                std::ofstream o(oct_out, std::ios::binary);
                if (!o) DIE("Can't save the pack");
                o.write((const char*)OctPack, header->Size);
                Debug->Trace("[HEADLESS] .oct written to %s (%u bytes)\n", oct_out, (unsigned)header->Size);
            }
            else Debug->Trace("[HEADLESS] pack built in memory from %s; no .oct written\n", app_dir);
        }
        else if (have_code)
        {
            std::ofstream oct(oct_path'''),

    # --- audio: silent (the engine still logs every sound start for MCP `record`)
    ('sim.h', '        waveOutSetVolume(0, 0x7FFF7FFF);\n',
     '        if (!SIM_headless()) waveOutSetVolume(0, 0x7FFF7FFF);   //[HEADLESS]\n'),
    ('sim.h', '            mciSendStringA(au, NULL, 0, 0);\n',
     '            if (!SIM_headless()) mciSendStringA(au, NULL, 0, 0);   //[HEADLESS] silent\n'),
    # dev's mixer worker opens waveOut here; failing the open leaves it silent (voices are reserved, never heard)
    ('sim_pcm.h', '''        //Init "hardware"
        if (waveOutOpen(''', '''        //Init "hardware"
        if (SIM_headless()) return 1;   //[HEADLESS] never open an audio device
        if (waveOutOpen('''),

    # --- dialogs: logged, never shown
    ('sim_dialogs.h', '''{
    CoInitializeEx(NULL, COINIT_APARTMENTTHREADED);''', r'''{
    if (SIM_headless()) { Debug->Trace("[HEADLESS] file dialog suppressed\n"); (void)param; return IDNO; }
    CoInitializeEx(NULL, COINIT_APARTMENTTHREADED);'''),
    ('sim_dialogs.h', '''    WCHAR* txt = (WCHAR*)param;
    int r = MessageBox(NULL, txt, L"Confirm",''', r'''    WCHAR* txt = (WCHAR*)param;
    if (SIM_headless()) { Debug->Trace("[HEADLESS] confirm suppressed (answered NO): %S\n", txt); return IDNO; }
    int r = MessageBox(NULL, txt, L"Confirm",'''),
    ('sim_dialogs.h', '''    WCHAR* txt = (WCHAR*)param;
    int r = MessageBox(NULL, txt, L"Info",''', r'''    WCHAR* txt = (WCHAR*)param;
    if (SIM_headless()) { Debug->Trace("[HEADLESS] message box suppressed: %S\n", txt); return IDOK; }
    int r = MessageBox(NULL, txt, L"Info",'''),

    # --- no global single-instance mutex (it would turn the user's own simulator into a "second instance")
    ('sim_hal_windows.h', '''        if (StoredInstanceNumber >= 0) return StoredInstanceNumber;
''', '''        if (StoredInstanceNumber >= 0) return StoredInstanceNumber;
        if (SIM_headless()) { StoredInstanceNumber = 0; return false; }   //[HEADLESS]
'''),
]


# MSVC compatibility of the stock engine, applied to the engine COPY only when the line is present (upstream may
# fix it): octavios dev 609d5ae marks minimp3's hot functions `__attribute__((noinline))` in engine/oct_mp3.h,
# which MSVC rejects (C2065 'noinline'), so even the stock apps\build_sim.cmd cannot build the Windows simulator.
ENGINE_COMPAT: list[tuple[str, str, str]] = [
    ('oct_mp3.h', '#define MINIMP3_OUT_OF_LINE __attribute__((noinline))\n',
     '#if defined(_MSC_VER) && !defined(__clang__)   //[HEADLESS] MSVC has no GNU attributes\n'
     '#define MINIMP3_OUT_OF_LINE __declspec(noinline)\n'
     '#else\n'
     '#define MINIMP3_OUT_OF_LINE __attribute__((noinline))\n'
     '#endif\n'),
]


def apply_compat(engine_dir: str, patches=ENGINE_COMPAT) -> list[str]:
    """Optional fixes: applied when the anchor is there once, skipped when it is gone or the file already has an
    MSVC branch for it (upstream fixed it, or this copy was patched before). Returns notes."""
    notes = []
    for fn, old, new in patches:
        path = os.path.join(engine_dir, fn)
        s = _read(path) if os.path.isfile(path) else ""
        crlf = "\r\n" in s
        o, n = _native(old, crlf), _native(new, crlf)
        hits = s.count(o)
        if hits and "_MSC_VER" in s and "__declspec(noinline)" in s:
            notes.append(f"compat: engine/{fn} already has an MSVC branch (no fix needed)")
            continue
        if hits == 1:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(s.replace(o, n))
            notes.append(f"compat: engine/{fn} patched for MSVC")
        elif hits == 0:
            notes.append(f"compat: engine/{fn} needs no MSVC fix (anchor absent)")
        else:
            raise SystemExit(f"PATCH FAILED: engine/{fn}: compat anchor found {hits}x")
    return notes


def _read(path: str) -> str:
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def _native(text: str, crlf: bool) -> str:
    text = text.replace("\r\n", "\n")
    return text.replace("\n", "\r\n") if crlf else text


def count_anchors(src_dir: str, patches=PATCHES) -> list[tuple[str, str, int]]:
    """(file, anchor head, occurrences) for every patch, against a stock sim/src folder."""
    out = []
    for fn, old, _new in patches:
        path = os.path.join(src_dir, fn)
        s = _read(path) if os.path.isfile(path) else ""
        out.append((fn, old.strip().splitlines()[0][:70], s.count(_native(old, "\r\n" in s))))
    return out


def apply_patches(src_dir: str, patches=PATCHES) -> None:
    for fn, old, new in patches:
        path = os.path.join(src_dir, fn)
        s = _read(path)
        crlf = "\r\n" in s
        o, n = _native(old, crlf), _native(new, crlf)
        hits = s.count(o)
        if hits != 1:
            raise SystemExit(f"PATCH FAILED: {fn}: anchor found {hits}x (expected 1): {old.strip()[:90]!r}\n"
                             f"  The simulator sources changed; update tools/sim_headless/patch.py for this octavios.")
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(s.replace(o, n))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--octavios", required=True, help="octavios checkout (dev 609d5ae or later)")
    ap.add_argument("--out", help="work dir that receives sim/src (patched) and engine (copy)")
    ap.add_argument("--check", action="store_true", help="only count the anchors in <octavios>/sim/src")
    a = ap.parse_args(argv)

    oct_dir = os.path.abspath(a.octavios)
    stock_src = os.path.join(oct_dir, "sim", "src")
    if not os.path.isfile(os.path.join(stock_src, "sim_wrap_win.h")):
        print(f"ERROR: {stock_src} has no sim_wrap_win.h - not an octavios checkout", file=sys.stderr)
        return 2

    if a.check:
        bad = 0
        for fn, head, n in count_anchors(stock_src):
            print(f"{'OK ' if n == 1 else 'BAD'} {fn:20s} x{n}  {head!r}")
            bad += n != 1
        print(f"{len(PATCHES) - bad}/{len(PATCHES)} anchors match")
        for fn, head, n in count_anchors(os.path.join(oct_dir, "engine"), ENGINE_COMPAT):
            print(f"compat engine/{fn}: x{n} ({'will be patched' if n == 1 else 'not needed'})  {head!r}")
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
    for f in os.listdir(os.path.join(HERE, "hl_src")):
        shutil.copy2(os.path.join(HERE, "hl_src", f), os.path.join(src, f))
    apply_patches(src)
    for note in apply_compat(eng):
        print(note)
    print(f"headless patch OK ({len(PATCHES)} patches) -> {src}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
