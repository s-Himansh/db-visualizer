#!/bin/bash
# Run by the Build workflow inside a fresh ubuntu:24.04 container, to prove the Linux app starts the way it would for a person
# who has just downloaded it:   bash /in/packaging/linux-check.sh Cairn-Linux-x86_64.tar.gz
# /in is the repository (read-only) with the tarball in it. The container has a virtual screen and Mesa's graphics libraries
# (what every Linux desktop has) and nothing else, so the libraries bundled in the app are what is being tested.
set -u

apt-get update -qq
apt-get install -y -qq --no-install-recommends xvfb xauth libegl1 libgl1 libegl-mesa0 libglx-mesa0 libgl1-mesa-dri >/dev/null
mkdir /t && tar xzf "/in/$1" -C /t && cd /t/Cairn || exit 1

echo "--- libraries the bundle needs that this system lacks (none is best):"
# ldd is told where the bundle keeps its own libraries, and only the Qt files are checked
export LD_LIBRARY_PATH=/t/Cairn/_internal:/t/Cairn/_internal/PySide6/Qt/lib
find /t/Cairn \( -name "libQt6*" -o -name "libq*.so" -o -name QtWebEngineProcess -o -name "*.abi3.so" \) -type f \
    | xargs ldd 2>/dev/null | grep "not found" | sort | uniq -c | sort -rn | head -40
unset LD_LIBRARY_PATH
echo "---"

export DBV_DATA_DIR=/tmp/cairn-data
SCREEN="-screen 0 1280x1024x24"

echo "--- the built-in check"
timeout -s KILL 120 xvfb-run -a -s "$SCREEN" ./Cairn --self-check || exit 1

# Open the real window and see whether it is still there after 15 seconds. A build machine has no GPU, so what works without one
# is what is being found out: each variant sets the environment differently. Chromium shuts down through its event loop on a
# polite stop, which a headless run never finishes, so the stop is followed by a hard kill.
try() {  # try <name> <screen arguments> [VAR=value ...]
    local name=$1 screen=$2
    shift 2
    env "$@" timeout -s KILL 90 xvfb-run -a -s "$screen" bash -c \
        './Cairn > /tmp/launch.log 2>&1 & pid=$!; sleep 15; if kill -0 $pid 2>/dev/null; then kill $pid; sleep 2; kill -9 $pid 2>/dev/null; exit 0; else exit 1; fi'
    local rc=$?
    echo "RESULT $name: $([ $rc -eq 0 ] && echo "the window stayed open" || echo FAILED)"
    if [ $rc -ne 0 ]; then tail -3 /tmp/launch.log | cut -c1-200; fi
    return $rc
}

ok=0
try "1 the app as it ships"                       "$SCREEN" && ok=1
try "2 software Qt Quick, no GPU"                 "$SCREEN" QT_QUICK_BACKEND=software QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox --disable-gpu" && ok=1
try "3 as 2, and no software rasteriser"          "$SCREEN" QT_QUICK_BACKEND=software QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox --disable-gpu --disable-software-rasterizer" && ok=1
try "4 offscreen platform, software Qt Quick"     "$SCREEN" QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox --disable-gpu" && ok=1
try "5 SwiftShader through ANGLE"                 "$SCREEN" LIBGL_ALWAYS_SOFTWARE=1 QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox --use-gl=angle --use-angle=swiftshader --enable-unsafe-swiftshader" && ok=1
try "6 as 2, with GLX switched on in the X server" "$SCREEN +extension GLX +render -noreset" QT_QUICK_BACKEND=software QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox --disable-gpu" && ok=1

if [ $ok -eq 0 ]; then echo "no way of starting the window worked"; exit 1; fi
