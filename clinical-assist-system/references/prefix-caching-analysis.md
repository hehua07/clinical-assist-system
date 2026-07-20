# vLLM Prefix Caching 利弊分析

> 分析日期：2026-07-18 | 系统：寿县和华医院临床AI辅助系统

## 背景

当前 vLLM (Qwen3-32B-NVFP4) 生成速度约 10 tokens/s，临床分析每次需生成 800-1300 tokens，耗时 100-130s。启用 prefix caching 可节省 system prompt prefill 时间。

## 原理

每个请求的 system prompt 完全相同（~2000 tokens）。Prefix caching 缓存 system prompt 的 KV cache，首请求计算一次后，后续请求直接复用。

```
无缓存:  每轮都从零计算整个 prompt
  ████████████████████████ (system prefill, ~15-20s)
  ████████████████████████ (user context prefill)
  ████████████████████████████████████████████ (generation, 80-100s)

有缓存:  system prompt 只算一次
  ✅ (system 命中缓存, 0s)
  ████████████████████████ (user context prefill)
  ████████████████████████████████████████████ (generation)
```

## ✅ 利

| 项 | 说明 |
|:--|:--|
| **耗时减少** | 每请求省 10-15s，目标从~99s → ~85s |
| **并发收益** | 多人同时使用时，所有请求共享同一份缓存，收益叠加 |
| **GPU 利用率提升** | 避免重复计算，省下的算力可服务更多请求 |
| **命中率 100%** | system prompt 完全固定，不会有冷启动惩罚（除首请求） |
| **零代码改动** | 纯 vLLM 启动参数 `--enable-prefix-caching`，不影响 RAG/Frontend 代码 |

## ❌ 弊与风险

| 项 | 说明 | 严重度 |
|:--|:--|:--|
| **需要重启 vLLM** | 2-3 分钟宕机，所有分析中断 | ⚠️ 中 |
| **重启失败风险** | 上次 256K 上下文导致 OOM；当前 16384 稳定但重启未知 | ⚠️ 中 |
| **额外 GPU 显存** | 缓存占用额外显存，但当前只用了 50% (gpu-memory-utilization=0.50)，余量充足 | 🟢 低 |
| **缓存管理开销** | 轻微 CPU/显存开销 | 🟢 低 |
| **与 enforce_eager 兼容性** | 理论上兼容但未经本环境测试 | 🟡 低-中 |
| **system prompt 不可变** | 修改 prompt 后缓存失效需重建 | 🟢 低 |

## 估算

```
当前优化后:  0.1s(Oracle) + 0.9s(向量) + 97s(LLM) ≈ 99s
加 prefix caching:  0.1s(Oracle) + 0.9s(向量) + 82s(LLM) ≈ 85s
节省:  ~14s (约 14%)
```

## 操作命令

```bash
# 1. 停 vLLM (确保在维护窗口，无活跃用户)
kill -15 $(pgrep -f vllm.entrypoints)
sleep 5

# 2. 带 prefix caching 启动
deactivate  # 退出 Hermes venv
nohup python3 -m vllm.entrypoints.openai.api_server \
  --model /home/hehua/models/Qwen3-32B-NVFP4 \
  --port 8200 --host 0.0.0.0 \
  --max-model-len 16384 \
  --gpu-memory-utilization 0.50 \
  --trust-remote-code \
  --quantization modelopt \
  --enforce-eager \
  --enable-prefix-caching \
  > /tmp/vllm_pc.log 2>&1 &

# 3. 等预热 + 验证（约2-3分钟）
sleep 120
curl -s http://127.0.0.1:8200/v1/models | head -1

# 4. 如果失败，去掉 --enable-prefix-caching 恢复原样
```

## 决策建议

**等维护窗口（如深夜无用户时）再操作**。收益确定（省 10-15s），但重启期间服务中断，日间有活跃用户时不应操作。

## 其他优化方向（对比）

| 方案 | 预期提速 | 风险 | 是否需改代码 |
|:--|:--|:--|:--|
| Prefix caching | 14s | 低（重启） | 否 |
| 换小模型 (14B/7B) | 40-60s | 中（质量下降） | 否 |
| 批量推理 | 视并发 | 低 | 是 |
| 减少 embedding 调用 | 0.5s | 低 | 是 |
