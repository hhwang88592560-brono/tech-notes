r"""make_site_nav.py - generate the mkdocs nav for the course workspace.

WHY A SCRIPT
------------
Hand-writing the nav for a 20-page tree is error-prone, and the tree grows
every week. This regenerates `mkdocs.yml`'s `nav:` block from what is
actually in `docs/`, so a missing page shows up as a build error (with
`--strict`) instead of a silently missing page in the sidebar.

★ It scans `docs/`, NOT the source tree — because `docs/` is what mkdocs
actually publishes. If the two ever diverge, the nav follows the site
(which is the one that matters), and `sync_docs.py --check` is what
catches the divergence.

USAGE
-----
    python make_site_nav.py            # print the nav YAML
    python make_site_nav.py --write    # write it into mkdocs.yml
    python make_site_nav.py --plan     # just show what is in docs/
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

ROOT = Path(r'C:\Users\18798\Documents\技术蒸馏课程')
DOCS = ROOT / 'docs'

# 章节顺序（空章节不写进 nav —— mkdocs 拒绝 `- "x":` 这种空值）
SECTION_ORDER = [
    '01_C语言核心',
    '02_嵌入式基础',
    '03_驱动与硬件',
    '04_实时系统',
    '05_综合项目',
    '99_工具与模板',
]


def first_h1(path: Path) -> str | None:
    try:
        for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
            if line.startswith('# '):
                return line[2:].strip()
    except Exception:
        pass
    return None


def collect() -> list[tuple[str, list[tuple[str, str]]]]:
    """[(section, [(title, path_relative_to_docs)])]"""
    tree: list[tuple[str, list[tuple[str, str]]]] = []

    index = DOCS / 'index.md'
    if index.is_file():
        tree.append(('总纲', [(first_h1(index) or '总纲', 'index.md')]))

    for section in SECTION_ORDER:
        base = DOCS / section
        if not base.is_dir():
            continue
        pages: list[tuple[str, str]] = []
        for p in sorted(base.rglob('*.md'), key=lambda x: x.as_posix()):
            rel = p.relative_to(DOCS).as_posix()
            pages.append((first_h1(p) or p.stem, rel))
        if pages:
            tree.append((section, pages))
    return tree


def nav_yaml(tree) -> str:
    lines = ['nav:']
    for section, pages in tree:
        lines.append(f'  - "{section}":')
        for title, rel in pages:
            lines.append(f'      - "{title}": "{rel}"')
    return '\n'.join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--write', action='store_true', help='写入 mkdocs.yml 的 nav 段')
    ap.add_argument('--plan', action='store_true', help='只看 docs/ 里有什么')
    args = ap.parse_args()

    if not DOCS.is_dir():
        print(f'docs/ 不存在：{DOCS}')
        print('先跑：python sync_docs.py')
        return 1

    tree = collect()
    total = sum(len(p) for _, p in tree)
    print(f'docs/ 共 {total} 页\n')
    for section, pages in tree:
        print(f'  {section}  ({len(pages)} 页)')
        for title, rel in pages:
            print(f'      {title}   ← {rel}')

    if args.plan:
        return 0

    y = nav_yaml(tree)
    if args.write:
        cfg = ROOT / 'mkdocs.yml'
        text = cfg.read_text(encoding='utf-8') if cfg.exists() else ''
        head = text.split('\nnav:\n')[0] if '\nnav:\n' in text else text.rstrip() + '\n'
        cfg.write_text(head + '\n' + y + '\n', encoding='utf-8', newline='\n')
        print(f'\n已写入 {cfg}')
    else:
        print('\n--- nav YAML ---')
        print(y)
    return 0


if __name__ == '__main__':
    sys.exit(main())
