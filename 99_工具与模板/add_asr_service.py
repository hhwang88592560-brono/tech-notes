"""Add the whisper-asr service to D:\DeepTutorLab\docker-compose.yml.

Why a compose service and not a hand-started container:
  * `docker-compose down` would orphan a hand-started container
  * the compose file is the single source of truth for this lab
  * the model cache has to live on a mounted volume, otherwise every
    recreate re-downloads ~0.5-3 GB from HuggingFace (measured: 140 KB/s
    from this network, so large-v3 took hours)

The service joins the same `deeptutor-network` as the app, so DeepTutor
reaches it at http://whisper-asr:8000/v1 with no host port involved.
A loopback-only host port is still published for host-side testing.

Text is inserted, nothing else in the file is touched.
"""
from __future__ import annotations

import datetime as dt
import shutil
import sys
from pathlib import Path

LAB = Path(r'D:\DeepTutorLab')
COMPOSE = LAB / 'docker-compose.yml'
BACKUP = LAB / 'backups'

SERVICE = '''
  # ---------------------------------------------------------------
  # 本机语音转写（Whisper）—— 给 DeepTutor 的"阅读/视频"能力用
  #
  # 为什么单独一个容器：
  #   DeepTutor 官方镜像里没有 STT 模型。它对本地视频的流程是
  #     ffmpeg 切片 → STT 转写 → 还原时间轴
  #   官方 STT_PROVIDERS 表里只有云端厂商 + 一个 local: vllm，
  #   没有现成的 whisper 容器。faster-whisper-server 正好是
  #   OpenAI 兼容的 /v1/audio/transcriptions，支持 verbose_json
  #   返回 segments（带时间戳）—— 这正是 DeepTutor 的
  #   transcribe_cues 需要的形状。
  #
  # 为什么用 faster-whisper 而不是官方 openai-whisper-asr-webservice：
  #   前者 2.55GB（CTranslate2，不含 torch），后者 GPU 版 13.35GB。
  #
  # ⚠️ 模型下载慢：本机到 huggingface.co 实测约 140 KB/s。
  #   所以模型缓存在挂载卷里（./data/whisper-cache），
  #   换模型只要改 WHISPER__MODEL 再 docker-compose up -d，
  #   **不要**删那个卷。
  # ---------------------------------------------------------------
  whisper-asr:
    image: fedirz/faster-whisper-server:0.6.0-rc.3-cuda
    pull_policy: if_not_present
    container_name: whisper-asr
    restart: unless-stopped
    ports:
      # 只绑本机：宿主机上可以用 curl 直接测 DeepTutor 会发的那个请求
      - "127.0.0.1:${WHISPER_ASR_HOST_PORT:-9000}:8000"
    volumes:
      # ★ 模型缓存必须持久化，否则每次重建都要重新下载
      - ./data/whisper-cache:/home/ubuntu/.cache
    environment:
      # 想换模型改这一行即可（tiny / base / small / medium / large-v3）
      # 可用名： Systran/faster-whisper-tiny ... Systran/faster-whisper-large-v3
      - WHISPER__MODEL=${WHISPER__MODEL:-Systran/faster-whisper-small}
      # 3060 是 12GB，用 int8_float16 是速度/精度折中
      - WHISPER__COMPUTE_TYPE=${WHISPER__COMPUTE_TYPE:-int8_float16}
      - UVICORN_HOST=0.0.0.0
      - UVICORN_PORT=8000
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
    networks:
      - deeptutor-network

'''


def main() -> int:
    if not COMPOSE.exists():
        print('compose file not found:', COMPOSE)
        return 1
    text = COMPOSE.read_text(encoding='utf-8')
    if 'whisper-asr:' in text:
        print('  whisper-asr service already present - nothing to do')
        return 0

    marker = '\nnetworks:\n'
    idx = text.rfind(marker)
    if idx < 0:
        print('  could not find the networks: block - aborting, nothing written')
        return 1

    BACKUP.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime('%Y%m%d_%H%M%S')
    bak = BACKUP / f'docker-compose.before-whisper-{stamp}.yml'
    shutil.copy2(COMPOSE, bak)

    new = text[:idx] + '\n' + SERVICE + text[idx + 1:]
    COMPOSE.write_text(new, encoding='utf-8', newline='')
    print(f'  backup -> {bak}')
    print('  whisper-asr service inserted')
    print()
    print('  Next:')
    print('    cd D:\\DeepTutorLab')
    print('    docker-compose up -d whisper-asr')
    print('    docker-compose logs -f whisper-asr')
    return 0


if __name__ == '__main__':
    sys.exit(main())
