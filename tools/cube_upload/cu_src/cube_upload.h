#pragma once
//[UPLOAD] tools/cube_upload: helpers of the windowless SOFTWARE uploader (one .oct to one paired cube over SPP).
//Configured only through the environment (run_upload.ps1 sets it):
//  CUBE_UPLOAD_MAC          cube address, e.g. 0xAABBCCDDEEFF (module 0 is the cube's only SPP endpoint)
//  CUBE_UPLOAD_PATH         the .oct to upload (BLOB_TYPE_SOFTWARE)
//  CUBE_UPLOAD_NAME         label for the log (optional)
//  CUBE_UPLOAD_CONNECT_SEC  give up when no SPP link comes up within this many seconds (default 60)
//The outcome lands in upload_result.txt next to the exe (status=SUCCESS|FAILED|ABORTED|NO_CONNECTION|NO_ARGS).
#include <windows.h>
#include <mmsystem.h>
#include <stdio.h>
#include <stdlib.h>

inline DWORD CU_env_ms(const char* name, DWORD def_sec)
    {
        char b[32] = {};
        if (GetEnvironmentVariableA(name, b, sizeof(b)) == 0 || b[0] == 0) return def_sec * 1000u;
        int v = atoi(b);
        return (DWORD)(v > 0 ? v : (int)def_sec) * 1000u;
    }

//One line, overwritten per run, read by run_upload.ps1
inline void CU_write_result(const char* status, int fin, unsigned long bytes, unsigned long elapsed_ms)
    {
        FILE* f = NULL;
        if (fopen_s(&f, "upload_result.txt", "wb") == 0 && f)
        {
            fprintf(f, "status=%s fin=%d bytes=%lu elapsed_ms=%lu\n", status, fin, bytes, elapsed_ms);
            fclose(f);
        }
    }

//Main-loop pacing (~60 fps): the window is never shown, so there is no vsync to pace it
inline bool CU_frame_due()
    {
        static DWORD last = 0;
        DWORD now = timeGetTime();
        if (now - last < 16) return false;
        last = now;
        return true;
    }
