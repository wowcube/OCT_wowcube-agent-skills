#!/usr/bin/env bash
# Linux mirror of build_device.ps1: build the cube-loadable .oct of an app_<game> folder into
# <workspace>/dist/, verified. Never starts a simulator.
#
#   octpack (default when available; octavios dev 609d5ae+):
#     uv run --frozen --project <octavios>/octpacker octpack-build <app> --out <out> --engine <octavios>
#     (metadata from src/app_metadata.h, art/octpack.json packed if present - AI-art apps have none and keep
#      the python packer's art/packed + index.bin -, ARM build with cmake + Ninja into out/, the .oct)
#   python (fallback): cmake + Ninja ARM build, then scripts/pack_beta.py --build-oct (stamps SaveSize from
#     APP_SAVE_SIZE reached through src/app_metadata.h, read from app_save.h's static_assert)
#   verify (mandatory): the .oct ends with out/<app>.bin, then scripts/pack_beta.py --verify-oct: magic, size, CRC,
#     code_size/offset, non-zero build id, title/version/GUID/categories/save size == the app's defines, MAP "ico",
#     assets == index.bin (header from octpack-info when it runs, else read locally); failure to verify = exit 1
#
# Usage: build_device.sh --app-dir <workspace>/app_<game> [--octavios <dir>] [--out <path.oct>]
#                        [--builder auto|octpack|python] [--no-uv]   (--no-uv / WOWCUBE_NO_UV=1: never start uv)
#                        [--uv-env <dir>]   octpacker's environment: default UV_PROJECT_ENVIRONMENT, else
#                        <workspace>/.uv_octpack_venv - never inside octavios (first use downloads the pinned packages)
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACK_PY="$SCRIPT_DIR/pack_beta.py"
APP_DIR=''; OCTAVIOS=''; OUT=''; BUILDER='auto'; NO_UV=0; UV_ENV=''
case "${WOWCUBE_NO_UV:-}" in 1|true|yes) NO_UV=1;; esac
fail() { printf 'ERROR: %s\n' "$1" >&2; exit 1; }
step() { printf '==> %s\n' "$1"; }
have() { command -v "$1" >/dev/null 2>&1; }

while [ $# -gt 0 ]; do
    case "$1" in
        --app-dir)  APP_DIR="$2"; shift 2;;
        --octavios) OCTAVIOS="$2"; shift 2;;
        --out)      OUT="$2"; shift 2;;
        --builder)  BUILDER="$2"; shift 2;;
        --no-uv)    NO_UV=1; shift;;
        --uv-env)   UV_ENV="$2"; shift 2;;
        *) fail "unknown argument: $1";;
    esac
done
[ -n "$APP_DIR" ] || fail "--app-dir <path> is required"
[ -d "$APP_DIR" ] || fail "app folder not found: $APP_DIR"
APP_DIR="$(cd "$APP_DIR" && pwd)"
n_targets=$(find "$APP_DIR" -maxdepth 1 -name '*.target' -type f | wc -l)
[ "$n_targets" -eq 1 ] || fail "$APP_DIR must hold exactly one *.target marker (found $n_targets)"
app=$(basename "$(find "$APP_DIR" -maxdepth 1 -name '*.target' -type f)" .target)
[ -f "$APP_DIR/index.bin" ] || fail "$APP_DIR/index.bin missing - pack the assets first (Stage 3)"

[ -n "$OCTAVIOS" ] || OCTAVIOS="$APP_DIR/../octavios"
[ -f "$OCTAVIOS/apps/CMakeLists.txt" ] || fail "octavios SDK not found (pass --octavios)"
OCTAVIOS="$(cd "$OCTAVIOS" && pwd)"
[ -n "$OUT" ] || OUT="$(dirname "$APP_DIR")/dist/$app.oct"
mkdir -p "$(dirname "$OUT")"
OUT="$(cd "$(dirname "$OUT")" && pwd)/$(basename "$OUT")"

