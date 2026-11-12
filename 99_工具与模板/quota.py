"""quota.py - what is actually available right now, across sites AND models.

The dispatcher needs this: knowing WHICH site AND WHICH model still has room
is what makes failover work. Probing only the default model is how you get
stuck on a 402 when the same site still serves gpt-6.1-sol fine.

Probes each (site, model) pair with one tiny request, in parallel-safe
sequential order, and reports the live state.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ENV = dict(os.environ)
ENV['CODEX_HOME'] = r'C:\Users\18798\.codex'
NPM = Path(os.environ.get('APPDATA', r'C:\Users\18798\AppData\Roaming')) / 'npm'

# (site, model) -> the codex profile that requests exactly that combination
COMBOS = [
    ('agentrouter', 'gpt-6-astra',    'relay-agentrouter'),
    ('agentrouter', 'gpt-6.1-sol',    'relay-agentrouter-sol'),
    ('pincar',      'gpt-6-astra',    'relay-pincar'),
    ('pincar',      'gpt-6.1-sol',    'relay-pincar-sol'),
]

RETRYABLE = re.compile(
    r'402|Budget pool quota|429|Too Many Requests|503|no available channel|'
    r'exceeded retry limit|stream disconnected', re.IGNORECASE)


def codex_exe() -> str:
    for n in ('codex.cmd', 'codex.bat', 'codex.exe'):
        p = NPM / n
        if p.exists():
            return str(p)
    raise FileNotFoundError('codex launcher not found')


def probe(profile: str, timeout: int = 200) -> tuple[str, float]:
    t0 = time.monotonic()
    try:
        r = subprocess.run([codex_exe(), 'exec', '--profile', profile,
                            '--skip-git-repo-check', 'reply with the single word OK'],
                           capture_output=True, text=True, encoding='utf-8',
                           errors='replace', env=ENV, timeout=timeout, input='')
    except subprocess.TimeoutExpired:
        return 'TIMEOUT', time.monotonic() - t0
    out = (r.stdout or '') + (r.stderr or '')
    dt = time.monotonic() - t0
    if r.returncode == 0 and 'OK' in out:
        return 'ALIVE', dt
    m = RETRYABLE.search(out)
    if '402' in out:
        return '402 budget pool empty', dt
    if '429' in out:
        return '429 rate limited', dt
    if '503' in out:
        return '503 no channel', dt
    if 'access denied' in out.lower():
        return 'LOCKED (app-server busy)', dt
    if m:
        return 'quota/transport error', dt
    return f'rc={r.returncode}', dt


def main() -> int:
    print('=' * 74)
    print('LIVE QUOTA MATRIX  (one tiny real request per cell)')
    print('=' * 74)
    rows = []
    for site, model, profile in COMBOS:
        status, dt = probe(profile)
        print(f'  {site:14s} {model:14s} {status:26s} ({dt:.1f}s)', flush=True)
        rows.append({'site': site, 'model': model, 'profile': profile,
                     'status': status, 'seconds': round(dt, 1)})
    print()
    alive = [r for r in rows if r['status'] == 'ALIVE']
    print('  usable right now:')
    if alive:
        for r in alive:
            print(f"     {r['site']} / {r['model']}   (profile {r['profile']})")
    else:
        print('     none - both sites are out of room at the moment')
    out = Path(__file__).resolve().parent / 'quota_latest.json'
    out.write_text(json.dumps({'at': time.strftime('%Y-%m-%d %H:%M:%S'),
                               'rows': rows}, ensure_ascii=False, indent=2),
                   encoding='utf-8')
    print(f'\n  saved -> {out.name}')
    return 0 if alive else 1


if __name__ == '__main__':
    sys.exit(main())
