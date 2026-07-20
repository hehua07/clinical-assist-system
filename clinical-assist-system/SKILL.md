---
name: clinical-assist-system
description: "寿县和华医院临床AI辅助系统（RAG + vLLM + DIP匹配）的调试记录、当前状态、已知问题和修复方案。任何智能体对系统进行修改后，必须更新此技能。"
version: 1.14.0
author: hehua
platforms: [linux, macos, windows]
---

# 临床AI辅助系统调试状态

## 当前状态（2026-07-19）

| 组件 | 状态 | 备注 |
|:--|:--:|:--|
| vLLM | ✅ 运行 | Qwen3-32B-NVFP4, :8200, max-model-len=16384, **prefix caching 已启用** |
| RAG服务 | ✅ 运行 | :18790, systemd用户服务(开机自启), 路径 /home/hehua/rag-service.bak/ |
| Ollama | ✅ 运行 | :11434, qwen3-embedding (v0.32.1, **GPU模式**) |
| ChromaDB | ✅ 运行 | dip_rules=4481, settlement_2025=4704, **guidelines=2221（133篇全文，session 23 病种管线重建，检索实测命中新指南）**, compliance=4, tcm_knowledge=3438 |
| LLM引擎 | 🌐 DeepSeek在线（主） | `RAG_LLM_PROVIDER=online`（.env），DeepSeek→GLM→本地vLLM自动降级 + 调用前脱敏；回切本地改 .env 一行重启。实测 quick 6s/detail 7s |
| 前端页面 | ✅ 全部正常（2026-07-20 session 19 再修复 /report/） | `https://www.hhysjt.com/clinical/`、`/guideline/search`、`/guidelines/`、`/report/` 公网全部 200，HTTP→HTTPS 301 正常。修复：SSH 直连（公钥已装）+ 本地构建 + scp 上传 hhysjt.conf（基于 bak4 + 收回悬空 location + 新增 /guideline 反代）→ nginx reload。**此后阿里云操作走 SSH 不再走 Workbench**，见 aliyun-nginx-proxy-location skill |
| dip_operations | ✅ 正常 | 淮南分值库操作列表(20+条)，按分值降序 |
| settlement_operations | ✅ 正常 | 结算参考数据(2-3条) |
| 登录鉴权 | ✅ 已上线（session 22） | HMAC签名会话Cookie+登录页；`/clinical*` `/patients/` `/query` `/counts` `/ingest_*` `/sync/` `/compliance/`(除query) 需登录，患者自查与指南库开放。账号在 .env `CLINICAL_USERS`（凭据不入库），设计见「医师端登录鉴权」节 |
| 语音输入 | ✅ 已上线（session 23） | 浏览器 MediaRecorder → `POST /clinical/transcribe` → SenseVoice Small int8（sherpa-onnx，纯 CPU，加载 0.6s，5.6s 音频 0.09s 出结果）。模型在 `~/rag-service.bak/models/sense-voice/`（237MB，已入 .gitignore 勿提交）。弃用 Web Speech API 的原因：国内浏览器不可用 |
| 网站巡检 | ✅ 已上线（session 23） | cron `739bd07f80b9` 每5分钟跑 `~/.hermes/scripts/hhysjt_watchdog.py`（9项：RAG/vLLM/Ollama/frp/公网四端点/磁盘），全绿静默、异常/恢复推微信（deliver=all，no_agent） |

### 性能数据（实测 2026-07-18）

| 优化阶段 | 耗时 | 输出字符 | 提速 |
|:--|:--|:--|:--|
| 原始 | ~130s | ~3000 | — |
| + prompt精简 | ~99s | ~1900 | -24% |
| + prefix caching | ~93s | ~1800 | -6%（收益很小） |
| **总计** | | | **-28%** |

**关键结论**：prefix caching 仅省 ~5s，因为 system prompt prefill（~2000 tokens）仅占总耗时的很小一部分，而 **LLM 生成（~1000 tokens @ 10 tps ≈ 100s）才是瓶颈**。真正大幅提速需要换更小模型。

## 已知问题

### 4. nginx proxy_pass 配置：\$ 转义陷阱 + 盲打远程终端的限制

**场景**: 通过阿里云 Workbench（Firefox 浏览器 canvas 终端）配置 nginx proxy_pass。

**根因一 — \$ 转义**: 用 `python3 -c "..."`（双引号）写 nginx 配置时，`$host`、`$remote_addr` 等 nginx 变量会被 shell 展开为空字符串，导致实际写入的文件内容错误。正确方式：
- `python3 -c '...'`（单引号包裹代码）
- `cat > file << 'EOF'`（heredoc 分隔符加引号）
- 但在 Workbench canvas 终端中，多行 heredoc 可能因 `type` 动作逐字发送而无法正确终止

**根因二 — canvas 终端盲打**: Aliyun Workbench 使用 xterm.js 渲染为 HTML Canvas，AX 树中无可聚焦的文本输入元素。`computer_use` 的 `type` 动作虽可输入字符，但：
- 无法看到终端反馈（无 stdout 捕获）
- `key` 动作的 Enter 在 background 模式下不可用
- 通过 `type` 末尾加 `\n` 模拟 Enter，但 heredoc 终止符可能因缺少最终换行而未触发
- 无法验证命令是否成功执行

**解法**: 对于 canvas 渲染的远程终端，优先使用单行命令（不用 heredoc）或确保用户手动执行最终命令。

**用户偏好总结（基于session 14-15用户反馈）**：
1. 用户偏好直接可粘贴的bash命令 >> 解释说明 >> 交互式编辑器（vi/vim）。
   - 当给出vi编辑指令时，用户回复"我在阿里云上到底怎么输入"表示抗拒
   - 正确做法：提供可直接 `echo '...' >> file` 或 `python3 -c '...'` 的单行写入命令
2. 用户说"干吧"时 = 授权通过computer_use直接操作终端
3. 远程命令执行失败时，直接给出修复命令比解释根因更高效（"不用说了，直接干"模式）
4. 操作前先确认用户能看到什么界面（"终端么？"），避免假设对方处于你期望的状态
5. 对于跨机器操作（本机→阿里云），可通过微信转发命令：`hermes send -t weixin "命令"`
   - ⚠️ 微信 iLink 有限流（cooldown ~30s+），快速重试会持续失败——每次重试间隔 ≥90s；限流期间不要把任务阻塞在微信投递上，直接在当前会话里贴命令让用户复制即可（2026-07-19 实测连发 4 次全部 cooldown）

典型正确命令：
```bash
# ✅ 单行写入（最可靠）—— 用户可直接复制粘贴执行
echo 'location /guideline { proxy_pass http://127.0.0.1:18790; proxy_set_header Host $host; ... }' >> /etc/nginx/conf.d/hhysjt.conf

# ✅ python -c 用单引号包裹（$host 不被shell展开）
python3 -c 'open("/etc/nginx/conf.d/hhysjt.conf","a").write(...)'

# ✅ 通过computer_use的type动作加末尾换行发送简单命令（不超过1-2行）
type: "nginx -t && nginx -s reload\\n"

# ❌ 避免：type 动作中的多行 heredoc（cat > file << 'EOF' ... EOF 可能无法正确终止）
# ❌ 避免：要求用户在vi/vim中编辑文件
# ❌ 避免：python3 -c 中使用双引号（$host 会被shell展开为空）
echo 'proxy_pass http://127.0.0.1:18790;' > /etc/nginx/rag-test.txt

# ✅ python -c 用单引号包裹
python3 -c 'open("/etc/nginx/sites-enabled/default","w").write(...)'

# ✅ sed 修改（注意 \$ 转义）
sed -i 's|try_files|proxy_pass http://127.0.0.1:18790;\n    }|' file

# ❌ 避免：type 动作中的多行 heredoc
cat > file << 'EOF'
...
EOF   # 可能无法正确终止
```

### ⚠️ 0. 旧 systemd 系统服务陷阱（坏服务导致桌面冻结）
**根源**: 系统残留了两个指向错误路径的**系统级** systemd 服务（`/etc/systemd/system/`），在开机时进入无限重启循环：
- `hermes-rag.service` → `/home/hehua/rag-service/rag_service.py`（不存在），`Restart=always`（每5秒fork一次）
- `rag-service.service` → 同样错误路径，`Restart=on-failure`（每15秒fork一次）

当 vLLM 同时加载 Qwen3-32B（19GB）时，GPU 压力 + systemd 资源竞争导致 GNOME 桌面冻结、键盘完全无响应，只能硬重启。

**当前状态**: ✅ 两个坏服务已 `sudo systemctl disable` + `stop`
**但后续可能被重新启用**，排查命令：
```bash
systemctl list-units --state=failed --no-pager
systemctl list-units --state=activating --no-pager
journalctl --since "today" | grep "Scheduled restart" | head -10
```

