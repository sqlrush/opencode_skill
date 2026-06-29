# proctune / procinfo 安装与排错

## 一、安装 gdaa

`proctune` / `procinfo` 依赖 `gdaa` 二进制在 PATH 上。

- 预检 `gdaa --version` 失败说明 PATH 上没有 gdaa。
- 安装：从源码 `make install`（装到 `~/.local/bin/gdaa`），或下载 release 二进制放进任意 PATH 目录（如 `/usr/local/bin`）。
- 放哪个目录不限，只要**运行宿主（OpenClaw 等）的进程能在 PATH 上解析到 `gdaa`**。

## 二、配置连接

```bash
gdaa connect add <name> --type opengauss|gaussdb --host <h> --port <p> -U <user> -d <db>
gdaa connect test <name>
gdaa connect list
```

密码以 AES-256-GCM 加密存于 `~/.gdaa/credentials/<name>.enc`；非交互场景用环境变量 `GDAA_PASSWORD`。`proctune` 全程只用 `-c <name>`，不构造含密码的连接串。

## 三、开启运行时归因（可选但推荐）

`## Runtime Attribution` 需要实例采集**嵌套语句**统计。未开启时 `proctune` 自动降级为纯静态分析（命令不失败），但拿不到「哪条 embedded SQL 真正耗时」的真实排序。

- 把 `track_stmt_stat_level` 调到捕获嵌套层级（具体取值见实例文档），重采 `gdaa proc collect` 即可获得真实 calls/avg/total。
- 这是只读统计，不改业务行为。

## 四、症状对照表

| 症状 | 可能原因 | 处理 |
|---|---|---|
| `gdaa --version` 失败 | gdaa 不在 PATH | 见「一、安装 gdaa」 |
| `unknown connection` | 连接名未配置 | `gdaa connect add ...` 后 `gdaa connect list` 核对 |
| 连接失败（退出码 2） | host/port/凭据错或库不可达 | `gdaa connect test <name>` 排查；确认网络与账号 |
| 权限不足（退出码 3） | 账号缺 `pg_get_functiondef` / `dbe_perf` / `gs_index_advise` / hypopg 权限 | 用有相应读取/调优权限的账号 |
| `## Runtime Attribution` 为空或标「不可用」 | 未开 `track_stmt_stat_level` 捕获嵌套语句 | 见「三、开启运行时归因」；不开则按纯静态分析进行 |
| `## Verified Index Candidates` 显示无候选 | gs_index_advise 未发现，或合成值下无收益 | 用 `--bind <var=value>` 传真实值重验；或仅作未验证思路呈现 |
| 索引验证报「不可用」 | 实例未启用 hypopg / `enable_hypo_index` | 确认 OpenGauss 版本支持并启用；不支持则索引验证降级，命令仍成功 |
| 大量游标进 `## Skipped Cursors` | FOR UPDATE / 动态 / 参数化 / 包内 / REF CURSOR | 属预期：v1 仅自动改只读基础游标，其余转建议 |
| 语句超时（退出码 5） | 采证据/验证超过 `--timeout` | 增大 `--timeout`，或检查目标对象规模 |

## 五、与 sqltune 的关系

`proctune` 对游标 SELECT 的优化复用 sqltune 同一套机器（`Collect` / `VerifyIndexes` / `gdaa verify`）。若单独一条 SQL 的调优诉求，直接用 `/sqltune` 更直接；`proctune` 面向「过程内的游标 + 过程结构」整体分析。
