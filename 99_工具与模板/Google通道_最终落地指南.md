# Google 通道 · 最终落地指南

> **这份是"照着做"的版本。** 为什么这么做（配额表、协议断点、土区政策、2026-06-18 关闭事件）
> 在 [谷歌渠道调研与使用指南.md](谷歌渠道调研与使用指南.md) —— 那是"为什么"，这份是"怎么做"。
>
> 状态日期：**2026-11-12**。所有结论都是本机实测的（查 Clash 路由日志、跑验证脚本、看 CLI 源码），
> 不是抄文档。

---

## 0. 一页速览

| 问题 | 答案 |
|---|---|
| Google 能不能当主力 AGENT？ | **不能当 Codex 的主力**（协议不兼容，硬断点）；**能当批量蒸馏的后端**，且**不占 Codex 配额** |
| 接在哪一层？ | **网关/批量那一腿**（`dispatch.py` 的 `transport: http`），不是 Codex 那一腿 |
| 地区会不会被卡？ | **不会** —— 本机 Google 域名走 Clash 的日本出口，日本在支持列表里 |
| 要不要换 Clash 节点？ | **不要**（已经就在日本；万一该节点挂了才去 GUI 换） |
| 要不要设 `HTTPS_PROXY`？ | **不要**（TUN 模式开着，命令行自动被 Clash 接管并按同一套规则分流） |
| 现在卡在哪？ | **只差你按一次回车 + 在浏览器登录一次 Google 账号** |

### 现在这台机器的真实状态

| 组件 | 状态 |
|---|---|
| **AI Studio API key** | ❌ 没有（`GEMINI_API_KEY` 未设）—— **要你去建** |
| **Antigravity IDE** | ✅ **早就装好了**，2026-10 完成引导（`post_onboarding` 四步全过） |
| **Gemini CLI** | ✅ **早就装好了**，已自动升级到 **0.68.0** |
| **Google OAuth 凭据** | ❌ 没有（`~/.gemini/oauth_creds.json` 不存在）—— **要你去登录** |
| **Clash 的 Google 分流** | ✅ `RuleSet(gemini)` + `DomainSuffix(googleapis.com)` → 日本节点，**不用动** |
| **`dispatch.py` 的 google 腿** | ✅ 代码就绪（`transport: http` + `site_ready()` 自动跳过无 key 的站） |
| **统一换站器 `relay`** | ✅ `google` 已登记（带完整"为什么不能直连"） |
| **`openai` 包** | ✅ 已装进 Python312（3.49.0） |
| **Gemini CLI 的信任目录** | ✅ 已配（`~/.gemini/trustedFolders.json`） |

---

## 1. 你要做的事（两条路，**互不依赖**）

### 路 A —— 给 `dispatch.py` 用（要一个 API key）

1. 浏览器打开 **<https://aistudio.google.com/apikey>**（已经给你打开了）
2. 建一个**专门的项目**（额度按项目算，不是按 key 算 —— 加 key 不涨额度）
3. Create API key → 复制
4. 在终端跑：

```bash
cd "C:\Users\18798\Documents\技术蒸馏课程\99_工具与模板"
python setup_google_key.py --key <你的KEY>
```

这一条命令会：写用户级环境变量 `GEMINI_API_KEY` → **立刻**跑完整验证（4 项）→ 打印结论。

> ⚠️ **新开一个终端**再跑 `dispatch.py`（环境变量要新进程才继承）。
> ⚠️ `setup_google_key.py` 用 `reg add` 写注册表，**不用 `setx`**（`setx` 有 1024 字符上限，会静默截断 PATH —— 本机出过事故）。

### 路 B —— 给 Gemini CLI / Antigravity 用（不要 key，但要登录）

**这是最省事的一条**，因为 Google 自己的 CLI 已经在你机器上了。

1. 打开终端面板里那个 **`Gemini 登录`** 标签页（停在 `Sign in with Google`，选项 1 已选中）
2. **按回车** → 浏览器弹出登录页 → 登录你的 Google 账号 → 授权
3. **必须在 5 分钟内完成** —— OAuth 超时是**硬编码**的 5 分钟（`authTimeout = 5*60*1e3`），不可配

> ⚠️ **这一步只能在交互终端里做。**
> `NO_BROWSER=true` 在非交互下会被直接拒绝：
> `Manual authorization is required but the current session is non-interactive`。
> 登录成功后 `~/.gemini/oauth_creds.json` 落盘，**之后无头/批处理都能用了**。

