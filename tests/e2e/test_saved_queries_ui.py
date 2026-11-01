"""Saved queries, through the real UI."""
import pytest

from conftest import manual_dialogs

pytestmark = pytest.mark.e2e

PURGE = """async () => {
  const list = await (await fetch('/api/saved-queries')).json();
  for (const q of list.queries) await fetch('/api/saved-queries/' + q.id, {method: 'DELETE'});
}"""
LIST = "async () => (await (await fetch('/api/saved-queries')).json()).queries"


@pytest.fixture(autouse=True)
def clean(page):
    page.evaluate(PURGE)
    yield
    page.evaluate(PURGE)


def stored(pg):
    return pg.evaluate(LIST)


def eventually(pg, check, what):
    """Wait (up to 5 s) until check(stored queries) is true. Toasts are no use here: an earlier one may still be showing."""
    for _ in range(50):
        queries = stored(pg)
        if check(queries):
            return queries
        pg.wait_for_timeout(100)
    raise AssertionError(f'{what}; stored: {queries}')


def new_query(pg, sql=''):
    pg.click('#new-query-tab-btn')
    pg.wait_for_selector('.tab-content.active .CodeMirror')
    pg.evaluate("sql => document.querySelector('.tab-content.active .CodeMirror').CodeMirror.setValue(sql)", sql)


def editor_text(pg):
    pg.wait_for_selector('.tab-content.active .CodeMirror')
    return pg.evaluate("document.querySelector('.tab-content.active .CodeMirror').CodeMirror.getValue()")


def toast_with(pg, text):
    pg.wait_for_function("t => document.querySelector('#toast-stack') && document.querySelector('#toast-stack').innerText.includes(t)", arg=text)


def answer(pg, ok):
    pg.click(f'.app-dialog [data-answer={"ok" if ok else "cancel"}]')
    pg.wait_for_selector('.app-dialog', state='detached')


def save_as(pg, name):
    manual_dialogs(pg)
    pg.click('.tab-content.active [data-action=save-query]')
    pg.wait_for_selector('.app-dialog-input')
    pg.fill('.app-dialog-input', name)
    pg.click('.app-dialog [data-answer=ok]')


def keep(pg, name, sql):
    new_query(pg, sql)
    save_as(pg, name)
    toast_with(pg, f'Saved the query "{name}"')


def open_panel(pg):
    pg.click('.tab-content.active [data-action=saved-queries]')
    pg.wait_for_selector('#saved-queries-modal.active')


def names_in_panel(pg):
    return pg.locator('#saved-queries-list .saved-name').all_inner_texts()


# ---- saving -------------------------------------------------------------------------------------------------

def test_save_a_query_and_find_it_again_after_a_reload(connected):
    new_query(connected, 'select name from customers where country = \'US\'')
    save_as(connected, 'US customers')
    toast_with(connected, 'Saved the query "US customers"')
    [q] = stored(connected)
    assert q['name'] == 'US customers' and q['sql'] == "select name from customers where country = 'US'" and q['connection_name'] == 'Demo shop'
    connected.reload()
    connected.wait_for_selector('#manage-connections-btn')
    assert [q['name'] for q in stored(connected)] == ['US customers']


def test_an_empty_editor_is_not_saved_and_asks_for_nothing(connected):
    new_query(connected, '   ')
    connected.click('.tab-content.active [data-action=save-query]')
    toast_with(connected, 'Write a query first')
    assert connected.locator('.app-dialog').count() == 0 and stored(connected) == []


def test_a_blank_name_is_refused_in_the_dialog_and_cancel_saves_nothing(connected):
    new_query(connected, 'select 1')
    manual_dialogs(connected)
    connected.click('.tab-content.active [data-action=save-query]')
    connected.wait_for_selector('.app-dialog-input')
    connected.fill('.app-dialog-input', '   ')
    connected.click('.app-dialog [data-answer=ok]')
    assert 'name' in connected.inner_text('.app-dialog-error').lower()
    assert connected.locator('.app-dialog').count() == 1                 # still open: fix it or cancel
    connected.fill('.app-dialog-input', 'x')
    assert not connected.is_visible('.app-dialog-error')               # typing clears the complaint
    answer(connected, False)
    assert stored(connected) == []


def test_enter_in_the_name_field_saves_and_escape_cancels(connected):
    new_query(connected, 'select 1')
    manual_dialogs(connected)
    connected.click('.tab-content.active [data-action=save-query]')
    connected.wait_for_selector('.app-dialog-input')
    connected.keyboard.press('Escape')
    connected.wait_for_selector('.app-dialog', state='detached')
    assert stored(connected) == []
    connected.click('.tab-content.active [data-action=save-query]')
    connected.wait_for_selector('.app-dialog-input')
    connected.keyboard.type('From keyboard')
    connected.keyboard.press('Enter')
    toast_with(connected, 'Saved the query "From keyboard"')


