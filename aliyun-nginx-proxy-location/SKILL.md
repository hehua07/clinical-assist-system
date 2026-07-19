---
name: aliyun-nginx-proxy-location
description: 在阿里云 nginx (conf.d/hhysjt.conf) 上添加反向代理 location 到本机 frp 隧道服务
version: 1.3.0
---

# 阿里云 Nginx 添加反向代理 Location

## 场景

RAG 服务在本机（DGX Spark）运行在 18790 端口，通过 frp 隧道映射到阿里云服务器 `127.0.0.1:18790`。需要在阿里云 nginx 添加 `location /guideline` 等反向代理。

## 架构

```
用户 → www.hhysjt.com (阿里云 nginx) → location /guideline → proxy_pass 127.0.0.1:18790 → frp 隧道 → 本机 RAG
```

## 阿里云配置位置

**不是** `/etc/nginx/sites-enabled/default`，而是：
```
/etc/nginx/conf.d/hhysjt.conf
```

## 阿里云 Workbench 终端限制

阿里云 Workbench（浏览器 web 终端）有以下已知限制，操作时必须注意：

- **`cat > file << 'EOF' heredoc 失效** — 敲回车后立刻回到 shell 提示符，不进入 heredoc 模式
- **任何超过 ~70 字符的命令行都可能被断行**（2026-07-19 实测 200+ 字符命令在 `>>` 处断裂：前半句 syntax error，后半句被当成新命令执行报 Permission denied）。发给用户的每条命令必须 ≤70 字符；长内容用 `echo -n '段1' > /tmp/f` + `echo -n '段2' >> /tmp/f` 分段拼装再 `cat` 到位
- **单行 `echo` 内容超长时可能 `syntax error near unexpected token`**
- **`computer_use` 的 `type` 无法向终端输入**（无 AT-SPI focus-free 后端）
- 正确工作流：准备命令 → 发给用户 → 用户复制粘贴到 Workbench 执行 → 用户反馈输出

## 方法 0：SSH 直连（首选 — 2026-07-19 验证网络可达）

**不要再默认走 Workbench 盲终端 relay。** 2026-07-19 实测：从 Spark 执行
`ssh root@47.102.41.191` 网络层完全可达（TCP/22 通、SSH 握手成功），仅因
阿里云 `/root/.ssh/authorized_keys` 缺 Spark 公钥而 `Permission denied
(publickey)`。旧记录里"Spark 直连阿里云被防火墙阻挡"的判断**是错的**。

一次性安装公钥（让用户在 Workbench 粘贴，只需执行一次）。

⚠️ **不要发一条 200+ 字符的长命令** — 2026-07-19 实测：长命令粘贴时在 `>>`
后被断行，前半句报 `syntax error near unexpected token 'newline'`，后半句
`/root/.ssh/authorized_keys && chmod ...` 被当成独立命令去"执行"该文件，
报 `Permission denied`。整条失败、公钥未写入。用户对此明确反馈"不要走错误的老路子"。
## 方法 0：SSH 直连（✅ 已打通 — 2026-07-19 公钥已安装）

**公钥已安装完成，SSH 直连可用，这是唯一首选方式：**

```bash
ssh -i /home/hehua/.ssh/id_ed25519 -o BatchMode=yes root@47.102.41.191 '命令'
```

**写文件首选 scp 从本地上传**（完全避开 shell 引号/断行问题）：

```bash
# 1. 本地用 write_file 写好 /tmp/hhysjt.conf.new
# 2. 上传 + 测试 + 重载
scp -i /home/hehua/.ssh/id_ed25519 /tmp/hhysjt.conf.new root@47.102.41.191:/etc/nginx/conf.d/hhysjt.conf
ssh -i /home/hehua/.ssh/id_ed25519 root@47.102.41.191 'nginx -t && nginx -s reload'
```

历史记录：2026-07-19 实测网络可达（TCP/22 通），仅缺公钥；旧记录"Spark 直连阿里云被防火墙阻挡"是错的。公钥通过 7 条 ≤67 字符短命令（拆段 echo 到 /tmp/k.pub 再 append）让用户在 Workbench 一次性安装——长命令整行 echo 必被 Workbench/微信断行截断，切勿再用。

## 2026-07-19 修复案例：空配置导致全站瘫痪

- **事故**：`hhysjt.conf` 被失败写入截断成 0 字节，全站只剩 nginx 默认页
- **恢复**：以最新备份 `hhysjt.conf.bak4`（7052 字节）为基础，收回两个悬空在 server 块外的 location（/guidelines/、/guidelines-api/），新增 /guideline 反代，本地构建后 scp 上传
- **教训**：备份文件命名 `.bak4` 等数字后缀，最新的不一定是 .bak；恢复前先 `ls -la` 对比大小和日期

## 写入方法优先级（阿里云 Workbench，仅当 SSH 不可用时）

从最可靠到最不可靠：

1. **`python3 -c "..."`**（推荐，最可靠）— 用 Python 的 triple-quoted string 避免 shell 问题
2. **`python3 << 'PYEOF' ... PYEOF`** — 也可靠
3. **`echo '...' > /path`** — 单引号防 $ 展开，但长字符串可能报错
4. **`cat > /path << 'EOF'`** — 最不可靠（阿里云 Workbench heredoc 经常失效）

## 核心坑：`nginx -t` 通过 ≠ 文件真的被写了！

这是本 session 最重要的教训。如果 `echo` 报语法错误或 heredoc 无声失败，磁盘上的文件**没变**——但 `nginx -t` 读取旧的配置文件并报告 "syntax is ok"，给你虚假的成功感。

**每次重写后必须做双重验证：**

```bash
# 第一重：检查文件实际内容
grep -c "listen 443" /etc/nginx/conf.d/hhysjt.conf
# 应输出 ≥2（ipv4 + ipv6）

