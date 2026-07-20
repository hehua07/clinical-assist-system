# 阿里云 Workbench 盲终端调试

当通过 `computer_use` 向阿里云 Workbench 终端（Web SSH）打字时，**完全看不到输出**。xterm.js 的 canvas 在 AX 树中不暴露文本内容。

## 基本原则

1. **不要试图「看」输出** — 无论怎么 capture，terminal 输出都不会出现在 AX 树或截图中
2. **用外部验证代替看输出** — 从本机 curl 目标服务来确认命令是否生效
3. **优先用本地 curl 验证**而非反复执行命令试图查看效果

## Workflow

```
通过 type 在远程执行命令 → 从本机 curl 受影响服务确认效果
```

### 替代验证方法

| 方法 | 适用场景 | 命令示例 |
|:--|:--|:--|
| 从本机 curl 服务 | 修改 nginx 配置后 | `curl -s http://www.hhysjt.com/endpoint` |
| 写文件到 web root 再 fetch | 需要查看远程文件内容 | `echo data > /var/www/hhysjt/out.txt` 然后 `curl http://www.hhysjt.com/out.txt` |
| 让用户贴出结果 | 最后一次验证 | 让用户执行 `cat /etc/nginx/conf.d/hhysjt.conf` 贴出输出 |

### 致命陷阱

1. **heredoc `<< 'EOF'` 通过 type 发送不可靠** — terminator 字符可能丢失，shell 卡住等待。用 Python `-c` 或一条命令替代
2. **多行 sed 中的 `$variable`** — `$host`、`$remote_addr` 等 nginx 变量在 shell 中可能被展开为空字符串（不在单引号内时）。始终用单引号或 `\$` 转义
3. **`&&` 链中第一个命令失败则后面不执行** — 分开执行并分别验证
4. **`cat > file << 'EOF'` 写入大段内容时风险最高** — 优先用 `python3 -c` 写文件
5. **`nginx -t` 成功后 `nginx -s reload` 可能静默失败** — 实际配置未更新。用 `curl -sI http://www.hhysjt.com/endpoint` 验证

## OS 类型检测（第一步）

```bash
# 在远程终端执行
cat /etc/os-release | head -3
```

- **Ubuntu/Debian**: nginx 配置在 `/etc/nginx/sites-enabled/`
- **CentOS/AlmaLinux**: nginx 配置在 `/etc/nginx/conf.d/`
- **确认 include 路径**: `grep include /etc/nginx/nginx.conf`
- **dump 全部生效配置**: `nginx -T 2>&1 | grep -E "server_name|location /"`

## 可靠的单行命令示例

### 追加内容到 nginx 配置文件
```bash
echo '    # 指南共识查询
    location /guideline {
        proxy_pass http://127.0.0.1:18790;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 300s;
    }' >> /etc/nginx/conf.d/hhysjt.conf
```

### 用 Python 写文件（最可靠）
```bash
python3 -c 'open("/etc/nginx/conf.d/hhysjt.conf","w").write("...")'
```

### sed 在最后一行前插入
```bash
# 注意：sed 不支持 \n，需用实际换行或用其他工具
sed -i '$i\line1\nline2' file  # \n 在 GNU sed 中不一定工作
```

优先用 `echo >>` 追加或 `python3 -c` 写文件，避免 sed heredoc。
