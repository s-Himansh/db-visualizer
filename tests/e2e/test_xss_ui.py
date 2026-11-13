"""Names and values come from the database and the user. Anywhere they are shown they must be text, never markup:
the grid, schema view, map, switcher, search panel and review dialog."""
import sqlite3

import pytest

from conftest import connect, manual_dialogs

pytestmark = pytest.mark.e2e

BOOM = '<img src=x onerror="window.__xss=(window.__xss||0)+1">'
TABLE, PARENT = f'{BOOM}orders', f'{BOOM}parents'


@pytest.fixture
def hostile(page, tmp_path):
    path = str(tmp_path / 'hostile.db')
    s = sqlite3.connect(path)
    s.executescript(f'''
        create table "{PARENT.replace('"', '""')}"(id integer primary key, "{BOOM.replace('"', '""')}" text);
        create table "{TABLE.replace('"', '""')}"(id integer primary key, parent integer references "{PARENT.replace('"', '""')}"(id),
                                                  note text, "{BOOM.replace('"', '""')}" text);
    ''')
    s.execute(f'insert into "{PARENT.replace(chr(34), chr(34) * 2)}" values (1, ?)', (BOOM,))
    s.execute(f'insert into "{TABLE.replace(chr(34), chr(34) * 2)}" values (1, 1, ?, ?)', (BOOM, '<script>window.__xss=99</script>'))
    s.commit()
    s.close()
    page.click('#manage-connections-btn')
    page.click('#new-connection-btn-manager')
    page.select_option('select[name=type]', 'sqlite')
    page.fill('input[name=name]', BOOM + 'conn')
    page.fill('input[name=database]', path)
    page.click('#connection-form button[type=submit]')
    page.wait_for_selector('.connection-item')
    page.click('.connection-item .connect-btn')
    page.wait_for_selector('#tables-content .tree-item')
    page.evaluate("document.querySelectorAll('.modal.active').forEach(m => m.classList.remove('active'))")
    page.evaluate('window.__xss = 0')
    return page


def nothing_ran(page):
    page.wait_for_timeout(400)
    assert page.evaluate('window.__xss') == 0, 'hostile text ran as script'
    assert not [e for e in page.errs if 'PAGEERROR' in e] if hasattr(page, 'errs') else True
    assert page.locator('img[src="x"]').count() == 0, 'hostile text became an element'


def test_names_and_values_stay_text_in_every_view(hostile):
    page = hostile
    page.locator('#tables-content .tree-item').filter(has_text='orders').first.click()
    page.wait_for_selector('.tab-content.active .data-table tbody tr')
    nothing_ran(page)

    page.click('#open-map-btn')                                   # the map, with every column
    page.wait_for_selector('.tab-content.active .map-svg[data-ready]')
    page.check('.tab-content.active [data-map=all-columns]')
    page.wait_for_timeout(1500)
    nothing_ran(page)

    page.keyboard.press('ControlOrMeta+Shift+D')                   # the switcher
    page.wait_for_selector('#switcher-panel.open')
    nothing_ran(page)
    page.keyboard.press('Escape')

    page.keyboard.press('ControlOrMeta+Shift+F')                   # search, echoing a hostile term back
    page.fill('.palette-input', BOOM)
    page.keyboard.press('Enter')
    page.wait_for_function("() => { const l = document.querySelector('.palette-list'); return l && !l.innerText.includes('Looking for') && !l.innerText.includes('Looks in every'); }")
    assert BOOM in page.inner_text('.palette-list')                 # shown literally
    nothing_ran(page)
    page.keyboard.press('Escape')


def test_the_review_dialog_shows_hostile_values_as_text(hostile):
    page = hostile
    page.locator('#tables-content .tree-item').filter(has_text='orders').first.click()
    page.wait_for_selector('.tab-content.active .data-table tbody tr')
    cell = page.locator('.tab-content.active tr[data-row-index="0"] td[data-column=note]')
    cell.click()
    page.keyboard.press('ControlOrMeta+A')
    page.keyboard.type(BOOM)
    page.keyboard.press('Tab')
    manual_dialogs(page)
    page.click('.tab-content.active [data-action=save-changes]')
    page.wait_for_selector('.app-dialog')
    assert '<img src=x onerror' in page.inner_text('.app-dialog')    # shown literally (the dialog shortens long values)
    nothing_ran(page)
    page.click('.app-dialog button:has-text("Cancel")')
