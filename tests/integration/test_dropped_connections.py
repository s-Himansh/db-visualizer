"""A connection the server (or a firewall) drops must not strand the user: after a quiet spell the next request
re-opens it, and right after a drop at most one request fails. Run through the same wrapper the app uses, on every
database."""
import copy
import os
import tempfile
import time

import pytest

import db
from conftest import HOST, reachable
from db_connectors.redis import RedisConnector
from test_connectors import BACKENDS, Backend, ensure_cassandra_keyspace, new_connector

pytestmark = pytest.mark.integration
ALL = BACKENDS + [Backend('redis', RedisConnector, 16379, {}, db='1')]


def drop(b, wrapper, admin):
    """Make the server side of the wrapper's connection go away, the way a restart or a timeout would."""
    raw = wrapper._connector.connection
    if b.id == 'postgresql':
        cur = admin.connection.cursor()
        cur.execute('SELECT pg_terminate_backend(%s)', (raw.get_backend_pid(),))
    elif b.id == 'mysql':
        cur = admin.connection.cursor()
        cur.execute(f'KILL {raw.thread_id()}')
    elif b.id == 'sqlserver':
        cur = raw.cursor()
        cur.execute('SELECT @@SPID')
        spid = cur.fetchone()[0]
        admin.connection.autocommit(True)
        admin.connection.cursor().execute(f'KILL {spid}')
    elif b.id == 'redis':
        admin.connection.client_kill_filter(_id=raw.client_id())
    elif b.id == 'cassandra':
        raw.cluster.shutdown()
    else:                                      # sqlite, oracle, mongodb: the client object goes away
        raw.close()


def read(b, wrapper):
    if b.id == 'redis':
        return wrapper.get_table_data('*', b.db, limit=1)
    return wrapper.get_table_data('people', b.db, limit=1)


@pytest.fixture(params=ALL, ids=lambda b: b.id)
def live(request):
    b = copy.copy(request.param)      # never change the shared definition: other test files use it
    if b.port and not reachable(b.port):
        pytest.skip(f'{b.id} server not running')
    if b.id == 'sqlite':     # a private in-memory database would vanish with the connection
        b.params = {**b.params, 'database': os.path.join(tempfile.mkdtemp(), 'drop.db')}
        b.db = b.params['database']
    ensure_cassandra_keyspace(b)
    conn = new_connector(b)
    for stmt in b.ddl:
        assert not conn.execute_query(stmt).get('error'), stmt
    if b.id == 'mongodb':
        conn.connection[b.db]['people'].drop()
    if b.id == 'redis':
        conn.connection.flushdb()
        conn.connection.set('qa:1', 'x')
    else:
        for i in range(1, 4):
            assert conn.insert_row('people', {'id': i, 'name': f'n{i}', 'country': 'IN', 'score': 1}, b.db)[0]
    wrapper = db.SerializedConnector(conn)
    admin = new_connector(b) if b.id in ('postgresql', 'mysql', 'sqlserver', 'redis') else None
    yield b, wrapper, admin
    try:
        wrapper.disconnect()
    except Exception:
        pass
    if admin:
        admin.disconnect()


def test_a_connection_dropped_while_idle_is_reopened_by_the_next_request(live):
    b, wrapper, admin = live
    assert read(b, wrapper)['rows']
    drop(b, wrapper, admin)
    time.sleep(0.5)
    wrapper._last_used = time.monotonic() - db.IDLE_PING_SECONDS - 1     # it has been quiet for a while
    assert read(b, wrapper)['rows'], f'{b.id}: the request after an idle drop did not recover'


def test_right_after_a_drop_at_most_one_request_fails(live):
    b, wrapper, admin = live
    assert read(b, wrapper)['rows']
    drop(b, wrapper, admin)
    time.sleep(0.5)
    failures = 0
    for _ in range(3):
        try:
            if read(b, wrapper)['rows']:
                break
        except Exception:
            failures += 1
    else:
        pytest.fail(f'{b.id}: still failing after three requests')
    assert failures <= 1, f'{b.id}: {failures} requests failed after one drop'


def listing(b, wrapper):
    """The calls whose connectors report a failure as an empty answer instead of raising."""
    if b.id == 'redis':
        return wrapper.get_tables(b.db)
    return wrapper.get_tables(b.db)


def test_a_dropped_connection_never_looks_like_an_empty_database(live):
    b, wrapper, admin = live
    assert listing(b, wrapper), 'the fixture has data'
    drop(b, wrapper, admin)
    time.sleep(0.5)
    assert listing(b, wrapper), f'{b.id}: the table list came back empty after a drop, as if the database had no tables'
    assert listing(b, wrapper)


def test_the_schema_is_not_lost_either(live):
    b, wrapper, admin = live
    if b.id == 'redis':
        pytest.skip('a Redis schema is fixed')
    assert wrapper.get_schema('people', b.db)['columns']
    drop(b, wrapper, admin)
    time.sleep(0.5)
    assert wrapper.get_schema('people', b.db)['columns'], f'{b.id}: the schema came back empty after a drop'
