"""Find the relationships a database has but never declared.

Many databases have no foreign keys: legacy schemas, MySQL MyISAM tables, SQLite (which does not enforce them), or
keys dropped for speed. The app's links and schema map only know declared keys, so here the missing ones are inferred
from what the database itself shows:

  1. Names. `orders.customer_id` looks like it points at `customers`. A bare `id`, or a name that matches no table,
     is never guessed at.
  2. Types. The two columns must hold the same kind of value (numbers with numbers, text with text).
  3. Data. The first rows of the child column are checked against the parent's key. Most of the values must exist there.

The parent column must be unique (a single-column primary key or unique index), or "points at" has no meaning.
Nothing is applied automatically: each suggestion carries its evidence for the user to accept or ignore.
"""
import re
import time
from typing import Any, Dict, List, Optional, Tuple

SAMPLE_ROWS = 2000            # rows of the child column that are looked at
MIN_CONTAINMENT = 0.7         # share of the sampled distinct values that must exist in the parent to suggest it at all
CLEAN_CONTAINMENT = 0.98      # at or above this it is a clean relationship; between the two it has orphans
MAX_CANDIDATES = 300
TIME_BUDGET_SECONDS = 25
HINT_SUFFIXES = ('id', 'key', 'fk', 'ref', 'uuid', 'guid')

_IRREGULAR = {'people': 'person', 'children': 'child', 'men': 'man', 'women': 'woman', 'mice': 'mouse'}


def normal(name: str) -> str:
    """Lower case with separators removed, so customer_id, CustomerID and customer-id are the same."""
    return re.sub(r'[^a-z0-9]', '', name.lower())


def singular(word: str) -> str:
    """The singular of a (normalised) table name, by English's usual rules. Wrong for rare words, which is fine:
    the original plural is tried as well."""
    if word in _IRREGULAR:
        return _IRREGULAR[word]
    if word.endswith('ies') and len(word) > 4:
        return word[:-3] + 'y'
    if re.search(r'(sses|xes|ches|shes|uses|zes)$', word):
        return word[:-2]
    if word.endswith('s') and not word.endswith(('ss', 'us', 'is')):
        return word[:-1]
    return word


def name_hints(table: str) -> List[str]:
    """Column names (normalised) that suggest a reference to `table`, best guess first."""
    plural = normal(table)
    one = singular(plural)
    hints = []
    for base in dict.fromkeys([one, plural]):
        hints += [base + suffix for suffix in HINT_SUFFIXES]
    return list(dict.fromkeys(hints))


_KIND = (('num', re.compile(r'(^|[^a-z])(tiny|small|medium|big)?(integer|int|serial|numeric|decimal|number|float|double|real|money)(?![a-z])', re.I)),
         ('text', re.compile(r'char|text|string|clob|uuid|guid|uniqueidentifier', re.I)))


def kind_of(column_type: Optional[str]) -> str:
    text = str(column_type or '')
    return next((kind for kind, pattern in _KIND if pattern.search(text)), 'other')


def compatible(a: Optional[str], b: Optional[str]) -> bool:
    """Can a value of one type equal a value of the other?"""
    ka, kb = kind_of(a), kind_of(b)
    return ka == kb and (ka != 'other' or str(a or '').lower() == str(b or '').lower())


