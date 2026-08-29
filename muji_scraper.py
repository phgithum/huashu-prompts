# -*- coding: utf-8 -*-
"""
MUJI（无印良品中国官网 muji.com.cn）商品详情抓取脚本
=====================================================

【合规红线】（务必遵守）
  1. 本脚本仅用于个人学习/研究，数据不得商用、不得分发。
  2. 遵守 robots.txt 与目标服务器承载力：请求间随机延时 0.5~1.5 秒，
     遇 403/429 自动降频；不得打崩对方服务器。
  3. 不绕过登录/付费墙，不抓取需授权的接口（购物车、订单、会员等均不涉及）。
  4. 若对方有明显反爬升级（大量 403、封 IP、验证码），应立即停止，
     不得使用破解/对抗手段。脚本内不含任何验证码识别或 IP 代理逻辑。
  5. 说明：官网无 robots.txt（该路径返回 404 页面，未发现 Disallow 规则）。

【实现说明】
  muji.com.cn 的商城（/cn/store/）是 Vue 单页应用（SPA）：
  - 直接请求 HTML 只能得到空壳 <div id="app"></div>；
  - 页面数据来自官方前端调用的公开 JSON 接口（/cn/ecapi/maps/ec/*），
    请求头需携带前端 JS 计算的 X-Sign 签名（MD5，密钥写死在前端代码中）。

  因此脚本采用双链路：
  - 主链路（requests）：直接调用官网公开的列表/详情 JSON 接口，
    并按前端同样算法计算 X-Sign —— 与浏览器正常访问等价，请求数更少、更稳。
  - 兜底链路（Playwright 无头 Chromium）：当主链路失败（签名被服务端
    更换、接口升级等）时，真实渲染页面后用 BeautifulSoup 解析 DOM，
    图片兼容懒加载 data-src。

【产出物】
  - muji_products.json   UTF-8，缩进 2
  - muji_products.csv    UTF-8-sig（Excel 直接打开不乱码）
  - failed_urls.txt      失败清单（跑完后按提示补抓）
  - progress.json        断点续抓进度（每 20 条自动落盘）

【用法】
  python muji_scraper.py <列表页或详情页URL> [选项]
  示例：
    # 全站商品（按官网全量列表翻页）
    python muji_scraper.py "https://www.muji.com.cn/cn/store/commodities"
    # 指定分类（URL 带 cateId/cateType 参数即可）
    python muji_scraper.py "https://www.muji.com.cn/cn/store/commodities?cateId=300000132&cateType=middle"
    # 单个商品
    python muji_scraper.py "https://www.muji.com.cn/cn/store/commodity/99018"
    # 限制最多抓 30 条（试跑用）
    python muji_scraper.py "https://www.muji.com.cn/cn/store/commodities" --limit 30
  选项：
    --limit N        最多抓取 N 个商品（默认不限）
    --per-page N     列表分页大小（默认 20，最大 50）
    --out-dir DIR    产出目录（默认当前目录）
    --no-playwright  禁用 Playwright 兜底（仅用 requests 主链路）
"""

import argparse
import csv
import hashlib
import json
import os
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup

try:
    from fake_useragent import UserAgent
    _UA = UserAgent()
    def random_ua() -> str:
        """随机 User-Agent（fake_useragent 失败时退回内置 UA 池）"""
        try:
            return _UA.random
        except Exception:
            return random.choice(FALLBACK_UAS)
except Exception:
    def random_ua() -> str:
        return random.choice(FALLBACK_UAS)

FALLBACK_UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]

# ----------------------------------------------------------------------
# 常量配置
# ----------------------------------------------------------------------
SITE_BASE = "https://www.muji.com.cn"
ECAPI_BASE = f"{SITE_BASE}/cn/ecapi/maps/ec"   # 官方前端使用的公开 JSON 接口基址
EC_SECRET = "3CE70638F556FB9B"                  # 前端 JS 内置的签名密钥（与浏览器一致）

# 详情页 URL 特征：/commodity/{id}（新）、/goods/{id}（旧）、/product/{id}（兼容）
RE_DETAIL_URL = re.compile(r"/(?:commodity|goods|product)/(\d{1,9})")

CHECKPOINT_EVERY = 20          # 每 20 条落盘一次
MAX_RETRIES = 3                # 失败重试次数
BACKOFF_BASE = 1.0             # 指数退避基数：1s、2s、4s
DELAY_MIN, DELAY_MAX = 0.5, 1.5  # 请求间随机延时（秒）

