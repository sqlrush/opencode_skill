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

Connections are read from `~/.gdaa/config.yaml` + `~/.gdaa/credentials/` (the
same store the Go `gdaa` tool uses), or override the base dir with `GDAA_HOME`.
`GDAA_PASSWORD` overrides the stored secret for one-off / CI use.

## Scope (current)

SQL-optimization family:

- `skills/slowsql`  — find slow SQL by avg-time threshold
- `skills/topsql`   — rank the most resource-consuming SQL
- `skills/sqlfetch` — resolve a unique_sql_id to full SQL text
- `skills/explain`  — execution plan + deterministic risk findings
- `skills/sqltune`  — deep SQL tuning (hypopg + cost + equivalence verification)

Stored-procedure family:

- `skills/proctune` — stored-procedure analysis + cursor SELECT tuning

Each skill's output is cross-validated byte-identical against the Go `gdaa`
binary (slowsql/topsql/sqlfetch differ only in the trailing "Next:" hint, which
points at the local Python scripts instead of `gdaa`).

Driver: `pg8000` (pure Python; verified against openGauss-lite 5.0.3 for both
`opengauss` and `gaussdb` connection types).
"""
