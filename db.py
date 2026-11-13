from flask import Flask, Response, abort, jsonify, request
from werkzeug.exceptions import HTTPException
from flask.json.provider import DefaultJSONProvider
import atexit
import contextlib
import json
import logging
import os
import secrets
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from cryptography.fernet import Fernet
import base64
import shutil
from datetime import datetime, date
from typing import Dict, Any, Optional

# Import connectors
from db_connectors.sqlite import SQLiteConnector
from db_connectors.postgres import PostgreSQLConnector
from db_connectors.mysql import MySQLConnector
from db_connectors.sqlserver import SQLServerConnector
from db_connectors.oracle import OracleConnector
from db_connectors.mongodb import MongoDBConnector
from db_connectors.redis import RedisConnector
from db_connectors.cassandra import CassandraConnector
from db_connectors import safety
from db_connectors.base import binary_text
from sample_data import build_sample
import ai_assistant
import csv_import
import relationship_inference
from db_connectors.tunnel import KnownHosts, SSHError, SSHTunnel, UnknownHostKey


def plain_value(obj):
    """Something a database returned that JSON has no type for, as text the grid and the exports can show.
    A table with a binary, set or interval column must still open, whatever the column holds."""
    if isinstance(obj, (bytes, bytearray, memoryview)):
        return binary_text(obj)
    if isinstance(obj, (set, frozenset)):
        return sorted(obj, key=str)
    if hasattr(obj, 'isoformat'):      # a time of day
        return obj.isoformat()
    return str(obj)


JS_SAFE_INT = 2 ** 53 - 1   # the largest whole number a browser holds exactly


