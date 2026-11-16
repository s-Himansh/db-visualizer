#!/bin/bash
# Runs the RELEASED Linux build in a full desktop session (XFCE: window manager, panel, a real X display) on a native x86-64 Ubuntu
# machine, then drives the app's own window and takes screenshots of the whole desktop.
#   bash packaging/linux-desktop-check.sh v0.2.2         a published release
#   bash packaging/linux-desktop-check.sh run:43843861947   the Linux build of a CI run (to test a fix before anything is released)
# (needs GH_TOKEN and GITHUB_REPOSITORY; used by the Linux desktop check workflow). It uses the file exactly as a person would get
# it, started the way they would start it (./Cairn/Cairn, no settings).
set -euo pipefail
SOURCE=${1:?a release tag such as v0.2.2, or run:<id>}
TAR=Cairn-Linux-x86_64.tar.gz
ROOT=$PWD
OUT=${OUT:-$PWD/desktop-check}
STATUS=0
mkdir -p "$OUT" && cd "$OUT"

echo "::group::Download the build ($SOURCE)"
if [[ "$SOURCE" == run:* ]]; then
    gh run download "${SOURCE#run:}" -R "$GITHUB_REPOSITORY" -n Cairn-Linux-x86_64 -D .
else
    gh release download "$SOURCE" -R "$GITHUB_REPOSITORY" -p "$TAR" -p SHA256SUMS.txt
    grep "$TAR" SHA256SUMS.txt | sha256sum -c -
fi
ls -la "$TAR" | awk '{print $5/1048576 " MB"}'
mkdir app && tar xzf "$TAR" -C app
if [ "${DESKTOP_WITHOUT_BUNDLED_GL:-0}" = "1" ]; then
    echo "removing the bundled graphics dispatch libraries, so the system's are used:"
    for lib in libGL.so.1 libGLX.so.0 libGLdispatch.so.0 libEGL.so.1; do
        [ -e "app/Cairn/_internal/$lib" ] && rm -v "app/Cairn/_internal/$lib" | sed 's/^/  /'
    done
fi
echo "::endgroup::"

echo "::group::Install a desktop"
sudo apt-get update -qq
sudo apt-get install -y -qq --no-install-recommends xfce4 xfce4-terminal tigervnc-standalone-server dbus-x11 xdotool \
    imagemagick x11-utils fonts-dejavu-core >/dev/null
echo "::endgroup::"

# DESKTOP_GPU=1: the app's hardware drawing path (DBV_GPU=1) instead of its software default. A CI machine has no physical GPU, so this
# gives that path a real OpenGL driver to talk to: Mesa, whose software rasteriser (llvmpipe) is reached through the same libglvnd / GLX / EGL
# plumbing a hardware driver uses. It tests how the app's bundled dispatch libraries meet the system's driver; it does not test any
# particular vendor's driver.
if [ "${DESKTOP_GPU:-0}" = "1" ]; then
    echo "::group::Install Mesa, the OpenGL driver for the hardware drawing path"
    sudo apt-get install -y -qq --no-install-recommends libgl1 libglx-mesa0 libgl1-mesa-dri libegl1 libegl-mesa0 libgbm1 mesa-utils >/dev/null
    echo "::endgroup::"
fi

export DISPLAY=:1
Xvnc :1 -geometry 1440x900 -depth 24 -SecurityTypes None -localhost yes > xvnc.log 2>&1 &
for i in $(seq 1 30); do xdpyinfo >/dev/null 2>&1 && break; sleep 1; done
xdpyinfo | grep -E "dimensions|depth of root" | sed 's/^ *//'
if [ "${DESKTOP_GPU:-0}" = "1" ]; then
    echo "--- what the desktop's OpenGL looks like"; glxinfo -B 2>&1 | grep -E "direct rendering|OpenGL renderer|OpenGL version|Error|couldn" | sed 's/^/  /'
