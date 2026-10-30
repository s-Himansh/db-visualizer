"""Table and column names come from the browser. They must be quoted (never pasted into SQL), so a name
with spaces, quotes or reserved words works, and a malicious name is just an unknown name."""
import pytest

from conftest import reachable
from test_connectors import BACKENDS, new_connector

pytestmark = pytest.mark.integration
SQL = [b for b in BACKENDS if b.id in ('sqlite', 'mysql', 'postgresql', 'sqlserver')]
# a name using every quote character any of these dialects treats as special
TABLE = 'we"ird `t` ]x;--'
COLS = ['select', 'na"me `x`]', 'from']


@pytest.fixture(scope='module', params=SQL, ids=lambda b: b.id)
def awkward(request):
    b = request.param
    if b.port and not reachable(b.port):
        pytest.skip(f'{b.id} server not running')
    conn = new_connector(b)
    text = 'TEXT' if b.id == 'sqlite' else 'VARCHAR(50)'
    conn.execute_query(f'DROP TABLE IF EXISTS {conn.q(TABLE)}')
    r = conn.execute_query(f'CREATE TABLE {conn.q(TABLE)} ({conn.q(COLS[0])} INT PRIMARY KEY, {conn.q(COLS[1])} {text}, {conn.q(COLS[2])} {text})')
    assert not r.get('error'), r['error']
    yield b, conn
    conn.execute_query(f'DROP TABLE IF EXISTS {conn.q(TABLE)}')
    conn.disconnect()


def test_names_with_quotes_spaces_and_reserved_words_work_everywhere(awkward):
    b, conn = awkward
    for i in range(1, 4):
        ok, msg = conn.insert_row(TABLE, {COLS[0]: i, COLS[1]: f'v{i}', COLS[2]: 'f'}, b.db)
        assert ok, msg
    page = conn.get_table_data(TABLE, b.db, limit=2, sort_by=COLS[0], sort_order='DESC')
    assert page['total_count'] == 3 and [r[COLS[0]] for r in page['rows']] == [3, 2]
    assert conn.get_table_data(TABLE, b.db, filters={COLS[1]: 'v2'})['total_count'] == 1
    assert conn.get_table_data(TABLE, b.db, filters={'search_term': 'v3', 'search_column': COLS[1]})['total_count'] == 1
    assert conn.update_row(TABLE, {COLS[0]: 1}, {COLS[1]: 'changed'}, b.db)[0]
    assert conn.get_table_data(TABLE, b.db, filters={COLS[1]: 'changed'})['total_count'] == 1
    assert conn.delete_row(TABLE, {COLS[0]: 3}, b.db)[0]
    assert conn.get_table_data(TABLE, b.db)['total_count'] == 2
    assert conn.get_columns(b.db, [TABLE])[TABLE] == COLS


# (Oracle is only in this group: it forbids a double-quote character inside any identifier, so the awkward-name
# test above cannot apply to it. Injection through names is still tested.)
@pytest.fixture(scope='module', params=[b for b in BACKENDS if b.id in ('sqlite', 'mysql', 'postgresql', 'sqlserver', 'oracle', 'cassandra')], ids=lambda b: b.id)
def seeded(request):
    b = request.param
    if b.port and not reachable(b.port):
        pytest.skip(f'{b.id} server not running')
    conn = new_connector(b)
    if b.id == 'sqlite':   # a private in-memory database needs its own table
        conn.execute_query('CREATE TABLE people(id INTEGER PRIMARY KEY, name TEXT)')
        conn.insert_row('people', {'id': 1, 'name': 'a'}, b.db)
    elif b.id == 'oracle':
        conn.execute_query("BEGIN EXECUTE IMMEDIATE 'DROP TABLE \"people\"'; EXCEPTION WHEN OTHERS THEN NULL; END;")
        assert not conn.execute_query('CREATE TABLE "people"("id" NUMBER(10) PRIMARY KEY, "name" VARCHAR2(50))').get('error')
        conn.insert_row('people', {'id': 1, 'name': 'a'}, b.db)
    elif b.id == 'cassandra':
        conn.execute_query('CREATE TABLE IF NOT EXISTS dbviz.people(id int PRIMARY KEY, name text)')
        conn.insert_row('people', {'id': 1, 'name': 'a'}, b.db)
    else:
        conn.execute_query('CREATE TABLE IF NOT EXISTS people(id INT PRIMARY KEY, name VARCHAR(50))')
        conn.insert_row('people', {'id': 1, 'name': 'a'}, 'dbviz' if b.id != 'sqlserver' else 'master') if conn.get_table_data('people', b.db)['total_count'] == 0 else None
    yield b, conn
    conn.disconnect()


def intact(b, conn):
    return conn.get_table_data('people', b.db)['total_count'] >= 1


@pytest.mark.parametrize('evil', ['people; DROP TABLE people', 'people" ; DROP TABLE people; --', 'people` ; DROP TABLE people; --',
                                  'people] ; DROP TABLE people; --'])
def test_injection_through_the_table_name_does_nothing(seeded, evil):
    b, conn = seeded
    with pytest.raises(Exception):
        conn.get_table_data(evil, b.db, limit=5)
    assert not conn.insert_row(evil, {'id': 9, 'name': 'x'}, b.db)[0]
    assert not conn.update_row(evil, {'id': 1}, {'name': 'x'}, b.db)[0]
    assert not conn.delete_row(evil, {'id': 1}, b.db)[0]
    assert intact(b, conn)


@pytest.mark.parametrize('evil', ['id; DROP TABLE people', 'id" , (SELECT 1) --', 'id` ; DROP TABLE people; --', '(SELECT 1)'])
def test_injection_through_sort_and_filter_names_does_nothing(seeded, evil):
    b, conn = seeded
    for kwargs in ({'sort_by': evil}, {'filters': {evil: 1}}, {'filters': {'search_term': 'a', 'search_column': evil}}):
        try:
            conn.get_table_data('people', b.db, limit=5, **kwargs)
        except Exception:
            pass  # an error is the right answer for a column that does not exist
    assert intact(b, conn)
    assert not conn.update_row('people', {evil: 1}, {'name': 'x'}, b.db)[0]
    assert not conn.insert_row('people', {evil: 1}, b.db)[0]
    assert intact(b, conn)