def exact_ints(obj):
    """A browser rounds integers beyond 2**53, which would show a wrong id and make a save look for a row that is not
    there (or a different one). Such integers are sent as text; everything else is untouched."""
    if isinstance(obj, int) and not isinstance(obj, bool):
        return str(obj) if abs(obj) > JS_SAFE_INT else obj
    if isinstance(obj, dict):
        return {k: exact_ints(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [exact_ints(v) for v in obj]
    return obj


# Custom JSON encoder to handle datetime objects
class CustomJSONProvider(DefaultJSONProvider):
    def dumps(self, obj, **kwargs):
        return super().dumps(exact_ints(obj), **kwargs)

    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.strftime('%Y-%m-%d %H:%M:%S')
        elif isinstance(obj, date):
            return obj.strftime('%Y-%m-%d')
        try:
            return super().default(obj)
        except TypeError:
            return plain_value(obj)


__version__ = '1.0.0'
APP_NAME = 'DB Visualizer'
STATIC_DIR = Path(getattr(sys, '_MEIPASS', Path(__file__).parent)) / 'static'


def _data_dir() -> Path:
    """Per-user writable directory; the app bundle itself is read-only once packaged."""
    if os.environ.get('DBV_DATA_DIR'):
        return Path(os.environ['DBV_DATA_DIR'])
    if sys.platform == 'darwin':
        base = Path.home() / 'Library' / 'Application Support'
    elif sys.platform == 'win32':
        base = Path(os.environ.get('APPDATA', Path.home()))
    else:
        base = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local' / 'share'))
    return base / APP_NAME


# Configuration
CONFIG_DIR = _data_dir()
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
os.chmod(CONFIG_DIR, 0o700)
CONNECTIONS_FILE = CONFIG_DIR / 'connections.json'
KEY_FILE = CONFIG_DIR / 'secret.key'
CERTS_DIR = CONFIG_DIR / 'certs'

handlers = [RotatingFileHandler(CONFIG_DIR / 'app.log', maxBytes=1_000_000, backupCount=3)]
if sys.stderr:  # absent in a windowed app bundle
    handlers.append(logging.StreamHandler())
logging.basicConfig(level=logging.INFO, handlers=handlers,
                    format='%(asctime)s %(levelname)s %(name)s: %(message)s')
logger = logging.getLogger('dbviz')


def _migrate_legacy_config():
    """One-time import of the old ./config folder (pre-1.0 kept data next to the code)."""
    import shutil
    legacy = Path(__file__).parent / 'config'
    # An explicit data dir (tests, portable installs) must never inherit someone's saved credentials
    if os.environ.get('DBV_DATA_DIR') or CONNECTIONS_FILE.exists() or not (legacy / 'connections.json').exists():
        return
    for name in ('connections.json', 'secret.key'):
        if (legacy / name).exists():
            shutil.copy2(legacy / name, CONFIG_DIR / name)
            os.chmod(CONFIG_DIR / name, 0o600)
    if (legacy / 'certs').exists():
        shutil.copytree(legacy / 'certs', CERTS_DIR, dirs_exist_ok=True)
    logger.info('Imported legacy config from %s', legacy)


_migrate_legacy_config()

# Flask app initialization
app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path='/static')
app.json = CustomJSONProvider(app)
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024  # cert uploads are tiny; this just bounds abuse

# The UI is same-origin, so there is deliberately no CORS. Every /api call must carry this
# per-launch token (injected into the served page), so other local processes and web pages
# the user visits cannot drive the connected databases.
APP_TOKEN = secrets.token_urlsafe(32)
ALLOWED_HOSTS = {'127.0.0.1', 'localhost'}

MAX_PAGE_SIZE = 10000
SQL_TYPES = {'sqlite', 'postgresql', 'mysql', 'sqlserver', 'oracle'}

# Active connections pool
active_connections: Dict[str, Any] = {}

# Connector classes mapping
CONNECTOR_CLASSES = {
    'sqlite': SQLiteConnector,
    'postgresql': PostgreSQLConnector,
    'mysql': MySQLConnector,
    'sqlserver': SQLServerConnector,
    'oracle': OracleConnector,
    'mongodb': MongoDBConnector,
    'redis': RedisConnector,
    'cassandra': CassandraConnector
}


# Where the encryption key for saved passwords lives. 'keychain' is the OS credential store (macOS Keychain,
# Windows Credential Manager, Secret Service); 'file' keeps secret.key beside the data. An explicit data
# directory means a portable or test setup, so it defaults to 'file' and never touches the user's keychain.
KEY_STORE = os.environ.get('DBV_KEY_STORE') or ('file' if os.environ.get('DBV_DATA_DIR') else 'keychain')
KEY_SERVICE = os.environ.get('DBV_KEYRING_SERVICE', APP_NAME)
KEY_ACCOUNT = 'connection-encryption-key'
_key_cache: Optional[bytes] = None


def _os_keyring():
    """The OS credential store, or None when there is no working one (headless Linux, store disabled)."""
    if KEY_STORE != 'keychain':
        return None
    try:
        import keyring
        from keyring.backends import fail
        return None if isinstance(keyring.get_keyring(), fail.Keyring) else keyring
    except Exception as e:
        logger.warning('No OS keychain available (%s); keeping the encryption key in a file', e)
        return None


def _read_key_file() -> Optional[bytes]:
    return KEY_FILE.read_bytes().strip() if KEY_FILE.exists() else None


def _write_key_file(key: bytes):
    with os.fdopen(os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as f:
        f.write(key)


def load_key() -> bytes:
    """The Fernet key for saved passwords.

    A key that already exists is never replaced: a new key would make every saved password unreadable.
    So if the keychain cannot be read (locked, denied) and there is no file copy, this raises instead of
    inventing a key.
    """
    global _key_cache
    if _key_cache:
        return _key_cache

    file_key = _read_key_file()
    store = _os_keyring()
    key = None
    if store:
        try:
            stored = store.get_password(KEY_SERVICE, KEY_ACCOUNT)
        except Exception as e:
            if file_key is None:
                raise RuntimeError(f'Could not read the encryption key from the system keychain ({e}). '
                                   'Unlock the keychain and restart the app.') from e
            logger.warning('Could not read the keychain (%s); using the key file', e)
            stored = None
            store = None
        if store:
            if stored:
                key = stored.encode()
                if file_key and file_key != key:
                    logger.warning('secret.key differs from the key in the keychain; using the keychain')
            else:
                # First run with the keychain: adopt the existing file key (migration), or make a new one
                candidate = file_key or Fernet.generate_key()
                try:
                    store.set_password(KEY_SERVICE, KEY_ACCOUNT, candidate.decode())
                    if store.get_password(KEY_SERVICE, KEY_ACCOUNT) != candidate.decode():
                        raise RuntimeError('the keychain did not return the stored key')
                    key = candidate
                    if file_key:
                        KEY_FILE.unlink()  # the key now lives only in the keychain
                        logger.info('Moved the encryption key from secret.key into the system keychain')
                except Exception as e:
                    logger.warning('Could not store the key in the keychain (%s); using the key file', e)

    if key is None:  # no keychain, or it could not be used: the file is the store
        key = file_key
        if key is None:
            key = Fernet.generate_key()
            _write_key_file(key)
    _key_cache = key
    return key


def get_cipher():
    """Fernet cipher for saved passwords."""
    return Fernet(load_key())


def encrypt_password(password: str) -> str:
    """Encrypt a password."""
    if not password:
        return ''
    cipher = get_cipher()
    return cipher.encrypt(password.encode()).decode()


def decrypt_password(encrypted: str) -> str:
    """Decrypt a password."""
    if not encrypted:
        return ''
    cipher = get_cipher()
    return cipher.decrypt(encrypted.encode()).decode()


def save_certificate_file(connection_id: str, cert_type: str, cert_base64: str, filename: str) -> str:
    """Save a certificate file and return its path."""
    # Ensure certs directory exists
    CERTS_DIR.mkdir(exist_ok=True)

    # Create connection-specific directory
    conn_cert_dir = CERTS_DIR / connection_id
    conn_cert_dir.mkdir(exist_ok=True)

    # Decode base64 and save file
    cert_data = base64.b64decode(cert_base64)
    cert_path = conn_cert_dir / filename

    with open(cert_path, 'wb') as f:
        f.write(cert_data)

    return str(cert_path)


def store_certs(data: Dict, connection_id: str):
    """Replace uploaded base64 certs in data with paths of the saved files."""
    if not data.get('use_ssl'):
        return
    for field in ('ca_cert', 'client_cert', 'client_key'):
        if data.get(field) and data.get(field + '_filename'):
            data[field + '_path'] = save_certificate_file(
                connection_id, field, data.pop(field), data.pop(field + '_filename'))


# Every change to the saved connections reads the list, changes it and writes it back: two at once would undo each other
CONNECTIONS_LOCK = threading.RLock()


def load_connections() -> list:
    """Load saved connections from file."""
    if not CONNECTIONS_FILE.exists():
        return []

    try:
        with open(CONNECTIONS_FILE, 'r') as f:
            encrypted_connections = json.load(f)
    except (OSError, ValueError) as e:
        # Never fall through to [] silently: the next save would overwrite the user's connections.
        backup = CONNECTIONS_FILE.with_suffix('.corrupt')
        os.replace(CONNECTIONS_FILE, backup)
        logger.error('connections.json unreadable (%s); moved to %s', e, backup)
        return []

    connections = []
    for conn in encrypted_connections:
        conn_copy = conn.copy()
        unreadable = {}
        for field in SECRET_FIELDS:
            if conn_copy.get(field):
                try:
                    conn_copy[field] = decrypt_password(conn_copy[field])
                except Exception:
                    logger.warning('Could not decrypt %s for %s (wrong or missing key?)', field, conn.get('id'))
                    unreadable[field] = conn_copy[field]  # keep the ciphertext so a later save does not erase it
                    conn_copy[field] = ''
        if unreadable:
            conn_copy['_unreadable_secrets'] = unreadable
        connections.append(conn_copy)
    return connections


def save_connections(connections: list):
    """Save connections to file with encrypted passwords."""
    try:
        encrypted_connections = []
        for conn in connections:
            conn_copy = conn.copy()
            kept = conn_copy.pop('_unreadable_secrets', {})
            for field in SECRET_FIELDS:
                if conn_copy.get(field):
                    conn_copy[field] = encrypt_password(conn_copy[field])
                elif kept.get(field):
                    conn_copy[field] = kept[field]  # unreadable before, and the user has not set a new one
            encrypted_connections.append(conn_copy)

        # Atomic write (temp file + rename) with a rolling backup, so a crash can't truncate the file
        tmp = CONNECTIONS_FILE.with_suffix('.tmp')
        with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as f:
            json.dump(encrypted_connections, f, indent=2)
        if CONNECTIONS_FILE.exists():
            os.replace(CONNECTIONS_FILE, CONNECTIONS_FILE.with_suffix('.bak'))
        os.replace(tmp, CONNECTIONS_FILE)
        return True
    except Exception:
        logger.exception('Error saving connections')
        return False


IDLE_PING_SECONDS = 30   # after this long unused, prove the connection is alive before trusting it
QUERY_TIMEOUT = int(os.environ.get('DBV_QUERY_TIMEOUT', 60))  # seconds; 0 disables
# Connection-level calls that must not trigger a health check (they are how the check itself works)
_NO_HEALTH_CHECK = {'connect', 'disconnect', 'test_connection', 'ping', 'is_connected', 'get_connection_info'}
cancel_reasons: Dict[str, str] = {}  # why a running query was stopped, so the user sees a clear message


class SerializedConnector:
    """Wraps a live database connection so that requests can share it safely.

    - One request at a time: the server handles requests on parallel threads, and the UI fires many at once
      (autocomplete loads every table's schema on connect). pymysql, sqlite3 and others cannot share one
      connection across threads ("Command Out of Sync", "(0, '')").
    - Reconnect: idle connections are dropped by servers and firewalls. After a quiet spell, or after any
      failure, the next call first pings; a dead connection is re-opened instead of failing the user.
    - cancel() deliberately skips the lock, since the query to cancel is the one holding it.
    Everything else (attributes, methods) is passed straight through to the real connector.
    """

    def __init__(self, connector, tunnel: Optional[SSHTunnel] = None):
        self._connector = connector
        self._tunnel = tunnel
        self._lock = threading.RLock()
        self._last_used = time.monotonic()
        self._suspect = False

    def cancel(self):
        return self._connector.cancel()

    def close_tunnel(self):
        if self._tunnel:
            self._tunnel.stop()
            self._tunnel = None

    def _ensure_alive(self):
        if self._tunnel and not self._tunnel.alive():
            logger.warning('SSH tunnel to %s dropped; re-opening', self._tunnel.ssh_host)
            self._tunnel.restart()  # same local port, so the connector's settings stay valid
            self._suspect = True    # the database session went down with it: ping, then reconnect
        if not self._suspect and time.monotonic() - self._last_used < IDLE_PING_SECONDS:
            return
        if self._connector.ping():
            self._suspect = False
            return
        logger.warning('Connection to %s was lost; reconnecting', self._connector.connection_params.get('name'))
        self._connector.disconnect()
        if not self._connector.connect():
            raise ConnectionError('The database connection was lost and could not be re-opened. '
                                  'Check that the server is reachable, then try again.')
        self._suspect = False

    def __getattr__(self, name):
        attr = getattr(self._connector, name)
        if not callable(attr):
            return attr
        check = name not in _NO_HEALTH_CHECK

        def locked(*args, **kwargs):
            with self._lock:
                if check:
                    self._ensure_alive()
                try:
                    result = attr(*args, **kwargs)
                except Exception:
                    self._suspect = True
                    raise
                if isinstance(result, dict) and result.get('error'):
                    self._suspect = True  # connectors report failures as data; ping before the next call
                self._last_used = time.monotonic()
                return result
        return locked


def get_connector(connection_id: str) -> Optional[Any]:
    """Get active connector by connection ID."""
    return active_connections.get(connection_id)


def error_response(e: Exception):
    """JSON for a failed request. A lost database connection is 503 (try again later), anything else 500."""
    return jsonify({'success': False, 'error': str(e)}), (503 if isinstance(e, ConnectionError) else 500)


SECRET_FIELDS = ('password', 'ssh_password', 'ssh_passphrase')  # encrypted at rest, masked in the API
DEFAULT_PORTS = {'mysql': 3306, 'postgresql': 5432, 'sqlserver': 1433, 'oracle': 1521, 'mongodb': 27017,
                 'redis': 6379, 'cassandra': 9042}
KNOWN_HOSTS = KnownHosts(CONFIG_DIR / 'known_hosts.json')


def start_tunnel(params: Dict, trust: Optional[str] = None) -> SSHTunnel:
    """Open the SSH tunnel a connection asks for. Raises SSHError (UnknownHostKey when the server key must be
    confirmed by the user first)."""
    if params.get('connection_url'):
        raise SSHError('An SSH tunnel needs the database host and port. Clear the connection URL and fill those in.')
    if not params.get('ssh_host'):
        raise SSHError('Enter the SSH server address.')
    use_key = params.get('ssh_auth') == 'key'
    tunnel = SSHTunnel(
        params['ssh_host'], params.get('ssh_port') or 22, params.get('ssh_user') or '',
        params.get('host') or 'localhost', params.get('port') or DEFAULT_PORTS.get(params.get('type', '').lower(), 0),
        known_hosts=KNOWN_HOSTS, trust=trust,
        password=None if use_key else params.get('ssh_password'),
        key_path=params.get('ssh_key_path') if use_key else None,
        passphrase=params.get('ssh_passphrase') if use_key else None)
    tunnel.start()
    return tunnel


def tunnel_error_response(e: SSHError):
    if isinstance(e, UnknownHostKey):  # not a failure yet: the UI asks the user whether to trust this server
        return jsonify({'success': False, 'needs_host_key_confirmation': True, 'host': e.host, 'port': e.port,
                        'key_type': e.key_type, 'fingerprint': e.fingerprint, 'error': str(e)}), 409
    return jsonify({'success': False, 'error': str(e)}), 502


def read_only_error(connector) -> Optional[Any]:
    """A 403 response when the connection is marked read-only, else None. Used by every write endpoint."""
    if connector.connection_params.get('read_only'):
        return jsonify({'success': False, 'read_only': True,
                        'error': 'This connection is read-only. Edit the connection to allow changes.'}), 403
    return None


def create_connector(conn_params: Dict) -> Optional[Any]:
    """Create a new connector instance."""
    db_type = conn_params.get('type', '').lower()
    connector_class = CONNECTOR_CLASSES.get(db_type)

    if not connector_class:
        return None

    return connector_class(conn_params)


# API Routes

@app.before_request
def guard_local_api():
    # Host check defeats DNS-rebinding; the token check defeats cross-origin / other-process calls
    if request.host.split(':')[0] not in ALLOWED_HOSTS:
        abort(403)
    if request.path.startswith('/api/') and not secrets.compare_digest(
            request.headers.get('X-DBV-Token', ''), APP_TOKEN):
        abort(403)


@app.after_request
def security_headers(resp):
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    resp.headers['X-Frame-Options'] = 'DENY'
    resp.headers['Referrer-Policy'] = 'no-referrer'
    resp.headers['Cache-Control'] = 'no-store' if request.path.startswith('/api/') else resp.headers.get('Cache-Control', 'no-cache')
    return resp


@app.errorhandler(Exception)
def handle_error(e):
    if isinstance(e, HTTPException):
        return jsonify({'success': False, 'error': e.description}), e.code
    if isinstance(e, ConnectionError):
        return jsonify({'success': False, 'error': str(e)}), 503
    logger.exception('Unhandled error on %s %s', request.method, request.path)
    return error_response(e)


@app.route('/')
def index():
    """Serve the main page with the per-launch API token attached to every fetch, and the saved theme applied
    before the first paint so there is no flash of the wrong one."""
    html = (STATIC_DIR / 'index.html').read_text(encoding='utf-8')
    theme = ('(function(){var p=%s,r=document.documentElement;r.dataset.themePref=p;'
             "r.dataset.theme=p==='system'?(matchMedia('(prefers-color-scheme: light)').matches?'light':'dark'):p;})();"
             % json.dumps(saved_theme()))
    bootstrap = (
        '<script>(function(){var t=%s,f=window.fetch;window.fetch=function(u,o){o=o||{};'
        "if(typeof u==='string'&&u.charAt(0)==='/'){o.headers=Object.assign({},o.headers,{'X-DBV-Token':t});}"
        'return f.call(this,u,o);};})();%s</script>' % (json.dumps(APP_TOKEN), theme))
    return Response(html.replace('<head>', '<head>' + bootstrap, 1), mimetype='text/html')


ENVIRONMENTS = ('', 'local', 'development', 'staging', 'production')


def next_connection_id(connections: list) -> str:
    taken = {int(c['id'][5:]) for c in connections if str(c.get('id', '')).startswith('conn_') and c['id'][5:].isdigit()}
    n = 1
    while n in taken:
        n += 1
    return f'conn_{n}'


# ---- settings and the optional AI assistant ----------------------------------------------------------------------

SETTINGS_FILE = CONFIG_DIR / 'settings.json'
AI_BASE_URL = os.environ.get('DBV_AI_BASE_URL')   # tests point this at a local fake of the API


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS_FILE.read_text())
    except (OSError, ValueError):
        return {}


def save_settings(settings: dict):
    tmp = SETTINGS_FILE.with_suffix('.tmp')
    with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as f:
        json.dump(settings, f, indent=2)
    os.replace(tmp, SETTINGS_FILE)


# ---- saved queries: SQL you want to keep, stored on disk so a webview that forgets its storage cannot lose them --------

SAVED_QUERIES_FILE = CONFIG_DIR / 'saved_queries.json'
SAVED_QUERIES_LOCK = threading.Lock()
MAX_SAVED_QUERIES = 500
MAX_QUERY_NAME = 100
MAX_QUERY_SQL = 100_000


def load_saved_queries() -> list:
    try:
        queries = json.loads(SAVED_QUERIES_FILE.read_text(encoding='utf-8'))
        if not isinstance(queries, list):
            return []
        return [q for q in queries if isinstance(q, dict) and all(isinstance(q.get(k), str) for k in ('id', 'name', 'sql'))]
    except FileNotFoundError:
        return []
    except (OSError, ValueError):
        # unreadable: keep a copy so the next save cannot silently destroy whatever is in there
        try:
            shutil.copy2(SAVED_QUERIES_FILE, SAVED_QUERIES_FILE.with_suffix('.corrupt.json'))
        except OSError:
            pass
        return []


def write_saved_queries(queries: list):
    tmp = SAVED_QUERIES_FILE.with_suffix('.tmp')
    with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w', encoding='utf-8') as f:
        json.dump(queries, f, indent=2, ensure_ascii=False)
    os.replace(tmp, SAVED_QUERIES_FILE)


def clean_query_fields(data: dict, need_both: bool):
    """(name, sql, error): trimmed, length-checked values from a request body."""
    name, sql = data.get('name'), data.get('sql')
    if (need_both or name is not None) and (not isinstance(name, str) or not name.strip()):
        return None, None, 'Give the query a name.'
    if (need_both or sql is not None) and (not isinstance(sql, str) or not sql.strip()):
        return None, None, 'There is no SQL to save.'
    if name is not None and len(name.strip()) > MAX_QUERY_NAME:
        return None, None, f'The name can be at most {MAX_QUERY_NAME} characters.'
    if sql is not None and len(sql) > MAX_QUERY_SQL:
        return None, None, f'A saved query can be at most {MAX_QUERY_SQL:,} characters.'
    return (name.strip() if name is not None else None), sql, None


def query_summary(q: dict) -> dict:
    return {k: q.get(k) for k in ('id', 'name', 'sql', 'connection_name', 'updated')}


def find_by_name(queries: list, name: str):
    return next((q for q in queries if q['name'].casefold() == name.casefold()), None)


@app.route('/api/saved-queries', methods=['GET'])
def list_saved_queries():
    with SAVED_QUERIES_LOCK:
        queries = load_saved_queries()
    queries.sort(key=lambda q: q.get('updated', ''), reverse=True)
    return jsonify({'success': True, 'queries': [query_summary(q) for q in queries]})


@app.route('/api/saved-queries', methods=['POST'])
def create_saved_query():
    """Save a query under a name. A name that already exists is a 409 unless `replace` is true."""
    data = request.get_json(silent=True) or {}
    name, sql, problem = clean_query_fields(data, need_both=True)
    if problem:
        return jsonify({'success': False, 'error': problem}), 400
    connection = data.get('connection_name')
    connection = connection.strip()[:MAX_QUERY_NAME] if isinstance(connection, str) and connection.strip() else None
    now = datetime.now().isoformat(timespec='microseconds')
    with SAVED_QUERIES_LOCK:
        queries = load_saved_queries()
        existing = find_by_name(queries, name)
        if existing and not data.get('replace'):
            return jsonify({'success': False, 'exists': True, 'id': existing['id'],
                            'error': f'A saved query called "{existing["name"]}" already exists.'}), 409
        if existing:
            existing.update(sql=sql, connection_name=connection, updated=now)
            saved = existing
        else:
            if len(queries) >= MAX_SAVED_QUERIES:
                return jsonify({'success': False, 'error': f'You can keep at most {MAX_SAVED_QUERIES} saved queries. Delete some first.'}), 400
            saved = {'id': secrets.token_hex(6), 'name': name, 'sql': sql, 'connection_name': connection, 'updated': now}
            queries.append(saved)
        write_saved_queries(queries)
    return jsonify({'success': True, 'query': query_summary(saved)}), (200 if existing else 201)


@app.route('/api/saved-queries/<query_id>', methods=['PUT'])
def update_saved_query(query_id):
    """Rename a saved query and/or change its SQL."""
    name, sql, problem = clean_query_fields(request.get_json(silent=True) or {}, need_both=False)
    if problem:
        return jsonify({'success': False, 'error': problem}), 400
    if name is None and sql is None:
        return jsonify({'success': False, 'error': 'Nothing to change.'}), 400
    with SAVED_QUERIES_LOCK:
        queries = load_saved_queries()
        target = next((q for q in queries if q.get('id') == query_id), None)
        if not target:
            return jsonify({'success': False, 'error': 'That saved query no longer exists.'}), 404
        clash = find_by_name(queries, name) if name is not None else None
        if clash and clash is not target:
            return jsonify({'success': False, 'exists': True, 'error': f'A saved query called "{clash["name"]}" already exists.'}), 409
        if name is not None:
            target['name'] = name
        if sql is not None:
            target['sql'] = sql
        target['updated'] = datetime.now().isoformat(timespec='microseconds')
        write_saved_queries(queries)
    return jsonify({'success': True, 'query': query_summary(target)})


@app.route('/api/saved-queries/<query_id>', methods=['DELETE'])
def delete_saved_query(query_id):
    with SAVED_QUERIES_LOCK:
        queries = load_saved_queries()
        kept = [q for q in queries if q.get('id') != query_id]
        if len(kept) == len(queries):
            return jsonify({'success': False, 'error': 'That saved query no longer exists.'}), 404
        write_saved_queries(kept)
    return jsonify({'success': True})


THEMES = ('system', 'light', 'dark')


def saved_theme() -> str:
    theme = load_settings().get('theme')
    return theme if theme in THEMES else 'system'


@app.route('/api/theme', methods=['GET'])
def get_theme():
    return jsonify({'success': True, 'theme': saved_theme()})


@app.route('/api/theme', methods=['PUT'])
def put_theme():
    """Remember the theme: system (follow the operating system), light or dark."""
    theme = (request.get_json(silent=True) or {}).get('theme')
    if theme not in THEMES:
        return jsonify({'success': False, 'error': 'Theme must be system, light or dark.'}), 400
    settings = load_settings()
    settings['theme'] = theme
    save_settings(settings)
    return jsonify({'success': True, 'theme': theme})


def ai_api_key() -> Optional[str]:
    """The saved key (encrypted at rest), else the environment's, else None."""
    saved = load_settings().get('ai_api_key')
    if saved:
        try:
            return decrypt_password(saved)
        except Exception:
            logger.warning('The saved assistant API key could not be decrypted')
    return os.environ.get('ANTHROPIC_API_KEY') or None


@app.route('/api/ai/settings', methods=['GET'])
def get_ai_settings():
    settings = load_settings()
    return jsonify({'success': True, 'enabled': bool(settings.get('ai_enabled')), 'has_key': bool(settings.get('ai_api_key')),
                    'env_key': bool(os.environ.get('ANTHROPIC_API_KEY')), 'model': ai_assistant.MODEL})


@app.route('/api/ai/settings', methods=['PUT'])
def put_ai_settings():
    """Turn the assistant on or off, and set or remove its API key. The key is never returned."""
    data = (request.get_json(silent=True) or {})
    settings = load_settings()
    if data.get('remove_key'):
        settings.pop('ai_api_key', None)
    key = (data.get('api_key') or '').strip()
    if key:
        if len(key) > 500 or any(c.isspace() for c in key):
            return jsonify({'success': False, 'error': 'That does not look like an API key.'}), 400
        settings['ai_api_key'] = encrypt_password(key)
    if 'enabled' in data:
        if data['enabled'] and not settings.get('ai_api_key') and not os.environ.get('ANTHROPIC_API_KEY'):
            return jsonify({'success': False, 'error': 'Enter an Anthropic API key to turn the assistant on.'}), 400
        settings['ai_enabled'] = bool(data['enabled'])
    save_settings(settings)
    return get_ai_settings()


@app.route('/api/ai/sql', methods=['POST'])
def ai_sql():
    """Write one SQL statement from a plain-English request. It is only returned, never run."""
    data = (request.get_json(silent=True) or {})
    if not load_settings().get('ai_enabled'):
        return jsonify({'success': False, 'needs_setup': True,
                        'error': 'The assistant is turned off. Turn it on in its settings first.'}), 403
    text = (data.get('request') or '').strip()
    if not text:
        return jsonify({'success': False, 'error': 'Describe what you want first.'}), 400
    if len(text) > ai_assistant.MAX_REQUEST_CHARS:
        return jsonify({'success': False, 'error': f'Keep the request under {ai_assistant.MAX_REQUEST_CHARS} characters.'}), 400

    connector = get_connector(data.get('connection_id'))
    if not connector:
        return jsonify({'success': False, 'error': 'Not connected'}), 400
    db_type = str(connector.connection_params.get('type', '')).lower()
    if db_type not in ai_assistant.DIALECTS:
        return jsonify({'success': False, 'error': 'The assistant works with SQL databases only.'}), 400

    try:
        database = data.get('database')
        tables = [t['name'] for t in connector.get_tables(database)]
        columns = connector.get_columns(database)
        prompt = ai_assistant.build_prompt(db_type, tables, columns, connector.get_relations(database), text)
        if data.get('preview'):
            return jsonify({'success': True, 'preview': prompt})

        key = ai_api_key()
        if not key:
            return jsonify({'success': False, 'needs_setup': True, 'error': 'Add an Anthropic API key in the assistant settings.'}), 400
        reply = ai_assistant.ask(prompt, key, AI_BASE_URL)
    except ai_assistant.AIError as e:
        return jsonify({'success': False, 'error': str(e)}), e.status
    except Exception as e:
        return error_response(e)

    parsed = ai_assistant.parse_reply(reply['text'])
    result = {'success': True, **parsed, 'truncated': reply['truncated'],
              'usage': {'model': reply['model'], 'input_tokens': reply['input_tokens'], 'output_tokens': reply['output_tokens']}}
    if parsed['sql']:
        verdict = safety.check(db_type, parsed['sql'])
        result.update(read_only=verdict.read_only, destructive=verdict.destructive, why_not=verdict.why_not)
    return jsonify(result)


@app.route('/api/sample', methods=['POST'])
def open_sample():
    """Create (once) a small sample database and a saved connection to it, so a first run has something to explore."""
    path = CONFIG_DIR / 'sample' / 'shop.db'
    if not path.exists():
        build_sample(path)
    with CONNECTIONS_LOCK:
        connections = load_connections()
        existing = next((c for c in connections if c.get('sample')), None)
        if existing:
            if existing.get('database') != str(path):  # the data folder moved
                existing['database'] = str(path)
                save_connections(connections)
            return jsonify({'success': True, 'id': existing['id']})
        conn = {'id': next_connection_id(connections), 'name': 'Sample shop', 'type': 'sqlite', 'database': str(path),
                'environment': 'local', 'sample': True}
        connections.append(conn)
        if not save_connections(connections):
            return jsonify({'success': False, 'error': 'Could not save the sample connection'}), 500
        return jsonify({'success': True, 'id': conn['id']})


@app.route('/api/connections', methods=['GET'])
def get_connections():
    """Get all saved connections (without passwords)."""
    connections = load_connections()

    # Remove passwords from response
    safe_connections = []
    for conn in connections:
        safe_conn = conn.copy()
        safe_conn.pop('_unreadable_secrets', None)
        for field in SECRET_FIELDS:
            if field in safe_conn:
                safe_conn[field] = '***' if safe_conn[field] else ''
        safe_connections.append(safe_conn)

    return jsonify({'connections': safe_connections})


@app.route('/api/connections', methods=['POST'])
def save_connection():
    """Save a new connection."""
    data = (request.get_json(silent=True) or {})
    if data.get('environment', '') not in ENVIRONMENTS:
        return jsonify({'success': False, 'error': 'Unknown environment'}), 400
    with CONNECTIONS_LOCK:
        connections = load_connections()

        connection_id = data['id'] if data.get('id') else next_connection_id(connections)

        data['id'] = connection_id

        store_certs(data, connection_id)

        connections.append(data)

        if save_connections(connections):
            return jsonify({'success': True, 'id': connection_id})
        else:
            return jsonify({'success': False, 'error': 'Failed to save connection'}), 500


@app.route('/api/connections/<connection_id>', methods=['PUT'])
def update_connection(connection_id):
    """Update an existing connection."""
    data = (request.get_json(silent=True) or {})
    if data.get('environment', '') not in ENVIRONMENTS:
        return jsonify({'success': False, 'error': 'Unknown environment'}), 400
    with CONNECTIONS_LOCK:
        connections = load_connections()

        # The edit form never shows the stored password, so a blank/masked one means "unchanged"
        for field in SECRET_FIELDS:
            if data.get(field) in (None, '', '***'):
                data.pop(field, None)

        # Find and update connection
        for i, conn in enumerate(connections):
            if conn.get('id') == connection_id:
                store_certs(data, connection_id)
                connections[i] = {**conn, **data, 'id': connection_id}
                if save_connections(connections):
                    return jsonify({'success': True})
                else:
                    return jsonify({'success': False, 'error': 'Failed to update connection'}), 500

        return jsonify({'success': False, 'error': 'Connection not found'}), 404


@app.route('/api/connections/<connection_id>', methods=['DELETE'])
def delete_connection(connection_id):
    """Delete a connection."""
    with CONNECTIONS_LOCK:
        connections = load_connections()

        # Filter out the connection to delete
        connections = [conn for conn in connections if conn.get('id') != connection_id]

        # Also disconnect if active
        if connection_id in active_connections:
            try:
                active_connections[connection_id].disconnect()
            except Exception as e:
                logger.warning("Error disconnecting %s: %s", connection_id, e)
            active_connections[connection_id].close_tunnel()
            del active_connections[connection_id]

        shutil.rmtree(CERTS_DIR / connection_id, ignore_errors=True)
        forget_relationship_decisions(connection_id)

        if save_connections(connections):
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': 'Failed to delete connection'}), 500


@app.route('/api/connect', methods=['POST'])
def connect():
    """Connect to a database."""
    data = (request.get_json(silent=True) or {})
    connection_id = data.get('id')

    if not connection_id:
        return jsonify({'success': False, 'error': 'Connection ID is required'}), 400

    # Check if already connected
    if connection_id in active_connections:
        connector = active_connections[connection_id]
        if connector.is_connected():
            return jsonify({'success': True, 'message': 'Already connected'})

    # Get connection parameters
    connections = load_connections()
    conn_params = next((c for c in connections if c.get('id') == connection_id), None)

    if not conn_params:
        # Try using provided data
        conn_params = data

    if not CONNECTOR_CLASSES.get(str(conn_params.get('type', '')).lower()):
        return jsonify({'success': False, 'error': f"Unsupported database type: {conn_params.get('type')}"}), 400

    tunnel = None
    if conn_params.get('ssh_enabled') and conn_params.get('type') != 'sqlite':
        try:
            tunnel = start_tunnel(conn_params, trust=data.get('ssh_trust_host_key'))
        except SSHError as e:
            return tunnel_error_response(e)
        conn_params = {**conn_params, 'host': '127.0.0.1', 'port': tunnel.local_port}  # the connector talks to the tunnel

    connector = create_connector(conn_params)
    if connector.connect():
        active_connections[connection_id] = SerializedConnector(connector, tunnel)
        return jsonify({'success': True, 'message': 'Connected successfully'})
    if tunnel:
        tunnel.stop()
    return jsonify({'success': False, 'error': 'Failed to connect' + (' (the SSH tunnel is up, but the database did not accept the connection)' if tunnel else '')}), 500


@app.route('/api/disconnect', methods=['POST'])
def disconnect():
    """Disconnect from a database."""
    data = (request.get_json(silent=True) or {})
    connection_id = data.get('id')

    if not connection_id:
        return jsonify({'success': False, 'error': 'Connection ID is required'}), 400

    connector = get_connector(connection_id)
    if not connector:
        return jsonify({'success': True, 'message': 'Not connected'})

    if connector.disconnect():
        connector.close_tunnel()
        del active_connections[connection_id]
        return jsonify({'success': True, 'message': 'Disconnected successfully'})
    else:
        return jsonify({'success': False, 'error': 'Failed to disconnect'}), 500


@app.route('/api/test-connection', methods=['POST'])
def test_connection():
    """Test a database connection."""
    data = (request.get_json(silent=True) or {})

    # An edited connection arrives without its secrets (the form never shows them); use the saved ones
    if data.get('id'):
        saved = next((c for c in load_connections() if c.get('id') == data['id']), {})
        for field in SECRET_FIELDS:
            if not data.get(field):
                data[field] = saved.get(field, '')

    store_certs(data, 'temp_test_connection')

    if not CONNECTOR_CLASSES.get(str(data.get('type', '')).lower()):
        return jsonify({'success': False, 'error': f"Unsupported database type: {data.get('type')}"}), 400

    tunnel = None
    try:
        params = data
        if data.get('ssh_enabled') and data.get('type') != 'sqlite':
            try:
                tunnel = start_tunnel(data, trust=data.get('ssh_trust_host_key'))
            except SSHError as e:
                return tunnel_error_response(e)
            params = {**data, 'host': '127.0.0.1', 'port': tunnel.local_port}
        success, message = create_connector(params).test_connection()
    finally:
        if tunnel:
            tunnel.stop()
        # Clean up temporary certificate files
        shutil.rmtree(CERTS_DIR / 'temp_test_connection', ignore_errors=True)

    return jsonify({'success': success, 'message': message})


@app.route('/api/databases', methods=['GET'])
def get_databases():
    """Get list of databases - returns only the connected database."""
    connection_id = request.args.get('connection_id')

    if not connection_id:
        return jsonify({'success': False, 'error': 'Connection ID is required'}), 400

    connector = get_connector(connection_id)
    if not connector:
        return jsonify({'success': False, 'error': 'Not connected'}), 400

    try:
        # Only return the database specified in the connection
        # This prevents showing all databases in a PostgreSQL/MySQL cluster
        connected_db = connector.connection_params.get('database')

        if connector.db_type == 'oracle':
            databases = [connector.current_schema()]   # the service name in the form owns no tables; the login's schema does
        elif connected_db:
            # Return only the connected database
            databases = [connected_db]
        else:
            # If no specific database was specified, show all (e.g., for SQLite)
            databases = connector.get_databases()

        return jsonify({'success': True, 'databases': databases})
    except Exception as e:
        return error_response(e)


@app.route('/api/tables', methods=['GET'])
def get_tables():
    """Get list of tables/collections."""
    connection_id = request.args.get('connection_id')
    database = request.args.get('database')

    if not connection_id:
        return jsonify({'success': False, 'error': 'Connection ID is required'}), 400

    connector = get_connector(connection_id)
    if not connector:
        return jsonify({'success': False, 'error': 'Not connected'}), 400

    try:
        tables = connector.get_tables(database)
        return jsonify({'success': True, 'tables': tables})
    except Exception as e:
        return error_response(e)


@app.route('/api/columns', methods=['GET'])
def get_columns():
    """Column names per table for autocomplete: one catalog query, optionally limited to ?tables=a&tables=b."""
    connection_id = request.args.get('connection_id')
    connector = get_connector(connection_id)
    if not connector:
        return jsonify({'success': False, 'error': 'Not connected'}), 400
    tables = request.args.getlist('tables')[:200] if 'tables' in request.args else None
    try:
        return jsonify({'success': True, 'columns': connector.get_columns(request.args.get('database'), tables)})
    except Exception as e:
        return error_response(e)


# ---- relationships the user has decided about: accepted ones count as foreign keys, ignored ones are not suggested again ----

RELATION_DECISIONS_FILE = CONFIG_DIR / 'relationship_decisions.json'
RELATION_DECISIONS_LOCK = threading.Lock()
RELATION_FIELDS = ('table', 'column', 'referenced_table', 'referenced_column')


def load_relationship_decisions() -> dict:
    try:
        data = json.loads(RELATION_DECISIONS_FILE.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        try:
            shutil.copy2(RELATION_DECISIONS_FILE, RELATION_DECISIONS_FILE.with_suffix('.corrupt.json'))
        except OSError:
            pass
        return {}


def write_relationship_decisions(data: dict):
    tmp = RELATION_DECISIONS_FILE.with_suffix('.tmp')
    with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, RELATION_DECISIONS_FILE)


def relationship_decisions(connection_id: str, database: Optional[str]) -> Dict[str, list]:
    """{'accepted': [...], 'ignored': [...]} for one connection and database, as stored."""
    with RELATION_DECISIONS_LOCK:
        mine = load_relationship_decisions().get(connection_id)
        mine = mine.get(database or '') if isinstance(mine, dict) else None
    mine = mine if isinstance(mine, dict) else {}       # a hand-edited or damaged file must not break the schema map
    clean = lambda items: [r for r in (items if isinstance(items, list) else [])
                           if isinstance(r, dict) and all(isinstance(r.get(f), str) for f in RELATION_FIELDS)]
    return {'accepted': clean(mine.get('accepted')), 'ignored': clean(mine.get('ignored'))}


def forget_relationship_decisions(connection_id: str):
    with RELATION_DECISIONS_LOCK:
        data = load_relationship_decisions()
        if data.pop(connection_id, None) is not None:
            write_relationship_decisions(data)


def clean_relation(raw) -> Optional[Dict[str, str]]:
    if not isinstance(raw, dict) or not all(isinstance(raw.get(f), str) and raw[f].strip() for f in RELATION_FIELDS):
        return None
    return {f: raw[f] for f in RELATION_FIELDS}


def same_relation(a: dict, b: dict) -> bool:
    return all(a.get(f) == b.get(f) for f in ('table', 'column'))


@app.route('/api/relations', methods=['GET'])
def get_relations():
    """Tables and the foreign keys between them, for the schema map and for following links in the grid.
    Relationships the user accepted are included, marked `virtual`, and behave like declared keys."""
    connection_id = request.args.get('connection_id')
    connector = get_connector(connection_id)
    if not connector:
        return jsonify({'success': False, 'error': 'Not connected'}), 400
    database = request.args.get('database')
    try:
        tables = connector.get_tables(database)
        relations = connector.get_relations(database)
        names = {t['name'] for t in tables}
        declared = {(r['table'], r['column']) for r in relations}
        for accepted in relationship_decisions(connection_id, database)['accepted']:
            if accepted['table'] in names and accepted['referenced_table'] in names and (accepted['table'], accepted['column']) not in declared:
                relations.append({**{f: accepted[f] for f in RELATION_FIELDS}, 'virtual': True})
        return jsonify({'success': True, 'tables': tables, 'relations': relations})
    except Exception as e:
        return error_response(e)


@app.route('/api/relations/inferred', methods=['GET'])
def inferred_relations():
    """Relationships the database has but never declared, found from column names and checked against the data."""
    connection_id = request.args.get('connection_id')
    connector = get_connector(connection_id)
    if not connector:
        return jsonify({'success': False, 'error': 'Not connected'}), 400
    if not connector.SUPPORTS_PROFILE:
        return jsonify({'success': False, 'error': 'Finding relationships works with SQL databases.'}), 400
    database = request.args.get('database')
    decided = relationship_decisions(connection_id, database)
    started = time.time()
    try:
        found = relationship_inference.infer(connector, database, connector.get_relations(database), decided['accepted'] + decided['ignored'])
    except Exception as e:
        return error_response(e)
    found['seconds'] = round(time.time() - started, 1)
    found['ignored'] = len(decided['ignored'])
    return jsonify({'success': True, **found})


ORPHAN_ROWS = 20


@app.route('/api/relations/orphans', methods=['GET'])
def relation_orphans():
    """The rows of a table whose value in one column has no match in the table it seems to point at."""
    connection_id = request.args.get('connection_id')
    connector = get_connector(connection_id)
    if not connector:
        return jsonify({'success': False, 'error': 'Not connected'}), 400
    if not connector.SUPPORTS_PROFILE:
        return jsonify({'success': False, 'error': 'Finding orphans works with SQL databases.'}), 400
    database = request.args.get('database')
    table, column, parent, parent_column = (request.args.get(k) for k in ('table', 'column', 'referenced_table', 'referenced_column'))
    try:
        for name, col in ((table, column), (parent, parent_column)):   # names go into SQL: only accept real ones
            if not name or not col or col not in {c['name'] for c in connector.get_schema(name, database)['columns']}:
                return jsonify({'success': False, 'error': 'Unknown table or column'}), 400
        return jsonify({'success': True, 'data': connector.orphan_rows(table, column, parent, parent_column, database, ORPHAN_ROWS)})
    except Exception as e:
        return error_response(e)


@app.route('/api/relations/decisions', methods=['GET'])
def list_relation_decisions():
    """What the user has accepted (with the evidence it was accepted on) and ignored, so either can be undone."""
    connection_id = request.args.get('connection_id')
    if not get_connector(connection_id):
        return jsonify({'success': False, 'error': 'Not connected'}), 400
    decided = relationship_decisions(connection_id, request.args.get('database') or None)
    return jsonify({'success': True, **decided})


@app.route('/api/relations/decision', methods=['POST'])
def decide_relation():
    """Accept a suggested relationship (it then works like a foreign key), ignore it (never suggest it again), or
    forget an earlier decision."""
    data = request.get_json(silent=True) or {}
    connection_id, action = data.get('connection_id'), data.get('action')
    relation = clean_relation(data.get('relation'))
    if action not in ('accept', 'ignore', 'forget') or not relation:
        return jsonify({'success': False, 'error': 'Say which relationship, and accept, ignore or forget.'}), 400
    connector = get_connector(connection_id)
    if not connector:
        return jsonify({'success': False, 'error': 'Not connected'}), 400
    database = data.get('database') or None
    try:
        columns = connector.get_columns(database)
    except Exception as e:
        return error_response(e)
    if action != 'forget' and (relation['column'] not in columns.get(relation['table'], [])
                               or relation['referenced_column'] not in columns.get(relation['referenced_table'], [])):
        return jsonify({'success': False, 'error': 'That table or column does not exist.'}), 400
    evidence = data.get('evidence') if isinstance(data.get('evidence'), dict) else {}
    with RELATION_DECISIONS_LOCK:
        everything = load_relationship_decisions()
        if not isinstance(everything.get(connection_id), dict):
            everything[connection_id] = {}
        if not isinstance(everything[connection_id].get(database or ''), dict):
            everything[connection_id][database or ''] = {}
        mine = everything[connection_id][database or '']
        for bucket in ('accepted', 'ignored'):
            current = mine.get(bucket) if isinstance(mine.get(bucket), list) else []
            mine[bucket] = [r for r in current if isinstance(r, dict) and not same_relation(r, relation)]
        if action == 'accept':
            mine['accepted'].append({**relation, 'evidence': {k: evidence[k] for k in ('distinct', 'matched', 'containment', 'confidence')
                                                              if k in evidence}, 'accepted_at': datetime.now().isoformat(timespec='seconds')})
        elif action == 'ignore':
            mine['ignored'].append(relation)
        write_relationship_decisions(everything)
    return jsonify({'success': True})


PROFILE_SAMPLE_THRESHOLD = 1_000_000   # above this many rows (by the catalog's estimate) insights read a sample instead
PROFILE_SAMPLE_ROWS = 100_000


@app.route('/api/profile', methods=['GET'])
def profile_column():
    """What is in one column: nulls, distinct values, range, most common values, histogram."""
    connection_id = request.args.get('connection_id')
    database, table, column = request.args.get('database'), request.args.get('table'), request.args.get('column')
    connector = get_connector(connection_id)
    if not connector:
        return jsonify({'success': False, 'error': 'Not connected'}), 400
    if not connector.SUPPORTS_PROFILE:
        return jsonify({'success': False, 'error': 'Column insights are not available for this kind of database.'}), 400
    if not table or not column:
        return jsonify({'success': False, 'error': 'Table and column are required'}), 400

    try:
        if column not in {c['name'] for c in connector.get_schema(table, database)['columns']}:
            return jsonify({'success': False, 'error': 'Unknown column'}), 400
        estimate = next((t.get('rows') for t in connector.get_tables(database) if t['name'] == table), None)
        sample = PROFILE_SAMPLE_ROWS if estimate and estimate > PROFILE_SAMPLE_THRESHOLD else None

        cancel_reasons.pop(connection_id, None)
        watchdog = None
        if QUERY_TIMEOUT:
            watchdog = threading.Timer(QUERY_TIMEOUT, stop_query, (connection_id, connector,
                                       f'Stopped: reading this column took longer than {QUERY_TIMEOUT} seconds.'))
            watchdog.daemon = True
            watchdog.start()
        try:
            profile = connector.profile_column(table, column, database, sample)
        except Exception as e:
            reason = cancel_reasons.pop(connection_id, None)
            if reason:
                return jsonify({'success': False, 'error': reason}), 504
            raise e
        finally:
            if watchdog:
                watchdog.cancel()
        return jsonify({'success': True, 'profile': profile})
    except NotImplementedError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        return error_response(e)


@app.route('/api/schema', methods=['GET'])
def get_schema():
    """Get table schema."""
    connection_id = request.args.get('connection_id')
    database = request.args.get('database')
    table = request.args.get('table')

    if not connection_id or not table:
        return jsonify({'success': False, 'error': 'Connection ID and table are required'}), 400

    connector = get_connector(connection_id)
    if not connector:
        return jsonify({'success': False, 'error': 'Not connected'}), 400

    try:
        schema = connector.get_schema(table, database)
        return jsonify({'success': True, 'schema': schema})
    except Exception as e:
        return error_response(e)


@app.route('/api/query', methods=['POST'])
def execute_query():
    """Execute a query."""
    data = (request.get_json(silent=True) or {})
    connection_id = data.get('connection_id')
    query = data.get('query')
    params = data.get('params')

    if not connection_id or not query:
        return jsonify({'success': False, 'error': 'Connection ID and query are required'}), 400

    connector = get_connector(connection_id)
    if not connector:
        return jsonify({'success': False, 'error': 'Not connected'}), 400

    verdict = safety.check(connector.connection_params.get('type', ''), query)
    if connector.connection_params.get('read_only') and not verdict.read_only:
        return jsonify({'success': False, 'read_only': True,
                        'error': f'This connection is read-only: {verdict.why_not}.'}), 403
    if verdict.destructive and not data.get('confirmed'):
        return jsonify({'success': False, 'needs_confirmation': True, 'reason': verdict.destructive}), 409

    try:
        cancel_reasons.pop(connection_id, None)
        watchdog = None
        if QUERY_TIMEOUT:
            watchdog = threading.Timer(QUERY_TIMEOUT, stop_query,
                                       (connection_id, connector, f'Query stopped: it ran longer than {QUERY_TIMEOUT} seconds.'))
            watchdog.daemon = True
            watchdog.start()
        try:
            result = connector.execute_query(query, params)
        finally:
            if watchdog:
                watchdog.cancel()

        reason = cancel_reasons.pop(connection_id, None)
        if reason and result.get('error'):
            result['error'] = reason

        limit = connector.MAX_ROWS
        if len(result.get('rows') or []) > limit:
            result['rows'] = result['rows'][:limit]
            result['row_count'] = limit
            result['truncated'] = True

        if result.get('error'):
            return jsonify({'success': False, 'error': result['error'], 'result': result})
        else:
            return jsonify({'success': True, 'result': result})
    except Exception as e:
        return error_response(e)


def stop_query(connection_id, connector, reason) -> bool:
    """Ask the driver to abort the running query. Returns False if this database cannot do that."""
    cancel_reasons[connection_id] = reason
    try:
        return bool(connector.cancel())
    except Exception:
        logger.exception('Could not cancel the query on %s', connection_id)
        return False


@app.route('/api/query/cancel', methods=['POST'])
def cancel_query():
    """Stop the query that is running on a connection."""
    connection_id = (request.get_json(silent=True) or {}).get('connection_id')
    connector = get_connector(connection_id)
    if not connector:
        return jsonify({'success': False, 'error': 'Not connected'}), 400
    ok = stop_query(connection_id, connector, 'Query cancelled.')
    return jsonify({'success': ok, 'error': None if ok else 'This database type cannot stop a running query.'})


@app.route('/api/data', methods=['GET'])
def get_data():
    """Get table data with pagination and search."""
    connection_id = request.args.get('connection_id')
    database = request.args.get('database')
    table = request.args.get('table')
    try:
        limit = min(max(int(request.args.get('limit', 1000)), 1), MAX_PAGE_SIZE)
        offset = max(int(request.args.get('offset', 0)), 0)
    except ValueError:
        return jsonify({'success': False, 'error': 'limit and offset must be integers'}), 400
    sort_by = request.args.get('sort_by')
    # sort_order is interpolated into SQL by every connector, so allow only the two keywords
    sort_order = 'DESC' if request.args.get('sort_order', '').upper() == 'DESC' else 'ASC'
    search_term = request.args.get('search')
    search_column = request.args.get('search_column')
    where_column = request.args.get('where_column')   # exact match, used when following a foreign key
    where_value = request.args.get('where_value')

    if not connection_id or not table:
        return jsonify({'success': False, 'error': 'Connection ID and table are required'}), 400

    connector = get_connector(connection_id)
    if not connector:
        return jsonify({'success': False, 'error': 'Not connected'}), 400

    try:
        # sort_by / search_column are interpolated into SQL; only accept real column names
        if connector.db_type in SQL_TYPES and (sort_by or search_column or where_column):
            known = {c['name'] for c in connector.get_schema(table, database)['columns']}
            if any(c and c not in known for c in (sort_by, search_column, where_column)):
                return jsonify({'success': False, 'error': 'Unknown column'}), 400

        # Build filters for search
        filters = {}
        if search_term:
            filters['search_term'] = search_term
            filters['search_column'] = search_column  # None means search all columns
        if where_column:
            filters[where_column] = where_value
        filters = filters or None

        result = connector.get_table_data(
            table=table,
            database=database,
            limit=limit,
            offset=offset,
            filters=filters,
            sort_by=sort_by,
            sort_order=sort_order
        )
        return jsonify({'success': True, 'data': result})
    except Exception as e:
        return error_response(e)


@app.route('/api/data', methods=['POST'])
def insert_data():
    """Insert a row."""
    data = (request.get_json(silent=True) or {})
    connection_id = data.get('connection_id')
    database = data.get('database')
    table = data.get('table')
    row_data = data.get('data')

    if not connection_id or not table or not row_data:
        return jsonify({'success': False, 'error': 'Connection ID, table, and data are required'}), 400

    connector = get_connector(connection_id)
    if not connector:
        return jsonify({'success': False, 'error': 'Not connected'}), 400

    blocked = read_only_error(connector)
    if blocked:
        return blocked

    try:
        success, message = connector.insert_row(table, row_data, database)
        if success:
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'success': False, 'error': message})
    except Exception as e:
        return error_response(e)


