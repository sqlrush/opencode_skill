"""Catalog-driven placeholder typing for sqltune.

替换占位符前用**一条**无状态 catalog 查询取出比较列的真实类型，让合成值
首发就类型正确（默认 gsql 后端每语句一个子进程、无跨语句会话，所以不能走
PREPARE/pg_prepared_statements 探测，只能用单条查询）。

任何环节失败都降级回纯文本启发式并在 stderr 说一声——本模块绝不让
sqltune 因它而失败。
"""
from __future__ import annotations

import re
import sys

import evidence
import placeholder

_NUMERIC_LITERAL_RE = re.compile(r"^[+-]?\d+(\.\d+)?$")
# openGauss/GaussDB: 老式 "for integer" 与新式 "for type numeric" 两种措辞都有。
_TYPE_ERR_RE = re.compile(r'invalid input syntax for (?:type )?[\w ]+:\s*"([^"]*)"')


def _quoted_in(names: list[str]) -> str:
    quoted = ["'" + n.replace("'", "''") + "'" for n in names]
    return "(" + ",".join(quoted) + ")"


def infer_types(db, sql_text: str) -> list:
    """Per-placeholder column type (or None), aligned with substitute() order.

    列名取自各占位符的左上下文；同名列在多张表里类型冲突时保守放弃
    （返回 None，交回启发式）。查询失败同样全量降级。
    """
    contexts = placeholder.placeholder_contexts(sql_text)
    if not contexts:
        return []
    columns = [placeholder.comparison_column(c) for c in contexts]
    wanted = sorted({c for c in columns if c})
    tables = evidence.extract_tables(sql_text)
    if not wanted or not tables:
        return [None] * len(contexts)

    try:
        mapping = _lookup_column_types(db, tables, wanted)
    except Exception as exc:  # 探测是增强,不是硬依赖——失败就退回启发式
        print(f"warning: 列类型探测失败,占位符替换退回启发式: {exc}",
              file=sys.stderr)
        return [None] * len(contexts)
    return [mapping.get(c) if c else None for c in columns]


def _lookup_column_types(db, tables: list[str], columns: list[str]) -> dict:
    q = f"""
SELECT a.attname, format_type(a.atttypid, NULL)
FROM pg_attribute a
JOIN pg_class c ON c.oid = a.attrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relname IN {_quoted_in(tables)}
  AND a.attname IN {_quoted_in(columns)}
  AND a.attnum > 0 AND NOT a.attisdropped
  AND c.relkind IN ('r','p','v','m')
  AND n.nspname NOT IN ('pg_catalog','information_schema')"""
    _, rows = db.query(q)
    seen: dict = {}
    for col, typ in rows:
        seen.setdefault(col, set()).add(typ)
    # 只保留类型无歧义的列;跨表冲突宁可不猜。
    return {col: next(iter(types)) for col, types in seen.items() if len(types) == 1}


def _unquote(value: str) -> str:
    """剥掉最外层 SQL 单引号,让 `--bind "'2'"` 这种老写法照常过数值校验。

    2026-08-14 之前脚本不会自己加引号,现场模型学到的唯一可行写法就是把引号
    写进值里；接口改进不该把老用法判成错位。`'L1'` 剥完仍不是数字,照拦。
    """
    v = value.strip()
    if len(v) >= 2 and v.startswith("'") and v.endswith("'"):
        return v[1:-1].replace("''", "'")
    return v


def validate_binds(substitutions, types: list) -> None:
    """--bind 的值与推断类型明显不符时执行前拦截（治 bind 顺序错位）。

    只校验整数/数值族——字符串塞进整数列必炸且报错难定位；日期等格式
    多样，不硬卡。
    """
    problems = []
    for i, s in enumerate(substitutions):
        if s.source != "bind":
            continue
        t = types[i] if i < len(types) else None
        if t and placeholder.is_numeric_type(t) \
                and not _NUMERIC_LITERAL_RE.match(_unquote(s.value)):
            problems.append(
                f"  bind #{i + 1} = {s.value!r} 但该占位符对应 {t} 列"
                f"（上下文: …{s.context[-50:]}）")
    if problems:
        raise ValueError(
            "bind 值与占位符类型不符——检查 --bind 顺序是否错位:\n"
            + "\n".join(problems))


def enrich_type_error(message: str, substitutions):
    """EXPLAIN 报类型转换错时,点名坏值出自哪个占位符;不相关则返回 None。"""
    m = _TYPE_ERR_RE.search(message)
    if not m:
        return None
    bad = m.group(1)
    hits = [(i, s) for i, s in enumerate(substitutions)
            if s.value == bad or s.value.strip("'") == bad]
    if not hits:
        return None

    lines = [f"  #{i + 1} {s.token} -> {s.value} ({s.source})"
             f"  上下文: …{s.context[-50:]}" for i, s in hits]
    if all(s.source == "bind" for _, s in hits):
        hint = ("提示: 该值来自 --bind,疑似 bind 顺序错位——"
                "对照下列位置检查传值顺序:")
    else:
        hint = ("提示: 该值是 sqltune 自动填的合成值,列类型猜错了。"
                "若用户能给出真实值,可用 --bind 按占位符顺序传入绕过猜测"
                "(没有就不要臆造——编出来的值会改变选择性,索引/改写的 cost "
                "倍数会跟着失真)。可能位置:")
    return message + "\n" + hint + "\n" + "\n".join(lines)
