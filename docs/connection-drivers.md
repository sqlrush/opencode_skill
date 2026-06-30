# 连接驱动（connection-drivers）

`common/` 连接层支持两种后端驱动，通过 `~/.gdaa/config.yaml` 的 `driver` 字段配置，也可通过环境变量覆盖。

---

## `driver` 字段

```yaml
# ~/.gdaa/config.yaml
connections:
  - name: og-pri
    type: opengauss
    host: 127.0.0.1
    port: 5435
    database: postgres
    user: gaussdb
    driver: gsql        # gsql（默认）| pg8000
```

| 值 | 说明 |
|---|---|
| `gsql`（默认） | 本机 `gsql` 命令行客户端，每条查询起一个子进程，通过 `-c` 执行 |
| `pg8000` | 纯 Python 驱动，TCP 直连，无需安装 gsql 二进制 |

旧版 config.yaml 不含 `driver` 字段时，默认视为 `gsql`（向后兼容）。

---

## 环境变量

| 变量 | 说明 |
|---|---|
| `GDAA_GSQL` | 覆盖 gsql 二进制路径（默认在 `PATH` 查找 `gsql`）。示例：`GDAA_GSQL=/usr/local/bin/gsql` |
| `PGSSLMODE` | 覆盖 SSL 模式（若 config.yaml 里也有 `sslmode` 字段，配置文件优先，未设置时 `PGSSLMODE` 生效）；gsql 后端通过 `env["PGSSLMODE"]` 传入子进程 |
| `GDAA_HOME` | 覆盖 `~/.gdaa` 根目录路径 |
| `GDAA_PASSWORD` | 临时覆盖存储的密码（一次性使用 / CI 用） |

---

## 连接级自动兜底（fallback）

`Database.open()` 门面实现了**连接级自动兜底**：

1. 优先尝试 `conn.driver`（config.yaml 里配置的驱动）。
2. 若该驱动抛出 `DBError`（二进制缺失、连接拒绝、认证失败），自动尝试另一个驱动。
3. 两个驱动都失败时，合并两个错误消息，抛出 `DBError`。

```
gsql 不可用（DBError）
    ↓ 自动兜底
pg8000 连接成功
    ↓
返回 Database（透明，调用方无感知）
```

**示例**：在 macOS 开发机（无 `gsql` 二进制）上，配置了 `driver: gsql` 的连接会自动降为 pg8000，所有 skill 照常工作，无需改 config.yaml。

如果你希望**跳过 gsql 尝试**（节省延迟 / 避免日志噪音），在 config.yaml 中显式设置 `driver: pg8000`。

---

## json_agg 类型保真与已知差异

> **待验证（理论分析，未经 Linux + gsql 实证）**：本节基于两后端的代码路径推演，
> 尚未在具备 gsql 二进制的真库上做过 parity diff，请勿当作已确认结论。

**关键洞察**：gsql 后端把可包裹的 SELECT 包成
`SELECT json_agg(row_to_json(_t)) FROM (...) _t`，再用
`json.loads(text, parse_float=Decimal)` 解析。这意味着——对 **JSON 原生标量类型**，
gsql 解析出的 Python 值与 pg8000 返回的**完全一致**：

| 数据库类型 | JSON 中间形态 | gsql 后端 Python 值 | pg8000 后端 Python 值 | 是否一致 |
|---|---|---|---|---|
| 整数（`int`/`bigint`） | JSON number（整数） | `int` | `int` | ✅ 一致 |
| 数值/浮点（`numeric`/`float`/`double`） | JSON number（小数） | `Decimal`（`parse_float=Decimal`） | `Decimal` | ✅ 一致 |
| 布尔（`bool`） | JSON `true`/`false` | `bool` | `bool` | ✅ 一致 |
| `NULL` | JSON `null` | `None` | `None` | ✅ 一致 |

**真正的残留差异**只出现在 **非 JSON 原生类型**——这些类型在 `row_to_json` 里被
渲染成 ISO/文本字符串，于是经 gsql 解析后是 Python `str`，而 pg8000 返回的是带类型的对象：

