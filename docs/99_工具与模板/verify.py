"""verify.py - the course quality gate: do the code blocks actually compile?

WHY THIS EXISTS
---------------
The hardest failure in LLM-distilled embedded material is code that LOOKS
right and is wrong. Old tutorials, `printf` retargeting mistakes, missing
`volatile`, functions declared without `void`. A wall of text that reads
perfectly can still hand you code that will not build.

So the course gate is: extract every C code block from the lesson and
COMPILE it. Code that does not compile is not in the course.

Also checks the things a compiler cannot:
  * `volatile` present where a register is polled
  * obvious placeholder leftovers ("...", "TODO", "your code here")
  * the presence of the five required lesson sections

USAGE
-----
    python verify.py <lesson.md> [...]
    python verify.py --lesson-dir 01_C语言核心
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REQUIRED_SECTIONS = ['00_导读', '10_要点', '20_动手', '30_自测', '99_复盘']

# Code fences we can actually try to build.
C_LANGS = {'c', 'cpp', 'h'}

BLOCK_RE = re.compile(r'```([A-Za-z0-9_+#]*)\n(.*?)```', re.DOTALL)

PLACEHOLDER_RE = re.compile(
    r'(TODO|FIXME|your\s+code\s+here|fill\s+in|省略|其余代码不变|\.\.\.\s*$)',
    re.IGNORECASE | re.MULTILINE)


def find_compiler() -> str | None:
    for name in ('gcc', 'cc', 'clang', 'x86_64-w64-mingw32-gcc'):
        p = shutil.which(name)
        if p:
            return p
    return None


def extract_blocks(text: str) -> list[tuple[str, str, int]]:
    """Return [(lang, code, line_no)] for every fenced block."""
    out = []
    for m in BLOCK_RE.finditer(text):
        lang = (m.group(1) or '').strip().lower()
        code = m.group(2)
        line = text[:m.start()].count('\n') + 1
        out.append((lang, code, line))
    return out


def is_compilable_c(lang: str, code: str) -> bool:
    """Heuristic: does this look like a self-contained C program?

    We only compile blocks that look like complete programs (have main and
    a standard include). Fragments are reported as 'skipped' rather than
    failed, because a fragment is legitimate in a lesson.
    """
    if 'main' not in code:
        return False
    if not re.search(r'#include\s*<', code):
        return False
    return True


def compile_block(cc: str, code: str, tmp: Path, idx: int) -> tuple[str, str]:
    src = tmp / f'blk{idx}.c'
    src.write_text(code, encoding='utf-8')
    exe = tmp / f'blk{idx}.exe'
    cmd = [cc, '-std=c11', '-Wall', '-Wextra', '-o', str(exe), str(src)]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=120)
    if r.returncode == 0:
        return 'ok', ''
    return 'fail', (r.stderr or r.stdout)[:1200]


def check_volatile(text: str) -> list[str]:
    """Flag register-polling loops whose register is not declared volatile.

    A polling loop like `while (!(UART_STATUS & 1)) ;` is broken when the
    register macro is not volatile: the compiler is free to hoist the read
    out of the loop and the program hangs. So the check is: does the loop's
    operand name appear in a `volatile` declaration anywhere in the file?
    """
    problems = []
    # every identifier declared volatile in this file
    volatile_ids = set(re.findall(
        r'volatile\s+(?:const\s+)?(?:unsigned\s+|signed\s+)?'
        r'(?:char|short|int|long|uint\d+_t|int\d+_t|size_t|bool)\s*\*?\s*'
        r'([A-Za-z_]\w*)', text))
    # macros that alias a volatile pointer, e.g.
    #   #define UART_STATUS (*(volatile uint32_t *)0x40011000)
    for line in text.splitlines():
        m = re.match(r'\s*#\s*define\s+([A-Za-z_]\w*)\s*\(', line)
        if m and 'volatile' in line:
            volatile_ids.add(m.group(1))
    # also any all-caps macro whose own definition mentions volatile
    for m in re.finditer(r'#\s*define\s+([A-Z][A-Z0-9_]*)\b[^\n]*volatile', text):
        volatile_ids.add(m.group(1))

    # polling loops: while ( ... ) ;  — match the whole condition, then take
    # the first identifier inside it.
    for m in re.finditer(r'while\s*\(([^;{}]*)\)\s*;', text):
        cond = m.group(1)
        ident = re.search(r'([A-Za-z_]\w*)', cond)
        if not ident:
            continue
        ident = ident.group(1)
        if ident in volatile_ids:
            continue
        # only complain if it looks like a register (all-caps macro-ish)
        if not re.fullmatch(r'[A-Z][A-Z0-9_]*', ident):
            continue
        line = text[:m.start()].count('\n') + 1
        problems.append(
            f'line ~{line}: polling loop on {ident} but {ident} is not declared volatile')
    return problems


def check_sections(text: str) -> list[str]:
    return [s for s in REQUIRED_SECTIONS if s not in text]


def verify_file(path: Path, cc: str | None) -> dict:
    text = path.read_text(encoding='utf-8')
    result = {'file': str(path), 'sections_missing': check_sections(text),
              'placeholders': [], 'volatile': check_volatile(text),
              'blocks': [], 'compiled': 0, 'failed': 0, 'skipped': 0}

    for i, ln in enumerate(text.split('\n'), 1):
        if PLACEHOLDER_RE.search(ln):
            result['placeholders'].append(f'line {i}: {ln.strip()[:90]}')

    tmp = Path(tempfile.mkdtemp(prefix='verify_'))
    try:
        idx = 0
        for lang, code, line in extract_blocks(text):
            if lang not in C_LANGS:
                continue
            if not is_compilable_c(lang, code):
                result['blocks'].append({'line': line, 'lang': lang,
                                         'status': 'skipped (fragment)'})
                result['skipped'] += 1
                continue
            if cc is None:
                result['blocks'].append({'line': line, 'lang': lang,
                                         'status': 'skipped (no compiler)'})
                result['skipped'] += 1
                continue
            idx += 1
            status, err = compile_block(cc, code, tmp, idx)
            result['blocks'].append({'line': line, 'lang': lang,
                                     'status': status,
                                     'error': err if err else None})
            if status == 'ok':
                result['compiled'] += 1
            else:
                result['failed'] += 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    result['passed'] = (not result['sections_missing'] and not result['placeholders']
                        and not result['volatile'] and result['failed'] == 0)
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description='Verify a distilled lesson.')
    ap.add_argument('files', nargs='*', help='lesson .md files')
    ap.add_argument('--lesson-dir', help='verify every .out.md in this dir')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()

    cc = find_compiler()
    targets: list[Path] = [Path(f) for f in args.files]
    if args.lesson_dir:
        d = Path(args.lesson_dir)
        targets += sorted(d.glob('*.out.md'))
    if not targets:
        print('nothing to verify (pass lesson .md files or --lesson-dir)')
        return 1

    print(f'compiler: {cc or "NOT FOUND - compile checks skipped"}')
    all_res = []
    for t in targets:
        if not t.exists():
            print(f'\n!! missing: {t}')
            continue
        r = verify_file(t, cc)
        all_res.append(r)
        if args.json:
            continue
        print('\n' + '=' * 74)
        print(t.name)
        print('=' * 74)
        if r['sections_missing']:
            print('  MISSING SECTIONS :', ', '.join(r['sections_missing']))
        if r['placeholders']:
            print('  PLACEHOLDERS     :')
            for p in r['placeholders']:
                print('     -', p)
        if r['volatile']:
            print('  VOLATILE ISSUES  :')
            for v in r['volatile']:
                print('     -', v)
        print(f'  code blocks      : {r["compiled"]} compiled ok, '
              f'{r["failed"]} FAILED, {r["skipped"]} skipped')
        for b in r['blocks']:
            mark = {'ok': 'PASS', 'fail': 'FAIL'}.get(b['status'], 'skip')
            print(f'     [{mark}] line {b["line"]:>4}  {b["status"]}')
            if b.get('error'):
                for el in str(b['error']).splitlines()[:8]:
                    print('            ' + el)
        print(f'  RESULT           : {"PASS" if r["passed"] else "FAIL"}')

    if args.json:
        print(json.dumps(all_res, ensure_ascii=False, indent=2))
    failed = [r for r in all_res if not r['passed']]
    if not args.json:
        print('\n' + '=' * 74)
        print(f'{len(all_res) - len(failed)}/{len(all_res)} lessons passed the gate')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
