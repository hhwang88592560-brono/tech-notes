"""Transcribe REAL speech through DeepTutor's own STT path.

The tone test only proved the plumbing. This synthesises actual speech with
Windows SAPI (offline, no API cost), then runs it through DeepTutor's
transcribe_cues() so we can see whether words and timestamps come back.
"""
from __future__ import annotations
import asyncio
import subprocess
import sys
from pathlib import Path

WAV = Path('/tmp/speech.wav')
TEXT = 'Git commit creates a new snapshot of the repository.'


def synth(text: str, out: str) -> bool:
    """The WAV is synthesised on the HOST (the container has no PowerShell);
    it is copied in beforehand as /tmp/speech.wav."""
    p = Path(out)
    return p.exists() and p.stat().st_size > 1000


async def main():
    if not synth(TEXT, str(WAV)):
        print('SAPI synthesis failed')
        return 1
    print(f'synthesised {WAV.stat().st_size} bytes of real speech: {TEXT!r}\n')

    from deeptutor.services.config.provider_runtime import resolve_stt_runtime_config
    from deeptutor.services.voice.adapters.openai_compat import OpenAICompatSTTAdapter
    import dataclasses, os

    cfg = resolve_stt_runtime_config()
    if os.environ.get('PROBE_STT_MODEL'):
        cfg = dataclasses.replace(cfg, model=os.environ['PROBE_STT_MODEL'])
    print('model:', cfg.model, '| base_url:', cfg.base_url, '\n')

    audio = WAV.read_bytes()
    adapter = OpenAICompatSTTAdapter()
    cues = await adapter.transcribe_cues(audio, cfg, filename='speech.wav',
                                         content_type='audio/wav')
    print(f'transcribe_cues() -> {len(cues)} cue(s)')
    for c in cues[:6]:
        # TranscriptCue fields are start_seconds / end_seconds / text / timed
        # (NOT start / end - an earlier version of this probe printed '?').
        start = getattr(c, 'start_seconds', None)
        end = getattr(c, 'end_seconds', None)
        timed = getattr(c, 'timed', None)
        print('   [%s - %s] %s%s' % (
            start, end, (getattr(c, 'text', '') or '').strip(),
            '' if timed is not False else '  (untimed)'))
    WAV.unlink(missing_ok=True)
    return 0 if cues else 1


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