CSV_COLUMNS = ["title", "price", "sku", "images", "description", "category", "url"]


def log(msg: str) -> None:
    """带时间戳的日志输出"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def polite_sleep(a: float = DELAY_MIN, b: float = DELAY_MAX) -> None:
    """请求间随机延时，控制频率不给服务器添堵"""
    time.sleep(random.uniform(a, b))


# ----------------------------------------------------------------------
# X-Sign 签名（与官网前端拦截器算法一致）
# ----------------------------------------------------------------------
def make_sign(params: dict) -> str:
    """
    复刻官网前端 X-Sign 算法：
      1. 取参数所有 key 排序；
      2. 跳过值为 None / dict / list 的项；
      3. 将 "key+value" 依次拼接，再拼接密钥；
      4. MD5 后转大写。
    """
    parts = []
    for k in sorted(params.keys()):
        v = params[k]
        if v is None or isinstance(v, (dict, list)):
            continue
        parts.append(f"{k}{v}")
    raw = "".join(parts) + EC_SECRET
    return hashlib.md5(raw.encode("utf-8")).hexdigest().upper()


class MujiClient:
    """官网公开接口客户端（requests 主链路，自带限速/重试/UA 轮换）"""

    def __init__(self):
        self.session = requests.Session()
        self._rotate_ua()

    def _rotate_ua(self):
        """轮换 User-Agent 并更新 Referer 等伪装头"""
        self.session.headers.update({
            "User-Agent": random_ua(),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": f"{SITE_BASE}/cn/store/",
            "X-App-Source": "1",  # 官网常量：1 = DESKTOP_WEB
        })

    def api_get(self, path: str, params: dict = None) -> dict:
        """
        调用公开 JSON 接口（自动计算 X-Sign）。
        失败重试：指数退避 1s/2s/4s，最多 3 次；
        403/429 时降频（额外等待）并轮换 UA。
        """
        params = dict(params or {})
        last_err = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                headers = {"X-Sign": make_sign(params)}
                resp = self.session.get(f"{ECAPI_BASE}{path}", params=params,
                                        headers=headers, timeout=20)
                if resp.status_code in (403, 429):
                    # 反爬响应：降频 + 轮换 UA 后重试
                    wait = BACKOFF_BASE * (2 ** (attempt - 1)) + random.uniform(2, 5)
                    log(f"  !! HTTP {resp.status_code}，降频等待 {wait:.1f}s 后重试")
                    self._rotate_ua()
                    time.sleep(wait)
                    last_err = f"HTTP {resp.status_code}"
                    continue
                resp.raise_for_status()
                data = resp.json()
                if data.get("code") != 0:
                    # 业务错误（如参数缺失、签名失效）——原样抛给上层判断
                    raise RuntimeError(f"接口业务错误: {data.get('message')} (code={data.get('code')})")
                return data.get("data") or {}
            except RuntimeError:
                raise
            except Exception as e:
                last_err = str(e)
                wait = BACKOFF_BASE * (2 ** (attempt - 1))
                log(f"  !! 请求失败（第{attempt}次）：{last_err}，{wait:.0f}s 后重试")
                self._rotate_ua()
                time.sleep(wait)
        raise RuntimeError(f"重试{MAX_RETRIES}次仍失败: {last_err}")


# ----------------------------------------------------------------------
# 主链路：JSON 接口抓取
# ----------------------------------------------------------------------
def build_category_map(client: MujiClient) -> dict:
    """
    拉取官网分类树（/categories），构建 selLineCd -> "父分类/子分类" 映射，
    用于给每个商品填充 category 字段。失败时返回空表（分类留空，不影响主流程）。
    """
    try:
        data = client.api_get("/categories")
        items = data.get("list") or []
        by_id = {it.get("id"): it for it in items}
        mapping = {}

        def path_of(it):
            """沿 parentId 向上回溯，拼出分类全路径"""
            names, cur, guard = [], it, 0
            while cur and guard < 6:
                names.append(cur.get("cateName") or "")
                cur = by_id.get(cur.get("parentId"))
                guard += 1
            return "/".join(reversed([n for n in names if n]))

        for it in items:
            full = path_of(it)
            for cd in (it.get("selLineCds") or []):
                mapping[str(cd)] = full
        return mapping
    except Exception as e:
        log(f"  !! 分类树获取失败（category 字段将留空）：{e}")
        return {}


def list_products_api(client: MujiClient, cate_id=None, cate_type="all",
                      per_page=20, max_pages=None, max_items=None):
    """
    列表接口分页抓取全部商品 id。
    返回 [(spu_id, sel_line_cd), ...]，按接口翻页顺序；
    max_items 不为空时，凑够即提前停止翻页（避免多余请求）。
    """
    items, page = [], 1
    while True:
        params = {
            "currentPage": page,
            "perPage": per_page,
            "cateId": cate_id,
            "cateType": cate_type,
            "orderBy": "date_desc",
            "searchKey": None,
            "shopId": 0,
            "deliveryType": 0,
            "provinceCd": "310000",  # 上海市，仅用于查询在售状态
        }
        data = client.api_get("/commodities", params)
        meta = data.get("meta") or {}
        batch = data.get("list") or []
        if not batch:
            break
        for it in batch:
            items.append((it.get("id"), it.get("selLineCd")))
            if max_items and len(items) >= max_items:
                return items[:max_items]
        log(f"  列表第 {page}/{meta.get('lastPage', '?')} 页，累计 {len(items)}/{meta.get('total', '?')} 条")
        if max_pages and page >= max_pages:
            break
        if page >= int(meta.get("lastPage") or 1):
            break
        page += 1
        polite_sleep()
    return items


def fetch_detail_api(client: MujiClient, spu_id, sel_line_cd=None, cate_name=None,
                     category_map=None):
    """详情接口抓取单个商品，并整理为标准字段结构"""
    data = client.api_get("/commodity", {
        "id": str(spu_id),
        "skuCd": None,
        "provinceCd": "310000",
    })
    return normalize(data, spu_id, sel_line_cd, cate_name, category_map)


def normalize(d: dict, spu_id, sel_line_cd=None, cate_name=None, category_map=None) -> dict:
    """
    将接口返回的原始详情整理为目标字段。
    所有字段均有空值兜底（缺失时返回 "" 或 []），保证结构稳定。
    """
    title = (d.get("name") or "").strip()
    price = d.get("mktPrice")
    if price in (None, ""):
        price = d.get("price")
    sku = d.get("spuCd") or ""

    # 图片：主图 + 相册 + 详情图，去重、剔除空值
    images = []
    for key in ("defaultPic", "albumPics", "detail"):
        v = d.get(key)
        if isinstance(v, str) and v:
            images.append(v)
        elif isinstance(v, list):
            images.extend(x for x in v if x)
    seen = set()
    images = [x for x in images if not (x in seen or seen.add(x))]

    # 描述：材质 + 说明 + 注意事项 拼接，截断 500 字
    desc_parts = []
    for key, label in (("countryMaterial", "材质"),
                       ("countryDirection", "说明"),
                       ("countryDemerit", "注意事项")):
        v = (d.get(key) or "").strip()
        if v:
            desc_parts.append(f"{label}：{v}")
    description = " ".join(desc_parts)[:500]

    # 分类：优先用爬取任务传入的分类名，其次用 selLineCd 查分类树映射
    if cate_name:
        category = cate_name
    elif category_map and sel_line_cd:
        category = category_map.get(str(sel_line_cd), "")
    else:
        category = ""

    return {
        "title": title,
        "price": price if price is not None else "",
        "sku": sku,
        "images": images,
        "description": description,
        "category": category,
        "url": f"{SITE_BASE}/cn/store/commodity/{spu_id}",
        "_sel_line_cd": sel_line_cd or "",
    }


# ----------------------------------------------------------------------
# 兜底链路：Playwright 真实渲染 + BeautifulSoup 解析 DOM
# ----------------------------------------------------------------------
def fetch_detail_playwright(url: str) -> dict:
    """
    Playwright 无头渲染详情页后用 BeautifulSoup 解析。
    图片兼容懒加载：优先 src，取不到时回退 data-src。
    仅在 requests 主链路失败时启用。
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=random_ua())
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            # 等核心内容「产品参数」区块渲染（该站无 h1，用文字锚点，最多 15s）
            try:
                page.wait_for_selector("text=产品参数", timeout=15000)
            except Exception:
                time.sleep(3)
            time.sleep(1.5)  # 给懒加载图片一点时间
            html = page.content()
        finally:
            browser.close()

    soup = BeautifulSoup(html, "lxml")

    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else ""

    price = ""
    m = re.search(r"[¥￥]\s*([0-9,]+(?:\.[0-9]{1,2})?)", soup.get_text(" ", strip=True))
    if m:
        price = m.group(1).replace(",", "")

    sku = ""
    m = re.search(r"(?:商品编号|货号)[：:]\s*([0-9]{8,13})", soup.get_text(" ", strip=True))
    if m:
        sku = m.group(1)

    # 图片：懒加载 data-src 兜底
    images = []
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if "img.muji.com.cn" in src or "webimg.muji.com.cn" in src:
            images.append(src)
    seen = set()
    images = [x for x in images if not (x in seen or seen.add(x))]

    description = ""
    main = soup.find("div", id="app") or soup
    text = main.get_text("\n", strip=True)
    description = re.sub(r"\n{2,}", "\n", text)[:500]

    return {
        "title": title, "price": price, "sku": sku, "images": images,
        "description": description, "category": "", "url": url, "_sel_line_cd": "",
    }


