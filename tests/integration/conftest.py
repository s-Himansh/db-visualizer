"""Real-database tests. Start the servers with:  docker compose -f docker-compose.test.yml up -d --wait
A backend whose server is not reachable is skipped, so the suite still runs with only some of them up."""
import os
import re
import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

HOST = '127.0.0.1'


SQL_BACKENDS = {'mysql', 'postgresql', 'sqlserver', 'oracle', 'sqlite'}
NOSQL_BACKENDS = {'mongodb', 'redis', 'cassandra'}


def pytest_collection_modifyitems(config, items):
    """DBV_TEST_PART=sql or nosql keeps only that part. CI runs the two as separate jobs, each starting only its own servers, so
    every test must land in exactly one. A test belongs to the NoSQL part when its backend parameter is a NoSQL one (or it is the
    Redis file); everything else, including the SSH tunnel tests that have no backend in their id, is SQL. The split looks at the
    parameter, not at words in a test's name: a test called ..._mongodb_... runs for every backend, and its MySQL variant must
    go with MySQL."""
    part = os.environ.get('DBV_TEST_PART')
    if not part:
        return

    def part_of(item):
        ids = set(re.split(r'[-\[\]]', item.callspec.id)) if hasattr(item, 'callspec') else set()
        return 'nosql' if (ids & NOSQL_BACKENDS or item.path.name == 'test_redis.py') else 'sql'

    keep = [i for i in items if part_of(i) == part]
    config.hook.pytest_deselected(items=[i for i in items if part_of(i) != part])
    items[:] = keep


def reachable(port):
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex((HOST, port)) == 0
