# opencode_skill

OpenGauss / GaussDB DBA skills, rewritten in Python from the Go `gdaa` tool.

Structure (per the agreed refactor):

```
common/            # ONLY shared layer: connection / credential / read-only driver
skills/<name>/
  SKILL.md         # model-facing playbook (invokes the local python scripts)
  references/      # methodology + GaussDB knowledge base
  scripts/         # this skill's own logic (entry + vendored probes)
tests/             # pytest (live tests skip when the connection is absent)
```

Design rule: `common/` is the single shared package (it just connects to the DB
and decrypts credentials, reusing gdaa's `~/.gdaa` store unchanged). Everything
else — probes, report rendering, analysis — lives inside each skill's `scripts/`.

## Setup

```bash
python3 -m pip install -r requirements.txt
```

## Install into OpenCode

```bash
./install-opencode.sh          # → ~/.config/opencode/skills/
```

Full step-by-step (prerequisites, DB connection setup, verification,
troubleshooting): see [docs/INSTALL-opencode.md](docs/INSTALL-opencode.md).

Connections are read from `~/.gdaa/config.yaml` + `~/.gdaa/credentials/` (the
same store the Go `gdaa` tool uses), or override the base dir with `GDAA_HOME`.
`GDAA_PASSWORD` overrides the stored secret for one-off / CI use.

## Scope (current)

Full parity with the Go `gdaa` skill set — 10 skills across 3 families.

SQL-optimization family:

- `skills/slowsql`  — find slow SQL by avg-time threshold
- `skills/topsql`   — rank the most resource-consuming SQL
- `skills/sqlfetch` — resolve a unique_sql_id to full SQL text
- `skills/explain`  — execution plan + deterministic risk findings
- `skills/sqltune`  — deep SQL tuning (hypopg + cost + equivalence verification)

Stored-procedure family:

- `skills/proctune` — stored-procedure analysis + cursor SELECT tuning
- `skills/procinfo` — read-only stored-procedure structural diagnostic (hand off to proctune)
- `skills/topproc`  — rank the most resource-consuming procedures (pg_stat_user_functions)

Diagnostics family:

- `skills/health`   — 12-dimension read-only health check + deterministic findings
- `skills/wdr`      — WDR snapshot-delta interpretation (7 dims, snaps/collect/render)

Each skill's output is cross-validated against the Go `gdaa` binary. health and
wdr were diffed byte-for-byte: same dimensions, headers, threshold strings, and
findings (wdr's immutable-snapshot evidence is numerically identical, and `wdr
render` matches except an intentional drop of the "gdaa" word in the footer).
slowsql/topsql/sqlfetch differ only in the trailing "Next:" hint, which points
at the local Python scripts instead of `gdaa`.

Driver: `pg8000` (pure Python; verified against openGauss-lite 5.0.3 for both
`opengauss` and `gaussdb` connection types).
