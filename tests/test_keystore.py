"""Where the password-encryption key lives, and what happens when the OS keychain misbehaves.
The one rule above all: never replace a key that may exist, or every saved password becomes unreadable."""
import os
import json

import pytest
from cryptography.fernet import Fernet

import db


class FakeKeychain:
    def __init__(self, stored=None, fail_get=False, fail_set=False, lie_on_readback=False):
        self.items = {}
        if stored:
            self.items[(db.KEY_SERVICE, db.KEY_ACCOUNT)] = stored
        self.fail_get, self.fail_set, self.lie = fail_get, fail_set, lie_on_readback
        self.sets = 0
        self.gets = 0          # how many times the keychain was ASKED: on a Mac every ask can be a prompt

    def get_password(self, service, account):
        self.gets += 1
        if self.fail_get:
            raise RuntimeError('keychain is locked')
        if self.lie and self.sets:
            return 'something-else'
        return self.items.get((service, account))

    def set_password(self, service, account, value):
        if self.fail_set:
            raise RuntimeError('access denied')
        self.sets += 1
        self.items[(service, account)] = value


@pytest.fixture(autouse=True)
def fresh_key_state(monkeypatch):
    monkeypatch.setattr(db, '_key_cache', None)
    monkeypatch.setattr(db, '_key_error', None)
    db.KEY_FILE.unlink(missing_ok=True)
    yield
    db.KEY_FILE.unlink(missing_ok=True)


def use(monkeypatch, keychain):
    monkeypatch.setattr(db, '_os_keyring', lambda: keychain)
    monkeypatch.setattr(db, '_key_cache', None)
    monkeypatch.setattr(db, '_key_error', None)


def stored(keychain):
    return keychain.items.get((db.KEY_SERVICE, db.KEY_ACCOUNT))


def test_fresh_install_keeps_the_key_in_the_keychain_and_writes_no_file(monkeypatch):
    kc = FakeKeychain()
    use(monkeypatch, kc)
    assert db.decrypt_password(db.encrypt_password('hunter2')) == 'hunter2'
    assert stored(kc) and not db.KEY_FILE.exists()


def test_existing_key_file_is_moved_into_the_keychain_and_old_passwords_still_work(monkeypatch):
    old_key = Fernet.generate_key()
    db.KEY_FILE.write_bytes(old_key)
    ciphertext = Fernet(old_key).encrypt(b'saved-long-ago').decode()
    kc = FakeKeychain()
    use(monkeypatch, kc)
    assert db.decrypt_password(ciphertext) == 'saved-long-ago'
    assert stored(kc) == old_key.decode()
    assert not db.KEY_FILE.exists()   # it now exists only in the keychain


def test_keychain_key_is_used_when_present(monkeypatch):
    key = Fernet.generate_key()
    kc = FakeKeychain(stored=key.decode())
    use(monkeypatch, kc)
    assert db.decrypt_password(Fernet(key).encrypt(b'x').decode()) == 'x'
    assert kc.sets == 0 and not db.KEY_FILE.exists()


def test_when_file_and_keychain_disagree_the_keychain_wins_and_the_file_is_left_alone(monkeypatch):
    keychain_key, file_key = Fernet.generate_key(), Fernet.generate_key()
    db.KEY_FILE.write_bytes(file_key)
    use(monkeypatch, FakeKeychain(stored=keychain_key.decode()))
    assert db.load_key() == keychain_key
    assert db.KEY_FILE.read_bytes() == file_key


def test_no_keychain_falls_back_to_a_private_key_file(monkeypatch):
    use(monkeypatch, None)
    assert db.decrypt_password(db.encrypt_password('pw')) == 'pw'
    if os.name != 'nt':   # Windows has no Unix permission bits; the user profile's own access rules protect the file
        assert db.KEY_FILE.exists() and oct(db.KEY_FILE.stat().st_mode & 0o777) == '0o600'


def test_locked_keychain_with_a_file_copy_uses_the_file(monkeypatch):
    key = Fernet.generate_key()
    db.KEY_FILE.write_bytes(key)
    use(monkeypatch, FakeKeychain(fail_get=True))
    assert db.load_key() == key


def test_locked_keychain_and_no_file_refuses_to_invent_a_key(monkeypatch):
    use(monkeypatch, FakeKeychain(fail_get=True))
    with pytest.raises(RuntimeError, match='keychain'):
        db.load_key()
    assert not db.KEY_FILE.exists()   # no replacement key was created


def test_failed_keychain_write_keeps_the_file_so_nothing_is_lost(monkeypatch):
    key = Fernet.generate_key()
    db.KEY_FILE.write_bytes(key)
    use(monkeypatch, FakeKeychain(fail_set=True))
    assert db.load_key() == key and db.KEY_FILE.read_bytes() == key


def test_failed_keychain_write_on_a_fresh_install_still_works_via_the_file(monkeypatch):
    use(monkeypatch, FakeKeychain(fail_set=True))
    assert db.decrypt_password(db.encrypt_password('pw')) == 'pw'
    assert db.KEY_FILE.exists()


