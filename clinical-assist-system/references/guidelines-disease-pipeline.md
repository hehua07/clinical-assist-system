# 病种驱动指南共识管线（disease_pipeline.py）

需求4 产物（2026-07-20 session 23）。以结算 Top 病种为关键词自动建设指南/共识全文库：
**AnySearch 发现 → 全文抓取 → guidelines.json → curate_guidelines.py 治理 → import_knowledge_base_v3 向量化 → rsync 展示页上站**。

⚠️ 2026-07-21 起 v2 导入废弃：新增治理层 `curate_guidelines.py`（用户五条规则：近3年时效/同族新版优先·更新件除外/同源择优/参考文献清洗/网页展示完整原文含参考文献），产出 `curated/{guidelines_curated.json, guidelines_dropped.json, clean/, display/}`；v3 导入带块级全局去重，元数据含 year/local_url/kept_as。治理层数据坑见末节。

## 文件清单

| 文件 | 作用 |
|:--|:--|
| `/home/hehua/guidelines_scraper/disease_pipeline.py` | 管线主脚本（/usr/bin/python3 运行） |
| `pipeline_urls.json` | discover 产物：候选 URL 池（含 disease/title/type） |
| `pipeline_state.json` | 断点状态：`done` 列表 + `failed` {url: 次数} |
| `pipeline_full.log` | 运行日志 |
| `content/guidelines.json` | 合并后的总索引（202 条；pub_date 是抓取年不可信，年份以标题解析为准） |
| `curate_guidelines.py` | 治理脚本：家族分组(标准号code/归一化标题/prefix合并)+时效+同源择优+错抓检测+参考文献清洗+展示页导出 |
| `import_knowledge_base_v3.py` | 治理产物向量化（替代 v2；块级全局去重；元数据 year/local_url/kept_as） |
| `content/*.md` | 全文 Markdown（文件名含 `**原文**` URL frontmatter） |

## 运行方式

```bash
cd /home/hehua/guidelines_scraper
/usr/bin/python3 disease_pipeline.py --discover [--top N]   # 病种检索 → pipeline_urls.json
/usr/bin/python3 disease_pipeline.py --fetch                # 断点续抓全文 → md + 合并 json
/usr/bin/python3 disease_pipeline.py --all                  # 两步连跑
/usr/bin/python3 curate_guidelines.py                     # 治理: 只读原始库 → curated/{clean,display,*.json}
systemctl --user stop rag-service.service                 # 停服避免集合句柄冲突
/usr/bin/python3 import_knowledge_base_v3.py              # 向量化 guidelines（~10min，块级全局去重）
systemctl --user start rag-service.service
rsync -az --delete curated/display/ root@47.102.41.191:/var/www/hhysjt/guidelines/display/  # 展示页上站
```

- `--fetch` 幂等断点续跑：`done` 跳过、`failed>=2` 跳过。
- URL 三路分发：`.pdf` 直链→PyMuPDF；`guide.medlive.cn/guideline/N`→复用 guidelines_scraper 详情接口；其余→AnySearch extract。
- 正文 <1500 字丢弃（摘要页/付费墙自动过滤）。

## 坑与修法（全部已修，重开发时别回退）

**1. 境外站涓流下载挂死（EASL PDF，卡 7 分钟无超时）**
`requests.get(timeout=60)` 的非流式读在对方逐字节吐数据时永不触发。修法：流式 `iter_content` + 墙钟硬上限 90s + 体积上限 30MB，超时即抛错跳过。诊断手法：`ss -tnp | grep <pid>` 看 ESTABLISHED 连接对端 IP + `/proc/<pid>/wchan` 看 poll_schedule_timeout。

