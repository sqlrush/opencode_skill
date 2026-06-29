"""`wdr snaps` — list WDR snapshots + preflight enable_wdr_snapshot.

Port of internal/probe/wdr/snaps.go. Returns an ERROR (not a degraded report)
when WDR is off or fewer than 2 snapshots exist — the toolkit never creates
snapshots; it tells the user to enable WDR / create one themselves.
"""
from __future__ import annotations

import render
from util import i64

import common  # resolved on sys.path by the entry script


def snaps(db, limit: int) -> str:
    if limit <= 0:
        limit = 20
    try:
        enabled = db.scalar("SHOW enable_wdr_snapshot")
    except common.DBError as exc:
        raise common.DBError(f"读取 enable_wdr_snapshot 失败：{exc}")
    if str(enabled or "").strip().lower() != "on":
        raise common.DBError(
            "WDR 未开启（enable_wdr_snapshot=off）。请由 DBA 执行 "
            "`ALTER SYSTEM SET enable_wdr_snapshot=on`（需 reload/重启）并等待自动快照，"
            "或自行 `SELECT create_wdr_snapshot();`。本工具只读、不代为开启或创建。")

    q = f"""SELECT snapshot_id,
       to_char(start_ts,'YYYY-MM-DD HH24:MI') AS start_ts,
       to_char(end_ts,'YYYY-MM-DD HH24:MI')   AS end_ts,
       round(EXTRACT(EPOCH FROM (end_ts-start_ts))/60)::bigint AS dur_min
FROM snapshot.snapshot ORDER BY snapshot_id DESC LIMIT {int(limit)}"""
    try:
        _, rows = db.query(q)
    except common.DBError as exc:
        raise common.DBError(f"查询 snapshot.snapshot 失败：{exc}")

    snaps_list = [(int(r[0]), r[1], r[2], int(r[3] or 0)) for r in rows]
    if len(snaps_list) < 2:
        raise common.DBError(
            f"可用快照不足（{len(snaps_list)} 个）：WDR 报告至少需要两个快照围出窗口。"
            "请等待下一个自动快照间隔，或由 DBA 自行 `SELECT create_wdr_snapshot();`。")

    tbl = [[i64(s[0]), s[1], s[2], i64(s[3])] for s in snaps_list]
    out = f"# WDR Snapshots（enable_wdr_snapshot={enabled}）\n\n"
    out += render.table(["snapshot_id", "start_ts", "end_ts", "dur_min"], tbl)
    # snaps_list[0] is newest (DESC); suggest the two most-recent consecutive.
    out += f"\n建议窗口：`--begin {snaps_list[1][0]} --end {snaps_list[0][0]}`（最近两个快照）。\n"
    return out
