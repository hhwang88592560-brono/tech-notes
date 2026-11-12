"""Drive DeepTutor's OWN STT code path against the local Whisper server.

This is the real integration test: it uses DeepTutor's own
`services/voice/adapters/openai_compat.py` transcribe/transcribe_cues,
with the config it resolves from model_catalog.json - not a hand-rolled
curl. If this passes, DeepTutor's video ingestion can transcribe locally.

Run inside the deeptutor container.
"""
from __future__ import annotations
import asyncio
import math
import struct
import wave
from pathlib import Path

from deeptutor.services.config.provider_runtime import resolve_stt_runtime_config
from deeptutor.services.voice.adapters.openai_compat import OpenAICompatSTTAdapter


def make_tone(path: Path, seconds=2.0, rate=16000):
    n = int(rate * seconds)
    frames = b''.join(struct.pack('<h', int(9000 * math.sin(2 * math.pi * 300 * i / rate)))
                      for i in range(n))
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames)


async def main():
    cfg = resolve_stt_runtime_config()
    print('resolved STT config:')
    print('   model    =', cfg.model)
    print('   provider =', cfg.provider_name)
    print('   base_url =', cfg.base_url)
    print('   adapter  =', cfg.adapter)
    print('   style    =', cfg.request_style)
    print()

    wav = Path('/tmp/tonetest.wav')
    make_tone(wav)
    audio = wav.read_bytes()
    adapter = OpenAICompatSTTAdapter()

    # allow the model field to be overridden for the test (the server picks
    # the model per request; whisper-1 maps to its configured default)
    import os
    if os.environ.get('PROBE_STT_MODEL'):
        import dataclasses
        cfg = dataclasses.replace(cfg, model=os.environ['PROBE_STT_MODEL'])

    # 1) plain transcription
    try:
        text = await adapter.transcribe(audio, cfg, filename='tonetest.wav',
                                        content_type='audio/wav')
        print('transcribe()      -> OK, returned %r' % (text[:60],))
    except Exception as e:
        print('transcribe()      -> FAILED:', type(e).__name__, e)
        return 1

    # 2) timed cues (what video ingestion actually uses)
    try:
        cues = await adapter.transcribe_cues(audio, cfg, filename='tonetest.wav',
                                             content_type='audio/wav')
        print('transcribe_cues() -> OK, %d cue(s)' % len(cues))
        for c in cues[:3]:
            print('   cue: start=%s end=%s text=%r' %
                  (getattr(c, 'start', '?'), getattr(c, 'end', '?'),
                   (getattr(c, 'text', '') or '')[:50]))
    except Exception as e:
        print('transcribe_cues() -> FAILED:', type(e).__name__, e)
        return 1

    wav.unlink(missing_ok=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
