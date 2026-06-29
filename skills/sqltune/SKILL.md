---
name: sqltune
version: 2.0.0
description: "按 sql_id 或文本调优 OpenGauss/GaussDB 慢 SQL：脚本采集证据，并对每个索引/改写方案先验证（hypopg + cost 校验）再呈现。"
allowed-tools: ["exec", "read"]
metadata: {"opencode":{"emoji":"🔬","runtime":"python3","requires":{"pip":["pg8000","cryptography","PyYAML"]}}}
---

# SQL Tune（OpenGauss/GaussDB）

深度调优工作流。证据采集是「一条命令」（不要拆开，也不要为占位符停下来）。
**你呈现的每条建议都必须有脚本的验证背书——绝不要把未验证的索引或改写当成确定的优化呈现。**

本技能用 Python 脚本（`{baseDir}/scripts/`）取数与验证：`sqltune.py` 一次性出证据包+索引验证，`verify.py` 验改写。连接/凭据复用 `~/.gdaa`（与 gdaa 相同的存储）。

## 工作流

1. **预检。** 运行 `python3 {baseDir}/scripts/sqltune.py -h`。若报缺少依赖，按 `{baseDir}/references/setup.md` 安装（`python3 -m pip install pg8000 cryptography PyYAML`）后停下让用户处理。
2. **选择连接。** 连接名沿用 `~/.gdaa/config.yaml` 的 `name` 字段（与 gdaa 共用）。若不确定有哪些连接，读 `~/.gdaa/config.yaml` 看 name 列表；只在有多个时才问用哪一个。该文件**只含连接元数据，无密码**——口令在 `~/.gdaa/credentials/*.enc`，由脚本解密，**你不要去读/解密它**。
3. **采集证据——一条命令，中途不停。**

   - unique_sql_id（一个数字，可能为负）：

     ```bash
     python3 {baseDir}/scripts/sqltune.py -c <conn> <unique_sql_id>
     ```

   - 直接给 SQL 文本（一律走 stdin heredoc，绝不内联）：

     ```bash
     python3 {baseDir}/scripts/sqltune.py -c <conn> --sql-stdin <<'SQL'
     SELECT ... user's SQL here ...
     SQL
     ```

   这会自动取 SQL、自动替换占位符、采集完整证据包，**并自动用 hypopg 验证索引候选**。
   **不要单独取 SQL/采集，也不要向用户索要占位符的值。**
   选项：`--bind '<value>'`（可重复，按占位符顺序）传真实值；`--analyze` 仅用于只读 SQL 或用户明确同意时。

4. **合成值提醒。** 若输出含 `## Placeholder Substitution` 一节，说明计划「形状」可靠，但行数/选择性是近似值。要把这点说清楚，并指出索引/改写验证用的是这些合成值——可用 `--bind` 传真实值做精确验证。

5. **加载方法论。** 阅读 `{baseDir}/references/tuning-methodology.md`，对照证据各节按其检查清单分析（`## Execution Plan`、`## Tables`、`## Indexes`、`## Column Statistics`、`## Key Parameters (GUC)`、`## Deterministic Findings`）。深度判断按需查 GaussDB 专项知识：CBO 与诊断边界 → `{baseDir}/references/gaussdb-cbo-and-diagnosis.md`；改写候选 → `{baseDir}/references/gaussdb-rewrite-patterns.md`；A 兼容库（`sql_compatibility='A'`）→ `{baseDir}/references/gaussdb-a-compat-gotchas.md`；分区表/分布式 → `{baseDir}/references/gaussdb-partition-distribution.md`。

6. **索引建议——只用已验证的那一节。**
   `sqltune.py` 的输出含 `## Verified Index Candidates` 一节。这些是用假设（虚拟）索引硬验证过的——cost 是真实的 EXPLAIN 对比。
   - **只推荐出现在那张已验证表里的索引**，并引用它们真实的 `Orig → Hypo cost (N×)` 数字。
   - 若该节显示 "No index candidate passed verification"，**不要**自己编索引建议当成优化呈现。你可以提一个索引「思路」，但必须明确标注为「未验证——假设索引检查未确认其 cost 收益（可能因合成占位符值选择性不强；可试 `--bind`）」。