### 两条路各自解决什么

| | 路 A（API key） | 路 B（OAuth 登录） |
|---|---|---|
| 打通谁 | `dispatch.py` 的第三条腿（批量蒸馏） | Gemini CLI / Antigravity（交互式 agent） |
| 额度来源 | AI Studio 免费层（Flash 系列） | Code Assist 额度（视账号而定） |
| 要钱吗 | 不要 | 不要 |
| 占 Codex 配额吗 | **不占** | **不占** |

---

## 2. 验证

### 路 A 验证（`setup_google_key.py` 会自动跑）

```bash
python "C:\Users\18798\Documents\技术蒸馏课程\99_工具与模板\verify_google_key.py"
```

4 项独立判据：

| # | 查什么 | 通过标志 |
|---|---|---|
| 1 | 通用出口（**仅参考**） | 不是地区判据，见 §4 |
| 2 | key 有效性 + 模型列表 | `✓ key 有效，可见 N 个模型` |
| 3 | OpenAI 兼容层 `/chat/completions` 能出活 | `✓ HTTP 200 模型=…` ← **dispatch.py 走的就是这条** |
| 4 | 原生 `generateContent`（对照） | `HTTP 200` |

然后确认调度器认到它：

```bash
cd "C:\Users\18798\Documents\技术蒸馏课程\99_工具与模板"
python dispatch.py --list     # google 那行应该不再是「不可用: GEMINI_API_KEY 没设」
python dispatch.py --probe    # 实测两个 gemini 模型
```

### 路 B 验证（登录完之后）

```bash
gemini -p "Reply with exactly: GOOGLE_AGENT_OK" --approval-mode plan
```

看到 `GOOGLE_AGENT_OK` 就通了。**无头跑之前先确认工作目录受信任**
（课程目录已经加进 `~/.gemini/trustedFolders.json`；其它目录要么加进去，
要么设 `GEMINI_CLI_TRUST_WORKSPACE=true`）。

---

## 3. 三条腿的关系（别搞混）

```
Codex        ──→ Codex 原生（Responses API） ──→ agentrouter / pincar
Claude Code  ──→ 你的网关适配器 (18146)      ──→ agentrouter / pincar
dispatch.py  ──→ transport: codex | http      ──→ 各站的 (站 × 模型) 池
                                              └─→ google  ← transport: http
```

**为什么中转站必须用真 Codex 客户端**：它们校验客户端指纹
（pincar 对普通 HTTP 客户端返 403 `This account only allows Codex official clients`）。
**Google 不校验**，而且提供 OpenAI 兼容的 `/chat/completions`（只是**没有** `/responses`）⇒ 给
`dispatch.py` 加 `transport: 'http'` 就能接。

**所以 Google 是"网关/批量"那一腿，不是"Codex"那一腿。**
这也是为什么 `relay sites` 里 `google` 的 Codex / Claude Code 两列都是 ✘ —— 不是没配好，是协议层就不通。

### 统一换站器（跟 Google 无关但同属这套体系）

```bash
relay status          # 所有 app 现在在哪
relay sites           # 有哪些站、各自支持哪些 app、为什么
relay use <site>      # 切换所有支持的 app
relay doctor          # 自检
```

---

## 4. ⚠️ 三个容易判错的地方（我自己都踩过）

### ① **通用出口 IP ≠ Google 的实际出口**

用 `ifconfig.co` 之类的回显站查到的是 **HKT 香港**（通用分流），
但 Google 域名走**专用分流**，实际出口是**日本**。

**拿通用出口去判 Gemini 的地区可行性，会得出错误结论。**

要判某个域名的真实出口，看 Clash 的路由日志：

```
%APPDATA%\io.github.clash-verge-rev.clash-verge-rev\logs\service\service_latest.log
```

找 `generativelanguage.googleapis.com` 那一行，`using` 后面那个就是真实出口节点。

### ② **"能到达" ≠ "能用"，但"地区报错"才是判据**

Google 的 API 会先验 key 再验地区。所以：

| 响应 | 含义 |
|---|---|
| `INVALID_ARGUMENT / API key not valid` | **key 的问题**（地区还没轮到判） |
| `FAILED_PRECONDITION / User location is not supported` | **这才是地区问题** |