OCTPACK="$OCTAVIOS/octpacker"
# octpacker's environment lives in the workspace, never in the SDK tree (uv would otherwise create octpacker/.venv)
UV_ENV="${UV_ENV:-${UV_PROJECT_ENVIRONMENT:-$(dirname "$APP_DIR")/.uv_octpack_venv}}"
# uv resolves a RELATIVE UV_PROJECT_ENVIRONMENT against --project (octpacker/), which would put the venv inside the
# SDK: make it absolute from the caller's working directory first
case "$UV_ENV" in /*|[A-Za-z]:[/\\]*) ;; *) UV_ENV="$PWD/$UV_ENV";; esac
export UV_PROJECT_ENVIRONMENT="$UV_ENV"
use_uv=0
have uv && [ "$NO_UV" -eq 0 ] && use_uv=1
[ "$NO_UV" -eq 1 ] && echo "    NOTE: --no-uv / WOWCUBE_NO_UV: uv is not started (python builder, local header check)" >&2
octpack_ready=0
[ -f "$OCTPACK/pyproject.toml" ] && [ "$use_uv" -eq 1 ] && [ -f "$APP_DIR/src/app_metadata.h" ] && octpack_ready=1
case "$BUILDER" in
    auto)    [ "$octpack_ready" -eq 1 ] && BUILDER=octpack || BUILDER=python;;
    octpack) [ "$octpack_ready" -eq 1 ] || fail "octpack-build needs octavios dev (octpacker/), uv and src/app_metadata.h (check_env.sh); or --builder python";;
    python)  ;;
    *) fail "--builder must be auto, octpack or python";;
esac
BIN="$APP_DIR/out/$app.bin"
info_file=''
stamp=$(mktemp); trap 'rm -f "$stamp" ${info_file:+"$info_file"}' EXIT

# --- 1. build ----------------------------------------------------------------
if [ "$BUILDER" = octpack ]; then
    [ -f "$APP_DIR/art/octpack.json" ] && \
        echo "    NOTE: art/octpack.json present: octpack-build re-packs art from its sources (wipes art/packed and index.bin)." >&2
    step "octpack-build $app -> $OUT"
    uv run --frozen --project "$OCTPACK" octpack-build "$APP_DIR" --out "$OUT" --engine "$OCTAVIOS" \
        || fail "octpack-build failed. Stale out/ from another SDK checkout? rm -rf $APP_DIR/out and retry."
else
    for t in arm-none-eabi-g++ cmake ninja python3; do have "$t" || fail "$t not on PATH - run check_env.sh"; done
    step "ARM device build (cmake + Ninja) for $app"
    cmake -G Ninja -S "$OCTAVIOS/apps" -B "$APP_DIR/out" -DAPP_TELEMETRY=OFF \
        || fail "cmake configure failed. Stale out/ from another SDK checkout? rm -rf $APP_DIR/out and retry."
    cmake --build "$APP_DIR/out" --parallel 4 || fail "ARM build failed"
    step "Packing .oct (python scripts/pack_beta.py --build-oct)"
    rm -f "$OUT"
    python3 "$PACK_PY" --build-oct --app-dir "$APP_DIR" --code "$BIN" --out "$OUT" || fail "python .oct builder failed"
fi

# --- 2. verify -----------------------------------------------------------------
[ -f "$OUT" ] || fail "no .oct at $OUT"
[ "$OUT" -nt "$stamp" ] || fail "$OUT was not rewritten by this build"
[ -f "$BIN" ] || fail "no ARM module at $BIN"
bin_len=$(wc -c < "$BIN"); oct_len=$(wc -c < "$OUT")
[ "$bin_len" -gt 0 ] || fail "$BIN is empty - the ARM build produced no code"
{ [ "$oct_len" -ge "$bin_len" ] && cmp -s <(tail -c "$bin_len" "$OUT") "$BIN"; } \
    || fail "the .oct does NOT end with out/$app.bin: no ARM code, dead on the cube"
echo "    ARM code embedded ($bin_len bytes)"

# Header verification is MANDATORY (scripts/pack_beta.py --verify-oct): magic, size, CRC, the ARM tail, a non-zero
# build id, title/version/GUID/categories/save size == the app's defines, MAP "ico", assets == index.bin. The header
# comes from octpack-info when it runs, otherwise from a local read; what cannot be verified fails the build.
version=''
have python3 || fail "cannot verify $OUT: python3 is not on PATH (scripts/pack_beta.py --verify-oct reads the header)"
if [ -f "$OCTPACK/pyproject.toml" ] && [ "$use_uv" -eq 1 ]; then
    info_file=$(mktemp)
    if ! uv run --frozen --project "$OCTPACK" octpack-info "$OUT" --engine "$OCTAVIOS" > "$info_file" \
            || [ ! -s "$info_file" ]; then
        echo "    octpack-info failed: verifying with the local header check instead" >&2
        rm -f "$info_file"; info_file=''
    fi
else
    echo "    uv/octpacker not available: verifying with the local header check (scripts/pack_beta.py)" >&2
fi
verify_args=(--verify-oct "$OUT" --app-dir "$APP_DIR" --code "$BIN")
[ -n "$info_file" ] && verify_args+=(--info-json "$info_file")
verify_out=$(python3 "$PACK_PY" "${verify_args[@]}"); verify_rc=$?
[ -n "$info_file" ] && rm -f "$info_file"
printf '%s\n' "$verify_out"
[ "$verify_rc" -eq 0 ] || fail ".oct verification failed (exit $verify_rc): see the ERROR lines above - nothing to deliver"
version=$(printf '%s\n' "$verify_out" | sed -n 's/^VERSION=//p' | head -n 1)

echo ''
echo "CUBE PACKAGE READY ($BUILDER): $OUT"
echo "  $oct_len bytes = assets + sounds + $bin_len bytes ARM code${version:+; version $version}"
echo "  Upload when the user asks: $OCTAVIOS/build/spptest --mac <AA:BB:CC:DD:EE:FF> --software $OUT --long-timeout"
echo "  (spptest: cmake -S $OCTAVIOS -B $OCTAVIOS/build && cmake --build $OCTAVIOS/build --target spptest)"
echo "  Deliver this file, never one a simulator wrote into the app folder."
exit 0
