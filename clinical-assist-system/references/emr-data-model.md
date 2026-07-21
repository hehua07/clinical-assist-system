# Oracle EMR 数据模型摸底（病历批量向量化用）

> 2026-07-21 只读侦察（his_ro @ 192.168.20.49:1521/HISEMR，schema ICSHIS6）。全部 SELECT、样本 ROWNUM≤10、COUNT 带 call_timeout 保护。来源：rag_service.py 逐行核读 + 数据字典 + 实测 COUNT。

## 核心结论

1. **EMR + EMR_ELEMENT 是全院病历文书中心**：EMR（文档头，388K 份）按 `NAME` 区分文书类型，正文拆在 EMR_ELEMENT（16.1M 行）的 `ELEMENT_NAME/ELEMENT_VALUE`。入院/病程/出院/手术记录全在这里，**不在独立表**。
2. **DRG_UPLOAD_HN_* 系列已停更**（全部止于 2026-02-06，近一年仅 3-328 条）：是 2022-11~2026-02 医保 DRG 上传快照。`ingest_visits`/`ingest_firstpage`/`_get_patient_clinical_data` 里的 DRG 回退查询导的是死数据，不能当批量主源。影像描述正文（IMAGEDESCRIBE）只有这系列表里有，实时 EMR_PACS_REPORT 只有诊断结论（均 28 字）。
3. **出院小结存在**：EMR 文书 `出院记录_NEW`（14,411 份，全文档均 1,306 字）+ `日间手术24小时入出院记录`（6,768，仅 121 字/份、模板化，建议过滤或降权）+ 病种小结（胆囊 365/疝气 106）。元素：入院时主要症状及体征/住院治疗经过/主要化验结果/特殊检查及重要会诊/出院情况/出院医嘱。
4. **BIZ_ORDER 才是全量医嘱主表**（835K 行，179K/年）；代码在用的 BIZ_ORDER_MEDTEC 只是医技医嘱（305K）。

## 文书类型 → 量（全量 / 近一年 / 整文档均字）

| EMR.NAME | 全量 | 近1年 | 均字/份 |
|---|--:|--:|--:|
| 入院记录（全院通用） | 14,557 | 1,011 | 5,070 |
| 病程记录 | 14,656 | 1,094 | 2,238 |
| 出院记录_NEW | 14,411 | 1,283 | 1,306 |
| 手术记录单 | 13,315 | 905 | 587 |
| 日间手术24小时入出院记录 | 6,768 | 3,279 | 121（低价值） |
| 日间手术记录病程记录 | 5,956 | 2,918 | 103（低价值） |
| 住院病案首页(2020版) | 21,864 | 4,659 | — |
| 新版西医病历（实为门诊模板：卡号/处方信息） | 46,986 | 23,221 | 511 |

- 无独立"首次病程记录"文书名（含在病程记录里）。
- 核心住院文书 ≈ 4,300 份/年，全量 ≈ 5.7 万份 → 800 字分块约 20 万 chunks，qwen3-embedding 几小时量级。

## 关键表速查

| 用途 | 表 | 关键字段 | 量（全/近1年） |
|---|---|---|--:|
| 就诊索引 | BIZ_VISIT_INFO | ID, PATIENT_ID, VISIT_NO(住院号), OP_FLAG(**1=门诊/2=住院**), ADMISSION_TIME, DEPT_ID/ACCEPT_DEPT_ID→DICT_DEPT, ACCEPT_DOCTOR_ID→DICT_USER, ID_NO, BED_NO | 120K / 35.8K（门诊30.7K+住院5.1K） |
| 患者主索引 | BIZ_PATIENT | ID, NAME, ID_NO, PHONE_NO, POSTAL_ADDR/CURRENT_ADDR/HOUSEHOLD_REGISTER_ADDR, CONTACT/GUARDIAN* | 58.8K / 12.9K |
| 文书头/元素 | EMR / EMR_ELEMENT | EMR: ID, NAME, VISIT_ID, EMR_TIME, CREATE_USER_ID；ELEMENT: EMR_ID, ELEMENT_NAME, ELEMENT_VALUE, ORDER_NO, VALID | 388K / 96.8K；16.1M / 3.46M |
| 诊断 | EMR_DIAGNOSIS | VISIT_ID, ICD_ID, ICD_NAME, CATEGORY, ORDER_NO | 222K / 60.4K |
| 病案首页 | EMR_FIRST_PAGE(22K) + EMR_FIRST_PAGE_AUX(33.6K，含 CHIEF_COMPLAINT/PRESENT_ILLNESS) | VISIT_ID, ADMISSION_TIME, **LEAVE_HOSPITAL_TIME**, DAYS, 医师IDs | 4.8K/年(AUX) |
| 手术结构化 | EMR_OPERATION | VISIT_ID, OPERATION_NAME/_TIME/_LEVEL, MAIN_DOCTOR_ID, FINISH_TIME | 28.2K / 6K |
| 检验 | EMR_LIS_REPORT(151K) + _DETAIL(2.0M，~12项/张) | VISIT_ID, LAB_ITEM_NAME, LAB_TIME；ITEM_NAME/VALUE/UNIT/RANGE | 35.6K张/年 |
| 影像 | EMR_PACS_REPORT | VISIT_ID, BILL_TYPE, SCAN_PART, SCAN_TIME, DIAGNOSIS(CLOB 结论) | 48K / 11.6K |
| 门诊病历 | BIZ_OP_EMR | VISIT_ID, CHIEF_COMPLAINT/PRESENT_ILLNESS/PHYSICAL_EXAMINATION(CLOB) | 46.5K / 23K（主诉均8字，很简略） |

