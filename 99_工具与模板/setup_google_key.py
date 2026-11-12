r"""setup_google_key.py - 把 Gemini key 接进本机（拿到 key 后跑这个）。

做三件事：
  1. 把 key 存进**用户级环境变量** GEMINI_API_KEY（不写进任何文件）
  2. 可选：把 HTTPS_PROXY 也设成用户级变量（CLI 走代理用）
  3. 跑一次完整验证

★ 为什么用 reg add 而不是 setx ★
  setx 有 1024 字符上限，会**静默截断** PATH（2026-11-12 出过一次事故）。
  reg add 上限 16383，不截断。
  ★ 而且这里只**新增**一个变量值，不碰 PATH，所以不涉及截断风险。

用法：
    python setup_google_key.py --key <KEY>
    python setup_google_key.py --key <KEY> --proxy http://127.0.0.1:7897
    python setup_google_key.py --check        # 只看当前状态
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

REG = r'C:\Windows\System32\reg.exe'
KEY_R = r'HKCU\Environment'


def reg_get(name: str) -> str | None:
    r = subprocess.run([REG, 'query', KEY_R, '/v', name],
                       capture_output=True, text=True, errors='replace')
    for line in r.stdout.splitlines():
        if line.strip().startswith(name) and 'REG_' in line:
            return line.split('REG_SZ',1)[1].strip()
    return None


def reg_set(name: str, value: str) -> tuple[bool, str]:
    r = subprocess.run([REG, 'add', KEY_R, '/v', name, '/t', 'REG_SZ',
                        '/d', value, '/f'],
                       capture_output=True, text=True, errors='replace')
    return r.returncode == 0, (r.stdout or '') + (r.stderr or '')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--key', default='')
    ap.add_argument('--proxy', default='')
    ap.add_argument('--check', action='store_true')
    args = ap.parse_args()

    print('=' * 72)
    print('Gemini key 接入')
    print('=' * 72)

    cur_key = reg_get('GEMINI_API_KEY')
    cur_proxy = reg_get('HTTPS_PROXY')
    print(f'  当前 GEMINI_API_KEY : {"已设 (" + str(len(cur_key)) + " 字符)" if cur_key else "未设"}')
    print(f'  当前 HTTPS_PROXY    : {cur_proxy or "未设"}')

    if args.check:
        print('\n（--check 只看状态）')
        return 0

    key = args.key.strip()
    if not key:
        print('\n✘ 要 --key <KEY>')
        return 2

    ok, out = reg_set('GEMINI_API_KEY', key)
    print(f'\n  GEMINI_API_KEY : {"✔ 已写入用户级环境变量" if ok else "✘ " + out.strip()[:120]}')
    if not ok:
        return 1

    if args.proxy:
        ok2, out2 = reg_set('HTTPS_PROXY', args.proxy)
        print(f'  HTTPS_PROXY    : {"✔ 已写入 " + args.proxy if ok2 else "✘ " + out2.strip()[:120]}')
        print('  （命令行走代理需要它；浏览器已经由 Clash 的"系统代理"接管）')

    # 本进程也要能看到（新开的终端才会继承注册表的值）
    os.environ['GEMINI_API_KEY'] = key
    if args.proxy:
        os.environ['HTTPS_PROXY'] = args.proxy

    print('\n--- 完整验证 ---')
    here = os.path.dirname(os.path.abspath(__file__))
    r = subprocess.run([sys.executable, os.path.join(here, 'verify_google_key.py')],
                       env=dict(os.environ))
    return r.returncode


if __name__ == '__main__':
    sys.exit(main())
