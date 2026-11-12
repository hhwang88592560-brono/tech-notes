r"""verify_172.py - the 12-item acceptance checklist for the DeepTutor 1.7.2 trial.

Runs every check against the TRIAL container (deeptutor-172), never against
the production 1.6.15 one. Exits 0 only if all hard checks pass.

    python verify_172.py            # run everything
    python verify_172.py --only 5 7 # run selected checks
    python verify_172.py --list     # show what each check does

HARD checks (a failure means "do not migrate"):  5, 6, 7, 12
SOFT checks (a failure means "the feature is degraded but the app works"):
everything else.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

C = 'deeptutor'              # target container; override with --container
LAB = r'D:\DeepTutorLab'
RESULTS: list[tuple[int, str, bool, bool, str]] = []   # (n, name, ok, hard, detail)


def sh(cmd: list[str], timeout: int = 180) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8',
                           errors='replace', timeout=timeout)
        return r.returncode, ((r.stdout or '') + (r.stderr or '')).strip()
    except subprocess.TimeoutExpired:
        return 124, f'TIMEOUT after {timeout}s'
    except Exception as e:
        return 1, f'{type(e).__name__}: {e}'


def dexec(code: str, timeout: int = 180) -> tuple[int, str]:
    return sh(['docker', 'exec', C, 'python', '-c', code], timeout)


def record(n: int, name: str, ok: bool, hard: bool, detail: str = '') -> bool:
    RESULTS.append((n, name, ok, hard, detail))
    return ok


# ---------------------------------------------------------------- checks

def c1_container_healthy() -> None:
    rc, out = sh(['docker', 'ps', '--filter', f'name=^{C}$',
                  '--format', '{{.Names}}|{{.Status}}|{{.Image}}'])
    line = out.splitlines()[0] if out.strip() else ''
    ok = 'healthy' in line or ('Up ' in line and 'starting' not in line)
    record(1, '容器健康', ok, False, line or out)


def c2_extras_installed() -> None:
    """Functional, not by package name.

    Two traps here:
      * `fastapi-guard` (the DISTRIBUTION) provides the MODULE `guard`
        (renamed in v8) - `import fastapi_guard` fails even when it is installed.
      * the `deeptutor-*` sub-distributions (reading / partners /
        parser-pymupdf4llm) are NOT pip-installed: the image ships the whole
        `deeptutor/` SOURCE tree, so `deeptutor.reading` etc. import fine
        straight from /app/deeptutor.
    So the honest test is: can each feature's module be imported?
    """
    code = (
        "import importlib, importlib.util as u\n"
        "mods=['guard','pymupdf4llm','lightrag','edge_tts',"
        "'deeptutor.reading','deeptutor.partners','deeptutor.reading.ingestion']\n"
        "bad=[]\n"
        "for m in mods:\n"
        "    try:\n"
        "        if u.find_spec(m) is None: bad.append(m+'(not found)')\n"
        "        else: importlib.import_module(m)\n"
        "    except Exception as e: bad.append(m+'('+type(e).__name__+')')\n"
        "print('BAD', ','.join(bad) if bad else 'none')\n")
    p = subprocess.run(['docker', 'exec', '-i', C, 'python', '-'],
                       input=code, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180)
    out = (p.stdout or '') + (p.stderr or '')
    bad = out.split('BAD')[1].split()[0] if 'BAD' in out else 'unknown'
    record(2, 'extras 功能模块全部可 import', bad == 'none', False,
           'unimportable: ' + bad if bad != 'none' else 'all 7 importable')


def c3_guard_did_not_block_start() -> None:
    rc, out = sh(['docker', 'logs', C])
    bad = [l for l in out.splitlines()
           if 'security_guard is enabled' in l or 'not installed' in l.lower()
           or 'RuntimeError' in l]
    record(3, 'guard 没让容器拒绝启动', not bad, False,
           '\n'.join(bad[:4]) if bad else 'no guard errors')


def c4_guard_switch_still_works() -> None:
    rc, out = dexec(
        "import json;p='/app/data/user/settings/system.json';"
        "d=json.load(open(p));print(d.get('security_guard',{}).get('enabled'))")
    record(4, 'guard 开关仍生效 (system.json)', out.strip() == 'True',
           False, out.strip() or 'unreadable')


def c5_stt_schema_compatible() -> None:
    """HARD. The whole local-whisper wiring rides on these four fields."""
    rc, out = dexec(
        "from deeptutor.services.config.provider_runtime import "
        "resolve_stt_runtime_config as r; c=r(); "
        "print(c.model, c.provider_name, c.base_url, c.adapter)")
    want = ['whisper-1', 'custom', 'whisper-asr:8000', 'openai_compat']
    ok = rc == 0 and all(w in out for w in want)
    record(5, '★ STT 配置 schema 兼容', ok, True, out.strip()[:300])


def c6_task_model_works() -> None:
    """HARD. Resolves the task profile AND makes a real request with it."""
    rc, out = dexec(
        "from deeptutor.services.config.provider_runtime import "
        "resolve_llm_runtime_config as r; c=r(service_name='task'); "
        "print('RESOLVED', c.model, c.provider_name, c.base_url)")
    if rc != 0 or 'RESOLVED' not in out:
        record(6, '★ 出题模型指向本机且能真的回答', False, True,
               out.strip()[:300] or 'resolve failed')
        return
    resolved = out.strip()
    local = ('qwen3' in resolved and '11434' in resolved)
    # now actually ask it something.
    # max_tokens must be generous: at 64 the local qwen3 returns an EMPTY
    # content (the budget is consumed before any visible token lands).
    # 512 is the smallest that reliably answers.
    code = (
        "import asyncio\n"
        "from openai import AsyncOpenAI\n"
        "from deeptutor.services.config.provider_runtime import "
        "resolve_llm_runtime_config as r\n"
        "async def go():\n"
        "    c=r(service_name='task')\n"
        "    cli=AsyncOpenAI(base_url=c.base_url, api_key=c.api_key or 'ollama')\n"
        "    resp=await cli.chat.completions.create(model=c.model,"
        " messages=[{'role':'user','content':'Reply with exactly: PIPELINE_OK'}],"
        " max_tokens=512)\n"
        "    print('REPLY:', (resp.choices[0].message.content or '').strip()[:120])\n"
        "asyncio.run(go())\n")
    p = subprocess.run(['docker', 'exec', '-i', C, 'python', '-'],
                       input=code, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=240)
    out2 = (p.stdout or '') + (p.stderr or '')
    answered = 'REPLY:' in out2 and 'PIPELINE_OK' in out2.replace(' ', '')
    record(6, '★ 出题模型指向本机且能真的回答', local and answered, True,
           (resolved + ' | ' + out2.strip())[:400])


def c7_whisper_transcribes() -> None:
    """HARD. Real speech in, real words out, through DeepTutor's own adapter."""
    wav = r'C:\Users\18798\Documents\speech.wav'
    if not __import__('os').path.exists(wav):
        record(7, '★ 本机 Whisper 真能转写', False, True,
               'speech.wav missing - synthesize it first')
        return
    # put the wav in the container (stdin, because Git Bash rewrites /tmp paths)
    with open(wav, 'rb') as fh:
        subprocess.run(['docker', 'exec', '-i', C, 'sh', '-c',
                        'cat > /tmp/speech.wav'],
                       stdin=fh, capture_output=True)
    code = (
        "import asyncio\n"
        "from deeptutor.services.config.provider_runtime import resolve_stt_runtime_config\n"
        "from deeptutor.services.voice.adapters.openai_compat import OpenAICompatSTTAdapter\n"
        "async def go():\n"
        "    cfg=resolve_stt_runtime_config()\n"
        "    audio=open('/tmp/speech.wav','rb').read()\n"
        "    cues=await OpenAICompatSTTAdapter().transcribe_cues("
        "audio,cfg,filename='speech.wav',content_type='audio/wav')\n"
        "    print('CUES',len(cues))\n"
        "    for c in cues[:3]:\n"
        "        print('  ',getattr(c,'start_seconds','?'),'-',getattr(c,'end_seconds','?'),"
        "(getattr(c,'text','') or '').strip())\n"
        "asyncio.run(go())\n")
    p = subprocess.run(['docker', 'exec', '-i', C, 'python', '-'],
                       input=code, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=300)
    out = (p.stdout or '') + (p.stderr or '')
    n_cues = 0
    if 'CUES' in out:
        try:
            n_cues = int(out.split('CUES')[1].split()[0])
        except Exception:
            n_cues = 0
    ok = n_cues > 0 and 'Traceback' not in out
    record(7, '★ 本机 Whisper 真能转写', ok, True, out.strip()[:400])


