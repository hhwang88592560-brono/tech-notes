# 课程流水线接入 DeepTutor · 保姆级教程

> **目标**：视频 → 转写 → 出题 → 成课，**转写和出题都走本机**，
> 不花云端 token，也不出网。
>
> **本文写的是已经在你本机跑通的那条线**（2026-11-11~12 实测），
> 不是通用教程。每条命令都给了**预期输出**和**看不懂时怎么办**。

---

## 0. 现在的状态（先看这个，别重复劳动）

| 环节 | 状态 | 证据 |
|---|---|---|
| DeepTutor 容器 | ✅ 跑着，healthy | `deeptutor` Up (healthy)，**官方镜像 `ghcr.io/hkuds/deeptutor:1.7.2`**（2026-11-12 从自建的 1.6.15-guard 切过来） |
| 本机 Ollama + qwen3:8b | ✅ 装好 | RTX 3060 12GB |
| 本机 Whisper 容器 | ✅ 跑着 | `whisper-asr` Up |
| **出题走本机** | ✅ **已激活并验证** | `resolve_llm_runtime_config(service_name='task')` → `qwen3:8b @ host.docker.internal:11434/v1` |
| **转写走本机** | ✅ **已激活并验证** | `resolve_stt_runtime_config()` → `whisper-1 / custom / http://whisper-asr:8000/v1 / openai_compat` |
| **Whisper 模型** | ✅ **small**（483,546,902 字节，sha256 校验过） | 日志 `Loading model Systran/faster-whisper-small` |
| 聊天（llm） | 仍走 MiniMax API | `llm` → `MiniMax-M3.1-Flash @ api.minimaxi.com`（**故意保留**，见 §7） |
| 真实语音 → cue | ✅ **端到端验证，一字不差** | `"Git commit creates a new snapshot of the repository."` |
| 一键自检 | ✅ **11 项全过** | `python check_pipeline.py` |
| 编译闸 | ✅ | `verify.py`（16 项断言自测通过） |

**当前模型矩阵**（`data/user/settings/model_catalog.json`）：

```
llm        api-minimax-llm            / minimax-M3.1-Flash     ← 云端（聊天）
task       local-ollama-qwen3-task    / ollama-qwen3-8b       ← 本机（出题）✔
embedding  local-ollama-embedding-bge-m3 / ollama-bge-m3       ← 本机
stt        local-whisper-stt          / whisper-whisper-1      ← 本机（转写）✔
```

---

## 1. 心智模型：DeepTutor 里"谁做什么"

先把四个角色分清楚，后面所有事都靠这个：

| 角色 | DeepTutor 里的名字 | 谁来做 | 干什么 |
|---|---|---|---|
| **LLM** | `llm` | 云端 / 本机 | 聊天、对话、讲解 |
| **Task**（子任务模型） | `task` | ⭐ **本机 qwen3** | **出题**、出知识点、生成评估 |
| **Embedding** | `embedding` | 本机 bge-m3 | 把文档切块、向量化、建索引 |
| **STT** | `stt` | ⭐ **本机 Whisper** | **把音视频转成文字** |

> ⭐ **关键认知**：
> "出题"走的是 **`task`**，不是 `llm`。
> 所以把 `task` 指到本机，**出题就完全本地**了 —— 而聊天仍然可以享受云端大模型。
> **这两个开关是独立的**，这是整套方案能成立的根本原因。

**视频转写的完整链路**（DeepTutor 官方源码 `deeptutor/reading/ingestion.py`）：

```
视频文件
  ↓ ffmpeg 切片成 16kHz 单声道 mp3
  ↓ STT 转写（POST {base}/audio/transcriptions，multipart）
  ↓ _rebase_cues 还原时间轴
  ↓ 带时间戳的字幕
```

**两条报错要认识**：
- `stt_not_configured` —— **在 ffmpeg 之前就抛了** ⇒ 说明 STT 没配好，跟视频本身无关
- `media_transcription_failed` —— ffmpeg 过了但转写失败 ⇒ 音频有问题或服务器挂了

