"""Browser tests: start the real app server in a subprocess and drive it with Chrome via Playwright."""
import os
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from fake_anthropic import FakeAnthropic

playwright_sync = pytest.importorskip('playwright.sync_api')
ROOT = Path(__file__).resolve().parents[2]

AUTO_ANSWER = """
window.__dialogs = []; window.__dialogAnswer = true;
new MutationObserver(() => {
  const d = document.querySelector('.app-dialog:not([data-seen])');
  if (!d) return;
  d.dataset.seen = '1';
  window.__dialogs.push(d.querySelector('.app-dialog-message').textContent);
  if (window.__dialogAnswer === 'manual') return;   // the test answers it itself
  setTimeout(() => d.querySelector(window.__dialogAnswer ? '[data-answer=ok]' : '[data-answer=cancel]').click(), 30);
}).observe(document, {childList: true, subtree: true});
"""


@pytest.fixture(scope='session')
def fake_ai_server():
    f = FakeAnthropic()
    yield f
    f.stop()


@pytest.fixture
def fake_ai(fake_ai_server):
    """The stand-in for the Anthropic API, reset for each test."""
    f = fake_ai_server
    f.requests.clear()
    f.reply('```sql\nSELECT country, COUNT(*) AS customers FROM customers GROUP BY country;\n```\nCounts customers per country.')
    return f


@pytest.fixture(scope='session')
def server(tmp_path_factory, fake_ai_server):
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
    data_dir = tmp_path_factory.mktemp('e2e-data')
    env = {**os.environ, 'DBV_DATA_DIR': str(data_dir), 'DBV_AI_BASE_URL': fake_ai_server.url}
    env.pop('ANTHROPIC_API_KEY', None)
    os.environ['E2E_SERVER_DATA_DIR'] = str(data_dir)   # lets a test reach the server's known_hosts.json
    code = f"import sys; sys.path.insert(0, {str(ROOT)!r}); import db; db.app.run(port={port}, threaded=True)"
    proc = subprocess.Popen([sys.executable, '-c', code], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f'http://127.0.0.1:{port}/'
    for _ in range(50):
        try:
            urllib.request.urlopen(url, timeout=1)
            break
        except OSError:
            time.sleep(0.2)
    yield url
    proc.terminate()


@pytest.fixture(scope='session')
def browser():
    with playwright_sync.sync_playwright() as p:
        try:
            b = p.chromium.launch(channel='chrome')
        except Exception:
            b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def demo_db(tmp_path):
    path = str(tmp_path / 'demo.db')
    s = sqlite3.connect(path)
    s.executescript("""
        create table customers(id integer primary key, name text not null, email text, country text, notes text, meta text);
        create table orders(id integer primary key, customer_id integer references customers(id), total real, status text);
        create index idx_orders_customer on orders(customer_id);
        create table items(id integer primary key, order_id integer references orders(id), sku text);
        create table reviews(id integer primary key, customer_id integer references customers(id), body text);
        create view paid_orders as select * from orders where status = 'paid';
    """)
    names = ['Ava Chen', 'Liam Patel', 'Noah Garcia', 'Mia Rossi', 'Ethan Kim']
    for i in range(1, 31):
        n = names[i % 5]
        s.execute('insert into customers values(?,?,?,?,?,?)', (
            i, n if i != 7 else "O'Brien <b>", f'{n.split()[0].lower()}{i}@example.com', ['IN', 'US', 'DE'][i % 3],
            '' if i == 2 else None if i == 3 else 'note', '{"tier": "gold", "tags": ["a", "b"]}' if i % 3 == 0 else None))
    for i in range(1, 251):
        s.execute('insert into orders values(?,?,?,?)', (i, i % 30 + 1, i * 1.5, ['paid', 'pending'][i % 2]))
    s.executemany('insert into items values(?,?,?)', [(1, 1, 'A'), (2, 1, 'B'), (3, 2, 'C'), (4, None, 'D'), (5, 250, 'E')])
    s.executemany('insert into reviews values(?,?,?)', [(1, 2, 'good'), (2, 2, 'great'), (3, 5, 'ok')])
    s.commit()
    s.close()
    return path


@pytest.fixture
def page(browser, server, demo_db):
    ctx = browser.new_context(viewport={'width': 1400, 'height': 860}, accept_downloads=True)
    pg = ctx.new_page()
    pg.set_default_timeout(6000)
    pg.errors = []
    pg.on('pageerror', lambda e: pg.errors.append(f'PAGEERROR {e}'))
    pg.on('console', lambda m: pg.errors.append(f'CONSOLE {m.text}') if m.type == 'error' else None)
    # The app has its own confirm dialog (ui.js). Answer it automatically and record what it asked.
    # Tests flip the answer with answer_dialogs(pg, False) and read the questions with dialogs(pg).
    pg.native_dialogs = []   # the browser's alert()/confirm() must never appear; see the teardown below
    pg.on('dialog', lambda d: (pg.native_dialogs.append(d.message), d.accept()))
    ctx.add_init_script(AUTO_ANSWER)
    pg.demo_db = demo_db
    pg.goto(server)
    pg.wait_for_selector('#manage-connections-btn')
    # The server is shared across tests: remove (and so disconnect) connections left by earlier tests.
    pg.evaluate("""fetch('/api/connections').then(r => r.json()).then(d =>
        Promise.all(d.connections.map(c => fetch('/api/connections/' + c.id, {method: 'DELETE'}))))""")
    pg.evaluate("""fetch('/api/ai/settings', {method: 'PUT', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({enabled: false, remove_key: true})})""")
    pg.reload()
    pg.wait_for_selector('#manage-connections-btn')
    yield pg
    ctx.close()
    assert pg.native_dialogs == [], f'native browser dialogs appeared: {pg.native_dialogs}'


def answer_dialogs(pg, accept):
    pg.evaluate(f'window.__dialogAnswer = {"true" if accept else "false"}')


def manual_dialogs(pg):
    """Stop auto-answering: the test looks at the dialog and answers it (keyboard or click)."""
    pg.evaluate("window.__dialogAnswer = 'manual'")


def dialogs(pg):
    """Text of every in-app confirm dialog shown so far."""
    return pg.evaluate('window.__dialogs || []')


def add_sqlite_connection(pg, name='Demo shop', read_only=False):
    pg.click('#manage-connections-btn')
    pg.click('#new-connection-btn-manager')
    pg.select_option('select[name=type]', 'sqlite')
    pg.fill('input[name=name]', name)
    pg.fill('input[name=database]', pg.demo_db)
    if read_only:
        pg.check('#read-only-checkbox')
    pg.click('#connection-form button[type=submit]')
    pg.wait_for_selector(f'.connection-item:has-text("{name}")')


def connect(pg, name='Demo shop'):
    pg.click(f'.connection-item:has-text("{name}") .connect-btn')
    pg.wait_for_selector('#tables-content .tree-item')
    pg.evaluate("document.querySelectorAll('.modal.active').forEach(m => m.classList.remove('active'))")


@pytest.fixture
def connected(page):
    add_sqlite_connection(page)
    connect(page)
    return page
