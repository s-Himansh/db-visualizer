"""The SSH tunnel through the real UI. Needs the sshd and mysql test containers (docker-compose.test.yml)."""
import os
import socket
from pathlib import Path

import pytest

from conftest import answer_dialogs, dialogs, manual_dialogs

pytestmark = pytest.mark.e2e


def up(port):
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(('127.0.0.1', port)) == 0


@pytest.fixture(autouse=True)
def tunnel_servers():
    if not (up(12222) and up(13306)):
        pytest.skip('sshd/mysql test containers not running')
    known = Path(os.environ['E2E_SERVER_DATA_DIR']) / 'known_hosts.json'
    known.unlink(missing_ok=True)   # every test starts as a first-time visitor
    yield known


def fill_form(pg, name='Via SSH', ssh_password='tunnelpw', submit=False):
    pg.click('#manage-connections-btn')
    pg.click('#new-connection-btn-manager')
    pg.select_option('select[name=type]', 'mysql')
    pg.fill('input[name=name]', name)
    pg.fill('input[name=host]', 'mysql')          # only resolvable inside the docker network
    pg.fill('input[name=port]', '3306')
    pg.fill('input[name=database]', 'dbviz')
    pg.fill('input[name=username]', 'root')
    pg.fill('input[name=password]', 'testpw')
    pg.check('#ssh-enabled-checkbox')
    pg.fill('input[name=ssh_host]', '127.0.0.1')
    pg.fill('input[name=ssh_port]', '12222')
    pg.fill('input[name=ssh_user]', 'tunnel')
    pg.fill('input[name=ssh_password]', ssh_password)
    if submit:
        pg.click('#connection-form button[type=submit]')
        pg.wait_for_selector(f'.connection-item:has-text("{name}")')


def test_ssh_fields_appear_only_when_they_apply(page):
    page.click('#manage-connections-btn')
    page.click('#new-connection-btn-manager')
    page.select_option('select[name=type]', 'mysql')
    assert page.is_visible('#ssh-toggle-group') and not page.is_visible('#ssh-fields')
    page.check('#ssh-enabled-checkbox')
    assert page.is_visible('input[name=ssh_host]') and page.is_visible('input[name=ssh_password]')
    assert not page.is_visible('input[name=ssh_key_path]')
    page.select_option('#ssh-auth-select', 'key')
    assert page.is_visible('input[name=ssh_key_path]') and page.is_visible('input[name=ssh_passphrase]')
    assert not page.is_visible('input[name=ssh_password]')
    page.select_option('select[name=type]', 'sqlite')
    assert not page.is_visible('#ssh-toggle-group') and not page.is_visible('#ssh-fields')


def test_first_connection_shows_the_fingerprint_with_cancel_as_the_default(page, tunnel_servers):
    fill_form(page, submit=True)
    answer_dialogs(page, False)
    page.click('.connection-item:has-text("Via SSH") .connect-btn')
    page.wait_for_function("window.__dialogs.length === 1", timeout=8000)      # the question was asked...
    page.wait_for_selector('.app-dialog', state='detached', timeout=5000)      # ...and answered
    asked = dialogs(page)
    assert len(asked) == 1 and 'SHA256:' in asked[0] and '127.0.0.1:12222' in asked[0]
    assert page.locator('#tables-content .tree-item').count() == 0       # declined: nothing connected
    assert not tunnel_servers.exists()                                    # ...and nothing remembered


def test_default_focus_of_the_trust_dialog_is_cancel(page):
    fill_form(page, submit=True)
    manual_dialogs(page)   # do not auto-answer: look at the dialog
    page.click('.connection-item:has-text("Via SSH") .connect-btn')
    page.wait_for_selector('.app-dialog')
    assert page.evaluate("document.activeElement.textContent.trim()") == 'Cancel'
    page.keyboard.press('Enter')
    page.wait_for_selector('.app-dialog', state='detached')
    assert page.locator('#tables-content .tree-item').count() == 0


def test_trusting_the_server_connects_and_shows_real_data_through_the_tunnel(page, tunnel_servers):
    fill_form(page, submit=True)
    page.click('.connection-item:has-text("Via SSH") .connect-btn')
    page.wait_for_selector('#tables-content .tree-item:has(.tree-label:text-is("people"))', timeout=10000)
    assert 'SHA256:' in dialogs(page)[0]
    assert tunnel_servers.exists()
    page.evaluate("document.querySelectorAll('.modal.active').forEach(m => m.classList.remove('active'))")
    page.click('#tables-content .tree-item:has(.tree-label:text-is("people"))')
    page.wait_for_selector('.tab-content.active .data-table tbody tr')
    assert '30 total rows' in page.inner_text('.tab-content.active .results-info') or page.locator('.tab-content.active tbody tr').count() >= 30


def test_second_connection_to_a_known_server_does_not_ask_again(page):
    fill_form(page, submit=True)
    page.click('.connection-item:has-text("Via SSH") .connect-btn')
    page.wait_for_selector('#tables-content .tree-item', timeout=10000)
    page.click('#manage-connections-btn')
    page.click('.connection-item:has-text("Via SSH") .connect-btn')   # disconnect
    page.wait_for_selector('#tables-content .tree-item', state='detached')
    before = len(dialogs(page))
    page.click('.connection-item:has-text("Via SSH") .connect-btn')   # connect again
    page.wait_for_selector('#tables-content .tree-item', timeout=10000)
    assert len(dialogs(page)) == before


def test_test_connection_button_works_through_the_tunnel(page):
    fill_form(page)
    page.click('#test-connection-btn')
    page.wait_for_selector('#status-message:has-text("Connection successful")', timeout=10000)
    assert 'SHA256:' in dialogs(page)[0]       # the same first-contact question, asked from the test button


def test_wrong_ssh_password_says_why(page):
    fill_form(page, ssh_password='nope')
    page.click('#test-connection-btn')
    page.wait_for_selector('#status-message:has-text("refused the login")', timeout=10000)


def test_editing_a_tunnel_connection_shows_its_settings_but_never_its_secrets(page):
    fill_form(page, submit=True)
    page.click('.connection-item:has-text("Via SSH") .edit-btn')
    assert page.is_checked('#ssh-enabled-checkbox') and page.is_visible('#ssh-fields')
    assert page.input_value('input[name=ssh_host]') == '127.0.0.1'
    assert page.input_value('input[name=ssh_user]') == 'tunnel'
    assert page.input_value('input[name=ssh_password]') == '' and page.input_value('input[name=password]') == ''
    page.fill('input[name=name]', 'Via SSH (renamed)')
    page.click('#connection-form button[type=submit]')
    page.click('.connection-item:has-text("renamed") .connect-btn')           # the saved secrets still work
    page.wait_for_selector('#tables-content .tree-item', timeout=10000)
