# sqltune 测量保真度优化设计（Measurement Fidelity）

- 日期：2026-06-29
- 目标 skill：`skills/sqltune`（Python，v2.0.0）
- 上游：本缺陷源自 gdaa Go `internal/probe/*`，详见 §9
- 状态：待审核（review 通过后开始编码）

---

## 1. 背景与问题

对黄金用例 `scripts/fixtures/bigquery.sql`（10 表 join + 两个相关标量子查询 + 多层嵌套子查询，跑在 `bigjoin` 合成库）做实测：

| 方案 | 实测耗时 | 相对原始 |
|---|---|---|
| 原始 SQL（真实参数 `order_date>=2024-01-01`，20000 行） | **3458 ms** | 基线 |
| 原始 SQL，仅加 `reviews(customer_id)` + `shipments(order_id)`（+`reviews(product_id,rating)`），**不改写** | **61 ms** | **57×** |

而 sqltune 实际输出的结论是「当前测试库 + 合成占位符值下，最高 1.25×，突破不了 1.3× 阈值，无优化空间」。

**模型（OpenCode）的推理没问题**——它找出了冗余 JOIN、揪出了 GROUP BY 语义问题、也把对的索引列当“想法”列了出来。**失效的是 skill 的测量底座**：它让模型在一个「假数据 + 只看估算 cost」的退化计划上做判断，模型只是如实复述了工具给出的「无 ≥1.3× 收益」。

### 1.1 根因（已逐条实证 + 定位代码）

| 编号 | 根因 | 代码位置 | 实证 |
|---|---|---|---|
| RC1 | **占位符替换数据盲**：比较谓词一律填 `50`、日期填 `'2024-01-01'`、int/IN 填 `1`，文件 docstring 自承 *"Pure text heuristics, no DB lookups"* | `placeholder.py:152/161/162` | `pct` 实际 max=29、`rating` max=5 → 合成的 `pct>50`、`rating>=50` 各匹配 **0 行** → `IN(...)` 空、`EXISTS(...)` 恒假 → 整条查询空集 → 两个相关子查询（真凶）**一次都不执行** → 计划退化、看不出任何索引收益 |
| RC2 | **只看 optimizer cost，从不实测时间**：`explain_cost` 用 `EXPLAIN (FORMAT JSON, COSTS TRUE)`，无 ANALYZE；speedup = cost 比值；阈值 1.3× 也是 cost 比值 | `cost.py:13`、`verify.py:35/114`、`hypoindex.py:85` | 报告里的每个数字都是估算，不是实测速度；`sqltune.py` 有 `--analyze`、`evidence.py` 能 EXPLAIN ANALYZE，但**仅用于展示证据计划，决策路径完全无视它** |
| RC3 | **无退化哨兵**：只在 `cost<=0` 时拒绝，空结果（cost=6772>0）被当成合法基线 | `verify.py:109`、`hypoindex.py:55` | 从不具代表性的计划里输出了带十足信心的「无优化空间」 |
| RC4 | **候选发现只靠 `gs_index_advise`**，且 advise 跑在被污染的退化计划上 | `hypoindex.py:60`、`verify.py:163` | 空计划里相关子查询不花一分钱，advise 结构上**不可能**推荐 `reviews(customer_id)`/`shipments(order_id)`；另外 `scan_plan`（`evidence.py:114`）是纯文本匹配，**根本不识别 SubPlan/相关子查询**，真凶从头到尾没被标记 |

> RC1 是主因（它让瓶颈消失），RC2 是可信度问题（数字非实测），RC3 让错误结论带上了确定性，RC4 让正确候选无法被发现。四者叠加才产生了「57× 空间却报无优化空间」。

---

## 2. 目标 / 非目标

**目标**
1. 在 normalized SQL（带占位符）上，sqltune 能可靠地发现真实优化、给出**实测** before/after 时间，并对退化场景**诚实**。
2. 黄金用例 `bigquery.sql` 无需 `--bind` 即可自动得出 `reviews(customer_id)`+`shipments(order_id)`，实测 speedup ≫ 1.3×。

**非目标**
- 不重写/不替换优化器。
- 不做自动 DDL 上线（仍只产出建议 + 在回滚事务里临时验证）。
- 不改动 evidence 的整体展示格式（仅新增字段/章节）。
- 本轮不强制同步改 gdaa Go（§9 给出建议与决策点）。

---

## 3. 设计总览（四个改动，全量、不分期）

数据流（改造后）：

