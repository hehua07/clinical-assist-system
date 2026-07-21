# /clinical 前端分析路径（2026-07-19 分步分析改造后）

页面 `rag-service.bak/clinical_assist_page.html` 有**四条**进入后端 `/clinical/assist` 的 JS 路径，排查"卡住/没反应"时必须先分清用户点的是哪一条：

| 入口 | JS 函数 | 发送的 mode | 后端行为 |
|---|---|---|---|
| 「🤖 生成AI建议」主按钮 | `submitAssist()` | `quick` | 首诊：诊断+鉴别+检查建议（2026-07-20 起输出去 DIP） |
| 结果页底部「🔍 二次分析」按钮 | `submitDetail()` | `detail` + `prior_analysis`（回传首诊 JSON） | 医嘱+合规+病程，与首诊一致 |
| 诊断/操作下拉旁「🔄 重新分析」 | `reanalyzeWithSelection()` | `quick`（2026-07-20 起，原为不带 mode 走 full 11s+） | 带选中诊断/操作重跑首诊，~6s |
| 操作候选/参考的「选用」按钮 | `selectOperation()` → `reanalyzeWithCode()` | `quick`（2026-07-20 起） | 带 selected_operation 重跑首诊。**⚠️ payload 硬编码 `description:''`（1831–1836 行）**——检索失去首次分析的语义锚点，见下节 |

full 模式（旧 10 字段大 prompt）自此无前端入口，仅作后端兜底。

## ⚠️ 加选后参考列表消失（不卡死、不报错）= 检索锚点丢失（2026-07-21 确诊，未修复）

「选用」路径发的请求**不带病情描述**（`description:''`），而后端 `search_query` = description + 姓名/主诉 + HIS 诊断（rag_service.py 2410–2416）。当 visit 无 EMR 诊断（近 7 天住院约 6%）且主诉为空时，查询串退化为无语义文本，向量命中全低于 0.55 阈值 → `dip_operations`/`settlement_operations` 空 → `renderOperationReferences` 静默 return（HTML 1766 行），参考区整块消失。**有诊断的 visit 加选完全正常**（A/B 实测三种 payload 均返回数据）。与「遮罩泄漏」的鉴别：遮罩泄漏 = 数据已渲染但被转圈盖住；本条 = 响应 200 但列表字段为空、区域被前端主动隐藏。次因：HIS 诊断码含 `x`（`I10.x00x002`）使后端提取正则失效，精确匹配路径名存实亡。完整 RCA 与修复建议见 `references/operation-reselect-empty-rca.md`。

## 登录态直调端点 A/B 复现法（2026-07-21 新增）

鉴权上线后 curl 直调需先取 cookie；按前端真实 payload 逐字段对照调用、一次只变一个字段，是区分"前端发错/后端算错"的最快手段：

```bash
curl -s -c /tmp/ck.txt -X POST http://localhost:18790/login -H 'Content-Type: application/json' \
  -d '{"username":"<账号>","password":"<密码>"}'        # 账号在 .env CLINICAL_USERS，凭据不入库
# A：模拟首次分析（带 description）
curl -s -b /tmp/ck.txt -m 300 -X POST http://localhost:18790/clinical/assist -H 'Content-Type: application/json' \
  -d '{"description":"...","patient_name":"...","visit_id":"...","mode":"quick"}'
# B：模拟选用（description 空 + selected_operation）——与 A 对比 dip_operations/settlement_operations 数量
curl -s -b /tmp/ck.txt -m 300 -X POST http://localhost:18790/clinical/assist -H 'Content-Type: application/json' \
  -d '{"description":"","patient_name":"...","visit_id":"...","selected_operation":"51.2300","mode":"quick"}'
```

「二次分析」的词义陷阱：**2026-07-20 用户亲口纠正——他说的「二次分析」= 更改主诊断/主操作后的重新分析（③/④），不是②**。报"二次分析卡住"时先确认指的是哪个按钮，别按自己改造时的新定义对号入座。

## 「卡住」诊断启发式（先定前端还是后端，30 秒）

```bash
journalctl --user -u rag-service.service --since "10 min ago" --no-pager | grep -E "\[LLM\]|\[TIMER\]|POST /clinical"
```

- 有点击时间之后的请求记录 → 后端链路问题（Oracle 查询/向量检索/DeepSeek/GLM 降级链）
- **没有任何新请求记录 → 前端 JS 根本没发出 fetch**（dispatcher 缺分支、按钮作用域、JS 异常、或点错了按钮），不用去查后端
- **有请求且全部 200 返回 → 后端无罪**：浏览器缓存了旧页面（让用户 Ctrl+F5 强刷）、长生成（12s+）被感知为卡住、或 nginx/frp 中间层截断

