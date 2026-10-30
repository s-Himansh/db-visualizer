"""The SSH tunnel against a real sshd. The databases are addressed by their Docker-internal names (mysql, postgres),
which do not resolve from this machine: a query that works can only have travelled through the tunnel."""
import socket
import threading
from pathlib import Path

import pytest

from conftest import reachable
from db_connectors.mysql import MySQLConnector
from db_connectors.postgres import PostgreSQLConnector
from db_connectors.tunnel import HostKeyChanged, KnownHosts, SSHError, SSHTunnel, UnknownHostKey, fingerprint

pytestmark = pytest.mark.integration
SSH_PORT = 12222
KEYS = Path(__file__).resolve().parents[1] / 'ssh_fixture'


@pytest.fixture(scope='module', autouse=True)
def need_servers():
    if not (reachable(SSH_PORT) and reachable(13306)):
        pytest.skip('sshd/mysql test containers not running (docker compose -f docker-compose.test.yml up -d --wait)')


@pytest.fixture
def known(tmp_path):
    return KnownHosts(tmp_path / 'known_hosts.json')


@pytest.fixture
def server_fp():
    import paramiko
    t = paramiko.Transport(socket.create_connection(('127.0.0.1', SSH_PORT), timeout=10))
    t.start_client(timeout=10)
    fp = fingerprint(t.get_remote_server_key())
    t.close()
    return fp


@pytest.fixture
def make(known, server_fp):
    """Build a tunnel to the MySQL container. By default the host key is already trusted."""
    made = []

    def build(trusted=True, remote=('mysql', 3306), **kw):
        if trusted:
            known.add('127.0.0.1', SSH_PORT, 'ssh-ed25519', server_fp)
        opts = dict(username='tunnel', password='tunnelpw')
        opts.update(kw)
        t = SSHTunnel('127.0.0.1', SSH_PORT, remote_host=remote[0], remote_port=remote[1], known_hosts=known, **opts)
        made.append(t)
        return t
    yield build
    for t in made:
        t.stop()


def mysql_through(tunnel):
    c = MySQLConnector({'type': 'mysql', 'host': '127.0.0.1', 'port': tunnel.local_port, 'username': 'root',
                        'password': 'testpw', 'database': 'dbviz'})
    assert c.connect(), 'could not connect through the tunnel'
    return c


def test_the_database_name_only_resolves_inside_docker():
    with pytest.raises(socket.gaierror):
        socket.gethostbyname('mysql')   # so everything below must really use the tunnel


def test_password_login_carries_a_mysql_session(make):
    t = make()
    t.start()
    c = mysql_through(t)
    assert c.execute_query('SELECT 41 + 1 AS answer')['rows'] == [{'answer': 42}]
    c.disconnect()


def test_key_login_ed25519(make):
    t = make(password=None, key_path=str(KEYS / 'id_ed25519'))
    t.start()
    assert mysql_through(t).execute_query('SELECT 1 AS one')['rows'] == [{'one': 1}]


def test_key_login_with_passphrase(make):
    t = make(password=None, key_path=str(KEYS / 'id_rsa_passphrase'), passphrase='phrase123')
    t.start()
    assert mysql_through(t).execute_query('SELECT 1 AS one')['rows'] == [{'one': 1}]


def test_passphrase_key_without_or_with_the_wrong_passphrase_says_so(make):
    for passphrase in (None, 'wrong'):
        with pytest.raises(SSHError, match='passphrase'):
            make(password=None, key_path=str(KEYS / 'id_rsa_passphrase'), passphrase=passphrase).start()


def test_wrong_password_and_wrong_user_are_refused_clearly(make):
    with pytest.raises(SSHError, match='refused the login'):
        make(password='nope').start()
    with pytest.raises(SSHError, match='refused the login'):
        make(username='nobody').start()


def test_missing_key_file_and_missing_credentials(make):
    with pytest.raises(SSHError, match='not found'):
        make(password=None, key_path='/no/such/key').start()
    with pytest.raises(SSHError, match='password or choose a private key'):
        make(password=None).start()


def test_unreachable_ssh_server(known):
    t = SSHTunnel('127.0.0.1', 1, 'u', 'mysql', 3306, known_hosts=known, password='x', connect_timeout=3)
    with pytest.raises(SSHError, match='Could not reach the SSH server'):
        t.start()


