# Database Visualizer

A powerful database management and visualization tool supporting both SQL and NoSQL databases.

## Supported Databases

- **SQL**: SQLite, PostgreSQL, MySQL, SQL Server, Oracle
- **NoSQL**: MongoDB, Redis

## Features

- **Follow the data:** a value that points at another table (a foreign key) has a **↗** arrow: click it to open
  exactly that row. A value that other tables point at has a **↘**: click it to see the rows referring to it. The
  filter shows as a chip you can clear. Hold ⌘/Ctrl and click a value to follow it from anywhere in the cell.
- **Schema map:** the **Map** button draws every table that takes part in a relationship, parents on the left and
  children on the right. Hover a table to light up what it touches, drag to pan, scroll to zoom, click a table to open it.
- **Jump to anything (⌘K / Ctrl K):** type part of a table, connection, open tab or action name.
- **Environments:** mark a connection Local, Development, Staging or Production. The window takes on that colour,
  and Production connections start read-only and ask before saving changes or running destructive statements.
- **Column insights:** the ▾ on a column header shows what is in it: empty and distinct counts, range, average, a
  histogram for numbers and the most common values. Click a common value to filter the table to it. Big tables are
  sampled, and the 60-second limit and Cancel apply.
- **SQL assistant (optional, off by default):** describe a query in plain English and Claude writes it into the
  editor. See *SQL assistant* below for exactly what is sent.
- **Sample database:** no database handy? **Try a sample database** on the first screen opens a small online shop.
- Multi-database connection management (SQLite, PostgreSQL, MySQL, SQL Server, Oracle, MongoDB, Redis, Cassandra),
  SSH tunnels, read-only connections, a query editor with autocomplete, an editable data grid with search, sorting
  and paging, schema viewer, CSV/JSON export, query history.

## Installation

### Option 1: Using the startup script (Recommended)

```bash
./run.sh
```

### Option 2: Manual installation

```bash
# Use a venv; the system pip on macOS can't build pyobjc (needed by pywebview)
python3 -m venv .venv
.venv/bin/python -m pip install -U pip -r requirements.txt

# Run the application
.venv/bin/python db.py
```

## Quick Start

1. **Launch the application**
   - Run `./run.sh` or `python3 db.py`

2. **Create a connection**
   - Click the "+" button in the sidebar
   - Select your database type
   - Enter connection details (host, port, username, password)
   - Click "Test Connection" to verify
   - Save the connection

3. **Connect to database**
   - Click the connection button (○) next to your saved connection
   - The database tree will load automatically

4. **Browse and query**
   - Expand databases and tables in the sidebar
   - Double-click a table to view data
   - Write queries in the editor
   - Press Ctrl+Enter (Cmd+Enter on Mac) to execute

## Tips

- **JSON Fields**: JSON/object fields are displayed in monospace font and are read-only in the data grid
- **Editing Data**: Double-click cells in the data grid to edit, changes are highlighted
- **Row counts**: the number beside each table is a catalog estimate (shown with `~`) so connecting never scans your tables. SQLite shows exact counts for files under 50 MB.
- **SQLite**: Only requires a file path, no host/port/credentials needed
- **Export**: Query results can be exported as CSV or JSON
- **Query History**: Access recent queries via the "History" button

## Troubleshooting

### Command not found: pip

Use `pip3` instead of `pip` on macOS:
```bash
pip3 install -r requirements.txt
```

### Module not found errors

Install all dependencies:
```bash
pip3 install --upgrade -r requirements.txt
```

### Database-specific issues

- **Oracle**: connects with python-oracledb in thin mode, so no Oracle Instant Client is needed
- **SQL Server**: the pymssql wheels bundle FreeTDS; install it separately only if pip has to build pymssql from source
- **PostgreSQL/MySQL**: Ensure the database server is running and accessible

## Keyboard Shortcuts

- `Ctrl/Cmd + Enter` - Execute query
- `Escape` - Close modal dialogs
- `Tab` - Navigate between fields

## Safety rails

- **Read-only connections:** tick *Read-only* on a connection and the server rejects inserts, updates, deletes and
  schema changes (query editor and row editing alike). PostgreSQL, MySQL and SQLite also refuse writes in the
  driver itself. It cannot see side effects hidden inside functions, so for production data also use a database
  user that only has `SELECT`.
- **Confirmation:** `UPDATE`/`DELETE` without a real `WHERE`, `DROP`, `TRUNCATE`, `ALTER` and Redis `FLUSH*` ask
  first; nothing runs until you agree.
- **Limits:** results are capped at 10,000 rows and queries stop after 60 seconds (`DBV_QUERY_TIMEOUT`, `0` turns
  it off). **Run** becomes **Cancel** while a query runs. Cancel works on PostgreSQL, MySQL, SQLite and Oracle;
  SQL Server, MongoDB, Redis and Cassandra cannot stop a running query (the timeout does not apply there either).
- **Reconnect:** a connection that sat idle or was dropped by the server is re-opened automatically.

## SQL assistant

Off until you turn it on (**Ask** in a query tab, or ⌘K → *SQL assistant settings*) with your own Anthropic API key,
which is stored encrypted on this computer and billed to your Anthropic account.

