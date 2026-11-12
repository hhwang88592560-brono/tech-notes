# DeepTutor 要不要升级？—— 1.7.2 评估与决策

**日期**：2026-11-12
**本机现状**：✅ **已升级到 `ghcr.io/hkuds/deeptutor:1.7.2`（官方镜像）**，运行中，健康。
**上游最新版**：`v1.7.2`（2026-11-06）。
**回退资产**：`backups/data-before-172-20261112_113932/` + `backups/docker-compose.before-172-*.yml`
+ `Dockerfile.guard`（配方在文件头部，见 §5.2）。
⚠️ 预构建镜像已删，回退需重建（约 40 分钟）。

---

## 0. 一句话结论

> **不卸载重下。也不原地升级。**
> **维持 1.6.15-guard 跑着，另外并行起一个 1.7.2 的试用实例，用验收清单决定要不要迁。**

> ### ✅ 2026-11-12 更新：**试用已跑完，12/12 全过 ⇒ 可以迁移**
>
> 并行实例 `deeptutor-172`（端口 3792，独立 network / redis / 数据副本）已起来并通过全部验收。
> **生产实例全程未被触碰**（镜像、端口、401 行为、catalog mtime 全部不变）。
> 详见 **§4.5 试用实测结果**。迁移步骤见 **§5**。

三个选项的裁决：

| 选项 | 裁决 | 理由 |
|---|---|---|
| **卸载重下**（删干净装新版） | ❌ **明确反对** | 丢弃已验证的 guard 层与全部配置；官方明确警告"同一事务里装 `deeptutor[full]` 可能删掉 core 共享文件"；而上游说"运行时数据原地保留、无需手动迁移"——**换句话说，本来就不需要卸载** |
| **原地升级**（改 compose 的 image 就重启） | ⏸ **等切流窗口** | 验收已全过，但**切生产要停机换 compose**，属于"替换一个正在用的系统" ⇒ 留给你决定什么时候做 |
| **并行试用**（新端口 + 数据副本） | ✅ **已完成，12/12 过** | 82GB 空闲盘足够；上游说数据原地保留 ⇒ 迁移成本低；先在副本上跑验收清单，通过了再切 |

---

## 1. 为什么"卸载重下"是错的

官方 1.7.2 发布说明原文（三个硬约束）：

1. **"先停应用、备份 runtime home，再安装 `deeptutor[full]==1.7.2`，保持同一个 `DEEPTUTOR_HOME`"**
2. **"从 1.6.15 或更早升上来，必须先 `pip uninstall deeptutor-cli`"**
   —— 官方原因：**"在同一事务里重装兼容包可能移除新 core 需要的共享文件"**
3. **"运行时信息在同一个 `DEEPTUTOR_HOME` 下原地保留；包的变化与用户数据是分开的"**

**第 3 条是关键**：官方设计就是**"换包不动数据"**。
所以"卸载重下"这个动作**不但没必要，还额外承担第 2 条的删文件风险**。

> 你现在的 Docker 部署里，runtime home 就是 `./data`（`- ./data:/app/data`）。
> 换镜像 = 换包，数据不动。**这就是"升级"的全部含义。**

---

## 2. 1.7.x 到底改了什么（架构级，不是小版本）

我把上游 v1.7.2 的 `Dockerfile` 和 `pyproject.toml` 拉下来逐行看了。**这不是补丁级更新**：

### 2.1 进程模型变了：PID 1 从 uvicorn 变成 supervisord

```dockerfile
# v1.7.2 Dockerfile，Stage 3
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
...
RUN cat > /etc/supervisor/conf.d/programs.conf <<'EOF'
[program:backend]
command=/bin/bash /app/start-backend.sh
user=deeptutor          # ← 后端以 uid 1000 跑
[program:frontend]
command=/bin/bash /app/start-frontend.sh
user=deeptutor
EOF
...
exec /usr/bin/supervisord -c /etc/supervisor/supervisord.conf   # ← PID 1
```