---

## 2. 准备工作：确认三件事

### 2.1 Ollama 在跑，qwen3:8b 在

```bash
curl -s http://localhost:11434/api/tags | python -c "
import sys,json
for m in json.load(sys.stdin)['models']:
    print(m['name'], round(m['size']/1e9,1),'GB')
"
```

**期望**：看到 `qwen3:8b`（约 5.2GB）。

**没有的话**：
```bash
ollama pull qwen3:8b
```

### 2.2 Ollama 允许局域网/容器访问

DeepTutor 跑在容器里，**不能**用 `localhost` 找宿主机的 Ollama，要用
`host.docker.internal`。

```bash
docker exec deeptutor curl -s http://host.docker.internal:11434/api/tags | head -c 200
```

**期望**：能返回 JSON。
**返回空/连不上** ⇒ 在 `docker-compose.yml` 里给 `deeptutor` 服务补一行：

```yaml
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

### 2.3 Whisper 容器在跑

```bash
docker ps --format '{{.Names}}\t{{.Status}}' | grep whisper
# whisper-asr   Up 12 hours

# 直接测它（DeepTutor 会发的那个请求）
curl -s http://127.0.0.1:9000/v1/models
```

**期望**：
```json
{"data":[{"id":"whisper-1",...}]}
```

> ⚠️ `whisper-1` 是**别名**，服务器会把它映射成 `WHISPER__MODEL` 里配的真实模型。
> 换模型只改环境变量，**catalog 一个字都不用动**。

---

## 3. 第一步：接入本机 qwen3（出题走本机）

### 3.1 为什么用现成脚本，而不是手改 JSON

`model_catalog.json` 有三个坑，每一个都曾经咬过我：

| 坑 | 后果 | 脚本怎么规避 |
|---|---|---|
| **同名 profile 重复** | DeepTutor 取**第一个**匹配 ⇒ 你改的那份永远不生效 | `upsert()` 先删同名再追加 |
| **JSON 带 BOM** | **整个配置重置为默认值** | 写盘用 `encoding='utf-8'`（无 BOM），写完读回来断言 |
| **写完没重启** | 容器还拿着旧配置 | 脚本提示重启命令 |

### 3.2 执行

```bash
cd "/c/Users/18798/Documents/技术蒸馏课程/99_工具与模板"

# 先看它打算做什么（默认就是 dry-run）
python connect_local_models.py --apply --activate task --stt-base-url "http://whisper-asr:8000/v1"
```

**期望输出**：

```
======================================================================
APPLY
======================================================================
  task: ADD profile local-ollama-qwen3-task (qwen3:8b via Ollama)
  llm: ADD profile local-ollama-qwen3-llm (qwen3:8b via Ollama)
  stt: ADD profile local-whisper-stt -> http://whisper-asr:8000/v1
  task: ACTIVE profile switched to the local qwen3:8b

  embedding stays as-is: local-ollama-embedding-bge-m3 / ollama-bge-m3

  backup -> D:\DeepTutorLab\backups\model_catalog.before-local-20261112_101134.json
  model_catalog.json written (UTF-8, NO BOM)
  read-back OK; BOM absent; stt active = local-whisper-stt

  Next: restart the container so it reloads the catalog
```

> 📌 **备份文件在 `D:\DeepTutorLab\backups\`，每次都会多一个带时间戳的副本。**
> 这些是回退的唯一凭据，别删。

### 3.3 重启并验证

```bash
cd /d/DeepTutorLab && docker-compose restart deeptutor
sleep 20
docker ps --format '{{.Names}}\t{{.Status}}' | grep deeptutor
```

**验证出题 profile 真的被认出来了**（在容器里解析）：

```bash
docker exec deeptutor python -c "
from deeptutor.services.config.provider_runtime import resolve_llm_runtime_config as r
for svc in ('llm','task'):
    c = r(service_name=svc)
    print(f'{svc:5s} -> model={c.model}  provider={c.provider_name}  base_url={c.base_url}')
