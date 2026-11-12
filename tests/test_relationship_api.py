"""Finding, accepting and ignoring undeclared relationships through the API, against a SQLite file with traps in it."""
import json
import os
import sqlite3
import stat

import pytest

import db
import relationship_inference as ri


@pytest.fixture(autouse=True)
def clean_decisions():
    for p in db.CONFIG_DIR.glob('relationship_decisions*'):
        p.unlink()
    yield
    for p in db.CONFIG_DIR.glob('relationship_decisions*'):
        p.unlink()


@pytest.fixture
def shop(tmp_path):
    path = str(tmp_path / 'shop.db')
    c = sqlite3.connect(path)
    c.executescript("""
        create table customers(id integer primary key, name text, email text unique);
        create table orders(id integer primary key, customer_id integer, status_id integer, placed_by integer);
        create table items(id integer primary key, order_id integer, note text);
        create table reviews(id integer primary key, customer_id integer, body text);
        create table payments(id integer primary key, order_id integer);
        create table notes(id integer primary key, order_id text);
        create table empty_refs(id integer primary key, customer_id integer);
        create table shipments(id integer primary key, order_id integer references orders(id));
        create table tags(label text);
        create table tagged(id integer primary key, tag_id integer);
        create table "Invoices"("Id" integer primary key, "CustomerID" integer);
        create table "Customers_Legacy"(a integer);
        create view paid_orders as select * from orders;
    """)
    c.executemany('insert into customers values(?,?,?)', [(i, f'c{i}', f'c{i}@x.com') for i in range(1, 61)])
    c.executemany('insert into orders values(?,?,?,?)', [(i, i % 60 + 1, i % 4 + 1, i % 7) for i in range(1, 201)])
    c.executemany('insert into items values(?,?,?)', [(i, i % 200 + 1, 'x') for i in range(1, 401)])
    # reviews: a fifth of the customers they point at do not exist
    c.executemany('insert into reviews values(?,?,?)', [(i, (i % 60 + 1) if i % 5 else 1000 + i, 'ok') for i in range(1, 101)])
    c.executemany('insert into payments values(?,?)', [(i, 9000 + i) for i in range(1, 30)])           # the name fits, the data does not
    c.executemany('insert into notes values(?,?)', [(i, f'word{i}') for i in range(1, 20)])              # text, against numbers
    c.executemany('insert into empty_refs(id) values(?)', [(i,) for i in range(1, 10)])
    c.executemany('insert into shipments values(?,?)', [(i, i) for i in range(1, 20)])
    c.executemany('insert into tagged values(?,?)', [(i, i) for i in range(1, 20)])
    c.executemany('insert into "Invoices" values(?,?)', [(i, i % 60 + 1) for i in range(1, 80)])
    c.commit()
    c.close()
    return path


@pytest.fixture
def cid(client, shop):
    cid = client.post('/api/connections', json={'name': 'shop', 'type': 'sqlite', 'database': shop}).get_json()['id']
    assert client.post('/api/connect', json={'id': cid}).get_json()['success']
    return cid


def inferred(client, cid, shop):
    r = client.get(f'/api/relations/inferred?connection_id={cid}&database={shop}')
    assert r.status_code == 200, r.get_json()
    return r.get_json()


def found(body):
    return {(s['table'], s['column']): s for s in body['suggestions']}


def decide(client, cid, shop, action, table, column, referenced_table, referenced_column='id', **extra):
    return client.post('/api/relations/decision', json={
        'connection_id': cid, 'database': shop, 'action': action,
        'relation': {'table': table, 'column': column, 'referenced_table': referenced_table, 'referenced_column': referenced_column}, **extra})


def relations(client, cid, shop):
    return client.get(f'/api/relations?connection_id={cid}&database={shop}').get_json()['relations']


# ---- what is found -----------------------------------------------------------------------------------------------

def test_the_real_relationships_are_found_with_their_evidence(client, cid, shop):
    got = found(inferred(client, cid, shop))
    orders = got[('orders', 'customer_id')]
    assert (orders['referenced_table'], orders['referenced_column']) == ('customers', 'id')
    assert orders['distinct'] == 60 and orders['matched'] == 60 and orders['containment'] == 1.0 and orders['confidence'] == 'high'
    assert got[('items', 'order_id')]['referenced_table'] == 'orders' and got[('items', 'order_id')]['containment'] == 1.0
    assert got[('Invoices', 'CustomerID')]['referenced_table'] == 'customers'                   # PascalCase names


def test_a_relationship_with_orphans_is_suggested_and_says_so(client, cid, shop):
    review = found(inferred(client, cid, shop))[('reviews', 'customer_id')]
    assert review['orphans'] > 0 and review['matched'] < review['distinct'] and 0.7 <= review['containment'] < ri.CLEAN_CONTAINMENT
    assert review['confidence'] == 'low'