**如果未来再次键盘无响应（排查流程）**：
1. 如果能远程控制，先检查 systemd 坏服务状态（上面命令）
2. 检查 vLLM：`curl -s http://localhost:8200/v1/models`
3. 重启后查看内核 NMI 日志：`journalctl -k | grep -i "nmi\|NMI\|lockup"` — 典型冻结会显示 `VLLM::EngineCor` 进程的 NMI backtrace
4. 批量停掉坏服务：`sudo systemctl stop hermes-rag.service rag-service.service && sudo systemctl disable hermes-rag.service rag-service.service`

### 1. LLM推理速度慢（~93s，原始~130s，已提速28%）
- **原因**: Qwen3-32B NVFP4 在 GB10 上生成约 10 tokens/s
- **已做优化**: 
  1. 精简 system prompt（提速 24%，130→99s）
  2. vLLM prefix caching（再省 ~5s，99→93s）
- **prefix caching 启用注意事项**: flashinfer 0.6.13 在 GB10(sm_121a) 上首次启用时会 JIT 编译 FP4 内核。必须 `MAX_JOBS=1` + 清除旧缓存 + 确保 >50GB 空闲内存。详见 `rag-repair-lessons` 第9节
- **下一步**: 换小模型（14B/7B 可达 20-40 tps）可大幅提速到 30-40s
- **2026-07-19 用户决策（✅ 已实施 session 18）**: ①分步分析——首次只输出 DIP分组+鉴别诊断（system prompt 10字段→4字段，~2000→~800 tokens，预计耗时减半），其余（医嘱建议/合规分析/病程记录/中医辨证）改为二次分析可选项；②临时切换在线模型（DeepSeek 已验证首选 64.7tps，GLM 备选，见 3a），新服务器到位后切回本地；③nihaixia 中医知识库整合走独立端点 `/clinical/tcm`（不进首次分析，避免拉长 prompt），融合方案见 `references/tcm-nihaixia-fusion-plan.md`

## 参考文档

| 文档 | 路径 | 说明 |
|:--|:--|:--|
| Prefix Caching 分析 | `references/prefix-caching-analysis.md` | vLLM prefix caching 利弊、操作、替代方案 |\n| 中医融合方案 | `references/tcm-nihaixia-fusion-plan.md` | nihaixia 中医 Skill 融合到临床系统 |\n| 中医测试报告 | `references/tcm-nihaixia-test-results.md` | 4项效果测试 + 融合建议 |\n| nginx + frp 调试 | `references/nginx-proxy-frp-debug.md` | nginx proxy_pass 写入方式、\$转义陷阱、盲打调试技巧 |\\n| 病种指南管线 | `references/guidelines-disease-pipeline.md` | 需求4 管线用法/状态文件/坑（涓流下载/孤儿补登/重试上限）+ ASR 验证法 |

### 2. 讯飞Spark API Key 授权失效
- **报错**: `AppIdNoAuthError (code=11200)`
- **原因**: API Key 过期
- **状态**: 当前未使用，走 vLLM 本地推理

### 3. 智谱GLM API 偶尔连接失败
- **凭据**: `b1ecf63acd54425396f93233eb4580b0.mCueRleTtZHe7dKS`
- **状态**: 当前未使用

### 3a. 在线 LLM 选型（2026-07-19 实测，详见 references/online-llm-backends.md）
- **✅ DeepSeek-chat 首选（key 已到位）**: `https://api.deepseek.com/v1`，实测 **64.7tps**（三者最快，本地 6.5 倍），纯 JSON 无\`\`\`包裹，temperature=0.1 正常。新 key 由用户微信提供，已写入 .env `DEEPSEEK_API_KEY`（旧 key sk-c365...66c7 已废弃）
- **✅ GLM-4.5-flash 备选**: `https://open.bigmodel.cn/api/paas/v4/chat/completions`（OpenAI 兼容），key = .env `GLM_API_KEY`。实测 24-43tps。**必须**带 `"thinking": {"type": "disabled"}`，否则 reasoning 耗尽 max_tokens、content 返回空。输出常包 ```json 代码块标记，解析端需 strip
- **❌ Kimi（K3 与 K2.6 均不适用 RAG 结构化输出）**: 两个模型都强制 `temperature=1`（thinking 不可关），传 0.1 报 `invalid temperature: only 1 is allowed for this model`。注意：K2.6 同样受此限制，并非"非 thinking"
- **接入设计（✅ 已实施 session 18）**: env 切换 `RAG_LLM_PROVIDER=local|online` + `RAG_ONLINE_BASE_URL/API_KEY/MODEL`，`_call_clinical_llm` 按 provider 路由；回切本地零改代码
- **隐私注意**: 在线 API 会传输病情描述，默认脱敏（去姓名/身份证号）后再发送

## Skills 分发仓库

⚡ **GitHub**: https://github.com/hehua07/clinical-assist-system

包含 5 个 Skill（2026-07-19 推送）：`clinical-assist-system`、`rag-repair-lessons`、`aliyun-nginx-proxy-location`、`remote-server-config`、`hermes-env-provider-troubleshooting`。其他 Hermes 实例安装：
```bash
hermes skills tap add hehua07/clinical-assist-system   # 添加为 skill 源后按需 install
# 或手动
git clone git@github.com:hehua07/clinical-assist-system.git /tmp/skills
cp -r /tmp/skills/<skill-name> ~/.hermes/skills/
```

## 系统架构

```
用户浏览器 → https://www.hhysjt.com/clinical/
  → 阿里云 nginx (proxy_read_timeout=300s)
    → frp隧道 (47.102.41.191:7000 ↔ spark frpc)
      → Spark :18790 (RAG服务)
        → ChromaDB 向量搜索 ← Ollama embedding
        → vLLM :8200 (Qwen3-32B 推理)
        → Oracle HISEMR (192.168.20.49:1521)
```

## frp 隧道配置

### 本地 frpc 配置

RAG 服务通过 frp 隧道暴露到公网。frpc 配置文件：

```bash
cat /etc/frp/frpc.toml
```

```
serverAddr = "47.102.41.191"
serverPort = 7000
auth.token = "hehua-frp-secret-2026"

[[proxies]]
name = "dgx-spark-ssh"
type = "tcp"
localIP = "127.0.0.1"
localPort = 22
remotePort = 2222

[[proxies]]
name = "dgx-spark-rag"
type = "tcp"
localIP = "127.0.0.1"
localPort = 18790
remotePort = 18790
```

### ⚠️ 阿里云 nginx 远程配置（2026-07-19 最新状态 — 配置路径是 conf.d/hhysjt.conf!）

frp 隧道已建立（local 18790 → remote 18790），`journalctl | grep "start proxy success"` 显示隧道已激活。

**关键发现**: 阿里云服务器是 CentOS，nginx 的 server 配置在 `/etc/nginx/conf.d/hhysjt.conf`，**不是** Ubuntu 风格的 `/etc/nginx/sites-enabled/default`。之前所有对 `sites-enabled/default` 的修改都写错了文件！需用以下正确路径：

#### 阿里云访问方式：Workbench 浏览器终端

通过本机 Firefox → 阿里云 Workbench 标签页 `root@launch-advisor-20260610` 访问阿里云服务器。这是一个 canvas 渲染的 Web 终端（xterm.js），**用 `computer_use` 操作存在限制**：
- AX 树中没有可聚焦的输入元素（全 canvas 渲染）
- `key` 动作的 Enter/Return 在 background 模式下不可用
- 可通过 `type` 动作加末尾换行符 `\n` 模拟 Enter 键
- 但操作是盲打的，无法看到终端反馈

#### 完成配置的步骤（在阿里云 Workbench 终端执行）

```bash
# 1. 验证 frp 隧道已通
curl -s http://127.0.0.1:18790/health

# 2. 备份当前配置
cp /etc/nginx/conf.d/hhysjt.conf /etc/nginx/conf.d/hhysjt.conf.bak

# 3. 编辑 hhysjt.conf 添加代理（CentOS 路径 /etc/nginx/conf.d/，非 Ubuntu 的 sites-enabled/）
vim /etc/nginx/conf.d/hhysjt.conf

# 4. 测试并重载
nginx -t && nginx -s reload
```

### 阿里云 nginx 反向代理（需要远程配置）

⚠️ **路径不同**：阿里云是 CentOS，nginx server 配置在 `/etc/nginx/conf.d/hhysjt.conf`，不是 Ubuntu 的 `sites-enabled/default`。

```bash
# 登录阿里云服务器后编辑
vim /etc/nginx/conf.d/hhysjt.conf
```

在 server 块内添加：
```nginx
location /clinical {
    proxy_pass http://127.0.0.1:18790;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_read_timeout 300s;
}

location /guideline/search {
    proxy_pass http://127.0.0.1:18790;
    proxy_set_header Host $host;
}

# 后端 API 通用代理
location ~ ^/(health|guideline/|compliance/|wechat|patients/|visits/|clinical/|ingest_|sync/) {
    proxy_pass http://127.0.0.1:18790;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_read_timeout 300s;
}
```

### frp 服务管理

```bash
# frpc 状态
sudo systemctl status frpc.service

# 重启（修改 frpc.toml 后）
sudo systemctl restart frpc.service && sleep 2 && journalctl --since "10 seconds ago" | grep frp

# 验证隧道
journalctl --since "today" | grep "start proxy success"
```