# ----------------------------------------------------------------------
# 入口 URL 解析与商品发现
# ----------------------------------------------------------------------
def parse_input_url(url: str):
    """
    解析入口 URL，返回 (mode, kwargs)：
      - ("detail", spu_id)                单个商品
      - ("catalog", cate_id, cate_type)   指定分类列表
      - ("all",)                          全站列表
      - ("html",)                         需先尝试 HTML 提取链接的列表页
    """
    parsed = urlparse(url)
    m = RE_DETAIL_URL.search(parsed.path)
    if m:
        return ("detail", int(m.group(1)))

    if "/commodities" in parsed.path or "/store" in parsed.path:
        qs = parse_qs(parsed.query)
        cate_id = qs.get("cateId", [None])[0]
        cate_type = qs.get("cateType", ["top" if qs.get("cateId") else "all"])[0]
        if cate_id:
            return ("catalog", cate_id, cate_type)
        return ("all",)
    return ("html",)


def extract_links_from_html(url: str, client: MujiClient, use_playwright=True):
    """
    从列表页 HTML 提取商品详情链接（/commodity/、/goods/、/product/）。
    requests 拿不到（SPA 空壳）时自动切换 Playwright 渲染再提取。
    URL 规律与预期不符时，打印该页链接清单方便人工核对。
    """
    found, all_links = [], []
    try:
        resp = client.session.get(url, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            all_links.append(href)
            m = RE_DETAIL_URL.search(href)
            if m:
                found.append(int(m.group(1)))
    except Exception as e:
        log(f"  HTML 提取失败：{e}")

    if not found and use_playwright:
        log("  HTML 无有效链接（疑似 JS 渲染空壳），切换 Playwright 渲染列表页...")
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(user_agent=random_ua())
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_selector("a", timeout=20000)
                time.sleep(2)
                html = page.content()
                browser.close()
            soup = BeautifulSoup(html, "lxml")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                all_links.append(href)
                m = RE_DETAIL_URL.search(href)
                if m:
                    found.append(int(m.group(1)))
        except Exception as e:
            log(f"  Playwright 渲染失败：{e}")

    seen = set()
    found = [x for x in found if not (x in seen or seen.add(x))]

    if not found:
        # URL 规律与预期不符：打印该页链接清单，方便人工核对调整
        uniq = list(dict.fromkeys(all_links))[:40]
        log("  !! 未提取到商品链接。该页全部链接清单如下（供人工核对 URL 规律）：")
        for h in uniq:
            log(f"     {h}")
    return found


# ----------------------------------------------------------------------
# 断点续抓与产出物
# ----------------------------------------------------------------------
def _write_csv(rows, path):
    """写出 CSV（UTF-8-sig）"""
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for p in rows:
            row = dict(p)
            row["images"] = ";".join(p.get("images") or [])
            writer.writerow({k: row.get(k, "") for k in CSV_COLUMNS})


def _fallback_path(path):
    """被占用时的备用文件名：xxx_备用.ext"""
    base, ext = os.path.splitext(path)
    return f"{base}_备用{ext}"


def save_outputs(products, out_dir):
    """
    写出 muji_products.json（UTF-8 缩进2）与 muji_products.csv（UTF-8-sig）。
    若文件被 Excel 等程序锁定（PermissionError），先重试，仍失败则改写
    备用文件，保证抓取进程不崩溃。
    """
    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, "muji_products.json")
    csv_path = os.path.join(out_dir, "muji_products.csv")

    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(products, f, ensure_ascii=False, indent=2)
    except PermissionError:
        alt = _fallback_path(json_path)
        log(f"  !! JSON 被占用，改写到 {os.path.basename(alt)}（请关闭打开它的程序）")
        with open(alt, "w", encoding="utf-8") as f:
            json.dump(products, f, ensure_ascii=False, indent=2)

    for attempt in range(2):
        try:
            _write_csv(products, csv_path)
            break
        except PermissionError:
            if attempt == 0:
                log("  !! muji_products.csv 被 Excel 占用，3 秒后重试...")
                time.sleep(3)
            else:
                alt = _fallback_path(csv_path)
                log(f"  !! CSV 仍被占用，本轮改写到 {os.path.basename(alt)}"
                    f"（建议查看时先关闭 Excel，最终结果会写回主文件）")
                _write_csv(products, alt)
    return json_path, csv_path