MAX_BATCH_OPERATIONS = 5000


def import_target():
    """(connector, table, database, error response) for the CSV import endpoints, which take a multipart form."""
    form = request.form
    table = (form.get('table') or '').strip()
    if not form.get('connection_id') or not table or 'file' not in request.files:
        return None, None, None, (jsonify({'success': False, 'error': 'Choose a file, a connection and a table.'}), 400)
    connector = get_connector(form['connection_id'])
    if not connector:
        return None, None, None, (jsonify({'success': False, 'error': 'Not connected'}), 400)
    blocked = read_only_error(connector)
    if blocked:
        return None, None, None, (blocked[0], blocked[1])
    if not connector.SUPPORTS_TRANSACTIONS:
        return None, None, None, (jsonify({'success': False, 'error':
                                  'CSV import needs a database that can roll back, so a bad row cannot leave half a file behind. '
                                  'It works with SQLite, PostgreSQL, MySQL, SQL Server and Oracle.'}), 400)
    return connector, table, (form.get('database') or None), None


def read_import_file():
    """Parse the uploaded file with the delimiter and header choices from the form."""
    name = (request.form.get('delimiter') or '').strip().lower()
    if name and name not in csv_import.DELIMITERS:
        raise csv_import.ImportProblem('Choose comma, semicolon, tab or pipe as the delimiter.')
    raw = request.files['file'].read(csv_import.MAX_IMPORT_BYTES + 1)
    return csv_import.analyze(raw, csv_import.DELIMITERS.get(name), request.form.get('has_header', 'true') != 'false')


