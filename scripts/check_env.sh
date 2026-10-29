#!/usr/bin/env bash
# Linux mirror of check_env.ps1: check the WowCube toolchain against the pipeline's minimum SDK
# (octavios dev 609d5ae, 2026-10-21). Reports only (distros differ): prints the install line for what is missing.
#
#   SDK        octavios dev (engine/oct_app_version.h, octpacker/, tools/mcp/, sim/src/sim_mcp.h, tools/new_app.sh;
#              git checkouts must contain 609d5ae) + wowcube/telemetry checked out NEXT TO octavios
#   .oct build uv, Python 3.12 (uv-managed), clang++ or g++, cmake, ninja, arm-none-eabi-g++
#   simulator  sdl3, bluez, libsystemd (+ xvfb-run for hidden smoke runs: no window on the user's display)
#   assets     python3 + Pillow/numpy/pytoshop/psd-tools, ffmpeg
#   info       Codex CLI logged in with ChatGPT
#
# Usage: check_env.sh [--octavios <dir>] [--workspace <dir>] [--report-only]
# Exit 0 = everything required is present; 2 = something required is missing.
set -uo pipefail

OCTAVIOS="${OCTAVIOS_DIR:-}"; WORKSPACE="$(pwd)"
while [ $# -gt 0 ]; do
    case "$1" in
        --octavios)    OCTAVIOS="$2"; shift 2;;
        --workspace)   WORKSPACE="$2"; shift 2;;
        --report-only) shift;;
        *) echo "unknown argument: $1" >&2; exit 1;;
    esac
done
[ -n "$OCTAVIOS" ] || OCTAVIOS="$WORKSPACE/octavios"

have() { command -v "$1" >/dev/null 2>&1; }
ok()   { echo "  [ok]      $1"; }
info() { echo "  [info]    $1"; }
missing=()
miss() { echo "  [MISSING] $1  -> $2"; missing+=("$1"); }

echo "==> WowCube toolchain (minimum SDK: octavios dev 609d5ae, 2026-10-21)"

# --- SDK -------------------------------------------------------------------
if [ ! -d "$OCTAVIOS/engine" ]; then
    miss "octavios SDK at $OCTAVIOS" "git clone https://github.com/wowcube/octavios.git (branch dev), or --octavios <dir>"
else
    OCTAVIOS="$(cd "$OCTAVIOS" && pwd)"
    old=()
    for f in engine/oct_app_version.h octpacker/pyproject.toml tools/mcp/octavios_mcp.py sim/src/sim_mcp.h tools/new_app.sh; do
        [ -e "$OCTAVIOS/$f" ] || old+=("$f")
    done
    # the 609d5ae import set: also answers for an export without git history
    if [ -f "$OCTAVIOS/engine/oct_app_module.h" ] && ! grep -q cube_pose_visual "$OCTAVIOS/engine/oct_app_module.h"; then
        old+=("engine/oct_app_module.h without cube_pose_visual (the 609d5ae import set)")
    fi
    commit=''
    if [ -d "$OCTAVIOS/.git" ] && have git; then
        commit=$(git -C "$OCTAVIOS" log -1 --format='%h %cs' 2>/dev/null)
        if ! git -C "$OCTAVIOS" cat-file -e '609d5ae^{commit}' 2>/dev/null; then old+=("commit 609d5ae not in this clone")
        elif ! git -C "$OCTAVIOS" merge-base --is-ancestor 609d5ae HEAD 2>/dev/null; then old+=("HEAD does not contain 609d5ae"); fi
    fi
    if [ "${#old[@]}" -gt 0 ]; then
        miss "octavios at $OCTAVIOS is older than dev 609d5ae${commit:+ (HEAD $commit)}: lacks ${old[*]}" \
             "git -C $OCTAVIOS pull --ff-only origin dev; then rm -rf app_*/out app_*/build-sim"
    else
        ok "octavios dev at $OCTAVIOS${commit:+ (HEAD $commit)}"
    fi
    TEL="$(dirname "$OCTAVIOS")/telemetry"
    if [ -f "$TEL/octavios_simulator/telemetry_sim.cpp" ]; then ok "telemetry next to octavios ($TEL)"
    else miss "wowcube/telemetry next to octavios ($TEL)" "git clone https://github.com/wowcube/telemetry.git $TEL"; fi
