# 中医 nihaixia Skill 融合到临床辅助系统方案

> 2026-07-18 规划。用户分享头条文章（GitHub千星 nihaixia 中医Skill），要求将其融合到医师辅助系统。
>
> **⚠️ 2026-07-19 修订（用户批准）**：**步骤4（system prompt 注入 tcm_analysis）废弃** —— TCM 知识不进 `/clinical/assist` 首次分析 prompt（增加输出 tokens，与提速目标直接冲突）。中医以**步骤5独立端点 `POST /clinical/tcm` 为主入口**，前端加「🌿 中医辨证」Tab。同时 `/clinical/assist` 增加 `mode=quick`（首次: 诊断+DIP分组+鉴别诊断, ~800tok）/ `mode=detail`（二次: 医嘱+合规+病程）分步分析。在线 LLM 首选 DeepSeek-chat（64.7tps，见 online-llm-backends.md）。

## 背景

- nihaixia 仓库: https://github.com/jangviktor-web/nihaixia
- 已克隆到: `/home/hehua/nihaixia/`（6.5MB）
- 核心文件: SKILL.md (11,169行) + modules/ (9个模块, 34,667行) + cases/ (6个医案分类, 2,040行) + distilled_cases.md (1,781行) + expression_style.md (249行)
- 知识覆盖: 伤寒论129条 + 金匮23篇 + 黄帝内经71篇 + 神农本草经345种 + 针灸穴位361个 + 849个临床医案
- 核心方法论: 六经辨证（太阳/阳明/少阳/太阴/少阴/厥阴）→ 经方选药

## 系统架构分析

### 现有 RAG 服务结构 (rag_service.py, 2370行)

- **VectorStore 类** (L94-146): ChromaDB PersistentClient + OllamaEmbeddingFunction
  - 集合: hehua_patients, hehua_visits, hehua_rules, dip_rules, medical_pricing, settlement_2025
  - `_get_coll(name, desc)` → 创建集合, cosine similarity
  - `_add_batch(coll, docs, metas, ids)` → 批量upsert, batch_size=200
  - `search(collection, query, n, filt)` → 向量搜索
- **OllamaClient 类** (L149-167): 走 vLLM :8200, max_tokens=2500, temperature=0.1, enable_thinking=False
- **clinical_assist 函数** (L1941-2175): POST /clinical/assist
  - 流程: 查Oracle患者数据 → 向量搜索DIP规则/结算/相似病例 → 拼 user_prompt → 调LLM → 解析JSON
- **CLINICAL_SYSTEM_PROMPT** (L1778-1902): 要求输出结构化JSON（primary_diagnosis, dip_score, differential_diagnosis, suggested_orders, compliance_analysis等）
- **_clinical_vector_search 函数**: 搜索多个集合并汇总结果

### nihaixia Skill 结构

- SKILL.md: 关键词索引 + 检索指南 + 六经速查表 + 方剂速查 + 心智模型 + 诊断流程图
- modules/: 按经典分块（伤寒论太阳篇/其他篇/金匮/内经/梁冬对话/闭门课/针灸本草）
- cases/: 按疾病分类的医案（癌症147案/心血管22案/代谢12案/自身免疫/神经/其他59案）

## 融合方案（5步）

### 1. 新建 ChromaDB 集合 `tcm_knowledge`

```python
COLL_TCM = "tcm_knowledge"  # 倪海厦中医知识库

# 在 VectorStore.__init__ 中添加:
self.coll_tcm = self._get_coll(COLL_TCM, "倪海厦中医知识(六经辨证/经方/本草/医案)")
```

### 2. 编写导入脚本

