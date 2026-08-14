"""DB-free unit tests for sqltune's catalog-driven placeholder typing (coltypes)."""
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "skills" / "sqltune" / "scripts"))

import coltypes  # noqa: E402
import placeholder  # noqa: E402


class FakeDB:
    """query() 返回预置行；rows 传 Exception 实例则抛出（模拟连接故障）。"""

    def __init__(self, rows):
        self._rows = rows
        self.queries = []

    def query(self, sql, params=None):
        self.queries.append(sql)
        if isinstance(self._rows, Exception):
            raise self._rows
        return ([], self._rows)


# --- comparison_column: 从占位符左上下文提取比较列名 --------------------------

def test_comparison_column_qualified_eq():
    ctx = "SELECT * FROM orders o WHERE o.stock_quantity = "
    assert placeholder.comparison_column(ctx) == "stock_quantity"


def test_comparison_column_no_space_before_op():
    assert placeholder.comparison_column("... WHERE total_items=") == "total_items"


def test_comparison_column_in_list():
    # IN 前面的 "in"/"(" 要跳过，取到真正的列名
    assert placeholder.comparison_column("... WHERE category_id in (") == "category_id"
    assert placeholder.comparison_column("... WHERE category_id IN(") == "category_id"


def test_comparison_column_not_a_column():
    assert placeholder.comparison_column("SELECT ") is None
    assert placeholder.comparison_column("... WHERE TO_CHAR(d, ") is None


# --- value_for_type: 类型 → 合成值 -------------------------------------------

def test_value_for_type_int_and_numeric():
    assert placeholder.value_for_type("integer") == "1"
    assert placeholder.value_for_type("bigint") == "1"
    assert placeholder.value_for_type("numeric") == "1"
    assert placeholder.value_for_type("double precision") == "1"


def test_value_for_type_datetime_ordering():
    # "timestamp..." 必须在 "time..." 之前判断，否则会被误配成 time
    assert placeholder.value_for_type("timestamp without time zone") == "'2024-01-01 00:00:00'"
    assert placeholder.value_for_type("date") == "'2024-01-01'"
    assert placeholder.value_for_type("time without time zone") == "'12:00:00'"


def test_value_for_type_string_and_unknown_returns_none():
    # 字符串类型交回启发式（LIKE 上下文需要 '%test%'），未知类型也不硬猜
    assert placeholder.value_for_type("character varying") is None
    assert placeholder.value_for_type("text") is None
    assert placeholder.value_for_type("some_weird_type") is None
    assert placeholder.value_for_type(None) is None


# --- substitute(types=...): 类型信息驱动替换 ---------------------------------

def test_substitute_type_overrides_heuristic():
    # 列名不在整数白名单里,但 catalog 说它是 integer → 填 1 而不是 'test'
    r = placeholder.substitute(
        "SELECT * FROM orders WHERE stock_quantity = ?", [], types=["integer"])
    assert r.substitutions[0].value == "1"
    assert r.substitutions[0].source == "type"


def test_substitute_bind_beats_type():
    r = placeholder.substitute(
        "SELECT * FROM orders WHERE stock_quantity = ?", ["7"], types=["integer"])
    assert r.substitutions[0].value == "7"
    assert r.substitutions[0].source == "bind"


def test_substitute_none_type_falls_back_to_heuristic():
    r = placeholder.substitute(
        "SELECT * FROM orders WHERE stock_quantity = ?", [], types=[None])
    assert r.substitutions[0].value == "'test'"
    assert r.substitutions[0].source == "rule"


def test_substitute_types_shorter_than_positions():
    r = placeholder.substitute(
        "SELECT * FROM t WHERE a = ? AND b = ?", [], types=["integer"])
    assert r.substitutions[0].value == "1"
    assert r.substitutions[1].value == "'test'"  # 越界按 None 处理


# --- infer_types: 一条 catalog 查询推断各占位符类型 ---------------------------

def test_infer_types_happy_path():
    db = FakeDB([("stock_quantity", "integer")])
    types = coltypes.infer_types(
        db, "SELECT * FROM orders o WHERE o.stock_quantity = ?")
    assert types == ["integer"]
    assert len(db.queries) == 1
    assert "pg_attribute" in db.queries[0]