```
normalized SQL
  → [Fix1] 数据感知占位符替换 (pg_stats 取值, --bind 仍优先)
  → evidence collect (plan + ANALYZE + stats + findings)
  → [Fix3] 退化哨兵 (空结果/选择性≈0或1/无重节点 → inconclusive)
  → [Fix4] 候选合成 (gs_index_advise ∪ 从 findings 派生: 相关子查询关联列 / 无索引 join 键 / 高选择性过滤列)
  → [Fix2] 两层验证 (hypopg+cost 初筛 → top-N 在 BEGIN…ROLLBACK 里真建索引跑 EXPLAIN ANALYZE)
  → 排名 verdict (cost 估算 + 实测 time 双列, accepted 以实测 time 为准)
```

### Fix 1（RC1）数据感知占位符

- 扩展 `placeholder.py`：`substitute(sql, binds, *, stats_provider=None)`。
  - `stats_provider=None` 时**行为完全不变**（保留纯文本启发，无 DB 依赖，老测试不破）。
  - 提供 provider 时：解析占位符左侧列引用（`alias.col` / `schema.table.col`），按算子选值：
    - `=` / `IN` → `most_common_vals[0]`，无 MCV 则 `histogram_bounds` 中位。
    - `>` `>=` `<` `<=` → `histogram_bounds` 的某分位（默认 p50），使选择性≈中等。
    - `LIKE` → MCV 前缀；否则保留 `'%token%'`。
    - 全部 clamp 到 `[min,max]`（histogram 首尾）。
  - 取不到 stats（表没 ANALYZE 过 / 列解析失败）→ 回退旧启发，`source` 标 `heuristic-fallback` 并触发 §Fix3 警告。
- 新文件 `stats.py`：`StatsProvider`，查 `pg_stats`（`most_common_vals` / `histogram_bounds` / `null_frac`）+ `pg_class.reltuples`；纯查询、可注入 mock。
- alias→表 的解析：优先复用 evidence 已解析的 FROM/alias 信息；若不足，先实现「从 SQL 文本提取 `FROM/JOIN <schema.table> [AS] <alias>`」的最小解析器（独立小函数，单测覆盖）。

### Fix 2（RC2）两层实测打分

- **第一层（初筛，便宜不锁表）**：维持 hypopg + cost，筛掉明显无效候选，保留 cost 比值 top-N（默认 N=3，可配 `--top-n`）。
- **第二层（最终判定，实测）**：对 top-N 候选，在**单个 `BEGIN … ROLLBACK` 事务**里 `CREATE INDEX` 真建，跑 `EXPLAIN (ANALYZE, TIMING, FORMAT JSON)` 取 `Actual Total Time`，多次取中位（默认 `--runs 3`），与 baseline 实测对比；`ROLLBACK` 撤销索引。
- 新文件 `measure.py`：封装两层流程；新增 `cost.py::explain_actual_time()`（ANALYZE JSON、多 run 取中位）。
- 报告新增双列：`speedup_cost`（估算）+ `speedup_time`（实测）；`accepted` 以 `speedup_time >= MIN_SPEEDUP` 为准。
- 默认开启实测；`--no-measure` 退回纯 cost-only（CI / 无写权限场景）。

### Fix 3（RC3）退化场景哨兵

- 在 baseline 评估后检测，命中任一即判 **inconclusive**（区别于 rejected）：
  1. baseline 计划 `actual rows ≈ 0`（有 ANALYZE 时）或 estimated rows ≤ 阈值；
  2. 任一被替换谓词的估算选择性 ≈ 0 或 ≈ 1（用 Fix1 的 stats 估算）；
  3. baseline 计划里没有任何「重节点」（无 SubPlan、无大 Seq Scan、root cost 低于阈值）。
- 命中 → **绝不输出「无优化空间」**；改为醒目警告「合成值不具代表性，请用 `--bind` 提供真实值」，verdict 标 `inconclusive`。

### Fix 4（RC4）候选合成不只依赖 gs_index_advise

- 增强 `evidence.py::scan_plan` → 结构化提取（新增 `Finding` 字段或并行的结构化 candidate 列表）：
  - **相关子查询（SubPlan）的关联列**（如 `reviews.customer_id`、`shipments.order_id`）—— 当前完全没识别，是本次最关键补强；
  - 无索引的 join 键；
  - 高选择性的范围/等值过滤列。
- 新文件 `candidates.py`：把上述派生候选转成 `CREATE INDEX` DDL，与 `gs_index_advise` 候选**合并去重**，统一送入 Fix2 两层验证。

---

## 4. 模块 / 文件影响

