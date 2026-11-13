"""Saving is all-or-nothing, and never overwrites someone else's change without asking."""
import sqlite3

import pytest

from conftest import add_sqlite_connection, answer_dialogs, connect, dialogs

pytestmark = pytest.mark.e2e


def db(pg, sql, *args):
    c = sqlite3.connect(pg.demo_db)
    try:
        out = c.execute(sql, args).fetchall()
        c.commit()
        return out
    finally:
        c.close()


def open_table(pg, name):
    pg.locator('#tables-content .tree-item').filter(has=pg.locator(f'.tree-label:text-is("{name}")')).click()
    pg.wait_for_selector('.tab-content.active .data-table tbody tr')


def edit(pg, row, column, text):
    cell = pg.locator(f'.tab-content.active tr[data-row-index="{row}"] td[data-column={column}]')
    cell.click()
    pg.keyboard.press('ControlOrMeta+A')
    pg.keyboard.type(text)
    pg.keyboard.press('Tab')


def save(pg):
    pg.click('.tab-content.active [data-action=save-changes]')


def toast_with(pg, text):
    """Wait for a toast that says `text` (older toasts may still be on screen)."""
    pg.wait_for_function("t => document.querySelector('#toast-stack') && document.querySelector('#toast-stack').innerText.includes(t)", arg=text)
    return pg.inner_text('#toast-stack')


# ---- the happy path ---------------------------------------------------------------------------------------------

def test_several_edits_save_together_and_say_how_many(connected):
    open_table(connected, 'customers')
    edit(connected, 0, 'name', 'First')
    edit(connected, 1, 'name', 'Second')
    save(connected)
    connected.wait_for_function("document.querySelector('#toast-stack') && document.querySelector('#toast-stack').innerText.includes('Saved 2 changes')")
    assert db(connected, 'select name from customers where id in (1, 2) order by id') == [('First',), ('Second',)]
    assert connected.locator('.tab-content.active td.modified').count() == 0


# ---- all or nothing ----------------------------------------------------------------------------------------------

def test_one_bad_row_means_nothing_is_saved_and_your_edits_are_kept(connected):
    open_table(connected, 'customers')
    before = db(connected, 'select name from customers where id = 1')
    edit(connected, 0, 'name', 'Would be saved')
    connected.click('.tab-content.active [data-action=add-row]')
    new = connected.locator('.tab-content.active tr.new-row')
    new.locator('td[data-column=id]').click()
    connected.keyboard.type('2')                                    # id 2 already exists: this insert must fail
    new.locator('td[data-column=name]').click()
    connected.keyboard.type('Duplicate')
    connected.keyboard.press('Tab')
    save(connected)
    toast_with(connected, 'Nothing was saved')
    assert db(connected, 'select name from customers where id = 1') == before     # the good edit was not saved alone
    assert db(connected, "select count(*) from customers where name = 'Duplicate'") == [(0,)]
    assert connected.locator('.tab-content.active td.modified').count() >= 1     # still there to fix and retry
    assert connected.locator('.tab-content.active tr.new-row').count() == 1


def test_deleting_rows_is_one_step_and_a_row_already_gone_does_not_block_it(connected):
    open_table(connected, 'customers')
    connected.check('.tab-content.active tr[data-row-index="0"] .row-checkbox')
    connected.check('.tab-content.active tr[data-row-index="1"] .row-checkbox')
    db(connected, 'delete from customers where id = 1')               # someone already deleted the first one
    connected.click('.tab-content.active [data-action=delete-row]')
    connected.wait_for_function("document.querySelector('#toast-stack') && document.querySelector('#toast-stack').innerText.includes('Deleted 2 rows')")
    assert db(connected, 'select count(*) from customers where id in (1, 2)') == [(0,)]


# ---- someone else changed it -----------------------------------------------------------------------------------------

