import sqlite3

import pytest

from conftest import add_sqlite_connection, answer_dialogs, connect, dialogs, manual_dialogs

pytestmark = pytest.mark.e2e


def db_rows(pg, sql, *args):
    c = sqlite3.connect(pg.demo_db)
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


def open_table(pg, name, action='View Data'):
    item = pg.locator('#tables-content .tree-item').filter(has=pg.locator(f'.tree-label:text-is("{name}")'))
    if action == 'View Data':
        item.click()
        pg.wait_for_selector('.tab-content.active .data-table tbody tr')
    else:
        item.click(button='right')
        pg.click(f'.table-context-menu >> text="{action}"')


def grid_rows(pg):
    return pg.locator('.tab-content.active .data-table tbody tr').count()


def active_tab_id(pg):
    return pg.locator('.tab-content.active').first.get_attribute('data-content-for')


def run_query(pg, sql, wait='.tab-content.active .results-grid table, .tab-content.active .results-grid .error-message'):
    pg.click('#new-query-tab-btn')
    pg.wait_for_selector('.tab-content.active .CodeMirror')
    pg.evaluate("sql => document.querySelector('.tab-content.active .CodeMirror').CodeMirror.setValue(sql)", sql)
    pg.click('.tab-content.active [data-action=execute]')
    pg.wait_for_selector(wait)


# ---- connections -----------------------------------------------------------

def test_first_run_shows_guidance(page):
    text = page.inner_text('#main-content') + page.inner_text('#tables-content')
    assert 'connection' in text.lower()


def test_add_test_connect_and_browse(page):
    page.click('#manage-connections-btn')
    page.click('#new-connection-btn-manager')
    page.select_option('select[name=type]', 'sqlite')
    page.fill('input[name=name]', 'Demo shop')
    page.fill('input[name=database]', page.demo_db)
    page.click('#test-connection-btn')
    page.wait_for_selector('text=Connection successful')
    page.click('#connection-form button[type=submit]')
    page.wait_for_selector('.connection-item:has-text("Demo shop")')
    connect(page)
    names = page.locator('#tables-content .tree-label').all_inner_texts()
    assert names == ['customers', 'items', 'orders', 'paid_orders', 'reviews']
    assert page.errors == []


def test_connecting_closes_manager(page):
    add_sqlite_connection(page)
    page.click('.connection-item:has-text("Demo shop") .connect-btn')
    page.wait_for_selector('#tables-content .tree-item')
    assert page.locator('#connections-manager-modal.active').count() == 0


def test_escape_closes_modal(page):
    page.click('#manage-connections-btn')
    page.wait_for_selector('#connections-manager-modal.active')
    page.keyboard.press('Escape')
    assert page.locator('#connections-manager-modal.active').count() == 0


def test_edit_connection_keeps_password_and_prefills(page):
    page.click('#manage-connections-btn')
    page.click('#new-connection-btn-manager')
    page.select_option('select[name=type]', 'mysql')
    page.fill('input[name=name]', 'pw test')
    page.fill('input[name=password]', 'hunter2')
    page.click('#connection-form button[type=submit]')
    page.click('.connection-item:has-text("pw test") .edit-btn')
    assert page.input_value('input[name=name]') == 'pw test'
    page.fill('input[name=name]', 'pw renamed')
    page.click('#connection-form button[type=submit]')
    page.wait_for_selector('.connection-item:has-text("pw renamed")')
    assert page.locator('.connection-item:has-text("pw test")').count() == 0  # edited, not duplicated


def test_connection_name_is_escaped(page):
    add_sqlite_connection(page, name='<img src=x onerror=alert(1)>')
    assert page.locator('.connection-item img').count() == 0
    assert dialogs(page) == []


def test_failed_connect_reports_error(page):
    page.click('#manage-connections-btn')
    page.click('#new-connection-btn-manager')
    page.select_option('select[name=type]', 'sqlite')
    page.fill('input[name=name]', 'broken')
    page.fill('input[name=database]', '/nonexistent/dir/x.db')
    page.click('#connection-form button[type=submit]')
    page.click('.connection-item:has-text("broken") .connect-btn')
    page.wait_for_timeout(800)
    assert page.locator('.connection-item:has-text("broken") .connect-btn').inner_text().strip() == 'Connect'


# ---- table browsing -----------------------------------------------------------