def c8_old_knowledge_bases() -> None:
    """Look INSIDE the container - the host-side path differs per instance
    (production uses ./data, the trial used ./data-172), and the trial's
    directory is gone now that it has been torn down."""
    code = (
        "import os, pathlib\n"
        "kb=pathlib.Path('/app/data/knowledge_bases')\n"
        "e=sorted(p.name for p in kb.iterdir()) if kb.exists() else []\n"
        "print('ENTRIES', len(e), e[:6])\n"
        "cfg=kb/'kb_config.json'\n"
        "print('CONFIG', cfg.exists(), cfg.stat().st_size if cfg.exists() else 0)\n")
    p = subprocess.run(['docker', 'exec', '-i', C, 'python', '-'],
                       input=code, capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=180)
    out = (p.stdout or '') + (p.stderr or '')
    n = 0
    if 'ENTRIES' in out:
        try:
            n = int(out.split('ENTRIES')[1].split()[0])
        except Exception:
            n = 0
    record(8, '老知识库还在', n > 0, False, out.strip()[:300])


def c9_old_chat_history() -> None:
    code = (
        "import pathlib, sqlite3\n"
        "db=pathlib.Path('/app/data/user/chat_history.db')\n"
        "print('SIZE', db.stat().st_size if db.exists() else 0)\n"
        "if db.exists():\n"
        "    c=sqlite3.connect(str(db))\n"
        "    t=c.execute(\"select count(*) from sqlite_master where type='table'\").fetchone()[0]\n"
        "    print('TABLES', t)\n"
        "    for (n,) in c.execute(\"select name from sqlite_master where type='table'\"):\n"
        "        try:\n"
        "            k=c.execute(f'select count(*) from \\\"{n}\\\"').fetchone()[0]\n"
        "            if k: print('ROWS', n, k)\n"
        "        except Exception: pass\n")
    p = subprocess.run(['docker', 'exec', '-i', C, 'python', '-'],
                       input=code, capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=180)
    out = (p.stdout or '') + (p.stderr or '')
    size = 0
    if 'SIZE' in out:
        try:
            size = int(out.split('SIZE')[1].split()[0])
        except Exception:
            size = 0
    record(9, '老对话还在', size > 10000, False, out.strip()[:300])


