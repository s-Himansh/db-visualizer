"""CSV import through the HTTP API, against a real SQLite file: preview, mapping, all-or-nothing, dry run, limits."""
import io
import json
import sqlite3

import pytest

import csv_import
import db


@pytest.fixture
def people(tmp_path):
    path = str(tmp_path / 'people.db')
    c = sqlite3.connect(path)
    c.execute('create table people(id integer primary key, name text not null, age int, joined date, note text, score real default 1.5)')
    c.execute("insert into people(id, name) values (1, 'Existing')")
    c.commit()
    c.close()
    return path


@pytest.fixture
def cid(client, people):
    cid = client.post('/api/connections', json={'name': 'p', 'type': 'sqlite', 'database': people}).get_json()['id']
    assert client.post('/api/connect', json={'id': cid}).get_json()['success']
    return cid


def sql(path, query):
    c = sqlite3.connect(path)
    try:
        return c.execute(query).fetchall()
    finally:
        c.close()


def form(cid, path, text, **extra):
    data = {'connection_id': cid, 'database': path, 'table': 'people', 'file': (io.BytesIO(text if isinstance(text, bytes) else text.encode()), 'f.csv')}
    data.update({k: v if isinstance(v, (str, bytes)) else json.dumps(v) for k, v in extra.items()})
    return data


def preview(client, cid, path, text, **extra):
    return client.post('/api/import/preview', data=form(cid, path, text, **extra), content_type='multipart/form-data')


def do_import(client, cid, path, text, mapping, **extra):
    return client.post('/api/import', data=form(cid, path, text, mapping=mapping, **extra), content_type='multipart/form-data')


GOOD = 'id,Name,age,joined\n10,Ann,31,2026-03-04\n11,Bo,,2026-01-02\n12,Cy,45,\n'
ALL = {'id': 0, 'name': 1, 'age': 2, 'joined': 3}


# ---- preview ---------------------------------------------------------------------------------------------------

def test_preview_describes_the_file_and_the_table(client, cid, people):
    body = preview(client, cid, people, GOOD).get_json()
    assert body['success'] and body['headers'] == ['id', 'Name', 'age', 'joined'] and body['total_rows'] == 3
    assert body['delimiter'] == 'comma' and body['has_header'] is True and body['problems'] == []
    assert body['sample_rows'][0] == ['10', 'Ann', '31', '2026-03-04']
    assert body['suggested_mapping'] == {'id': 0, 'name': 1, 'age': 2, 'joined': 3, 'note': None, 'score': None}
    required = {c['name']: c['required'] for c in body['table_columns']}
    assert required == {'id': False, 'name': True, 'age': False, 'joined': False, 'note': False, 'score': False}


def test_preview_shows_at_most_five_rows_but_counts_them_all(client, cid, people):
    body = preview(client, cid, people, 'id,name\n' + ''.join(f'{i},n{i}\n' for i in range(40))).get_json()
    assert len(body['sample_rows']) == 5 and body['total_rows'] == 40


def test_preview_detects_other_delimiters_and_accepts_overrides(client, cid, people):
    semi = 'id;name\n1;"Smith, J"\n'
    assert preview(client, cid, people, semi).get_json()['delimiter'] == 'semicolon'
    forced = preview(client, cid, people, semi, delimiter='comma').get_json()
    assert forced['headers'] == ['id;name']
    assert preview(client, cid, people, semi, delimiter='tab').get_json()['delimiter'] == 'tab'


def test_preview_without_a_header_row(client, cid, people):
    body = preview(client, cid, people, '1,Ann\n2,Bo\n', has_header='false').get_json()
    assert body['headers'] == ['Column 1', 'Column 2'] and body['total_rows'] == 2


def test_preview_reports_problems_with_the_file(client, cid, people):
    body = preview(client, cid, people, 'id,name\n1\n2,Bo\n').get_json()
    assert body['success'] and body['problems'] == ['Row 1 has 1 value but there are 2 columns.']


@pytest.mark.parametrize('text,status', [('', 400), (b'PK\x03\x04\x00\x00', 400)])
def test_preview_refuses_unreadable_files(client, cid, people, text, status):
    r = preview(client, cid, people, text)
    assert r.status_code == status and r.get_json()['success'] is False