def test_a_row_changed_by_someone_else_is_shown_and_you_can_keep_editing(connected):
    open_table(connected, 'customers')
    original = db(connected, 'select name from customers where id = 1')[0][0]
    edit(connected, 0, 'name', 'My version')
    db(connected, "update customers set name = 'Their version' where id = 1")      # changed behind your back
    answer_dialogs(connected, [True, False])                                       # accept the review, then "Keep editing"
    save(connected)
    connected.wait_for_function("window.__dialogs.length >= 2")
    text = dialogs(connected)[-1]
    assert 'changed by someone else' in text and 'Nothing has been saved' in text
    assert f'name was "{original}" when you loaded it, now "Their version"' in text and 'id = 1' in text
    assert db(connected, 'select name from customers where id = 1') == [('Their version',)]
    assert connected.locator('.tab-content.active td.modified').count() == 1       # your edit is still pending


def test_you_can_choose_to_save_over_it(connected):
    open_table(connected, 'customers')
    edit(connected, 0, 'name', 'My version')
    db(connected, "update customers set name = 'Their version' where id = 1")
    answer_dialogs(connected, [True, True])                                        # accept the review, then "Save anyway"
    save(connected)
    connected.wait_for_function("document.querySelector('#toast-stack') && document.querySelector('#toast-stack').innerText.includes('Saved 1 change')")
    assert db(connected, 'select name from customers where id = 1') == [('My version',)]


def test_every_conflicting_row_is_listed_at_once(connected):
    open_table(connected, 'customers')
    edit(connected, 0, 'name', 'Mine 1')
    edit(connected, 1, 'name', 'Mine 2')
    db(connected, "update customers set name = 'Theirs 1' where id = 1")
    db(connected, "update customers set name = 'Theirs 2' where id = 2")
    answer_dialogs(connected, [True, False])
    save(connected)
    connected.wait_for_function("window.__dialogs.length >= 2")
    text = dialogs(connected)[-1]
    assert '2 rows were changed' in text and 'Theirs 1' in text and 'Theirs 2' in text


def test_editing_a_row_that_was_deleted_says_so(connected):
    open_table(connected, 'customers')
    edit(connected, 0, 'name', 'Mine')
    db(connected, 'delete from customers where id = 1')
    answer_dialogs(connected, [True, False])
    save(connected)
    connected.wait_for_function("window.__dialogs.length >= 2")
    assert 'no longer exists' in dialogs(connected)[-1]


def test_unchanged_rows_cause_no_dialog_even_after_other_rows_change(connected):
    open_table(connected, 'customers')
    edit(connected, 0, 'name', 'Mine')
    db(connected, "update customers set name = 'Elsewhere' where id = 5")          # a different row
    save(connected)
    connected.wait_for_function("document.querySelector('#toast-stack') && document.querySelector('#toast-stack').innerText.includes('Saved 1 change')")
    assert not any('changed by someone else' in d for d in dialogs(connected))   # only the review was shown


# ---- the silent failure this replaces ----------------------------------------------------------------------------------

def test_editing_a_table_with_no_primary_key_and_a_null_really_saves(page):
    db(page, 'create table loose(a text, b text)')
    db(page, "insert into loose values ('one', NULL), ('two', 'x')")
    add_sqlite_connection(page)
    connect(page)
    open_table(page, 'loose')
    edit(page, 0, 'a', 'ONE')
    save(page)
    toast_with(page, 'Saved 1 change')
    assert db(page, 'select a, b from loose order by rowid') == [('ONE', None), ('two', 'x')]


# ---- undoing an edit before it is saved --------------------------------------------------------------------------------

def cell_text(pg, row, column):
    return pg.locator(f'.tab-content.active tr[data-row-index="{row}"] td[data-column={column}]').inner_text()