def test_only_the_selection_is_saved_when_there_is_one(connected):
    new_query(connected, 'select 1;\nselect 2;')
    connected.evaluate("""() => { const cm = document.querySelector('.tab-content.active .CodeMirror').CodeMirror;
        cm.setSelection({line: 1, ch: 0}, {line: 1, ch: 9}); }""")
    save_as(connected, 'second only')
    eventually(connected, lambda qs: [q['sql'] for q in qs] == ['select 2;'], 'only the selection should be saved')


def test_the_same_name_asks_before_replacing(connected):
    keep(connected, 'report', 'select 1')
    new_query(connected, 'select 2')
    save_as(connected, 'REPORT')
    connected.wait_for_selector('.app-dialog [data-answer=ok]')
    assert 'already saved' in connected.inner_text('.app-dialog-message')
    answer(connected, False)
    assert [q['sql'] for q in stored(connected)] == ['select 1']                  # kept
    save_as(connected, 'report')
    connected.wait_for_selector('.app-dialog [data-answer=ok]')
    answer(connected, True)
    eventually(connected, lambda qs: [q['sql'] for q in qs] == ['select 2'], 'the query was not replaced')   # still one entry


def test_saving_again_from_a_tab_you_loaded_it_into_updates_it_without_asking(connected):
    keep(connected, 'report', 'select 1')
    open_panel(connected)
    connected.click('#saved-queries-list .saved-main')                           # empty editor now has it
    connected.wait_for_selector('#saved-queries-modal.active', state='hidden')
    # (the editor already held the same text, so no confirmation was needed)
    connected.evaluate("document.querySelector('.tab-content.active .CodeMirror').CodeMirror.setValue('select 1 -- edited')")
    save_as(connected, 'report')
    eventually(connected, lambda qs: [q['sql'] for q in qs] == ['select 1 -- edited'], 'the saved query was not updated')
    assert connected.locator('.app-dialog').count() == 0                       # and nobody was asked anything


# ---- the list -----------------------------------------------------------------------------------------------

def test_the_panel_lists_newest_first_and_says_when_empty(connected):
    new_query(connected, 'select 1')
    open_panel(connected)
    assert 'Nothing saved yet' in connected.inner_text('#saved-queries-empty')
    connected.click('#saved-queries-close')
    keep(connected, 'older', 'select 1')
    keep(connected, 'newer', 'select 2')
    open_panel(connected)
    assert names_in_panel(connected) == ['newer', 'older']
    assert 'Demo shop' in connected.inner_text('#saved-queries-list .saved-item')


def test_the_filter_matches_names_and_sql(connected):
    keep(connected, 'Revenue by month', 'select sum(total) from orders')
    keep(connected, 'Who is in Germany', "select * from customers where country = 'DE'")
    open_panel(connected)
    connected.fill('#saved-queries-filter', 'revenue')
    assert names_in_panel(connected) == ['Revenue by month']
    connected.fill('#saved-queries-filter', 'country')                        # matches the SQL
    assert names_in_panel(connected) == ['Who is in Germany']
    connected.fill('#saved-queries-filter', 'zzz')
    assert names_in_panel(connected) == [] and 'No saved query matches' in connected.inner_text('#saved-queries-empty')


def test_using_a_query_puts_it_in_the_editor_but_does_not_run_it(connected):
    keep(connected, 'orders', 'select * from orders')
    new_query(connected, '')
    open_panel(connected)
    connected.click('#saved-queries-list .saved-main')
    connected.wait_for_selector('#saved-queries-modal.active', state='hidden')
    assert editor_text(connected) == 'select * from orders'
    assert connected.locator('.tab-content.active .results-grid table').count() == 0     # nothing ran


def test_using_a_query_over_existing_text_asks_first(connected):
    keep(connected, 'saved one', 'select 1')
    new_query(connected, 'select 99 -- my work in progress')
    manual_dialogs(connected)
    open_panel(connected)
    connected.click('#saved-queries-list .saved-main')
    connected.wait_for_selector('.app-dialog [data-answer=ok]')
    assert 'replaces what is in the editor' in connected.inner_text('.app-dialog-message')
    answer(connected, False)
    assert editor_text(connected) == 'select 99 -- my work in progress'              # untouched
    connected.click('#saved-queries-list .saved-main')
    connected.wait_for_selector('.app-dialog [data-answer=ok]')
    answer(connected, True)
    assert editor_text(connected) == 'select 1'


def test_new_tab_keeps_your_current_work(connected):
    keep(connected, 'saved one', 'select 1')
    new_query(connected, 'select 99')
    mine = connected.evaluate("app.tabManager.tabs.get(app.tabManager.activeTabId).title")
    tabs_before = connected.locator('.tab-label').count()
    open_panel(connected)
    connected.click('#saved-queries-list [data-act=tab]')
    connected.wait_for_function("n => document.querySelectorAll('.tab-label').length === n + 1", arg=tabs_before)
    connected.wait_for_function("document.querySelector('.tab-content.active .CodeMirror')?.CodeMirror.getValue() === 'select 1'")   # the saved query is in the new tab
    connected.click(f'.tab-label:text-is("{mine}")')
    connected.wait_for_function("document.querySelector('.tab-content.active .CodeMirror')?.CodeMirror.getValue() === 'select 99'")  # your work is still there


