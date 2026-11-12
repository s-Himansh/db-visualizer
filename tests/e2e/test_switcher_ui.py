"""Open connections: the edge handle and the panel that slides over the sidebar."""
import pytest

from conftest import add_sqlite_connection, connect, manual_dialogs

pytestmark = pytest.mark.e2e

BOXES = """() => Object.fromEntries(['#sidebar', '.main-content'].map(s => { const r = document.querySelector(s).getBoundingClientRect(); return [s, [r.left, r.width]]; }))"""


@pytest.fixture
def two(page):
    add_sqlite_connection(page, 'Alpha DB')
    connect(page, 'Alpha DB')
    page.click('#manage-connections-btn')
    page.click('#new-connection-btn-manager')
    page.select_option('select[name=type]', 'sqlite')
    page.fill('input[name=name]', 'Beta DB')
    page.fill('input[name=database]', page.demo_db)
    page.select_option('#environment-select', 'production')
    page.click('#connection-form button[type=submit]')
    page.wait_for_selector('.connection-item:has-text("Beta DB")')
    page.click('.connection-item:has-text("Beta DB") .connect-btn')
    page.wait_for_function("document.querySelector('.connection-badge.active').textContent.includes('Beta DB')")
    page.evaluate("document.querySelectorAll('.modal.active').forEach(m => m.classList.remove('active'))")
    return page


def toast_with(pg, text):
    pg.wait_for_function("t => document.querySelector('#toast-stack') && document.querySelector('#toast-stack').innerText.includes(t)", arg=text)


def active_name(pg):
    return pg.inner_text('.connection-badge.active .connection-name')


def test_the_handle_shows_one_dot_per_open_connection_and_the_top_bar_names_the_active_one(two):
    assert two.locator('#switcher-handle .switch-dot').count() == 2
    assert two.locator('#switcher-handle .switch-dot.active').count() == 1
    assert two.locator('#switcher-handle .switch-dot.env-production').count() == 1        # Beta DB is production
    assert two.locator('.connection-badges-container .connection-badge').count() == 1 and active_name(two) == 'Beta DB'
    assert not two.evaluate("document.querySelector('#switcher-panel').classList.contains('open')")


def test_the_panel_lists_the_open_ones_and_switching_does_not_move_anything(two):
    before = two.evaluate(BOXES)
    two.click('#switcher-handle')
    two.wait_for_selector('#switcher-panel.open')
    rows = two.locator('#switcher-panel .switch-name').all_inner_texts()
    assert rows == ['Alpha DB', 'Beta DB']
    assert two.locator('#switcher-panel .switch-row.active .switch-name').inner_text() == 'Beta DB'
    assert two.evaluate(BOXES) == before                                                # it floats: no layout change
    two.click('#switcher-panel .switch-row:has-text("Alpha DB") .switch-main')
    two.wait_for_function("document.querySelector('.connection-badge.active').textContent.includes('Alpha DB')")
    assert not two.evaluate("document.querySelector('#switcher-panel').classList.contains('open')")   # picking closes it
    assert two.evaluate(BOXES) == before


def test_hovering_the_handle_opens_it_and_leaving_closes_it(two):
    two.hover('#switcher-handle')
    two.wait_for_selector('#switcher-panel.open')
    two.mouse.move(900, 500)
    two.wait_for_function("!document.querySelector('#switcher-panel').classList.contains('open')")


def test_the_keyboard_switches_and_closes(two):
    two.keyboard.press('ControlOrMeta+1')
    two.wait_for_function("document.querySelector('.connection-badge.active').textContent.includes('Alpha DB')")
    two.keyboard.press('ControlOrMeta+Shift+d')
    two.wait_for_selector('#switcher-panel.open')
    assert two.evaluate("document.activeElement.closest('.switch-row') && document.activeElement.closest('.switch-row').classList.contains('active')")
    two.keyboard.press('Escape')
    two.wait_for_function("!document.querySelector('#switcher-panel').classList.contains('open')")


def test_the_x_disconnects_and_the_handle_goes_when_nothing_is_open(two):
    two.click('#switcher-handle')
    two.locator('#switcher-panel .switch-row:has-text("Beta DB")').hover()
    two.click('#switcher-panel .switch-row:has-text("Beta DB") .switch-close')
    two.wait_for_function("document.querySelectorAll('#switcher-handle .switch-dot').length === 1")
    assert active_name(two) == 'Alpha DB'                                                 # it fell back to the other one
    two.click('.connection-badge.active .connection-close')
    two.wait_for_function("document.querySelector('#switcher-handle').hidden")