| 文件 | 改动 |
|---|---|
| `placeholder.py` | 加 stats-aware 取值路径 + 列引用解析；保留无-provider 的旧行为 |
| `stats.py`（新） | `StatsProvider`：查 pg_stats / reltuples，可注入 |
| `cost.py` | 加 `explain_actual_time()`（ANALYZE JSON、多 run 中位） |
| `measure.py`（新） | 两层验证：cost 初筛 + 回滚事务真索引实测 |
| `candidates.py`（新） | 从 findings 派生候选 DDL + 合并去重 |
| `evidence.py` | `scan_plan` 结构化提取 SubPlan 关联列 / join 键 / 过滤列 |
| `verify.py` / `hypoindex.py` | 接入 measure + 候选合成；引入 `inconclusive` verdict |
| `sqltune.py` | 编排 + 新 flag：`--measure/--no-measure`、`--runs`、`--top-n` |

遵循「多小文件」：新增 `stats.py` / `measure.py` / `candidates.py` 而非堆进现有文件。

---

## 5. 错误处理 / 边界

- 无 pg_stats（表没 ANALYZE）→ Fix1 回退启发 + Fix3 警告。
- 只读连接但要实测 → 自动退 cost-only 并提示（复用 `sqltune.py:180` 的 `read_only=not analyze` 思路）。
- 事务内建索引超时 / 失败 → 跳过该候选并标注，不整体失败。
- hypopg / gs_index_advise 不可用 → 维持现有 graceful degrade；Fix4 派生候选仍可独立验证。
- DML → 沿用现有「跳过等价 + 不实测」。

---

## 6. 测试策略（TDD）

- **黄金端到端**：`bigjoin.sql` + `bigquery.sql`（normalized 形态）跑全 pipeline，断言：① 推荐含 `reviews(customer_id)`+`shipments(order_id)`；② 报告含实测 before/after time；③ `speedup_time ≥ 10×`；④ equivalence ✅；⑤ 不再误报 inconclusive。
- **单测**：
  - `placeholder` stats-aware：注入 mock `StatsProvider`，断言取值落在分位且 clamp 生效；无 provider 时输出与现状一致。
  - `degenerate guard`：`pct>50` 空结果场景 → `inconclusive` 且不出现「无优化空间」。
  - `candidates`：SubPlan 计划文本 → 派生出关联列候选。
  - `explain_actual_time`：多 run 取中位逻辑。
- **回归**：现有 `*_test.py`（含 placeholder 旧路径）全绿。

---

## 7. 验收标准（Acceptance）

1. 对 `bigquery.sql`（normalized、无 `--bind`），sqltune 自动推荐 `reviews(customer_id)`+`shipments(order_id)`，报告实测 before/after time，`speedup_time ≥ 10×`，equivalence ✅。
2. 当替换值导致空结果 / 选择性退化时，输出 `inconclusive` + 「请用 `--bind`」，**绝不**输出「无优化空间」。
3. 报告同时含 `speedup_cost`（估算）与 `speedup_time`（实测）双列；`accepted` 基于实测。
4. 无 stats / 无 hypopg / 只读连接 等降级路径行为明确且不崩。
5. 既有测试全绿。

---

## 8. 风险

| 风险 | 缓解 |
|---|---|
| 事务内真建索引在大表上的锁 / 耗时 | top-N 限制 + `statement_timeout` 兜底 + `--no-measure` 可关 |
| pg_stats 过期 / 缺失导致选值不准 | 回退启发 + Fix3 哨兵兜底 + `--bind` 仍优先 |
| 分位中值未必触发与生产相同的计划 | 允许 `--bind`；哨兵在退化时给警告而非假结论 |

---

## 9. gdaa 上游 parity

本缺陷 1:1 存在于 gdaa Go（OpenCode 是其忠实端口，非端口引入）：

| 根因 | gdaa Go 位置 |
|---|---|
| RC1 数据盲取值（`50` / `'2024-01-01'` / `1`） | `internal/probe/placeholder.go:218/221/231` |
| RC2 只看 cost（注释明写 no ANALYZE） | `internal/probe/explaincost.go:33` |
| RC2 阈值 / cost 打分 | `internal/probe/verify.go:12/80`、`hypoindex.go:188` |
| RC4 仅靠 gs_index_advise | `internal/probe/hypoindex.go:120`、`verify.go:283` |

**建议**：同一设计回移植到 gdaa Go（至少 Fix1 + Fix3）。
**决策点（待 review）**：本轮是否一并产出 gdaa 的对应 spec / 改动，还是先 OpenCode 落地、验证后再回移植。

---

## 10. 待确认决策点（review 时回填）

- [ ] 实测默认开启 vs 默认关闭（本 spec 取「默认开 + `--no-measure` 退回」）。
- [ ] `--top-n` / `--runs` 默认值（本 spec 取 3 / 3）。
- [ ] Fix1 分位默认取 p50 vs 让选择性贴近某目标值（如 ~20%）。
- [ ] gdaa 回移植是否本轮一并做（§9）。