def test_a_header_row_with_nothing_under_it_previews_with_an_explanation(client, cid, people):
    body = preview(client, cid, people, 'Hal Nine,hal@example.com\n').get_json()
    assert body['success'] and body['total_rows'] == 0 and 'untick' in body['problems'][0]
    assert do_import(client, cid, people, 'Hal Nine,hal@example.com\n', {'name': 0}).status_code == 400      # but cannot be imported
    again = preview(client, cid, people, 'Hal Nine,hal@example.com\n', has_header='false').get_json()
    assert again['total_rows'] == 1 and again['problems'] == []


def test_preview_of_a_table_that_does_not_exist(client, cid, people):
    data = form(cid, people, GOOD)
    data['table'] = 'nope'
    r = client.post('/api/import/preview', data=data, content_type='multipart/form-data')
    assert r.status_code == 404 and 'not found' in r.get_json()['error']


def test_a_bad_delimiter_name_is_refused(client, cid, people):
    assert preview(client, cid, people, GOOD, delimiter='space').status_code == 400


@pytest.mark.parametrize('drop', ['file', 'table', 'connection_id'])
def test_missing_pieces_are_refused(client, cid, people, drop):
    for url in ('/api/import/preview', '/api/import'):
        data = form(cid, people, GOOD)                    # a fresh upload stream each time: a request consumes it
        del data[drop]
        assert client.post(url, data=data, content_type='multipart/form-data').status_code == 400


def test_not_connected(client, people):
    r = client.post('/api/import/preview', data=form('conn_999', people, GOOD), content_type='multipart/form-data')
    assert r.status_code == 400 and 'Not connected' in r.get_json()['error']


# ---- importing --------------------------------------------------------------------------------------------------

def test_import_inserts_every_row_with_values_the_database_converts(client, cid, people):
    r = do_import(client, cid, people, GOOD, ALL)
    assert r.get_json() == {'success': True, 'imported': 3, 'dry_run': False}
    assert sql(people, 'select id, name, age, joined, typeof(age) from people where id >= 10 order by id') == [
        (10, 'Ann', 31, '2026-03-04', 'integer'), (11, 'Bo', None, '2026-01-02', 'null'), (12, 'Cy', 45, None, 'integer')]


def test_unmapped_columns_get_their_defaults(client, cid, people):
    do_import(client, cid, people, 'name\nAnn\n', {'name': 0})
    assert sql(people, "select name, age, score from people where name = 'Ann'") == [('Ann', None, 1.5)]


def test_empty_values_are_null_unless_you_say_otherwise(client, cid, people):
    do_import(client, cid, people, 'id,name,note\n20,A,\n', {'id': 0, 'name': 1, 'note': 2})
    do_import(client, cid, people, 'id,name,note\n21,B,\n', {'id': 0, 'name': 1, 'note': 2}, empty_as_null='false')
    assert sql(people, 'select id, note from people where id in (20, 21) order by id') == [(20, None), (21, '')]


def test_the_file_can_have_its_columns_in_any_order_and_extras(client, cid, people):
    do_import(client, cid, people, 'junk,note,name,id\nx,hello,Zed,30\n', {'id': 3, 'name': 2, 'note': 1})
    assert sql(people, 'select id, name, note from people where id = 30') == [(30, 'Zed', 'hello')]


def test_quotes_commas_newlines_and_unicode_survive(client, cid, people):
    text = 'id,name,note\n40,"Smith, ""Jo""","line1\nline2 ✓"\n'.encode('utf-8-sig')
    assert do_import(client, cid, people, text, {'id': 0, 'name': 1, 'note': 2}).get_json()['success']
    assert sql(people, 'select name, note from people where id = 40') == [('Smith, "Jo"', 'line1\nline2 ✓')]


def test_a_windows_excel_file(client, cid, people):
    text = 'id;name\r\n50;José\r\n'.encode('cp1252')
    assert do_import(client, cid, people, text, {'id': 0, 'name': 1}).get_json()['imported'] == 1
    assert sql(people, 'select name from people where id = 50') == [('José',)]


