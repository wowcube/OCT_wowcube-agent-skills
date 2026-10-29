#pragma once
//[HEADLESS] lifetime, frame pacing and frame capture of the hidden simulator.
//
//Capture: every SIM_HEADLESS_EVERY_MS the 24 full-res 240x240 RGB565 framebuffers (Rts[sid].Data, filled by
//DISPLAY_StartDMA after the engine composed/upscaled them, the same buffers MCP "screens" reads) are copied
//and written as PNGs by worker threads. 0 = no periodic capture (drive the instance over MCP instead).
//
//Face composition uses the engine's own viewport math (oct_trans.h): for viewport vid = plane*4 + sector,
//framebuf[r*240 + col] maps to plane coords p = R(-A) * (r, col), A = OctServerQuads[vid].Tm.A (-90*sector by
//default). Plane coords are drawn +X right / +Y up, which is how a player sees the face from outside: with that
//convention OCT_SIDE_ADJ gives a consistent net (TOP above FRONT, BOTTOM below, LEFT FRONT RIGHT BACK in a row),
//the same arrangement the sim's own unfolded view (Space key) uses.
//
//Lifetime: after SIM_HEADLESS_SECONDS the hidden window is closed (the simulator has no quit command), with a
//15 s watchdog in case teardown hangs. The whole run therefore always ends by itself.
#include <thread>
#include <atomic>
#include <deque>
#include <condition_variable>
#include <vector>
#include <filesystem>

int hl_png_write(const char* path, int w, int h, const unsigned char* rgb);   //hl_png.cpp (optimized TU)

#define HL_SIDE      240
#define HL_SCRGAP    4      //gap between the 4 screens of a face
#define HL_FACEGAP   12     //gap between faces in the cross
#define HL_FACE      (2 * HL_SIDE + HL_SCRGAP)
#define HL_WORKERS   6
#define HL_QUEUE_CAP 40
#define HL_FRAME_MS  16     //main-loop pacing: ~60 fps, what a visible window gets from vsync

struct hlJob
    {
        int         Index;
        uint32_t    Ms;
        uint16_t    Pix[24][HL_SIDE * HL_SIDE];
        uint8_t     Sid[24];
        int16_t     A[24];
    };

struct hlCapture
    {
        bool                        On = false, Finished = false;
        int                         EveryMs = 0, Seconds = 20, Face = -1;
        char                        Dir[MAX_PATH] = {};
        uint32_t                    StartMs = 0, NextMs = 0, LastFrameMs = 0;
        int                         Index = 0, Dropped = 0;
        std::atomic<int>            Written{0};
        std::deque<hlJob*>          Queue;
        std::mutex                  Mtx;
        std::condition_variable     Cv;
        bool                        Quit = false;
        std::vector<std::thread>    Workers;
    };
static hlCapture HL;

static inline void HL_put(uint8_t* img, int w, int x, int y, uint16_t c)
    {
        uint8_t* p = img + 3 * (y * w + x);
        uint8_t r = (uint8_t)((c >> 11) & 0x1F), g = (uint8_t)((c >> 5) & 0x3F), b = (uint8_t)(c & 0x1F);
        p[0] = (uint8_t)((r << 3) | (r >> 2));  p[1] = (uint8_t)((g << 2) | (g >> 4));  p[2] = (uint8_t)((b << 3) | (b >> 2));
    }

//Draw one face (plane) with its top-left corner at (ox, oy)
static void HL_draw_face(const hlJob* j, int plane, uint8_t* img, int w, int ox, int oy)
    {
        static const int RC[4] = { 1, 0, -1, 0 };
        static const int RS[4] = { 0, 1, 0, -1 };
        for (int q = 0; q < 4; q++)
        {
            int vid = plane * 4 + q;
            int sid = j->Sid[vid];
            int a   = j->A[vid];
            int idx = (a % 90 == 0) ? ((-a / 90) & 3) : q;
            int c = RC[idx], s = RS[idx];
            const uint16_t* fb = (sid < 24) ? j->Pix[sid] : NULL;
            for (int r = 0; r < HL_SIDE; r++)
            for (int col = 0; col < HL_SIDE; col++)
            {
                //Doubled half-pixel centres keep it integer: P = 2p in (-480, 480), odd values only
                int R2 = 2 * r + 1, C2 = 2 * col + 1;
                int px2 = c * R2 - s * C2;
                int py2 = s * R2 + c * C2;
                int ix = (px2 + 480) / 2;               //0..479, x right
                int iy = (480 - py2) / 2;               //0..479, y up
                if (ix >= HL_SIDE) ix += HL_SCRGAP;
                if (iy >= HL_SIDE) iy += HL_SCRGAP;
                HL_put(img, w, ox + ix, oy + iy, fb ? fb[r * HL_SIDE + col] : 0);
            }
        }
    }

