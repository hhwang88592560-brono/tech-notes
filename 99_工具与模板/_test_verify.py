"""Prove the verifier catches real problems, not just passes everything."""
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import importlib.util

spec = importlib.util.spec_from_file_location('v', HERE / 'verify.py')
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)

FAIL = []


def check(label, cond, extra=''):
    print(('  PASS  ' if cond else '  FAIL  ') + label +
          (('  | ' + str(extra)) if extra and not cond else ''))
    if not cond:
        FAIL.append(label)


CC = v.find_compiler()
check('gcc found', CC is not None, CC)

GOOD = '''## 00_导读
x

## 10_要点
x

## 20_动手
```c
#include <stdio.h>
int main(void) {
    printf("ok\\n");
    return 0;
}
```

## 30_自测
x

## 99_复盘
x
'''

BAD_TYPE = GOOD.replace('printf("ok\\n");',
                         'int x = "not an int";\n    printf("%d\\n", x);')

BAD_SYNTAX = GOOD.replace('#include <stdio.h>\nint main(void) {',
                           '#include <stdio.h>\nint main(void) { this is not c')

HAS_TODO = GOOD.replace('## 30_自测', '```c\n// TODO: 补全你的代码\n```\n\n## 30_自测')

NO_SECTIONS = GOOD.replace('## 30_自测\nx\n', '')

VOLATILE = '''## 00_导读
```c
#include <stdint.h>
#define UART_STATUS (*(volatile uint32_t*)0x40011000)
int main(void) {
    while (!(UART_STATUS & 1)) ;
    return 0;
}
```
## 10_要点
## 20_动手
## 30_自测
## 99_复盘
'''

# The same loop, but the register is NOT volatile - this is the bug the
# check must catch (the compiler may hoist the read and the program hangs).
VOLATILE_BROKEN = VOLATILE.replace(
    '#define UART_STATUS (*(volatile uint32_t*)0x40011000)',
    '#define UART_STATUS (*(uint32_t*)0x40011000)')

tmp = pathlib.Path(r'C:\Users\18798\Documents\_vt')
tmp.mkdir(exist_ok=True)

print('\n--- a good lesson passes ---')
p = tmp / 'good.md'
p.write_text(GOOD, encoding='utf-8')
r = v.verify_file(p, CC)
check('good lesson passes', r['passed'], r)
check('good: 1 compiled', r['compiled'] == 1, r['compiled'])

print('\n--- a type error is caught ---')
p = tmp / 'badtype.md'
p.write_text(BAD_TYPE, encoding='utf-8')
r = v.verify_file(p, CC)
check('type error -> FAILED', r['failed'] >= 1, r['failed'])
check('type error -> lesson fails', not r['passed'])

print('\n--- a syntax error is caught ---')
p = tmp / 'badsyn.md'
p.write_text(BAD_SYNTAX, encoding='utf-8')
r = v.verify_file(p, CC)
check('syntax error -> FAILED', r['failed'] >= 1, r['failed'])

print('\n--- a TODO placeholder is caught ---')
p = tmp / 'todo.md'
p.write_text(HAS_TODO, encoding='utf-8')
r = v.verify_file(p, CC)
check('TODO flagged', len(r['placeholders']) >= 1, r['placeholders'])
check('TODO -> lesson fails', not r['passed'])

print('\n--- a missing section is caught ---')
p = tmp / 'nosec.md'
p.write_text(NO_SECTIONS, encoding='utf-8')
r = v.verify_file(p, CC)
check('missing section flagged', len(r['sections_missing']) >= 1, r['sections_missing'])
check('missing section -> lesson fails', not r['passed'])

print('\n--- a missing volatile is caught ---')
p = tmp / 'vol.md'
p.write_text(VOLATILE_BROKEN, encoding='utf-8')
r = v.verify_file(p, CC)
check('missing volatile flagged', len(r['volatile']) >= 1, r['volatile'])
check('missing volatile -> lesson fails', not r['passed'])

print('\n--- a correct volatile is NOT falsely flagged ---')
p = tmp / 'vol_ok.md'
p.write_text(VOLATILE, encoding='utf-8')
r = v.verify_file(p, CC)
check('correct volatile not flagged', len(r['volatile']) == 0, r['volatile'])

print('\n' + ('ALL ASSERTIONS PASSED' if not FAIL else f'{len(FAIL)} FAILURES: {FAIL}'))
sys.exit(1 if FAIL else 0)
