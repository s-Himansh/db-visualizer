"""Real-database tests. Start the servers with:  docker compose -f docker-compose.test.yml up -d --wait
A backend whose server is not reachable is skipped, so the suite still runs with only some of them up."""
import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

HOST = '127.0.0.1'


def reachable(port):
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex((HOST, port)) == 0
