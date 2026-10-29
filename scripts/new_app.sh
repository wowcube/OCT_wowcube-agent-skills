#!/usr/bin/env bash
# Linux mirror of new_app.ps1: scaffold app_<name> from the AI template in the octavios dev layout, pack its
# assets, build the SDL3/CMake simulator, and (--smoke) prove it renders with one HIDDEN, MUTED run.
#
#   0. toolchain report (check_env.sh; installs nothing)
#   1. copy templates/app_ai_template -> <workspace>/app_<name>
#   2. rename the .target marker and the game/ids headers to app_<name>*
#   3. replace the template name in every text file
#   4. dev metadata: src/app_metadata.h with a RANDOM APP_GUID1 and the human title (OCT_APP_SEMVER version);
#      src/app.h includes it first and defines none of its macros; --with-save enables src/app_save.h;
#      SIM_SINGLE_THREAD is never defined
#   5. pack the art with scripts/pack.py (beta container + launcher map "ico"); _ids.h straight into src/
#   6. build the simulator: cmake -S <octavios> -B app_<name>/build-sim -DAPP_DIR=app_<name> (needs telemetry
#      next to octavios)
#   7. --smoke (alias --run): run it under xvfb-run (a virtual display: no window on the user's screen), muted
#      (sound_muted=1 + SDL dummy audio), for --smoke-seconds, then MCP "screens faces" -> PNG, then kill it by
#      its own process group. Without xvfb-run the smoke run is skipped, never shown on the real display.
#
# Usage: new_app.sh --name <game> [--workspace <root>] [--octavios <dir>] [--template <dir>] [--title <text>]
#                   [--with-save] [--smoke|--run] [--smoke-seconds 15] [--skip-build] [--skip-env-check]
# Exit 0 = infrastructure verified. Non-zero = the step named in the message failed.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TOKEN='app_ai_template'

NAME=''; WORKSPACE="$(pwd)"; OCTAVIOS=''; TEMPLATE=''; TITLE=''
WITH_SAVE=0; SMOKE=0; SMOKE_SECONDS=15; SKIP_BUILD=0; SKIP_ENV_CHECK=0
fail() { printf 'ERROR: %s\n' "$1" >&2; exit 1; }
step() { printf '==> %s\n' "$1"; }

while [ $# -gt 0 ]; do
    case "$1" in
        --name)           NAME="$2"; shift 2;;
        --workspace)      WORKSPACE="$2"; shift 2;;
        --octavios)       OCTAVIOS="$2"; shift 2;;
        --template)       TEMPLATE="$2"; shift 2;;
        --title)          TITLE="$2"; shift 2;;
        --with-save)      WITH_SAVE=1; shift;;
        --smoke|--run)    SMOKE=1; shift;;
        --smoke-seconds)  SMOKE_SECONDS="$2"; shift 2;;
        --skip-build)     SKIP_BUILD=1; shift;;
        --skip-env-check) SKIP_ENV_CHECK=1; shift;;
        *) fail "unknown argument: $1";;
    esac
done
[ -n "$NAME" ] || fail "--name <game> is required"
case "$NAME" in app_*) APP="$NAME";; *) APP="app_$NAME";; esac
[[ "$APP" =~ ^app_[A-Za-z0-9_]+$ ]] || fail "invalid app name '$APP' (expected app_<letters, digits, _>)"
[ -n "$TEMPLATE" ] || TEMPLATE="$REPO_ROOT/templates/app_ai_template"
[ -d "$TEMPLATE" ] || fail "template folder not found: $TEMPLATE"
TEMPLATE="$(cd "$TEMPLATE" && pwd)"
[ -d "$WORKSPACE" ] || fail "workspace not found: $WORKSPACE"
WORKSPACE="$(cd "$WORKSPACE" && pwd)"
APP_DIR="$WORKSPACE/$APP"
[ -n "$OCTAVIOS" ] || OCTAVIOS="$WORKSPACE/octavios"
[ -e "$APP_DIR" ] && fail "$APP_DIR already exists - remove it first or pick another name"
PY=python3; command -v python3 >/dev/null 2>&1 || PY=python

