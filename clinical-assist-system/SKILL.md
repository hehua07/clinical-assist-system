---
name: clinical-assist-system
description: "寿县和华医院临床AI辅助系统（RAG + vLLM + DIP匹配）的调试记录、当前状态、已知问题和修复方案。任何智能体对系统进行修改后，必须更新此技能。"
version: 1.4.0
author: hehua
platforms: [linux, macos, windows]
---

# 临床AI辅助系统调试状态

## 当前状态（2026-07-18）

| 组件 | 状态 | 备注 |
|:--|:--:|:--|
| vLLM | ✅ 运行 | Qwen3-32B-NVFP4, :8200, max-model-len=16384 (prefix caching待加,需重启) |
| RAG服务 | ✅ 运行 | :18790, 路径 /home/hehua/rag-service.bak/ |
| Ollama | ✅ 运行 | :11434, qwen3-embedding (v0.32.1, **GPU模式**) |
| ChromaDB | ✅ 运行 | dip_rules=4481, settlement_2025=4704 |
| LLM引擎 | 走vLLM | timeout 300s, max_tokens 2500, 生成约10tps |
| 前端页面 | 返回HTML | nginx代理 https://www.hhysjt.com/clinical/ |
| dip_operations | ✅ 正常 | 淮南分值库操作列表(20+条)，按分值降序 |
| settlement_operations | ✅ 正常 | 结算参考数据(2-3条) |
| selected_operation | ✅ 可用 | 二次分析选用功能正常 |

### 性能数据

| 阶段 | 耗时 | 说明 |
|:--|:--|:--|
| Oracle查询 | 0.1-2.5s | 患者数据+病历首页+检验+医嘱+手术 |
| 向量搜索 | 0.9-1.6s | 7路并行搜索(DIP/结算/定价/合规/相似病例等) |
| LLM推理 | 100-130s | Qwen3-32B 生成~800-1300 tokens @ 10tps |

**总耗时: 100-140秒**，瓶颈为LLM推理速度（Qwen3-32B NVFP4 在 GB10 上的硬件极限）。

## 已知问题

### 1. LLM推理速度慢（100-130秒）
- **原因**: Qwen3-32B NVFP4 在 GB10 上生成约 10 tokens/s，临床分析需输出 800-1300 tokens
- **已做优化**: 精简system prompt（合规分析结构简化+指令精简）, 病程记录 100-200字→30-60字, 添加[TIMER]计时日志定位瓶颈
- **待做**: vLLM 加 `--enable-prefix-caching` (需重启，阻塞于日间有活跃用户), 可节约10-15s
- **瓶颈**: 硬件限制，软件优化后从~130s降至~100s(提速24%)

### 2. 讯飞Spark API Key 授权失效
- **报错**: `AppIdNoAuthError (code=11200)`
- **原因**: API Key 过期
- **状态**: 当前未使用，走 vLLM 本地推理

### 3. 智谱GLM API 偶尔连接失败
- **凭据**: `b1ecf63acd54425396f93233eb4580b0.mCueRleTtZHe7dKS`
- **状态**: 当前未使用

## 系统架构
```
用户浏览器 → https://www.hhysjt.com/clinical/
  → 阿里云 nginx (proxy_read_timeout=300s)
    → frp隧道 → Spark :18790 (RAG服务)
      → ChromaDB 向量搜索 ← Ollama embedding
      → vLLM :8200 (Qwen3-32B 推理)
      → Oracle HISEMR (192.168.20.49:1521)
```

## RAG服务操作

### 启动
```bash
# 注意：必须用 /usr/bin/python3，不能用 hermes-venv 的 python3（缺 oracledb）
cd /home/hehua/rag-service.bak && nohup /usr/bin/python3 rag_service.py > /tmp/rag_final.log 2>&1 &
```

### 停止
```bash
kill -9 $(pgrep -f rag_service)
```

### 重启（修改代码后）
```bash
kill -9 $(pgrep -f rag_service)
sleep 3
rm -rf /home/hehua/rag-service.bak/__pycache__
cd /home/hehua/rag-service.bak && nohup python3 rag_service.py > /tmp/rag_final.log 2>&1 &
curl -s http://127.0.0.1:18790/health
```

## vLLM操作

### 启动（标准 16384 上下文 + prefix caching 推荐）
```bash
deactivate  # 退出Hermes venv
nohup python3 -m vllm.entrypoints.openai.api_server \
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
⚠️ `--enable-prefix-caching` 可节省每次请求的 system prompt prefill (~10-15s)。但重启 vLLM 会使当前活跃请求中断，建议在维护窗口操作。

## 关键文件路径

| 文件 | 路径 |
|:--|:--|
| RAG主程序 | `/home/hehua/rag-service.bak/rag_service.py` |
| 前端HTML | `/home/hehua/rag-service.bak/clinical_assist_page.html` |
| ChromaDB | `/home/hehua/rag-service.bak/chroma_data/` |
| 备份rag（含dip逻辑） | `rag_service.py.bak.dip_logic` |
| Oracle HISEMR | `192.168.20.49:1521/HISEMR`, 用户 `his_ro/his_ro`, Schema `ICSHIS6` |

## 中医 nihaixia 融合（测试完成，待实施）

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

## 修改规范（重要！）

任何智能体修改必须：
1. 修改前备份原文件（`.bak.日期时间`）
2. 验证语法：`py_compile.compile()`（Python）+ `new Function()`（JS）
3. 重启 RAG 服务
4. 用 `curl` 测试 `POST /clinical/assist`
5. **记录到下方 Changelog**
6. 如崩溃：`cp rag_service.py.bak.dip_logic rag_service.py`

## Changelog

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
