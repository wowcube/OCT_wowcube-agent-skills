#!/usr/bin/env bash
# Linux mirror of new_app.ps1.
#
# Scaffold a WowCube app folder from the template, pack its assets with the
# pure-Python packer, and verify the SDL3/CMake simulator builds + launches --
# the "infrastructure ready" gate that must pass BEFORE the orchestrator runs
# the first technical prompt.
#
# Procedure (mirrors new_app.ps1):
#   1. Copy templates/app_ai_template -> <workspace>/app_<name>
#   2. Rename the .target marker and the game/ids headers to app_<name>*
#   3. Replace every name-bearing reference (app.h, app_<name>.h)
#   4. Guarantee app.h defines APP_VERSION (template omits it -> sim won't compile)
#   5. Pack art assets (the shared scripts/pack.py --emit-raw); _ids.h -> src/
#   6. Configure + build the simulator via CMake -> app_<name>/build-sim/octavios_sim
#   7. (optional) launch it briefly to confirm it does not crash on start
#
# Exit 0 = infrastructure verified. Non-zero = a step failed (message says which).
#
# Usage:
#   new_app.sh --name <game> [--workspace <root>] [--octavios <path>]
#              [--template <path>] [--run] [--skip-build] [--skip-env-check]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"   # OCT_wowcube-agent-skills/ (scripts/ lives at its root)
TOKEN='app_ai_template'                            # literal name baked into template files

NAME=''; WORKSPACE="$(pwd)"; OCTAVIOS=''; TEMPLATE=''
RUN=0; SKIP_BUILD=0; SKIP_ENV_CHECK=0

fail() { printf 'ERROR: %s\n' "$1" >&2; exit 1; }
step() { printf '==> %s\n' "$1"; }

while [ $# -gt 0 ]; do
    case "$1" in
        --name)           NAME="$2"; shift 2;;
        --workspace)      WORKSPACE="$2"; shift 2;;
        --octavios)       OCTAVIOS="$2"; shift 2;;
        --template)       TEMPLATE="$2"; shift 2;;
        --run)            RUN=1; shift;;
        --skip-build)     SKIP_BUILD=1; shift;;
        --skip-env-check) SKIP_ENV_CHECK=1; shift;;
        *) fail "unknown argument: $1";;
    esac
done
[ -n "$NAME" ] || fail "--name <game> is required"

# --- Resolve names and paths ----------------------------------------------
case "$NAME" in app_*) APP="$NAME";; *) APP="app_$NAME";; esac
[[ "$APP" =~ ^app_[A-Za-z0-9_]+$ ]] || fail "invalid app name '$APP' (expected app_<alphanumeric_or_underscore>)"

[ -n "$TEMPLATE" ] || TEMPLATE="$REPO_ROOT/templates/app_ai_template"
[ -d "$TEMPLATE" ] || fail "template folder not found: $TEMPLATE (pass --template)"
TEMPLATE="$(cd "$TEMPLATE" && pwd)"

[ -d "$WORKSPACE" ] || fail "workspace not found: $WORKSPACE"
WORKSPACE="$(cd "$WORKSPACE" && pwd)"
APP_DIR="$WORKSPACE/$APP"
[ -n "$OCTAVIOS" ] || OCTAVIOS="$WORKSPACE/octavios"
PACK_PY="$REPO_ROOT/scripts/pack.py"   # canonical packer

[ -e "$APP_DIR" ] && fail "$APP_DIR already exists - remove it first or pick another name"

# --- 0. Verify (and install) the toolchain --------------------------------
if [ "$SKIP_ENV_CHECK" -eq 0 ] && [ -f "$SCRIPT_DIR/check_env.sh" ]; then
    step "Checking toolchain (check_env.sh)"
    bash "$SCRIPT_DIR/check_env.sh" || \
        echo "    toolchain check reported missing tools; scaffolding continues." >&2
fi

