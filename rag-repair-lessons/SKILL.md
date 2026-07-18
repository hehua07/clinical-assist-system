---
name: rag-repair-lessons
description: "RAG临床辅助系统反复故障的根因分析与修复经验，包括max_tokens截断、timeout不一致、备份版本混乱、json解析鲁棒性等教训。任何智能体在处理RAG相关问题时，必须先加载本技能。"
version: 1.1.0
author: hehua
platforms: [linux]
---

# RAG 系统修复经验教训

## 核心原则

1. **改代码前先备份** — 每次修改前 `cp rag_service.py rag_service.py.bak.$(date +%Y%m%d_%H%M%S)`
2. **只改一个变量，验证一个** — 不要一次性改多个参数，否则不知道哪个修好了问题
3. **日志是上帝** — `tail -f /tmp/rag_final*.log` 实时看，不要猜

## 已知故障根因

### 1. max_tokens 截断导致 JSON 解析失败（最高频！）
- **症状**: `LLM输出解析失败`，`raw_response` 末尾明显不完整
- **根因**: `rag_service.py` 中 `LLMClient.chat()` 的 `max_tokens` 被设为 1200，但LLM输出需要 2500+
- **修复**: 
  ```bash
  sed -i 's/"max_tokens": 1200/"max_tokens": 2500/' rag_service.py
  sed -i 's/"max_tokens": 500/"max_tokens": 1024/' rag_service.py
  ```
- **验证**: 看 `raw_response` 长度是否 > 2500，且末尾是完整JSON的 `}`

### 2. timeout 不一致（多个地方有不同的值）
- **症状**: 分析超时，前端显示 `signal timed out`
- **根因**: `rag_service.py` 中 timeout 有 120、180、300 三个不同值，每次恢复备份会覆盖
- **修复**: 全局统一为 300
  ```bash
  sed -i 's/timeout=120)/timeout=300)/g' rag_service.py
  sed -i 's/timeout=180)/timeout=300)/g' rag_service.py
  ```
- **验证**: `grep 'timeout=' rag_service.py` 确认全部是 300

### 3. CHROMA_PATH 指向错误目录
- **症状**: health 返回 patients=0, visits=0, dip_rules=0
- **根因**: 目录从 `rag-service/` 变为 `rag-service.bak/` 后，CHROMA_PATH 没更新
- **修复**: 
  ```bash
  sed -i 's|/home/hehua/rag-service/chroma_data|/home/hehua/rag-service.bak/chroma_data|' rag_service.py
  ```
- **验证**: `grep CHROMA_PATH rag_service.py | head -1`

### 4. 备份版本混乱
- **症状**: 恢复备份后发现 dip_operations 等功能缺失
- **根因**: 有 10+ 个 bak 文件，恢复时用了旧的 `bak.dip_logic`（不含新功能）
- **规则**: 
  - `rag_service.py.bak.dip_logic` = 基础版（无dip_operations）
  - `rag_service.py.bak.20260715_205904` = 完整版（含dip_operations、selected_operation等）
  - **恢复完整版**用：`cp rag_service.py.bak.20260715_205904 rag_service.py`
- **验证**: `grep 'dip_operations' rag_service.py` 如果有输出说明是完整版

### 5. JSON 解析鲁棒性不足
- **症状**: LLM 输出正确JSON但解析失败
- **修复**: 加 `strict=False` + 尾部逗号兼容
  ```python
  import re as _re
  clean2 = _re.sub(r',\s*([\]}])', r'\1', clean)
  result = json.loads(clean2, strict=False)
  ```

### 6. 日志混淆：旧进程日志 vs 新进程输出
- **症状**: 修代码后重启RAG，但tail日志看到的启动信息（如LLM_MODEL）与当前代码不一致
- **根因**: RAG 有 2 种启动方式，stdout 走不同的通道：
  - `nohup ... > /tmp/rag_final.log` — stdout 写文件。只有 nohup 启动的进程会写，文件内容持久
  - Hermes `terminal(background=true)` — stdout 走内部 pipe（`/proc/<pid>/fd/1 -> pipe`），不写文件
  - 重启后旧 nohup 进程的日志仍残留，tail 看到的是错误内容
