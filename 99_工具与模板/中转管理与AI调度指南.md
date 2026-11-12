# 中转站管理 + AI/Agent 调度指南

> **本文的每一条都是本机实测的**，不是抄来的。
> 实测时间：2026-11-11。额度状态会变，**带时间戳的数字请当作当时的快照**。
> 配套工具：`技术蒸馏课程\99_工具与模板\quota.py`（实时探测）、
> `dispatch.py`（带故障转移的执行）、`dispatch_*.md`（任务）。

---

## 1. 管理的对象是什么

你手上不是"一条线"，是**四层东西**，搞混了就会做出错误的操作：

| 层 | 是什么 | 本机实例 | 换它的代价 |
|---|---|---|---|
| **① 协议** | OpenAI Responses / Anthropic Messages / Gemini Native | Codex 用 Responses；Claude APP 用 Messages | 换协议 = 换客户端 |
| **② 站点** | 一个中转站 = 一个 base_url + 一把 key | pincar、agentrouter、freehyy | **换站 = 换 provider id = 旧对话全部失联** |
| **③ 模型** | 一个具体模型名 | gpt-6-astra、gpt-6.1-sol、gpt-5.6-sol… | 换模型 = 换思考风格 |
| **④ 档位** | effort / verbosity / context window | low / medium / high / xhigh / ultra / max | 换档 = 换速度与深度 |

**绝大多数"换站出问题"的根源，是把 ② 当成了可随手改的东西。**

---

## 2. ★ 三条铁律（都是踩出来的）

### 铁律一 · 换站 = 换 provider id = 旧对话失联

Codex 给每个对话打 `model_provider` 标签，存在 `state_5.sqlite`：

```sql
SELECT id, rollout_path, archived, source, model_provider FROM threads
```

桌面端拿这个标签和当前 `model_provider` 比，不一样就报"模型提供商不匹配"。

**推论：想要换站不丢对话，唯一办法是让 provider id 不变。**

### 铁律二 · ★ 额度是"每站 × 每模型"独立的，不是"每站"

**这是本指南最重要的一条，也是我实测踩到的。**

2026-11-11 20:40 实测矩阵（`quota.py` 输出）：

```
agentrouter    gpt-6-astra    402 budget pool empty      (6.2s)
agentrouter    gpt-6.1-sol    ALIVE                      (10.3s)
pincar         gpt-6-astra    429 rate limited           (4.5s)
pincar         gpt-6.1-sol    429 rate limited           (3.4s)

usable right now:  agentrouter / gpt-6.1-sol
```

看第一行：**agentrouter 明明活着，却对 `gpt-6-astra` 返 402，对 `gpt-6.1-sol` 正常。**

所以：
- 只探"站活着没"是**不够的**，必须探 **(站, 模型) 组合**
- 故障转移的单位不是"站"，是 **(站, 模型) 对**
- 一个站的 astra 预算池空了，不代表这个站废了 —— 换个模型照样能用

> 💡 同一天里 agentrouter 的 astra 池从 402 变成可用（17:19 成功、20:40 又 402），
> **额度是会回补的**。所以"一次 402 就弃用这个站"是错的。

### 铁律三 · ★ 一个客户端同一时刻只能跑一个 codex exec

并行会话实测：两个 `codex exec` 同时跑，**两个都失败**，报

```
failed to initialize in-process app-server client: access denied (os error 5)
```

`~/.codex/app-server-control/app-server-control.sock` 是**独占**的。

**推论：调度器不能并发跑多个任务，必须串行。**
这也解释了为什么并行会话各自蒸馏一课时会互相踩。

---

## 3. 三个工具的分工

| 工具 | 干什么 | 什么时候用 |
|---|---|---|
| `quota.py` | 探测每个 (站, 模型) 组合的实时可用性 | 开工前、报 402 后 |
| `dispatch.py --task <文件>` | 跑一个蒸馏任务，**自动故障转移** | 日常干活 |
| `dispatch.py --probe` | 只探活，不干活 | 排查 |
| `relay_pending.py --watch` | 等 Codex 关掉后自动做标签归一 | 一次性 |

### 3.1 故障转移的实际行为（实测）

```
$ python dispatch.py --task 某任务.md
--> trying agentrouter / gpt-6-astra via profile relay-agentrouter ...
    failed (402 budget pool empty)
--> trying agentrouter / gpt-6.1-sol via profile relay-agentrouter-sol ...

OK  -> 某任务.out.md
    done by agentrouter / gpt-6.1-sol
```

**它换了模型，不只是换了站** —— 这就是铁律二的直接结果。

### 3.2 每个组合对应的 profile

| 站 | 模型 | profile |
|---|---|---|
| agentrouter | gpt-6-astra | `relay-agentrouter` |
| agentrouter | gpt-6.1-sol | `relay-agentrouter-sol` |
| pincar | gpt-6-astra | `relay-pincar` |
| pincar | gpt-6.1-sol | `relay-pincar-sol` |

