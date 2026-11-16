"""The data grid fills the area and reads calmly: a gutter of row numbers, a quiet header, text in the interface face."""
import pytest

from conftest import first_family

pytestmark = pytest.mark.e2e


def open_table(pg, name):
    pg.locator('#tables-content .tree-item').filter(has=pg.locator(f'.tree-label:text-is("{name}")')).click()
    pg.wait_for_selector('.tab-content.active .data-table tbody tr')


def test_a_narrow_table_still_fills_the_whole_width(connected):
    open_table(connected, 'items')                                       # three columns
    box = connected.evaluate("""() => { const g = document.querySelector('.tab-content.active .table-data-grid'), t = g.querySelector('.data-table');
        return {table: t.getBoundingClientRect().width, area: g.clientWidth}; }""")
    assert box['table'] >= box['area'] - 2, box


def test_a_wide_table_scrolls_instead_of_squeezing(connected):
    connected.evaluate("document.querySelector('#sidebar').style.width = '260px'")
    connected.set_viewport_size({'width': 700, 'height': 800})
    open_table(connected, 'customers')                                   # six columns, narrow window
    box = connected.evaluate("""() => { const g = document.querySelector('.tab-content.active .table-data-grid'), t = g.querySelector('.data-table');
        return {table: t.getBoundingClientRect().width, area: g.clientWidth}; }""")
    assert box['table'] > box['area']                                    # wider than the area: it scrolls


def test_the_first_column_is_a_slim_gutter_of_row_numbers(connected):
    open_table(connected, 'orders')
    width = connected.evaluate("document.querySelector('.tab-content.active .data-table thead th:first-child').getBoundingClientRect().width")
    assert 40 <= width <= 60
    numbers = connected.locator('.tab-content.active .data-table tbody tr td:first-child .rowno').all_text_contents()
    assert numbers[:3] == ['1', '2', '3']


def test_row_numbers_carry_on_across_pages(connected):
    open_table(connected, 'orders')                                      # 250 rows, 100 a page
    connected.click('.tab-content.active [data-action=next-page]')
    connected.wait_for_function("document.querySelector('.tab-content.active .data-table tbody tr td:first-child .rowno')?.textContent === '101'")
    assert connected.locator('.tab-content.active .data-table tbody tr td:first-child .rowno').nth(1).text_content() == '102'


def test_the_number_becomes_a_checkbox_on_hover_and_stays_when_ticked(connected):
    open_table(connected, 'customers')
    box = '.tab-content.active .data-table tbody tr:nth-child(2) .row-checkbox'
    opacity = lambda: connected.evaluate(f"getComputedStyle(document.querySelector('{box}')).opacity")
    assert opacity() == '0'
    connected.hover('.tab-content.active .data-table tbody tr:nth-child(2)')
    connected.wait_for_function(f"getComputedStyle(document.querySelector('{box}')).opacity === '1'")
    connected.check(box)
    connected.hover('.tab-content.active .data-table tbody tr:nth-child(5)')              # pointer away: still shown, because ticked
    connected.wait_for_function("getComputedStyle(document.querySelector('.tab-content.active .data-table tbody tr:nth-child(5) .row-checkbox')).opacity === '1'")
    connected.wait_for_function("getComputedStyle(document.querySelector('.tab-content.active .data-table tbody tr:nth-child(2) .rowno')).opacity === '0'")   # the fade has finished
    assert opacity() == '1'                                                               # (reading it mid-fade would pass even when it is about to vanish)
    assert connected.evaluate("getComputedStyle(document.querySelector('.tab-content.active .data-table tbody tr:nth-child(2) .rowno')).opacity") == '0'


def test_text_is_in_the_interface_face_and_numbers_in_the_monospace(connected):
    open_table(connected, 'orders')
    face = lambda sel: connected.evaluate("s => getComputedStyle(document.querySelector(s)).fontFamily", sel)
    assert first_family(face('.tab-content.active td[data-column=status]')) == 'Instrument Sans'
    assert first_family(face('.tab-content.active td.cell-num')) == 'Geist Mono'


def test_the_header_is_a_quiet_line_and_a_hovered_row_wears_the_accent_bar(connected):
    open_table(connected, 'customers')
    head = connected.evaluate("getComputedStyle(document.querySelector('.tab-content.active .data-table thead th:nth-child(3)')).fontFamily")
    assert first_family(head) == 'Instrument Sans'
    connected.hover('.tab-content.active .data-table tbody tr:nth-child(3)')
    connected.wait_for_function("getComputedStyle(document.querySelector('.tab-content.active .data-table tbody tr:nth-child(3) td:first-child')).boxShadow.includes('inset')"
                                " && !getComputedStyle(document.querySelector('.tab-content.active .data-table tbody tr:nth-child(3) td:first-child')).boxShadow.startsWith('rgba(0, 0, 0, 0)')")


def test_columns_are_separated_by_vertical_lines(connected):
    open_table(connected, 'orders')
    edge = lambda sel: connected.evaluate("s => { const c = getComputedStyle(document.querySelector(s)); return [c.borderRightWidth, c.borderRightStyle]; }", '.tab-content.active ' + sel)
    for sel in ['thead th:nth-child(2)', 'tbody tr:nth-child(2) td:nth-child(2)', 'tbody tr:nth-child(2) td:first-child']:
        assert edge(sel) == ['1px', 'solid'], sel
    assert edge('tbody tr:nth-child(2) td:last-child')[1] == 'none'          # nothing after the last column