def test_a_name_that_fits_but_data_that_does_not_is_not_suggested(client, cid, shop):
    assert ('payments', 'order_id') not in found(inferred(client, cid, shop))        # 9001.. are not orders


def test_the_traps_are_all_left_alone(client, cid, shop):
    got = found(inferred(client, cid, shop))
    assert ('notes', 'order_id') not in got              # text against numbers
    assert ('empty_refs', 'customer_id') not in got      # nothing in the column
    assert ('shipments', 'order_id') not in got          # already a declared foreign key
    assert ('tagged', 'tag_id') not in got               # the parent has no key to point at
    assert ('orders', 'status_id') not in got and ('orders', 'placed_by') not in got   # no such table / no hint in the name
    assert ('paid_orders', 'customer_id') not in got     # a view takes its relationships from its tables


def test_the_response_says_what_it_did(client, cid, shop):
    body = inferred(client, cid, shop)
    assert body['truncated'] is False and body['examined'] >= 5 and isinstance(body['seconds'], float) and body['ignored'] == 0


def test_suggestions_are_ordered_most_certain_first(client, cid, shop):
    rows = inferred(client, cid, shop)['suggestions']
    assert [r['containment'] for r in rows] == sorted((r['containment'] for r in rows), reverse=True)


def test_reading_the_suggestions_changes_nothing(client, cid, shop):
    before = relations(client, cid, shop)
    inferred(client, cid, shop)
    assert relations(client, cid, shop) == before and not db.RELATION_DECISIONS_FILE.exists()


# ---- accepting ---------------------------------------------------------------------------------------------------------

def test_an_accepted_relationship_behaves_like_a_foreign_key_and_is_not_suggested_again(client, cid, shop):
    assert decide(client, cid, shop, 'accept', 'orders', 'customer_id', 'customers', evidence={'distinct': 60, 'matched': 60, 'containment': 1.0, 'confidence': 'high'}).get_json()['success']
    rel = next(r for r in relations(client, cid, shop) if r['table'] == 'orders')
    assert rel == {'table': 'orders', 'column': 'customer_id', 'referenced_table': 'customers', 'referenced_column': 'id', 'virtual': True}
    assert ('orders', 'customer_id') not in found(inferred(client, cid, shop))
    saved = json.loads(db.RELATION_DECISIONS_FILE.read_text())[cid][shop]['accepted'][0]
    assert saved['evidence']['containment'] == 1.0 and saved['accepted_at']


def test_real_foreign_keys_are_not_marked_virtual(client, cid, shop):
    declared = next(r for r in relations(client, cid, shop) if r['table'] == 'shipments')
    assert 'virtual' not in declared


def test_accepting_twice_keeps_one_entry(client, cid, shop):
    for _ in range(2):
        decide(client, cid, shop, 'accept', 'orders', 'customer_id', 'customers')
    assert len([r for r in relations(client, cid, shop) if r['table'] == 'orders']) == 1


def test_a_declared_key_wins_over_an_accepted_one_for_the_same_column(client, cid, shop):
    decide(client, cid, shop, 'accept', 'shipments', 'order_id', 'customers')          # a wrong guess about a column that has a real key
    rels = [r for r in relations(client, cid, shop) if r['table'] == 'shipments']
    assert len(rels) == 1 and rels[0]['referenced_table'] == 'orders' and 'virtual' not in rels[0]


def test_an_accepted_relationship_is_dropped_if_its_table_goes_away(client, cid, shop):
    decide(client, cid, shop, 'accept', 'orders', 'customer_id', 'customers')
    c = sqlite3.connect(shop)
    c.execute('drop table customers')
    c.commit()
    c.close()
    assert [r for r in relations(client, cid, shop) if r['table'] == 'orders'] == []


# ---- ignoring and forgetting --------------------------------------------------------------------------------------------

def test_an_ignored_suggestion_never_comes_back_and_is_not_a_relationship(client, cid, shop):
    decide(client, cid, shop, 'ignore', 'reviews', 'customer_id', 'customers')
    body = inferred(client, cid, shop)
    assert ('reviews', 'customer_id') not in found(body) and body['ignored'] == 1
    assert not [r for r in relations(client, cid, shop) if r['table'] == 'reviews']


def test_forgetting_a_decision_brings_the_suggestion_back(client, cid, shop):
    decide(client, cid, shop, 'ignore', 'reviews', 'customer_id', 'customers')
    decide(client, cid, shop, 'forget', 'reviews', 'customer_id', 'customers')
    assert ('reviews', 'customer_id') in found(inferred(client, cid, shop))
    decide(client, cid, shop, 'accept', 'orders', 'customer_id', 'customers')
    decide(client, cid, shop, 'forget', 'orders', 'customer_id', 'customers')
    assert ('orders', 'customer_id') in found(inferred(client, cid, shop)) and not [r for r in relations(client, cid, shop) if r['table'] == 'orders']


