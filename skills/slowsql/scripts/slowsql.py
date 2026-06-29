#!/usr/bin/env python3
"""slowsql — list statements slower than a threshold (avg ms).

Port of internal/probe/slowsql.go + internal/cli/slowsql.go. Reads
dbe_perf.statement aggregates; slowest first. cpu_sec is captured (JSON) to
expose the DB-time trap (slow-but-low-CPU = contention, not CPU-bound work).

Usage:
    slowsql.py -c <conn> [--threshold 1000] [--limit 20] [--format json]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from dataclasses import dataclass
from typing import Optional

_HERE = pathlib.Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parent))          # sibling modules
sys.path.insert(0, str(_HERE.parents[3]))      # repo root for `common`

import common  # noqa: E402
import render  # noqa: E402


@dataclass(frozen=True)
class StmtRow:
    sql_id: str
    query: str
    calls: int
    avg_ms: float
    total_sec: float
    cpu_sec: float
    rows: int


def slow_sql(db, threshold_ms: int, limit: int) -> list[StmtRow]:
    q = rf"""
SELECT
  unique_sql_id::text,
  LEFT(REGEXP_REPLACE(query, E'\\s+', ' ', 'g'), 180) AS query,
  n_calls AS calls,
  ROUND((total_elapse_time/NULLIF(n_calls,0))/1000::numeric, 2) AS avg_ms,
  ROUND(total_elapse_time/1000000::numeric, 2) AS total_sec,
  ROUND(cpu_time/1000000::numeric, 2) AS cpu_sec,
  n_returned_rows AS rows
FROM dbe_perf.statement
WHERE (total_elapse_time/NULLIF(n_calls,0))/1000 > {int(threshold_ms)}
  AND n_calls > 0
ORDER BY total_elapse_time/NULLIF(n_calls,0) DESC
LIMIT {int(limit)}"""
    _, rows = db.query(q)
    return [StmtRow(r[0], r[1], int(r[2]), float(r[3]), float(r[4]),
                    float(r[5]), int(r[6])) for r in rows]


def stmt_table(title: str, rows: list[StmtRow]) -> str:
    if not rows:
        return (f"## {title}\n\nNo matching statements. "
                f"Check `enable_stmt_track` / lower --threshold.\n")
    body = [[str(i + 1), r.sql_id, str(r.calls), f"{r.avg_ms:.2f}",
             f"{r.total_sec:.2f}", str(r.rows), render.truncate(r.query, 100)]
            for i, r in enumerate(rows)]
    return ("## " + title + "\n\n" +
            render.table(["#", "SQL_ID", "CALLS", "AVG_MS", "TOTAL_S", "ROWS", "QUERY"], body) +
            "\nNext: `python3 ../../sqlfetch/scripts/sqlfetch.py -c <conn> <SQL_ID>` "
            "to get the full SQL text.\n")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="slowsql.py",
                                 description="List statements slower than --threshold (avg ms)")
    ap.add_argument("-c", "--conn", required=True, help="connection name")
    ap.add_argument("--threshold", type=int, default=1000, help="avg elapsed threshold (ms)")
    ap.add_argument("--limit", type=int, default=20, help="max rows")
    ap.add_argument("--format", choices=["markdown", "json"], default="markdown")
    ap.add_argument("--timeout", type=int, default=30)
    args = ap.parse_args(argv)

    try:
        db = common.Database.connect(args.conn)
    except (common.ConfigError, common.CredentialError, common.DBError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        db.set_statement_timeout(args.timeout)
        rows = slow_sql(db, args.threshold, args.limit)
        if args.format == "json":
            print(json.dumps([r.__dict__ for r in rows], ensure_ascii=False, indent=2))
        else:
            print(stmt_table("Slow SQL", rows), end="")
        return 0
    except (ValueError, common.DBError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
