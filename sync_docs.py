r"""sync_docs.py - 同步课程内容到站点 docs/ 目录。

为什么需要它
------------
mkdocs 1.6 **明确禁止**两种布局：
  - `docs_dir` 是配置文件所在目录的父目录
  - `site_dir` 在 `docs_dir` 里面
所以站点源必须是配置文件的**子目录**。而我们的课程内容散在
`01_..` `99_..` 等多个目录里，于是用一个同步脚本来产出 `docs/`。

两种做法：
  A. 把内容**搬进** docs/  → 没有副本，但会打断所有
     `技术蒸馏课程\99_工具与模板\...` 这类路径引用
  B. 同步一份到 docs/     → 源目录原样不动，代价是有副本

选了 B：脚本会打印**每一项收录/排除的理由**，副本只有几十 KB 纯文本。

CI 侧（GitHub Actions）只负责 `mkdocs build`（构建已提交的 docs/），
不负责同步 —— 同步是本地提交前的动作。

用法：
    python sync_docs.py            # 同步并打印收录/排除清单
    python sync_docs.py --check    # 只检查 docs/ 是否已是最新（CI 用）
    python sync_docs.py --nav      # 顺便重新生成 mkdocs.yml 的 nav 段
"""
from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / 'docs'

# ---- 源目录 → docs/ 下的目标位置 ----------------------------------------
#   键是源目录名，值是 docs/ 下的子目录名
SECTIONS = {
    '01_C语言核心': '01_C语言核心',
    '02_嵌入式基础': '02_嵌入式基础',
    '03_驱动与硬件': '03_驱动与硬件',
    '04_实时系统': '04_实时系统',
    '05_综合项目': '05_综合项目',
    '99_工具与模板': '99_工具与模板',
}

# ---- 排除规则：谁不进网站，为什么 ---------------------------------------
EXCLUDE_DIR_NAMES = {
    '__pycache__': 'Python 缓存',
    'verification': '编译产物（.exe，4MB）',
    '学习周记': '个人周记（不发公开站）',
    '_site': '站点输出',
    '.git': 'git 内部',
    '.github': 'CI 配置',
}
EXCLUDE_FILE_NAMES = {
    # ⚠️ `verification_latest.json` **故意不排除**：
    #    90_验证记录.md 里链到它，而它是"这次验证过了没有"的权威指针
    #    （225 字节，只有 status / run_id / sha256，无凭据）。
    #    把链接改成纯文本会掩盖事实，所以让它进站。
    'mkdocs.yml': '站点配置',
    'sync_docs.py': '同步脚本',
    'make_site_nav.py': '导航生成脚本',
}
EXCLUDE_SUFFIXES = {'.exe', '.pyc', '.o', '.obj', '.log', '.db', '.sqlite3'}
# 源目录里其它要带上的文件类型：代码、示例
KEEP_SUFFIXES = {'.md', '.c', '.h', '.json', '.txt', '.py', '.ps1', '.cmd',
                 '.js', '.css', '.svg', '.png'}

# 根目录的静态资源目录 → docs/ 下的同名位置
# ⚠️ docs/ 会被 sync_docs.py 每次清空重建，所以**任何要发布的东西
#    必须住在源目录里**，直接往 docs/ 放会被无声删掉（这个坑踩过）。
ROOT_ASSET_DIRS = ['assets']


def classify(rel: Path) -> str | None:
    """Return a reason string if the path must be EXCLUDED, else None."""
    for part in rel.parts[:-1]:
        if part in EXCLUDE_DIR_NAMES:
            return EXCLUDE_DIR_NAMES[part]
    if rel.name in EXCLUDE_FILE_NAMES:
        return EXCLUDE_FILE_NAMES[rel.name]
    if rel.suffix in EXCLUDE_SUFFIXES:
        return f'后缀 {rel.suffix}'
    if rel.suffix not in KEEP_SUFFIXES:
        return f'后缀 {rel.suffix} 不在保留清单'
    return None