def parent_key(schema: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The single column that identifies a row of this table: its one-column primary key, else a one-column unique
    index. None if the table has neither (a many-column key says nothing about one column)."""
    columns = {c['name']: c for c in schema.get('columns', [])}
    primary = [c for c in columns.values() if c.get('primary_key')]
    if len(primary) == 1:
        return primary[0]
    unique = [i['columns'][0] for i in schema.get('indexes', []) if i.get('unique') and len(i.get('columns', [])) == 1]
    unique = [u for u in unique if u in columns]
    if unique:
        generic = [u for u in unique if normal(u) == 'id' or normal(u).endswith('id')]
        return columns[(generic or unique)[0]]
    return None


def confidence(distinct: int, containment: float) -> str:
    if containment < CLEAN_CONTAINMENT:
        return 'low'
    return 'high' if distinct >= 20 else 'medium' if distinct >= 5 else 'low'


def candidates(columns: Dict[str, List[str]], skip) -> List[Tuple[str, str, str]]:
    """(child table, child column, parent table) for every column whose name hints at another table.
    `skip(table, column)` is true for columns that already have a declared or decided relationship."""
    by_hint: Dict[str, List[Tuple[int, str]]] = {}
    for parent in columns:
        for rank, hint in enumerate(name_hints(parent)):
            by_hint.setdefault(hint, []).append((rank, parent))
    found = []
    for child, names in columns.items():
        for column in names:
            hint = normal(column)
            if hint == 'id' or skip(child, column):
                continue
            for rank, parent in by_hint.get(hint, []):
                if parent != child:
                    found.append((rank, child, column, parent))
    found.sort(key=lambda f: (f[0], f[1], f[2]))
    return [(child, column, parent) for _, child, column, parent in found]


def infer(connector, database: Optional[str], declared: List[Dict[str, str]], decided: List[Dict[str, str]],
          budget: Optional[float] = None, limit: Optional[int] = None) -> Dict[str, Any]:
    """Suggestions for relationships that are not declared and have not been accepted or ignored.

    Returns {'suggestions': [...], 'examined': n, 'truncated': bool}. Each suggestion is
    {table, column, referenced_table, referenced_column, distinct, matched, containment, confidence, orphans}.
    """
    started = time.monotonic()
    budget = TIME_BUDGET_SECONDS if budget is None else budget
    limit = MAX_CANDIDATES if limit is None else limit
    columns = connector.get_columns(database)
    try:   # a view gets its relationships from the tables it reads, so it is neither a parent nor a child here
        views = {t['name'] for t in connector.get_tables(database) if 'view' in str(t.get('type', '')).lower()}
    except Exception:
        views = set()
    columns = {table: names for table, names in columns.items() if table not in views}
    taken = {(r['table'], r['column']) for r in list(declared) + list(decided)}
    pairs = candidates(columns, lambda table, column: (table, column) in taken)
    truncated = len(pairs) > limit
    pairs = pairs[:limit]

    schemas: Dict[str, Optional[Dict[str, Any]]] = {}

    def schema(table: str):
        if table not in schemas:
            try:
                schemas[table] = connector.get_schema(table, database)
            except Exception:
                schemas[table] = None
        return schemas[table]

    suggestions, examined = [], 0
    for child, column, parent in pairs:
        if time.monotonic() - started > budget:
            truncated = True
            break
        child_schema, parent_schema = schema(child), schema(parent)
        if not child_schema or not parent_schema:
            continue
        key = parent_key(parent_schema)
        child_column = next((c for c in child_schema['columns'] if c['name'] == column), None)
        if not key or not child_column or not compatible(child_column.get('type'), key.get('type')):
            continue
        examined += 1
        try:
            result = connector.check_reference(child, column, parent, key['name'], database, SAMPLE_ROWS)
        except Exception:
            continue    # a type the database cannot compare, a permission problem: no evidence, so no suggestion
        distinct, matched = result['distinct'], result['matched']
        if not distinct:
            continue    # the column is empty: nothing to go on
        containment = matched / distinct
        if containment < MIN_CONTAINMENT:
            continue
        suggestions.append({
            'table': child, 'column': column, 'referenced_table': parent, 'referenced_column': key['name'],
            'distinct': distinct, 'matched': matched, 'containment': round(containment, 4),
            'orphans': distinct - matched, 'confidence': confidence(distinct, containment)})

    # a column hinting at two tables (user / users): keep the better-supported one
    best: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for s in suggestions:
        k = (s['table'], s['column'])
        if k not in best or (s['containment'], s['distinct']) > (best[k]['containment'], best[k]['distinct']):
            best[k] = s
    ordered = sorted(best.values(), key=lambda s: (-s['containment'], -s['distinct'], s['table'], s['column']))
    return {'suggestions': ordered, 'examined': examined, 'truncated': truncated}
