# -*- coding: utf-8 -*-
"""生成网页版数据文件：商品索引（含官网链接）+ 尺码数据"""
import io, os, json, re, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
HERE = os.path.dirname(os.path.abspath(__file__))
products = json.load(open(os.path.join(HERE, 'muji_products.json'), encoding='utf-8'))
sizes = {}
sz_path = os.path.join(HERE, 'sizes_ocr.jsonl')
if os.path.exists(sz_path):
    for line in open(sz_path, encoding='utf-8'):
        try:
            r = json.loads(line)
            sizes[r['sku']] = r
        except Exception:
            pass

prods = {}
for p in products:
    if not p.get('sku'):
        continue
    prods[p['sku']] = {
        't': (p.get('title') or '').strip(),
        'p': p.get('price'),
        'c': (p.get('category') or ''),
        'd': (p.get('description') or '')[:400],
        'i': (p.get('images') or [''])[0],
        'u': p.get('url') or '',
    }
sz = {}
for sku, r in sizes.items():
    if sku not in prods:
        continue
    v = {}
    for k, short in (('size_rec', 'r'), ('size_table', 'tb'), ('model', 'm'), ('fit', 'f')):
        if r.get(k):
            v[short] = r[k].replace(' | ', '；')
    if v:
        sz[sku] = v

payload = 'window.MUJI_DATA=' + json.dumps({'products': prods, 'sizes': sz}, ensure_ascii=False, separators=(',', ':')) + ';'
out = os.path.join(HERE, 'muji-chat', 'data.js')
open(out, 'w', encoding='utf-8').write(payload)
print('products:', len(prods), 'sizes:', len(sz), '| size:', round(os.path.getsize(out) / 1048576, 2), 'MB')
