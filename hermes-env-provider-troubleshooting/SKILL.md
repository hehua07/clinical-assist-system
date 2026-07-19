---
name: hermes-env-provider-troubleshooting
description: >-
  Diagnose and fix Hermes .env format issues, provider routing mismatches
  (kimi-coding vs kimi-coding-cn, DeepSeek China endpoints), and gateway
  crash-loop debugging for Chinese-environment Hermes deployments.
version: 1.2.0
platforms: [linux]
---

# Hermes .env & Provider Troubleshooting (China Deployment)

Diagnose two common failure modes for users in China running Hermes behind
the GFW: (1) `.env` files with invalid multi-variable-per-line formatting
that silently drops env vars, and (2) provider routing mismatches where
an API key works but the wrong provider base URL is selected.

---

## 1. .env Format: Multi-Variable Per Line (Silent Drop)

### The Pitfall

**Hermes loads `.env` with Python's `python-dotenv`, which reads ONE
`KEY=VALUE` pair per line.** Multiple pairs separated by spaces on the
same line are silently ignored beyond the first `=` on that line.

Bad (will NOT work):
```
ZAI_API_KEY=abc123 WEIXIN_ACCOUNT_ID=myid@im.bot
```

Good (each variable on its own line):
```
ZAI_API_KEY=abc123
WEIXIN_ACCOUNT_ID=myid@im.bot
```

### Detection

Gateway crash-loop with `status=78/CONFIG` and `WEIXIN_ACCOUNT_ID is required`
despite the variable being present in `.env`.

```bash
# Check for multi-variable lines
grep -n ' .*=' ~/.hermes/.env | grep -v '^#' | grep -v '^\s*#'

# Also check with nl -ba
nl -ba ~/.hermes/.env

# Count actual lines with K=V
grep -c '^[A-Z_][A-Z0-9_]*=' ~/.hermes/.env
```

### Fix

Split multi-variable lines with Python:
```python
import re
content = open('/home/hehua/.hermes/.env').read()
new_lines = []
for line in content.split('\n'):
    stripped = line.strip()
    if not stripped or stripped.startswith('#'):
        new_lines.append(line)
        continue
    # Split on space followed by UPPERCASE_VARNAME=
    parts = re.split(r'\s+(?=[A-Z_]+=)', stripped)
    if len(parts) > 1:
        for p in parts:
            new_lines.append(p)
    else:
        new_lines.append(line)
open('/home/hehua/.hermes/.env', 'w').write('\n'.join(new_lines))
```

---

## 2. Kimi Provider Routing: `kimi-coding` vs `kimi-coding-cn` → `kimi-for-coding`

### The Pitfall

In Hermes v0.18.x, all Kimi provider names (`kimi`, `kimi-coding`,
`kimi-coding-cn`, `moonshot`) are **aliased to a single overlay** called
`kimi-for-coding`. The overlay definition in `hermes_cli/providers.py`:

```python
"kimi-for-coding": HermesOverlay(
    transport="openai_chat",
    base_url_env_var="KIMI_BASE_URL",
),
```

**Crucially, no `base_url_override` is set.** Without `KIMI_BASE_URL` in
the environment, the base URL falls through to the default from models.dev,
which is `https://api.moonshot.ai/v1` (international endpoint). This means
even `kimi-coding-cn` as a config setting routes to the international .ai
endpoint, not the China .cn endpoint.

### The Fix: Set `KIMI_BASE_URL`

```bash
echo 'KIMI_BASE_URL=https://api.moonshot.cn/v1' >> ~/.hermes/.env
```

This env var is read directly by the `kimi-for-coding` overlay. Once set,
all Kimi providers (`kimi-coding`, `kimi-coding-cn`, `kimi`, `moonshot`) will
correctly route to the China domain. The credential layer reads `~/.hermes/.env`
directly (`_get_env_prefer_dotenv`), so no process restart is needed for the
new var to be seen.

**No need to change `model.provider` or `model.default`.** The fix is purely
an environment variable — **plus the auth-reset step below, which is NOT
optional if a 401 already occurred.**

### Stale 401 After the Base-URL Fix: Credential Pool Exhaustion Marker

Observed 2026-07-19: `KIMI_BASE_URL` was correctly set to the `.cn` endpoint,
yet every request still returned `HTTP 401: Invalid Authentication`.

Root cause: the earlier 401s (from hitting the international endpoint) made
the credential pool mark the key as failed:

```
kimi-coding (1 credentials):
  #1  KIMI_API_KEY  api_key env:KIMI_API_KEY auth failed invalid_authentication_error (401) (re-auth may be required)
```

While that marker stands, the pool refuses/skips the credential — fixing the
base URL alone does NOT clear it. Check with `hermes auth list` (bare, or
with the full provider id like `hermes auth list kimi-coding`; note
`hermes auth list kimi` matches nothing).

**Fix (required sequence):**

```bash
hermes auth reset kimi-coding      # clear the stale 401 exhaustion marker
hermes auth reset kimi-coding-cn   # harmless if nothing to reset
hermes chat -q "简单回复ok" --provider kimi-coding --model kimi-k3   # verify
```

