"""Create the throwaway SSH keys the tunnel tests use, if they are missing. Run it before starting the test containers:

    python tests/ssh_fixture/make_keys.py

The keys only open the disposable SSH server in docker-compose.test.yml. They are generated, never committed.
"""
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa

HERE = Path(__file__).resolve().parent
PASSPHRASE = b'phrase123'   # the tests expect exactly this


def write(path: Path, data: bytes, mode: int):
    path.write_bytes(data)
    path.chmod(mode)


def public_line(key, comment: str) -> bytes:
    raw = key.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH)
    return raw + f' {comment}\n'.encode()


def main():
    plain, locked = HERE / 'id_ed25519', HERE / 'id_rsa_passphrase'
    if not plain.exists():
        key = ed25519.Ed25519PrivateKey.generate()
        write(plain, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
                                       serialization.NoEncryption()), 0o600)
        write(HERE / 'id_ed25519.pub', public_line(key, 'dbviz-test'), 0o644)
    if not locked.exists():
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        write(locked, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                        serialization.BestAvailableEncryption(PASSPHRASE)), 0o600)
        write(HERE / 'id_rsa_passphrase.pub', public_line(key, 'dbviz-test-passphrase'), 0o644)
    (HERE / 'authorized_keys').write_bytes((HERE / 'id_ed25519.pub').read_bytes() + (HERE / 'id_rsa_passphrase.pub').read_bytes())


if __name__ == '__main__':
    main()
    print('SSH test keys ready in', HERE)
