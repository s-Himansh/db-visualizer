"""A Mac user clicks Deny on the keychain prompt. The app used to ask again for every saved password (dozens of prompts, so Deny just brought
the next one) and then showed the connections with empty passwords and no explanation. Now it asks once, stops, says so, and offers one
deliberate Try again."""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

pytestmark = pytest.mark.e2e
ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def denied(tmp_path):
    """A server whose keychain says no, holding connections saved while it said yes. Yields (url, allow, asked)."""
    key = Fernet.generate_key()
    (tmp_path / 'keychain-key').write_text(key.decode())
    flag, log = tmp_path / 'deny', tmp_path / 'asked.log'
    flag.write_text('')
    log.write_text('')
    data = tmp_path / 'data'
    data.mkdir()
    cipher = Fernet(key)
    (data / 'connections.json').write_text(json.dumps([
        {'id': f'conn_{i}', 'name': f'Saved {i}', 'type': 'mysql', 'host': 'db.example.test', 'port': 3306, 'database': 'app', 'username': 'u',
         'password': cipher.encrypt(f'pw{i}'.encode()).decode(), 'ssh_password': cipher.encrypt(f'ssh{i}'.encode()).decode(), 'environment': 'local'}
        for i in range(1, 8)]))
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
    env = {**os.environ, 'DBV_DATA_DIR': str(data), 'DBV_KEY_STORE': 'keychain', 'PYTHON_KEYRING_BACKEND': 'denying_keyring.DenyingKeyring',
           'PYTHONPATH': str(Path(__file__).parent) + os.pathsep + os.environ.get('PYTHONPATH', ''),
           'DENY_FLAG': str(flag), 'DENY_LOG': str(log), 'KEY_FILE': str(tmp_path / 'keychain-key')}
    env.pop('ANTHROPIC_API_KEY', None)
    code = f"import sys; sys.path.insert(0, {str(ROOT)!r}); import db; db.app.run(port={port}, threaded=True)"
    proc = subprocess.Popen([sys.executable, '-c', code], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f'http://127.0.0.1:{port}/'
    for _ in range(50):
        try:
            urllib.request.urlopen(url, timeout=1)
            break
        except OSError:
            time.sleep(0.2)
    log.write_text('')                                    # the readiness probe above is not part of the story
    yield url, (lambda: flag.unlink()), (lambda: len(log.read_text().split()))
    proc.terminate()


def until(condition, seconds=8):
    end = time.time() + seconds
    while time.time() < end:
        if condition():
            return True
        time.sleep(0.2)
    return False


def open_page(browser, url):
    ctx = browser.new_context(viewport={'width': 1300, 'height': 800})
    pg = ctx.new_page()
    pg.set_default_timeout(8000)
    pg.set_default_navigation_timeout(30000)    # loading is a different wait: a slow CI runner can pass 8s (as conftest.py does for its own page)
    pg.goto(url)
    return pg


def test_deny_asks_once_then_the_app_stops_and_says_so(browser, denied):
    url, allow, asked = denied
    pg = open_page(browser, url)
    pg.wait_for_selector('.app-dialog')
    assert "can't open its keychain entry" in pg.inner_text('.app-dialog-title')
    assert 'keychain' in pg.inner_text('.app-dialog-message') and "can't be used" in pg.inner_text('.app-dialog-message')
    pg.wait_for_timeout(2500)                             # everything else the page does on load has had time to ask again
    assert asked() == 1                                   # seven connections, fourteen secrets, ONE ask


def test_continuing_leaves_a_banner_and_no_more_prompts(browser, denied):
    url, allow, asked = denied
    pg = open_page(browser, url)
    pg.wait_for_selector('.app-dialog')
    pg.click('.app-dialog [data-answer=cancel]')          # "Continue without saved passwords"
    pg.wait_for_selector('.app-dialog', state='detached')
    assert pg.is_visible('#keychain-banner') and 'locked' in pg.inner_text('#keychain-banner')
    pg.click('#manage-connections-btn')                   # people can still open the list and see what is locked
    pg.wait_for_selector('.connection-item')
    assert pg.locator('.connection-item').count() == 7
    pg.wait_for_timeout(1500)
    assert asked() == 1                                   # browsing around never asks the keychain again by itself


def test_try_again_while_still_denied_is_one_ask_per_choice_and_says_so_again(browser, denied):
    url, allow, asked = denied
    pg = open_page(browser, url)
    pg.wait_for_selector('.app-dialog')
    pg.click('.app-dialog [data-answer=ok]')              # Try again
    assert until(lambda: asked() == 2)                    # the first read, plus the one retry they chose
    pg.wait_for_selector('.app-dialog')                   # still denied: the same clear message again, for them to answer
    assert "can't open its keychain entry" in pg.inner_text('.app-dialog-title')
    pg.wait_for_timeout(1500)
    assert asked() == 2                                   # and it does not go on by itself
    assert pg.is_visible('#keychain-banner')


def test_allowing_after_a_deny_unlocks_everything(browser, denied):
    url, allow, asked = denied
    pg = open_page(browser, url)
    pg.wait_for_selector('.app-dialog')
    pg.click('.app-dialog [data-answer=cancel]')
    pg.wait_for_selector('.app-dialog', state='detached')
    allow()                                               # the person fixes it (Allow, or unlocks the keychain)
    pg.click('#keychain-unlock')
    pg.wait_for_selector('.app-dialog')
    pg.click('.app-dialog [data-answer=ok]')
    pg.wait_for_selector('#keychain-banner', state='hidden')
    assert asked() == 2
    pg.wait_for_selector('text=Saved passwords are unlocked')
    assert pg.evaluate("fetch('/api/keychain').then(r => r.json())") == {'available': True}      # (through the page: the API wants its token)
