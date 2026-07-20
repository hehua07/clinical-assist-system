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

## 接入设计（rag_service.py，尚未实施）

```python
RAG_LLM_PROVIDER = os.environ.get("RAG_LLM_PROVIDER", "local")  # local|online
RAG_ONLINE_BASE_URL = os.environ.get("RAG_ONLINE_BASE_URL", "https://api.deepseek.com/v1")
RAG_ONLINE_API_KEY  = os.environ.get("RAG_ONLINE_API_KEY") or os.environ.get("DEEPSEEK_API_KEY", "")
RAG_ONLINE_MODEL    = os.environ.get("RAG_ONLINE_MODEL", "deepseek-chat")
```

- `_call_clinical_llm` 按 provider 路由；GLM 作备选时须带 `thinking: {"type": "disabled"}`（可按 model 名以 glm 开头自动加）
- **回切零改代码**：换快服务器后 `RAG_LLM_PROVIDER=local` 重启即回 vLLM
- ⚠️ 隐私：病情描述上云，建议默认脱敏（去姓名/身份证号）——正则身份证 `\d{17}[\dXx]`、手机号 `1[3-9]\d{9}`，姓名在拼 prompt 前从 patient_data 抹除