**影响**：你现在 `docker exec deeptutor curl http://localhost:8001/health/ready` 这种
探活方式仍然有效（supervisor 管的 backend 还在 8001），但
**"容器挂了"和"某个子进程挂了"的区别变了**，排障姿势要跟着改。

### 2.2 Node.js 22.23.4 直接烘进镜像 ★ 这是升级的最大收益

```dockerfile
FROM node:22.23.4-slim AS node-runtime
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node-runtime /usr/local/lib/node_modules /usr/local/lib/node_modules
```

1.7.0 的头号新功能 **"Narrated Video Lesson"（带解说的视频课）** 在官方文档里明确要求
**Node.js 22+ 和 npm**；在 1.7.2 的 Docker 镜像里**这个前提已经满足**。

> ⭐ 对你尤其重要：你的课程流水线核心就是**视频课**。
> "浏览器内渲染课程 + Edge TTS 朗读 + WebAssembly 里跑生成的代码" ——
> 1.6.15 做不了，1.7.2 开箱可用。

### 2.3 ffmpeg / LibreOffice / 中文字体也烘进去了

```dockerfile
RUN apt-get install -y --no-install-recommends \
    curl ca-certificates bash git supervisor \
    libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 \
    ffmpeg \                                   # ← 官方镜像自带了
    libreoffice-writer libreoffice-calc libreoffice-impress \
    fonts-noto-cjk fonts-liberation
```

⇒ **你 `Dockerfile.guard` 里那段 `apt-get install ffmpeg` 从 1.7.2 起变成冗余**。

### 2.4 ★ 你那层自建镜像的**存在理由已经消失**

`Dockerfile.guard` 当初存在的唯一原因是：
**1.6.15 官方镜像装不了 guard / lightrag / pymupdf4llm**。
我查了 v1.7.2 的 `pyproject.toml`，**这四个全部变成了官方 extra，
而且版本号和我们当初手写的 pin 一模一样**：

| 我们手写的（1.6.15 时期） | 1.7.2 官方 extra | 变化 |
|---|---|---|
| `fastapi-guard>=8.1.1,<9.0.0` | `guard = ["fastapi-guard>=8.1.1,<9.0.0"]` | **完全相同** |
| `lightrag-hku==1.5.7` | `rag-lightrag = ["lightrag-hku==1.5.7"]` | **完全相同** |
| `pymupdf4llm>=1.28.2,<2.0` | `parse-pymupdf4llm = ["deeptutor-parser-pymupdf4llm=={version}"]` | 变成正式子包，**`<2.0` 的坑被官方处理了** |
| `-r /app/requirements/partners.txt` | `partners = ["deeptutor-partners=={version}"]` | 变成正式子包 |
| `-r /app/requirements/video-learning.txt` | `video-learning = ["deeptutor-reading=={version}"]` | 变成正式子包 |

**而且运行时安装路径是通的**：`scripts/install_extras.py` 在 v1.7.2 仍存在，
入口点仍调用它：

```dockerfile
if [ -n "${DEEPTUTOR_EXTRAS:-}" ]; then
    python /app/scripts/install_extras.py "${DEEPTUTOR_EXTRAS}" || true
fi
```

而且它现在会从 `pyproject.toml` 的 `[tool.deeptutor.optional-dependencies]` 读清单
（`build_metadata.source_optional_dependencies`），
镜像里 `pyproject.toml` / `build_metadata.py` / `scripts/` **都被 COPY 进去了** ⇒ 可用。

**最要紧的一点**：这个安装步骤发生在 `exec supervisord` **之前**，
此时 PID 1 还是 root ⇒ **pip 写的是真正的 site-packages**
（这正是我们 `Dockerfile.guard` 里反复强调的"必须在构建期以 root 装"那个坑，
1.7.2 用运行时 root 阶段绕开了它）。

⇒ **1.7.2 上你可以直接删掉 `Dockerfile.guard`，改一行 compose：**

```yaml
- DEEPTUTOR_EXTRAS=guard,video-learning,partners,parse-pymupdf4llm,rag-lightrag
```

### 2.5 guard 开关的坑**没有**变