长文本元素均长（近1年 n=10）：体格检查 341、主要化验结果 296、鉴别诊断 196、入院时症状体征 194、出院情况 147、诊疗经过 142、出院医嘱 105、现病史 62、主诉 11。

## 数据坑（导出前必读）

- `BIZ_VISIT_INFO.DISCHARGE_TIME` 近一年**全空** → 出院时间用 `EMR_FIRST_PAGE.LEAVE_HOSPITAL_TIME` 或 `EMR.EMR_TIME`。
- EMR↔BIZ_VISIT_INFO 经 VISIT_ID JOIN 验证完好；VISIT_NO 即住院号（格式 2025003895）。
- EMR_ELEMENT 含**元素级 PII**：'姓名'(382K次)/'患者姓名'/'患者姓'/'联系电话'/'现住址'/'籍贯'/'卡号'/'住院号' 元素必须在导出时剔除。
- EMR_DATA / EMR_DATA_ORIGINAL 是 BLOB（PDF/二进制），向量化不用碰。
- 门诊病历文本极短，检索价值低；检验/影像/医嘱建议按就诊聚合摘要成 visit 级文档，而非逐条向量化。

## 批量导出推荐路径（勿循环 _get_patient_clinical_data）

该函数 per-visit 10+ 查询且 try/except 静默，且不拉 EMR 文书正文。推荐离线脚本三步：
1. 选文档：`SELECT ID,VISIT_ID,NAME,EMR_TIME FROM EMR WHERE NAME IN ('入院记录（全院通用）','病程记录','出院记录_NEW','手术记录单') AND EMR_TIME>=...` OFFSET/FETCH 分页
2. 拼正文：批拉 EMR_ELEMENT（EMR_ID IN 批）→ 剔 PII 元素 → ORDER_NO 拼接；JOIN BIZ_VISIT_INFO/DICT_DEPT/EMR_DIAGNOSIS 取 科室/诊断/时间 metadata
3. 800 字分块入新 collection（如 `emr_cases`），metadata: doc_type/dept/diagnosis_icd/emr_time/hash(VISIT_NO)；**别混入 hehua_visits**

## 脱敏建议

- 必脱：患者姓名（含元素级）、身份证 ID_NO/IDCARD/CARDNO、电话 PHONE_NO/CONTACT_PHONE_NO、住址/籍贯/单位/监护人联系人、住院号哈希化。
- 医生姓名：**保留**（本地院内库、溯源有价值；上云前现有 `_desensitize()` 已处理）。
- 复用 rag_service.py L2058 `_desensitize()`（身份证/手机号正则，CJK 边界用 `(?<!\d)(?!\d)` lookaround，不用 `\b`）。

## 只读侦察脚本套路（Oracle 生产库）

- `conn.call_timeout = 15000` 每语句限时，超时回退 ALL_TABLES.NUM_ROWS（统计估计，不扫表）。
- 数据字典 ALL_OBJECTS/ALL_TAB_COLUMNS 用 OFFSET/FETCH 每页 10 行翻页。
- 16M 行表 COUNT 实测 8s 可完成；GROUP BY NAME on 388K 行 <1s。