Related panel pitfall: in `hermes model` / `/model`, both `kimi-coding` and
`kimi-coding-cn` render as a single **`kimi-for-coding`** row (models.dev id;
"first one with valid credentials wins"). Selecting it resolves via alias to
`kimi-coding` — with `KIMI_BASE_URL` set and the pool reset, that path works
too. Exhaustion markers can also show a countdown, e.g.
`exhausted invalid_request_error (402) (47m left)` for a balance-depleted
DeepSeek key — same `hermes auth reset <provider>` remedy once the underlying
issue (balance, endpoint) is fixed.

### Detection

```bash
# Check current provider
grep 'provider:' ~/.hermes/config.yaml
grep 'default:' ~/.hermes/config.yaml

# Check KIMI_BASE_URL status
grep KIMI_BASE_URL ~/.hermes/.env || echo "NOT SET — 401 likely"

# Check which Kimi keys are set and their auth status
hermes auth list | grep -i kimi

# Test the key directly against CN endpoint (deterministic, no Hermes routing)
python3 -c "
import urllib.request, json
for line in open('/home/hehua/.hermes/.env'):
    if line.startswith('KIMI_API_KEY='):
        key = line.split('=', 1)[1].strip()
        break
r = urllib.request.Request('https://api.moonshot.cn/v1/models',
    headers={'Authorization': f'Bearer {key}'})
resp = urllib.request.urlopen(r, timeout=10)
data = json.loads(resp.read())
print(f'Status: {resp.status}')
for m in data['data']:
    print(f'  - {m[\"id\"]}')
"
```

### Available Models (as of mid-2026)

Common Kimi models accessible from a standard China domestic account:
- `kimi-k3` — latest flagship (recommended)
- `kimi-k2.6` — previous gen
- `kimi-k2.7-code` — code-focused
- `kimi-k2.7-code-highspeed` — fast code mode
- `moonshot-v1-8k` / `moonshot-v1-32k` / `moonshot-v1-128k` — exist on the
  account but **this user has explicitly excluded the entire v1 series;
  never suggest or mention them** (user instruction 2026-07-19)

Older models like `kimi-k1.5` may return 401 if no longer available on your
account tier. Try an API listing first before assuming the key is wrong.

### User Preference: This Account's Model Choices

For the user at 寿县和华医院:
- **Preferred model:** `kimi-k3` (only model used)
- **Excluded models:** ALL `moonshot-v1-*` series — never suggest or mention them
- Use `kimi-k3` as the default when configuring Kimi for this account
- **Do NOT proactively switch `model.default` / `model.provider`** — the user
  picks the active model themselves (panel / `/model`). Offer the config
  commands, but only apply them when the user explicitly asks
  (user instruction 2026-07-19: "不要，我自己选")

### Key Insight: `kimi-coding-cn` works with BOTH env vars

Despite the docs saying `kimi-coding-cn` reads `KIMI_CN_API_KEY`, you can
actually set **either** `KIMI_API_KEY` or `KIMI_CN_API_KEY` in `.env` and
the `kimi-for-coding` overlay will find it. The key value is the same — the
env var name just controls which label appears in `hermes auth list`.

### `custom_providers` Caveat (v0.18.x)

You can define a custom Kimi provider in `config.yaml`:
```yaml
custom_providers: '[{\"name\":\"kimi-custom\",\"type\":\"openai\",\"base_url\":\"https://api.moonshot.cn/v1\"}]'
```

However, in Hermes v0.18.x, the `custom:` prefix is required to reference
it, and the CLI flag `--provider kimi-custom` (without prefix) fails with
`Unknown provider`. The correct config-level use is:
```bash
hermes config set model.provider custom:kimi-custom
```

If `hermes chat --provider custom:kimi-custom` also fails or custom providers
don't route correctly, fall back to the built-in `kimi-coding-cn` provider.

### Quick Fix: Switch to kimi-coding-cn

```bash
# Switch provider and default model
hermes config set model.provider kimi-coding-cn
hermes config set model.default kimi-k2.6
```

Then `/reset` in the current session to pick up the new provider.

### Verification After Switching

```bash
# Test the new provider works end-to-end
hermes chat -q "简单回复ok" --provider kimi-coding-cn --model kimi-k2.6
```

Expected: a successful response (not 401).

---

## 3. Gateway Crash Loop Diagnosis

### Pattern

Gateway exits immediately with `status=78/CONFIG`, restarts, fails again.
The journal shows which platform failed.

```bash
journalctl --user -u hermes-gateway.service -n 50 --no-pager
```

Common symptoms and their root causes:

| Error message | Root cause | Fix |
|--------------|------------|-----|
| `WEIXIN_ACCOUNT_ID is required` | .env has multi-var-per-line (see §1) | Split .env lines |
| `status=78/CONFIG` | Non-retryable startup failure | Check journal for specific error |
| `[Weixin] ... failed: ...` | Missing or misformatted env var | Check .env format |

After fixing .env or config:
```bash
systemctl --user reset-failed hermes-gateway.service
```

Then restart from an **external shell** (cannot restart gateway from inside
the gateway process):
```bash
hermes gateway restart
```

### Why You Cannot `restart` From Inside the Gateway

The gateway process catches SIGTERM. Running `systemctl --user stop` or
`hermes gateway restart` from inside a gateway-spawned process would
kill the caller before the command completes. Always use an external
terminal or tmux session.
