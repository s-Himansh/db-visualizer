"""Decide, before a query reaches a database, whether it only reads and whether it is dangerous.

This is a guard against mistakes, not a security boundary: it cannot see side effects hidden inside
functions (pg_terminate_backend, ...). Read-only connections therefore also ask the driver to refuse
writes where it can (see the PostgreSQL, MySQL and SQLite connectors).
"""
import re
from dataclasses import dataclass
from typing import List, Optional

SQL_TYPES = {'sqlite', 'postgresql', 'mysql', 'sqlserver', 'oracle', 'cassandra'}
EXPLAIN_SAFE = {'sqlite', 'postgresql', 'mysql'}  # drivers enforce read-only there, so EXPLAIN cannot write

READ_FIRST_WORDS = {'select', 'with', 'show', 'describe', 'desc', 'explain', 'values', 'table'}
# Words that mean a statement writes, even when it starts like a read (WITH x AS (DELETE ...), SELECT ... INTO t)
WRITES_INSIDE_READ = re.compile(
    r'\b(insert|update|delete|merge|truncate|drop|alter|create|into|grant|revoke)\b'
    r'|\bfor\s+(update|share|no\s+key\s+update|key\s+share)\b|\block\s+in\s+share\s+mode\b')
ALWAYS_CONFIRM = {'drop': 'DROP permanently removes the object and its data',
                  'truncate': 'TRUNCATE removes every row and usually cannot be undone',
                  'alter': 'ALTER changes the structure of the table'}
TRIVIAL_WHERE = re.compile(r'\bwhere\s+(1\s*=\s*1|true|\(\s*1\s*=\s*1\s*\))\s*($|;)')

REDIS_READ = {
    'GET', 'MGET', 'EXISTS', 'TTL', 'PTTL', 'TYPE', 'KEYS', 'SCAN', 'STRLEN', 'GETRANGE', 'DBSIZE', 'PING', 'INFO',
    'HGET', 'HGETALL', 'HKEYS', 'HVALS', 'HLEN', 'HEXISTS', 'HMGET', 'HSCAN',
    'LRANGE', 'LLEN', 'LINDEX', 'SMEMBERS', 'SCARD', 'SISMEMBER', 'SSCAN', 'SRANDMEMBER',
    'ZRANGE', 'ZREVRANGE', 'ZCARD', 'ZSCORE', 'ZRANK', 'ZCOUNT', 'ZRANGEBYSCORE', 'ZSCAN', 'OBJECT', 'MEMORY',
}
REDIS_CONFIRM = {'FLUSHALL': 'FLUSHALL deletes every key in every database',
                 'FLUSHDB': 'FLUSHDB deletes every key in this database'}


@dataclass
class Verdict:
    read_only: bool          # True when nothing in the query writes
    why_not: str = ''        # what made it a write, for the error message
    destructive: Optional[str] = None  # set when the user should confirm first


def _blank(sql: str) -> str:
    """Lower-case the SQL with comments removed and string/identifier contents blanked out,
    so keywords inside literals ('delete me') or quoted names ("update") are never mistaken for syntax."""
    out, i, n = [], 0, len(sql)
    while i < n:
        c = sql[i]
        if sql.startswith('--', i):
            i = sql.find('\n', i)
            i = n if i == -1 else i
        elif sql.startswith('/*', i):
            j = sql.find('*/', i + 2)
            i = n if j == -1 else j + 2
            out.append(' ')
        elif c in ('\'', '"', '`'):
            j = i + 1
            while j < n:
                if sql[j] == c:
                    if j + 1 < n and sql[j + 1] == c:  # doubled quote = escaped quote
                        j += 2
                        continue
                    break
                j += 1
            out.append(c + c)
            i = j + 1
        else:
            out.append(c)
            i += 1
    return ''.join(out).lower()


def statements(sql: str) -> List[str]:
    return [s.strip() for s in _blank(sql).split(';') if s.strip()]


def _check_sql(db_type: str, sql: str) -> Verdict:
    stmts = statements(sql)
    if not stmts:
        return Verdict(True)
    why, destructive = '', None
    for stmt in stmts:
        first = re.match(r'[a-z_]+', stmt)
        first = first.group(0) if first else ''

        if first in ALWAYS_CONFIRM:
            destructive = destructive or ALWAYS_CONFIRM[first]
        elif first in ('update', 'delete') and (not re.search(r'\bwhere\b', stmt) or TRIVIAL_WHERE.search(stmt)):
            destructive = destructive or f'{first.upper()} without a WHERE clause changes every row in the table'

        reads = first in READ_FIRST_WORDS and not (first == 'explain' and db_type not in EXPLAIN_SAFE)
        if reads:
            hit = WRITES_INSIDE_READ.search(stmt)
            if hit:
                reads, why = False, why or f'contains "{hit.group(0)}"'
        elif not why:
            why = f'{first.upper() or "this statement"} is not a read-only statement'
    return Verdict(read_only=not why, why_not=why, destructive=destructive)


def _check_redis(command: str) -> Verdict:
    words = command.strip().split()
    name = words[0].upper() if words else ''
    if name in REDIS_CONFIRM:
        return Verdict(False, f'{name} is not a read command', REDIS_CONFIRM[name])
    return Verdict(name in REDIS_READ or not name, '' if name in REDIS_READ or not name else f'{name} is not a read command')


def check(db_type: str, query: str) -> Verdict:
    """Classify one query for a connection of the given type."""
    db_type = (db_type or '').lower()
    if db_type == 'redis':
        return _check_redis(query)
    if db_type == 'mongodb':
        return Verdict(True)  # the query runner only ever issues find()
    return _check_sql(db_type, query)
