r"""finalize_whisper_small.py - finish the faster-whisper-small download and switch to it.

The host-side `curl -C -` writes straight into the HuggingFace blob path, but
the blob name still carries the `.incomplete` suffix and the snapshot
directory has no `model.bin` entry. The HF client would then start the
483 MB download all over again inside the container (140 KB/s, ~1 hour).

This script:
  1. waits for the blob to reach the exact expected size
  2. renames it off the `.incomplete` suffix
  3. verifies its sha256 equals the blob's own filename (the filename IS the hash)
  4. materialises snapshots/<rev>/model.bin
  5. sets WHISPER__MODEL in .env and restarts whisper-asr
  6. asks the server what model it is actually serving

NOTE on step 4: Git Bash's `ln -s` produces a COPY, not a symlink (verified
on this machine), so we copy the file instead. 483 MB on an 82 GB free disk.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

CACHE = Path(r'D:\DeepTutorLab\data\whisper-cache\huggingface\hub')
REPO = CACHE / 'models--Systran--faster-whisper-small'
BLOBS = REPO / 'blobs'
SNAPS = REPO / 'snapshots'
ENV = Path(r'D:\DeepTutorLab\.env')

SHA = '3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671'
# authoritative size from the HF API (x/web-interface equivalent):
#   GET https://huggingface.co/api/models/Systran/faster-whisper-small/tree/main
#   -> model.bin  size=483546902  lfs_size=483546902
EXPECT = 483_546_902
MODEL = 'Systran/faster-whisper-small'


def log(msg: str) -> None:
    print(msg, flush=True)


def wait_for_blob(timeout_s: int = 5400) -> Path:
    """Wait until the blob is fully downloaded.

    The download lands in the `.incomplete` file; the rename to the final
    name happens afterwards, here. So the wait must treat "the .incomplete
    file reached the expected size" as done - waiting for the final name
    would deadlock (it only appears after this function returns).
    """
    incomplete = BLOBS / f'{SHA}.incomplete'
    final = BLOBS / SHA
    if final.exists() and final.stat().st_size == EXPECT:
        return final
    deadline = time.time() + timeout_s
    last = -1
    while time.time() < deadline:
        if final.exists() and final.stat().st_size == EXPECT:
            return final
        size = incomplete.stat().st_size if incomplete.exists() else 0
        if size == EXPECT:
            return incomplete
        if size != last:
            log(f'  waiting... {size:,} / {EXPECT:,} bytes ({size * 100 // EXPECT}%)')
            last = size
        if size > EXPECT:
            raise SystemExit(f'blob OVERSIZED: {size} > {EXPECT}')
        time.sleep(15)
    raise SystemExit('timed out waiting for the download')


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as fh:
        while True:
            chunk = fh.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    log('=== finalizing faster-whisper-small ===')
    blob = wait_for_blob()

    incomplete = BLOBS / f'{SHA}.incomplete'
    if incomplete.exists():
        incomplete.rename(blob)
        log(f'  renamed .incomplete -> {blob.name}')

    size = blob.stat().st_size
    if size != EXPECT:
        raise SystemExit(f'size mismatch: {size} != {EXPECT}')
    log(f'  size OK: {size:,} bytes')

    log('  computing sha256 (a few seconds)...')
    digest = sha256_of(blob)
    if digest != SHA:
        raise SystemExit(f'sha256 MISMATCH\n  got      {digest}\n  expected {SHA}')
    log('  sha256 OK (matches the blob filename)')

    rev = (REPO / 'refs' / 'main').read_text(encoding='utf-8').strip()
    snap = SNAPS / rev
    target = snap / 'model.bin'
    log(f'  snapshot revision: {rev}')
    if target.exists() and target.stat().st_size == EXPECT:
        log('  snapshots/<rev>/model.bin already present')
    else:
        shutil.copy2(blob, target)
        log(f'  copied blob -> {target}')

    # --- switch the model -------------------------------------------------
    if ENV.exists():
        raw = ENV.read_bytes().decode('utf-8')
        lines = raw.splitlines()
        found = False
        for i, line in enumerate(lines):
            if line.strip().startswith('WHISPER__MODEL'):
                lines[i] = f'WHISPER__MODEL={MODEL}'
                found = True
        if not found:
            lines.append(f'WHISPER__MODEL={MODEL}')
        # .env must stay CRLF for docker-compose on Windows
        text = '\r\n'.join(lines) + '\r\n'
        ENV.write_bytes(text.encode('utf-8'))
        log(f'  .env WHISPER__MODEL = {MODEL} (CRLF preserved)')
    else:
        log(f'  WARNING: {ENV} not found')

    log('  restarting whisper-asr...')
    subprocess.run(['docker-compose', 'up', '-d', '--force-recreate', 'whisper-asr'],
                   cwd=r'D:\DeepTutorLab', check=False)

    log('  waiting for the server to come up...')
    for _ in range(60):
        r = subprocess.run(['docker', 'exec', 'whisper-asr', 'curl', '-sf',
                            'http://localhost:8000/v1/models'],
                           capture_output=True, text=True)
        if r.returncode == 0:
            log(f'  /v1/models -> {r.stdout.strip()[:300]}')
            break
        time.sleep(5)
    else:
        log('  WARNING: server did not answer /v1/models in time')
        log(subprocess.run(['docker', 'logs', 'whisper-asr', '--tail', '40'],
                           capture_output=True, text=True).stdout)

    log('=== done ===')
    return 0


if __name__ == '__main__':
    sys.exit(main())