def test_without_a_header_row(client, cid, people):
    r = do_import(client, cid, people, '60,Ann\n61,Bo\n', {'id': 0, 'name': 1}, has_header='false')
    assert r.get_json()['imported'] == 2 and sql(people, 'select count(*) from people where id in (60, 61)') == [(2,)]


# ---- all or nothing ----------------------------------------------------------------------------------------------

def test_one_bad_row_imports_nothing_and_names_the_row(client, cid, people):
    text = 'id,name\n70,Fine\n71,AlsoFine\n1,Duplicate of an existing id\n72,Never reached\n'
    r = do_import(client, cid, people, text, {'id': 0, 'name': 1})
    body = r.get_json()
    assert r.status_code == 422 and body['success'] is False and body['row'] == 3 and body['rolled_back'] is True
    assert body['error'].startswith('Row 3:')
    assert sql(people, 'select count(*) from people') == [(1,)]                         # only the original row


def test_a_not_null_violation_in_the_last_row_still_rolls_everything_back(client, cid, people):
    r = do_import(client, cid, people, 'id,name\n80,A\n81,B\n82,\n', {'id': 0, 'name': 1})
    assert r.status_code == 422 and r.get_json()['row'] == 3
    assert sql(people, 'select count(*) from people where id >= 80') == [(0,)]


def test_the_connection_still_works_after_a_failed_import(client, cid, people):
    do_import(client, cid, people, 'id,name\n1,dup\n', {'id': 0, 'name': 1})
    assert do_import(client, cid, people, 'id,name\n90,ok\n', {'id': 0, 'name': 1}).get_json()['success']


# ---- dry run ------------------------------------------------------------------------------------------------------

def test_a_dry_run_reports_success_and_writes_nothing(client, cid, people):
    r = do_import(client, cid, people, GOOD, ALL, dry_run='true').get_json()
    assert r == {'success': True, 'imported': 3, 'dry_run': True}
    assert sql(people, 'select count(*) from people') == [(1,)]


def test_a_dry_run_finds_the_same_errors_a_real_import_would(client, cid, people):
    r = do_import(client, cid, people, 'id,name\n1,dup\n', {'id': 0, 'name': 1}, dry_run='true')
    assert r.status_code == 422 and r.get_json()['row'] == 1 and sql(people, 'select count(*) from people') == [(1,)]


def test_a_dry_run_then_the_real_thing(client, cid, people):
    do_import(client, cid, people, GOOD, ALL, dry_run='true')
    assert do_import(client, cid, people, GOOD, ALL).get_json()['imported'] == 3
    assert sql(people, 'select count(*) from people') == [(4,)]


# ---- refusals --------------------------------------------------------------------------------------------------------

def test_dates_in_an_unambiguous_layout_are_accepted_and_tidied(client, cid, people):
    text = 'id,name,joined\n201,A,2026-03-04\n202,B,2026-03-04T10:20:30\n203,C,\n'
    assert do_import(client, cid, people, text, {'id': 0, 'name': 1, 'joined': 2}).get_json()['imported'] == 3
    assert sql(people, 'select id, joined from people where id > 200 order by id') == [(201, '2026-03-04'), (202, '2026-03-04 10:20:30'), (203, None)]


@pytest.mark.parametrize('bad', ['04/03/2026', '4 Mar 2026', '2026-02-30', 'soon'])
def test_a_date_that_could_be_read_the_wrong_way_round_is_refused_with_its_row(client, cid, people, bad):
    text = f'id,name,joined\n210,Fine,2026-03-04\n211,Bad,{bad}\n'
    r = do_import(client, cid, people, text, {'id': 0, 'name': 1, 'joined': 2})
    body = r.get_json()
    assert r.status_code == 400 and body['error'].startswith('Row 2, "joined"') and bad in body['error']
    assert sql(people, 'select count(*) from people') == [(1,)]                           # nothing imported, not even row 1


def test_the_date_rule_does_not_touch_text_columns_or_unmapped_date_columns(client, cid, people):
    text = 'id,name,note,joined\n220,A,04/03/2026,not a date\n'
    assert do_import(client, cid, people, text, {'id': 0, 'name': 1, 'note': 2}).get_json()['imported'] == 1     # joined is not mapped
    assert sql(people, 'select note from people where id = 220') == [('04/03/2026',)]


