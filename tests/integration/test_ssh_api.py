"""The user journey through the HTTP API: save a connection that uses an SSH tunnel, trust the server, browse,
survive a dropped tunnel, and clean up. Needs the sshd and mysql test containers."""
import json
import socket

import pytest

import db
from conftest import reachable

pytestmark = pytest.mark.integration
SECRETS = ('tunnelpw', 'testpw', 'phrase123')


@pytest.fixture(autouse=True)
def servers_and_clean_state():
    if not (reachable(12222) and reachable(13306)):
        pytest.skip('sshd/mysql test containers not running')
    (db.CONFIG_DIR / 'known_hosts.json').unlink(missing_ok=True)
    yield
    for conn in list(db.active_connections.values()):
        conn.disconnect()
        conn.close_tunnel()
    db.active_connections.clear()


def ssh_connection(**overrides):
    # host "mysql" only exists inside the docker network: this connection cannot work without the tunnel
    return {'name': 'via ssh', 'type': 'mysql', 'host': 'mysql', 'port': 3306, 'database': 'dbviz',
            'username': 'root', 'password': 'testpw', 'ssh_enabled': True, 'ssh_host': '127.0.0.1', 'ssh_port': 12222,
            'ssh_user': 'tunnel', 'ssh_auth': 'password', 'ssh_password': 'tunnelpw', **overrides}


def save(client, **overrides):
    return client.post('/api/connections', json=ssh_connection(**overrides)).get_json()['id']


def host_key(client, cid):
    r = client.post('/api/connect', json={'id': cid})
    assert r.status_code == 409, r.get_json()
    return r.get_json()


def test_first_connect_asks_the_user_to_trust_the_server_and_connects_nothing(client):
    cid = save(client)
    body = host_key(client, cid)
    assert body['needs_host_key_confirmation'] and body['fingerprint'].startswith('SHA256:') and body['port'] == 12222
    assert cid not in db.active_connections
    assert not (db.CONFIG_DIR / 'known_hosts.json').exists()   # nothing remembered until the user agrees


def test_trusting_the_server_connects_and_remembers_it(client):
    cid = save(client)
    fp = host_key(client, cid)['fingerprint']
    r = client.post('/api/connect', json={'id': cid, 'ssh_trust_host_key': fp})
    assert r.get_json()['success'], r.get_json()
    tables = client.get(f'/api/tables?connection_id={cid}&database=dbviz').get_json()['tables']
    assert 'people' in [t['name'] for t in tables]
    assert json.loads((db.CONFIG_DIR / 'known_hosts.json').read_text())['127.0.0.1:12222']['fingerprint'] == fp

    client.post('/api/disconnect', json={'id': cid})
    again = client.post('/api/connect', json={'id': cid})          # no prompt the second time
    assert again.get_json()['success']


def test_data_flows_through_the_tunnel(client):
    cid = save(client)
    fp = host_key(client, cid)['fingerprint']
    client.post('/api/connect', json={'id': cid, 'ssh_trust_host_key': fp})
    r = client.get(f'/api/data?connection_id={cid}&database=dbviz&table=people&limit=5&sort_by=id').get_json()
    assert r['success'] and r['data']['total_count'] >= 1
    q = client.post('/api/query', json={'connection_id': cid, 'query': 'SELECT 6 * 7 AS answer'}).get_json()
    assert q['result']['rows'] == [{'answer': 42}]
    with pytest.raises(socket.gaierror):
        socket.gethostbyname('mysql')    # proof: the name does not resolve here, so it must have used the tunnel


def test_secrets_are_encrypted_on_disk_and_masked_in_the_api(client):
    save(client, ssh_auth='key', ssh_key_path='/keys/id', ssh_passphrase='phrase123')
    disk = db.CONNECTIONS_FILE.read_text()
    assert not any(s in disk for s in SECRETS)
    shown = client.get('/api/connections').get_json()['connections'][0]
    assert shown['password'] == shown['ssh_password'] == shown['ssh_passphrase'] == '***'
    assert shown['ssh_host'] == '127.0.0.1' and shown['ssh_user'] == 'tunnel'   # the non-secret parts are visible


def test_editing_without_retyping_secrets_keeps_them_and_still_connects(client):
    cid = save(client)
    client.put(f'/api/connections/{cid}', json={'name': 'renamed', 'password': '', 'ssh_password': '***'})
    saved = db.load_connections()[0]
    assert saved['password'] == 'testpw' and saved['ssh_password'] == 'tunnelpw'
    fp = host_key(client, cid)['fingerprint']
    assert client.post('/api/connect', json={'id': cid, 'ssh_trust_host_key': fp}).get_json()['success']


