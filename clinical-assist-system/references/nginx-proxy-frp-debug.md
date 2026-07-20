# nginx + frp 反向代理调试笔记

## 架构

```
用户浏览器 → www.hhysjt.com:80 (阿里云 nginx)
  → location /clinical { proxy_pass http://127.0.0.1:18790; }
    → frp 隧道 (阿里云 frps ← Spark frpc)
      → Spark :18790 (RAG服务 FastAPI/uvicorn)
```

## ⚠️ 配置路径：先确认 OS 再动文件

**2026-07-19 关键教训**: 阿里云 nginx 配置在 `/etc/nginx/conf.d/hhysjt.conf`（CentOS），不是 Ubuntu 的 `sites-enabled/default`。远程配置前必须先确认：

```bash
cat /etc/os-release | head -3            # 确认 OS 类型
grep "include" /etc/nginx/nginx.conf      # 看主配置的 include 路径
nginx -T 2>&1 | grep "server_name\|location"  # dump 全部生效配置
```

- CentOS / RHEL / Alibaba Linux → `/etc/nginx/conf.d/*.conf`
- Ubuntu / Debian → `/etc/nginx/sites-enabled/default`

## 已验证能用的完整 nginx server 块

```nginx
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name www.hhysjt.com hhysjt.com _;
    root /var/www/html;
    index index.html index.htm;

    location /clinical {
        proxy_pass http://127.0.0.1:18790;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 300s;
        proxy_http_version 1.1;
    }
    location /guideline {
        proxy_pass http://127.0.0.1:18790;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
    location /health {
        proxy_pass http://127.0.0.1:18790;
        proxy_set_header Host $host;
    }
    location / {
        try_files $uri $uri/ =404;
    }
}
```

## 写入方式

### ✅ 可靠（单行命令）
```bash
# 方案A: python3 -c 用单引号包裹（推荐）
python3 -c 'open("/etc/nginx/conf.d/hhysjt.conf","w").write("""server {\n    listen 80;\n    location /clinical {\n        proxy_pass http://127.0.0.1:18790;\n    }\n}""")'

# 方案B: 分段写入（Workbench 盲打场景最可靠）
echo 'location /clinical {' >> /etc/nginx/conf.d/hhysjt.conf
echo '    proxy_pass http://127.0.0.1:18790;' >> /etc/nginx/conf.d/hhysjt.conf
echo '}' >> /etc/nginx/conf.d/hhysjt.conf

# 方案C: 单独配置 include
cat > /etc/nginx/rag-proxy.conf << 'CFGEOF'
location /clinical {
    proxy_pass http://127.0.0.1:18790;
}
CFGEOF
```

### ❌ 可能有问题的写入方式
- `python3 -c "..."`（双引号）：`$host` 等被 shell 展开为空
- `type` 动作中的多行 heredoc：Workbench canvas 终端可能无法正确接收终止符
- `sed` 替换包含 `$` 的行：需要 `\$` 转义，容易出错

## 调试技巧

### 远程文件内容确认（盲打场景）
```bash
# 写入 nginx root 可访问路径的临时文件
grep -r "location" /etc/nginx/conf.d/ > /var/www/html/debug.txt
# 然后从本机 curl http://www.hhysjt.com/debug.txt
```

### 测试 frp 隧道连通性
```bash
# 在阿里云服务器上执行
curl -s http://127.0.0.1:18790/health
curl -s "http://127.0.0.1:18790/guideline/search?diagnosis=test"
```

### 后端响应 vs nginx 响应
- nginx 404：`Content-Type: text/html; charset=utf-8`，`Server: nginx/1.24.0`
- RAG 后端响应：包含 `Access-Control-Allow-Origin: *` 等 CORS 头，`Server: uvicorn`
- nginx 代理成功（但后端返回非200）：保留 `Server: nginx/1.24.0` + CORS 头 + 后端 Content-Type

### 从本机验证远程配置是否生效
```bash
# 检查响应头区分代理/未代理
curl -sI http://www.hhysjt.com/guideline/search?diagnosis=test
# 有 CORS + application/json = 代理生效
# nginx 404 页面 = 未代理（location 块不匹配或没写对文件）
```