fi
if [ "${DESKTOP_GPU:-0}" = "1" ]; then
    # the control: plain Qt (not Cairn), same minor version as the bundle, asks this X server for OpenGL
    echo "::group::Control: can a plain Qt program get OpenGL on this desktop?"
    # a plain Qt program needs the X11 libraries Cairn carries inside itself (since 6.5 the xcb plugin wants libxcb-cursor0 on the system)
    sudo apt-get install -y -qq --no-install-recommends libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 \
        libxcb-shape0 libxcb-xinerama0 libxcb-xkb1 libxkbcommon-x11-0 libxkbcommon0 libfontconfig1 libdbus-1-3 libglib2.0-0 >/dev/null
    python3 -m pip install --user -q "PySide6-Essentials~=6.12" 2>&1 | tail -1
    QT_QPA_PLATFORM=xcb python3 "$ROOT/packaging/qt_gl_control.py" 2>&1 | sed 's/^/  /' | cut -c1-200 || true
    echo "::endgroup::"
    echo "::group::Control: Cairn FROM SOURCE (plain Python and pip-installed Qt, no PyInstaller), hardware path on"
    python3 -m pip install --user -q -r "$ROOT/requirements.txt" -r "$ROOT/requirements-linux.txt" 2>&1 | tail -1
    sudo apt-get install -y -qq --no-install-recommends libnss3 libnspr4 libasound2t64 libxcomposite1 libxdamage1 libxrandr2 libxtst6 libxshmfence1 \
        libxfixes3 libxkbfile1 libegl1 libgl1 >/dev/null
    ( cd "$ROOT" && DISPLAY=:1 DBV_GPU=1 QT_QPA_PLATFORM=xcb QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox" DBV_DATA_DIR="$OUT/data-source" \
        python3 db.py > "$OUT/source.log" 2>&1 & pid=$!
      sleep 25
      if kill -0 $pid 2>/dev/null; then
          echo "  RESULT [from source, hardware path]: the app stayed running; its window: $(DISPLAY=:1 xdotool search --onlyvisible --name '^Cairn$' 2>/dev/null | head -1 | sed 's/^$/none found/')"
          kill $pid; sleep 1; kill -9 $pid 2>/dev/null
      else
          echo "  RESULT [from source, hardware path]: it exited ($(grep -m1 -oE 'Could not initialize GLX|ModuleNotFoundError[^\n]*|ImportError[^\n]*' "$OUT/source.log" || echo see source.log))"; tail -4 "$OUT/source.log" | cut -c1-200 | sed 's/^/    /'
      fi ) || true
    echo "::endgroup::"
    echo "::group::Control: can a plain Qt WebEngine program (no Cairn, no PyInstaller) show a page on this desktop?"
    sudo apt-get install -y -qq --no-install-recommends libnss3 libnspr4 libasound2t64 libxcomposite1 libxdamage1 libxrandr2 libxtst6 libxshmfence1 \
        libxfixes3 libxkbfile1 libegl1 libgl1 >/dev/null
    python3 -m pip install --user -q "PySide6-Addons~=6.12" "PySide6-WebEngine~=6.12" 2>&1 | tail -1
    echo "  -- with the hardware path (what DBV_GPU=1 gives the app)"
    QT_QPA_PLATFORM=xcb QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox" timeout -s KILL 60 python3 "$ROOT/packaging/qt_webengine_control.py" 2>&1 | sed 's/^/     /' | cut -c1-200 || true
    echo "  -- with the app's software defaults (what everyone gets)"
    QT_QPA_PLATFORM=xcb QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox --disable-gpu" QT_QUICK_BACKEND=software QT_XCB_GL_INTEGRATION=none timeout -s KILL 60 python3 "$ROOT/packaging/qt_webengine_control.py" 2>&1 | sed 's/^/     /' | cut -c1-200 || true
    echo "::endgroup::"
fi
dbus-run-session -- startxfce4 > xfce.log 2>&1 &
sleep 12                                     # the panel and window manager come up
echo "desktop windows now: $(xdotool search --onlyvisible --name '' 2>/dev/null | wc -l)"
import -window root 01-desktop-before-the-app.png

if [ "${DESKTOP_GPU:-0}" = "1" ]; then export DBV_GPU=1; echo "starting WITH DBV_GPU=1 (hardware drawing)"; fi
if [ "${DESKTOP_GPU_BISECT:-0}" = "1" ]; then
    # With DBV_GPU=1 the app fails on this desktop although a plain Qt program gets OpenGL here, so something in the bundle is at fault.
    # The bundle carries ~300 libraries copied from the build machine (Ubuntu 22.04), among them the X11 client stack, which then sits in
    # front of the desktop's own newer ones. Remove groups of them CUMULATIVELY and try the app after each: the first step at which the
    # window stays open names the group.
    echo "::group::Which bundled libraries break the hardware drawing path?"
    NAMES=("nothing removed" "GL dispatch" "X11 client" "xcb extensions" "drm, gbm, udev, wayland")
    LIBS=(""
          "libGL.so.1 libGLX.so.0 libGLdispatch.so.0 libEGL.so.1"
          "libX11.so.6 libX11-xcb.so.1 libXext.so.6 libXau.so.6 libXdmcp.so.6 libXfixes.so.3 libXrender.so.1 libXi.so.6 libXcomposite.so.1 libXdamage.so.1 libXrandr.so.2 libXtst.so.6 libXcursor.so.1 libXinerama.so.1"
          "libxcb-glx.so.0 libxcb-randr.so.0 libxcb-render.so.0 libxcb-shm.so.0 libxcb-sync.so.1 libxcb-xfixes.so.0 libxcb-dri3.so.0"
          "libgbm.so.1 libdrm.so.2 libudev.so.1 libexpat.so.1 libwayland-client.so.0 libwayland-server.so.0 libwayland-egl.so.1 libwayland-cursor.so.0")
    cp -a app trial
    for i in 0 1 2 3 4; do
        for lib in ${LIBS[$i]}; do rm -f "trial/Cairn/_internal/$lib"; done
        ( export DBV_GPU=1 DBV_DATA_DIR="$OUT/data-trial$i"; ./trial/Cairn/Cairn > "trial$i.log" 2>&1 & pid=$!
          sleep 14
          if kill -0 $pid 2>/dev/null; then echo "  RESULT after removing up to [${NAMES[$i]}]: the app stayed running"; kill $pid; sleep 1; kill -9 $pid 2>/dev/null
          else echo "  RESULT after removing up to [${NAMES[$i]}]: it exited ($(grep -m1 -oE 'Could not initialize GLX|cannot open shared object file[^,]*|undefined symbol[^ ]*' "trial$i.log" || echo see log))"; fi ) || true
    done
    echo "::endgroup::"
    exit 0
