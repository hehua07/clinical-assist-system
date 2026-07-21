# 新向量集合入推理链配方

2026-07-21 两例验证：`_guideline_context()`（session 27，guidelines 入链）与 `_emr_cases_context()`（session 30，emr_cases 入链）。下次把新集合（或新端点如 discharge_summary）接入推理时按此走，勿重新发明。

## 步骤

1. **建库时绑定嵌入函数**：`get_or_create_collection(name, embedding_function=ef, metadata={"hnsw:space": "cosine"})`。
   不绑 EF 的后果：集合持久化 EF=default，服务端带 EF get_or_create 抛 `Embedding function conflict` 启动崩溃循环（rag-repair-lessons 第19节），消费端只能退化为 `get_collection()` + `query_embeddings=ef([query])` 兼容路径。
2. **阈值实测标定，不拍脑袋**：用覆盖内/覆盖外两个探针查询各取 n=5 看 distances 分布，阈值取两簇之间。
   - emr_cases 实测：覆盖内 0.45-0.58、覆盖外 ≥0.72 → 阈值 0.65
   - guidelines：rel ≥ 0.58
   - 没有负例标定的阈值 = 噪声注入器或永远为空，必做第 6 步负例冒烟
3. **检索函数结构**（镜像 `_emr_cases_context`，rag_service.py L2442）：
   n=8~12 检索 → 按文档键去重（guidelines 按 title、emr_cases 按 emr_id，每文档保留最佳块）→ 阈值过滤 → top 2~3 文档各 ~500 字摘录拼注入块 → **异常静默降级返回空**（检索失败不得拖垮主分析）。
4. **prompt 条款**：quick/detail 两个系统提示词各加一条【XX参考】，写明：①用途边界（指南=对齐，病历=思路/格式参考）②引用格式（指南须注明名称+年份）③冲突优先级（患者安全/指南 > 历史病历）。
5. **响应字段 + 前端渲染**：响应带 `xxx_refs`（元数据 + relevance + 150字 snippet；**摘录正文只进 prompt 不回前端**——refs 是给前端展示"依据可见性"的）。前端镜像 `renderGuidelineRefs` 渲染到关键提醒区，**quick 全量渲染和 detail 合并渲染两条路径都要挂调用**（HTML 1268 与 918 两处）。
6. **冒烟三件套**：
   ① 覆盖内病例 refs > 0 且内容相关
   ② **覆盖外病种 refs = 0**（负例验证阈值有效性，如主动脉夹层对县级医院病历库）
   ③ 公网 curl grep 标志串 ≥1——公网验证须向公网域名重新 `POST /login` 取 cookie（cookie 按域名隔离，本机 cookie 不发送），curl 加 `-L` 跟 307。

## 一句话

绑定 EF → 实测标定阈值 → 文档去重 + 静默降级 → prompt 条款写边界 → refs 两路径挂渲染 → 正/负例 + 公网验证。
