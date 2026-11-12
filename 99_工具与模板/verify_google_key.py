r"""verify_google_key.py - 拿到 Gemini key 之后，5 分钟验完全部前提。

它回答四个问题，每个都对应一个独立的失败原因：

  1. 出口地区在不在 Gemini API 的支持列表里？
     （判定依据是**请求源 IP**，不是账号注册地）
  2. key 有效吗？（2026-05-28 之后创建的是 "auth key"，旧式 key 会被拒）
  3. 哪些模型可用？哪些在免费层里？
  4. OpenAI 兼容层真的能出活吗？（这是 dispatch.py 要用的路径）

用法：
    python verify_google_key.py                 # 从环境变量 GEMINI_API_KEY 读
    python verify_google_key.py --key <KEY>    # 直接给
    python verify_google_key.py --proxy http://127.0.0.1:7897
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

BASE = 'https://generativelanguage.googleapis.com/v1beta'
OPENAI_BASE = 'https://generativelanguage.googleapis.com/v1beta/openai'

# 已知的免费层模型（2026-11 口径；官方页面没列全 RPM/TPM/RPD，靠这里对名字）
FREE_HINT = ('flash', 'flash-lite', '2.5-pro')
# 已知不在免费层
NOT_FREE = ('pro-preview', 'argon', 'veo', 'lyria', 'omni')


def get(url: str, headers: dict, proxy: str | None, timeout: int = 25):
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({'https': proxy, 'http': proxy}) if proxy
        else urllib.request.ProxyHandler())
    req = urllib.request.Request(url, headers=headers)
    try:
        with opener.open(req, timeout=timeout) as r:
            return r.status, r.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'replace')
    except Exception as e:
        return 0, f'{type(e).__name__}: {e}'


def post(url: str, payload: dict, headers: dict, proxy: str | None, timeout: int = 60):
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({'https': proxy, 'http': proxy}) if proxy
        else urllib.request.ProxyHandler())
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={
        'Content-Type': 'application/json', **headers}, method='POST')
    try:
        with opener.open(req, timeout=timeout) as r:
            return r.status, r.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'replace')
    except Exception as e:
        return 0, f'{type(e).__name__}: {e}'


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--key', default=os.environ.get('GEMINI_API_KEY', ''))
    ap.add_argument('--proxy', default=os.environ.get('HTTPS_PROXY', ''),
                    help='出口代理，例如 http://127.0.0.1:7897')
    args = ap.parse_args()
    key = args.key.strip()
    proxy = args.proxy or None

    print('=' * 72)
    print('Gemini key 验证')
    print('=' * 72)
    print(f'  出口代理 : {proxy or "（直连）"}')
    if not key:
        print('\n✘ 没有 key。用 --key <KEY> 或设 GEMINI_API_KEY 环境变量。')
        return 2
    print(f'  key     : {key[:6]}...{key[-4:]}  ({len(key)} 字符)')

    # ---- 1. 出口地区 --------------------------------------------------
    print('\n[1/4] 出口地区')
    st, body = get('https://ifconfig.co/json', {'User-Agent': 'curl/8'}, proxy)
    if st == 200:
        try:
            d = json.loads(body)
            cc = d.get('country_iso')
            print(f'  IP={d.get("ip")}  地区={cc} {d.get("country")}')
            print(f'  ⚠ Google 支持列表里：土耳其/新加坡/日本/美国… **不含中国大陆与香港**')
            if cc in ('CN', 'HK'):
                print(f'  ⇒ 当前出口（{cc}）**不在 Gemini API 支持列表**，'
                      '换节点或换出口再继续')
        except Exception:
            print('  (拿不到地区信息，继续)')
    else:
        print(f'  (地区查询失败: {str(body)[:80]})')

    # ---- 2. key 有效性 + 模型列表 --------------------------------------
    print('\n[2/4] key 有效性 + 模型列表')
    st, body = get(f'{BASE}/models?key={key}', {'User-Agent': 'curl/8'}, proxy)
    if st != 200:
        print(f'  ✘ HTTP {st}')
        try:
            err = json.loads(body)['error']
            print(f"     {err.get('status')}: {err.get('message')}")
            if 'location' in err.get('message', '').lower():
                print('     ⇒ **出口地区不支持**（换代理节点）')
            elif 'API key' in err.get('message', ''):
                print('     ⇒ key 无效/被吊销/不是 auth key')
        except Exception:
            print('     ', body[:200])
        return 1
    try:
        models = json.loads(body).get('models', [])
    except Exception:
        print('  ✘ 响应不是 JSON')
        return 1
    names = sorted(m.get('name', '').replace('models/', '') for m in models)
    print(f'  ✓ key 有效，可见 {len(names)} 个模型')
    free = [n for n in names if any(h in n.lower() for h in FREE_HINT)]
    paid = [n for n in names if any(h in n.lower() for h in NOT_FREE)]
    print(f'\n  可能在免费层（名字含 flash / flash-lite / 2.5-pro）:')
    for n in free[:12]:
        print(f'      {n}')
    if paid:
        print(f'\n  ★ 已知**不在免费层**（用它们要钱）:')
        for n in paid[:12]:
            print(f'      {n}')

    # ---- 3. OpenAI 兼容层能不能出活（dispatch.py 用的就是这条） ----------
    print('\n[3/4] OpenAI 兼容层 /chat/completions（dispatch.py 走这条）')
    target = free[0] if free else (names[0] if names else None)
    if not target:
        print('  ✘ 没有可用模型')
        return 1
    st, body = post(f'{OPENAI_BASE}/chat/completions',
                    {'model': target,
                     'messages': [{'role': 'user', 'content': 'Reply with exactly: PIPELINE_OK'}],
                     'max_tokens': 64},
                    {'Authorization': f'Bearer {key}'}, proxy)
    if st == 200:
        try:
            d = json.loads(body)
            txt = (d['choices'][0]['message'].get('content') or '').strip()
            print(f'  ✓ HTTP 200  模型={target}')
            print(f'  回复: {txt[:80]!r}')
        except Exception:
            print('  ✓ HTTP 200（响应结构异常，打印原文前 200）:', body[:200])
    else:
        print(f'  ✘ HTTP {st}: {body[:220]}')
        return 1

    # ---- 4. 原生 generateContent（对照） --------------------------------
    print('\n[4/4] 原生 generateContent（对照，dispatch.py 不走这条）')
    st, body = post(f'{BASE}/models/{target}:generateContent',
                    {'contents': [{'parts': [{'text': 'Reply with exactly: OK'}]}],
                     'generationConfig': {'maxOutputTokens': 32}},
                    {'x-goog-api-key': key}, proxy)
    print(f'  HTTP {st}' + ('' if st == 200 else f': {body[:160]}'))

    print('\n' + '=' * 72)
    print('结论：这条链路可用 ✅')
    print(f'  下一步：设 GEMINI_API_KEY 环境变量，然后')
    print(f'    python dispatch.py --list    # 会看到 google 变成可用')
    print(f'    python dispatch.py --probe  # 实测两个 gemini 模型')
    print('=' * 72)
    return 0


if __name__ == '__main__':
    sys.exit(main())
