"""Catalog collection (I/O only — this module never judges anything).

Each dimension degrades independently: if the index query is denied, the table
findings still come out and the reason lands in `notes`, mirroring
skills/health/scripts/collectors.py.
"""
from __future__ import annotations

import common
from model import IndexFact, ObjectFacts, TableFact

_TABLES_Q = """
SELECT
  n.nspname::text                                              AS schema,
  c.relname::text                                              AS table,
  EXISTS (SELECT 1 FROM pg_constraint pk
          WHERE pk.conrelid = c.oid AND pk.contype = 'p')      AS has_pk,
  COALESCE((SELECT array_agg(fk.conname::text)
            FROM pg_constraint fk
            WHERE fk.conrelid = c.oid AND fk.contype = 'f'),
           ARRAY[]::text[])                                    AS fks,
  COALESCE((SELECT array_agg(a.attname::text ORDER BY a.attnum)
            FROM pg_attribute a
            WHERE a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped),
           ARRAY[]::text[])                                    AS columns
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind = 'r' AND n.nspname = %s
ORDER BY c.relname"""

# indkey is an int2vector; string_to_array keeps this portable across
# openGauss/GaussDB versions. Expression index columns (attnum 0) drop out.
_INDEXES_Q = """
SELECT
  n.nspname::text                                              AS schema,
  t.relname::text                                              AS table,
  i.relname::text                                              AS name,
  COALESCE((SELECT array_agg(a.attname::text ORDER BY k.ord)
            FROM unnest(string_to_array(ix.indkey::text, ' '))
                 WITH ORDINALITY AS k(attnum, ord)
            JOIN pg_attribute a
              ON a.attrelid = t.oid AND a.attnum = k.attnum::smallint),
           ARRAY[]::text[])                                    AS columns,
  ix.indisunique                                               AS is_unique,
  ix.indisprimary                                              AS is_primary,
  COALESCE(s.idx_scan, 0)                                      AS scans
FROM pg_index ix
JOIN pg_class i     ON i.oid = ix.indexrelid
JOIN pg_class t     ON t.oid = ix.indrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
LEFT JOIN pg_stat_user_indexes s ON s.indexrelid = ix.indexrelid
WHERE n.nspname = %s
ORDER BY t.relname, i.relname"""


def _as_tuple(val) -> tuple[str, ...]:
    """Array columns come back as list (pg8000) or JSON array (gsql)."""
    if not val:
        return ()
    if isinstance(val, str):                 # defensive: '{a,b}' text form
        return tuple(v for v in val.strip("{}").split(",") if v)
    return tuple(str(v) for v in val)


def _collect_tables(db, schema: str) -> tuple[tuple[TableFact, ...], list[str]]:
    try:
        _, rows = db.query(_TABLES_Q, (schema,))
    except common.DBError as exc:
        return (), [f"表信息采集失败（已降级）：{exc}"]
    return tuple(
        TableFact(schema=str(r[0]), table=str(r[1]), has_pk=bool(r[2]),
                  fks=_as_tuple(r[3]), columns=_as_tuple(r[4]))
        for r in rows
    ), []


def _collect_indexes(db, schema: str) -> tuple[tuple[IndexFact, ...], list[str]]:
    try:
        _, rows = db.query(_INDEXES_Q, (schema,))
    except common.DBError as exc:
        return (), [f"索引信息采集失败（已降级）：{exc}"]
    return tuple(
        IndexFact(schema=str(r[0]), table=str(r[1]), name=str(r[2]),
                  columns=_as_tuple(r[3]), is_unique=bool(r[4]),
                  is_primary=bool(r[5]), scans=int(r[6] or 0))
        for r in rows
    ), []


def collect_facts(db, schema: str) -> ObjectFacts:
    """Snapshot one schema's tables and indexes. Never raises on query failure."""
    tables, t_notes = _collect_tables(db, schema)
    indexes, i_notes = _collect_indexes(db, schema)
    return ObjectFacts(tables=tables, indexes=indexes, notes=tuple(t_notes + i_notes))
