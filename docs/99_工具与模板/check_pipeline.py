#!/usr/bin/env python3
"""课程流水线一键自检 —— 全部检查都在容器内执行。

用法:
    python check_pipeline.py

返回码: 0 = 全过, 1 = 有失败项。
"""
from __future__ import annotations

import subprocess
import sys

# Windows consoles default to GBK; Chinese labels would come out as mojibake.
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

COMPOSE_DIR = r'D:\DeepTutorLab'
DEEPTUTOR = 'deeptutor'
WHISPER = 'whisper-asr'


def run(cmd: list[str]) -> tuple[int, str]:
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8',
                       errors='replace')
    return r.returncode, ((r.stdout or '') + (r.stderr or '')).strip()


def in_deeptutor(code: str) -> tuple[int, str]:
    return run(['docker', 'exec', DEEPTUTOR, 'python', '-c', code])


def check(name: str, ok: bool, detail: str = '') -> bool:
    print(f"[{'OK  ' if ok else 'FAIL'}] {name}")
    if detail:
        for line in detail.splitlines()[:6]:
            print('        ' + line)
    return ok


def main() -> int:
    results: list[bool] = []

    # 1. 容器在跑 -----------------------------------------------------
    rc, out = run(['docker', 'ps', '--format', '{{.Names}} {{.Status}}'])
    lines = out.splitlines()
    results.append(check('DeepTutor 容器在跑',
                         rc == 0 and any(l.startswith(DEEPTUTOR + ' ') for l in lines),
                         '\n'.join(l for l in lines if DEEPTUTOR in l or WHISPER in l)))

    # 2. Whisper 容器在跑 ---------------------------------------------
    results.append(check('Whisper 容器在跑',
                         any(l.startswith(WHISPER + ' ') for l in lines),
                         '\n'.join(l for l in lines if WHISPER in l)))

    # 3. Ollama 从容器里可达 ------------------------------------------
    rc, out = run(['docker', 'exec', DEEPTUTOR, 'curl', '-sf',
                   'http://host.docker.internal:11434/api/tags'])
    results.append(check('Ollama 从容器可达 (host.docker.internal:11434)',
                         rc == 0, out[:200] if rc != 0 else out[:120]))

    # 4. Whisper 从容器里可达 -----------------------------------------
    # NB: /v1/models on faster-whisper-server queries huggingface.co LIVE and
    # lists every ctranslate2 ASR model on the hub - it does NOT report which
    # model this container loaded. The env var is the honest source.
    rc, out = run(['docker', 'exec', DEEPTUTOR, 'curl', '-sf',
                   'http://whisper-asr:8000/v1/models'])
    results.append(check('Whisper 从容器可达 (whisper-asr:8000)',
                         rc == 0, out[:200] if rc != 0 else out[:200]))

    # 4b. Whisper 实际加载的是哪个模型 ---------------------------------
    rc, out = run(['docker', 'exec', WHISPER, 'env'])
    model_line = next((l for l in out.splitlines()
                       if l.startswith('WHISPER__MODEL=')), '')
    results.append(check('Whisper 容器 WHISPER__MODEL 已设置',
                         bool(model_line), model_line or out[:200]))

    # 5. ★ STT 配置解析 ------------------------------------------------
    rc, out = in_deeptutor(
        "from deeptutor.services.config.provider_runtime import "
        "resolve_stt_runtime_config as r; c=r(); "
        "print(c.model, c.provider_name, c.base_url, c.adapter)")
    want = ('whisper-1', 'custom', 'http://whisper-asr:8000/v1', 'openai_compat')
    stt_ok = rc == 0 and all(w in out for w in want)
    results.append(check('★ STT 指向本机 Whisper', stt_ok, out[:300]))

    # 6. ★ task(出题) 配置解析 ----------------------------------------
    # 注意：provider_runtime 里**没有** resolve_task_runtime_config。
    # task 服务和 llm 服务同形，用同一个解析器 + service_name='task'。
    rc, out = in_deeptutor(
        "from deeptutor.services.config.provider_runtime import "
        "resolve_llm_runtime_config as r; c=r(service_name='task'); "
        "print(c.model, c.provider_name, c.base_url)")
    task_ok = rc == 0 and 'qwen3' in out and '11434' in out
    results.append(check('★ 出题(task)指向本机 Ollama qwen3', task_ok, out[:300]))

    # 6b. llm 应当仍然留在云端（刻意保留）----------------------------
    rc, out = in_deeptutor(
        "from deeptutor.services.config.provider_runtime import "
        "resolve_llm_runtime_config as r; c=r(service_name='llm'); "
        "print(c.model, c.base_url)")
    results.append(check('聊天(llm)仍走云端 MiniMax（刻意保留）',
                         rc == 0 and 'minimax' in out.lower(), out[:200]))

    # 7. ★ BOM 检查 ----------------------------------------------------
    rc, out = in_deeptutor(
        "b=open('/app/data/user/settings/model_catalog.json','rb').read(3);"
        "print('BOM' if b==b'\\xef\\xbb\\xbf' else 'clean')")
    results.append(check('model_catalog.json 无 BOM (带 BOM 会重置全部配置)',
                         'clean' in out, out[:120]))

    # 8. ★ 没有偷偷走云端 ----------------------------------------------
    rc, out = run(['docker', 'logs', DEEPTUTOR, '--since', '30m'])
    cloud = [l for l in out.splitlines()
             if 'minimax' in l.lower() and '/v1/chat' in l.lower()]
    results.append(check('★ 最近 30 分钟出题/转写没有走云端',
                         len(cloud) == 0,
                         '\n'.join(cloud[:5]) if cloud else 'no cloud chat calls'))

    # 9. 磁盘 -----------------------------------------------------------
    rc, out = run(['docker', 'exec', DEEPTUTOR, 'python', '-c',
                   "import shutil;print(shutil.disk_usage('/app/data').free)"])
    results.append(check('数据盘剩余空间可读', rc == 0, out[:120]))

    print()
    ok = all(results)
    print(f"=> {'全部通过 (' + str(len(results)) + ' 项)' if ok else '有失败项，见上'}")

    if not ok:
        print()
        print('排查表见: 技术蒸馏课程\\99_工具与模板\\课程流水线接入DeepTutor_保姆级.md §8')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
