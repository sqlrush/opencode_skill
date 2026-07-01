# opencode_skill

OpenGauss / GaussDB 数据库 DBA 技能集,由 Go 版 `gdaa` 工具用 Python 重写。

目录结构(按既定重构方案):

```
common/            # 唯一共享层:连接 / 凭据 / 只读驱动
skills/<name>/
  SKILL.md         # 面向模型的操作手册(调用本 skill 的 python 脚本)
  references/      # 方法论 + GaussDB 知识库
  scripts/         # 本 skill 自己的逻辑(入口 + vendored 探针)
tests/             # pytest(连接不存在时 live 测试自动跳过)
```

设计原则:`common/` 是唯一共享包(只负责连库 + 解密凭据,复用 gdaa 的 `~/.gdaa` 存储、原样不动)。其余一切——探针、报告渲染、分析——都放在各 skill 的 `scripts/` 里。

## 安装

```bash
python3 -m pip install -r requirements.txt
```

## 装进 OpenCode

```bash
./install-opencode.sh          # → ~/.config/opencode/skills/
```

完整步骤(前置依赖、建连接、验证、排障)见 [docs/INSTALL-opencode.md](docs/INSTALL-opencode.md);**成套交付/上手文档**(安装部署、代码结构、编码规范、参与开发)见 [docs/delivery/](docs/delivery/README.md)。

连接配置放在一个本地目录里,位置由环境变量 `GSDB_HOME` 指定(任意名/路径,默认 `~/.gdaa`,旧 `GDAA_HOME` 仍兼容):`$GSDB_HOME/config.yaml` + `$GSDB_HOME/credentials/`(和 Go 版 `gdaa` 共用同一份存储)。`GSDB_PASSWORD`(旧 `GDAA_PASSWORD` 仍兼容)可临时覆盖存储的密码(一次性 / CI 用)。支持 gsql（默认）与 pg8000 双后端，连接级自动兜底；详见 [docs/connection-drivers.md](docs/connection-drivers.md)。

## 范围(当前)

已与 Go 版 `gdaa` 技能集**全量对齐** —— 3 个族、10 个 skill。

SQL 优化族:

- `skills/slowsql`  —— 按平均耗时阈值找慢 SQL
- `skills/topsql`   —— 按资源消耗排名最重的 SQL
- `skills/sqlfetch` —— 把 unique_sql_id 还原成完整 SQL 文本
- `skills/explain`  —— 执行计划 + 确定性风险发现
- `skills/sqltune`  —— SQL 深度调优(hypopg + 成本 + 等价性验证)

存储过程族:

- `skills/proctune` —— 存储过程分析 + 只读游标 SELECT 调优
- `skills/procinfo` —— 存储过程只读结构诊断(交棒 proctune)
- `skills/topproc`  —— 按资源消耗排名最重的存储过程(pg_stat_user_functions)

诊断族:

- `skills/health`   —— 12 维只读健康检查 + 确定性发现
- `skills/wdr`      —— WDR 快照 delta 解读(7 维,snaps/collect/render)

每个 skill 的输出都对照 Go 版 `gdaa` 二进制做了交叉验证。health 与 wdr 做了逐字节 diff:维度、表头、阈值串、确定性发现完全一致(wdr 因快照不可变,证据数值完全相同;`wdr render` 除脚注里有意去掉「gdaa」一词外完全一致)。slowsql/topsql/sqlfetch 仅在末尾的 "Next:" 提示行不同——指向本地 Python 脚本而非 `gdaa`。

驱动:gsql（默认）+ pg8000 双后端，连接级自动兜底（gsql 不可用时自动降为 pg8000）。pg8000 已对 openGauss-lite 5.0.3 的 `opengauss` 与 `gaussdb` 两种连接类型实证；gsql parity 待在 Linux 主机验证，见 [docs/connection-drivers.md](docs/connection-drivers.md)。