# --- 0. toolchain report -----------------------------------------------------------
if [ "$SKIP_ENV_CHECK" -eq 0 ]; then
    step "Toolchain report (check_env.sh)"
    bash "$SCRIPT_DIR/check_env.sh" --octavios "$OCTAVIOS" --workspace "$WORKSPACE" \
        || echo "    toolchain incomplete (see above); scaffolding continues, later steps may fail" >&2
fi

# --- 1. clone ---------------------------------------------------------------------------
step "Cloning template -> $APP"
cp -r "$TEMPLATE" "$APP_DIR"
rm -rf "$APP_DIR/bin" "$APP_DIR/out" "$APP_DIR/build-sim" "$APP_DIR/art/packed" "$APP_DIR/art/exported" "$APP_DIR/index.bin"
find "$APP_DIR" -type f \( -name '*.log' -o -name '*.oct' \) -delete
if [ -f "$APP_DIR/art/octpack.json" ]; then   # AI-art apps are packed by scripts/pack.py, not from PSD sources
    mv "$APP_DIR/art/octpack.json" "$APP_DIR/art/octpack.json.template"
    echo "    art/octpack.json -> octpack.json.template (AI-art apps are packed by scripts/pack.py)"
fi

# --- 2.-4. rename, replace names, dev metadata (python: one implementation, no sed edge cases) ---
step "Renaming, patching names, writing the dev metadata"
"$PY" - "$APP_DIR" "$TOKEN" "$APP" "$TITLE" "$WITH_SAVE" <<'PY'
import os, re, secrets, sys
app_dir, token, app, title, with_save = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5] == "1"
game = app[4:]
title = title or " ".join(w[:1].upper() + w[1:] for w in game.split("_") if w)
if len(title.encode()) > 79 or '"' in title or "\\" in title:
    sys.exit("ERROR: the title must be <= 79 bytes, without quotes or backslashes")

for root, dirs, files in os.walk(app_dir, topdown=False):               # 2. rename
    for n in files:
        if token in n:
            os.rename(os.path.join(root, n), os.path.join(root, n.replace(token, app)))

def rd(p):
    with open(p, encoding="utf-8-sig", newline="") as f: return f.read()
def bom(p):
    with open(p, "rb") as f: return f.read(3) == b"\xef\xbb\xbf"
def wr(p, text, keep_bom=None):
    with open(p, "w", encoding="utf-8-sig" if keep_bom else "utf-8", newline="") as f: f.write(text)

for root, _, files in os.walk(app_dir):                                 # 3. names in text files
    for n in files:
        if os.path.splitext(n)[1] in (".h", ".txt", ".json", ".md"):
            p = os.path.join(root, n); t = rd(p)
            if token in t: wr(p, t.replace(token, app), bom(p))

src = os.path.join(app_dir, "src")                                      # 4. dev metadata
app_h, meta_h, save_h = (os.path.join(src, n) for n in ("app.h", "app_metadata.h", "app_save.h"))
keys = ["APP_VERSION_MAJOR", "APP_VERSION_MINOR", "APP_VERSION_PATCH", "APP_VERSION", "APP_GUID1",
        "APP_TITLE", "APP_CATEGORIES", "APP_COLORS"]
guid = 0
while guid == 0: guid = secrets.randbits(64)
guid_hex = "0x%016X" % guid
app_text = rd(app_h)
if not os.path.isfile(meta_h):   # legacy template: move the pack-header defines out of app.h
    m = re.search(r"(?m)^\s*#\s*define\s+APP_VERSION\s+OCT_APP_SEMVER\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", app_text)
    ma, mi, pa = (m.group(1), m.group(2), m.group(3)) if m else ("1", "0", "0")
    cat = re.search(r"(?m)^\s*#\s*define\s+APP_CATEGORIES\s+(.+?)\s*(//.*)?$", app_text)
    col = re.search(r"(?m)^\s*#\s*define\s+APP_COLORS\s+(\S+)", app_text)
    wr(meta_h, "\n".join([
        "#pragma once",
        "// Pack-header fields, a leaf header (octpack-build compiles it alone): include only oct_app_version.h,",
        "// oct_app_categories.h and app_save.h here. See templates/app_ai_template/API.md.",
        '#include "oct_app_version.h"', '#include "oct_app_categories.h"', "",
        f"#define APP_VERSION_MAJOR {ma}", f"#define APP_VERSION_MINOR {mi}", f"#define APP_VERSION_PATCH {pa}",
        "#define APP_VERSION OCT_APP_SEMVER(APP_VERSION_MAJOR, APP_VERSION_MINOR, APP_VERSION_PATCH)", "",
        "// permanent identity of this game (installs and saves are keyed by it): never copy it to another app",
        f"#define APP_GUID1 {guid_hex}", '#define APP_TITLE "x"',
        f"#define APP_CATEGORIES {cat.group(1) if cat else '(APP_CATEGORY_GAME)'}",
        f"#define APP_COLORS {col.group(1) if col else '0x00000000'}", "",
        '// #include "app_save.h"          // the save area (APP_SAVE_SIZE), see app_save.h',
        "// #define APP_HAS_ON_SAVE         // optional exports: the game header must then define the callback",
        "// #define APP_HAS_ON_SAVE_SYNCED", "// #define APP_HAS_PROC_DRAW", ""]))
    for k in keys:
        app_text = re.sub(rf"(?m)^[ \t]*#[ \t]*define[ \t]+{k}\b[^\r\n]*\r?\n?", "", app_text)
    print("    legacy template: APP_* defines moved from app.h into app_metadata.h")
