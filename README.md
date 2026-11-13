<div align="center">

# 🗄️ DB Visualizer

**Look at your data, follow its relationships, and change it without being afraid of it.**

A desktop app for browsing and editing SQL and NoSQL databases, with guard rails that stop the expensive mistakes.

![Python](https://img.shields.io/badge/python-3.9%2B-3776AB?logo=python&logoColor=white)
![SQL](https://img.shields.io/badge/SQL-SQLite%20·%20MySQL%20·%20PostgreSQL%20·%20SQL%20Server%20·%20Oracle-336791)
![NoSQL](https://img.shields.io/badge/NoSQL-MongoDB%20·%20Redis%20·%20Cassandra-47A248)
[![CI](../../actions/workflows/ci.yml/badge.svg)](../../actions/workflows/ci.yml)

[Quick start](#-quick-start) ·
[What it does](#-what-it-does) ·
[How it works](#-how-it-works) ·
[Safety](#-safety-rails) ·
[Databases](#-databases) ·
[Security](#-security) ·
[Develop](#-develop)

</div>

---

## ⚡ Quick start

```bash
./run.sh
```

No database handy? Click **Try a sample database** on the first screen. It opens a small online shop you can't hurt. It includes four add-on tables whose links to the rest of the shop are *not* declared, so you can try **Find missing relationships** on the Schema map and see what it finds, and what it refuses.

<details>
<summary><b>Install by hand</b> (if you don't want the script)</summary>

```bash
# Use a venv; the system pip on macOS can't build pyobjc (needed by pywebview)
python3 -m venv .venv
.venv/bin/python -m pip install -U pip -r requirements.txt
.venv/bin/python db.py
```
</details>

**Your first five minutes**

| Step | Do this |
|:--:|---|
| 1 | Click **+** in the sidebar, pick the database type, fill in the details, **Test Connection**, **Save** |
| 2 | Click the ○ next to the connection. The database tree loads |
| 3 | Double-click a table to see its data, or write SQL in the editor |
| 4 | **⌘/Ctrl + Enter** runs the query |
| 5 | Press **⌘K / Ctrl K** any time to jump to a table, tab, connection or action |

---

## ✨ What it does

<table>
<tr>
<td width="50%" valign="top">

### 🔗 Follow the data
A value that points at another table (a foreign key) shows **↗**: click it to open exactly that row. A value that other tables point at shows **↘**: click it to see who refers to it. Hold ⌘/Ctrl and click anywhere in a cell to follow it.

To see everything about one row, right-click it and choose **Explore this record**: the rows it points at and the rows that point at it, a few of each. Click one to step into it, or **Back** to return. It uses every link the app knows, including accepted ones.

</td>
<td width="50%" valign="top">

### 🗺️ Schema map
Every table that takes part in a relationship, parents on the left and children on the right. Hover to light up what a table touches, drag to pan, scroll to zoom, click a table to open it.

</td>
</tr>
<tr>
<td valign="top">

### 📊 Column insights
The **▾** on a column header shows empty and distinct counts, range, average, a histogram and the most common values. Click a common value to filter the table to it. Big tables are sampled.

</td>
<td valign="top">

### 🎨 Environments
Mark a connection Local, Development, Staging or Production. The window takes on that colour, and Production starts read-only and asks before saving or running anything destructive.

</td>
</tr>
<tr>
<td valign="top">

### 🔖 Saved queries
Press **Save** in a query tab to keep the SQL under a name (just the selection, if you've selected something). **Saved** lists them with a filter; open one in the editor or a new tab, rename it, delete it. They also show up in ⌘K. They're kept on disk, not in the browser, so they survive restarts.

</td>
<td valign="top">

### ✏️ Safe editing
Edit cells in the grid, add rows, delete rows, then save. It all happens together or not at all, and it refuses to overwrite a row someone else changed. [See how](#-saving-edits-safely).

</td>
</tr>
<tr>
<td valign="top">

### 📥 CSV import
**Import CSV** on a table opens a dialog: pick the separator, say which file column goes into which table column, **Check without importing** to try every row and undo it again, then import. All or nothing: one bad row and nothing is added. See [what it accepts](#-what-csv-import-accepts).

</td>
<td valign="top">

### 🤖 SQL assistant <sub>optional, off by default</sub>
Describe a query in plain English and Claude writes it into the editor. It only ever sees names, never data. [See exactly what is sent](#-sql-assistant).

</td>
</tr>

<tr>
<td colspan="2" valign="top">

### 🧩 Missing relationships
Many databases have no foreign keys at all, so most tools can't draw or follow anything. **Find missing relationships** on the Schema map reads column names (`orders.customer_id` looks like it points at `customers`) and **checks them against the data**: how many of its values really exist in the other table. Accept a suggestion and it works like a foreign key here: the ↗ and ↘ links in the grid, and a dashed edge on the map. Where some values point at nothing, **Show the rows** lists the rows that do, and clicking one explores it. Your database is never changed. [How it decides](#-how-missing-relationships-are-found).

</td>
</tr>
</table>

Also in the box: SSH tunnels, read-only connections, a query editor with autocomplete, a data grid with search, sorting and paging, a schema viewer, CSV/JSON/SQL export of a whole table, a review of every change before it is saved, query history, and **light and dark themes**: the button in the top bar cycles *System* (follows your computer), *Light* and *Dark*, and your choice is remembered.

---

## 🧭 How it works

Everything runs on your machine. The window talks to a small local server that only answers to itself.

```mermaid
flowchart LR
    subgraph pc["Your computer"]
        UI["Desktop window<br/>pywebview + JS UI"]
        API["Local API<br/>Flask on 127.0.0.1"]
        G["Safety guard<br/>read-only, confirm, limits"]
        C["Connectors<br/>one per database"]
        K[("System keychain<br/>holds the encryption key")]
        UI -->|"per-launch token"| API
        API --> G --> C
        API -.-> K
    end
    SQL[("SQLite · MySQL · PostgreSQL<br/>SQL Server · Oracle")]
    NOSQL[("MongoDB · Redis · Cassandra")]
    T["SSH tunnel<br/>bastion host"]
    AI["Anthropic API<br/>opt-in, names only"]
    C --> SQL
    C --> NOSQL
    C -.->|"optional"| T -.-> SQL
    API -.->|"only if you turn it on"| AI
```

<details>
<summary><b>Where things live</b></summary>

| What | Where |
|---|---|
| Server, routes, safety wiring | `db.py` |
| One connector per database | `db_connectors/` (`base`, `safety`, `tunnel`, `sqlite`, `mysql`, `postgres`, `sqlserver`, `oracle`, `mongodb`, `redis`, `cassandra`) |
| UI | `static/js/` (`app`, `connection`, `query`, `tabs`, `ui`, `palette`, `relations`, `insights`, `assistant`) |
| SQL assistant | `ai_assistant.py` |
| Sample shop database | `sample_data.py` |
| Your data | `~/Library/Application Support/DB Visualizer` (saved connections, saved queries, accepted relationships, `app.log`, known SSH hosts) |

</details>

---

## 🛡️ Safety rails

Every query passes through the same gate before it reaches your database.

```mermaid
flowchart TD
    Q["You run a query"] --> RO{"Connection<br/>read-only?"}
    RO -->|"yes, and the query writes"| NO["Refused"]
    RO -->|"no, or it only reads"| D{"Destructive?<br/>DROP · TRUNCATE · ALTER<br/>UPDATE or DELETE with no WHERE"}
    D -->|"yes"| ASK["You confirm first"] --> RUN
    D -->|"no"| RUN["Runs with a 60 s timeout<br/>and a 10,000 row cap"]
    RUN --> CANCEL["Run becomes Cancel while it works"]
```

| Rail | What it does |
|---|---|
| **Read-only connections** | The server rejects inserts, updates, deletes and schema changes, in the editor and the grid alike. PostgreSQL, MySQL and SQLite also refuse writes in the driver. It can't see side effects hidden inside functions, so for production data also use a database user that only has `SELECT`. |
| **Confirmation** | `UPDATE`/`DELETE` without a real `WHERE`, `DROP`, `TRUNCATE`, `ALTER` and Redis `FLUSH*` ask first. Nothing runs until you agree. |
| **Limits** | Results are capped at 10,000 rows and queries stop after 60 seconds (`DBV_QUERY_TIMEOUT`, `0` turns it off). |
| **Cancel** | Works on PostgreSQL, MySQL, SQLite and Oracle. SQL Server, MongoDB, Redis and Cassandra can't stop a running query, and the timeout doesn't apply there either. |
| **Reconnect** | A connection that sat idle or was dropped by the server is re-opened automatically. |

### 💾 Saving edits safely

Saving a grid is one request, checked against what you saw when you loaded it.

```mermaid
sequenceDiagram
    actor You
    participant Grid as Data grid
    participant API as Local API
    participant DB as Database
    You->>Grid: edit cells, add rows, delete rows
    You->>Grid: Save
    Grid->>API: every change, plus what each edited cell held when loaded
    API->>DB: begin a transaction, lock the edited rows
    alt someone else changed a row
        API->>DB: roll back
        API-->>Grid: row, column, was X, now Y
        Grid-->>You: Keep editing, or Save anyway
    else rows are as you left them
        API->>DB: apply inserts, updates and deletes
        alt any statement fails
            API->>DB: roll back, nothing is saved
            API-->>Grid: which change failed and why
        else all succeed
            API->>DB: commit
            API-->>Grid: saved
        end
    end
```

- **All or nothing** on SQLite, MySQL, PostgreSQL, SQL Server and Oracle.
- **MongoDB, Redis and Cassandra can't roll back.** They stop at the first failure and tell you how many changes were applied.
- A row that was already deleted doesn't block a delete. An edit to a row that no longer exists is reported.
- Updates and deletes that match no row are failures, never silent successes.

### 📥 What CSV import accepts

**Import CSV** on a table tab adds the rows of a file to that table. Nothing is guessed: you choose the column for each value, and **Check without importing** runs every row and then undoes it, so you find problems before they cost you anything.

- **All or nothing.** One bad row (a duplicate key, text in a number column, a missing required value) and nothing is imported. The message names the row, counting data rows without the header.
- **Works with** SQLite, PostgreSQL, MySQL, SQL Server and Oracle: databases that can roll back. Not MongoDB, Redis or Cassandra. It also refuses read-only connections, and asks first on Production.
- **Reads** comma, semicolon, tab or pipe separated files, with or without a header row; UTF-8 (with or without a BOM) or the Windows Excel encoding; quotes, doubled quotes and line breaks inside quotes. At most **10,000 rows** and **20 MB** per import: split bigger files.
- **Dates must be written year first**: `2026-03-04` or `2026-03-04 10:20:30` (a `T` between them is fine). `04/03/2026` is refused by name, because PostgreSQL and SQL Server quietly read it as 3 April, so a file that mixes layouts would import half wrong with no error.
- **Everything else is text the database converts** (`12.50` into a decimal column, `abc` into an integer column is refused). Empty values become NULL (untick to keep them as empty text). MySQL wants `1`/`0` for a yes/no column; PostgreSQL and SQL Server also take `true`/`false`.
- Column names in the file are never put into SQL: only columns that really exist in the table can be filled.
- Speed: roughly 2,000 rows in 1 to 4 seconds on a local database, so a full 10,000-row file takes up to about 20 seconds. Over a slow network it takes longer.
- A check on a table with an auto-numbered key can use up some of the numbers, because databases don't give those back after a rollback.

### 🧩 How missing relationships are found

For every column whose name looks like a reference to another table, three things have to agree before anything is suggested:

1. **The name.** `customer_id`, `CustomerID`, `customerKey` and `customer_uuid` hint at a table called `customers` (or `customer`). A bare `id`, or a name that matches no table, is never guessed at. Views are skipped, since they take their relationships from their tables.
2. **The type.** Numbers are compared with numbers and text with text.
3. **The data.** The first 2,000 non-empty rows of the column are checked against the other table's key, which must be a single-column primary key or unique index. At least 70% of the distinct values must exist there. A column where every value exists is **high** confidence if there are 20 or more different values; with fewer values, or with some that point at nothing ("orphans"), it is marked lower and says why.

You see the evidence for each one ("All 60 distinct values exist in customers.id", or "48 of 68 values exist, 20 point at nothing") and choose **Accept** or **Ignore**. Ignored suggestions stay ignored; both decisions can be undone from the panel. They are stored in the app's data folder, per connection, and are removed when you delete the connection.

- It samples rather than scans, stops after 25 seconds, and says so if it was cut short.
- It works with SQLite, PostgreSQL, MySQL, SQL Server and Oracle. It only finds relationships between a column and a table's *single-column* key, not composite keys.
- Only names that follow the `table_id` style are found: a column like `referred_by` or `owner` points at something, but nothing in its name says what.
- It samples the *first* rows, so a table whose early rows are unrepresentative can mislead it: that is why you decide.

---

## 🗃️ Databases

| | SQLite | MySQL | PostgreSQL | SQL Server | Oracle | MongoDB | Redis | Cassandra |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| Browse, edit, query | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Atomic saves + stale-edit check | ✅ | ✅ | ✅ | ✅ | ✅ | – | – | – |
| Cancel a running query | ✅ | ✅ | ✅ | – | ✅ | – | – | – |
| Driver refuses writes when read-only | ✅ | ✅ | ✅ | – | – | – | – | – |
| Tested against a real server | ✅ | ✅ | ✅ | ✅ <sup>1</sup> | ✅ <sup>2</sup> | ✅ | ✅ | ✅ |
| Tested through an SSH tunnel | n/a | ✅ | ✅ | – | – | ✅ | ✅ | ✅ |

<sup>1</sup> Azure SQL Edge, which runs natively on Apple Silicon. The regular SQL Server image is amd64-only. &nbsp; <sup>2</sup> Oracle 23ai Free only.

Cassandra has no `LIKE` or arbitrary sort, so search and sort are skipped there by design.

<details>
<summary><b>Database-specific notes</b></summary>

- **SQLite** only needs a file path. Row counts are exact for files under 50 MB.
- **Row counts elsewhere** are catalog estimates, shown with `~`, so connecting never scans your tables.
- **Oracle** uses python-oracledb in thin mode, so no Oracle Instant Client is needed.
- **SQL Server**: the pymssql wheels bundle FreeTDS. Install it separately only if pip has to build pymssql from source.
- **PostgreSQL / MySQL**: make sure the server is running and reachable.
- **JSON fields** appear in monospace.
</details>

---

## 🔌 SSH tunnels

Tick **Connect through an SSH tunnel** to reach a database that is only visible from an SSH server (a bastion or jump host). Enter the SSH server, your user, and a password or a private key file. The database **host and port are as seen from the SSH server**, e.g. `localhost`.

```mermaid
flowchart TD
    A["Connect through the tunnel"] --> B["Reach the SSH server<br/>nothing secret is sent yet"]
    B --> C{"Host key"}
    C -->|"never seen before"| D["App shows the fingerprint"]
    D -->|"you trust it"| E["Remembered in known_hosts.json"]
    D -->|"you don't"| X["Stop"]
    C -->|"matches the remembered key"| E
    C -->|"differs from the remembered key"| STOP["Refused, no override<br/>this is what interception looks like"]
    E --> F["Log in with your password or key"]
    F --> G["Listen on 127.0.0.1 only<br/>and forward to the database"]
```

- The tunnel closes when you disconnect or delete the connection, and re-opens on the same port if SSH drops.
- SSH passwords and passphrases are encrypted like database passwords. A key file stays where it is; only its path is saved.
- If you know a server was reinstalled, remove its entry from `known_hosts.json` in the data folder.
- **Not supported:** SSH agent or hardware keys, jump chains (`ProxyJump`), and MongoDB or Redis connections that use a URL (use host and port). The SSH server must allow `AllowTcpForwarding yes`.

---

## 🤖 SQL assistant

Off until you turn it on (**Ask** in a query tab, or ⌘K → *SQL assistant settings*) with your own Anthropic API key. The key is stored encrypted on this computer and billed to your Anthropic account.

| Sent to the Anthropic API | Never sent |
|---|---|
| The database type | Row data and query results |
| The *names* of tables and columns | Passwords |
| The foreign keys between them | Hosts and file paths |
| The text you type | |

- **Show what's sent** prints the exact text without sending it.
- It only **writes** SQL into the editor and never runs it. The statement is labelled *Reads data only*, *Changes data*, or a warning for `UPDATE`/`DELETE` without a `WHERE`. Running it goes through the usual confirmations and the read-only and production protections.
- For a large schema, only the tables your request seems to be about are described in full.
- Model: `claude-opus-5-5` by default (`DBV_AI_MODEL` to change). `DBV_AI_BASE_URL` points it at another endpoint.
- It needs an internet connection. A rejected key, a rate limit or an unreachable API is reported in the panel.

---

## 🔐 Security

- **Passwords are encrypted** with Fernet. The key lives in the **system keychain** (macOS Keychain, Windows Credential Manager, Secret Service), not in a file. An existing `secret.key` is moved there on first run (checked by reading it back) and then deleted.
- **No usable keychain?** The key stays in `secret.key` (`0600`). With an explicit `DBV_DATA_DIR` (portable or test setups) the key stays in that folder and the keychain isn't touched. `DBV_KEY_STORE=keychain|file` overrides this.
- **The key is never replaced once it exists.** A locked or unreadable keychain stops the app with a clear message instead of inventing a new key that would orphan every saved password.
- **Back up carefully.** `connections.json` is useless without the key. Lose the keychain item and your saved passwords are gone (the connections remain; re-enter the passwords).
- The data folder is `0700`; `connections.json` and `saved_queries.json` are `0600`. Saved queries are stored as plain text (unlike passwords), so don't put secrets in the SQL you save.
- **The UI talks to `127.0.0.1` only.** Every `/api` call needs a per-launch token and a loopback `Host` header, and CORS is off, so other local processes and web pages can't reach your databases.
- Table and column names are quoted for each database, never pasted into SQL, and values are always parameters.
- Logs go to `app.log` in the data folder (rotated) and contain no row data. `DBV_DEBUG=1` opens the web inspector.
- Anyone who can run code as your user can still ask the keychain for the key. This protects the file at rest, not a compromised account.

---

## ⌨️ Shortcuts

| Keys | Does |
|---|---|
| `⌘/Ctrl + K` | Jump to a table, connection, tab or action |
| `⌘/Ctrl + Enter` | Run the query |
| `Esc` | Close a dialog |
| `Tab` | Move between fields |

---

## 🧪 Develop

```mermaid
flowchart LR
    U["Unit + API tests<br/>SQLite, no servers"] --> I["Integration tests<br/>the same contract on each real database"]
    I --> E["Browser tests<br/>drive the real UI in Chrome"]
    E --> B["build.sh<br/>runs the tests, then builds the app"]
```

```bash
.venv/bin/python -m pytest tests --ignore=tests/e2e        # unit and API tests, no servers needed
.venv/bin/python -m pytest tests/e2e                       # browser tests (needs Playwright + Chrome)
python tests/ssh_fixture/make_keys.py                      # once: throwaway SSH keys for the tunnel tests (never committed)
docker compose -f docker-compose.test.yml up -d --wait     # MySQL, PostgreSQL, SQL Server, Oracle, MongoDB, Redis, Cassandra, SSH
.venv/bin/python -m pytest tests/integration               # the same contract against each real database
./build.sh                                                 # runs the tests, then builds dist/DB Visualizer.app
```

GitHub Actions runs the unit, real-database and browser tests on Linux, and builds the macOS app, on every push and pull request.

<details>
<summary><b>Status: what is and isn't verified</b></summary>

| | |
|---|---|
| ✅ Tested | All eight databases against real servers; SSH tunnels; the browser UI; the macOS build in CI |
| ⚠️ The macOS app is **unsigned** | To distribute it, sign and notarize it with an Apple Developer ID |
| ⚠️ Not tested | Windows. SQL Server and Oracle through an SSH tunnel. The SQL assistant against the live Anthropic API (tests use a local fake) |
| ⚠️ Different from production | SQL Server tests use Azure SQL Edge; Oracle tests use 23ai Free |

</details>

<details>
<summary><b>Troubleshooting</b></summary>

**`pip: command not found`** — use `pip3` on macOS.

**Module not found** — install everything: `pip3 install --upgrade -r requirements.txt`.

**Can't connect** — check the server is running, the port is reachable, and (for a bastion) that SSH allows TCP forwarding.

**Lost saved passwords** — they're encrypted with a key in your keychain. If that item is gone, re-enter the passwords; the connections themselves are kept.
</details>

---

<div align="center">

A custom database visualization tool, built for browsing and managing databases with fewer regrets.

</div>