- **Sent to the Anthropic API:** the database type, the *names* of tables and columns, the foreign keys between them,
  and the text you type. For a large schema only the tables your request seems to be about are described in full.
- **Never sent:** row data, query results, passwords, hosts, file paths. **Show what's sent** prints the exact text
  without sending it.
- It only **writes** SQL into the editor; it never runs it. The statement is labelled *Reads data only*, *Changes data*
  or a warning for `UPDATE`/`DELETE` without a `WHERE`, and running it goes through the usual confirmations and the
  read-only and production protections.
- Model: `claude-opus-5-5` by default (`DBV_AI_MODEL` to change). `DBV_AI_BASE_URL` points it at another endpoint.
- It needs an internet connection. If the key is rejected, rate limited or the API is unreachable, the panel says so.

## SSH tunnels

Tick **Connect through an SSH tunnel** on a connection to reach a database that is only visible from an SSH server
(a bastion or jump host). Enter the SSH server, your user, and either a password or a private key file (with its
passphrase if it has one). The database **host and port are as seen from the SSH server**, e.g. `localhost` or a
private address.

- **First connection to a server:** the app shows the server's fingerprint and asks whether to trust it. Nothing
  (no password, no key) is sent to the server before you agree. The key is then remembered in `known_hosts.json`.
- **If a remembered server's key changes,** the app refuses to connect and says why; there is no "connect anyway".
  A changed key is what an interception looks like. If you know the server was reinstalled, remove its entry from
  `known_hosts.json` in the data folder.
- The tunnel only listens on `127.0.0.1`, closes when you disconnect or delete the connection, and re-opens on the
  same port if the SSH connection drops.
- SSH passwords and passphrases are encrypted like database passwords. The key file stays where it is; only its path
  is saved.
- Not supported: SSH agent / hardware keys, jump chains (ProxyJump), and MongoDB or Redis connections that use a
  connection URL (use host and port instead). The SSH server must allow TCP forwarding (`AllowTcpForwarding yes`).

## Security

- Saved passwords are encrypted with Fernet. The encryption key lives in the **system keychain** (macOS Keychain,
  Windows Credential Manager, Secret Service), not in a file. An existing `secret.key` is moved there on first run
  (checked by reading it back) and then deleted. If there is no usable keychain, the key stays in `secret.key`
  (`0600`) as before. With an explicit `DBV_DATA_DIR` (portable or test setups) the key stays in that folder and the
  keychain is not touched; `DBV_KEY_STORE=keychain|file` overrides this.
- The key is never replaced once it exists: a locked or unreadable keychain stops the app with a clear message
  rather than inventing a new key that would orphan every saved password. A password that cannot be decrypted is
  kept as it is and survives later saves.
- **Back up carefully.** `connections.json` is useless without the key. If you lose the keychain item, your saved
  passwords are gone (the connections themselves remain; re-enter the passwords).
- The data folder is `0700`; `connections.json` is `0600`.
- The UI talks to a local server on `127.0.0.1` only. Every `/api` call needs a per-launch token and a
  loopback `Host` header, and CORS is off, so other local processes and web pages cannot reach your databases.
- Table and column names are quoted for each database, never pasted into SQL, and values are always parameters.
- Logs go to `app.log` in the data folder (rotated) and contain no row data. Set `DBV_DEBUG=1` for the web inspector.
- Anyone who can run code as your user can still ask the keychain for the key; this protects the file at rest, not
  a compromised account.

## Development & release

```bash
.venv/bin/python -m pytest tests --ignore=tests/e2e   # API + security tests (SQLite-backed, no servers needed)
.venv/bin/python -m pytest tests/e2e                  # 33 browser tests that drive the real UI in Chrome (needs Playwright + Chrome)
python tests/ssh_fixture/make_keys.py                  # once: throwaway SSH keys for the tunnel tests (never committed)
docker compose -f docker-compose.test.yml up -d --wait   # MySQL, PostgreSQL, MongoDB, Redis, Cassandra and an SSH server, on offset ports
.venv/bin/python -m pytest tests/integration          # the same behavioural contract run against each real database
./build.sh                        # runs the tests, then builds dist/DB Visualizer.app
```

The build is unsigned. To distribute outside your own machine, sign and notarize it with an Apple Developer ID.
Test coverage by database: SQLite, MySQL, PostgreSQL, SQL Server, Oracle, MongoDB, Redis and Cassandra all run against
real servers in `tests/integration` (SQL Server through Azure SQL Edge, which runs natively on Apple Silicon; the
regular SQL Server image is amd64-only). Cassandra has no `LIKE` or arbitrary sort, so search and sort are skipped
there by design (see the `unsupported` sets in the test file). Not covered: Windows and Linux desktop builds, and
SQL Server/Oracle through an SSH tunnel.

## Screenshots

The application features a modern dark theme with:
- Sidebar for connection and database browsing
- Query editor with SQL syntax highlighting
- Results grid with sorting and filtering
- Inline data editing with change tracking
- Schema visualization

## License

This is a custom database visualization tool built for comprehensive database management.
