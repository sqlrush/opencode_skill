"""gsql 协议层（纯函数，无 I/O）：参数注入、语句判别、结果与错误解析。"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Sequence

from .base import DBError


def _inline_or_var(val: Any, idx: int, vars_: dict) -> str:
    """决定第 idx 个参数的注入形式，必要时写入 vars_。"""
    if val is None:
        return "NULL"
    if isinstance(val, bool):  # 必须在 int 之前（bool 是 int 子类）
        return "TRUE" if val else "FALSE"
    if isinstance(val, (int, float, Decimal)):
        name = f"p{idx}"
        vars_[name] = str(val)
        return f":{name}"          # 裸值（数值上下文安全，值我方可控）
    if isinstance(val, str):
        name = f"p{idx}"
        vars_[name] = val
        return f":'{name}'"        # gsql 自行安全转义为带引号字面量
    raise DBError(f"unsupported gsql param type {type(val).__name__}")


def rewrite_params(sql: str, params: Sequence[Any]) -> tuple[str, dict]:
    """把 %s 占位符改写为 gsql 变量引用，返回 (新SQL, 变量映射)。"""
    params = list(params or ())
    out: list[str] = []
    vars_: dict = {}
    idx = 0
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch == "%":
            nxt = sql[i + 1] if i + 1 < n else ""
            if nxt == "%":
                out.append("%"); i += 2; continue
            if nxt == "s":
                if idx >= len(params):
                    raise DBError("more %s placeholders than params")
                out.append(_inline_or_var(params[idx], idx, vars_))
                idx += 1; i += 2; continue
            out.append("%"); i += 1; continue
        out.append(ch); i += 1
    if idx != len(params):
        raise DBError(
            f"placeholder/param count mismatch: {idx} placeholders, {len(params)} params"
        )
    return "".join(out), vars_