if not re.search(r'(?m)^\s*#\s*include\s+"app_metadata\.h"', app_text):
    new = re.sub(r"(?m)^([ \t]*#[ \t]*pragma[ \t]+once[^\r\n]*\r?\n)", r'\1#include "app_metadata.h"\n', app_text, count=1)
    app_text = new if new != app_text else '#include "app_metadata.h"\n' + app_text
for k in keys:
    if re.search(rf"(?m)^[ \t]*#[ \t]*define[ \t]+{k}\b", app_text):
        sys.exit(f"ERROR: src/app.h still defines {k}: the pack-header defines belong in app_metadata.h only")
wr(app_h, app_text, bom(app_h))

meta = rd(meta_h)
meta, n = re.subn(r"(?m)^([ \t]*#[ \t]*define[ \t]+APP_GUID1[ \t]+)0x[0-9A-Fa-f]+([uUlL]*)", rf"\g<1>{guid_hex}\g<2>", meta, count=1)
if n != 1: sys.exit(f"ERROR: no '#define APP_GUID1 0x...' in {meta_h}")
meta, n = re.subn(r'(?m)^([ \t]*#[ \t]*define[ \t]+APP_TITLE[ \t]+)"[^"\r\n]*"', lambda m: m.group(1) + '"' + title + '"', meta, count=1)
if n != 1: meta = meta.rstrip() + f'\n#define APP_TITLE "{title}"\n'
if "OCT_APP_SEMVER" not in meta: print("    WARNING: APP_VERSION is not OCT_APP_SEMVER(...) in app_metadata.h")
if with_save:
    if not os.path.isfile(save_h):
        wr(save_h, "\n".join([
            "#pragma once", "#include <stdint.h>",
            "// The saved game, a leaf header: app_metadata.h includes it. Read the header FIRST; fixed-width fields only.",
            "#define SAVE_MAGIC   0x00000000u", "#define SAVE_VERSION 1", "",
            "typedef struct { uint32_t magic; uint16_t version; uint16_t size; } saveHeader_t;",
            "typedef struct { saveHeader_t header; uint32_t best; } saveRecord_t;", "",
            'static_assert(sizeof(saveHeader_t) == 8,  "the record header is eight bytes on the wire");',
            'static_assert(sizeof(saveRecord_t) == 12, "update this when the record changes");', "",
            "#define APP_SAVE_SIZE sizeof(saveRecord_t)", ""]))
    letters = (re.sub(r"[^A-Z0-9]", "", game.upper()) + "XXX")[:3] + "1"
    magic = "0x" + "".join("%02X" % ord(c) for c in letters) + "u"
    st = rd(save_h)
    st = re.sub(r"(?m)^([ \t]*#[ \t]*define[ \t]+SAVE_MAGIC[ \t]+)0x[0-9A-Fa-f]+u?[^\r\n]*",
                lambda m: m.group(1) + magic + f'     // "{letters}" (new_app): four bytes of this game, never 0', st, count=1)
    wr(save_h, st, bom(save_h))
    if re.search(r'(?m)^[ \t]*//[ \t]*#[ \t]*include[ \t]+"app_save\.h"', meta):
        meta = re.sub(r'(?m)^[ \t]*//[ \t]*(#[ \t]*include[ \t]+"app_save\.h")', r"\1", meta, count=1)
    elif not re.search(r'(?m)^[ \t]*#[ \t]*include[ \t]+"app_save\.h"', meta):
        meta = meta.rstrip() + '\n#include "app_save.h"\n'
    print(f"    save area on: app_save.h (SAVE_MAGIC {magic} '{letters}') included by app_metadata.h")