`verify_google_key.py` 的第 1 步已降级为"仅参考"，判据只看上面这两条。

### ③ **`.cmd` 文件里不能有中文**

cmd.exe 按 ANSI 代码页（本机 GBK）读 `.cmd`，UTF-8 的中文注释会被当命令执行
（`'…' 不是内部或外部命令`）。**用 Write 工具生成的 `.cmd` 必须整份纯 ASCII。**

---

## 5. 故障对照表

| 现象 | 原因 | 处理 |
|---|---|---|
| `User location is not supported for the API use` | 出口地区不在支持列表 | 查 Clash 日志看真实出口；把 `📢 谷歌服务` 切到日本/美国 |
| `INVALID_ARGUMENT: API key not valid` | key 无效/不是 auth key | 重建（2026-05-28 后建的是 auth key） |
| `Authentication timed out after 5 minutes` | 浏览器没在 5 分钟内完成登录 | 重跑，**这次人在机器前**；交互终端里跑 |
| `Manual authorization is required but the current session is non-interactive` | 非交互下用了 `NO_BROWSER=true` | 换交互终端登录一次，之后凭据落盘就能无头用 |
| `Gemini CLI is not running in a trusted directory`（退出码 55） | 工作目录不受信任 | 加进 `~/.gemini/trustedFolders.json`，或设 `GEMINI_CLI_TRUST_WORKSPACE=true` |
| `dial 📢 谷歌服务 ... error: <host>:443 connect e...`（Clash 日志） | 那个节点挂了 | GUI 里把 `📢 谷歌服务` 换成别的日本/美国节点 |
| `This client is not supported for Gemini Code Assist for individuals` | 个人免费通道已于 2026-06-18 关闭 | 走 AI Studio key（路 A）或 Antigravity |
| `Your current account is not eligible for Antigravity...` | 账号地区与支持地区不匹配 | 换账号，或用路 A |
| `dispatch.py --list` 显示 google「不可用」 | `GEMINI_API_KEY` 没设 | 跑 `setup_google_key.py`，并**新开终端** |

---

## 6. 已确认的本机事实（省得你重查）

| 项 | 值 |
|---|---|
| Clash Verge | verge-mihomo，系统代理 `127.0.0.1:7897`，mixed 7897 / socks 7898 / http 7899 |
| TUN 模式 | **开着** ⇒ 命令行自动被接管分流 |
| 外部控制器 | **关着**（`enable_external_controller: false`）⇒ **换节点只能你在 GUI 点** |
| 激活订阅 | `RcqySQpe7uyY`（146 节点）；另一份 `Rd1KalmmTmnK.yaml` 里有 `土耳其TR-A` |
| Google 出口节点 | `📢 谷歌服务[【3x】中转|日本樱花🇯🇵]` |
| 生效的 Google 分流 | `RuleSet(gemini)`（blackmatrix7）+ `DomainSuffix(googleapis.com)` |
| Gemini CLI | 0.68.0，npm 全局；`--skip-trust` / `GEMINI_CLI_TRUST_WORKSPACE` 两种解法都实测过 |
| Antigravity | `AppData\Local\Programs\antigravity\Antigravity.exe`；agent 后端 `resources\bin\language_server.exe` |

---

## 7. 相关文件

| 文件 | 作用 |
|---|---|
| `99_工具与模板\谷歌渠道调研与使用指南.md` | **为什么** —— 配额表、协议断点、土区政策、关闭时间线 |
| `99_工具与模板\verify_google_key.py` | 4 项验证（地区参考 / key / 模型 / 能出活） |
| `99_工具与模板\setup_google_key.py` | 写环境变量 + 立刻验证 |
| `99_工具与模板\dispatch.py` | 多站调度（`transport: codex \| http`） |
| `99_工具与模板\中转管理与AI调度指南.md` | 统一换站器、站×app 矩阵、三条铁律 |
| `D:\...\agentrouter_switch_20261109\RELAY.md` | 换站器完整手册（**本地仓库，无远程**） |

---

## 8. 一句话

**Google 是这套体系里的第三条腿，专职批量蒸馏，不占 Codex 配额、不花钱、地区也不用管。**
现在只剩两下鼠标/回车：浏览器里建个 key（或登录一次 Gemini CLI），
剩下全是脚本已经跑通的事。
