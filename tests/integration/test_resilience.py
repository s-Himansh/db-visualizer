"""Cancel and reconnect against real servers, through the same wrapper the app uses."""
import threading
import time

import pytest

import db
from conftest import reachable
from test_connectors import BACKENDS, new_connector

pytestmark = pytest.mark.integration
SERVERS = [b for b in BACKENDS if b.id in ('postgresql', 'mysql')]
SLOW = {  # a query that takes far longer than the test will wait
    'postgresql': 'SELECT pg_sleep(60)',
    'mysql': 'SELECT COUNT(*) FROM information_schema.columns a, information_schema.columns b, information_schema.columns c',
}


@pytest.fixture(params=SERVERS, ids=lambda b: b.id)
def live(request):
    b = request.param
    if not reachable(b.port):
        pytest.skip(f'{b.id} server not running')
    wrapper = db.SerializedConnector(new_connector(b))
    yield b, wrapper
    wrapper.disconnect()


def test_cancel_stops_a_long_query_on_the_server(live):
    b, w = live
    out = {}
    t = threading.Thread(target=lambda: out.update(r=w.execute_query(SLOW[b.id])))
    t.start()
    time.sleep(1.0)
    started = time.time()
    assert w.cancel() is True
    t.join(15)
    assert not t.is_alive() and time.time() - started < 10
    assert out['r']['error']                                  # reported as an error, not a hang
    assert w.execute_query('SELECT 1')['error'] is None       # and the connection is still good


def test_reconnects_after_the_server_drops_the_connection(live):
    b, w = live
    admin = new_connector(b)
    raw = w._connector.connection
    if b.id == 'postgresql':
        pid = raw.get_backend_pid()
        cur = admin.connection.cursor()
        cur.execute('SELECT pg_terminate_backend(%s)', (pid,))
    else:
        cur = admin.connection.cursor()
        cur.execute(f'KILL {raw.thread_id()}')
    time.sleep(0.5)
    w._last_used -= 120   # the app notices only when it next uses the connection
    result = w.get_table_data('people', b.db, limit=1)
    assert result['total_count'] == 30
    assert w._connector.connection is not raw  # it really opened a new connection
    admin.disconnect()