def test_disconnect_and_delete_close_the_tunnel(client):
    cid = save(client)
    fp = host_key(client, cid)['fingerprint']
    client.post('/api/connect', json={'id': cid, 'ssh_trust_host_key': fp})
    port = db.active_connections[cid]._tunnel.local_port
    assert reachable(port)
    client.post('/api/disconnect', json={'id': cid})
    assert not reachable(port)

    client.post('/api/connect', json={'id': cid})
    port = db.active_connections[cid]._tunnel.local_port
    assert reachable(port)
    client.delete(f'/api/connections/{cid}')
    assert not reachable(port) and cid not in db.active_connections


def test_wrong_ssh_password_is_reported_clearly(client):
    cid = save(client, ssh_password='nope')
    fp = host_key(client, cid)['fingerprint']
    r = client.post('/api/connect', json={'id': cid, 'ssh_trust_host_key': fp})
    assert r.status_code == 502 and 'refused the login' in r.get_json()['error']
    assert cid not in db.active_connections


def test_a_database_host_the_ssh_server_cannot_reach_is_reported_clearly(client):
    cid = save(client, host='no-such-host')
    fp = host_key(client, cid)['fingerprint']
    r = client.post('/api/connect', json={'id': cid, 'ssh_trust_host_key': fp})
    assert r.status_code == 502 and 'no-such-host' in r.get_json()['error']


def test_wrong_database_password_through_a_working_tunnel_says_so(client):
    cid = save(client, password='wrong')
    fp = host_key(client, cid)['fingerprint']
    r = client.post('/api/connect', json={'id': cid, 'ssh_trust_host_key': fp})
    assert r.status_code == 500 and 'SSH tunnel is up' in r.get_json()['error']
    assert not db.active_connections


def test_connection_url_cannot_be_combined_with_a_tunnel(client):
    cid = save(client, type='mongodb', connection_url='mongodb://x:y@mongo:27017/d')
    r = client.post('/api/connect', json={'id': cid})
    assert r.status_code == 502 and 'connection URL' in r.get_json()['error']


def test_changed_host_key_is_refused_with_a_warning(client):
    cid = save(client)
    db.KNOWN_HOSTS.add('127.0.0.1', 12222, 'ssh-ed25519', 'SHA256:attacker')
    r = client.post('/api/connect', json={'id': cid, 'ssh_trust_host_key': 'SHA256:attacker'})
    assert r.status_code == 502 and 'CHANGED' in r.get_json()['error']


def test_test_connection_uses_a_temporary_tunnel_and_closes_it(client):
    body = ssh_connection()
    fp = client.post('/api/test-connection', json=body).get_json()['fingerprint']
    ok = client.post('/api/test-connection', json={**body, 'ssh_trust_host_key': fp}).get_json()
    assert ok['success'], ok
    assert not db.active_connections
    bad = client.post('/api/test-connection', json={**body, 'ssh_password': 'nope'}).get_json()
    assert bad['success'] is False and 'refused the login' in bad['error']


def test_test_connection_of_a_saved_connection_uses_the_saved_secrets(client):
    cid = save(client)
    fp = host_key(client, cid)['fingerprint']
    r = client.post('/api/test-connection', json={**ssh_connection(), 'id': cid, 'password': '', 'ssh_password': '',
                                                  'ssh_trust_host_key': fp})
    assert r.get_json()['success'], r.get_json()


def test_a_dropped_tunnel_recovers_on_the_next_request(client):
    cid = save(client)
    fp = host_key(client, cid)['fingerprint']
    client.post('/api/connect', json={'id': cid, 'ssh_trust_host_key': fp})
    wrapper = db.active_connections[cid]
    port = wrapper._tunnel.local_port
    wrapper._tunnel._transport.close()              # the SSH connection dies
    assert not wrapper._tunnel.alive()
    first = client.get(f'/api/tables?connection_id={cid}&database=dbviz')   # may fail once; it must repair itself
    second = client.get(f'/api/tables?connection_id={cid}&database=dbviz')
    assert second.status_code == 200 and second.get_json()['tables']
    assert wrapper._tunnel.alive() and wrapper._tunnel.local_port == port
    assert first.status_code in (200, 503)