"
```

**期望**（本机实测输出）：
```
llm   -> model=MiniMax-M3.1-Flash  provider=openai  base_url=https://api.minimaxi.com/v1
task  -> model=qwen3:8b  provider=custom  base_url=http://host.docker.internal:11434/v1
```

> ⚠️ **没有 `resolve_task_runtime_config` 这个函数** —— 我第一次写的时候就是用了它，
> 报 `ImportError`。**task 服务和 llm 服务同形，
> 用同一个解析器 `resolve_llm_runtime_config(service_name='task')`。**
> 字段名是 `provider_name`（不是 `provider`）。

> ⚠️⚠️ **一个安静的地雷：`services.task.mode`**
> `provider_runtime.py` 里 `resolve_llm_runtime_config` 有这么一段：
> ```python
> if service_name == "task" and llm_selection is None:
>     task = loaded.get("services", {}).get("task", {})
>     if task.get("mode") == "reference":
>         llm_selection = task.get("selection"); service_name = "llm"
>     elif task.get("mode") == "inherit":
>         service_name = "llm"
> ```
> **只要 `task.mode` 被写成 `"reference"` 或 `"inherit"`，task 服务就会改用 llm 的选择，
> 你在 task 里设的 active_profile_id 会被绕过 ⇒ 出题悄悄回到云端。**
> 现在你 catalog 里 `task` 的键只有 `active_model_id / active_profile_id / profiles`
> —— **没有 `mode`** ⇒ 走"task 服务自己的 active profile"这条分支 ⇒ 本机生效。
> **以后在 UI 上动 task 模型时，留意别给它写成 reference 模式。**

**不对怎么办**：
- 报 `ModuleNotFoundError` ⇒ 容器还没起好，`docker logs deeptutor | tail -30`
- base_url 是别的 ⇒ catalog 没被读到 ⇒ 检查 BOM（§3.2 的脚本已经断言了）
- task 却解析成 MiniMax ⇒ 看 `task.mode`（上面的地雷）
- 提示词很长 ⇒ qwen3 的 thinking 吃掉了预算，
  **这是已知的**：本机 quick card 里写过"答案偏短"。
  需要长答案时临时把 `llm` 也切到本机（`--activate both`），
  或让出题任务用更简短的指令。

---

## 4. 第二步：接入本机 Whisper（转写走本机）

### 4.1 Whisper 容器是怎么加进来的

用 `add_asr_service.py`（文本插入 `docker-compose.yml`，自动备份）：

```bash
python add_asr_service.py
```

它插入的服务长这样：

```yaml
  whisper-asr:
    image: fedirz/faster-whisper-server:0.6.0-rc.3-cuda
    pull_policy: if_not_present
    container_name: whisper-asr
    restart: unless-stopped
    ports: ["127.0.0.1:${WHISPER_ASR_HOST_PORT:-9000}:8000"]
    volumes: ["./data/whisper-cache:/home/ubuntu/.cache"]   # ★ 模型缓存必须持久化
    environment:
      - WHISPER__MODEL=${WHISPER__MODEL:-Systran/faster-whisper-small}
      - WHISPER__COMPUTE_TYPE=${WHISPER__COMPUTE_TYPE:-int8_float16}
      - UVICORN_HOST=0.0.0.0
      - UVICORN_PORT=8000
    deploy:
      resources:
        reservations:
          devices: [{driver: nvidia, count: all, capabilities: [gpu]}]
    networks: [deeptutor-network]
