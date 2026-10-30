"""Redis has keys, not tables: a "table" is a key pattern (`user:*`) and a row is one key."""
import pytest

from conftest import HOST, reachable
from db_connectors.redis import RedisConnector

pytestmark = pytest.mark.integration
PORT = 16379
DB = 'db1'  # a scratch database, so the tests never touch db0


@pytest.fixture(scope='module')
def r():
    if not reachable(PORT):
        pytest.skip('redis server not running on 16379')
    c = RedisConnector({'type': 'redis', 'host': HOST, 'port': PORT, 'database': 1})
    assert c.connect()
    c.connection.flushdb()
    for i in range(1, 31):
        c.connection.set(f'user:{i:02d}', f'name-{i}')
    c.connection.hset('session:abc', mapping={'user': '7', 'ip': '10.0.0.1'})
    c.connection.rpush('queue:jobs', 'a', 'b', 'c')
    yield c
    c.connection.flushdb()
    c.disconnect()


def page(r, pattern='user:*', **kw):
    return r.get_table_data(pattern, DB, **kw)


def keys(result):
    return [row['key'] for row in result['rows']]


def test_groups_keys_by_prefix(r):
    tables = {t['name']: t for t in r.get_tables(DB)}
    assert tables['user:*']['rows'] == 30 and 'session:*' in tables and 'queue:*' in tables


def test_total_count_is_the_real_total_not_the_page_size(r):
    result = page(r, limit=10, offset=0)
    assert result['total_count'] == 30 and len(result['rows']) == 10 and result['has_more'] is True


def test_every_page_is_reachable_and_disjoint(r):
    seen = []
    for offset in (0, 10, 20):
        result = page(r, limit=10, offset=offset)
        seen += keys(result)
        assert result['has_more'] is (offset < 20)
    assert len(seen) == 30 and len(set(seen)) == 30


def test_paging_order_is_stable(r):
    assert keys(page(r, limit=10)) == keys(page(r, limit=10)) == [f'user:{i:02d}' for i in range(1, 11)]


def test_sort_by_key_descending(r):
    assert keys(page(r, limit=3, sort_by='key', sort_order='DESC')) == ['user:30', 'user:29', 'user:28']


def test_search_matches_key_text(r):
    result = page(r, filters={'search_term': 'USER:1'}, limit=100)  # user:10..user:19
    assert result['total_count'] == 10 and all(k.startswith('user:1') for k in keys(result))
    assert page(r, filters={'search_term': 'nomatch'}, limit=10)['total_count'] == 0


def test_shows_value_type_and_ttl(r):
    row = page(r, 'session:*')['rows'][0]
    assert row['type'] == 'hash' and '10.0.0.1' in row['value']
    r.connection.set('ttl:one', 'x', ex=100)
    assert 0 < page(r, 'ttl:*')['rows'][0]['ttl'] <= 100


def test_insert_update_delete_roundtrip(r):
    assert r.insert_row('user:*', {'key': 'tmp:1', 'value': 'v1'}, DB)[0]
    assert page(r, 'tmp:*')['rows'][0]['value'] == 'v1'
    assert r.update_row('tmp:*', {'key': 'tmp:1'}, {'value': 'v2'}, DB)[0]
    assert page(r, 'tmp:*')['rows'][0]['value'] == 'v2'
    assert r.delete_row('tmp:*', {'key': 'tmp:1'}, DB)[0]
    assert page(r, 'tmp:*')['total_count'] == 0


def test_update_and_delete_of_missing_key_report_failure_without_creating_it(r):
    assert r.update_row('x', {'key': 'ghost'}, {'value': 'v'}, DB)[0] is False
    assert r.delete_row('x', {'key': 'ghost'}, DB)[0] is False
    assert not r.connection.exists('ghost')


def test_insert_requires_a_key(r):
    ok, msg = r.insert_row('x', {'value': 'v'}, DB)
    assert not ok and 'Key' in msg


def test_execute_command(r):
    result = r.execute_query('GET user:01')
    assert not result.get('error') and 'name-1' in str(result['rows'])
    assert r.execute_query('NOTACOMMAND')['error']


def test_large_keyspace_reports_real_total_and_pages(r):
    """SCAN returns ~100 keys per call, so a naive "stop after offset+limit keys" caps the total."""
    pipe = r.connection.pipeline()
    for i in range(1000):
        pipe.set(f'big:{i:04d}', i)
    pipe.execute()
    first = page(r, 'big:*', limit=10, offset=0)
    assert first['total_count'] == 1000 and first['has_more'] is True
    assert keys(page(r, 'big:*', limit=10, offset=990)) == [f'big:{i:04d}' for i in range(990, 1000)]
    assert page(r, 'big:*', limit=10, offset=990)['has_more'] is False