def test_open_table_data_and_row_count(connected):
    open_table(connected, 'customers')
    assert grid_rows(connected) == 30
    assert '30 total rows' in connected.inner_text('.tab-content.active .results-info')


def test_single_click_opens_data_directly(connected):
    connected.click('#tables-content .tree-item:has-text("customers")')
    connected.wait_for_selector('.tab-content.active .data-table tbody tr', timeout=3000)


def test_dblclick_opens_data(connected):
    connected.dblclick('#tables-content .tree-item:has-text("customers")')
    connected.wait_for_selector('.tab-content.active .data-table tbody tr', timeout=3000)
    assert connected.locator('#tabs-header .tab').count() <= 2


def test_pagination(connected):
    open_table(connected, 'orders')
    assert grid_rows(connected) == 100
    connected.click('.tab-content.active [data-action=next-page]')
    connected.wait_for_function("document.querySelector('.tab-content.active [id^=page-info]').innerText.includes('Page 2')")
    connected.click('.tab-content.active [data-action=next-page]')
    connected.wait_for_function("document.querySelector('.tab-content.active [id^=page-info]').innerText.includes('Page 3')")
    assert grid_rows(connected) == 50
    connected.click('.tab-content.active [data-action=prev-page]')
    connected.wait_for_function("document.querySelector('.tab-content.active [id^=page-info]').innerText.includes('Page 2')")


def test_search_all_columns_and_clear(connected):
    open_table(connected, 'customers')
    connected.fill('.tab-content.active [id^=table-search-]:not(select)', 'liam')
    connected.click('.tab-content.active [data-action=search-table]')
    connected.wait_for_function("document.querySelectorAll('.tab-content.active .data-table tbody tr').length == 6")
    connected.click('.tab-content.active [data-action=clear-search]')
    connected.wait_for_function("document.querySelectorAll('.tab-content.active .data-table tbody tr').length == 30")


def test_search_with_no_match_says_so(connected):
    open_table(connected, 'customers')
    connected.fill('.tab-content.active [id^=table-search-]:not(select)', 'zzzzqq')
    connected.press('.tab-content.active [id^=table-search-]:not(select)', 'Enter')
    connected.wait_for_timeout(600)
    assert 'no' in connected.inner_text('.tab-content.active .table-data-grid').lower()


def test_sort_by_clicking_header(connected):
    open_table(connected, 'customers')
    connected.click('.tab-content.active th:has-text("name") .th-content')
    connected.wait_for_timeout(600)
    first = connected.locator('.tab-content.active td[data-column=name]').first.inner_text()
    assert first == 'Ava Chen'
    connected.click('.tab-content.active th:has-text("name") .th-content')
    connected.wait_for_timeout(600)
    assert connected.locator('.tab-content.active td[data-column=name]').first.inner_text() == "O'Brien <b>"


def test_values_are_escaped_and_empty_string_is_not_null(connected):
    open_table(connected, 'customers')
    assert connected.locator('.tab-content.active .data-table b').count() == 0
    cells = connected.locator('.tab-content.active tr[data-row-index="1"] td[data-column=notes]')  # id=2, notes=''
    assert cells.inner_text().strip() != 'NULL'
    assert connected.locator('.tab-content.active tr[data-row-index="2"] td[data-column=notes]').inner_text().strip() == 'NULL'


def test_select_all_checkbox(connected):
    open_table(connected, 'customers')
    connected.check('.tab-content.active thead input[type=checkbox]')
    assert connected.locator('.tab-content.active .row-checkbox:checked').count() == 30


def test_json_cell_opens_viewer(connected):
    open_table(connected, 'customers')
    connected.locator('.tab-content.active .json-cell').first.click()
    connected.wait_for_selector('#json-editor-modal.active', timeout=3000)


def test_edit_cell_and_save_persists(connected):
    open_table(connected, 'customers')
    cell = connected.locator('.tab-content.active tr[data-row-index="0"] td[data-column=name]')
    cell.click()
    connected.keyboard.press('Meta+A')
    connected.keyboard.type('Renamed Person')
    connected.keyboard.press('Tab')  # blur the cell
    connected.click('.tab-content.active [data-action=save-changes]')
    connected.wait_for_timeout(800)
    assert db_rows(connected, 'select name from customers where id=1') == [('Renamed Person',)]


