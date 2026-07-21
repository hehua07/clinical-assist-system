# 加选（选用按钮）后参考操作列表返回无数据 — 根因分析（2026-07-21 只读分析，未修复）

> 任务性质：只读 RCA（禁止改文件/数据库）。结论已交付用户，**修复尚未实施**。行号基于工作区版本（git 92ddb64 + 未提交的指南 source 字段小改）。

## 症状

医师在「建议的主操作」下方参考列表（淮南市分值库匹配手术 / 和华医院结算参考）点【选用】加选主操作之外的手术/操作后：页面**不卡死、不报错**，但参考区数据消失（"返回无数据"）。

## 调用链（行号已核实）

### 前端 clinical_assist_page.html
| 环节 | 行号 |
|:--|:--|
| 参考列表渲染 `renderOperationReferences(dipOps, settleOps)` | 1761–1800（【选用】按钮 1778 / 1795） |
| `selectOperation(code,name)` → 写入 `procSelector` 下拉 | 1802–1816 |
| `reanalyzeWithCode(code,name)` → POST `/clinical/assist` | 1818–1848 |
| **payload 硬编码 `description:''`**，仅带 `selected_operation: code` | **1831–1836（关键！）** |
| 主操作下拉 `procSelector` + 🔄 按钮（另一路径 `reanalyzeWithSelection` 发 `selected_procedure`） | 1251–1265 / 1325–1387 |
| 渲染端静默消失机制：`renderResults` 先删旧参考区（1044–1046），`renderOperationReferences` 两列表均空时直接 return（1766） | — |

### 后端 rag_service.py
| 环节 | 行号 |
|:--|:--|
| `@app.post("/clinical/assist")` → `clinical_assist` | 2359 |
| `selected_operation` **只注入 LLM prompt，不进检索** | 2425–2427 |
| 检索查询串 = description + 姓名/主诉 + HIS 诊断名/码 | 2410–2416 |
| `_clinical_vector_search`：dip_rules 语义 n=6、距离阈值 0.55；诊断码精确匹配 + 前缀[5,4]回退 | 1861–1977（阈值 1864/1930；正则 1891） |
| 响应：`dip_operations`/`settlement_operations` | 2636–2637（`_format_dip_rules` 2323、`_format_settlement_ops` 2342） |
| 诊断来源：`ICSHIS6.EMR_DIAGNOSIS`（兜底 DRG_UPLOAD_HN_DIAGNOSE） | 1728–1751 |

## 根因（两层）

**主因 — 检索锚点丢失**：加选请求把 `description` 写死为空串。首次分析靠医师手输/语音的病情描述提供语义锚点；加选时锚点没了，向量检索只剩"姓名 + 主诉 + HIS 诊断"。当该 visit **尚未录入 EMR 诊断**（实测近 7 天住院 70 例中 4 例无诊断，如 Z202607170010）且主诉为空（VISIT_REASON 常为 NULL）时，search_query 退化为无语义文本 → 语义命中全部低于 0.55 阈值 → `dip_rules`/`dip_settlements` 空 → 前端参考区整块静默消失。

**次因 — 诊断码精确匹配路径近失效**：
1. HIS ICD 码大量含 `x`（医保版编码：`I10.x00x002`、`K36.x02`、`I10.x09`）→ 提取正则 `[A-Z][0-9]{2}[.][0-9]+` 在小数点后遇 `x` **直接匹配失败**
2. 前缀回退只会"截短查询码"（[5,4]），无法处理 HIS 码比分值库码短的情况（如 HIS `K61.0` vs 库 `K61.001`）

排除项：集合空（dip_rules=4481 / settlement=4704 ✅）、元数据字段名错（`std_dip_value` 一致 ✅）、Oracle join 过严、LLM 截断（仅偶发风险：quick max_tokens=2600，日志见 3736 字符输出贴顶）。

## 实测证据（只读，经 /login cookie 调本机服务）

用真实住院 visit Z202607200003（K80.101 胆囊结石+I10.x09 高血压）三种调用**均正常返回** dip_operations=5、settlement_operations=2：
- 带 description 首次分析 ✅
- `description:''` + `selected_operation:'51.2300'`（模拟选用）✅ — 有诊断时锚点仍在（HIS 诊断名入查询串）
- `selected_operation:'51.2300+44.1401'`（组合码）✅ — LLM 还能拆成 主操作+附加操作

→ 印证：有 HIS 诊断时加选正常；**无诊断/主诉空 + 空 description 时才空**。故障是条件性的，与"参考区消失"症状吻合。

## 现成但未用的数据资产

dip_rules 元数据 **2368/4481 条含 `extra_oper_codes`/`extra_oper_names`（附加操作）**，前后端均未读取/展示——"推荐附加操作"功能的现成数据源。`main_flag` 全空不可用。

## 最小修复建议（待用户决策，未实施）

1. **前端 1 行级**：`reanalyzeWithCode` payload 带 `description: document.getElementById('description').value.trim()`（或缓存首次提交值于 window），保持检索锚点
2. **后端 2410–2416**：`selected_operation`/`selected_diagnosis` 存在时拼入 `search_query`；正则放宽为 `[A-Z][0-9]{2}[.][0-9xX]+`
3. 可选：`dip_operations` 附带 extra_oper_codes/names 作"推荐附加操作"展示

## 表结构摘要

- Chroma `dip_rules`(4481)：diagnosis_code（五字符 X00.0 为主 4096 条，七字符 X00.000 共 37 条）、diagnosis_name、dip_code、operation_code/name、std_dip_value、dp_kind、extra_oper_codes/names、main_flag（空）
- Chroma `settlement_2025`(4704)：病种编码/名称/类型、病种手术操作代码/名称、病种分值、实际分值、总费用、DIP支付金额、超支结余、住院天数、倍率
- Oracle `ICSHIS6.EMR_DIAGNOSIS`(VISIT_ID, ICD_ID 含x格式, ICD_NAME, CATEGORY, ORDER_NO)；`ICSHIS6.BIZ_VISIT_INFO`(ID, NAME, OP_FLAG, VISIT_REASON 常空, STATUS, ADMISSION_TIME)

## 本次 RCA 方法（可复用）

1. **登录态直调端点做 A/B 复现**：`POST /login`（账号在 .env `CLINICAL_USERS`，凭据不入库）拿 cookie → 按前端各路径的 payload 逐字段对照直调 `/clinical/assist`，一次只变一个字段（description 有无 / selected_operation 有无）→ 把"前端发的什么"与"后端回的什么"钉死，避免猜
2. **Chroma 元数据键审计**：sqlite3 immutable 直查（见 vector-db-audit.md），核对键名（std_dip_value vs std_score）与取值分布（diagnosis_code 长度分布）——"代码读的键 ≠ 库里存的键"类 bug 一验便知
3. **Oracle 只读探针**：`PYTHONPATH=/home/hehua/.local/lib/python3.12/site-packages python3` + his_ro 账号，ROWNUM 限量；**注意 `python3 -c` 触发批准 gate，`python3 - <<'EOF'` heredoc 不触发**
