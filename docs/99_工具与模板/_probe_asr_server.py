"""Verify the local Whisper server answers exactly the way DeepTutor will call it.

DeepTutor sends (from services/voice/adapters/openai_compat.py):
    POST {base}/audio/transcriptions
    multipart: file=<audio>, model=<name>, response_format=verbose_json
and reads back per-utterance `segments` for the timestamps.

This reproduces that request verbatim. The audio is a generated tone (no
private content); a tone has no speech, so an empty transcript is the
CORRECT result - what matters is that the endpoint accepts the request,
returns 200, and returns the expected JSON shape.
"""
import json
import math
import struct
import subprocess
import sys
import wave
from pathlib import Path

WAV = Path(r'C:\Users\18798\Documents\_probe_tone.wav')
URL = 'http://127.0.0.1:9000/v1/audio/transcriptions'


def make_tone(path, seconds=2.0, rate=16000):
    n = int(rate * seconds)
    frames = b''.join(struct.pack('<h', int(9000 * math.sin(2 * math.pi * 300 * i / rate)))
                      for i in range(n))
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames)


make_tone(WAV)
print(f'probe wav: {WAV.stat().st_size} bytes (2s 300Hz tone, no speech)\n')

r = subprocess.run(
    ['curl', '-s', '-m', '900', '-w', '\n__HTTP__%{http_code}', '-X', 'POST', URL,
     '-F', f'file=@{WAV}', '-F', 'model=Systran/faster-whisper-tiny',
     '-F', 'response_format=verbose_json'],
    capture_output=True, text=True, encoding='utf-8', errors='replace')

out = (r.stdout or '')
code = out.rsplit('__HTTP__', 1)[-1].strip() if '__HTTP__' in out else '?'
body = out.rsplit('__HTTP__', 1)[0].strip() if '__HTTP__' in out else out
print(f'HTTP {code}')
try:
    j = json.loads(body)
    print('  keys        :', sorted(j.keys()))
    segs = j.get('segments')
    print('  segments    :', type(segs).__name__, len(segs) if isinstance(segs, list) else '-')
    if isinstance(segs, list) and segs:
        print('  segment[0]  :', json.dumps(segs[0], ensure_ascii=False)[:200])
    print('  text        :', repr(j.get('text'))[:120])
    print('  language    :', j.get('language'))
    ok = isinstance(segs, list)
    print('\n  =>', 'PASS: returns a segments list (DeepTutor can build timed cues)'
          if ok else 'FAIL: no segments list')
except Exception as e:
    print('  body:', body[:400])
    print('\n  => FAIL: not JSON:', e)

WAV.unlink(missing_ok=True)
