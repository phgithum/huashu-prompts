# -*- coding: utf-8 -*-
"""上传 kb_docs 下的文档到智谱知识库（CI 用：key 从环境变量读，重名文档先删后传）"""
import io, os, sys, json, time, uuid, requests
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

API_KEY = os.environ.get('ZHIPU_API_KEY', '')
KB_ID = '2096197757286182912'
H = {'Authorization': f'Bearer {API_KEY}'}
HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, 'kb_docs')

if not API_KEY:
    print('ZHIPU_API_KEY 未设置，跳过知识库同步')
    sys.exit(0)

def list_docs():
    r = requests.get('https://open.bigmodel.cn/api/llm-application/open/document', headers=H,
                     params={'knowledge_id': KB_ID, 'page': 1, 'size': 100}, timeout=30)
    return (r.json().get('data') or {}).get('list') or []

existing = {x.get('name'): x['id'] for x in list_docs()}
files = sorted(f for f in os.listdir(DOCS) if f.endswith('.md'))
print(f'待同步 {len(files)} 个文档，知识库现有 {len(existing)} 个')

# 删除同名旧文档（避免重复堆积）
for fn in files:
    if fn in existing:
        d = requests.delete(f"https://open.bigmodel.cn/api/llm-application/open/document/{existing[fn]}", headers=H, timeout=30)
        print('del', fn, d.status_code)
        time.sleep(0.6)

ok, fail = [], []
for i in range(0, len(files), 4):
    batch = files[i:i+4]
    payload = [('files', (fn, open(os.path.join(DOCS, fn), 'rb'), 'text/markdown')) for fn in batch]
    r = requests.post(f'https://open.bigmodel.cn/api/llm-application/open/document/upload_document/{KB_ID}',
                      headers=H, files=payload,
                      data={'knowledge_type': '1', 'parse_image': 'false', 'req_id': uuid.uuid4().hex}, timeout=120)
    try:
        j = r.json()
        ok += [s.get('fileName') for s in (j.get('data') or {}).get('successInfos', []) or []]
        fail += [(s.get('fileName'), s.get('failReason')) for s in (j.get('data') or {}).get('failedInfos', []) or []]
    except Exception:
        fail.append((batch, r.text[:150]))
    print(f'batch {i//4+1}: {r.status_code}')
    time.sleep(2)

print(f'uploaded ok={len(ok)} fail={len(fail)}')
for f in fail:
    print('FAIL:', f)
