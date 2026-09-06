# -*- coding: utf-8 -*-
"""把 muji_products.json 整理成适合知识库检索的 markdown 文档（按分类切分 + 材质专题）"""
import io, json, os, re, sys, collections
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'kb_docs')
os.makedirs(OUT, exist_ok=True)

products = json.load(open(os.path.join(HERE, 'muji_products.json'), encoding='utf-8'))

# ---------- 1. 按分类（前两级）切分 ----------
def cat_key(cat):
    parts = (cat or '未分类').split('/')
    return '/'.join(parts[:2]) if len(parts) >= 2 else (parts[0] if parts else '未分类')

# 标题关键词 -> 分类（补 60 条缺 category 的商品，多为宠物/园艺用品）
TITLE_CAT = [
    (r'宠物|猫|犬|狗|控砂|猫砂|铃铛玩具|除毛器|浴巾|香波', '生活杂货/宠物用品·园艺用品'),
    (r'园艺|花盆|种植|浇水', '生活杂货/宠物用品·园艺用品'),
]
def infer_cat(p):
    cat = p.get('category') or ''
    if cat:
        return cat
    t = p.get('title', '')
    for pat, c in TITLE_CAT:
        if re.search(pat, t):
            return c
    return '未分类'

groups = collections.defaultdict(list)
for p in products:
    groups[cat_key(infer_cat(p))].append(p)

files = []
for cat, items in sorted(groups.items()):
    safe = re.sub(r'[\\/:*?"<>|]', '_', cat)
    lines = [f'# MUJI 无印良品商品知识 —— {cat}', '',
             f'共 {len(items)} 个商品。字段：价格为人民币元，SKU 为 13 位商品条码，材质说明来自官网。', '']
    for p in sorted(items, key=lambda x: x.get('price') or 0):
        lines.append(f"## {p.get('title','（无标题）')}")
        lines.append(f"- 价格：¥{p.get('price','')}")
        lines.append(f"- SKU/条码：{p.get('sku','')}")
        if p.get('category'):
            lines.append(f"- 分类：{p['category']}")
        desc = (p.get('description') or '').strip()
        if desc:
            lines.append(f"- 材质与说明：{desc}")
        lines.append(f"- 官网页：{p.get('url','')}")
        lines.append('')
    fp = os.path.join(OUT, f'{safe}.md')
    open(fp, 'w', encoding='utf-8').write('\n'.join(lines))
    files.append(fp)

# ---------- 2. 材质/纱支专题（白名单统计，避免句子碎片噪音） ----------
MATERIALS = [
    '有机棉', '新疆棉', '长绒棉', '精梳棉', '天竺棉', '棉麻', '亚麻', '苎麻', '汉麻',
    '绵羊毛', '美利奴羊毛', '山羊绒', '羊毛', '马海毛', '羊驼毛',
    '蚕丝', '真丝', '桑蚕丝', '莱赛尔', '天丝', '莫代尔', '粘胶', '铜氨',
    '聚酯纤维', '涤纶', '再生尼龙', '聚酰胺', '尼龙', '氨纶', '聚氨酯', '腈纶',
    '聚丙烯', 'ABS树脂', 'AS树脂', '聚碳酸酯', '聚乙烯', 'MDF', '硅橡胶',
    '不锈钢', '铝合金', '竹', '陶瓷', '天然木', '白蜡木', '橡木', '榉木', '纸',
]
def count_term(term):
    n = 0
    for p in products:
        d = p.get('description') or ''
        if term in d or term in (p.get('title') or ''):
            n += 1
    return n

counts = sorted(((m, count_term(m)) for m in MATERIALS), key=lambda x: -x[1])
gabardine = sum(1 for p in products if '水洗' in (p.get('description') or ''))
yarn_terms = ['水洗', '抗菌', '防臭', '防羽', '天竺', '丝光', '磨毛', '起毛', '无氯漂白', '有机', '精梳']
yarn = sorted(((t, count_term(t)) for t in yarn_terms), key=lambda x: -x[1])

total = len(products)
lines = [
 '# MUJI 无印良品 材质与营销知识专题', '',
 f'数据来源：MUJI 中国官网商品库（{total} 条商品，抓取自 muji.com.cn）。本文档供 AI 销售话术参考。', '',
 '## 一、品牌卖点（营销通用）',
 '- 无印良品理念："这样就好"的克制美学，去多余装饰、重功能与材质本身。',
 '- 基础色系为主（米白/灰/藏青/卡其），易于搭配，适合极简、日系生活方式客群。',
 '- 强调材质溯源与工艺：有机棉、无氯漂白、精梳工艺、纱支密度是核心卖点。',
 '- 价格带透明，定位"高品质的基本款"，不打折话术可围绕"耐用·百搭·质感"展开。', '',
 '## 二、高频材质成分（官网商品描述统计，括号内为出现商品数）',
]
for k, v in counts:
    if v:
        lines.append(f'- {k}：{v} 个商品')
lines += ['', '## 三、工艺/纱支关键词（出现商品数）']
for k, v in yarn:
    if v:
        lines.append(f'- {k}：{v} 个商品')
lines += [
 '', '## 四、材质话术参考',
 '- 40支及以上精梳棉：纱线更细、织得更密，手感细腻不易起球，适合贴身穿着——推荐给追求手感的顾客。',
 '- 有机棉：种植不使用化学农药，通过有机认证，适合敏感肌、婴幼儿与环保偏好的顾客。',
 '- 莱赛尔（Lyocell）：木浆来源的再生纤维素纤维，吸湿透气、垂坠顺滑，夏装与床品常用。',
 '- 亚麻/棉麻：透气散热快、越洗越软，适合夏季；提醒顾客天然褶皱是质感的一部分。',
 '- 无氯漂白：漂白过程不使用含氯试剂，更环保低刺激，婴幼儿产品重点讲。',
 '- 抗菌防臭：汗季通勤、贴身内衣袜子类的主要卖点。',
 '- 水洗工艺：预先水洗缩率稳定，上身即合身、不易缩水。',
 '', '## 五、回答顾客的注意事项',
 '- 具体成分比例以商品页"材质与说明"为准，各分类商品文档中有逐条记录。',
 '- 报价用人民币原价，促销以官网为准；SKU 条码可用于对货。',
]
fp = os.path.join(OUT, '_材质与营销专题.md')
open(fp, 'w', encoding='utf-8').write('\n'.join(lines))
files.append(fp)

print(f'generated {len(files)} docs in {OUT}')
for f in files[:5]:
    print(' -', os.path.basename(f), os.path.getsize(f))
print('total size:', sum(os.path.getsize(f) for f in files))