# 第二重：检查端口监听
ss -tlnp | grep 443
# 应看到 LISTEN 0 511 0.0.0.0:443

# 如果以上任何一项不通过 → 写入失败，换方法重试
```

## 诊断检查清单

重写前先收集所有信息，一次性发给用户：

```bash
ss -tlnp | grep -E '443|80'
cat /etc/nginx/conf.d/hhysjt.conf
nginx -T 2>&1 | grep -A30 "server_name www.hhysjt.com"
grep -n 'listen\|ssl_certificate' /etc/nginx/conf.d/hhysjt.conf
```

常见发现：
- `ss` 显示 `*:80` 但没有 `*:443` → 缺少 `listen 443 ssl;`
- `nginx -T` 显示 location 在 server{} 外面 → 文件被弄乱了
- `cat` 只有 19 行（单行长行）→ 文件处于压缩格式

## 完整 server 块配置参考

见本技能 `references/hhysjt-nginx-server-block.conf`——包含所有 location、SSL 和路由配置。可作为备份模板使用。

## 方法 1：完全重写主配置文件（推荐，当配置已损坏时）

当主配置已被 sed/插入搞乱（location 跑到了 server{} 外面），**不要试图修补**——直接重写整个文件。

### 步骤 1：备份

```bash
cp /etc/nginx/conf.d/hhysjt.conf /etc/nginx/conf.d/hhysjt.conf.bak.$(date +%Y%m%d)
```

### 步骤 2：检查阿里云 Workbench 终端是否支持 heredoc

```bash
# 如果 heredoc 能工作，用这个（更安全，变量不展开）
cat > /etc/nginx/conf.d/hhysjt.conf << 'NGXEND'
server {
    listen 80;
    listen [::]:80;
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    ...
}
NGXEND
```

**如果 heredoc 失效**（最常见的阿里云 Workbench 问题），使用 python3 写文件——这是最可靠的方式：

```bash
python3 << 'PYEOF'
import os
conf = """server {
    listen 80;
    listen [::]:80;
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name www.hhysjt.com hhysjt.com;
    ...
}
"""
with open('/etc/nginx/conf.d/hhysjt.conf', 'w') as f:
    f.write(conf)
