#!/usr/bin/env bash
# Linux mirror of check_env.ps1.
#
# Verify the WowCube build toolchain on Linux. The SDL3/CMake simulator build
# needs cmake, a C++20 host compiler, and SDL3 (plus bluez/libsystemd for the
# BT upload path). The cube-loadable .oct deliverable additionally needs the ARM
# device toolchain: arm-none-eabi-gcc, cmake, ninja. Asset packing is pure
# Python (Pillow/numpy/pytoshop/psd-tools) on every OS.
#
# Unlike the Windows script this does NOT auto-install (distros vary); it reports
# what's missing and prints the install line for the detected package manager.
#
#   --report-only   alias kept for parity with the .ps1 (this script never installs)
#
# Exit 0 = everything needed is present.  Exit 2 = something is missing.
set -uo pipefail

step() { printf '==> %s\n' "$1"; }
have() { command -v "$1" >/dev/null 2>&1; }

# tool -> human purpose
SIM_TOOLS=(cmake g++)
DEVICE_TOOLS=(arm-none-eabi-gcc cmake ninja)
PY_MODULES=(PIL numpy pytoshop psd_tools)

missing=()

step "Checking WowCube toolchain (Linux)"

# --- Simulator build deps -------------------------------------------------
for t in "${SIM_TOOLS[@]}"; do
    if have "$t"; then echo "  [ok]      $t (simulator build)"
    else echo "  [MISSING] $t (simulator build)"; missing+=("$t"); fi
done
# SDL3 via pkg-config (header lib, not a binary on PATH)
if pkg-config --exists sdl3 2>/dev/null; then echo "  [ok]      sdl3 (simulator window/GL/audio)"
else echo "  [MISSING] sdl3 (simulator window/GL/audio)"; missing+=("sdl3"); fi
# Bluetooth/SPP upload path (optional but part of the sim)
pkg-config --exists bluez 2>/dev/null     && echo "  [ok]      bluez (SPP/RFCOMM)"        || echo "  [warn]    bluez not found (BT upload path only)"
pkg-config --exists libsystemd 2>/dev/null && echo "  [ok]      libsystemd (BLE via sd-bus)" || echo "  [warn]    libsystemd not found (BLE upload path only)"

# --- Device toolchain (ARM .bin -> .oct) ----------------------------------
for t in "${DEVICE_TOOLS[@]}"; do
    if have "$t"; then echo "  [ok]      $t (cube .oct device build)"
    else echo "  [MISSING] $t (cube .oct device build)"; missing+=("$t"); fi
done

# --- Python packer deps ---------------------------------------------------
for m in "${PY_MODULES[@]}"; do
    if python -c "import $m" >/dev/null 2>&1; then echo "  [ok]      python:$m (asset packer)"
    else echo "  [MISSING] python:$m (asset packer)"; missing+=("python:$m"); fi
done

if [ "${#missing[@]}" -eq 0 ]; then
    echo ''; echo "Toolchain OK."; exit 0
fi

echo ''
echo "Missing: ${missing[*]}"
if have pacman; then
    echo "Install (Arch):"
    echo "  sudo pacman -S cmake gcc sdl3 bluez bluez-libs systemd-libs arm-none-eabi-gcc ninja"
    echo "  pip install Pillow numpy pytoshop psd-tools"
elif have apt; then
    echo "Install (Debian/Ubuntu):"
    echo "  sudo apt install cmake g++ libsdl3-dev libbluetooth-dev libsystemd-dev gcc-arm-none-eabi ninja-build"
    echo "  pip install Pillow numpy pytoshop psd-tools"
else
    echo "Install the listed tools with your distro's package manager, plus:"
    echo "  pip install Pillow numpy pytoshop psd-tools"
fi
exit 2
