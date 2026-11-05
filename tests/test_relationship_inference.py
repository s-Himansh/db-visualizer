"""Inferring undeclared relationships: the name rules, the type rules, which column can be a parent, and the grading."""
import pytest

import relationship_inference as ri


# ---- names ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('table,expected', [
    ('customers', 'customer'), ('categories', 'category'), ('addresses', 'address'), ('statuses', 'status'), ('people', 'person'),
    ('status', 'status'), ('address', 'address'), ('bus', 'bus'), ('boxes', 'box'), ('Orders', 'order'), ('order_items', 'orderitem'),
    ('data', 'data'), ('analysis', 'analysis'), ('children', 'child'), ('companies', 'company'), ('batches', 'batch')])
def test_singular_of_a_table_name(table, expected):
    assert ri.singular(ri.normal(table)) == expected


@pytest.mark.parametrize('a,b', [('customer_id', 'CustomerID'), ('customer-id', 'customerId'), ('Customer ID', 'customer_id')])
def test_separators_and_case_are_ignored(a, b):
    assert ri.normal(a) == ri.normal(b) == 'customerid'


def test_hints_cover_both_the_singular_and_the_table_name_with_the_usual_suffixes():
    hints = ri.name_hints('customers')
    assert hints[0] == 'customerid' and 'customersid' in hints and 'customerkey' in hints and 'customeruuid' in hints
    assert 'id' not in hints and 'customer' not in hints                       # the bare name alone is not a reference


# ---- types ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('column_type,kind', [
    ('INTEGER', 'num'), ('bigint(20) unsigned', 'num'), ('int4', 'num'), ('smallint', 'num'), ('NUMBER(10)', 'num'), ('serial', 'num'),
    ('numeric(10,2)', 'num'), ('varchar(20)', 'text'), ('nvarchar(max)', 'text'), ('character varying', 'text'), ('uuid', 'text'),
    ('uniqueidentifier', 'text'), ('longtext', 'text'), ('VARCHAR2(40)', 'text'),
    ('point', 'other'), ('interval', 'other'), ('timestamp', 'other'), ('datetime', 'other'), ('jsonb', 'other'), (None, 'other')])
def test_kinds_of_column_types(column_type, kind):
    assert ri.kind_of(column_type) == kind


@pytest.mark.parametrize('a,b,ok', [('int', 'bigint', True), ('INTEGER', 'NUMBER(10)', True), ('varchar(10)', 'uuid', True),
                                    ('int', 'varchar(10)', False), ('text', 'integer', False), ('datetime', 'date', False),
                                    ('date', 'date', True), ('jsonb', 'jsonb', True)])
def test_which_types_can_be_compared(a, b, ok):
    assert ri.compatible(a, b) is ok


# ---- parent keys -----------------------------------------------------------------------------------------------

def schema(columns, indexes=()):
    return {'columns': [{'name': n, 'type': 'int', 'primary_key': pk} for n, pk in columns],
            'indexes': [{'name': 'i', 'columns': c, 'unique': u} for c, u in indexes]}


def test_a_single_column_primary_key_is_the_parent_key():
    assert ri.parent_key(schema([('id', True), ('name', False)]))['name'] == 'id'


def test_a_many_column_key_identifies_no_single_column():
    assert ri.parent_key(schema([('a', True), ('b', True)])) is None


def test_a_unique_index_will_do_when_there_is_no_primary_key():
    assert ri.parent_key(schema([('code', False), ('name', False)], [(['code'], True)]))['name'] == 'code'


def test_a_plain_index_or_a_many_column_unique_index_is_not_enough():
    assert ri.parent_key(schema([('a', False), ('b', False)], [(['a'], False), (['a', 'b'], True)])) is None


def test_of_two_unique_columns_the_id_like_one_wins():
    assert ri.parent_key(schema([('email', False), ('customer_id', False)], [(['email'], True), (['customer_id'], True)]))['name'] == 'customer_id'


def test_a_table_with_no_key_at_all():
    assert ri.parent_key(schema([('a', False)])) is None and ri.parent_key({}) is None


# ---- grading ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('distinct,containment,expected', [
    (500, 1.0, 'high'), (20, 0.99, 'high'), (19, 1.0, 'medium'), (5, 1.0, 'medium'), (4, 1.0, 'low'), (1, 1.0, 'low'),
    (500, 0.97, 'low'), (500, 0.7, 'low')])
def test_confidence(distinct, containment, expected):
    assert ri.confidence(distinct, containment) == expected


# ---- which columns are candidates ---------------------------------------------------------------------------------------

COLUMNS = {
    'customers': ['id', 'name'],
    'orders': ['id', 'customer_id', 'status_id', 'placed_by'],
    'order_items': ['id', 'order_id', 'product_id'],
    'products': ['id', 'sku'],
    'Invoices': ['Id', 'CustomerID', 'OrderId'],
}


