"""CSV import, through the real UI: pick a file, map columns, check, import."""
import sqlite3

import pytest

from conftest import add_sqlite_connection, connect, manual_dialogs

pytestmark = pytest.mark.e2e


def query(pg, sql, *args):
    c = sqlite3.connect(pg.demo_db)
    try:
        out = c.execute(sql, args).fetchall()
        c.commit()
        return out
    finally:
        c.close()


def open_table(pg, name, rows=True):
    pg.locator('#tables-content .tree-item').filter(has=pg.locator(f'.tree-label:text-is("{name}")')).click()
    pg.wait_for_selector('.tab-content.active .data-table tbody tr' if rows else '.tab-content.active .table-toolbar')


def pick(pg, tmp_path, text, name='data.csv'):
    # an in-memory file: the name can be anything the browser allows, including characters Windows forbids on disk
    payload = {'name': name, 'mimeType': 'text/csv', 'buffer': text if isinstance(text, bytes) else text.encode('utf-8')}
    with pg.expect_file_chooser() as chooser:
        pg.click('.tab-content.active [data-action=import-csv]')
    chooser.value.set_files(payload)


def opened(pg, tmp_path, text, name='data.csv', table='customers'):
    open_table(pg, table, rows=table != 'events')
    pick(pg, tmp_path, text, name)
    pg.wait_for_selector('#import-modal.active #import-body .import-mapping')


def mapping_of(pg):
    return pg.evaluate("""() => Object.fromEntries([...document.querySelectorAll('#import-body .import-mapping select')]
        .map(s => [s.dataset.column, s.options[s.selectedIndex].textContent]))""")


def status(pg):
    pg.wait_for_function("document.getElementById('import-status').style.display !== 'none' && !document.getElementById('import-status').classList.contains('busy')")
    return pg.inner_text('#import-status')


GOOD = 'name,email,country\nAlice Import,alice@example.com,FR\nBob Import,bob@example.com,ES\nCy Import,,IT\n'


@pytest.fixture
def with_events(page):
    query(page, 'create table events(id integer primary key, title text not null, happened date)')
    add_sqlite_connection(page)
    connect(page)
    return page


# ---- the dialog ---------------------------------------------------------------------------------------------------

def test_picking_a_file_shows_what_it_found_and_a_suggested_mapping(connected, tmp_path):
    opened(connected, tmp_path, GOOD)
    assert 'data.csv' in connected.inner_text('.import-summary') and '3 rows' in connected.inner_text('.import-summary')
    m = mapping_of(connected)
    assert m['name'] == 'name' and m['email'] == 'email' and m['country'] == 'country'
    assert m['id'] == "— don't import —" and m['notes'] == "— don't import —"            # no such column in the file
    assert connected.inner_text('#import-run') == 'Import 3 rows'
    assert 'Alice Import' in connected.inner_text('.import-sample-table')
    assert query(connected, 'select count(*) from customers') == [(30,)]               # looking changes nothing


def test_the_columns_are_labelled_with_type_key_and_required(connected, tmp_path):
    opened(connected, tmp_path, GOOD)
    name_row = connected.locator('.import-mapping tbody tr', has=connected.locator('.import-column-name:text-is("name")'))
    id_row = connected.locator('.import-mapping tbody tr', has=connected.locator('.import-column-name:text-is("id")'))
    assert 'required' in name_row.inner_text() and 'key' in id_row.inner_text() and 'required' not in id_row.inner_text()


def test_cancel_and_escape_close_it_without_importing(connected, tmp_path):
    opened(connected, tmp_path, GOOD)
    connected.click('#import-cancel')
    connected.wait_for_selector('#import-modal.active', state='hidden')
    pick(connected, tmp_path, GOOD)
    connected.wait_for_selector('#import-modal.active')
    connected.keyboard.press('Escape')
    connected.wait_for_selector('#import-modal.active', state='hidden')
    assert query(connected, 'select count(*) from customers') == [(30,)]


# ---- importing ----------------------------------------------------------------------------------------------------------

def test_import_adds_the_rows_and_refreshes_the_table(connected, tmp_path):
    opened(connected, tmp_path, GOOD)
    connected.click('#import-run')
    connected.wait_for_function("document.querySelector('#toast-stack') && document.querySelector('#toast-stack').innerText.includes('Imported 3 rows into customers')")
    connected.wait_for_selector('#import-modal.active', state='hidden')
    assert query(connected, "select name, email, country from customers where name like '% Import' order by name") == [
        ('Alice Import', 'alice@example.com', 'FR'), ('Bob Import', 'bob@example.com', 'ES'), ('Cy Import', None, 'IT')]   # empty email -> NULL
    connected.wait_for_function("document.querySelector('.tab-content.active .table-toolbar').innerText.includes('33 total rows')")   # the grid reloads a moment after the toast