wr(meta_h, meta, bom(meta_h))
print(f'==> APP_GUID1 = {guid_hex}, APP_TITLE = "{title}"')

for n in os.listdir(src):                                               # never SIM_SINGLE_THREAD
    p = os.path.join(src, n)
    if n.endswith(".h"):
        t = rd(p)
        t2 = re.sub(r"(?m)^([ \t]*)#([ \t]*define[ \t]+SIM_SINGLE_THREAD\b)", r"\1// removed by new_app (hides lockstep bugs): #\2", t)
        if t2 != t:
            wr(p, t2, bom(p)); print(f"    removed #define SIM_SINGLE_THREAD from {n}")
PY

# --- 5. pack ----------------------------------------------------------------------------------
# BMFont glyphs are exported only from <art-dir>/fonts/ (the asset stage copies them into assets_<game>/fonts the
# same way); without them every OCT_label_set draws nothing
n_fonts=$(find "$APP_DIR/art" -maxdepth 1 -type f -name 'font_*' \( -name '*.fnt' -o -name '*.png' \) | wc -l)
if [ "$n_fonts" -gt 0 ]; then
    mkdir -p "$APP_DIR/art/fonts"
    find "$APP_DIR/art" -maxdepth 1 -type f -name 'font_*' \( -name '*.fnt' -o -name '*.png' \) -exec cp -f {} "$APP_DIR/art/fonts/" \;
fi
step "Packing assets (pack.py beta container)"
beta_args=(--beta-app-dir "$APP_DIR" --app-name "$APP")
[ -f "$APP_DIR/art/icon.png" ] && beta_args+=(--icon "$APP_DIR/art/icon.png")
( cd "$APP_DIR" && "$PY" "$SCRIPT_DIR/pack.py" --export --build-palette --build-ids \
    --art-dir art --exported-dir art/exported --packed-dir art/packed --output-dir art/packed \
    --ids-output "src/${APP}_ids.h" --assets assets "${beta_args[@]}" ) || fail "asset packing failed"
raw_count=$(find "$APP_DIR/art/packed" -maxdepth 1 -name '*.raw' | wc -l)
[ "$raw_count" -gt 0 ] || fail "packing produced no .raw assets"
[ -f "$APP_DIR/index.bin" ] || fail "index.bin missing - the simulator and the .oct builders need it"
"$PY" - "$APP_DIR/index.bin" <<'PY' || fail "no MAP 'ico' in index.bin: the launcher would show an empty slot (art/icon.png missing?)"
import struct, sys
d = open(sys.argv[1], "rb").read(); n = struct.unpack_from("<i", d, 0)[0]
sys.exit(0 if any(struct.unpack_from("<i", d, 4 + i * 28)[0] == 3 and d[8 + i * 28:32 + i * 28].split(b"\0")[0] == b"ico"
                  for i in range(n)) else 1)
PY
glyphs=$({ grep -oiE '\bBMP_font_[0-9]+_[0-9]+' "$APP_DIR/src/${APP}_ids.h" || true; } | wc -l)
if [ "$n_fonts" -gt 0 ] && [ "$glyphs" -eq 0 ]; then
    fail "the fonts in art/ did not reach src/${APP}_ids.h (no BMP_font_* glyphs): labels would draw nothing"
fi
echo "    packed $raw_count .raw assets; index.bin with the launcher map 'ico'; $glyphs font glyphs; ids -> src/${APP}_ids.h"
echo "    the launcher icon is still the TEMPLATE's: Stage 3 replaces art/icon.png with the game's 160x160 badge"

