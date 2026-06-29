# Setup (OpenGauss/GaussDB connection)

These skills run as Python scripts — **no `gdaa` binary required**.

## Install

```bash
git clone https://github.com/sqlrush/opencode_skill
cd opencode_skill && python3 -m pip install -r requirements.txt   # pg8000, cryptography, PyYAML
python3 skills/sqltune/scripts/sqltune.py -h
```

Install into OpenCode: see `docs/INSTALL-opencode.md`.

## Add a connection

Connections live in `~/.gdaa` (shared, byte-compatible store) and are selected with `-c <name>`.
See `docs/INSTALL-opencode.md` §1 to create one:

- reuse an existing connection: `cat ~/.gdaa/config.yaml` (names only, no password)
- create by hand: write `~/.gdaa/config.yaml`, then encrypt the password with the repo's
  `common.save_secret` (writes `~/.gdaa/credentials/<name>.enc`, AES-256-GCM)
- CI / one-off: set `GDAA_PASSWORD` (and `GDAA_HOME` to relocate the store)

GaussDB: set `type: gaussdb` in the connection entry.

Verify it works (read-only):

```bash
python3 skills/sqltune/scripts/sqltune.py -c og-prod --sql-stdin <<'SQL'
SELECT 1
SQL
```

## Monitoring user minimal privileges

```sql
-- as admin; OG: monadmin covers dbe_perf
ALTER USER tuner MONADMIN;
-- or explicit grants:
GRANT USAGE ON SCHEMA dbe_perf TO tuner;
GRANT SELECT ON ALL TABLES IN SCHEMA dbe_perf TO tuner;
```

## Required GUCs for statement tracking

```sql
ALTER SYSTEM SET enable_stmt_track = on;        -- statement_history rows
ALTER SYSTEM SET track_stmt_parameter = on;     -- literal SQL (else normalized)
```

## Symptom → action

| Symptom | Action |
|---|---|
| exit 2 / connection refused | check host/port/firewall; verify with a `SELECT 1` via the script |
| exit 2 / password authentication | re-create the credential (see "Add a connection"), or set `GDAA_PASSWORD` |
| exit 3 / permission denied for dbe_perf | grant monadmin (SQL above) |
| sqlfetch finds nothing | enable `enable_stmt_track`, wait for traffic, retry |
| sqlfetch returns normalized SQL | enable `track_stmt_parameter`; or pass real values with `--bind` |
| exit 4 / syntax or object error | check substituted placeholder values and object names in the SQL |
| exit 5 / timeout | raise `--timeout`, or tune during off-peak |
