"""Two people save the same row at the same moment, both having loaded the old value. Exactly one save may win; the
other must be told the row changed. Two separate connections race, as two app windows or two users would."""
import copy
import os
import tempfile
import threading

import pytest

from conftest import reachable
from db_connectors.redis import RedisConnector
from test_connectors import BACKENDS, Backend, ensure_cassandra_keyspace, new_connector

pytestmark = pytest.mark.integration
ROUNDS = 25
ALL = BACKENDS + [Backend('redis', RedisConnector, 16379, {}, db='1')]


@pytest.fixture(params=ALL, ids=lambda b: b.id)
def pair(request):
    b = copy.copy(request.param)      # never change the shared definition: other test files use it
    if b.port and not reachable(b.port):
        pytest.skip(f'{b.id} server not running')
    if b.id == 'sqlite':
        b.params = {**b.params, 'database': os.path.join(tempfile.mkdtemp(), 'race.db')}
        b.db = b.params['database']
    ensure_cassandra_keyspace(b)
    first = new_connector(b)
    for stmt in b.ddl:
        assert not first.execute_query(stmt).get('error'), stmt
    if b.id == 'mongodb':
        first.connection[b.db]['people'].drop()
    if b.id == 'redis':
        first.connection.flushdb()
    row = {'key': 'race:1', 'value': 'base'} if b.id == 'redis' else {'id': 1, 'name': 'base', 'country': 'IN', 'score': 1}
    if b.id == 'redis':
        first.connection.set('race:1', 'base')
    else:
        assert first.insert_row('people', row, b.db)[0]
    second = new_connector(b)
    yield b, first, second
    first.disconnect()
    second.disconnect()


def reset(b, conn):
    if b.id == 'redis':
        conn.connection.set('race:1', 'base')
    else:
        assert conn.update_row('people', {'id': 1}, {'name': 'base'}, b.db)[0]


def edit(b, who):
    table, cond, col = ('*', {'key': 'race:1'}, 'value') if b.id == 'redis' else ('people', {'id': 1}, 'name')
    return table, [{'op': 'update', 'conditions': cond, 'data': {col: who}, 'expected': {col: 'base'}}]


def test_exactly_one_of_two_simultaneous_saves_wins(pair):
    b, first, second = pair
    both_won = []
    for n in range(ROUNDS):
        reset(b, first)
        barrier = threading.Barrier(2)
        out = {}

        def go(conn, who):
            table, ops = edit(b, who)
            barrier.wait()
            try:
                out[who] = conn.apply_batch(table, ops, b.db)
            except Exception as e:                     # a deadlock victim is also "told": nothing was saved
                out[who] = {'success': False, 'error': str(e)}
        threads = [threading.Thread(target=go, args=(first, 'one')), threading.Thread(target=go, args=(second, 'two'))]
        [t.start() for t in threads]
        [t.join(30) for t in threads]
        wins = [w for w, r in out.items() if r.get('success')]
        if len(wins) == 2:
            both_won.append(n)
    assert not both_won, f'{b.id}: both saves succeeded in {len(both_won)} of {ROUNDS} rounds, so one overwrote the other unnoticed'
