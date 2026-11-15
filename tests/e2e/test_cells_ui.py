"""Grid cells that understand their data, and the floating save bar."""
import sqlite3

import pytest

pytestmark = pytest.mark.e2e


def open_table(pg, name):
    pg.locator('#tables-content .tree-item').filter(has=pg.locator(f'.tree-label:text-is("{name}")')).click()
    pg.wait_for_selector('.tab-content.active .data-table tbody tr')


def db(pg, sql, *args):
    c = sqlite3.connect(pg.demo_db)
    try:
        out = c.execute(sql, args).fetchall()
        c.commit()
        return out
    finally:
        c.close()


def edit(pg, row, column, text):
    cell = pg.locator(f'.tab-content.active tr[data-row-index="{row}"] td[data-column={column}]')
    cell.click()
    pg.keyboard.press('ControlOrMeta+A')
    pg.keyboard.type(text)
    pg.keyboard.press('Tab')


def test_a_status_column_becomes_pills_in_the_right_colours(connected):
    open_table(connected, 'orders')
    pills = connected.locator('.tab-content.active td[data-column=status] .cell-pill').evaluate_all("els => els.map(e => [e.textContent, e.className])")
    assert pills and all('cell-pill' in c for _, c in pills)
    tones = {text: cls.split('cell-pill-')[1] for text, cls in pills}
    assert tones == {'paid': 'ok', 'pending': 'warn'}


def test_ordinary_text_columns_stay_plain(connected):
    open_table(connected, 'customers')
    assert connected.locator('.tab-content.active td[data-column=name] .cell-pill, .tab-content.active td[data-column=country] .cell-pill').count() == 0


def test_a_pilled_cell_still_edits_and_saves_as_plain_text(connected):
    open_table(connected, 'orders')
    before = db(connected, 'select status from orders where id = 1')[0][0]
    edit(connected, 0, 'status', 'shipped')
    connected.click('.tab-content.active [data-action=save-changes]')
    connected.wait_for_function("document.querySelector('#toast-stack') && document.querySelector('#toast-stack').innerText.includes('Saved 1 change')")
    assert db(connected, 'select status from orders where id = 1') == [('shipped',)] and before != 'shipped'
    connected.wait_for_selector('.tab-content.active td[data-column=status] .cell-pill-info')      # and after the reload it is a pill again


def test_numbers_line_up_on_the_right(connected):
    open_table(connected, 'orders')
    assert connected.evaluate("getComputedStyle(document.querySelector('.tab-content.active td[data-column=total]')).textAlign") == 'right'
    assert connected.evaluate("getComputedStyle(document.querySelector('.tab-content.active th[data-col=total]')).textAlign") == 'right'
    assert connected.evaluate("getComputedStyle(document.querySelector('.tab-content.active td[data-column=status]')).textAlign") != 'right'


def test_query_results_get_the_same_treatment(connected):
    connected.click('#new-query-tab-btn')
    connected.wait_for_selector('.tab-content.active .CodeMirror')
    connected.evaluate("sql => document.querySelector('.tab-content.active .CodeMirror').CodeMirror.setValue(sql)", 'select id, total, status from orders limit 5')
    connected.click('.tab-content.active [data-action=execute]')
    connected.wait_for_selector('.tab-content.active .results-grid table tbody tr')
    assert connected.locator('.tab-content.active .results-grid .cell-pill').count() >= 1
    assert connected.evaluate("getComputedStyle(document.querySelector('.tab-content.active .results-grid td.cell-num')).textAlign") == 'right'


def test_true_and_false_get_pills(connected):
    html = connected.evaluate("[app.tabManager.boolPill(true), app.tabManager.boolPill(false), app.tabManager.statusPill('<b>x</b>')]")
    assert 'cell-pill-ok' in html[0] and '>true<' in html[0] and 'cell-pill-off' in html[1] and '>false<' in html[1]
    assert '<b>' not in html[2] and '&lt;b&gt;x' in html[2]                       # text only, never markup


def test_only_a_few_short_words_count_as_a_status(connected):
    kinds = connected.evaluate("""() => app.tabManager.columnKinds(['status', 'type', 'name', 'total'], [
        {status: 'a', type: 'x'.repeat(30), name: 'p', total: 1}, {status: 'b', type: 'y', name: 'q', total: 2.5}])""")
    assert kinds == {'status': 'status', 'total': 'number'}                       # a long or non-status-named column is left alone
    many = connected.evaluate("app.tabManager.columnKinds(['status'], Array.from({length: 12}, (_, i) => ({status: 's' + i})))")
    assert many == {}                                                             # too many different values: it is not a status


def test_the_save_bar_floats_up_with_a_count_and_goes_when_saved(connected):
    open_table(connected, 'customers')
    bar = '.tab-content.active .tb-pending'
    assert connected.evaluate(f"getComputedStyle(document.querySelector('{bar}')).opacity") == '0'
    edit(connected, 0, 'name', 'One')
    connected.wait_for_selector(f'{bar}.show')
    assert connected.inner_text(f'{bar} .tb-count') == '1 unsaved change'
    edit(connected, 1, 'name', 'Two')
    connected.wait_for_function("document.querySelector('.tab-content.active .tb-count').textContent === '2 unsaved changes'")
    connected.wait_for_timeout(700)                                               # let the spring settle
    box = connected.evaluate(f"""() => {{ const b = document.querySelector('{bar}').getBoundingClientRect(), c = document.querySelector('.tab-content.active .table-data-container').getBoundingClientRect();
        return {{centre: Math.abs((b.left + b.right) / 2 - (c.left + c.right) / 2), inside: b.bottom <= c.bottom + 1 && b.top >= c.top}}; }}""")
    assert box['centre'] < 3 and box['inside']                                    # bottom centre of the table
    connected.click('.tab-content.active [data-action=save-changes]')
    connected.wait_for_function("document.querySelector('.tab-content.active .tb-pending:not(.show)')")
    assert connected.evaluate(f"getComputedStyle(document.querySelector('{bar}')).pointerEvents") == 'none'


def test_an_edited_status_changes_pill_colour_and_undo_puts_it_back(connected):
    open_table(connected, 'orders')
    tone = lambda: connected.evaluate("document.querySelector('.tab-content.active tr[data-row-index=\"0\"] td[data-column=status] .cell-pill').className")
    assert 'cell-pill-warn' in tone()                                              # pending
    edit(connected, 0, 'status', 'refunded')
    assert 'cell-pill-bad' in tone()                                               # the pill follows the new word
    connected.click('.tab-content.active [data-action=undo-edit]')
    assert 'cell-pill-warn' in tone() and connected.inner_text('.tab-content.active tr[data-row-index="0"] td[data-column=status]') == 'pending'
