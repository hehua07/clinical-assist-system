---
name: remote-server-config
description: |-
  Configure remote servers (VPS, cloud instances) through the user's
  browser-based terminal (Aliyun Workbench, AWS Console, web SSH).
  Covers the pattern where you provide commands for the user to
  copy-paste because direct computer_use terminal interaction is
  blind (no output capture).
version: 1.1.0
platforms: [linux]
---

# Remote Server Configuration (browser-terminal pattern)

When you need to configure a remote server but the only access is
through a web-based terminal in the user's browser (e.g. Aliyun
Workbench, AWS EC2 Instance Connect, GCP SSH-in-browser, any xterm.js
/ hterm based terminal), **do NOT use `computer_use` `type` to drive
the terminal**. You cannot see the output, which leads to blind
debugging and user frustration.

## The copy-paste workflow

1. **Show ONE command at a time.** Each message should contain one
   shell command the user can select and paste.

2. **Prefer simple one-line commands.** Avoid complex heredocs,
   multi-line sed, and long chains. If you need multi-line input:
   - Use single-quote `echo '...all content...' > file` for short files
   - **Prefer single-line echo over heredoc** — browser-based terminals
     (Aliyun Workbench, xterm.js) often fail to enter heredoc mode:
     the user hits Enter after `<< 'EOF'` and returns to the prompt
     instead of entering heredoc input mode
   - If using heredoc, warn the user it may not work and have a single-
     line fallback ready
   - Use Python one-liners: `python3 -c '...'` with single-quoted
     arguments

3. **Ask for output.** After each command, tell the user to paste the
   result back, e.g. "Run this and paste the output:".

4. **Recover from corrupted state by full rewrite, not patching.**
   When a config file gets mangled (duplicate content, truncated,
   wrong line count, `location` directive ended up outside `server{}`):
   - Ask `wc -l /path/to/file` to measure damage
   - Do NOT try to patch/sed broken state — always rewrite the entire
     file from scratch
   - First take a dated backup:
     `cp /etc/nginx/conf.d/hhysjt.conf /etc/nginx/conf.d/hhysjt.conf.bak.$(date +%Y%m%d)`
   - Write the whole config in a single `echo '...' > file` command
   - For nginx: check `nginx -T` for the full effective config

5. **Verify the file was actually written, not just that `nginx -t` passed.** 
   This is the single most important lesson. `nginx -t` reads from the on-disk
   file. If `echo` threw a syntax error, or the heredoc silently failed, the
   file on disk did not change — but `nginx -t` reports "syntax is ok" on the
   OLD content, giving a false sense of success. The steps:
   - After writing, check content: `grep -c "listen 443" /etc/nginx/conf.d/hhysjt.conf`
   - Check the service is actually listening: `ss -tlnp | grep 443`
   - Test from your own machine: `curl -sI https://example.com/path`
   - If `grep` returns 0 or `ss` shows no listener, the write failed — switch
     to a different writing method (single-line echo → python3 heredoc → file
     on a temp path)

6. **Write priority order on browser terminals** (most→least reliable):
   - **`python3 -c "..."` (best for complex multi-line content)** — the most
     reliable method for writing files. Uses Python's triple-quoted strings
     inside `-c`, completely avoids shell heredoc/expansion issues. Content
     in `'''...'''` or `"""..."""`. Example:
     ```bash
     python3 -c "
     content = '''server { listen 80; ... }'''
     with open('/etc/nginx/conf.d/hhysjt.conf', 'w') as f:
         f.write(content)
     print('Written', len(content), 'bytes')
     "
     ```
     If the content itself contains triple quotes, use raw string `r'''...'''`.
   - **`python3 << 'HEREDOC_END'`** — also reliable. Triple-quote string,
     avoids shell interpolation. BUT: triple quotes inside can cause issues.
   - **`echo '...all content...' > /path`** — single quote prevents $ expansion
     but can hit `syntax error near unexpected token` on very long strings
     (strings > ~2000 chars with special chars). If echo fails, file is empty
     — not partially written.
   - **`cat > /path << 'EOF' ... EOF`** — least reliable on browser terminals.
     User presses Enter after `<< 'EOF'` and returns to prompt instead of
     entering heredoc mode.

7. **Limit how many times you try the same approach before switching.** 
   Rule: if a write command runs without visible error but file content didn't
   change after 2 attempts, switch to a completely different write method.
   Don't keep trying variations of the same approach.

8. **For nginx specifically, collect the diagnostic checklist before rewriting:**
   ```bash
   # Collect all 4 in one message
   ss -tlnp | grep -E '443|80'
   cat /etc/nginx/conf.d/hhysjt.conf
   nginx -T 2>&1 | grep -A30 "server_name www.hhysjt.com"
   grep -n 'listen\|ssl_certificate' /etc/nginx/conf.d/hhysjt.conf
   ```
   This avoids blind groping — you see exactly what's missing before proposing
   a fix. Common findings:
   - `ss` shows `*:80` but no `*:443` → missing `listen 443 ssl;`
   - `nginx -T` shows location blocks outside `server {}` → file was mangled
   - `cat` shows 19+ lines (single long line) → file is in compressed form
   - `grep listen` returns nothing for 443 → `listen 443 ssl http2;` is absent

## Common pitfalls

- **"location" directive is not allowed here**: nginx location blocks
  must be INSIDE a `server { }` block. If they ended up outside (after
  the closing `}`), the config is invalid. Fix by inserting before the
  `}` with `sed -i '$i\\    location ...' file`.
- **sed `\\n` does not insert newlines** in some sed versions. Use
  literal newlines or `$i\\` (insert before last line).
- **`$host` and other nginx variables get expanded** by the shell in
  double-quoted strings. Always use single quotes around nginx config
  snippets containing `$host`, `$remote_addr`, `$proxy_add_x_forwarded_for`,
  `$uri`, `$scheme`, etc.
- **certbot managed files** often live in `/etc/nginx/conf.d/` on
  CentOS/RHEL, not `/etc/nginx/sites-enabled/`. Check both.
- **`apt: command not found`** means CentOS/RHEL — use `yum` instead.
- **heredoc (`cat > file << 'EOF'`) may fail in browser-based web
  terminals** (Aliyun Workbench, xterm.js clones). The user hits Enter
  after the heredoc opener and is returned to the shell prompt instead
  of entering heredoc input mode. **Workaround**: use a single `echo`
  command with single quotes to write the entire file on one line:
  `echo '...all content...' > /path/to/file`. This avoids heredoc mode
  entirely.
- **Recovery from corrupted config**: when sed/patch breaks a file
  (e.g. location block ended up outside server{}), DO NOT try to patch
  it again. Ask `wc -l /path` to measure the damage, then rewrite the
  entire file with a single echo command. Include `cp ...bak` first so
  you can revert if the echo also fails.
- **HTTPS can break independently of HTTP** when config corruption
  affects the server block boundaries. Always test both:
  `curl -sI https://example.com/` AND `curl -sI http://example.com/`

## Testing after each change

After writing a config change, ask the user to run:

```bash
nginx -t && nginx -s reload
```

Then test endpoints from your own machine:

```bash
curl -sI http://example.com/path
curl -sI https://example.com/path
```

## The rule of thumb

If you find yourself typing more than 3 commands into a blind terminal,
stop and ask the user to paste commands instead. Blind terminal typing
scales with O(n²) frustration — the more you type, the harder it gets
to recover.

## Linked references

This skill has a `references/` directory with session-specific detail:
- `references/nginx-frp-rag-proxy.md` — concrete nginx + frp + RAG
  service proxy configuration from the hhysjt.com deployment
