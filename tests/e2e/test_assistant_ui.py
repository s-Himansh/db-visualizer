"""The optional SQL assistant, end to end, against a local fake of the Anthropic API."""
import sqlite3

import pytest

from conftest import answer_dialogs

pytestmark = pytest.mark.e2e
KEY = 'sk-ant-e2e-key-456'


def new_query(pg):
    pg.click('#new-query-tab-btn')
    pg.wait_for_selector('.tab-content.active .CodeMirror')


def turn_on(pg, key=KEY):
    pg.click('.tab-content.active [data-action=ask]')
    pg.wait_for_selector('#ai-settings-modal.active')
    pg.fill('#ai-key', key)
    pg.check('#ai-consent')
    pg.click('#ai-save')
    pg.wait_for_selector('#ai-settings-modal.active', state='detached')


def ask(pg, text='customers per country'):
    pg.fill('.tab-content.active .ai-input', text)
    pg.click('.tab-content.active [data-action=ai-generate]')


def editor_text(pg):
    return pg.evaluate("document.querySelector('.tab-content.active .CodeMirror').CodeMirror.getValue()")


@pytest.fixture
def ready(connected, fake_ai):
    new_query(connected)
    turn_on(connected)
    connected.click('.tab-content.active [data-action=ask]')
    connected.wait_for_selector('.tab-content.active .ai-panel', state='visible')
    return connected


# ---- turning it on -------------------------------------------------------------------------------------------

def test_asking_while_it_is_off_opens_the_settings_and_sends_nothing(connected, fake_ai):
    new_query(connected)
    connected.click('.tab-content.active [data-action=ask]')
    connected.wait_for_selector('#ai-settings-modal.active')
    assert fake_ai.requests == []
    text = connected.inner_text('#ai-settings-modal')
    assert 'names' in text and 'never sent' in text.lower() and 'row data' in text and 'passwords' in text
    assert connected.get_attribute('#ai-key', 'type') == 'password'


def test_it_will_not_turn_on_without_a_key_or_without_agreement(connected):
    new_query(connected)
    connected.click('.tab-content.active [data-action=ask]')
    connected.wait_for_selector('#ai-settings-modal.active')
    connected.click('#ai-save')
    assert 'Tick the box' in connected.inner_text('#ai-error')
    connected.check('#ai-consent')
    connected.click('#ai-save')
    assert 'API key' in connected.inner_text('#ai-error')
    assert connected.is_visible('#ai-settings-modal')


def test_turning_it_on_closes_the_dialog_and_the_key_is_never_shown_again(connected):
    new_query(connected)
    turn_on(connected)
    connected.click('.tab-content.active [data-action=ask]')
    connected.click('.tab-content.active [data-action=ai-settings]')
    connected.wait_for_selector('#ai-settings-modal.active')
    assert connected.input_value('#ai-key') == '' and 'saved' in connected.get_attribute('#ai-key', 'placeholder')
    assert KEY not in connected.content()


# ---- using it --------------------------------------------------------------------------------------------------

def test_the_starter_template_is_replaced_not_kept(ready):
    assert 'Write your SQL query here' in editor_text(ready)
    ask(ready)
    ready.wait_for_selector('.tab-content.active .ai-badge')
    assert 'Write your SQL query here' not in editor_text(ready) and 'table_name' not in editor_text(ready)


def test_the_sql_lands_in_the_editor_labelled_and_unrun(ready, fake_ai):
    ask(ready)
    ready.wait_for_selector('.tab-content.active .ai-badge')
    assert 'GROUP BY country' in editor_text(ready)
    assert ready.inner_text('.tab-content.active .ai-badge') == 'Reads data only'
    assert 'Counts customers per country' in ready.inner_text('.tab-content.active .ai-result')
    assert 'Nothing has run yet' in ready.inner_text('.tab-content.active .ai-result')
    assert ready.locator('.tab-content.active .results-grid table').count() == 0     # not executed
    assert '321 tokens' in ready.inner_text('.tab-content.active .ai-result')


def test_what_is_sent_is_names_only(ready, fake_ai):
    ask(ready)
    ready.wait_for_selector('.tab-content.active .ai-badge')
    sent = fake_ai.sent_text
    assert 'customers' in sent and 'country' in sent and 'customers per country' in sent
    for value in ('Liam Patel', 'Ava Chen', 'example.com', ready.demo_db):
        assert value not in sent
    assert fake_ai.last['headers']['x-api-key'] == KEY