```

### 4.2 ★ 为什么选 faster-whisper 而不是官方那个

| | `fedirz/faster-whisper-server` | `onerahmet/openai-whisper-asr-webservice` (GPU) |
|---|---|---|
| 镜像大小 | **2.55GB**（CTranslate2，**不含 torch**） | 13.35GB |
| API | `/v1/audio/transcriptions`（**OpenAI 兼容**） | 同 |
| 时间戳 | `verbose_json` → `segments` ✔ | 同 |
| DeepTutor 适配 | ✅ `_canonical_voice_provider` 对未知 provider 回退到 `custom`（标签就叫"OpenAI Compatible"） | 同 |

**DeepTutor 的 STT adapter 契约**（`OpenAICompatSTTAdapter`）：

```
POST {base}/audio/transcriptions
Content-Type: multipart/form-data
  file           = 音频
  model          = whisper-1
  response_format= verbose_json      ← 要时间戳必须用这个
Authorization: Bearer <key>          ← 本地服务随便填，但别留空
```

### 4.3 ⚠️ 模型下载是这一环最大的坑

**实测速度**：本机 → huggingface.co 约 **140 KB/s**。
`faster-whisper-small` 的 `model.bin` 是 **483,546,902 字节** ⇒ **光这一个文件约 1 小时**。

**权威大小**（不要凭印象写，我第一次就写错了 1 字节）：

```bash
curl -sL "https://huggingface.co/api/models/Systran/faster-whisper-small/tree/main" \
  | python -c "
