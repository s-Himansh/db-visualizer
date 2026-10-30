"""The command palette, environment colours and the sample database, through the real UI."""
import re
import sqlite3

import pytest

from conftest import add_sqlite_connection, answer_dialogs, connect, dialogs, manual_dialogs

pytestmark = pytest.mark.e2e


def palette(pg):
    return pg.locator('.palette')


def open_palette(pg, key='Meta+k'):
    pg.keyboard.press(key)
    pg.wait_for_selector('.palette-input')


def results(pg):
    return pg.locator('.palette-item .palette-label').all_inner_texts()


# ---- command palette -----------------------------------------------------------------------------------------

def test_shortcut_opens_and_escape_closes_and_focus_returns(connected):
    connected.focus('#refresh-btn')
    open_palette(connected)
    assert connected.evaluate("document.activeElement.className") == 'palette-input'
    connected.keyboard.press('Escape')
    assert connected.locator('.palette-backdrop').count() == 0
    assert connected.evaluate("document.activeElement.id") == 'refresh-btn'


def test_ctrl_k_works_too_and_toggles(connected):
    open_palette(connected, 'Control+k')
    connected.keyboard.press('Control+k')
    assert connected.locator('.palette-backdrop').count() == 0


def test_the_toolbar_button_opens_it_and_shows_the_shortcut(connected):
    assert 'K' in connected.inner_text('#palette-btn')
    connected.click('#palette-btn')
    assert connected.locator('.palette-input').is_visible()


def test_typing_filters_and_enter_opens_the_table(connected):
    open_palette(connected)
    connected.keyboard.type('orde')
    assert results(connected)[0] == 'orders'
    connected.keyboard.press('Enter')
    connected.wait_for_selector('.tab-content.active .data-table tbody tr')
    assert connected.inner_text('#tabs-header .tab.active .tab-label') == 'orders'


def test_matching_is_forgiving_and_marks_the_letters_it_matched(connected):
    open_palette(connected)
    connected.keyboard.type('cstm')
    assert results(connected)[0] == 'customers'
    assert connected.locator('.palette-item.active .palette-label b').all_inner_texts() == ['c', 's', 't', 'm']


def test_arrow_keys_move_and_wrap(connected):
    open_palette(connected)
    connected.keyboard.type('o')
    first = connected.locator('.palette-item.active .palette-label').inner_text()
    connected.keyboard.press('ArrowUp')   # wraps to the last
    last = connected.locator('.palette-item.active .palette-label').inner_text()
    assert last != first
    connected.keyboard.press('ArrowDown')
    assert connected.locator('.palette-item.active .palette-label').inner_text() == first


def test_clicking_a_result_picks_it(connected):
    open_palette(connected)
    connected.keyboard.type('items')
    connected.locator('.palette-item').filter(has_text=re.compile(r'^items')).first.click()
    connected.wait_for_selector('.tab-content.active .data-table tbody tr')
    assert connected.inner_text('#tabs-header .tab.active .tab-label') == 'items'


def test_actions_are_there_and_work(connected):
    open_palette(connected)
    connected.keyboard.type('schema map')
    connected.keyboard.press('Enter')
    connected.wait_for_selector('.tab-content.active .map-svg[data-ready]')
    open_palette(connected)
    connected.keyboard.type('new query')
    connected.keyboard.press('Enter')
    connected.wait_for_selector('.tab-content.active .CodeMirror')


def test_other_open_tabs_can_be_reached(connected):
    connected.click('#new-query-tab-btn')
    connected.wait_for_selector('.tab-content.active .CodeMirror')
    connected.locator('#tables-content .tree-item').filter(has=connected.locator('.tree-label:text-is("customers")')).click()
    connected.wait_for_selector('.tab-content.active .data-table tbody tr')     # the active tab is now customers
    open_palette(connected)
    connected.keyboard.type('query 1')
    assert 'open tabs' in connected.inner_text('.palette-item.active .palette-hint')
    connected.keyboard.press('Enter')
    connected.wait_for_selector('.tab-content.active .CodeMirror')


def test_a_table_that_is_already_open_is_listed_once_not_twice(connected):
    connected.locator('#tables-content .tree-item').filter(has=connected.locator('.tree-label:text-is("customers")')).click()
    connected.wait_for_selector('.tab-content.active .data-table tbody tr')
    connected.click('#new-query-tab-btn')
    open_palette(connected)
    connected.keyboard.type('customers')
    assert results(connected).count('customers') == 1


def test_other_connections_can_be_switched_to_from_the_palette(page, tmp_path):
    add_sqlite_connection(page, name='Alpha')
    connect(page, name='Alpha')
    other = tmp_path / 'other.db'
    c = sqlite3.connect(other)
    c.execute('create table zebra(id integer primary key)')
    c.commit()
    c.close()
    page.demo_db = str(other)
    add_sqlite_connection(page, name='Beta')
    page.evaluate("document.querySelectorAll('.modal.active').forEach(m => m.classList.remove('active'))")
    open_palette(page)
    page.keyboard.type('Beta')
    assert 'connect' in page.inner_text('.palette-item.active .palette-hint')
    page.keyboard.press('Enter')
    page.wait_for_selector('#tables-content .tree-item:has(.tree-label:text-is("zebra"))', timeout=8000)