@app.route('/api/import/preview', methods=['POST'])
def import_preview():
    """Read a CSV file and say how it lines up with a table: its columns, a few rows and a suggested mapping."""
    connector, table, database, error = import_target()
    if error:
        return error
    try:
        parsed = read_import_file()
        columns = connector.get_schema(table, database)['columns']
        if not columns:
            return jsonify({'success': False, 'error': f'The table "{table}" was not found.'}), 404
    except csv_import.ImportProblem as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        return error_response(e)
    names = [c['name'] for c in columns]
    delimiter_name = next(n for n, ch in csv_import.DELIMITERS.items() if ch == parsed['delimiter'])
    return jsonify({
        'success': True, 'headers': parsed['headers'], 'sample_rows': parsed['rows'][:5], 'total_rows': len(parsed['rows']),
        'delimiter': delimiter_name, 'encoding': parsed['encoding'], 'has_header': parsed['has_header'], 'problems': parsed['problems'],
        'table_columns': [{**c, 'required': not c.get('nullable', True) and c.get('default') is None and not c.get('primary_key')}
                          for c in columns],
        'suggested_mapping': csv_import.suggest_mapping(names, parsed['headers'])})


@app.route('/api/import', methods=['POST'])
def import_csv():
    """Insert every row of a CSV file into a table, all or nothing. `dry_run` checks it and then rolls it back."""
    connector, table, database, error = import_target()
    if error:
        return error
    try:
        parsed = read_import_file()
        if parsed['problems']:
            return jsonify({'success': False, 'error': parsed['problems'][0], 'problems': parsed['problems']}), 400
        schema = connector.get_schema(table, database)['columns']
        columns = [c['name'] for c in schema]
        if not columns:
            return jsonify({'success': False, 'error': f'The table "{table}" was not found.'}), 404
        try:
            mapping = json.loads(request.form.get('mapping') or 'null')
        except ValueError:
            mapping = None
        chosen = csv_import.check_mapping(mapping, columns, len(parsed['headers']))
    except csv_import.ImportProblem as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        return error_response(e)

    date_columns = {c['name'] for c in schema if c['name'] in chosen and csv_import.is_date_type(c.get('type'))}
    problems = csv_import.date_problems(parsed['rows'], chosen, date_columns)
    if problems:
        return jsonify({'success': False, 'error': problems[0], 'problems': problems}), 400
    operations = csv_import.build_operations(parsed['rows'], chosen, request.form.get('empty_as_null', 'true') != 'false', date_columns)
    dry_run = request.form.get('dry_run') == 'true'
    try:
        # hold the connection for the whole import so nothing else runs inside Oracle's temporary date formats
        with getattr(connector, '_lock', contextlib.nullcontext()), connector.import_session():
            result = connector.apply_batch(table, operations, database, dry_run=dry_run)
    except Exception as e:
        return error_response(e)
    if result['success']:
        return jsonify({'success': True, 'imported': result['applied'], 'dry_run': dry_run})
    row = result.get('failed_at')
    message = result['error'] if row is None else f'Row {row + 1}: {result["error"]}'
    return jsonify({'success': False, 'error': message, 'row': None if row is None else row + 1,
                    'rolled_back': result.get('rolled_back', True)}), 422


