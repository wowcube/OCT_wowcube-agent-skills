#!/usr/bin/env bash
# Linux mirror of build_device.ps1.
#
# Produce the cube-loadable .oct for an existing app_<game> folder. The .oct is
# assembled by the SIMULATOR at launch, which packs: art .raw assets + sounds +
# (if present) the ARM device code from out/<app>.bin. So a *loadable* .oct is:
#
#   1. ARM device build  -> app_<game>/out/app_<game>.bin
#      (cmake -G Ninja -S <octavios>/apps -B out ; cmake --build out)
#   2. Launch the sim once -> it writes app_<game>/app_<game>.oct
#      (assets + sounds + ARM code)
#   3. Verify the ARM code is actually embedded (asset-only packs are DEAD on cube)
#
# Requires the device toolchain (arm-none-eabi-gcc, cmake, ninja) -- run
# check_env.sh first. Without the ARM .bin the sim still writes a .oct, but it
# contains assets only and will NOT run on the cube; this script treats a
# missing .bin as a failure.
#
# Usage: build_device.sh --app-dir <workspace>/app_<game> [--octavios <path>]
set -uo pipefail

APP_DIR=''; OCTAVIOS=''
fail() { printf 'ERROR: %s\n' "$1" >&2; exit 1; }
step() { printf '==> %s\n' "$1"; }

while [ $# -gt 0 ]; do
    case "$1" in
        --app-dir)  APP_DIR="$2"; shift 2;;
        --octavios) OCTAVIOS="$2"; shift 2;;
        *) fail "unknown argument: $1";;
    esac
done
[ -n "$APP_DIR" ] || fail "--app-dir <path> is required"
[ -d "$APP_DIR" ] || fail "app folder not found: $APP_DIR"
APP_DIR="$(cd "$APP_DIR" && pwd)"

target=$(find "$APP_DIR" -maxdepth 1 -name '*.target' -type f | head -n1)
[ -n "$target" ] || fail "no *.target marker in $APP_DIR"
app=$(basename "$target" .target)

[ -n "$OCTAVIOS" ] || OCTAVIOS="$APP_DIR/../octavios"
[ -d "$OCTAVIOS" ] || fail "octavios SDK not found (pass --octavios)"
OCTAVIOS="$(cd "$OCTAVIOS" && pwd)"
APPS_DIR="$OCTAVIOS/apps"

for t in arm-none-eabi-gcc cmake ninja; do
    command -v "$t" >/dev/null 2>&1 || fail "$t not on PATH -- run check_env.sh to install the device toolchain"
done

# --- 1. ARM device build --------------------------------------------------
step "ARM device build (cmake + ninja) for $app"
out="$APP_DIR/out"
( cd "$APP_DIR" && cmake -G Ninja -S "$APPS_DIR" -B "$out" && cmake --build "$out" ) \
    || fail "ARM device build failed"
bin="$out/$app.bin"
[ -f "$bin" ] || fail "device build produced no $bin"
bin_len=$(stat -c %s "$bin")
[ "$bin_len" -gt 0 ] || fail "$bin is empty -- ARM build produced no code"
echo "    built $bin ($bin_len bytes ARM code)"

# --- 2. Pack the .oct by launching the sim once ---------------------------
# The sim embeds out/<app>.bin ONLY if it exists (sim.h treats ARM code as
# optional -- a sim-only launch writes an asset-only .oct, dead on the cube).
# We just built the .bin, so this launch must embed it -- and we verify it.
sim="$APP_DIR/build-sim/octavios_sim"
[ -x "$sim" ] || fail "simulator missing ($sim) -- run new_app.sh first"
oct="$APP_DIR/$app.oct"
rm -f "$oct"

step "Packing .oct (launching simulator to assemble the package)"
"$sim" &
sim_pid=$!
sleep 5
kill "$sim_pid" 2>/dev/null || true
wait "$sim_pid" 2>/dev/null || true
[ -f "$oct" ] || fail "simulator did not produce $oct"

# --- 3. Verify the ARM code is actually embedded --------------------------
# The sim appends the ARM code as the LAST chunk (sim.h: assets -> sounds ->
# code), so the final <bin_len> bytes of the .oct must equal the .bin
# byte-for-byte. If not, the sim packed an asset-only .oct and it would silently
# fail on the cube -- so we refuse to ship it.
oct_len=$(stat -c %s "$oct")
embedded=0
if [ "$oct_len" -ge "$bin_len" ]; then
    if cmp -s <(tail -c "$bin_len" "$oct") "$bin"; then embedded=1; fi
fi
if [ "$embedded" -ne 1 ]; then
    fail "the .oct does NOT contain the ARM code (asset-only pack). It would run
  in the simulator but is dead on the cube. Check that out/$app.bin exists and
  that APP_DIR in src/app.h points back at this app folder."
fi
echo "    verified ARM code embedded ($bin_len bytes) in the .oct"

echo ''
echo "CUBE PACKAGE READY:"
echo "  $oct"
echo "  ($oct_len bytes -- assets + sounds + $bin_len bytes ARM code)"
echo "Load this .oct onto the WowCube."
echo ''
echo "NOTE: launching the simulator again will OVERWRITE this .oct with an"
echo "asset-only pack (no ARM code). Re-run this script after any sim testing"
echo "to regenerate the cube-loadable .oct as the LAST step before shipping."
exit 0