def test_discard_changes(connected):
    open_table(connected, 'customers')
    cell = connected.locator('.tab-content.active tr[data-row-index="0"] td[data-column=name]')
    cell.click()
    connected.keyboard.press('Meta+A')
    connected.keyboard.type('Temp')
    connected.keyboard.press('Tab')
    connected.click('.tab-content.active [data-action=discard-changes]')
    connected.wait_for_timeout(500)
    assert connected.locator('.tab-content.active tr[data-row-index="0"] td[data-column=name]').inner_text() != 'Temp'
    assert db_rows(connected, 'select name from customers where id=1')[0][0] != 'Temp'


def test_delete_selected_row(connected):
    open_table(connected, 'customers')
    connected.check('.tab-content.active tr[data-row-index="0"] .row-checkbox')
    connected.click('.tab-content.active [data-action=delete-row]')
    connected.wait_for_timeout(800)
    assert db_rows(connected, 'select count(*) from customers') == [(29,)]


def test_add_row_and_save(connected):
    open_table(connected, 'customers')
    connected.click('.tab-content.active [data-action=add-row]')
    new = connected.locator('.tab-content.active tbody tr').first
    new.locator('td[data-column=name]').click()
    connected.keyboard.type('Zed New')
    connected.keyboard.press('Tab')
    connected.click('.tab-content.active [data-action=save-changes]')
    connected.wait_for_timeout(900)
    assert db_rows(connected, "select count(*) from customers where name='Zed New'") == [(1,)]


def test_export_table_csv_and_json(connected):
    open_table(connected, 'customers')
    for fmt, ext in (('csv', '.csv'), ('json', '.json')):
        with connected.expect_download(timeout=5000) as dl:
            connected.click(f'.tab-content.active [data-action=export-table-{fmt}]')
        assert dl.value.suggested_filename.endswith(ext)


def test_schema_view_lists_columns_and_indexes(connected):
    open_table(connected, 'orders', action='View Schema')
    connected.wait_for_selector('.tab-content.active table')
    text = connected.inner_text('.tab-content.active')
    assert 'customer_id' in text and 'idx_orders_customer' in text


def test_views_are_marked_and_openable(connected):
    open_table(connected, 'paid_orders')
    assert grid_rows(connected) == 100


# ---- query editor -----------------------------------------------------------------

def test_run_query_shows_rows_and_timing(connected):
    run_query(connected, 'select id, name from customers order by id limit 5')
    assert connected.locator('.tab-content.active .results-grid tbody tr').count() == 5
    assert '5 row' in connected.inner_text('.tab-content.active .results-info')


def test_query_error_is_readable(connected):
    run_query(connected, 'select * from nope')
    assert 'nope' in connected.inner_text('.tab-content.active .results-grid')


def test_cmd_enter_runs_query(connected):
    connected.click('#new-query-tab-btn')
    connected.wait_for_selector('.tab-content.active .CodeMirror')
    connected.evaluate("document.querySelector('.tab-content.active .CodeMirror').CodeMirror.setValue('select 1 as one')")
    connected.click('.tab-content.active .CodeMirror')
    connected.keyboard.press('Meta+Enter')
    connected.wait_for_selector('.tab-content.active .results-grid table')


def test_query_history_and_export(connected):
    run_query(connected, 'select 42 as answer')
    connected.click('.tab-content.active [data-action=history]')
    connected.wait_for_selector('text=select 42 as answer')
    connected.keyboard.press('Escape')
    with connected.expect_download(timeout=5000) as dl:
        connected.click('.tab-content.active [data-action=export-csv]')
    assert dl.value.suggested_filename.endswith('.csv')


def test_write_query_reports_affected_rows(connected):
    run_query(connected, "update customers set country='XX' where id=1", wait='.tab-content.active .results-info:has-text("Completed")')
    assert db_rows(connected, 'select country from customers where id=1') == [('XX',)]


def test_no_console_errors_during_session(connected):
    open_table(connected, 'customers')
    run_query(connected, 'select 1')
    assert connected.errors == []


# ---- session ------------------------------------------------------------------------

def test_disconnect_clears_tree(connected):
    connected.click('#manage-connections-btn')
    connected.click('.connection-item:has-text("Demo shop") .connect-btn')
    connected.wait_for_timeout(600)
    assert connected.locator('#tables-content .tree-item').count() == 0


def test_layout_fits_small_window(connected):
    connected.set_viewport_size({'width': 1000, 'height': 600})
    open_table(connected, 'customers')
    overflow = connected.evaluate("document.documentElement.scrollWidth > window.innerWidth")
    assert not overflow


