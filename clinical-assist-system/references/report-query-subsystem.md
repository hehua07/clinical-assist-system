# 报告查询子系统（患者自助：身份证后6位查检验报告）

> 2026-07-20 重建。患者入口 `https://www.hhysjt.com/report/`，微信公众号/浏览器通用。
> 7-19 曾被 hermes dashboard 改造误伤（/report/ 403 + /api/ 前缀被抢），修复过程见 SKILL.md session-19 记录。

## 数据流

```
患者浏览器/微信 → www.hhysjt.com/report/  (nginx → 127.0.0.1:18790/wechat/)
                → FastAPI 返回静态页 wechat_report_page.html
页面 JS → /api/search-id6?id6=XXXXXX      (nginx 精确匹配 → 18790)
        → 返回该后6位的就诊列表（身份证打码 idn[:4]+********+idn[-4:]）
患者选一条 → /lab-results/{visit_id}       (nginx 前缀 → 18790)
           → Oracle 实时查询，返回检验报告
```

## 服务端点（rag_service.py，均在 18790）

| 端点 | 作用 | 数据源 |
|:--|:--|:--|
| `GET /wechat/` `/wechat/report-search` | 返回查询页 HTML（启动时一次性读入内存 `_WECHAT_PAGE`） | wechat_report_page.html |
| `GET /api/search-id6?id6=` | 身份证后6位查就诊列表，打码返回 | ICSHIS6.BIZ_VISIT_INFO.ID_NO |
| `GET /lab-results/{visit_id}` | 该就诊的检验报告（按报告分组） | LIS 相关表 |
| `GET /reports/{visit_id}` | 综合报告（检验+影像+胃肠镜） | 多表 |
| `GET /imaging-results/{visit_id}` | 影像报告（彩超/CT/MR） | PACS 相关表 |
| `GET /all-reports/{visit_id}` | 全部报告汇总 | 多表 |
| `GET /patients/search?query= / id_no=` | 按姓名/身份证号查就诊（医生用，**不公网暴露**） | BIZ_VISIT_INFO |
| `GET /patients/today` | 当日就诊列表（无 ID_NO 字段） | BIZ_VISIT_INFO |

## nginx 路由规则（/etc/nginx/conf.d/hhysjt.conf，2026-07-20 版）

- `/report/` → `http://127.0.0.1:18790/wechat/`（注意带尾斜杠的路径映射）
- `location = /api/search-id6`（**精确匹配**）→ 18790，无密码
- `/lab-results/` `/reports/` `/imaging-results/` `/all-reports/` → 18790
- 通用 `/api/` → hermes dashboard 18080（带 basic auth）
- **⚠️ /api/ 是两服务争夺前缀**：靠 nginx 最长前缀匹配共存，精确 location 优先。改动任一侧配置时不得删除另一侧
- `/patients/` 不公网暴露（全量患者数据，老配置 bak4 曾有，已不恢复）
- `/v1/` → 8088 死代理已删除（阿里云 8088 无服务）

## HIS 数据事实

- Oracle `192.168.20.49:1521/HISEMR`，只读账号 `his_ro/his_ro`
- BIZ_VISIT_INFO 约 12万条就诊，其中 11.2万条带 ID_NO（93% 覆盖）
- 不同患者可撞身份证后6位 → 页面设计为列表选择，属正常
- 验证用真实数据：用只读账号 `SELECT SUBSTR(ID_NO,-6) ... WHERE ROWNUM<=3` 取真实后6位测试，别用编造值（000000 只能证明端点活着，不能证明有数据）

## 已知设计取舍

- search-id6 公开免密是**患者自助的既有设计**（输出已打码），不要擅自加密码破坏公众号入口
- 知道 visit_id 即可看该就诊报告（无会话绑定）——既有设计，如需收紧需与站长确认
- 页面 HTML 改动必须重启 rag-service 才生效（`_WECHAT_PAGE` 启动时读入内存）
