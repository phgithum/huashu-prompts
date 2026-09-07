# -*- coding: utf-8 -*-
"""生成网页版数据文件：商品索引（含官网链接）+ 尺码数据"""
import io, os, json, re, sys, time
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

# 款号映射（来自赤兔知识标题"商品名——款号"）
chitu = {}
csz = None
for base in ['.', r'C:\Users\23395\Downloads', r'C:\Users\23395\Desktop']:
    try:
        if not os.path.isdir(base):
            continue
        for f in os.listdir(base):
            if f.startswith('chitu-knowledge') and f.endswith('.json'):
                p = os.path.join(base, f)
                if csz is None or os.path.getsize(p) > os.path.getsize(csz):
                    csz = p
    except Exception:
        pass
try:
    cd = json.load(open(csz, encoding='utf-8'))
    for det in cd.get('details', []):
        m = re.search(r'——\s*([A-Z0-9]{5,9})\s*$', det.get('title') or '')
        if m:
            chitu.setdefault(re.sub(r'——.*$', '', det['title']).strip(), m.group(1))
except Exception as e:
    print('chitu款号跳过:', e)

def _norm(t):
    return re.sub(r'[\s/（）()·＋+×\-—·]+', '', (t or '').lower())

sku_code = {}
for title, code in chitu.items():
    nt = _norm(title)
    for p in products:
        pt = _norm(p.get('title'))
        if nt and (nt in pt or pt in nt):
            sku_code[p['sku']] = code

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
    if sku_code.get(p['sku']):
        prods[p['sku']]['s'] = sku_code[p['sku']]
    # 尺码/颜色/产地/尺码表（v0.2 新增字段，旧页面会自动忽略）
    if p.get('sizes'):
        prods[p['sku']]['z'] = p['sizes']
    if p.get('sizeSpecs'):
        prods[p['sku']]['tb'] = p['sizeSpecs']
    if p.get('origin'):
        prods[p['sku']]['o'] = p['origin']
    if p.get('skus'):
        # 紧凑 SKU 表：[条码, 颜色, 尺码, 价格]
        prods[p['sku']]['v'] = [[s.get('skuCd', ''), s.get('colorName', ''), s.get('sizeName', ''), s.get('price')] for s in p['skus']]
print('款号映射:', len(sku_code))
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
# 自动给 index.html 的 data.js 引用换版本号，强制浏览器拉新数据
idx = os.path.join(HERE, 'muji-chat', 'index.html')
if os.path.exists(idx):
    html = open(idx, encoding='utf-8').read()
    html2 = re.sub(r'data\.js\?v=[0-9a-z]+', 'data.js?v=' + time.strftime('%Y%m%d%H%M'), html)
    if html2 != html:
        open(idx, 'w', encoding='utf-8').write(html2)
        print('index.html 版本号已更新')
print('products:', len(prods), 'sizes:', len(sz), '| size:', round(os.path.getsize(out) / 1048576, 2), 'MB')