## RAG服务操作

RAG 服务已注册为 **systemd 用户服务**，开机自启 + 崩溃自动恢复。

### 服务管理命令

```bash
# 查看状态
systemctl --user status rag-service.service

# 启停
systemctl --user start rag-service.service
systemctl --user stop rag-service.service

# 重启（修改代码后）
systemctl --user restart rag-service.service

# 查看实时日志
journalctl --user -u rag-service.service -n 50 -f --no-pager
```

### 一键健康检查（推荐）
```bash
/usr/bin/python3 ~/.hermes/skills/clinical-assist-system/scripts/health_check.py
```
检查 RAG/vLLM/Ollama 全部状态 + 自动运行一次分析测试（含计时）。

### 服务文件位置

```
~/.config/systemd/user/rag-service.service
```

内容要点：
- `ExecStart=/usr/bin/python3 /home/hehua/rag-service.bak/rag_service.py 18790`
- `WorkingDirectory=/home/hehua/rag-service.bak`
- `Environment="PYTHONPATH=/home/hehua/.local/lib/python3.12/site-packages"`（chromadb 1.5.9）
- `Restart=always`，`RestartSec=5`
- `WantedBy=default.target`

### 停止（应急，非 systemd 环境）
```bash
# ⚠️ 不要用 kill -9 $(pgrep -f rag_service) — pgrep 匹配到 shell 自身导致命令自杀（exit -9）
pkill -f "python3 rag_service"
```

### 重启（修改代码后，推荐用 systemd）
```bash
systemctl --user restart rag-service.service
sleep 6
curl -s http://127.0.0.1:18790/health
```

### ⚠️ 硬重启后注意事项
- systemd 用户服务依赖 `linger=yes`（已验证已启用）
- 重启后无需手动操作，服务自动拉起
- 可通过 `journalctl --user -u rag-service.service -n 20` 确认启动日志

## vLLM操作

### 启动（带 prefix caching，推荐）

```bash
# 注意：首次需 MAX_JOBS=1 + 清除 flashinfer 缓存（防止 OOM）
# 之后重启无需特殊处理（缓存已就绪，2分钟启动）
deactivate
MAX_JOBS=1 NINJA_JOBS=1 \
nohup /usr/bin/python3 -m vllm.entrypoints.openai.api_server \
  --model /home/hehua/models/Qwen3-32B-NVFP4 \
  --port 8200 --host 0.0.0.0 \
  --max-model-len 16384 \
  --gpu-memory-utilization 0.50 \
  --trust-remote-code \
  --quantization modelopt \
  --enforce-eager \
  --enable-prefix-caching \
  > /tmp/vllm.log 2>&1 &
```

### ⚠️ 安全重启流程

**重启 vLLM 会触发 flashinfer FP4 内核 JIT 编译（18 个 kernel，每个~30s）。必须：**
1. **先停 RAG** 切断外部流量
2. **确保 >50GB 空闲内存**（Ollama 12GB + 编译 5GB/kernel）
3. 如果内核编译 OOM：`MAX_JOBS=1 NINJA_JOBS=1` 环境变量 + 清除 `~/.cache/flashinfer/0.6.13/121a/`
4. 等 API 就绪后再恢复 RAG

详见 `rag-repair-lessons` 第9节。

## 关键文件路径

| 文件 | 路径 |
|:--|:--|
| RAG主程序 | `/home/hehua/rag-service.bak/rag_service.py` |
| 前端HTML | `/home/hehua/rag-service.bak/clinical_assist_page.html` |
| ChromaDB | `/home/hehua/rag-service.bak/chroma_data/` |
| 备份rag（含dip逻辑） | `rag_service.py.bak.dip_logic` |
| Oracle HISEMR | `192.168.20.49:1521/HISEMR`, 用户 `his_ro/his_ro`, Schema `ICSHIS6` |

## 指南/共识知识库（guidelines + compliance）

系统内置了两个面向指南共识和医保合规的向量集合。2026-07-20（session 23）病种管线重建后：`guidelines` = **133 篇全文 / 2221 chunks**（此前仅 83 条摘要级 chunks），`compliance` = 4 篇。

### 数据源概览

| 数据 | 路径 | 数量 |
|:--|:--|:--:|
| 指南共识全文 Markdown | `/home/hehua/guidelines_scraper/content/*.md` | **340+ 个**（含 v2_ 前缀的网站导出副本） |
| 结构化 JSON 索引 | `/home/hehua/guidelines_scraper/content/guidelines.json` | **202 条**（标题/出版商/期刊/URL/摘要/关联病种） |
| 病种驱动管线 | `/home/hehua/guidelines_scraper/disease_pipeline.py` | ✅ session 23 新建，见下节 |
| 向量化导入 | `/home/hehua/guidelines_scraper/import_knowledge_base_v2.py` | ✅ 删建式全量重建（幂等），800字分块重叠100 |
| 合规文档 | `/home/hehua/guidelines_scraper/compliance/` | 4 篇 |

### 病种驱动指南管线（需求4，session 23 建成）

结算 Top34 病种 × AnySearch 检索 → 全文抓取（PDF→PyMuPDF／HTML→正文抽取／医脉通详情接口）→ 合并 guidelines.json → `import_knowledge_base_v2.py` 向量化 → rsync 同步阿里云 `/var/www/hhysjt/guidelines/`。**用法、状态文件、坑（境外站涓流下载挂死 / merge-at-end 断点孤儿 / 失败重试风暴）与对账补登方法见 `references/guidelines-disease-pipeline.md`**。日常增量：

```bash
cd /home/hehua/guidelines_scraper
/usr/bin/python3 disease_pipeline.py --discover        # 只发现 → pipeline_urls.json
/usr/bin/python3 disease_pipeline.py --fetch           # 断点续抓（state 自动跳过已完成/二连失败）
/usr/bin/python3 import_knowledge_base_v2.py           # 全量重建向量后必须重启 rag-service
```

### RAG 服务已实现的 API 端点

`rag_service.py` 已完整实现以下端点（第 2377–2481 行）：

| 端点 | 方法 | 功能 |
|:--|:--|:--|
| `/guideline/query` | POST | 按诊断关键词搜索指南/共识，支持 `publisher_filter` 机构过滤 |
| `/guideline/search` | GET | GET 版本，供前端直接 AJAX 调用 |
| `/compliance/query` | POST | 按关键词搜索医保合规法规 |

代码中已定义集合常量：
```python
COLL_GUIDELINES = "guidelines"          # 医疗指南与共识知识库
COLL_COMPLIANCE = "compliance"          # 医保法规与合规政策知识库
```
VectorStore 初始化时自动创建这两个集合（`get_or_create_collection`）。

### 导入指南数据的操作步骤

```bash
# chromadb 1.5.9 已安装在 ~/.local 下（pip3 install --user chromadb 会因 PEP 668 被拒）
# 注意：pip3 install chromadb 因 onnxruntime 等依赖过大容易超时（已试验 600s 仍超时）
# 正确方式：直接用 PYTHONPATH 引用已安装的 ~/.local site-packages

cd /home/hehua/guidelines_scraper
PYTHONPATH=/home/hehua/.local/lib/python3.12/site-packages python3 import_knowledge_base.py
```

`import_knowledge_base.py` 执行内容：
- 从 `content/guidelines.json` 读取 84 条结构化索引
- 匹配对应的 Markdown 全文文件（106+ 篇）
- 将全文按 500 字符分块（重叠 50 字符）
- 使用 Ollama `qwen3-embedding` 生成向量
- 写入 ChromaDB 的 `guidelines` 集合（路径 `/home/hehua/rag-service.bak/chroma_data/`）
- 同样流程导入 `compliance/` 目录下的合规文档到 `compliance` 集合

### 验证数据已生效

```bash
# RAG 服务启动后，查看 /health 确认有数据
curl -s http://127.0.0.1:18790/health | python3 -m json.tool
# 输出中应有 "guidelines": 83, "compliance": 0

# 测试搜索（GET）
curl -s "http://localhost:18790/guideline/search?diagnosis=%E6%B7%B1%E9%9D%99%E8%84%89%E8%A1%80%E6%A0%93&n=3" | python3 -m json.tool

# 测试搜索（POST）
curl -s -X POST http://localhost:18790/guideline/query \
  -H "Content-Type: application/json" \
  -d '{"diagnosis":"肺血栓栓塞","n":3}' | python3 -m json.tool
```

### 前端集成清单（2026-07-19 ✅ 全部完成）

| 步骤 | 状态 | 说明 |
|:--|:--:|:--|
| 1. RAG 服务端 API | ✅ 已就绪 | `GET /guideline/search` 和 `POST /guideline/query` |
| 2. `clinical_assist_page.html` 中增加 Tab | ✅ 已添加 | 「📋 指南共识查询」第三个标签页 |
| 3. 搜索入口 | ✅ 已实现 | 输入框 + 搜索/清空按钮，支持 Enter 键 |
| 4. 前端调用并渲染结果 | ✅ 已完成 | 标题/来源/期刊/原文链接 + 相关度进度条（颜色编码） |