**2. merge-at-end + 断点续跑 = 孤儿条目（首轮被 kill 后丢 141 条）**
`fetch_all` 只在**全部跑完后**才把本轮 new_items 合并进 guidelines.json；而 state.done 是逐条落的。进程中途被杀 → 重启续跑时 done 条目被跳过、永远进不了 json（md 文件在盘但索引没有）。
对账补登法（reconcile）：扫 `content/2026-07-20_*.md`，正则 `\*\*原文\*\*: \[(https?://[^\]]+)\]` 取 URL，不在 guidelines.json 的解析 frontmatter（标题/来源/日期/关联病种）+ 正文前 300 字作 abstract 补登。**长期修法：把合并改成逐条增量（fetch 成功一条写一条）**。

**3. 失败 URL 无限重试风暴**
续跑只跳 done 不跳 failed → 每次运行都重试永久失败的页面（摘要页/付费墙）。修法：`failed` 从列表改成 `{url: 次数}`，>=2 次跳过。

**4. 域名质量**
文档分享站（renrendoc/book118/max.book118/cancer361/ye8.net）出 Preview 垃圾，已入 BLACKLIST；付费/摘要站靠 1500 字下限兜底。发现阶段每病种 2 条 query ×8 结果取前 6。

## 治理层 curate_guidelines.py 数据坑（2026-07-21 首轮全踩过，改规则前先读）

1. **抓取日污染发布年**：pipeline md frontmatter `**日期**: 2026-07-20` 是抓取日非发布日，82 篇年份曾因此全标 2026。年份证据优先级：标题年份 > frontmatter日期(≠文件名抓取日才采信) > 正文出版日期 > 期刊引用年（杂志, YYYY）> URL 路径年（uploads/2025/）。
2. **8位时间戳干扰年份正则**：`胃息肉病-202504100821` 会误判 2025——年份正则必须带 lookaround `(?<!\d)((?:19|20)\d{2})(?!\d)`。
3. **JSON 标题截断**：AnySearch 标题被截（如"指南共识_《中国慢性胆囊炎、胆囊结石内科"）→ 归一化族键变短、精确匹配无法成族。修法：prefix-merge（短键≥8字且是长键前缀则并族）+ 展示标题用 md 文件 H1 补全。
4. **标准号标题需独立族键**：`T_CACM1209-2019...` 按标题归一化会把全部 T_ 文档并成一族团灭（11 部中医指南险些全灭）——用标准号 `code:CACM1209` 作族键。
5. **错抓检测（标题↔正文不符）**：zgsyz.com 两篇文章正文错抓成 COVID 文（标题是肿瘤/直肠癌共识）。检测：标题去通用词后取≥2字疾病词，正文头部+中部采样零命中 → 判错抓淘汰（首轮淘汰 10 篇）。
6. **部分更新保护要带年份条件**："新版仅更新件则留旧版"规则若不看年份，会把同年不同源的长版本误判为旧版全文双保留（胆囊 2018 双份事故）。守卫：仅当 newest.year > older.year > 0 才触发。
7. **v3 导入块级全局去重**：跨文档同一文本块只留一份（首轮跳过 192 块），消除"同指南多来源"残留重复向量。
8. **前端改动验证要带 307+登录**：`curl /clinical/` 会 307→`/clinical`（无尾斜杠）再 302→/login；空响应≠旧版本。验证法：POST /login 取 `clinical_session` cookie → `-H "Cookie: ..."` 请求 `/clinical`（无斜杠）→ grep 标志串 ≥1。

## 网站为源同步架构（2026-07-21 session 31 需求4 起，向量库维护的主路径）

**网站 `https://www.hhysjt.com/guidelines/display/` 是指南全文的单一事实源（single source of truth）**。日常维护不再走"停服→import_knowledge_base_v3 全量导库"（那条路只剩灾难重建/初次建库用）；向量库由 `sync_guidelines_from_web.py` 每日从网站增量同步：

```
curate（治理/展示页生成）→ rsync --delete 上站 → sync_guidelines_from_web.py（网站→向量）
                                                    ↑ cron 4da787a0f65d 每日04:10 自动跑
```

### sync_guidelines_from_web.py（/home/hehua/guidelines_scraper/）

