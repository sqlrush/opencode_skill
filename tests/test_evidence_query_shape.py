"""证据采集 SQL 的输出列必须唯一命名。

gsql 后端用 json_agg(row_to_json(...)) 回传结果、GRMP 中间件按列名成键——
两种协议都以列名为键,重名列会被静默吞掉一列,行变短后按下标取值越界。
pg8000 走位置元组不受影响,所以这类缺陷只在换后端时才炸。
"""
import pathlib
import re
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "skills" / "sqltune" / "scripts"))

import evidence  # noqa: E402


class _RecordingDB:
    """记录 SQL 并回一个够宽的空结果,让采集函数走完。"""

    def __init__(self):
        self.queries: list[str] = []

    def query(self, sql, params=None):
        self.queries.append(sql)
        return [], []


def _output_names(sql: str) -> list[str]:
    """取 SELECT 列表里每个输出表达式的最终列名。"""
    m = re.search(r"(?is)\bSELECT\b(.*?)\bFROM\b", sql)
    assert m, f"no SELECT ... FROM in: {sql[:80]}"
    depth = 0
    items, cur = [], []
    for ch in m.group(1):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            items.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    items.append("".join(cur))

    names = []
    for it in items:
        it = it.strip()
        alias = re.search(r"(?is)\bAS\s+([a-z_][\w]*)\s*$", it)
        if alias:
            names.append(alias.group(1).lower())
            continue
        tail = it[it.rindex(".") + 1:] if "." in it else it
        tail = re.sub(r"::[\w ]+$", "", tail).strip()
        names.append(tail.lower())
    return names


@pytest.mark.parametrize("fn", [
    evidence.collect_tables,
    evidence.collect_indexes,
    evidence.collect_column_stats,
])
def test_collector_queries_have_unique_output_names(fn):
    db = _RecordingDB()
    fn(db, ["some_table"])
    assert db.queries, f"{fn.__name__} 未发出查询"
    for sql in db.queries:
        names = _output_names(sql)
        dupes = {n for n in names if names.count(n) > 1}
        assert not dupes, f"{fn.__name__} 输出列重名 {dupes}: {names}"


def test_collect_indexes_names_are_aliased():
    # 具体钉住曾经炸过的那两列(t.relname / i.relname)。
    db = _RecordingDB()
    evidence.collect_indexes(db, ["t"])
    names = _output_names(db.queries[0])
    assert "table_name" in names and "index_name" in names
    assert names.count("relname") == 0