static void HL_worker()
    {
        for (;;)
        {
            hlJob* j = NULL;
            {
                std::unique_lock<std::mutex> lk(HL.Mtx);
                HL.Cv.wait(lk, [] { return HL.Quit || !HL.Queue.empty(); });
                if (HL.Queue.empty()) return;
                j = HL.Queue.front();  HL.Queue.pop_front();
            }

            int w, h;
            if (HL.Face >= 0 && HL.Face < 6) w = h = HL_FACE;
            else                             w = 4 * HL_FACE + 3 * HL_FACEGAP, h = 3 * HL_FACE + 2 * HL_FACEGAP;
            std::vector<uint8_t> img((size_t)w * h * 3, 0);
            for (size_t i = 0; i < img.size(); i++) img[i] = 40;   //dark-gray gaps / background

            if (HL.Face >= 0 && HL.Face < 6) HL_draw_face(j, HL.Face, img.data(), w, 0, 0);
            else
            {
                //Cross: col,row per plane (TOP=0 FRONT=1 RIGHT=2 BACK=3 LEFT=4 BOTTOM=5), same as sim's PLANE_OFFSET
                static const int COL[6] = { 1, 1, 2, 3, 0, 1 };
                static const int ROW[6] = { 0, 1, 1, 1, 1, 2 };
                for (int p = 0; p < 6; p++) HL_draw_face(j, p, img.data(), w, COL[p] * (HL_FACE + HL_FACEGAP), ROW[p] * (HL_FACE + HL_FACEGAP));
            }

            char path[MAX_PATH + 64];
            sprintf_s(path, "%s\\frame_%06d_%06u.png", HL.Dir, j->Index, j->Ms);
            if (hl_png_write(path, w, h, img.data())) HL.Written++;
            else Debug->Trace("[HEADLESS] PNG write failed: %s\n", path);
            delete j;
        }
    }

//Main-loop pacing: a window that is never shown gets no vsync, so without this the loop would spin a core.
//The engine's modules run on their own threads; this only paces the host loop (MCP pump, 3D view, capture).
static inline bool HL_frame_due()
    {
        uint32_t now = timeGetTime();
        if (now - HL.LastFrameMs < HL_FRAME_MS) return false;
        HL.LastFrameMs = now;
        return true;
    }

static void HL_init()
    {
        if (!SIM_headless()) return;
        HL.EveryMs = SIM_headless_env_int("SIM_HEADLESS_EVERY_MS", 0);  if (HL.EveryMs < 0) HL.EveryMs = 0;  if (HL.EveryMs > 0 && HL.EveryMs < 10) HL.EveryMs = 10;
        HL.Seconds = SIM_headless_env_int("SIM_HEADLESS_SECONDS", 20);  if (HL.Seconds < 1) HL.Seconds = 1;
        HL.Face    = SIM_headless_env_int("SIM_HEADLESS_FACE", -1);
        if (GetEnvironmentVariableA("SIM_HEADLESS_DIR", HL.Dir, MAX_PATH) == 0 || HL.Dir[0] == 0)
        {
            GetCurrentDirectoryA(MAX_PATH, HL.Dir);
            strcat_s(HL.Dir, "\\frames");
        }
        if (HL.EveryMs > 0)
        {
            std::error_code ec;
            std::filesystem::create_directories(HL.Dir, ec);
            for (int i = 0; i < HL_WORKERS; i++) HL.Workers.emplace_back(HL_worker);
        }
        HL.StartMs = timeGetTime();
        HL.NextMs  = 0;
        HL.On      = true;
        Debug->Trace("[HEADLESS] ON: seconds=%d every_ms=%d face=%d dir=%s app_dir=%s mcp_port=%d\n",
                     HL.Seconds, HL.EveryMs, HL.Face, HL.Dir, SIM_headless_app_dir(), (int)simMcp::Port);
    }

//Called once per paced main-loop iteration, after rendering
static void HL_tick()
    {
        if (!HL.On || HL.Finished) return;
        uint32_t ms = timeGetTime() - HL.StartMs;

        if (ms >= (uint32_t)HL.Seconds * 1000u)
        {
            //Stop: drain writers, then close the (hidden) window -> WM_DESTROY -> APP->Deinit -> WM_QUIT
            HL.Finished = true;
            { std::lock_guard<std::mutex> lk(HL.Mtx); HL.Quit = true; }
            HL.Cv.notify_all();
            for (auto& t : HL.Workers) t.join();
            Debug->Trace("[HEADLESS] done: frames_captured=%d frames_written=%d dropped=%d elapsed_ms=%u\n", HL.Index, HL.Written.load(), HL.Dropped, ms);
            FILE* f = NULL;
            if (fopen_s(&f, "headless_summary.txt", "wb") == 0 && f)
            {
                fprintf(f, "captured=%d\nwritten=%d\ndropped=%d\nelapsed_ms=%u\nevery_ms=%d\nmcp_port=%d\ndir=%s\n",
                        HL.Index, HL.Written.load(), HL.Dropped, ms, HL.EveryMs, (int)simMcp::Port, HL.Dir);
                fclose(f);
            }

            //Watchdog: never linger if teardown hangs
            CreateThread(NULL, 0, [](LPVOID) -> DWORD { Sleep(15000); TerminateProcess(GetCurrentProcess(), 0); return 0; }, NULL, 0, NULL);
            PostMessage(WND, WM_CLOSE, 0, 0);
            return;
        }

        if (HL.EveryMs <= 0) return;
        if (ms < HL.NextMs) return;
        HL.NextMs += (uint32_t)HL.EveryMs;
        if (HL.NextMs <= ms) HL.NextMs = ms - (ms % (uint32_t)HL.EveryMs) + (uint32_t)HL.EveryMs;   //fell behind: skip ahead

        int idx = HL.Index++;
        {
            std::lock_guard<std::mutex> lk(HL.Mtx);
            if (HL.Queue.size() >= HL_QUEUE_CAP) { HL.Dropped++; return; }
        }
        hlJob* j = new hlJob;
        j->Index = idx,  j->Ms = ms;
        for (int i = 0; i < 24; i++)
        {
            memcpy(j->Pix[i], Rts[i].Data, sizeof(j->Pix[i]));
            j->Sid[i] = (uint8_t)OctServerQuads[i].Sid;
            j->A[i]   = OctServerQuads[i].Tm.A;
        }
        { std::lock_guard<std::mutex> lk(HL.Mtx); HL.Queue.push_back(j); }
        HL.Cv.notify_one();
    }