def test_undo_takes_back_one_edit_at_a_time_and_saves_nothing(connected):
    open_table(connected, 'customers')
    before = (cell_text(connected, 0, 'name'), cell_text(connected, 1, 'name'))
    stored = db(connected, 'select id, name from customers order by id')
    edit(connected, 0, 'name', 'First edit')
    edit(connected, 1, 'name', 'Second edit')
    assert connected.locator('.tab-content.active td.modified').count() == 2
    connected.click('.tab-content.active [data-action=undo-edit]')
    assert cell_text(connected, 1, 'name') == before[1]                         # the last edit is gone
    assert cell_text(connected, 0, 'name') == 'First edit'                      # the one before it is not
    assert connected.locator('.tab-content.active td.modified').count() == 1
    connected.keyboard.press('ControlOrMeta+z')                                 # the shortcut does the same
    assert cell_text(connected, 0, 'name') == before[0]
    assert connected.locator('.tab-content.active td.modified').count() == 0
    for action in ('save-changes', 'discard-changes', 'undo-edit'):             # nothing is pending, so nothing to click
        assert connected.is_hidden(f'.tab-content.active [data-action={action}]')
    assert db(connected, 'select id, name from customers order by id') == stored   # nothing was ever saved


def test_undo_restores_a_value_that_was_null(connected):
    open_table(connected, 'customers')
    row = connected.evaluate("() => [...document.querySelectorAll('.tab-content.active tbody tr')].findIndex(tr => tr.querySelector('td[data-column=notes]').classList.contains('null'))")
    assert row >= 0
    edit(connected, row, 'notes', 'something')
    connected.click('.tab-content.active [data-action=undo-edit]')
    assert cell_text(connected, row, 'notes') == 'NULL'
    assert connected.locator('.tab-content.active td.modified').count() == 0


# ---- query results are read-only ----------------------------------------------------------------------------------------

def run_query(pg, sql):
    from conftest import open_query_tab
    open_query_tab(pg)
    pg.evaluate("sql => document.querySelector('.tab-content.active .CodeMirror').CodeMirror.setValue(sql)", sql)
    pg.keyboard.press('ControlOrMeta+Enter')
    pg.wait_for_selector('.tab-content.active .results-grid td[data-column]')


def test_query_results_cannot_be_edited(connected):
    run_query(connected, 'select id, name, meta from customers order by id')
    grid = '.tab-content.active .results-grid'
    assert connected.locator(f'{grid} [contenteditable=true]').count() == 0
    cell = connected.locator(f'{grid} tr[data-row-index="0"] td[data-column=name]')
    before = cell.inner_text()
    cell.click()
    connected.keyboard.type('typed into a result')
    assert cell.inner_text() == before
    assert connected.locator(f'{grid} td.modified').count() == 0
    assert 'read-only' in connected.inner_text('.tab-content.active .results-note')


def test_a_json_value_in_a_query_result_opens_a_viewer_that_cannot_save(connected):
    run_query(connected, 'select id, meta from customers where meta is not null order by id')
    connected.locator('.tab-content.active .results-grid .json-view-icon').first.click()
    connected.wait_for_selector('#json-editor-modal.active')
    assert connected.is_hidden('#json-save-btn') and connected.is_hidden('#json-format-btn')
    assert connected.evaluate("document.querySelector('#json-editor-container .CodeMirror').CodeMirror.getOption('readOnly')") is True
    assert 'tier' in connected.inner_text('#json-editor-container')
    connected.click('#json-cancel-btn')
    connected.wait_for_selector('#json-editor-modal.active', state='hidden')
    assert connected.locator('.tab-content.active td.modified').count() == 0


# ---- JSON cells -------------------------------------------------------------------------------------------------------

def edit_json(pg, row, text):
    pg.locator(f'.tab-content.active tr[data-row-index="{row}"] .json-cell').click()
    pg.wait_for_selector('#json-editor-modal.active')
    pg.evaluate("v => document.querySelector('#json-editor-container .CodeMirror').CodeMirror.setValue(v)", text)
    assert pg.inner_text('#json-save-btn') == 'Finalize'            # it keeps the change; the table's Save writes it
    pg.click('#json-save-btn')


def test_an_edited_json_cell_is_saved(connected):
    import json
    open_table(connected, 'customers')
    row = connected.evaluate("() => [...document.querySelectorAll('.tab-content.active tbody tr')].findIndex(tr => tr.querySelector('.json-cell'))")
    assert row >= 0
    edit_json(connected, row, '{"tier": "silver", "tags": ["x"]}')
    save(connected)
    toast_with(connected, 'Saved 1 change')
    stored = db(connected, 'select meta from customers where id = ?', row + 1)[0][0]
    assert json.loads(stored) == {'tier': 'silver', 'tags': ['x']}
    assert db(connected, 'select count(*) from customers where meta like ?', '%silver%') == [(1,)]