这些 profile 在 `~/.codex/`，**不含 token** —— 它们只指向 config.toml 里已有的 provider 块。

---

## 4. "共同提问方法"是怎么做到的

你要的是「pincar 和 agentrouter 的内容可以共同使用提问方法」。这不是靠"两个站模型一样"，
而是靠**三个东西同时固定**：

| 固定什么 | 值 | 在哪固定 |
|---|---|---|
| **模型** | `gpt-6-astra`（两边都服务过的模型） | profile 的 `model =` |
| **思考档** | `max` | profile 的 `model_reasoning_effort =` |
| **提问模板** | 同一份提示词文件 | `99_工具与模板/提示词模板_标准课.md` |

**关键点：模型也要固定，不能各用各的。**
`gpt-6-astra` 和 `gpt-6.1-sol` 的思考风格不同，同一个提示词在两个模型上
产出的深度和结构会有差别。所以：

> **同一节课的蒸馏，全程用同一个模型。**
> 如果中途因为 402 换了模型，那一节的风格就和别节不一致 —— 记在 `.meta.json` 里，
> 复盘时知道就行。

`.meta.json` 会如实记录：

```json
{
  "site": "agentrouter", "model": "gpt-6.1-sol", "profile": "relay-agentrouter-sol",
  "effort": "max",
  "attempts": [
    {"site": "agentrouter", "model": "gpt-6-astra", "rc": 1, "reason": "402 budget pool empty"},
    {"site": "agentrouter", "model": "gpt-6.1-sol", "rc": 0}
  ]
}
```

**这一条让"共同提问方法"可审计**：你能查出哪一节课是在降级状态下做的。

---

## 5. 让对话跨站续上的做法（已实施，待生效）

### 5.1 做法

在 `config.toml` 里建**一个固定的 provider id**（叫 `relay`），
切站时只改它的 `base_url` 和 token，**id 不动**：

```toml
[model_providers.relay]
name = "统一中转 (pincar <-> AgentRouter)"
base_url = "https://agentrouter.org/v1"     # ← 切站时只改这里
wire_api = "responses"
requires_openai_auth = false
experimental_bearer_token = "..."
```

标签永远是 `relay` → 永远匹配 → **永远不报不匹配**。

### 5.2 为什么这在原理上成立（抓包实测）

Codex **不在服务端存对话状态**。真实请求长这样：

```
POST /v1/responses
  store                = false
  previous_response_id = 根本没有这个字段
  reasoning.context    = "all_turns"
  input                = 整个对话，每一轮全部重发
```

第二 turn 实测 input 从 7 项涨到 9 项，第一轮那句话原样重发。

**所以第 N+1 轮发去和第 N 轮不同的站，不会丢任何东西。**

### 5.3 为什么不用本地网关转发

两个站都**校验客户端是不是官方 Codex 客户端**：

| 站 | 普通 HTTP 客户端发请求 |
|---|---|
| pincar | 403 `This account only allows Codex official clients` |
| agentrouter | 401 `unauthorized client detected` |

**任何自己发请求的本地代理都会被拒。** 所以唯一可行的形态是：
**Codex 自己直连中转站**，你只改它连哪个站。

### 5.4 现在到哪一步了

| 步骤 | 状态 |
|---|---|
| CLI 侧的共同提问法 profile（6 个） | ✅ **已完成并实测**：两站都能跑 |
| `relay` provider 块写进 config.toml | ⏸ **待执行**（Codex 开着，写了会被桌面端回写覆盖） |
| 旧会话标签归一到 `relay` | ⏸ **待执行**（同上） |
| 桌面端默认站切到 `relay` | ⏸ **待执行** |

**后三步已经做成待执行任务**：

```
relay_pending.py --watch --site agentrouter
```

它每 20 秒探一次 codex.exe，**你一关掉桌面端，它立刻自动完成迁移**，
然后写日志到 `pending_state/watcher.log`。你不用管，任务不会因为你"还有事要干"而被耽误。

---

## 6. Agent 怎么调度（你问的"用 AI 和 AGENT 做好管理和调度"）

### 6.1 本机已有的调度能力

| 能力 | 状态 | 说明 |
|---|---|---|
| **多站并行** | ✅ | 两个站是两条独立线路，可同时用 |
| **同站多模型** | ✅ | 每个站至少两个可用模型，四个组合都有 profile |
| **自动故障转移** | ✅ | `dispatch.py` 已实测：402 → 换模型 → 成功 |
| **模型池实时探测** | ✅ | `quota.py` 已实测 |
| **跨站对话续接** | ⏸ | 机制已证明，待标签归一后生效 |
| **并发多任务** | ❌ | **做不到**：app-server socket 独占（铁律三） |

### 6.2 一条纪律：串行，不并发

```
❌ 同时起 4 个 codex exec 蒸馏 4 课
   → 4 个都挂：access denied (os error 5)

✅ 一个一个来
   → dispatch.py 自己内部串行试 (站, 模型) 组合
```

### 6.3 推荐的 Agent 分工