v1.7.2 的 entrypoint 仍然第一行就：

```bash
export DEEPTUTOR_IGNORE_PROCESS_ENV_OVERRIDES=1
```

⇒ **`DEEPTUTOR_GUARD_ENABLED` 等环境变量在 1.7.2 里依然是惰性的**。
开关仍然只在 `data/user/settings/system.json → security_guard.enabled`。
你 compose 里那几行注释**一字不改**。

### 2.6 数据布局：1.7.0 改了工作区

1.7.0 引入了 **Modern / Classic 两种布局、Task Board、Notebook/Dito**
（"分层页面 + block"，取代原来的 Co-Writer 编辑器）。

Dockerfile 里仍然创建老目录，说明**老数据路径仍被识别**：

```dockerfile
RUN mkdir -p \
    data/user/workspace/memory \
    data/user/workspace/notebook \
    data/user/workspace/co-writer/audio \
    data/user/workspace/chat/chat \
    data/user/workspace/chat/deep_solve \
    data/user/workspace/chat/deep_question \
    ...
```

官方也明确说 **"无需手动数据迁移，现有运行时数据原地保留"**。
但"原地保留"≠"新界面一定渲染得好"。
⇒ 这是验收清单里必查的一条。

---

## 3. 三个真实风险（按严重度）

### 风险 1 ★★ 模型目录 schema 可能不兼容 —— 直接打在你刚接好的本地模型上

1.7.2 发布说明里写：**"Settings 可以在凭据变化后重新发现模型、一次性导入多个模型、
并为自定义 provider 自动选择协议"** ⇒ provider profile 的结构**动过**。

你现在 `data/user/settings/model_catalog.json` 里的 profile 长这样：

```json
{"id": "local-ollama-qwen3-task", "provider": "ollama", "base_url": "...",
 "api_format": "openai_chat", "provider_mode": "local", "binding": "custom",
 "wire_api": "chat_completions", "api_key_env": "OLLAMA_API_KEY", "api_key": "ollama", ...}
```

**如果 1.7.2 改了 `api_format` / `binding` / `wire_api` 这几个键的语义，
你辛苦接的本地 qwen3 出题和本地 Whisper 转写会静默失效。**

> ⚠️ **"静默失效"是最坏的一种**：不会报错，只是默默切回云端，
> 或者默默不能用。**所以验收清单必须真的发一个请求、真的看转写结果，
> 不能只看 UI 上 profile 还在不在。**

### 风险 2 ★ 工作区/知识库在 1.7.0 重设计

老的 `chat/`、`co-writer/` 数据还在，但新界面是 Notebook/Dito 的分层页面。
**已有知识库要不要重建、能不能重建**，只有试了才知道。

### 风险 3 ★ 首次启动要下东西

1.7.2 镜像比 1.6.15 大得多（Node + LibreOffice + CJK 字体，估计 5GB 上下），
而且 `DEEPTUTOR_EXTRAS` 是**运行时**装的 ⇒ **第一次启动会联网 pip install 一批子包**。
**如果启动时网络不通，容器照样起得来（`|| true`），但功能是缺的** ——
这跟"装好了"长得一模一样，**必须逐项验**。

---

## 4. 并行试用方案（推荐执行路径）

### 4.1 原则

- **不动**现在跑着的 `deeptutor` 容器。
- 新实例用**不同的 compose project 名**、**不同端口**、**数据副本**。
- **唯一共享**的是只读的 whisper 模型缓存（627MB，模型文件，天然可共享）。

### 4.2 步骤

```bash
cd /d/DeepTutorLab

# ① 拉 1.7.2 镜像（这一步可能要几十分钟；后台跑，别在前台等）
docker pull ghcr.io/hkuds/deeptutor:1.7.2

# ② 复制数据（排除 whisper-cache，它只读共享）
cp -r data data-172
rm -rf data-172/whisper-cache

# ③ 写一份独立的 compose
cp docker-compose.yml docker-compose.172.yml
```

**④ 改 `docker-compose.172.yml`**（逐条）：

