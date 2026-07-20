#!/usr/bin/env python3
"""Clinical assist system health check and quick test.
Run: /usr/bin/python3 /home/hehua/.hermes/skills/clinical-assist-system/scripts/health_check.py
"""
import urllib.request, json, sys, time

def check(name, fn):
    try:
        t0 = time.time()
        fn()
        print(f"  ✅ {name} ({(time.time()-t0):.1f}s)")
        return True
    except Exception as e:
        print(f"  ❌ {name}: {e}")
        return False

print("═" * 40)
print("  临床AI辅助系统 - 健康检查")
print("═" * 40)

# 1. RAG health
print("\n1. RAG 服务")
check("health endpoint", lambda: print(end=""), )
req = urllib.request.Request('http://127.0.0.1:18790/health')
h = json.loads(urllib.request.urlopen(req, timeout=5).read())
print(f"   status={h['status']} oracle={h['oracle']} dip_rules={h['dip_rules']}")

# 2. vLLM
print("\n2. vLLM")
req = urllib.request.Request('http://127.0.0.1:8200/v1/models')
m = json.loads(urllib.request.urlopen(req, timeout=5).read())
model = m['data'][0]
print(f"   model={model['id'].split('/')[-1]} max_len={model['max_model_len']}")

# 3. Ollama
print("\n3. Ollama")
req = urllib.request.Request('http://127.0.0.1:11434/api/version')
v = json.loads(urllib.request.urlopen(req, timeout=5).read())
print(f"   version={v['version']}")

# 4. Quick analysis test (optional, slow)
print("\n4. 快速分析测试 (约100s)...")
req = urllib.request.Request('http://127.0.0.1:18790/clinical/assist',
    data=json.dumps({'patient_name': '蔡维良'}).encode(),
    headers={'Content-Type': 'application/json'})
t0 = time.time()
r = json.loads(urllib.request.urlopen(req, timeout=300).read())
elapsed = time.time() - t0
a = r.get('analysis', {})
if isinstance(a, dict) and 'primary_diagnosis' in a:
    pd = a['primary_diagnosis']
    print(f"   ✅ {(elapsed):.0f}s 诊断={pd.get('main','?')}")
    print(f"   dip_ops={len(r.get('dip_operations',[]))}条 settle_ops={len(r.get('settlement_operations',[]))}条")
else:
    err = a.get('error', 'unknown')
    print(f"   ❌ {err[:80]}")
    sys.exit(1)

print("\n═" * 40)
print("  全部通过 ✅")
print("═" * 40)