def test_show_what_is_sent_displays_it_and_sends_nothing(ready, fake_ai):
    ready.fill('.tab-content.active .ai-input', 'orders per customer')
    ready.click('.tab-content.active [data-action=ai-preview]')
    ready.wait_for_selector('.tab-content.active .ai-preview pre')
    shown = ready.inner_text('.tab-content.active .ai-preview pre')
    assert '<schema>' in shown and 'orders(' in shown and 'orders per customer' in shown and 'Nothing has been sent' in ready.inner_text('.tab-content.active .ai-preview')
    assert fake_ai.requests == []
    ready.click('.tab-content.active [data-action=ai-generate]')
    ready.wait_for_selector('.tab-content.active .ai-badge')
    assert fake_ai.last['body']['messages'][0]['content'] in shown       # what was shown is what was sent


def test_it_fills_an_empty_editor_appends_below_text_and_replaces_a_selection(ready, fake_ai):
    ask(ready)
    ready.wait_for_selector('.tab-content.active .ai-badge')
    assert editor_text(ready).count('SELECT') == 1

    ready.evaluate("document.querySelector('.tab-content.active .CodeMirror').CodeMirror.setValue('SELECT 42;')")
    ready.click('.tab-content.active [data-action=ai-generate]')
    ready.wait_for_function("document.querySelector('.tab-content.active .CodeMirror').CodeMirror.getValue().includes('GROUP BY')")
    text = editor_text(ready)
    assert text.startswith('SELECT 42;') and text.count('SELECT') == 2             # what you had is still there

    ready.evaluate("""() => { const cm = document.querySelector('.tab-content.active .CodeMirror').CodeMirror;
        cm.setValue('SELECT 1;\\nSELECT old;\\nSELECT 3;'); cm.setSelection({line: 1, ch: 0}, {line: 1, ch: 11}); }""")
    ready.click('.tab-content.active [data-action=ai-generate]')
    ready.wait_for_function("!document.querySelector('.tab-content.active .CodeMirror').CodeMirror.getValue().includes('SELECT old')")
    text = editor_text(ready)
    assert 'SELECT 1;' in text and 'SELECT 3;' in text and 'GROUP BY' in text


def test_a_destructive_suggestion_is_flagged_and_changes_nothing_until_you_run_it(ready, fake_ai):
    fake_ai.reply('```sql\nDELETE FROM customers;\n```\nRemoves every customer.')
    ask(ready, 'remove all customers')
    ready.wait_for_selector('.tab-content.active .ai-badge.is-danger')
    assert 'WHERE' in ready.inner_text('.tab-content.active .ai-badge')
    assert editor_text(ready).strip() == 'DELETE FROM customers;'
    c = sqlite3.connect(ready.demo_db)
    assert c.execute('select count(*) from customers').fetchone()[0] == 30
    c.close()
    answer_dialogs(ready, False)                                                  # and running it still asks first
    ready.click('.tab-content.active [data-action=execute]')
    ready.wait_for_selector('.tab-content.active .results-info:has-text("Nothing was run")')
    c = sqlite3.connect(ready.demo_db)
    assert c.execute('select count(*) from customers').fetchone()[0] == 30
    c.close()


def test_a_statement_that_changes_data_is_called_that(ready, fake_ai):
    fake_ai.reply("```sql\nUPDATE customers SET country = 'IN' WHERE id = 1;\n```\nMoves one customer.")
    ask(ready, 'move customer 1 to India')
    ready.wait_for_selector('.tab-content.active .ai-badge.is-write')
    assert ready.inner_text('.tab-content.active .ai-badge') == 'Changes data'


def test_an_answer_with_no_sql_is_shown_as_an_explanation(ready, fake_ai):
    fake_ai.reply('There is no column for shipping address in this schema.')
    ask(ready, 'shipping addresses')
    ready.wait_for_selector('.tab-content.active .ai-explanation')
    assert 'shipping address' in ready.inner_text('.tab-content.active .ai-result')
    assert 'GROUP BY' not in editor_text(ready) and ready.locator('.tab-content.active .ai-badge').count() == 0   # the editor is untouched


def test_the_reply_is_text_never_markup(ready, fake_ai):
    fake_ai.reply('```sql\nSELECT 1; -- <img src=x onerror=window.__pwned=1>\n```\n<img src=x onerror=window.__pwned=1> <b>bold</b>')
    ask(ready)
    ready.wait_for_selector('.tab-content.active .ai-badge')
    assert ready.locator('.tab-content.active .ai-result img, .tab-content.active .ai-result b').count() == 0
    assert ready.evaluate('window.__pwned') is None