def test_rename(connected):
    keep(connected, 'before', 'select 1')
    keep(connected, 'other', 'select 2')
    open_panel(connected)
    manual_dialogs(connected)
    connected.locator('#saved-queries-list .saved-item', has_text='before').locator('[data-act=rename]').click()
    connected.wait_for_selector('.app-dialog-input')
    assert connected.input_value('.app-dialog-input') == 'before'               # starts from the current name
    connected.fill('.app-dialog-input', 'after')
    connected.click('.app-dialog [data-answer=ok]')
    connected.wait_for_function("() => [...document.querySelectorAll('#saved-queries-list .saved-name')].some(e => e.textContent === 'after')")
    assert sorted(q['name'] for q in stored(connected)) == ['after', 'other']
    connected.locator('#saved-queries-list .saved-item', has_text='after').locator('[data-act=rename]').click()
    connected.wait_for_selector('.app-dialog-input')
    connected.fill('.app-dialog-input', 'OTHER')                                 # another query's name
    connected.click('.app-dialog [data-answer=ok]')
    toast_with(connected, 'already exists')
    assert sorted(q['name'] for q in stored(connected)) == ['after', 'other']


def test_delete_asks_and_can_be_cancelled(connected):
    keep(connected, 'doomed', 'select 1')
    open_panel(connected)
    manual_dialogs(connected)
    connected.click('#saved-queries-list [data-act=delete]')
    connected.wait_for_selector('.app-dialog [data-answer=ok]')
    assert 'doomed' in connected.inner_text('.app-dialog-message')
    assert connected.evaluate("document.activeElement.textContent.trim()") == 'Cancel'      # the safe default
    answer(connected, False)
    assert len(stored(connected)) == 1
    connected.click('#saved-queries-list [data-act=delete]')
    connected.wait_for_selector('.app-dialog [data-answer=ok]')
    answer(connected, True)
    connected.wait_for_function("document.querySelectorAll('#saved-queries-list .saved-item').length === 0")
    assert stored(connected) == []


def test_escape_and_clicking_outside_close_the_panel(connected):
    new_query(connected, 'select 1')
    open_panel(connected)
    connected.keyboard.press('Escape')
    connected.wait_for_selector('#saved-queries-modal.active', state='hidden')
    open_panel(connected)
    connected.mouse.click(5, 5)
    connected.wait_for_selector('#saved-queries-modal.active', state='hidden')


def test_the_keyboard_can_use_a_query(connected):
    keep(connected, 'by keyboard', 'select 7')
    new_query(connected, '')
    open_panel(connected)
    connected.focus('#saved-queries-list .saved-main')
    connected.keyboard.press('Enter')
    connected.wait_for_selector('#saved-queries-modal.active', state='hidden')
    assert editor_text(connected) == 'select 7'


# ---- the command palette ----------------------------------------------------------------------------------------

def test_the_palette_opens_a_saved_query_in_a_new_tab_without_running_it(connected):
    keep(connected, 'palette query', 'select 123456')
    connected.keyboard.press('Meta+k')
    connected.fill('.palette-input', 'palette query')
    assert connected.locator('.palette-item .palette-label').all_inner_texts() == ['palette query']
    connected.keyboard.press('Enter')
    connected.wait_for_function("document.querySelector('.tab-content.active .CodeMirror') && document.querySelector('.tab-content.active .CodeMirror')?.CodeMirror.getValue() === 'select 123456'")
    assert connected.locator('.tab-content.active .results-grid table').count() == 0


def test_the_palette_action_opens_the_list(connected):
    keep(connected, 'x', 'select 1')
    connected.keyboard.press('Meta+k')
    connected.fill('.palette-input', 'saved queries')
    connected.keyboard.press('Enter')
    connected.wait_for_selector('#saved-queries-modal.active')


# ---- names and SQL are data, never markup -------------------------------------------------------------------------

def test_hostile_names_and_sql_stay_plain_text(connected):
    name = '<img src=x onerror="window.__pwned=1">'
    sql = '</code><script>window.__pwned=2</script><b>bold</b>'
    keep(connected, name, sql)
    open_panel(connected)
    assert names_in_panel(connected) == [name]
    assert connected.locator('#saved-queries-list img, #saved-queries-list script, #saved-queries-list b').count() == 0
    assert connected.inner_text('#saved-queries-list .saved-sql') == sql
    assert connected.evaluate("window.__pwned") is None
    connected.keyboard.press('Meta+k')
    connected.fill('.palette-input', 'img')
    assert connected.evaluate("window.__pwned") is None
