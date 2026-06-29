---
name: wdr
version: 2.0.0
description: "OpenGauss/GaussDB WDR 报告解读：脚本只读列快照→对选定窗口生成原生 WDR(留底)并自查快照视图算结构化 delta(7 维：Load Profile/库级 Stat/Top SQL/等待/Checkpoint/Cache/File IO)→按阈值产确定性发现；LLM 解读并优先定位高风险，出建议前先做证据锚定+对 Top SQL 用 sqltune 做 hypopg 实证，出诚实可落地的优化报告。用户问'这段时间库为什么慢/看下两个快照之间的 WDR/有没有高风险 SQL·等待·checkpoint 压力'即用。"
allowed-tools: ["exec", "read", "write"]
compatibility: opencode
metadata:
  runtime: python3
  emoji: "📊"
  family: diagnostics
---

# WDR 报告解读（OpenGauss/GaussDB）

只读、可信的 WDR 工作负载诊断。**确定性归脚本（采集 + 阈值发现），判断归你（LLM），但你的判断必须对脚本的 `## Deterministic Findings` 做证据锚定校验；优化建议出炉前还要对 Top SQL 做 hypopg 实证。** 严格只读：脚本绝不创建快照。

本技能用 Python 脚本（`{baseDir}/scripts/wdr.py`）取数与渲染，连接/凭据复用 `~/.gdaa`。

## 工作流

1. **预检。** 运行 `python3 {baseDir}/scripts/wdr.py -h`。若报缺少依赖，按 `{baseDir}/references/setup.md` 安装（`python3 -m pip install pg8000 cryptography PyYAML`）后停下让用户处理。
2. **选连接。** 连接名沿用 `~/.gdaa/config.yaml` 的 `name` 字段。仅多连接时才问。
3. **列快照、定窗口。**

   ```bash
   python3 {baseDir}/scripts/wdr.py snaps -c <conn>
   ```

   读 `enable_wdr_snapshot` 与快照列表，给出建议窗口。**若报"WDR 未开启"或"快照不足"**：如实转告用户需在 DB 侧 `ALTER SYSTEM SET enable_wdr_snapshot=on`（需 reload/重启）或 `SELECT create_wdr_snapshot();`，**绝不代为开启或创建**，然后停止等待用户。默认采用建议窗口，除非用户另指定 begin/end。

4. **采集证据——一条命令不中停。**

   ```bash
   python3 {baseDir}/scripts/wdr.py collect -c <conn> --begin <B> --end <E>
   ```

   只读产固定小节证据包 + `## Deterministic Findings`（严重度/Code/指标/值/阈值/证据/sql_id）+ `## Collection Notes`。`--top N` 调列表条数；`--save-html <path>` 留底原生 WDR；`--format json` 取结构化。**不要**为单一维度多跑命令。

5. **加载方法论。** 阅读 `{baseDir}/references/wdr-methodology.md`，逐维度按检查清单解读，阈值口径查 `wdr-thresholds.md`。

6. **逐维度判断，优先定位高风险，并把每条问题闭环到"引发请求 + 怎么优化"。** 对每个维度解读 delta、**先看 severity ≥ 🟠 的发现**、定根因、跨维关联。**报告不能只列问题**——每条发现必须落到：① **哪些请求引发**（按 `references/wdr-methodology.md` 的「问题归因纪律」表，从 Top SQL 的对应列定位：temp 溢出→`spill_MB`、DB time/CPU→`elapsed_s`/`cpu_s`、IO→物理读、锁/死锁→`cpu_s`≈0 被阻塞语句 + 死锁表的 DML）；② **该请求如何优化**（带 sql_id 的先 `sqltune` 实证；阻塞/睡眠类给事务并发层建议）。注意 temp/IO/锁的元凶请求往往不是同一条，别一锅烩。每条结论引用证据包里某个真实数字。

7. **交叉验证门（核心，出建议前必须做）。**
   - **证据锚定**：每条结论/建议必须引用一个真实越界指标/发现（按 Code）；无指标支撑的移入「未证实想法」，不进正式发现。
   - **红线不漏**：每条 🟠/🔴 确定性发现都必须被处理；漏掉的标 `⚠ 模型遗漏：<Code>`。
   - **严重度一致**：你的严重度必须与确定性带一致；不一致标 `⚠ 严重度不符`，以确定性为准。总体状态 = 确定性最差 severity，**你不得下调**。
   - **hypopg 实证（关键）**：对带 `sql_id` 的 Top SQL 类发现，若你要给索引/SQL 改写建议，**先验证再呈现**：

     ```bash
     python3 {baseDir}/../sqltune/scripts/sqltune.py -c <conn> <sql_id>
     ```

     采纳其 `## Verified Index Candidates` / 改写验证里**已通过**的方案（带真实倍数，如 `6602→2.47, 2672×`）；**验证未通过/未达标的建议不要写进报告**。