7. **改写建议——每条都先验证再呈现。**
   对每个你想推荐的 SQL 改写，先验证：

   ```bash
   python3 {baseDir}/scripts/verify.py -c <conn> \
     --original 'SELECT ... (the substituted original) ...' \
     --rewrite  'SELECT ... (your rewrite) ...'
   ```

   - 两侧都用**替换后**的 SQL（不含 `?` 占位符）——verify 会拒绝带占位符的 SQL。
   - **只有当 verify 判 ACCEPTED 时**（加速 ≥ 1.3× 且结果集等价）才把改写当成确定的优化呈现。引用其真实的 `cost X → Y (N×)` 和等价性结果。
   - 若 verify REJECTS（加速不足，或不等价），把它移到「未验证/被驳回想法」子节并注明驳回原因——**不要**当成确定的改进呈现。

7b. **组合验证——改写+索引的赢点。** 一个改写单独看常常很弱，却是某个索引生效的*前提*（例如 `TO_CHAR(col)=...` → `col >= ... AND col < ...` 才让日期索引可用）。当单独的改写不达标，或 `## Verified Index Candidates` 一无所获时，别急着放弃，先验证**组合**：

   ```bash
   python3 {baseDir}/scripts/verify.py -c <conn> \
     --original 'SELECT ... (substituted original) ...' \
     --rewrite  'SELECT ... (your rewrite) ...' \
     --auto-index \
     --index 'CREATE INDEX ON schema.table(col_your_rootcause_found)'
   ```

   合并**两个**索引来源，因为各有盲区：
   - `--auto-index` 让脚本在改写后的 SQL 上用 gs_index_advise（OpenGauss 内置顾问）发现索引。
   - **`--index 'CREATE INDEX ...'`（可重复）**——把你根因分析推断出的关键索引补上，尤其是被改写刚刚解锁的列。gs_index_advise 经常漏掉这些：例如把 `TO_CHAR(order_date)=...` 改写成范围后，gs_index_advise 可能不建议 `order_date` 索引，但你已识别该列是瓶颈——所以显式传 `--index 'CREATE INDEX ON sqltune_demo.orders(order_date)'`。同理，对你标记为 Seq Scan 热点的 join 键也补一个索引。

   每个索引（自动发现的和你显式给的）都会经 hypopg 硬验证——猜错的索引只会显示「无 cost 收益」并被如实标注，所以你永远不会把未验证的索引当成赢点呈现。若组合返回 ACCEPTED，把它作为推荐动作呈现：引用组合的 `cost X → Y (N×)`、等价性结果，以及实际应用的索引 DDL。当改写和索引单独都不达标时，这通常才是真正的赢点。

8. **报告。** 按以下顺序产出：
   - **被分析的 SQL** —— 先用 ```sql 代码块展示完整 SQL（证据 `## SQL` 节里那个替换后/可执行的形式），让读者在看计划前就明确到底调的是哪条。
   - **执行计划** —— 紧接 SQL 之后，把证据 `## Execution Plan` 节里的原始计划树原样放进一个普通 ``` 代码块复现。务必展示这棵真实的计划树；**不要**用手画的总结表替代。每一行保持原样，但**在每个瓶颈节点行末尾追加内联标记 `[P1]`、`[P2]`…**（那些昂贵的 Seq Scan、你点名的昂贵 join/sort）。按严重度从上到下编号。
   - **计划走查** —— 一张瓶颈表，**第一列就用同样的 `[P1]`/`[P2]` 标签**，让每一行与上方计划树里对应的节点交叉引用。引用证据里的真实 cost/行数。
   - **根因** —— 引用具体数字。
   - **已验证推荐** —— **只**放来自 `## Verified Index Candidates` 的索引、`verify.py` 判 ACCEPTED 的改写、以及第 7b 步任何 ACCEPTED 的改写+索引组合，各自带真实 cost 差值。REJECT / 验证超时 / 未验证的改写**不**进此节。
   - **未验证想法**（明确分区）—— 没通过验证的建议（含 REJECT / 验证超时 / 合成值下不达标），注明原因，并提示 `--bind` 传真实值可能改变结论。
   - **风险** —— CREATE INDEX 的锁时间、计划回退、GUC 调整的内存影响。