def test_empty_values_can_stay_empty_text(connected, tmp_path):
    opened(connected, tmp_path, GOOD)
    connected.uncheck('#import-null')
    assert 'NULL' not in connected.inner_text('.import-sample-table')
    connected.click('#import-run')
    connected.wait_for_selector('#import-modal.active', state='hidden')
    assert query(connected, "select email from customers where name = 'Cy Import'") == [('',)]


def test_choosing_a_different_file_column_or_none(connected, tmp_path):
    opened(connected, tmp_path, 'full name,mail\nZed One,z@example.com\n')
    assert mapping_of(connected)['name'] == "— don't import —"                          # "full name" is not "name"
    assert 'Not filled in: name. It is required and has no default' in connected.inner_text('#import-body')   # and it is required
    connected.select_option('select[data-column=name]', label='full name')
    connected.select_option('select[data-column=email]', label='mail')
    assert 'Not filled in' not in connected.inner_text('#import-body')
    connected.click('#import-run')
    connected.wait_for_selector('#import-modal.active', state='hidden')
    assert query(connected, "select name, email from customers where name = 'Zed One'") == [('Zed One', 'z@example.com')]


def test_nothing_chosen_cannot_be_imported(connected, tmp_path):
    opened(connected, tmp_path, 'unrelated\nx\n')
    assert connected.is_disabled('#import-run') and connected.is_disabled('#import-check')
    assert 'Choose at least one column' in connected.inner_text('.import-preview')


# ---- separators and headers ----------------------------------------------------------------------------------------------

def test_a_semicolon_file_is_detected_and_can_be_read_differently(connected, tmp_path):
    opened(connected, tmp_path, 'name;email\n"Smith, Sam";sam@example.com\n')
    assert connected.input_value('#import-delimiter') == 'semicolon' and mapping_of(connected)['email'] == 'email'
    connected.select_option('#import-delimiter', 'comma')                               # read it wrongly on purpose
    connected.wait_for_function("document.querySelector('#import-body .import-mapping select[data-column=email]').selectedIndex === 0")
    connected.select_option('#import-delimiter', 'semicolon')
    connected.wait_for_function("document.querySelector('#import-body .import-mapping select[data-column=email]').selectedIndex > 0")


def test_a_file_without_a_header_row(connected, tmp_path):
    opened(connected, tmp_path, 'Hal Nine,hal@example.com\n')
    connected.uncheck('#import-header')
    connected.wait_for_function("document.querySelector('#import-body .import-mapping select').options.length > 1 && [...document.querySelectorAll('#import-body .import-mapping select option')].some(o => o.textContent === 'Column 1')")
    connected.select_option('select[data-column=name]', label='Column 1')
    connected.select_option('select[data-column=email]', label='Column 2')
    connected.click('#import-run')
    connected.wait_for_selector('#import-modal.active', state='hidden')
    assert query(connected, "select name, email from customers where name = 'Hal Nine'") == [('Hal Nine', 'hal@example.com')]


# ---- checking ---------------------------------------------------------------------------------------------------------------

def test_check_says_it_works_and_changes_nothing(connected, tmp_path):
    opened(connected, tmp_path, GOOD)
    connected.click('#import-check')
    assert 'Looks good: all 3 rows can be imported. Nothing was changed.' in status(connected)
    assert query(connected, 'select count(*) from customers') == [(30,)] and connected.is_visible('#import-modal.active')


def test_check_finds_the_bad_row(connected, tmp_path):
    opened(connected, tmp_path, 'id,name\n500,Fine\n1,Duplicate id\n501,Never\n')
    connected.click('#import-check')
    text = status(connected)
    assert text.startswith('Row 2:') and 'Nothing was changed' in text
    assert query(connected, 'select count(*) from customers') == [(30,)]


# ---- all or nothing ---------------------------------------------------------------------------------------------------------

def test_one_bad_row_imports_nothing_and_the_dialog_stays_for_a_fix(connected, tmp_path):
    opened(connected, tmp_path, 'id,name\n600,Fine\n601,Also fine\n1,Duplicate id\n')
    connected.click('#import-run')
    text = status(connected)
    assert text.startswith('Nothing was imported. Row 3:')
    assert connected.is_visible('#import-modal.active')
    assert query(connected, 'select count(*) from customers where id >= 600') == [(0,)]
    connected.select_option('select[data-column=id]', label="— don't import —")           # fix: let the database number them
    connected.click('#import-run')
    connected.wait_for_selector('#import-modal.active', state='hidden')
    assert query(connected, "select count(*) from customers where name in ('Fine', 'Also fine', 'Duplicate id')") == [(3,)]


def test_a_file_with_uneven_rows_cannot_be_imported(connected, tmp_path):
    opened(connected, tmp_path, 'name,email\nAnn,a@example.com\nBo\n')
    assert 'Row 2 has 1 value but there are 2 columns' in connected.inner_text('.import-problems')
    assert connected.is_disabled('#import-run') and connected.is_disabled('#import-check')


