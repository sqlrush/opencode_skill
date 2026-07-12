---
name: sqlreview
version: 1.0.0
description: "审查 OpenGauss/GaussDB 的 DDL/DML/DQL 是否符合 SQL 规范：脚本按 references/rules.yaml 里的规则确定性判定（表必须有主键、禁外键、表/索引/列命名、禁物理删除、禁前置模糊匹配、索引列数上限、索引冗余等），产出违规清单；规则表达不了的（如索引是否建在高基数列）由脚本取证后交模型判断。支持三种输入：SQL 文件/stdin、线上 SQL(sql_id/Top N)、库中存量表与索引。用户问「这段 SQL 合不合规 / 上线前审一下 / 库里哪些表不合规范」即用。"
allowed-tools: ["exec", "read"]
compatibility: opencode
metadata:
  runtime: python3
  emoji: "📏"
  family: sql-governance
---

# SQL Review（OpenGauss/GaussDB 规范审查）

规范的唯一来源是 `{baseDir}/references/rules.yaml`。**判定由脚本做，不由你做**——
你负责解读结果、排优先级、判 advisory 规则、给整改方案。

## 工作流

1. **预检。** 运行 `python3 {baseDir}/scripts/sqlreview.py -h`。若报缺少依赖，
   提示用户 `python3 -m pip install pg8000 cryptography PyYAML`，然后停下。

2. **选输入源。** 三选一，按用户意图挑：

   ```bash
   # a) 审查 SQL 文件（上线前评审，不连库）
   python3 {baseDir}/scripts/sqlreview.py --file changes.sql

   # b) 审查线上跑过的 SQL（需要连接）
   python3 {baseDir}/scripts/sqlreview.py -c <conn> --sql-id <unique_sql_id>
   python3 {baseDir}/scripts/sqlreview.py -c <conn> --top 20

   # c) 审查库中存量的表与索引（需要连接）
   python3 {baseDir}/scripts/sqlreview.py -c <conn> --schema public
   ```

   连接名沿用 `~/.gdaa/config.yaml` 的 `name` 字段，仅在有多个时才问用哪一个。
   需要机器可读结果时加 `--format json`。

3. **读脚本输出，不要自己重新判定。**
   - `## Deterministic Findings` —— 脚本已确定性判定的违规，**逐条如实呈现**，
     不得增删、不得改写规则 id 与级别。
   - `## Advisory（需结合证据判断）` —— 脚本判不了的规则，已附 `依据（criteria）`
     和采到的证据。你**逐条**对照证据给结论：是否违规、为什么。证据不足以下结论时，
     明说「证据不足」并指出还需要什么数据，**不要猜**。

4. **证据锚定校验。** 你写进报告的每个数字（行号、列数、表名、索引名）必须能在脚本
   输出里逐字找到。找不到就不要写。禁止凭印象补充脚本没报的"违规"。

5. **给整改方案。** 按 error → warn → info 排序。每条整改都标注 `[需人工执行]`。
   涉及索引优化时，可转 `sqltune` skill 做 hypopg 实证；涉及存量表膨胀时转 `health`。

6. **退出码语义。** `0` = 脚本跑成功（**不代表没有违规**，违规结论在 stdout）；
   `1` = 运行错误（规则文件非法、SQL 读取失败）；`2` = 连接/配置错误。
   不要把退出码 0 解释为「审查通过」。

## 规范怎么改

规范全部在 `{baseDir}/references/rules.yaml`，用户可以自由编辑：

- 换成自家命名前缀 → 改 `pattern`
- 某条规则不适用 → 加 `enabled: false`
- 调整严重程度 → 改 `severity`
- 新增文本规则 → `check: regex` + `pattern`，**不用改 Python 代码**

用户问「你们的规范有哪些」时，用 `read` 工具读 `{baseDir}/references/rules.yaml`
列清单。**注意**：安装脚本会重拷整个 skill 目录，所以规范要改**源码仓**里的
`skills/sqlreview/references/rules.yaml`，改完重跑 `./install-opencode.sh sqlreview`；
直接改安装目录下的副本会在下次安装时丢失。

## 能力边界（如实说明，不要假装）

- 脚本**没有** SQL 语法解析器，用的是轻量分词 + 规则匹配。注释与字符串字面量已被正确
  剥离（注释里的 `DELETE` 不会误报），但深层语义（子查询里的表别名归属、函数索引的
  实际列）判不了。遇到判不了的，如实说「当前规则无法覆盖」。
- `--sql-id` 取到的线上 SQL 可能是**归一化文本**（字面量变成占位符）或**被截断**
  （`track_activity_query_size` 限制），脚本会在报告里出 note。此时前置模糊匹配这类
  依赖字面量的规则会失效，必须如实说明，不要断言"没有违规"。
- 存量对象审查（`--schema`）看到的是**服务端折叠后的名字**（未加引号的 `OrderItems`
  在库里就是 `orderitems`），所以大小写类命名违规只能在 DDL 文本审查中发现。

## 安全红线

- **只通过本技能脚本取数**：`{baseDir}/scripts/sqlreview.py` 走只读会话、自动解密
  `~/.gdaa` 凭据。**你自己不要**直接写 Python/psql/gsql 连库，**不要**读取或解密
  `~/.gdaa/credentials/`。脚本未覆盖的能力，如实说明「当前无此能力」并停止。
- **只读审查**：本技能不执行任何变更。所有整改建议（加主键、删外键、删冗余索引、
  改逻辑删除）一律只给 SQL 文本并标注 `[需人工执行]`，绝不代为执行。
- **不得替脚本判定**：不要绕过 `rules.yaml` 自行认定某条 SQL "不合规"，也不要
  隐瞒脚本报出的违规。你的判断只作用于 `Advisory` 区，且必须基于脚本给出的证据。
