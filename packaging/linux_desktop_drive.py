"""Drives the app's own window the way a person would, on a real desktop session. Run by linux-desktop-check.sh; exits non-zero when
something is wrong.

READING the page uses Qt's web engine debugging port (QTWEBENGINE_REMOTE_DEBUGGING=9222), over a plain websocket: Playwright cannot attach
to it (QtWebEngine does not implement the browser-context part of the protocol it asks for). ACTING on the page uses real mouse and
keyboard events through the X server (xdotool), so the app receives what a person's hand would send. Screenshots of the whole desktop are
taken between steps with ImageMagick."""
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import websocket

out = Path(sys.argv[1])
failures = []


def check(label, ok, detail=''):
    print(('PASS  ' if ok else 'FAIL  ') + label + (f'   {detail}' if detail else ''), flush=True)
    if not ok:
        failures.append(label)


def desktop(name):
    subprocess.run(['import', '-window', 'root', str(out / name)], check=True)


# ---- reading the page -------------------------------------------------------------------------------------------------------------
target = next(t for t in json.load(urllib.request.urlopen('http://127.0.0.1:9222/json')) if t['type'] == 'page')
ws = websocket.create_connection(target['webSocketDebuggerUrl'], timeout=30)
_ids = iter(range(1, 10_000))


def js(expression):
    """Run JavaScript in the page and return its value."""
    ident = next(_ids)
    ws.send(json.dumps({'id': ident, 'method': 'Runtime.evaluate',
                        'params': {'expression': expression, 'awaitPromise': True, 'returnByValue': True}}))
    while True:
        reply = json.loads(ws.recv())
        if reply.get('id') == ident:
            if 'exceptionDetails' in reply.get('result', {}):
                raise RuntimeError(reply['result']['exceptionDetails'].get('text', 'script error'))
            return reply['result']['result'].get('value')


def wait_for(expression, seconds=30):
    end = time.time() + seconds
    while time.time() < end:
        if js(expression):
            return True
        time.sleep(0.4)
    return False


# ---- acting on it, with real input --------------------------------------------------------------------------------------------------
window = subprocess.run(['xdotool', 'search', '--onlyvisible', '--name', '^Cairn$'], capture_output=True, text=True).stdout.split()[0]


def x(*args):
    subprocess.run(['xdotool', *args], check=True)


def point_at(selector, nth=0):
    """Move the real pointer onto an element. The page fills the window, so a position in the page is a position in the window."""
    box = js(f"(() => {{ const e = document.querySelectorAll({json.dumps(selector)})[{nth}]; if (!e) return null; e.scrollIntoView({{block: 'center'}});"
             f"const r = e.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; }})()")
    assert box, f'nothing matches {selector}'
    x('mousemove', '--window', window, str(int(box[0])), str(int(box[1])))
    time.sleep(0.3)


def click(selector, nth=0, times=1):
    point_at(selector, nth)
    x('click', '--repeat', str(times), '--delay', '90', '1')
    time.sleep(0.5)


# ---- the session ------------------------------------------------------------------------------------------------------------------------
info = js("({title: document.title, ua: navigator.userAgent, w: innerWidth, h: innerHeight})")
print('web view:', info['ua'].split(') ')[-1], f"{info['w']}x{info['h']}", flush=True)
check('the page title is Cairn', info['title'] == 'Cairn', info['title'])
check('it is the packaged Qt web view', 'QtWebEngine' in info['ua'])
check('the first screen offers the sample database', wait_for("!!document.querySelector('#welcome-sample')"))

click('#welcome-sample')
check('the sample database connected and lists its tables', wait_for("document.querySelectorAll('#tables-content .tree-item').length >= 3"),
      ', '.join(js("[...document.querySelectorAll('#tables-content .tree-label')].map(e => e.textContent).slice(0, 6)") or []))
time.sleep(1)
desktop('03-sample-database-connected.png')

index = js("[...document.querySelectorAll('#tables-content .tree-item')].findIndex(e => e.textContent.includes('orders'))")
click('#tables-content .tree-item', nth=index)
ROWS = "document.querySelectorAll('.tab-content.active .data-table tbody tr').length"
check('a table opens and its grid draws rows', wait_for(ROWS + ' >= 10'), f'{js(ROWS)} rows')
check('the coloured status labels draw', js("document.querySelectorAll('.tab-content.active .cell-pill').length") > 0)
check('the app typefaces loaded (Instrument Sans, Geist Mono)',
      js("document.fonts.load('13px \"Instrument Sans\"').then(f => f.length > 0)") and js("document.fonts.load('13px \"Geist Mono\"').then(f => f.length > 0)"))
point_at('.tab-content.active .data-table tbody tr', nth=3)
time.sleep(1.5)
desktop('04-a-table-open.png')

# a real edit and the unsaved-changes bar: the interaction the app is built around (double-click, type, press Tab)
click('.tab-content.active .data-table tbody tr:nth-child(2) td[data-column=total]', times=2)
x('key', 'ctrl+a')
x('type', '--delay', '60', '123.45')
x('key', 'Tab')
time.sleep(0.8)
check('editing a cell raises the unsaved-changes bar', js("document.querySelectorAll('.tb-pending.show').length") == 1)
check('the edited value is in the cell', js("document.querySelector('.tab-content.active .data-table tbody tr:nth-child(2) td[data-column=total]').textContent.trim()") == '123.45')
desktop('05-an-unsaved-edit.png')
click('.tab-content.active [data-action=discard-changes]')
check('discarding removes the bar', wait_for("document.querySelectorAll('.tb-pending.show').length === 0"))

sys.exit(1 if failures else 0)