EXPORT_ROW_LIMIT = 100_000   # shortcut: built in memory, so a whole table is capped; stream to disk if bigger tables matter


BINARY_LITERAL = {'mysql': "0x{}", 'sqlserver': "0x{}", 'sqlite': "X'{}'", 'postgresql': "'\\x{}'::bytea", 'oracle': "HEXTORAW('{}')"}


def _sql_literal(value, kind=None) -> str:
    if value is None:
        return 'NULL'
    if isinstance(value, (bytes, bytearray, memoryview)):
        return BINARY_LITERAL.get(kind, "X'{}'").format(bytes(value).hex())
    if isinstance(value, bool):
        return '1' if value else '0'
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (dict, list)):
        value = json.dumps(value, default=plain_value)
    return "'" + str(value).replace("'", "''") + "'"


SEARCH_TABLES = 200      # shortcut: a plain scan table by table; very large databases get a partial answer, told to the user
SEARCH_SECONDS = 20
SEARCH_SAMPLE = 3


@app.route('/api/search', methods=['GET'])
def search_database():
    """Which tables hold a value, in any column: the connector's own table search, run over every table."""
    connection_id, database = request.args.get('connection_id'), request.args.get('database')
    term = (request.args.get('term') or '').strip()
    connector = get_connector(connection_id)
    if not connector:
        return jsonify({'success': False, 'error': 'Not connected'}), 400
    if connector.db_type not in SQL_TYPES:
        return jsonify({'success': False, 'error': 'Searching every table works with SQL databases.'}), 400
    if len(term) < 2:
        return jsonify({'success': False, 'error': 'Type at least two characters to search for.'}), 400
    started, results, failed = time.time(), [], 0
    try:
        names = [t['name'] for t in connector.get_tables(database)]
    except Exception as e:
        return error_response(e)
    scanned = 0
    for name in names[:SEARCH_TABLES]:
        if time.time() - started > SEARCH_SECONDS:
            break
        scanned += 1
        try:
            page = connector.get_table_data(table=name, database=database, limit=SEARCH_SAMPLE, offset=0,
                                            filters={'search_term': term, 'search_column': None})
        except Exception:
            failed += 1
            continue
        if page.get('total_count'):
            results.append({'table': name, 'total': page['total_count'], 'columns': page['columns'], 'rows': page['rows']})
    return jsonify({'success': True, 'results': results, 'tables': len(names), 'scanned': scanned, 'failed': failed,
                    'seconds': round(time.time() - started, 1)})