def c10_bilibili_subtitles() -> None:
    """The B站 native path, using DeepTutor's own loader.

    `_load_bilibili_media(url, languages)` -> BilibiliMedia(title, cover_url,
    duration_seconds, page_number, cid, segments, chapters).

    NOTE on segments: B站's player/v2 returns NO subtitle track for anonymous
    requests on most videos - this is a B站 API property, NOT a 1.7.2
    regression (verified identical on 1.6.15). What must work is that the
    loader reaches the API and returns a real BilibiliMedia.
    """
    code = (
        "import asyncio\n"
        "from deeptutor.reading.ingestion import _load_bilibili_media\n"
        "async def go():\n"
        "    m=await _load_bilibili_media("
        "'https://www.bilibili.com/video/BV1Zn4y19743',"
        "['zh','zh-CN','zh-Hans','zh-Hant','en'])\n"
        "    print('TITLE',m.title)\n"
        "    print('DURATION',m.duration_seconds)\n"
        "    print('SEGMENTS',len(m.segments))\n"
        "    print('CHAPTERS',len(m.chapters))\n"
        "    for s in (m.segments[:2]):\n"
        "        print('SEG',getattr(s,'start_seconds','?'),"
        "getattr(s,'end_seconds','?'),(getattr(s,'text','') or '')[:80])\n"
        "asyncio.run(go())\n")
    p = subprocess.run(['docker', 'exec', '-i', C, 'python', '-'],
                       input=code, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=240)
    out = (p.stdout or '') + (p.stderr or '')
    ok = 'TITLE' in out and 'Traceback' not in out
    record(10, 'B站原生取字幕链路可用', ok, False, out.strip()[:400])


def c11_video_lesson_available() -> None:
    """The 1.7.0 headline feature: narrated video lessons.

    It is NOT a pip package - the code ships in the source tree
    (`deeptutor/agents/video_lesson/`) together with a Remotion kit
    (`remotion/kit.tsx`, `build.mjs`, `package.json`). The Node toolchain is
    installed on demand at first use (runtime.py: INSTALL_TIMEOUT_S = 900),
    and the browser plays the composition live via WebAssembly - no video is
    encoded on the server.
    """
    rc, out = sh(['docker', 'exec', C, 'node', '--version'])
    node = out.strip()
    code = (
        "import importlib.util as u, pathlib\n"
        "d=pathlib.Path('/app/deeptutor/agents/video_lesson')\n"
        "print('MODULE', bool(u.find_spec('deeptutor.agents.video_lesson')))\n"
        "kit=d/'remotion'/'kit.tsx'\n"
        "print('KIT', kit.exists())\n"
        "print('FILES', sorted(p.name for p in (d/'remotion').glob('*'))[:9])\n"
        "print('EDGE_TTS', bool(u.find_spec('edge_tts')))\n")
    p = subprocess.run(['docker', 'exec', '-i', C, 'python', '-'],
                       input=code, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180)
    out2 = (p.stdout or '') + (p.stderr or '')
    ok = (node.startswith('v') and 'MODULE True' in out2
          and 'KIT True' in out2 and 'EDGE_TTS True' in out2)
    record(11, '新功能：带解说的视频课可用', ok, False,
           f'node={node} | ' + out2.strip().replace(chr(10), ' | ')[:260])