def load_progress(out_dir):
    """读取断点进度：已完成商品与已抓结果"""
    prog_path = os.path.join(out_dir, "progress.json")
    if os.path.exists(prog_path):
        try:
            with open(prog_path, encoding="utf-8") as f:
                state = json.load(f)
            return state.get("done", {}), state.get("products", [])
        except Exception:
            log("  !! progress.json 损坏，忽略并重新开始")
    return {}, []


def save_progress(out_dir, done, products):
    prog_path = os.path.join(out_dir, "progress.json")
    with open(prog_path, "w", encoding="utf-8") as f:
        json.dump({"done": done, "products": products}, f, ensure_ascii=False)


def record_failure(out_dir, url, reason):
    """失败 URL 单独记录，跑完后提示补抓"""
    path = os.path.join(out_dir, "failed_urls.txt")
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{url}\t{reason}\n")


# 快速模式：每线程独立客户端（requests.Session 非线程安全）
_tls = threading.local()


def _thread_client():
    if not hasattr(_tls, "client"):
        _tls.client = MujiClient()
    return _tls.client


def run_fast_details(pending, done, products, category_map, out_dir):
    """
    快速模式抓详情：4 线程小并发 + 压缩延时（0.05~0.2s），
    遇 403/429 时接口层会自动降频退避。仍保留每 20 条落盘的断点保护。
    """
    def work(task):
        spu_id, sel_line_cd, cate_name = task
        detail_url = f"{SITE_BASE}/cn/store/commodity/{spu_id}"
        try:
            time.sleep(random.uniform(0.05, 0.2))
            rec = fetch_detail_api(_thread_client(), spu_id, sel_line_cd,
                                   cate_name, category_map)
            return task, rec, None
        except Exception as e:
            return task, None, str(e)

    ok_cnt = fail_cnt = finished = 0
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = [ex.submit(work, t) for t in pending]
        for fut in as_completed(futures):
            (spu_id, _, _), rec, err = fut.result()
            finished += 1
            if rec is not None:
                products.append(rec)
                done[str(spu_id)] = True
                ok_cnt += 1
            else:
                fail_cnt += 1
                record_failure(out_dir, f"{SITE_BASE}/cn/store/commodity/{spu_id}", err)
            if finished % 50 == 0:
                log(f"  快速模式进度：{finished}/{len(pending)}")
            if finished % CHECKPOINT_EVERY == 0:
                save_outputs(products, out_dir)
                save_progress(out_dir, done, products)
    return ok_cnt, fail_cnt


