# ChromaDB guidelines 集合段级损坏 → 以站为源全量重建（2026-07-21 晚实录）

## 事故时间线

1. 当晚为「需求4b：网站为源定时同步入库」跑 `sync_guidelines_from_web.py` 首次全量同步
2. 期间出现**两个并发同步进程**（重复发起）+ 一次 pkill 清理（EXIT:143）
3. 随后任何对 `guidelines` 集合的读取**直接段错误（SIGSEGV, exit 139）**：

```
Fatal Python error: Segmentation fault
  File ".../chromadb/api/rust.py", line 440 in _get
  File ".../chromadb/api/models/Collection.py", line 161 in get
```

`coll.count()`、`coll.get(limit=1)` 均崩；核心已转储。

## 诊断法（三辨）

| 检查 | 结果 | 含义 |
|:--|:--|:--|
| `sqlite3 chroma.sqlite3 "PRAGMA integrity_check"` | `ok` | **sqlite 元数据层完好**——不是库文件损坏 |
| 其他集合（emr_cases.count()=38293 等） | 全部正常 | 损坏是**集合级**，不是实例级 |
| 段文件 `chroma_data/<segment-uuid>/{data_level0.bin, link_lists.bin, ...}` mtime | 恰在事故窗口内被改写 | **HNSW 向量段文件损坏** |

定位段 UUID 的方法：

```bash
sqlite3 "file:.../chroma.sqlite3?mode=ro" \
  "SELECT c.name, s.id, s.scope FROM segments s JOIN collections c ON s.collection=c.id WHERE c.name='guidelines';"
# guidelines|<VECTOR段uuid>|VECTOR  ← 坏的就是这个目录
# guidelines|<METADATA段uuid>|METADATA
```

**鉴别**：rag-repair-lessons §13（进程态损坏，重启即好）、§19（EF 冲突，启动崩溃+journal 有 ValueError）。本节是**数据段损坏**——重启不复现崩溃但读取必崩，health 端点报 `{"status":"error","detail":"Collection [uuid] does not exist."}`（服务其余集合正常）。

**根因推断**：并发写 + pkill 中断写，HNSW 段 bin 文件半写状态。未深究其必然性——教训按「批量写前必须备份 + 单进程纪律」记录。

## 修复全流程（实测通过）

```bash
# 1. 整库冷备份（5.9G，先确认磁盘空间）
cp -a /home/hehua/rag-service.bak/chroma_data /home/hehua/chroma_data.bak.$(date +%Y%m%d_%H%M%S)

# 2. 删掉损坏集合（sqlite 层完好，删除可正常执行）
/usr/bin/python3 -X faulthandler -c "
import chromadb
c = chromadb.PersistentClient(path='/home/hehua/rag-service.bak/chroma_data')
c.delete_collection('guidelines')"

# 3. 同步脚本改为幂等建集合——⚠️ 必须带与原集合相同的 metadata
#    hnsw:space=cosine 是指南检索 0.58 阈值体系的前提，丢了阈值全废
#    embedding_function 必须绑（rag-repair-lessons §19 铁律）
coll = client.get_or_create_collection(
    COLL, embedding_function=ef,
    metadata={"description": "指南共识(治理版v3, web同步维护)", "hnsw:space": "cosine"})

# 4. 清状态文件，单进程全量重建
rm -f /home/hehua/guidelines_scraper/web_sync_state.json
cd /home/hehua/guidelines_scraper && /usr/bin/python3 -X faulthandler sync_guidelines_from_web.py
```

- 重建速率实测：约 35 页/4 分钟（132 页总量 ≈ 15 分钟），逐页 `新增 <标题>: N块` 日志
- **过渡期预期**：重建完成前 rag-service `/health` 报 `Collection [...] does not exist` 属正常——指南检索暂不可用，相似病历/DIP/患者查询等其余功能不受影响。**不要**看到这个就重启服务或回滚
- 重建完成后必须验证：health 恢复 ok + guidelines 块数（基准 3192 块/138 篇）+ 一次 quick 冒烟确认 guideline_refs 正常返回

## sync_guidelines_from_web.py 使用要点（需求4b 产物）

- **定位**：网站（`https://www.hhysjt.com/guidelines/display/`）为单一事实源；抓 index.html → 逐页抓全文 → 复用 `curate_guidelines.clean_for_vector` 清洗 → 哈希增量 upsert 进 `guidelines` 集合
- 状态文件 `web_sync_state.json` 记录已同步页哈希；**删掉它 = 全量重建**，保留 = 增量
- fetch 前对 URL 做 `urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%")`——展示页文件名含中文，不转码 urllib 报 ascii codec 错
- 页面失败率上限 `MAX_PAGE_FAIL_RATIO = 0.2`，超过即中止（防半库覆盖）
- **单进程纪律**：发起前 `pgrep -f sync_guidelines_from_web.py` 确认无存活；pgrep 计数会把 bash 包装层算进去（实测 count=3 实为 wrapper+python+pgrep 自身），用 `ps aux | grep ... | awk '{print $2,$11,$12}'` 看真实进程
- 后续形态：每日 cron 跑增量；网站内容更新即知识库更新

## 预防铁律

1. **任何批量写 chroma 的脚本，跑前 `cp -a` 整库备份**（5.9G 约 1 分钟，磁盘 8% 水位无压力）
2. 建/取集合一律 `get_or_create_collection(EF + hnsw:space=cosine)`，杜绝裸 `get_collection`（§19）与丢 metadata 的重建
3. 同步类脚本单进程运行；中断（pkill/断电）后下次跑前先按本文「三辨」抽检集合可读性
