# tech-notes · 技术蒸馏课程

> **课程网站**：<https://hhwang88592560-brono.github.io/tech-notes/>
> 推 `main` 分支 → GitHub Actions 自动构建并发布（`--strict` + 站点自检，三道闸任一不过就不发）。

这个仓库是**课程工作区 + 站点源**：

```
技术蒸馏课程/
├── 01_C语言核心/ … 05_综合项目/    ← 课程正文（人写的地方）
├── 99_工具与模板/                  ← 工具脚本 + 指南
├── assets/                         ← 站点静态资源（mermaid.js 等）
├── docs/                           ← ★ 站点源，由 sync_docs.py 生成，**别手改**
├── mkdocs.yml                      ← 站点配置（nav 段由脚本生成，别手改）
├── sync_docs.py                    ← 源 → docs/ 的同步脚本
├── check_site.py                   ← 产物层面的质量闸
└── .github/workflows/pages.yml     ← 自动发布
```

## 两条不能破的纪律

**1. 改了源，要跑同步再提交**

```bash
python sync_docs.py                    # 源 → docs/
python 99_工具与模板/make_site_nav.py --write   # 重新生成 nav
python -m mkdocs build --strict        # 闸 1：markdown 层
python check_site.py                   # 闸 2：产物层
git add -A && git commit
```

忘了同步？CI 会直接失败并告诉你 —— 站点内容永远和源一致。

**2. `docs/` 里不要直接放东西**

`sync_docs.py` 每次会**清空 `docs/` 再重建**，直接放进去的文件会被无声删掉。
要发布的静态资源放 `assets/`。

## 质量闸

| 闸 | 查什么 | 为什么 mkdocs --strict 不够 |
|---|---|---|
| `mkdocs build --strict` | markdown 断链、nav 指向不存在、警告 | —— |
| `python check_site.py` | **628 条内部链接（含 .js/.css）**、产物里的编译产物、首页三件套、代码高亮、sitemap | `--strict` **不管** `extra_javascript` 的路径解析 —— 文件在 `docs/javascripts/`、页面引用 `assets/javascripts/x.js` 时，它一声不响，21 条断链照样发布 |
| CI 的同步闸 | `docs/` 与源是否一致 | 防止"忘了同步"把旧内容发出去 |

## 这个站点怎么来的

从**原始材料**（书/文档/博客/视频）经过一条流水线蒸馏成可执行的学习包：

```
原始材料 → 中转站调度（换站不中断）→ 五件套（00导读/10要点/20动手/30自测/99复盘）
                                                    ↓
                                          gcc 编译闸（不编译的代码不算代码）
                                                    ↓
                                          DeepTutor（本地 qwen3 出题 + 本机 Whisper 转写）
                                                    ↓
                                                  本站
```

相关文档在 `99_工具与模板/`，站点上有完整版。

## 许可

课程内容与脚本随仓库走。引用请注明出处。