## ⚠️ 新增 Tab 三触点（2026-07-20 确诊 bug）

`clinical_assist_page.html` 加新 Tab 必须**同时**改三处，漏一处即"点击无反应"：

1. 按钮：`<button class="tab" onclick="switchTab('xxx')">`
2. 内容区：`<div id="tab-xxx" class="tab-content" style="display:none">`
3. **dispatcher 分支**：`switchTab()` 里 `else if (tab === 'xxx') { ... }`（含 `querySelectorAll('.tab')[序号]` 激活 + 内容区 display）

2026-07-20 病例：①②已加、漏③ → 点击后所有 tab 被取消激活、所有内容被隐藏，无匹配分支 → 页面空白，用户报"中医辨证点击后没有反应"。**静态 grep 验证法**：改完后 `grep -n "switchTab" page.html`，确认每个 onclick 参数在函数体内都有对应分支。

## ⚠️ 全屏遮罩泄漏（2026-07-20 确诊 bug，"卡住"的头号假象）

`loadingIndicator` 是全屏 overlay（`loading-overlay`）。**只 `classList.add('active')` 不 `remove` = 请求早已 200 返回、结果已渲染，但遮罩永远盖住页面**，用户看到的就是"卡死在转圈"。排查法：

```bash
grep -n "loadingIndicator" clinical_assist_page.html
# 逐个引用点核对：每个 add('active') 是否在 成功/失败/异常 全路径都有配对 remove
# finally 块里 remove 最保险；.then().catch() 两条链都要补
```

病例：`reanalyzeWithCode()`（「选用」按钮）加了遮罩，`.then`/`.catch` 都漏 remove → 用户更改主操作点「选用」后页面永远转圈，报"二次分析卡住"。journal 同期全 200——**日志全绿 + 页面停在转圈遮罩 = 遮罩泄漏，不是后端卡**。

同类隐患：函数顶部静默守卫 `if (!x) return;`——守卫命中时不转圈不报错，用户点按钮"完全没反应"。加守卫时顺手加用户可见反馈（toast/error 提示）。

## ⚠️ 页面在内存：改 HTML 必须重启服务

`rag_service.py` 启动时把 HTML 一次性读入 `_CLINICAL_PAGE` 内存变量（`@app.get("/clinical")` 直接返回它）。**改完 HTML 不重启 = 改动不生效**，curl/grep 文件确认内容对了也不够。生效链路：改文件 → `systemctl --user restart rag-service.service` → 用户端 Ctrl+F5 强刷（防浏览器缓存旧页）。

## 已决案例

- **2026-07-20 "更改主操作后二次分析卡住"** = `reanalyzeWithCode()` 遮罩泄漏（见上节）。注意时序假象：用户**先**报"二次分析卡住"，当时按②排查后端全绿、嫌疑误判为浏览器缓存；用户纠正是③/④后才抓到真凶——**词义没对齐，排查方向就错**。
- **"中医辨证点击无反应"** = switchTab 缺 tcm 分支（见上），journal 全程无 `/clinical/tcm` 请求 → 前端从未发出。
- **"二次分析还是被卡住"（首轮报告）** = 排查 journal 23:45-00:00：用户全部 `/clinical/assist` 请求 200 返回（quick 5-7s / detail 11-13s），无卡死记录 → 后端无罪。当时嫌疑收敛为浏览器缓存/长生成；后证实真凶是④的遮罩泄漏。

## ⚠️ 文档先行未落盘（2026-07-20 元教训）

session 19 的 Changelog 已写"switchTab 修复在文件中已生效"，但实际 **HTML 补丁从未落盘**——下一个 session 读文件才发现分支仍缺。规矩：**先改代码、grep 文件验证、重启后 grep 公网页面验证，三步都过了才准在文档里写"已修复"**。文档里只写"已落盘+已验证"的事实，不写计划。

## 验证用例（后端链路自检，排除后端嫌疑用）

```bash
# quick
curl -s -m 280 -X POST http://127.0.0.1:18790/clinical/assist -H 'Content-Type: application/json' \
  -d '{"patient_name":"蔡维良","mode":"quick"}'
# detail（prior_analysis 用上一步返回的 analysis）
curl -s -m 280 -X POST http://127.0.0.1:18790/clinical/assist -H 'Content-Type: application/json' \
  -d '{"patient_name":"蔡维良","mode":"detail","prior_analysis":{...},"description":"（沿用首诊）"}'
```

两条都正常（实测 6s/7s）则后端无罪，全力查前端 JS console。