def test_infer_types_conflict_across_tables_is_dropped():
    # 同名列在两张表里类型不同 → 保守放弃，交回启发式
    db = FakeDB([("status", "integer"), ("status", "character varying")])
    types = coltypes.infer_types(
        db, "SELECT * FROM orders o JOIN shipments s ON s.id = o.id WHERE status = ?")
    assert types == [None]


def test_infer_types_db_failure_degrades_to_none():
    db = FakeDB(RuntimeError("connection lost"))
    types = coltypes.infer_types(db, "SELECT * FROM orders WHERE qty2 = ?")
    assert types == [None]


def test_infer_types_no_placeholders_no_query():
    db = FakeDB([])
    assert coltypes.infer_types(db, "SELECT 1") == []
    assert db.queries == []


# --- validate_binds: bind 错位在执行前拦截 -----------------------------------

def test_validate_binds_string_on_int_position_raises():
    r = placeholder.substitute(
        "SELECT * FROM orders WHERE total_items = ?", ["STANDARD"], types=["integer"])
    with pytest.raises(ValueError) as ei:
        coltypes.validate_binds(r.substitutions, ["integer"])
    msg = str(ei.value)
    assert "STANDARD" in msg
    assert "#1" in msg
    assert "--bind" in msg


def test_validate_binds_numeric_ok():
    r = placeholder.substitute(
        "SELECT * FROM orders WHERE total_items = ?", ["42"], types=["integer"])
    coltypes.validate_binds(r.substitutions, ["integer"])  # 不应抛


def test_validate_binds_without_type_info_is_noop():
    r = placeholder.substitute(
        "SELECT * FROM orders WHERE x = ?", ["STANDARD"], types=[None])
    coltypes.validate_binds(r.substitutions, [None])  # 不应抛


# --- enrich_type_error: 失败时点名坏在哪个占位符 -----------------------------

def test_enrich_type_error_names_synthetic_position():
    r = placeholder.substitute(
        "SELECT * FROM orders WHERE a_id = ? AND stock_quantity = ?", [])
    msg = 'ERROR:  invalid input syntax for integer: "test"'
    enriched = coltypes.enrich_type_error(msg, r.substitutions)
    assert enriched is not None
    assert "#2" in enriched
    assert "--bind" in enriched


def test_enrich_type_error_bind_misalignment_hint():
    r = placeholder.substitute(
        "SELECT * FROM orders WHERE total_items = ?", ["STANDARD"])
    msg = 'ERROR:  invalid input syntax for integer: "STANDARD"'
    enriched = coltypes.enrich_type_error(msg, r.substitutions)
    assert enriched is not None
    assert "错位" in enriched


def test_enrich_type_error_unrelated_value_returns_none():
    r = placeholder.substitute("SELECT * FROM orders WHERE a_id = ?", [])
    msg = 'ERROR:  invalid input syntax for integer: "not-ours"'
    assert coltypes.enrich_type_error(msg, r.substitutions) is None


def test_enrich_type_error_non_type_error_returns_none():
    r = placeholder.substitute("SELECT * FROM orders WHERE a_id = ?", [])
    assert coltypes.enrich_type_error("ERROR: relation does not exist", r.substitutions) is None


def test_quoted_numeric_bind_is_not_flagged_as_a_type_mismatch():
    """`--bind "'2'"` 传给整数列不该被当成错位。

    现场模型在 2026-08-14 那轮学会了「把引号写进值里」,那是当时唯一走得通的
    写法;现在引号由脚本自己加,但这种旧写法仍要照常放行——不能因为一次接口
    改进就把老用法判成错误。真正的错位('L1' 之类)必须继续拦。
    """
    r = placeholder.substitute("SELECT 1 FROM t WHERE lv = ?", ["'2'"], ["smallint"])
    coltypes.validate_binds(r.substitutions, ["smallint"])   # 不抛即通过

    bad = placeholder.substitute("SELECT 1 FROM t WHERE lv = ?", ["L1"], ["smallint"])
    try:
        coltypes.validate_binds(bad.substitutions, ["smallint"])
    except ValueError as exc:
        assert "错位" in str(exc)
    else:
        raise AssertionError("'L1' 塞进 smallint 列必须被拦下")