def test_columns_named_after_a_table_are_candidates_and_nothing_else():
    found = ri.candidates(COLUMNS, lambda t, c: False)
    assert set(found) == {('orders', 'customer_id', 'customers'), ('order_items', 'product_id', 'products'),
                          ('order_items', 'order_id', 'orders'), ('Invoices', 'CustomerID', 'customers'),
                          ('Invoices', 'OrderId', 'orders')}
    assert not any(c == 'status_id' or c == 'placed_by' for _, c, _ in found)        # no such table, no hint
    assert not any(c.lower() == 'id' for _, c, _ in found)                            # a bare id says nothing


def test_order_id_in_order_items_points_at_orders_and_not_at_the_table_it_is_in():
    found = ri.candidates(COLUMNS, lambda t, c: False)
    assert ('order_items', 'order_id', 'orders') in found and ('order_items', 'order_id', 'order_items') not in found


def test_with_no_orders_table_there_is_nothing_for_order_id_to_point_at():
    cols = {k: v for k, v in COLUMNS.items() if k != 'orders'}
    assert not any(c.lower() == 'order_id' or c == 'OrderId' for _, c, _ in ri.candidates(cols, lambda t, c: False))


def test_a_table_is_never_its_own_parent_by_name():
    assert ri.candidates({'users': ['id', 'user_id']}, lambda t, c: False) == []


def test_columns_that_already_have_a_decision_are_skipped():
    found = ri.candidates(COLUMNS, lambda t, c: (t, c) == ('orders', 'customer_id'))
    assert ('orders', 'customer_id', 'customers') not in found


def test_a_column_hinting_at_two_tables_is_a_candidate_for_each():
    cols = {'user': ['id'], 'users': ['id'], 'posts': ['id', 'user_id']}
    assert {p for t, c, p in ri.candidates(cols, lambda t, c: False)} == {'user', 'users'}


def test_better_name_matches_come_first():
    cols = {'customers': ['id'], 'a': ['customer_id'], 'b': ['customerkey']}
    assert ri.candidates(cols, lambda t, c: False)[0][1] == 'customer_id'


# ---- inference with a stand-in connector ------------------------------------------------------------------------------------

class Fake:
    """Answers the questions infer() asks of a connector, with canned data."""

    def __init__(self, columns, schemas, checks):
        self._columns, self._schemas, self._checks, self.asked = columns, schemas, checks, []

    views = ()

    def get_columns(self, database):
        return self._columns

    def get_tables(self, database):
        return [{'name': n, 'type': 'view' if n in self.views else 'table'} for n in self._columns]

    def get_schema(self, table, database):
        return self._schemas[table]

    def check_reference(self, child, column, parent, parent_column, database, sample):
        self.asked.append((child, column, parent, parent_column, sample))
        result = self._checks[(child, column, parent)]
        if isinstance(result, Exception):
            raise result
        return result


def shop(checks):
    schemas = {'customers': {'columns': [{'name': 'id', 'type': 'INTEGER', 'primary_key': True}], 'indexes': []},
               'orders': {'columns': [{'name': 'id', 'type': 'INTEGER', 'primary_key': True}, {'name': 'customer_id', 'type': 'INTEGER'}], 'indexes': []}}
    return Fake({'customers': ['id'], 'orders': ['id', 'customer_id']}, schemas, checks)


def test_a_clean_relationship_is_suggested_with_its_evidence():
    out = ri.infer(shop({('orders', 'customer_id', 'customers'): {'distinct': 50, 'matched': 50}}), None, [], [])
    assert out['suggestions'] == [{'table': 'orders', 'column': 'customer_id', 'referenced_table': 'customers', 'referenced_column': 'id',
                                   'distinct': 50, 'matched': 50, 'containment': 1.0, 'orphans': 0, 'confidence': 'high'}]
    assert out['examined'] == 1 and out['truncated'] is False


def test_the_check_is_told_how_many_rows_to_look_at():
    fake = shop({('orders', 'customer_id', 'customers'): {'distinct': 5, 'matched': 5}})
    ri.infer(fake, None, [], [])
    assert fake.asked == [('orders', 'customer_id', 'customers', 'id', ri.SAMPLE_ROWS)]


def test_values_that_mostly_do_not_exist_in_the_parent_are_not_suggested():
    assert ri.infer(shop({('orders', 'customer_id', 'customers'): {'distinct': 50, 'matched': 10}}), None, [], [])['suggestions'] == []


def test_some_orphans_still_suggests_it_but_says_so():
    [s] = ri.infer(shop({('orders', 'customer_id', 'customers'): {'distinct': 100, 'matched': 90}}), None, [], [])['suggestions']
    assert s['orphans'] == 10 and s['confidence'] == 'low' and s['containment'] == 0.9


def test_an_empty_column_gives_nothing_to_go_on():
    assert ri.infer(shop({('orders', 'customer_id', 'customers'): {'distinct': 0, 'matched': 0}}), None, [], [])['suggestions'] == []


