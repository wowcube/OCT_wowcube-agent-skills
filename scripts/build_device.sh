#!/usr/bin/env bash
# Linux mirror of build_device.ps1.
#
# Produce the cube-loadable .oct for an existing app_<game> folder. The .oct is
# assembled by the pure-Python builder (scripts/pack_beta.py --build-oct),
# which packs: art .raw assets + sounds + the ARM device code from
# out/<app>.bin. So a *loadable* .oct is:
#
#   1. ARM device build  -> app_<game>/out/app_<game>.bin
#      (cmake -G Ninja -S <octavios>/apps -B out ; cmake --build out)
#   2. python scripts/pack_beta.py --build-oct -> app_<game>/app_<game>.oct
#      (assets + sounds + ARM code, deterministic bytes)
#   3. Verify the ARM code is actually embedded (asset-only packs are DEAD on cube)
#
# This no longer launches the simulator or needs MSVC -- only the ARM device
# toolchain (arm-none-eabi-gcc, cmake, ninja) and python. Run check_env.sh
# first if any of those are missing. Without the ARM .bin there is no code to
# embed; this script treats a missing/empty .bin as a failure.
#
# Usage: build_device.sh --app-dir <workspace>/app_<game> [--octavios <path>]
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACK_PY="$SCRIPT_DIR/pack_beta.py"

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

for t in arm-none-eabi-gcc cmake ninja python; do
    command -v "$t" >/dev/null 2>&1 || fail "$t not on PATH -- run check_env.sh to install the device toolchain"
done
[ -f "$PACK_PY" ] || fail "python builder not found: $PACK_PY"

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

# --- 2. Pack the .oct with the pure-Python builder -------------------------
# scripts/pack_beta.py --build-oct assembles the pack directly from
# index.bin + art/packed + sound/assets + the ARM code, byte-identical to
# what the simulator used to write (minus its wall-clock BuildDateTime stamp,
# which the python builder pins to 0 for determinism). No simulator launch,
# no MSVC needed.
oct="$APP_DIR/$app.oct"
rm -f "$oct"

step "Packing .oct (python scripts/pack_beta.py --build-oct)"
python "$PACK_PY" --build-oct --app-dir "$APP_DIR" --code "$bin" --out "$oct" \
    || fail "python .oct builder failed"
[ -f "$oct" ] || fail "python builder did not produce $oct"

# --- 3. Verify the ARM code is actually embedded --------------------------
# The builder appends the ARM code as the LAST chunk (assets -> sounds ->
# code), so the final <bin_len> bytes of the .oct must equal the .bin
# byte-for-byte. If not, something upstream produced an asset-only .oct and it
# would silently fail on the cube -- so we refuse to ship it. This check is
# unchanged from when the simulator wrote the .oct; it now verifies our own
# python builder instead, which is still valuable.
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

# --- 4. Warn about stray timestamped .oct files in the app root ------------
# The Linux simulator deletes root .oct files at startup, so anything like
# <app>_20250101.oct left in the app root can silently vanish. Warning only.
stray_oct=$(find "$APP_DIR" -maxdepth 1 -name "${app}_*.oct" -type f 2>/dev/null)
if [ -n "$stray_oct" ]; then
    {
        echo "WARNING: stray timestamped .oct file(s) in the app root:"
        printf '%s\n' "$stray_oct" | while IFS= read -r s; do echo "    $(basename "$s")"; done
        echo "The Linux simulator deletes root .oct files at startup. Keep deliverables"
        echo "in a pack/ subfolder (or copy them out of the app root) so they survive."
    } >&2
fi

echo ''
echo "CUBE PACKAGE READY:"
echo "  $oct"
echo "  ($oct_len bytes -- assets + sounds + $bin_len bytes ARM code)"
echo "Load this .oct onto the WowCube."
echo ''
echo "NOTE: launching the simulator manually will still OVERWRITE this .oct with"
echo "an asset-only pack (no ARM code) -- but device delivery no longer depends"
echo "on the sim. Re-run this script after any sim play-testing session to"
echo "regenerate the cube-loadable .oct as the LAST step before shipping."
exit 0