def test_changing_your_mind_replaces_the_old_decision(client, cid, shop):
    decide(client, cid, shop, 'ignore', 'orders', 'customer_id', 'customers')
    decide(client, cid, shop, 'accept', 'orders', 'customer_id', 'customers')
    mine = json.loads(db.RELATION_DECISIONS_FILE.read_text())[cid][shop]
    assert len(mine['accepted']) == 1 and mine['ignored'] == []


def test_forgetting_something_never_decided_is_harmless(client, cid, shop):
    assert decide(client, cid, shop, 'forget', 'orders', 'customer_id', 'customers').get_json()['success']


# ---- who they belong to ---------------------------------------------------------------------------------------------------

def test_decisions_belong_to_one_connection(client, cid, shop, tmp_path):
    decide(client, cid, shop, 'accept', 'orders', 'customer_id', 'customers')
    other = client.post('/api/connections', json={'name': 'again', 'type': 'sqlite', 'database': shop}).get_json()['id']
    client.post('/api/connect', json={'id': other})
    assert not [r for r in relations(client, other, shop) if r.get('virtual')]
    assert ('orders', 'customer_id') in found(inferred(client, other, shop))


def test_deleting_a_connection_forgets_its_decisions(client, cid, shop):
    decide(client, cid, shop, 'accept', 'orders', 'customer_id', 'customers')
    decide(client, cid, shop, 'ignore', 'reviews', 'customer_id', 'customers')
    assert client.delete(f'/api/connections/{cid}').get_json()['success']
    assert cid not in json.loads(db.RELATION_DECISIONS_FILE.read_text())


# ---- refusals -----------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('body', [
    {'action': 'accept'}, {'relation': {}}, {'action': 'delete', 'relation': {'table': 'a', 'column': 'b', 'referenced_table': 'c', 'referenced_column': 'd'}},
    {'action': 'accept', 'relation': {'table': 'a', 'column': '', 'referenced_table': 'c', 'referenced_column': 'd'}},
    {'action': 'accept', 'relation': {'table': 1, 'column': 'b', 'referenced_table': 'c', 'referenced_column': 'd'}},
    {'action': 'accept', 'relation': 'orders.customer_id'}])
def test_unclear_decisions_are_refused(client, cid, shop, body):
    r = client.post('/api/relations/decision', json={'connection_id': cid, 'database': shop, **body})
    assert r.status_code == 400 and r.get_json()['success'] is False and not db.RELATION_DECISIONS_FILE.exists()


@pytest.mark.parametrize('args', [('nope', 'customer_id', 'customers'), ('orders', 'nope', 'customers'), ('orders', 'customer_id', 'nope'),
                                  ('orders', 'customer_id', 'customers', 'nope')])
def test_a_relationship_between_things_that_do_not_exist_is_refused(client, cid, shop, args):
    for action in ('accept', 'ignore'):
        r = decide(client, cid, shop, action, *args)
        assert r.status_code == 400 and 'does not exist' in r.get_json()['error']
    assert not db.RELATION_DECISIONS_FILE.exists()


def test_not_connected(client, shop):
    assert client.get('/api/relations/inferred?connection_id=conn_999').status_code == 400
    assert decide(client, 'conn_999', shop, 'accept', 'a', 'b', 'c').status_code == 400


def test_databases_that_are_not_sql_are_refused(client, cid, shop, monkeypatch):
    from db_connectors.sqlite import SQLiteConnector
    monkeypatch.setattr(SQLiteConnector, 'SUPPORTS_PROFILE', False)
    r = client.get(f'/api/relations/inferred?connection_id={cid}&database={shop}')
    assert r.status_code == 400 and 'SQL databases' in r.get_json()['error']


def test_a_read_only_connection_can_still_explore_relationships(client, shop):
    cid = client.post('/api/connections', json={'name': 'ro', 'type': 'sqlite', 'database': shop, 'read_only': True}).get_json()['id']
    client.post('/api/connect', json={'id': cid})
    assert ('orders', 'customer_id') in found(inferred(client, cid, shop))        # reading only
    assert decide(client, cid, shop, 'accept', 'orders', 'customer_id', 'customers').get_json()['success']   # app data, not the database


def test_the_search_is_cut_short_rather_than_run_forever(client, cid, shop, monkeypatch):
    monkeypatch.setattr(ri, 'TIME_BUDGET_SECONDS', -1)
    body = inferred(client, cid, shop)
    assert body['truncated'] is True and body['suggestions'] == []


# ---- the file ----------------------------------------------------------------------------------------------------------------------