fi

# --- .oct build ------------------------------------------------------------------
if have uv; then
    ok "uv ($(uv --version))"
    if py=$(uv python find 3.12 2>/dev/null); then ok "Python 3.12 for octpacker ($py)"
    else info "no uv-managed Python 3.12 yet: the first octpack run downloads it (uv python install 3.12)"; fi
else miss "uv (runs octavios/octpacker)" "your package manager (pacman -S uv; brew install uv) or: pipx install uv"; fi
if [ -n "${CXX:-}" ] || have clang++ || have g++; then ok "host C++ compiler for octpack probes (${CXX:-$(command -v clang++ || command -v g++)})"
else miss "clang++ or g++" "install clang or g++"; fi
for t in cmake ninja arm-none-eabi-g++; do
    if have "$t"; then ok "$t (ARM build)"; else miss "$t" "see the install line below"; fi
done

# --- simulator -----------------------------------------------------------------
if pkg-config --exists sdl3 2>/dev/null; then ok "sdl3 (simulator)"; else miss "sdl3 (simulator)" "see the install line below"; fi
pkg-config --exists bluez 2>/dev/null      && ok "bluez (SPP upload, spptest)"   || info "bluez not found (upload with spptest needs it)"
pkg-config --exists libsystemd 2>/dev/null && ok "libsystemd (BLE)"              || info "libsystemd not found (BLE only)"
if have xvfb-run; then ok "xvfb-run (hidden simulator smoke runs)"
else info "xvfb-run not found: hidden smoke runs are skipped (agents never open a window on the user's display); apt install xvfb / pacman -S xorg-server-xvfb"; fi

# --- assets ----------------------------------------------------------------------
if have python3 && ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    miss "python 3.11+ (python3 is older; the pinned numpy needs 3.11)" "install Python 3.11+ (distro package or uv python install 3.11)"
elif have python3; then
    absent=$(python3 -c "import importlib.util as u; print(' '.join(m for m in ['PIL','numpy','pytoshop','psd_tools'] if u.find_spec(m) is None))")
    if [ -n "$absent" ]; then miss "python packages: $absent" "python3 -m pip install -r <skills repo>/scripts/requirements.txt"
    else ok "python3 + Pillow/numpy/pytoshop/psd-tools"; fi
else miss "python3 (3.11+)" "install Python 3.11+"; fi
if have ffmpeg; then ok "ffmpeg (sound encoding)"; else miss "ffmpeg (sound encoding)" "see the install line below"; fi

# --- informational -----------------------------------------------------------------
if have codex; then
    status=$(codex login status 2>&1 | head -n 1)
    case "$status" in *ChatGPT*) info "Codex CLI logged in ($status) - default image provider";;
                      *) info "Codex CLI not logged in with ChatGPT ($status): the user runs 'codex login'";; esac
else info "Codex CLI not found: image generation falls back to the paid-API providers"; fi

echo ''
if [ "${#missing[@]}" -eq 0 ]; then echo "Toolchain OK."; exit 0; fi
echo "Missing ${#missing[@]} item(s)."
if have pacman; then
    echo "Install (Arch):  sudo pacman -S cmake gcc clang sdl3 bluez bluez-libs systemd-libs arm-none-eabi-gcc arm-none-eabi-newlib ninja uv ffmpeg xorg-server-xvfb"
elif have apt; then
    echo "Install (Debian/Ubuntu):  sudo apt install cmake g++ clang libsdl3-dev libbluetooth-dev libsystemd-dev gcc-arm-none-eabi ninja-build ffmpeg xvfb pipx  (then uv: pipx install uv)"
fi
# Never pipe a downloaded script into a shell (curl ... | sh): install from the distro's package manager or pipx,
# after the user approved the download (skills/cube_orchestrator/references/AGENT_SAFETY.md).
echo "Python packages:  python3 -m pip install -r <skills repo>/scripts/requirements.txt"
exit 2
