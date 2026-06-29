# 在 OpenCode 上装载这些 skill —— 操作手册

本手册说明如何把 `opencode_skill` 的 6 个技能（slowsql / topsql / sqlfetch /
explain / sqltune / proctune）装到 [OpenCode](https://opencode.ai) 并跑通。

OpenCode 原生支持 Agent Skills：它会从下列目录发现 `SKILL.md`——

- **全局**：`~/.config/opencode/skills/<name>/SKILL.md`
- **项目级**：`<repo>/.opencode/skills/<name>/SKILL.md`（也认 `.claude/skills/`、`.agents/skills/`）

> 注意：OpenCode 没有 `{baseDir}` 占位符。本仓库的 `SKILL.md` 用 `{baseDir}` 指代自身目录，
> 安装脚本会在拷贝时把它替换成真实绝对路径，所以**必须用安装脚本（或手动替换）**，不能直接软链。

---

## 0. 前置条件

| 依赖 | 说明 |
|---|---|
| Python ≥ 3.9 | 运行各 skill 的脚本 |
| `pg8000` / `cryptography` / `PyYAML` | 纯 Python，无需编译 |
| OpenGauss/GaussDB 连接（`~/.gdaa`） | 与 gdaa 共用的连接+凭据存储 |

安装 Python 依赖：

```bash
python3 -m pip install -r requirements.txt
# 或： python3 -m pip install pg8000 cryptography PyYAML
```

---

## 1. 准备数据库连接（`~/.gdaa`）

所有 skill 通过 `-c <name>` 选连接，连接信息复用 `~/.gdaa`：

- `~/.gdaa/config.yaml` —— 连接元数据（host/port/db/user/type，**无密码**）
- `~/.gdaa/credentials/<name>.enc` —— AES-256-GCM 加密的口令
- `~/.gdaa/key` —— 32 字节本机密钥

**情况 A：已有 `~/.gdaa` 连接** —— 直接复用，跳到第 2 步。查看现有连接：

```bash
cat ~/.gdaa/config.yaml      # 看 name 列表（不含密码）
```

**情况 B：手工新建** —— 写 `config.yaml` + 用本仓库的 `common` 加密口令：

```bash
mkdir -p ~/.gdaa && chmod 700 ~/.gdaa
cat >> ~/.gdaa/config.yaml <<'YAML'
connections:
  - name: og-prod
    type: opengauss        # opengauss | gaussdb
    host: 10.0.0.1
    port: 5432
    database: appdb
    user: tuner
YAML
chmod 600 ~/.gdaa/config.yaml

# 加密口令（会在 ~/.gdaa/credentials/og-prod.enc 落盘，与 gdaa 字节兼容）
python3 -c "import sys; sys.path.insert(0,'.'); from common import save_secret; save_secret('og-prod', input('password: '))"
```

> 临时/CI 也可用环境变量 `GDAA_PASSWORD` 覆盖存储口令；用 `GDAA_HOME` 覆盖 `~/.gdaa` 根目录。

验证连接可用：

```bash
python3 skills/sqltune/scripts/sqltune.py -c og-prod --sql-stdin <<'SQL'
SELECT 1
SQL
```

---

## 2. 安装 skill 到 OpenCode

### 方式一：安装脚本（推荐）

```bash
# 全局安装到 ~/.config/opencode/skills/
./install-opencode.sh

# 只装部分
./install-opencode.sh sqltune slowsql

# 装到某个项目（<repo>/.opencode/skills/）
./install-opencode.sh --project /path/to/your/repo

# 预演，不写盘
./install-opencode.sh --dry-run
```

脚本做三件事：① 检查 Python 依赖；② 把每个 skill 目录拷到目标；③ 连同共享层
`common/` 一起拷过去，并把 `SKILL.md` 里的 `{baseDir}` 替换成真实绝对路径。

安装后目录结构（全局示例）：

```
~/.config/opencode/skills/
├── common/                  # 共享连接层（无 SKILL.md，OpenCode 自动忽略）
├── sqltune/  SKILL.md + scripts/ + references/
├── proctune/ SKILL.md + scripts/ + references/
├── slowsql/  topsql/  sqlfetch/  explain/  ...
```

### 方式二：手动安装

```bash
DEST=~/.config/opencode/skills
mkdir -p "$DEST"
cp -R common "$DEST/common"
cp -R skills/sqltune "$DEST/sqltune"          # 对每个要装的 skill 重复
# 把 SKILL.md 里的 {baseDir} 换成该 skill 的绝对路径：
python3 - "$DEST/sqltune" <<'PY'
import pathlib,sys; b=pathlib.Path(sys.argv[1]); f=b/"SKILL.md"; f.write_text(f.read_text().replace("{baseDir}",str(b)))
PY
```

---

## 3. 验证 OpenCode 已发现 skill

启动 OpenCode，技能会通过原生 `skill` 工具暴露。模型可调用
`skill({ name: "sqltune" })` 等。让 agent「列出可用 skill」即可确认 6 个都在。

命令行快速自检（不经 OpenCode，直接验证脚本可独立运行）：

```bash
python3 ~/.config/opencode/skills/sqltune/scripts/sqltune.py -h
python3 ~/.config/opencode/skills/slowsql/scripts/slowsql.py -c og-prod --threshold 1000
```

---

## 4. 各 skill 用途与触发

| skill | 何时用 | 入口脚本 |
|---|---|---|
| **slowsql** | 「哪些 SQL 慢」 | `slowsql.py -c <conn> --threshold <ms>` |
| **topsql** | 「最耗资源的 SQL 排名」 | `topsql.py -c <conn> --by time\|avg\|calls\|reads\|rows` |
| **sqlfetch** | 「把 sql_id 还原成 SQL 文本」 | `sqlfetch.py -c <conn> <unique_sql_id>` |
| **explain** | 「看这条 SQL 的执行计划+风险」 | `explain.py -c <conn> --sql-stdin` |
| **sqltune** | 「深度调优这条 SQL」（hypopg 验证索引、verify 验改写） | `sqltune.py -c <conn> <id\|--sql-stdin>`、`verify.py ...` |
| **proctune** | 「调优存储过程」（结构分析 + 游标 SELECT 调优） | `proctune.py collect\|tune-cursor -c <conn> <schema.proc>` |

用户用自然语言提问（「库里哪些 SQL 慢」「帮我调这条 SQL」「看下这个存储过程」），
OpenCode 会按 `SKILL.md` 的 description 选中对应 skill 并按其工作流执行。

---

## 5. 安全模型

- 脚本以**只读会话**连库（写/DDL 被会话级 `READ ONLY` 拦截；存储过程不被执行）。
- 凭据由脚本就地解密，**不会**在对话中回显；`SKILL.md` 明确禁止 agent 自行连库或读取
  `~/.gdaa/credentials/`——取数只走这些脚本。
- `sqltune`/`proctune` 的索引与改写建议都经 hypopg + cost（+ 等价性）硬验证后才呈现。

---

## 6. 故障排查

| 现象 | 处理 |
|---|---|
| `ModuleNotFoundError: No module named 'pg8000'` | `python3 -m pip install -r requirements.txt` |
| `ModuleNotFoundError: No module named 'common'` | 没用安装脚本（漏拷 `common/`）。重跑 `install-opencode.sh` |
| SKILL.md 里出现字面量 `{baseDir}` | 没做替换。用安装脚本，或手动跑第 2 步的替换片段 |
| `no connection named 'xxx'` | `~/.gdaa/config.yaml` 里没有该 name；见第 1 步 |
| `decrypt credential ...` 失败 | `~/.gdaa/key` 与 `.enc` 不匹配（换机要一起带过来），或用 `GDAA_PASSWORD` |
| `connect ... Connection reset` | 目标可能是只读备库，连主库；或检查 host/port/防火墙 |
| 慢SQL/topsql 为空 | 实例未开 `enable_stmt_track`，或降低 `--threshold` |

---

## 7. 升级 / 卸载

```bash
# 升级：仓库 git pull 后重跑安装脚本（覆盖式）
./install-opencode.sh

# 卸载：删掉对应目录
rm -rf ~/.config/opencode/skills/{sqltune,proctune,slowsql,topsql,sqlfetch,explain,common}
```
