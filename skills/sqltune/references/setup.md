# 安装与连接(OpenGauss/GaussDB)

本工具以 Python 脚本运行 —— **无需 `gdaa` 二进制**。

## 安装

```bash
git clone https://github.com/sqlrush/opencode_skill
cd opencode_skill && python3 -m pip install -r requirements.txt   # pg8000, cryptography, PyYAML
python3 skills/sqltune/scripts/sqltune.py -h
```

装进 OpenCode:见 `docs/INSTALL-opencode.md`。

## 添加连接

连接存在 `~/.gdaa`(共享、字节兼容的存储),用 `-c <name>` 选择。建连见 `docs/INSTALL-opencode.md` §1:

- 复用已有连接:`cat ~/.gdaa/config.yaml`(只看名字,无密码)
- 手工创建:写 `~/.gdaa/config.yaml`,再用仓库的 `common.save_secret` 加密密码(写入 `~/.gdaa/credentials/<name>.enc`,AES-256-GCM)
- CI / 一次性:设 `GDAA_PASSWORD`(用 `GDAA_HOME` 可换存储位置)

GaussDB:连接项里设 `type: gaussdb`。

验证连通(只读):

```bash
python3 skills/sqltune/scripts/sqltune.py -c og-prod --sql-stdin <<'SQL'
SELECT 1
SQL
```

## 监控账号最小权限

```sql
-- 用管理员执行;OG:monadmin 即可覆盖 dbe_perf
ALTER USER tuner MONADMIN;
-- 或显式授权:
GRANT USAGE ON SCHEMA dbe_perf TO tuner;
GRANT SELECT ON ALL TABLES IN SCHEMA dbe_perf TO tuner;
```

## 语句跟踪所需 GUC

```sql
ALTER SYSTEM SET enable_stmt_track = on;        -- statement_history 行
ALTER SYSTEM SET track_stmt_parameter = on;     -- 字面 SQL(否则归一化)
```

## 症状 → 处理

| 症状 | 处理 |
|---|---|
| 退出码 2 / connection refused | 查 host/port/防火墙;用脚本跑 `SELECT 1` 验证 |
| 退出码 2 / password authentication | 重建凭据(见「添加连接」),或设 `GDAA_PASSWORD` |
| 退出码 3 / permission denied for dbe_perf | 授 monadmin(上面 SQL) |
| sqlfetch 查不到 | 开 `enable_stmt_track`,等有流量后重试 |
| sqlfetch 返回归一化 SQL | 开 `track_stmt_parameter`;或用 `--bind` 传真实值 |
| 退出码 4 / syntax or object error | 检查替换后的占位符值与 SQL 里的对象名 |
| 退出码 5 / timeout | 调大 `--timeout`,或错峰调优 |
