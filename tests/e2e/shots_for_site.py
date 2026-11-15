"""Regenerates the screenshots on the download page (site/img). Not a test, so it is not collected by a normal run:

    python3 -m pytest tests/e2e/shots_for_site.py -p no:cacheprovider

It drives the app on its sample shop in both themes and rewrites the PNGs, so run it after the look of the app changes."""
import pytest
from test_grid_ui import open_table
from test_theme_ui import use
from test_relationship_ui import open_map
pytestmark = pytest.mark.e2e
from pathlib import Path
OUT = str(Path(__file__).resolve().parent.parent.parent / 'site' / 'img')

def settle(pg, ms=700):
    pg.mouse.move(1100, 700); pg.wait_for_timeout(ms)

def test_main_shots(connected):
    pg = connected; pg.set_viewport_size({'width': 1360, 'height': 840})
    pg.evaluate("document.getElementById('toast-stack') && document.getElementById('toast-stack').remove()")
    for theme in ['sky', 'obsidian']:
        use(pg, theme)
        pg.evaluate("document.querySelectorAll('.tab[data-tab-id]').forEach(t => {})")
        open_table(pg, 'orders')
        pg.evaluate("document.querySelectorAll('.toast, .notification').forEach(n => n.remove())")
        # two pending edits, so the floating save bar shows
        for r in (2, 4):
            cell = pg.locator(f'.tab-content.active .data-table tbody tr:nth-child({r}) td[data-column=total]')
            cell.dblclick(); pg.keyboard.press('Meta+a'); pg.keyboard.type('99.5'); pg.keyboard.press('Tab')
        pg.evaluate('document.activeElement && document.activeElement.blur()'); pg.wait_for_timeout(300)
        pg.hover('.tab-content.active .data-table tbody tr:nth-child(6)')
        pg.wait_for_timeout(900)
        pg.evaluate("document.querySelectorAll('.toast, .notification').forEach(n => n.remove())")
        pg.screenshot(path=f'{OUT}/grid-{theme}.png')
        pg.click('.tab-content.active [data-action=discard-changes]') if pg.locator('.tab-content.active [data-action=discard-changes]').count() else None
        if True:
            open_map(pg); pg.wait_for_timeout(1200); pg.evaluate("document.querySelectorAll('.toast, .notification').forEach(n => n.remove())")
            pg.screenshot(path=f'{OUT}/map-{theme}.png')
            pg.keyboard.press('Control+k'); pg.wait_for_selector('#palette, .palette', state='visible'); pg.wait_for_timeout(600)
            pg.screenshot(path=f'{OUT}/palette-{theme}.png'); pg.keyboard.press('Escape'); pg.evaluate("document.querySelectorAll('.tab .tab-close, .tab .close').forEach(()=>{})")


def test_detail_shots(connected):
    pg = connected
    for theme in ['sky', 'obsidian']:
        use(pg, theme); pg.set_viewport_size({'width': 1000, 'height': 540})
        open_table(pg, 'orders')
        pg.evaluate("document.querySelectorAll('.toast, .notification').forEach(n => n.remove())")
        pg.hover('.tab-content.active .data-table tbody tr:nth-child(3) td[data-column=customer_id]'); pg.wait_for_timeout(700)
        pg.screenshot(path=f'{OUT}/links-{theme}.png')
        for r in (2, 3):
            pg.locator(f'.tab-content.active .data-table tbody tr:nth-child({r}) td[data-column=total]').dblclick()
            pg.keyboard.press('Meta+a'); pg.keyboard.type('99.5'); pg.keyboard.press('Tab')
        pg.evaluate('document.activeElement && document.activeElement.blur()'); pg.mouse.move(900, 330); pg.wait_for_timeout(900)
        pg.evaluate("document.querySelectorAll('.toast, .notification').forEach(n => n.remove())")
        pg.screenshot(path=f'{OUT}/save-{theme}.png')
        pg.click('.tab-content.active [data-action=discard-changes]')
