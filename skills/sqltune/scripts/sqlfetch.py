"""Resolve a unique_sql_id to SQL text (port of internal/probe/sqlfetch.go).

statement_history first (literal values), dbe_perf.statement as the normalized
fallback. The id is parsed as an integer and inlined (safe: int-validated).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_PLACEHOLDER_RE = re.compile(r"\?|\$\d+|(?:^|[^:])(:[a-zA-Z_]\w*)")


@dataclass(frozen=True)
class FetchResult:
    sql_id: str
    sql: str
    schema: str
    source: str  # statement_history | statement
    normalized: bool
    placeholders: int


def count_placeholders(sql_text: str) -> int:
    n = 0
    for m in _PLACEHOLDER_RE.finditer(sql_text):
        if m.group(1) or m.group(0).startswith("?") or m.group(0).startswith("$"):
            n += 1
    return n


def sql_fetch(db, raw_id: str) -> FetchResult:
    try:
        sid = int(raw_id.strip())
    except ValueError as exc:
        raise ValueError(
            f"sql id {raw_id!r}: must be a (possibly negative) integer") from exc

    hist = f"""
SELECT schema_name, query
FROM dbe_perf.statement_history
WHERE unique_query_id = {sid}
  AND query NOT LIKE '/* missing SQL statement%'
ORDER BY start_time DESC
LIMIT 1"""
    _, rows = db.query(hist)
    if rows:
        schema, query = rows[0][0], rows[0][1]
        source = "statement_history"
    else:
        stmt = f"""
SELECT query FROM dbe_perf.statement
WHERE unique_sql_id = {sid}
  AND query IS NOT NULL
  AND query <> ''
LIMIT 1"""
        _, srows = db.query(stmt)
        if not srows:
            raise ValueError(
                f"sql id {raw_id} not found in dbe_perf.statement_history or "
                f"dbe_perf.statement (check enable_stmt_track / track_stmt_parameter)")
        schema, query = "", srows[0][0]
        source = "statement"

    n = count_placeholders(query)
    return FetchResult(sql_id=raw_id, sql=query, schema=schema or "",
                       source=source, normalized=n > 0, placeholders=n)