- **诊断**: 
  ```bash
  ls -la /proc/$(pgrep -f rag_service | head -1)/fd/1
  # pipe → Hermes bg 启动; 文件 → nohup 启动; socket → 其他
  ```
- **修复**: 用 Hermes 的 `process(action='log', session_id=...)` 看正确的进程输出

### 7. 性能瓶颈定位：TIMER 打点法
- **症状**: 分析慢（100s+）但不知道哪个阶段慢
- **修复**: 在 `clinical_assist()` 的三个关键阶段加计时：
  ```python
  _t0 = time.time()
  vector_results = _clinical_vector_search(search_query, n=3)
  print(f"[TIMER] 向量搜索: {time.time()-_t0:.1f}s", flush=True)
  
  _t0 = time.time()
  llm_response = _call_clinical_llm(...)
  print(f"[TIMER] LLM推理: {time.time()-_t0:.1f}s (输出{len(llm_response)}字符)", flush=True)
  ```
- **验证**: 看进程输出中的 [TIMER] 行。本系统：Oracle 0.1s + 向量 0.9s + LLM 97-150s（99%瓶颈）
- **优化方向**: LLM慢则精简prompt/减少输出；向量慢则检查Ollama是否GPU模式

## RAG 启动故障排查流程

```bash
# 1. 先检查端口是否被占用
ss -tlnp | grep 18790

# 2. 检查日志最新内容
tail -10 /tmp/rag_final*.log

# 3. 检查是否有旧进程残留
ps aux | grep rag_service | grep -v grep

# 4. 如果 health 返回 0 数据，查 CHROMA_PATH
grep CHROMA_PATH /home/hehua/rag-service.bak/rag_service.py

# 5. 如果 LLM 解析失败，查 raw_response 长度
grep 'max_tokens' /home/hehua/rag-service.bak/rag_service.py

# 6. 如果超时，查 timeout 值
grep 'timeout=' /home/hehua/rag-service.bak/rag_service.py | grep -v 'def'

# 7. 如果 dip_operations 消失，查备份版本
grep 'dip_operations' /home/hehua/rag-service.bak/rag_service.py
```

## 一键健康检查

```bash
# RAG 状态
curl -s http://127.0.0.1:18790/health | python3 -m json.tool

# vLLM 状态
curl -s http://127.0.0.1:8200/v1/models | python3 -m json.tool

# Ollama 状态
curl -s http://127.0.0.1:11434/api/version

# Gateway 状态
tail -3 ~/.hermes/logs/gateway.log
```

## 修改规范（新增）

1. **改 `rag_service.py` 前必须备份**
2. **改完必须验证**：
   ```bash
   python3 -c "import py_compile; py_compile.compile('rag_service.py', doraise=True); print('OK')"
   ```
3. **重启 RAG 后必须测试**：
   ```bash
   sleep 35
   python3 -c "import urllib.request, json; r=json.loads(urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:18790/clinical/assist', data=b'{\"patient_name\":\"蔡维良\"}', headers={'Content-Type':'application/json'}), timeout=300).read()); a=r['analysis']; print('OK' if 'primary_diagnosis' in a else 'FAIL: '+a.get('error','?'))"
   ```
4. **修改记录必须写到本技能的 Changelog**
5. **如果连续 3 次重启失败，恢复备份并记录失败原因**

## Changelog

### 2026-07-18 (p2)
- **新增**: 日志混淆问题 — nohup vs Hermes bg 启动，stdout 走不同通道，tail 旧日志会误导
- **新增**: TIMER 打点法 — 性能瓶颈定位（Oracle/向量/LLM 三段计时）
- **新增**: prompt 精简技巧 — compliance_analysis 结构从 verbose nested → 简短 nested，指令从15条→8条

### 2026-07-18
- 创建本技能，记录所有已知故障根因
- max_tokens 1200→2500（修复LLM输出截断）
- timeout 统一为300（修复超时）
- json.loads 加 strict=False + 尾部逗号兼容（修复解析失败）
- 明确备份版本选择规则
- **新增**: RAG服务必须用 /usr/bin/python3 启动（非hermes-venv的python3，后者缺oracledb）
- **新增**: _format_dip_rules 中 score 字段应读 `std_score`（向量搜索返回的字段名），而非 `std_dip_value`（ChromaDB原始metadata字段名）
