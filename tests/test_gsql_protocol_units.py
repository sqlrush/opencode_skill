import sys, pathlib
from decimal import Decimal
_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402
from common.backends.base import DBError  # noqa: E402
from common.backends import gsql_protocol as gp  # noqa: E402

def test_string_param_uses_quoted_var():
    sql, vars_ = gp.rewrite_params("WHERE n = %s", ["public"])
    assert sql == "WHERE n = :'p0'"
    assert vars_ == {"p0": "public"}

def test_numeric_param_uses_raw_var():
    sql, vars_ = gp.rewrite_params("LIMIT %s", [100])
    assert sql == "LIMIT :p0"
    assert vars_ == {"p0": "100"}

def test_decimal_param_preserved_as_text():
    sql, vars_ = gp.rewrite_params("x > %s", [Decimal("1.5")])
    assert sql == "x > :p0"
    assert vars_ == {"p0": "1.5"}

def test_bool_and_none_inlined():
    sql, vars_ = gp.rewrite_params("a=%s AND b=%s", [True, None])
    assert sql == "a=TRUE AND b=NULL"
    assert vars_ == {}

def test_mixed_string_and_numeric():
    sql, vars_ = gp.rewrite_params(
        "p=%s AND (%s='' OR n=%s) LIMIT %s", ["proc", "", "public", 1]
    )
    assert sql == "p=:'p0' AND (:'p1'='' OR n=:'p2') LIMIT :p3"
    assert vars_ == {"p0": "proc", "p1": "", "p2": "public", "p3": "1"}

def test_percent_literal_escaped():
    sql, vars_ = gp.rewrite_params("x LIKE 'a%%b'", [])
    assert sql == "x LIKE 'a%b'"
    assert vars_ == {}

def test_count_mismatch_raises():
    with pytest.raises(DBError):
        gp.rewrite_params("a=%s AND b=%s", ["only-one"])

def test_unsupported_type_raises():
    with pytest.raises(DBError):
        gp.rewrite_params("x=%s", [object()])

def test_is_wrappable_true_for_select():
    assert gp.is_wrappable_select("SELECT 1")
    assert gp.is_wrappable_select("  select * from t")
    assert gp.is_wrappable_select("WITH x AS (SELECT 1) SELECT * FROM x")

def test_is_wrappable_strips_leading_comment():
    assert gp.is_wrappable_select("-- c\nSELECT 1")
    assert gp.is_wrappable_select("/* c */ SELECT 1")

def test_is_wrappable_false_for_non_select():
    assert not gp.is_wrappable_select("SHOW enable_wdr_snapshot")
    assert not gp.is_wrappable_select("EXPLAIN ANALYZE SELECT 1")
    assert not gp.is_wrappable_select("SET statement_timeout = 1000")

def test_wrap_select_json_strips_trailing_semicolon():
    assert (
        gp.wrap_select_json("SELECT a FROM t;")
        == "SELECT json_agg(row_to_json(_t)) FROM (SELECT a FROM t) _t"
    )
