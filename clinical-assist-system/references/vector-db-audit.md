# ChromaDB 离线审计方法（rag-service.bak）

## 何时用
- 验证导入/重建结果（counts、chunk 质量、重复、元数据完整性）而不干扰运行中的服务
- 排查「数据在库但检索/分析不命中」类问题

⚠️ 不要用 `chromadb.PersistentClient` 直开运行中库的目录做审计（慢且可能争锁）；用 sqlite 只读模式。

## 方法 1：sqlite 只读（immutable）直查

```python
import sqlite3
con = sqlite3.connect('file:/home/hehua/rag-service.bak/chroma_data/chroma.sqlite3?mode=ro&immutable=1', uri=True)
```

`mode=ro&immutable=1` = 不加锁，与运行中的 rag-service 并行安全。

### chromadb 1.5.9 sqlite schema 要点
- 文档正文**不在** `embeddings` 表（它没有 document 列！），在 FTS 表 `embedding_fulltext_search_content(id INTEGER PK, c0)`，与 `embeddings.id` 一一对齐
- 元数据：`embedding_metadata(id, key, string_value)`，key ∈ title / url / publisher / pub_date / ...
- 按集合过滤：`collections(id, name)` → `segments(id, collection)` → `embeddings.segment_id`

### 审计查询清单（2026-07-20 实战验证过）
1. **chunk 量与规格**：join content 表取 `length(c0)` 分布（min/p50/p90/max、空块、<50字碎片）
2. **完全重复**：`Counter(c0)` 找计数>1 的组，并回溯这些 chunk 属于哪些标题
3. **文档数去重**：`Counter(title)` 的 distinct 数对比宣称的篇数（导入 md 文件数 ≠ 入库独立文档数）
4. **元数据完整性**：title/url 空值计数
5. **内容抽样**：随机 3-5 个 chunk 肉眼检查——重点防：参考文献列表成块、PDF 表格变"数字粥"、选题外 boilerplate 混入

### 元数据键名/取值审计（2026-07-21 dip_rules 实战，治"代码读的键 ≠ 库里存的键"）

sqlite3 CLI 即可（无需 python），先拿集合的 METADATA 段 id，再聚合 `embedding_metadata`：

```bash
cd /home/hehua/rag-service.bak/chroma_data
DB="file:chroma.sqlite3?immutable=1"
# 1) collections(id,name) → 2) segments(id,scope) WHERE collection='<id>' → 取 scope=METADATA 的段
sqlite3 "$DB" "SELECT id, scope FROM segments WHERE collection='<collection_uuid>';"
# 3) 键清单（该集合全部元数据键，一眼核对代码 m.get(...) 的键名是否存在）
sqlite3 "$DB" "SELECT group_concat(DISTINCT key) FROM embedding_metadata
 WHERE id IN (SELECT id FROM embeddings WHERE segment_id='<METADATA段id>' LIMIT 300);"
# 4) 取值分布（如 diagnosis_code 长度分布，判断精确匹配/前缀回退是否可能命中）
sqlite3 "$DB" "SELECT LENGTH(string_value), COUNT(*) FROM embedding_metadata
 WHERE key='diagnosis_code' AND id IN (SELECT id FROM embeddings WHERE segment_id='<METADATA段id>')
 GROUP BY 1 ORDER BY 1;"
# 5) 某键非空率（如 extra_oper_codes 附加操作覆盖度）
sqlite3 "$DB" "SELECT COUNT(DISTINCT id) FROM embedding_metadata
 WHERE key='extra_oper_codes' AND string_value<>'' AND id IN (SELECT id FROM embeddings WHERE segment_id='<METADATA段id>');"
```

2026-07-21 实测存档（dip_rules，4481 条）：键含 `std_dip_value`（**不是** std_score——代码 `_clinical_vector_search` 读 `std_dip_value` 正确；`_format_dip_rules` 先读 std_score 是读它自己上游 dict 的键，两层别混）、`diagnosis_code`（五字符 X00.0 占 4096，七字符 X00.000 仅 37）、`operation_code/name`、`dip_code`、`dp_kind`、`extra_oper_codes/extra_oper_names`（2368 条非空，附加操作数据，前后端未用）、`main_flag`（全空）。settlement_2025 键为中文（病种手术操作代码/名称、病种分值、实际分值、总费用、超支结余等）。⚠️ sqlite 相关子查询里不能用外层 CTE 别名，逐条简单查询最稳。

## 方法 2：检索打靶（经服务 API）

```bash
curl -s "http://127.0.0.1:18790/guideline/search?diagnosis=<URLEncode的病种>&n=3"
```

- 返回 `{diagnosis, answer, sources[]}`——sources 只有 title/publisher/journal/url/relevance，**无内容字段**
- 检查两缺陷：①同一标题霸榜 top-N（无文档级去重，前端会显示三条相同标题）；②未收录病种也返回低分结果（无相关度阈值拒绝，如高血压→卒中指南 rel 0.57）

## 方法 3：链路在用性审计（「入库 ≠ 在用」）

`/health` 的集合计数**只证明数据入库**，不证明推理链路在用它。验证：

```bash
grep -n "coll_<name>" rag_service.py    # 该集合被哪些端点引用
grep -n "vs\.search(" rag_service.py    # 列出全部检索调用点
```

对照 `_clinical_vector_search`（/clinical/assist 的检索函数）实际查哪些集合。2026-07-20 实测：它只查 visits / dip_rules / dip_settlement / medical_pricing / rules / patients 共 6 个集合，**guidelines 和 tcm_knowledge 都不在临床分析链路里**。

另注意**死代码信号**：`/guideline/query`（rag_service.py ~2957 行）构建了 `context` 变量准备做 LLM 问答但从未使用——纯检索接口，只回标题/URL/相关度。

## 2026-07-20 审计结果存档（guidelines 集合）

| 项 | 实测 |
|:--|:--|
| chunks | 2221，全部 800 字规格（100 重叠），无空块/碎片块 |
| 不同标题 | **118**（≠此前记录的 133 篇——同指南多来源双份入库） |
| 完全重复 chunk | 83 条 / 81 组（上尿路结石共识解读、腹股沟疝2024、CAP基层指南2018/实践版、肝胆管结石湖南共识等各双份） |
| 元数据 | title/url 零缺失 |
| 内容噪声 | 参考文献列表成块；PDF 表格变数字粥（糖尿病药代动力学表）；胆道肿瘤共识混入检验防护 boilerplate |
| 检索命中 | 胆囊结石→胆石症共识2025(0.75)、前列腺增生→2025中医指南(0.78)、阑尾炎→2025共识、疝→2024指南，头部命中准确 ✅ |
| 链路在用性 | ❌ guidelines 不在 `_clinical_vector_search`；只有手动查询 Tab 在用 |
