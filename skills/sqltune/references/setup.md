# gdaa Setup

## Install

```bash
git clone https://github.com/sqlrush/openclaw_dbaa
cd openclaw_dbaa && make install   # builds bin/gdaa into ~/.local/bin
gdaa --version
```

## Add a connection (password prompted, stored AES-256-GCM encrypted)

```bash
gdaa connect add og-prod --type opengauss --host 10.0.0.1 --port 5432 -U tuner -d appdb
gdaa connect test og-prod
```

GaussDB: use `--type gaussdb`.

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
| exit 2 / connection refused | check host/port/firewall; `gdaa connect test <name>` |
| exit 2 / password authentication | re-run `gdaa connect add <name> ...` to re-enter password |
| exit 3 / permission denied for dbe_perf | grant monadmin (SQL above) |
| sqlfetch finds nothing | enable `enable_stmt_track`, wait for traffic, retry |
| sqlfetch returns normalized SQL | enable `track_stmt_parameter`; or ask user for literal values |
| exit 4 / syntax or object error | check substituted placeholder values and object names in the SQL |
| exit 5 / timeout | raise `--timeout`, or tune during off-peak |