def test_a_json_edit_and_a_plain_edit_are_saved_together(connected):
    import json
    open_table(connected, 'customers')
    row = connected.evaluate("() => [...document.querySelectorAll('.tab-content.active tbody tr')].findIndex(tr => tr.querySelector('.json-cell'))")
    edit(connected, row, 'name', 'Renamed')
    edit_json(connected, row, '{"tier": "bronze"}')
    save(connected)
    toast_with(connected, 'Saved 1 change')
    name, meta = db(connected, 'select name, meta from customers where id = ?', row + 1)[0]
    assert name == 'Renamed' and json.loads(meta) == {'tier': 'bronze'}


# ---- search boxes ---------------------------------------------------------------------------------------------------------

def test_search_boxes_are_not_auto_capitalised(connected):
    """The desktop window capitalises the first letter of a text field unless told not to: a search for 'ava' became 'Ava'."""
    open_table(connected, 'customers')
    connected.click('#new-query-tab-btn')
    connected.keyboard.press('Meta+k')
    connected.wait_for_selector('.palette-input')
    found = connected.evaluate("""() => [...document.querySelectorAll('input.table-search-input, input.palette-input, #saved-queries-filter')]
        .map(i => [i.id || i.className, i.getAttribute('autocapitalize'), i.getAttribute('autocorrect')])""")
    assert len(found) >= 3
    assert all(cap == 'off' and correct == 'off' for _, cap, correct in found), found


def test_finalizing_a_json_edit_stages_it_and_the_table_save_writes_it(connected):
    import json
    open_table(connected, 'customers')
    row = connected.evaluate("() => [...document.querySelectorAll('.tab-content.active tbody tr')].findIndex(tr => tr.querySelector('.json-cell'))")
    stored = db(connected, 'select meta from customers where id = ?', row + 1)
    edit(connected, row, 'name', 'Staged too')
    edit_json(connected, row, '{"tier": "staged"}')

    assert db(connected, 'select meta from customers where id = ?', row + 1) == stored      # finalizing alone writes nothing
    assert connected.is_visible('.tab-content.active [data-action=save-changes]')
    save(connected)
    toast_with(connected, 'Saved 1 change')
    name, meta = db(connected, 'select name, meta from customers where id = ?', row + 1)[0]
    assert name == 'Staged too' and json.loads(meta) == {'tier': 'staged'}


# ---- review before saving ---------------------------------------------------------------------------------------

def test_saving_shows_each_change_first_and_cancel_saves_nothing(connected):
    from conftest import manual_dialogs
    open_table(connected, 'customers')
    before = db(connected, 'select name from customers where id = 1')[0][0]
    edit(connected, 0, 'name', 'Reviewed')
    manual_dialogs(connected)
    save(connected)
    connected.wait_for_selector('.app-dialog')
    text = connected.inner_text('.app-dialog')
    assert 'Review changes' in text and f'name {before} → Reviewed' in text
    connected.click('.app-dialog button:has-text("Cancel")')
    connected.wait_for_selector('.app-dialog', state='detached')
    assert db(connected, 'select name from customers where id = 1')[0][0] == before
    assert connected.locator('.tab-content.active td.modified').count() == 1   # your edit is still there
    connected.click('.tab-content.active [data-action=save-changes]')
    connected.click('.app-dialog button:has-text("Save 1 change")')
    toast_with(connected, 'Saved 1 change')
    assert db(connected, 'select name from customers where id = 1') == [('Reviewed',)]


def test_export_sql_downloads_the_whole_table(connected):
    open_table(connected, 'customers')
    with connected.expect_download(timeout=5000) as dl:
        connected.click('.tab-content.active [data-action=export-table-sql]')
    assert dl.value.suggested_filename.endswith('.sql')
    text = open(dl.value.path()).read()
    assert text.count('INSERT INTO') == db(connected, 'select count(*) from customers')[0][0]