```yaml
services:
  deeptutor:
    image: ghcr.io/hkuds/deeptutor:1.7.2     # ← 官方镜像，不再自建
    container_name: deeptutor-172
    ports:
      - "127.0.0.1:3792:3782"                # ← 换端口，别撞 3782
    volumes:
      - ./data-172:/app/data                  # ← 数据副本
      - "./data/whisper-cache:/home/ubuntu/.cache"   # ← 共享只读模型缓存
    environment:
      - DEEPTUTOR_EXTRAS=guard,video-learning,partners,parse-pymupdf4llm,rag-lightrag
      - DEEPTUTOR_MINIMAX_API_KEY=${DEEPTUTOR_MINIMAX_API_KEY:-}
      - DEEPTUTOR_MINIMAX_BASE_URL=${DEEPTUTOR_MINIMAX_BASE_URL:-https://api.minimaxi.com/v1}
      - TZ=${TZ:-Asia/Shanghai}
    # ⚠️ 保留 redis 服务，但换容器名和 network，避免和旧实例抢
```

```yaml
  redis:
    container_name: deeptutor-redis-172
```

> ⚠️ **network 也要隔离**：两个实例如果用同一个 `deeptutor-network`，
> 容器名虽然不同但服务名 `redis` 相同 ⇒ DNS 会解析到任一个。
> **给 172 的 compose 用独立的 network 名。**

```bash
# ⑤ 用独立 project 起
docker-compose -p dt172 -f docker-compose.172.yml up -d

# ⑥ 看日志（重点看 extras 装没装成功）
docker logs -f deeptutor-172
```

### 4.3 验收清单（**逐条实测，不许看 UI 就下结论**）

| # | 检查项 | 命令 / 动作 | 通过标准 |
|---|---|---|---|
| 1 | 容器健康 | `docker ps --format '{{.Names}} {{.Status}}'` | `deeptutor-172` Up + healthy |
| 2 | extras 装上了 | `docker exec deeptutor-172 pip list \| grep -Ei 'fastapi-guard\|lightrag\|pymupdf4llm\|deeptutor-'` | **四个都在** |
| 3 | guard 没让容器拒绝启动 | `docker logs deeptutor-172 \| grep -i 'security_guard'` | 无 "not installed" |
| 4 | guard 开关仍生效 | `docker exec deeptutor-172 python -c "import json;print(json.load(open('/app/data/user/settings/system.json'))['security_guard']['enabled'])"` | `True` |
| 5 | ★ **模型目录 schema 兼容** | `docker exec deeptutor-172 python -c "from deeptutor.services.config.provider_runtime import resolve_stt_runtime_config as r; c=r(); print(c.model, c.provider_name, c.base_url, c.adapter)"` | `model=whisper-1`、`provider=custom`、`base_url=http://whisper-asr:8000/v1`、`adapter=openai_compat` |
| 6 | ★ **本地 qwen3 真的能出题** | 在 172 的界面里对一个知识库点"出题"，看它是否走本机（看容器日志或看响应延迟） | 出的是题，**不是报错** |
| 7 | ★ **本地 Whisper 真的能转写** | 跑 `_probe_speech.py` 那套（真实语音 → `transcribe_cues()`） | 返回 ≥1 条 cue，文本合理 |
| 8 | 老知识库还在 | 界面上看旧知识库 | 能列出、能打开 |
| 9 | 老对话还在 | 界面上看历史会话 | 能打开（**哪怕界面换了**） |
| 10 | B站字幕仍可用 | 丢一个 B站链接进"阅读/观看" | 出字幕 |
| 11 | 新功能：视频课 | 看能不能生成带解说的视频课 | 能生成（Node 22 已烘进） |
| 12 | **没有偷偷走云端** | `docker logs deeptutor-172 \| grep -i 'minimax\|api.minimax'` | 出题/转写请求里**不出现**云端调用 |

> ⭐ **第 5、6、7、12 条是真正的验收**。1~4 和 8~11 只是"没坏"。
> **第 12 条最容易漏**：本地模型没被认出来时，它会**默默用云端**，
> 账单上多一笔，而界面看起来一切正常。

