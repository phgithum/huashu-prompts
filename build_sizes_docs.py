# -*- coding: utf-8 -*-
"""把 sizes_ocr.jsonl 生成尺码知识文档（含身高体重推荐指南），并入 kb_docs"""
import io, os, json, re, sys, collections
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'kb_docs')
os.makedirs(OUT, exist_ok=True)   # 独立运行时不依赖 build_kb_docs.py 先建目录

recs = {}
SZ_SRC = os.path.join(HERE, 'sizes_ocr.jsonl')
if not os.path.exists(SZ_SRC):
    # 缺输入时优雅退出，避免把同一个 run 块后面的 upload_kb.py 一起带崩
    print('sizes_ocr.jsonl 不存在，跳过尺码文档生成（不影响商品文档同步）')
    sys.exit(0)
for line in open(SZ_SRC, encoding='utf-8'):
    try:
        r = json.loads(line)
        if not r.get('sku'):
            continue
        recs[r['sku']] = r  # 同 sku 后写覆盖
    except Exception:
        pass
print('records:', len(recs))

def cat_key(cat):
    parts = (cat or '未分类').split('/')
    return '/'.join(parts[:2]) if len(parts) >= 2 else (parts[0] if parts else '未分类')

groups = collections.defaultdict(list)
for r in recs.values():
    groups[cat_key(r.get('category'))].append(r)

files = []
for cat, items in sorted(groups.items()):
    safe = re.sub(r'[\\/:*?"<>|]', '_', cat)
    lines = [f'# MUJI 服装尺码知识 —— {cat}', '',
             '内容：尺码对照表（各码实测尺寸cm）、尺码推荐（身高号型映射）、模特实穿参考、版型。'
             '用于回答顾客"我身高XX体重XX穿什么码"。整理话术时以对照表数值和号型映射为准。', '']
    for r in sorted(items, key=lambda x: x.get('title') or ''):
        has = False
        lines.append(f"## {r.get('title')}")
        lines.append(f"- 价格：¥{r.get('price')}　SKU：{r.get('sku')}")
        if r.get('size_table'):
            lines.append(f"- 尺码对照表：{r['size_table']}")
            has = True
        if r.get('size_rec'):
            lines.append(f"- 尺码推荐（号型映射）：{r['size_rec']}")
            has = True
        if r.get('model'):
            lines.append(f"- 模特参考：{r['model']}")
            has = True
        if r.get('fit'):
            lines.append(f"- 版型：{r['fit']}")
            has = True
        if not has:
            lines.append('- （该商品详情图未提供尺码数据，按品类通用尺码回答）')
        lines.append('')
    fp = os.path.join(OUT, f'尺码_{safe}.md')
    open(fp, 'w', encoding='utf-8').write('\n'.join(lines))
    files.append(fp)

# 通用身高体重推荐指南
lines = [
    '# MUJI 服装尺码推荐指南（身高体重 → 码数）', '',
    '本指南来自 MUJI 中国官网各商品详情图的尺码推荐（号型制 GB：如 155/80A 表示适合身高155cm左右、胸围80cm左右）。',
    '推荐逻辑：先看具体商品文档里的号型映射和尺码对照表；没有时按本通用表，并结合版型（修身/宽松）提示。', '',
    '## 一、号型速查（官网尺码推荐图规则）',
    '- 男装常见号型：S=160/76A・170/80A，M=170/84A，L=175/88A，XL=180/92A，XXL=185/96A（依品类略有差异，以商品文档为准）',
    '- 女装常见号型：S=155/80A，M=160/84A，L=165/88A，XL=165/92A・170/92A（依品类略有差异，以商品文档为准）',
    '- 牛仔裤以腰围英寸标码（22~32inch）， socks/童装以脚长cm/身高cm标码',
    '', '## 二、按身高体重快速推荐（标准体型经验表，最终以商品号型为准）',
    '- 女装：150~158cm/40~48kg→S；158~165cm/45~55kg→M；163~170cm/52~62kg→L；168cm以上/60kg以上→XL',
    '- 男装：160~168cm/50~60kg→S；168~175cm/58~70kg→M；173~180cm/68~80kg→L；178cm以上/78~90kg→XL；185cm/90kg以上→XXL',
    '- 介于两码之间：想要修身效果选小一码，想要宽松效果选大一码；毛衣针织类通常建议按身高选，卫衣外套可大一码叠穿',
    '- 体重明显偏离标准（如健壮体型）时优先参考体重对应的码，再核对胸围/腰围对照表', '',
    '## 三、话术要点',
    '- 回答时先给结论码数，再说明依据（号型或对照表数值），并提示"标准体型参考，喜欢宽松可大一码"',
    '- 有模特实穿数据的商品（如模特168cm穿M）直接引用，更有说服力',
    '- 童装按身高选码最准（110~150cm），袜类按脚长cm',
]
fp = os.path.join(OUT, '_尺码推荐指南.md')
open(fp, 'w', encoding='utf-8').write('\n'.join(lines))
files.append(fp)

total = sum(os.path.getsize(f) for f in files)
print(f'generated {len(files)} docs, total {total} bytes ({total/1048576:.2f} MB)')