def test_cmd_enter_asks_and_escape_closes_the_panel(ready, fake_ai):
    ready.fill('.tab-content.active .ai-input', 'customers per country')
    ready.press('.tab-content.active .ai-input', 'Meta+Enter')
    ready.wait_for_selector('.tab-content.active .ai-badge')
    assert len(fake_ai.requests) == 1
    ready.press('.tab-content.active .ai-input', 'Escape')
    assert not ready.is_visible('.tab-content.active .ai-panel')


def test_asking_for_nothing_says_so_without_calling_the_api(ready, fake_ai):
    ready.click('.tab-content.active [data-action=ai-generate]')
    assert 'Describe what you want' in ready.inner_text('.tab-content.active .ai-result')
    assert fake_ai.requests == []


# ---- when it goes wrong ---------------------------------------------------------------------------------------------

def test_a_rejected_key_is_explained_in_the_panel_and_never_echoed(ready, fake_ai):
    fake_ai.fail(401, 'authentication_error')
    ask(ready)
    ready.wait_for_selector('.tab-content.active .ai-result .ai-error')
    assert 'rejected the key' in ready.inner_text('.tab-content.active .ai-result')
    assert KEY not in ready.content()


def test_rate_limit_and_outage_messages(ready, fake_ai):
    fake_ai.fail(429, 'rate_limit_error')
    ask(ready)
    ready.wait_for_selector('.tab-content.active .ai-result .ai-error')
    assert 'rate limiting' in ready.inner_text('.tab-content.active .ai-result')
    fake_ai.fail(500, 'api_error')
    ready.click('.tab-content.active [data-action=ai-generate]')
    ready.wait_for_function("document.querySelector('.tab-content.active .ai-result').innerText.includes('returned an error')")


def test_the_button_recovers_after_a_failure(ready, fake_ai):
    fake_ai.fail(500, 'api_error')
    ask(ready)
    ready.wait_for_selector('.tab-content.active .ai-result .ai-error')
    assert ready.inner_text('.tab-content.active [data-action=ai-generate]') == 'Write SQL'
    assert ready.is_enabled('.tab-content.active [data-action=ai-generate]')


# ---- turning it off ----------------------------------------------------------------------------------------------------

def test_turning_it_off_sends_the_next_ask_to_the_settings(ready, fake_ai):
    ready.click('.tab-content.active [data-action=ai-settings]')
    ready.wait_for_selector('#ai-settings-modal.active')
    ready.click('#ai-turn-off')
    ready.wait_for_selector('#ai-settings-modal.active', state='detached')
    ready.click('.tab-content.active [data-action=ask]')   # off again: Ask goes to the settings
    ready.wait_for_selector('#ai-settings-modal.active')
    ready.keyboard.press('Escape')
    ready.wait_for_selector('#ai-settings-modal.active', state='detached')
    ready.fill('.tab-content.active .ai-input', 'customers per country')
    ready.click('.tab-content.active [data-action=ai-generate]')   # a still-open panel cannot get around it
    ready.wait_for_selector('#ai-settings-modal.active')
    assert fake_ai.requests == []


def test_removing_the_key_turns_it_off(ready):
    ready.click('.tab-content.active [data-action=ai-settings]')
    ready.wait_for_selector('#ai-settings-modal.active')
    ready.click('#ai-remove-key')
    ready.wait_for_selector('#ai-settings-modal.active', state='detached')
    state = ready.evaluate("fetch('/api/ai/settings').then(r => r.json())")
    assert state['enabled'] is False and state['has_key'] is False


# ---- the palette -------------------------------------------------------------------------------------------------------------

def test_the_palette_opens_the_assistant_and_its_settings(ready):
    ready.keyboard.press('Meta+k')
    ready.keyboard.type('sql assistant settings')
    ready.keyboard.press('Enter')
    ready.wait_for_selector('#ai-settings-modal.active')
    ready.keyboard.press('Escape')
    ready.wait_for_selector('#ai-settings-modal.active', state='detached')
    ready.click('.tab-content.active [data-action=ai-close]')
    ready.keyboard.press('Meta+k')
    ready.keyboard.type('ask the sql')
    ready.keyboard.press('Enter')
    ready.wait_for_selector('.tab-content.active .ai-panel', state='visible')