fi

if [ "${DESKTOP_GPU_VARIANTS:-0}" = "1" ]; then
    # The failure ("Could not initialize GLX ... qglx_findConfig ... version 2.0") is Qt WebEngine asking this virtual X server for an OpenGL ES 2.0
    # context through GLX. Try the app with settings that ask differently, and see which start.
    echo "::group::Which GL settings start the app?"
    run_variant() {  # run_variant <name> [VAR=value ...]
        local name=$1; shift
        rm -rf "$OUT/data-variant"
        ( export DBV_GPU=1 DBV_DATA_DIR="$OUT/data-variant"; env "$@" ./app/Cairn/Cairn > variant.log 2>&1 & pid=$!
          sleep 14
          if kill -0 $pid 2>/dev/null; then echo "  RESULT [$name]: the app stayed running"; kill $pid; sleep 1; kill -9 $pid 2>/dev/null
          else echo "  RESULT [$name]: it exited ($(grep -m1 -oE 'Could not initialize GLX|cannot open shared object file[^,]*|undefined symbol[^ ]*|Failed to create [A-Za-z ]*' variant.log || echo see log))"; fi ) || true
    }
    run_variant "as it ships with DBV_GPU=1"
    run_variant "Qt GL through EGL instead of GLX" QT_XCB_GL_INTEGRATION=xcb_egl
    run_variant "force desktop OpenGL" QT_OPENGL=desktop
    run_variant "Chromium: --use-gl=egl" "QTWEBENGINE_CHROMIUM_FLAGS=--no-sandbox --use-gl=egl"
    run_variant "Chromium: ANGLE over desktop GL" "QTWEBENGINE_CHROMIUM_FLAGS=--no-sandbox --use-gl=angle --use-angle=gl"
    run_variant "EGL for Qt and for Chromium" QT_XCB_GL_INTEGRATION=xcb_egl "QTWEBENGINE_CHROMIUM_FLAGS=--no-sandbox --use-gl=egl"
    echo "::endgroup::"
    exit 0
fi

echo "::group::Start the app the way a person would"
# QTWEBENGINE_REMOTE_DEBUGGING only lets the test drive the window afterwards; it changes no rendering setting.
DBV_DATA_DIR="$OUT/data" QTWEBENGINE_REMOTE_DEBUGGING=9222 ./app/Cairn/Cairn > app-stdout.log 2>&1 &
APP=$!
win=""
for i in $(seq 1 60); do
    win=$(xdotool search --onlyvisible --name '^Cairn$' 2>/dev/null | head -1 || true)
    [ -n "$win" ] && break
    kill -0 $APP 2>/dev/null || { echo "the app exited before its window appeared"; tail -20 app-stdout.log; exit 1; }
    sleep 1
done
[ -n "$win" ] || { echo "no window named Cairn appeared in 60 seconds"; tail -20 app-stdout.log; exit 1; }
echo "window found: id $win after ~${i}s"
xdotool getwindowgeometry "$win" | sed 's/^ *//'
echo "window title: $(xdotool getwindowname "$win")"
sleep 6
import -window root 02-the-app-window.png
echo "::endgroup::"

echo "::group::Use it: sample database, a table, the grid"
python3 -m pip install --user -q websocket-client
python3 "$ROOT/packaging/linux_desktop_drive.py" "$OUT" || { echo "the drive script failed"; STATUS=1; }
echo "::endgroup::"

kill -0 $APP 2>/dev/null && echo "the app is still running after the session: yes" || { echo "the app is still running: NO (it exited)"; STATUS=1; }
import -window root 07-the-desktop-at-the-end.png
kill $APP 2>/dev/null || true; sleep 2; kill -9 $APP 2>/dev/null || true
echo "--- the end of the app's output"; tail -5 app-stdout.log | cut -c1-200
exit $STATUS
