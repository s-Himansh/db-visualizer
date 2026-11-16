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
echo "::endgroup::"

echo "::group::Install a desktop"
sudo apt-get update -qq
sudo apt-get install -y -qq --no-install-recommends xfce4 xfce4-terminal tigervnc-standalone-server dbus-x11 xdotool \
    imagemagick x11-utils fonts-dejavu-core >/dev/null
echo "::endgroup::"

export DISPLAY=:1
Xvnc :1 -geometry 1440x900 -depth 24 -SecurityTypes None -localhost yes > xvnc.log 2>&1 &
for i in $(seq 1 30); do xdpyinfo >/dev/null 2>&1 && break; sleep 1; done
xdpyinfo | grep -E "dimensions|depth of root" | sed 's/^ *//'
dbus-run-session -- startxfce4 > xfce.log 2>&1 &
sleep 12                                     # the panel and window manager come up
echo "desktop windows now: $(xdotool search --onlyvisible --name '' 2>/dev/null | wc -l)"
import -window root 01-desktop-before-the-app.png

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
import -window root 06-the-desktop-at-the-end.png
kill $APP 2>/dev/null || true; sleep 2; kill -9 $APP 2>/dev/null || true
echo "--- the end of the app's output"; tail -5 app-stdout.log | cut -c1-200
exit $STATUS
