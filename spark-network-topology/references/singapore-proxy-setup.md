# 新加坡 tinyproxy 出海代理配置

## 配置文件查找

如果 `/etc/tinyproxy/tinyproxy.conf` 不存在：

```bash
# 方法1：查找文件
find / -name 'tinyproxy*' -type f 2>/dev/null

# 方法2：看进程启动参数
ps aux | grep tinyproxy
cat /proc/$(pgrep tinyproxy)/cmdline | tr '\0' ' '

# 方法3：可能路径
ls /etc/tinyproxy/
ls /usr/local/etc/tinyproxy/
```

## 添加 IP 白名单

Spark 公网 IP：`112.28.117.8`

在 tinyproxy 配置文件中找到 `Allow` 区域，添加：

```
Allow 112.28.117.8
```

如果没有任何 Allow 行（tinyproxy 默认拒绝所有），至少需要加一条：

```
Allow 127.0.0.1
Allow 47.102.41.191
Allow 112.28.117.8
```

## 重启生效

```bash
systemctl restart tinyproxy
# 或
service tinyproxy restart
```

## 验证（从 Spark 执行）

```bash
# HTTP 测试
curl -s -x http://47.236.149.135:8888 http://httpbin.org/ip

# HTTPS CONNECT 测试（Git 用这个）
curl -s -w "%{http_code}" -x http://47.236.149.135:8888 https://github.com -o /dev/null

# 配置 Git 使用代理
git config --global http.proxy http://47.236.149.135:8888
git config --global https.proxy http://47.236.149.135:8888

# 测试推送
git ls-remote git@github.com:hehua07/llm.git
```

## 故障：403 Access denied

如果 `curl -v -x ...` 显示：
```
< HTTP/1.0 403 Access denied
< Server: tinyproxy/1.11.2
```

说明 IP 白名单未生效，检查：
1. 配置文件中 Allow 行是否在 `Allow` section 内（不在注释段）
2. 是否执行了 `systemctl restart tinyproxy`
3. `tail -f /var/log/tinyproxy/tinyproxy.log` 查看被拒绝的源 IP