def test_sort_with_unsaved_changes_asks_first(connected):
    open_table(connected, 'customers')
    connected.click('.tab-content.active [data-action=add-row]')
    answer_dialogs(connected, False)
    connected.click('.tab-content.active th:has-text("name") .th-content')
    connected.wait_for_timeout(300)
    assert any('unsaved' in d for d in dialogs(connected))
    assert connected.locator('.tab-content.active tr.new-row').count() == 1  # nothing was discarded


# ---- safety rails -------------------------------------------------------------------

def test_read_only_connection_hides_editing_and_blocks_writes(page):
    add_sqlite_connection(page, read_only=True)
    assert 'read-only' in page.inner_text('.connection-item:has-text("Demo shop")')
    connect(page)
    open_table(page, 'customers')
    for action in ('add-row', 'delete-row', 'save-changes'):
        assert not page.locator(f'.tab-content.active [data-action={action}]').is_visible()
    assert page.locator('.tab-content.active td[contenteditable="true"]').count() == 0
    run_query(page, 'delete from customers where id = 1')
    assert 'read-only' in page.inner_text('.tab-content.active .results-grid')
    assert db_rows(page, 'select count(*) from customers') == [(30,)]


def test_read_only_can_still_run_selects(page):
    add_sqlite_connection(page, read_only=True)
    connect(page)
    run_query(page, 'select id from customers limit 3')
    assert page.locator('.tab-content.active .results-grid tbody tr').count() == 3


def test_edit_form_remembers_read_only(page):
    add_sqlite_connection(page, read_only=True)
    page.click('.connection-item:has-text("Demo shop") .edit-btn')
    assert page.is_checked('#read-only-checkbox')


def test_delete_without_where_asks_and_cancel_runs_nothing(page):
    add_sqlite_connection(page)
    connect(page)
    answer_dialogs(page, False)
    run_query(page, 'delete from customers', wait='.tab-content.active .results-info:has-text("Nothing was run")')
    assert any('WHERE' in d for d in dialogs(page))
    assert db_rows(page, 'select count(*) from customers') == [(30,)]


def test_delete_without_where_runs_after_confirming(page):
    add_sqlite_connection(page)
    connect(page)
    run_query(page, 'delete from customers', wait='.tab-content.active .results-info:has-text("Completed")')
    assert any('WHERE' in d for d in dialogs(page))
    assert db_rows(page, 'select count(*) from customers') == [(0,)]


def test_scoped_delete_does_not_ask(page):
    add_sqlite_connection(page)
    connect(page)
    run_query(page, 'delete from customers where id = 1', wait='.tab-content.active .results-info:has-text("Completed")')
    assert dialogs(page) == []
    assert db_rows(page, 'select count(*) from customers') == [(29,)]


# ---- long-running queries ------------------------------------------------------------

ENDLESS = 'WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c) SELECT count(*) FROM c'


def test_run_button_becomes_cancel_and_stops_a_runaway_query(connected):
    connected.click('#new-query-tab-btn')
    connected.wait_for_selector('.tab-content.active .CodeMirror')
    connected.evaluate("sql => document.querySelector('.tab-content.active .CodeMirror').CodeMirror.setValue(sql)", ENDLESS)
    run = connected.locator('.tab-content.active [data-action=execute]')
    run.click()
    connected.wait_for_function("document.querySelector('.tab-content.active [data-action=execute]').textContent.trim() === 'Cancel'")
    run.click()
    connected.wait_for_selector('.tab-content.active .results-grid:has-text("Query cancelled")')
    connected.wait_for_function("document.querySelector('.tab-content.active [data-action=execute]').textContent.trim() === 'Run'")
    connected.evaluate("document.querySelector('.tab-content.active .CodeMirror').CodeMirror.setValue('select 1 as ok')")
    run.click()
    connected.wait_for_selector('.tab-content.active .results-grid table')


def test_huge_result_is_capped_with_a_notice(connected):
    run_query(connected, 'WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c WHERE x < 10500) SELECT x FROM c')
    connected.wait_for_function("document.querySelector('.tab-content.active .results-info').textContent.includes('Only the first')", timeout=30000)
    assert '10,000' in connected.inner_text('.tab-content.active .results-info')


def test_with_queries_show_their_rows(connected):
    run_query(connected, 'WITH x AS (SELECT id FROM customers LIMIT 4) SELECT * FROM x')
    assert connected.locator('.tab-content.active .results-grid tbody tr').count() == 4