def test_ssh_server_that_cannot_reach_the_database_fails_at_start_with_a_clear_message(make):
    with pytest.raises(SSHError, match=r'could not connect to nope-host:3306'):
        make(remote=('nope-host', 3306)).start()


def test_postgres_works_through_the_tunnel_too(make):
    if not reachable(15432):
        pytest.skip('postgres not running')
    t = make(remote=('postgres', 5432))
    t.start()
    c = PostgreSQLConnector({'type': 'postgresql', 'host': '127.0.0.1', 'port': t.local_port, 'username': 'postgres',
                             'password': 'testpw', 'database': 'dbviz'})
    assert c.connect()
    assert c.execute_query('SELECT 7 AS seven')['rows'] == [{'seven': 7}]


# ---- host keys ----------------------------------------------------------------------------------

def test_unknown_host_key_is_reported_with_its_fingerprint_before_any_credentials_are_sent(make, server_fp, monkeypatch):
    t = make(trusted=False)
    monkeypatch.setattr(t, '_authenticate', lambda transport: pytest.fail('credentials were sent to an unverified server'))
    with pytest.raises(UnknownHostKey) as info:
        t.start()
    assert info.value.fingerprint == server_fp and info.value.fingerprint.startswith('SHA256:')


def test_trusting_a_key_remembers_it(make, known, server_fp):
    make(trusted=False, trust=server_fp).start()
    assert known.get('127.0.0.1', SSH_PORT)['fingerprint'] == server_fp
    make(trusted=False).start()   # no confirmation needed any more


def test_trusting_the_wrong_fingerprint_does_not_work(make):
    with pytest.raises(UnknownHostKey):
        make(trusted=False, trust='SHA256:notthekey').start()


def test_a_changed_host_key_is_refused_and_credentials_are_never_sent(make, known, monkeypatch):
    known.add('127.0.0.1', SSH_PORT, 'ssh-ed25519', 'SHA256:someoneelse')
    t = make(trusted=False)
    monkeypatch.setattr(t, '_authenticate', lambda transport: pytest.fail('credentials were sent to a changed host'))
    with pytest.raises(HostKeyChanged, match='CHANGED'):
        t.start()


def test_trust_cannot_override_a_changed_key(make, known, server_fp):
    known.add('127.0.0.1', SSH_PORT, 'ssh-ed25519', 'SHA256:someoneelse')
    with pytest.raises(HostKeyChanged):
        make(trusted=False, trust=server_fp).start()


# ---- behaviour under load and failure -----------------------------------------------------------------

def test_many_parallel_connections(make):
    t = make()
    t.start()
    results, errors = [], []

    def work(i):
        try:
            c = mysql_through(t)
            results.append(c.execute_query(f'SELECT {i} AS n')['rows'][0]['n'])
            c.disconnect()
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(20)]
    [th.start() for th in threads]
    [th.join(30) for th in threads]
    assert not errors and sorted(results) == list(range(20))


def test_large_result_arrives_intact(make):
    t = make()
    t.start()
    c = mysql_through(t)
    r = c.execute_query("SET SESSION group_concat_max_len = 4000000")
    row = c.execute_query('SELECT LENGTH(REPEAT(\'ab\', 1500000)) AS n, MD5(REPEAT(\'ab\', 1500000)) AS h, REPEAT(\'ab\', 1500000) AS body')['rows'][0]
    import hashlib
    assert row['n'] == 3_000_000 and hashlib.md5(row['body'].encode()).hexdigest() == row['h']


def test_restart_reopens_on_the_same_local_port(make):
    t = make()
    t.start()
    port = t.local_port
    t._transport.close()          # the SSH connection dies (network drop, server restart)
    assert not t.alive()
    t.restart()
    assert t.alive() and t.local_port == port
    assert mysql_through(t).execute_query('SELECT 1 AS one')['rows'] == [{'one': 1}]


def test_stop_closes_the_local_port(make):
    t = make()
    t.start()
    port = t.local_port
    t.stop()
    assert not t.alive() and not reachable(port)


def test_listener_is_loopback_only(make):
    t = make()
    t.start()
    assert t._listener.getsockname()[0] == '127.0.0.1'
