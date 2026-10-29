#pragma once
//[HEADLESS] tools/sim_headless: switches, env helpers and dialog suppression for the hidden simulator.
//sim_headless.exe is compiled with /DSIM_HEADLESS_FORCE, so it is ALWAYS hidden. Without that define the
//patched sources stay dormant unless env SIM_HEADLESS=1 is set, i.e. they still build a normal simulator.
#include <windows.h>
#include <werapi.h>
#include <crtdbg.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <signal.h>

inline bool SIM_headless()
    {
#ifdef SIM_HEADLESS_FORCE
        return true;
#else
        static int v = -1;
        if (v < 0) { char b[8] = {}; v = (GetEnvironmentVariableA("SIM_HEADLESS", b, sizeof(b)) > 0 && b[0] == '1') ? 1 : 0; }
        return v == 1;
#endif
    }

inline int SIM_headless_env_int(const char* name, int def)
    {
        char b[32] = {};
        if (GetEnvironmentVariableA(name, b, sizeof(b)) == 0 || b[0] == 0) return def;
        return atoi(b);
    }

//The app folder the pack is built from at launch: env SIM_HEADLESS_APP_DIR, else the snapshot folder baked in
//by build.ps1 (never the user's real app folder, so nothing a run does can touch it)
inline const char* SIM_headless_app_dir()
    {
        static char dir[MAX_PATH] = {};
        if (dir[0] == 0)
        {
            if (GetEnvironmentVariableA("SIM_HEADLESS_APP_DIR", dir, MAX_PATH) == 0 || dir[0] == 0)
            {
#ifdef SIM_HEADLESS_APP_DIR_BAKED
                strcpy_s(dir, MAX_PATH, SIM_HEADLESS_APP_DIR_BAKED);
#endif
            }
        }
        return dir;
    }

//Any fatal path ends here: one line in headless_crash.txt (cwd = the exe's folder), exit code 99, no dialog
inline LONG WINAPI SIM_headless_crash_filter(EXCEPTION_POINTERS* ep)
    {
        char msg[160];
        sprintf_s(msg, "[HEADLESS] FATAL 0x%08lX - exiting without a dialog (exit code 99)\n",
                  ep && ep->ExceptionRecord ? ep->ExceptionRecord->ExceptionCode : 0ul);
        OutputDebugStringA(msg);
        FILE* f = NULL;
        if (fopen_s(&f, "headless_crash.txt", "ab") == 0 && f) { fputs(msg, f); fclose(f); }
        TerminateProcess(GetCurrentProcess(), 99);
        return EXCEPTION_EXECUTE_HANDLER;
    }

inline void SIM_headless_abort_handler(int) { SIM_headless_crash_filter(NULL); }
inline void SIM_headless_invalid_param(const wchar_t*, const wchar_t*, const wchar_t*, unsigned int, uintptr_t) { SIM_headless_crash_filter(NULL); }
inline void SIM_headless_purecall() { SIM_headless_crash_filter(NULL); }

//No WER, CRT-assert, abort() or invalid-parameter dialog may ever appear in headless mode
inline void SIM_headless_early_init()
    {
        if (!SIM_headless()) return;
        SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX);
        WerSetFlags(WER_FAULT_REPORTING_NO_UI);
        _set_abort_behavior(0, _WRITE_ABORT_MSG | _CALL_REPORTFAULT);
        _CrtSetReportMode(_CRT_WARN,   _CRTDBG_MODE_DEBUG);
        _CrtSetReportMode(_CRT_ERROR,  _CRTDBG_MODE_DEBUG);
        _CrtSetReportMode(_CRT_ASSERT, _CRTDBG_MODE_DEBUG);
        _set_invalid_parameter_handler(SIM_headless_invalid_param);
        _set_purecall_handler(SIM_headless_purecall);
        signal(SIGABRT, SIM_headless_abort_handler);
        SetUnhandledExceptionFilter(SIM_headless_crash_filter);
    }