def test_key_that_does_not_read_back_is_not_trusted_and_the_file_is_kept(monkeypatch):
    key = Fernet.generate_key()
    db.KEY_FILE.write_bytes(key)
    use(monkeypatch, FakeKeychain(lie_on_readback=True))
    assert db.load_key() == key
    assert db.KEY_FILE.read_bytes() == key   # not deleted: the keychain copy could not be verified


def test_key_is_loaded_once(monkeypatch):
    kc = FakeKeychain()
    use(monkeypatch, kc)
    db.load_key(); db.load_key(); db.load_key()
    assert kc.sets == 1


def test_explicit_data_dir_means_file_storage():
    assert db.KEY_STORE == 'file'   # the test suite runs with DBV_DATA_DIR set: never touches a real keychain
    assert db._os_keyring() is None


# ---- a password that cannot be decrypted must survive a save --------------------------------

def test_unreadable_password_is_preserved_when_connections_are_saved(client, monkeypatch):
    use(monkeypatch, None)
    cid = client.post('/api/connections', json={'name': 'a', 'type': 'mysql', 'password': 'secret'}).get_json()['id']
    original = json.loads(db.CONNECTIONS_FILE.read_text())[0]['password']

    monkeypatch.setattr(db, '_key_cache', Fernet.generate_key())   # the wrong key: decryption now fails
    assert db.load_connections()[0]['password'] == ''
    assert client.put(f'/api/connections/{cid}', json={'name': 'renamed'}).get_json()['success']
    assert json.loads(db.CONNECTIONS_FILE.read_text())[0]['password'] == original   # ciphertext untouched

    monkeypatch.setattr(db, '_key_cache', None)   # the right key comes back
    assert db.load_connections()[0]['password'] == 'secret'


def test_a_new_password_replaces_an_unreadable_one(client, monkeypatch):
    use(monkeypatch, None)
    cid = client.post('/api/connections', json={'name': 'a', 'type': 'mysql', 'password': 'secret'}).get_json()['id']
    monkeypatch.setattr(db, '_key_cache', Fernet.generate_key())
    assert client.put(f'/api/connections/{cid}', json={'password': 'fresh'}).get_json()['success']
    assert db.load_connections()[0]['password'] == 'fresh'


def test_internal_ciphertext_field_never_reaches_the_browser(client, monkeypatch):
    use(monkeypatch, None)
    client.post('/api/connections', json={'name': 'a', 'type': 'mysql', 'password': 'secret'})
    monkeypatch.setattr(db, '_key_cache', Fernet.generate_key())
    body = client.get('/api/connections').get_data(as_text=True)
    assert '_unreadable_secrets' not in body and 'gAAAA' not in body


def test_the_names_that_locate_saved_connections_and_passwords_survive_the_rebrand(monkeypatch):
    """The app is called Cairn and its keychain entry now is too, but the data folder keeps the old name (renaming it would hide every
    existing user's connections), and the old keychain name is still READ, so saved passwords stay readable."""
    assert db.APP_NAME == 'Cairn'
    assert db.STORAGE_NAME == 'DB Visualizer'
    assert db.KEY_SERVICE == 'Cairn'
    assert db.LEGACY_KEY_SERVICE == 'DB Visualizer'
    monkeypatch.delenv('DBV_DATA_DIR', raising=False)                           # the real, per-user location
    assert db._data_dir().name == 'DB Visualizer'


# ---- the keychain says no (a Mac user chose Deny): ask once, then stop and say so -----------------------------------------------

def saved_connections_then_a_refusing_keychain(client, monkeypatch, count=6):
    """Connections saved while the keychain worked, then the same keychain refusing (the person chose Deny)."""
    good = FakeKeychain()
    use(monkeypatch, good)
    for i in range(count):
        assert client.post('/api/connections', json={'name': f'c{i}', 'type': 'mysql', 'password': f'p{i}', 'ssh_password': f's{i}'}).get_json()['success']
    refusing = FakeKeychain(stored=stored(good), fail_get=True)
    use(monkeypatch, refusing)
    return refusing


def test_a_refused_keychain_is_asked_once_not_once_per_saved_password(client, monkeypatch):
    """The bug: each of the dozens of saved passwords called load_key() again, and on a Mac each call was another prompt, so Deny
    brought the next prompt, over and over."""
    refusing = saved_connections_then_a_refusing_keychain(client, monkeypatch)
    db.load_connections()
    db.load_connections()
    client.get('/api/connections')
    assert refusing.gets == 1


def test_the_list_still_shows_the_connections_and_says_the_keychain_is_locked(client, monkeypatch):
    saved_connections_then_a_refusing_keychain(client, monkeypatch)
    body = client.get('/api/connections').get_json()
    assert len(body['connections']) == 6                                  # people can still see what is locked
    assert body['keychain']['available'] is False and 'Try again' in body['keychain']['message']
    assert all(c['password'] == '' or c['password'] == '***' for c in body['connections'])      # no secret ever leaves


