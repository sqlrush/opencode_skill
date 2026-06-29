---
name: health
version: 2.0.0
description: "OpenGauss/GaussDB 数据库健康检查：脚本只读采集 12 维证据（总览/等待事件/慢 SQL/长事务与空闲事务/死元组膨胀/轻量锁/事务锁与阻塞链/连接与活跃会话/checkpoint·归档/主备复制/对象索引/事务并发）并按阈值产确定性发现；LLM 判断后做证据锚定校验，出诚实可落地的健康检查报告。用户问“库健康吗 / 为什么卡 / 有没有阻塞·长事务·膨胀·复制延迟·无用索引”等即用。"
allowed-tools: ["exec", "read"]
compatibility: opencode
metadata:
  runtime: python3
  emoji: "🏥"
  family: diagnostics
---

# Health Check（OpenGauss/GaussDB 数据库健康检查）

一次性、只读、可信的数据库健康检查。**确定性归脚本（采集 + 阈值发现），判断归你（LLM），但你的判断必须对脚本的 `## Deterministic Findings` 做证据锚定校验。** 报告抬头用确定性状态带，不编造单一分数。

本技能用 Python 脚本（`{baseDir}/scripts/health.py`）取数：只读、一次性跑全部 12 个采集器。连接/凭据复用 `~/.gdaa`。

## 工作流

1. **预检。** 运行 `python3 {baseDir}/scripts/health.py -h`。若报缺少依赖，按 `{baseDir}/references/setup.md` 安装（`python3 -m pip install pg8000 cryptography PyYAML`）后停下让用户处理。
2. **选择连接。** 连接名沿用 `~/.gdaa/config.yaml` 的 `name` 字段。仅在有多个连接时才问用哪一个。
3. **采集证据——一条命令，中途不停。**

   ```bash
   python3 {baseDir}/scripts/health.py -c <conn>
   ```

   只读、一次性跑全部 12 个采集器，产固定小节的证据包：`## Overview`、`## Wait Events`、`## Slow SQL`、`## Long & Idle Transactions`、`## Dead Tuples & Bloat`、`## Lightweight Locks (LWLock)`、`## Transaction Locks & Blocking Chains`、`## Connections`、`## Checkpoint / WAL / Archiving`、`## Replication / Standby`、`## Schema / Objects`、`## Transactions / Concurrency`，外加 **`## Deterministic Findings`**（按阈值算出的确定性发现，含 严重度/Code/指标/值/阈值/证据）与 `## Collection Notes`（哪些维度降级）。
   选项：`--include/--exclude <dims>` 裁剪维度；`--top N` 调列表条数；`--format json` 取结构化。**不要**为某一维度单独多跑命令。

4. **加载方法论。** 阅读 `{baseDir}/references/gaussdb-health-methodology.md`，逐维度按其检查清单解读，并做跨维度关联。阈值口径查 `{baseDir}/references/health-thresholds.md`。涉及具体慢 SQL 深调时导向 `/sqltune`，存储过程导向 `/proctune`。

5. **逐维度判断。** 对每个维度：解读原始指标、定位根因、做跨维度关联（典型：空闲事务 IIT 持锁 → 阻塞链 + 卡住 vacuum 回收 → 死元组膨胀）。每条结论都要引用证据包里的某个真实数字。

6. **证据锚定校验门（核心，必须做）。** 拿 `## Deterministic Findings` 逐条核对你的判断：
   - **每条结论必须引用一个真实越界指标/发现**；无指标支撑的结论移入「未证实想法」，不进正式发现。
   - **每条 WARN/CRITICAL 确定性发现都必须被你处理**；漏掉的在报告里标 `⚠ 模型遗漏：<Code>`。
   - **你给的严重度必须与确定性带一致**；不一致标 `⚠ 严重度不符（模型 X / 确定性 Y）`，并**以确定性为准**。
   - **总体状态必须等于确定性最差 severity**（`## Deterministic Findings` 里最重的一条）；**你不得下调**。
   产出**判断校验徽章**：`✓ 已锚定（N 条发现全覆盖、无夸大、无遗漏）`，或列出上述偏差。

7. **报告。** 按以下顺序与版式产出：
   - **抬头状态带** —— `总体状态 <🟢健康/🟡关注/🟠告警/🔴严重>`，附一句「驱动：<最重发现的根因摘要>」；下一行 `判断校验 <徽章>`。
   - **维度概览矩阵** —— 12 维各一行：维度、严重度徽章、关键指标（取该维 Headline / 关键数字）。
   - **按严重度排序的发现** —— 对每条确定性发现（重→轻）：**证据**（引用真实指标 vs 阈值）→ **根因** → **建议**（带 `风险:低/中/高` 与 `[需人工执行]`）。
   - **关键原始证据** —— 重要维度的原始表（如阻塞链树、Top 死元组表、等待 Top）。
   - **处置优先级** —— 用 **P0/P1/P2 文字**标优先级，各引证、带风险级；**不要用严重度 emoji（🔴🟠🟡）当优先级图标**（见规则）。
   - 收尾一句：本报告全部经脚本只读采集，所有结论已对确定性发现锚定校验。

## 规则

- **报告只呈现结论，不呈现推演。** 「等等 / 换个角度」这类自我纠正不得进入报告；若改了判断，回头同步矩阵里的严重度，使报告自洽。
- **只读、绝不执行修复。** health 不执行 `kill` / `pg_terminate_backend` / `VACUUM` / 任何 DML；处置一律只给带风险级的建议，注明 `[需人工执行]`。
- 不要编造统计：每个结论引用脚本输出里的某个数字。
- **总体状态以确定性发现为准**，LLM 不得下调；无确定性发现时才是 🟢健康。
- **优先级与严重度是两个独立维度，分开标。** 确定性严重度用 🟢🟡🟠🔴（脚本定，不可改）；处置优先级用 P0/P1/P2（你按影响排）。一条 🟡 的发现可以因持锁/扩散风险被你排成 P0——这没问题，但呈现时该发现**仍标 🟡，P0 用文字**；**绝不用 🔴 当 P0 小节的图标**，否则会让人误以为存在 critical 级发现。
- 某维度 `## Collection Notes` 标了降级（缺视图/权限）时，如实说明该维度不可用，不要臆测其结论。
- 绝不在对话中回显密码或 DSN。
- 遇到脚本报错，查 `{baseDir}/references/setup.md` 的症状对照表。

## 安全红线

- **只通过本技能脚本取数**：`{baseDir}/scripts/health.py` 走只读会话、自动解密 `~/.gdaa` 凭据。**你自己不要**直接写 Python/psql/gsql 连库、不要读取或解密 `~/.gdaa/credentials/`。脚本未覆盖的能力，如实说明「当前无此能力」并停止。
- **绝不执行变更**：健康检查是只读诊断，任何 kill / VACUUM / DDL / DML 都只作为建议交由用户人工执行。
