# 病种驱动指南共识管线（disease_pipeline.py）

需求4 产物（2026-07-20 session 23）。以结算 Top 病种为关键词自动建设指南/共识全文库：
**AnySearch 发现 → 全文抓取 → guidelines.json → curate_guidelines.py 治理 → import_knowledge_base_v3 向量化 → rsync 展示页上网站**。

⚠️ 2026-07-21 起，v2 导入已废弃。新增治理层 `curate_guidelines.py`（用户五条规则：近3年时效/同族新版优先(更新件除外)/同源择优/参考文献清洗/网页展示完整原文含参考文献），产出 `curated/guidelines_curated.json`+`clean/`+`display/`。v3 导入按块级全局去重，元数据带 year/local_url/kept_as。

## 文件清单

| 文件 | 作用 |
|:--|:--|
| `/home/hehua/guidelines_scraper/disease_pipeline.py` | 管线主脚本（/usr/bin/python3 运行） |
| `pipeline_urls.json` | discover 产物：候选 URL 池（含 disease/title/type） |
| `pipeline_state.json` | 断点状态：`done` 列表 + `failed` {url: 次数} |
| `pipeline_full.log` | 运行日志 |
| `content/guidelines.json` | 合并后的总索引（202 条，pub_date 字段是抓取年不可信，年份以标题解析为准） |
| `curate_guidelines.py` | 治理脚本：家族分组(标准号/归一化标题/prefix合并)+时效+择优+清洗+展示页导出 |
| `import_knowledge_base_v3.py` | 治理产物向量化（替代 v2） |
| `content/*.md` | 全文 Markdown（文件名含 `**原文**` URL frontmatter） |

## 运行方式

```bash
cd /home/hehua/guidelines_scraper
/usr/bin/python3 disease_pipeline.py --discover [--top N]   # 病种检索 → pipeline_urls.json
/usr/bin/python3 disease_pipeline.py --fetch                # 断点续抓全文 → md + 合并 json
/usr/bin/python3 disease_pipeline.py --all                  # 两步连跑
/usr/bin/python3 curate_guidelines.py                     # 治理: curated/{clean,display,*.json}（只读原始库）
systemctl --user stop rag-service.service                   # 停服避免集合句柄冲突
/usr/bin/python3 import_knowledge_base_v3.py                # 向量化 guidelines（~10min，块级去重）
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
