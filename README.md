# MUJI 商品详情抓取（muji.com.cn）

批量抓取无印良品中国官网商品详情，产出结构化数据表。仅限个人学习/研究，不得商用、不得分发。

## 文件说明

| 文件 | 说明 |
|---|---|
| `muji_scraper.py` | 主脚本（Python 3，含合规红线、断点续抓、Playwright 兜底） |
| `muji_products.csv` | 全站商品数据（UTF-8-sig，Excel 直接打开），3568 条 |
| `muji_products.json` | 同一份完整数据（UTF-8，缩进 2） |
| `failed_urls.txt` | 抓取时失效的商品链接 |

## 数据字段

`title` 商品标题 / `price` 价格 / `sku` 货号（13 位条码） / `images` 图片链接（分号分隔） / `description` 材质与说明（≤500 字） / `category` 分类全路径 / `url` 商品页地址

## 用法

```bash
pip install requests beautifulsoup4 lxml fake_useragent playwright
python -m playwright install chromium

# 全站抓取（约 3560 个，1~2 小时，请求间隔 0.5~1.5s）
python muji_scraper.py "https://www.muji.com.cn/cn/store/commodities"

# 限量试跑
python muji_scraper.py "https://www.muji.com.cn/cn/store/commodities" --limit 30

# 指定分类（cateId 见官网列表页 URL）
python muji_scraper.py "https://www.muji.com.cn/cn/store/commodities?cateId=300000132&cateType=middle"
```

支持断点续抓（每 20 条落盘 `progress.json`，重跑自动跳过已完成）、失败重试（指数退避 1s/2s/4s）、403/429 自动降频轮换 UA。

## 技术说明

官网商城为 Vue SPA，直接请求 HTML 为空壳。脚本双链路：

1. **主链路（requests）**：调用官网前端公开 JSON 接口 `/cn/ecapi/maps/ec/*`，按前端同款算法计算 `X-Sign` 签名（MD5，参数排序拼接 + 密钥，转大写）；
2. **兜底链路（Playwright）**：主链路失败时无头渲染页面后用 BeautifulSoup 解析 DOM，图片兼容懒加载 `data-src`。

## 合规红线

- 遵守 robots.txt（官网未发现 Disallow 规则），控制请求频率，不打崩对方服务器
- 数据仅个人学习/研究，不商用、不分发、不绕过登录/付费墙
- 若对方明显反爬升级，立即停止，不使用破解/对抗手段
