import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

# Must be set before `db` is imported: it creates its data dir at import time.
os.environ['DBV_DATA_DIR'] = tempfile.mkdtemp(prefix='dbv-test-')
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db  # noqa: E402


@pytest.fixture(autouse=True)
def clean_state():
    for p in db.CONFIG_DIR.glob('connections.*'):
        p.unlink()
    db.active_connections.clear()
    yield


@pytest.fixture
def client():
    c = db.app.test_client()
    c.environ_base['HTTP_X_DBV_TOKEN'] = db.APP_TOKEN
    return c


@pytest.fixture
def sqlite_path(tmp_path):
    path = str(tmp_path / 't.db')
    s = sqlite3.connect(path)
    s.execute('create table t(id integer primary key, name text, v real)')
    s.executemany('insert into t(name,v) values(?,?)', [('alpha', 1), ('beta', 2), ("O'Brien", 3)])
    s.commit()
    s.close()
    return path


@pytest.fixture
def conn_id(client, sqlite_path):
    cid = client.post('/api/connections', json={'name': 'x', 'type': 'sqlite', 'database': sqlite_path}).get_json()['id']
    assert client.post('/api/connect', json={'id': cid}).get_json()['success']
    return cid
