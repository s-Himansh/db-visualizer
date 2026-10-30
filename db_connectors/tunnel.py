"""SSH tunnels: reach a database that is only visible from an SSH server.

The tunnel listens on a random port of 127.0.0.1 and forwards every connection through the SSH server to
`remote_host:remote_port`. The database connector is then pointed at 127.0.0.1:<local port>.

Security rules, in the order they happen:
  1. The server's host key is checked BEFORE any password or key is sent. An unknown key must be confirmed by the
     user (UnknownHostKey carries the fingerprint to show); a key that differs from the remembered one is refused
     outright (HostKeyChanged): that is what a man-in-the-middle looks like.
  2. The listener only binds to 127.0.0.1.
"""
import base64
import hashlib
import json
import logging
import os
import select
import socket
import threading
from pathlib import Path
from typing import Dict, Optional

import paramiko

logger = logging.getLogger(__name__)


class SSHError(ConnectionError):
    """Anything that stops the tunnel from working. The message is written for the user."""


class UnknownHostKey(SSHError):
    def __init__(self, host: str, port: int, key_type: str, fingerprint: str):
        super().__init__(f'The SSH server {host}:{port} has not been seen before (key {fingerprint}).')
        self.host, self.port, self.key_type, self.fingerprint = host, port, key_type, fingerprint


class HostKeyChanged(SSHError):
    def __init__(self, host: str, port: int, expected: str, got: str):
        super().__init__(
            f'The SSH host key of {host}:{port} has CHANGED (remembered {expected}, server now presents {got}). '
            'Someone may be intercepting the connection, or the server was reinstalled. '
            'If you are sure the change is legitimate, remove that entry from known_hosts.json in the app data folder.')
        self.host, self.port, self.expected, self.got = host, port, expected, got


def fingerprint(key: paramiko.PKey) -> str:
    """OpenSSH-style fingerprint, e.g. SHA256:abc... (what `ssh-keygen -lf` prints)."""
    digest = hashlib.sha256(key.asbytes()).digest()
    return 'SHA256:' + base64.b64encode(digest).decode().rstrip('=')