def test_the_decisions_file_is_private(client, cid, shop):
    decide(client, cid, shop, 'accept', 'orders', 'customer_id', 'customers')
    assert stat.S_IMODE(os.stat(db.RELATION_DECISIONS_FILE).st_mode) == 0o600


def test_a_damaged_file_is_backed_up_and_the_app_carries_on(client, cid, shop):
    db.RELATION_DECISIONS_FILE.write_text('{ not json')
    assert relations(client, cid, shop)                                                       # still serves relationships
    assert decide(client, cid, shop, 'accept', 'orders', 'customer_id', 'customers').get_json()['success']
    assert db.RELATION_DECISIONS_FILE.with_suffix('.corrupt.json').read_text() == '{ not json'


def test_junk_in_the_file_is_ignored(client, cid, shop):
    db.RELATION_DECISIONS_FILE.write_text(json.dumps({cid: {shop: {'accepted': ['x', 5, {'table': 't'}], 'ignored': None}}}))
    assert not [r for r in relations(client, cid, shop) if r.get('virtual')]
    assert ('orders', 'customer_id') in found(inferred(client, cid, shop))


def test_the_api_needs_the_token(client, cid, shop):
    anonymous = db.app.test_client()
    assert anonymous.get(f'/api/relations/inferred?connection_id={cid}').status_code in (401, 403)
    assert anonymous.post('/api/relations/decision', json={}).status_code in (401, 403)


# ---- odd names ------------------------------------------------------------------------------------------------------------------------

def test_names_with_quotes_and_spaces_cannot_break_the_check(client, tmp_path):
    path = str(tmp_path / 'odd.db')
    c = sqlite3.connect(path)
    c.executescript('create table "we""ird parents"(id integer primary key); create table "kids"("we""ird parent id" integer);')
    c.executemany('insert into "we""ird parents" values(?)', [(i,) for i in range(1, 12)])
    c.executemany('insert into kids values(?)', [(i,) for i in range(1, 12)])
    c.commit()
    c.close()
    cid = client.post('/api/connections', json={'name': 'odd', 'type': 'sqlite', 'database': path}).get_json()['id']
    client.post('/api/connect', json={'id': cid})
    body = client.get(f'/api/relations/inferred?connection_id={cid}&database={path}').get_json()
    assert body['success'] is True and body['examined'] >= 0        # it ran, and did not fall over
    # the hint "weirdparentsid" needs a column of that name on a table named for the parent: the point is no error and no injection
    assert sqlite3.connect(path).execute('select count(*) from "we""ird parents"').fetchone() == (11,)


# ---- the sample shop is there to show this off ---------------------------------------------------------------------------------

def test_the_sample_shop_shows_the_feature_including_a_correct_no(client, tmp_path):
    from sample_data import build_sample
    path = str(build_sample(tmp_path / 'shop.db'))
    cid = client.post('/api/connections', json={'name': 'sample', 'type': 'sqlite', 'database': path}).get_json()['id']
    client.post('/api/connect', json={'id': cid})
    got = found(inferred(client, cid, path))
    assert set(got) == {('support_tickets', 'customer_id'), ('support_tickets', 'order_id'), ('wishlists', 'customer_id'),
                        ('wishlists', 'product_id'), ('coupon_redemptions', 'order_id')}
    assert got[('coupon_redemptions', 'order_id')]['orphans'] == 8 and got[('coupon_redemptions', 'order_id')]['confidence'] == 'low'
    assert got[('support_tickets', 'customer_id')]['confidence'] == 'high'
    assert not any(table == 'affiliate_clicks' for table, _ in got)           # the name fits, the data does not: the app says no
    declared = {(r['table'], r['column']) for r in relations(client, cid, path)}
    assert ('orders', 'customer_id') in declared and not declared & set(got)  # the shop's own keys are real; the add-ons are not


def test_orphan_rows_are_listed_with_their_count(client, tmp_path):
    from sample_data import build_sample
    path = str(build_sample(tmp_path / 'shop.db'))
    cid = client.post('/api/connections', json={'name': 'sample', 'type': 'sqlite', 'database': path}).get_json()['id']
    client.post('/api/connect', json={'id': cid})
    q = f'/api/relations/orphans?connection_id={cid}&database={path}&table=coupon_redemptions&column=order_id&referenced_table=orders&referenced_column=id'
    data = client.get(q).get_json()['data']
    assert data['total_count'] >= 8 and len(data['rows']) == min(data['total_count'], 20)
    ids = {i for (i,) in sqlite3.connect(path).execute('select id from orders')}
    assert all(r['order_id'] not in ids for r in data['rows'])        # every row shown really points at nothing
    assert client.get(q.replace('column=order_id', 'column=nope')).status_code == 400
