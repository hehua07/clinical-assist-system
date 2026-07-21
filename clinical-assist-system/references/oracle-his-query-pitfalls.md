# Oracle HIS 查询陷阱（ICSHIS6 @ 192.168.20.49:1521/HISEMR）

对和华 HIS Oracle 库写批量/分页查询前必读。2026-07-21 `ingest_emr_records.py` 首跑 ORA-01722 确诊，以下三条均为实测。

## 1. EMR.ID 是 VARCHAR2，不是数字

- `ICSHIS6.EMR.ID` = **VARCHAR2**，字母数字混编（如 `0G3VI0JE5UUHQN8P`），16 位定宽编码。`EMR_ELEMENT.EMR_ID`、`EMR.VISIT_ID` 同为 VARCHAR2。
- **坑**：`WHERE ID > :int`（绑定 int）→ Oracle 对整列做隐式 `TO_NUMBER` → 遇非数字值报 **ORA-01722 无效数字**。
- 键控分页必须绑**字符串**；定宽编码下字典序单调递增，可直接作分页键（`ORDER BY ID` + `max(emr_ids)` 取字符串 max 一致）。

## 2. Oracle 空串 = NULL

- 字符串分页的下界初始值**不能是 `''`**：`ID > ''` 即 `ID > NULL` → UNKNOWN → 静默返回 0 行（不报错，最阴的一种）。
- 正确写法 = 首轮在 SQL 层省略分页条件（条件 SQL），不要靠绑定值 hack：

```python
if st["last_id"]:
    cur.execute("""SELECT ... FROM ICSHIS6.EMR
        WHERE NAME IN (:1,:2,:3,:4) AND EMR_TIME >= ADD_MONTHS(SYSDATE, -:5)
          AND ID > :6
        ORDER BY ID FETCH NEXT 50 ROWS ONLY""", [*DOC_TYPES, months, st["last_id"]])
else:
    cur.execute("""SELECT ... FROM ICSHIS6.EMR
        WHERE NAME IN (:1,:2,:3,:4) AND EMR_TIME >= ADD_MONTHS(SYSDATE, -:5)
        ORDER BY ID FETCH NEXT 50 ROWS ONLY""", [*DOC_TYPES, months])
```

## 3. 写查询前先探列类型，不凭列名猜

名叫 `ID` 的列照样是字符串。his_ro 只读账号可直接查数据字典：

```python
cur.execute("SELECT COLUMN_NAME, DATA_TYPE FROM ALL_TAB_COLUMNS "
            "WHERE OWNER='ICSHIS6' AND TABLE_NAME='EMR'")
```

新表/新脚本第一步先跑这个，再写 WHERE 条件。

## 4. 分页 state 持久化

state JSON 的 `last_id` 存字符串；load 时用 `str(x or "")` 兼容历史 int 初始值（`0 → ''`），防止旧 state 文件把 int 带进绑定变量再次触发 ORA-01722。