# --- 6. simulator build (CMake/SDL3; starts nothing) -------------------------------------------
if [ "$SKIP_BUILD" -eq 1 ]; then echo ''; echo "INFRA SCAFFOLDED (build not verified): $APP_DIR"; exit 0; fi
[ -f "$OCTAVIOS/CMakeLists.txt" ] || fail "octavios SDK not found: $OCTAVIOS (pass --octavios or --skip-build)"
[ -f "$(dirname "$OCTAVIOS")/telemetry/octavios_simulator/telemetry_sim.cpp" ] \
    || fail "wowcube/telemetry must be checked out next to octavios (the dev simulator links it)"
step "Building the simulator (cmake -DAPP_DIR=$APP_DIR)"
cmake -S "$OCTAVIOS" -B "$APP_DIR/build-sim" -DAPP_DIR="$APP_DIR" || fail "simulator configure failed"
cmake --build "$APP_DIR/build-sim" -j 4 --target octavios_sim || fail "simulator build failed"
SIM="$APP_DIR/build-sim/octavios_sim"
[ -x "$SIM" ] || fail "build reported success but $SIM is missing"
echo "    built $SIM (for the USER to play; agents run it only hidden, below)"

# --- 7. hidden, muted smoke run --------------------------------------------------------------------
if [ "$SMOKE" -eq 1 ]; then
    if ! command -v xvfb-run >/dev/null 2>&1 || ! command -v setsid >/dev/null 2>&1; then
        echo "    smoke run SKIPPED: xvfb-run (and setsid) are needed so no window opens on the user's display" >&2
        echo "    (apt install xvfb / pacman -S xorg-server-xvfb). Infra gate: build verified, render NOT verified." >&2
    else
        WORK="$WORKSPACE/.sim_headless/${APP}_linux"; rm -rf "$WORK"; mkdir -p "$WORK"
        printf 'sound_muted=1\n' > "$WORK/sim_user_linux.cfg"
        PORT=8177; SHOT="$WORK/smoke_faces.png"
        step "Hidden smoke run (${SMOKE_SECONDS}s under xvfb-run, muted, MCP port $PORT)"
        # Force X11 so the window lands on xvfb's virtual display: on a Wayland session SDL/GLFW/GTK would otherwise
        # pick WAYLAND_DISPLAY and open a real window on the user's screen despite xvfb-run's DISPLAY.
        ( cd "$WORK" && exec env -u WAYLAND_DISPLAY XDG_SESSION_TYPE=x11 SDL_VIDEODRIVER=x11 GDK_BACKEND=x11 \
              GLFW_PLATFORM=x11 QT_QPA_PLATFORM=xcb SDL_AUDIO_DRIVER=dummy SDL_AUDIODRIVER=dummy \
              setsid xvfb-run -a -s "-screen 0 1280x1024x24" \
              "$SIM" --mcp-port "$PORT" > "$WORK/stdout.txt" 2>&1 ) &
        PGID=$!
        cleanup() { kill -TERM -- "-$PGID" 2>/dev/null || true; sleep 1; kill -KILL -- "-$PGID" 2>/dev/null || true; }
        trap cleanup EXIT
        sleep "$SMOKE_SECONDS"
        port=$({ grep -ao 'control socket listening on 127.0.0.1:[0-9]*' "$WORK/log_linux.txt" 2>/dev/null || true; } | tail -n1 | sed 's/.*://')
        [ -n "$port" ] || fail "the simulator never opened its MCP socket (crashed at start?); see $WORK/log_linux.txt and $WORK/stdout.txt"
        reply=$("$PY" - "$port" "$SHOT" <<'PY'
import socket, sys
s = socket.create_connection(("127.0.0.1", int(sys.argv[1])), timeout=30)
s.sendall(("screens faces " + sys.argv[2] + "\n").encode()); buf = b""
while not buf.endswith(b"\n"):
    chunk = s.recv(4096)
    if not chunk: break
    buf += chunk
print(buf.decode().strip())
PY
)
        cleanup; trap - EXIT
        case "$reply" in ok*) echo "    $reply"; echo "    LOOK at $SHOT (Read tool): all six faces as intended, no black screens, no garbage";;
                         *) fail "MCP screens failed: $reply";; esac
    fi
fi

echo ''
echo "INFRA READY: $APP_DIR"
echo "  marker   : $APP.target"
echo "  metadata : src/app_metadata.h"
echo "  source   : src/$APP.h  (the orchestrator writes game code here)"
echo "  sim      : build-sim/octavios_sim (visible: for the user only)"
exit 0