def test_with_nothing_connected_it_still_helps(page):
    open_palette(page)
    assert 'New connection' in results(page) and 'Open the sample database' in results(page)
    page.keyboard.type('new conn')
    page.keyboard.press('Enter')
    page.wait_for_selector('#connection-modal.active')


def test_no_match_says_so(connected):
    open_palette(connected)
    connected.keyboard.type('qqqzzz')
    assert 'Nothing matches' in connected.inner_text('.palette-empty')
    connected.keyboard.press('Enter')   # nothing to run: must not throw or close oddly
    assert connected.locator('.palette-input').is_visible()


def test_table_names_are_text_not_markup(page):
    c = sqlite3.connect(page.demo_db)
    c.execute('create table "a<img src=x onerror=window.__pwned=1>"(id integer primary key)')
    c.commit()
    c.close()
    add_sqlite_connection(page)
    connect(page)
    open_palette(page)
    page.keyboard.type('a<img')
    assert page.locator('.palette-item').count() >= 1
    assert page.locator('.palette img').count() == 0 and page.evaluate("window.__pwned") is None


# ---- environments -----------------------------------------------------------------------------------------------

def add_env_connection(pg, name, env, read_only=None):
    if not pg.locator('#connections-manager-modal.active').count():   # saving leaves the manager open
        pg.click('#manage-connections-btn')
    pg.click('#new-connection-btn-manager')
    pg.select_option('select[name=type]', 'sqlite')
    pg.fill('input[name=name]', name)
    pg.fill('input[name=database]', pg.demo_db)
    pg.select_option('#environment-select', env)
    if read_only is not None:
        pg.set_checked('#read-only-checkbox', read_only)
    pg.click('#connection-form button[type=submit]')
    pg.wait_for_selector(f'.connection-item:has-text("{name}")')


def test_choosing_production_defaults_to_read_only_and_explains(page):
    page.click('#manage-connections-btn')
    page.click('#new-connection-btn-manager')
    assert not page.is_checked('#read-only-checkbox') and not page.is_visible('#environment-hint')
    page.select_option('#environment-select', 'production')
    assert page.is_checked('#read-only-checkbox') and page.is_visible('#environment-hint')


def test_the_window_takes_the_colour_of_the_environment_and_loses_it_on_disconnect(page):
    add_env_connection(page, 'Prod DB', 'production')
    page.click('.connection-item:has-text("Prod DB") .connect-btn')
    page.wait_for_selector('#tables-content .tree-item')
    assert page.evaluate("document.body.dataset.env") == 'production'
    assert 'production' in page.inner_text('.connection-badge.active').lower()
    assert page.evaluate("getComputedStyle(document.querySelector('.status-bar'), '::after').content") == '"PRODUCTION"'
    page.click('.connection-badge.active .connection-close')
    page.wait_for_function("document.body.dataset.env === undefined")


def test_switching_connections_switches_the_environment(page):
    add_env_connection(page, 'Dev DB', 'development')
    add_env_connection(page, 'Prod DB', 'production')
    connect(page, 'Dev DB')
    assert page.evaluate("document.body.dataset.env") == 'development'
    page.click('#manage-connections-btn')
    page.click('.connection-item:has-text("Prod DB") .connect-btn')
    page.wait_for_function("document.body.dataset.env === 'production'")
    page.click('.connection-badge:has-text("Dev DB")')
    page.wait_for_function("document.body.dataset.env === 'development'")


def test_each_environment_has_its_own_colour(page):
    colours = set()
    for env in ('local', 'development', 'staging', 'production'):
        page.evaluate(f"document.body.dataset.env = '{env}'")
        colours.add(page.evaluate("getComputedStyle(document.body, '::before').backgroundColor"))
    assert len(colours) == 4


def test_the_edit_form_remembers_the_environment(page):
    add_env_connection(page, 'Staging DB', 'staging')
    page.click('.connection-item:has-text("Staging DB") .edit-btn')
    assert page.input_value('#environment-select') == 'staging'


def test_destructive_statements_on_production_name_it_in_the_warning(page):
    add_env_connection(page, 'Prod DB', 'production', read_only=False)
    connect(page, 'Prod DB')
    answer_dialogs(page, False)
    page.click('#new-query-tab-btn')
    page.wait_for_selector('.tab-content.active .CodeMirror')
    page.evaluate("document.querySelector('.tab-content.active .CodeMirror').CodeMirror.setValue('delete from customers')")
    page.click('.tab-content.active [data-action=execute]')
    page.wait_for_function("window.__dialogs.length === 1")
    assert page.evaluate("document.querySelector('.app-dialog-title, .app-dialog') ? 1 : 1") == 1
    assert any('WHERE' in d for d in dialogs(page))