def test_saving_while_the_keychain_refuses_says_why_and_changes_nothing(client, monkeypatch):
    saved_connections_then_a_refusing_keychain(client, monkeypatch)
    before = db.CONNECTIONS_FILE.read_text()
    response = client.post('/api/connections', json={'name': 'new', 'type': 'mysql', 'password': 'x'})
    assert response.status_code == 503 and response.get_json()['error_code'] == 'keychain_unavailable'
    assert 'keychain' in response.get_json()['error']
    assert db.CONNECTIONS_FILE.read_text() == before                      # the existing, encrypted passwords are untouched


def test_try_again_asks_once_more_and_everything_works_when_allowed(client, monkeypatch):
    refusing = saved_connections_then_a_refusing_keychain(client, monkeypatch)
    db.load_connections()
    assert refusing.gets == 1
    refusing.fail_get = False                                             # the person now chooses Allow
    assert client.post('/api/keychain/retry').get_json() == {'available': True}
    assert refusing.gets == 2
    assert [c['password'] for c in db.load_connections()] == [f'p{i}' for i in range(6)]
    assert client.get('/api/connections').get_json()['keychain'] == {'available': True}


def test_try_again_while_still_refused_asks_exactly_once_and_stays_quiet_after(client, monkeypatch):
    refusing = saved_connections_then_a_refusing_keychain(client, monkeypatch)
    db.load_connections()
    asked = refusing.gets
    body = client.post('/api/keychain/retry').get_json()
    assert body['available'] is False and refusing.gets == asked + 1      # one prompt, because they asked for it
    db.load_connections()
    client.get('/api/connections')
    assert refusing.gets == asked + 1                                     # and then no more on their own


def test_a_working_keychain_is_reported_available_and_asked_once(client, monkeypatch):
    good = FakeKeychain(stored=Fernet.generate_key().decode())             # an existing install: the key is already there
    use(monkeypatch, good)
    assert client.get('/api/keychain').get_json() == {'available': True}
    for name in ('a', 'b'):
        assert client.post('/api/connections', json={'name': name, 'type': 'mysql', 'password': 'x'}).get_json()['success']
    client.get('/api/connections')
    assert good.gets == 1                                                  # asked once, then remembered


# ---- the keychain entry is named Cairn now; a key saved under the old name is copied, never lost or replaced ------------------------

def old_name(kc, key):
    kc.items[(db.LEGACY_KEY_SERVICE, db.KEY_ACCOUNT)] = key


def test_a_key_under_the_old_name_is_used_and_copied_to_the_new_name(monkeypatch):
    kc = FakeKeychain()
    key = Fernet.generate_key().decode()
    old_name(kc, key)
    use(monkeypatch, kc)
    token = Fernet(key.encode()).encrypt(b'hunter2').decode()          # a password saved by an earlier version
    assert db.load_key() == key.encode()
    assert db.decrypt_password(token) == 'hunter2'
    assert stored(kc) == key                                          # now also under the new name
    assert kc.items[(db.LEGACY_KEY_SERVICE, db.KEY_ACCOUNT)] == key    # and the old item is left alone
    assert not db.KEY_FILE.exists()


def test_after_the_copy_the_old_name_is_not_asked_again(monkeypatch):
    kc = FakeKeychain()
    old_name(kc, Fernet.generate_key().decode())
    use(monkeypatch, kc)
    db.load_key()
    kc.gets = 0
    monkeypatch.setattr(db, '_key_cache', None)                        # a later launch
    db.load_key()
    assert kc.gets == 1 and stored(kc)


def test_a_failed_copy_still_uses_the_old_key_and_never_invents_one(monkeypatch):
    kc = FakeKeychain(fail_set=True)
    key = Fernet.generate_key().decode()
    old_name(kc, key)
    use(monkeypatch, kc)
    assert db.load_key() == key.encode()
    assert not db.KEY_FILE.exists()                                    # no new key, no file: the existing key is simply used
    assert kc.items[(db.LEGACY_KEY_SERVICE, db.KEY_ACCOUNT)] == key


def test_a_denied_keychain_with_only_the_old_name_still_asks_once_and_stops(monkeypatch):
    kc = FakeKeychain(fail_get=True)
    old_name(kc, Fernet.generate_key().decode())
    use(monkeypatch, kc)
    with pytest.raises(db.KeychainUnavailable):
        db.load_key()
    with pytest.raises(db.KeychainUnavailable):
        db.load_key()
    assert kc.gets == 1


def test_the_new_name_wins_when_both_exist(monkeypatch):
    kc = FakeKeychain(stored=Fernet.generate_key().decode())
    old_name(kc, Fernet.generate_key().decode())
    use(monkeypatch, kc)
    assert db.load_key() == stored(kc).encode() and kc.gets == 1


def test_an_explicit_service_name_gets_no_legacy_lookup():
    """Tests and portable setups name their own entry; they must not read (or copy from) the real 'DB Visualizer' item."""
    import importlib, os, sys
    code = "import db; print(db.KEY_SERVICE, db.LEGACY_KEY_SERVICE)"
    out = __import__('subprocess').run([sys.executable, '-c', code], capture_output=True, text=True, cwd=os.path.dirname(db.__file__),
                                       env={**os.environ, 'DBV_KEYRING_SERVICE': 'my-test-entry'}).stdout.strip()
    assert out == 'my-test-entry None'