- **流程**：抓 index.html 解析页面清单 → 逐页抓取 → 提取 `gd-*` 机器 meta（year/publisher/journal/url/kept/family，curate 的 DISPLAY_TMPL 生成）+ `<article>` 正文 → 剥 md frontmatter → `clean_for_vector()` 清洗（复用 curate 规则，剔参考文献）→ md5 哈希比对 → 变更页删旧块+800/100 分块+qwen3-embedding+upsert；**网站上消失的页 → 按 local_url 扫库删向量**（相对/绝对双形态兼容）
- **local_url 一律写绝对地址** `https://www.hhysjt.com/guidelines/display/<slug>.html`（临床助手"原文链接"可直接点、可微信分享打开）
- **state**=`web_sync_state.json`（slug→hash/chunks/title，逐页落盘；删之=强制全量重建 ~15min/3000块）
- **flock 单实例锁** `/tmp/guidelines_websync.lock`——⚠️ **chroma 同库多写进程必坏**（session 31 晚事故：4 个幻影并发同步进程+pkill -9 → HNSW 段文件撕裂，集合读取即 SIGSEGV；取证见 `chromadb-segment-corruption-rebuild.md`）。任何写 chroma 的脚本都必须带单实例锁，且**绝不并发跑**
- **collection 用 `get_or_create_collection` 且 metadata 必须带 `hnsw:space: cosine`**（0.58 相关度阈值体系依赖；缺了空间度量默认 l2，阈值全乱）
- 中文文件名 URL 必须 `urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%")`，否则 urllib 抛 ascii 编码错
- 输出规范（cron no_agent 看门狗）：无变更静默；有变更/失败打印汇总（deliver=all 推微信）；索引不可达或失败率>20% 非零退出
- **增量不停服**：只 delete/upsert 既有集合（rag-service 无需重启）；唯一例外=集合 delete+recreate 后服务 init 期缓存的 `coll_guidelines` 句柄失效，必须重启 rag-service 重绑

### 下架坏条目标准流程（JUNK_FILES 机制，session 31 实测 8 篇）

1. 从 `curated/guidelines_curated.json` 拿坏条目的 `orig_md` 文件名（含 URL 哈希前缀，如 `htmlaf008a28`）
2. 把哈希前缀加进 `curate_guidelines.py` 的 `JUNK_FILES` 元组（**按文件哈希而非标题排除**——同标题不同源有好有坏，如痔病 2020 两个源一残一全）
3. 重跑 curate：坏条目在**过滤阶段**（家族竞选之前）被剔除 → **同族全文版自动扶正**（痔病换上 2025 中西医全文版、胆道感染换上 2021 版，均为淘汰池兄弟自动晋级）；无兄弟的（付费墙/抓取残缺）出库待重抓
4. 清孤儿：display/clean 目录里不在新 curated 集合的旧文件手动删（curate 只写不删）
5. `rsync -az --delete curated/display/ root@47.102.41.191:/var/www/hhysjt/guidelines/display/` 上站
6. 下一次 sync 自动从向量库删掉下架页的块（无需手工动向量）

### 审计全文覆盖的快查法

`guidelines_curated.json` 自带 `chars_clean` 字段：排序列出 <3000 字的逐篇目检——指南全文正常 5000+ 字；1000-3000 字的多为导航垃圾/摘要页/付费墙著录/新闻稿（注意：临床路径类本身短，2460 字属正常勿误杀）。

## 微信收料通道（2026-07-21 session 27 需求1c，ingest_single_guideline.py）

用户平时工作中发现指南/共识/高价值资料，经微信发链接给助理。标准动作（不要手工走全流程）：

```bash
cd /home/hehua/guidelines_scraper
/usr/bin/python3 ingest_single_guideline.py "<URL>" [--title 手动标题] [--publisher 发布机构] [--journal 期刊名] [--no-sync]
```

