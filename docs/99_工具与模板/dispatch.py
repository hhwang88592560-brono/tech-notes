"""dispatch.py - run one distillation task on whichever relay site still has quota.

THE PROBLEM THIS SOLVES
------------------------
You want to learn C and embedded systems by distilling material with an LLM.
You have two relay sites (pincar and agentrouter). They serve different models,
their quotas run out at different times, and one of them often returns
402 "budget pool exhausted" or 429 "too many requests" mid-session.

Naively, every failed call means: stop, open the dashboard, read the error,
edit a config file, retry. That is slow and it loses the thread.

WHY A DISPATCHER IS THE RIGHT SHAPE
------------------------------------
Proved by capture (2026-11-11): Codex re-sends the ENTIRE conversation every
turn, with store=false and no previous_response_id. So a conversation carries
its own context, and the site that answers a turn does not have to be the
site that answered the previous one.

That means the retry can be done at the TASK level, not the site level:
this script picks the site, runs the task, and if the site is out of quota
it picks another one and runs the same task there - with the same prompt,
the same model family and the same asking method.

THE SHARED ASKING METHOD
------------------------
Every site is called through the same profile shape:
    model            = gpt-6-astra   (the one model both sites serve)
    reasoning effort = max
    the same prompt file
So "pincar 提问" and "agentrouter 提问" produce the same style of answer.
The site changes; the method does not.

USAGE
-----
    python dispatch.py --list
        show the sites, their profiles, and which one is preferred now

    python dispatch.py --probe
        actually test each site with a tiny request, print which are alive

    python dispatch.py --task <file.md> [--profile <name>]
        run one task file through the best available site, with failover

    python dispatch.py --task <file.md> --dry-run
        show exactly what would be sent, without sending it
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
COURSE = ROOT.parent

# The shared asking method. Same model + same effort + same prompt on every
# site, which is what makes "pincar 提问" and "agentrouter 提问" the same
# method. The model is the one both sites serve.
SHARED_MODEL = 'gpt-6-astra'
SHARED_EFFORT = 'max'

# Ordered by preference. 'agentrouter' first: its daily check-in is larger,
# so it tends to run out later in the day; pincar is the fallback.
#
# IMPORTANT (measured 2026-11-11): the SITE is not the only thing that
# runs out. Each site has a separate budget pool PER MODEL, so a site can
# answer gpt-6.1-sol while returning 402 for gpt-6-astra. Failover must
# therefore walk (site, model) pairs, not just sites.
#
# The model order inside a site is fixed (astra first, sol second) so that
# "the same asking method" is preserved: the shared model is preferred, and
# gpt-6.1-sol is only used when the shared model's pool is empty.
#
# ★ transport: 每站可以用不同的传输方式 ★
#   'codex' —— 走真实 Codex 客户端（codex exec --profile X）。
#              ★ 必须这样 because 中转站会**校验客户端指纹**：
#              pincar 对普通 HTTP 客户端返 403
#              'This account only allows Codex official clients'。
#   'http'  —— 走 OpenAI SDK 的 chat.completions（普通 HTTP）。
#              用于**不校验指纹**的官方渠道，比如 Google Gemini 的
#              OpenAI 兼容层 https://generativelanguage.googleapis.com/v1beta/openai/
#              （它没有 /responses 端点，所以**不能**接进 Codex 那条腿，
#                但正好能接这条批量蒸馏的腿）。
#
# ★ 额度是按 (站 × 模型) 分池的 —— 所以故障转移要遍历 (站, 模型) 对，
#   而不只是站（2026-11-11 实测：同一站可以 gpt-6.1-sol 正常、gpt-6-astra 402）。
SITES = [
    {'name': 'agentrouter', 'transport': 'codex',
     'provider': 'agentrouter_main_20261109',
     'base_url': 'https://agentrouter.org/v1',
     'profiles': [('gpt-6-astra', 'relay-agentrouter'),
                  ('gpt-6.1-sol', 'relay-agentrouter-sol')]},
    {'name': 'pincar', 'transport': 'codex',
     'provider': 'pincar',
     'base_url': 'https://intl.freehyy.com',
     'profiles': [('gpt-6-astra', 'relay-pincar'),
                  ('gpt-6.1-sol', 'relay-pincar-sol')]},
    # Google Gemini（官方 OpenAI 兼容层）。**没有 key 就自动跳过**，
    # 不会给每次任务添乱。详见《谷歌渠道调研与使用指南.md》。
    {'name': 'google', 'transport': 'http',
     'base_url': 'https://generativelanguage.googleapis.com/v1beta/openai',
     'api_key_env': 'GEMINI_API_KEY',
     'profiles': [('gemini-3.8-flash', None),
                  ('gemini-2.5-pro', None)]},
]

# Errors that mean "this site is out of room; try the other one".
RETRYABLE = re.compile(
    r'402|Budget pool quota|429|Too Many Requests|503|no available channel|'
    r'exceeded retry limit|stream disconnected|connection|timeout',
    re.IGNORECASE)


def codex_home() -> Path:
    return Path(os.environ.get('CODEX_HOME', r'C:\Users\18798\.codex'))


def codex_exe() -> str:
    """Resolve the codex launcher.

    On this machine `codex` is an npm shim, so it is a .cmd on Windows -
    which subprocess cannot exec directly without a shell. Resolve it by
    hand instead of relying on PATH.
    """
    if shutil.which('codex'):
        return shutil.which('codex')
    npm = Path(os.environ.get('APPDATA', r'C:\Users\18798\AppData\Roaming')) / 'npm'
    for name in ('codex.cmd', 'codex.bat', 'codex.exe'):
        p = npm / name
        if p.exists():
            return str(p)
    # The desktop app's bundled binary is a last resort.
    app = Path(os.environ.get('LOCALAPPDATA', r'C:\Users\18798\AppData\Local'))
    for p in (app / 'OpenAI' / 'Codex' / 'bin').glob('*/codex.exe'):
        return str(p)
    raise FileNotFoundError('codex executable not found')


def run_codex(profile: str, prompt: str, timeout: int = 900) -> tuple[int, str]:
    env = dict(os.environ)
    env['CODEX_HOME'] = str(codex_home())
    try:
        exe = codex_exe()
    except FileNotFoundError as exc:
        return 127, str(exc)
    cmd = [exe, 'exec', '--profile', profile, '--skip-git-repo-check', prompt]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8',
                           errors='replace', env=env, timeout=timeout,
                           input='')
        return r.returncode, (r.stdout or '') + '\n' + (r.stderr or '')
    except subprocess.TimeoutExpired:
        return 124, f'TIMEOUT after {timeout}s'
    except FileNotFoundError:
        return 127, 'codex executable not found'


def run_http(model: str, base_url: str, prompt: str, api_key: str,
             timeout: int = 900) -> tuple[int, str]:
    """Call an OpenAI-compatible /chat/completions endpoint directly.

    Used for channels that do NOT fingerprint the client (Google Gemini's
    OpenAI-compatibility layer). Those have no /responses endpoint, so they
    cannot be driven by the Codex client at all - but they do speak
    chat.completions, which is all a distillation run needs.
    """
    try:
        from openai import OpenAI
    except ImportError as exc:
        return 127, f'openai package not installed: {exc}'
    try:
        client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
        resp = client.chat.completions.create(
            model=model,
            messages=[{'role': 'user', 'content': prompt}],
        )
        text = resp.choices[0].message.content or ''
        return 0, text
    except Exception as exc:
        return 1, f'{type(exc).__name__}: {exc}'


def site_ready(site: dict) -> tuple[bool, str]:
    """Is this site usable right now?

    A site that needs an env var we don't have is SKIPPED, not failed -
    otherwise every task would burn a retry slot on it.
    """
    env = site.get('api_key_env')
    if env and not os.environ.get(env):
        return False, f'{env} 没设（跳过）'
    return True, ''


def strip_banner(text: str) -> str:
    """Codex exec prints a header block and a trailing 'tokens used' block.

    Keep only the answer: everything between the 'user' echo and the
    'tokens used' marker.
    """
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if ln.strip() == 'user':
            start = i + 1
            break
    if start is None:
        return text.strip()
    out = []
    for ln in lines[start:]:
        if ln.startswith('tokens used'):
            break
        out.append(ln)
    return '\n'.join(out).strip() or text.strip()


def probe_site(site: dict, model: str, prof: str | None) -> tuple[bool, str]:
    """Probe one (site, model) pair with a real request."""
    if site.get('transport') == 'http':
        key = os.environ.get(site.get('api_key_env', ''), '')
        rc, out = run_http(model, site['base_url'],
                           'reply with the single word OK', key, timeout=180)
    else:
        rc, out = run_codex(prof, 'reply with the single word OK', timeout=180)
    if rc == 0 and 'OK' in out:
        return True, 'alive'
    m = RETRYABLE.search(out)
    reason = 'out of quota' if m else f'rc={rc}'
    return False, reason


def cmd_list(args) -> int:
    print('=' * 74)
    print('Sites available to the dispatcher (same asking method on each)')
    print('=' * 74)
    print(f'  shared model  : {SHARED_MODEL}   (preferred everywhere)')
    print(f'  shared effort : {SHARED_EFFORT}')
    print()
    print('  Failover walks (site, model) pairs, because each site has a')
    print('  separate budget pool PER MODEL - a site can 402 on astra while')
    print('  still serving sol. Measured 2026-11-11: exactly that happened.')
    print()
    print('  transport: codex = 走真实 Codex 客户端（站点校验客户端指纹时必需）')
    print('             http  = 走 OpenAI 兼容 chat.completions（普通 HTTP）')
    print()
    for i, s in enumerate(SITES):
        ready, why = site_ready(s)
        mark = '' if ready else f'   [不可用: {why}]'
        print(f'  {i + 1}. {s["name"]:14s} {s["base_url"]}'
              f'   transport={s.get("transport", "codex")}{mark}')
        for model, prof in s['profiles']:
            tag = '  <- shared model' if model == SHARED_MODEL else '  <- fallback'
            print(f'       {model:16s} profile={str(prof):22s}{tag}')
    print()
    print('  Task file format: a .md file used verbatim as the prompt.')
    print('  Output goes next to it as <name>.out.md + <name>.meta.json')
    return 0


def cmd_probe(args) -> int:
    print('=' * 74)
    print('Probing every (site, model) pair with a real request')
    print('=' * 74)
    alive = []
    for s in SITES:
        ready, why = site_ready(s)
        if not ready:
            print(f'  {s["name"]:14s} {"SKIP":14s}  ({why})', flush=True)
            continue
        for model, prof in s['profiles']:
            t0 = time.monotonic()
            ok, why2 = probe_site(s, model, prof)
            dt = round(time.monotonic() - t0, 1)
            print(f'  {s["name"]:14s} {model:16s} {"ALIVE" if ok else "DOWN "}  '
                  f'({why2}, {dt}s)', flush=True)
            if ok:
                alive.append((s['name'], model, prof))
    print()
    if alive:
        print('  usable right now (in failover order):')
        for site, model, prof in alive:
            print(f'     {site:14s} / {model:16s}  profile {prof}')
    else:
        print('  usable right now: none - every pool is empty')
    return 0 if alive else 1


def cmd_task(args) -> int:
    task = Path(args.task).resolve()
    if not task.exists():
        print('task file not found:', task)
        return 1
    prompt = task.read_text(encoding='utf-8')

    # Build the ordered list of (site, model, profile, site_cfg) to try.
    # Sites whose required env var is missing are skipped entirely -
    # they must not burn a retry slot.
    pairs = []
    skipped = []
    for s in SITES:
        ready, why = site_ready(s)
        if not ready:
            skipped.append((s['name'], why))
            continue
        for model, prof in s['profiles']:
            pairs.append((s['name'], model, prof, s))
    if args.first:
        pairs.sort(key=lambda p: 0 if p[0] == args.first else 1)
    if args.profile:
        pairs = [p for p in pairs if p[2] == args.profile] or pairs

    if args.dry_run:
        print('=' * 74)
        print('DRY RUN')
        print('=' * 74)
        print(f'  task      : {task}')
        print(f'  would try : {[(s, m) for s, m, _, _ in pairs]}')
        for name, why in skipped:
            print(f'  skipped   : {name}  ({why})')
        print(f'  effort    : {SHARED_EFFORT}')
        print(f'  prompt len: {len(prompt)} chars')
        print()
        print('--- prompt ---')
        print(prompt[:args.show_chars])
        if len(prompt) > args.show_chars:
            print(f'... (+{len(prompt) - args.show_chars} chars)')
        return 0

    attempts = []
    for site, model, prof, scfg in pairs:
        transport = scfg.get('transport', 'codex')
        if transport == 'http':
            key = os.environ.get(scfg.get('api_key_env', ''), '')
            print(f'--> trying {site} / {model} via http ({scfg["base_url"]}) ...',
                  flush=True)
            rc, out = run_http(model, scfg['base_url'], prompt, key,
                               timeout=args.timeout)
        else:
            print(f'--> trying {site} / {model} via profile {prof} ...', flush=True)
            rc, out = run_codex(prof, prompt, timeout=args.timeout)
        if rc == 0:
            answer = strip_banner(out) if transport == 'codex' else out
            dest = task.with_suffix('.out.md')
            dest.write_text(answer, encoding='utf-8')
            meta = task.with_suffix('.meta.json')
            meta.write_text(json.dumps({
                'task': str(task), 'site': site, 'profile': prof,
                'model': model, 'effort': SHARED_EFFORT,
                'transport': transport,
                'at': time.strftime('%Y-%m-%d %H:%M:%S'),
                'attempts': attempts + [{'site': site, 'model': model,
                                          'profile': prof, 'rc': rc}],
            }, ensure_ascii=False, indent=2), encoding='utf-8')
            print(f'\nOK  -> {dest}')
            print(f'    done by {site} / {model}')
            return 0
        m = RETRYABLE.search(out)
        if '402' in out:
            reason = '402 budget pool empty'
        elif '429' in out:
            reason = '429 rate limited'
        elif '503' in out:
            reason = '503 no channel'
        elif 'access denied' in out.lower():
            reason = 'app-server busy (another codex exec is running)'
        elif m:
            reason = 'quota/transport error'
        else:
            reason = f'rc={rc}'
        print(f'    failed ({reason})', flush=True)
        attempts.append({'site': site, 'model': model, 'profile': prof,
                         'transport': transport, 'rc': rc, 'reason': reason})
        if not m and 'access denied' not in out.lower():
            print('    (not a quota problem - not retrying elsewhere)')
            break
    print('\nAll combinations failed. Attempts:')
    for a in attempts:
        print('  ', a)
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description='Dispatch a distillation task to a live relay site.')
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--probe', action='store_true')
    ap.add_argument('--task', help='task markdown file to run')
    ap.add_argument('--profile', help='force one profile (no failover)')
    ap.add_argument('--first', help='try this site first')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--timeout', type=int, default=900)
    ap.add_argument('--show-chars', type=int, default=1200)
    args = ap.parse_args()

    if args.task:
        return cmd_task(args)
    if args.probe:
        return cmd_probe(args)
    return cmd_list(args)


if __name__ == '__main__':
    sys.exit(main())
