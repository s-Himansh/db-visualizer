"""The review pass: grouped toolbars, tabs that stay reachable, a tidy connections window, an iconed palette, a tinted map."""
import pytest

pytestmark = pytest.mark.e2e


def open_table(pg, name):
    pg.locator('#tables-content .tree-item').filter(has=pg.locator(f'.tree-label:text-is("{name}")')).click()
    pg.wait_for_selector('.tab-content.active .data-table tbody tr')


def test_the_table_toolbar_groups_its_actions_and_exports_from_one_control(connected):
    open_table(connected, 'customers')
    labels = connected.locator('.tab-content.active .tb-export .seg .btn').all_inner_texts()
    assert labels == ['CSV', 'JSON', 'SQL']
    assert connected.locator('.tab-content.active .table-toolbar .btn .ico').count() >= 6
    with connected.expect_download(timeout=5000) as dl:
        connected.click('.tab-content.active [data-action=export-table-csv]')
    assert dl.value.suggested_filename.endswith('.csv')


def test_the_query_toolbar_has_the_same_export_control(connected):
    connected.click('#new-query-tab-btn')
    connected.wait_for_selector('.tab-content.active .tb-export')
    assert connected.locator('.tab-content.active .tb-export .seg .btn').all_inner_texts() == ['CSV', 'JSON']


def test_with_many_tabs_the_active_one_is_always_in_view(connected):
    for _ in range(12):
        connected.click('#new-query-tab-btn')
    connected.wait_for_function("document.querySelectorAll('.tab').length >= 13")
    connected.wait_for_timeout(300)
    inside = connected.evaluate("""() => { const bar = document.getElementById('tabs-header').getBoundingClientRect();
        const t = document.querySelector('.tab.active').getBoundingClientRect(); return t.left >= bar.left - 1 && t.right <= bar.right + 1; }""")
    assert inside
    connected.click('.tab:first-child')                              # and going back to the first scrolls it into view too
    connected.wait_for_timeout(300)
    assert connected.evaluate("""() => { const bar = document.getElementById('tabs-header').getBoundingClientRect();
        const t = document.querySelector('.tab.active').getBoundingClientRect(); return t.left >= bar.left - 1; }""")


def test_the_new_connection_button_sits_in_the_search_row(connected):
    connected.click('#manage-connections-btn')
    connected.wait_for_selector('#connections-manager-modal .conn-search')
    box = connected.evaluate("""() => { const s = document.querySelector('#connections-manager-modal .conn-search').getBoundingClientRect();
        const b = document.getElementById('new-connection-btn-manager').getBoundingClientRect();
        return {sTop: s.top, sBottom: s.bottom, bTop: b.top, bBottom: b.bottom, sRight: s.right, bRight: b.right}; }""")
    assert box['bTop'] >= box['sTop'] - 2 and box['bBottom'] <= box['sBottom'] + 2          # level with the search box
    assert box['bRight'] <= box['sRight'] + 1


def test_palette_results_carry_icons_and_connections_wear_their_colour(connected):
    connected.keyboard.press('ControlOrMeta+k')
    connected.wait_for_selector('.palette-item')
    assert connected.locator('.palette-item .palette-ic').count() == connected.locator('.palette-item').count()
    assert connected.locator('.palette-item .palette-ic .ico').count() >= 3
    connected.fill('.palette-input', 'theme: sky')
    assert connected.locator('.palette-item .palette-ic').count() >= 1
    assert connected.evaluate("getComputedStyle(document.querySelector('.palette-backdrop')).backdropFilter").startswith('blur')


def test_map_node_headers_follow_the_connections_colour(connected):
    connected.click('#open-map-btn')
    connected.wait_for_selector('.tab-content.active .map-svg[data-ready]')
    fill = lambda: connected.evaluate("getComputedStyle(document.querySelector('.tab-content.active .map-node-head')).fill")
    connected.evaluate("document.documentElement.style.transition = 'none'; document.documentElement.style.setProperty('--hue', '20')")
    a = fill()
    connected.evaluate("document.documentElement.style.setProperty('--hue', '200')")
    assert a != fill()