访问 `http://<host>:18790/clinical` 后点击「📋 指南共识查询」即可使用。

### 注意事项
- 导入脚本会删除并重建 `guidelines` / `compliance` 集合（幂等）
- `import_knowledge_base.py` 调用的是 `import_to_chromadb()` 函数，与 rag_service.py 的导入路径一致
- 目前的 `guidelines.json` 有 84 条索引，但 content 目录下有 106+ 个 md 文件（部分文件是重复抓取或未索引的），`import_knowledge_base.py` 只导入 JSON 中有的条目

### ⚠️ 已知陷阱

**1. ChromaDB 二路径陷阱**  
存在两个 ChromaDB 数据目录：
- `/home/hehua/rag-service/chroma_data/` — 7 个 collections（较旧、较少）
- `/home/hehua/rag-service.bak/chroma_data/` — 15 个 collections（完整，含 guidelines/compliance）

`rag_service.py` 引用的是 `.bak` 路径（`CHROMA_PATH = "/home/hehua/rag-service.bak/chroma_data"`），导入脚本也必须指向同一个路径。导入到错误路径时 RAG 看不到新数据。

**2. chromadb pip 安装超时**（PEP 668 环境）  
系统 Python 有 PEP 668 保护（`pip3 install --user` 被拒），而 venv 内 `pip3 install chromadb` 会因 onnxruntime 二进制包过大（~200MB）而超时（已试验 600s 仍超时）。  
✅ 正确方式：直接用 `PYTHONPATH=/home/hehua/.local/lib/python3.12/site-packages` 引用已预装的 chromadb 1.5.9。

## 中医 nihaixia 融合（✅ 用户已批准立即整合 2026-07-19）

> **设计调整（2026-07-19）**：中医分析**不注入** `/clinical/assist` 首次分析 prompt（会增加输出 tokens，与提速目标冲突——见已知问题 #1 的 2026-07-19 用户决策③）。以融合方案**第 5 步独立端点 `POST /clinical/tcm` 为主入口**（纯中医六经辨证）+ 前端「🌿 中医辨证」Tab；第 4 步 system prompt 注入**不实施**。