def test_a_dry_run_also_catches_bad_dates(client, cid, people):
    r = do_import(client, cid, people, 'id,name,joined\n230,A,04/03/2026\n', {'id': 0, 'name': 1, 'joined': 2}, dry_run='true')
    assert r.status_code == 400 and 'wrong way round' in r.get_json()['error']


def test_a_file_with_ragged_rows_is_refused_before_touching_the_table(client, cid, people):
    r = do_import(client, cid, people, 'id,name\n95,A\n96\n', {'id': 0, 'name': 1})
    assert r.status_code == 400 and 'Row 2 has 1 value' in r.get_json()['error']
    assert sql(people, 'select count(*) from people') == [(1,)]


@pytest.mark.parametrize('mapping', [None, {}, {'id': None}, {'nope': 0}, {'id': 9}, 'text', [0]])
def test_unusable_mappings_are_refused(client, cid, people, mapping):
    r = do_import(client, cid, people, GOOD, mapping)
    assert r.status_code == 400 and sql(people, 'select count(*) from people') == [(1,)]


def test_a_mapping_that_is_not_json(client, cid, people):
    data = form(cid, people, GOOD, mapping='{not json')
    assert client.post('/api/import', data=data, content_type='multipart/form-data').status_code == 400


def test_too_many_rows(client, cid, people, monkeypatch):
    monkeypatch.setattr(csv_import, 'MAX_IMPORT_ROWS', 2)
    r = do_import(client, cid, people, GOOD, ALL)
    assert r.status_code == 400 and 'At most 2' in r.get_json()['error'] and sql(people, 'select count(*) from people') == [(1,)]


def test_a_read_only_connection_cannot_import(client, people):
    cid = client.post('/api/connections', json={'name': 'ro', 'type': 'sqlite', 'database': people, 'read_only': True}).get_json()['id']
    client.post('/api/connect', json={'id': cid})
    for url in ('/api/import', '/api/import/preview'):
        r = client.post(url, data=form(cid, people, GOOD, mapping=ALL), content_type='multipart/form-data')
        assert r.status_code == 403 and r.get_json()['read_only'] is True
    assert sql(people, 'select count(*) from people') == [(1,)]


def test_a_database_that_cannot_roll_back_is_refused(client, cid, people, monkeypatch):
    from db_connectors.sqlite import SQLiteConnector
    monkeypatch.setattr(SQLiteConnector, 'SUPPORTS_TRANSACTIONS', False)
    r = do_import(client, cid, people, GOOD, ALL)
    assert r.status_code == 400 and 'roll back' in r.get_json()['error'] and sql(people, 'select count(*) from people') == [(1,)]


def test_a_huge_upload_is_refused_with_json(client, cid, people):
    r = do_import(client, cid, people, b'id,name\n' + b'1,x\n' * (6 * 1024 * 1024), ALL)
    assert r.status_code == 413 and r.get_json()['success'] is False


def test_the_api_needs_the_token(client, cid, people):
    anonymous = db.app.test_client()
    for url in ('/api/import', '/api/import/preview'):
        assert anonymous.post(url, data=form(cid, people, GOOD), content_type='multipart/form-data').status_code in (401, 403)


# ---- hostile input -------------------------------------------------------------------------------------------------------

def test_sql_in_values_and_headers_is_just_text(client, cid, people):
    evil = "x'); drop table people; --"
    text = f'id,"{evil}",name\n100,"{evil}","{evil}"\n'
    assert preview(client, cid, people, text).get_json()['suggested_mapping']['name'] == 2
    assert do_import(client, cid, people, text, {'id': 0, 'name': 2}).get_json()['success']
    assert sql(people, 'select name from people where id = 100') == [(evil,)] and sql(people, 'select count(*) from people') == [(2,)]
    assert do_import(client, cid, people, text, {evil: 1}).status_code == 400            # a header name is never a column


def test_ten_thousand_rows(client, cid, people):
    text = 'id,name\n' + ''.join(f'{1000 + i},person {i}\n' for i in range(10_000))
    assert do_import(client, cid, people, text, {'id': 0, 'name': 1}).get_json()['imported'] == 10_000
    assert sql(people, 'select count(*), min(id), max(id) from people where id >= 1000') == [(10_000, 1000, 10_999)]