将 nihaixia 知识按章节分块导入：
- SKILL.md: 按二级标题(`##`)分块，保留上下文
- modules/*.md: 每个文件按三级标题(`###`)分块
- cases/*.md: 每个医案独立成块
- distilled_cases.md: 按医案分隔符分块

每块 metadata: `{"source": "SKILL.md"/"modules/01_shanghan_sun.md"/...，"section": "六经辨证"/"太阳病篇"/...，"type": "理论"/"方剂"/"医案"/"本草"/"针灸"}`

预计 ~2000 个文档块。

### 3. 扩展向量搜索

在 `_clinical_vector_search()` 中新增对 `tcm_knowledge` 的搜索：
```python
# TCM知识检索
try:
    tcm_results = vs.search(vs.coll_tcm, search_query, n=5)
    tcm_docs = []
    for doc, meta, dist in zip(tcm_results["documents"][0], tcm_results["metadatas"][0], tcm_results["distances"][0]):
        tcm_docs.append({
            "content": doc[:500],
            "source": meta.get("source",""),
            "section": meta.get("section",""),
            "type": meta.get("type",""),
            "relevance": f"{1-dist:.2f}"
        })
    result["tcm_knowledge"] = tcm_docs
except: pass
```

### 4. 扩展 System Prompt（❌ 已废弃 — 2026-07-19 用户决策）

> 废弃原因：注入 tcm_analysis 会让首次分析输出再增 ~500-800 tokens，与"首次分析提速"目标直接冲突。中医走步骤5独立端点，首次/二次分析保持纯西医。以下仅为历史记录，**不要实施**。

在 CLINICAL_SYSTEM_PROMPT 末尾追加：
```
如果检索结果包含 [中医知识参考] 部分，请在JSON中增加 "tcm_analysis" 字段：
"tcm_analysis": {
  "liujing": "六经归属判断（太阳/阳明/少阳/太阴/少阴/厥阴/合病）",
  "zhengxing": "证型（如太阳中风证、少阴寒化证）",
  "fangji": "推荐经方名称及组成",
  "yili": "对应的伤寒论/金匮要略原文条文",
  "zhenjiu": "可选针灸穴位",
  "health_standard": "倪氏六健康标准评估（如有相关症状信息）",
  "disclaimer": "中医分析仅供参考，需执业中医师确认"
}
如果检索结果不包含中医知识或与当前病情无关，tcm_analysis 设为 null。
```

### 5. 新增独立端点 `POST /clinical/tcm`

纯中医咨询入口，不依赖Oracle患者数据：
```python
class TCMReq(BaseModel):
    description: str  # 症状描述
    patient_info: Optional[str] = None  # 可选的患者基本信息

@app.post("/clinical/tcm")
def tcm_consult(req: TCMReq):
    """纯中医六经辨证咨询。"""
    tcm_results = vs.search(vs.coll_tcm, req.description, n=8)
    # 构建中医专用prompt，调LLM返回辨证结果
```

## 关键设计原则

- **增量添加，不破坏现有功能**: 西医/DIP 分析逻辑完全不变
- **同一套基础设施**: 复用 ChromaDB + Ollama embedding + vLLM
- **同一次LLM调用**: 中医知识作为额外context注入，不增加API调用次数
- **检索不到则返回空**: 如果 tcm_knowledge 搜索无相关结果，tcm_analysis 为 null，不影响其他字段
- **max_tokens 可能需要调整**: 当前 2500 tokens，加入中医分析后可能需要 3500-4000

## 实施顺序

1. 写导入脚本 `import_tcm.py`，分块导入 nihaixia 知识到 ChromaDB
2. 验证导入结果: `curl http://127.0.0.1:18790/health` 应显示 tcm_knowledge 条数
3. 修改 rag_service.py: 添加 COLL_TCM + VectorStore 初始化 + 搜索逻辑 + prompt 扩展
4. 重启 RAG 服务
5. 测试: `curl -X POST http://127.0.0.1:18790/clinical/assist -H 'Content-Type: application/json' -d '{"description":"怕冷无汗肩颈僵硬"}'`
6. 前端增加 TCM 分析展示面板（可选，后续迭代）