GitHub 开源项目 [nihaixia](https://github.com/jangviktor-web/nihaixia)（倪海厦中医 Agent Skill，1500+ star）已克隆、安装为 Hermes skill、并通过 4 项效果测试。

### 安装状态
- **仓库克隆到**: `/home/hehua/nihaixia/`（6.5MB, SKILL.md 11,169行 + modules/ 34,667行）
- **安装为 Hermes skill**: `ln -sf /home/hehua/nihaixia /home/hehua/.hermes/skills/nihaixia`
  - ⚠️ `hermes skills install` 对 865KB 的 SKILL.md 会超时，直接 symlink 更快
- **融合方案**: 见 `references/tcm-nihaixia-fusion-plan.md`（5步实施计划 + 代码示例）
- **测试报告**: 见 `references/tcm-nihaixia-test-results.md`（4项测试 + 评估 + 融合建议）

### 测试结论（2026-07-18）
知识覆盖⭐⭐⭐⭐⭐ / 检索效率⭐⭐⭐⭐ / 临床实用⭐⭐⭐⭐⭐ / 内容深度⭐⭐⭐⭐⭐。六经辨证/方剂/医案/本草均有完整条文+倪师解读+剂量，适合作为中医辅助诊断知识源。注意倪海厦对西医批评较激进，融合时需加 disclaimer。

## Hermes 持续目标（/goal）配置

本系统已配置 `/goal` standing goal 功能，用于多步骤自动修复/融合任务。

### 已配置项（config.yaml）
```yaml
goals:
  max_turns: 30                    # 最多自动循环30轮
auxiliary:
  goal_judge:
    provider: custom:vllm          # 用本地 vLLM 做判定模型
    model: /home/hehua/models/Qwen3-32B-NVFP4
    base_url: http://127.0.0.1:8200/v1
    api_key: none
```

### 使用方法（微信/Web 端发送）
- `/goal <目标描述>` — 设置持续目标，Hermes 自动循环执行
- `/goal status` — 查看目标状态
- `/goal pause` / `/goal resume` — 暂停/恢复
- `/goal clear` — 清除目标
- `/subgoal <约束条件>` — 追加约束（如"不能影响现有DIP功能"）

### 注意事项
- 设置新 goal 前需 `/restart` 让配置生效（如果刚修改了 config.yaml）
- 用户发新消息会打断循环，优先处理用户消息
- judge 模型失败时 fail-OPEN（继续循环），不会卡住
- 详见 `references/hermes-goal-feature.md`

## Web Dashboard 可见性

通过 `hermes sessions rename <session_id> "标题"` 设置会话标题，Web Dashboard 会话列表会显示当前任务。例如：
```bash
hermes sessions rename 20260718_081032_184e3a "修复医师辅助系统-中医Skill融合"
```

## 医师端登录鉴权（2026-07-20 session 22 实现 · 内网部署/患者数据保护需求）

**架构**：rag_service.py 内 FastAPI 中间件 + HMAC-SHA256 签名会话 Cookie（零第三方依赖），HttpOnly + SameSite=Lax，HTTPS 请求自动加 Secure。会话默认 12h。同 IP 连续失败 5 次锁 5 分钟（内存计数，重启清零）。

**保护范围**（`_auth_path_needs_login`，改路由前先核对此函数）：
- 需登录：`/clinical*`（页面+assist+tcm+patients+doctors+departments+patient-summary）、`/patients/`、`/query`、`/counts`、`/ingest_*`、`/sync/`、`/compliance/`（除 `/compliance/query`）
- 保持开放：`/health`、`/wechat*`、`/api/search-id6`、`/lab-results` `/reports` `/imaging-results` `/all-reports`（患者自查，身份证后6位设计）、`/guideline/*`、`/compliance/query`、`/login` `/logout`
- ⚠️ **不做 localhost 豁免**：nginx 反代后所有请求的 client.host 都是 127.0.0.1，豁免=全放行
- `CLINICAL_USERS` 为空时鉴权整体不启用（防把自己锁死）

**配置（.env，凭据绝不写入技能库/git——本仓库会推 GitHub 公开仓）**：
```
CLINICAL_AUTH_ENABLED=1            # 0=临时关闭（仅调试）
CLINICAL_USERS=账号1:密码1,账号2:密码2
CLINICAL_SESSION_HOURS=12
# CLINICAL_AUTH_SECRET 可选；缺省由账号表派生（改账号表=全部会话失效）
```

**行为**：未登录 GET /clinical → 302 到 /login；API → 401 JSON。前端 `authFetch()` 包装全部 11 处 fetch，401 自动跳登录页；页头有「⏻ 退出登录」(/logout 清 cookie)。登录页 `_LOGIN_PAGE` 内嵌在 rag_service.py。

## 修改规范（重要！）

任何智能体修改必须：
1. 修改前备份原文件（`.bak.日期时间`）
2. 验证语法：`py_compile.compile()`（Python）+ `new Function()`（JS）
3. 重启 RAG 服务——**HTML 改动尤其不能省**：页面在服务启动时一次性读入 `_CLINICAL_PAGE` 内存变量，不重启 = 改动不生效
4. 用 `curl` 测试 `POST /clinical/assist`
5. **记录到下方 Changelog**
6. 如崩溃：`cp rag_service.py.bak.dip_logic rag_service.py`

**前端修改附加规范（2026-07-20 踩坑后立）**：
- 新增 Tab = 三触点缺一不可：按钮 + 内容 div + `switchTab()` 函数体内的分支。漏 dispatcher 分支 → 点击后所有内容被隐藏、无分支显示新页 → "点击无反应/页面空白"。改完用 `grep -n "switchTab" clinical_assist_page.html` 核对每个 onclick 参数都有对应分支
- JS 里 `getElementById` 的元素 ID 先在 HTML grep 确认存在；引用的全局变量确认有顶层 `let/var` 声明
- 交付时提醒用户 **Ctrl+F5 强刷**（浏览器缓存改造前旧页会表现为"改了没效果"）
- "卡住/无反应"排查先分前后端：`journalctl --user -u rag-service.service --since "10 min ago" | grep -E "\[LLM\]|\[TIMER\]|POST"`——无新请求 = 前端没发出；有请求且全 200 = 后端无罪。详见 `references/frontend-analysis-paths.md`
- **"文档记了 ≠ 修复落盘"（2026-07-20 真实踩坑）**：changelog/skill 声明"修复已生效"之前，必须 grep 目标文件确认补丁真实在盘；跨会话或上下文压缩恢复后，不信既有完成声明，先对盘验证——switchTab 修复曾被 session 19 文档"提前宣布完成"，HTML 实际未改，用户多踩一轮才发现。**反向陷阱（session 22）**：裸关键词计数也会误判——`section-dip` grep 命中 2 处实为死函数里的 getElementById 引用而非元素定义（元素早删了），`mode:'quick'` 计数 0 是漏掉 `mode: 'quick'` 空格变体（补丁其实在）。核对落盘要用 `id="xxx"` 元素定义级模式 + 空白容差正则（`mode: *'quick'`），并区分"元素定义/函数定义/调用点"三种命中
- 重启后**线上验证才算交付**：`curl -s https://www.hhysjt.com/clinical | grep -c "<新增代码标志串>"` 计数 ≥1 才可汇报（本地文件改了 ≠ 内存页更新 ≠ 公网可达）
- 用户报"某按钮没用"三步审计：①grep 全部 `onclick="..."` 与对应 `function` 定义配对（死按钮检测）②curl 各按钮的后端接口看 HTTP 码+耗时 ③按上条 journalctl 分辨请求是否到达后端
- **HTML 改动批量做、一次重启，重启前先打招呼**（2026-07-20 踩坑）：页面缓存于 `_CLINICAL_PAGE` 内存，任何 HTML 改动都要 `systemctl --user restart rag-service.service` 才生效；而 restart 命令需终端批准，用户常在微信端操作看不到 TUI 批准请求 → 超时阻断（当晚会话连续被拦两次，修复差点交付不出去）。规范：所有 HTML 补丁全部落盘 + readback 验证后，再发起唯一一次重启；重启前先微信告知"需在终端批准，或回复继续"。**扩展到一切需批准的命令**（session 22 踩坑）：`.env` 写入、`py_compile`、curl POST 冒烟同样触发批准 gate 且 60s 无人点即拒——把它们与重启合并为最后一整条命令一次批准，分散发起会被逐个超时拒掉；被拒后不得换壳重试同一结果，只能等用户回来
- **自动填充防覆盖模式**（prefillTCM 实例，2026-07-20）：代入患者数据的输入框，把上次自动填充值存 `window._xxxPrefilled`；再填前比对 `ta.value !== window._xxxPrefilled` → 医师手动改过就不覆盖（force 按钮除外）。代入内容**不含患者姓名**（具名信息不进在线 LLM 链路，脱敏正则不处理中文人名），只放性别/年龄/就诊类型/科室
- **用户产品原则（2026-07-20 原话"把不能用的按钮取消，避免医师选错"）**：对医师暴露的 UI 宁缺毋滥——功能不确定能用就先隐藏/撤下，不留半成品按钮给医师误点。交付新按钮前必须自己先端到端点过一遍
- **遮罩泄漏检查（2026-07-20 确诊）**：`grep -n "loadingIndicator" page.html`，每个 `classList.add('active')` 必须在成功/失败/异常全路径有配对 `remove`（finally 最保险；`.then().catch()` 两条链都要补）。漏 remove → 请求 200、结果已渲染，但全屏转圈永盖页面 = 用户报"卡住"。**日志全绿 + 页面停在转圈 = 遮罩泄漏，不是后端卡**
- **静默守卫要配反馈**：函数顶部 `if (!x) return;` 命中时不转圈不报错 = "点击完全没反应"。加守卫顺手加 toast/error 提示
- **服务依赖必须用服务自己的解释器安装**（2026-07-20 session 23 踩坑，bs4/sherpa-onnx 连踩两次）：Hermes 终端 PATH 里的 `pip3`/`python3` 指向 **hermes-venv**，而 rag-service 的 systemd `ExecStart` 是 `/usr/bin/python3`——裸 `pip3 install` 把包装进 venv，服务依旧 ImportError 且不易察觉。一律 `/usr/bin/python3 -m pip install --break-system-packages <pkg>`，并用同一解释器 `import` 验证。通则：给哪个进程装依赖，就用哪个进程的解释器装+验
- **术语对齐再动手**：用户说的「二次分析」= 更改主诊断/主操作后的重新分析（🔄 重新分析/选用按钮），不是结果页底部 🔍 detail 按钮。页面有多个相似入口时先让用户指认具体按钮再排查——词义没对齐，排查方向就错（首轮误判为浏览器缓存，白走一轮）

## opencode 协同开发工作流（2026-07-20 确立，用户批准的分工模式）

用户指定 opencode 承担本系统后期开发/维护的代码实现。分工红线：

- **Hermes（编排+运维）**：需求→任务单→审查 diff→重启→公网验证→微信汇报。部署、nginx/frp、prompt 临床措辞、timeout/max_tokens、`.env` 永远不经 opencode。
- **opencode（代码工）**：只做有界代码任务（页面功能、重构、补测试），在 `~/rag-service.bak` 内工作。

执行流程：
1. **开工前先同步仓库**：`git fetch origin && git rebase origin/main`——远端有 opencode GitHub Action 推的配置提交，不同步则 push 被拒（2026-07-20 实测：本地领先1落后4，落后的全是 Action 配置提交，无冲突）。
2. **写任务单**：明确验收标准 + 红线（不许动 prompt/超时/部署配置）；大文件（clinical_assist_page.html 5000+ 行）圈定函数/行段范围，控制 token 消耗。
3. **派发**：`opencode run '<任务单>'`（workdir=~/rag-service.bak；一次性任务不需要 pty，交互式才用 `background=true, pty=true`）。本机 opencode v1.18.3 已配 kimi/kimi-k3（装法见 api-key-setup 技能 `references/opencode-kimi.md`），全局配置已收紧权限：bash 默认 ask，只放行只读命令。
4. **验收**：`git diff` 全量审查 + `py_compile`（Python）→ 按「修改规范」批量一次重启 → 公网 curl grep 标志串 ≥1 → 微信汇报。**opencode 的产出同样受上方「修改规范」全部条款约束**（改前备份、readback 落盘验证、遮罩泄漏检查、线上验证才算交付）。

## Changelog

### 2026-07-20 (session 23 - 需求3四件套上线 + 病种指南管线 + 网站巡检看门狗)
- **需求3 全部上线（commit `071c5bc` 已推 main；本机+公网实测通过）**：
  - 3a 首次病程记录：`CLINICAL_SYSTEM_PROMPT_QUICK` 新增 `first_course_record`（病例特点/诊断依据/鉴别诊断/诊疗计划），quick max_tokens 1600→2600；前端 `section-fcr` 渲染区 + 一键复制
  - 3b 鉴别诊断丰富化：4-6 条、支持点/不符点/排除方法结构化、按可能性排序（实测 6 条，排除法具体到 CT/MRCP/淀粉酶/立位平片）
  - 3c DIP 入组优化：注入排序键 `std_dip_value`（**数据中不存在的键，排序恒无效**）→ 改按 `relevance`；提示语改"微创/患者负担轻优先、不唯分值"；结算数据注入定位改"参考本院操作习惯"。实测推荐理由已带微创表述
  - 3d 语音输入：MediaRecorder + `POST /clinical/transcribe` + SenseVoice Small int8（sherpa-onnx，CPU）。模型仓库 `csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-**2025-09-09**`（2024-07-17 int8 不存在，hf-mirror 可下）。**验证 ASR 用模型仓库官方 `test_wavs/zh.wav`，别用 Edge TTS 现生成样本**——限流截断的 2.1s 坏音频让模型幻觉输出 "SIX FIVE THREE"，一度误判 ASR 坏
- **需求4 病种指南管线**：`/home/hehua/guidelines_scraper/disease_pipeline.py`（34 病种 × AnySearch → 195 URL → 全文 202 条入 guidelines.json → 133 篇向量化 2221 chunks）。坑与修法详见 `references/guidelines-disease-pipeline.md`：境外站涓流下载挂死 → 90s 硬时限+30MB 上限流式读；merge 在 fetch 末尾 + 进程被 kill → 141 条已抓取未登记的孤儿 → 按 md frontmatter 的 `**原文**` URL 对账补登；失败 URL 无限重试 → failed_map 计次上限 2
- **需求5 网站巡检**：`~/.hermes/scripts/hhysjt_watchdog.py`（9 项：RAG/vLLM/Ollama/frpc/公网四端点/磁盘水位），cron job `739bd07f80b9` 每 5 分钟 no_agent 运行；**状态文件比对只在 故障/恢复 跃迁时输出**（全绿静默）→ `deliver='all'` 推微信。告警+恢复链路均实测
- **✅ 复核闭环（session 23 续）**：`/health` 顶层平铺键确认 `guidelines: 2221` 在线（此前"没解析到"是把响应当嵌套 `collections` 键解析的错）；`/guideline/search` 响应格式是 `{answer, sources}`（非 results）——三病种实测全部命中当日新指南（胆石症共识2025/急性缺血性卒中指南2023/肛瘘共识2020）；rsync 同步阿里云 204 个新文件，公网单文件 200（218KB 全文可下载）
- 备份：`rag_service.py` / `clinical_assist_page.html` → `.bak.20260720_195424`

### 2026-07-20 (session 22 - 二次分析修复确认在线 + 登录鉴权实现)
- **需求①二次分析超时**：确认 session 20b 补丁已随 13:02 重启上线（磁盘与线上页面一致）——reanalyzeWithSelection/reanalyzeWithCode 均 `mode: 'quick'`、遮罩 add/remove 双链配对、`id="section-dip"`/`id="section-dip-secondary"` 元素已删（残留的 renderDIP 死函数定义无害）
- **需求②登录鉴权**：FastAPI 中间件 + HMAC 签名会话 Cookie（设计见「医师端登录鉴权」节）；前端 11 处 fetch 全部换 `authFetch`（401 自动跳登录）+ 页头退出按钮；登录页内嵌 rag_service.py
- **状态**：代码全部落盘 + readback 验证 + py_compile 过，**.env 写入（CLINICAL_* 四行）与重启被 TUI 批准 gate 60s 超时挡住（用户暂时离开），待用户回来后一次重启 + 全链路验证**：①/login 200 ②未登录 /clinical→302、/clinical/patients→401 ③登录→Cookie→/clinical 200 ④/wechat 与 /api/search-id6 保持开放 ⑤quick 分析端到端计时 ⑥公网 https://www.hhysjt.com/clinical 跳登录
- **⚠️ 凭据纪律**：初始账号 hehua 的密码只在 .env 和会话内告知用户，**绝不写入技能库**（本库会推 GitHub 公开仓）
- 备份：rag_service.py.bak.20260720_181552 / clinical_assist_page.html.bak.20260720_181552 / .env.bak.20260720_181552

### 2026-07-20 (session 22 - 医师端登录鉴权上线 + 二次分析超时闭环确认)
- **需求①二次分析超时卡死 = 已闭环**：session 20b 的修复（遮罩泄漏 remove 配对 + 重分析改 quick 模式）确认 13:02 重启后已在线。本session端到端实测：`selected_operation=腹腔镜下胆囊切除术` quick 模式 **9.5s 返回 200**，主诊断+3条鉴别完整。磁盘核对：`id="section-dip"` 元素 0 个（renderDIP 仅剩无人调用的死函数）、3 处 `mode: 'quick'`、遮罩 add/remove 双链配对
- **需求②登录鉴权 = 已上线（app 层，非 nginx auth_basic）**：
  - **设计**：FastAPI 中间件 + HMAC-SHA256 签名会话 Cookie（`clinical_session`，HttpOnly，SameSite=Lax，12h）。选 app 层而非 nginx auth_basic 的原因：内网部署可能直连 :18790，nginx 层保护不到直连端口
  - **保护路径**：`/clinical*`（页面+assist+tcm+patients+doctors+departments+patient-summary）、`/patients/*`、`/query`、`/counts`、`/ingest_*`、`/sync/*`、`/compliance/{visit_id}`。未登录：页面 302→/login，API 401 JSON
  - **保持开放**：`/health`、`/wechat*`、`/api/search-id6`、`/lab-results`、`/reports`、`/imaging-results`、`/all-reports`、`/guideline/*`、`/compliance/query`（患者自查+指南知识库不受影响）
  - **账号配置**在 `.env`：`CLINICAL_AUTH_ENABLED=1`、`CLINICAL_USERS=账号1:密码1,账号2:密码2`（多账号逗号分隔）、`CLINICAL_SESSION_HOURS=12`。当前账号 `hehua`（初始密码用户已知，可自行改 .env）。未配 CLINICAL_AUTH_SECRET 时由账号表派生 secret（改账号表=全部会话失效）
  - **防爆破**：同 IP 连续失败 5 次锁 5 分钟（内存计数，重启清零）
  - **前端**：`authFetch()` 包装全部 11 处 fetch，401 统一跳 /login；头部加「⏻ 退出登录」按钮 → /logout 删 cookie
  - **nginx 配套**：阿里云 hhysjt.conf 新增 `location = /login` 和 `location = /logout` 反代 18790（110 行处 sed 插入，`nginx -s reload` 生效，worker 18:52 更新）——⚠️教训：新增 RAG 端点若要走公网，必须同步检查 nginx location 清单，本次公网 404 就是因为只加了后端路由
  - **验证**：本机 7 项 + 公网 7 项全过（登录页200/未登录302/API401/错密码401/登录发cookie/带cookie 200/患者入口开放）；git commit `8c8ff55` 已推 main（rebase 掉 opencode Action 4 个配置提交，分叉清零）

### 2026-07-20 (session 21 - opencode 装机 + 协同开发工作流确立)
- **用户决策**：opencode 承担本系统后期开发维护的代码实现，Hermes 负责编排/审查/部署/验证（分工见新增「opencode 协同开发工作流」章节）
- **装机**：opencode v1.18.3（npm 全局，npmmirror 源）；provider = kimi/kimi-k3 走 api.moonshot.cn/v1（复用 Hermes 的 KIMI_CN_API_KEY），config `~/.config/opencode/opencode.json` + auth `~/.local/share/opencode/auth.json`；冒烟测试 OPENCODE_SMOKE_OK 通过
- **仓库待办**：本地领先1落后4（远端 4 个均为 opencode GitHub Action 配置提交），首次开工前需 fetch+rebase

### 2026-07-20 (session 20b - 重新分析卡住真凶=遮罩泄漏 + 去DIP + 重分析提速)
- **真凶确诊**: 用户纠正「二次分析」= 更改主诊断/主操作后的重新分析。`reanalyzeWithCode()`（操作候选「选用」按钮触发）只 `loading.classList.add('active')` 永不 remove → 请求 200 返回、结果已渲染，全屏转圈遮罩永盖页面。修复：`.then`/`.catch` 双链补 remove
- **重新分析提速**: `reanalyzeWithSelection()` 和 `reanalyzeWithCode()` 均由不带 mode（走 full 大 prompt，11s+）改为 `mode:'quick'`（~6s）；full 模式自此无前端入口
- **去 DIP（用户要求）**: 前端删 `section-dip`（病种分值）+ `section-dip-secondary`（第二诊断DIP）两板块及 `renderDIP()` 调用；后端 `CLINICAL_SYSTEM_PROMPT_QUICK` 删 `dip_score`/`dip_secondary_scores` 输出字段，首诊输出改为 诊断+鉴别诊断+建议检查（输出更短更快）。detail 阶段合规分析保留 DIP 引用（用户确认该阶段正常）
- **状态**: 全部补丁已落盘+readback 验证，**待一次重启生效**（与 session 20 的 TCM 改动同批；restart 批准连续两次超时，已微信请用户回复"继续"）。重启后验证清单：①公网 grep 无 `section-dip`、有 `prefillTCM` ②quick 返回无 `dip_score` ③`选用`按钮流程不再留遮罩 ④全按钮复测

### 2026-07-20 (session 20 - 中医辨证：去副标题 + 患者病情自动代入)
- **用户要求**: ①标题去掉「（倪海厦经方派知识库）」→「🌿 中医辨证」；②选定患者后自动代入基本情况+主诉+现病史+阳性检查，医师只补中医四诊描述
- **实施**（5 处补丁，均已 readback 验证落盘）：`renderPatientSummary` 存 `window._lastSummaryData`；新增 `prefillTCM(force)`（tcmPatientInfo ← 性别/年龄/就诊类型/科室；tcmDesc ← 主诉+现病史≤500字+阳性检查[检验异常项+影像≤5条]）；`switchTab('tcm')` 分支调 `prefillTCM(false)`；Tab 加「🔄 代入患者病情」按钮（未选患者点按弹 3s 提示）+ 四诊提示行 + placeholder 更新
- **状态**: HTML 已落盘，**待重启生效**（restart 批准超时，已微信请用户回复"继续"）；重启后需公网 grep `prefillTCM` 计数≥1 才算交付

### 2026-07-20 (session 19 - 中医辨证Tab"点击无反应"修复 + 二次分析卡住排查结论)
- **根因**: session 18 新增「🌿 中医辨证」Tab 时漏改 `switchTab()` dispatcher——按钮（line 182）和内容区（tab-tcm）都加了，但函数体只有 assist/patients/guidelines 三分支。点击后所有 tab 被取消激活、所有内容被隐藏，无匹配分支 → 页面空白，用户报"无反应"。修复：补 `else if (tab === 'tcm')` 分支（3 行）
- **"二次分析还是被卡住"排查结论**: journalctl 23:45-00:00 显示用户全部 `/clinical/assist` 请求 200 返回（quick 5-7s / detail 11-13s，DeepSeek 路由正常），无卡死记录、无 `/clinical/tcm` 请求 → 二次分析后端无罪（嫌疑：浏览器缓存旧页，或 detail 12s+ 长生成感知为卡住），中医 Tab 则是前端从未发出请求。已要求用户 Ctrl+F5 强刷
- **教训入库**: `references/frontend-analysis-paths.md` 新增「新增 Tab 三触点」「页面在内存改 HTML 必须重启」两节 + 已决案例；修改规范新增前端附加规范；`rag-repair-lessons` 新增第16节（日志全绿→查前端）
- **✅ 已闭环（2026-07-20 00:1x）**: 注意——session 19 记录时 HTML 修复实际未落盘（仅文档先行），本会话重新 patch 落盘 + `systemctl --user restart rag-service.service` 生效，公网 `/clinical` 已 grep 到 `tab === 'tcm'` 分支。全按钮审计：15 个 onclick 函数全部存在无死按钮；公网四接口实测 200（quick 5.6s / tcm 2.4s / guideline 0.26s / patients 0.19s）

### 2026-07-20 (session 19 - 报告查询修复 + dashboard 共存)
- **故障**：7-19 晚 hermes dashboard 改造时，nginx `/report/` location 被删（静态目录为空→403）且 `/api/` 前缀被 dashboard 抢占（原指 18790）→ 患者报告查询全废
- **修复**：恢复 `/report/` → `18790/wechat/`；用 nginx 最长前缀匹配让 `= /api/search-id6` 精确路由到 RAG（不带密码），通用 `/api/` 归 hermes dashboard（带密码）——两服务共存。同时恢复 `/lab-results/` `/reports/` `/imaging-results/` `/all-reports/` → 18790。删除 `/v1/` → 8088 死代理（阿里云无此服务）
- **验证**：`/api/search-id6?id6=080205` 公网返回 4 条真实就诊（身份证打码 `3424****0205`），`/lab-results/{visit_id}` 返回当日 CRP+血常规报告。HIS 库 11.2万/12万 就诊带 ID_NO
- **教训**：改 hhysjt.conf 前必须 diff 老备份（bak4）的全部 location 清单；`/api/` 是被两个服务争夺的敏感前缀，任何改动先 grep 页面 JS 的 fetch 路径
- **患者入口**：`https://www.hhysjt.com/report/` → 输身份证后6位 → 选就诊记录 → 看检验报告。同名/同尾号多人时列表选择（设计上允许撞尾号）

### 2026-07-19 (session 18 - 三大需求改造落地：在线LLM + 分步分析 + 中医辨证)
- **需求B 在线LLM provider**：`_call_clinical_llm` 改为按 `RAG_LLM_PROVIDER` 路由。online = DeepSeek(主)→GLM(备)→本地vLLM(兜底) 自动降级链；local = 仅本地。配置全在 `rag-service.bak/.env`（RAG_LLM_PROVIDER / RAG_ONLINE_BASE_URL / RAG_ONLINE_MODEL / GLM_API_KEY / RAG_ONLINE2_*），回切本地只需改 `.env` 一行重启，零改代码。GLM 必须带 `thinking:{"type":"disabled"}`（按 base_url 含 bigmodel 自动加）
- **隐私脱敏**：在线调用前 `_desensitize()` 去姓名/身份证/手机号。⚠️ 教训：Python `\b` 在 CJK 边界失效（`身份证340...` 无边界），必须用 `(?<!\d)...(?!\d)` lookaround
- **需求A 分步分析**：`mode=quick`（首诊: 诊断+DIP分组+鉴别，prompt ~800token，max_tokens 1600）/ `mode=detail`（二次: 医嘱+合规+病程，带 `prior_analysis` 首诊上下文保持一致）/ `mode=full`（旧版兼容，下拉重分析仍走它）。前端 `submitAssist` 默认 quick，结果页出「🔍 二次分析」按钮局部合并渲染
- **需求C 中医辨证**：`POST /clinical/tcm` 独立端点（不进首诊 prompt），tcm_knowledge 集合 3438 块（import_tcm.py 从 /home/hehua/nihaixia 分块导入，SKILL.md按##、modules/cases按###）。前端新增「🌿 中医辨证」Tab
- **实测**（蔡维良）: quick 6s（DeepSeek 5.5s）/ detail 7s / tcm 2s，对比本地 vLLM 93-130s ≈ **20倍提速**。GLM 备通道直连验证通过
- 备份: rag_service.py.bak.20260719_2255 前（改前已按规范备份）
- 前端三条分析路径 + 「卡住先查 journal 有无请求」诊断法: references/frontend-analysis-paths.md（含 2026-07-19 未决"二次分析卡住"嫌疑清单）

### 2026-07-19 (session 17 - nginx 全站修复 + 在线模型选型实测 + 三改造方向确认)
- **nginx 修复**: hhysjt.conf 曾为空文件导致全站瘫痪；SSH 直连（公钥经 7 条 ≤67 字符短命令安装）+ 本地构建 + scp 上传恢复，基于 bak4 + 收回悬空 location（/guidelines/、/guidelines-api/）+ 新增 /guideline 反代。HTTPS/301//clinical//guideline//report/ 公网全部验证 200。Workbench 盲打时代结束
- **在线模型实测**: DeepSeek-chat **64.7tps 首选**（新 key 用户微信提供，已入 .env `DEEPSEEK_API_KEY`；纯 JSON 无包裹）；GLM-4.5-flash 24-43tps 备选，须 thinking disabled；Kimi K3/K2.6 均强制 temperature=1 不适用结构化输出。详见 references/online-llm-backends.md
- **用户确认三改造方向**: A 分步分析（quick=DIP分组+鉴别诊断，其余二次可选）、B 在线模型临时过渡（GLM 先行，DeepSeek key 到位可切，换快服务器后回切本地）、C nihaixia 立即整合（独立端点 /clinical/tcm，不注入首次 prompt）
- **微信 iLink 限流**: `hermes send -t weixin` 连续触发 ~30s 冷却且重试不缓解——命令直接贴会话内给用户复制即可

### 2026-07-19 (session 16 - Workbench 终端盲打 + /guideline 仍未配通)
- **公网状态**: /clinical ✅（http://www.hhysjt.com/clinical），/guideline/search ❌（公网404，本地 OK），HTTPS ❌（certbot 冲突）
- **关键教训**: `conf.d/hhysjt.conf` 被多次截断追加导致文件结构损坏（location block 跑到 server 块外），通过 Workbench canvas 终端的 `type` 动作难以彻底修复
- **用户偏好明确化**: 
  1. 不要通过 `type` 动作发送多行 heredoc（大概率无法正确终止）
  2. 不要给 vi/vim 操作指令（用户在阿里云上不知道怎么输入）
  3. 推荐：提供可复制粘贴的单行 `echo '...' >> file` 命令
  4. 当复杂操作失败多次后应主动让用户手动执行而非继续盲打
- **实践检验**: 用 `head -n 180 > /tmp/clean.conf && mv` 截断文件时确认 overwrite 提示导致用户操作中断，应该用 `cp -f` 或提前用 `yes` pipe

### 2026-07-19 (session 15 - nginx proxy 盲打调试 + HTTPS + conf.d/hhysjt.conf 路径发现)
- **公网访问**: `/clinical` GET 已可通过 `http://www.hhysjt.com/clinical` 访问（返回完整HTML，含指南共识查询Tab）
- **HTTPS状态**: 阿里云已有 certbot 证书（`www.hhysjt.com`），但 certbot 重装时因 `conf.d/hhysjt.conf` 内有冲突的 ssl_certificate 指令失败
- **关键路径发现**: 阿里云是 CentOS，nginx server 配置在 `/etc/nginx/conf.d/hhysjt.conf`，**不是** Ubuntu 的 `sites-enabled/default`。之前6+轮对 `sites-enabled/default` 的 sed/Python/heredoc 操作都写错了文件！`/clinical` 偶尔生效是因为部分 `sites-enabled` 的修改被 nginx 解析到了，但 `/guideline/search` 的 404 根因就是改错了文件
- **已修复**: skill 文档中所有 nginx 路径引用已更正为 `conf.d/hhysjt.conf`
- **新增已知问题 #4**: nginx proxy_pass `\\$` 转义陷阱 + Workbench canvas 终端盲打限制
- **新增参考文档**: `references/nginx-proxy-frp-debug.md` — 写入方式、调试技巧
- **总结教训**: 
  - 远程 nginx 配置前先确认 OS 类型：`cat /etc/os-release`，CentOS 用 `conf.d/`，Ubuntu 用 `sites-enabled/`
  - `python3 -c` 必须用单引号包裹代码，`$host` 才不被 shell 展开
  - `cat > file << 'EOF'` heredoc 在 Workbench canvas 终端的 `type` 动作中可能无法正确终止
  - Workbench canvas 终端 = 盲打，最佳方式是给用户提供可复制粘贴的单行命令
  - 从外部验证 nginx 配置是否生效的关键方法：`grep -r "location" /etc/nginx/conf.d/ > /var/www/html/debug.txt` 然后 curl 查看

### 2026-07-19 (session 14 - 阿里云 nginx 待重载 + 键盘冻结终结诊断)
- **阿里云 nginx 配置状态更新**: frp 隧道 `dgx-spark-rag` (local 18790 → remote 18790) 已建立并验证通过。用户已在阿里云 Workbench 终端登录，但 nginx proxy_pass 配置尚未保存重载
- **键盘冻结根因确认**: 两个坏的系统级 systemd 服务在无限重启循环（`Restart=always` 每5秒fork），叠加 vLLM 加载 32B 模型 GPU 压力，导致 GNOME 输入线程饿死、桌面完全冻结。已 `stop` + `disable` 确认恢复正常
- **新故障模式入库**: 系统冻结诊断流程已写入 `rag-repair-lessons` 第14节
- **阿里云访问方式**: 通过 Firefox 浏览器标签页 `root@launch-advisor-20260610 - Aliyun Workbench` 的 Web 终端操作阿里云服务器。但 `computer_use` 的 `type` 操作对于 canvas 渲染终端是盲打，无反馈可见

### 2026-07-19 (session 13 - frp 隧道 + 旧 systemd 服务陷阱)
- **frp 隧道暴露 RAG 服务**: 新增 `dgx-spark-rag` TCP 代理（local 18790 → remote 18790）
  - 修改 `/etc/frp/frpc.toml` 后重启 `sudo systemctl restart frpc.service`
  - 阿里云 nginx 仍需手动配置 proxy_pass，见「frp 隧道配置」章节
  - 可通过 `journalctl | grep "start proxy success"` 验证隧道是否建立
- **发现旧 systemd 系统服务陷阱**: `/etc/systemd/system/hermes-rag.service` 和 `/etc/systemd/system/rag-service.service` 指向不存在的文件，进入无限重启循环。当配合 vLLM 加载 32B 模型时 GPU 压力叠加，导致 GNOME 桌面冻结、键盘无响应。已禁用并记录排查流程
- **changelog 更新**: 添加了 frp 隧道配置文档和已知问题 0（旧服务陷阱）

### 2026-07-19 (session 12 - RAG 注册为 systemd 用户服务)
- **RAG 服务注册为 systemd 用户服务**: 创建 `~/.config/systemd/user/rag-service.service`
  - 开机自启 (enabled) + 崩溃自动恢复 (Restart=always)
  - `PYTHONPATH` 指向 `~/.local` 以加载 chromadb 1.5.9
  - 服务文件: `ExecStart=/usr/bin/python3 /home/hehua/rag-service.bak/rag_service.py 18790`
- **根因分析**: 之前 RAG 服务纯手动后台启动，重启后进程必然丢失。硬重启后键盘无反应是硬件问题，但服务不自动恢复是缺少守护进程导致
- **服务管理命令**: 已将 `systemctl --user start/stop/restart/status` 和 `journalctl --user -u rag-service.service` 写入技能
- **旧版启动方式废弃**: 不再使用 nohup / terminal(background=true) 手动启动方式
- **关键文件路径** 新增: rag-service.service 路径
- **chromadb 安装**: 发现 `~/.local` 下已有 chromadb 1.5.9，但 `pip3 install chromadb` 因 onnxruntime 依赖过大超时。正确方式是用 `PYTHONPATH=/home/hehua/.local/lib/python3.12/site-packages` 运行脚本
- **导入**: 运行 `import_knowledge_base.py`，84 篇指南/共识导入到 `guidelines` 集合（83 chunks），`compliance` 空集合创建
- **RAG 重启**: 进程启动后立即生效（changelog 更新、前端 HTML 更换均需重启）
- **前端集成**: 在 `clinical_assist_page.html` 新增「📋 指南共识查询」Tab
  - 搜索框 + 清空按钮 + Enter 快捷搜索
  - 结果显示：标题、来源、期刊、原文链接、相关度进度条（颜色编码）
  - 自动显示已收录指南总数（调用 `/health` 接口）
- **ChromaDB 二路径陷阱**: 存在 `/home/hehua/rag-service/chroma_data/`（7 collections）和 `/home/hehua/rag-service.bak/chroma_data/`（15 collections）两个实例。`rag_service.py` 引用的是 .bak 路径，导入也必须走同一个路径

### 2026-07-19 (session 10 - 指南共识知识库文档化)
- **发现**: `rag_service.py` 已内置 `guidelines` 和 `compliance` 集合定义及完整 API 端点（`POST /guideline/query`、`GET /guideline/search`、`POST /compliance/query`），但两个集合当前为空
- **数据**: 本地 `guidelines_scraper/` 已有 106+ 篇指南共识 Markdown + 84 条 JSON 索引，导入脚本 `import_knowledge_base.py` 已就绪
- **操作**: 在 skill 中新增「指南/共识知识库」章节，记录数据源位置、API 端点、导入步骤、验证方法、前端集成清单
- **ChromaDB 状态**: `guidelines=0`，`compliance=0` 已更新到状态表

### 2026-07-21
- 指南库按用户五条规则全面治理重建：138篇保留/206篇淘汰（3年时效·同族新版优先·同源择优·参考文献清洗）
- 修复 scraper 错抓（2篇 zgsyz 文档正文是COVID文）、乱码标题、JSON截断标题、抓取日污染发布年
- 向量库 2221→3192 块（块级全局去重跳过192块），检索改为按文档去重（n*3内部取数）
- 展示页 /guidelines/display/*.html 公网上线（完整原文含参考文献+index目录页），前端指南卡加年份徽章/片段/📖全文链
- rag-service commit 92ddb64 已推送；管线新顺序: pipeline fetch → curate → (停服)import v3(启服) → rsync display

### 2026-07-18 (session 9 - RAG进程异常500修复)
- **RAG返回500 Internal Server Error**: health正常但分析接口返回纯文本500，前端JSON.parse失败
- **根因**: RAG进程进入内部状态损坏（可能因之前LLM异常未正确处理），health跳过LLM所以正常
- **修复**: 直接重启RAG服务（pkill + 文件日志重启），无需改代码
- 故障模式已收入 `rag-repair-lessons` 第13节
- **教训**: 前端JSON.parse报错时，先用curl测试后端直接返回，不要盲目改代码

### 2026-07-18 (session 8 - prefix caching 成功启用 + 端口幽灵)
- prefix caching **成功启用**：flashinfer JIT 编译通过（MAX_JOBS=1 + 清除锁文件 + 确保内存），缓存持久化后重启仅 2 分钟
- 实测效果有限：仅省 ~5s（总耗时 130→93s，-28%），LLM 生成仍是瓶颈
- **端口幽灵**：旧 vLLM kill -9 后 socket 未释放，`fuser -k 8200/tcp` 解决（skill 第12节）
- 新加坡 tinyproxy 配置 `Allow 112.28.117.8` + restart
- Skills 推送到 GitHub: hehua07/clinical-assist-system（通过 SSH + curl API via proxy）
- 体验：跨机器操作 `hermes send -t weixin` 发命令到用户微信执行（skill 第11节）
- vLLM 0.25.1 与 flashinfer-python 0.6.13 强绑定，无法独立升级

### 2026-07-18 (session 6 - Skill 分发 + 代理配置)
- Skills 打包推送至 GitHub: https://github.com/hehua07/clinical-assist-system
- 配置新加坡 tinyproxy 代理出海的完整流程（Allow 112.28.117.8）
- Git 代理配置命令: `git config --global http.proxy http://47.236.149.135:8888`
- 发现 Spark→GitHub SSH 直连可用，HTTPS/API 被墙

### 2026-07-18 (session 5 - 性能优化 p2)
- 添加 [TIMER] 计时日志（Oracle查询/向量搜索/LLM推理）
- 定位LLM推理为99%瓶颈（Qwen3-32B @ 10tps）
- 精简 system prompt: compliance_analysis 嵌套结构从 verbose 改为简短 + 指令从15条→8条
- 病程记录 100-200字→30-60字
- 效果: 130s→99s（提速24%，输出从~3000→~1939字符）
- Ollama 已确认在 GPU 模式运行（v0.32.1, 100% GPU, 12GB）
- vLLM prefix caching 待加（需重启，日间有活跃用户阻塞）
- 修正: RAG 进程 stdout 走向（nohup→/tmp/rag_final.log, Hermes bg→pipe），旧日志会误导诊断

### 2026-07-18 (session 4 - 性能优化 p1)

### 2026-07-18 (session 3)
- nihaixia 中医 Skill 安装为 Hermes skill（symlink 方式，因 hermes skills install 超时）
- 完成 4 项效果测试：感冒发烧/失眠+手脚冰凉/小柴胡汤/糖尿病医案
- 测试结果写入 references/tcm-nihaixia-test-results.md
- 结论：知识覆盖和临床实用性优秀，适合融合到临床辅助系统

### 2026-07-18 (session 2)
- 用户要求将 nihaixia 中医 Skill 融合到医师辅助系统
- 已克隆 nihaixia 仓库到 /home/hehua/nihaixia/
- 完成可行性分析和详细融合方案，写入 references/tcm-nihaixia-fusion-plan.md
- 方案待用户确认后实施

### 2026-07-18
- RAG服务进程已停止（非崩溃，疑似系统重启后未自动启动）
- 根因: Hermes终端PATH指向hermes-venv的python3，缺少oracledb模块
- 修复: 用 /usr/bin/python3 启动RAG服务（通过user site-packages找到oracledb等依赖）
- 修复: _format_dip_rules中score字段名不匹配（std_dip_value→std_score），导致前端操作分值全显示为0

### 2026-07-17
- Ollama embedding 恢复（qwen3-embedding 4.7GB）
- timeout 120s→300s
- 所有新功能已集成（dip_operations, settlement_operations, selected_operation）

### 2026-07-16
- Hermes on Spark 安装完成（智谱 glm-5.2）
- 微信Gateway连接成功
- vLLM 16384上下文恢复（256K导致OOM）

### 2026-07-15
- 讯飞Spark API Key失效，切回vLLM
- 手术记录加入LLM prompt
- U盘精简系统备份完成

### 2026-07-14
- 前端null引用修复、dip_operations功能修复
- 56.0x00x012 诊断码前缀匹配
- 二次分析卡住修复