print('Written', len(conf), 'bytes')
PYEOF
```

**如果 python3 heredoc 也失效**（极少见），使用单行 echo，但注意：
- ⚠️ 内容过长时 shell 可能报 `syntax error near unexpected token`
- ⚠️ 如果 echo 报错，文件不会被写入（空文件）
- 用 `skill_view` 读取本技能的 `references/hhysjt-nginx-server-block.conf` 然后提取内嵌的单行版本

```bash
python3 -c "
import os
conf = '''server {
    listen 80;
    listen [::]:80;
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name www.hhysjt.com hhysjt.com;
    ...
}
'''
with open('/etc/nginx/conf.d/hhysjt.conf', 'w') as f:
    f.write(conf)
print('Written', len(conf), 'bytes')
"
```

### 步骤 4：测试并重载

```bash
nginx -t && nginx -s reload
```

### 步骤 5：验证——必须双重检查

⚠️ **`nginx -t` 通过不代表文件真的被写了！** 如果写入失败（echo 报错、heredoc 不生效、文件为空），`nginx -t` 会使用**磁盘上旧的配置文件**并告诉我通过了——这是这个 session 遇到的真实坑。

**必须做双重验证：**

```bash
# 第一重：确认 listen 443 实际写入了
grep -c "listen 443" /etc/nginx/conf.d/hhysjt.conf
# 应该输出 2（ipv4 + ipv6）

# 第二重：确认 nginx 实际监听了 443
ss -tlnp | grep 443
# 应该看到类似 LISTEN 0  511  0.0.0.0:443

# 如果上面两个检查不通过，文件没被成功写入——换另一种写入方法重试
```

### 步骤 4：验证（HTTP 和 HTTPS 都要测）

```bash
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://www.hhysjt.com/guideline/search?diagnosis=糖尿病
curl -s -o /dev/null -w "HTTP %{http_code}\n" https://www.hhysjt.com/clinical/
```

## 方法 2：独立文件 + include（仅当主配置未损坏时）

当主配置完全正常，只需追加新 location 时：

### 创建独立配置文件（单行 echo）

```bash
echo 'location /guideline { proxy_pass http://127.0.0.1:18790; proxy_set_header Host $host; proxy_set_header X-Real-IP $remote_addr; proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for; proxy_read_timeout 300s; } location ~ ^/clinical(/.*)?$ { proxy_pass http://127.0.0.1:18790; proxy_set_header Host $host; proxy_set_header X-Real-IP $remote_addr; proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for; proxy_read_timeout 300s; add_header Cache-Control "no-cache" always; } location /api/ { proxy_pass http://127.0.0.1:18790; proxy_set_header Host $host; proxy_set_header X-Real-IP $remote_addr; proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for; proxy_read_timeout 30s; }' > /etc/nginx/rag-routing.conf
```

### 在 server 块最后一个 } 前插入 include

```bash
sed -i '$i\    include /etc/nginx/rag-routing.conf;' /etc/nginx/conf.d/hhysjt.conf
```

### 测试并重载

```bash
nginx -t && nginx -s reload
```

## 如果配置彻底损坏：恢复建议

```bash
# 1. 先用备份恢复
cp /etc/nginx/conf.d/hhysjt.conf.bak /etc/nginx/conf.d/hhysjt.conf
nginx -t && nginx -s reload

# 2. 如果没有备份，先检查行数
wc -l /etc/nginx/conf.d/hhysjt.conf

# 3. 然后使用 "完全重写" 方法（方法 1）
```

## 注意事项

- 所有 location 必须在 `server { }` 块**内部**，不能在外面
- `$host`、`$remote_addr` 等在单引号中不会被 shell 展开
- 阿里云是 CentOS/AlmaLinux，用 `yum` 不是 `apt`
- **如果 sed 插入失败**（location 跑到了 server 块外面），不要反复 sed——立即切换到"完全重写"模式
- 备份文件用日期后缀 `.bak.$(date +%Y%m%d)`，方便识别
- 重写后一定测试 HTTP **和** HTTPS 两个协议，SSL 部分可能因 server 块边界错误而受影响
- 本机测试通过公网访问：`curl -sI http://www.hhysjt.com/...`

## 本机 frp 隧道检查

在重写 nginx 之前，先确认 frp 隧道正常：

```bash
curl -s http://127.0.0.1:18790/health
```
