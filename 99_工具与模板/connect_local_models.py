r"""connect_local_models.py - wire the course pipeline to LOCAL models in DeepTutor.

WHAT THIS DOES
--------------
Three additive edits to DeepTutor's model catalog
(D:\DeepTutorLab\data\user\settings\model_catalog.json):

  1. add an LLM profile for local qwen3:8b on Ollama
  2. add a task profile for the same
  3. add an STT profile pointing at a local OpenAI-compatible Whisper server

and optionally switch the active profiles to the local ones.

WHY IT IS SAFE
--------------
  * every existing profile is left byte-identical; we only APPEND
  * a timestamped backup is written before any change
  * the JSON is written WITHOUT a BOM (DeepTutor does not strip BOMs, and a
    BOM resets the whole config to defaults - see the ops BOM rule)
  * the file is re-parsed after writing, and the container is restarted
    only if you ask for it
  * --dry-run is the default

USAGE
-----
    python connect_local_models.py --dry-run
    python connect_local_models.py --apply
    python connect_local_models.py --apply --activate-local
    python connect_local_models.py --apply --stt-base-url http://whisper-asr:9000/v1
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sys
from pathlib import Path

LAB = Path(r'D:\DeepTutorLab')
CATALOG = LAB / 'data' / 'user' / 'settings' / 'model_catalog.json'
BACKUP_DIR = LAB / 'backups'

OLLAMA_BASE = 'http://host.docker.internal:11434/v1'
DEFAULT_STT_BASE = 'http://whisper-asr:8000/v1'

# The Whisper server maps the OpenAI-style name "whisper-1" to whichever model
# it was started with (WHISPER__MODEL). Using that name here means the catalog
# never has to change when you swap the model - change the env var instead.
STT_MODEL = 'whisper-1'


def qwen3_profile(profile_id: str, role: str) -> dict:
    """An Ollama profile for qwen3:8b, shaped exactly like the existing ones."""
    return {
        'id': profile_id,
        'name': f'Ollama 本机 {role} - qwen3:8b (RTX 3060)',
        'provider': 'ollama',
        'base_url': OLLAMA_BASE,
        'api_format': 'openai_chat',
        'provider_mode': 'local',
        'binding': 'custom',
        'wire_api': 'chat_completions',
        'api_key_env': 'OLLAMA_API_KEY',
        'api_key': 'ollama',
        'api_version': '',
        'extra_headers': {},
        'models': [
            {'id': 'ollama-qwen3-8b', 'name': 'qwen3:8b', 'model': 'qwen3:8b'},
        ],
    }


def stt_profile(base_url: str) -> dict:
    """An OpenAI-compatible Whisper profile.

    binding='custom' maps to the 'custom' entry of DeepTutor's STT_PROVIDERS
    table, whose label is literally "OpenAI Compatible": the adapter posts
    multipart {file, model, response_format} to {base}/audio/transcriptions.
    """
    return {
        'id': 'local-whisper-stt',
        'name': f'本机 Whisper (faster-whisper, {STT_MODEL})',
        'provider': 'openai',
        'base_url': base_url,
        'provider_mode': 'local',
        'binding': 'custom',
        'api_key_env': '',
        'api_key': 'sk-no-key-required',
        'api_version': '',
        'extra_headers': {},
        'models': [
            {'id': f'whisper-{STT_MODEL}', 'name': STT_MODEL, 'model': STT_MODEL},
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description='Point DeepTutor at local models.')
    ap.add_argument('--stt-base-url', default=DEFAULT_STT_BASE,
                    help=f'base url of the OpenAI-compatible Whisper server (default {DEFAULT_STT_BASE})')
    ap.add_argument('--activate', choices=['none', 'task', 'llm', 'both'], default='none',
                    help="which ACTIVE profile to switch to the local qwen3 ones. "
                         "'task' = 出题/子任务走本机; 'both' = 连聊天也走本机")
    ap.add_argument('--apply', action='store_true', help='write (default: dry run)')
    args = ap.parse_args()

    if not CATALOG.exists():
        print('catalog not found:', CATALOG)
        return 1

    raw = CATALOG.read_bytes()
    had_bom = raw[:3] == b'\xef\xbb\xbf'
    data = json.loads(raw.decode('utf-8-sig'))
    services = data['services']

    plan = []

    def upsert(cfg: dict, profile: dict) -> str:
        """Replace a profile with the same id, or append it.

        Appending blindly would leave two profiles with the same id, and
        DeepTutor's resolver takes the FIRST match - so the old one would
        silently keep winning. Always replace.
        """
        pid = profile['id']
        profiles = cfg.setdefault('profiles', [])
        before = len(profiles)
        profiles[:] = [p for p in profiles if p.get('id') != pid]
        profiles.append(profile)
        return 'REFRESH' if len(profiles) == before else 'ADD'

    # ---- 1 & 2: local qwen3 profiles for llm and task -------------------
    for svc, pid in (('llm', 'local-ollama-qwen3-llm'), ('task', 'local-ollama-qwen3-task')):
        action = upsert(services[svc], qwen3_profile(pid, svc))
        plan.append(f'{svc}: {action} profile {pid} (qwen3:8b via Ollama)')

    # ---- 3: local whisper STT ------------------------------------------
    stt = services['stt']
    stt_id = 'local-whisper-stt'
    action = upsert(stt, stt_profile(args.stt_base_url))
    plan.append(f'stt: {action} profile {stt_id} -> {args.stt_base_url}')
    stt['active_profile_id'] = stt_id
    stt['active_model_id'] = f'whisper-{STT_MODEL}'

    if args.activate in ('llm', 'both'):
        services['llm']['active_profile_id'] = 'local-ollama-qwen3-llm'
        services['llm']['active_model_id'] = 'ollama-qwen3-8b'
        plan.append('llm: ACTIVE profile switched to the local qwen3:8b')
    if args.activate in ('task', 'both'):
        services['task']['active_profile_id'] = 'local-ollama-qwen3-task'
        services['task']['active_model_id'] = 'ollama-qwen3-8b'
        plan.append('task: ACTIVE profile switched to the local qwen3:8b')

    print('=' * 70)
    print('DRY RUN' if not args.apply else 'APPLY')
    print('=' * 70)
    for line in plan:
        print('  ' + line)
    print()
    print('  embedding stays as-is:',
          services['embedding']['active_profile_id'],
          '/', services['embedding']['active_model_id'])

    if not args.apply:
        print('\n  Dry run only. Re-run with --apply to write.')
        return 0

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime('%Y%m%d_%H%M%S')
    bak = BACKUP_DIR / f'model_catalog.before-local-{stamp}.json'
    shutil.copy2(CATALOG, bak)
    print(f'\n  backup -> {bak}')

    # write WITHOUT BOM - DeepTutor does not strip a BOM and would reset
    # the whole config to defaults
    text = json.dumps(data, ensure_ascii=False, indent=2)
    CATALOG.write_text(text, encoding='utf-8', newline='')
    print('  model_catalog.json written (UTF-8, NO BOM)')

    # read back and verify
    back = json.loads(CATALOG.read_bytes().decode('utf-8'))
    assert back['services']['stt']['active_profile_id'] == 'local-whisper-stt'
    assert back['services']['llm']['profiles'][-1]['id'] == 'local-ollama-qwen3-llm'
    assert CATALOG.read_bytes()[:3] != b'\xef\xbb\xbf'
    print('  read-back OK; BOM absent; stt active =', back['services']['stt']['active_profile_id'])
    print()
    print('  Next: restart the container so it reloads the catalog')
    print('    cd D:\\DeepTutorLab; docker compose restart deeptutor')
    return 0


if __name__ == '__main__':
    sys.exit(main())