@app.route('/api/export', methods=['GET'])
def export_table():
    """The whole table (not just the page on screen) as a csv, json or SQL INSERT file."""
    connection_id, table, database = request.args.get('connection_id'), request.args.get('table'), request.args.get('database')
    fmt = request.args.get('format', 'csv')
    if not connection_id or not table or fmt not in ('csv', 'json', 'sql'):
        return jsonify({'success': False, 'error': 'Connection, table and a format of csv, json or sql are required'}), 400
    connector = get_connector(connection_id)
    if not connector:
        return jsonify({'success': False, 'error': 'Not connected'}), 400
    if fmt == 'sql' and connector.db_type not in SQL_TYPES:
        return jsonify({'success': False, 'error': 'SQL export is only available for SQL databases'}), 400
    try:
        columns, rows = [], []
        while len(rows) < EXPORT_ROW_LIMIT:
            page = connector.get_table_data(table=table, database=database, limit=MAX_PAGE_SIZE, offset=len(rows))
            columns = page['columns']
            rows += page['rows']
            if len(page['rows']) < MAX_PAGE_SIZE:
                break
    except Exception as e:
        return error_response(e)
    truncated = len(rows) >= EXPORT_ROW_LIMIT
    rows = rows[:EXPORT_ROW_LIMIT]

    def cell(row, i, col):
        return row.get(col) if isinstance(row, dict) else row[i]

    if fmt == 'json':
        body = json.dumps([{c: cell(r, i, c) for i, c in enumerate(columns)} for r in rows], indent=2, default=plain_value)
        mime = 'application/json'
    elif fmt == 'sql':
        target = connector.table_ref(table, database)
        names = ', '.join(connector.q(c) for c in columns)
        body = ''.join(f"INSERT INTO {target} ({names}) VALUES ({', '.join(_sql_literal(cell(r, i, c), connector.db_type) for i, c in enumerate(columns))});\n"
                       for r in rows)
        mime = 'application/sql'
    else:
        import csv, io
        out = io.StringIO()
        writer = csv.writer(out, lineterminator='\n')
        writer.writerow(columns)
        for r in rows:
            writer.writerow(['' if v is None else json.dumps(v, default=plain_value) if isinstance(v, (dict, list)) else plain_value(v) if isinstance(v, (bytes, bytearray, memoryview, set, frozenset)) else v
                             for v in (cell(r, i, c) for i, c in enumerate(columns))])
        body, mime = out.getvalue(), 'text/csv'
    response = Response(body, mimetype=mime)
    safe_name = ''.join(ch if ch.isalnum() or ch in '_-' else '_' for ch in table)
    response.headers['Content-Disposition'] = f'attachment; filename="{safe_name}.{fmt}"'
    response.headers['X-Export-Rows'] = str(len(rows))
    response.headers['X-Export-Truncated'] = 'true' if truncated else 'false'
    return response