### 4.4 回退

```bash
# 停掉试用实例，旧的完全没被动过
docker-compose -p dt172 -f docker-compose.172.yml down
rm -rf data-172
```

**旧的 1.6.15 实例全程不需要任何操作** —— 这就是并行试用的意义。

---

### 4.5 ★ 试用实测结果（2026-11-12，12/12 全过）

**镜像**：`ghcr.io/hkuds/deeptutor:1.7.2`，拉取 985.3 MB 压缩 / 3.86 GB 落盘，
拉取耗时约 25 分钟。

**并行实例**：`deeptutor-172`，端口 **3792**，project `dt172`，
network `dt172_deeptutor-network-172`，redis `deeptutor-redis-172`，
数据目录 `./data-172`（41 MB，**不含** whisper-cache —— 那个只读共享）。

**验收脚本**：`技术蒸馏课程\99_工具与模板\verify_172.py`（`--only N` 可单跑一条）。

```
[PASS]   soft  1. 容器健康            deeptutor-172|Up 8 minutes (healthy)|ghcr.io/hkuds/deeptutor:1.7.2
[PASS]   soft  2. extras 功能模块全部可 import    all 7 importable
[PASS]   soft  3. guard 没让容器拒绝启动   no guard errors
[PASS]   soft  4. guard 开关仍生效 (system.json)   True
[PASS] ★HARD  5. ★ STT 配置 schema 兼容
          whisper-1 custom http://whisper-asr:8000/v1 openai_compat
[PASS] ★HARD  6. ★ 出题模型指向本机且能真的回答
          RESOLVED qwen3:8b custom http://host.docker.internal:11434/v1 | REPLY: PIPELINE_OK
[PASS] ★HARD  7. ★ 本机 Whisper 真能转写
          CUES 1
             0.0 - 4.0 Git commit creates a new snapshot of the repository.
[PASS]   soft  8. 老知识库还在          2 entries: ['.lightrag-locks', 'kb_config.json']
[PASS]   soft  9. 老对话还在            212,992 bytes; tables=15
[PASS]   soft 10. B站原生取字幕链路可用
          TITLE Docker镜像停服? 我编写了一个镜像转存工具，解决国内无法使用docker的问题…
          DURATION 301.0   SEGMENTS 0   CHAPTERS 4
[PASS]   soft 11. 新功能：带解说的视频课可用
          node=v22.23.4 | MODULE True | KIT True
          FILES ['build.mjs','china_outline.json','kit.tsx','package-lock.json',
                 'package.json','render-platform.ts','voice.ts'] | EDGE_TTS True
[PASS] ★HARD 12. ★ 没有偷偷走云端        no cloud chat calls

12 条全部通过 ⇒ 可以迁移
```

**生产实例全程未被触碰**（实测）：

```
deeptutor | Up About an hour (healthy) | deeptutor-local:1.6.15-guard
3782 /            http=307     （和升级前一致）
3782 /api/...     http=401     （和升级前一致）
model_catalog.json  mtime = Nov 12 10:11   （升级前的时间戳，未变）
```

### 4.6 试用期间挖出来的 6 个事实（**都是真坑，迁移时必须知道**）

