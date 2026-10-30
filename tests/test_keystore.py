"""Where the password-encryption key lives, and what happens when the OS keychain misbehaves.
The one rule above all: never replace a key that may exist, or every saved password becomes unreadable."""
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

    def get_password(self, service, account):
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
    db.KEY_FILE.unlink(missing_ok=True)
    yield
    db.KEY_FILE.unlink(missing_ok=True)


def use(monkeypatch, keychain):
    monkeypatch.setattr(db, '_os_keyring', lambda: keychain)
    monkeypatch.setattr(db, '_key_cache', None)


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
