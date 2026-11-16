"""Drives the app's own window (Qt's web engine, started with QTWEBENGINE_REMOTE_DEBUGGING=9222) the way a person would: opens the sample
database, opens a table, and checks that the grid and the app's own fonts really drew. Screenshots of the whole desktop are taken
between steps with ImageMagick. Run by linux-desktop-check.sh; exits non-zero when something is wrong."""
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

out = Path(sys.argv[1])


def desktop(name):
    subprocess.run(['import', '-window', 'root', str(out / name)], check=True)


failures = []


def check(label, ok, detail=''):
    print(('PASS  ' if ok else 'FAIL  ') + label + (f'   {detail}' if detail else ''))
    if not ok:
        failures.append(label)


with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp('http://127.0.0.1:9222')
    page = browser.contexts[0].pages[0]
    info = page.evaluate("() => ({title: document.title, ua: navigator.userAgent, width: innerWidth, height: innerHeight})")
    print('web view:', info['ua'].split(') ')[-1], f"{info['width']}x{info['height']}")
    check('the page title is Cairn', info['title'] == 'Cairn', info['title'])
    check('it is the packaged Qt web view', 'QtWebEngine' in info['ua'])

    page.wait_for_selector('#welcome-sample', timeout=30000)
    check('the first screen offers the sample database', True)
    page.click('#welcome-sample')
    page.wait_for_selector('#tables-content .tree-item', timeout=30000)
    tables = page.locator('#tables-content .tree-label').all_text_contents()
    check('the sample database connected and lists its tables', len(tables) >= 3, ', '.join(tables[:6]))
    desktop('03-sample-database-connected.png')

    page.locator('#tables-content .tree-item').filter(has=page.locator('.tree-label:text-is("orders")')).click()
    page.wait_for_selector('.tab-content.active .data-table tbody tr', timeout=30000)
    rows = page.locator('.tab-content.active .data-table tbody tr').count()
    check('a table opens and its grid draws rows', rows >= 10, f'{rows} rows')
    pills = page.locator('.tab-content.active .cell-pill').count()
    check('the coloured status labels draw', pills > 0, f'{pills} labels')
    check('the app typefaces loaded (Instrument Sans, Geist Mono)',
          page.evaluate("document.fonts.load('13px \"Instrument Sans\"').then(f => f.length > 0)")
          and page.evaluate("document.fonts.load('13px \"Geist Mono\"').then(f => f.length > 0)"))
    page.hover('.tab-content.active .data-table tbody tr:nth-child(4)')
    page.wait_for_timeout(1500)
    desktop('04-a-table-open.png')

    # a real edit and the unsaved-changes bar, then undo: the interaction the app is built around
    page.locator('.tab-content.active .data-table tbody tr:nth-child(2) td[data-column=total]').dblclick()
    page.keyboard.press('Control+a')
    page.keyboard.type('123.45')
    page.keyboard.press('Tab')
    page.wait_for_timeout(600)
    check('editing a cell raises the unsaved-changes bar', page.locator('.tb-pending.show').count() == 1)
    page.click('.tab-content.active [data-action=discard-changes]')
    page.wait_for_timeout(600)

sys.exit(1 if failures else 0)