| # | 事实 | 影响 |
|---|---|---|
| **1** | ★ **`integrations.json` 的 `turn_coordination.redis_url` 是新的硬依赖**。1.7.x 引入"turn 协调后端"，后端连不上 Redis 就**拒绝启动**：`Turn coordination backend is unavailable; refusing to start` → 容器起不来、API 500。 | **迁移前必查**。你生产里现在是 `redis://deeptutor-redis:6379`，**容器名不变就正好对得上 ⇒ 生产不用改**。但**任何一次容器改名都会让 DeepTutor 起不来**。 |
| **2** | ★ **`fastapi-guard` v8 的模块名是 `guard`，不是 `fastapi_guard`**。 | `import fastapi_guard` 会失败，但包是装好的。你 1.6.15 的 `Dockerfile.guard` 里那句"import 不到就 RuntimeError 拒绝启动"在 1.7.2 变成了"顶多不启用 guard"，不再致命。 |
| **3** | ★ **`pymupdf4llm` 现在是 2.1，是真包**（`import pymupdf4llm` 直接 OK）。 | 你 `Dockerfile.guard` 里 `pymupdf4llm>=1.28.2,<2.0` 那个 **`<2.0` 的坑已经不存在了** —— 上游重做了版本线。 |
| **4** | ★ **extras 是运行时以 root 装的**（`install_extras.py` 在 `exec supervisord` 之前跑）。 | 你"必须在构建期以 root 装，否则退化成 `~/.local` 导致 import 不到"那套**整个不需要了**。`Dockerfile.guard` 可以删。 |
| **5** | ★ **`deeptutor-reading` / `deeptutor-partners` 等根本没被 pip 装** —— 因为镜像把整个 `deeptutor/` **源码树** COPY 进去了，`deeptutor.reading` 直接从 `/app/deeptutor` 导入。 | **不要用"pip list 里有没有这个包"判断功能在不在**，要用 `import` 判断。 |
| **6** | ★ **B站匿名请求拿不到字幕（segments=0）**，但章节（chapters）能拿到。 | **不是 1.7.2 的回归** —— 在 1.6.15 上跑同一个视频，结果**完全一样**（segments=0 / chapters=4）。这是 B站 `player/v2` 对未登录请求的行为。**要字幕必须带登录态**（这正好是你 All API Hub / playwright `--persistent` 那条路的用武之地）。 |

### 4.7 另外两个"我的测试写错了、不是系统坏了"的坑

| 坑 | 说明 |
|---|---|
| **本机 qwen3 在 `max_tokens=64` 时返回空 content** | 512 才稳定返回 `PIPELINE_OK`。**不是模型坏了，是预算不够**。凡是测本机 qwen3 的脚本，`max_tokens` 至少给 512。 |
| **Git Bash 会把容器路径改写** | `docker exec deeptutor python /tmp/x.py` → `python: can't open file '/app/C:/msys64/tmp/x.py'`。用 `MSYS_NO_PATHCONV=1`，或 `docker exec -i deeptutor python - < 脚本`（最省事）。 |
| **Windows 控制台是 GBK** | `subprocess.run(text=True)` 不显式指定 `encoding='utf-8'` 时，遇到中文标题会 `UnicodeDecodeError`。 |

---

## 5. 迁移（✅ **已于 2026-11-12 执行完毕**）

> **执行记录（2026-11-12）**：前置检查通过 → 备份 → 改 compose →
> **只重建 `deeptutor` 一个服务**（redis 和 whisper-asr 全程没动）→
> 容器 healthy → **12/12 验收全过** → 试用实例已拆除 → `Dockerfile.guard` 已标退役。
> 回退资产：`backups/data-before-172-20261112_113932/`（54MB，含全部 settings 与
> `chat_history.db`，sha256 逐个核对 MATCH）、`backups/docker-compose.before-172-*.yml`、
> `backups/Dockerfile.guard.before-172-*`，以及镜像 `deeptutor-local:1.6.15-guard` 仍在本地。

**前置确认**：生产实例的 `integrations.json` 里
`turn_coordination.redis_url` 必须仍指向**当前 redis 容器名**
（现在是 `redis://deeptutor-redis:6379`，容器名 `deeptutor-redis` ⇒ **正好，不用改**）。
**容器名一改，DeepTutor 就起不来**（见 §4.6 第 1 条）。

```bash
cd /d/DeepTutorLab

# ① 停旧容器（保留 data）
docker-compose down

# ② 备份数据（这一步不能省）
cp -r data backups/data-before-172-$(date +%Y%m%d_%H%M%S)

# ③ 改 docker-compose.yml
#    image: ghcr.io/hkuds/deeptutor:1.7.2       ← 换掉 deeptutor-local:1.6.15-guard
#    DEEPTUTOR_EXTRAS=guard,video-learning,partners,parse-pymupdf4llm,rag-lightrag,video-lesson,edge-tts
#    # 删掉 Dockerfile.guard 相关内容（镜像自带 ffmpeg / LibreOffice / 中文字体）
#    # DEEPTUTOR_APT_PACKAGES=ffmpeg 也可以留着（幂等，官方镜像已自带）

# ④ 起（第一次启动会联网 pip install extras，等几分钟）
docker-compose up -d
docker-compose logs -f deeptutor
```