def collect() -> tuple[list[tuple[Path, str]], list[tuple[Path, str]]]:
    """Returns (kept, excluded) as (path_relative_to_ROOT, reason|dest)."""
    kept: list[tuple[Path, str]] = []
    excluded: list[tuple[Path, str]] = []

    # 根目录的单个 md（00_课程总纲.md）→ docs/index.md
    for p in sorted(ROOT.glob('*.md')):
        rel = p.relative_to(ROOT)
        reason = classify(rel)
        if reason:
            excluded.append((rel, reason))
        elif p.name == '00_课程总纲.md':
            kept.append((rel, 'index.md'))
        else:
            kept.append((rel, p.name))

    # 根目录的静态资源目录（assets/ 等）→ docs/ 下**同名**位置
    # ⚠️ 必须保留 asset_dir 这一层前缀：mkdocs 的 extra_javascript
    #    是相对 docs_dir 解析的，页面里引用的路径要和文件位置对得上。
    #    （漏掉前缀 ⇒ 21 条断链，这个坑踩过。）
    for asset_dir in ROOT_ASSET_DIRS:
        base = ROOT / asset_dir
        if not base.is_dir():
            continue
        for p in sorted(base.rglob('*')):
            if p.is_dir():
                continue
            rel = p.relative_to(ROOT)
            reason = classify(rel)
            if reason:
                excluded.append((rel, reason))
                continue
            dest = Path(asset_dir) / p.relative_to(base)
            kept.append((rel, dest.as_posix()))

    for src_dir, dst_dir in SECTIONS.items():
        base = ROOT / src_dir
        if not base.is_dir():
            excluded.append((Path(src_dir), '目录还不存在'))
            continue
        for p in sorted(base.rglob('*')):
            if p.is_dir():
                continue
            rel = p.relative_to(ROOT)
            reason = classify(rel)
            if reason:
                excluded.append((rel, reason))
                continue
            dest = Path(dst_dir) / p.relative_to(base)
            kept.append((rel, dest.as_posix()))
    return kept, excluded


def do_sync(kept, excluded, check_only: bool) -> int:
    if DOCS.exists() and not check_only:
        shutil.rmtree(DOCS)
    DOCS.mkdir(parents=True, exist_ok=True)

    changed, same = 0, 0
    for src_rel, dest in kept:
        src = ROOT / src_rel
        dst = DOCS / dest
        dst.parent.mkdir(parents=True, exist_ok=True)
        if check_only:
            if dst.exists() and filecmp.cmp(src, dst, shallow=False):
                same += 1
            else:
                changed += 1
                print(f'  ✗ 不同步: {dest}')
            continue
        shutil.copy2(src, dst)
        changed += 1

    if check_only:
        print(f'\ndocs/ 检查：{same} 个一致, {changed} 个需要重新同步')
        return 0 if changed == 0 else 1

    print(f'同步完成：{changed} 个文件 → docs/')
    print(f'排除 {len(excluded)} 项：')
    for rel, reason in excluded:
        print(f'      {rel.as_posix()}  ← {reason}')
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true',
                    help='只检查 docs/ 是否已是最新（CI 用），不同步')
    ap.add_argument('--nav', action='store_true',
                    help='同步后顺便重新生成 mkdocs.yml 的 nav 段')
    args = ap.parse_args()

    kept, excluded = collect()
    print(f'源：{ROOT}')
    print(f'目标：{DOCS}')
    print(f'将收录 {len(kept)} 个文件\n')

    rc = do_sync(kept, excluded, args.check)

    if args.nav and not args.check:
        import subprocess
        r = subprocess.run([sys.executable, str(ROOT / '99_工具与模板' / 'make_site_nav.py'),
                            '--write'], capture_output=True, text=True,
                           encoding='utf-8', errors='replace')
        print(r.stdout[-400:] if r.stdout else r.stderr[-400:])
    return rc


if __name__ == '__main__':
    sys.exit(main())
