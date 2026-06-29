---
name: explain
version: 2.0.0
description: "展示 OpenGauss/GaussDB 上某条 SQL 的执行计划，并给出确定性风险标注（Seq Scan、Sort、Nested Loop）。"
allowed-tools: ["exec", "read"]
metadata: {"opencode":{"emoji":"📋","runtime":"python3","requires":{"pip":["pg8000","cryptography","PyYAML"]}}}
---

# Explain（OpenGauss/GaussDB）

仅当用户想要从真实数据库拿到优化器的实际执行计划时使用，而不是要一段「这条查询在做什么」的文字描述。

1. **预检。** 运行 `python3 {baseDir}/scripts/explain.py -h`。若报缺少依赖，`python3 -m pip install pg8000 cryptography PyYAML` 后停下让用户处理。
2. **选择连接。** 连接名沿用 `~/.gdaa/config.yaml` 的 `name` 字段。仅在有多个时才问用哪一个。
3. 运行（SQL 一律走 stdin heredoc，绝不内联）：

   ```bash
   python3 {baseDir}/scripts/explain.py -c <conn> --sql-stdin <<'SQL'
   <the SQL>
   SQL
   ```

   仅当语句是只读、或用户明确同意执行时才加 `--analyze`（DML 会自动用回滚事务包裹，但仍要先问）。
4. 带用户走查计划：访问路径、join 顺序、`## Findings` 一节。若标注暗示需要更深入的工作，建议运行 sqltune 工作流。

## 安全红线

- **只通过本技能脚本取数**：`{baseDir}/scripts/explain.py` 走只读会话（默认不执行 SQL）、自动解密 `~/.gdaa` 凭据。**你自己不要**直接写 Python/psql/gsql 连库、不要读取或解密 `~/.gdaa/credentials/`。脚本未覆盖的能力，如实说明「当前无此能力」并停止。