## 规则

- 没有脚本验证背书，绝不把索引或改写当成确定的优化呈现。已验证与未验证的内容放在明确分开的小节里。
- **「已验证推荐」只放经背书的结论。** 任何 REJECT / 验证超时 / 未验证的改写一律归入「未验证想法」，**严禁挂在「已验证推荐」标题下**——即使内联写了「未验」也不行。
- **逐字誊抄，严禁自算倍数。** 「已验证推荐」里的索引与 cost 倍数必须**原样誊抄** `sqltune.py` 的 `## Verified Index Candidates` 表（DDL / Orig Cost / Hypo Cost / Speedup 照搬）；改写的倍数只能取自对应那一条 `verify.py` ACCEPTED 输出的真实数字。**严禁自行重算、估算或改写倍数。**
- **一个 cost 倍数只能归属于验证它的那一个对象。** 严禁把某索引（或第 7b 步多索引组合 verify）的战果安到另一条改写/另一个索引上；严禁把同一条验证结果当成两条独立推荐重复计数（例如把"索引 X 单独的 N×"又同时算给"改写 Y"）。组合（改写+索引）的倍数标注为「组合」，不拆给单独的改写或单独的索引。
- **严禁编造未经 verify 的因果。** "必须和某改写一起落地""索引隐含消除 Sort/排序"这类断言，除非有对应 verify/EXPLAIN 证据否则不得写——一条 verify 只证明它自己那一条；尤其当某索引**单独**经 `## Verified Index Candidates` 即达标时，不得反过来声称"单加索引无效、必须配合改写"。
- **索引去冗余。** 推荐多个索引时，前缀已被覆盖的不重复推荐（已荐 `(a,b)` 就不再单列 `(a)`）。
- **合成值 caveat。** 倍数基于 `## Placeholder Substitution` 的合成值时，在「已验证推荐」里附一句：真实参数选择性不同、倍数会变，可 `--bind` 精确化。
- **报告只呈现结论，不呈现推演。** 「等等 / 换个角度 / 让我重新想」这类自我纠正、被推翻的中途判断不得进入交付报告；分析中若改了结论，回头同步改正计划树里的 `[P1]/[P2]` 标记与严重度，使报告自洽。
- 一次 `sqltune.py` 调用产出整个证据包（含自动索引验证）。绝不在工作流中途停下来索要占位符的值。
- 不要编造统计信息：每个结论都要引用脚本输出里的某个数字。
- 默认**不**执行用户的 SQL（`--analyze` 关闭）。
- 绝不在对话中回显密码或 DSN。
- 遇到脚本报错，查阅 `{baseDir}/references/setup.md` 里的症状对照表。

## 安全红线

- **只通过本技能的脚本取数与验证**：`{baseDir}/scripts/` 下的 `sqltune.py` / `verify.py` 是唯一的取数与验证通道，它们走只读会话、自动解密 `~/.gdaa` 凭据。**你自己不要**直接写 Python/psql/gsql 连库、不要去读取或解密 `~/.gdaa/credentials/`、不要绕开脚本另起一套查询。脚本没有覆盖的能力时，如实说明「当前无此能力」并停止。
- 脚本对数据库的会话是**只读**的（写/DDL 被会话级 `READ ONLY` 拦截）；`--analyze` 才会真正执行 SQL，且对 DML 自动包在回滚事务里。
