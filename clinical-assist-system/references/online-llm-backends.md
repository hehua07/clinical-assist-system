# 在线 LLM 后端实测与接入设计（2026-07-19）

> 背景：本地 Qwen3-32B-NVFP4 仅 ~10tps，临床分析 ~93s。用户决定临时切换在线模型，更换更快服务器后回切本地。

## 实测结果（2026-07-19，从 Spark 直连）

| 模型 | 端点 | 实测 | 结论 |
|:--|:--|:--|:--|
| **DeepSeek-chat** | api.deepseek.com/v1 | **1.0s / 63tok（64.7tps）** | ✅ **首选**（key 已到位并验证） |
| GLM-4.5-flash | open.bigmodel.cn/api/paas/v4 | 3.0s / 73tok（24-43tps） | ✅ 备选 |
| Kimi K3 / K2.6 | api.moonshot.cn/v1 | 400 报错 | ❌ 强制 temperature=1，不适用 |

## Kimi 限制（K3 与 K2.6 均有）

请求带 `temperature: 0.1` 直接 400：
```json
{"error":{"message":"invalid temperature: only 1 is allowed for this model","type":"invalid_request_error"}}
```
thinking 类模型，无法低温输出严格 JSON → **不适用临床结构化分析**。Kimi key（.env `KIMI_API_KEY`/`KIMI_CN_API_KEY`）本身有效，仅模型行为不匹配。

## GLM-4.5-flash 接入要点

- 端点：`https://open.bigmodel.cn/api/paas/v4/chat/completions`（OpenAI 兼容）
- Key：.env `GLM_API_KEY`（智谱 b1ecf6...，与 ZAI_API_KEY 同值）
- **必须关闭 thinking**：`"thinking": {"type": "disabled"}`。不关则 reasoning 耗尽 max_tokens，`content` 返回空字符串
- `temperature: 0.1` 可用，`finish_reason: stop` 正常
- 输出常包 ```` ```json ```` 代码块标记，解析端需 strip
- 实测 24-43 tps，是本地的 2.5-4 倍

## DeepSeek 状态（✅ 已验证首选 2026-07-19）

- 端点：`https://api.deepseek.com/v1/chat/completions`，model `deepseek-chat`
- **新 key 已到位**：用户微信提供，已写入 .env `DEEPSEEK_API_KEY`（旧 key sk-c365...66c7 已废弃 401）
- 实测 **64.7 tps**（1.0s/63tok）——三者最快，是本地的 6.5 倍；**纯 JSON 输出无 \`\`\` 包裹**，`temperature: 0.1` 正常
- 预估：完整分析 ~28s；+ quick mode（~800tok）≈ **12-15s**
- 微信取 key 技巧：gateway 消息不在 TUI 会话库，查 `~/.hermes/state.db` 的 `gateway_routing` 表定位微信 session_id 再查 `messages`（见 hermes-troubleshooting skill）

## 接入现状（✅ 已实施 session 18；行号基于 main@92ddb64）

实际代码（rag_service.py L41-54）与本设计稿的差异：**默认值是 `online` 而非 `local`**：

```python
VLLM_BASE = "http://localhost:8200"                      # L41 硬编码
LLM_MODEL = "/home/hehua/models/Qwen3-32B-NVFP4"         # L43
RAG_LLM_PROVIDER  = os.environ.get("RAG_LLM_PROVIDER", "online")   # L48
RAG_ONLINE_BASE_URL/API_KEY/MODEL                        # L49-51 DeepSeek（key 回退 DEEPSEEK_API_KEY）
RAG_ONLINE2_BASE_URL/API_KEY/MODEL                       # L52-54 GLM（key 回退 GLM_API_KEY）
```

- 路由在 `_call_clinical_llm`（L2099-2128）：online = DeepSeek→GLM→本地 vLLM 兜底；GLM 的 `thinking:{"type":"disabled"}` 按 **base_url 含 bigmodel** 自动加（L2087-2088），不是按 model 名
- 脱敏在 `_desensitize`（L2060-2071）：身份证 18/15 位用 `(?<!\d)...(?!\d)` lookaround（`\b` 对 CJK 失效）、手机号、姓名列表替换"某患者"
- **回切零改代码**：换快服务器后 .env 改 `RAG_LLM_PROVIDER=local` 重启即回 vLLM
- ⚠️ 两个路由之外的例外（2026-07-21 只读侦察发现）：
  1. `/compliance/{visit_id}?mode=full`（L836-918）**绕过 provider 开关**，直连硬编码 DeepSeek（key 只认 `DEEPSEEK_API_KEY`，timeout=30，max_tokens=1024）——切 local 后此端点仍上云
  2. `SPARK_API_URL/SPARK_API_KEY/SPARK_MODEL`（L2052-2054）是死配置，全文件无调用点
- 当前 prompt 各段截断规格与"为速度精简掉的内容"清单见 `references/prompt-content-map.md`