def test_a_check_that_fails_gives_no_suggestion_and_does_not_stop_the_rest():
    assert ri.infer(shop({('orders', 'customer_id', 'customers'): RuntimeError('cannot compare')}), None, [], [])['suggestions'] == []


def test_declared_and_decided_columns_are_not_looked_at_again():
    fake = shop({('orders', 'customer_id', 'customers'): {'distinct': 5, 'matched': 5}})
    declared = [{'table': 'orders', 'column': 'customer_id', 'referenced_table': 'customers', 'referenced_column': 'id'}]
    assert ri.infer(fake, None, declared, [])['suggestions'] == [] and fake.asked == []
    fake2 = shop({('orders', 'customer_id', 'customers'): {'distinct': 5, 'matched': 5}})
    assert ri.infer(fake2, None, [], declared)['suggestions'] == [] and fake2.asked == []


def test_incompatible_types_are_never_compared():
    fake = shop({})
    fake._schemas['orders']['columns'][1]['type'] = 'varchar(20)'
    assert ri.infer(fake, None, [], [])['suggestions'] == [] and fake.asked == []


def test_a_parent_without_a_unique_key_is_skipped():
    fake = shop({})
    fake._schemas['customers']['columns'][0]['primary_key'] = False
    assert ri.infer(fake, None, [], [])['suggestions'] == [] and fake.asked == []


def test_the_time_budget_stops_the_search_and_says_so():
    fake = shop({('orders', 'customer_id', 'customers'): {'distinct': 5, 'matched': 5}})
    out = ri.infer(fake, None, [], [], budget=-1)
    assert out['truncated'] is True and out['suggestions'] == [] and fake.asked == []


def test_too_many_candidates_are_cut_and_flagged():
    columns = {f't{i}': ['id', 'parent_id'] for i in range(5)}
    columns['parent'] = ['id']
    out = ri.infer(Fake(columns, {}, {}), None, [], [], limit=2)
    assert out['truncated'] is True


def test_when_two_tables_fit_the_better_supported_one_is_kept():
    schemas = {t: {'columns': [{'name': 'id', 'type': 'int', 'primary_key': True}], 'indexes': []} for t in ('user', 'users')}
    schemas['posts'] = {'columns': [{'name': 'id', 'type': 'int', 'primary_key': True}, {'name': 'user_id', 'type': 'int'}], 'indexes': []}
    fake = Fake({'user': ['id'], 'users': ['id'], 'posts': ['id', 'user_id']}, schemas,
                {('posts', 'user_id', 'user'): {'distinct': 30, 'matched': 12}, ('posts', 'user_id', 'users'): {'distinct': 30, 'matched': 30}})
    [s] = ri.infer(fake, None, [], [])['suggestions']
    assert s['referenced_table'] == 'users'


def test_the_most_certain_suggestions_come_first():
    cols = {'customers': ['id'], 'products': ['id'], 'orders': ['id', 'customer_id', 'product_id']}
    key = {'columns': [{'name': 'id', 'type': 'int', 'primary_key': True}], 'indexes': []}
    schemas = {'customers': key, 'products': key, 'orders': {'columns': [{'name': 'id', 'type': 'int', 'primary_key': True},
               {'name': 'customer_id', 'type': 'int'}, {'name': 'product_id', 'type': 'int'}], 'indexes': []}}
    fake = Fake(cols, schemas, {('orders', 'customer_id', 'customers'): {'distinct': 100, 'matched': 90},
                                ('orders', 'product_id', 'products'): {'distinct': 100, 'matched': 100}})
    assert [s['column'] for s in ri.infer(fake, None, [], [])['suggestions']] == ['product_id', 'customer_id']


def test_a_table_whose_name_is_only_punctuation_cannot_make_every_id_column_a_reference():
    assert ri.candidates({'_': ['id'], 'things': ['id', 'x']}, lambda t, c: False) == []


def test_views_are_neither_parents_nor_children():
    fake = shop({('orders', 'customer_id', 'customers'): {'distinct': 5, 'matched': 5}})
    fake._columns['paid_orders'] = ['id', 'customer_id']
    fake._schemas['paid_orders'] = fake._schemas['orders']
    fake._checks[('paid_orders', 'customer_id', 'customers')] = {'distinct': 5, 'matched': 5}
    fake.views = ('paid_orders',)
    assert [s['table'] for s in ri.infer(fake, None, [], [])['suggestions']] == ['orders']
    assert not any(a[0] == 'paid_orders' for a in fake.asked)


def test_a_connector_that_cannot_list_tables_still_works():
    fake = shop({('orders', 'customer_id', 'customers'): {'distinct': 5, 'matched': 5}})
    fake.get_tables = lambda database: (_ for _ in ()).throw(RuntimeError('no catalog'))
    assert len(ri.infer(fake, None, [], [])['suggestions']) == 1
