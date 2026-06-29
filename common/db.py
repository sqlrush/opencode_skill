"""Read-only database access for OpenGauss / GaussDB via pg8000.

Port of internal/driver/driver.go. Both connection types (opengauss, gaussdb)
speak a PostgreSQL-compatible wire protocol that pg8000 connects to directly
(verified against openGauss-lite 5.0.3). The session is pinned READ ONLY by
default so probes can never mutate user data; callers that need to run
EXPLAIN ANALYZE on DML (wrapped in a rolled-back transaction) opt out explicitly.
"""
from __future__ import annotations

import ssl
from typing import Any, Optional, Sequence

import pg8000.dbapi

from .config import Connection
from .credential import load_secret

CONNECT_TIMEOUT = 15  # seconds, matches gdaa's pingTimeout

# sslmode values that imply an encrypted channel. pg8000 takes an ssl.SSLContext
# (or None); we map the gdaa sslmode whitelist onto that.
_SSL_MODES = frozenset({"allow", "prefer", "require", "verify-ca", "verify-full"})


class DBError(Exception):
    """Raised on connection or query failures."""


def _ssl_context(sslmode: str) -> Optional[ssl.SSLContext]:
    if sslmode not in _SSL_MODES:
        return None
    ctx = ssl.create_default_context()
    if sslmode in ("allow", "prefer", "require"):
        # No CA verification for these modes (parity with libpq semantics).
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


class Database:
    """Thin read-only wrapper over a pg8000 DB-API connection."""

    def __init__(self, raw: "pg8000.dbapi.Connection", conn: Connection):
        self._raw = raw
        self.conn = conn

    @classmethod
    def open(
        cls, conn: Connection, password: str, read_only: bool = True
    ) -> "Database":
        """Connect and verify reachability, then pin the session read-only."""
        try:
            raw = pg8000.dbapi.connect(
                host=conn.host,
                port=conn.port,
                database=conn.database,
                user=conn.user,
                password=password,
                timeout=CONNECT_TIMEOUT,
                ssl_context=_ssl_context(conn.sslmode or "disable"),
            )
        except Exception as exc:
            raise DBError(
                f"connect to {conn.name} "
                f"({conn.user}@{conn.host}:{conn.port}/{conn.database}): {exc}"
            ) from exc

        raw.autocommit = True
        db = cls(raw, conn)
        if read_only:
            # Belt-and-suspenders: block any accidental writes/DDL at the
            # session level. hypopg/EXPLAIN/catalog reads are unaffected.
            try:
                db.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
            except DBError:
                # Some deployments reject this; fall back to the GUC form.
                db.execute("SET default_transaction_read_only = on")
        return db

    @classmethod
    def connect(cls, name: str, read_only: bool = True) -> "Database":
        """Open the named connection, resolving credentials from ~/.gdaa."""
        from .config import find

        conn = find(name)
        return cls.open(conn, load_secret(conn.name), read_only=read_only)

    def query(
        self, sql: str, params: Optional[Sequence[Any]] = None
    ) -> tuple[list[str], list[tuple]]:
        """Run a query, returning (column_names, rows)."""
        cur = self._raw.cursor()
        try:
            cur.execute(sql, params or ())
            cols = [d[0] for d in (cur.description or [])]
            rows = [tuple(r) for r in cur.fetchall()] if cur.description else []
            return cols, rows
        except Exception as exc:
            raise DBError(_format_pg_error(exc)) from exc
        finally:
            cur.close()

    def scalar(self, sql: str, params: Optional[Sequence[Any]] = None) -> Any:
        """Run a query and return the first column of the first row (or None)."""
        _, rows = self.query(sql, params)
        return rows[0][0] if rows else None

    def query_in_rollback(
        self, sql: str, params: Optional[Sequence[Any]] = None
    ) -> tuple[list[str], list[tuple]]:
        """Run a query inside a transaction that is always rolled back.

        Used for EXPLAIN ANALYZE on DML so the statement executes (producing
        real timings) but never commits. Requires a non-read-only session.
        """
        prev = self._raw.autocommit
        self._raw.autocommit = False
        cur = self._raw.cursor()
        try:
            cur.execute(sql, params or ())
            cols = [d[0] for d in (cur.description or [])]
            rows = [tuple(r) for r in cur.fetchall()] if cur.description else []
            return cols, rows
        except Exception as exc:
            raise DBError(_format_pg_error(exc)) from exc
        finally:
            try:
                self._raw.rollback()
            finally:
                cur.close()
                self._raw.autocommit = prev

    def set_statement_timeout(self, seconds: int) -> None:
        """Bound server-side statement execution time (parity with gdaa)."""
        self.execute(f"SET statement_timeout = {int(seconds) * 1000}")

    def execute(self, sql: str, params: Optional[Sequence[Any]] = None) -> None:
        """Run a statement that returns no rows (SET, function calls, ...)."""
        cur = self._raw.cursor()
        try:
            cur.execute(sql, params or ())
        except Exception as exc:
            raise DBError(_format_pg_error(exc)) from exc
        finally:
            cur.close()

    def close(self) -> None:
        try:
            self._raw.close()
        except Exception:
            pass

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _format_pg_error(exc: Exception) -> str:
    """Render a pg8000 error the way pgx does: 'ERROR: <msg> (SQLSTATE <code>)'.

    pg8000 raises its DatabaseError with a dict of openGauss error fields
    (keys: 'S' severity, 'M' message, 'C' SQLSTATE). Fall back to str().
    """
    args = getattr(exc, "args", None)
    if args and isinstance(args[0], dict):
        fields = args[0]
        msg = fields.get("M", str(exc))
        code = fields.get("C", "")
        if code:
            return f"ERROR: {msg} (SQLSTATE {code})"
        return f"ERROR: {msg}"
    return str(exc)
