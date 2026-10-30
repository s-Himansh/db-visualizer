"""Column insights: the panel behind the ▾ on a column header."""
import pytest

from conftest import add_sqlite_connection, connect

pytestmark = pytest.mark.e2e


def open_table(pg, name):
    pg.locator('#tables-content .tree-item').filter(has=pg.locator(f'.tree-label:text-is("{name}")')).click()
    pg.wait_for_selector('.tab-content.active .data-table tbody tr')


def open_insight(pg, column):
    th = pg.locator(f'.tab-content.active th[data-col="{column}"]')
    th.hover()
    th.locator('.th-insight').click()
    pg.wait_for_selector('.insight .insight-facts')


def facts(pg):
    names = pg.locator('.insight-facts dt').all_inner_texts()
    values = pg.locator('.insight-facts dd').all_inner_texts()
    return dict(zip(names, values))


def test_the_arrow_appears_on_hover_and_opens_the_panel(connected):
    open_table(connected, 'customers')
    th = connected.locator('.tab-content.active th[data-col="country"]')
    assert th.locator('.th-insight').evaluate("e => getComputedStyle(e).opacity") == '0'
    th.hover()
    connected.wait_for_function("document.querySelector('.tab-content.active th[data-col=\"country\"] .th-insight').matches(':hover') || getComputedStyle(document.querySelector('.tab-content.active th[data-col=\"country\"] .th-insight')).opacity === '1'")
    connected.wait_for_function("getComputedStyle(document.querySelector('.tab-content.active th[data-col=\"country\"] .th-insight')).opacity === '1'")
    th.locator('.th-insight').click()
    connected.wait_for_selector('.insight .insight-facts')
    assert connected.inner_text('.insight-name') == 'country'


def test_text_column_facts_and_common_values(connected):
    open_table(connected, 'customers')
    open_insight(connected, 'country')
    f = facts(connected)
    assert f['Rows'] == '30' and f['Empty'] == '0 (0%)' and f['Distinct'] == '3'
    assert f['Lowest'] == 'DE' and f['Highest'] == 'US'
    rows = connected.locator('.insight-row').all_inner_texts()
    assert len(rows) == 3 and all('10' in r and '33%' in r for r in rows)
    assert connected.locator('.insight-hist').count() == 0       # not a number: no histogram


def test_empty_values_are_counted(connected):
    open_table(connected, 'customers')
    open_insight(connected, 'meta')                               # only every third customer has JSON in meta
    f = facts(connected)
    assert f['Rows'] == '30' and f['Empty'] == '20 (67%)'
    assert connected.locator('.insight-meter span').evaluate("e => e.style.width") == '33%'


def test_numeric_column_has_average_and_a_histogram(connected):
    open_table(connected, 'orders')
    open_insight(connected, 'total')
    f = facts(connected)
    assert f['Rows'] == '250' and f['Lowest'] == '1.5' and f['Highest'] == '375' and f['Average'] != '—'
    bars = connected.locator('.insight-hist span')
    assert bars.count() == 10
    counts = bars.evaluate_all("els => els.map(e => e.title)")
    assert sum(int(t.split(': ')[1].split(' ')[0].replace(',', '')) for t in counts) == 250


def test_clicking_a_common_value_filters_the_table_to_it(connected):
    open_table(connected, 'customers')
    open_insight(connected, 'country')
    connected.locator('.insight-row:has-text("US")').click()
    connected.wait_for_function("document.querySelector('#tabs-header .tab.active .tab-label').textContent.includes('country = US')")
    connected.wait_for_selector('.tab-content.active .data-table tbody tr')
    assert connected.locator('.tab-content.active tbody tr').count() == 10
    assert connected.locator('.insight').count() == 0             # the panel closes once you act on it


def test_values_are_text_never_markup(connected):
    open_table(connected, 'customers')
    open_insight(connected, 'name')                               # one customer is called "O'Brien <b>"
    assert "O'Brien <b>" in connected.inner_text('.insight-top')
    assert connected.locator('.insight b, .insight img').count() == 0


def test_escape_outside_click_and_the_x_all_close_it_and_only_one_is_open(connected):
    open_table(connected, 'customers')
    open_insight(connected, 'country')
    connected.keyboard.press('Escape')
    assert connected.locator('.insight').count() == 0
    open_insight(connected, 'country')
    connected.mouse.click(700, 500)
    assert connected.locator('.insight').count() == 0
    open_insight(connected, 'country')
    connected.click('.insight-close')
    assert connected.locator('.insight').count() == 0
    open_insight(connected, 'country')
    open_insight(connected, 'name')
    assert connected.locator('.insight').count() == 1 and connected.inner_text('.insight-name') == 'name'


def test_clicking_the_arrow_again_closes_it_and_never_sorts(connected):
    open_table(connected, 'customers')
    first = connected.locator('.tab-content.active tr[data-row-index="0"] td[data-column=id]').inner_text()
    open_insight(connected, 'country')
    connected.locator('.tab-content.active th[data-col="country"] .th-insight').click()
    assert connected.locator('.insight').count() == 0
    assert connected.locator('.tab-content.active th[data-sort]').count() == 0
    assert connected.locator('.tab-content.active tr[data-row-index="0"] td[data-column=id]').inner_text() == first


def test_a_failure_is_explained_in_the_panel(connected):
    connected.route('**/api/profile**', lambda route: route.fulfill(
        status=504, content_type='application/json',
        body='{"success": false, "error": "Stopped: reading this column took longer than 60 seconds."}'))
    open_table(connected, 'customers')
    th = connected.locator('.tab-content.active th[data-col="country"]')
    th.hover()
    th.locator('.th-insight').click()
    connected.wait_for_selector('.insight-error')
    assert 'longer than 60 seconds' in connected.inner_text('.insight-error')


def test_the_panel_stays_on_screen_for_the_last_column(connected):
    open_table(connected, 'customers')
    open_insight(connected, 'meta')
    box = connected.locator('.insight').bounding_box()
    viewport = connected.viewport_size
    assert box['x'] >= 0 and box['x'] + box['width'] <= viewport['width']
    assert box['y'] >= 0 and box['y'] + box['height'] <= viewport['height']


def test_the_arrow_is_not_offered_where_it_cannot_work(page):
    # a connection whose type is not SQL: render a table tab the way the app would and look for the button
    add_sqlite_connection(page)
    connect(page)
    assert page.evaluate("ColumnInsights.supported('sqlite') && ColumnInsights.supported('oracle')")
    assert page.evaluate("!ColumnInsights.supported('mongodb') && !ColumnInsights.supported('redis') && !ColumnInsights.supported('cassandra')")