脚本自动完成：三路抓取（pdf/medlive/AnySearch extract，复用 disease_pipeline）→ 按 pipeline 格式存 `content/YYYY-MM-DD_hash_标题.md` + 增量并入 `content/guidelines.json`（按 URL 幂等去重）→ **重跑 curate 全量治理**（家族去重/时效/清洗/展示页/索引全自动；新文档可能顶掉同族旧版或被判淘汰，行为与批量治理一致）→ 在新 curated.json 中按 URL 定位本篇 → 增量向量 upsert（先按 url 删旧块再加新块，**集合不重建、服务不用停**）→ rsync 展示页上站（--delete 镜像）→ 打印确认摘要（标题/年份/kept_as/块数/向量总数/site_sync）。

- 文档被治理淘汰时脚本打印原因（正文不足/抓取错位/解读类），回复用户"该链接未通过质量关卡"并附原因。
- 同 URL 重发安全：guidelines.json 幂等、向量先删后加，不会重复。
- 实测：2026-07-21 以 medsci 链接跑通全程（7287字→保留为全文-最新版→10块→rsync ok），库 138→139 篇。
- 收料后顺手更新一次覆盖核查（见下节）。

## 病种覆盖核查与缺口通知（2026-07-21 session 27 需求1b）

- 病种清单：`disease_pipeline.py` 内 TOP 病种 34 个（结算口径）。
- 核查法：每病种配同义词表，对 `curated/guidelines_curated.json` 标题模糊匹配；**弱覆盖**判定=最佳匹配年份<2018或未知、标题带乱码/竖线垃圾、仅地方/团体/解读类单篇。
- 首查（session 27）：34/34 标题级全覆盖；7 个弱覆盖（膀胱结石/短暂性脑缺血发作/翼状胬肉/胆管结石/带状疱疹/肩周炎/颈椎病）已一次性微信通知用户人工核实。
- **一次性微信通知固定做法**：no_agent 脚本直出（如 `~/.hermes/scripts/guideline_gap_report.py`）+ 一次性 cron（schedule '1m', repeat=1, deliver='all'），微信端即收到；job 跑完自动消失属正常。

## AnySearch 使用要点

- CLI：`/usr/bin/python3 /home/hehua/.hermes/skills/anysearch/scripts/anysearch_cli.py search|extract "<query>" --max_results 8`
- key 在该 skill 的 `.env`（as_sk_ 前缀）；服务端只认 `Authorization: Bearer`。
- 搜索结果解析 CLI 输出的 `### N. 标题` + `- **URL**: ...` 行；extract 返回正文 markdown。

## 附：SenseVoice ASR（需求3d）安装/验证备查

- 依赖：`/usr/bin/python3 -m pip install --break-system-packages sherpa-onnx numpy`（**必须系统解释器**，见 SKILL.md 修改规范的 pip 陷阱条）。
- 模型：`~/rag-service.bak/models/sense-voice/`（model.int8.onnx 237MB + tokens.txt），仓库 `csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09`（hf-mirror 可直连；**注意 2024-07-17 的 int8 版不存在**，2024-07-17 只有 fp32）。
- 验证用仓库官方 `test_wavs/zh.wav`（5.6s 中文，期望输出「放时间早上九点至下午五点」）。**不要用 Edge TTS 现生成中文样本**：限流时会给出截断的 2.1s 坏音频，模型对坏音频会幻觉输出英文（实测 "SIX FIVE THREE"），极易误判 ASR 管线坏。
- 端点 `POST /clinical/transcribe`（表单 file），ffmpeg 转 16k 单声道 f32le → numpy → `sherpa_onnx.OfflineRecognizer`；模型懒加载 0.6s，识别速度 ~60 倍实时。

## 网站同步

```bash
rsync -avz --delete -e "ssh -o StrictHostKeyChecking=no" \
  /home/hehua/guidelines_scraper/content/ \
  root@47.102.41.191:/var/www/hhysjt/guidelines/
```
（`guidelines_scraper.py --deploy` 内嵌同一命令。`--delete` 是镜像语义，目标目录多余文件会被删。）
