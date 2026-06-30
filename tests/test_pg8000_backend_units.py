# tests/test_pg8000_backend_units.py
import sys, pathlib
_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402
from common.config import Connection  # noqa: E402
from common.backends.base import DBError  # noqa: E402
from common.backends import pg8000_backend as pgb  # noqa: E402

class FakeCursor:
    def __init__(self, desc, rows): self._desc, self._rows, self.description = desc, rows, desc
    def execute(self, sql, params=()): self.last = (sql, params)
    def fetchall(self): return self._rows
    def close(self): pass

class FakeConn:
    def __init__(self, desc=None, rows=None):
        self.autocommit = False
        self._cur = FakeCursor(desc, rows or [])
        self.executed = []
    def cursor(self):
        self.executed.append("cursor")
        return self._cur
    def rollback(self): self.executed.append("rollback")
    def close(self): self.executed.append("close")

def _conn(): return Connection(name="a", type="opengauss", host="h", port=5432, database="d", user="u")

def test_open_pins_read_only(monkeypatch):
    fake = FakeConn()
    monkeypatch.setattr(pgb.pg8000.dbapi, "connect", lambda **kw: fake)
    b = pgb.Pg8000Backend.open(_conn(), "pw", read_only=True)
    # 只读钉：execute 过 SET ... READ ONLY
    assert fake.autocommit is True

def test_query_returns_cols_and_rows(monkeypatch):
    fake = FakeConn(desc=[("a",), ("b",)], rows=[(1, "x")])
    monkeypatch.setattr(pgb.pg8000.dbapi, "connect", lambda **kw: fake)
    b = pgb.Pg8000Backend.open(_conn(), "pw", read_only=False)
    cols, rows = b.query("select 1 a, 'x' b")
    assert cols == ["a", "b"]
    assert rows == [(1, "x")]

def test_open_connect_failure_raises_dberror(monkeypatch):
    def boom(**kw): raise RuntimeError("refused")
    monkeypatch.setattr(pgb.pg8000.dbapi, "connect", boom)
    with pytest.raises(DBError):
        pgb.Pg8000Backend.open(_conn(), "pw")
