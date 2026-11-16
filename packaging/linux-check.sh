#!/bin/bash
# Run by the Build workflow inside a fresh ubuntu:24.04 container, to prove the Linux app starts the way it would for a person
# who has just downloaded it:   bash /in/packaging/linux-check.sh Cairn-Linux-x86_64.tar.gz
# /in is the repository (read-only) with the tarball in it. The container has a virtual screen and nothing else (no Mesa, no
# libGL, no libEGL), so the libraries bundled in the app are what is being tested. (An earlier version installed libegl1 here and
# called it what every desktop has; a full desktop session then found the app failing for want of exactly that.)
set -u

apt-get update -qq
apt-get install -y -qq --no-install-recommends xvfb xauth >/dev/null
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

# Open the real window the way the app ships (its own defaults: see linux_web_view_defaults in db.py) and require two things after
# 15 seconds: the program is still running, and the web view has asked the app's local server for its page (the app writes a log
# line when it serves the main page; pywebview's own server logs nothing), which is real evidence it drew something and not just that a process exists. A build machine has no GPU, and the
# virtual X server here (Xvfb) has no working GLX; the first attempts died with "Could not initialize GLX" until the app was made
# to draw in software by default. Chromium shuts down through its event loop on a polite stop, which a headless run never
# finishes, so the stop is followed by a hard kill.
rm -f "$DBV_DATA_DIR/app.log"      # so the self-check above (which also asks for the page) is not mistaken for the window
timeout -s KILL 90 xvfb-run -a -s "$SCREEN" bash -c \
    './Cairn > /tmp/launch.log 2>&1 & pid=$!; sleep 15; if kill -0 $pid 2>/dev/null; then echo alive > /tmp/alive; kill $pid; sleep 2; kill -9 $pid 2>/dev/null; fi; exit 0'
echo "--- the end of the app log"
tail -6 /tmp/launch.log | cut -c1-200
if [ ! -f /tmp/alive ]; then echo "FAILED: the program was not running after 15 seconds"; exit 1; fi
if ! grep -q 'serving the main page' "$DBV_DATA_DIR/app.log" 2>/dev/null; then echo "FAILED: the program ran but the web view never asked for the page"; exit 1; fi
echo "OK: the window stayed open and the web view loaded the page"