@app.route('/api/data/batch', methods=['POST'])
def batch_data():
    """Save several inserts, updates and deletes as one unit (all or nothing where the database allows it)."""
    data = (request.get_json(silent=True) or {})
    table, operations = data.get('table'), data.get('operations')
    if not data.get('connection_id') or not table or not isinstance(operations, list) or not operations:
        return jsonify({'success': False, 'error': 'Connection ID, table and a list of operations are required'}), 400
    if len(operations) > MAX_BATCH_OPERATIONS:
        return jsonify({'success': False, 'error': f'At most {MAX_BATCH_OPERATIONS} changes can be saved at once'}), 400
    if not all(isinstance(op, dict) and op.get('op') in ('insert', 'update', 'delete') for op in operations):
        return jsonify({'success': False, 'error': 'Each change must be an insert, update or delete'}), 400

    connector = get_connector(data['connection_id'])
    if not connector:
        return jsonify({'success': False, 'error': 'Not connected'}), 400
    blocked = read_only_error(connector)
    if blocked:
        return blocked

    try:
        result = connector.apply_batch(table, operations, data.get('database'), bool(data.get('force')))
    except Exception as e:
        return error_response(e)
    status = 200 if result['success'] else 409 if result.get('conflicts') else 422
    return jsonify(result), status