def test_the_right_click_menu_opens_a_new_query_on_that_connection(two):
    two.click('#switcher-handle')
    two.locator('#switcher-panel .switch-row:has-text("Alpha DB")').click(button='right')
    two.click('.table-context-menu .context-menu-item:text-is("New query")')
    two.wait_for_function("document.querySelector('.connection-badge.active').textContent.includes('Alpha DB')")
    assert two.locator('#tabs-header .tab.active .tab-label').inner_text().lower().startswith('query')


def test_a_hostile_connection_name_stays_plain_text(page):
    name = '<img src=x onerror=window.__pwned=1>'
    add_sqlite_connection(page, name)
    connect(page, name)
    page.click('#switcher-handle')
    page.wait_for_selector('#switcher-panel.open')
    assert page.locator('#switcher-panel img').count() == 0
    assert name in page.inner_text('#switcher-panel')
    assert page.evaluate('window.__pwned') is None


def rename_from_panel(pg, row, new):
    manual_dialogs(pg)                                           # the test answers the dialog itself
    pg.click('#switcher-handle')
    pg.locator(f'#switcher-panel .switch-row:has-text("{row}")').click(button='right')
    pg.click('.table-context-menu .context-menu-item:text-is("Rename")')
    pg.wait_for_selector('.app-dialog-input')
    pg.fill('.app-dialog-input', new)
    pg.click('.app-dialog [data-answer=ok]')


def test_renaming_the_active_connection_updates_everywhere_and_is_remembered(two):
    rename_from_panel(two, 'Beta DB', 'Renamed Prod')
    toast_with(two, 'Renamed "Beta DB" to "Renamed Prod".')                         # says what changed to what
    two.wait_for_function("document.querySelector('.connection-badge.active .connection-name').textContent === 'Renamed Prod'")
    assert 'Connected to Renamed Prod' in two.inner_text('#connection-status')
    assert two.evaluate("fetch('/api/connections').then(r => r.json()).then(d => d.connections.map(c => c.name).sort())") == ['Alpha DB', 'Renamed Prod']
    two.click('#switcher-handle')
    assert two.locator('#switcher-panel .switch-name').all_inner_texts() == ['Alpha DB', 'Renamed Prod']
    assert two.evaluate("fetch('/api/connections').then(r => r.json()).then(d => d.connections.find(c => c.name === 'Renamed Prod').environment)") == 'production'   # nothing else changed


def test_renaming_another_connection_leaves_the_active_one_alone(two):
    rename_from_panel(two, 'Alpha DB', 'Alpha Two')
    toast_with(two, 'Renamed "Alpha DB" to "Alpha Two".')
    two.wait_for_function("document.querySelectorAll('#switcher-panel .switch-name').length === 2 && [...document.querySelectorAll('#switcher-panel .switch-name')].some(n => n.textContent === 'Alpha Two')")
    assert active_name(two) == 'Beta DB'


def test_a_blank_name_is_refused_and_cancel_changes_nothing(two):
    manual_dialogs(two)
    two.click('#switcher-handle')
    two.locator('#switcher-panel .switch-row:has-text("Alpha DB")').click(button='right')
    two.click('.table-context-menu .context-menu-item:text-is("Rename")')
    two.wait_for_selector('.app-dialog-input')
    two.fill('.app-dialog-input', '   ')
    two.click('.app-dialog [data-answer=ok]')
    assert 'Give the connection a name' in two.inner_text('.app-dialog-error')
    two.click('.app-dialog [data-answer=cancel]')
    two.wait_for_selector('.app-dialog', state='detached')
    assert two.evaluate("fetch('/api/connections').then(r => r.json()).then(d => d.connections.map(c => c.name).sort())") == ['Alpha DB', 'Beta DB']


def test_keeping_the_same_name_does_nothing(two):
    rename_from_panel(two, 'Alpha DB', 'Alpha DB')
    two.wait_for_selector('.app-dialog', state='detached')
    assert 'Renamed' not in two.evaluate("document.querySelector('#toast-stack') ? document.querySelector('#toast-stack').innerText : ''")
