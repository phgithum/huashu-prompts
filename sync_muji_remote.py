# -*- coding: utf-8 -*-
"""把每周抓取结果同步到 MUJI 独立仓库（phgithum/MUJI）。

设计原则：数据可以覆盖，页面绝不能被覆盖。
  - data.js       ：正常更新（商品数据每周变）
  - index.html    ：只把 data.js 的版本号替换成新时间戳，页面其它内容原样保留
  - admin.html    ：不动
  - acl.json      ：不动（运行时 ACL 走 kvdb，仓库这份只是存档）

安全闸：推送 index.html 前会检查线上版本里是否存在门禁标记 frontGate，
       不存在就直接中止并报错，避免用本地旧模板把线上门禁覆盖掉。
"""
import base64
import json
import os
import re
import sys
import time
import urllib.request

TOKEN = os.environ.get('TOKEN', '')
REPO = 'phgithum/MUJI'
STAMP = sys.argv[1] if len(sys.argv) > 1 else time.strftime('%Y%m%d%H%M')
H = {
    'Authorization': 'Bearer ' + TOKEN,
    'Accept': 'application/vnd.github+json',
    'Content-Type': 'application/json',
    'User-Agent': 'muji-sync',
}


def api_get(path):
    """contents API：拿 sha（顺带拿小文件内容，>1MB 的文件 content 会为空）"""
    url = 'https://api.github.com/repos/%s/contents/%s?ref=main' % (REPO, path)
    j = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=H)).read())
    raw = b''
    if j.get('content'):
        raw = base64.b64decode(j['content'].replace('\n', ''))
    return j['sha'], raw


def raw_get(path):
    """raw 通道：大文件也能完整读回"""
    url = 'https://raw.githubusercontent.com/%s/main/%s?t=%d' % (REPO, path, time.time())
    return urllib.request.urlopen(urllib.request.Request(url)).read()


def api_put(path, raw, sha, msg):
    url = 'https://api.github.com/repos/%s/contents/%s' % (REPO, path)
    body = {
        'message': msg,
        'branch': 'main',
        'content': base64.b64encode(raw).decode(),
        'sha': sha,
    }
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method='PUT', headers=H)
    return urllib.request.urlopen(req).status


def main():
    if not TOKEN:
        raise SystemExit('未提供 TOKEN，无法同步')

    # ---------- 1. data.js：正常更新 ----------
    local_data = open(os.path.join('muji-chat', 'data.js'), 'rb').read()
    try:
        remote_data = raw_get('data.js')
    except Exception as e:
        remote_data = b''
        print('读取线上 data.js 失败，将直接推送:', e)
    if remote_data and remote_data == local_data:
        print('data.js 内容无变化，跳过')
    else:
        sha, _ = api_get('data.js')
        print('data.js ->', api_put('data.js', local_data, sha, 'weekly data update ' + STAMP))

    # ---------- 2. index.html：只换版本号，其余原样保留 ----------
    sha, html = api_get('index.html')
    text = html.decode('utf-8')
    if 'frontGate' not in text:
        raise SystemExit(
            '中止：线上 index.html 未检测到门禁标记（frontGate），'
            '为防止覆盖页面已停止同步，请先人工确认线上版本'
        )
    new_text = re.sub(r'data\.js\?v=[0-9a-zA-Z]+', 'data.js?v=' + STAMP, text)
    if new_text == text:
        print('index.html 版本号无变化，跳过')
    else:
        print('index.html ->', api_put(
            'index.html', new_text.encode('utf-8'), sha, 'chore: bump data version ' + STAMP))

    print('同步完成：admin.html 与 acl.json 保持不动')


if __name__ == '__main__':
    main()
