"""The few animations answer something you did, never get in the way, and stop under "reduce motion"."""
import pytest

pytestmark = pytest.mark.e2e


def open_table(pg, name):
    pg.locator('#tables-content .tree-item').filter(has=pg.locator(f'.tree-label:text-is("{name}")')).click()
    pg.wait_for_selector('.tab-content.active .data-table tbody tr')


def test_a_table_shows_grey_bars_while_it_loads(connected):
    connected.route('**/api/data?*', lambda route: (connected.wait_for_timeout(700), route.continue_()))
    connected.locator('#tables-content .tree-item').filter(has=connected.locator('.tree-label:text-is("customers")')).click()
    connected.wait_for_selector('.tab-content.active .skeleton')
    assert connected.locator('.tab-content.active .skeleton-row').count() == 10
    connected.wait_for_selector('.tab-content.active .data-table tbody tr')
    assert connected.locator('.tab-content.active .skeleton').count() == 0


def test_the_first_rows_rise_in_once_then_redraws_are_still(connected):
    open_table(connected, 'customers')
    assert connected.evaluate("document.querySelector('.tab-content.active .table-data-grid').classList.contains('first-load')")
    first = connected.evaluate("getComputedStyle(document.querySelector('.tab-content.active .data-table tbody tr')).animationName")
    assert first == 'row-in'
    connected.click('.tab-content.active .data-table th[data-col="name"] .th-content')      # sort: a redraw
    connected.wait_for_function("document.querySelector('.tab-content.active .data-table th[data-sort]')")
    assert not connected.evaluate("document.querySelector('.tab-content.active .table-data-grid').classList.contains('first-load')")


def test_a_new_tab_eases_in_and_then_stops(connected):
    connected.click('#new-query-tab-btn')
    connected.wait_for_selector('.tab.tab-entering')
    connected.wait_for_selector('.tab.active:not(.tab-entering)')


def test_an_edited_cell_flashes_and_the_save_buttons_spring_in(connected):
    open_table(connected, 'customers')
    cell = connected.locator('.tab-content.active tr[data-row-index="0"] td[data-column=name]')
    cell.click()
    connected.keyboard.press('ControlOrMeta+A')
    connected.keyboard.type('Edited')
    connected.keyboard.press('Tab')
    connected.wait_for_selector('.tab-content.active td.modified')
    assert connected.evaluate("getComputedStyle(document.querySelector('.tab-content.active td.modified')).animationName") == 'cell-flash'
    assert connected.evaluate("getComputedStyle(document.querySelector('.tab-content.active [data-action=save-changes]')).animationName") == 'btn-in'


def test_the_saved_toast_draws_its_check_and_keeps_its_words(connected):
    connected.evaluate("ui.notify('Saved 2 changes.', 'success')")
    mine = '#toast-stack .notification-success:has-text("Saved 2 changes")'     # other toasts may still be on screen
    connected.wait_for_selector(f'{mine} .toast-check')
    assert connected.inner_text(mine) == 'Saved 2 changes.'
    connected.wait_for_function("getComputedStyle([...document.querySelectorAll('#toast-stack .notification-success')].find(n => n.textContent === 'Saved 2 changes.').querySelector('path')).strokeDashoffset === '0px'")
    connected.evaluate("ui.notify('Nothing was saved.', 'error')")
    connected.wait_for_selector('#toast-stack .notification-error')
    assert connected.locator('#toast-stack .notification-error .toast-check').count() == 0       # only success gets the check


def test_arriving_in_a_connection_pops_its_avatar(connected):
    assert connected.evaluate("document.getElementById('side-avatar').classList.contains('pop')")


def test_the_palette_opens_with_a_small_pop(connected):
    connected.keyboard.press('ControlOrMeta+k')
    connected.wait_for_selector('.palette')
    assert connected.evaluate("getComputedStyle(document.querySelector('.palette')).animationName") == 'palette-in'


def test_nothing_moves_when_the_system_asks_for_reduced_motion(browser, server, demo_db):
    ctx = browser.new_context(reduced_motion='reduce')
    pg = ctx.new_page()
    pg.goto(server)
    pg.wait_for_selector('#manage-connections-btn')
    for el in ('document.documentElement', 'document.body'):
        assert pg.evaluate(f"parseFloat(getComputedStyle({el}).transitionDuration) < 0.001")
    pg.evaluate("ui.notify('Saved 1 change.', 'success')")
    pg.wait_for_selector('#toast-stack .toast-check')
    assert pg.evaluate("parseFloat(getComputedStyle(document.querySelector('#toast-stack .toast-check path')).animationDuration) < 0.001")
    ctx.close()
