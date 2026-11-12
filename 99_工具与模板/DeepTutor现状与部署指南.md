# DeepTutor：近况 · 本地现状 · 穿透 · 部署

> **本文全部是本机实测**，不是抄文档。
> 实测时间：2026-11-11。机器：`C:\Users\18798\Documents`（Windows 11）
> 部署目录：`D:\DeepTutorLab` · 运维脚本：`...\AI_Workstation_FINAL_20261015\ops\`

---

## 一、近况（项目本身）

| 项 | 值 |
|---|---|
| 项目 | **DeepTutor**，香港大学 HKUDS 数据科学实验室开源 |
| 仓库 | <https://github.com/HKUDS/DeepTutor> · 官网 <https://deeptutor.info/> |
| 许可 | **Apache 2.0** |
| GitHub 最新 release | **v1.7.2（2026-11-06）** ← 本机已升级到这个版本 |
| 定位 | **Agent-Native 个性化教学/学习工作台** |
| 环境要求 | Python **3.11–3.14** + Node.js **20+**（源码开发要 22 LTS）· 不需要 Docker/显卡/云账号 |
| 端口 | 前端 **3782** · 后端 **8001** |

### 核心能力（与你的课程蒸馏直接相关）

| 能力 | 说明 |
|---|---|
| **单一 Agent Loop** | Chat / Quiz / Research / Visualize / Solve / Mastery Path / **Immersive Reading·Watching** / Co-Writer 共用一个上下文 |
| **多引擎 RAG** | LlamaIndex / PageIndex / GraphRAG / LightRAG；解析引擎支持 Text-only / MinerU / Docling / **PyMuPDF4LLM**；可挂 Obsidian |
| **三层可审计记忆** | L1 事件日志 / L2 场景总结 / L3 跨会话知识图谱，**全明文文件可回溯** |
| **本地模型** | Ollama / LM Studio / llama.cpp / **vLLM** / Lemonade（Docker 内用 `host.docker.internal`） |
| **多用户** | 默认**不开认证**；开启后首个注册账号是 admin，用户工作区隔离，管理员可分配模型/知识库/skill 权限 |

> ⚠️ **官网本身没有公网暴露/穿透/反代的说明** —— 文档示例全部只绑 `127.0.0.1`。
> 所以"怎么让外面访问"这部分**必须自己做**，见第四节。

---

## 二、本地现状（你这台机器上已经跑起来了）

### 2.1 容器清单（实测 `docker ps`）

```
NAMES              IMAGE                          PORTS                                       STATUS
deeptutor          ghcr.io/hkuds/deeptutor:1.7.2  127.0.0.1:3782->3782/tcp                    Up (healthy)
deeptutor-redis    redis:7.4-alpine               6379/tcp                                    Up 3 days (healthy)
whisper-asr        fedirz/faster-whisper-server   127.0.0.1:9000->8000/tcp                    Up
kg-neo4j           neo4j:5                        127.0.0.1:7474->7474, 7687->7687             Up
sub2api            weishaw/sub2api:0.1.163        127.0.0.1:18080->8080/tcp                    Up (healthy)
sub2api-postgres   postgres:18-alpine             5432/tcp                                    Up (healthy)
sub2api-redis      redis:8-alpine                 6379/tcp                                    Up (healthy)
```

**DeepTutor v1.7.2 已经在跑（官方镜像）。**
`kg-neo4j` 是给它做 L3 知识图谱用的；
`whisper-asr` 是本机语音转写（给"阅读/观看"用，模型缓存挂在 `./data/whisper-cache`）。

### 2.2 访问

```
http://127.0.0.1:3782      → 307 重定向到 /chat → 200 ✅
```

### 2.3 部署配置（`D:\DeepTutorLab\docker-compose.yml`，原注释已经写得很清楚）

| 修改点 | 做法 | 为什么 |
|---|---|---|
| 镜像版本 | 固定 `ghcr.io/hkuds/deeptutor:1.7.2`，`pull_policy: if_not_present` | 防止重启就换版本。**已从自建的 `deeptutor-local:1.6.15-guard` 切到官方镜像（2026-11-12）** |
| **端口绑定** | **`127.0.0.1:3782`**，不是 `3782:3782` | 写成后者会绑 `0.0.0.0`，**整个局域网都能连上** |
| 端口数量 | **只暴露 3782**（前端） | 单容器架构下前端会把 `/api/*` 转发给容器内后端 8001，宿主机**不需要**映射 8001。实测 `/api/system/status` 经 3782 与直连 8001 返回码一致（401），证明代理链路通 |
| 挂载 | **整个 `./data`** | 只挂子目录会导致 `data/system`（认证密钥、账号、token）留在容器可写层，**重建容器就没了** |
| extras | `guard,video-learning,partners,parse-pymupdf4llm,rag-lightrag,video-lesson,edge-tts` | 声明式环境变量 → 每次启动幂等重装。**1.7.2 起这七个全是官方 extra**，`install_extras.py` 在 root 阶段装（`exec supervisord` 之前） |

> ⭐ **为什么从自建镜像切到官方 1.7.2（2026-11-12）**：
> 1.7.2 把 guard / rag-lightrag / parse-pymupdf4llm / video-learning / partners
> 全变成**官方 extra**，而且**改成运行时以 root 装** ⇒ `Dockerfile.guard` 这层
> **失去存在理由**（ffmpeg / LibreOffice / 中文字体官方镜像也自带）。
> 额外收获：**Node.js 22.23.4 烘进了镜像** ⇒ 1.7.0 的"带解说的视频课"开箱可用。
> 完整评估 + 12 条验收清单 + 回退办法见
> `技术蒸馏课程\99_工具与模板\DeepTutor升级决策_1.7.2评估.md`。

> ⚠️ **1.7.2 新增一条硬依赖**：`integrations.json → turn_coordination.redis_url`
> （现值 `redis://deeptutor-redis:6379`）**必须等于 redis 服务的 `container_name`**，
> 否则后端拒绝启动（`Turn coordination backend is unavailable; refusing to start`）。
> **改容器名 = 同时要改这个 URL。**

### 2.4 数据与工作区

```
D:\DeepTutorLab\data                    → /app/data        （配置、记忆、知识库、账号）
D:\DeepTutorLab\data\user\workspace     → /workspace       （模型能碰的唯一目录）
```

`DEEPTUTOR_WORKSPACE_ROOT=/workspace` + `DEEPTUTOR_WORKSPACE_ALLOWED_ROOTS=/workspace`
→ **容器里模型生成的代码只能碰 `/workspace`**。这也是"百度网盘视频放哪"的标准答案。

### 2.5 LLM 配置

当前走 **MiniMax 官方 API**：

```
DEEPTUTOR_MINIMAX_BASE_URL=https://api.minimaxi.com/v1
DEEPTUTOR_MINIMAX_API_KEY=<用户级环境变量，不写进文件>
```

密钥三层管理（`ops\README.md` 记录）：
```
权威副本   → 用户级环境变量（不在任何项目文件里）
运行时副本 → model_catalog.json 的 profile.api_key（DeepTutor 的设计，只能在这）
基线/交接包 → 导出时自动脱敏
```

切换脚本：`ops\switch-model.ps1 -Target local|api`
（local = 本机 RTX 3060 的 qwen3:8b，免费离线但慢；api = MiniMax M3.1 Flash，快但花钱）

> 💡 **本机 Ollama 已有**：`qwen3` / `qwen2.5` / `bge-m3` / `nomic-embed-text`
> —— 前两个是对话，后两个是嵌入。**做语音转写还需要 ASR 模型**（见视频课程教程 §3）。

### 2.6 ⚠️⚠️ 一个必须知道的坑：环境变量覆盖是被屏蔽的

```
官方 entrypoint 导出了 DEEPTUTOR_IGNORE_PROCESS_ENV_OVERRIDES=1
而 runtime_settings.py 的 _process_env_value() 开头就是：
    if self._ignore_process_overrides():
        return ""          # ← 所有环境变量覆盖被丢弃
```

**⇒ `DEEPTUTOR_GUARD_*` 这几个环境变量在本镜像里不生效。**
**guard 的唯一真实开关是 `data\user\settings\system.json` → `security_guard.enabled`**
（已写入 `true`）。

> 官方 `SECURITY_GUARD.md` 说的 "Docker: `DEEPTUTOR_EXTRAS=guard`" 是**装包装**，
> 不是**开开关** —— 这两件事经常被混为一谈。

### 2.7 BOM 规则（写反都出事）

| 文件 | BOM | 违反后果 |
|---|---|---|
| `.ps1` 脚本 | ✅ **要** | PS 5.1 按 ANSI 读 → 中文乱码 → 语法错 |
| `.json` 配置 | ❌ **不能要** | 应用不剥 BOM → **整份配置被默认值重置** |

守卫：`ops\check-encoding.ps1`

---

## 三、运维脚本清单（已有，别重写）

`...\AI_Workstation_FINAL_20261015\ops\`

| 脚本 | 干什么 |
|---|---|
| `after-reboot-check.ps1` | **重启后自检（12 项）** —— 开机后第一个跑 |
| `audit-requirements.ps1` | 需求审计（当前 **44 PASS / 8 FAIL**，共 52 条） |
| `setup-24-final-verify.ps1` | 交付验收（38 项） |
| `converge-config.ps1` | 配置收敛：界面/回答中文 · turn_coordination→Redis · LightRAG 绑 LLM · 解析引擎→pymupdf4llm |
| `switch-model.ps1` | 本机 ⇄ 云端模型切换 |
| `test-providers.ps1` | 测两条链路通不通 |
| `collect-videos-bili.ps1` | **B站采集**（搜索 + view API，带时效门槛） |
| `collect-videos.ps1` | YouTube 采集 |
| `public-exposure-audit.ps1` | **对外暴露前的安全审计** |
| `gpu-lease.ps1` | 公共 GPU 按需租约（申请→执行→自动释放，带收据） |
| `farm-status.ps1` / `fleet-inventory.ps1` | 三机 GPU 池状态汇总 + 调度建议 |
| `backup-data.ps1` / `export-baseline.ps1` / `export-handover.ps1` | 备份与交接 |
| `migrate-from-1.5.ps1` | 旧版 1.5.17 数据迁移（**旧机容器必须还活着**） |
| `frpc-local.toml` / `frps-install.sh` | **frp 穿透**（客户端/服务端） |
| `ollama-doctor.ps1` | Ollama 体检 |
| `redact-secrets.ps1` | 脱敏 |

三个只读复验命令（贴显示器那张速查卡）：

```powershell
$OPS = "C:\Users\18798\Documents\Codex\2026-09-30\ni-ha\outputs\AI_Workstation_FINAL_20261015\ops"
& "$OPS\after-reboot-check.ps1"
& "$OPS\audit-requirements.ps1"
& "$OPS\setup-24-final-verify.ps1"
```

---

## 四、穿透（把 3782 暴露到公网）

### 4.1 现在的状态：**什么都没开**

| 项 | 实测 |
|---|---|
| `cloudflared` | ❌ **没装** |
| `frpc` / `frps` 进程 | ❌ **都没跑** |
| 端口 3782 绑定 | ✅ **`127.0.0.1`（仅本机）** ← 这是对的 |

### 4.2 两条路（`frpc-local.toml` 的注释里已经算过账）

| 方案 | 成本 | 国内访问 | 备注 |
|---|---|---|---|
| **Cloudflare Tunnel** | **0 元** | 慢（实测 **1.0~2.6 秒/次**，走海外边缘） | 零配置，已验证能跑通 |
| **frp + VPS** | **38 元/年**（约 3~6 元/月） | **快**（几十毫秒） | 入口稳定，需一台轻量服务器 |

**两个方案可以并存**，用 frp 时关掉 cloudflared 即可。

### 4.3 frp 怎么走（文件已备好，只差填三处）

`ops\frpc-local.toml` 里要填的：

```toml
serverAddr = "你的阿里云/腾讯云轻量服务器公网 IP"   # ← 填
serverPort = 7000
auth.token = "<与 VPS 上的 FRP_TOKEN 完全一致>"        # ← 填
[[proxies]]
name = "deeptutor-web"
type = "https"
localIP = "127.0.0.1"
localPort = 3782
customDomains = ["你的域名"]                          # ← 填（已 A 记录到上面的 IP）
```

**没有域名想先用 IP+端口试跑**（文件里注释了）：把 `type` 改 `http` + `remotePort = 8080`，
并在 VPS 上开 `vhostHTTPSPort`。
⚠️ **纯 HTTP 只用于调试，不要长期用 —— 没有 TLS。**

启动：

```powershell
frpc.exe -c ops\frpc-local.toml
# 开机自启：
sc.exe create DeepTutor-Frpc binPath= "C:\path\frpc.exe -c C:\path\frpc-local.toml" start= auto
```

服务端：`ops\frps-install.sh`

### 4.4 ⚠️⚠️ 穿透之前必须先解决的三件事（否则就是把后门打开）

**这是当前 8 项未达标里最要紧的 3 项：**

| 需求 | 状态 | 为什么必须先做 |
|---|---|---|
| `REQ-NET-006` **对外有访问控制** | ❌ FAIL | **DeepTutor 默认不开认证**（`system.json` 无 `auth` 段 = 认证关闭）。**裸暴露 = 任何人打开就是管理员** |
| `REQ-NET-005` **对外是 HTTPS** | ❌ FAIL | frp `type = "https"` 需要域名 + 证书；Cloudflare Tunnel 自带证书 |
| `REQ-NET-004` **反代支持 WebSocket** | ❌ FAIL | 聊天是流式 WebSocket，普通反代会断流 |

**正确顺序**：

```
① 开认证（DeepTutor 内 /register 注册第一个账号 → 自动成为 admin）
② 开反向代理 + HTTPS（Cloudflare Tunnel 自带证书，最省事）
③ 确认 WebSocket 能穿透
④ 最后才套访问控制（Cloudflare Access / frp 侧白名单）
⑤ 跑 ops\public-exposure-audit.ps1 复验
```

### 4.5 Cloudflare Tunnel 的替代路径

因为 `cloudflared` 没装，如果想零成本先试：

```bash
# 1) 装 cloudflared（Windows）
winget install --id Cloudflare.cloudflared

# 2) 登录（浏览器授权）
cloudflared tunnel login

# 3) 建隧道并绑定 3782
cloudflared tunnel create deeptutor
cloudflared tunnel route dns deeptutor <你的域名>

# 4) 写 config.yml
#    tunnel: <tunnel-id>
#    credentials-file: C:\Users\18798\.cloudflared\<tunnel-id>.json
#    ingress:
#      - hostname: <你的域名>
#        service: http://127.0.0.1:3782
#      - service: http_status:404

# 5) 跑起来 + 开机自启
cloudflared tunnel run deeptutor
```

**注意**：Cloudflare Tunnel 默认会把流量**回源到你的家宽 IP**，
国内访问慢（实测 1.0~2.6 秒/次）—— 这就是 frp 方案存在的理由。

### 4.6 Codex OAuth 回调要单独开隧道

DeepTutor 支持用 Codex OAuth 登录，远端做 OAuth 回调时需要：

```bash
ssh -N -L 1455:127.0.0.1:3782 <ssh-user>@<server-host>
```

（容器里 OAuth 回调端口是 **1455 或 1457**，且**必须留在 loopback**。）

---

## 五、部署（怎么重建 / 换机 / 升级）

### 5.1 日常启停

```powershell
cd D:\DeepTutorLab
docker compose ps              # 看状态
docker compose logs -f deeptutor   # 看日志
docker compose restart deeptutor   # 改完配置后重启（模型/解析引擎改了必须重启）
docker compose up -d           # 启动
docker compose down            # 停（数据在 ./data，不会丢）
```

### 5.2 升级镜像

```powershell
cd D:\DeepTutorLab
# ① 先备份数据
& "$OPS\backup-data.ps1"
# ② 改 docker-compose.yml 的 image: 标签 → docker compose pull
docker compose pull deeptutor
docker compose up -d
# ③ 验收
& "$OPS\setup-24-final-verify.ps1"
```

> ⚠️ **别用 `latest`**。compose 里明确写了原因：防止重启就换版本。
> 而且 1.6.14 → 1.6.15 就是一次**功能本体从无到有**的升级（guard）。

### 5.3 换机迁移

```powershell
# 【旧机】容器必须还活着！
& "$OPS\migrate-from-1.5.ps1" -Phase Export
# 【新机】
& "$OPS\migrate-from-1.5.ps1" -Phase Import -Source "<zip>"
& "$OPS\migrate-from-1.5.ps1" -Phase Check
```

⭐ **RAG 迁移硬前提：embedding 模型必须和旧机一致**（否则向量失效**且不报错**）。
脚本会自动对比并报告。

### 5.4 数据在哪、怎么备份

```
D:\DeepTutorLab\data\
  ├─ user\settings\   ← 所有配置（system.json / model_catalog.json / auth.json …）
  ├─ user\workspace\  ← 工作区（放视频/材料的地方）
  ├─ knowledge_bases\ ← 知识库（你的课程材料）
  ├─ memory\          ← 三层记忆
  ├─ partners\        ← IM 渠道配置
  ├─ parse_cache\     ← 解析缓存
  └─ system\          ← 认证密钥、账号、token
```

**备份 `data` 整个目录**，不要挑着备份 —— `system/` 里的认证密钥丢了要重新配。

---

## 六、还差什么（8 项，都要你本人）

`handover\20261022-132025\07-剩余事项清单.md` 原文：

| 需求 | 内容 |
|---|---|
| `REQ-NET-004` | 反代支持 WebSocket |
| `REQ-NET-005` | 对外为 HTTPS |
| `REQ-NET-006` | 对外有访问控制 |
| `REQ-MOB-001` | 支持多用户注册 |
| `REQ-MOB-002` | 管理员可管理用户 |
| `REQ-MOB-003` | 用户数据相互隔离 |
| `REQ-MOB-004` | 可分配模型/知识库/skill 权限 |
| `REQ-MOB-005` | 共享书籍可配置 |

**为什么 AI 代劳不了**（原文）：

| 类别 | 具体 |
|---|---|
| 账号 | 注册第一个管理员（`/register`，第一个注册的自动是 admin）、给朋友建号 |
| 第三方账号 | 域名 + Cloudflare 账号（隧道 + Access 门禁 + 边缘限流） |
| 物理操作 | BIOS「来电恢复供电 = Power On」（必须到机器前） |
| 花钱 | 租 VM 跑 Jenkins + k3s（$5~8/月，**绝不租 GPU**） |
| 另一台机器 | 1.5.17 旧数据迁移（要在**旧机器容器还在跑的时候** cp 出来） |

> 💡 **注意 `REQ-MOB-001~005` 这五项其实不用"手工"** ——
> DeepTutor **本身就有**多用户功能（开认证后首个注册=admin、管理员可分配
> 模型/知识库/skill 权限、用户工作区隔离）。
> **你要做的只是"把认证打开 + 注册第一个账号"**，剩下的在界面里点。
> 这个审计是按"必须人工确认"判的 FAIL，不是说功能不存在。

---

## 七、给你的最小行动清单

```
第 1 步（5 分钟）  浏览器打开 http://127.0.0.1:3782
                   → /register 注册第一个账号（自动是 admin）
                   → 这一个动作同时解掉 REQ-MOB-001~005 的"账号"部分

第 2 步（10 分钟） 跑 ops\after-reboot-check.ps1
                   → 确认 12 项自检全绿

第 3 步（要花钱） 买一台轻量服务器（约 38 元/年）
                   → 填 ops\frpc-local.toml 三处 → frpc 跑起来
                   → 域名 + 证书（HTTPS）→ 反代要支持 WebSocket

第 4 步（5 分钟） 跑 ops\public-exposure-audit.ps1
                   → 确认对外暴露没有裸奔
```

---

## 相关

- 视频课程怎么用 DeepTutor 蒸馏：`技术蒸馏课程\99_工具与模板\视频课程蒸馏教程.md`
- 租服务器与资源利用：`技术蒸馏课程\99_工具与模板\租服务器与资源利用指南.md`
- 课程总纲：`技术蒸馏课程\00_课程总纲.md`
- 官方仓库：<https://github.com/HKUDS/DeepTutor> · 官网 <https://deeptutor.info/>
