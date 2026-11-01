"""Saved queries: kept on disk, named uniquely, validated, and never lost to a damaged file."""
import json
import os
import stat

import pytest

import db


@pytest.fixture(autouse=True)
def empty_store():
    for p in db.CONFIG_DIR.glob('saved_queries*'):
        p.unlink()
    yield
    for p in db.CONFIG_DIR.glob('saved_queries*'):
        p.unlink()


def save(client, name='Top customers', sql='select * from customers limit 10', **extra):
    return client.post('/api/saved-queries', json={'name': name, 'sql': sql, **extra})


def listed(client):
    return client.get('/api/saved-queries').get_json()['queries']


def test_nothing_saved_yet(client):
    assert client.get('/api/saved-queries').get_json() == {'success': True, 'queries': []}


def test_a_saved_query_is_listed_with_its_sql_exactly_as_written(client):
    sql = "select 'it''s' as x,\n       \"quoted\"  from t -- note\nwhere a <> 1;"
    r = save(client, 'Tricky ünïcode ✓', sql, connection_name='Demo shop')
    assert r.status_code == 201
    [q] = listed(client)
    assert q['name'] == 'Tricky ünïcode ✓' and q['sql'] == sql and q['connection_name'] == 'Demo shop' and q['id']


def test_it_survives_a_restart(client):
    save(client)
    assert json.loads(db.SAVED_QUERIES_FILE.read_text())[0]['name'] == 'Top customers'    # on disk, not in memory


def test_the_file_is_private_to_the_user(client):
    save(client)
    assert stat.S_IMODE(os.stat(db.SAVED_QUERIES_FILE).st_mode) == 0o600


def test_the_most_recently_changed_comes_first(client):
    a = save(client, 'a').get_json()['query']['id']
    save(client, 'b')
    assert [q['name'] for q in listed(client)] == ['b', 'a']
    client.put(f'/api/saved-queries/{a}', json={'sql': 'select 2'})            # touching a brings it to the top
    assert [q['name'] for q in listed(client)] == ['a', 'b']


def test_the_same_name_is_refused_unless_you_say_replace(client):
    first = save(client).get_json()['query']
    again = save(client, 'TOP CUSTOMERS', 'select 1')                      # names compare ignoring case
    assert again.status_code == 409 and again.get_json()['exists'] is True and again.get_json()['id'] == first['id']
    assert listed(client)[0]['sql'] == 'select * from customers limit 10'   # untouched
    replaced = save(client, 'TOP CUSTOMERS', 'select 1', replace=True)
    assert replaced.status_code == 200 and len(listed(client)) == 1 and listed(client)[0]['sql'] == 'select 1'
    assert listed(client)[0]['id'] == first['id']                          # same record, not a new one


@pytest.mark.parametrize('body', [
    {'name': '', 'sql': 'select 1'}, {'name': '   ', 'sql': 'select 1'}, {'name': 'x', 'sql': ''}, {'name': 'x', 'sql': '  \n '},
    {'name': 'x'}, {'sql': 'select 1'}, {'name': 5, 'sql': 'select 1'}, {'name': 'x', 'sql': ['select 1']},
    {'name': 'n' * 101, 'sql': 'select 1'}, {'name': 'x', 'sql': 's' * 100_001}, {}])
def test_bad_input_is_refused_and_saves_nothing(client, body):
    r = client.post('/api/saved-queries', json=body)
    assert r.status_code == 400 and r.get_json()['success'] is False
    assert listed(client) == []


def test_not_json_is_refused(client):
    assert client.post('/api/saved-queries', data='nope').status_code == 400


def test_the_limit_on_how_many_can_be_kept(client, monkeypatch):
    monkeypatch.setattr(db, 'MAX_SAVED_QUERIES', 2)
    save(client, 'a'); save(client, 'b')
    assert save(client, 'c').status_code == 400 and len(listed(client)) == 2
    assert save(client, 'a', 'select 9', replace=True).status_code == 200      # replacing is not adding


def test_rename_and_edit(client):
    qid = save(client).get_json()['query']['id']
    r = client.put(f'/api/saved-queries/{qid}', json={'name': 'Best customers'})
    assert r.status_code == 200 and listed(client)[0]['name'] == 'Best customers' and listed(client)[0]['sql'].startswith('select *')
    client.put(f'/api/saved-queries/{qid}', json={'sql': 'select 42'})
    assert listed(client)[0]['sql'] == 'select 42' and listed(client)[0]['name'] == 'Best customers'


def test_a_rename_cannot_take_another_querys_name(client):
    save(client, 'a'); b = save(client, 'b').get_json()['query']['id']
    r = client.put(f'/api/saved-queries/{b}', json={'name': 'A'})
    assert r.status_code == 409 and {q['name'] for q in listed(client)} == {'a', 'b'}
    assert client.put(f'/api/saved-queries/{b}', json={'name': 'B'}).status_code == 200      # your own name is fine


def test_changing_a_missing_query_is_a_404(client):
    assert client.put('/api/saved-queries/nope', json={'name': 'x'}).status_code == 404
    assert client.delete('/api/saved-queries/nope').status_code == 404


def test_an_edit_with_nothing_in_it_is_refused(client):
    qid = save(client).get_json()['query']['id']
    assert client.put(f'/api/saved-queries/{qid}', json={}).status_code == 400
    assert client.put(f'/api/saved-queries/{qid}', json={'name': ' '}).status_code == 400


def test_delete(client):
    a = save(client, 'a').get_json()['query']['id']; save(client, 'b')
    assert client.delete(f'/api/saved-queries/{a}').status_code == 200
    assert [q['name'] for q in listed(client)] == ['b']


def test_a_damaged_file_is_backed_up_not_overwritten(client):
    db.SAVED_QUERIES_FILE.write_text('{ this is not json')
    assert listed(client) == []                                             # the app keeps working
    assert db.SAVED_QUERIES_FILE.with_suffix('.corrupt.json').read_text() == '{ this is not json'
    assert save(client).status_code == 201                                  # and can save again
    assert db.SAVED_QUERIES_FILE.with_suffix('.corrupt.json').read_text() == '{ this is not json'   # the evidence is kept


def test_junk_entries_in_the_file_are_ignored_not_fatal(client):
    db.SAVED_QUERIES_FILE.write_text(json.dumps(['text', 5, None, {'id': 'x'}, {'id': 'ok', 'name': 'Keep', 'sql': 'select 1'}]))
    assert [q['name'] for q in listed(client)] == ['Keep']


def test_script_in_a_name_is_stored_as_plain_text(client):
    save(client, '<img src=x onerror=alert(1)>', '</script><script>alert(1)</script>')
    [q] = listed(client)
    assert q['name'] == '<img src=x onerror=alert(1)>' and '<script>' in q['sql']       # escaping is the UI's job; see the e2e test


def test_the_api_needs_the_token(client):
    anonymous = db.app.test_client()
    assert anonymous.get('/api/saved-queries').status_code in (401, 403)
    assert anonymous.post('/api/saved-queries', json={'name': 'x', 'sql': 'select 1'}).status_code in (401, 403)
    assert anonymous.delete('/api/saved-queries/x').status_code in (401, 403)


def test_saving_does_not_touch_the_other_settings(client):
    client.put('/api/theme', json={'theme': 'dark'})
    save(client)
    assert client.get('/api/theme').get_json()['theme'] == 'dark'
