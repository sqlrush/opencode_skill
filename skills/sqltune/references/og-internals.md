# OpenGauss/GaussDB Internals Cheat Sheet

## dbe_perf views used by gdaa

| View | Content | Notes |
|---|---|---|
| dbe_perf.statement | Normalized statement aggregates (unique_sql_id, n_calls, total_elapse_time µs, n_returned_rows, n_blocks_hit/fetched) | Source for slowsql/topsql |
| dbe_perf.statement_history | Per-execution history with literal SQL + schema_name | Needs `enable_stmt_track=on`; literals need `track_stmt_parameter=on` |

`total_elapse_time` is in microseconds; gdaa converts to ms/s.

## Plan node quick reference

- Seq Scan / Index Scan / Index Only Scan / Bitmap Heap Scan — access paths.
- Nested Loop / Hash Join / Merge Join — join strategies.
- "Sort Method: external merge" (ANALYZE output) — work_mem spill.
- Row-store vs column-store tables (orientation=column) have different
  optimal access patterns; check table DDL when plans look odd.

## OG vs vanilla PostgreSQL differences that matter

- Authentication: OG uses sha256, GaussDB uses SCRAM-SHA256(10) — vanilla
  psql/libpq clients typically cannot connect; gdaa bundles drivers.
- GaussDB requires `database=` DSN key and simple query protocol (xid64).
- Some `enable_*` planner GUCs are OG-specific; read actual values from the `## Key Parameters (GUC)` evidence section rather than assuming PG defaults.
- WDR (workload diagnosis report) exists on OG; out of gdaa v1 scope.