| 数据库类型 | gsql 后端 Python 值 | pg8000 后端 Python 值 |
|---|---|---|
| 时间戳（`timestamp`/`timestamptz`） | `str`（ISO 串，如 `"2024-01-01T12:00:00"`） | `datetime.datetime` 对象 |
| 日期（`date`） | `str`（如 `"2024-01-01"`） | `datetime.date` 对象 |
| 时间（`time`） | `str` | `datetime.time` 对象 |
| 时间间隔（`interval`） | `str` | 类型化对象 |
| 数组（`array`） | `list`（JSON 数组，元素再按上表规则） | 类型化 `list` |
| 字节串（`bytea`） | `str`（文本表示） | `bytes` 对象 |

各 skill 的探针 SQL 均设计为对这些差异**不敏感**（比较前统一转为字符串，或只使用数值
大小而不依赖具体类型）。若新增探针涉及时间戳/日期/数组/bytea 等非 JSON 原生类型，
建议在 SQL 中显式 `CAST(... AS text)` 以消除差异。

---

## 主机要求（HOST REQUIREMENT）

**gsql 是 Linux 原生客户端，无 macOS 原生版本。**

| 场景 | 说明 |
|---|---|
| Linux 生产主机（含 gsql） | `driver: gsql` 完全可用；若不存在则兜底 pg8000 |
| macOS 开发机 | gsql 二进制不存在，`shutil.which("gsql")` 返回空，自动兜底到 pg8000；或显式配置 `driver: pg8000` 跳过尝试 |
| CI/容器（无 gsql） | 同 macOS，兜底 pg8000 |

> 若要固定只用 pg8000（推荐 macOS 开发 / CI 环境）：在 config.yaml 对应连接中设置 `driver: pg8000`，消除兜底路径的日志干扰。

---

## 排错

### gsql 二进制缺失

```
DBError: gsql binary not found (set GDAA_GSQL or add gsql to PATH)
```

**原因**：`PATH` 中找不到 `gsql`，且未设置 `GDAA_GSQL`。

**解决**：
- macOS / CI：改用 pg8000（`driver: pg8000` 或等待自动兜底）。
- Linux：安装 openGauss 客户端包，确保 `gsql` 在 `PATH`，或 `export GDAA_GSQL=/path/to/gsql`。

### 连接被拒（Connection refused）

```
DBError: pg8000: ... Connection refused
DBError: gsql: ... could not connect to server: Connection refused
```

**原因**：数据库未启动，或 host/port 配置错误。

**检查**：
```bash
# 确认端口可达
nc -zv 127.0.0.1 5435
# 查 config.yaml
cat ~/.gdaa/config.yaml
```

### 认证失败

```
DBError: password authentication failed for user "gaussdb"
```

**解决**：用 `gdaa connect add <name> ...` 重新保存凭据，或 `export GDAA_PASSWORD=...` 临时覆盖。

---

## 待验证 — gsql vs pg8000 真库 parity diff

在配备 gsql 二进制的 **Linux 主机**上，可执行如下 parity 验证：

```bash
# gsql 路径
python3 skills/health/scripts/health.py --conn og-pri > /tmp/health.gsql.txt

# 切换 driver
# 临时改 config.yaml driver: pg8000，或用一个不存在的路径强制 gsql 走 "binary not found" 分支兜底到 pg8000：
GDAA_GSQL=/nonexistent/path python3 skills/health/scripts/health.py --conn og-pri > /tmp/health.pg.txt

diff /tmp/health.gsql.txt /tmp/health.pg.txt || true
```

**当前状态**：本机为 macOS，gsql 不可用，parity diff **延迟至具备 gsql 的 Linux 主机后再执行**。预期差异仅限上文「已知差异」表中**非 JSON 原生类型**的差异（时间戳/日期/数组/bytea 的 `str` vs 类型化对象）；int/Decimal/bool/NULL 在两后端一致。各 skill 已设计为对其不敏感，输出内容应完全一致。