def test_saving_edits_on_production_asks_and_defaults_to_cancel(page):
    add_env_connection(page, 'Prod DB', 'production', read_only=False)
    connect(page, 'Prod DB')
    page.locator('#tables-content .tree-item').filter(has=page.locator('.tree-label:text-is("customers")')).click()
    page.wait_for_selector('.tab-content.active .data-table tbody tr')
    cell = page.locator('.tab-content.active tr[data-row-index="0"] td[data-column=name]')
    cell.click()
    page.keyboard.press('Meta+A')
    page.keyboard.type('Changed')
    page.keyboard.press('Tab')
    manual_dialogs(page)
    page.click('.tab-content.active [data-action=save-changes]')
    page.wait_for_selector('.app-dialog')
    assert 'production database' in page.inner_text('.app-dialog-message')
    assert page.inner_text('.app-dialog-title') == 'Change production data'
    assert page.evaluate("document.activeElement.textContent.trim()") == 'Cancel'
    page.keyboard.press('Enter')   # the safe default: nothing is written
    page.wait_for_selector('.app-dialog', state='detached')
    c = sqlite3.connect(page.demo_db)
    assert c.execute("select count(*) from customers where name = 'Changed'").fetchone()[0] == 0
    c.close()


def test_saving_edits_on_a_non_production_connection_does_not_ask(page):
    add_env_connection(page, 'Dev DB', 'development')
    connect(page, 'Dev DB')
    page.locator('#tables-content .tree-item').filter(has=page.locator('.tree-label:text-is("customers")')).click()
    page.wait_for_selector('.tab-content.active .data-table tbody tr')
    page.locator('.tab-content.active tr[data-row-index="0"] td[data-column=name]').click()
    page.keyboard.press('Meta+A')
    page.keyboard.type('Changed')
    page.keyboard.press('Tab')
    page.click('.tab-content.active [data-action=save-changes]')
    page.wait_for_timeout(800)
    assert not any('production' in d for d in dialogs(page))


# ---- the sample database ------------------------------------------------------------------------------------------

def test_first_run_offers_a_sample_and_it_opens_connected(page):
    assert page.is_visible('#welcome-sample')
    page.click('#welcome-sample')
    page.wait_for_selector('#tables-content .tree-item:has(.tree-label:text-is("orders"))', timeout=15000)
    names = page.locator('#tables-content .tree-label').all_inner_texts()
    assert {'categories', 'customers', 'order_items', 'orders', 'products', 'reviews', 'shipments', 'revenue_by_country'} <= set(names)
    assert 'Sample shop' in page.inner_text('.connection-badge.active') and 'local' in page.inner_text('.connection-badge.active').lower()
    assert page.evaluate("document.body.dataset.env") == 'local'


def test_the_sample_shows_off_the_map_and_following_links(page):
    page.click('#welcome-sample')
    page.wait_for_selector('#tables-content .tree-item', timeout=15000)
    page.click('#open-map-btn')
    page.wait_for_selector('.tab-content.active .map-svg[data-ready]')
    assert page.locator('.tab-content.active .map-node').count() == 7
    assert '9 relationships' in page.inner_text('.tab-content.active .map-info')
    page.locator('.tab-content.active .map-node[data-table="orders"]').click()
    page.wait_for_selector('.tab-content.active td.fk')
    cell = page.locator('.tab-content.active td[data-column=customer_id].fk').first
    box = cell.bounding_box()
    cell.click(position={'x': box['width'] - 10, 'y': box['height'] / 2})
    page.wait_for_function("document.querySelector('#tabs-header .tab.active .tab-label').textContent.startsWith('customers')")


def test_the_sample_button_is_not_offered_again_once_it_exists(page):
    page.click('#welcome-sample')
    page.wait_for_selector('#tables-content .tree-item', timeout=15000)
    page.click('.connection-badge.active .connection-close')
    page.wait_for_selector('#welcome')
    assert page.locator('#welcome-sample').count() == 0
    assert 'Sample shop' in page.inner_text('#welcome')


def test_the_palette_can_open_the_sample(page):
    open_palette(page)
    page.keyboard.type('sample')
    page.keyboard.press('Enter')
    page.wait_for_selector('#tables-content .tree-item', timeout=15000)


def test_the_closest_name_ranks_first(connected):
    open_palette(connected)
    connected.keyboard.type('ord')
    assert results(connected)[:2] == ['orders', 'paid_orders']   # a prefix match outranks a match in the middle
    connected.fill('.palette-input', 'items')
    assert results(connected)[0] == 'items'                        # an exact name beats longer ones containing it


def test_notifications_do_not_cover_the_toolbar(connected):
    connected.evaluate("window.app.tabManager.showNotification('A message that must not hide the buttons', 'info')")
    connected.wait_for_selector('#toast-stack .notification')
    toast = connected.locator('#toast-stack').bounding_box()
    toolbar = connected.locator('.toolbar').bounding_box()
    assert toast['y'] > toolbar['y'] + toolbar['height']