# --- 1. Clone the template ------------------------------------------------
step "Cloning template -> $APP"
cp -r "$TEMPLATE" "$APP_DIR"
rm -rf "$APP_DIR/bin" "$APP_DIR/out" "$APP_DIR/build-sim" "$APP_DIR/art/packed" "$APP_DIR/art/exported"
find "$APP_DIR" \( -name '*.log' -o -name '*.oct' \) -type f -delete 2>/dev/null || true

# --- 2. Rename name-bearing files -----------------------------------------
step "Renaming marker and headers"
find "$APP_DIR" -depth -name "*${TOKEN}*" -type f | while read -r f; do
    mv "$f" "$(dirname "$f")/$(basename "$f" | sed "s/${TOKEN}/${APP}/g")"
done

# --- 3. Replace name references inside text files -------------------------
step "Patching name references ($TOKEN -> $APP)"
find "$APP_DIR" -type f \( -name '*.h' -o -name '*.txt' \) -print0 | while IFS= read -r -d '' f; do
    grep -q "$TOKEN" "$f" && sed -i "s/${TOKEN}/${APP}/g" "$f"
done

# --- 4. Guarantee APP_VERSION in app.h (template omits it) ----------------
APP_H="$APP_DIR/src/app.h"
[ -f "$APP_H" ] || fail "expected $APP_H after clone"
if ! grep -q 'APP_VERSION' "$APP_H"; then
    step "Adding missing APP_VERSION to src/app.h"
    sed -i '/^[[:space:]]*#include[[:space:]]\+"app_/a #define APP_VERSION 100 //v1.00' "$APP_H"
fi

# --- 5. Pack assets (pure-Python packer; same on Windows and Linux) -------
if [ -f "$PACK_PY" ]; then
    step "Packing assets (pack.py --emit-raw)"
    ( cd "$APP_DIR" && python "$PACK_PY" \
        --export --build-palette --build-ids --emit-raw \
        --art-dir art --exported-dir art/exported \
        --packed-dir art/packed --output-dir art/packed --raw-dir art/packed \
        --ids-output "src/${APP}_ids.h" --assets assets )
    raw_count=$(find "$APP_DIR/art/packed" -maxdepth 1 -name '*.raw' 2>/dev/null | wc -l)
    [ "$raw_count" -gt 0 ] || fail "packing produced no .raw assets in $APP_DIR/art/packed"
    echo "    packed $raw_count .raw assets; ids -> src/${APP}_ids.h"
else
    echo "    (scripts/pack.py not found at $PACK_PY - skipping pack)" >&2
fi

# --- 6. Build the simulator (CMake/SDL3; NOT the ARM build) ---------------
if [ "$SKIP_BUILD" -eq 1 ]; then
    step "--skip-build set - scaffolding done, build skipped"
    echo "INFRA SCAFFOLDED (build not verified): $APP_DIR"
    exit 0
fi
[ -d "$OCTAVIOS" ] || fail "octavios SDK not found: $OCTAVIOS (pass --octavios or --skip-build)"
step "Building simulator (cmake -DAPP_DIR=$APP_DIR)"
cmake -S "$OCTAVIOS" -B "$APP_DIR/build-sim" -DAPP_DIR="$APP_DIR"
cmake --build "$APP_DIR/build-sim"
SIM="$APP_DIR/build-sim/octavios_sim"
[ -x "$SIM" ] || fail "build reported success but $SIM is missing"
echo "    built $SIM"

# --- 7. Optional run smoke test -------------------------------------------
if [ "$RUN" -eq 1 ]; then
    step "Launching simulator (smoke test)"
    "$SIM" &
    sim_pid=$!
    sleep 4
    if ! kill -0 "$sim_pid" 2>/dev/null; then
        wait "$sim_pid" 2>/dev/null && code=0 || code=$?
        fail "simulator exited early (code $code) - likely missing/unpacked assets"
    fi
    echo "    running OK (pid $sim_pid)"
    kill "$sim_pid" 2>/dev/null || true   # leave nothing dangling in CI; user can re-launch
fi

echo ''
echo "INFRA READY: $APP_DIR"
echo "  marker : $APP.target"
echo "  source : src/$APP.h  (orchestrator writes game code here)"
echo "  sim    : build-sim/octavios_sim"
exit 0
