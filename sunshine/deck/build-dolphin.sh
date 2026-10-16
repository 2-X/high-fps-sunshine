#!/bin/bash
# Build the patched Dolphin on a Steam Deck (SteamOS has no compiler).
#
# The build runs inside the Dolphin Flatpak's own sandbox with the matching
# KDE SDK as the toolchain (`flatpak run --devel`), so the binary links against
# exactly the libraries it will have at run time — dolphin-deck launches it in
# the same sandbox. Nothing is installed on the read-only system image.
#
# Needs (one-off):  flatpak install --user flathub org.kde.Sdk//6.10
#                   (match the "Sdk:" line of `flatpak info org.DolphinEmu.dolphin-emu`)
# Source tree:      <repo>/dolphin = dolphin-emu at dolphin-patches/UPSTREAM_COMMIT.txt
#                   + high-fps-dolphin.patch, submodules initialised.
set -euo pipefail
REPO="$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd)"
APP=org.DolphinEmu.dolphin-emu
JOBS="${JOBS:-$(nproc)}"

[ -f "$REPO/dolphin/CMakeLists.txt" ] || {
  echo "no Dolphin source at $REPO/dolphin — see sunshine/dolphin-patches/README.md" >&2; exit 1; }

flatpak run --devel --filesystem=host --command=bash "$APP" -euc '
  cd "$1/dolphin"
  # libevdev ships in the app (/app), not the SDK; flatpak run does not put
  # /app on the pkg-config / CMake search paths the way flatpak-builder does.
  export PKG_CONFIG_PATH=/app/lib/pkgconfig CMAKE_PREFIX_PATH=/app
  mkdir -p build && cd build
  cmake .. -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DLINUX_LOCAL_DEV=ON \
    -DENABLE_TESTS=OFF \
    -DENABLE_AUTOUPDATE=OFF \
    -DENABLE_ANALYTICS=OFF \
    -DUSE_DISCORD_PRESENCE=OFF \
    -DUSE_RETRO_ACHIEVEMENTS=OFF \
    -DENABLE_CLI_TOOL=OFF
  nice -n 19 ninja -j "$2" dolphin-emu
' build "$REPO" "$JOBS"

# The process must be named "Dolphin": every `pgrep -x Dolphin` guard in this
# repo (launcher, gecko.py, bridge) matches on it, and it keeps our build
# distinct from a stock `dolphin-emu` the user may also be running.
ln -sfn dolphin-emu "$REPO/dolphin/build/Binaries/Dolphin"
# LINUX_LOCAL_DEV builds read their data from <exe dir>/Sys.
ln -sfn ../../Data/Sys "$REPO/dolphin/build/Binaries/Sys"
echo "built: $REPO/dolphin/build/Binaries/Dolphin"
