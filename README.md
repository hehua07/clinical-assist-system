# Hermes 临床AI辅助系统 Skills

寿县和华医院临床AI辅助系统的调试、维护和修复经验。

## 包含的 Skills

| Skill | 用途 | 行数 |
|:--|:--|--:|
| `clinical-assist-system` | 系统架构、组件状态、操作手册、修改规范 | ~290行 |
| `rag-repair-lessons` | 已知故障根因、修复方案、排查流程、性能优化 | ~200行 |

## 安装

```bash
# 克隆到任意 Hermes 实例
git clone git@github.com:hehua07/hermes-clinical-assist-skills.git /tmp/clinical-skills

# 安装 skills
cp -r /tmp/clinical-skills/clinical-assist-system ~/.hermes/skills/
cp -r /tmp/clinical-skills/rag-repair-lessons ~/.hermes/skills/

# 验证
ls ~/.hermes/skills/clinical-assist-system/SKILL.md
ls ~/.hermes/skills/rag-repair-lessons/SKILL.md
```

安装后，Hermes 智能体在遇到医师辅助系统相关任务时会自动加载这两个 skill。

## 使用效果

安装后智能体获得：
- ✅ 系统架构和当前状态（不会从头诊断）
- ✅ 所有已知故障根因和修复方案（不会重复踩坑）
- ✅ 正确的启动/重启/健康检查命令
- ✅ 性能瓶颈数据（Oracle 0.1s + 向量 0.9s + LLM 100s）
- ✅ 性能优化方向（prompt 精简、prefix caching）

## 涵盖的故障知识

1. `max_tokens` 截断导致 JSON 解析失败
2. `timeout` 不一致导致超时
3. `CHROMA_PATH` 指向错误目录
4. 备份版本混乱（10+ 个 bak 文件）
5. JSON 解析鲁棒性不足
6. 日志混淆（nohup vs Hermes bg 启动）
7. 性能瓶颈定位（TIMER 打点法）
8. RAG 服务 Python 解释器路径（必须用 `/usr/bin/python3`）
9. DIP 分值字段名不匹配（`std_score` vs `std_dip_value`）
