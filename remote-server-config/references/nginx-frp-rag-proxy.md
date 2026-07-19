# nginx + frp RAG proxy setup (reference)

This is a concrete example from a real session configuring the web
front-end for a clinical RAG service.

## Architecture

```
[User Browser] → nginx (Aliyun, 47.102.41.191:80/443)
    ↓ (reverse proxy per-path)
    frp server (Aliyun, same host as nginx)
    ↓ (frp TCP tunnel, port 18790)
frp client (DGX Spark, local machine)
    ↓ (localhost:18790)
RAG Service (uvicorn, FastAPI)
```

## Key config file locations

- **Aliyun server**: `/etc/nginx/conf.d/hhysjt.conf`
  (NOT `/etc/nginx/sites-enabled/default` — that's Ubuntu convention)
- **Local machine frpc**: `/etc/frp/frpc.toml`
- **Local machine RAG service**: `/home/hehua/rag-service.bak/rag_service.py`
- **RAG Chrome DB**: `/home/hehua/rag-service.bak/chroma_data`
- **Systemd user service**: `~/.config/systemd/user/rag-service.service`

## nginx proxy location block (insert inside server {})

```nginx
location /guideline {
    proxy_pass http://127.0.0.1:18790;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_read_timeout 300s;
}
```

⚠️ Always use single quotes or quoted heredoc when writing this block
to prevent shell expansion of `$host` and friends.

## frp tunnel (added to frpc.toml)

```toml
[[proxies]]
name = "dgx-spark-rag"
type = "tcp"
localIP = "127.0.0.1"
localPort = 18790
remotePort = 18790
```

## certbot renewal

On CentOS/RHEL, use `yum` not `apt`:

```bash
# Already installed certs:
certbot install --cert-name www.hhysjt.com

# Check cert status:
certbot certificates
```

## Troubleshooting checklist

1. Is frpc connected? → `journalctl -u frpc.service --since "5 min ago"`
2. Is RAG service running? → `systemctl --user status rag-service.service`
3. Is nginx config valid? → `nginx -t`
4. Direct test from remote server: `curl -s http://127.0.0.1:18790/health`
5. Public test through proxy: `curl -s http://www.example.com/health`