def test_a_file_that_is_not_text_is_refused_before_any_dialog(connected, tmp_path):
    open_table(connected, 'customers')
    pick(connected, tmp_path, b'PK\x03\x04\x00\x00 not a csv', 'sheet.xlsx')
    connected.wait_for_function("document.querySelector('#toast-stack') && document.querySelector('#toast-stack').innerText.includes('text file')")
    assert not connected.is_visible('#import-modal.active')


# ---- dates -------------------------------------------------------------------------------------------------------------------------

def test_dates_written_the_ambiguous_way_are_refused_by_name(with_events, tmp_path):
    opened(with_events, tmp_path, 'title,happened\nLaunch,2026-03-04\nParty,04/03/2026\n', table='events')
    with_events.click('#import-run')
    text = status(with_events)
    assert text.startswith('Nothing was imported. Row 2, "happened"') and 'wrong way round' in text
    assert query(with_events, 'select count(*) from events') == [(0,)]


def test_dates_written_year_first_are_imported(with_events, tmp_path):
    opened(with_events, tmp_path, 'title,happened\nLaunch,2026-03-04\nParty,2026-03-05T20:00:00\nTBC,\n', table='events')
    with_events.click('#import-run')
    with_events.wait_for_selector('#import-modal.active', state='hidden')
    assert query(with_events, 'select title, happened from events order by id') == [('Launch', '2026-03-04'), ('Party', '2026-03-05 20:00:00'), ('TBC', None)]


# ---- the guards the rest of the app has ----------------------------------------------------------------------------------------

def test_a_read_only_connection_has_no_import_button(page, tmp_path):
    add_sqlite_connection(page, read_only=True)
    connect(page)
    open_table(page, 'customers')
    assert not page.is_visible('.tab-content.active [data-action=import-csv]')


def test_importing_into_production_asks_first(page, tmp_path):
    page.click('#manage-connections-btn')
    page.click('#new-connection-btn-manager')
    page.select_option('select[name=type]', 'sqlite')
    page.fill('input[name=name]', 'Demo shop')
    page.fill('input[name=database]', page.demo_db)
    page.select_option('#environment-select', 'production')
    page.uncheck('#read-only-checkbox')
    page.click('#connection-form button[type=submit]')
    page.wait_for_selector('.connection-item:has-text("Demo shop")')
    connect(page)
    opened(page, tmp_path, GOOD)
    manual_dialogs(page)
    page.click('#import-run')
    page.wait_for_selector('.app-dialog [data-answer=ok]')
    assert 'production database' in page.inner_text('.app-dialog-message')
    assert page.evaluate("document.activeElement.textContent.trim()") == 'Cancel'           # the safe default
    page.click('.app-dialog [data-answer=cancel]')
    page.wait_for_selector('.app-dialog', state='detached')
    assert query(page, 'select count(*) from customers') == [(30,)]
    page.click('#import-run')
    page.wait_for_selector('.app-dialog [data-answer=ok]')
    page.click('.app-dialog [data-answer=ok]')
    page.wait_for_selector('#import-modal.active', state='hidden')
    assert query(page, 'select count(*) from customers') == [(33,)]


def test_unsaved_edits_in_the_table_are_not_silently_lost(connected, tmp_path):
    open_table(connected, 'customers')
    cell = connected.locator('.tab-content.active tr[data-row-index="0"] td[data-column=name]')
    cell.click(); connected.keyboard.press('ControlOrMeta+A'); connected.keyboard.type('Unsaved'); connected.keyboard.press('Tab')
    manual_dialogs(connected)
    connected.click('.tab-content.active [data-action=import-csv]')
    connected.wait_for_selector('.app-dialog [data-answer=ok]')
    assert 'unsaved changes' in connected.inner_text('.app-dialog-message')
    connected.click('.app-dialog [data-answer=cancel]')
    connected.wait_for_selector('.app-dialog', state='detached')
    assert not connected.is_visible('#import-modal.active')


# ---- untrusted text -------------------------------------------------------------------------------------------------------------------

def test_hostile_file_names_headers_and_values_stay_plain_text(connected, tmp_path):
    header, value = '<img src=x onerror=window.__pwned=1>', '<script>window.__pwned=2</script>'
    opened(connected, tmp_path, f'name,"{header}"\n"{value}",x\n', name='<b>evil<img src=x onerror=window.__pwned=3>.csv')
    box = connected.inner_html('#import-body')
    assert '<img' not in box and '<script' not in box and '<b>' not in box
    assert '<b>evil<img src=x onerror=window.__pwned=3>.csv' in connected.inner_text('.import-summary') and header in connected.inner_text('.import-mapping')
    assert connected.evaluate('window.__pwned') is None
    connected.click('#import-run')
    connected.wait_for_selector('#import-modal.active', state='hidden')
    assert query(connected, 'select name from customers where name like "%script%"') == [(value,)]      # stored as text