| Agent | 干什么 | 用哪个组合 |
|---|---|---|
| **蒸馏工** | 把材料变成一课 | `dispatch.py --task`，它自己挑组合 |
| **审校工** | 跑 `verify.py`，编译所有代码块 | 本地 gcc，不需要模型 |
| **复核工** | 核对要点里的 API/标准出处 | 固定用一个站+模型（保持风格一致） |
| **答疑工** | 回答你的问题 | 任意有额度的组合 |

**审校工不消耗额度**（纯本地编译）—— 这是最划算的一环，
因为它挡住的是"看起来对但编译不过"的代码，那是最费时间的返工。

### 6.4 什么时候该人工介入

| 信号 | 处理 |
|---|---|
| `dispatch.py` 四个组合全失败 | 先跑 `quota.py` 看是不是全线告急 → 去做签到 |
| 某一课 `.meta.json` 显示换了模型 | 复盘时注意这节风格可能不同 |
| `verify.py` 报 `402` 之类的**不是**编译错误 | 那是代理把上游错误当成了代码错误 → 换站重跑 |

---

## 7. 额度管理：把签到变成不用想的事

### 7.1 本机签到状态（实测）

| 资源 | 状态 |
|---|---|
| AgentRouter | ✅ 已用；**每日签到 $25**（`agentrouter.org` 后台首页点一下） |
| pincar | ✅ 已用（与 freehyy 同主机、不同账号组） |
| All API Hub 扩展 | ❌ **未安装** ← 这是最该补的 |
| magpie | ❌ 未安装 |
| free-claude-code | ❌ 未安装 |

### 7.2 优先级（按投入产出比排序）

```
第 1 步  装 All API Hub 扩展，把已有的两个站加进去
         → 每天自动签到，零维护，成本 10 分钟
         → 这是 ROI 最高的一步，因为你已经有站了

第 2 步  按薅羊毛指南 §6 的表再开 2~3 个站
         → 优先 AnyRouter / KKtoken / DoCode（都是"Claude Code 和 Codex 都支持"，
           日签到 $20~25）

第 3 步  需要"一个面板 + 自动换卡"再上 magpie
         → magpie accounts checkin
         → 建路由组，同家的多张卡合成一个，额度耗尽自动切

第 4 步  想要 61 家模型随便换再上 FCC
         → 本地 8082，fcc-claude / fcc-codex
```

完整的站表、邀请码、安全注意事项见
`技术蒸馏课程\99_工具与模板\薅羊毛指南_20261111.md`。

### 7.3 ⚠️ 一个反直觉的提醒

**装签到插件不会让 Codex 用上这些站的额度。**

签到插件解决的是"**额度每天到账**"，
而 Codex 用哪个站是 `config.toml` 的 `model_provider` 决定的，**完全独立**。

要让 Codex 真的用上新站的额度，得：

```bash
# 1) 把新站的 provider 块加进 config.toml
# 2) 给它加一个 profile
# 3) 把调度器的 SITES 列表加上它
```

**三步都要做。** 只做第 1 步的话，签到了但用不上。

---

## 8. 完整的一次工作流

```bash
cd "C:\Users\18798\Documents\技术蒸馏课程"

# ① 开工前看一眼哪些组合还活着
python 99_工具与模板\quota.py

# ② 写好这一课的任务文件（模板在 99_工具与模板/）
#    复制 提示词模板_标准课.md，改标题和主题

# ③ 蒸馏（自动选站、自动故障转移、自动记录用了哪个组合）
python 99_工具与模板\dispatch.py --task 01_C语言核心\任务_02_xxx.md

# ④ 质量闸：编译所有代码块 + 查占位符 + 查 volatile
python 99_工具与模板\verify.py 01_C语言核心\任务_02_xxx.out.md

# ⑤ 没过闸 → 改任务文件重跑；过了 → 拆成五个文件放进课程目录

# ⑥ 把 99_复盘.md 里的错题填进下一课的任务文件
```

---

## 9. 现在还剩什么（待你决定）

| # | 事项 | 谁做 |
|---|---|---|
| 1 | 装 All API Hub 扩展 | 你点商店链接 |
| 2 | 把两个站加进扩展 | 浏览器登录后加 |
| 3 | 开 2~3 个新站 | 你注册 |
| 4 | 把新站接进调度器 | 我改 `dispatch.py` 的 SITES |
| 5 | **关掉一次 Codex 桌面端** | 你 —— 归一任务会自动执行 |
| 6 | 继续蒸馏下一课 | 我，用 dispatch.py |

---

## 相关

- 薅羊毛完整站表：`技术蒸馏课程\99_工具与模板\薅羊毛指南_20261111.md`
- 换站不丢对话的完整原理：`D:\RectSSL_AIRD_Quality_20261027_v4\agentrouter_switch_20261109\手动切换操作手册.md` 第 16 节
- 站点总管理手册：`C:\Users\18798\Documents\中转站与插件管理总手册_20261110.md`
- 27 篇手把手：`C:\Users\18798\Documents\手把手文档集_v2_20261004\`