@app.route('/api/data', methods=['PUT'])
def update_data():
    """Update rows."""
    data = (request.get_json(silent=True) or {})
    connection_id = data.get('connection_id')
    database = data.get('database')
    table = data.get('table')
    conditions = data.get('conditions')
    row_data = data.get('data')

    if not connection_id or not table or not conditions or not row_data:
        return jsonify({'success': False, 'error': 'Connection ID, table, conditions, and data are required'}), 400

    connector = get_connector(connection_id)
    if not connector:
        return jsonify({'success': False, 'error': 'Not connected'}), 400

    blocked = read_only_error(connector)
    if blocked:
        return blocked

    try:
        success, message = connector.update_row(table, conditions, row_data, database)
        if success:
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'success': False, 'error': message})
    except Exception as e:
        return error_response(e)


@app.route('/api/data', methods=['DELETE'])
def delete_data():
    """Delete rows."""
    data = (request.get_json(silent=True) or {})
    connection_id = data.get('connection_id')
    database = data.get('database')
    table = data.get('table')
    conditions = data.get('conditions')

    if not connection_id or not table or not conditions:
        return jsonify({'success': False, 'error': 'Connection ID, table, and conditions are required'}), 400

    connector = get_connector(connection_id)
    if not connector:
        return jsonify({'success': False, 'error': 'Not connected'}), 400

    blocked = read_only_error(connector)
    if blocked:
        return blocked

    try:
        success, message = connector.delete_row(table, conditions, database)
        if success:
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'success': False, 'error': message})
    except Exception as e:
        return error_response(e)


@app.route('/api/connection-status', methods=['GET'])
def connection_status():
    """Get status of all active connections."""
    status = {}
    for conn_id, connector in active_connections.items():
        status[conn_id] = {
            'connected': connector.is_connected(),
            'info': connector.get_connection_info()
        }

    return jsonify({'success': True, 'connections': status})


def shutdown():
    for connector in list(active_connections.values()):
        try:
            connector.disconnect()
        except Exception:
            pass
        connector.close_tunnel()


if __name__ == '__main__':
    import webview

    atexit.register(shutdown)
    # pywebview ignores file downloads unless told otherwise, which silently broke every Export button in the desktop app
    webview.settings['ALLOW_DOWNLOADS'] = True
    webview.create_window(
        APP_NAME,
        app,
        width=1400,
        height=900,
        resizable=True,
        fullscreen=False,
        min_size=(1000, 600)
    )
    webview.start(debug=bool(os.environ.get('DBV_DEBUG')))