# ---- autocomplete schema loading ---------------------------------------------------------

def _sql_requests(pg):
    seen = []
    pg.on('request', lambda r: seen.append(r.url) if '/api/schema' in r.url or '/api/columns' in r.url else None)
    return seen


def _hint_tables(pg):
    return pg.evaluate("""() => {
        const tab = window.app.tabManager.tabs.get(window.app.tabManager.activeTabId);
        return tab.editor.getOption('hintOptions').tables;
    }""")


def test_small_schema_loads_all_columns_in_one_request(page):
    add_sqlite_connection(page)
    seen = _sql_requests(page)
    connect(page)  # connecting opens the first query tab, which loads the autocomplete schema
    page.wait_for_function("""() => {
        const tab = window.app.tabManager.tabs.get(window.app.tabManager.activeTabId);
        const t = tab.editor && tab.editor.getOption('hintOptions').tables;
        return t && t.customers && t.customers.length > 0;
    }""")
    assert [u for u in seen if '/api/schema' in u] == []                    # no per-table schema calls any more
    assert len([u for u in seen if '/api/columns' in u]) == 1
    assert {'id', 'name', 'country'} <= set(_hint_tables(page)['customers'])


def test_second_query_tab_reuses_the_cache(connected):
    connected.click('#new-query-tab-btn')
    connected.wait_for_function("window.app.tabManager.schemaCache && window.app.tabManager.schemaCache.size === 1")
    connected.wait_for_timeout(500)
    seen = _sql_requests(connected)
    connected.click('#new-query-tab-btn')
    connected.wait_for_selector('.tab-content.active .CodeMirror')
    connected.wait_for_timeout(800)
    assert seen == []
    assert 'customers' in _hint_tables(connected)


def test_big_schema_loads_columns_only_for_tables_you_mention(page):
    import sqlite3
    c = sqlite3.connect(page.demo_db)
    for i in range(80):
        c.execute(f'create table extra_{i:02d}(id integer primary key, col_{i:02d} text)')
    c.commit()
    c.close()
    add_sqlite_connection(page)
    connect(page)
    seen = _sql_requests(page)
    page.click('#new-query-tab-btn')
    page.wait_for_selector('.tab-content.active .CodeMirror')
    page.wait_for_timeout(1000)
    assert seen == []                                                       # nothing loaded up front
    page.evaluate("document.querySelector('.tab-content.active .CodeMirror').CodeMirror.setValue('select * from extra_07 join extra_42 on 1=1')")
    page.wait_for_function("""() => {
        const tab = window.app.tabManager.tabs.get(window.app.tabManager.activeTabId);
        const t = tab.editor.getOption('hintOptions').tables;
        return t.extra_07.length > 0 && t.extra_42.length > 0;
    }""", timeout=8000)
    column_calls = [u for u in seen if '/api/columns' in u]
    assert len(column_calls) == 1 and 'extra_07' in column_calls[0] and 'extra_42' in column_calls[0]
    assert 'extra_13' not in column_calls[0]
    assert _hint_tables(page)['extra_13'] == []


def test_sidebar_counts_show_for_small_sqlite(connected):
    assert connected.locator('#tables-content .tree-item:has-text("customers") .tree-count').inner_text() == '30'


# ---- unsaved changes are never lost silently ------------------------------------------------

def _dirty_table(pg, table='orders'):
    open_table(pg, table)
    pg.click('.tab-content.active [data-action=add-row]')   # a pending new row
    answer_dialogs(pg, False)


def test_paging_with_unsaved_changes_asks_first_and_keeps_them_on_cancel(connected):
    _dirty_table(connected)
    connected.click('.tab-content.active [data-action=next-page]')
    connected.wait_for_timeout(400)
    assert any('unsaved' in d for d in dialogs(connected))
    assert connected.locator('.tab-content.active tr.new-row').count() == 1
    assert 'Page 1' in connected.inner_text('.tab-content.active [id^=page-info]')


def test_paging_proceeds_when_the_user_agrees_to_discard(connected):
    _dirty_table(connected)
    answer_dialogs(connected, True)
    connected.click('.tab-content.active [data-action=next-page]')
    connected.wait_for_function("document.querySelector('.tab-content.active [id^=page-info]').innerText.includes('Page 2')")
    assert connected.locator('.tab-content.active tr.new-row').count() == 0


