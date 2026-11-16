"""A keyring backend for the keychain tests: it behaves like a Mac keychain where the person can choose Deny.

While the file named by DENY_FLAG exists, reading the key raises (as keyring does when a Mac user clicks Deny or the keychain is locked);
once the file is gone it hands the key over. Every read is logged to DENY_LOG, so a test can count how many times the app ASKED (on a Mac
each ask is a system prompt). Selected with PYTHON_KEYRING_BACKEND=denying_keyring.DenyingKeyring."""
import os

from keyring.backend import KeyringBackend
from keyring.errors import KeyringLocked


class DenyingKeyring(KeyringBackend):
    priority = 100

    def get_password(self, service, username):
        with open(os.environ['DENY_LOG'], 'a') as log:
            log.write('asked\n')
        if os.path.exists(os.environ['DENY_FLAG']):
            raise KeyringLocked('The user denied access')
        try:
            return open(os.environ['KEY_FILE']).read() or None
        except FileNotFoundError:
            return None

    def set_password(self, service, username, password):
        with open(os.environ['KEY_FILE'], 'w') as f:
            f.write(password)

    def delete_password(self, service, username):
        try:
            os.remove(os.environ['KEY_FILE'])
        except FileNotFoundError:
            pass