class KnownHosts:
    """Remembered SSH server keys, kept as JSON: {"host:port": {"type": ..., "fingerprint": ...}}."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def _load(self) -> Dict[str, dict]:
        try:
            return json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}

    def get(self, host: str, port: int) -> Optional[dict]:
        return self._load().get(f'{host}:{port}')

    def add(self, host: str, port: int, key_type: str, fp: str):
        with self._lock:
            entries = self._load()
            entries[f'{host}:{port}'] = {'type': key_type, 'fingerprint': fp}
            tmp = self.path.with_suffix('.tmp')
            tmp.write_text(json.dumps(entries, indent=2))
            os.replace(tmp, self.path)


class SSHTunnel:
    def __init__(self, ssh_host: str, ssh_port: int, username: str, remote_host: str, remote_port: int, *,
                 known_hosts: KnownHosts, password: Optional[str] = None, key_path: Optional[str] = None,
                 passphrase: Optional[str] = None, trust: Optional[str] = None, connect_timeout: float = 10):
        self.ssh_host, self.ssh_port, self.username = ssh_host, int(ssh_port or 22), username
        self.remote_host, self.remote_port = remote_host, int(remote_port)
        self.known_hosts, self.trust = known_hosts, trust
        self._password, self._key_path, self._passphrase = password, key_path, passphrase
        self._timeout = connect_timeout
        self._transport: Optional[paramiko.Transport] = None
        self._listener: Optional[socket.socket] = None
        self._stopping = threading.Event()
        self.local_port: Optional[int] = None

    # -- lifecycle -------------------------------------------------------------------------------

    def start(self):
        self._connect_transport()
        self._open_listener(self.local_port or 0)
        # prove the SSH server can reach the database now, so a wrong host/port fails here with a clear message
        self._check_target()
        threading.Thread(target=self._accept_loop, args=(self._listener,), daemon=True, name='ssh-tunnel-accept').start()
        logger.info('SSH tunnel up: 127.0.0.1:%s -> %s -> %s:%s', self.local_port, self.ssh_host, self.remote_host, self.remote_port)

    def alive(self) -> bool:
        return bool(self._transport and self._transport.is_active() and self._listener and not self._stopping.is_set())

    def restart(self):
        """Re-open a dropped tunnel on the same local port, so existing connector settings stay valid."""
        port = self.local_port
        self._shutdown(keep_port=True)
        self._stopping.clear()
        self.local_port = port
        self.start()

    def stop(self):
        self._shutdown(keep_port=False)

    def _shutdown(self, keep_port: bool):
        self._stopping.set()
        for closer in (self._listener, self._transport):
            try:
                if closer:
                    closer.close()
            except Exception:
                pass
        self._listener = self._transport = None
        if not keep_port:
            self.local_port = None

    # -- connecting ---------------------------------------------------------------------------------

    def _connect_transport(self):
        try:
            sock = socket.create_connection((self.ssh_host, self.ssh_port), timeout=self._timeout)
        except OSError as e:
            raise SSHError(f'Could not reach the SSH server {self.ssh_host}:{self.ssh_port} ({e}).') from e
        transport = paramiko.Transport(sock)
        try:
            transport.start_client(timeout=self._timeout)
            self._verify_host_key(transport)
            self._authenticate(transport)
        except BaseException:
            transport.close()
            raise
        transport.set_keepalive(30)
        self._transport = transport

    def _verify_host_key(self, transport: paramiko.Transport):
        key = transport.get_remote_server_key()
        fp, key_type = fingerprint(key), key.get_name()
        known = self.known_hosts.get(self.ssh_host, self.ssh_port)
        if known:
            if known['fingerprint'] != fp:
                raise HostKeyChanged(self.ssh_host, self.ssh_port, known['fingerprint'], fp)
        elif self.trust == fp:
            self.known_hosts.add(self.ssh_host, self.ssh_port, key_type, fp)
        else:
            raise UnknownHostKey(self.ssh_host, self.ssh_port, key_type, fp)

    def _load_key(self) -> paramiko.PKey:
        path = os.path.expanduser(self._key_path)
        passphrase = self._passphrase.encode() if self._passphrase else None  # paramiko 5 requires bytes
        try:
            return paramiko.PKey.from_path(path, passphrase)
        except FileNotFoundError as e:
            raise SSHError(f'The SSH key file {self._key_path} was not found.') from e
        except paramiko.PasswordRequiredException as e:
            raise SSHError('The SSH key is protected by a passphrase. Enter it in the connection settings.') from e
        except TypeError as e:  # paramiko 5: "Password was not given but private key is encrypted"
            if 'not given' in str(e):
                raise SSHError('The SSH key is protected by a passphrase. Enter it in the connection settings.') from e
            raise
        except ValueError as e:
            if 'password' in str(e).lower() or 'decrypt' in str(e).lower():
                raise SSHError('Wrong passphrase for the SSH key.') from e
            raise SSHError('The SSH key file is not a usable private key (supported: OpenSSH and PEM formats).') from e
        except paramiko.SSHException as e:
            raise SSHError('The SSH key could not be read. Check the passphrase and that the file is a private key.') from e

    def _authenticate(self, transport: paramiko.Transport):
        try:
            if self._key_path:
                transport.auth_publickey(self.username, self._load_key())
            elif self._password:
                transport.auth_password(self.username, self._password)
            else:
                raise SSHError('Enter an SSH password or choose a private key file.')
        except paramiko.AuthenticationException as e:
            raise SSHError(f'The SSH server refused the login for user "{self.username}". '
                           'Check the user name and the password or key.') from e
        except paramiko.SSHException as e:
            raise SSHError(f'SSH login failed: {e}') from e

    def _open_channel(self, origin=('127.0.0.1', 0)):
        try:
            return self._transport.open_channel('direct-tcpip', (self.remote_host, self.remote_port), origin)
        except paramiko.ChannelException as e:
            reason = str(e)
            if 'prohibited' in reason.lower():
                raise SSHError('The SSH server does not allow port forwarding (AllowTcpForwarding is off).') from e
            raise SSHError(f'The SSH server could not connect to {self.remote_host}:{self.remote_port} ({reason}). '
                           'Check the database host and port as seen from the SSH server.') from e
        except (paramiko.SSHException, EOFError, OSError) as e:
            raise SSHError(f'The SSH connection dropped ({e}).') from e

    def _check_target(self):
        self._open_channel().close()

    # -- forwarding ---------------------------------------------------------------------------------

    def _open_listener(self, port: int):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(('127.0.0.1', port))
        listener.listen(32)
        self._listener = listener
        self.local_port = listener.getsockname()[1]

    def _accept_loop(self, listener: socket.socket):
        while not self._stopping.is_set():
            try:
                client, addr = listener.accept()
            except OSError:
                return  # listener closed
            threading.Thread(target=self._serve, args=(client, addr), daemon=True, name='ssh-tunnel-conn').start()

    def _serve(self, client: socket.socket, addr):
        try:
            channel = self._open_channel(addr)
        except SSHError as e:
            logger.warning('SSH tunnel could not open a connection: %s', e)
            client.close()
            return
        try:
            while True:
                readable, _, _ = select.select([client, channel], [], [], 1.0)
                if self._stopping.is_set():
                    break
                if client in readable:
                    data = client.recv(32768)
                    if not data:
                        break
                    channel.sendall(data)
                if channel in readable:
                    data = channel.recv(32768)
                    if not data:
                        break
                    client.sendall(data)
        except (OSError, EOFError, paramiko.SSHException):
            pass
        finally:
            for c in (channel, client):
                try:
                    c.close()
                except Exception:
                    pass