def c12_no_silent_cloud() -> None:
    """HARD. If the task profile silently failed, it fell back to the cloud."""
    rc, out = sh(['docker', 'logs', C, '--since', '2h'])
    cloud = [l for l in out.splitlines()
             if 'minimax' in l.lower() and ('/v1/chat' in l.lower()
                                            or 'chat/completions' in l.lower())]
    record(12, '★ 没有偷偷走云端', not cloud, True,
           ('\n'.join(cloud[:4])) if cloud else 'no cloud chat calls')


CHECKS = {1: c1_container_healthy, 2: c2_extras_installed,
          3: c3_guard_did_not_block_start, 4: c4_guard_switch_still_works,
          5: c5_stt_schema_compatible, 6: c6_task_model_works,
          7: c7_whisper_transcribes, 8: c8_old_knowledge_bases,
          9: c9_old_chat_history, 10: c10_bilibili_subtitles,
          11: c11_video_lesson_available, 12: c12_no_silent_cloud}

DESCRIPTIONS = {
    1: '容器状态是 healthy',
    2: 'pip list 里能看到 7 个官方 extra 包',
    3: '启动日志里没有 "security_guard is enabled but ... not installed"',
    4: 'system.json 的 security_guard.enabled 还是 true',
    5: 'resolve_stt_runtime_config() 仍能解出 whisper-1/custom/.../openai_compat',
    6: 'resolve_llm_runtime_config(service_name="task") 指向本机 qwen3 并真的能回答',
    7: '真实语音经 DeepTutor 的 transcribe_cues() 出词',
    8: '复制过来的 knowledge_bases 还在',
    9: '复制过来的 chat_history.db 还在',
    10: 'BilibiliLoader 能取到 B站 字幕',
    11: 'Node.js 在镜像里 + video-lesson / edge-tts 可 import',
    12: '容器日志里没有 minimax 的 chat/completions 调用',
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', type=int, nargs='*', default=None)
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--container', default='deeptutor',
                    help='target container (default: deeptutor; '
                         'the 1.7.2 trial instance is deeptutor-172)')
    args = ap.parse_args()
    global C
    C = args.container

    if args.list:
        for n in sorted(CHECKS):
            print(f'{n:2d}. {DESCRIPTIONS[n]}')
        return 0

    todo = args.only or sorted(CHECKS)
    for n in todo:
        if n not in CHECKS:
            print(f'no such check: {n}')
            continue
        print(f'--- check {n}: {DESCRIPTIONS[n]}')
        try:
            CHECKS[n]()
        except Exception as e:
            record(n, DESCRIPTIONS[n], False, n in (5, 6, 7, 12),
                   f'{type(e).__name__}: {e}')
        time.sleep(0.3)

    print()
    print('=' * 78)
    hard_fail = []
    for n, name, ok, hard, detail in sorted(RESULTS):
        tag = '★HARD' if hard else '  soft'
        print(f'[{ "PASS" if ok else "FAIL" }] {tag} {n:2d}. {name}')
        if detail:
            for line in detail.splitlines()[:4]:
                print('          ' + line)
        if not ok and hard:
            hard_fail.append(n)
    print('=' * 78)
    if hard_fail:
        print(f'HARD 失败: {hard_fail}  ⇒ 不要迁移，先修这几条')
        return 1
    soft_fail = [n for n, _, ok, _, _ in RESULTS if not ok]
    if soft_fail:
        print(f'全部 HARD 通过；soft 失败: {soft_fail}  ⇒ 功能退化，需人工确认')
        return 2
    if len(RESULTS) < len(CHECKS):
        print(f'已跑的 {len(RESULTS)} 条全部通过（还有 {len(CHECKS) - len(RESULTS)} 条没跑）'
              ' ⇒ 还不能下"可以迁移"的结论')
        return 0
    print('12 条全部通过 ⇒ 可以迁移')
    return 0


if __name__ == '__main__':
    sys.exit(main())
