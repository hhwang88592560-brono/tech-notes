r"""check_site.py - 站点质量闸：构建产物自检。

WHY THIS EXISTS
---------------
`mkdocs build --strict` 只管 markdown 本身（断链的 markdown 链接、
nav 指向不存在的文件、警告）。它**不管**这些：
  - 页面引用的 .js/.css 在产物里到底有没有（extra_javascript 的路径
    解析规则和直觉不一样，踩过：文件在 docs/javascripts/，
    页面引用 assets/javascripts/xxx.js ⇒ 21 条断链，--strict 一声不响）
  - 编译产物（.exe）有没有混进产物
  - 代码块有没有被高亮

所以构建完再跑这个。它是"能编译通过"那条纪律在文档上的对应物。

用法：
    python check_site.py            # 检查 _site/
    python check_site.py --site X   # 检查别的目录
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys
import urllib.parse

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

ROOT = pathlib.Path(__file__).resolve().parent
BANNED_SUFFIX = {'.exe', '.o', '.obj', '.pyc', '.sqlite3', '.db'}
BANNED_NAMES = {'credentials.json', '.env'}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--site', default=str(ROOT / '_site'))
    args = ap.parse_args()
    site = pathlib.Path(args.site)

    if not site.is_dir():
        print(f'产物目录不存在：{site}\n先跑：python -m mkdocs build --strict')
        return 2

    problems: list[str] = []
    pages = sorted(site.rglob('*.html'))
    if not pages:
        print('产物里没有 HTML 页面')
        return 2

    # ---- 1. 内部链接（含 src）必须都指向真实文件 ----------------------
    checked = 0
    for p in pages:
        html = p.read_text(encoding='utf-8', errors='replace')
        for href in re.findall(r'(?:href|src)="([^"#?]+)(?:#[^"]*)?"', html):
            if href.startswith(('http://', 'https://', 'mailto:', 'data:')):
                continue
            t = urllib.parse.unquote(href)
            cand = (site / t.lstrip('/')) if t.startswith('/') else (p.parent / t)
            if cand.is_dir():
                cand = cand / 'index.html'
            checked += 1
            if not cand.exists():
                problems.append(f'断链: {p.relative_to(site).as_posix()} → {href}')

    # ---- 2. 不该出现在产物里的东西 -------------------------------------
    for p in site.rglob('*'):
        if not p.is_file():
            continue
        if p.suffix.lower() in BANNED_SUFFIX:
            problems.append(f'产物里有编译产物: {p.relative_to(site).as_posix()}')
        if p.name in BANNED_NAMES:
            problems.append(f'产物里有敏感文件: {p.relative_to(site).as_posix()}')

    # ---- 3. 首页三件套在不在 ------------------------------------------
    idx = (site / 'index.html')
    if idx.exists():
        h = idx.read_text(encoding='utf-8', errors='replace')
        for probe, label in [('md-nav__list', '左侧导航'),
                             ('md-search', '搜索框'),
                             ('md-content', '正文区')]:
            if probe not in h:
                problems.append(f'首页缺少{label} ({probe})')

    # ---- 4. 代码块高亮 -------------------------------------------------
    total_hl = 0
    for p in pages:
        h = p.read_text(encoding='utf-8', errors='replace')
        total_hl += len(re.findall(r'<div class="language-[a-z0-9+#]+[^"]*highlight"', h))
    if total_hl == 0:
        problems.append('全站 0 个高亮代码块 —— markdown 扩展可能没生效')

    # ---- 5. sitemap ----------------------------------------------------
    if not (site / 'sitemap.xml').exists():
        problems.append('缺 sitemap.xml')

    # ---- 报告 ----------------------------------------------------------
    print(f'产物：{site}')
    print(f'  HTML 页面 {len(pages)} 个，检查内部链接 {checked} 条')
    print(f'  高亮代码块 {total_hl} 个')
    print(f'  产物大小 {sum(f.stat().st_size for f in site.rglob("*") if f.is_file()) / 1024:.0f} KB')

    if problems:
        print(f'\n✗ {len(problems)} 个问题：')
        for x in problems[:25]:
            print(f'    {x}')
        if len(problems) > 25:
            print(f'    ... 还有 {len(problems) - 25} 个')
        return 1
    print('\n✓ 站点自检全部通过')
    return 0


if __name__ == '__main__':
    sys.exit(main())