import sys,json
for f in json.load(sys.stdin):
    if f.get('type')=='file':
        lfs=f.get('lfs') or {}
        print(f\"{f['path']:22s} size={f.get('size'):>12,} lfs={lfs.get('size','-')}\")
"
```

**本次实际做法（断点续传，直接下到挂载卷里）**：

```bash
BLOB="/d/DeepTutorLab/data/whisper-cache/huggingface/hub/models--Systran--faster-whisper-small/blobs/3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671.incomplete"

# -C - 是断点续传，--retry-all-errors 应对网络抖动
curl -L -C - --max-time 5400 --retry 20 --retry-delay 5 --retry-all-errors \
     -o "$BLOB" \
     "https://huggingface.co/Systran/faster-whisper-small/resolve/main/model.bin"
```

**下载完成后**（用 `finalize_whisper_small.py` 一条命令做完，见 §4.3.1）：

```bash
# ① 校验完整性 —— 文件名本身就是 sha256
sha256sum "$BLOB"
#   必须等于 3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671

# ② 去掉 .incomplete 后缀
cd /d/DeepTutorLab/data/whisper-cache/huggingface/hub/models--Systran--faster-whisper-small/blobs/
mv 3e305921....incomplete 3e305921...

# ③ ★ 关键：在 snapshots/<rev>/ 下补一份 model.bin
#    否则 huggingface_hub 找不到本地文件，容器会重新下 1 小时
REV=$(cat ../refs/main)
cp 3e305921... "../snapshots/$REV/model.bin"
```

> ⚠️ **第 ③ 步不能省**。HF 缓存是两层：
> ```
> blobs/<sha256>                  ← 真实文件
> snapshots/<commit>/model.bin    ← 指向它的符号链接
> ```
> **只有 blobs 里的文件，容器照样会重新下载。**
> 而 **Git Bash 的 `ln -s` 在这台机器上会落成实体副本**（已实测），
> 所以这里直接 `cp` 一份（483MB，D 盘还有 82GB）。

#### 4.3.1 用现成脚本（推荐）

```bash
cd "/c/Users/18798/Documents/技术蒸馏课程/99_工具与模板"
python -u finalize_whisper_small.py
```

它会：等下满 → 改名 → **算 sha256 校验** → 补 snapshot →
改 `.env` 的 `WHISPER__MODEL` → `docker-compose up -d --force-recreate whisper-asr`
→ 探活。

> 💡 **为什么这么绕**：让容器自己去下 = 容器内 140KB/s 且**没有断点续传**，
> 断了就从头再来。宿主机 curl 有 `-C -`。
> **但更简单的选择是先用 `tiny`（已下好，~75MB）跑通全链路，
> 等网络好的时候再换 `small`。**

### 4.4 换模型

**只改 `.env` 一行，然后重启**：

```bash
# D:\DeepTutorLab\.env
WHISPER__MODEL=Systran/faster-whisper-small
WHISPER__COMPUTE_TYPE=int8_float16
WHISPER_ASR_HOST_PORT=9000
```

```bash
cd /d/DeepTutorLab && docker-compose up -d whisper-asr
```

> ⚠️ **`.env` 的编码规则**（踩过）：
> - `.env` 用 **CRLF**（Windows + docker-compose）
> - `model_catalog.json` 用 **UTF-8 无 BOM**
> - **JSON 带 BOM ⇒ 整个配置重置为默认值**

### 4.5 验证：走 DeepTutor 自己的代码路径

**不要**用 curl 手搓请求糊弄过去 —— 要用 **DeepTutor 自己的 adapter**，
它解析的正是 DeepTutor 会用的那份配置。

```bash
# 把探针脚本拷进容器
docker cp _probe_deeptutor_stt.py deeptutor:/tmp/probe.py
docker exec deeptutor python /tmp/probe.py
```

**期望输出**：
```
resolved STT config:
   model    = whisper-1
   provider = custom
   base_url = http://whisper-asr:8000/v1
   adapter  = openai_compat
   style    = multipart

transcribe()      -> OK, returned '...'
transcribe_cues() -> OK, 1 cue(s)
   cue: start=0.0 end=5.2 text='...'
```

> ⚠️ **Git Bash 会把容器路径改写**：`docker exec deeptutor python /tmp/probe.py`
> 会被改成 `/app/C:/msys64/tmp/probe.py`。
> **要么用 `MSYS_NO_PATHCONV=1`，要么像下面这样从 stdin 灌进去**（最省事）：
> ```bash
> docker exec -i deeptutor python - < _probe_speech.py
> ```

> ⚠️ **`/v1/models` 不能用来判断"加载了哪个模型"** ——
> faster-whisper-server 的这个接口是**实时去 huggingface.co 查**然后把
> 全部 ctranslate2 语音模型列出来（日志里能看到 `GET https://huggingface.co/api/models?filter=ctranslate2...`）。
> **它返回的是"HF 上有什么"，不是"本容器加载了什么"。**
> 唯一可信的判据是**日志**：
> ```bash
> docker logs whisper-asr --tail 200 | grep "Loading model"
> # → Loading model Systran/faster-whisper-small
> ```

### 4.6 终极验证：真语音进去，真文字出来

**纯音调测试只能证明管道通，证明不了能识别词。**
所以再跑一次真实语音（Windows SAPI 离线合成，不用花钱）：

```bash
# ① 在宿主机合成真实语音（容器里没有 PowerShell）
powershell -NoProfile -Command "
Add-Type -AssemblyName System.Speech
\$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
\$s.SetOutputToWaveFile('C:\Users\18798\Documents\speech.wav')
\$s.Speak('Git commit creates a new snapshot of the repository.')
\$s.Dispose()
"

# ② 灌进容器（用 stdin，避开 Git Bash 的路径改写）
cd /c/Users/18798/Documents
docker exec -i deeptutor sh -c 'cat > /tmp/speech.wav' < speech.wav

# ③ 跑探针
cd "/c/Users/18798/Documents/技术蒸馏课程/99_工具与模板"
docker exec -i deeptutor python - < _probe_speech.py
```

**本次实测结果**（**small** 模型，2026-11-12）：

```
synthesised 204146 bytes of real speech: 'Git commit creates a new snapshot of the repository.'

model: whisper-1 | base_url: http://whisper-asr:8000/v1

transcribe_cues() -> 1 cue(s)
   [0.0 - 4.0] Git commit creates a new snapshot of the repository.
```

> ✅ **一字不差。** 对照 **tiny** 模型的结果：
> `[0.0 - 4.6] Get commit creates a news snapshot of the repository.`
> —— `Get` vs `Git`、`news` vs `new`。**同一个管道，模型换大就完全正确了。**
>
> 📌 **cue 的字段名是 `start_seconds` / `end_seconds` / `text` / `timed`**
> （类名 `TranscriptCue`），**不是 `start` / `end`**。
> 探针脚本早期用 `getattr(c, 'start', '?')` 所以打出来全是 `?` —— 已修。

**判定标准**：文字**大致对**就算管道通了（课程字幕仍要人工校对），
但**一个词都不差**说明模型和接线都没问题。

---

## 5. 第三步：让它接进课程流水线

### 5.1 整体链路

```
     视频源
        ├── B站/YouTube ──► DeepTutor 原生字幕（零下载，秒级）★★
        └── 本地/百度网盘 ──► ffmpeg → whisper-asr → 带时间轴字幕
                                    ▲
                                    └─ 本机 RTX 3060
        ↓
   DeepTutor 知识库（embedding 走本机 bge-m3）
        ↓
   出题 / 掌握路径 ──────────► 本机 qwen3:8b
        ↓
   课程五件套（00 / 10 / 20 / 30 / 99）
        ↓
   verify.py 编译闸 ──► 过了才进正式课程
```

### 5.2 ★★ B站那条是 DeepTutor 的原生能力（零配置）

源码 `deeptutor/reading/ingestion.py` 里的 `BilibiliLoader`：

- 用官方接口 `x/web-interface/view`（拿标题、简介、章节）
- 用 `x/player/v2` 拿 `subtitle.subtitles[]`（**含 AI 字幕**）
- 拿 `view_points`（章节/要点）
- **不下载视频**（只下字幕）

⇒ **你有 B站视频直接丢链接进 DeepTutor 的"阅读/观看"，立刻就有字幕。**
这条比本地转写快几个数量级，**优先用它**。

### 5.3 本地视频（百度网盘下载的）走 ffmpeg 路线

DeepTutor 自己做：ffmpeg → 16kHz 单声道 mp3 分片 → STT → `_rebase_cues`。
你只需要保证：

1. ffmpeg 在容器里 ✔（**1.7.2 官方镜像自带**，不用额外装）
2. STT 已配置 ✔（§4）
3. 视频格式是常见容器（mp4/mkv/mov）

**手工预转写也行**（长视频更稳，省掉反复重试）：

```bash
# 宿主机先转成单声道 16kHz mp3
ffmpeg -i 原视频.mp4 -ac 1 -ar 16000 -vn 音频.mp3
```

### 5.4 知识库怎么建

- **引擎**：默认 llamaindex。LightRAG/GraphRAG 需要 `lightrag-hku`
  （**1.7.2 起是官方 extra `rag-lightrag`，已在 `DEEPTUTOR_EXTRAS` 里**）。
  1.7.2 起是官方 extra `rag-lightrag`。
- **embedding**：本机 `ollama-bge-m3`（已激活）。
- 建库之后**别忘了两件事**：
  1. 1.7.2 换 embedding 模型要**重新索引**（官方明确说）
  2. 索引构建可以断点续跑（1.7.0 修复的）

---

## 6. 第四步：出题 → 成课 → 编译闸

### 6.1 让模型出题（走本机）

在 DeepTutor 界面对着知识库点"出题"/"生成练习"。
**此时 `task` profile = 本机 qwen3:8b ⇒ 完全本地。**

怎么确认真的走了本机而不是偷偷回云端：

```bash
# 容器日志里不应该出现云端调用
docker logs deeptutor --since 5m | grep -i 'minimax\|api.minimaxi'
```

**没有输出 ⇒ 没走云端 ✔**

### 6.2 蒸馏成课程五件套

```bash
cd "/c/Users/18798/Documents/技术蒸馏课程"

# ① 看额度（选站）
python 99_工具与模板/quota.py

# ② 蒸馏（自动选站 + 故障转移）
python 99_工具与模板/dispatch.py --task 01_C语言核心/任务_02_xxx.md

# ③ 过编译闸
python 99_工具与模板/verify.py 01_C语言核心/任务_02_xxx.out.md
```

`dispatch.py` 做的事：按 (站, 模型) 组合依次试，
遇到 `402 / 429 / 503 / 断流` 就换下一个，
最后写下 `<任务>.out.md` 和 `<任务>.meta.json`（记录用了哪个站、哪个模型、试了几次）。

### 6.3 编译闸在查什么（`verify.py`）

| 检查 | 为什么 |
|---|---|
| 每个 C 代码块 `gcc -std=c11 -Wall -Wextra` 编译 | AI 写的代码经常**编译不过** |
| 占位符（`TODO` / `...` / "省略"） | AI 最爱留坑 |
| 轮询循环里的变量**必须 `volatile`** | 嵌入式第一大坑（编译器会把寄存器变量缓存进寄存器） |

> ⭐ **这个闸是整条流水线里最值钱的东西**：
> 它把"AI 写的课看起来对"变成"AI 写的课**编译得过**"。

---

## 7. 一个刻意的设计决定：聊天仍然走云端

```bash
# 不要顺手执行这个：
python connect_local_models.py --apply --activate both   # ← 会把 llm 也切到本机
```

**为什么**：

| | 云端 llm | 本机 qwen3:8b |
|---|---|---|
| 讲解质量 | 好 | 一般（8B 模型的短板） |
| 速度 | 快 | 慢（thinking 吃 token） |
| 成本 | 花 token | 免费 |
| 出题质量 | 好 | **够用**（题是结构化的） |

⇒ **该省的地方省（出题、转写、embedding —— 都是"批量、结构化"的工作），
不该省的地方不省（聊天讲解 —— 是"要质量"的工作）。**

**只有在你确定要离线、或要压成本**时才 `--activate both`。

---

## 8. 故障排查速查表

| 症状 | 最可能的原因 | 怎么查 | 怎么修 |
|---|---|---|---|
| `stt_not_configured` | STT profile 没被认出来 | `docker exec deeptutor python -c "from deeptutor.services.config.provider_runtime import resolve_stt_runtime_config as r; print(r())"` | 重跑 `connect_local_models.py --apply`；查 BOM |
| `media_transcription_failed` | 音频坏了 / whisper 挂了 | `docker logs whisper-asr --tail 30` | 重启 `docker-compose restart whisper-asr` |
| 转写结果全是乱码/空 | 模型没下全（**snapshots 里缺 model.bin**） | `ls -l /d/DeepTutorLab/data/whisper-cache/huggingface/hub/models--Systran--faster-whisper-*/snapshots/*/` | 跑 `finalize_whisper_small.py`（它会补齐 + 校验 sha256） |
| 转写文字错很多 | **模型太小** | `docker logs whisper-asr --tail 200 \| grep "Loading model"` | 换 `small`（本机实测：`tiny` 把 "Git" 听成 "Get"，`small` 一字不差） |
| 容器重启后又在重新下模型 | 只补了 `blobs/`，没补 `snapshots/<rev>/model.bin` | 看 `docker logs whisper-asr` 里有没有下载进度 | `cp blobs/<sha> snapshots/<rev>/model.bin` |
| `/v1/models` 显示的不是你配的模型 | **这个接口是实时查 HF 的**，不代表容器加载了什么 | `docker logs whisper-asr \| grep "Loading model"` | 以日志为准 |
| **出题悄悄走了云端** | `services.task.mode` 被写成 `reference`/`inherit` | `python -c "import json;print(json.load(open('/d/DeepTutorLab/data/user/settings/model_catalog.json'))['services']['task'].get('mode'))"` | 删掉 `mode` 键（不设就等于用 task 自己的 active profile） |
| 出题报错 / 答案偏短 | qwen3 thinking 吃预算 | `docker logs deeptutor --since 2m \| grep -i ollama` | 换 `--activate both`；或缩短指令 |
| `ImportError: resolve_task_runtime_config` | **没这个函数** | —— | 用 `resolve_llm_runtime_config(service_name='task')` |
| Ollama 连不上 | 容器里 `localhost` 指向自己 | `docker exec deeptutor curl -s http://host.docker.internal:11434/api/tags` | compose 里加 `extra_hosts: host.docker.internal:host-gateway` |
| `python: can't open file '/app/C:/msys64/tmp/...'` | **Git Bash 改写了容器路径** | —— | `MSYS_NO_PATHCONV=1`，或用 `docker exec -i ... python - < 脚本` |
| **模型配置突然全没了** | **JSON 带 BOM** | `head -c 3 /d/DeepTutorLab/data/user/settings/model_catalog.json \| xxd` | 用 `connect_local_models.py` 重写（它保证无 BOM） |
| 容器起不来 | ① **turn_coordination 连不上 redis**（1.7.x 新增硬依赖）；② extras 装不上 | `docker logs deeptutor --tail 50 \| grep -i coordination`；`docker logs deeptutor --tail 50 \| grep Successfully installed` | ① 查 `integrations.json` 的 `redis_url` 是否等于 redis 的 `container_name`；② 重启容器（extras 是运行时装的） |
| 改了配置没生效 | 没重启 | —— | `docker-compose restart deeptutor` |

---

## 9. 一键自检脚本

已写好并放在同目录：

```bash
cd "/c/Users/18798/Documents/技术蒸馏课程/99_工具与模板"
python check_pipeline.py
```

**实测输出（11 项全过）**：

```
[OK  ] DeepTutor 容器在跑
[OK  ] Whisper 容器在跑
[OK  ] Ollama 从容器可达 (host.docker.internal:11434)
[OK  ] Whisper 从容器可达 (whisper-asr:8000)
[OK  ] Whisper 容器 WHISPER__MODEL 已设置
       WHISPER__MODEL=Systran/faster-whisper-small
[OK  ] ★ STT 指向本机 Whisper
       whisper-1 custom http://whisper-asr:8000/v1 openai_compat
[OK  ] ★ 出题(task)指向本机 Ollama qwen3
       qwen3:8b custom http://host.docker.internal:11434/v1
[OK  ] 聊天(llm)仍走云端 MiniMax（刻意保留）
       MiniMax-M3.1-Flash https://api.minimaxi.com/v1
[OK  ] model_catalog.json 无 BOM (带 BOM 会重置全部配置)
       clean
[OK  ] ★ 最近 30 分钟出题/转写没有走云端
       no cloud chat calls
[OK  ] 数据盘剩余空间可读

=> 全部通过 (11 项)
```

> 💡 **"没有偷偷走云端"这一项要看日志才准** ——
> 容器日志里出现 `/v1/chat` + `minimax` 才算走云端。
> 只看 UI 是看不出来的：**配置错了它会默默用云端，界面一切正常。**

**改动任何东西之后都跑一次这个脚本。**

---

## 10. 升级 DeepTutor 吗？

**结论：不卸载重下，也别原地升级 —— 并行起一个 1.7.2 试用实例。**
完整的证据、风险、验收清单（12 条）、迁移步骤和回退办法在：

> **`技术蒸馏课程\99_工具与模板\DeepTutor升级决策_1.7.2评估.md`**

一句话理由：**上游 1.7.2 已经把 guard / lightrag / pymupdf4llm 全变成官方 extra
（版本 pin 和你手写的一模一样），你自建镜像层的存在理由消失了**，
而且 **Node.js 22 烘进了镜像**，1.7.0 的"带解说视频课"开箱可用。
**但 1.7.x 动了模型目录 schema，正好压在你刚接好的本地模型接线上** ——
所以先在副本上验，再迁。

---

## 11. 相关

- 升级决策：`DeepTutor升级决策_1.7.2评估.md`
- DeepTutor 现状与部署：`DeepTutor现状与部署指南.md`
- 视频课程蒸馏（各种源怎么进）：`视频课程蒸馏教程.md`
- 中转管理与调度：`中转管理与AI调度指南.md`
- 学习路线（爬爬虾）：`爬爬虾学习路线_任务与时间分配.md`
- 综合能力：`综合能力进步指南.md`