def test_searching_with_unsaved_changes_asks_first(connected):
    _dirty_table(connected, 'customers')
    connected.fill('.tab-content.active [id^=table-search-]:not(select)', 'ava')
    connected.click('.tab-content.active [data-action=search-table]')
    connected.wait_for_timeout(400)
    assert any('unsaved' in d for d in dialogs(connected))
    assert connected.locator('.tab-content.active tr.new-row').count() == 1


def test_closing_a_table_tab_with_unsaved_changes_asks_first(connected):
    _dirty_table(connected, 'customers')
    connected.click('#tabs-header .tab.active .tab-close')
    connected.wait_for_timeout(400)
    assert any('close this tab' in d for d in dialogs(connected))
    assert connected.locator('#tabs-header .tab:has-text("customers")').count() == 1   # still open


def test_clean_tables_never_prompt(connected):
    open_table(connected, 'orders')
    connected.click('.tab-content.active [data-action=next-page]')
    connected.wait_for_function("document.querySelector('.tab-content.active [id^=page-info]').innerText.includes('Page 2')")
    connected.click('#tabs-header .tab.active .tab-close')
    assert dialogs(connected) == []


def test_next_is_disabled_on_the_last_page_and_previous_on_the_first(connected):
    open_table(connected, 'orders')   # 250 rows, 100 per page
    prev, nxt = '.tab-content.active [data-action=prev-page]', '.tab-content.active [data-action=next-page]'
    assert connected.is_disabled(prev) and connected.is_enabled(nxt)
    for expected in ('Page 2', 'Page 3'):
        connected.click(nxt)
        connected.wait_for_function(f"document.querySelector('.tab-content.active [id^=page-info]').innerText.includes('{expected}')")
    connected.wait_for_function("document.querySelector('.tab-content.active [data-action=next-page]').disabled")
    assert connected.is_enabled(prev)
    connected.evaluate("document.querySelector('.tab-content.active [data-action=next-page]').disabled = false")  # even if forced
    connected.click(nxt)
    connected.wait_for_timeout(400)
    assert 'Page 3' in connected.inner_text('.tab-content.active [id^=page-info]')   # it does not run past the end


# ---- the dialog itself --------------------------------------------------------------------

def test_delete_rows_uses_the_styled_dialog_and_deletes_only_after_confirming(connected):
    open_table(connected, 'customers')
    connected.check('.tab-content.active tr[data-row-index="0"] .row-checkbox')
    answer_dialogs(connected, False)
    connected.click('.tab-content.active [data-action=delete-row]')
    connected.wait_for_timeout(500)
    assert any('cannot be undone' in d for d in dialogs(connected))
    assert db_rows(connected, 'select count(*) from customers') == [(30,)]


def test_dialog_escape_cancels_and_enter_does_not_confirm_a_destructive_action(connected):
    manual_dialogs(connected)   # keep the auto-answer out of the way: we answer with the keyboard
    connected.evaluate("""() => { window.__result = null;
        ui.confirm('Really?', {danger: true, confirmLabel: 'Delete'}).then(r => window.__result = r); }""")
    connected.wait_for_selector('.app-dialog')
    focused = connected.evaluate("document.activeElement.textContent.trim()")
    assert focused == 'Cancel'                      # the safe choice has focus
    connected.keyboard.press('Enter')
    connected.wait_for_function("window.__result === false")
    connected.evaluate("""() => { window.__result = null; ui.confirm('Again?').then(r => window.__result = r); }""")
    connected.wait_for_selector('.app-dialog')
    connected.keyboard.press('Escape')
    connected.wait_for_function("window.__result === false")
    assert connected.locator('.app-dialog').count() == 0


def test_dialog_text_is_not_interpreted_as_html(connected):
    connected.evaluate("() => { ui.confirm('<img src=x onerror=window.__pwned=1> & <b>bold</b>', {title: '<i>t</i>'}); }")
    connected.wait_for_selector('.app-dialog')
    assert connected.locator('.app-dialog img, .app-dialog b, .app-dialog i').count() == 0
    assert connected.evaluate("window.__pwned") is None


def test_informational_messages_are_toasts_not_dialogs(connected):
    open_table(connected, 'customers')
    connected.click('.tab-content.active [data-action=search-table]')   # empty search term
    connected.wait_for_selector('#toast-stack .notification')
    assert 'search' in connected.inner_text('#toast-stack').lower()