> 💡 **本次实际用的是更温和的写法**：
> ```bash
> docker-compose up -d deeptutor      # 只重建这一个服务
> ```
> **redis 和 whisper-asr 不会被碰** ⇒ 不用停它们、不会丢 redis 数据、
> 也不用重新加载 Whisper 模型（11 秒）。
> `docker-compose down` 会把 compose 文件里的**所有**服务都停掉 ——
> **包括 whisper-asr**，那就要重新拉起 + 重新加载模型，没必要。

**迁移后必须重跑验收**（脚本支持 `--container`）：

```bash
cd "/c/Users/18798/Documents/技术蒸馏课程/99_工具与模板"
python verify_172.py --container deeptutor
```

### 迁移时最容易翻车的三点

1. **`.env` 的 BOM 规则不变**：`.env` 要 **CRLF**（Windows + docker-compose 解析），
   `model_catalog.json` 要 **UTF-8 无 BOM**。
   **JSON 带 BOM ⇒ 整个配置重置为默认值**（你踩过）。
2. **别在同一条命令里既装 `deeptutor[full]` 又重装 `deeptutor-cli`** ——
   官方明确说会删共享文件。**Docker 镜像路径不受影响**（镜像里两个都在）。
3. **首次启动会联网装 extras，失败是 `|| true`（不致命）** ——
   所以"容器起来了"**不等于**"功能装上了"。**必须跑 `verify_172.py`。**

### 迁移后可以退休的东西

| 文件 | 为什么能退休 | 现状 |
|---|---|---|
| `Dockerfile.guard` | 4 个包全变官方 extra 且运行时以 root 装；ffmpeg/LibreOffice/中文字体官方镜像自带 | ✅ **已加退役横幅，保留作历史记录** |
| `pyproject-upstream.toml` / `requirements-guard/` | 同上 | 未动（留着不碍事） |
| `ops/` 里针对 1.6.15 的补丁 | 1.7.2 原生支持 | 未动 |

**保留**：`docker-compose.yml`（已改镜像行）、`docker-compose.172.yml`（留作将来的
并行试用模板）、`data/`（原样）、`.env`、`backups/`。

### 5.1 旧镜像清理（2026-11-12）

删掉的镜像（**四个全删了**）：

```
docker rmi deeptutor-local:1.6.14-guard
docker rmi ghcr.io/hkuds/deeptutor:1.6.14
docker rmi ghcr.io/hkuds/deeptutor:1.6.15
docker rmi deeptutor-local:1.6.15-guard        ← 最后一个，2026-11-12 补删
```

> ⚠️ **实测结论，和一开始的估计不一样**：前三个**几乎没腾出空间**。
> `docker system df -v` 的 UNIQUE 列显示，它们和 1.7.2 **共享同一个 3.3GB 基础层**
> （`SHARED SIZE 3.299GB / UNIQUE SIZE` 只有 297MB / 10.8MB / 10.8MB）。
> 删掉 `ghcr.io/hkuds/deeptutor:1.6.15` 之后，那个基础层**只剩 `deeptutor-local:1.6.15-guard` 一个人持有**
> ⇒ 它的 UNIQUE 从 674MB 涨到 **3.973GB**，整体 RECLAIMABLE 从 1.015GB 变成 **4.669GB**。
>
> ⇒ **真正占空间的是最后一个，不是前三个。**
> 补删它之后 RECLAIMABLE 从 4.669GB 降到 **695.7MB** —— 也就是说
> **这 3.97GB 是删掉最后一个才真正释放的。**

数据与备份未受影响：`data/` 1.2GB（whisper 三个模型都在）、
`backups/data-before-172-20261112_113932/` 54MB。