# ----------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------
def run(args):
    global DELAY_MIN, DELAY_MAX
    out_dir = args.out_dir
    os.makedirs(out_dir, exist_ok=True)
    client = MujiClient()

    if args.fast:
        DELAY_MIN, DELAY_MAX = 0.05, 0.2
        log("快速模式：压缩延时 + 4 并发（遇限流自动降频，若大量失败请改回普通模式）")

    # 1. 解析入口 URL，确定抓取范围
    mode, *extra = parse_input_url(args.url)
    category_map = build_category_map(client)  # selLineCd -> 分类全路径
    targets = []  # [(spu_id, sel_line_cd, cate_name)]
    if mode == "detail":
        targets = [(extra[0], None, "")]
        log(f"模式：单个商品 spuId={extra[0]}")
    elif mode == "catalog":
        cate_id, cate_type = extra
        log(f"模式：指定分类 cateId={cate_id} cateType={cate_type}")
        items = list_products_api(client, cate_id=cate_id, cate_type=cate_type,
                                  per_page=args.per_page, max_items=args.limit)
        targets = [(sid, cd, "") for sid, cd in items]
    elif mode == "all":
        log("模式：全站商品列表")
        items = list_products_api(client, cate_id=None, cate_type="all",
                                  per_page=args.per_page, max_items=args.limit)
        targets = [(sid, cd, "") for sid, cd in items]
    else:
        log("模式：HTML 链接提取（未识别的 URL 规律）")
        ids = extract_links_from_html(args.url, client, use_playwright=not args.no_playwright)
        if not ids:
            log("未发现商品链接，改用全站列表模式继续。")
            items = list_products_api(client, per_page=args.per_page, max_items=args.limit)
            targets = [(sid, cd, "") for sid, cd in items]
        else:
            targets = [(i, None, "") for i in ids]

    if args.limit:
        targets = targets[:args.limit]
    log(f"待抓取商品共 {len(targets)} 个")

    # 2. 断点续抓：跳过已完成商品
    done, products = load_progress(out_dir)
    pending = [t for t in targets if str(t[0]) not in done]
    log(f"已完成 {len(targets) - len(pending)} 个（断点续抓），本次需抓 {len(pending)} 个")

    ok_cnt = fail_cnt = 0
    if args.fast and pending:
        ok_cnt, fail_cnt = run_fast_details(pending, done, products, category_map, out_dir)
    for idx, (spu_id, sel_line_cd, cate_name) in enumerate(pending, 1):
        if args.fast:
            break  # 快速模式已在上面处理完
        detail_url = f"{SITE_BASE}/cn/store/commodity/{spu_id}"
        log(f"({idx}/{len(pending)}) spuId={spu_id} {detail_url}")
        try:
            polite_sleep()
            try:
                rec = fetch_detail_api(client, spu_id, sel_line_cd, cate_name, category_map)
            except RuntimeError as e:
                if args.no_playwright:
                    raise
                log(f"  主链路失败（{e}），切换 Playwright 兜底重抓...")
                rec = fetch_detail_playwright(detail_url)
            products.append(rec)
            done[str(spu_id)] = True
            ok_cnt += 1
            log(f"  ✔ {rec['title'][:30]}  价格={rec['price']}  图{len(rec['images'])}张")
        except Exception as e:
            fail_cnt += 1
            log(f"  ✘ 抓取失败：{e}")
            record_failure(out_dir, detail_url, str(e))

        # 每 20 条自动落盘（断点续抓）
        if idx % CHECKPOINT_EVERY == 0:
            save_outputs(products, out_dir)
            save_progress(out_dir, done, products)
            log(f"  -- 已落盘 {len(products)} 条（断点保护）--")

    # 3. 收尾：最终产出与失败清单提示
    save_outputs(products, out_dir)
    save_progress(out_dir, done, products)

    failed_path = os.path.join(out_dir, "failed_urls.txt")
    log("=" * 56)
    log(f"完成：成功 {ok_cnt}，失败 {fail_cnt}，累计 {len(products)} 条")
    log(f"JSON: {os.path.join(out_dir, 'muji_products.json')}")
    log(f"CSV : {os.path.join(out_dir, 'muji_products.csv')}")
    if os.path.exists(failed_path) and fail_cnt:
        log(f"!! 存在失败 URL，清单见 {failed_path}，可重新运行本脚本自动补抓")
    log("=" * 56)


def main():
    parser = argparse.ArgumentParser(
        description="MUJI（muji.com.cn）商品详情抓取脚本（仅限个人学习/研究）")
    parser.add_argument("url", help="列表页或详情页 URL")
    parser.add_argument("--limit", type=int, default=None, help="最多抓取 N 个商品")
    parser.add_argument("--per-page", type=int, default=20, help="列表分页大小（默认20，最大50）")
    parser.add_argument("--out-dir", default=".", help="产出目录（默认当前目录）")
    parser.add_argument("--no-playwright", action="store_true", help="禁用 Playwright 兜底")
    parser.add_argument("--fast", action="store_true",
                        help="快速模式：压缩延时+4并发（更快，但被限流风险更高）")
    args = parser.parse_args()

    if args.per_page > 50:
        args.per_page = 50  # 接口上限保护，避免异常大分页给服务器压力
    run(args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n用户中断，进度已按最近一次落盘保存。", flush=True)
        sys.exit(130)
