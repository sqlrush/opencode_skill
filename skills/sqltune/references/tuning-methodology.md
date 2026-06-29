# OpenGauss/GaussDB SQL Tuning Methodology

Checklist distilled from the opendb tuner. Work through it against the
evidence bundle; cite numbers, not impressions.

## 1. Plan walkthrough

- Identify the most expensive node (highest cost share / actual time when analyzed).
- For each Seq Scan: is the table large (`## Tables` pages/tuples)? Is the
  Filter selective (`## Column Statistics` n_distinct, null_frac)?
  - Selective filter + large table + no matching index → index candidate.
  - n_distinct negative values are ratios (e.g. -0.5 = 50% distinct rows).
- For each Sort: does an existing index already order by the Sort Key
  (`## Indexes` DEF)? If not and the sort is hot, consider an index;
  check `work_mem` for spills (EXPLAIN ANALYZE shows "Sort Method: external").
- For Nested Loop: multiply inner-rows × outer-loops; if inner side is a
  Seq Scan, a join-key index usually wins.
- Hash Join is normally fine; verify build side fits work_mem.

## 2. Cardinality sanity

- Compare plan estimated rows vs reltuples and (when --analyze) actual rows.
- >10× mis-estimate → stale stats: recommend `ANALYZE <table>;` first,
  and check `default_statistics_target` for skewed columns.

## 3. Index recommendations

- Composite index column order: equality predicates first, then range,
  then ORDER BY columns.
- Verify no existing index already covers the prefix (`## Indexes`).
- Always provide exact DDL: `CREATE INDEX idx_<table>_<cols> ON <table>(<cols>);`
- Warn: OpenGauss CREATE INDEX takes ShareLock (blocks writes); suggest
  off-peak execution; CONCURRENTLY semantics differ on OpenGauss — verify on the target version before recommending it.

## 4. GUC review (against `## Key Parameters (GUC)`)

| Parameter | Heuristic |
|---|---|
| work_mem | Sort/Hash spills → raise session-level first, not globally |
| effective_cache_size | Should reflect available OS cache; too low biases away from index scans |
| random_page_cost | SSD storage → 1.1–2.0; default 4 over-penalizes index scans |
| max_parallel_workers_per_gather | Large scans may benefit; verify CPU headroom |
| default_statistics_target | Raise per-column for skewed data, then ANALYZE |

Prefer SQL rewrite > index > session GUC > global GUC (ascending blast radius).

## 5. Rewrite patterns

- `SELECT *` → project needed columns (enables index-only scans).
- Leading-wildcard LIKE cannot use btree; consider trigram/full-text.
- OR across columns → UNION ALL of indexed branches.
- Functions wrapping indexed columns defeat the index; move the function
  to the constant side.
- Large IN lists → JOIN against VALUES.

## 6. Recommendation ranking

Order by (expected speedup × confidence) / risk. One primary
recommendation; alternatives listed under "if constraints forbid".