### 5.2 回退办法（**镜像已删 ⇒ 回退变慢**）

预构建好的 `deeptutor-local:1.6.15-guard` **已删除**，所以现在回退要自己重建（约 40 分钟）：

```bash
cd /d/DeepTutorLab
docker pull ghcr.io/hkuds/deeptutor:1.6.15        # 3.3GB，约 25 分钟
docker build -t deeptutor-local:1.6.15-guard -f Dockerfile.guard .
# 把 docker-compose.yml 的 image 行改回 deeptutor-local:1.6.15-guard
#   并把 DEEPTUTOR_EXTRAS 改回 guard,video-learning,partners,parse-pymupdf4llm
#   （1.6.15 不认识 rag-lightrag / video-lesson / edge-tts 这三个 extra）
docker-compose up -d deeptutor
```

**数据回退**：`backups/data-before-172-20261112_113932/`（54MB）
**compose 回退**：`backups/docker-compose.before-172-20261112_113932.yml`

> 💡 这套步骤也写进了 `D:\DeepTutorLab\Dockerfile.guard` 顶部的退役横幅里 ——
> 免得真要回退时找不到配方。

---

## 6. 第三条路：Windows 桌面版（1.7.2 新增）

1.7.1/1.7.2 提供了 **Windows x64 安装包 + 便携 ZIP**（含 Python、Node.js、学习工作区）。

**优点**：
- **不用 Docker、不用 compose、不用维护 `Dockerfile.guard`** ——
  你这台机器上少一整套 Docker 维护负担。
- 本机 3060 直通（不用 `host.docker.internal`）。
- 官方说"同一个 `DEEPTUTOR_HOME` 下运行时数据原地保留" ⇒ 理论上可以指向 `D:\DeepTutorLab\data`。

**缺点 / 注意**：
- **Windows 构建未签名** ⇒ SmartScreen 会拦，要手动放行。
- **"自动更新发现未接通"** ⇒ 以后升级还是得手动下载。
- 桌面版能不能复用你现在的 `model_catalog.json`（含本地 qwen3 / whisper profile）
  **必须实测** —— 同一份 schema 在桌面版不一定一样。
- 桌面版会把 `DEEPTUTOR_HOME` 指到别处 ⇒ **必须显式设置**指向副本。

⇒ **建议**：等 1.7.2 的 Docker 试用验收过了，再考虑要不要试桌面版。
**别同时开三个战场**（旧 Docker + 新 Docker + 桌面版）。

---

## 7. 什么时候必须升级（触发条件）

不要为了"新"而升级。**出现下面任一条，再回来执行第 4 节**：

- [ ] 你要用 **Narrated Video Lesson**（带解说的视频课）—— 1.6.15 做不到
- [ ] 你需要 **edge-tts 朗读**（中文课程配音）
- [ ] 你要 **Notebook/Dito 分层页面**（替代 Co-Writer）
- [ ] 1.6.15 出现你绕不过去的 bug
- [ ] `Dockerfile.guard` 的维护开始占用你时间（那 4 个 pin 上游已经接管了）
- [ ] 你要**桌面版**（Windows 原生，不需要 Docker）

## 8. 什么时候**不要**升级

- ❌ 只是因为"最新版听起来好"
- ❌ 现在的本地模型接线刚刚验证通过（**别在验证通过的当天换掉它**）
- ❌ 手上还有别的正事（你的 RectSSL 线才是主战场，DeepTutor 是辅助）

---

## 9. 相关

- DeepTutor 现状与部署：`技术蒸馏课程\99_工具与模板\DeepTutor现状与部署指南.md`
- 课程流水线接线（保姆级）：`技术蒸馏课程\99_工具与模板\课程流水线接入DeepTutor_保姆级.md`
- 视频课程蒸馏：`技术蒸馏课程\99_工具与模板\视频课程蒸馏教程.md`
- 上游仓库：<https://github.com/HKUDS/DeepTutor>
- v1.7.2 Release：<https://github.com/HKUDS/DeepTutor/releases/tag/v1.7.2>