8. **写判断 → 渲染报告。** 把交叉验证过的判断写成 `interp.json`（schema 见下），再让脚本确定性渲染：

   ```bash
   python3 {baseDir}/scripts/wdr.py collect -c <conn> --begin <B> --end <E> --format json > /tmp/wdr_ev.json   # 若 step4 未存则补存
   # 写 /tmp/wdr_interp.json（你的判断，见下）
   python3 {baseDir}/scripts/wdr.py render --evidence /tmp/wdr_ev.json --interp /tmp/wdr_interp.json --format md
   ```

   **最终报告必须是 `wdr.py render` 的完整 stdout，逐字呈现给用户——这是硬性要求，不是可选。** render 现产**自顶向下全景报告**：抬头状态带（结论先行）→ 维度概览矩阵 → **全景分析**（Load Profile→库级 Stat→等待→**Top SQL 多维表**[含「各维度元凶」行：DB time/CPU/溢出/物理读/调用 各自冠军 + 全列表]→Checkpoint→Cache→File IO，每维带一句判读）→ 高风险发现（根因→引发请求→优化）。

   **🚫 绝不允许：用你自己的话另写一份叙事报告替换 render 的输出、或浓缩/省略「全景分析」。** 尤其 **Top SQL 的多维表与「各维度元凶」行必须原样出现在最终报告里**——用户要看的就是"各维度的 Top SQL"，不是 prose 里点几个 sql_id。你的全部判断（根因、引发请求、优化）只写进 `interp.json` 的 findings，由 render 铺开为「高风险发现」段；你**最多**在 render 输出的最前面加 **≤3 行执行摘要**，正文一律是 render 的原样输出。终端用户要富文本可另跑 `--format ansi`。

   **render 会机械复核**：interp 里引用的 Code 必须在证据包确定性发现中、实证类建议必须 `status=verified`，否则落入「⚠ 未锚定 / ⚠ 未验证 / ⚠ 模型遗漏」区，不作正式发现/建议——这是最后一道确定性闸。

   `interp.json` schema：

   ```jsonc
   {
     "overall": { "severity": "OK|NOTICE|WARN|CRITICAL", "driver": "<最重发现根因一句话>" },
     "verificationBadge": "<可留空，render 会自算>",
     "findings": [
       { "code": "<必须是证据包里出现的 Code>", "rootCause": "...", "sqlId": "<Top SQL 类才有>",
         "suggestions": [
           { "text": "...", "risk": "低|中|高", "manual": true,
             "validation": { "method": "hypopg|cost-rewrite|none", "status": "verified|failed|n/a", "evidence": "6602→2.47 (2672×)" } }
         ] }
     ]
   }
   ```

   规则：① 只为证据包里真实存在的 Code 写 finding；② 索引/SQL 改写建议必须先经 sqltune 实证、把真实倍数填进 `validation`，未过的不写或标 `status:failed`（render 会剔除）；③ 总体严重度以确定性为准，render 以 Evidence 的 overall 为准、你写错会被标注。

## 规则

- **最终报告 = `wdr.py render` 的完整输出，逐字呈现，绝不自述替换。** 不得用 prose 浓缩/省略「全景分析」；**Top SQL 多维表与「各维度元凶」行必须原样保留**。判断只进 interp.json，正文一律 render 原样输出（最多前置 ≤3 行摘要）。
- **报告只呈现结论，不呈现推演。** 自我纠正不进报告；改了判断回头同步矩阵严重度。
- **只读、绝不执行变更。** wdr 不创建快照、不 kill / VACUUM / DDL / DML；处置一律给带风险级建议，注明 `[需人工执行]`。
- 不编造统计：每个结论引用脚本输出里的某个数字。
- **总体状态以确定性发现为准**，不得下调；无确定性发现时才是 🟢健康。
- **优先级（P0/P1/P2）与严重度（🟢🟡🟠🔴）分开标**；绝不用 🔴 当 P0 图标。
- 某维度 `## Collection Notes` 标降级时，如实说明不可用，不臆测其结论。
- 绝不回显密码 / DSN。
- 遇脚本报错查 `{baseDir}/references/setup.md`。

## 安全红线

- **只通过本技能脚本取数与渲染**：`{baseDir}/scripts/wdr.py`（及实证用的 `../sqltune/scripts/sqltune.py`）走只读会话、自动解密 `~/.gdaa` 凭据；**你自己不要**直连库、不读取/解密 `~/.gdaa/credentials/`、不用 psql/gsql 自行取数。脚本无对应能力时如实说明并停止。
- **绝不执行变更**：WDR 解读是只读诊断；**尤其绝不调用 `create_wdr_snapshot` 或代用户开启 WDR**——缺快照只指引用户人工处理。任何索引 / 改写 / DDL 都经 hypopg 虚拟验证后，交用户人工落地。
