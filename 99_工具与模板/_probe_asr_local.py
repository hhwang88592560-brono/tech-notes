"""Does Ollama's own /v1/audio/transcriptions work for STT? (avoids another container)"""
import math
import struct
import subprocess
import sys
import wave
from pathlib import Path

OUT = Path(r'C:\Users\18798\Documents\_probe_tone.wav')


def make_tone(path: Path, seconds=2.0, rate=16000):
    n = int(rate * seconds)
    frames = b''.join(struct.pack('<h', int(9000 * math.sin(2 * math.pi * 300 * i / rate)))
                      for i in range(n))
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames)


make_tone(OUT)
print(f'probe wav: {OUT.stat().st_size} bytes (2s tone, no private content)\n')

for endpoint in ('http://127.0.0.1:11434/v1/audio/transcriptions',):
    for model in ('whisper', 'whisper-base', 'whisper-large-v3'):
        r = subprocess.run(
            ['curl', '-s', '-m', '90', '-X', 'POST', endpoint,
             '-F', f'file=@{OUT}', '-F', f'model={model}',
             '-F', 'response_format=verbose_json'],
            capture_output=True, text=True, encoding='utf-8', errors='replace')
        body = (r.stdout or '').strip()
        print(f'  model={model:18s} -> {body[:180]}')
    print()
OUT.unlink(missing_ok=True)
